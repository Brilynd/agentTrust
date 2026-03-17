// Policy Engine Service
// Risk classification and policy enforcement

const fs = require('fs').promises;
const path = require('path');

let policies = null;
let policiesLoadedAt = 0;
const POLICY_CACHE_TTL_MS = 5000;

const DEFAULT_PROMPT_INJECTION_PATTERNS = [
  'ignore\\s+(all|any|previous|prior)\\s+instructions',
  'disregard\\s+(all|any|previous|prior)\\s+instructions',
  'system\\s+prompt',
  'developer\\s+message',
  'jailbreak',
  'bypass\\s+(safety|guardrails|policy)',
  'disable\\s+(security|safety|guardrails|policy)',
  'reveal|leak|exfiltrate.*(token|secret|password|api\\s*key)',
  '(curl|wget|powershell|cmd\\.exe|bash|rm\\s+-rf|del\\s+/f|Invoke-WebRequest)'
];

const DEFAULT_MALICIOUS_TERMS = [
  'credential dump',
  'session hijack',
  'token theft',
  'download and execute',
  'remote command execution',
  'data exfiltration'
];

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
    domain_trust_profiles: {},
    impact_keywords: ['send', 'email', 'message', 'compose', 'reply', 'forward',
      'publish', 'comment', 'invite', 'create issue', 'new message', 'post'],
    content_actions: ['/mail/send', '/messages/new', '/issues/new', '/compose',
      '/send', '/comments', '/events', '/publish', '/invite'],
    prompt_injection_patterns: DEFAULT_PROMPT_INJECTION_PATTERNS,
    malicious_terms: DEFAULT_MALICIOUS_TERMS,
    max_untrusted_text_chars: 12000,
    untrusted_content_action: 'step_up_or_block'
  };
}

function _coerceStringArray(values, fallback) {
  if (!Array.isArray(values)) return fallback;
  const cleaned = values
    .filter(v => typeof v === 'string')
    .map(v => v.trim())
    .filter(Boolean);
  return cleaned.length > 0 ? cleaned : fallback;
}

function _normalizeUntrustedAction(action) {
  const normalized = String(action || '').toLowerCase();
  if (['allow', 'step_up', 'block', 'step_up_or_block'].includes(normalized)) {
    return normalized;
  }
  return 'step_up_or_block';
}

function evaluateUntrustedContent(text, policyOverride = null) {
  const sourcePolicies = policyOverride || policies || getDefaultPolicies();
  const patternSources = _coerceStringArray(
    sourcePolicies.prompt_injection_patterns,
    DEFAULT_PROMPT_INJECTION_PATTERNS
  );
  const maliciousTerms = _coerceStringArray(
    sourcePolicies.malicious_terms,
    DEFAULT_MALICIOUS_TERMS
  );
  const maxChars = Number(sourcePolicies.max_untrusted_text_chars) > 0
    ? Number(sourcePolicies.max_untrusted_text_chars)
    : 12000;
  const action = _normalizeUntrustedAction(sourcePolicies.untrusted_content_action);

  const content = String(text || '').slice(0, maxChars);
  if (!content.trim()) {
    return {
      flagged: false,
      matches: [],
      riskLevel: 'low',
      action: 'allow',
      reason: null,
      scannedChars: 0
    };
  }

  const matches = [];

  for (const source of patternSources) {
    try {
      const regex = new RegExp(source, 'i');
      if (regex.test(content)) {
        matches.push(`pattern:${source}`);
      }
    } catch (error) {
      // Ignore malformed regex from policy config to avoid runtime policy outage.
    }
  }

  const lowerContent = content.toLowerCase();
  for (const term of maliciousTerms) {
    if (lowerContent.includes(term.toLowerCase())) {
      matches.push(`term:${term}`);
    }
  }

  if (matches.length === 0) {
    return {
      flagged: false,
      matches: [],
      riskLevel: 'low',
      action: 'allow',
      reason: null,
      scannedChars: content.length
    };
  }

  return {
    flagged: true,
    matches,
    riskLevel: 'high',
    action,
    reason: 'Potential prompt injection or malicious instruction detected in untrusted content',
    scannedChars: content.length
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

  // Impact-aware keywords: content-sending actions (send email, post comment, etc.)
  // should be treated as at least medium risk regardless of HTTP method
  const impactKeywords = policies.impact_keywords || [];
  if (impactKeywords.some(kw => allText.includes(kw))) {
    riskScore += 2;
  }

  // Content-action URL patterns: always require approval
  const contentActions = policies.content_actions || [];
  if (contentActions.some(pattern => urlLower.includes(pattern))) {
    riskScore += 3;
  }
  
  // Form-submit type actions on sensitive domains get extra score
  if (type === 'form_submit') {
    riskScore += 1;
  }

  // Clicks on form control elements (buttons, submit inputs, selects, divs with role="button")
  // get elevated risk since they can trigger state changes
  const FORM_CONTROL_TAGS = ['button', 'select', 'option', 'input'];
  const FORM_ACTION_TEXT = ['submit', 'save', 'confirm', 'apply', 'continue',
    'next', 'proceed', 'agree', 'accept', 'authorize', 'sign in','send', 'send money', 'send payment',
    'log in', 'login', 'register', 'sign up', 'checkout', 'place order'];
  if (type === 'click') {
    const tagLower = (target?.tagName || '').toLowerCase();
    const roleAttr = (target?.role || target?.ariaRole || '').toLowerCase();
    if (FORM_CONTROL_TAGS.includes(tagLower) || roleAttr === 'button') {
      riskScore += 1;
    }
    if (FORM_ACTION_TEXT.some(ft => targetText.includes(ft))) {
      riskScore += 1;
    }
  }

  // Email/messaging domains: sending content on these should always be high risk
  const EMAIL_DOMAINS = ['mail.google.com', 'gmail.com', 'outlook.com', 'outlook.live.com',
    'mail.yahoo.com', 'mail.live.com', 'protonmail.com'];
  if (type === 'click' || type === 'form_submit') {
    if (EMAIL_DOMAINS.some(ed => domainLower.includes(ed))) {
      if (FORM_ACTION_TEXT.some(ft => targetText.includes(ft)) ||
          contentActions.some(pattern => urlLower.includes(pattern))) {
        riskScore += 2;
      }
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
  
  // Check if step-up is required based on risk level.
  // High-risk actions ALWAYS require human approval — the M2M token's
  // scopes cannot self-approve dangerous actions.
  if (policies.requires_step_up.includes(riskLevel)) {
    return {
      allowed: false,
      requiresStepUp: true,
      reason: `${riskLevel}-risk action requires user approval`
    };
  }
  
  // Check scope requirements — offer step-up approval instead of flat denial.
  // This applies to form_submit AND clicks on form control elements
  // (buttons, submit inputs, divs with role="button") that could trigger state changes.
  const tagLower = (actionData.target?.tagName || '').toLowerCase();
  const roleAttr = (actionData.target?.role || actionData.target?.ariaRole || '').toLowerCase();
  const isFormControl = actionData.type === 'click' &&
    (['button', 'select', 'input'].includes(tagLower) || roleAttr === 'button');
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
  evaluateUntrustedContent,
  getPolicies,
  updatePolicies
};
