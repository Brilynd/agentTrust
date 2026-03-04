// Policy Engine Service
// Risk classification and policy enforcement

const fs = require('fs').promises;
const path = require('path');

let policies = null;

async function loadPolicies() {
  if (policies) return policies;
  
  try {
    const policyPath = path.join(__dirname, '../../config/policies.json');
    const data = await fs.readFile(policyPath, 'utf8');
    policies = JSON.parse(data);
    return policies;
  } catch (error) {
    // Return default policies if file doesn't exist
    return getDefaultPolicies();
  }
}

function getDefaultPolicies() {
  return {
    allowed_domains: [],
    blocked_domains: [],
    high_risk_keywords: ['delete', 'remove', 'merge', 'transfer', 'confirm'],
    medium_risk_keywords: ['submit', 'post', 'send'],
    financial_domains: ['bank', 'paypal', 'stripe', 'venmo'],
    requires_step_up: ['high'],
    domain_trust_profiles: {}
  };
}

async function classifyRisk(actionData) {
  const policies = await loadPolicies();
  const { type, domain, url, target, form } = actionData;
  
  let riskScore = 0;
  
  if (policies.blocked_domains.some(blocked => domain && domain.includes(blocked))) {
    return 'blocked';
  }
  
  if (policies.financial_domains.some(fin => domain && domain.includes(fin))) {
    riskScore += 3;
  }
  
  // Build a searchable text blob from ALL available context
  const targetText = (target?.text || '').toLowerCase();
  const targetClass = (target?.className || '').toLowerCase();
  const targetId = (target?.id || '').toLowerCase();
  const targetAriaLabel = (target?.aria_label || '').toLowerCase();
  const urlLower = (url || '').toLowerCase();
  const domainLower = (domain || '').toLowerCase();
  
  const allText = `${targetText} ${targetClass} ${targetId} ${targetAriaLabel} ${urlLower}`;
  
  // High risk: keywords in element text, URL path, or element attributes
  const highRiskUrlPatterns = [
    '/delete', '/remove', '/destroy', '/settings/admin',
    '/transfer', '/merge', '/close', '/deactivate'
  ];
  
  if (policies.high_risk_keywords.some(keyword => allText.includes(keyword))) {
    riskScore += 3;
  }
  if (highRiskUrlPatterns.some(pattern => urlLower.includes(pattern))) {
    riskScore += 3;
  }
  
  // Medium risk keywords
  if (policies.medium_risk_keywords.some(keyword => allText.includes(keyword))) {
    riskScore += 1;
  }
  
  // Form-submit type actions on sensitive domains get extra score
  if (type === 'form_submit') {
    riskScore += 1;
  }
  
  // Check form fields for passwords
  if (form) {
    const fields = form.fields || form;
    if (typeof fields === 'object') {
      const hasPassword = Object.values(fields).some(
        field => field && (field.type === 'password' && field.hasValue)
      );
      if (hasPassword) {
        riskScore += 2;
      }
    }
  }
  
  if (riskScore >= 3) return 'high';
  if (riskScore >= 1) return 'medium';
  return 'low';
}

async function checkPolicy(actionData, agentScopes) {
  const policies = await loadPolicies();
  const riskLevel = actionData.riskLevel || await classifyRisk(actionData);
  
  // Check if domain is blocked
  if (policies.blocked_domains.some(blocked => actionData.domain.includes(blocked))) {
    return {
      allowed: false,
      reason: 'Domain is blocked by policy'
    };
  }
  
  // Check if domain is allowed (if allowlist exists)
  if (policies.allowed_domains.length > 0) {
    const isAllowed = policies.allowed_domains.some(allowed => 
      actionData.domain.includes(allowed)
    );
    if (!isAllowed) {
      return {
        allowed: false,
        reason: 'Domain not in allowed list'
      };
    }
  }
  
  // Check if step-up is required
  if (policies.requires_step_up.includes(riskLevel)) {
    const hasHighRiskScope = agentScopes.includes('browser.high_risk');
    
    if (!hasHighRiskScope) {
      return {
        allowed: false,
        requiresStepUp: true,
        reason: 'High-risk action requires step-up authentication'
      };
    }
  }
  
  // Check scope requirements
  if (actionData.type === 'form_submit' && !agentScopes.includes('browser.form.submit')) {
    return {
      allowed: false,
      reason: 'Insufficient scope: browser.form.submit required'
    };
  }
  
  return {
    allowed: true
  };
}

async function getPolicies() {
  return await loadPolicies();
}

async function updatePolicies(newPolicies) {
  policies = { ...policies, ...newPolicies };
  
  // Save to file
  const policyPath = path.join(__dirname, '../../config/policies.json');
  await fs.writeFile(policyPath, JSON.stringify(policies, null, 2));
}

module.exports = {
  classifyRisk,
  checkPolicy,
  getPolicies,
  updatePolicies
};
