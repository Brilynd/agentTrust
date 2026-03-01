// Auto-create database script
// Creates the agenttrust database if it doesn't exist
// No psql required - uses Node.js pg library

const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

// Build SSL configuration
function getSSLConfig() {
  // If certificate path is provided, use it
  if (process.env.DB_SSL_CERT_PATH) {
    const certPath = path.resolve(process.env.DB_SSL_CERT_PATH);
    if (fs.existsSync(certPath)) {
      return {
        rejectUnauthorized: true,
        ca: fs.readFileSync(certPath).toString()
      };
    } else {
      console.warn(`⚠️  SSL certificate not found at ${certPath}, using rejectUnauthorized: false`);
      return { rejectUnauthorized: false };
    }
  }
  
  // For AWS RDS, use SSL with rejectUnauthorized: false by default
  const dbHost = process.env.DB_HOST || '';
  if (dbHost.includes('rds.amazonaws.com') || dbHost.includes('amazonaws.com')) {
    return { rejectUnauthorized: false };
  }
  
  // No SSL for local connections
  return false;
}

async function createDatabase() {
  // Support both local PostgreSQL and AWS RDS
  const dbHost = process.env.DB_HOST || 'localhost';
  const dbPort = process.env.DB_PORT || 5432;
  const dbUser = process.env.DB_USER || 'postgres';
  const dbPassword = process.env.DB_PASSWORD;
  const dbName = process.env.DB_NAME || 'agenttrust';

  // Check if using DATABASE_URL (supports AWS RDS connection strings)
  let adminPool;
  if (process.env.DATABASE_URL) {
    // Parse DATABASE_URL to get connection details
    const url = new URL(process.env.DATABASE_URL);
    
    // Always connect to 'postgres' database to create our target database
    const sslConfig = url.searchParams.get('sslmode') === 'require' 
      ? getSSLConfig() 
      : false;
    
    adminPool = new Pool({
      host: url.hostname,
      port: parseInt(url.port) || 5432,
      user: url.username,
      password: url.password,
      database: 'postgres', // Connect to default 'postgres' DB to create new DB
      ssl: sslConfig
    });
  } else {
    // Use individual connection parameters (local or RDS)
    // Validate port
    if (dbPort === 543) {
      console.error('⚠️  WARNING: Port is 543, should be 5432!');
      console.error('   Update DB_PORT=5432 in your .env file');
    }
    
    adminPool = new Pool({
      host: dbHost,
      port: dbPort,
      user: dbUser,
      password: dbPassword,
      database: 'postgres', // Connect to default database
      ssl: getSSLConfig(),
      connectionTimeoutMillis: 15000, // 15 seconds timeout
      query_timeout: 15000
    });
  }

  try {
    console.log(`Creating database '${dbName}'...`);
    const displayHost = process.env.DATABASE_URL 
      ? new URL(process.env.DATABASE_URL).hostname 
      : dbHost;
    const displayPort = process.env.DATABASE_URL 
      ? new URL(process.env.DATABASE_URL).port || 5432
      : dbPort;
    console.log(`Connecting to: ${displayHost}:${displayPort}`);

    // Check if database exists
    const checkResult = await adminPool.query(
      `SELECT 1 FROM pg_database WHERE datname = $1`,
      [dbName]
    );

    if (checkResult.rows.length > 0) {
      console.log(`✅ Database '${dbName}' already exists!`);
      return;
    }

    // Create database
    await adminPool.query(`CREATE DATABASE ${dbName}`);
    console.log(`✅ Database '${dbName}' created successfully!`);

  } catch (error) {
    if (error.code === '42P04') {
      console.log(`✅ Database '${dbName}' already exists!`);
    } else {
      console.error('❌ Error creating database:', error.message);
      console.error('\n💡 Make sure:');
      if (dbHost.includes('rds.amazonaws.com') || dbHost.includes('amazonaws.com')) {
        console.error('   AWS RDS:');
        console.error('   1. RDS instance is "Available" (not "Creating")');
        console.error('   2. Security group allows your IP on port 5432');
        console.error('   3. Public access is enabled (for development)');
        console.error('   4. DB_PASSWORD matches RDS master password');
      } else {
        console.error('   Local PostgreSQL:');
        console.error('   1. PostgreSQL is installed and running');
        console.error('   2. DB_PASSWORD is set in backend/.env');
        console.error('   3. DB_USER has permission to create databases');
      }
      throw error;
    }
  } finally {
    await adminPool.end();
  }
}

if (require.main === module) {
  createDatabase()
    .then(() => {
      console.log('\n✅ Database setup complete!');
      console.log('Next step: Run migrations with: npm run migrate');
      process.exit(0);
    })
    .catch((error) => {
      console.error('\n❌ Database setup failed!');
      process.exit(1);
    });
}

module.exports = { createDatabase };
