const express = require('express');
const router = express.Router();
const axios = require('axios').default || require('axios');
const { validateAction } = require('../middleware/auth');
const { logAction } = require('../services/audit');
const { evaluateUntrustedContent, getPolicies } = require('../services/policy-engine');
const { createApproval } = require('./approvals');

const HIGH_RISK_API_PATTERNS = [
  '/repos/', '/orgs/', '/user/repos',
  '/calendars/', '/acl',
  '/chat.postmessage', '/chat.update', '/chat.delete',
  '/me/sendmail', '/me/messages', '/me/drive/',
  '/me/todo/',
  '/v1/pages', '/v1/databases', '/v1/blocks',
];
const DESTRUCTIVE_URL_KEYWORDS = [
  'delete', 'remove', 'destroy', 'deactivate', 'revoke', 'transfer',
];
const IMPACT_URL_KEYWORDS = [
  'send', 'comment', 'issue', 'message', 'event',
  'invite', 'publish', 'mail', 'email', 'review',
  'calendar', 'compose',
  'postmessage', 'channels', 'conversations',
  'sendmail', 'todo', 'tasks', 'drive', 'files',
  'pages', 'databases', 'blocks',
];

function classifyApiRisk(method, url) {
  const m = method.toUpperCase();
  const urlLower = url.toLowerCase();

  if (m === 'DELETE') return 'high';

  if (m === 'GET') {
    if (DESTRUCTIVE_URL_KEYWORDS.some(kw => urlLower.includes(kw))) return 'medium';
    return 'low';
  }

  if (['POST', 'PUT', 'PATCH'].includes(m)) {
    if (DESTRUCTIVE_URL_KEYWORDS.some(kw => urlLower.includes(kw))) return 'high';
    if (IMPACT_URL_KEYWORDS.some(kw => urlLower.includes(kw))) return 'high';
    if (HIGH_RISK_API_PATTERNS.some(p => urlLower.includes(p))) return 'medium';
    return 'medium';
  }

  return 'low';
}

const AUTH0_DOMAIN = process.env.AUTH0_DOMAIN;
const AUTH0_CLIENT_ID = process.env.AUTH0_CLIENT_ID;
const AUTH0_CLIENT_SECRET = process.env.AUTH0_CLIENT_SECRET;
const AUTH0_AUDIENCE = process.env.AUTH0_AUDIENCE;

const PROVIDER_TO_AUTH0_CONNECTION = {
  'github': 'github',
  'google-oauth2': 'google-oauth2',
  'slack': 'slack',
  'windowslive': 'windowslive',
  'notion': 'notion',
};

let _mgmtTokenCache = { token: null, expiresAt: 0 };

async function getManagementApiToken() {
  if (_mgmtTokenCache.token && Date.now() < _mgmtTokenCache.expiresAt) {
    return _mgmtTokenCache.token;
  }
  const resp = await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
    grant_type: 'client_credentials',
    client_id: AUTH0_CLIENT_ID,
    client_secret: AUTH0_CLIENT_SECRET,
    audience: `https://${AUTH0_DOMAIN}/api/v2/`
  }, { timeout: 10000 });
  _mgmtTokenCache = {
    token: resp.data.access_token,
    expiresAt: Date.now() + (resp.data.expires_in - 60) * 1000
  };
  return _mgmtTokenCache.token;
}

async function getProviderTokenViaManagementApi(provider, auth0UserId) {
  const mgmtToken = await getManagementApiToken();
  const resp = await axios.get(
    `https://${AUTH0_DOMAIN}/api/v2/users/${encodeURIComponent(auth0UserId)}?fields=identities&include_fields=true`,
    { headers: { Authorization: `Bearer ${mgmtToken}` }, timeout: 10000 }
  );
  const connection = PROVIDER_TO_AUTH0_CONNECTION[provider] || provider;
  const identity = (resp.data.identities || []).find(id => id.connection === connection);
  if (!identity || !identity.access_token) {
    throw new Error(`No ${provider} access token found in user identities`);
  }
  return identity.access_token;
}

