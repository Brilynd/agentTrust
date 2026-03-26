import { promises as fs } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";

import cors from "cors";
import express from "express";
import pinoHttp from "pino-http";

import { evaluatePolicy } from "@agenttrust/policy";
import type { AgentTaskInput, BotConfiguration, BrowserStep } from "@agenttrust/shared";

import { logger } from "./lib/logger";
import { prisma } from "./lib/prisma";
import { agentQueue } from "./queue";
import { emitPlatformEvent } from "./socket";

type JobContextMessage = {
  prompt: string;
  details?: Record<string, unknown>;
  createdAt: string;
};

const CONFIG_STORE_PATH = path.join(process.cwd(), "apps", "api", "data", "bot-configurations.json");

function createStepHashes(steps: BrowserStep[]) {
  let previousHash = "0";
  return steps.map((step, sequence) => {
    const hash = createHash("sha256")
      .update(JSON.stringify({ previousHash, step }))
      .digest("hex");
    const row = { sequence, hash, previousHash, step };
    previousHash = hash;
    return row;
  });
}

function normalizeJobInput(body: unknown): AgentTaskInput {
  const raw = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const details =
    raw.details && typeof raw.details === "object" && !Array.isArray(raw.details)
      ? (raw.details as Record<string, unknown>)
      : {};

  const merged = {
    ...details,
    ...raw,
    metadata: {
      ...((details.metadata as Record<string, unknown> | undefined) || {}),
      ...((raw.metadata as Record<string, unknown> | undefined) || {})
    }
  } as Record<string, unknown>;

  delete merged.details;

  const task = String(merged.task || "").trim();
  if (!task) {
    throw new Error("Task prompt is required");
  }

  const steps = Array.isArray(merged.steps) ? (merged.steps as BrowserStep[]) : [];
  if (steps.length === 0) {
    throw new Error("Job details JSON must include a non-empty steps array");
  }

  return {
    task,
    agentId: merged.agentId ? String(merged.agentId) : undefined,
    sessionId: merged.sessionId ? String(merged.sessionId) : undefined,
    promptId: merged.promptId ? String(merged.promptId) : undefined,
    allowedDomains: Array.isArray(merged.allowedDomains)
      ? merged.allowedDomains.map((value) => String(value))
      : undefined,
    steps,
    metadata:
      merged.metadata && typeof merged.metadata === "object"
        ? (merged.metadata as Record<string, unknown>)
        : undefined
  };
}

async function appendQueuedSteps(jobId: string, stepsToAppend: BrowserStep[]) {
  if (!stepsToAppend.length) {
    return;
  }

  const existingSteps = await prisma.agentStep.findMany({
    where: { jobId },
    orderBy: { sequence: "asc" }
  });
  const lastSequence = existingSteps.length;
  let previousHash = existingSteps.at(-1)?.hash || "0";
  const newStepRows = stepsToAppend.map((step, index) => {
    const hash = createHash("sha256")
      .update(JSON.stringify({ previousHash, step }))
      .digest("hex");
    const row = {
      sequence: lastSequence + index,
      hash,
      previousHash,
      step
    };
    previousHash = hash;
    return row;
  });

  await prisma.agentStep.createMany({
    data: newStepRows.map(({ sequence, hash, previousHash, step }) => ({
      jobId,
      sequence,
      name: step.name,
      action: step.action,
      selector: step.target,
      selectorText: step.target?.text || step.target?.name || step.target?.label || null,
      payload: step,
      verification: step.verification,
      hash,
      previousHash
    }))
  });
}

