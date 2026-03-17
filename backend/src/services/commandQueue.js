// Single source of truth for in-memory command queues.
// Both commands.js and routines.js require this module so
// run_routine commands are pushed to the same queue the agent polls.

const queues = new Map();   // sessionId -> [command]
const waiters = new Map();  // sessionId -> [{ res, timer }]

let cmdCounter = 0;
function nextCommandId() {
  return `cmd_${Date.now()}_${++cmdCounter}`;
}

module.exports = { queues, waiters, nextCommandId };
