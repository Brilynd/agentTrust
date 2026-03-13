// Audit Service
// Handles audit log storage and retrieval

const { createHash } = require('../utils/crypto');
const { Action } = require('../models/action');
const pool = require('../config/database');
const { cwLog } = require('./cloudwatch');
const { uploadScreenshotToS3 } = require('./screenshot-storage');

// Cache for previous hash (for chain continuity)
let previousHashCache = new Map();

async function getPreviousHash(agentId) {
  // Get the most recent action's hash for this agent
  const query = `
    SELECT hash FROM actions 
    WHERE agent_id = $1 
    ORDER BY timestamp DESC 
    LIMIT 1
  `;
  const result = await pool.query(query, [agentId]);
  
  if (result.rows.length > 0) {
    return result.rows[0].hash;
  }
  
  // If no previous action, check cache or return '0'
  return previousHashCache.get(agentId) || '0';
}

async function logAction(actionData) {
  const {
    agentId,
    sessionId,
    type,
    domain,
    url,
    riskLevel,
    target,
    formData,
    scopes,
    stepUpRequired,
    reason,
    status,
    screenshot,
    promptId,
    parentActionId,
    subOrder
  } = actionData;
  
  const previousHash = await getPreviousHash(agentId);
  const hash = createHash(previousHash, actionData);
  const id = `action_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  let screenshotPayload = {
    screenshot: screenshot || null,
    screenshotS3Key: null
  };

  if (screenshot) {
    try {
      screenshotPayload = await uploadScreenshotToS3({
        screenshot,
        agentId,
        actionId: id,
        timestamp: actionData.timestamp || new Date().toISOString()
      });
    } catch (uploadErr) {
      console.error('Failed to upload screenshot to S3, falling back to DB storage:', uploadErr.message);
      screenshotPayload = { screenshot, screenshotS3Key: null };
    }
  }
  
  const loggedAction = {
    id,
    agentId,
    sessionId: sessionId || null,
    type,
    timestamp: actionData.timestamp || new Date().toISOString(),
    domain,
    url,
    riskLevel,
    hash,
    previousHash,
    target,
    formData,
    scopes,
    stepUpRequired,
    reason,
    status: status || 'allowed',
    screenshot: screenshotPayload.screenshot,
    screenshotS3Key: screenshotPayload.screenshotS3Key,
    promptId: promptId || null,
    parentActionId: parentActionId || null,
    subOrder: subOrder != null ? subOrder : null
  };
  
  const savedAction = await Action.create(loggedAction);
  previousHashCache.set(agentId, hash);

  // Send to CloudWatch (fire-and-forget)
  cwLog.action({
    id,
    agentId,
    sessionId: sessionId || null,
    type,
    domain,
    url,
    riskLevel,
    status: status || 'allowed',
    reason,
    hash
  });

  return savedAction;
}

async function getActionChain(agentId, limit = 100) {
  // Query from database
  const filters = { limit };
  if (agentId) {
    filters.agentId = agentId;
  }
  
  const actions = await Action.findAll(filters);
  
  // Convert to plain objects for API response
  return actions.map(action => ({
    id: action.id,
    agentId: action.agentId,
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
    createdAt: action.createdAt
  }));
}

async function getAgentAuditLog(agentId, filters = {}) {
  // Query from database with filters
  const dbFilters = {
    ...filters,
    agentId
  };
  
  const actions = await Action.findByAgent(agentId, dbFilters);
  
  // Convert to plain objects for API response
  return actions.map(action => ({
    id: action.id,
    agentId: action.agentId,
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
    createdAt: action.createdAt
  }));
}

module.exports = {
  logAction,
  getActionChain,
  getAgentAuditLog
};