function extractAuth0UserId(jwt) {
  try {
    const payload = JSON.parse(Buffer.from(jwt.split('.')[1], 'base64url').toString());
    return payload.sub;
  } catch {
    return null;
  }
}

async function exchangeTokenViaTokenVault(provider, subjectToken) {
  const response = await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
    grant_type: 'urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token',
    client_id: AUTH0_CLIENT_ID,
    client_secret: AUTH0_CLIENT_SECRET,
    subject_token: subjectToken,
    subject_token_type: 'urn:ietf:params:oauth:token-type:access_token',
    requested_token_type: 'http://auth0.com/oauth/token-type/federated-connection-access-token',
    connection: provider,
    audience: AUTH0_AUDIENCE
  }, { timeout: 10000 });
  return response.data.access_token;
}

const SENSITIVE_KEYS = new Set([
  'access_token', 'refresh_token', 'token', 'secret', 'client_secret',
  'private_key', 'api_key', 'authorization', 'cookie', 'session_token',
  'x-auth-token',
]);
const MAX_RESPONSE_SIZE = 50000;

function sanitizeApiResponse(data, depth = 0) {
  if (depth > 10) return '[nested]';
  if (data === null || data === undefined) return data;
  if (typeof data === 'string') {
    return data.length > 5000 ? data.substring(0, 5000) + '...[truncated]' : data;
  }
  if (typeof data !== 'object') return data;

  if (Array.isArray(data)) {
    const capped = data.length > 50 ? data.slice(0, 50) : data;
    const result = capped.map(item => sanitizeApiResponse(item, depth + 1));
    if (data.length > 50) result.push(`...[${data.length - 50} more items]`);
    return result;
  }

  const cleaned = {};
  for (const [key, value] of Object.entries(data)) {
    if (SENSITIVE_KEYS.has(key.toLowerCase())) {
      cleaned[key] = '[REDACTED]';
    } else {
      cleaned[key] = sanitizeApiResponse(value, depth + 1);
    }
  }
  return cleaned;
}

function _buildApiImpactSummary(method, url, provider, body) {
  const m = method.toUpperCase();
  const urlLower = url.toLowerCase();
  const parts = [];

  if (m === 'DELETE') parts.push('Delete');
  else if (m === 'POST') parts.push('Create');
  else if (['PUT', 'PATCH'].includes(m)) parts.push('Update');

  if (urlLower.includes('/issues')) parts.push('issue');
  else if (urlLower.includes('/comments')) parts.push('comment');
  else if (urlLower.includes('/pulls')) parts.push('pull request');
  else if (urlLower.includes('/repos')) parts.push('repository');
  else if (urlLower.includes('/events')) parts.push('calendar event');
  else if (urlLower.includes('/messages') || urlLower.includes('/send')) parts.push('message');
  else if (urlLower.includes('chat.postmessage')) parts.push('Slack message');
  else if (urlLower.includes('conversations.')) parts.push('Slack channel');
  else if (urlLower.includes('/sendmail')) parts.push('Outlook email');
  else if (urlLower.includes('/todo/')) parts.push('To Do task');
  else if (urlLower.includes('/drive/')) parts.push('OneDrive file');
  else if (urlLower.includes('/v1/pages')) parts.push('Notion page');
  else if (urlLower.includes('/v1/databases')) parts.push('Notion database');
  else parts.push('resource');

  parts.push(`on ${provider}`);

  if (body && typeof body === 'object') {
    if (body.title) parts.push(`"${String(body.title).substring(0, 60)}"`);
    else if (body.subject) parts.push(`"${String(body.subject).substring(0, 60)}"`);
    else if (body.summary) parts.push(`"${String(body.summary).substring(0, 60)}"`);
    else if (body.text) parts.push(`"${String(body.text).substring(0, 60)}"`);
    else if (body.channel) parts.push(`to #${String(body.channel).substring(0, 30)}`);
    else if (body.message?.subject) parts.push(`"${String(body.message.subject).substring(0, 60)}"`);
    else if (body.query) parts.push(`search: "${String(body.query).substring(0, 40)}"`);
  }

  return parts.join(' ');
}

