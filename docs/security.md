# AgentTrust Security Documentation

## Overview

AgentTrust implements multiple layers of security to protect the API and ensure safe agent operations. This document outlines all security measures, configurations, and best practices.

---

## 🔐 Authentication & Authorization

### JWT Token Validation

All API endpoints (except `/api/auth/validate` and `/health`) require JWT authentication via Auth0.

**Token Format**:
```
Authorization: Bearer <JWT_TOKEN>
```

**Validation Process**:
1. Token extracted from `Authorization` header
2. Token validated against Auth0 JWKS (JSON Web Key Set)
3. Token signature verified using RS256 algorithm
4. Token audience and issuer validated
5. Token expiration checked
6. Agent identity and scopes extracted

**Code Location**: `backend/src/middleware/auth.js`, `backend/src/services/auth0.js`

### Token Caching

Valid tokens are cached to improve performance:
- **Cache TTL**: Configurable via `TOKEN_CACHE_TTL` (default: 3600 seconds)
- **Cache Key**: First 50 characters of token
- **Automatic Expiration**: Cache entries expire with token or TTL, whichever comes first

### Scoped Access Control

Three-tier scope system:
- `browser.basic`: Read-only and low-risk navigation
- `browser.form.submit`: Form submissions and medium-risk actions
- `browser.high_risk`: Deletions, transfers, financial actions (requires step-up)

**Usage**:
```javascript
const { requireScope } = require('../middleware/auth');
router.post('/sensitive-action', validateAction, requireScope('browser.high_risk'), handler);
```

---

## 🛡️ Security Middleware

### Helmet.js

Sets security HTTP headers:
- `Content-Security-Policy`: Prevents XSS attacks
- `X-Content-Type-Options`: Prevents MIME type sniffing
- `X-Frame-Options`: Prevents clickjacking
- `X-XSS-Protection`: Additional XSS protection
- Removes `X-Powered-By` header

**Configuration**: `backend/src/server.js`

### CORS (Cross-Origin Resource Sharing)

Configured to allow specific origins:
- **Development**: `http://localhost:3000`
- **Production**: Configurable via `CORS_ORIGIN` environment variable
- **Chrome Extensions**: Allowed via `chrome-extension://*`

**Configuration**: `backend/src/server.js` → `corsOptions`

### Rate Limiting

Prevents abuse and DDoS attacks:
- **Window**: 15 minutes (configurable via `RATE_LIMIT_WINDOW_MS`)
- **Max Requests**: 100 per window (configurable via `RATE_LIMIT_MAX_REQUESTS`)
- **Scope**: Per IP address
- **Headers**: Returns rate limit info in `RateLimit-*` headers

**Configuration**: `backend/src/server.js` → `limiter`

### Input Sanitization

**NoSQL Injection Prevention**:
- Uses `express-mongo-sanitize` to sanitize request data
- Removes `$` and `.` operators from user input

**HTTP Parameter Pollution Prevention**:
- Uses `hpp` (HTTP Parameter Pollution) middleware
- Prevents duplicate parameter attacks

**Custom Input Validation**:
- SQL injection pattern detection
- XSS pattern detection
- Input length limits

**Code Location**: `backend/src/middleware/security.js`

---

## 🔒 Data Protection

### Request Size Limits

- **JSON Body**: 10MB limit
- **URL Encoded**: 10MB limit

Prevents memory exhaustion attacks.

### Data Sanitization

All user input is sanitized:
- String trimming
- HTML tag removal
- Length limits
- Type validation

**Code Location**: `backend/src/utils/security.js`

### Cryptographic Hashing

Action chain uses SHA256 for tamper-evidence:
- Each action hash includes previous hash
- Ensures chain integrity
- Prevents historical modification

**Code Location**: `backend/src/utils/crypto.js`

---

## 🚨 Security Headers

