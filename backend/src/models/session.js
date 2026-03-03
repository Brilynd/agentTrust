// Session Model
// Database model for action sessions

const pool = require('../config/database');

class Session {
  constructor(data) {
    this.id = data.id;
    this.agentId = data.agent_id || data.agentId;
    this.startedAt = data.started_at;
    this.endedAt = data.ended_at;
    this.actionCount = data.action_count || 0;
    this.createdAt = data.created_at;
  }
  
  static async create(agentId) {
    const id = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    const query = `
      INSERT INTO sessions (id, agent_id, started_at)
      VALUES ($1, $2, NOW())
      RETURNING *
    `;
    
    const values = [id, agentId];
    
    try {
      const result = await pool.query(query, values);
      return new Session(result.rows[0]);
    } catch (error) {
      console.error('Error creating session:', error);
      throw error;
    }
  }
  
  static async findById(id) {
    const query = 'SELECT * FROM sessions WHERE id = $1';
    const result = await pool.query(query, [id]);
    
    if (result.rows.length === 0) {
      return null;
    }
    
    return new Session(result.rows[0]);
  }
  
  static async findByAgent(agentId, limit = 50) {
    const query = `
      SELECT * FROM sessions 
      WHERE agent_id = $1 
      ORDER BY started_at DESC 
      LIMIT $2
    `;
    const result = await pool.query(query, [agentId, limit]);
    return result.rows.map(row => new Session(row));
  }

  static async findAll(limit = 50) {
    const query = `
      SELECT * FROM sessions 
      ORDER BY started_at DESC 
      LIMIT $1
    `;
    const result = await pool.query(query, [limit]);
    return result.rows.map(row => new Session(row));
  }
  
  static async getOrCreateActiveSession(agentId) {
    // Try to find an active session (not ended) from the last hour
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    
    const query = `
      SELECT * FROM sessions 
      WHERE agent_id = $1 
      AND ended_at IS NULL 
      AND started_at > $2
      ORDER BY started_at DESC 
      LIMIT 1
    `;
    
    const result = await pool.query(query, [agentId, oneHourAgo]);
    
    if (result.rows.length > 0) {
      return new Session(result.rows[0]);
    }
    
    // Create new session
    return await Session.create(agentId);
  }
  
  async end() {
    const query = 'UPDATE sessions SET ended_at = NOW() WHERE id = $1 RETURNING *';
    const result = await pool.query(query, [this.id]);
    return new Session(result.rows[0]);
  }
  
  async incrementActionCount() {
    const query = 'UPDATE sessions SET action_count = action_count + 1 WHERE id = $1 RETURNING *';
    const result = await pool.query(query, [this.id]);
    this.actionCount = result.rows[0].action_count;
    return this;
  }
  
  toJSON() {
    return {
      id: this.id,
      agentId: this.agentId,
      startedAt: this.startedAt,
      endedAt: this.endedAt,
      actionCount: this.actionCount,
      createdAt: this.createdAt
    };
  }
}

module.exports = { Session };
