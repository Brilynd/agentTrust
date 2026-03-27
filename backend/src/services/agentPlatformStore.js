const fs = require('fs/promises');
const path = require('path');
const { randomUUID, createHash } = require('crypto');

const pool = require('../config/database');

const LEGACY_CONFIG_PATH = path.resolve(__dirname, '..', '..', '..', 'platform', 'apps', 'api', 'data', 'bot-configurations.json');

let schemaReady;

function hashStep(previousHash, step) {
  return createHash('sha256')
    .update(JSON.stringify({ previousHash, step }))
    .digest('hex');
}

function normalizeSensitiveDataGrants(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const grants = [];
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const id = String(item.id || '').trim();
    const referenceKey = String(item.referenceKey || '').trim();
    const key = referenceKey || id;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    grants.push({
      id: id || undefined,
      referenceKey: referenceKey || undefined,
      label: item.label ? String(item.label).trim() : undefined,
      category: item.category ? String(item.category).trim() : undefined,
      fieldNames: Array.isArray(item.fieldNames)
        ? Array.from(new Set(item.fieldNames.map((field) => String(field).trim()).filter(Boolean)))
        : undefined
    });
  }
  return grants;
}

function mergeSensitiveDataGrants(...sources) {
  return normalizeSensitiveDataGrants(sources.flatMap((source) => normalizeSensitiveDataGrants(source)));
}

