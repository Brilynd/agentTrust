// Authentication Routes
// Handles JWT validation and step-up token exchange

const express = require('express');
const router = express.Router();
const { validateToken } = require('../services/auth0');
const { exchangeForStepUpToken } = require('../services/token-exchange');
const { validateAction } = require('../middleware/auth');

// Validate JWT token
router.post('/validate', async (req, res) => {
  try {
    const { token } = req.body;
    
    if (!token) {
      return res.status(400).json({
        success: false,
        error: 'Token is required'
      });
    }
    
    const validation = await validateToken(token);
    
    res.json({
      success: true,
      ...validation
    });
  } catch (error) {
    console.error('Token validation failed:', error);
    res.status(401).json({
      success: false,
      error: error.message || 'Invalid token'
    });
  }
});

// Request step-up token (requires authentication)
router.post('/stepup', validateAction, async (req, res) => {
  try {
    const { action, reason } = req.body;
    
    // Validate input
    if (!action) {
      return res.status(400).json({
        success: false,
        error: 'Action is required'
      });
    }
    
    if (!reason || typeof reason !== 'string' || reason.trim().length < 10) {
      return res.status(400).json({
        success: false,
        error: 'Reason is required and must be at least 10 characters'
      });
    }
    
    // Get current token from header
    const authHeader = req.headers.authorization;
    const currentToken = authHeader.substring(7);
    
    // Exchange for step-up token
    const stepUpToken = await exchangeForStepUpToken(currentToken, action, reason, req.agent.id);
    
    // Log step-up event
    console.log('Step-up token issued:', {
      agentId: req.agent.id,
      action: action.type,
      domain: action.domain,
      requestId: req.id
    });
    
    res.json({
      success: true,
      token: stepUpToken.token,
      expiresIn: stepUpToken.expiresIn,
      scopes: stepUpToken.scopes,
      issuedAt: stepUpToken.issuedAt
    });
  } catch (error) {
    console.error('Step-up token exchange failed:', error);
    res.status(500).json({
      success: false,
      error: error.message || 'Failed to obtain step-up token',
      code: 'STEPUP_ERROR'
    });
  }
});

module.exports = router;
