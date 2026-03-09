const express = require('express');
const router = express.Router();
const axios = require('axios').default || require('axios');
const pool = require('../config/database');
const { authenticateUser, validateAction } = require('../middleware/auth');

const AUTH0_DOMAIN = process.env.AUTH0_DOMAIN;
const AUTH0_CLIENT_ID = process.env.AUTH0_CLIENT_ID;
const AUTH0_CLIENT_SECRET = process.env.AUTH0_CLIENT_SECRET;
const AUTH0_AUDIENCE = process.env.AUTH0_AUDIENCE;

function isTokenVaultConfigured() {
  return !!(AUTH0_DOMAIN && AUTH0_CLIENT_ID && AUTH0_CLIENT_SECRET);
}

const PROVIDER_SCOPES = {
  'github': 'repo read:user user:email',
  'google-oauth2': 'https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile',
};

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
      subject_token_type: 'urn:ietf:params:oauth:token-type:access_token',
      requested_token_type: 'http://auth0.com/oauth/token-type/federated-connection-access-token',
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

  try {
    const result = await pool.query(
      'SELECT provider, connected_at FROM user_connections WHERE user_id = $1',
      [req.user.userId]
    );
    const connections = result.rows.map(r => ({
      provider: r.provider,
      connectedAt: r.connected_at
    }));
    return res.json({ success: true, connections, configured: true });
  } catch (err) {
    console.error('Failed to load connections:', err);
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

  const extraScopes = PROVIDER_SCOPES[provider] || '';
  const scope = ['openid', 'profile', 'email', 'offline_access', extraScopes].filter(Boolean).join(' ');

  const redirectUri = process.env.AUTH0_CALLBACK_URL || 'http://localhost:3000/api/token-vault/callback';
  const authorizeUrl = `https://${AUTH0_DOMAIN}/authorize?` + new URLSearchParams({
    response_type: 'code',
    client_id: AUTH0_CLIENT_ID,
    redirect_uri: redirectUri,
    connection: provider,
    audience: AUTH0_AUDIENCE,
    scope,
    state: JSON.stringify({ provider, userId: req.user.userId })
  }).toString();

  res.json({ success: true, authorizeUrl });
});

// OAuth callback (handles redirect after user authorizes)
router.get('/callback', async (req, res) => {
  console.log('OAuth callback received:', JSON.stringify(req.query));
  const { code, state, error, error_description } = req.query;
  if (error) {
    console.error('OAuth callback error from Auth0:', error, error_description);
    return res.status(400).send(`<html><body><h2>Authorization Error</h2><p><b>${error}</b>: ${error_description || 'Unknown error'}</p></body></html>`);
  }
  if (!code) {
    return res.status(400).send('Missing authorization code. Query params: ' + JSON.stringify(req.query));
  }

  try {
    const stateData = state ? JSON.parse(state) : {};
    const redirectUri = process.env.AUTH0_CALLBACK_URL || 'http://localhost:3000/api/token-vault/callback';

    const tokenResponse = await axios.post(`https://${AUTH0_DOMAIN}/oauth/token`, {
      grant_type: 'authorization_code',
      client_id: AUTH0_CLIENT_ID,
      client_secret: AUTH0_CLIENT_SECRET,
      code,
      redirect_uri: redirectUri
    });

    const { access_token, refresh_token } = tokenResponse.data;
    const { provider, userId } = stateData;

    if (provider && userId) {
      await pool.query(
        `INSERT INTO user_connections (user_id, provider, auth0_access_token, auth0_refresh_token, connected_at)
         VALUES ($1, $2, $3, $4, NOW())
         ON CONFLICT (user_id, provider)
         DO UPDATE SET auth0_access_token = $3, auth0_refresh_token = $4, connected_at = NOW()`,
        [userId, provider, access_token || null, refresh_token || null]
      );
      console.log(`Token Vault: stored ${provider} connection for user ${userId}`);
    }

    res.send('<html><body><h2>Connected successfully!</h2><p>You can close this tab.</p><script>window.close()</script></body></html>');
  } catch (err) {
    console.error('OAuth callback error:', err.response?.data || err.message);
    res.status(500).send('<html><body><h2>Connection failed</h2><p>' + (err.response?.data?.error_description || err.message) + '</p></body></html>');
  }
});

// Disconnect a provider (user auth)
router.delete('/connections/:provider', authenticateUser, async (req, res) => {
  const { provider } = req.params;
  try {
    await pool.query(
      'DELETE FROM user_connections WHERE user_id = $1 AND provider = $2',
      [req.user.userId, provider]
    );
    res.json({ success: true });
  } catch (err) {
    console.error('Failed to disconnect provider:', err);
    res.status(500).json({ success: false, error: 'Failed to disconnect' });
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

/**
 * Look up the stored Auth0 access token for a given user + provider.
 * Used by external-api.js to auto-supply a user token for Token Vault exchanges.
 */
async function getStoredUserToken(userId, provider) {
  try {
    const result = await pool.query(
      'SELECT auth0_access_token FROM user_connections WHERE user_id = $1 AND provider = $2',
      [userId, provider]
    );
    if (result.rows.length > 0) {
      return result.rows[0].auth0_access_token;
    }
  } catch (err) {
    console.error('Failed to look up stored user token:', err);
  }
  return null;
}

module.exports = router;
module.exports.getStoredUserToken = getStoredUserToken;