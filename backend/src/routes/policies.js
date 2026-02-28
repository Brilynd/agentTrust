// Policies Routes
// Handles policy management

const express = require('express');
const router = express.Router();
const { validateAction } = require('../middleware/auth');
const { getPolicies, updatePolicies } = require('../services/policy-engine');

// Get current policies
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

// Update policies
router.put('/', validateAction, async (req, res) => {
  try {
    // TODO: Add authorization check (only admins can update policies)
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

module.exports = router;
