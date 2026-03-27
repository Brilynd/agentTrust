const express = require('express');
const crypto = require('crypto');

const { authenticateUser, validateAction } = require('../middleware/auth');
const approvalsModule = require('./approvals');
const pool = require('../config/database');
const { encryptJSON, decryptJSON } = require('../utils/crypto');

const router = express.Router();

function normalizeDomain(input) {
  if (!input) return '';
  let value = String(input).trim().toLowerCase();
  value = value.replace(/^https?:\/\//, '');
  value = value.replace(/^www\./, '');
  value = value.split('/')[0];
  value = value.split('?')[0];
  value = value.split(':')[0];
  return value;
}

function normalizeStringArray(value) {
  const items = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(',')
      : [];
  return Array.from(new Set(items.map((item) => String(item || '').trim()).filter(Boolean)));
}

function parseStoredJsonList(value) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function getByPath(source, path) {
  const parts = String(path || '').split('.').map((part) => part.trim()).filter(Boolean);
  let current = source;
  for (const part of parts) {
    if (!current || typeof current !== 'object' || !(part in current)) {
      return undefined;
    }
    current = current[part];
  }
  return current;
}

function serializeMetadata(row) {
  return {
    id: row.id,
    referenceKey: row.reference_key,
    label: row.label,
    category: row.category,
    fieldNames: parseStoredJsonList(row.field_names),
    allowedDomains: parseStoredJsonList(row.allowed_domains),
    tags: parseStoredJsonList(row.tags),
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

async function loadJobSensitiveGrant(promptId, referenceKey, requestedFields) {
  const jobId = String(promptId || '').trim();
  if (!jobId) return { required: false, allowed: true, grant: null };

  const jobResult = await pool.query(
    'SELECT metadata FROM agent_jobs WHERE id = $1 OR prompt_id = $1 LIMIT 1',
    [jobId]
  );
  if (!jobResult.rows.length) {
    return { required: true, allowed: false, reason: 'Operation-specific sensitive data permissions are missing for this job.' };
  }

  const metadata = jobResult.rows[0].metadata || {};
  const grants = Array.isArray(metadata.sensitiveDataGrants) ? metadata.sensitiveDataGrants : [];
  const grant = grants.find((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return false;
    return String(item.referenceKey || '').trim() === referenceKey;
  });

  if (!grant) {
    return { required: true, allowed: false, reason: `Sensitive record ${referenceKey} was not granted to this operation.` };
  }

  const allowedFields = Array.isArray(grant.fieldNames)
    ? grant.fieldNames.map((field) => String(field).trim()).filter(Boolean)
    : [];
  if (allowedFields.length > 0 && requestedFields.some((field) => !allowedFields.includes(field))) {
    return {
      required: true,
      allowed: false,
      reason: `Requested fields for ${referenceKey} are outside the fields granted to this operation.`
    };
  }

  return { required: true, allowed: true, grant };
}

let tableReady = false;
async function ensureTable() {
  if (tableReady) return;
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS sensitive_records (
        id VARCHAR(255) PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        reference_key VARCHAR(255) NOT NULL UNIQUE,
        label VARCHAR(255),
        category VARCHAR(100),
        encrypted_payload TEXT NOT NULL,
        iv VARCHAR(64) NOT NULL,
        field_names TEXT NOT NULL,
        allowed_domains TEXT,
        tags TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      )
    `);
    await pool.query('CREATE INDEX IF NOT EXISTS idx_sensitive_records_user_id ON sensitive_records(user_id)');
    await pool.query('CREATE INDEX IF NOT EXISTS idx_sensitive_records_reference_key ON sensitive_records(reference_key)');
    tableReady = true;
  } catch (error) {
    console.error('Failed to ensure sensitive_records table:', error);
  }
}

router.get('/', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      `SELECT id, reference_key, label, category, field_names, allowed_domains, tags, created_at, updated_at
       FROM sensitive_records
       WHERE user_id = $1
       ORDER BY updated_at DESC, created_at DESC`,
      [req.user.userId]
    );
    res.json({ success: true, records: result.rows.map(serializeMetadata) });
  } catch (error) {
    console.error('Failed to list sensitive records:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const fields = req.body?.fields && typeof req.body.fields === 'object' && !Array.isArray(req.body.fields)
      ? req.body.fields
      : null;
    if (!fields || Object.keys(fields).length === 0) {
      return res.status(400).json({ success: false, error: 'fields object is required' });
    }

    const label = String(req.body?.label || '').trim() || null;
    const category = String(req.body?.category || 'pii').trim() || 'pii';
    const referenceKey = String(req.body?.referenceKey || `vault_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`).trim();
    const allowedDomains = normalizeStringArray(req.body?.allowedDomains).map(normalizeDomain).filter(Boolean);
    const tags = normalizeStringArray(req.body?.tags);
    const { encrypted, iv } = encryptJSON(fields);
    const id = `srec_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;

    await pool.query(
      `INSERT INTO sensitive_records (
        id, user_id, reference_key, label, category, encrypted_payload, iv, field_names, allowed_domains, tags
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [
        id,
        req.user.userId,
        referenceKey,
        label,
        category,
        encrypted,
        iv,
        JSON.stringify(Object.keys(fields)),
        JSON.stringify(allowedDomains),
        JSON.stringify(tags)
      ]
    );

    res.status(201).json({
      success: true,
      record: {
        id,
        referenceKey,
        label,
        category,
        fieldNames: Object.keys(fields),
        allowedDomains,
        tags,
        fieldRefs: Object.keys(fields).reduce((acc, field) => {
          acc[field] = `vault://${referenceKey}/${field}`;
          return acc;
        }, {})
      }
    });
  } catch (error) {
    console.error('Failed to create sensitive record:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

router.put('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const existing = await pool.query(
      'SELECT * FROM sensitive_records WHERE id = $1 AND user_id = $2',
      [req.params.id, req.user.userId]
    );
    if (!existing.rows.length) {
      return res.status(404).json({ success: false, error: 'Sensitive record not found' });
    }

    const updates = [];
    const values = [];
    let idx = 1;
    if (req.body?.label !== undefined) {
      updates.push(`label = $${idx++}`);
      values.push(String(req.body.label || '').trim() || null);
    }
    if (req.body?.category !== undefined) {
      updates.push(`category = $${idx++}`);
      values.push(String(req.body.category || 'pii').trim() || 'pii');
    }
    if (req.body?.referenceKey !== undefined) {
      updates.push(`reference_key = $${idx++}`);
      values.push(String(req.body.referenceKey || '').trim());
    }
    if (req.body?.allowedDomains !== undefined) {
      updates.push(`allowed_domains = $${idx++}`);
      values.push(JSON.stringify(normalizeStringArray(req.body.allowedDomains).map(normalizeDomain).filter(Boolean)));
    }
    if (req.body?.tags !== undefined) {
      updates.push(`tags = $${idx++}`);
      values.push(JSON.stringify(normalizeStringArray(req.body.tags)));
    }
    if (req.body?.fields && typeof req.body.fields === 'object' && !Array.isArray(req.body.fields)) {
      const { encrypted, iv } = encryptJSON(req.body.fields);
      updates.push(`encrypted_payload = $${idx++}`);
      values.push(encrypted);
      updates.push(`iv = $${idx++}`);
      values.push(iv);
      updates.push(`field_names = $${idx++}`);
      values.push(JSON.stringify(Object.keys(req.body.fields)));
    }
    if (!updates.length) {
      return res.status(400).json({ success: false, error: 'No fields to update' });
    }
    updates.push('updated_at = NOW()');
    values.push(req.params.id, req.user.userId);
    await pool.query(
      `UPDATE sensitive_records SET ${updates.join(', ')} WHERE id = $${idx++} AND user_id = $${idx}`,
      values
    );
    res.json({ success: true, message: 'Sensitive record updated' });
  } catch (error) {
    console.error('Failed to update sensitive record:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

router.delete('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      'DELETE FROM sensitive_records WHERE id = $1 AND user_id = $2 RETURNING id',
      [req.params.id, req.user.userId]
    );
    if (!result.rows.length) {
      return res.status(404).json({ success: false, error: 'Sensitive record not found' });
    }
    res.json({ success: true, message: 'Sensitive record deleted' });
  } catch (error) {
    console.error('Failed to delete sensitive record:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/lookup/by-reference', validateAction, async (req, res) => {
  await ensureTable();
  try {
    const referenceKey = String(req.query?.ref || '').trim();
    if (!referenceKey) {
      return res.status(400).json({ success: false, error: 'ref query param required' });
    }

    const requestedFields = normalizeStringArray(req.query?.fields || req.query?.field);
    if (!requestedFields.length) {
      return res.status(400).json({ success: false, error: 'field or fields query param required' });
    }

    const result = await pool.query(
      `SELECT id, reference_key, label, category, encrypted_payload, iv, field_names, allowed_domains, tags
       FROM sensitive_records
       WHERE reference_key = $1
       LIMIT 1`,
      [referenceKey]
    );
    if (!result.rows.length) {
      return res.json({ success: true, record: null });
    }

    const row = result.rows[0];
    const grantCheck = await loadJobSensitiveGrant(req.query?.promptId, referenceKey, requestedFields);
    if (!grantCheck.allowed) {
      return res.status(403).json({
        success: false,
        error: grantCheck.reason,
        status: 'denied'
      });
    }
    const allowedDomains = parseStoredJsonList(row.allowed_domains).map(normalizeDomain).filter(Boolean);
    const requestDomain = normalizeDomain(req.query?.domain || '');
    if (allowedDomains.length > 0 && (!requestDomain || !allowedDomains.includes(requestDomain))) {
      return res.status(403).json({
        success: false,
        error: `Sensitive record ${referenceKey} is not allowed for domain ${requestDomain || '(missing)'}`,
        status: 'denied'
      });
    }

    const approvalUrl = `vault://${referenceKey}`;
    const requestedFieldPreview = requestedFields.join(', ');
    const { approvalId } = req.query;
    if (!approvalId) {
      const approval = approvalsModule.createApproval({
        sessionId: req.query.sessionId || null,
        actionId: null,
        type: 'sensitive_record_access',
        domain: requestDomain || null,
        url: approvalUrl,
        riskLevel: 'high',
        reason: `Reveal sensitive data from ${referenceKey} (${requestedFieldPreview}) — requires user approval`,
        preview: { referenceKey, fields: requestedFields },
        impactSummary: `Reveal protected fields from ${referenceKey}`,
        promptId: req.query.promptId || null
      });
      return res.status(403).json({
        success: false,
        error: `Sensitive record access for ${referenceKey} requires user approval`,
        requiresStepUp: true,
        approvalId: approval.id,
        riskLevel: 'high',
        status: 'step_up_required'
      });
    }

    const approval = approvalsModule.__pendingApprovals.get(approvalId);
    if (!approval || approval.type !== 'sensitive_record_access' || approval.url !== approvalUrl) {
      return res.status(403).json({
        success: false,
        error: 'Sensitive record approval is missing or expired',
        requiresStepUp: true,
        status: 'step_up_required'
      });
    }
    if (approval.status !== 'approved') {
      return res.status(403).json({
        success: false,
        error: approval.status === 'denied' ? 'Sensitive record access denied by user' : 'Sensitive record access approval pending',
        requiresStepUp: true,
        approvalId,
        riskLevel: 'high',
        status: 'step_up_required'
      });
    }

    const decrypted = decryptJSON(row.encrypted_payload, row.iv);
    if (!decrypted || typeof decrypted !== 'object' || Array.isArray(decrypted)) {
      return res.status(500).json({ success: false, error: 'Failed to decrypt sensitive record' });
    }

    const fields = {};
    for (const fieldPath of requestedFields) {
      const value = getByPath(decrypted, fieldPath);
      if (value !== undefined) {
        fields[fieldPath] = value;
      }
    }

    res.json({
      success: true,
      record: {
        id: row.id,
        referenceKey: row.reference_key,
        label: row.label,
        category: row.category,
        fields
      }
    });
  } catch (error) {
    console.error('Failed to lookup sensitive record:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      `SELECT id, reference_key, label, category, field_names, allowed_domains, tags, created_at, updated_at
       FROM sensitive_records
       WHERE id = $1 AND user_id = $2`,
      [req.params.id, req.user.userId]
    );
    if (!result.rows.length) {
      return res.status(404).json({ success: false, error: 'Sensitive record not found' });
    }
    res.json({ success: true, record: serializeMetadata(result.rows[0]) });
  } catch (error) {
    console.error('Failed to fetch sensitive record:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;
