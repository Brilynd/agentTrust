import "dotenv/config";

import { Worker } from "bullmq";
import IORedis from "ioredis";
import pino from "pino";
import { io as createSocket } from "socket.io-client";

import { PlaywrightExecutionEngine } from "@agenttrust/engine";
import type { AgentTaskInput, BrowserStep, FailureType } from "@agenttrust/shared";
import { PrismaClient } from "@prisma/client";

const logger = pino({
  level: process.env.LOG_LEVEL || "info",
  base: { service: "agenttrust-platform-worker" }
});

const prisma = new PrismaClient();
const redis = new IORedis(process.env.REDIS_URL || "redis://127.0.0.1:6379", {
  maxRetriesPerRequest: null
});
const socket = createSocket(process.env.API_SOCKET_URL || "http://127.0.0.1:3200", {
  transports: ["websocket"]
});

async function emit(channel: string, payload: unknown) {
  socket.emit("platform:event", { channel, payload });
}

async function getControlState(jobId: string) {
  return prisma.agentJob.findUnique({
    where: { id: jobId },
    select: { pauseRequested: true, cancelRequested: true }
  });
}

async function honorControls(jobId: string) {
  while (true) {
    const state = await getControlState(jobId);
    if (!state) {
      throw new Error("Job not found during control check");
    }
    if (state.cancelRequested) {
      throw new Error("Job cancelled by operator");
    }
    if (!state.pauseRequested) {
      return;
    }
    await prisma.agentJob.update({
      where: { id: jobId },
      data: { status: "paused" }
    });
    await emit("job.updated", { id: jobId, status: "paused" });
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function createApproval(jobId: string, step: BrowserStep, sequence: number, reason: string) {
  const approval = await prisma.approvalRequest.create({
    data: {
      jobId,
      stepId: `${jobId}:${sequence}`,
      action: step.action,
      target: step.target || undefined,
      policyReason: reason,
      status: "pending",
      expiresAt: new Date(Date.now() + 2 * 60 * 1000)
    }
  });
  await prisma.agentJob.update({
    where: { id: jobId },
    data: { status: "waiting_approval" }
  });
  await emit("approval.created", approval);
  return approval;
}

async function waitForApproval(jobId: string, approvalId: string) {
  while (true) {
    const approval = await prisma.approvalRequest.findUnique({ where: { id: approvalId } });
    if (!approval) {
      throw new Error("Approval not found");
    }
    if (approval.status === "approved") {
      await prisma.agentJob.update({
        where: { id: jobId },
        data: { status: "running", pauseRequested: false }
      });
      return "approved" as const;
    }
    if (approval.status === "rejected" || approval.status === "expired") {
      return "rejected" as const;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

const worker = new Worker(
  "agenttrust-jobs",
  async (job) => {
    const jobId = String(job.data.jobId);
    const input = job.data.input as AgentTaskInput;
    const engine = new PlaywrightExecutionEngine();

    await prisma.agentJob.update({
      where: { id: jobId },
      data: {
        status: "running",
        startedAt: new Date(),
        lastHeartbeatAt: new Date(),
        currentStep: "Planning",
        progress: 0
      }
    });
    await emit("job.updated", { id: jobId, status: "running", progress: 0 });

    try {
      const result = await engine.run(input, {
        onStepStart: async (step, sequence) => {
          await honorControls(jobId);
          await prisma.agentJob.update({
            where: { id: jobId },
            data: {
              currentStepIndex: sequence,
              currentStep: step.name,
              progress: Math.round((sequence / Math.max(input.steps.length, 1)) * 100),
              lastHeartbeatAt: new Date(),
              status: "running"
            }
          });
          await prisma.agentStep.updateMany({
            where: { jobId, sequence },
            data: { status: "running", startedAt: new Date() }
          });
          await emit("step.updated", { jobId, sequence, step: step.name, status: "running" });
        },
        onStepUpdate: async ({ step, sequence, status, retryCount, failureType, message }) => {
          const stepData = await prisma.agentStep.updateMany({
            where: { jobId, sequence },
            data: {
              status:
                status === "succeeded"
                  ? "succeeded"
                  : status === "waiting_approval"
                    ? "waiting_approval"
                    : "failed",
              retryCount,
              failureType: failureType as FailureType,
              failureMessage: message,
              result: { message },
              finishedAt: status === "running" ? null : new Date()
            }
          });

          await prisma.agentJob.update({
            where: { id: jobId },
            data: {
              retryCount: retryCount > 0 ? retryCount : undefined,
              lastHeartbeatAt: new Date()
            }
          });

          if (status === "failed" && retryCount >= 4 && step.target) {
            const domain = step.url ? new URL(step.url).hostname : "unknown";
            await prisma.correctionMemory.create({
              data: {
                jobId,
                domain,
                actionType: step.action,
                failureType: failureType as FailureType,
                failedSelector: step.target,
                notes: message
              }
            });
          }

          await emit("step.updated", {
            jobId,
            sequence,
            step: step.name,
            status,
            retryCount,
            failureType,
            message
          });

          return stepData;
        },
        onReplayEvent: async (event) => {
          await prisma.replayChunk.create({
            data: {
              jobId,
              sequence: event.sequence,
              eventType: event.eventType,
              payload: event.payload
            }
          });
          await emit("replay.updated", { jobId, sequence: event.sequence });
        },
        awaitApproval: async ({ step, sequence, reason }) => {
          const approval = await createApproval(jobId, step, sequence, reason);
          return waitForApproval(jobId, approval.id);
        },
        lookupCorrection: async ({ domain, actionType }) => {
          const correction = await prisma.correctionMemory.findFirst({
            where: { domain, actionType },
            orderBy: { createdAt: "desc" }
          });
          return (correction?.correctedSelector as BrowserStep["target"]) || null;
        }
      });

      await prisma.metricRollup.createMany({
        data: [
          { jobId, metricKey: "success", metricValue: result.success ? 1 : 0 },
          { jobId, metricKey: "execution_time_ms", metricValue: Date.now() - job.timestamp }
        ]
      });

      await prisma.agentJob.update({
        where: { id: jobId },
        data: {
          status: "completed",
          progress: 100,
          result,
          completedAt: new Date(),
          currentStep: "Done"
        }
      });
      await emit("job.updated", { id: jobId, status: "completed", progress: 100 });
      return result;
    } catch (error) {
      await prisma.metricRollup.create({
        data: {
          jobId,
          metricKey: "failed",
          metricValue: 1,
          labels: { reason: String((error as Error)?.message || error) }
        }
      });
      await prisma.agentJob.update({
        where: { id: jobId },
        data: {
          status: "failed",
          error: String((error as Error)?.message || error),
          completedAt: new Date()
        }
      });
      await emit("job.updated", {
        id: jobId,
        status: "failed",
        error: String((error as Error)?.message || error)
      });
      throw error;
    } finally {
      await engine.dispose();
    }
  },
  {
    connection: redis
  }
);

worker.on("ready", () => {
  logger.info("worker ready");
});

worker.on("failed", (job, error) => {
  logger.error({ jobId: job?.id, error }, "job failed");
});
