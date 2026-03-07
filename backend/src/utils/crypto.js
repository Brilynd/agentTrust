// Cryptographic Utilities
// Handles hashing for audit chain + AES-256-GCM encryption for sensitive fields

const crypto = require('crypto');

const AES_ALGORITHM = 'aes-256-gcm';

function _getEncryptionKey() {
  const hex = process.env.CREDENTIAL_ENCRYPTION_KEY;
  if (hex && hex.length >= 64) {
    return Buffer.from(hex, 'hex');
  }
  const secret = process.env.JWT_SECRET || 'agenttrust-default-credential-key';
  return crypto.createHash('sha256').update(secret).digest();
}

function encryptJSON(obj) {
  if (obj == null) return { encrypted: null, iv: null };
  const key = _getEncryptionKey();
  const plaintext = typeof obj === 'string' ? obj : JSON.stringify(obj);
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv(AES_ALGORITHM, key, iv);
  let enc = cipher.update(plaintext, 'utf8', 'hex');
  enc += cipher.final('hex');
  const tag = cipher.getAuthTag().toString('hex');
  return { encrypted: enc + ':' + tag, iv: iv.toString('hex') };
}

function decryptJSON(encryptedStr, ivHex) {
  if (!encryptedStr || !ivHex) return null;
  try {
    const key = _getEncryptionKey();
    const [enc, tag] = encryptedStr.split(':');
    const iv = Buffer.from(ivHex, 'hex');
    const decipher = crypto.createDecipheriv(AES_ALGORITHM, key, iv);
    decipher.setAuthTag(Buffer.from(tag, 'hex'));
    let dec = decipher.update(enc, 'hex', 'utf8');
    dec += decipher.final('utf8');
    try { return JSON.parse(dec); } catch { return dec; }
  } catch {
    return null;
  }
}

function createHash(previousHash, actionData) {
  const payload = JSON.stringify({
    previousHash,
    agentId: actionData.agentId,
    type: actionData.type,
    timestamp: actionData.timestamp,
    domain: actionData.domain,
    url: actionData.url,
    riskLevel: actionData.riskLevel
  });
  
  return crypto
    .createHash('sha256')
    .update(payload)
    .digest('hex');
}

function verifyChain(chain) {
  for (let i = 1; i < chain.length; i++) {
    const current = chain[i];
    const previous = chain[i - 1];
    
    const expectedHash = createHash(previous.hash, current);
    
    if (current.hash !== expectedHash) {
      return {
        valid: false,
        invalidIndex: i,
        reason: 'Hash mismatch'
      };
    }
  }
  
  return { valid: true };
}

module.exports = {
  createHash,
  verifyChain,
  encryptJSON,
  decryptJSON,
  _getEncryptionKey
};
