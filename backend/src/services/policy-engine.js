// Policy Engine Service
// Risk classification and policy enforcement

const fs = require('fs').promises;
const path = require('path');

let policies = null;
let policiesLoadedAt = 0;
const POLICY_CACHE_TTL_MS = 5000;

async function loadPolicies() {
  if (policies && (Date.now() - policiesLoadedAt) < POLICY_CACHE_TTL_MS) {
    return policies;
  }
  
  try {
    const policyPath = path.join(__dirname, '../../config/policies.json');
    const data = await fs.readFile(policyPath, 'utf8');
    policies = JSON.parse(data);
    policiesLoadedAt = Date.now();
    return policies;
  } catch (error) {
    return getDefaultPolicies();
  }
}

function getDefaultPolicies() {
  return {
    allowed_domains: [],
    blocked_domains: [],
    high_risk_keywords: ['delete', 'remove', 'merge', 'transfer', 'confirm',
      'account', 'profile', 'settings', 'password', 'billing',
      'payment', 'security', 'deactivate', 'disable'],
    medium_risk_keywords: ['submit', 'post', 'send', 'update', 'edit'],
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
    '/transfer', '/merge', '/close', '/deactivate',
    '/account', '/profile', '/settings', '/security',
    '/billing', '/payment', '/password', '/preferences',
    '/admin', '/manage',
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

  // Clicks on form control elements (buttons, submit inputs, selects)
  // get elevated risk since they can trigger state changes
  const FORM_CONTROL_TAGS = ['button', 'select', 'option', 'input'];
  const FORM_ACTION_TEXT = ['submit', 'save', 'confirm', 'apply', 'continue',
    'next', 'proceed', 'agree', 'accept', 'authorize', 'sign in','send', 'send money', 'send payment',
    'log in', 'login', 'register', 'sign up', 'checkout', 'place order'];
  if (type === 'click') {
    const tagLower = (target?.tagName || '').toLowerCase();
    if (FORM_CONTROL_TAGS.includes(tagLower)) {
      riskScore += 1;
    }
    if (FORM_ACTION_TEXT.some(ft => targetText.includes(ft))) {
      riskScore += 1;
    }
  }

  // Form input — typing into fields. Sensitive fields (password, card)
  // get higher risk; plain text inputs stay low.
  if (type === 'form_input') {
    if (target?.is_sensitive) {
      riskScore += 2;  // e.g. password field on a financial domain → high
    }
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
        requiresStepUp: true,
        reason: 'Domain not in allowed list — requires user approval'
      };
    }
  }
  
  // Check if step-up is required based on risk level
  if (policies.requires_step_up.includes(riskLevel)) {
    const hasHighRiskScope = agentScopes.includes('browser.high_risk');
    
    if (!hasHighRiskScope) {
      return {
        allowed: false,
        requiresStepUp: true,
        reason: `${riskLevel}-risk action requires user approval`
      };
    }
  }
  
  // Check scope requirements — offer step-up approval instead of flat denial.
  // This applies to form_submit AND clicks on form control elements
  // (buttons, submit inputs) that could trigger state changes.
  const isFormControl = actionData.type === 'click' &&
    ['button', 'select', 'input'].includes((actionData.target?.tagName || '').toLowerCase());
  if ((actionData.type === 'form_submit' || isFormControl) &&
      !agentScopes.includes('browser.form.submit')) {
    return {
      allowed: false,
      requiresStepUp: true,
      reason: 'Form interaction requires user approval'
    };
  }

  // Sensitive form inputs (password, card fields) require approval if on
  // a financial domain or if the scope is missing
  if (actionData.type === 'form_input' && actionData.target?.is_sensitive) {
    if (policies.financial_domains.some(fin => actionData.domain && actionData.domain.includes(fin))) {
      if (!agentScopes.includes('browser.form.submit')) {
        return {
          allowed: false,
          requiresStepUp: true,
          reason: 'Sensitive input on financial site requires user approval'
        };
      }
    }
  }
  
  return {
    allowed: true
  };
}

async function getPolicies() {
  return await loadPolicies();
}

async function updatePolicies(newPolicies) {
  const current = await loadPolicies();
  policies = { ...current, ...newPolicies };
  policiesLoadedAt = Date.now();
  
  const policyPath = path.join(__dirname, '../../config/policies.json');
  await fs.writeFile(policyPath, JSON.stringify(policies, null, 2));
}

module.exports = {
  classifyRisk,
  checkPolicy,
  getPolicies,
  updatePolicies
};
