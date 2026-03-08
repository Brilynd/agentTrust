// Sessions Routes
// Handles session creation, ending, and queries

const express = require('express');
const router = express.Router();
const { authenticateUser, validateAction } = require('../middleware/auth');
const { Session } = require('../models/session');
const { Action } = require('../models/action');
const { Prompt } = require('../models/prompt');

// Agent explicitly creates a new session (M2M auth)
router.post('/', validateAction, async (req, res) => {
  try {
    const session = await Session.create(req.agent.id);
    res.status(201).json({ success: true, session: session.toJSON() });
  } catch (error) {
    console.error('Failed to create session:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Agent ends a session (M2M auth)
router.post('/:sessionId/end', validateAction, async (req, res) => {
  try {
    const session = await Session.findById(req.params.sessionId);
    if (!session) {
      return res.status(404).json({ success: false, error: 'Session not found' });
    }
    const ended = await session.end();
    res.json({ success: true, session: ended.toJSON() });
  } catch (error) {
    console.error('Failed to end session:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get all sessions for the authenticated user (optionally filtered by agentId)
router.get('/', authenticateUser, async (req, res) => {
  try {
    const { agentId, limit = 50 } = req.query;
    const userId = req.user.userId;
    
    // Auto-claim any unclaimed sessions for this user
    await Session.claimUnclaimedSessions(userId);
    
    let sessions;
    if (agentId && agentId !== 'all') {
      sessions = await Session.findByUserAndAgent(userId, agentId, parseInt(limit));
    } else {
      sessions = await Session.findByUser(userId, parseInt(limit));
    }
    
    const sessionsWithDetails = await Promise.all(
      sessions.map(async (session) => {
        const [actions, prompts] = await Promise.all([
          Action.findBySession(session.id),
          Prompt.findBySession(session.id)
        ]);
        return {
          ...session.toJSON(),
          prompts: prompts.map(p => p.toJSON()),
          actions: actions.map(action => ({
            id: action.id,
            agentId: action.agentId,
            type: action.type,
            timestamp: action.timestamp,
            domain: action.domain,
            url: action.url,
            riskLevel: action.riskLevel,
            status: action.status || 'allowed',
            target: action.target,
            formData: action.formData,
            reason: action.reason,
            stepUpRequired: action.stepUpRequired,
            screenshot: action.screenshot,
            promptId: action.promptId || null
          }))
        };
      })
    );
    
    res.json({
      success: true,
      sessions: sessionsWithDetails,
      count: sessionsWithDetails.length
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
    
    // Only allow users to see their own sessions
    if (session.userId && session.userId !== req.user.userId) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }
    
    const [actions, prompts] = await Promise.all([
      Action.findBySession(sessionId),
      Prompt.findBySession(sessionId)
    ]);
    
    res.json({
      success: true,
      session: {
        ...session.toJSON(),
        prompts: prompts.map(p => p.toJSON()),
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
          stepUpRequired: action.stepUpRequired,
          screenshot: action.screenshot,
          promptId: action.promptId || null
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
