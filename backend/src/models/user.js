// User Model
// Database model for user authentication

const pool = require('../config/database');
const bcrypt = require('bcrypt');

class User {
  constructor(data) {
    this.id = data.id;
    this.email = data.email;
    this.name = data.name;
    this.passwordHash = data.password_hash;
    this.createdAt = data.created_at;
    this.updatedAt = data.updated_at;
    this.lastLogin = data.last_login;
    this.isActive = data.is_active;
  }
  
  static async create(data) {
    const { email, password, name } = data;
    
    // Hash password
    const passwordHash = await bcrypt.hash(password, 10);
    
    const query = `
      INSERT INTO users (email, password_hash, name)
      VALUES ($1, $2, $3)
      RETURNING id, email, name, created_at, is_active
    `;
    
    const values = [email, passwordHash, name || null];
    
    try {
      const result = await pool.query(query, values);
      const user = new User(result.rows[0]);
      // Don't return password hash
      delete user.passwordHash;
      return user;
    } catch (error) {
      if (error.code === '23505') { // Unique violation
        throw new Error('Email already exists');
      }
      throw error;
    }
  }
  
  static async findByEmail(email) {
    const query = 'SELECT * FROM users WHERE email = $1 AND is_active = true';
    const result = await pool.query(query, [email]);
    
    if (result.rows.length === 0) {
      return null;
    }
    
    return new User(result.rows[0]);
  }
  
  static async findById(id) {
    const query = 'SELECT id, email, name, created_at, updated_at, last_login, is_active FROM users WHERE id = $1 AND is_active = true';
    const result = await pool.query(query, [id]);
    
    if (result.rows.length === 0) {
      return null;
    }
    
    return new User(result.rows[0]);
  }
  
  async verifyPassword(password) {
    if (!this.passwordHash) {
      return false;
    }
    return await bcrypt.compare(password, this.passwordHash);
  }
  
  async updateLastLogin() {
    const query = 'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = $1';
    await pool.query(query, [this.id]);
  }
  
  toJSON() {
    return {
      id: this.id,
      email: this.email,
      name: this.name,
      createdAt: this.createdAt,
      lastLogin: this.lastLogin
    };
  }
}

module.exports = { User };
