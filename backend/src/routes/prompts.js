const express = require('express');
const router = express.Router();
const { validateAction, authenticateUser } = require('../middleware/auth');
const { Prompt } = require('../models/prompt');
const { Session } = require('../models/session');

// Agent stores a prompt (called by the Python agent)
router.post('/', validateAction, async (req, res) => {
  try {
    const { content, response, sessionId } = req.body;

    if (!content) {
      return res.status(400).json({ success: false, error: 'Prompt content is required' });
    }

    // Resolve session: use provided sessionId or get/create active session
    let resolvedSessionId = sessionId;
    if (!resolvedSessionId) {
      try {
        const session = await Session.getOrCreateActiveSession(req.agent.id);
        resolvedSessionId = session.id;
      } catch (e) {
        // continue without session
      }
    }

    const prompt = await Prompt.create({
      agentId: req.agent.id,
      sessionId: resolvedSessionId,
      content,
      response: response || null
    });

    res.status(201).json({ success: true, prompt: prompt.toJSON() });
  } catch (error) {
    console.error('Failed to store prompt:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Agent updates a prompt with its response and/or progress
router.patch('/:promptId', validateAction, async (req, res) => {
  try {
    const { response, progress } = req.body;
    if (!response && !progress) {
      return res.status(400).json({ success: false, error: 'response or progress is required' });
    }

    let updated;
    if (response) {
      updated = await Prompt.updateResponse(req.params.promptId, response);
    }
    if (progress) {
      updated = await Prompt.updateProgress(req.params.promptId, progress);
    }

    if (!updated) {
      return res.status(404).json({ success: false, error: 'Prompt not found' });
    }

    res.json({ success: true, prompt: updated.toJSON() });
  } catch (error) {
    console.error('Failed to update prompt:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Extension fetches prompts for a session (user auth)
router.get('/session/:sessionId', authenticateUser, async (req, res) => {
  try {
    const prompts = await Prompt.findBySession(req.params.sessionId);
    res.json({ success: true, prompts: prompts.map(p => p.toJSON()) });
  } catch (error) {
    console.error('Failed to fetch prompts:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;
