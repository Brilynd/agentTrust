// Audit Service
// Handles audit log storage and retrieval

const { createHash } = require('../utils/crypto');
const { Action } = require('../models/action');
const pool = require('../config/database');

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
    type,
    domain,
    url,
    riskLevel,
    target,
    formData,
    scopes,
    stepUpRequired,
    reason
  } = actionData;
  
  // Get previous hash for this agent
  const previousHash = await getPreviousHash(agentId);
  
  // Calculate cryptographic hash
  const hash = createHash(previousHash, actionData);
  
  // Generate unique ID
  const id = `action_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  
  const loggedAction = {
    id,
    agentId,
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
    reason
  };
  
  // Store in database
  const savedAction = await Action.create(loggedAction);
  
  // Update cache
  previousHashCache.set(agentId, hash);
  
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
