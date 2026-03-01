// Action Model
// Database model for action logs

const pool = require('../config/database');

class Action {
  constructor(data) {
    this.id = data.id;
    this.agentId = data.agent_id || data.agentId;
    this.type = data.type;
    this.timestamp = data.timestamp;
    this.domain = data.domain;
    this.url = data.url;
    this.riskLevel = data.risk_level || data.riskLevel;
    this.hash = data.hash;
    this.previousHash = data.previous_hash || data.previousHash;
    this.target = data.target;
    this.formData = data.form_data || data.form;
    this.scopes = data.scopes;
    this.stepUpRequired = data.step_up_required || data.stepUpRequired;
    this.reason = data.reason;
    this.createdAt = data.created_at;
  }
  
  static async create(data) {
    const {
      id,
      agentId,
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
      reason
    } = data;
    
    const query = `
      INSERT INTO actions (
        id, agent_id, type, timestamp, domain, url, risk_level,
        hash, previous_hash, target, form_data, scopes,
        step_up_required, reason
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
      RETURNING *
    `;
    
    const values = [
      id,
      agentId,
      type,
      timestamp,
      domain,
      url,
      riskLevel || null,
      hash,
      previousHash || null,
      target ? JSON.stringify(target) : null,
      formData ? JSON.stringify(formData) : null,
      scopes || [],
      stepUpRequired || false,
      reason || null
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
    const query = 'SELECT * FROM actions WHERE id = $1';
    const result = await pool.query(query, [id]);
    
    if (result.rows.length === 0) {
      return null;
    }
    
    return new Action(result.rows[0]);
  }
  
  static async findByAgent(agentId, filters = {}) {
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
    
    query += ' ORDER BY timestamp DESC';
    
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
    let query = 'SELECT * FROM actions WHERE 1=1';
    const values = [];
    let paramIndex = 1;
    
    if (filters.agentId) {
      query += ` AND agent_id = $${paramIndex}`;
      values.push(filters.agentId);
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
    
    query += ' ORDER BY timestamp DESC';
    
    if (filters.limit) {
      query += ` LIMIT $${paramIndex}`;
      values.push(filters.limit);
    } else {
      query += ' LIMIT 100';
    }
    
    const result = await pool.query(query, values);
    return result.rows.map(row => new Action(row));
  }
}

module.exports = { Action };
