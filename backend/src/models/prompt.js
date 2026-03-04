const pool = require('../config/database');

class Prompt {
  constructor(data) {
    this.id = data.id;
    this.sessionId = data.session_id || data.sessionId;
    this.agentId = data.agent_id || data.agentId;
    this.content = data.content;
    this.response = data.response;
    this.createdAt = data.created_at || data.createdAt;
  }

  static async create(data) {
    const id = `prompt_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    const query = `
      INSERT INTO prompts (id, session_id, agent_id, content, response)
      VALUES ($1, $2, $3, $4, $5)
      RETURNING *
    `;

    const values = [
      id,
      data.sessionId || null,
      data.agentId,
      data.content,
      data.response || null
    ];

    const result = await pool.query(query, values);
    return new Prompt(result.rows[0]);
  }

  static async findBySession(sessionId) {
    const query = 'SELECT * FROM prompts WHERE session_id = $1 ORDER BY created_at ASC';
    const result = await pool.query(query, [sessionId]);
    return result.rows.map(row => new Prompt(row));
  }

  static async findByAgent(agentId, limit = 50) {
    const query = 'SELECT * FROM prompts WHERE agent_id = $1 ORDER BY created_at DESC LIMIT $2';
    const result = await pool.query(query, [agentId, limit]);
    return result.rows.map(row => new Prompt(row));
  }

  static async updateResponse(id, response) {
    const query = 'UPDATE prompts SET response = $1 WHERE id = $2 RETURNING *';
    const result = await pool.query(query, [response, id]);
    if (result.rows.length === 0) return null;
    return new Prompt(result.rows[0]);
  }

  toJSON() {
    return {
      id: this.id,
      sessionId: this.sessionId,
      agentId: this.agentId,
      content: this.content,
      response: this.response,
      createdAt: this.createdAt
    };
  }
}

module.exports = { Prompt };
