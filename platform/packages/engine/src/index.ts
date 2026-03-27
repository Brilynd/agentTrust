import { createHash } from "node:crypto";

import { chromium, type Browser, type BrowserContext, type Page } from "playwright";

import { evaluatePolicy, type PolicyEvaluation } from "@agenttrust/policy";
import type {
  AgentTaskInput,
  BrowserStep,
  FailureType,
  ReplayEventPayload,
  SelectorDescriptor
} from "@agenttrust/shared";

export interface EngineHooks {
  onStepStart?(step: BrowserStep, sequence: number): Promise<void> | void;
  onStepUpdate?(payload: {
    step: BrowserStep;
    sequence: number;
    status: "running" | "succeeded" | "failed" | "waiting_approval";
    retryCount: number;
    failureType: FailureType;
    message: string;
    policy?: PolicyEvaluation;
  }): Promise<void> | void;
  onReplayEvent?(event: ReplayEventPayload): Promise<void> | void;
  awaitApproval?(payload: { step: BrowserStep; sequence: number; reason: string }): Promise<"approved" | "rejected">;
  lookupCorrection?(payload: { domain: string; actionType: string }): Promise<SelectorDescriptor | null>;
  rememberCorrection?(payload: {
    step: BrowserStep;
    sequence: number;
    domain: string;
    actionType: string;
    failureType: FailureType;
    failedSelector?: SelectorDescriptor;
    correctedSelector: SelectorDescriptor;
    reason: string;
  }): Promise<void> | void;
}

export interface EngineRunResult {
  success: boolean;
  currentUrl: string;
  extractedText?: string;
}

function classifyFailure(error: unknown): FailureType {
  const message = String((error as Error)?.message || error || "").toLowerCase();
  if (message.includes("goal not achieved")) return "GOAL_NOT_ACHIEVED";
  if (message.includes("verification failed")) return "VERIFICATION_FAILED";
  if (message.includes("timeout")) return "TIMEOUT";
  if (message.includes("not found")) return "ELEMENT_NOT_FOUND";
  if (message.includes("interactable") || message.includes("visible")) return "NOT_INTERACTABLE";
  if (message.includes("navigation") || message.includes("net::")) return "NAVIGATION_ERROR";
  return "UNKNOWN";
}

function hashStep(previousHash: string, step: BrowserStep): string {
  return createHash("sha256")
    .update(JSON.stringify({ previousHash, step }))
    .digest("hex");
}

