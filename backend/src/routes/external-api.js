const express = require('express');
const router = express.Router();
const axios = require('axios').default || require('axios');
const { validateAction } = require('../middleware/auth');
const { logAction } = require('../services/audit');
const { createApproval } = require('./approvals');

const HIGH_RISK_API_PATTERNS = [
  '/repos/', '/orgs/', '/user/repos',
  '/calendars/', '/acl',
];
const DESTRUCTIVE_URL_KEYWORDS = [
  'delete', 'remove', 'destroy', 'deactivate', 'revoke', 'transfer',
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

router.post('/call', validateAction, async (req, res) => {
  const { provider, method, url: apiUrl, body: apiBody, sessionId, promptId, userToken } = req.body;

  if (!provider || !method || !apiUrl) {
    return res.status(400).json({ success: false, error: 'provider, method, and url are required' });
  }

  const allowed = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  if (!allowed.includes(method.toUpperCase())) {
    return res.status(400).json({ success: false, error: `Invalid method. Allowed: ${allowed.join(', ')}` });
  }

  let apiDomain;
  try {
    apiDomain = new URL(apiUrl).hostname;
  } catch {
    return res.status(400).json({ success: false, error: 'Invalid API URL' });
  }

  const riskLevel = classifyApiRisk(method, apiUrl);
  const requiresApproval = riskLevel === 'high';

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
        ? `High-risk external API call (${method.toUpperCase()} ${provider}) requires approval`
        : `External API call (${provider})`
    });
  } catch (logErr) {
    console.error('Failed to log external API call:', logErr);
  }

  if (requiresApproval) {
    const approval = createApproval({
      sessionId: sessionId || null,
      actionId: loggedAction?.id || null,
      type: 'api_call',
      domain: apiDomain,
      url: apiUrl,
      riskLevel,
      reason: `${method.toUpperCase()} ${apiUrl} — destructive API call requires approval`,
      target: { provider, method: method.toUpperCase() }
    });

    return res.status(403).json({
      success: false,
      error: `High-risk API call requires user approval (${method.toUpperCase()} to ${provider})`,
      requiresStepUp: true,
      riskLevel,
      actionId: loggedAction?.id,
      approvalId: approval.id,
      status: 'step_up_required'
    });
  }

  // Get the provider access token.
  // Strategy 1: Management API — decode stored Auth0 JWT to get user sub, then
  //   call GET /api/v2/users/{sub} to get the provider access token from identities.
  // Strategy 2: Token Vault exchange (fallback).
  let providerToken;
  const pool = require('../config/database');
  const errors = [];

  // Strategy 1: Management API via stored user JWT
  try {
    const dbResult = await pool.query(
      "SELECT auth0_access_token FROM user_connections WHERE provider = $1 AND auth0_access_token IS NOT NULL ORDER BY connected_at DESC LIMIT 1",
      [provider]
    );
    if (dbResult.rows.length > 0) {
      const storedJwt = dbResult.rows[0].auth0_access_token;
      const auth0UserId = extractAuth0UserId(storedJwt);
      if (auth0UserId) {
        providerToken = await getProviderTokenViaManagementApi(provider, auth0UserId);
        console.log(`Got ${provider} token via Management API for user ${auth0UserId}`);
      }
    }
  } catch (err) {
    const msg = err.response?.data?.message || err.response?.data?.error_description || err.message;
    errors.push(`Management API: ${msg}`);
    console.log(`Management API strategy failed for ${provider}:`, msg);
  }

  // Strategy 2: Token Vault exchange with stored access_token
  if (!providerToken) {
    try {
      const subjectToken = userToken || req.headers.authorization?.substring(7);
      if (subjectToken) {
        providerToken = await exchangeTokenViaTokenVault(provider, subjectToken);
        console.log(`Got ${provider} token via Token Vault exchange`);
      }
    } catch (err) {
      const msg = err.response?.data?.error_description || err.message;
      errors.push(`Token Vault: ${msg}`);
      console.log(`Token Vault strategy failed for ${provider}:`, msg);
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
    res.status(status).json({
      success: false,
      error: data?.message || apiErr.message,
      status,
      data
    });
  }
});

module.exports = router;