async function readConfigurations(): Promise<BotConfiguration[]> {
  try {
    const raw = await fs.readFile(CONFIG_STORE_PATH, "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as BotConfiguration[]) : [];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw error;
  }
}

async function writeConfigurations(configs: BotConfiguration[]) {
  await fs.mkdir(path.dirname(CONFIG_STORE_PATH), { recursive: true });
  await fs.writeFile(CONFIG_STORE_PATH, JSON.stringify(configs, null, 2), "utf8");
}

export function createApp() {
  const app = express();

  app.use(cors({ origin: true, credentials: true }));
  app.use(express.json({ limit: "10mb" }));
  app.use(pinoHttp({ logger }));

  app.get("/health", async (_req, res) => {
    const [jobCount, approvalCount] = await Promise.all([
      prisma.agentJob.count(),
      prisma.approvalRequest.count({ where: { status: "pending" } })
    ]);
    res.json({ ok: true, service: "agenttrust-platform-api", jobCount, approvalCount });
  });

  app.post("/api/jobs", async (req, res, next) => {
    try {
      const input = normalizeJobInput(req.body);
      const steps = input.steps || [];
      const hashedSteps = createStepHashes(steps);
      const job = await prisma.agentJob.create({
        data: {
          task: input.task,
          agentId: input.agentId,
          sessionId: input.sessionId,
          promptId: input.promptId,
          input,
          plan: { steps },
          status: "queued",
          metadata: input.metadata,
          steps: {
            create: hashedSteps.map(({ sequence, hash, previousHash, step }) => ({
              sequence,
              name: step.name,
              action: step.action,
              selector: step.target,
              selectorText: step.target?.text || step.target?.name || step.target?.label || null,
              payload: step,
              verification: step.verification,
              hash,
              previousHash
            }))
          }
        },
        include: { steps: true }
      });

      await agentQueue.add(
        "task",
        { jobId: job.id, input },
        { jobId: job.id }
      );

      emitPlatformEvent("job.created", job);
      res.status(202).json({ success: true, job });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/jobs/:jobId/context", async (req, res, next) => {
    try {
      const jobId = req.params.jobId;
      const job = await prisma.agentJob.findUnique({ where: { id: jobId } });
      if (!job) {
        return res.status(404).json({ success: false, error: "Job not found" });
      }

      const prompt = String(req.body?.prompt || "").trim();
      const details =
        req.body?.details && typeof req.body.details === "object" && !Array.isArray(req.body.details)
          ? (req.body.details as Record<string, unknown>)
          : {};

      if (!prompt) {
        return res.status(400).json({ success: false, error: "Prompt is required" });
      }

      const existingMetadata =
        job.metadata && typeof job.metadata === "object"
          ? (job.metadata as Record<string, unknown>)
          : {};
      const existingMessages = Array.isArray(existingMetadata.operatorPrompts)
        ? (existingMetadata.operatorPrompts as JobContextMessage[])
        : [];

      const operatorMessage: JobContextMessage = {
        prompt,
        details,
        createdAt: new Date().toISOString()
      };

      const appendSteps = Array.isArray(details.appendSteps) ? (details.appendSteps as BrowserStep[]) : [];
      const existingInput =
        job.input && typeof job.input === "object" ? (job.input as Record<string, unknown>) : {};
      const existingInputSteps = Array.isArray(existingInput.steps)
        ? (existingInput.steps as BrowserStep[])
        : [];
      const updatedInput = {
        ...existingInput,
        operatorPrompts: [...existingMessages, operatorMessage],
        steps: [...existingInputSteps, ...appendSteps]
      };

      await prisma.agentJob.update({
        where: { id: jobId },
        data: {
          input: updatedInput,
          metadata: {
            ...existingMetadata,
            operatorPrompts: [...existingMessages, operatorMessage]
          }
        },
        include: {
          steps: { orderBy: { sequence: "asc" } },
          approvals: { orderBy: { createdAt: "desc" } },
          replays: { orderBy: { sequence: "asc" } }
        }
      });

      if (appendSteps.length > 0) {
        await appendQueuedSteps(jobId, appendSteps);
      }

      const queueJob = await agentQueue.getJob(jobId);
      if (queueJob) {
        await queueJob.updateData({
          ...queueJob.data,
          input: updatedInput
        });
      }

      const updatedJob = await prisma.agentJob.findUniqueOrThrow({
        where: { id: jobId },
        include: {
          steps: { orderBy: { sequence: "asc" } },
          approvals: { orderBy: { createdAt: "desc" } },
          replays: { orderBy: { sequence: "asc" } }
        }
      });

      emitPlatformEvent("job.context_added", { jobId, prompt: operatorMessage.prompt, details });
      emitPlatformEvent("job.updated", updatedJob);
      res.status(202).json({
        success: true,
        job: updatedJob,
        context: operatorMessage,
        appendedSteps: appendSteps.length
      });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/configurations", async (_req, res, next) => {
    try {
      const configurations = await readConfigurations();
      res.json({ success: true, configurations });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/configurations", async (req, res, next) => {
    try {
      const name = String(req.body?.name || "").trim();
      const task = String(req.body?.task || "").trim();
      const description = String(req.body?.description || "").trim();
      const details =
        req.body?.details && typeof req.body.details === "object" && !Array.isArray(req.body.details)
          ? (req.body.details as Record<string, unknown>)
          : null;

      if (!name || !task || !details) {
        return res.status(400).json({ success: false, error: "name, task, and details are required" });
      }

      const configurations = await readConfigurations();
      const now = new Date().toISOString();
      const configuration: BotConfiguration = {
        id: `cfg_${Date.now()}`,
        name,
        description: description || undefined,
        task,
        details,
        createdAt: now,
        updatedAt: now
      };

      configurations.unshift(configuration);
      await writeConfigurations(configurations);
      res.status(201).json({ success: true, configuration });
    } catch (error) {
      next(error);
    }
  });

  app.put("/api/configurations/:configId", async (req, res, next) => {
    try {
      const configurations = await readConfigurations();
      const idx = configurations.findIndex((entry) => entry.id === req.params.configId);
      if (idx === -1) {
        return res.status(404).json({ success: false, error: "Configuration not found" });
      }

      const existing = configurations[idx];
      const details =
        req.body?.details && typeof req.body.details === "object" && !Array.isArray(req.body.details)
          ? (req.body.details as Record<string, unknown>)
          : existing.details;

      configurations[idx] = {
        ...existing,
        name: String(req.body?.name || existing.name).trim(),
        description: String(req.body?.description || existing.description || "").trim() || undefined,
        task: String(req.body?.task || existing.task).trim(),
        details,
        updatedAt: new Date().toISOString()
      };

      await writeConfigurations(configurations);
      res.json({ success: true, configuration: configurations[idx] });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/configurations/:configId/launch", async (req, res, next) => {
    try {
      const configurations = await readConfigurations();
      const configuration = configurations.find((entry) => entry.id === req.params.configId);
      if (!configuration) {
        return res.status(404).json({ success: false, error: "Configuration not found" });
      }

      const input = normalizeJobInput({
        task: configuration.task,
        details: configuration.details
      });
      const steps = input.steps || [];
      const hashedSteps = createStepHashes(steps);
      const job = await prisma.agentJob.create({
        data: {
          task: input.task,
          agentId: input.agentId,
          sessionId: input.sessionId,
          promptId: input.promptId,
          input,
          plan: { steps },
          status: "queued",
          metadata: {
            ...(input.metadata || {}),
            configurationId: configuration.id,
            configurationName: configuration.name
          },
          steps: {
            create: hashedSteps.map(({ sequence, hash, previousHash, step }) => ({
              sequence,
              name: step.name,
              action: step.action,
              selector: step.target,
              selectorText: step.target?.text || step.target?.name || step.target?.label || null,
              payload: step,
              verification: step.verification,
              hash,
              previousHash
            }))
          }
        },
        include: { steps: true }
      });

      await agentQueue.add("task", { jobId: job.id, input }, { jobId: job.id });
      emitPlatformEvent("job.created", job);
      res.status(202).json({ success: true, job, configuration });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/jobs", async (_req, res, next) => {
    try {
      const jobs = await prisma.agentJob.findMany({
        orderBy: { createdAt: "desc" },
        include: {
          steps: { orderBy: { sequence: "asc" } },
          approvals: true
        }
      });
      res.json({ success: true, jobs });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/jobs/:jobId", async (req, res, next) => {
    try {
      const job = await prisma.agentJob.findUnique({
        where: { id: req.params.jobId },
        include: {
          steps: { orderBy: { sequence: "asc" } },
          approvals: { orderBy: { createdAt: "desc" } },
          replays: { orderBy: { sequence: "asc" } }
        }
      });
      if (!job) {
        return res.status(404).json({ success: false, error: "Job not found" });
      }
      res.json({ success: true, job });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/jobs/:jobId/pause", async (req, res, next) => {
    try {
      const job = await prisma.agentJob.update({
        where: { id: req.params.jobId },
        data: { pauseRequested: true, status: "paused" }
      });
      emitPlatformEvent("job.updated", job);
      res.json({ success: true, job });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/jobs/:jobId/resume", async (req, res, next) => {
    try {
      const job = await prisma.agentJob.update({
        where: { id: req.params.jobId },
        data: { pauseRequested: false, status: "running" }
      });
      emitPlatformEvent("job.updated", job);
      res.json({ success: true, job });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/jobs/:jobId/cancel", async (req, res, next) => {
    try {
      const queueJob = await agentQueue.getJob(req.params.jobId);
      if (queueJob) {
        await queueJob.remove().catch(() => undefined);
      }
      const job = await prisma.agentJob.update({
        where: { id: req.params.jobId },
        data: { cancelRequested: true, status: "cancelled", completedAt: new Date() }
      });
      emitPlatformEvent("job.updated", job);
      res.json({ success: true, job });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/approvals", async (_req, res, next) => {
    try {
      const approvals = await prisma.approvalRequest.findMany({
        where: { status: "pending" },
        orderBy: { createdAt: "desc" }
      });
      res.json({ success: true, approvals });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/approvals/:approvalId", async (req, res, next) => {
    try {
      const approval = await prisma.approvalRequest.findUnique({
        where: { id: req.params.approvalId }
      });
      if (!approval) {
        return res.status(404).json({ success: false, error: "Approval not found" });
      }
      res.json({ success: true, approval });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/approvals/:approvalId/decision", async (req, res, next) => {
    try {
      const approved = !!req.body?.approved;
      const approval = await prisma.approvalRequest.update({
        where: { id: req.params.approvalId },
        data: {
          status: approved ? "approved" : "rejected",
          decisionBy: req.body?.decisionBy || "dashboard",
          decisionComment: req.body?.decisionComment || null,
          decidedAt: new Date()
        }
      });
      await prisma.agentJob.update({
        where: { id: approval.jobId },
        data: { status: approved ? "running" : "failed" }
      });
      emitPlatformEvent("approval.updated", approval);
      res.json({ success: true, approval });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/replays/:jobId", async (req, res, next) => {
    try {
      const replay = await prisma.replayChunk.findMany({
        where: { jobId: req.params.jobId },
        orderBy: { sequence: "asc" }
      });
      res.json({ success: true, replay });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/corrections", async (req, res, next) => {
    try {
      const corrections = await prisma.correctionMemory.findMany({
        where: {
          domain: typeof req.query.domain === "string" ? req.query.domain : undefined,
          actionType: typeof req.query.actionType === "string" ? req.query.actionType : undefined
        },
        orderBy: { createdAt: "desc" }
      });
      res.json({ success: true, corrections });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/corrections", async (req, res, next) => {
    try {
      const correction = await prisma.correctionMemory.create({
        data: {
          jobId: req.body.jobId,
          domain: req.body.domain,
          actionType: req.body.actionType,
          failureType: req.body.failureType || "UNKNOWN",
          failedSelector: req.body.failedSelector || undefined,
          correctedSelector: req.body.correctedSelector || undefined,
          notes: req.body.notes || null
        }
      });
      emitPlatformEvent("correction.created", correction);
      res.status(201).json({ success: true, correction });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/metrics/summary", async (_req, res, next) => {
    try {
      const [totalJobs, completedJobs, failedJobs, waitingApproval, jobs] = await Promise.all([
        prisma.agentJob.count(),
        prisma.agentJob.count({ where: { status: "completed" } }),
        prisma.agentJob.count({ where: { status: "failed" } }),
        prisma.agentJob.count({ where: { status: "waiting_approval" } }),
        prisma.agentJob.findMany({
          select: { retryCount: true, startedAt: true, completedAt: true }
        })
      ]);
      const averageRetries =
        jobs.reduce((sum, job) => sum + job.retryCount, 0) / Math.max(jobs.length, 1);
      const executionDurations = jobs
        .filter((job) => job.startedAt && job.completedAt)
        .map((job) => job.completedAt!.getTime() - job.startedAt!.getTime());
      const averageExecutionMs =
        executionDurations.reduce((sum, value) => sum + value, 0) / Math.max(executionDurations.length, 1);

      const groupedFailures = await prisma.agentStep.groupBy({
        by: ["failureType"],
        _count: {
          _all: true
        }
      });
      const failureBreakdown = Object.fromEntries(
        groupedFailures.map((row) => [row.failureType, row._count._all])
      );

      res.json({
        success: true,
        metrics: {
          successRate: totalJobs === 0 ? 0 : completedJobs / totalJobs,
          totalJobs,
          completedJobs,
          failedJobs,
          waitingApproval,
          averageRetries,
          averageExecutionMs,
          failureBreakdown
        }
      });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/compat/sessions", async (req, res, next) => {
    try {
      const externalRef = req.body?.sessionId || `legacy-session-${Date.now()}`;
      const job = await prisma.agentJob.create({
        data: {
          externalRef,
          agentId: req.body?.agentId || "legacy-agent",
          task: req.body?.task || "Legacy AgentTrust session",
          input: req.body || {},
          status: "queued"
        }
      });
      res.status(201).json({
        success: true,
        session: {
          id: job.externalRef,
          mappedJobId: job.id,
          createdAt: job.createdAt
        }
      });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/sessions", async (req, res, next) => {
    try {
      const externalRef = req.body?.sessionId || `legacy-session-${Date.now()}`;
      const job = await prisma.agentJob.create({
        data: {
          externalRef,
          agentId: req.body?.agentId || "legacy-agent",
          task: req.body?.task || "Legacy AgentTrust session",
          input: req.body || {},
          status: "queued"
        }
      });
      res.status(201).json({
        success: true,
        session: {
          id: job.externalRef,
          mappedJobId: job.id,
          createdAt: job.createdAt
        }
      });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/compat/actions/evaluate", async (req, res, next) => {
    try {
      const policy = evaluatePolicy({
        type: req.body?.type || "click",
        url: req.body?.url,
        domain: req.body?.domain,
        target: req.body?.target,
        form: req.body?.form,
        allowedDomains: req.body?.allowedDomains
      });

      let approvalId: string | undefined;
      if (policy.decision === "require_approval" && req.body?.jobId) {
        const approval = await prisma.approvalRequest.create({
          data: {
            jobId: req.body.jobId,
            stepId: req.body?.stepId || null,
            action: req.body?.type || "click",
            target: req.body?.target || null,
            policyReason: policy.reason,
            status: "pending",
            expiresAt: new Date(Date.now() + 2 * 60 * 1000)
          }
        });
        approvalId = approval.id;
        await prisma.agentJob.update({
          where: { id: req.body.jobId },
          data: { status: "waiting_approval" }
        });
        emitPlatformEvent("approval.created", approval);
      }

      res.json({
        success: policy.decision !== "deny",
        status: policy.decision,
        riskLevel: policy.riskLevel,
        reason: policy.reason,
        approvalId
      });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/actions", async (req, res, next) => {
    try {
      const policy = evaluatePolicy({
        type: req.body?.type || "click",
        url: req.body?.url,
        domain: req.body?.domain,
        target: req.body?.target,
        form: req.body?.form,
        allowedDomains: req.body?.allowedDomains
      });

      let approvalId: string | undefined;
      if (policy.decision === "require_approval" && req.body?.jobId) {
        const approval = await prisma.approvalRequest.create({
          data: {
            jobId: req.body.jobId,
            stepId: req.body?.stepId || null,
            action: req.body?.type || "click",
            target: req.body?.target || null,
            policyReason: policy.reason,
            status: "pending",
            expiresAt: new Date(Date.now() + 2 * 60 * 1000)
          }
        });
        approvalId = approval.id;
      }

      res.json({
        success: policy.decision !== "deny",
        status: policy.decision,
        riskLevel: policy.riskLevel,
        reason: policy.reason,
        approvalId
      });
    } catch (error) {
      next(error);
    }
  });

  app.post("/api/compat/openclaw/jobs", async (req, res, next) => {
    try {
      const payload = req.body as AgentTaskInput;
      const response = await fetch(`${req.protocol}://${req.get("host")}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      res.status(response.status).json(data);
    } catch (error) {
      next(error);
    }
  });

  app.use((error: Error, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    logger.error({ error }, "platform api error");
    res.status(500).json({ success: false, error: error.message });
  });

  return app;
}
