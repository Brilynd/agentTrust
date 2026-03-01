// Test RDS Connection
// Helps diagnose connection issues

const { Pool } = require('pg');
require('dotenv').config();

const dbHost = process.env.DB_HOST || 'localhost';
const dbPort = parseInt(process.env.DB_PORT) || 5432;
const dbUser = process.env.DB_USER || 'postgres';
const dbPassword = process.env.DB_PASSWORD;

console.log('\n🔍 Testing RDS Connection...\n');
console.log('Configuration:');
console.log(`  Host: ${dbHost}`);
console.log(`  Port: ${dbPort} ${dbPort === 543 ? '⚠️  WARNING: Should be 5432!' : ''}`);
console.log(`  User: ${dbUser}`);
console.log(`  Password: ${dbPassword ? '***' : '❌ NOT SET'}`);
console.log('');

if (!dbPassword) {
  console.error('❌ DB_PASSWORD is not set in .env file!');
  process.exit(1);
}

if (dbPort === 543) {
  console.error('⚠️  WARNING: Port is 543, should be 5432!');
  console.error('   Update DB_PORT=5432 in your .env file\n');
}

const pool = new Pool({
  host: dbHost,
  port: dbPort,
  user: dbUser,
  password: dbPassword,
  database: 'postgres',
  ssl: { rejectUnauthorized: false },
  connectionTimeoutMillis: 10000, // 10 seconds
  query_timeout: 10000
});

async function test() {
  try {
    console.log('Attempting connection...');
    const result = await pool.query('SELECT NOW(), version()');
    console.log('\n✅ SUCCESS! Connected to RDS!\n');
    console.log('Database time:', result.rows[0].now);
    console.log('PostgreSQL version:', result.rows[0].version.split(' ')[0] + ' ' + result.rows[0].version.split(' ')[1]);
    console.log('\n✅ Your connection is working! You can now run: npm run create-db');
  } catch (error) {
    console.error('\n❌ CONNECTION FAILED!\n');
    console.error('Error:', error.message);
    console.error('\n💡 Most Common Issues:\n');
    
    if (error.code === 'ETIMEDOUT' || error.message.includes('timeout')) {
      console.error('1. 🔒 SECURITY GROUP - Most likely issue!');
      console.error('   → Go to AWS RDS Console → Your database → Security group');
      console.error('   → Edit inbound rules → Add rule:');
      console.error('      Type: PostgreSQL');
      console.error('      Port: 5432');
      console.error('      Source: "My IP" (or your current IP)');
      console.error('   → Save rules and try again\n');
      
      console.error('2. 🌐 PUBLIC ACCESS');
      console.error('   → Check RDS instance has "Publicly accessible" = Yes');
      console.error('   → If No, modify instance and enable public access\n');
      
      console.error('3. 📍 PORT NUMBER');
      console.error(`   → Check DB_PORT in .env is 5432 (currently: ${dbPort})`);
      if (dbPort === 543) {
        console.error('   → ⚠️  Your port is 543, change to 5432!\n');
      }
    } else if (error.code === 'ENOTFOUND') {
      console.error('1. ❌ HOSTNAME NOT FOUND');
      console.error(`   → Check DB_HOST in .env: ${dbHost}`);
      console.error('   → Verify RDS endpoint in AWS Console\n');
    } else if (error.code === '28P01' || error.message.includes('password')) {
      console.error('1. 🔑 PASSWORD AUTHENTICATION');
      console.error('   → Check DB_PASSWORD matches RDS master password');
      console.error('   → Verify DB_USER is correct (usually "postgres")\n');
    } else {
      console.error('Check:');
      console.error('   - RDS instance status is "Available"');
      console.error('   - Security group allows your IP on port 5432');
      console.error('   - Public access is enabled');
      console.error('   - DB_HOST and DB_PORT are correct\n');
    }
    
    console.error('📖 See: backend/TROUBLESHOOT_RDS_CONNECTION.md for detailed help\n');
  } finally {
    await pool.end();
  }
}

test();
