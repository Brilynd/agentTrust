// Sessions Routes
// Handles session queries for authenticated users

const express = require('express');
const router = express.Router();
const { authenticateUser } = require('../middleware/auth');
const { Session } = require('../models/session');
const { Action } = require('../models/action');

// Get all sessions (optionally filtered by agentId)
router.get('/', authenticateUser, async (req, res) => {
  try {
    const { agentId, limit = 50 } = req.query;
    
    const sessions = (agentId && agentId !== 'all')
      ? await Session.findByAgent(agentId, parseInt(limit))
      : await Session.findAll(parseInt(limit));
    
    // Get action counts for each session
    const sessionsWithActions = await Promise.all(
      sessions.map(async (session) => {
        const actions = await Action.findBySession(session.id);
        return {
          ...session.toJSON(),
          actions: actions.map(action => ({
            id: action.id,
            type: action.type,
            timestamp: action.timestamp,
            domain: action.domain,
            url: action.url,
            riskLevel: action.riskLevel,
            status: action.status,
            screenshot: action.screenshot
          }))
        };
      })
    );
    
    res.json({
      success: true,
      sessions: sessionsWithActions,
      count: sessionsWithActions.length
    });
  } catch (error) {
    console.error('Failed to query sessions:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Get a specific session with all actions
router.get('/:sessionId', authenticateUser, async (req, res) => {
  try {
    const { sessionId } = req.params;
    
    const session = await Session.findById(sessionId);
    
    if (!session) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }
    
    const actions = await Action.findBySession(sessionId);
    
    res.json({
      success: true,
      session: {
        ...session.toJSON(),
        actions: actions.map(action => ({
          id: action.id,
          type: action.type,
          timestamp: action.timestamp,
          domain: action.domain,
          url: action.url,
          riskLevel: action.riskLevel,
          status: action.status,
          target: action.target,
          formData: action.formData,
          reason: action.reason,
          screenshot: action.screenshot
        }))
      }
    });
  } catch (error) {
    console.error('Failed to get session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

module.exports = router;
