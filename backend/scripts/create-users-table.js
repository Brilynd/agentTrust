// Create Users Table Script
// Run this to create the users table in PostgreSQL

const pool = require('../src/config/database');

async function createUsersTable() {
  try {
    console.log('Creating users table...');
    
    const query = `
      CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        name VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP,
        is_active BOOLEAN DEFAULT true
      );
      
      CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
      CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
    `;
    
    await pool.query(query);
    console.log('✅ Users table created successfully');
    
    // Create a default admin user (password: admin123 - CHANGE THIS!)
    const bcrypt = require('bcrypt');
    const defaultEmail = process.env.DEFAULT_ADMIN_EMAIL || 'admin@agenttrust.local';
    const defaultPassword = process.env.DEFAULT_ADMIN_PASSWORD || 'admin123';
    
    const passwordHash = await bcrypt.hash(defaultPassword, 10);
    
    const insertQuery = `
      INSERT INTO users (email, password_hash, name, is_active)
      VALUES ($1, $2, $3, $4)
      ON CONFLICT (email) DO NOTHING
      RETURNING id, email, name;
    `;
    
    const result = await pool.query(insertQuery, [
      defaultEmail,
      passwordHash,
      'Admin User',
      true
    ]);
    
    if (result.rows.length > 0) {
      console.log(`✅ Default admin user created: ${defaultEmail} / ${defaultPassword}`);
      console.log('⚠️  IMPORTANT: Change the default password after first login!');
    } else {
      console.log('ℹ️  Default admin user already exists');
    }
    
    process.exit(0);
  } catch (error) {
    console.error('❌ Error creating users table:', error);
    process.exit(1);
  }
}

createUsersTable();
