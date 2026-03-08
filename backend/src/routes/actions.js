// Actions Routes
// Handles action logging and validation

const express = require('express');
const router = express.Router();
const { validateAction } = require('../middleware/auth');
const { enforcePolicy } = require('../middleware/policy');

function sanitizeFormData(fd) {
  if (!fd || typeof fd !== 'object') return fd;
  const out = { ...fd };
  if (out.fields && typeof out.fields === 'object') {
    const safe = { ...out.fields };
    if (safe.password) safe.password = '***';
    if (safe.username) safe.username = safe.username.substring(0, 3) + '***';
    out.fields = safe;
  }
  return out;
}

// Log an action
// NOTE: The enforcePolicy middleware already logs the action to the database
// (for both allowed and denied actions). We reuse that logged action here
// instead of creating a duplicate.
router.post('/', validateAction, enforcePolicy, async (req, res) => {
  try {
    const loggedAction = req.loggedAction;
    
    if (!loggedAction) {
      return res.status(500).json({ success: false, error: 'Action was not logged by policy middleware' });
    }
    
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
    const { agentId, domain, riskLevel, type, startDate, endDate, limit = 100 } = req.query;
    const userId = req.user.userId;
    
    const { Action } = require('../models/action');
    const { Session } = require('../models/session');
    
    // Get sessions belonging to this user (includes unclaimed sessions)
    const userSessions = await Session.findByUser(userId, 1000);
    const userSessionIds = userSessions.map(s => s.id);
    
    const filters = {
      limit: parseInt(limit),
      sessionIds: userSessionIds
    };
    
    if (agentId) {
      filters.agentId = agentId;
    }
    if (type) {
      filters.type = type;
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
      formData: sanitizeFormData(action.formData),
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
      formData: sanitizeFormData(action.formData),
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

// Log an action from the extension (user auth) — used for error/failed
// actions that the agent couldn't log via M2M because the API call itself failed.
router.post('/extension-log', require('../middleware/auth').authenticateUser, async (req, res) => {
  try {
    const { type, url, domain, status, target, formData, timestamp } = req.body;
    if (!type || !url) {
      return res.status(400).json({ success: false, error: 'type and url are required' });
    }

    const { logAction } = require('../services/audit');
    const { Session } = require('../models/session');

    // Try to attach to an active session (use a generic agent id)
    const agentId = req.body.agentId || 'extension-captured';
    let session;
    try { session = await Session.getOrCreateActiveSession(agentId); } catch { /* ignore */ }

    const logged = await logAction({
      agentId,
      sessionId: session?.id || null,
      type,
      url,
      domain: domain || new URL(url).hostname,
      target: target || null,
      formData: formData || null,
      riskLevel: req.body.riskLevel || 'unknown',
      status: status || 'error',
      reason: req.body.reason || req.body.message || null,
      scopes: [],
      stepUpRequired: false,
      timestamp: timestamp || new Date().toISOString()
    });

    res.status(201).json({ success: true, action: { id: logged.id } });
  } catch (error) {
    console.error('Failed to log extension action:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;
