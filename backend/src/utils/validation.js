// Validation Utilities
// Input validation helpers

function validateActionData(actionData) {
  const required = ['type', 'timestamp', 'domain', 'url'];
  const missing = required.filter(field => !actionData[field]);
  
  if (missing.length > 0) {
    throw new Error(`Missing required fields: ${missing.join(', ')}`);
  }
  
  const validTypes = ['click', 'form_submit', 'navigation'];
  if (!validTypes.includes(actionData.type)) {
    throw new Error(`Invalid action type: ${actionData.type}`);
  }
  
  return true;
}

function validatePolicy(policy) {
  if (typeof policy !== 'object') {
    throw new Error('Policy must be an object');
  }
  
  // Validate structure
  const validKeys = [
    'allowed_domains',
    'blocked_domains',
    'high_risk_keywords',
    'medium_risk_keywords',
    'financial_domains',
    'requires_step_up',
    'domain_trust_profiles'
  ];
  
  for (const key in policy) {
    if (!validKeys.includes(key)) {
      throw new Error(`Invalid policy key: ${key}`);
    }
  }
  
  return true;
}

module.exports = {
  validateActionData,
  validatePolicy
};
