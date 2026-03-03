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
    // Normalize action data format
    const actionData = {
      type: req.body.type,
      url: req.body.url,
      domain: req.body.domain,
      target: req.body.target || null,
      formData: req.body.form?.fields || req.body.formData || req.body.form || null,
      scopes: req.agent.scopes || [],
      stepUpRequired: req.policyCheck?.requiresStepUp || false,
      reason: req.body.reason || null,
      agentId: req.agent.id,
      timestamp: req.body.timestamp || new Date().toISOString(),
      riskLevel: req.policyCheck?.riskLevel || req.body.riskLevel || null,
      screenshot: req.body.screenshot || null // Screenshot from agent or extension
    };
    
    // Log action to database
    const loggedAction = await logAction(actionData);
    
    res.status(201).json({
      success: true,
      action: {
        id: loggedAction.id,
        agentId: loggedAction.agentId,
        type: loggedAction.type,
        timestamp: loggedAction.timestamp,
        domain: loggedAction.domain,
        url: loggedAction.url,
        riskLevel: loggedAction.riskLevel,
        hash: loggedAction.hash,
        previousHash: loggedAction.previousHash,
        target: loggedAction.target,
        formData: loggedAction.formData,
        scopes: loggedAction.scopes,
        stepUpRequired: loggedAction.stepUpRequired,
        reason: loggedAction.reason,
        createdAt: loggedAction.createdAt
      }
    });
  } catch (error) {
    console.error('Failed to log action:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Query audit log (for authenticated users - browser extension)
router.get('/user', require('../middleware/auth').authenticateUser, async (req, res) => {
  try {
    const { agentId, domain, riskLevel, startDate, endDate, limit = 100 } = req.query;
    
    const { Action } = require('../models/action');
    
    const filters = {
      limit: parseInt(limit)
    };
    
    if (agentId) {
      filters.agentId = agentId;
    }
    if (domain) {
      filters.domain = domain;
    }
    if (riskLevel) {
      filters.riskLevel = riskLevel;
    }
    if (startDate) {
      filters.startDate = startDate;
    }
    if (endDate) {
      filters.endDate = endDate;
    }
    
    const actions = await Action.findAll(filters);
    
    // Convert to API format
    const formattedActions = actions.map(action => ({
      id: action.id,
      agentId: action.agentId,
      sessionId: action.sessionId,
      type: action.type,
      timestamp: action.timestamp,
      domain: action.domain,
      url: action.url,
      riskLevel: action.riskLevel,
      hash: action.hash,
      previousHash: action.previousHash,
      target: action.target,
      formData: action.formData,
      scopes: action.scopes,
      stepUpRequired: action.stepUpRequired,
      reason: action.reason,
      status: action.status || 'allowed',
      screenshot: action.screenshot,
      createdAt: action.createdAt
    }));
    
    res.json({
      success: true,
      actions: formattedActions,
      count: formattedActions.length
    });
  } catch (error) {
    console.error('Failed to query actions:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Query audit log (for agents - existing endpoint)
router.get('/', validateAction, async (req, res) => {
  try {
    const { agentId, domain, riskLevel, startDate, endDate, limit = 100 } = req.query;
    
    const { Action } = require('../models/action');
    
    const filters = {
      limit: parseInt(limit)
    };
    
    if (agentId) {
      filters.agentId = agentId;
    }
    if (domain) {
      filters.domain = domain;
    }
    if (riskLevel) {
      filters.riskLevel = riskLevel;
    }
    if (startDate) {
      filters.startDate = startDate;
    }
    if (endDate) {
      filters.endDate = endDate;
    }
    
    const actions = await Action.findAll(filters);
    
    // Convert to API format
    const formattedActions = actions.map(action => ({
      id: action.id,
      agentId: action.agentId,
      sessionId: action.sessionId,
      type: action.type,
      timestamp: action.timestamp,
      domain: action.domain,
      url: action.url,
      riskLevel: action.riskLevel,
      hash: action.hash,
      previousHash: action.previousHash,
      target: action.target,
      formData: action.formData,
      scopes: action.scopes,
      stepUpRequired: action.stepUpRequired,
      reason: action.reason,
      status: action.status || 'allowed',
      screenshot: action.screenshot,
      createdAt: action.createdAt
    }));
    
    res.json({
      success: true,
      actions: formattedActions,
      count: formattedActions.length
    });
  } catch (error) {
    console.error('Failed to query actions:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Update action screenshot (for agents to add screenshot after action)
router.patch('/:actionId', validateAction, async (req, res) => {
  try {
    const { actionId } = req.params;
    const { screenshot } = req.body;
    
    if (!screenshot) {
      return res.status(400).json({
        success: false,
        error: 'Screenshot is required'
      });
    }
    
    const { Action } = require('../models/action');
    const action = await Action.findById(actionId);
    
    if (!action) {
      return res.status(404).json({
        success: false,
        error: 'Action not found'
      });
    }
    
    // Verify action belongs to this agent
    if (action.agentId !== req.agent.id) {
      return res.status(403).json({
        success: false,
        error: 'Not authorized to update this action'
      });
    }
    
    // Update screenshot in database
    const pool = require('../config/database');
    await pool.query(
      'UPDATE actions SET screenshot = $1 WHERE id = $2',
      [screenshot, actionId]
    );
    
    res.json({
      success: true,
      message: 'Screenshot updated'
    });
  } catch (error) {
    console.error('Failed to update screenshot:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

module.exports = router;
