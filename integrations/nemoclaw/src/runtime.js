const { getDomain } = require('./agenttrust-client');

function stringifyTarget(target) {
  if (!target) return 'unknown target';
  return (
    target.text ||
    target.aria_label ||
    target.ariaLabel ||
    target.id ||
    target.href ||
    target.selector ||
    target.name ||
    'unnamed target'
  );
}

class AgentTrustOpenClawRuntime {
  constructor({ agentTrust, browser, approvalTimeoutSeconds = 120 } = {}) {
    if (!agentTrust) {
      throw new Error('AgentTrustOpenClawRuntime requires an agentTrust bridge.');
    }
    if (!browser) {
      throw new Error('AgentTrustOpenClawRuntime requires a browser adapter.');
    }

    this.agentTrust = agentTrust;
    this.browser = browser;
    this.approvalTimeoutSeconds = approvalTimeoutSeconds;
    this.progressLines = [];
  }

  async startSession() {
    const session = await this.agentTrust.createSession();
    this.progressLines = [];
    return session;
  }

  async endSession() {
    return this.agentTrust.endSession();
  }

  async startPrompt(content) {
    const prompt = await this.agentTrust.storePrompt(content);
    this.progressLines = [];
    await this.pushProgress('PLAN', 'Starting task');
    return prompt;
  }

  async completePrompt(response) {
    await this.pushProgress('DONE', 'Done');
    if (this.agentTrust.currentPromptId) {
      await this.agentTrust.updatePromptResponse(this.agentTrust.currentPromptId, response);
    }
  }

  async pushProgress(stage, message) {
    this.progressLines.push(`${stage}|${message}`);
    if (this.agentTrust.currentPromptId) {
      await this.agentTrust.updatePromptProgress(
        this.agentTrust.currentPromptId,
        this.progressLines.join('\n')
      );
    }
    return this.progressLines;
  }

  async captureContext({ includeScreenshot = true } = {}) {
    return this.browser.captureSnapshot({ includeScreenshot });
  }

  async uploadPostActionScreenshot(actionId) {
    const post = await this.captureContext({ includeScreenshot: true });
    if (post.screenshot) {
      await this.agentTrust.uploadScreenshot(actionId, post.screenshot);
    }
    return post;
  }

  async guardedNavigate({ url }) {
    await this.pushProgress('ACT', `Navigating to ${getDomain(url) || url}`);

    const decision = await this.agentTrust.executeAction(
      {
        type: 'navigation',
        url,
        domain: getDomain(url),
      },
      {
        approvalTimeoutSeconds: this.approvalTimeoutSeconds,
      }
    );

    if (decision.status !== 'allowed') {
      return decision;
    }

    const result = await this.browser.navigate({ url });
    await this.uploadPostActionScreenshot(decision.action_id);
    return { ...decision, browser_result: result };
  }

  async guardedClick({ target }) {
    const current = await this.captureContext({ includeScreenshot: true });
    await this.pushProgress('ACT', `Clicking ${stringifyTarget(target)}`);

    const decision = await this.agentTrust.executeAction(
      {
        type: 'click',
        url: current.url,
        domain: current.domain,
        target,
        screenshot: current.screenshot,
        pageText: current.text,
        untrustedContent: current.untrustedContent,
      },
      {
        approvalTimeoutSeconds: this.approvalTimeoutSeconds,
      }
    );

    if (decision.status !== 'allowed') {
      return decision;
    }

    const result = await this.browser.click({ target });
    await this.uploadPostActionScreenshot(decision.action_id);
    return { ...decision, browser_result: result };
  }

  async guardedType({ target, text, isSensitive = false, submit = false }) {
    const current = await this.captureContext({ includeScreenshot: true });
    await this.pushProgress('ACT', `Typing into ${stringifyTarget(target)}`);

    const decision = await this.agentTrust.executeAction(
      {
        type: 'form_input',
        url: current.url,
        domain: current.domain,
        target: {
          ...target,
          is_sensitive: !!isSensitive,
        },
        form: {
          fields: {
            value: {
              type: isSensitive ? 'password' : 'text',
              hasValue: true,
            },
          },
        },
        screenshot: current.screenshot,
        pageText: current.text,
        untrustedContent: current.untrustedContent,
      },
      {
        approvalTimeoutSeconds: this.approvalTimeoutSeconds,
      }
    );

    if (decision.status !== 'allowed') {
      return decision;
    }

    const result = await this.browser.type({
      target,
      text,
      clearFirst: true,
      pressEnter: !!submit,
    });
    await this.uploadPostActionScreenshot(decision.action_id);
    return { ...decision, browser_result: result };
  }

  async guardedSubmit({ target, formData = {} }) {
    const current = await this.captureContext({ includeScreenshot: true });
    await this.pushProgress('ACT', `Submitting ${stringifyTarget(target)}`);

    const decision = await this.agentTrust.executeAction(
      {
        type: 'form_submit',
        url: current.url,
        domain: current.domain,
        target,
        form: {
          fields: formData,
        },
        screenshot: current.screenshot,
        pageText: current.text,
        untrustedContent: current.untrustedContent,
      },
      {
        approvalTimeoutSeconds: this.approvalTimeoutSeconds,
      }
    );

    if (decision.status !== 'allowed') {
      return decision;
    }

    const result = await this.browser.submit({ target });
    await this.uploadPostActionScreenshot(decision.action_id);
    return { ...decision, browser_result: result };
  }

  async guardedOpenTab({ url, label }) {
    await this.pushProgress('ACT', `Opening tab ${label || getDomain(url) || url}`);
    const result = await this.browser.openTab({ url, label });
    return { success: true, browser_result: result };
  }

  async guardedSwitchTab({ label, index }) {
    await this.pushProgress('ACT', `Switching tab ${label || index}`);
    const result = await this.browser.switchTab({ label, index });
    return { success: true, browser_result: result };
  }

  async guardedExtractPage() {
    const snapshot = await this.captureContext({ includeScreenshot: true });
    await this.pushProgress('OBSERVE', `Viewing ${snapshot.domain || snapshot.url}`);
    return snapshot;
  }

  async guardedCaptureScreenshot() {
    const snapshot = await this.captureContext({ includeScreenshot: true });
    await this.pushProgress('OBSERVE', 'Captured screenshot');
    return {
      screenshot: snapshot.screenshot,
      url: snapshot.url,
      title: snapshot.title,
    };
  }

  async guardedExternalApiCall({ provider, method, url, body }) {
    await this.pushProgress('ACT', `API call ${method.toUpperCase()} ${provider}`);
    return this.agentTrust.callExternalApi(
      { provider, method, url, body },
      { approvalTimeoutSeconds: this.approvalTimeoutSeconds }
    );
  }

  createGuardedToolset() {
    return {
      guarded_navigate: (args) => this.guardedNavigate(args),
      guarded_click: (args) => this.guardedClick(args),
      guarded_type: (args) => this.guardedType(args),
      guarded_submit: (args) => this.guardedSubmit(args),
      guarded_open_tab: (args) => this.guardedOpenTab(args),
      guarded_switch_tab: (args) => this.guardedSwitchTab(args),
      guarded_extract_page: () => this.guardedExtractPage(),
      guarded_capture_screenshot: () => this.guardedCaptureScreenshot(),
      guarded_external_api_call: (args) => this.guardedExternalApiCall(args),
    };
  }
}

module.exports = {
  AgentTrustOpenClawRuntime,
};