Custom security headers added:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Request-ID`: For request tracking

**Code Location**: `backend/src/middleware/security.js` → `securityHeaders`

---

## 📝 Logging & Monitoring

### Request Logging

**Development**: Morgan `dev` format
**Production**: Morgan `combined` format

Logs include:
- Request method and path
- Response status
- Response time
- IP address

### Security Event Logging

The following events are logged:
- Failed authentication attempts
- Token validation failures
- Step-up token requests
- Potential injection attempts
- Rate limit violations

**Log Format**:
```javascript
{
  event: 'AUTH_FAILED',
  ip: '192.168.1.1',
  path: '/api/actions',
  error: 'Invalid token',
  timestamp: '2026-03-15T10:30:00Z'
}
```

---

## 🔑 Environment Variables

### Required Variables

```bash
# Auth0 Configuration
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_CLIENT_ID=your-client-id
AUTH0_CLIENT_SECRET=your-client-secret
AUTH0_AUDIENCE=your-api-identifier

# Security Configuration
RATE_LIMIT_WINDOW_MS=900000        # 15 minutes
RATE_LIMIT_MAX_REQUESTS=100
CORS_ORIGIN=http://localhost:3000
TOKEN_CACHE_TTL=3600              # 1 hour
```

### Security Best Practices

1. **Never commit `.env` file** - Use `.env.example` as template
2. **Use strong secrets** - Generate random strings for `JWT_SECRET`
3. **Rotate credentials** - Regularly update Auth0 secrets
4. **Limit CORS origins** - Only allow necessary origins in production
5. **Monitor logs** - Watch for suspicious activity

---

## 🧪 Security Testing

### Manual Testing

1. **Token Validation**:
   ```bash
   # Valid token
   curl -H "Authorization: Bearer <valid_token>" http://localhost:3000/api/actions
   
   # Invalid token
   curl -H "Authorization: Bearer invalid" http://localhost:3000/api/actions
   
   # Missing token
   curl http://localhost:3000/api/actions
   ```

2. **Rate Limiting**:
   ```bash
   # Send 101 requests quickly
   for i in {1..101}; do curl http://localhost:3000/api/actions; done
   ```

3. **Input Validation**:
   ```bash
   # SQL injection attempt
   curl -X POST http://localhost:3000/api/actions \
     -H "Content-Type: application/json" \
     -d '{"type": "SELECT * FROM users"}'
   ```

### Automated Testing

Add security tests to `backend/tests/`:
- Token validation tests
- Rate limiting tests
- Input sanitization tests
- CORS tests

---

## 🚀 Production Deployment

### Security Checklist

- [ ] All environment variables set
- [ ] `NODE_ENV=production` set
- [ ] CORS origins restricted
- [ ] Rate limits configured appropriately
- [ ] HTTPS enabled (use reverse proxy)
- [ ] Database credentials secured
- [ ] Auth0 credentials rotated
- [ ] Logging configured
- [ ] Monitoring enabled
- [ ] Backup strategy in place

### Recommended Infrastructure

1. **Reverse Proxy** (nginx/traefik):
   - SSL/TLS termination
   - Additional rate limiting
   - DDoS protection

2. **Firewall**:
   - Restrict access to necessary ports
   - IP whitelisting if needed

3. **Monitoring**:
   - Failed authentication attempts
   - Rate limit violations
   - Unusual traffic patterns
   - Error rates

4. **Backup**:
   - Regular database backups
   - Encrypted backups
   - Off-site storage

---

## 🔄 Security Updates

### Regular Maintenance

1. **Dependencies**: Run `npm audit` regularly
2. **Auth0**: Keep Auth0 SDK updated
3. **Node.js**: Keep Node.js version updated
4. **Security Patches**: Apply security patches promptly

### Vulnerability Reporting

If you discover a security vulnerability:
1. Do not open a public issue
2. Contact the maintainers privately
3. Provide detailed information
4. Allow time for fix before disclosure

---

## 📚 Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Auth0 Security Best Practices](https://auth0.com/docs/security)
- [Express Security Best Practices](https://expressjs.com/en/advanced/best-practice-security.html)
- [Node.js Security Checklist](https://blog.risingstack.com/node-js-security-checklist/)

---

## 🎯 Security Goals

AgentTrust aims to achieve:

1. **Confidentiality**: All sensitive data encrypted in transit
2. **Integrity**: Cryptographic action chains prevent tampering
3. **Availability**: Rate limiting and monitoring prevent DoS
4. **Authentication**: Strong JWT validation via Auth0
5. **Authorization**: Scoped access control
6. **Non-repudiation**: Complete audit trail with agent identity
7. **Accountability**: All actions logged with context

---

**Last Updated**: March 2026
