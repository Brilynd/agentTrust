import "./runtime-env";

import * as os from "node:os";

import { Pool } from "pg";
import pino = require("pino");
import { io as createSocket } from "socket.io-client";

import { PlaywrightExecutionEngine } from "../../../packages/engine/src/index";
import type { AgentTaskInput, BrowserStep, FailureType, SelectorDescriptor } from "../../../packages/shared/src/index";

const logger = pino({
  level: process.env.LOG_LEVEL || "info",
  base: { service: "agenttrust-platform-local-worker" }
});

function getPoolConfig() {
  if (process.env.DATABASE_URL && !process.env.DB_HOST) {
    const url = new URL(process.env.DATABASE_URL);
    const config: { connectionString: string; ssl?: { rejectUnauthorized: boolean } } = {
      connectionString: process.env.DATABASE_URL
    };
    if (url.searchParams.get("sslmode") === "require") {
      config.ssl = { rejectUnauthorized: false };
    }
    return config;
  }

  return {
    host: process.env.DB_HOST || "localhost",
    port: Number(process.env.DB_PORT || 5432),
    user: process.env.DB_USER || "postgres",
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME || process.env.POSTGRES_DB || process.env.DB_USER || "postgres",
    ssl:
      process.env.DB_HOST && process.env.DB_HOST.includes("rds.amazonaws.com")
        ? { rejectUnauthorized: false }
        : undefined
  };
}

function getArg(name: string) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

const jobId = getArg("--jobId");
const workerId = getArg("--workerId") || `worker_${Date.now()}`;

if (!jobId) {
  throw new Error("Missing required --jobId");
}

const pool = new Pool(getPoolConfig());
const socket = createSocket(process.env.PLATFORM_BACKEND_URL || "http://127.0.0.1:3000", {
  transports: ["websocket"]
});
let replaySequence = 0;

async function emit(channel: string, payload: unknown) {
  socket.emit("platform:event", { channel, payload });
}

async function queryOne<T>(sql: string, values: unknown[] = []) {
  const result = await pool.query<T>(sql, values);
  return result.rows[0];
}

async function getJobInput() {
  const row = await queryOne<{ input: AgentTaskInput }>(
    `SELECT input FROM agent_jobs WHERE id = $1`,
    [jobId]
  );
  if (!row) {
    throw new Error(`Job ${jobId} not found`);
  }
  return row.input;
}

async function seedReplaySequence() {
  const row = await queryOne<{ maxSequence: number | null }>(
    `SELECT MAX(sequence) AS "maxSequence" FROM replay_chunks WHERE job_id = $1`,
    [jobId]
  );
  replaySequence = Number(row?.maxSequence || 0);
}

async function updateWorker(status: string, extra: Record<string, unknown> = {}) {
  await pool.query(
    `UPDATE worker_processes
     SET status = $2, pid = $3, host = $4, last_heartbeat_at = NOW(), metadata = COALESCE($5::jsonb, metadata)
     WHERE id = $1`,
    [workerId, status, process.pid, os.hostname(), JSON.stringify(extra)]
  );
}

async function updateJobStatus(data: Record<string, unknown>) {
  const mappings: Record<string, string> = {
    status: "status",
    progress: "progress",
    currentStep: "current_step",
    currentStepIndex: "current_step_index",
    error: "error",
    retryCount: "retry_count",
    startedAt: "started_at",
    completedAt: "completed_at",
    result: "result",
    metadata: "metadata",
    workerId: "worker_id"
  };

  const keys = Object.keys(data);
  if (keys.length === 0) {
    return;
  }
  const sets: string[] = [];
  const values: unknown[] = [jobId];
  let idx = 2;
  for (const key of keys) {
    const column = mappings[key];
    if (!column) continue;
    const value = data[key];
    const isJson = key === "result" || key === "metadata";
    sets.push(`${column} = ${isJson ? `$${idx}::jsonb` : `$${idx}`}`);
    values.push(isJson ? JSON.stringify(value ?? null) : value);
    idx += 1;
  }
  sets.push(`last_heartbeat_at = NOW()`);
  await pool.query(`UPDATE agent_jobs SET ${sets.join(", ")}, updated_at = NOW() WHERE id = $1`, values);
}

