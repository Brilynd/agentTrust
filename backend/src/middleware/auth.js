// Authentication Middleware
// Validates JWT tokens from Auth0

const { validateToken } = require('../services/auth0');

/**
 * Middleware to validate JWT tokens from Auth0
 * Attaches agent information to request object
 */
async function validateAction(req, res, next) {
  try {
    // Check for Authorization header
    const authHeader = req.headers.authorization;
    
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        error: 'Authorization header required',
        code: 'MISSING_AUTH_HEADER'
      });
    }
    
    // Validate Bearer token format
    if (!authHeader.startsWith('Bearer ')) {
      return res.status(401).json({
        success: false,
        error: 'Invalid authorization format. Expected: Bearer <token>',
        code: 'INVALID_AUTH_FORMAT'
      });
    }
    
    // Extract token
    const token = authHeader.substring(7).trim();
    
    if (!token) {
      return res.status(401).json({
        success: false,
        error: 'Token is required',
        code: 'MISSING_TOKEN'
      });
    }
    
    // Validate token
    const validation = await validateToken(token);
    
    if (!validation.valid) {
      // Log security events
      console.warn('Token validation failed:', {
        error: validation.error,
        code: validation.code,
        ip: req.ip,
        path: req.path
      });
      
      return res.status(401).json({
        success: false,
        error: validation.error || 'Invalid token',
        code: validation.code || 'INVALID_TOKEN'
      });
    }
    
    // Attach agent info to request
    req.agent = {
      id: validation.sub,
      scopes: validation.scopes || [],
      tokenExp: validation.exp,
      tokenIat: validation.iat
    };
    
    // Log successful authentication (in development)
    if (process.env.NODE_ENV === 'development') {
      console.log('Authenticated agent:', {
        id: validation.sub,
        scopes: validation.scopes,
        path: req.path
      });
    }
    
    next();
  } catch (error) {
    console.error('Auth middleware error:', error);
    res.status(500).json({
      success: false,
      error: 'Authentication service error',
      code: 'AUTH_SERVICE_ERROR'
    });
  }
}

/**
 * Middleware to check if agent has required scope
 * @param {string|string[]} requiredScopes - Required scope(s)
 */
function requireScope(requiredScopes) {
  const scopes = Array.isArray(requiredScopes) ? requiredScopes : [requiredScopes];
  
  return (req, res, next) => {
    if (!req.agent) {
      return res.status(401).json({
        success: false,
        error: 'Authentication required',
        code: 'NOT_AUTHENTICATED'
      });
    }
    
    const agentScopes = req.agent.scopes || [];
    const hasScope = scopes.some(scope => agentScopes.includes(scope));
    
    if (!hasScope) {
      return res.status(403).json({
        success: false,
        error: `Insufficient permissions. Required scope(s): ${scopes.join(', ')}`,
        code: 'INSUFFICIENT_SCOPE',
        required: scopes,
        current: agentScopes
      });
    }
    
    next();
  };
}

/**
 * Optional authentication - doesn't fail if no token, but validates if present
 */
async function optionalAuth(req, res, next) {
  const authHeader = req.headers.authorization;
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    // No token provided, continue without authentication
    return next();
  }
  
  // Token provided, validate it
  try {
    const token = authHeader.substring(7).trim();
    const validation = await validateToken(token);
    
    if (validation.valid) {
      req.agent = {
        id: validation.sub,
        scopes: validation.scopes || [],
        tokenExp: validation.exp,
        tokenIat: validation.iat
      };
    }
    // If invalid, continue without agent info (optional auth)
    
    next();
  } catch (error) {
    // On error, continue without authentication
    next();
  }
}

module.exports = { 
  validateAction, 
  requireScope,
  optionalAuth 
};
