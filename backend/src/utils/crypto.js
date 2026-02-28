// Cryptographic Utilities
// Handles cryptographic hashing for action chain

const crypto = require('crypto');

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
  verifyChain
};
