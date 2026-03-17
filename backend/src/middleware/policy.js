// Policy Enforcement Middleware
// Checks if action is allowed based on policies
// CRITICAL: Logs ALL actions (allowed, denied, step-up required) before responding

const { classifyRisk, checkPolicy, evaluateUntrustedContent, getPolicies } = require('../services/policy-engine');
const { logAction } = require('../services/audit');
const { Session } = require('../models/session');
const { createApproval } = require('../routes/approvals');

const PREVIEW_SENSITIVE_KEYS = new Set(['password', 'passwd', 'secret', 'token', 'credit_card', 'cvv', 'ssn']);

function _buildActionPreview(actionData) {
  const formData = actionData.form?.fields || actionData.formData || actionData.form;
  if (!formData || typeof formData !== 'object') return null;

  const preview = {};
  const entries = Object.entries(formData);
  for (const [key, val] of entries.slice(0, 10)) {
    if (PREVIEW_SENSITIVE_KEYS.has(key.toLowerCase())) {
      preview[key] = '***';
    } else if (typeof val === 'string') {
      preview[key] = val.length > 200 ? val.substring(0, 200) + '...' : val;
    } else if (val && typeof val === 'object' && val.value) {
      preview[key] = PREVIEW_SENSITIVE_KEYS.has(key.toLowerCase()) ? '***' : String(val.value).substring(0, 200);
    } else {
      preview[key] = val;
    }
  }
  if (entries.length > 10) preview['...'] = `${entries.length - 10} more fields`;
  return preview;
}

function _buildActionImpactSummary(actionData) {
  const type = actionData.type;
  const domain = actionData.domain || '';
  const urlLower = (actionData.url || '').toLowerCase();
  const targetText = (actionData.target?.text || '').toLowerCase();

  if (type === 'form_submit') {
    if (urlLower.includes('/send') || urlLower.includes('/compose') || targetText.includes('send'))
      return `Send message on ${domain}`;
    if (urlLower.includes('/comment') || targetText.includes('comment'))
      return `Post comment on ${domain}`;
    if (urlLower.includes('/issue') || urlLower.includes('/new'))
      return `Create new item on ${domain}`;
    return `Submit form on ${domain}`;
  }
  if (type === 'click') {
    const text = actionData.target?.text || 'button';
    return `Click "${String(text).substring(0, 40)}" on ${domain}`;
  }
  return `${type} on ${domain}`;
}

function _collectUntrustedText(actionData) {
  const chunks = [];

  const addChunk = (value) => {
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (trimmed) chunks.push(trimmed);
    }
  };

  addChunk(actionData.untrustedContent);
  addChunk(actionData.pageText);
  addChunk(actionData.url);
  addChunk(actionData.target?.text);
  addChunk(actionData.target?.aria_label);
  addChunk(actionData.target?.placeholder);

  const formData = actionData.form?.fields || actionData.formData || actionData.form;
  if (formData && typeof formData === 'object') {
    for (const value of Object.values(formData)) {
      if (typeof value === 'string') {
        addChunk(value);
      } else if (value && typeof value === 'object') {
        addChunk(value.value);
        addChunk(value.text);
        addChunk(value.label);
      }
    }
  }

  return chunks.join('\n');
}

