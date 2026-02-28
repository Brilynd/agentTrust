// Security Utilities
// Helper functions for security operations

const crypto = require('crypto');

/**
 * Generate a secure random token
 * @param {number} length - Token length in bytes
 * @returns {string} Hex-encoded token
 */
function generateSecureToken(length = 32) {
  return crypto.randomBytes(length).toString('hex');
}

/**
 * Hash a value using SHA256
 * @param {string} value - Value to hash
 * @returns {string} Hex-encoded hash
 */
function hashValue(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

/**
 * Constant-time string comparison to prevent timing attacks
 * @param {string} a - First string
 * @param {string} b - Second string
 * @returns {boolean} True if strings are equal
 */
function secureCompare(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

/**
 * Sanitize string input to prevent injection attacks
 * @param {string} input - Input string
 * @returns {string} Sanitized string
 */
function sanitizeInput(input) {
  if (typeof input !== 'string') {
    return '';
  }
  
  return input
    .trim()
    .replace(/[<>]/g, '') // Remove angle brackets
    .substring(0, 10000); // Limit length
}

/**
 * Validate email format (basic)
 * @param {string} email - Email to validate
 * @returns {boolean} True if valid
 */
function isValidEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

/**
 * Validate domain format
 * @param {string} domain - Domain to validate
 * @returns {boolean} True if valid
 */
function isValidDomain(domain) {
  const domainRegex = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/i;
  return domainRegex.test(domain);
}

/**
 * Check if IP address is in allowed range (basic)
 * @param {string} ip - IP address
 * @param {string[]} allowedRanges - Allowed IP ranges
 * @returns {boolean} True if allowed
 */
function isIPAllowed(ip, allowedRanges = []) {
  if (allowedRanges.length === 0) {
    return true; // No restrictions
  }
  
  // Simple check - in production, use proper IP range checking library
  return allowedRanges.some(range => ip.startsWith(range));
}

module.exports = {
  generateSecureToken,
  hashValue,
  secureCompare,
  sanitizeInput,
  isValidEmail,
  isValidDomain,
  isIPAllowed
};
