// Audit Service
// Handles audit log storage and retrieval

const { createHash } = require('../utils/crypto');
const { Action } = require('../models/action');

let actionChain = [];
let previousHash = '0';

async function logAction(actionData) {
  // Calculate cryptographic hash
  const hash = createHash(previousHash, actionData);
  
  const loggedAction = {
    ...actionData,
    hash,
    previousHash,
    id: `action_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  };
  
  // Update chain
  previousHash = hash;
  actionChain.push(loggedAction);
  
  // TODO: Store in database
  // await Action.create(loggedAction);
  
  return loggedAction;
}

async function getActionChain(agentId, limit = 100) {
  // TODO: Query from database
  // For now, return in-memory chain
  let chain = actionChain;
  
  if (agentId) {
    chain = chain.filter(action => action.agentId === agentId);
  }
  
  return chain.slice(-limit);
}

async function getAgentAuditLog(agentId, filters = {}) {
  // TODO: Implement database query with filters
  let actions = actionChain.filter(action => action.agentId === agentId);
  
  if (filters.startDate) {
    actions = actions.filter(action => action.timestamp >= filters.startDate);
  }
  
  if (filters.endDate) {
    actions = actions.filter(action => action.timestamp <= filters.endDate);
  }
  
  if (filters.riskLevel) {
    actions = actions.filter(action => action.riskLevel === filters.riskLevel);
  }
  
  if (filters.domain) {
    actions = actions.filter(action => action.domain === filters.domain);
  }
  
  return actions;
}

module.exports = {
  logAction,
  getActionChain,
  getAgentAuditLog
};
