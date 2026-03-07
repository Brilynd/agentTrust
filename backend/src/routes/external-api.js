const express = require('express');
const router = express.Router();
const axios = require('axios').default || require('axios');
const { validateAction } = require('../middleware/auth');
const { logAction } = require('../services/audit');

const AUTH0_DOMAIN = process.env.AUTH0_DOMAIN;
const AUTH0_CLIENT_ID = process.env.AUTH0_CLIENT_ID;
const AUTH0_CLIENT_SECRET = process.env.AUTH0_CLIENT_SECRET;
const AUTH0_AUDIENCE = process.env.AUTH0_AUDIENCE;

async function exchangeToken(provider, subjectToken) {
  const response = await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
    grant_type: 'urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token',
    client_id: AUTH0_CLIENT_ID,
    client_secret: AUTH0_CLIENT_SECRET,
    subject_token: subjectToken,
    subject_token_type: 'urn:auth0:params:oauth:token-type:access-token',
    connection: provider,
    audience: AUTH0_AUDIENCE
  }, { timeout: 10000 });
  return response.data.access_token;
}

// Agent calls an external API through the backend proxy (M2M auth)
router.post('/call', validateAction, async (req, res) => {
  const { provider, method, url: apiUrl, body: apiBody, sessionId, promptId } = req.body;

  if (!provider || !method || !apiUrl) {
    return res.status(400).json({ success: false, error: 'provider, method, and url are required' });
  }

  const allowed = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  if (!allowed.includes(method.toUpperCase())) {
    return res.status(400).json({ success: false, error: `Invalid method. Allowed: ${allowed.join(', ')}` });
  }

  // Extract domain from the target API URL for audit logging
  let apiDomain;
  try {
    apiDomain = new URL(apiUrl).hostname;
  } catch {
    return res.status(400).json({ success: false, error: 'Invalid API URL' });
  }

  // Log the external API call to audit
  try {
    await logAction({
      type: 'api_call',
      url: apiUrl,
      domain: apiDomain,
      target: { provider, method: method.toUpperCase() },
      agentId: req.agent.id,
      sessionId: sessionId || null,
      promptId: promptId || null,
      timestamp: new Date().toISOString(),
      riskLevel: 'low',
      status: 'allowed',
      reason: `External API call via Token Vault (${provider})`
    });
  } catch (logErr) {
    console.error('Failed to log external API call:', logErr);
  }

  // Try to exchange token via Token Vault
  let providerToken;
  try {
    const agentToken = req.headers.authorization?.substring(7);
    providerToken = await exchangeToken(provider, agentToken);
  } catch (exchangeErr) {
    const msg = exchangeErr.response?.data?.error_description || exchangeErr.message;
    return res.status(502).json({
      success: false,
      error: `Token exchange failed for ${provider}: ${msg}. Ensure the user has connected this provider in the extension.`
    });
  }

  // Make the actual API call
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
      data: response.data
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
