const { requestJson, HttpError } = require('./http');

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function getDomain(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
}

class AgentTrustBridge {
  constructor(options = {}) {
    this.apiBaseUrl = trimTrailingSlash(
      options.apiBaseUrl || process.env.AGENTTRUST_API_URL || 'http://localhost:3000/api'
    );
    this.auth0Domain = trimTrailingSlash(options.auth0Domain || process.env.AUTH0_DOMAIN);
    this.auth0ClientId = options.auth0ClientId || process.env.AUTH0_CLIENT_ID;
    this.auth0ClientSecret = options.auth0ClientSecret || process.env.AUTH0_CLIENT_SECRET;
    this.auth0Audience = trimTrailingSlash(options.auth0Audience || process.env.AUTH0_AUDIENCE);
    this.userEmail = options.userEmail || process.env.AGENTTRUST_USER_EMAIL || '';
    this.userPassword = options.userPassword || process.env.AGENTTRUST_USER_PASSWORD || '';

    this.agentToken = null;
    this.agentTokenExpiresAt = 0;
    this.userToken = options.userToken || null;
    this.currentSessionId = null;
    this.currentPromptId = null;
  }

  async getAgentToken(forceRefresh = false) {
    if (!forceRefresh && this.agentToken && Date.now() < this.agentTokenExpiresAt) {
      return this.agentToken;
    }

    if (!this.auth0Domain || !this.auth0ClientId || !this.auth0ClientSecret || !this.auth0Audience) {
      throw new Error(
        'Missing Auth0 M2M configuration. Set AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, and AUTH0_AUDIENCE.'
      );
    }

    const data = await requestJson(`https://${this.auth0Domain}/oauth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: this.auth0ClientId,
        client_secret: this.auth0ClientSecret,
        audience: this.auth0Audience,
        grant_type: 'client_credentials',
      }),
    });

    this.agentToken = data.access_token;
    this.agentTokenExpiresAt = Date.now() + Math.max((data.expires_in || 3600) - 300, 60) * 1000;
    return this.agentToken;
  }

  async loginUser({ email, password } = {}) {
    const resolvedEmail = email || this.userEmail;
    const resolvedPassword = password || this.userPassword;

    if (!resolvedEmail || !resolvedPassword) {
      throw new Error('User login requires an email and password.');
    }

    const data = await requestJson(`${this.apiBaseUrl}/users/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: resolvedEmail,
        password: resolvedPassword,
      }),
    });

    this.userToken = data.token;
    return data;
  }

  async ensureUserToken() {
    if (this.userToken) {
      return this.userToken;
    }

    await this.loginUser();
    return this.userToken;
  }

  async requestAgent(pathname, options = {}) {
    const token = await this.getAgentToken();
    return requestJson(`${this.apiBaseUrl}${pathname}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        Authorization: `Bearer ${token}`,
      },
    });
  }

  async requestUser(pathname, options = {}) {
    const token = await this.ensureUserToken();
    return requestJson(`${this.apiBaseUrl}${pathname}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        Authorization: `Bearer ${token}`,
      },
    });
  }

  async verifyConnectivity() {
    const healthUrl = this.apiBaseUrl.replace(/\/api$/, '/health');
    await requestJson(healthUrl);
    await this.getAgentToken();
    return { ok: true };
  }

  async createSession() {
    const data = await this.requestAgent('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });

    this.currentSessionId = data?.session?.id || null;
    if (this.currentSessionId && this.userToken) {
      await this.claimSession(this.currentSessionId);
    }
    return data.session;
  }

  async endSession(sessionId = this.currentSessionId) {
    if (!sessionId) return null;

    const data = await this.requestAgent(`/sessions/${sessionId}/end`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });

    if (this.currentSessionId === sessionId) {
      this.currentSessionId = null;
    }
    return data.session;
  }

  async storePrompt(content, sessionId = this.currentSessionId) {
    const data = await this.requestAgent('/prompts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        sessionId: sessionId || undefined,
      }),
    });

    this.currentPromptId = data?.prompt?.id || null;
    return data.prompt;
  }

  async updatePromptProgress(promptId, progress) {
    if (!promptId) return null;
    return this.requestAgent(`/prompts/${promptId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ progress }),
    });
  }

  async updatePromptResponse(promptId, response) {
    if (!promptId) return null;
    return this.requestAgent(`/prompts/${promptId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response }),
    });
  }

  async uploadScreenshot(actionId, screenshot) {
    if (!actionId || !screenshot) return null;
    return this.requestAgent(`/actions/${actionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ screenshot }),
    });
  }

  async executeAction(actionData, options = {}) {
    const payload = {
      ...actionData,
      domain: actionData.domain || getDomain(actionData.url),
      sessionId: actionData.sessionId || this.currentSessionId || undefined,
      promptId: actionData.promptId || this.currentPromptId || undefined,
    };

    try {
      const data = await this.requestAgent('/actions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      return {
        status: 'allowed',
        action_id: data?.action?.id,
        risk_level: data?.action?.riskLevel,
        executionLease: data?.executionLease || null,
        message: 'Action allowed and logged',
        raw: data,
      };
    } catch (error) {
      if (!(error instanceof HttpError) || error.status !== 403) {
        throw error;
      }

      const data = error.data || {};
      if (!data.requiresStepUp || !data.approvalId) {
        return {
          status: 'denied',
          message: data.error || error.message,
          risk_level: data.riskLevel,
          raw: data,
        };
      }

      if (options.autoWaitForApproval === false) {
        return {
          status: 'step_up_required',
          message: data.error || 'Action requires approval',
          risk_level: data.riskLevel,
          approvalId: data.approvalId,
          action_id: data.actionId,
          raw: data,
        };
      }

      const approvalResult = await this.waitForApproval(data.approvalId, options.approvalTimeoutSeconds || 120);
      if (!approvalResult.approved) {
        return {
          status: 'denied',
          message: approvalResult.reason || 'Action denied or approval timed out',
          risk_level: data.riskLevel,
          approval_denied: true,
          approvalId: data.approvalId,
          raw: data,
        };
      }

      return this.retryActionWithApproval(payload, data.approvalId);
    }
  }

  async retryActionWithApproval(actionData, approvalId) {
    try {
      const data = await this.requestAgent('/actions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...actionData,
          approvalId,
        }),
      });

      return {
        status: 'allowed',
        action_id: data?.action?.id,
        risk_level: data?.action?.riskLevel,
        executionLease: data?.executionLease || null,
        message: 'Action allowed after user approval',
        raw: data,
      };
    } catch (error) {
      if (error instanceof HttpError) {
        return {
          status: 'error',
          message: error.message,
          status_code: error.status,
          raw: error.data,
        };
      }
      throw error;
    }
  }

  async waitForApproval(approvalId, timeoutSeconds = 120) {
    try {
      const data = await this.requestAgent(`/approvals/${approvalId}/wait?timeout=${Math.min(timeoutSeconds, 60) * 1000}`, {
        method: 'GET',
      });

      return {
        approved: !!data.approved,
        reason: data.reason,
        actionId: data.actionId,
        approvalId,
      };
    } catch (error) {
      if (error instanceof HttpError && error.status === 404) {
        return { approved: false, reason: 'Approval not found or expired', approvalId };
      }
      throw error;
    }
  }

  async respondToApproval(approvalId, approved) {
    return this.requestUser(`/approvals/${approvalId}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: !!approved }),
    });
  }

  async listPendingApprovals(sessionId) {
    const query = sessionId ? `?sessionId=${encodeURIComponent(sessionId)}` : '';
    const data = await this.requestUser(`/approvals/pending${query}`, { method: 'GET' });
    return data.approvals || [];
  }

  async sendCommand(content, sessionId = this.currentSessionId) {
    if (!sessionId) {
      throw new Error('A sessionId is required to send a command.');
    }

    return this.requestUser('/commands', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, sessionId }),
    });
  }

  async claimSession(sessionId = this.currentSessionId) {
    if (!sessionId) {
      throw new Error('A sessionId is required to claim a session.');
    }

    const data = await this.requestUser(`/sessions/${sessionId}/claim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });

    return data.session;
  }

  async pollCommand(sessionId = this.currentSessionId, timeoutSeconds = 30) {
    if (!sessionId) return null;

    const data = await this.requestAgent(
      `/commands/pending?sessionId=${encodeURIComponent(sessionId)}&timeout=${Math.min(timeoutSeconds, 30) * 1000}`,
      { method: 'GET' }
    );
    return data.command || null;
  }

  async getSession(sessionId = this.currentSessionId) {
    if (!sessionId) {
      throw new Error('A sessionId is required to load session details.');
    }

    const data = await this.requestUser(`/sessions/${sessionId}`, { method: 'GET' });
    return data.session;
  }

  async listSessions({ agentId = 'all', limit = 20, fields = 'full' } = {}) {
    const params = new URLSearchParams({
      agentId,
      limit: String(limit),
      fields,
    });
    const data = await this.requestUser(`/sessions?${params.toString()}`, { method: 'GET' });
    return data.sessions || [];
  }

  async callExternalApi({ provider, method, url, body, sessionId, promptId, approvalId }, options = {}) {
    const payload = {
      provider,
      method,
      url,
      body,
      sessionId: sessionId || this.currentSessionId || undefined,
      promptId: promptId || this.currentPromptId || undefined,
      userToken: this.userToken || undefined,
      issueLeaseOnly: !!options.issueLeaseOnly,
      approvalId: approvalId || options.approvalId || undefined,
    };

    try {
      return await this.requestAgent('/external/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      if (!(error instanceof HttpError) || error.status !== 403) {
        throw error;
      }

      const data = error.data || {};
      if (!data.requiresStepUp || !data.approvalId) {
        return {
          success: false,
          status: 'denied',
          error: data.error || error.message,
          riskLevel: data.riskLevel,
        };
      }

      if (options.autoWaitForApproval === false) {
        return {
          success: false,
          status: 'step_up_required',
          error: data.error || 'API call requires approval',
          approvalId: data.approvalId,
          riskLevel: data.riskLevel,
        };
      }

      const approvalResult = await this.waitForApproval(data.approvalId, options.approvalTimeoutSeconds || 120);
      if (!approvalResult.approved) {
        return {
          success: false,
          status: 'denied',
          error: approvalResult.reason || 'API call denied or approval timed out',
          approvalId: data.approvalId,
          riskLevel: data.riskLevel,
        };
      }

      return this.requestAgent('/external/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...payload,
          approvalId: data.approvalId,
        }),
      });
    }
  }
}

module.exports = {
  AgentTrustBridge,
  getDomain,
};
