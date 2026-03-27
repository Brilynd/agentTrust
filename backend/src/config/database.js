// Database Configuration
// Shared PostgreSQL connection pool

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

// Create shared connection pool
const pool = new Pool(getPoolConfig());

// Handle pool errors
pool.on('error', (err) => {
  console.error('Unexpected database pool error:', err);
});

module.exports = pool;
module.exports.getPoolConfig = getPoolConfig;