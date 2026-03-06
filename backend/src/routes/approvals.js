const express = require('express');
const router = express.Router();
const { authenticateUser, validateAction } = require('../middleware/auth');

// In-memory approval queue
// approvalId -> { id, sessionId, actionId, type, domain, url, riskLevel, reason, status, createdAt }
const pendingApprovals = new Map();

// Long-poll waiters: approvalId -> [{ res, timer }]
const approvalWaiters = new Map();

let approvalCounter = 0;

function createApproval({ sessionId, actionId, type, domain, url, riskLevel, reason, target }) {
  const id = `approval_${Date.now()}_${++approvalCounter}`;
  const approval = {
    id,
    sessionId,
    actionId,
    type,
    domain,
    url,
    riskLevel,
    reason,
    target: target || null,
    status: 'pending',
    createdAt: new Date().toISOString()
  };
  pendingApprovals.set(id, approval);

  // Auto-expire after 2 minutes
  setTimeout(() => {
    const a = pendingApprovals.get(id);
    if (a && a.status === 'pending') {
      a.status = 'expired';
      resolveWaiters(id, { approved: false, reason: 'Approval expired' });
      pendingApprovals.delete(id);
    }
  }, 120000);

  return approval;
}

function resolveWaiters(approvalId, result) {
  const waiters = approvalWaiters.get(approvalId);
  if (waiters) {
    for (const w of waiters) {
      clearTimeout(w.timer);
      if (!w.res.headersSent) {
        w.res.json({ success: true, ...result });
      }
    }
    approvalWaiters.delete(approvalId);
  }
}

// Extension polls for pending approvals (user auth)
router.get('/pending', authenticateUser, (req, res) => {
  const { sessionId } = req.query;
  const results = [];

  for (const approval of pendingApprovals.values()) {
    if (approval.status === 'pending') {
      if (!sessionId || approval.sessionId === sessionId) {
        results.push(approval);
      }
    }
  }

  res.json({ success: true, approvals: results });
});

// Extension approves or denies (user auth)
router.post('/:id/respond', authenticateUser, (req, res) => {
  const { id } = req.params;
  const { approved } = req.body;

  const approval = pendingApprovals.get(id);
  if (!approval) {
    return res.status(404).json({ success: false, error: 'Approval not found or expired' });
  }

  if (approval.status !== 'pending') {
    return res.status(409).json({ success: false, error: `Approval already ${approval.status}` });
  }

  approval.status = approved ? 'approved' : 'denied';

  resolveWaiters(id, { approved: !!approved, approvalId: id, actionId: approval.actionId });

  // Clean up after a short delay
  setTimeout(() => pendingApprovals.delete(id), 10000);

  res.json({ success: true, approval });
});

// Agent long-polls waiting for user decision (M2M auth)
router.get('/:id/wait', validateAction, (req, res) => {
  const { id } = req.params;
  const timeout = Math.min(parseInt(req.query.timeout) || 60000, 60000);

  const approval = pendingApprovals.get(id);
  if (!approval) {
    return res.status(404).json({ success: false, error: 'Approval not found' });
  }

  // Already resolved
  if (approval.status !== 'pending') {
    return res.json({
      success: true,
      approved: approval.status === 'approved',
      approvalId: id,
      actionId: approval.actionId
    });
  }

  // Hold connection open
  const timer = setTimeout(() => {
    const list = approvalWaiters.get(id);
    if (list) {
      const idx = list.findIndex(w => w.res === res);
      if (idx !== -1) list.splice(idx, 1);
      if (list.length === 0) approvalWaiters.delete(id);
    }
    if (!res.headersSent) {
      res.json({ success: true, approved: false, reason: 'Approval wait timed out' });
    }
  }, timeout);

  if (!approvalWaiters.has(id)) approvalWaiters.set(id, []);
  approvalWaiters.get(id).push({ res, timer });

  req.on('close', () => {
    clearTimeout(timer);
    const list = approvalWaiters.get(id);
    if (list) {
      const idx = list.findIndex(w => w.res === res);
      if (idx !== -1) list.splice(idx, 1);
      if (list.length === 0) approvalWaiters.delete(id);
    }
  });
});

module.exports = router;
module.exports.createApproval = createApproval;
module.exports.__pendingApprovals = pendingApprovals;
