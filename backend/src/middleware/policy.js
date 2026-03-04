// Policy Enforcement Middleware
// Checks if action is allowed based on policies
// CRITICAL: Logs ALL actions (allowed, denied, step-up required) before responding

const { classifyRisk, checkPolicy } = require('../services/policy-engine');
const { logAction } = require('../services/audit');
const { Session } = require('../models/session');

async function enforcePolicy(req, res, next) {
  try {
    const actionData = req.body;
    
    // Classify risk level
    const riskLevel = await classifyRisk(actionData);
    actionData.riskLevel = riskLevel;
    
    // Check policy
    const policyCheck = await checkPolicy(actionData, req.agent.scopes);
    
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
      reason: policyCheck.reason || (policyCheck.allowed ? null : 'Action denied by policy'),
      agentId: req.agent.id,
      sessionId: session?.id || null,
      timestamp: actionData.timestamp || new Date().toISOString(),
      riskLevel: riskLevel,
      status: policyCheck.allowed ? 'allowed' : (policyCheck.requiresStepUp ? 'step_up_required' : 'denied'),
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
    
    // If action is not allowed, return error but action is already logged
    if (!policyCheck.allowed) {
      return res.status(403).json({
        success: false,
        error: policyCheck.reason || 'Action not allowed by policy',
        requiresStepUp: policyCheck.requiresStepUp,
        riskLevel: riskLevel,
        actionId: loggedAction?.id, // Include action ID so it can be tracked
        status: policyCheck.requiresStepUp ? 'step_up_required' : 'denied'
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