router.post('/call', validateAction, async (req, res) => {
  const { provider, method, url: apiUrl, body: apiBody, sessionId, promptId, userToken } = req.body;

  if (!provider || !method || !apiUrl) {
    return res.status(400).json({ success: false, error: 'provider, method, and url are required' });
  }

  const allowed = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  if (!allowed.includes(method.toUpperCase())) {
    return res.status(400).json({ success: false, error: `Invalid method. Allowed: ${allowed.join(', ')}` });
  }

  const auth0Connection = PROVIDER_TO_AUTH0_CONNECTION[provider] || provider;

  let apiDomain;
  try {
    apiDomain = new URL(apiUrl).hostname;
  } catch {
    return res.status(400).json({ success: false, error: 'Invalid API URL' });
  }

  const policies = await getPolicies();
  const untrustedPayload = [
    apiUrl,
    typeof apiBody === 'string' ? apiBody : JSON.stringify(apiBody || {}),
  ].join('\n');
  const untrustedCheck = evaluateUntrustedContent(untrustedPayload, policies);

  const riskLevel = untrustedCheck.flagged ? 'high' : classifyApiRisk(method, apiUrl);

  let approvedViaStepUp = false;
  if (req.body.approvalId) {
    const approvalsModule = require('./approvals');
    const pendingApprovals = approvalsModule.__pendingApprovals;
    if (pendingApprovals) {
      const priorApproval = pendingApprovals.get(req.body.approvalId);
      if (priorApproval && priorApproval.status === 'approved') {
        approvedViaStepUp = true;
      }
    }
  }
  const requiresApproval = riskLevel === 'high' && !approvedViaStepUp;

  if (untrustedCheck.flagged && untrustedCheck.action === 'block' && !approvedViaStepUp) {
    return res.status(403).json({
      success: false,
      error: 'Blocked: API call payload contains prompt-injection or malicious command patterns',
      requiresStepUp: false,
      riskLevel: 'high',
      status: 'denied',
      matches: untrustedCheck.matches
    });
  }

  let loggedAction;
  try {
    loggedAction = await logAction({
      type: 'api_call',
      url: apiUrl,
      domain: apiDomain,
      target: { provider, method: method.toUpperCase() },
      agentId: req.agent.id,
      sessionId: sessionId || null,
      promptId: promptId || null,
      timestamp: new Date().toISOString(),
      riskLevel,
      status: requiresApproval ? 'step_up_required' : 'allowed',
      reason: requiresApproval
        ? (untrustedCheck.flagged
          ? `Untrusted content detected in API payload (${method.toUpperCase()} ${provider}) — requires approval`
          : `High-risk external API call (${method.toUpperCase()} ${provider}) requires approval`)
        : `External API call (${provider})`
    });
  } catch (logErr) {
    console.error('Failed to log external API call:', logErr);
  }

  if (requiresApproval) {
    let bodyPreview = null;
    if (apiBody) {
      try {
        const s = typeof apiBody === 'string' ? apiBody : JSON.stringify(apiBody, null, 2);
        bodyPreview = s.length > 500 ? s.substring(0, 500) + '...' : s;
      } catch { bodyPreview = '[unreadable body]'; }
    }

    const impactSummary = _buildApiImpactSummary(method, apiUrl, provider, apiBody);

    const approval = createApproval({
      sessionId: sessionId || null,
      actionId: loggedAction?.id || null,
      type: 'api_call',
      domain: apiDomain,
      url: apiUrl,
      riskLevel,
      reason: `${method.toUpperCase()} ${apiUrl} — requires approval`,
      target: { provider, method: method.toUpperCase() },
      preview: bodyPreview ? { method: method.toUpperCase(), url: apiUrl, body: bodyPreview } : { method: method.toUpperCase(), url: apiUrl },
      impactSummary,
      promptId: promptId || null
    });

    return res.status(403).json({
      success: false,
      error: `High-risk API call requires user approval (${method.toUpperCase()} to ${provider})`,
      requiresStepUp: true,
      riskLevel,
      actionId: loggedAction?.id,
      approvalId: approval.id,
      status: 'step_up_required',
      matches: untrustedCheck.flagged ? untrustedCheck.matches : undefined
    });
  }

  // Get the provider access token.
  // Strategy 1 (preferred): Token Vault exchange — uses scopes requested during
  //   the connect flow (e.g. 'repo' for GitHub), so write operations work.
  // Strategy 2 (fallback): Management API — reads the identity provider token
  //   stored in Auth0's user profile. This token may lack write scopes if it
  //   originated from a social-login (non-connect) flow.
  let providerToken;
  let tokenStrategy = '';
  const pool = require('../config/database');
  const errors = [];

  // Strategy 1: Token Vault exchange (preserves scopes from connect flow)
  try {
    const subjectToken = userToken || req.headers.authorization?.substring(7);
    if (subjectToken) {
      providerToken = await exchangeTokenViaTokenVault(auth0Connection, subjectToken);
      tokenStrategy = 'Token Vault';
      console.log(`Got ${provider} token via Token Vault exchange`);
    }
  } catch (err) {
    const msg = err.response?.data?.error_description || err.message;
    errors.push(`Token Vault: ${msg}`);
    console.log(`Token Vault strategy failed for ${provider}:`, msg);
  }

  // Strategy 2: Management API via stored user JWT (fallback)
  if (!providerToken) {
    try {
      const dbResult = await pool.query(
        "SELECT auth0_access_token FROM user_connections WHERE provider = $1 AND auth0_access_token IS NOT NULL ORDER BY connected_at DESC LIMIT 1",
        [auth0Connection]
      );
      if (dbResult.rows.length > 0) {
        const storedJwt = dbResult.rows[0].auth0_access_token;
        const auth0UserId = extractAuth0UserId(storedJwt);
        if (auth0UserId) {
          providerToken = await getProviderTokenViaManagementApi(auth0Connection, auth0UserId);
          tokenStrategy = 'Management API';
          console.log(`Got ${provider} token via Management API for user ${auth0UserId}`);
        }
      }
    } catch (err) {
      const msg = err.response?.data?.message || err.response?.data?.error_description || err.message;
      errors.push(`Management API: ${msg}`);
      console.log(`Management API strategy failed for ${provider}:`, msg);
    }
  }

  if (!providerToken) {
    return res.status(502).json({
      success: false,
      error: `Token exchange failed for ${provider}: ${errors.join(' | ')}. Ensure the user has connected this provider via the extension's Permissions > Connected Accounts.`
    });
  }

  try {
    const axiosConfig = {
      method: method.toUpperCase(),
      url: apiUrl,
      headers: {
        'Authorization': `Bearer ${providerToken}`,
        'Accept': 'application/json'
      },
      timeout: 20000
    };

    if (provider === 'notion') {
      axiosConfig.headers['Notion-Version'] = '2022-06-28';
    }

    if (apiBody && ['POST', 'PUT', 'PATCH'].includes(method.toUpperCase())) {
      axiosConfig.data = apiBody;
      axiosConfig.headers['Content-Type'] = 'application/json';
    }

    const response = await axios(axiosConfig);

    res.json({
      success: true,
      status: response.status,
      data: sanitizeApiResponse(response.data)
    });
  } catch (apiErr) {
    const status = apiErr.response?.status || 502;
    const data = apiErr.response?.data;
    let errorMsg = data?.message || apiErr.message;

    // Provide actionable hints for common failures
    if (status === 404 && provider === 'github' && method.toUpperCase() === 'POST') {
      errorMsg += ` (Token obtained via ${tokenStrategy}. ` +
        'If GET works but POST returns 404, the token may lack the "repo" scope. ' +
        'Reconnect GitHub in the extension\'s Connected Accounts to refresh scopes.)';
    }

    res.status(status).json({
      success: false,
      error: errorMsg,
      status,
      data
    });
  }
});

module.exports = router;