async function getControlState() {
  return queryOne<{ pause_requested: boolean; cancel_requested: boolean }>(
    `SELECT pause_requested, cancel_requested FROM agent_jobs WHERE id = $1`,
    [jobId]
  );
}

async function honorControls() {
  while (true) {
    const state = await getControlState();
    if (!state) {
      throw new Error("Job not found during control check");
    }
    if (state.cancel_requested) {
      throw new Error("Job cancelled by operator");
    }
    if (!state.pause_requested) {
      return;
    }
    await updateJobStatus({ status: "paused" });
    await emit("job.updated", { id: jobId, status: "paused" });
    await updateWorker("paused");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function updateStep(sequence: number, data: Record<string, unknown>) {
  const mappings: Record<string, string> = {
    status: "status",
    retryCount: "retry_count",
    failureType: "failure_type",
    failureMessage: "failure_message",
    result: "result",
    startedAt: "started_at",
    finishedAt: "finished_at"
  };
  const keys = Object.keys(data);
  const sets: string[] = [];
  const values: unknown[] = [jobId, sequence];
  let idx = 3;
  for (const key of keys) {
    const column = mappings[key];
    if (!column) continue;
    const isJson = key === "result";
    sets.push(`${column} = ${isJson ? `$${idx}::jsonb` : `$${idx}`}`);
    values.push(isJson ? JSON.stringify(data[key] ?? null) : data[key]);
    idx += 1;
  }
  sets.push(`updated_at = NOW()`);
  await pool.query(
    `UPDATE agent_steps SET ${sets.join(", ")} WHERE job_id = $1 AND sequence = $2`,
    values
  );
}

async function createApproval(step: BrowserStep, sequence: number, reason: string) {
  const approvalId = `apr_${Date.now()}_${sequence}`;
  await pool.query(
    `INSERT INTO approval_requests (
      id, job_id, step_id, action, target, policy_reason, status, expires_at, created_at, updated_at
    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'pending', $7, NOW(), NOW())`,
    [
      approvalId,
      jobId,
      `${jobId}:${sequence}`,
      step.action,
      JSON.stringify(step.target || null),
      reason,
      new Date(Date.now() + 2 * 60 * 1000)
    ]
  );
  await updateJobStatus({ status: "waiting_approval" });
  const approval = await queryOne(
    `SELECT id, action, policy_reason AS "policyReason", job_id AS "jobId", status
     FROM approval_requests WHERE id = $1`,
    [approvalId]
  );
  await emit("approval.created", approval);
  return approvalId;
}

async function waitForApproval(approvalId: string) {
  while (true) {
    const approval = await queryOne<{ status: string }>(
      `SELECT status FROM approval_requests WHERE id = $1`,
      [approvalId]
    );
    if (!approval) {
      throw new Error("Approval not found");
    }
    if (approval.status === "approved") {
      await updateJobStatus({ status: "running" });
      return "approved" as const;
    }
    if (approval.status === "rejected" || approval.status === "expired") {
      return "rejected" as const;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function lookupCorrection(domain: string, actionType: string): Promise<SelectorDescriptor | null> {
  const row = await queryOne<{ correctedSelector: SelectorDescriptor | null }>(
    `SELECT corrected_selector AS "correctedSelector"
     FROM correction_memory
     WHERE domain = $1 AND action_type = $2 AND corrected_selector IS NOT NULL
     ORDER BY created_at DESC
     LIMIT 1`,
    [domain, actionType]
  );
  return row?.correctedSelector || null;
}

async function insertReplay(sequence: number, eventType: string, payload: Record<string, unknown>) {
  await pool.query(
    `INSERT INTO replay_chunks (id, job_id, sequence, event_type, payload, created_at)
     VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
     ON CONFLICT (job_id, sequence) DO UPDATE
     SET event_type = EXCLUDED.event_type, payload = EXCLUDED.payload`,
    [`replay_${jobId}_${sequence}`, jobId, sequence, eventType, JSON.stringify(payload)]
  );
}

async function createCorrection({
  step,
  failureType,
  message,
  correctedSelector,
  domain
}: {
  step: BrowserStep;
  failureType: string;
  message: string;
  correctedSelector?: SelectorDescriptor | null;
  domain?: string;
}) {
  const resolvedDomain = domain || (step.url ? new URL(step.url).hostname : "unknown");
  await pool.query(
    `INSERT INTO correction_memory (
      id, job_id, domain, action_type, failure_type, failed_selector, corrected_selector, notes, created_at
    ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, NOW())`,
    [
      `corr_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
      jobId,
      resolvedDomain,
      step.action,
      failureType,
      JSON.stringify(step.target || null),
      JSON.stringify(correctedSelector || null),
      message
    ]
  );
}

async function insertMetric(metricKey: string, metricValue: number, labels?: Record<string, unknown>) {
  await pool.query(
    `INSERT INTO metric_rollups (id, job_id, metric_key, metric_value, labels, created_at)
     VALUES ($1, $2, $3, $4, $5::jsonb, NOW())`,
    [`metric_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`, jobId, metricKey, metricValue, JSON.stringify(labels || {})]
  );
}

async function main() {
  const input = await getJobInput();
  await seedReplaySequence();
  const engine = new PlaywrightExecutionEngine();

  await updateWorker("running", { jobId });
  await updateJobStatus({
    status: "running",
    startedAt: new Date(),
    currentStep: "Planning",
    progress: 0,
    workerId
  });
  await emit("job.updated", { id: jobId, status: "running", progress: 0 });

  try {
    const startedAt = Date.now();
    const result = await engine.run(input, {
      onStepStart: async (step, sequence) => {
        await honorControls();
        await updateWorker("running", { sequence });
        await updateJobStatus({
          currentStepIndex: sequence,
          currentStep: step.name,
          progress: Math.round((sequence / Math.max(input.steps.length, 1)) * 100),
          status: "running"
        });
        await updateStep(sequence, { status: "running", startedAt: new Date() });
        await emit("job.updated", { id: jobId, currentStep: step.name, progress: Math.round((sequence / Math.max(input.steps.length, 1)) * 100), status: "running" });
      },
      onStepUpdate: async ({ step, sequence, status, retryCount, failureType, message }) => {
        await updateStep(sequence, {
          status: status === "succeeded" ? "succeeded" : status === "waiting_approval" ? "waiting_approval" : "failed",
          retryCount,
          failureType,
          failureMessage: message,
          result: { message },
          finishedAt: status === "running" ? null : new Date()
        });
        await updateJobStatus({ retryCount });
        if (status === "failed" && retryCount >= 4 && step.target) {
          await createCorrection({
            step,
            failureType,
            message
          });
        }
        if (status === "waiting_approval") {
          await emit("approval.created", { jobId, sequence, action: step.action });
        } else {
          await emit("job.updated", { id: jobId, status, currentStep: step.name });
        }
      },
      onReplayEvent: async (event) => {
        replaySequence += 1;
        await insertReplay(replaySequence, event.eventType, {
          ...event.payload,
          stepSequence: event.sequence
        });
        await emit("replay.updated", { jobId });
      },
      awaitApproval: async ({ step, sequence, reason }) => {
        const approvalId = await createApproval(step, sequence, reason);
        return waitForApproval(approvalId);
      },
      lookupCorrection: async ({ domain, actionType }) => lookupCorrection(domain, actionType),
      rememberCorrection: async ({ step, domain, failureType, correctedSelector, reason }) => {
        await createCorrection({
          step,
          domain,
          failureType,
          correctedSelector,
          message: reason
        });
      }
    });

    await updateJobStatus({
      status: "completed",
      progress: 100,
      completedAt: new Date(),
      currentStep: "Completed",
      result
    });
    await updateWorker("completed", { result });
    await insertMetric("job_duration_ms", Date.now() - startedAt, { status: "completed" });
    await emit("job.updated", { id: jobId, status: "completed", progress: 100, currentStep: "Completed" });
  } catch (error) {
    const message = String((error as Error)?.message || error);
    await updateJobStatus({
      status: message.includes("cancelled") ? "cancelled" : "failed",
      error: message,
      completedAt: new Date()
    });
    await updateWorker("failed", { error: message });
    await insertMetric("job_failure", 1, { error: message });
    await emit("job.updated", { id: jobId, status: message.includes("cancelled") ? "cancelled" : "failed", error: message });
    throw error;
  } finally {
    await pool.end().catch(() => undefined);
    socket.close();
  }
}

main().catch((error) => {
  logger.error({ message: String(error?.message || error), stack: error?.stack }, "local worker failed");
  console.error(error);
  process.exit(1);
});
