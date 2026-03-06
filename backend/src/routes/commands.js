const express = require('express');
const router = express.Router();
const { authenticateUser, validateAction } = require('../middleware/auth');

// In-memory command queue: sessionId -> [{ id, content, createdAt }]
const queues = new Map();

// Long-poll waiters: sessionId -> [{ res, timer }]
const waiters = new Map();

let cmdCounter = 0;

// Extension submits a command (user auth)
router.post('/', authenticateUser, (req, res) => {
  const { content, sessionId } = req.body;

  if (!content || !sessionId) {
    return res.status(400).json({ success: false, error: 'content and sessionId are required' });
  }

  const command = {
    id: `cmd_${Date.now()}_${++cmdCounter}`,
    content,
    sessionId,
    createdAt: new Date().toISOString()
  };

  // If an agent is long-polling for this session, resolve it immediately
  const pending = waiters.get(sessionId);
  if (pending && pending.length > 0) {
    const waiter = pending.shift();
    clearTimeout(waiter.timer);
    if (!waiter.res.headersSent) {
      waiter.res.json({ success: true, command });
    }
    if (pending.length === 0) waiters.delete(sessionId);
    return res.status(201).json({ success: true, command });
  }

  // Otherwise queue it for the next poll
  if (!queues.has(sessionId)) queues.set(sessionId, []);
  queues.get(sessionId).push(command);

  res.status(201).json({ success: true, command });
});

// Agent long-polls for pending commands (M2M auth)
router.get('/pending', validateAction, (req, res) => {
  const { sessionId } = req.query;
  const timeout = Math.min(parseInt(req.query.timeout) || 30000, 30000);

  if (!sessionId) {
    return res.status(400).json({ success: false, error: 'sessionId query param required' });
  }

  // Check if there's already a queued command
  const queue = queues.get(sessionId);
  if (queue && queue.length > 0) {
    const command = queue.shift();
    if (queue.length === 0) queues.delete(sessionId);
    return res.json({ success: true, command });
  }

  // No command yet — hold the connection open (long poll)
  const timer = setTimeout(() => {
    const list = waiters.get(sessionId);
    if (list) {
      const idx = list.findIndex(w => w.res === res);
      if (idx !== -1) list.splice(idx, 1);
      if (list.length === 0) waiters.delete(sessionId);
    }
    if (!res.headersSent) {
      res.json({ success: true, command: null });
    }
  }, timeout);

  if (!waiters.has(sessionId)) waiters.set(sessionId, []);
  waiters.get(sessionId).push({ res, timer });

  // Clean up if client disconnects
  req.on('close', () => {
    clearTimeout(timer);
    const list = waiters.get(sessionId);
    if (list) {
      const idx = list.findIndex(w => w.res === res);
      if (idx !== -1) list.splice(idx, 1);
      if (list.length === 0) waiters.delete(sessionId);
    }
  });
});

module.exports = router;
