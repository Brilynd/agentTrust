// Policies Routes
// Handles policy management for both M2M (agent) and user (extension) auth

const express = require('express');
const router = express.Router();
const { validateAction, authenticateUser } = require('../middleware/auth');
const { getPolicies, updatePolicies } = require('../services/policy-engine');

// Get current policies (M2M auth - agent)
router.get('/', validateAction, async (req, res) => {
  try {
    const policies = await getPolicies();
    res.json({
      success: true,
      policies
    });
  } catch (error) {
    console.error('Failed to get policies:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Update policies (M2M auth - agent)
router.put('/', validateAction, async (req, res) => {
  try {
    const { policies } = req.body;
    await updatePolicies(policies);
    res.json({
      success: true,
      message: 'Policies updated successfully'
    });
  } catch (error) {
    console.error('Failed to update policies:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Get current policies (user auth - extension)
router.get('/user', authenticateUser, async (req, res) => {
  try {
    const policies = await getPolicies();
    res.json({
      success: true,
      policies
    });
  } catch (error) {
    console.error('Failed to get policies:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Update policies (user auth - extension)
router.put('/user', authenticateUser, async (req, res) => {
  try {
    const { policies } = req.body;

    if (!policies || typeof policies !== 'object') {
      return res.status(400).json({
        success: false,
        error: 'policies object is required'
      });
    }

    await updatePolicies(policies);
    res.json({
      success: true,
      message: 'Policies updated successfully'
    });
  } catch (error) {
    console.error('Failed to update policies:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

module.exports = router;
