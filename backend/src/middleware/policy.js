// Policy Enforcement Middleware
// Checks if action is allowed based on policies
// CRITICAL: Logs ALL actions (allowed, denied, step-up required) before responding

const { classifyRisk, checkPolicy } = require('../services/policy-engine');
const { logAction } = require('../services/audit');
const { Session } = require('../models/session');
const { createApproval } = require('../routes/approvals');

async function enforcePolicy(req, res, next) {
  try {
    const actionData = req.body;

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
    
    // Classify risk level
    const riskLevel = actionData.approvedViaStepUp ? actionData.riskLevel : await classifyRisk(actionData);
    actionData.riskLevel = riskLevel;
    
    // Check policy — skip if already approved via step-up
    const policyCheck = actionData.approvedViaStepUp
      ? { allowed: true, requiresStepUp: false, reason: 'Approved via step-up' }
      : await checkPolicy(actionData, req.agent.scopes);
    
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
      promptId: actionData.promptId || null
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
        const approval = createApproval({
          sessionId: session?.id || actionData.sessionId || null,
          actionId: loggedAction?.id || null,
          type: actionData.type,
          domain: actionData.domain,
          url: actionData.url,
          riskLevel: riskLevel,
          reason: policyCheck.reason || 'Action requires approval',
          target: actionData.target || null
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
