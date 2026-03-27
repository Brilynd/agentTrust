import { Queue, type JobsOptions, type Job } from "bullmq";
import IORedis from "ioredis";

let connection: IORedis | null = null;
let agentQueue: Queue | null = null;

function getRedisUrl() {
  return process.env.REDIS_URL || "redis://127.0.0.1:6379";
}

function createQueue() {
  if (!connection) {
    connection = new IORedis(getRedisUrl(), {
      maxRetriesPerRequest: null
    });
  }

  if (!agentQueue) {
    agentQueue = new Queue("agenttrust-jobs", {
      connection,
      defaultJobOptions: {
        attempts: 4,
        removeOnComplete: 1000,
        removeOnFail: 1000
      }
    });
  }

  return agentQueue;
}

export async function enqueueAgentJob(name: string, data: Record<string, unknown>, options?: JobsOptions) {
  return createQueue().add(name, data, options);
}

export async function getAgentQueueJob(jobId: string): Promise<Job | undefined> {
  return createQueue().getJob(jobId);
}

export function hasLegacyQueueConfigured() {
  return Boolean(process.env.REDIS_URL);
}
