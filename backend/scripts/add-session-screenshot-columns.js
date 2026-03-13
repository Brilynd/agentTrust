// Add Session and Screenshot Columns Migration
// Run this to add session_id and screenshot columns to existing actions table

const pool = require('../src/config/database');

async function addColumns() {
  try {
    console.log('Adding session_id and screenshot columns to actions table...');
    
    // Create sessions table if it doesn't exist
    await pool.query(`
      CREATE TABLE IF NOT EXISTS sessions (
        id VARCHAR(255) PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        started_at TIMESTAMP DEFAULT NOW(),
        ended_at TIMESTAMP,
        action_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);
    
    // Add session_id column if it doesn't exist
    await pool.query(`
      ALTER TABLE actions 
      ADD COLUMN IF NOT EXISTS session_id VARCHAR(255)
    `);
    
    // Add screenshot column if it doesn't exist
    await pool.query(`
      ALTER TABLE actions 
      ADD COLUMN IF NOT EXISTS screenshot TEXT
    `);

    await pool.query(`
      ALTER TABLE actions
      ADD COLUMN IF NOT EXISTS screenshot_s3_key TEXT
    `);
    
    // Create index on session_id
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_session_id ON actions(session_id)
    `);
    
    // Create index on agent_id and started_at for sessions
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_sessions_agent_started ON sessions(agent_id, started_at)
    `);
    
    console.log('✅ Session and screenshot columns added successfully');
    
    process.exit(0);
  } catch (error) {
    console.error('❌ Error adding columns:', error);
    process.exit(1);
  }
}

addColumns();