async function enforcePolicy(req, res, next) {
  try {
    const actionData = req.body;
    const policies = await getPolicies();

    // If the agent is retrying with an approved approvalId, verify and allow
    if (actionData.approvalId) {
      const approvalsModule = require('../routes/approvals');
      const pendingApprovals = approvalsModule.__pendingApprovals;
      if (pendingApprovals) {
        const approval = pendingApprovals.get(actionData.approvalId);
        if (approval && approval.status === 'approved') {
          actionData.riskLevel = approval.riskLevel || 'high';
          actionData.approvedViaStepUp = true;
        }
      }
    }
    
    // Analyze untrusted text from page/context before any action execution.
    const untrustedText = _collectUntrustedText(actionData);
    const untrustedCheck = evaluateUntrustedContent(untrustedText, policies);

    // Classify risk level
    const riskLevel = actionData.approvedViaStepUp
      ? actionData.riskLevel
      : (untrustedCheck.flagged ? 'high' : await classifyRisk(actionData));
    actionData.riskLevel = riskLevel;

    if (untrustedCheck.flagged) {
      actionData.securityDetection = {
        type: 'prompt_injection',
        matches: untrustedCheck.matches,
        scannedChars: untrustedCheck.scannedChars
      };
    }
    
    // Check policy — skip if already approved via step-up
    let policyCheck;
    if (actionData.approvedViaStepUp) {
      policyCheck = { allowed: true, requiresStepUp: false, reason: 'Approved via step-up' };
    } else if (untrustedCheck.flagged) {
      const shouldBlock = untrustedCheck.action === 'block';
      policyCheck = {
        allowed: false,
        requiresStepUp: !shouldBlock,
        reason: shouldBlock
          ? 'Blocked: untrusted content includes prompt-injection or malicious command patterns'
          : 'Untrusted content appears malicious — user approval required',
      };
    } else {
      policyCheck = await checkPolicy(actionData, req.agent.scopes);
    }
    
    // Use explicit sessionId from agent, or fall back to auto-detect
    let session;
    try {
      if (actionData.sessionId) {
        session = await Session.findById(actionData.sessionId);
      }
      if (!session) {
        session = await Session.getOrCreateActiveSession(req.agent.id);
      }
      await session.incrementActionCount();
    } catch (sessionError) {
      console.error('Failed to get/create session (continuing anyway):', sessionError);
    }
    
    // Determine the logged status — distinguish manual overrides
    let logStatus;
    if (actionData.approvedViaStepUp) {
      logStatus = 'approved_override';
    } else if (policyCheck.allowed) {
      logStatus = 'allowed';
    } else if (policyCheck.requiresStepUp) {
      logStatus = 'step_up_required';
    } else {
      logStatus = 'denied';
    }

    // CRITICAL: Log action BEFORE responding (whether allowed or denied)
    // This ensures all actions are logged in the browser extension
    const logData = {
      type: actionData.type,
      url: actionData.url,
      domain: actionData.domain,
      target: actionData.target || null,
      formData: actionData.form?.fields || actionData.formData || actionData.form || null,
      scopes: req.agent.scopes || [],
      stepUpRequired: policyCheck.requiresStepUp || false,
      reason: actionData.approvedViaStepUp
        ? 'Manually approved by user (elevated permissions)'
        : (policyCheck.reason || (policyCheck.allowed ? null : 'Action denied by policy')),
      agentId: req.agent.id,
      sessionId: session?.id || null,
      timestamp: actionData.timestamp || new Date().toISOString(),
      riskLevel: riskLevel,
      status: logStatus,
      screenshot: actionData.screenshot || null,
      promptId: actionData.promptId || null,
      securityDetection: actionData.securityDetection || null
    };
    
    // Log action to database (even if denied)
    let loggedAction;
    try {
      loggedAction = await logAction(logData);
    } catch (logError) {
      console.error('Failed to log action (continuing anyway):', logError);
      // Continue even if logging fails - don't block the response
    }
    
    // If action is denied, create an approval request so the user can override
    if (!policyCheck.allowed) {
      const isBlockedDomain = policyCheck.reason && policyCheck.reason.includes('blocked by policy');

      if (!isBlockedDomain) {
        const preview = _buildActionPreview(actionData);
        const impactSummary = _buildActionImpactSummary(actionData);

        const approval = createApproval({
          sessionId: session?.id || actionData.sessionId || null,
          actionId: loggedAction?.id || null,
          type: actionData.type,
          domain: actionData.domain,
          url: actionData.url,
          riskLevel: riskLevel,
          reason: policyCheck.reason || 'Action requires approval',
          target: actionData.target || null,
          preview,
          impactSummary
        });

        return res.status(403).json({
          success: false,
          error: policyCheck.reason || 'Action requires user approval',
          requiresStepUp: true,
          riskLevel: riskLevel,
          actionId: loggedAction?.id,
          approvalId: approval.id,
          status: 'step_up_required'
        });
      }

      // Blocked domains are flat-denied without approval option
      return res.status(403).json({
        success: false,
        error: policyCheck.reason || 'Action not allowed by policy',
        requiresStepUp: false,
        riskLevel: riskLevel,
        actionId: loggedAction?.id,
        status: 'denied'
      });
    }
    
    // Attach policy check result and logged action to request
    req.policyCheck = policyCheck;
    req.actionData = actionData;
    req.loggedAction = loggedAction;
    
    next();
  } catch (error) {
    console.error('Policy enforcement error:', error);
    res.status(500).json({
      success: false,
      error: 'Policy check failed'
    });
  }
}

module.exports = { enforcePolicy };
