// Database Migration Script
// Sets up initial database schema

// TODO: Implement actual database migrations using a migration library
// For now, this is a placeholder

const { Pool } = require('pg');
require('dotenv').config();

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});

async function migrate() {
  try {
    console.log('Running migrations...');
    
    // Create actions table
    await pool.query(`
      CREATE TABLE IF NOT EXISTS actions (
        id VARCHAR(255) PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        type VARCHAR(50) NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        domain VARCHAR(255) NOT NULL,
        url TEXT NOT NULL,
        risk_level VARCHAR(20),
        hash VARCHAR(64) NOT NULL,
        previous_hash VARCHAR(64),
        target JSONB,
        form_data JSONB,
        scopes TEXT[],
        step_up_required BOOLEAN DEFAULT FALSE,
        reason TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);
    
    // Create index on agent_id for faster queries
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_agent_id ON actions(agent_id)
    `);
    
    // Create index on timestamp for date range queries
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions(timestamp)
    `);
    
    // Create index on domain for domain filtering
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_domain ON actions(domain)
    `);
    
    // Create index on risk_level for risk filtering
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_risk_level ON actions(risk_level)
    `);
    
    console.log('Migrations completed successfully!');
    
  } catch (error) {
    console.error('Migration failed:', error);
    throw error;
  } finally {
    await pool.end();
  }
}

if (require.main === module) {
  migrate()
    .then(() => process.exit(0))
    .catch(() => process.exit(1));
}

module.exports = { migrate };
