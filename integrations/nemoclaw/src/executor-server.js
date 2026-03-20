const http = require('http');
const crypto = require('crypto');

const { loadAgentTrustNemoclawEnv } = require('./load-env');
const { AgentTrustBridge } = require('./agenttrust-client');
const { OpenClawBrowserAdapter } = require('./browser-adapter');

loadAgentTrustNemoclawEnv();

function getLeaseSecret() {
  const secret = process.env.AGENTTRUST_EXECUTION_LEASE_SECRET || '';
  if (!secret) {
    throw new Error('Missing AGENTTRUST_EXECUTION_LEASE_SECRET');
  }
  return secret;
}

function getProviderModule() {
  const providerModule = process.env.AGENTTRUST_BROWSER_PROVIDER_MODULE || '';
  if (!providerModule) {
    throw new Error('Missing AGENTTRUST_BROWSER_PROVIDER_MODULE');
  }
  return providerModule;
}

function base64urlDecode(value) {
  const normalized = String(value).replace(/-/g, '+').replace(/_/g, '/');
  const padding = normalized.length % 4 === 0 ? '' : '='.repeat(4 - (normalized.length % 4));
  return Buffer.from(normalized + padding, 'base64').toString('utf8');
}

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
        type: action.type,
        url: action.url,
        domain: action.domain,
        target: action.target || null,
        formData: action.formData || null,
        provider: action.provider || null,
        method: action.method || null,
        sessionId: action.sessionId || null,
        promptId: action.promptId || null,
      })
    )
    .digest('hex');
}

function verifyLease(token) {
  const leaseSecret = getLeaseSecret();
  const [encoded, signature] = String(token || '').split('.');
  if (!encoded || !signature) {
    throw new Error('Invalid lease token format');
  }

  const expected = crypto.createHmac('sha256', leaseSecret).update(encoded).digest('base64url');
  const provided = Buffer.from(signature);
  const expectedBuf = Buffer.from(expected);

  if (provided.length !== expectedBuf.length || !crypto.timingSafeEqual(provided, expectedBuf)) {
    throw new Error('Invalid lease signature');
  }

  const payload = JSON.parse(base64urlDecode(encoded));
  if (!payload.exp || Date.now() >= payload.exp) {
    throw new Error('Lease expired');
  }

  return payload;
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 2 * 1024 * 1024) {
        reject(new Error('Request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error('Invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

function writeJson(res, statusCode, body) {
  const text = JSON.stringify(body);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(text),
  });
  res.end(text);
}

function loadBrowserProvider() {
  const loaded = require(getProviderModule());
  const provider = loaded.default || loaded.browserProvider || loaded;
  return new OpenClawBrowserAdapter(provider);
}

async function executeBrowserAction(browser, action) {
  switch (action.type) {
    case 'navigation':
      return browser.navigate({ url: action.url });
    case 'click':
      return browser.click({ target: action.target });
    case 'form_input':
      return browser.type({
        target: action.target,
        text: action.text || '',
        clearFirst: action.clearFirst !== false,
        pressEnter: !!action.pressEnter,
      });
    case 'form_submit':
      return browser.submit({ target: action.target });
    case 'open_tab':
      return browser.openTab({ url: action.url, label: action.label });
    case 'switch_tab':
      return browser.switchTab({ label: action.label, index: action.index });
    default:
      throw new Error(`Unsupported browser action type: ${action.type}`);
  }
}

async function main() {
  const host = process.env.AGENTTRUST_EXECUTOR_HOST || '127.0.0.1';
  const port = Number(process.env.AGENTTRUST_EXECUTOR_PORT || 3101);
  const bridge = new AgentTrustBridge({
    apiBaseUrl: process.env.AGENTTRUST_API_URL,
    auth0Domain: process.env.AUTH0_DOMAIN,
    auth0ClientId: process.env.AUTH0_CLIENT_ID,
    auth0ClientSecret: process.env.AUTH0_CLIENT_SECRET,
    auth0Audience: process.env.AUTH0_AUDIENCE,
    userEmail: process.env.AGENTTRUST_USER_EMAIL,
    userPassword: process.env.AGENTTRUST_USER_PASSWORD,
    userToken: process.env.AGENTTRUST_USER_TOKEN,
  });

  const browser = loadBrowserProvider();
  const usedNonces = new Map();

  await bridge.verifyConnectivity();

  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === 'GET' && req.url === '/health') {
        return writeJson(res, 200, { ok: true, service: 'agenttrust-executor' });
      }

      if (req.method !== 'POST' || (req.url !== '/execute/browser' && req.url !== '/execute/api')) {
        return writeJson(res, 404, { ok: false, error: 'Not found' });
      }

      const body = await readJson(req);
      const lease = verifyLease(body.lease);

      if (!lease.nonce) {
        throw new Error('Lease missing nonce');
      }
      if (usedNonces.has(lease.nonce)) {
        throw new Error('Lease nonce already used');
      }
      usedNonces.set(lease.nonce, lease.exp);

      for (const [nonce, exp] of usedNonces.entries()) {
        if (exp <= Date.now()) {
          usedNonces.delete(nonce);
        }
      }

      const action = body.action || {};
      const fingerprint = actionFingerprint(action);
      if (lease.actionHash !== fingerprint) {
        throw new Error('Lease/action hash mismatch');
      }

      if (req.url === '/execute/browser') {
        if (lease.kind !== 'browser_action') {
          throw new Error('Lease kind mismatch');
        }

        const result = await executeBrowserAction(browser, action);
        const snapshot = await browser.captureSnapshot({ includeScreenshot: true });
        if (lease.actionId && snapshot.screenshot) {
          await bridge.uploadScreenshot(lease.actionId, snapshot.screenshot);
        }

        return writeJson(res, 200, {
          ok: true,
          result,
          screenshotAttached: !!(lease.actionId && snapshot.screenshot),
        });
      }

      if (lease.kind !== 'api_action') {
        throw new Error('Lease kind mismatch');
      }

      const result = await bridge.callExternalApi(
        {
          provider: action.provider,
          method: action.method,
          url: action.url,
          body: action.body,
          sessionId: action.sessionId,
          promptId: action.promptId,
        },
        { autoWaitForApproval: false }
      );

      return writeJson(res, 200, { ok: true, result });
    } catch (error) {
      return writeJson(res, 400, { ok: false, error: error.message || 'Executor error' });
    }
  });

  server.listen(port, host, () => {
    console.log(`agenttrust-executor listening on http://${host}:${port}`);
  });
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = {
  actionFingerprint,
  verifyLease,
};
