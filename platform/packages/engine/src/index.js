"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PlaywrightExecutionEngine = void 0;
const node_crypto_1 = require("node:crypto");
const playwright_1 = require("playwright");
const policy_1 = require("@agenttrust/policy");
function classifyFailure(error) {
    const message = String(error?.message || error || "").toLowerCase();
    if (message.includes("timeout"))
        return "TIMEOUT";
    if (message.includes("not found"))
        return "ELEMENT_NOT_FOUND";
    if (message.includes("interactable") || message.includes("visible"))
        return "NOT_INTERACTABLE";
    if (message.includes("navigation") || message.includes("net::"))
        return "NAVIGATION_ERROR";
    return "UNKNOWN";
}
function hashStep(previousHash, step) {
    return (0, node_crypto_1.createHash)("sha256")
        .update(JSON.stringify({ previousHash, step }))
        .digest("hex");
}
async function resolveLocator(page, target, correction) {
    const candidate = correction || target;
    if (candidate.role && candidate.name) {
        return page.getByRole(candidate.role, { name: candidate.name });
    }
    if (candidate.label) {
        return page.getByLabel(candidate.label);
    }
    if (candidate.text) {
        return page.getByText(candidate.text, { exact: false });
    }
    if (candidate.selector) {
        return page.locator(candidate.selector);
    }
    if (candidate.placeholder) {
        return page.getByPlaceholder(candidate.placeholder);
    }
    throw new Error("Element not found: selector descriptor is empty");
}
async function verifyStep(page, step) {
    if (!step.verification)
        return true;
    if (step.verification.urlIncludes && !page.url().includes(step.verification.urlIncludes)) {
        throw new Error(`Verification failed: URL does not include ${step.verification.urlIncludes}`);
    }
    if (step.verification.textVisible) {
        await page.getByText(step.verification.textVisible, { exact: false }).waitFor({ state: "visible" });
    }
    if (step.verification.selectorExists) {
        const locator = await resolveLocator(page, step.verification.selectorExists);
        await locator.waitFor({ state: "visible" });
    }
    return true;
}
async function captureReplay(page, sequence, hooks) {
    if (!hooks?.onReplayEvent)
        return;
    const html = await page.content();
    await hooks.onReplayEvent({
        sequence,
        eventType: "dom_snapshot",
        payload: { html, url: page.url() }
    });
}
async function runStep(page, task, step, sequence, hooks) {
    let retryCount = 0;
    const maxRetries = 4;
    const currentDomain = new URL(page.url() || step.url || "https://example.com").hostname;
    while (retryCount < maxRetries) {
        try {
            const policy = (0, policy_1.evaluatePolicy)({
                type: step.action,
                url: step.url || page.url(),
                domain: currentDomain,
                target: step.target,
                form: step.value ? { value: step.value } : undefined,
                allowedDomains: task.allowedDomains
            });
            if (policy.decision === "deny") {
                await hooks?.onStepUpdate?.({
                    step,
                    sequence,
                    status: "failed",
                    retryCount,
                    failureType: "POLICY_DENIED",
                    message: policy.reason,
                    policy
                });
                throw new Error(policy.reason);
            }
            if (policy.decision === "require_approval") {
                await hooks?.onStepUpdate?.({
                    step,
                    sequence,
                    status: "waiting_approval",
                    retryCount,
                    failureType: "NONE",
                    message: policy.reason,
                    policy
                });
                const decision = await hooks?.awaitApproval?.({
                    step,
                    sequence,
                    reason: policy.reason
                });
                if (decision !== "approved") {
                    throw new Error("Approval rejected");
                }
            }
            await hooks?.onStepStart?.(step, sequence);
            await page.waitForLoadState("domcontentloaded");
            if (step.action === "goto" && step.url) {
                await page.goto(step.url, { waitUntil: "domcontentloaded" });
            }
            else if (step.action === "click" && step.target) {
                const correction = await hooks?.lookupCorrection?.({ domain: currentDomain, actionType: step.action });
                const locator = await resolveLocator(page, step.target, correction || undefined);
                await locator.scrollIntoViewIfNeeded();
                await locator.click();
            }
            else if (step.action === "type" && step.target) {
                const correction = await hooks?.lookupCorrection?.({ domain: currentDomain, actionType: step.action });
                const locator = await resolveLocator(page, step.target, correction || undefined);
                await locator.scrollIntoViewIfNeeded();
                await locator.fill(step.value || "");
                if (step.submit) {
                    await locator.press("Enter");
                }
            }
            else if (step.action === "press" && step.value) {
                await page.keyboard.press(step.value);
            }
            else if (step.action === "extract" && step.target) {
                const locator = await resolveLocator(page, step.target);
                const text = await locator.textContent();
                await hooks?.onStepUpdate?.({
                    step,
                    sequence,
                    status: "succeeded",
                    retryCount,
                    failureType: "NONE",
                    message: text || ""
                });
            }
            else {
                throw new Error(`Unsupported action ${step.action}`);
            }
            await page.waitForLoadState("networkidle").catch(() => undefined);
            await verifyStep(page, step);
            await captureReplay(page, sequence, hooks);
            await hooks?.onStepUpdate?.({
                step,
                sequence,
                status: "succeeded",
                retryCount,
                failureType: "NONE",
                message: "Step completed"
            });
            return;
        }
        catch (error) {
            retryCount += 1;
            const failureType = classifyFailure(error);
            await hooks?.onStepUpdate?.({
                step,
                sequence,
                status: "failed",
                retryCount,
                failureType,
                message: String(error?.message || error)
            });
            if (retryCount >= maxRetries) {
                throw error;
            }
            await page.waitForLoadState("domcontentloaded").catch(() => undefined);
        }
    }
}
class PlaywrightExecutionEngine {
    browser;
    context;
    page;
    async run(task, hooks) {
        this.browser = await playwright_1.chromium.launch({ headless: true });
        this.context = await this.browser.newContext();
        this.page = await this.context.newPage();
        let previousHash = "0";
        for (const [sequence, step] of task.steps.entries()) {
            previousHash = hashStep(previousHash, step);
            await runStep(this.page, task, step, sequence, hooks);
        }
        const result = {
            success: true,
            currentUrl: this.page.url()
        };
        await this.dispose();
        return result;
    }
    async dispose() {
        await this.page?.close().catch(() => undefined);
        await this.context?.close().catch(() => undefined);
        await this.browser?.close().catch(() => undefined);
    }
}
exports.PlaywrightExecutionEngine = PlaywrightExecutionEngine;
