// Session Model
// Database model for action sessions

const pool = require('../config/database');
const { cwLog } = require('../services/cloudwatch');

class Session {
  constructor(data) {
    this.id = data.id;
    this.agentId = data.agent_id || data.agentId;
    this.userId = data.user_id || data.userId || null;
    this.startedAt = data.started_at;
    this.endedAt = data.ended_at;
    this.actionCount = data.action_count || 0;
    this.createdAt = data.created_at;
  }
  
  static async create(agentId, userId = null) {
    const id = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    const query = `
      INSERT INTO sessions (id, agent_id, user_id, started_at)
      VALUES ($1, $2, $3, NOW())
      RETURNING *
    `;
    
    const values = [id, agentId, userId];
    
    try {
      const result = await pool.query(query, values);
      const session = new Session(result.rows[0]);

      // Send to CloudWatch (fire-and-forget)
      cwLog.session({ id, agentId, userId });

      return session;
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

  static async findByUser(userId, limit = 50) {
    // Return sessions owned by this user OR still unclaimed
    const query = `
      SELECT * FROM sessions 
      WHERE user_id = $1 OR user_id IS NULL
      ORDER BY started_at DESC 
      LIMIT $2
    `;
    const result = await pool.query(query, [userId, limit]);
    return result.rows.map(row => new Session(row));
  }

  static async findByUserStrict(userId, limit = 50) {
    // Return ONLY sessions owned by this user (no unclaimed)
    const query = `
      SELECT * FROM sessions 
      WHERE user_id = $1 
      ORDER BY started_at DESC 
      LIMIT $2
    `;
    const result = await pool.query(query, [userId, limit]);
    return result.rows.map(row => new Session(row));
  }

  static async findByUserAndAgent(userId, agentId, limit = 50) {
    const query = `
      SELECT * FROM sessions 
      WHERE (user_id = $1 OR user_id IS NULL) AND agent_id = $2 
      ORDER BY started_at DESC 
      LIMIT $3
    `;
    const result = await pool.query(query, [userId, agentId, limit]);
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
  
  static async getOrCreateActiveSession(agentId, userId = null) {
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
    return await Session.create(agentId, userId);
  }

  async setUserId(userId) {
    const query = 'UPDATE sessions SET user_id = $1 WHERE id = $2 RETURNING *';
    const result = await pool.query(query, [userId, this.id]);
    if (result.rows.length > 0) {
      this.userId = result.rows[0].user_id;
    }
    return this;
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
      userId: this.userId,
      startedAt: this.startedAt,
      endedAt: this.endedAt,
      actionCount: this.actionCount,
      createdAt: this.createdAt
    };
  }
}

module.exports = { Session };
