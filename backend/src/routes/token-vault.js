const express = require('express');
const router = express.Router();
const axios = require('axios').default || require('axios');
const { authenticateUser, validateAction } = require('../middleware/auth');

const AUTH0_DOMAIN = process.env.AUTH0_DOMAIN;
const AUTH0_CLIENT_ID = process.env.AUTH0_CLIENT_ID;
const AUTH0_CLIENT_SECRET = process.env.AUTH0_CLIENT_SECRET;
const AUTH0_AUDIENCE = process.env.AUTH0_AUDIENCE;

function isTokenVaultConfigured() {
  return !!(AUTH0_DOMAIN && AUTH0_CLIENT_ID && AUTH0_CLIENT_SECRET);
}

// Agent requests a provider access token via Token Vault exchange (M2M auth)
router.post('/exchange', validateAction, async (req, res) => {
  if (!isTokenVaultConfigured()) {
    return res.status(501).json({ success: false, error: 'Token Vault not configured on this server' });
  }

  const { provider, userToken } = req.body;
  if (!provider) {
    return res.status(400).json({ success: false, error: 'provider is required' });
  }

  try {
    const response = await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
      grant_type: 'urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token',
      client_id: AUTH0_CLIENT_ID,
      client_secret: AUTH0_CLIENT_SECRET,
      subject_token: userToken || req.headers.authorization?.substring(7),
      subject_token_type: 'urn:auth0:params:oauth:token-type:access-token',
      connection: provider,
      audience: AUTH0_AUDIENCE
    }, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 10000
    });

    res.json({
      success: true,
      access_token: response.data.access_token,
      expires_in: response.data.expires_in,
      token_type: response.data.token_type || 'Bearer'
    });
  } catch (error) {
    const msg = error.response?.data?.error_description || error.message;
    console.error('Token Vault exchange error:', msg);
    res.status(error.response?.status || 500).json({
      success: false,
      error: `Token exchange failed: ${msg}`
    });
  }
});

// Extension fetches connected providers (user auth)
router.get('/connections', authenticateUser, async (req, res) => {
  if (!isTokenVaultConfigured()) {
    return res.json({ success: true, connections: [], configured: false });
  }

  // In a full implementation, this would query Auth0 Management API
  // for the user's linked identities. For now, return configured state.
  try {
    const mgmtToken = await getManagementToken();
    if (!mgmtToken) {
      return res.json({ success: true, connections: [], configured: true });
    }

    // Try to get user's linked identities from Auth0
    // This requires the Auth0 Management API and the user's Auth0 user_id
    return res.json({ success: true, connections: [], configured: true });
  } catch {
    return res.json({ success: true, connections: [], configured: true });
  }
});

// Extension initiates OAuth connection for a provider (user auth)
router.post('/connect', authenticateUser, async (req, res) => {
  if (!isTokenVaultConfigured()) {
    return res.status(501).json({ success: false, error: 'Token Vault not configured' });
  }

  const { provider } = req.body;
  if (!provider) {
    return res.status(400).json({ success: false, error: 'provider is required' });
  }

  const redirectUri = process.env.AUTH0_CALLBACK_URL || `http://localhost:3000/api/token-vault/callback`;
  const authorizeUrl = `https://${AUTH0_DOMAIN}/authorize?` + new URLSearchParams({
    response_type: 'code',
    client_id: AUTH0_CLIENT_ID,
    redirect_uri: redirectUri,
    connection: provider,
    scope: 'openid profile email',
    state: JSON.stringify({ provider, userId: req.user.userId })
  }).toString();

  res.json({ success: true, authorizeUrl });
});

// OAuth callback (handles redirect after user authorizes)
router.get('/callback', async (req, res) => {
  const { code, state } = req.query;
  if (!code) {
    return res.status(400).send('Missing authorization code');
  }

  try {
    const stateData = state ? JSON.parse(state) : {};
    const redirectUri = process.env.AUTH0_CALLBACK_URL || `http://localhost:3000/api/token-vault/callback`;

    await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
      grant_type: 'authorization_code',
      client_id: AUTH0_CLIENT_ID,
      client_secret: AUTH0_CLIENT_SECRET,
      code,
      redirect_uri: redirectUri
    });

    res.send('<html><body><h2>Connected successfully!</h2><p>You can close this tab.</p><script>window.close()</script></body></html>');
  } catch (error) {
    console.error('OAuth callback error:', error.response?.data || error.message);
    res.status(500).send('<html><body><h2>Connection failed</h2><p>' + (error.response?.data?.error_description || error.message) + '</p></body></html>');
  }
});

let _managementToken = null;
let _managementTokenExpiry = null;

async function getManagementToken() {
  if (_managementToken && _managementTokenExpiry && Date.now() < _managementTokenExpiry) {
    return _managementToken;
  }
  try {
    const response = await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
      grant_type: 'client_credentials',
      client_id: AUTH0_CLIENT_ID,
      client_secret: AUTH0_CLIENT_SECRET,
      audience: `https://${AUTH0_DOMAIN}/api/v2/`
    });
    _managementToken = response.data.access_token;
    _managementTokenExpiry = Date.now() + ((response.data.expires_in - 300) * 1000);
    return _managementToken;
  } catch {
    return null;
  }
}

module.exports = router;