async function resolveLocator(page: Page, target: SelectorDescriptor, correction?: SelectorDescriptor) {
  const candidate = correction || target;
  if (candidate.role && candidate.name) {
    return page.getByRole(candidate.role as never, { name: candidate.name });
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

function serializeDescriptor(target?: SelectorDescriptor | null) {
  return JSON.stringify(target || {});
}

function describeSelector(target?: SelectorDescriptor) {
  return [
    target?.role ? `role=${target.role}` : "",
    target?.name ? `name=${target.name}` : "",
    target?.text ? `text=${target.text}` : "",
    target?.label ? `label=${target.label}` : "",
    target?.placeholder ? `placeholder=${target.placeholder}` : "",
    target?.selector ? `selector=${target.selector}` : ""
  ]
    .filter(Boolean)
    .join(", ");
}

function selectorLabels(target?: SelectorDescriptor) {
  return Array.from(
    new Set(
      [target?.name, target?.text, target?.label, target?.placeholder]
        .map((value) => String(value || "").trim())
        .filter(Boolean)
    )
  );
}

async function emitReplay(sequence: number, eventType: string, payload: Record<string, unknown>, hooks?: EngineHooks) {
  if (!hooks?.onReplayEvent) return;
  await hooks.onReplayEvent({ sequence, eventType, payload });
}

async function verifyStep(page: Page, step: BrowserStep) {
  if (!step.verification) return [];
  const warnings: string[] = [];

  if (step.verification.urlIncludes && !page.url().includes(step.verification.urlIncludes)) {
    warnings.push(`URL did not include ${step.verification.urlIncludes}`);
  }

  if (step.verification.textVisible) {
    const visible = await page
      .getByText(step.verification.textVisible, { exact: false })
      .first()
      .isVisible({ timeout: 2500 })
      .catch(() => false);
    if (!visible) {
      warnings.push(`Text "${step.verification.textVisible}" was not visible yet`);
    }
  }

  if (step.verification.selectorExists) {
    const locator = await resolveLocator(page, step.verification.selectorExists);
    const visible = await locator.first().isVisible({ timeout: 2500 }).catch(() => false);
    if (!visible) {
      warnings.push(`Selector goal was not visible yet (${describeSelector(step.verification.selectorExists)})`);
    }
  }

  if (warnings.length > 0 && step.verification.strict) {
    throw new Error(`Verification failed: ${warnings.join("; ")}`);
  }

  return warnings;
}

async function captureReplay(
  page: Page,
  sequence: number,
  hooks?: EngineHooks,
  eventType = "screenshot",
  extra: Record<string, unknown> = {}
) {
  if (!hooks?.onReplayEvent) return;
  const screenshot = await page.screenshot({
    type: "jpeg",
    quality: 55,
    fullPage: false,
    animations: "disabled",
    caret: "hide"
  });
  await hooks.onReplayEvent({
    sequence,
    eventType,
    payload: {
      screenshotBase64: screenshot.toString("base64"),
      screenshotMimeType: "image/jpeg",
      url: page.url(),
      ...extra
    }
  });
}

async function hasLocatorMatch(page: Page, target: SelectorDescriptor) {
  try {
    const locator = await resolveLocator(page, target);
    return (await locator.first().count()) > 0;
  } catch {
    return false;
  }
}

async function inferCorrection(page: Page, target?: SelectorDescriptor | null) {
  if (!target) return null;
  const labels = selectorLabels(target);
  const candidates: SelectorDescriptor[] = [];

  if (target.role && target.name) {
    candidates.push({ role: target.role, name: target.name });
  }
  if (target.selector) {
    candidates.push({ selector: target.selector });
  }
  if (target.label) {
    candidates.push({ label: target.label });
  }
  if (target.placeholder) {
    candidates.push({ placeholder: target.placeholder });
  }
  if (target.text) {
    candidates.push({ text: target.text });
  }

  for (const label of labels) {
    candidates.push({ text: label });
    candidates.push({ label });
    candidates.push({ placeholder: label });
    candidates.push({ role: "button", name: label });
    candidates.push({ role: "link", name: label });
    if (target.role) {
      candidates.push({ role: target.role, name: label });
    }
  }

  const seen = new Set<string>();
  for (const candidate of candidates) {
    const key = serializeDescriptor(candidate);
    if (seen.has(key)) continue;
    seen.add(key);
    if (await hasLocatorMatch(page, candidate)) {
      return candidate;
    }
  }

  return null;
}

async function extractObservation(page: Page, step: BrowserStep) {
  if (step.target) {
    try {
      const locator = await resolveLocator(page, step.target);
      const count = await locator.count().catch(() => 0);
      if (count > 0) {
        const text = await locator.first().textContent().catch(() => "");
        return {
          message: String(text || step.target.text || step.goal || "Observation captured").trim(),
          found: true
        };
      }
    } catch {
      // Soft-fail below and treat the step as an observation goal.
    }
  }

  const bodyText = (await page.locator("body").textContent().catch(() => "")) || "";
  const goalText = String(step.target?.text || step.goal || "").trim();
  if (goalText && bodyText.toLowerCase().includes(goalText.toLowerCase())) {
    return { message: goalText, found: true };
  }

  const snippet = bodyText.replace(/\s+/g, " ").trim().slice(0, 240);
  return {
    message: snippet || `${step.goal || step.name} remains a goal for the agent, not a hard blocker`,
    found: false
  };
}

async function recoverAfterFailure(
  page: Page,
  step: BrowserStep,
  sequence: number,
  retryCount: number,
  failureType: FailureType,
  hooks?: EngineHooks,
  currentCorrection?: SelectorDescriptor | null
) {
  let nextCorrection = currentCorrection || null;

  await emitReplay(
    sequence,
    "step.retrying",
    {
      retryCount,
      failureType,
      action: step.action,
      goal: step.goal || step.name,
      currentUrl: page.url()
    },
    hooks
  );

  await page.waitForLoadState("domcontentloaded").catch(() => undefined);
  await page.waitForLoadState("networkidle").catch(() => undefined);

  if (retryCount === 1) {
    await page.mouse.wheel(0, 700).catch(() => undefined);
  } else if (retryCount === 2) {
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.mouse.wheel(0, -700).catch(() => undefined);
  } else if (retryCount >= 3 && step.action !== "goto") {
    await page.reload({ waitUntil: "domcontentloaded" }).catch(() => undefined);
  }

  if (step.target) {
    const inferred = await inferCorrection(page, step.target);
    if (inferred && serializeDescriptor(inferred) !== serializeDescriptor(nextCorrection || step.target)) {
      nextCorrection = inferred;
      await emitReplay(
        sequence,
        "correction.discovered",
        {
          action: step.action,
          failureType,
          originalTarget: step.target,
          correctedTarget: inferred,
          retryCount
        },
        hooks
      );
    }
  }

  return nextCorrection;
}

async function runStep(
  page: Page,
  task: AgentTaskInput,
  step: BrowserStep,
  sequence: number,
  hooks?: EngineHooks
) {
  let retryCount = 0;
  const maxRetries = 4;
  let runtimeCorrection: SelectorDescriptor | null = null;

  while (retryCount < maxRetries) {
    const currentDomain = new URL(page.url() || step.url || "https://example.com").hostname;
    try {
      const policy = evaluatePolicy({
        type: step.action,
        url: step.url || page.url(),
        domain: currentDomain,
        target: step.target,
        form: step.value ? { value: step.value } : undefined,
        allowedDomains: task.allowedDomains
      });

      if (policy.decision === "deny") {
        await emitReplay(
          sequence,
          "policy.denied",
          { action: step.action, reason: policy.reason, target: step.target || null, currentUrl: page.url() },
          hooks
        );
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
        await emitReplay(
          sequence,
          "approval.requested",
          { action: step.action, reason: policy.reason, target: step.target || null, currentUrl: page.url() },
          hooks
        );
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
        await emitReplay(sequence, "approval.approved", { action: step.action, currentUrl: page.url() }, hooks);
      }

      await hooks?.onStepStart?.(step, sequence);
      await page.waitForLoadState("domcontentloaded");
      await emitReplay(
        sequence,
        "step.started",
        {
          retryCount,
          action: step.action,
          stepName: step.name,
          goal: step.goal || step.name,
          target: runtimeCorrection || step.target || null,
          currentUrl: page.url()
        },
        hooks
      );

      let completionMessage = "Step completed";

      if (step.action === "goto" && step.url) {
        await emitReplay(sequence, "navigation.requested", { url: step.url, retryCount }, hooks);
        await page.goto(step.url, { waitUntil: "domcontentloaded" });
      } else if (step.action === "click" && step.target) {
        runtimeCorrection =
          runtimeCorrection ||
          (await hooks?.lookupCorrection?.({ domain: currentDomain, actionType: step.action })) ||
          null;
        const locator = await resolveLocator(page, step.target, runtimeCorrection || undefined);
        await locator.scrollIntoViewIfNeeded();
        await locator.click();
      } else if (step.action === "type" && step.target) {
        runtimeCorrection =
          runtimeCorrection ||
          (await hooks?.lookupCorrection?.({ domain: currentDomain, actionType: step.action })) ||
          null;
        const locator = await resolveLocator(page, step.target, runtimeCorrection || undefined);
        await locator.scrollIntoViewIfNeeded();
        await locator.fill(step.value || "");
        if (step.submit) {
          await locator.press("Enter");
        }
      } else if (step.action === "press" && step.value) {
        await page.keyboard.press(step.value);
      } else if (step.action === "extract" && step.target) {
        const observation = await extractObservation(page, step);
        completionMessage = observation.message;
        await emitReplay(
          sequence,
          "goal.observed",
          {
            found: observation.found,
            observation: observation.message,
            target: step.target,
            goal: step.goal || step.name
          },
          hooks
        );
        if (!observation.found && !step.optional) {
          throw new Error(`Goal not achieved: ${step.goal || step.target.text || step.name}`);
        }
      } else {
        throw new Error(`Unsupported action ${step.action}`);
      }

      await page.waitForLoadState("networkidle").catch(() => undefined);
      const warnings = await verifyStep(page, step);
      if (warnings.length > 0) {
        await emitReplay(
          sequence,
          "goal.warning",
          { warnings, strict: Boolean(step.verification?.strict), currentUrl: page.url() },
          hooks
        );
        if (step.action !== "extract") {
          completionMessage = `${completionMessage}. ${warnings.join("; ")}`;
        }
      }
      await captureReplay(page, sequence, hooks, "screenshot", { retryCount, goal: step.goal || step.name });
      if (runtimeCorrection && step.target && serializeDescriptor(runtimeCorrection) !== serializeDescriptor(step.target)) {
        await hooks?.rememberCorrection?.({
          step,
          sequence,
          domain: currentDomain,
          actionType: step.action,
          failureType: "NONE",
          failedSelector: step.target,
          correctedSelector: runtimeCorrection,
          reason: "Runtime recovery found a better selector"
        });
      }
      await hooks?.onStepUpdate?.({
        step,
        sequence,
        status: "succeeded",
        retryCount,
        failureType: "NONE",
        message: completionMessage
      });
      return;
    } catch (error) {
      retryCount += 1;
      const failureType = classifyFailure(error);
      const message = String((error as Error)?.message || error);
      await emitReplay(
        sequence,
        "step.failed",
        {
          retryCount,
          failureType,
          message,
          target: runtimeCorrection || step.target || null,
          currentUrl: page.url()
        },
        hooks
      );
      await captureReplay(page, sequence, hooks, "screenshot", {
        retryCount,
        failureType,
        error: message,
        goal: step.goal || step.name
      });
      await hooks?.onStepUpdate?.({
        step,
        sequence,
        status: "failed",
        retryCount,
        failureType,
        message
      });
      if (retryCount >= maxRetries) {
        throw error;
      }
      runtimeCorrection = await recoverAfterFailure(
        page,
        step,
        sequence,
        retryCount,
        failureType,
        hooks,
        runtimeCorrection
      );
    }
  }
}

export class PlaywrightExecutionEngine {
  private browser?: Browser;
  private context?: BrowserContext;
  private page?: Page;

  async run(task: AgentTaskInput, hooks?: EngineHooks): Promise<EngineRunResult> {
    this.browser = await chromium.launch({ headless: true });
    this.context = await this.browser.newContext();
    this.page = await this.context.newPage();

    let previousHash = "0";
    for (const [sequence, step] of task.steps.entries()) {
      previousHash = hashStep(previousHash, step);
      await runStep(this.page, task, step, sequence, hooks);
    }

    const result: EngineRunResult = {
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