async function ensureSchema() {
  if (!schemaReady) {
    schemaReady = (async () => {
      await pool.query(`
        CREATE TABLE IF NOT EXISTS agent_jobs (
          id TEXT PRIMARY KEY,
          external_ref TEXT UNIQUE,
          agent_id TEXT,
          session_id TEXT,
          prompt_id TEXT,
          task TEXT NOT NULL,
          input JSONB NOT NULL,
          plan JSONB,
          status TEXT NOT NULL DEFAULT 'queued',
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
          worker_id TEXT,
          locked_at TIMESTAMP,
          created_at TIMESTAMP NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
      `);
      await pool.query(`
        CREATE TABLE IF NOT EXISTS agent_steps (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
          sequence INTEGER NOT NULL,
          name TEXT NOT NULL,
          action TEXT NOT NULL,
          selector JSONB,
          selector_text TEXT,
          payload JSONB,
          verification JSONB,
          result JSONB,
          status TEXT NOT NULL DEFAULT 'pending',
          retry_count INTEGER NOT NULL DEFAULT 0,
          failure_type TEXT NOT NULL DEFAULT 'NONE',
          failure_message TEXT,
          hash TEXT NOT NULL,
          previous_hash TEXT NOT NULL,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          created_at TIMESTAMP NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
          UNIQUE(job_id, sequence)
        )
      `);
      await pool.query(`
        CREATE TABLE IF NOT EXISTS approval_requests (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
          step_id TEXT,
          action TEXT NOT NULL,
          target JSONB,
          policy_reason TEXT,
          requested_by TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          decision_by TEXT,
          decision_comment TEXT,
          expires_at TIMESTAMP,
          decided_at TIMESTAMP,
          created_at TIMESTAMP NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
      `);
      await pool.query(`
        CREATE TABLE IF NOT EXISTS replay_chunks (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
          step_id TEXT,
          sequence INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          payload JSONB NOT NULL,
          created_at TIMESTAMP NOT NULL DEFAULT NOW(),
          UNIQUE(job_id, sequence)
        )
      `);
      await pool.query(`
        CREATE TABLE IF NOT EXISTS correction_memory (
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES agent_jobs(id) ON DELETE CASCADE,
          domain TEXT NOT NULL,
          action_type TEXT NOT NULL,
          failure_type TEXT NOT NULL,
          failed_selector JSONB,
          corrected_selector JSONB,
          notes TEXT,
          created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
      `);
      await pool.query(`
        CREATE TABLE IF NOT EXISTS metric_rollups (
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES agent_jobs(id) ON DELETE CASCADE,
          metric_key TEXT NOT NULL,
          metric_value DOUBLE PRECISION NOT NULL,
          labels JSONB,
          created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
      `);
      await pool.query(`
        CREATE TABLE IF NOT EXISTS bot_configurations (
          id TEXT PRIMARY KEY,
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
          id TEXT PRIMARY KEY,
          job_id TEXT REFERENCES agent_jobs(id) ON DELETE SET NULL,
          host TEXT,
          pid INTEGER,
          status TEXT NOT NULL DEFAULT 'starting',
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
    })();
  }
  await schemaReady;
}

async function migrateLegacyConfigurationsIfNeeded() {
  await ensureSchema();
  const existing = await pool.query('SELECT COUNT(*)::int AS count FROM bot_configurations');
  if (existing.rows[0].count > 0) {
    return;
  }

  try {
    const raw = await fs.readFile(LEGACY_CONFIG_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return;
    }
    for (const config of parsed) {
      await pool.query(
        `INSERT INTO bot_configurations (id, name, description, task, details, created_at, updated_at)
         VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
         ON CONFLICT (id) DO NOTHING`,
        [
          String(config.id || randomUUID()),
          String(config.name || 'Imported Configuration'),
          config.description ? String(config.description) : null,
          String(config.task || ''),
          JSON.stringify(config.details || {}),
          config.createdAt ? new Date(config.createdAt) : new Date(),
          config.updatedAt ? new Date(config.updatedAt) : new Date()
        ]
      );
    }
  } catch (error) {
    if (error && error.code === 'ENOENT') {
      return;
    }
    throw error;
  }
}

function createStepRows(jobId, steps, offset = 0, previousHashSeed = '0') {
  let previousHash = previousHashSeed;
  return steps.map((step, index) => {
    const sequence = offset + index;
    const normalizedStep = step && typeof step === 'object' ? step : {};
    const derivedAction = String(
      normalizedStep.action
      || (normalizedStep.url ? 'goto' : '')
      || (normalizedStep.target ? 'act' : '')
      || 'goal'
    );
    const derivedName = String(
      normalizedStep.name
      || normalizedStep.goal
      || normalizedStep.description
      || normalizedStep.label
      || (normalizedStep.url ? `Open ${normalizedStep.url}` : '')
      || `${derivedAction} step ${sequence + 1}`
    ).trim();
    const stepPayload = {
      ...normalizedStep,
      action: derivedAction,
      name: derivedName
    };
    const hash = hashStep(previousHash, stepPayload);
    const row = {
      id: randomUUID(),
      jobId,
      sequence,
      name: derivedName,
      action: derivedAction,
      selector: normalizedStep.target || null,
      selectorText: normalizedStep.target?.text || normalizedStep.target?.name || normalizedStep.target?.label || null,
      payload: stepPayload,
      verification: normalizedStep.verification || null,
      hash,
      previousHash
    };
    previousHash = hash;
    return row;
  });
}

async function hydrateJob(jobId) {
  const [jobRes, stepsRes, approvalsRes] = await Promise.all([
    pool.query(
      `SELECT id, status, progress, current_step AS "currentStep", error, metadata, task, created_at AS "createdAt",
              updated_at AS "updatedAt", current_step_index AS "currentStepIndex", input
       FROM agent_jobs
       WHERE id = $1`,
      [jobId]
    ),
    pool.query(
      `SELECT id, sequence, name, status, retry_count AS "retryCount", failure_type AS "failureType",
              failure_message AS "failureMessage", created_at AS "createdAt"
       FROM agent_steps
       WHERE job_id = $1
       ORDER BY sequence ASC`,
      [jobId]
    ),
    pool.query(
      `SELECT id, action, policy_reason AS "policyReason", job_id AS "jobId", status
       FROM approval_requests
       WHERE job_id = $1
       ORDER BY created_at DESC`,
      [jobId]
    )
  ]);

  if (!jobRes.rows[0]) {
    return null;
  }

  return {
    ...jobRes.rows[0],
    steps: stepsRes.rows,
    approvals: approvalsRes.rows
  };
}

async function listJobs() {
  await ensureSchema();
  const jobsRes = await pool.query(
    `SELECT id, status, progress, current_step AS "currentStep", error, metadata, task, created_at AS "createdAt",
            updated_at AS "updatedAt"
     FROM agent_jobs
     ORDER BY created_at DESC
     LIMIT 100`
  );
  return jobsRes.rows;
}

async function listRecoverableJobs() {
  await ensureSchema();
  const res = await pool.query(
    `SELECT id
     FROM agent_jobs
     WHERE status IN ('queued', 'running')
       AND cancel_requested = FALSE
     ORDER BY created_at ASC
     LIMIT 20`
  );
  return res.rows;
}

async function getJob(jobId) {
  await ensureSchema();
  return hydrateJob(jobId);
}

async function createJob(input, options = {}) {
  await ensureSchema();
  const jobId = randomUUID();
  const steps = Array.isArray(input.steps) ? input.steps : [];
  const metadata = {
    ...(input.metadata || {}),
    ...(options.runtimeMetadata || {}),
    sensitiveDataGrants: mergeSensitiveDataGrants(
      input.metadata?.sensitiveDataGrants,
      options.runtimeMetadata?.sensitiveDataGrants
    ),
    ...(options.configuration
      ? {
          configurationId: options.configuration.id,
          configurationName: options.configuration.name
        }
      : {})
  };
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query(
      `INSERT INTO agent_jobs (
        id, agent_id, session_id, prompt_id, task, input, plan, status, metadata, max_retries, created_at, updated_at
      ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, 'queued', $8::jsonb, $9, NOW(), NOW())`,
      [
        jobId,
        input.agentId || null,
        input.sessionId || null,
        input.promptId || null,
        input.task,
        JSON.stringify(input),
        JSON.stringify({ steps }),
        JSON.stringify(metadata),
        4
      ]
    );
    const stepRows = createStepRows(jobId, steps);
    for (const row of stepRows) {
      await client.query(
        `INSERT INTO agent_steps (
          id, job_id, sequence, name, action, selector, selector_text, payload, verification,
          status, retry_count, failure_type, hash, previous_hash, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb, $9::jsonb, 'pending', 0, 'NONE', $10, $11, NOW(), NOW())`,
        [
          row.id,
          row.jobId,
          row.sequence,
          row.name,
          row.action,
          JSON.stringify(row.selector),
          row.selectorText,
          JSON.stringify(row.payload),
          JSON.stringify(row.verification),
          row.hash,
          row.previousHash
        ]
      );
    }
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
  return hydrateJob(jobId);
}

async function appendJobContext(jobId, prompt, details) {
  await ensureSchema();
  const jobRes = await pool.query('SELECT input, metadata FROM agent_jobs WHERE id = $1', [jobId]);
  if (!jobRes.rows[0]) {
    return null;
  }
  const input = jobRes.rows[0].input || {};
  const metadata = jobRes.rows[0].metadata || {};
  const existingMessages = Array.isArray(metadata.operatorPrompts) ? metadata.operatorPrompts : [];
  const operatorMessage = { prompt, details, createdAt: new Date().toISOString() };
  const appendSteps = Array.isArray(details.appendSteps) ? details.appendSteps : [];
  const existingSteps = Array.isArray(input.steps) ? input.steps : [];
  const updatedInput = {
    ...input,
    operatorPrompts: [...existingMessages, operatorMessage],
    steps: [...existingSteps, ...appendSteps]
  };
  const updatedMetadata = {
    ...metadata,
    operatorPrompts: [...existingMessages, operatorMessage],
    sensitiveDataGrants: mergeSensitiveDataGrants(
      metadata.sensitiveDataGrants,
      details.sensitiveDataGrants
    )
  };

  const lastStepRes = await pool.query(
    'SELECT sequence, hash FROM agent_steps WHERE job_id = $1 ORDER BY sequence DESC LIMIT 1',
    [jobId]
  );
  const offset = lastStepRes.rows[0] ? lastStepRes.rows[0].sequence + 1 : 0;
  const prevHash = lastStepRes.rows[0]?.hash || '0';

  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query(
      `UPDATE agent_jobs
       SET input = $2::jsonb, metadata = $3::jsonb, updated_at = NOW()
       WHERE id = $1`,
      [jobId, JSON.stringify(updatedInput), JSON.stringify(updatedMetadata)]
    );
    const stepRows = createStepRows(jobId, appendSteps, offset, prevHash);
    for (const row of stepRows) {
      await client.query(
        `INSERT INTO agent_steps (
          id, job_id, sequence, name, action, selector, selector_text, payload, verification,
          status, retry_count, failure_type, hash, previous_hash, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb, $9::jsonb, 'pending', 0, 'NONE', $10, $11, NOW(), NOW())`,
        [
          row.id,
          row.jobId,
          row.sequence,
          row.name,
          row.action,
          JSON.stringify(row.selector),
          row.selectorText,
          JSON.stringify(row.payload),
          JSON.stringify(row.verification),
          row.hash,
          row.previousHash
        ]
      );
    }
    await client.query('COMMIT');
    return {
      job: await hydrateJob(jobId),
      appendedSteps: appendSteps.length,
      context: operatorMessage
    };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

async function updateJobControl(jobId, patch) {
  await ensureSchema();
  const fields = [];
  const values = [jobId];
  let index = 2;
  Object.entries(patch).forEach(([key, value]) => {
    const column = key.replace(/[A-Z]/g, (match) => `_${match.toLowerCase()}`);
    fields.push(`${column} = $${index++}`);
    values.push(value);
  });
  fields.push(`updated_at = NOW()`);
  await pool.query(`UPDATE agent_jobs SET ${fields.join(', ')} WHERE id = $1`, values);
  return hydrateJob(jobId);
}

async function listConfigurations() {
  await migrateLegacyConfigurationsIfNeeded();
  const res = await pool.query(
    `SELECT id, name, description, task, details, created_at AS "createdAt", updated_at AS "updatedAt"
     FROM bot_configurations
     ORDER BY created_at DESC`
  );
  return res.rows;
}

async function getConfiguration(configId) {
  await migrateLegacyConfigurationsIfNeeded();
  const res = await pool.query(
    `SELECT id, name, description, task, details, created_at AS "createdAt", updated_at AS "updatedAt"
     FROM bot_configurations
     WHERE id = $1`,
    [configId]
  );
  return res.rows[0] || null;
}

async function createConfiguration(config) {
  await ensureSchema();
  const id = config.id || `cfg_${Date.now()}`;
  const res = await pool.query(
    `INSERT INTO bot_configurations (id, name, description, task, details, created_at, updated_at)
     VALUES ($1, $2, $3, $4, $5::jsonb, NOW(), NOW())
     RETURNING id, name, description, task, details, created_at AS "createdAt", updated_at AS "updatedAt"`,
    [id, config.name, config.description || null, config.task, JSON.stringify(config.details || {})]
  );
  return res.rows[0];
}

async function updateConfiguration(configId, patch) {
  await ensureSchema();
  const res = await pool.query(
    `UPDATE bot_configurations
     SET name = $2, description = $3, task = $4, details = $5::jsonb, updated_at = NOW()
     WHERE id = $1
     RETURNING id, name, description, task, details, created_at AS "createdAt", updated_at AS "updatedAt"`,
    [configId, patch.name, patch.description || null, patch.task, JSON.stringify(patch.details || {})]
  );
  return res.rows[0] || null;
}

async function listApprovals() {
  await ensureSchema();
  const res = await pool.query(
    `SELECT id, action, policy_reason AS "policyReason", job_id AS "jobId", status
     FROM approval_requests
     WHERE status = 'pending'
     ORDER BY created_at DESC`
  );
  return res.rows;
}

async function getApproval(approvalId) {
  await ensureSchema();
  const res = await pool.query(
    `SELECT id, job_id AS "jobId", step_id AS "stepId", action, target, policy_reason AS "policyReason",
            status, decision_by AS "decisionBy", decision_comment AS "decisionComment",
            expires_at AS "expiresAt", decided_at AS "decidedAt", created_at AS "createdAt"
     FROM approval_requests WHERE id = $1`,
    [approvalId]
  );
  return res.rows[0] || null;
}

async function decideApproval(approvalId, approved, decisionBy = 'dashboard-operator', comment = null) {
  await ensureSchema();
  const status = approved ? 'approved' : 'rejected';
  const res = await pool.query(
    `UPDATE approval_requests
     SET status = $2, decision_by = $3, decision_comment = $4, decided_at = NOW(), updated_at = NOW()
     WHERE id = $1
     RETURNING id, action, policy_reason AS "policyReason", job_id AS "jobId", status`,
    [approvalId, status, decisionBy, comment]
  );
  return res.rows[0] || null;
}

async function upsertApproval(approval) {
  await ensureSchema();
  const res = await pool.query(
    `INSERT INTO approval_requests (
      id, job_id, step_id, action, target, policy_reason, status, requested_by, expires_at, created_at, updated_at
    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, NOW(), NOW())
    ON CONFLICT (id) DO UPDATE
    SET job_id = EXCLUDED.job_id,
        step_id = EXCLUDED.step_id,
        action = EXCLUDED.action,
        target = EXCLUDED.target,
        policy_reason = EXCLUDED.policy_reason,
        requested_by = EXCLUDED.requested_by,
        expires_at = EXCLUDED.expires_at,
        updated_at = NOW()
    RETURNING id, action, policy_reason AS "policyReason", job_id AS "jobId", status`,
    [
      approval.id,
      approval.jobId || null,
      approval.stepId || null,
      approval.action,
      JSON.stringify(approval.target || null),
      approval.policyReason || null,
      approval.status || 'pending',
      approval.requestedBy || 'legacy-agenttrust',
      approval.expiresAt || null
    ]
  );
  return res.rows[0] || null;
}

async function listReplay(jobId) {
  await ensureSchema();
  const res = await pool.query(
    `SELECT id, sequence, event_type AS "eventType", payload
     FROM replay_chunks
     WHERE job_id = $1
     ORDER BY sequence ASC`,
    [jobId]
  );
  return res.rows;
}

async function listCorrections() {
  await ensureSchema();
  const res = await pool.query(
    `SELECT id, job_id AS "jobId", domain, action_type AS "actionType", failure_type AS "failureType",
            failed_selector AS "failedSelector", corrected_selector AS "correctedSelector",
            notes, created_at AS "createdAt"
     FROM correction_memory
     ORDER BY created_at DESC
     LIMIT 200`
  );
  return res.rows;
}

async function createCorrection(correction) {
  await ensureSchema();
  const res = await pool.query(
    `INSERT INTO correction_memory (
      id, job_id, domain, action_type, failure_type, failed_selector, corrected_selector, notes, created_at
    ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, NOW())
    RETURNING id, job_id AS "jobId", domain, action_type AS "actionType", failure_type AS "failureType",
              failed_selector AS "failedSelector", corrected_selector AS "correctedSelector",
              notes, created_at AS "createdAt"`,
    [
      randomUUID(),
      correction.jobId || null,
      correction.domain,
      correction.actionType,
      correction.failureType,
      JSON.stringify(correction.failedSelector || null),
      JSON.stringify(correction.correctedSelector || null),
      correction.notes || null
    ]
  );
  return res.rows[0];
}

async function getMetricsSummary() {
  await ensureSchema();
  const [jobCounts, retries, avgDuration, failureBreakdown] = await Promise.all([
    pool.query(`
      SELECT
        COUNT(*)::int AS total,
        COUNT(*) FILTER (WHERE status = 'completed')::int AS completed,
        COUNT(*) FILTER (WHERE status = 'failed')::int AS failed,
        COUNT(*) FILTER (WHERE status = 'waiting_approval')::int AS waiting_approval
      FROM agent_jobs
    `),
    pool.query(`SELECT COALESCE(AVG(retry_count), 0) AS avg_retries FROM agent_steps`),
    pool.query(`
      SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000), 0) AS avg_execution_ms
      FROM agent_jobs
      WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
    `),
    pool.query(`
      SELECT failure_type AS key, COUNT(*)::int AS count
      FROM agent_steps
      WHERE failure_type IS NOT NULL AND failure_type <> 'NONE'
      GROUP BY failure_type
    `)
  ]);
  const counts = jobCounts.rows[0] || { total: 0, completed: 0, failed: 0, waiting_approval: 0 };
  const successRate = counts.total > 0 ? counts.completed / counts.total : 0;
  return {
    successRate,
    totalJobs: counts.total,
    completedJobs: counts.completed,
    failedJobs: counts.failed,
    waitingApproval: counts.waiting_approval,
    averageRetries: Number(retries.rows[0]?.avg_retries || 0),
    averageExecutionMs: Number(avgDuration.rows[0]?.avg_execution_ms || 0),
    failureBreakdown: Object.fromEntries(failureBreakdown.rows.map((row) => [row.key, row.count]))
  };
}

async function clearHistoricalActivity() {
  await ensureSchema();

  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const historicalStatuses = ['completed', 'failed', 'cancelled'];
    const historicalJobsResult = await client.query(
      `SELECT id FROM agent_jobs WHERE status = ANY($1::text[])`,
      [historicalStatuses]
    );
    const historicalJobIds = historicalJobsResult.rows.map((row) => row.id);

    let deletedJobs = 0;
    if (historicalJobIds.length > 0) {
      const deletedJobsResult = await client.query(
        `DELETE FROM agent_jobs
         WHERE id = ANY($1::text[])`,
        [historicalJobIds]
      );
      deletedJobs = deletedJobsResult.rowCount || 0;
    }

    const deletedApprovalsResult = await client.query(
      `DELETE FROM approval_requests
       WHERE status <> 'pending'
          OR job_id IS NULL`
    );

    const deletedWorkersResult = await client.query(
      `DELETE FROM worker_processes
       WHERE status <> 'running'`
    );

    let deletedActions = 0;
    try {
      const deletedActionsResult = await client.query(`DELETE FROM actions`);
      deletedActions = deletedActionsResult.rowCount || 0;
    } catch (_error) {
      deletedActions = 0;
    }

    await client.query('COMMIT');

    return {
      deletedJobs,
      deletedApprovals: deletedApprovalsResult.rowCount || 0,
      deletedWorkers: deletedWorkersResult.rowCount || 0,
      deletedActions,
      preservedStatuses: ['queued', 'running', 'paused', 'waiting_approval']
    };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

async function registerWorkerProcess(workerId, payload) {
  await ensureSchema();
  await pool.query(
    `INSERT INTO worker_processes (id, job_id, host, pid, status, last_heartbeat_at, metadata)
     VALUES ($1, $2, $3, $4, $5, NOW(), $6::jsonb)
     ON CONFLICT (id) DO UPDATE
     SET job_id = EXCLUDED.job_id,
         host = EXCLUDED.host,
         pid = EXCLUDED.pid,
         status = EXCLUDED.status,
         last_heartbeat_at = NOW(),
         metadata = EXCLUDED.metadata`,
    [
      workerId,
      payload.jobId || null,
      payload.host || null,
      payload.pid || null,
      payload.status || 'starting',
      JSON.stringify(payload.metadata || {})
    ]
  );
}

async function completeWorkerProcess(workerId, payload = {}) {
  await ensureSchema();
  await pool.query(
    `UPDATE worker_processes
     SET status = $2, exit_code = $3, exited_at = NOW(), last_heartbeat_at = NOW(), metadata = COALESCE($4::jsonb, metadata)
     WHERE id = $1`,
    [workerId, payload.status || 'exited', payload.exitCode ?? null, payload.metadata ? JSON.stringify(payload.metadata) : null]
  );
}

module.exports = {
  ensureSchema,
  migrateLegacyConfigurationsIfNeeded,
  listJobs,
  listRecoverableJobs,
  getJob,
  createJob,
  appendJobContext,
  updateJobControl,
  listConfigurations,
  getConfiguration,
  createConfiguration,
  updateConfiguration,
  listApprovals,
  getApproval,
  decideApproval,
  upsertApproval,
  listReplay,
  listCorrections,
  createCorrection,
  getMetricsSummary,
  clearHistoricalActivity,
  registerWorkerProcess,
  completeWorkerProcess
};
