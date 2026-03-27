const express = require('express');
const router = express.Router();
const { authenticateUser, validateAction } = require('../middleware/auth');
const store = require('../services/agentPlatformStore');
const { emitPlatformEvent } = require('../services/platformSocket');

// In-memory approval queue
// approvalId -> { id, sessionId, actionId, type, domain, url, riskLevel, reason, status, createdAt }
const pendingApprovals = new Map();

// Long-poll waiters: approvalId -> [{ res, timer }]
const approvalWaiters = new Map();

let approvalCounter = 0;

// Dashboard/platform approvals stored in Postgres
router.get('/', async (_req, res, next) => {
  try {
    const approvals = await store.listApprovals();
    res.json({ success: true, approvals });
  } catch (error) {
    next(error);
  }
});

router.get('/:id', async (req, res, next) => {
  try {
    const approval = await store.getApproval(req.params.id);
    if (!approval) {
      return res.status(404).json({ success: false, error: 'Approval not found' });
    }
    res.json({ success: true, approval });
  } catch (error) {
    next(error);
  }
});

router.post('/:id/decision', async (req, res, next) => {
  try {
    const existingLegacy = pendingApprovals.get(req.params.id);
    const approval = await store.decideApproval(
      req.params.id,
      Boolean(req.body?.approved),
      req.body?.decisionBy || 'dashboard-operator',
      req.body?.comment || null
    );
    if (!approval) {
      return res.status(404).json({ success: false, error: 'Approval not found' });
    }
    if (existingLegacy && existingLegacy.status === 'pending') {
      existingLegacy.status = req.body?.approved ? 'approved' : 'denied';
      resolveWaiters(req.params.id, {
        approved: Boolean(req.body?.approved),
        approvalId: req.params.id,
        actionId: existingLegacy.actionId,
        reason: req.body?.comment || null
      });
    }
    emitPlatformEvent('approval.updated', approval);
    res.json({ success: true, approval });
  } catch (error) {
    next(error);
  }
});

function createApproval({ sessionId, actionId, type, domain, url, riskLevel, reason, target, preview, impactSummary, promptId }) {
  // Supersede any existing pending approvals for the same action
  // so the extension only shows the latest one
  for (const [existingId, existing] of pendingApprovals) {
    if (existing.status === 'pending' && existing.type === type && existing.url === url) {
      existing.status = 'superseded';
      resolveWaiters(existingId, { approved: false, reason: 'Superseded by new request' });
      pendingApprovals.delete(existingId);
    }
  }

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
    preview: preview || null,
    impactSummary: impactSummary || null,
    status: 'pending',
    createdAt: new Date().toISOString()
  };
  pendingApprovals.set(id, approval);

  void store.upsertApproval({
    id,
    jobId: promptId || null,
    stepId: promptId ? `${promptId}:approval:${type}` : null,
    action: type,
    target: target || null,
    policyReason: reason,
    status: 'pending',
    requestedBy: 'legacy-agenttrust',
    expiresAt: new Date(Date.now() + 2 * 60 * 1000)
  }).then((platformApproval) => {
    if (platformApproval) {
      emitPlatformEvent('approval.updated', platformApproval);
    }
  }).catch((error) => {
    console.error('Failed to mirror legacy approval into platform store:', error);
  });

  // Auto-expire after 2 minutes
  setTimeout(() => {
    const a = pendingApprovals.get(id);
    if (a && a.status === 'pending') {
      a.status = 'expired';
      resolveWaiters(id, { approved: false, reason: 'Approval expired' });
      pendingApprovals.delete(id);
      void store.decideApproval(id, false, 'system', 'Approval expired').catch(() => undefined);
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

function clearPendingApprovals(reason = 'Dashboard history reset') {
  for (const [approvalId, approval] of pendingApprovals.entries()) {
    if (approval.status === 'pending') {
      approval.status = 'cancelled';
      resolveWaiters(approvalId, {
        approved: false,
        approvalId,
        actionId: approval.actionId,
        reason
      });
    }
    pendingApprovals.delete(approvalId);
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

  // Keep approved actions longer so retries can reuse the approvalId
  const cleanupDelay = approved ? 120000 : 10000;
  setTimeout(() => pendingApprovals.delete(id), cleanupDelay);

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
module.exports.clearPendingApprovals = clearPendingApprovals;