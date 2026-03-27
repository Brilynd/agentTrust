// Database Migration Script
// Sets up initial database schema

// TODO: Implement actual database migrations using a migration library
// For now, this is a placeholder

const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

function hasValidDatabaseUrl(value) {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === 'postgresql:' || parsed.protocol === 'postgres:') &&
      !!parsed.hostname &&
      parsed.pathname &&
      parsed.pathname !== '/' &&
      !parsed.pathname.includes('=require')
    );
  } catch {
    return false;
  }
}

function buildDatabaseConfigFromParts() {
  const host = process.env.DB_HOST || '';
  const user = process.env.DB_USER || 'postgres';
  const password = process.env.DB_PASSWORD || '';
  if (!host) return null;
  return {
    host,
    port: parseInt(process.env.DB_PORT) || 5432,
    user,
    password,
    database: process.env.DB_NAME || process.env.POSTGRES_DB || user || 'postgres'
  };
}

// Build connection config with SSL support
function getPoolConfig() {
  // If DATABASE_URL is provided, use it (with SSL parsing)
  const derivedConfig = buildDatabaseConfigFromParts();
  if (hasValidDatabaseUrl(process.env.DATABASE_URL)) {
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
  const config = derivedConfig || {
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

    // Agent platform tables
    await pool.query(`
      CREATE TABLE IF NOT EXISTS agent_jobs (
        id VARCHAR(255) PRIMARY KEY,
        external_ref VARCHAR(255) UNIQUE,
        agent_id VARCHAR(255),
        session_id VARCHAR(255),
        prompt_id VARCHAR(255),
        task TEXT NOT NULL,
        input JSONB NOT NULL,
        plan JSONB,
        status VARCHAR(50) NOT NULL DEFAULT 'queued',
        current_step_index INTEGER NOT NULL DEFAULT 0,
        progress INTEGER NOT NULL DEFAULT 0,
        current_step TEXT,
        result JSONB,
        error TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        max_retries INTEGER NOT NULL DEFAULT 4,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        last_heartbeat_at TIMESTAMP,
        pause_requested BOOLEAN NOT NULL DEFAULT FALSE,
        cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
        metadata JSONB,
        worker_id VARCHAR(255),
        locked_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS agent_steps (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        name TEXT NOT NULL,
        action VARCHAR(100) NOT NULL,
        selector JSONB,
        selector_text TEXT,
        payload JSONB,
        verification JSONB,
        result JSONB,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        retry_count INTEGER NOT NULL DEFAULT 0,
        failure_type VARCHAR(50) NOT NULL DEFAULT 'NONE',
        failure_message TEXT,
        hash VARCHAR(255) NOT NULL,
        previous_hash VARCHAR(255) NOT NULL,
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(job_id, sequence)
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS approval_requests (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
        step_id VARCHAR(255),
        action VARCHAR(100) NOT NULL,
        target JSONB,
        policy_reason TEXT,
        requested_by VARCHAR(255),
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        decision_by VARCHAR(255),
        decision_comment TEXT,
        expires_at TIMESTAMP,
        decided_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS replay_chunks (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
        step_id VARCHAR(255),
        sequence INTEGER NOT NULL,
        event_type VARCHAR(100) NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(job_id, sequence)
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS correction_memory (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) REFERENCES agent_jobs(id) ON DELETE CASCADE,
        domain VARCHAR(255) NOT NULL,
        action_type VARCHAR(100) NOT NULL,
        failure_type VARCHAR(50) NOT NULL,
        failed_selector JSONB,
        corrected_selector JSONB,
        notes TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS metric_rollups (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) REFERENCES agent_jobs(id) ON DELETE CASCADE,
        metric_key VARCHAR(100) NOT NULL,
        metric_value DOUBLE PRECISION NOT NULL,
        labels JSONB,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS bot_configurations (
        id VARCHAR(255) PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        task TEXT NOT NULL,
        details JSONB NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      )
    `);

    await pool.query(`
      CREATE TABLE IF NOT EXISTS worker_processes (
        id VARCHAR(255) PRIMARY KEY,
        job_id VARCHAR(255) REFERENCES agent_jobs(id) ON DELETE SET NULL,
        host VARCHAR(255),
        pid INTEGER,
        status VARCHAR(50) NOT NULL DEFAULT 'starting',
        last_heartbeat_at TIMESTAMP,
        started_at TIMESTAMP NOT NULL DEFAULT NOW(),
        exited_at TIMESTAMP,
        exit_code INTEGER,
        metadata JSONB
      )
    `);

    await pool.query(`CREATE INDEX IF NOT EXISTS idx_agent_jobs_status_created_at ON agent_jobs(status, created_at DESC)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_agent_steps_job_status ON agent_steps(job_id, status)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_approval_requests_job_status ON approval_requests(job_id, status)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_replay_chunks_job_step ON replay_chunks(job_id, step_id)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_correction_memory_domain_action ON correction_memory(domain, action_type)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_metric_rollups_job_metric ON metric_rollups(job_id, metric_key)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_bot_configurations_created_at ON bot_configurations(created_at DESC)`);
    await pool.query(`CREATE INDEX IF NOT EXISTS idx_worker_processes_job_status ON worker_processes(job_id, status)`);
    
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
