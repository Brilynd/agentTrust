// Auth0 Service
// Handles Auth0 token validation and management

const jwt = require('jsonwebtoken');
const jwksClient = require('jwks-rsa');

// Validate environment variables
if (!process.env.AUTH0_DOMAIN) {
  throw new Error('AUTH0_DOMAIN environment variable is required');
}
if (!process.env.AUTH0_AUDIENCE) {
  throw new Error('AUTH0_AUDIENCE environment variable is required');
}

// Initialize JWKS client with caching
const client = jwksClient({
  jwksUri: `https://${process.env.AUTH0_DOMAIN}/.well-known/jwks.json`,
  cache: true,
  cacheMaxEntries: 5,
  cacheMaxAge: 600000, // 10 minutes
  rateLimit: true,
  jwksRequestsPerMinute: 10
});

// Token cache to avoid repeated validations
const tokenCache = new Map();
const CACHE_TTL = parseInt(process.env.TOKEN_CACHE_TTL) || 3600; // 1 hour default

function getKey(header, callback) {
  client.getSigningKey(header.kid, (err, key) => {
    if (err) {
      console.error('Error getting signing key:', err);
      return callback(err);
    }
    const signingKey = key.publicKey || key.rsaPublicKey;
    callback(null, signingKey);
  });
}

/**
 * Validate JWT token from Auth0
 * @param {string} token - JWT token to validate
 * @returns {Promise<Object>} Validation result with agent info
 */
async function validateToken(token) {
  // Check cache first
  const cacheKey = token.substring(0, 50); // Use first 50 chars as cache key
  const cached = tokenCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.result;
  }

  return new Promise((resolve) => {
    jwt.verify(
      token,
      getKey,
      {
        audience: process.env.AUTH0_AUDIENCE,
        issuer: `https://${process.env.AUTH0_DOMAIN}/`,
        algorithms: ['RS256'],
        complete: false
      },
      (err, decoded) => {
        if (err) {
          const result = {
            valid: false,
            error: err.message,
            code: err.name
          };
          resolve(result);
          return;
        }

        // Validate token expiration
        const now = Math.floor(Date.now() / 1000);
        if (decoded.exp && decoded.exp < now) {
          const result = {
            valid: false,
            error: 'Token has expired',
            code: 'TokenExpiredError'
          };
          resolve(result);
          return;
        }

        // Extract scopes
        const scopes = decoded.scope 
          ? decoded.scope.split(' ').filter(s => s.trim())
          : [];

        const result = {
          valid: true,
          sub: decoded.sub,
          scopes: scopes,
          exp: decoded.exp,
          iat: decoded.iat,
          aud: decoded.aud,
          iss: decoded.iss
        };

        // Cache valid token
        if (decoded.exp) {
          const expiresAt = Math.min(
            decoded.exp * 1000, // Token expiration
            Date.now() + (CACHE_TTL * 1000) // Cache TTL
          );
          tokenCache.set(cacheKey, { result, expiresAt });
        }

        resolve(result);
      }
    );
  });
}

/**
 * Clear token cache (useful for testing or forced refresh)
 */
function clearTokenCache() {
  tokenCache.clear();
}

/**
 * Get cache statistics
 */
function getCacheStats() {
  return {
    size: tokenCache.size,
    maxSize: 1000 // Arbitrary limit
  };
}

module.exports = { 
  validateToken, 
  clearTokenCache,
  getCacheStats 
};
