import { Queue } from "bullmq";
import IORedis from "ioredis";

const connection = new IORedis(process.env.REDIS_URL || "redis://127.0.0.1:6379", {
  maxRetriesPerRequest: null
});

export const agentQueue = new Queue("agenttrust-jobs", {
  connection,
  defaultJobOptions: {
    attempts: 4,
    removeOnComplete: 1000,
    removeOnFail: 1000
  }
});

export { connection as redisConnection };
