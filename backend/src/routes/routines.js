const express = require('express');
const router = express.Router();
const crypto = require('crypto');
const { authenticateUser, validateAction } = require('../middleware/auth');
const pool = require('../config/database');
const { encryptJSON, decryptJSON } = require('../utils/crypto');
const { cwLog } = require('../services/cloudwatch');
const { queues, waiters, nextCommandId } = require('../services/commandQueue');
const { Session } = require('../models/session');

let _tableChecked = false;
async function ensureTable() {
  if (_tableChecked) return;
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS routines (
        id VARCHAR(255) PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        scope VARCHAR(20) DEFAULT 'private',
        steps JSONB NOT NULL DEFAULT '[]',
        tags TEXT[] DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      )
    `);
    await pool.query('CREATE INDEX IF NOT EXISTS idx_routines_user ON routines(user_id)');
    await pool.query('CREATE INDEX IF NOT EXISTS idx_routines_scope ON routines(scope)');
    _tableChecked = true;
  } catch (err) {
    console.error('Failed to ensure routines table:', err);
  }
}

function encryptField(value) {
  if (value == null) return value;
  const { encrypted, iv } = encryptJSON(value);
  return { _enc: encrypted, _iv: iv };
}

function decryptField(value) {
  if (value && typeof value === 'object' && value._enc && value._iv) {
    return decryptJSON(value._enc, value._iv);
  }
  return value;
}

function encryptRoutineStep(step) {
  if (!step || typeof step !== 'object') return step;
  const out = { ...step };
  for (const key of ['url', 'domain', 'target', 'formData', 'label', 'promptText']) {
    if (out[key] != null) out[key] = encryptField(out[key]);
  }
  return out;
}

function decryptRoutineStep(step) {
  if (!step || typeof step !== 'object') return step;
  const out = { ...step };
  for (const key of ['url', 'domain', 'target', 'formData', 'label', 'promptText']) {
    out[key] = decryptField(out[key]);
  }
  return out;
}

function decryptRoutineSteps(rawSteps) {
  const steps = typeof rawSteps === 'string' ? JSON.parse(rawSteps) : (rawSteps || []);
  return steps.map(decryptRoutineStep);
}

// List routines: user's private + all global
router.get('/', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const { search } = req.query;
    let query = `SELECT * FROM routines WHERE (user_id = $1 OR scope = 'global')`;
    const values = [req.user.userId];
    let idx = 2;

    if (search) {
      query += ` AND name ILIKE $${idx}`;
      values.push(`%${search}%`);
      idx++;
    }
    query += ' ORDER BY updated_at DESC';

    const result = await pool.query(query, values);
    res.json({
      success: true,
      routines: result.rows.map(r => ({
        ...r,
        steps: decryptRoutineSteps(r.steps)
      }))
    });
  } catch (error) {
    console.error('Failed to list routines:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get single routine
router.get('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      `SELECT * FROM routines WHERE id = $1 AND (user_id = $2 OR scope = 'global')`,
      [req.params.id, req.user.userId]
    );
    if (result.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Routine not found' });
    }
    res.json({
      success: true,
      routine: {
        ...result.rows[0],
        steps: decryptRoutineSteps(result.rows[0].steps)
      }
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Create routine
router.post('/', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const { name, description, scope, steps, tags } = req.body;
    if (!name || !steps || !Array.isArray(steps)) {
      return res.status(400).json({ success: false, error: 'name and steps array are required' });
    }

    const id = `rtn_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;
    const encryptedSteps = steps.map(encryptRoutineStep);
    await pool.query(
      `INSERT INTO routines (id, user_id, name, description, scope, steps, tags)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [id, req.user.userId, name, description || null,
       scope === 'global' ? 'global' : 'private',
       JSON.stringify(encryptedSteps), tags || []]
    );

    // Send to CloudWatch (fire-and-forget)
    cwLog.routine({ id, name, userId: req.user.userId, scope: scope || 'private', stepCount: steps.length });

    res.status(201).json({
      success: true,
      routine: { id, name, description, scope: scope || 'private', steps, tags: tags || [] }
    });
  } catch (error) {
    console.error('Failed to create routine:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Update routine (owner only)
router.put('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const existing = await pool.query(
      'SELECT id FROM routines WHERE id = $1 AND user_id = $2',
      [req.params.id, req.user.userId]
    );
    if (existing.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Routine not found or not owned by you' });
    }

    const { name, description, scope, steps, tags } = req.body;
    const updates = [];
    const values = [];
    let idx = 1;

    if (name) { updates.push(`name = $${idx++}`); values.push(name); }
    if (description !== undefined) { updates.push(`description = $${idx++}`); values.push(description || null); }
    if (scope) { updates.push(`scope = $${idx++}`); values.push(scope === 'global' ? 'global' : 'private'); }
    if (steps) { updates.push(`steps = $${idx++}`); values.push(JSON.stringify(steps.map(encryptRoutineStep))); }
    if (tags) { updates.push(`tags = $${idx++}`); values.push(tags); }
    updates.push('updated_at = NOW()');

    if (values.length === 0) {
      return res.status(400).json({ success: false, error: 'No fields to update' });
    }

    values.push(req.params.id);
    await pool.query(
      `UPDATE routines SET ${updates.join(', ')} WHERE id = $${idx}`,
      values
    );
    res.json({ success: true, message: 'Routine updated' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Delete routine (owner only)
router.delete('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      'DELETE FROM routines WHERE id = $1 AND user_id = $2 RETURNING id',
      [req.params.id, req.user.userId]
    );
    if (result.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Routine not found' });
    }
    res.json({ success: true, message: 'Routine deleted' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Create routine from session — cherry-pick specific actions
router.post('/from-session/:sessionId', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const { sessionId } = req.params;
    const { name, description, scope, selectedActionIds } = req.body;

    if (!name) {
      return res.status(400).json({ success: false, error: 'name is required' });
    }

    // Fetch actions for the session (include form_data_iv for decryption)
    let query = `SELECT id, type, url, domain, target, form_data, form_data_iv, status, prompt_id
                 FROM actions WHERE session_id = $1 AND status IN ('allowed', 'approved_override')
                   AND parent_action_id IS NULL
                 ORDER BY timestamp ASC`;
    const result = await pool.query(query, [sessionId]);

    if (result.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'No allowed actions found in session' });
    }

    let actions = result.rows;

    if (selectedActionIds && Array.isArray(selectedActionIds) && selectedActionIds.length > 0) {
      const idSet = new Set(selectedActionIds);
      actions = actions.filter(a => idSet.has(a.id));
    }

    // Pre-fetch all sub-actions (children) for auto_login parent actions in this session
    const parentIds = actions.map(a => a.id);
    let subActionMap = {};
    if (parentIds.length > 0) {
      const subQuery = `SELECT id, type, url, domain, target, form_data, form_data_iv, status,
                               prompt_id,
                               parent_action_id, sub_order, reason
                        FROM actions WHERE parent_action_id = ANY($1)
                        ORDER BY sub_order ASC, timestamp ASC`;
      const subResult = await pool.query(subQuery, [parentIds]);
      for (const row of subResult.rows) {
        const pid = row.parent_action_id;
        if (!subActionMap[pid]) subActionMap[pid] = [];
        subActionMap[pid].push(row);
      }
    }

    const promptIds = new Set();
    for (const a of actions) {
      if (a.prompt_id) promptIds.add(a.prompt_id);
      for (const child of (subActionMap[a.id] || [])) {
        if (child.prompt_id) promptIds.add(child.prompt_id);
      }
    }

    const promptMap = {};
    if (promptIds.size > 0) {
      const promptRes = await pool.query(
        'SELECT id, content FROM prompts WHERE id = ANY($1)',
        [[...promptIds]]
      );
      for (const row of promptRes.rows) promptMap[row.id] = row.content;
    }

    function decryptFormData(row) {
      if (!row.form_data) return null;
      if (row.form_data_iv) {
        const plain = typeof row.form_data === 'string' ? row.form_data : JSON.stringify(row.form_data);
        return decryptJSON(plain, row.form_data_iv);
      }
      // Legacy unencrypted row
      if (typeof row.form_data === 'string') {
        try { return JSON.parse(row.form_data); } catch { return row.form_data; }
      }
      return row.form_data;
    }

    function parseTarget(raw) {
      if (!raw) return null;
      if (typeof raw === 'string') {
        try { return JSON.parse(raw); } catch { return null; }
      }
      return raw;
    }

    function normalizeActionType(type) {
      return type === 'form_input' ? 'type_text' : type;
    }

    function labelForInput(target, formData, domain) {
      const field =
        formData?.field ||
        target?.name ||
        target?.id ||
        target?.placeholder ||
        target?.ariaLabel ||
        'field';
      return `Type into ${field} on ${domain}`;
    }

    function labelForAction(a, formData) {
      const domain = a.domain || '';
      switch (a.type) {
        case 'navigation': return `Navigate to ${domain}`;
        case 'click': {
          const target = parseTarget(a.target);
          const text = target?.text || target?.id || 'element';
          return `Click "${text}" on ${domain}`;
        }
        case 'form_input': {
          return labelForInput(parseTarget(a.target), formData, domain);
        }
        case 'form_submit': {
          if (formData && formData.action === 'auto_login') return `Login on ${domain}`;
          return `Submit form on ${domain}`;
        }
        case 'press_key': {
          const key = formData?.value || parseTarget(a.target)?.value || 'Enter';
          return `Press ${key} on ${domain}`;
        }
        default: return `${a.type} on ${domain}`;
      }
    }

    const steps = [];
    let stepOrder = 0;

    for (const a of actions) {
      const target = parseTarget(a.target);
      const formData = decryptFormData(a);
      const promptText = promptMap[a.prompt_id] || null;

      // Check if this action has granular sub-steps (e.g. auto_login)
      const children = subActionMap[a.id];
      if (children && children.length > 0) {
        for (const child of children) {
          stepOrder++;
          const childTarget = parseTarget(child.target);
          const childFormData = decryptFormData(child);
          const childPromptText = promptMap[child.prompt_id] || promptText || null;

          let encChildFormData = null;
          if (childFormData != null) {
            const { encrypted, iv } = encryptJSON(childFormData);
            encChildFormData = { _enc: encrypted, _iv: iv };
          }

          steps.push({
            order: stepOrder,
            type: 'action',
            actionType: normalizeActionType(child.type),
            url: child.url || a.url,
            domain: child.domain || a.domain,
            target: childTarget || null,
            formData: encChildFormData,
            label: child.reason || labelForAction(child, childFormData),
            promptText: childPromptText || null
          });
        }
      } else {
        stepOrder++;
        let encFormData = null;
        if (formData != null) {
          const { encrypted, iv } = encryptJSON(formData);
          encFormData = { _enc: encrypted, _iv: iv };
        }

        steps.push({
          order: stepOrder,
          type: 'action',
          actionType: normalizeActionType(a.type),
          url: a.url,
          domain: a.domain,
          target: target || null,
          formData: encFormData,
          label: labelForAction(a, formData),
          promptText: promptText || null
        });
      }
    }

    const id = `rtn_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;
    const encryptedSteps = steps.map(encryptRoutineStep);
    await pool.query(
      `INSERT INTO routines (id, user_id, name, description, scope, steps)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [id, req.user.userId, name, description || null,
       scope === 'global' ? 'global' : 'private',
       JSON.stringify(encryptedSteps)]
    );

    res.status(201).json({
      success: true,
      routine: { id, name, description, scope: scope || 'private', steps }
    });
  } catch (error) {
    console.error('Failed to create routine from session:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Execute routine — push run_routine command to the shared agent queue
router.post('/:id/execute', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const { sessionId, requireApproval } = req.body;
    if (!sessionId) {
      return res.status(400).json({ success: false, error: 'sessionId is required' });
    }

    // Associate unclaimed session with this user so the extension always sees it
    try {
      const session = await Session.findById(sessionId);
      if (session && !session.userId) {
        await session.setUserId(req.user.userId);
      }
    } catch (err) {
      console.error('Failed to associate session with user:', err);
    }

    const result = await pool.query(
      `SELECT * FROM routines WHERE id = $1 AND (user_id = $2 OR scope = 'global')`,
      [req.params.id, req.user.userId]
    );
    if (result.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Routine not found' });
    }

    const routine = result.rows[0];
    const steps = decryptRoutineSteps(routine.steps);

    const isOwner = routine.user_id === req.user.userId;

    const command = {
      id: nextCommandId(),
      type: 'run_routine',
      routineId: routine.id,
      routineName: routine.name,
      scope: routine.scope,
      isOwner,
      requireApproval: Boolean(requireApproval),
      steps,
      sessionId,
      createdAt: new Date().toISOString()
    };

    const pending = waiters.get(sessionId);
    if (pending && pending.length > 0) {
      const waiter = pending.shift();
      clearTimeout(waiter.timer);
      if (!waiter.res.headersSent) {
        waiter.res.json({ success: true, command });
      }
      if (pending.length === 0) waiters.delete(sessionId);
    } else {
      if (!queues.has(sessionId)) queues.set(sessionId, []);
      queues.get(sessionId).push(command);
    }

    res.json({ success: true, message: `Routine "${routine.name}" queued for execution`, routineId: routine.id, routineName: routine.name, stepCount: steps.length });
  } catch (error) {
    console.error('Failed to execute routine:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Agent fetches a routine by ID (M2M auth)
router.get('/agent/:id', validateAction, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query('SELECT * FROM routines WHERE id = $1', [req.params.id]);
    if (result.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Routine not found' });
    }
    res.json({ success: true, routine: result.rows[0] });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;
