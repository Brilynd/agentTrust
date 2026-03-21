const { getDomain } = require('./agenttrust-client');

function requiredMethod(provider, methodName) {
  const value = provider && provider[methodName];
  if (typeof value !== 'function') {
    throw new Error(`OpenClaw browser provider must implement ${methodName}().`);
  }
  return value.bind(provider);
}

class OpenClawBrowserAdapter {
  constructor(provider) {
    this.provider = provider || {};
    this.navigateImpl = requiredMethod(this.provider, 'navigate');
    this.clickImpl = requiredMethod(this.provider, 'click');
    this.typeImpl = requiredMethod(this.provider, 'type');
    this.submitImpl = requiredMethod(this.provider, 'submit');
    this.openTabImpl = requiredMethod(this.provider, 'openTab');
    this.switchTabImpl = requiredMethod(this.provider, 'switchTab');
    this.getPageImpl = requiredMethod(this.provider, 'getCurrentPage');
  }

  async getCurrentPage() {
    const snapshot = await this.getPageImpl();
    return {
      url: snapshot?.url || '',
      title: snapshot?.title || '',
      text: snapshot?.text || '',
      untrustedContent: snapshot?.untrustedContent || snapshot?.text || '',
      screenshot: snapshot?.screenshot || null,
      elements: Array.isArray(snapshot?.elements) ? snapshot.elements : [],
      domain: snapshot?.domain || getDomain(snapshot?.url || ''),
      activeTab: snapshot?.activeTab || null,
      tabs: Array.isArray(snapshot?.tabs) ? snapshot.tabs : [],
    };
  }

  async navigate({ url }) {
    return this.navigateImpl({ url });
  }

  async click({ target }) {
    return this.clickImpl({ target });
  }

  async type({ target, text, clearFirst = true, pressEnter = false }) {
    return this.typeImpl({ target, text, clearFirst, pressEnter });
  }

  async submit({ target, formData }) {
    return this.submitImpl({ target, formData });
  }

  async openTab({ url, label }) {
    return this.openTabImpl({ url, label });
  }

  async switchTab({ label, index }) {
    return this.switchTabImpl({ label, index });
  }

  async captureSnapshot({ includeScreenshot = true } = {}) {
    const snapshot = await this.getCurrentPage();
    if (!includeScreenshot) {
      snapshot.screenshot = null;
    }
    return snapshot;
  }
}

module.exports = {
  OpenClawBrowserAdapter,
};
