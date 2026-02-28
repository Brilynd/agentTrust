// Audit Routes
// Handles audit log queries and cryptographic chain verification

const express = require('express');
const router = express.Router();
const { validateAction } = require('../middleware/auth');
const { getActionChain, getAgentAuditLog } = require('../services/audit');

// Get cryptographic action chain
router.get('/chain', validateAction, async (req, res) => {
  try {
    const { agentId, limit = 100 } = req.query;
    
    const chain = await getActionChain(agentId, limit);
    
    res.json({
      success: true,
      chain
    });
  } catch (error) {
    console.error('Failed to get action chain:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Get agent-specific audit log
router.get('/agent/:agentId', validateAction, async (req, res) => {
  try {
    const { agentId } = req.params;
    const { startDate, endDate, riskLevel, domain } = req.query;
    
    const auditLog = await getAgentAuditLog(agentId, {
      startDate,
      endDate,
      riskLevel,
      domain
    });
    
    res.json({
      success: true,
      auditLog
    });
  } catch (error) {
    console.error('Failed to get agent audit log:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

module.exports = router;
