// Actions Routes
// Handles action logging and validation

const express = require('express');
const router = express.Router();
const { validateAction } = require('../middleware/auth');
const { enforcePolicy } = require('../middleware/policy');
const { logAction } = require('../services/audit');

// Log an action
router.post('/', validateAction, enforcePolicy, async (req, res) => {
  try {
    const actionData = {
      ...req.body,
      agentId: req.agent.id,
      timestamp: new Date().toISOString()
    };
    
    // Log action to database
    const loggedAction = await logAction(actionData);
    
    res.status(201).json({
      success: true,
      action: loggedAction
    });
  } catch (error) {
    console.error('Failed to log action:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Query audit log
router.get('/', validateAction, async (req, res) => {
  try {
    const { agentId, domain, riskLevel, startDate, endDate, limit = 100 } = req.query;
    
    // TODO: Implement audit log query
    const actions = [];
    
    res.json({
      success: true,
      actions,
      count: actions.length
    });
  } catch (error) {
    console.error('Failed to query actions:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

module.exports = router;
