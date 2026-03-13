// Database Migration Script
// Sets up initial database schema

// TODO: Implement actual database migrations using a migration library
// For now, this is a placeholder

const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

// Build connection config with SSL support
function getPoolConfig() {
  // If DATABASE_URL is provided, use it (with SSL parsing)
  if (process.env.DATABASE_URL) {
    const url = new URL(process.env.DATABASE_URL);
    const config = {
      connectionString: process.env.DATABASE_URL
    };
    
    // Handle SSL from connection string
    if (url.searchParams.get('sslmode') === 'require') {
      config.ssl = { rejectUnauthorized: false };
    }
    
    return config;
  }
  
  // Otherwise, use individual connection parameters
  const config = {
    host: process.env.DB_HOST || 'localhost',
    port: parseInt(process.env.DB_PORT) || 5432,
    user: process.env.DB_USER || 'postgres',
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME || 'agenttrust'
  };
  
  // Handle SSL with certificate file
  if (process.env.DB_SSL_CERT_PATH) {
    const certPath = path.resolve(process.env.DB_SSL_CERT_PATH);
    if (fs.existsSync(certPath)) {
      config.ssl = {
        rejectUnauthorized: true,
        ca: fs.readFileSync(certPath).toString()
      };
    } else {
      console.warn(`⚠️  SSL certificate not found at ${certPath}, using rejectUnauthorized: false`);
      config.ssl = { rejectUnauthorized: false };
    }
  } else if (process.env.DB_HOST && process.env.DB_HOST.includes('rds.amazonaws.com')) {
    // AWS RDS - use SSL but don't require certificate validation for development
    config.ssl = { rejectUnauthorized: false };
  }
  
  return config;
}

const pool = new Pool(getPoolConfig());

async function migrate() {
  try {
    console.log('Running migrations...');
    
    // Create sessions table
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
    
    // Create actions table
    await pool.query(`
      CREATE TABLE IF NOT EXISTS actions (
        id VARCHAR(255) PRIMARY KEY,
        agent_id VARCHAR(255) NOT NULL,
        session_id VARCHAR(255),
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
        status VARCHAR(20) DEFAULT 'allowed',
        screenshot TEXT,
        screenshot_s3_key TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);
    
    // Add status column if it doesn't exist (for existing databases)
    await pool.query(`
      ALTER TABLE actions 
      ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'allowed'
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

    // Add screenshot_s3_key column for S3-backed screenshot storage
    await pool.query(`
      ALTER TABLE actions
      ADD COLUMN IF NOT EXISTS screenshot_s3_key TEXT
    `);

    // Add prompt_id column to link actions to the prompt that triggered them
    await pool.query(`
      ALTER TABLE actions 
      ADD COLUMN IF NOT EXISTS prompt_id VARCHAR(255)
    `);
    
    // Create foreign key for session_id
    await pool.query(`
      DO $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM pg_constraint WHERE conname = 'fk_actions_session'
        ) THEN
          ALTER TABLE actions 
          ADD CONSTRAINT fk_actions_session 
          FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL;
        END IF;
      END $$;
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
    
    // Create index on session_id for session queries
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_session_id ON actions(session_id)
    `);
    
    // Add user_id column to sessions so each session belongs to a specific user
    await pool.query(`
      ALTER TABLE sessions 
      ADD COLUMN IF NOT EXISTS user_id INTEGER
    `);

    // Create index on user_id for filtering sessions by user
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)
    `);

    // Create index on agent_id and started_at for session queries
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_sessions_agent_started ON sessions(agent_id, started_at)
    `);

    // Create prompts table to store user prompts linked to sessions
    await pool.query(`
      CREATE TABLE IF NOT EXISTS prompts (
        id VARCHAR(255) PRIMARY KEY,
        session_id VARCHAR(255) REFERENCES sessions(id) ON DELETE CASCADE,
        agent_id VARCHAR(255) NOT NULL,
        content TEXT NOT NULL,
        response TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);

    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_prompts_session_id ON prompts(session_id)
    `);

    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_prompts_agent_id ON prompts(agent_id)
    `);

    // Create credentials table for stored website logins
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

    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_credentials_domain ON credentials(domain)
    `);

    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_credentials_user_id ON credentials(user_id)
    `);

    // Create user_connections table for Token Vault linked accounts
    await pool.query(`
      CREATE TABLE IF NOT EXISTS user_connections (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        provider VARCHAR(100) NOT NULL,
        auth0_access_token TEXT,
        auth0_refresh_token TEXT,
        connected_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, provider)
      )
    `);

    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_user_connections_user_id ON user_connections(user_id)
    `);

    // Add parent_action_id for sub-action tracking (auto_login sub-steps)
    await pool.query(`
      ALTER TABLE actions
      ADD COLUMN IF NOT EXISTS parent_action_id VARCHAR(255)
    `);

    await pool.query(`
      ALTER TABLE actions
      ADD COLUMN IF NOT EXISTS sub_order INTEGER
    `);

    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_actions_parent ON actions(parent_action_id)
    `);

    await pool.query(`
      ALTER TABLE prompts
      ADD COLUMN IF NOT EXISTS progress TEXT
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
