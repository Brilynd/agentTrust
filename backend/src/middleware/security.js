// Security Middleware
// Additional security measures for the API

/**
 * Validate request origin (basic check)
 */
function validateOrigin(req, res, next) {
  const origin = req.headers.origin;
  const allowedOrigins = process.env.CORS_ORIGIN?.split(',') || [];
  
  // Allow same-origin requests
  if (!origin || origin === req.headers.host) {
    return next();
  }
  
  // In production, you might want stricter origin checking
  if (process.env.NODE_ENV === 'production' && allowedOrigins.length > 0) {
    if (!allowedOrigins.includes(origin)) {
      return res.status(403).json({
        success: false,
        error: 'Origin not allowed'
      });
    }
  }
  
  next();
}

/**
 * Request ID middleware for tracking
 */
function requestId(req, res, next) {
  req.id = req.headers['x-request-id'] || 
           `req_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  res.setHeader('X-Request-ID', req.id);
  next();
}

/**
 * Security headers middleware
 */
function securityHeaders(req, res, next) {
  // Add custom security headers
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  
  // Remove server header (if not already removed by helmet)
  res.removeHeader('X-Powered-By');
  
  next();
}

/**
 * Input validation middleware
 * Validates common input patterns
 */
function validateInput(req, res, next) {
  // Check for suspicious patterns in request body
  if (req.body) {
    const bodyStr = JSON.stringify(req.body);
    
    // Basic SQL injection pattern detection
    const sqlPatterns = [
      /(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b)/i,
      /('|\\'|;|--|\/\*|\*\/|\+|\%)/i
    ];
    
    // Basic XSS pattern detection
    const xssPatterns = [
      /<script[^>]*>.*?<\/script>/gi,
      /javascript:/gi,
      /on\w+\s*=/gi
    ];
    
    // Check for SQL patterns
    if (sqlPatterns.some(pattern => pattern.test(bodyStr))) {
      console.warn('Potential SQL injection attempt detected:', {
        ip: req.ip,
        path: req.path,
        requestId: req.id
      });
      return res.status(400).json({
        success: false,
        error: 'Invalid input detected'
      });
    }
    
    // Check for XSS patterns
    if (xssPatterns.some(pattern => pattern.test(bodyStr))) {
      console.warn('Potential XSS attempt detected:', {
        ip: req.ip,
        path: req.path,
        requestId: req.id
      });
      return res.status(400).json({
        success: false,
        error: 'Invalid input detected'
      });
    }
  }
  
  next();
}

module.exports = {
  validateOrigin,
  requestId,
  securityHeaders,
  validateInput
};
