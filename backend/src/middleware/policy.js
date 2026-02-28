// Policy Enforcement Middleware
// Checks if action is allowed based on policies

const { classifyRisk, checkPolicy } = require('../services/policy-engine');

async function enforcePolicy(req, res, next) {
  try {
    const actionData = req.body;
    
    // Classify risk level
    const riskLevel = await classifyRisk(actionData);
    actionData.riskLevel = riskLevel;
    
    // Check policy
    const policyCheck = await checkPolicy(actionData, req.agent.scopes);
    
    if (!policyCheck.allowed) {
      return res.status(403).json({
        success: false,
        error: policyCheck.reason || 'Action not allowed by policy',
        requiresStepUp: policyCheck.requiresStepUp,
        riskLevel
      });
    }
    
    // Attach policy check result to request
    req.policyCheck = policyCheck;
    req.actionData = actionData;
    
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
