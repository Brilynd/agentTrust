const crypto = require('crypto');

function stableStringify(value) {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
}

function actionFingerprint(action) {
  return crypto
    .createHash('sha256')
    .update(
      stableStringify({
        type: action.type || null,
        url: action.url || null,
        domain: action.domain || null,
        target: action.target || null,
        formData: action.formData || action.form || null,
        text:
          action.executionInput?.text ??
          action.text ??
          null,
        clearFirst:
          action.executionInput?.clearFirst ??
          action.clearFirst ??
          null,
        pressEnter:
          action.executionInput?.pressEnter ??
          action.pressEnter ??
          null,
        label: action.label || null,
        index: action.index ?? null,
        provider: action.provider || null,
        method: action.method || null,
        body: action.body || null,
        sessionId: action.sessionId || null,
        promptId: action.promptId || null,
      })
    )
    .digest('hex');
}

function signLeasePayload(payload, secret) {
  const encoded = Buffer.from(JSON.stringify(payload), 'utf8').toString('base64url');
  const signature = crypto.createHmac('sha256', secret).update(encoded).digest('base64url');
  return `${encoded}.${signature}`;
}

function issueExecutionLease({ kind, actionId, agentId, action, approvalId = null, ttlMs = 60000 } = {}) {
  const secret = process.env.AGENTTRUST_EXECUTION_LEASE_SECRET || '';
  if (!secret) {
    return null;
  }

  const now = Date.now();
  const payload = {
    kind,
    actionId,
    agentId,
    approvalId,
    actionHash: actionFingerprint(action || {}),
    nonce: crypto.randomBytes(16).toString('hex'),
    iat: now,
    exp: now + ttlMs,
  };

  return {
    lease: signLeasePayload(payload, secret),
    payload,
  };
}

module.exports = {
  actionFingerprint,
  issueExecutionLease,
  signLeasePayload,
};
