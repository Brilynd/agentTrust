const express = require('express');
const router = express.Router();
const crypto = require('crypto');
const { authenticateUser, validateAction } = require('../middleware/auth');
const pool = require('../config/database');

const ALGORITHM = 'aes-256-gcm';

function normalizeDomain(input) {
  if (!input) return '';
  let d = input.trim().toLowerCase();
  d = d.replace(/^https?:\/\//, '');
  d = d.replace(/^www\./, '');
  d = d.split('/')[0]; // strip path
  d = d.split('?')[0]; // strip query
  d = d.split(':')[0]; // strip port
  return d;
}

let _tableChecked = false;
async function ensureTable() {
  if (_tableChecked) return;
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS credentials (
        id VARCHAR(255) PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        domain VARCHAR(255) NOT NULL,
        username VARCHAR(255) NOT NULL,
        password_encrypted TEXT NOT NULL,
        iv VARCHAR(64) NOT NULL,
        label VARCHAR(255),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      )
    `);
    await pool.query('CREATE INDEX IF NOT EXISTS idx_credentials_domain ON credentials(domain)');
    _tableChecked = true;
  } catch (err) {
    console.error('Failed to ensure credentials table:', err);
  }
}

function getEncryptionKey() {
  const hex = process.env.CREDENTIAL_ENCRYPTION_KEY;
  if (hex && hex.length >= 64) {
    return Buffer.from(hex, 'hex');
  }
  // Fallback: derive a key from JWT_SECRET so credentials still work without a dedicated key
  const secret = process.env.JWT_SECRET || 'agenttrust-default-credential-key';
  return crypto.createHash('sha256').update(secret).digest();
}

function encrypt(text) {
  const key = getEncryptionKey();
  if (!key) throw new Error('CREDENTIAL_ENCRYPTION_KEY not configured');
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
  let encrypted = cipher.update(text, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  const authTag = cipher.getAuthTag().toString('hex');
  return { encrypted: encrypted + ':' + authTag, iv: iv.toString('hex') };
}

function decrypt(encryptedData, ivHex) {
  const key = getEncryptionKey();
  if (!key) throw new Error('CREDENTIAL_ENCRYPTION_KEY not configured');
  const [encrypted, authTag] = encryptedData.split(':');
  const iv = Buffer.from(ivHex, 'hex');
  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
  decipher.setAuthTag(Buffer.from(authTag, 'hex'));
  let decrypted = decipher.update(encrypted, 'hex', 'utf8');
  decrypted += decipher.final('utf8');
  return decrypted;
}

// List all saved credentials for the user (passwords masked)
router.get('/', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      'SELECT id, domain, username, label, created_at, updated_at FROM credentials WHERE user_id = $1 ORDER BY domain',
      [req.user.userId]
    );
    res.json({ success: true, credentials: result.rows });
  } catch (error) {
    console.error('Failed to list credentials:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Store a new credential (user auth)
router.post('/', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const { domain, username, password, label } = req.body;
    if (!domain || !username || !password) {
      return res.status(400).json({ success: false, error: 'domain, username, and password are required' });
    }

    const normalizedDomain = normalizeDomain(domain);
    const { encrypted, iv } = encrypt(password);
    const id = `cred_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;

    await pool.query(
      `INSERT INTO credentials (id, user_id, domain, username, password_encrypted, iv, label)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [id, req.user.userId, normalizedDomain, username, encrypted, iv, label || null]
    );

    res.status(201).json({
      success: true,
      credential: { id, domain: normalizedDomain, username, label: label || null }
    });
  } catch (error) {
    console.error('Failed to store credential:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Update a credential (user auth)
router.put('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const { id } = req.params;
    const { domain, username, password, label } = req.body;

    const existing = await pool.query(
      'SELECT id FROM credentials WHERE id = $1 AND user_id = $2',
      [id, req.user.userId]
    );
    if (existing.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Credential not found' });
    }

    const updates = [];
    const values = [];
    let idx = 1;

    if (domain) { updates.push(`domain = $${idx++}`); values.push(normalizeDomain(domain)); }
    if (username) { updates.push(`username = $${idx++}`); values.push(username); }
    if (password) {
      const { encrypted, iv } = encrypt(password);
      updates.push(`password_encrypted = $${idx++}`); values.push(encrypted);
      updates.push(`iv = $${idx++}`); values.push(iv);
    }
    if (label !== undefined) { updates.push(`label = $${idx++}`); values.push(label || null); }
    updates.push(`updated_at = NOW()`);

    if (values.length === 0) {
      return res.status(400).json({ success: false, error: 'No fields to update' });
    }

    values.push(id);
    await pool.query(
      `UPDATE credentials SET ${updates.join(', ')} WHERE id = $${idx}`,
      values
    );

    res.json({ success: true, message: 'Credential updated' });
  } catch (error) {
    console.error('Failed to update credential:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Delete a credential (user auth)
router.delete('/:id', authenticateUser, async (req, res) => {
  await ensureTable();
  try {
    const result = await pool.query(
      'DELETE FROM credentials WHERE id = $1 AND user_id = $2 RETURNING id',
      [req.params.id, req.user.userId]
    );
    if (result.rows.length === 0) {
      return res.status(404).json({ success: false, error: 'Credential not found' });
    }
    res.json({ success: true, message: 'Credential deleted' });
  } catch (error) {
    console.error('Failed to delete credential:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Agent looks up credentials by domain (M2M auth)
router.get('/lookup', validateAction, async (req, res) => {
  await ensureTable();
  try {
    const { domain } = req.query;
    if (!domain) {
      return res.status(400).json({ success: false, error: 'domain query param required' });
    }

    const normalized = normalizeDomain(domain);

    // Try exact match first, then substring match in both directions
    const result = await pool.query(
      `SELECT id, domain, username, password_encrypted, iv, label FROM credentials
       WHERE domain = $1
          OR domain ILIKE '%' || $1 || '%'
          OR $1 ILIKE '%' || domain || '%'
       ORDER BY
         CASE WHEN domain = $1 THEN 0 ELSE 1 END
       LIMIT 1`,
      [normalized]
    );

    if (result.rows.length === 0) {
      return res.json({ success: true, credential: null });
    }

    const row = result.rows[0];
    let password;
    try {
      password = decrypt(row.password_encrypted, row.iv);
    } catch {
      return res.status(500).json({ success: false, error: 'Failed to decrypt credential' });
    }

    res.json({
      success: true,
      credential: {
        id: row.id,
        domain: row.domain,
        username: row.username,
        password,
        label: row.label
      }
    });
  } catch (error) {
    console.error('Failed to lookup credential:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;
