// Add Status Column Migration
// Run this to add the status column to existing actions table

const pool = require('../src/config/database');

async function addStatusColumn() {
  try {
    console.log('Adding status column to actions table...');
    
    // Add status column if it doesn't exist
    await pool.query(`
      ALTER TABLE actions 
      ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'allowed'
    `);
    
    // Update existing rows that don't have a status
    // If step_up_required is true, set status to 'step_up_required'
    // If reason contains 'denied' or 'blocked', set status to 'denied'
    // Otherwise, set to 'allowed'
    await pool.query(`
      UPDATE actions 
      SET status = CASE
        WHEN step_up_required = true THEN 'step_up_required'
        WHEN reason ILIKE '%denied%' OR reason ILIKE '%blocked%' THEN 'denied'
        ELSE 'allowed'
      END
      WHERE status IS NULL OR status = 'allowed'
    `);
    
    console.log('✅ Status column added successfully');
    console.log('✅ Existing actions updated with appropriate status');
    
    process.exit(0);
  } catch (error) {
    console.error('❌ Error adding status column:', error);
    process.exit(1);
  }
}

addStatusColumn();
