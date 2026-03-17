// Action Model
// Database model for action logs
// form_data is encrypted at rest with AES-256-GCM

const pool = require('../config/database');
const { encryptJSON, decryptJSON } = require('../utils/crypto');

let _ivColumnChecked = false;
async function ensureFormDataIvColumn() {
  if (_ivColumnChecked) return;
  try {
    await pool.query(`
      ALTER TABLE actions ADD COLUMN IF NOT EXISTS form_data_iv VARCHAR(64)
    `);
    _ivColumnChecked = true;
  } catch {
    _ivColumnChecked = true;
  }
}

class Action {
  constructor(data) {
    this.id = data.id;
    this.agentId = data.agent_id || data.agentId;
    this.sessionId = data.session_id || data.sessionId;
    this.type = data.type;
    this.timestamp = data.timestamp;
    this.domain = data.domain;
    this.url = data.url;
    this.riskLevel = data.risk_level || data.riskLevel;
    this.hash = data.hash;
    this.previousHash = data.previous_hash || data.previousHash;
    this.target = data.target;
    this.scopes = data.scopes;
    this.stepUpRequired = data.step_up_required || data.stepUpRequired;
    this.reason = data.reason;
    this.status = data.status || 'allowed';
    this.screenshot = data.screenshot;
    this.promptId = data.prompt_id || data.promptId;
    this.parentActionId = data.parent_action_id || data.parentActionId || null;
    this.subOrder = data.sub_order != null ? data.sub_order : (data.subOrder != null ? data.subOrder : null);
    this.createdAt = data.created_at;

    // Decrypt form_data if it was stored with an IV (encrypted)
    const rawFormData = data.form_data || data.formData || data.form;
    const iv = data.form_data_iv || data.formDataIv;
    if (rawFormData && iv) {
      const plain = typeof rawFormData === 'string' ? rawFormData : JSON.stringify(rawFormData);
      this.formData = decryptJSON(plain, iv);
    } else if (rawFormData) {
      // Legacy unencrypted rows — parse as-is
      if (typeof rawFormData === 'string') {
        try { this.formData = JSON.parse(rawFormData); } catch { this.formData = rawFormData; }
      } else {
        this.formData = rawFormData;
      }
    } else {
      this.formData = null;
    }
  }
  
  static async create(data) {
    await ensureFormDataIvColumn();

    const {
      id,
      agentId,
      sessionId,
      type,
      timestamp,
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
      status,
      screenshot,
      promptId,
      parentActionId,
      subOrder
    } = data;

    // Encrypt form_data before storing
    let formDataStr = null;
    let formDataIv = null;
    if (formData != null) {
      const { encrypted, iv } = encryptJSON(formData);
      // form_data is a JSONB column, so encrypted text must be stored as a JSON string.
      formDataStr = JSON.stringify(encrypted);
      formDataIv = iv;
    }
    
    const query = `
      INSERT INTO actions (
        id, agent_id, session_id, type, timestamp, domain, url, risk_level,
        hash, previous_hash, target, form_data, form_data_iv, scopes,
        step_up_required, reason, status, screenshot, prompt_id,
        parent_action_id, sub_order
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
      RETURNING *
    `;
    
    const values = [
      id,
      agentId,
      sessionId || null,
      type,
      timestamp,
      domain,
      url,
      riskLevel || null,
      hash,
      previousHash || null,
      target ? JSON.stringify(target) : null,
      formDataStr,
      formDataIv,
      scopes || [],
      stepUpRequired || false,
      reason || null,
      status || 'allowed',
      screenshot || null,
      promptId || null,
      parentActionId || null,
      subOrder != null ? subOrder : null
    ];
    
    try {
      const result = await pool.query(query, values);
      return new Action(result.rows[0]);
    } catch (error) {
      console.error('Error creating action:', error);
      throw error;
    }
  }
  
  static async findById(id) {
    await ensureFormDataIvColumn();
    const query = 'SELECT * FROM actions WHERE id = $1';
    const result = await pool.query(query, [id]);
    
    if (result.rows.length === 0) {
      return null;
    }
    
    return new Action(result.rows[0]);
  }
  
  static async findByAgent(agentId, filters = {}) {
    await ensureFormDataIvColumn();
    let query = 'SELECT * FROM actions WHERE agent_id = $1';
    const values = [agentId];
    let paramIndex = 2;
    
    if (filters.domain) {
      query += ` AND domain = $${paramIndex}`;
      values.push(filters.domain);
      paramIndex++;
    }
    
    if (filters.riskLevel) {
      query += ` AND risk_level = $${paramIndex}`;
      values.push(filters.riskLevel);
      paramIndex++;
    }
    
    if (filters.startDate) {
      query += ` AND timestamp >= $${paramIndex}`;
      values.push(filters.startDate);
      paramIndex++;
    }
    
    if (filters.endDate) {
      query += ` AND timestamp <= $${paramIndex}`;
      values.push(filters.endDate);
      paramIndex++;
    }
    
    query += ' ORDER BY timestamp ASC';
    
    if (filters.limit) {
      query += ` LIMIT $${paramIndex}`;
      values.push(filters.limit);
    } else {
      query += ' LIMIT 100';
    }
    
    const result = await pool.query(query, values);
    return result.rows.map(row => new Action(row));
  }
  
  static async findAll(filters = {}) {
    await ensureFormDataIvColumn();
    let query = 'SELECT * FROM actions WHERE 1=1';
    const values = [];
    let paramIndex = 1;
    
    if (filters.agentId) {
      query += ` AND agent_id = $${paramIndex}`;
      values.push(filters.agentId);
      paramIndex++;
    }
    
    if (filters.sessionId) {
      query += ` AND session_id = $${paramIndex}`;
      values.push(filters.sessionId);
      paramIndex++;
    }
    
    // Filter by multiple session IDs (for user-scoped queries)
    if (filters.sessionIds && filters.sessionIds.length > 0) {
      query += ` AND session_id = ANY($${paramIndex})`;
      values.push(filters.sessionIds);
      paramIndex++;
    }
    
    if (filters.type) {
      query += ` AND type = $${paramIndex}`;
      values.push(filters.type);
      paramIndex++;
    }
    
    if (filters.domain) {
      query += ` AND domain = $${paramIndex}`;
      values.push(filters.domain);
      paramIndex++;
    }
    
    if (filters.riskLevel) {
      query += ` AND risk_level = $${paramIndex}`;
      values.push(filters.riskLevel);
      paramIndex++;
    }
    
    if (filters.startDate) {
      query += ` AND timestamp >= $${paramIndex}`;
      values.push(filters.startDate);
      paramIndex++;
    }
    
    if (filters.endDate) {
      query += ` AND timestamp <= $${paramIndex}`;
      values.push(filters.endDate);
      paramIndex++;
    }
    
    query += ' ORDER BY timestamp ASC';
    
    if (filters.limit) {
      query += ` LIMIT $${paramIndex}`;
      values.push(filters.limit);
    } else {
      query += ' LIMIT 100';
    }
    
    const result = await pool.query(query, values);
    return result.rows.map(row => new Action(row));
  }
  
  static async findBySession(sessionId) {
    return await Action.findAll({ sessionId });
  }
}

module.exports = { Action };
