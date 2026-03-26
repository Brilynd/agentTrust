CREATE TYPE "AgentJobStatus" AS ENUM (
  'queued',
  'running',
  'waiting_approval',
  'paused',
  'completed',
  'failed',
  'cancelled'
);

CREATE TYPE "AgentStepStatus" AS ENUM (
  'pending',
  'running',
  'succeeded',
  'failed',
  'skipped',
  'waiting_approval'
);

CREATE TYPE "ApprovalStatus" AS ENUM (
  'pending',
  'approved',
  'rejected',
  'expired'
);

CREATE TYPE "FailureType" AS ENUM (
  'NONE',
  'ELEMENT_NOT_FOUND',
  'TIMEOUT',
  'NOT_INTERACTABLE',
  'NAVIGATION_ERROR',
  'POLICY_DENIED',
  'VERIFICATION_FAILED',
  'UNKNOWN'
);

CREATE TABLE "AgentJob" (
  "id" TEXT PRIMARY KEY,
  "externalRef" TEXT UNIQUE,
  "agentId" TEXT,
  "sessionId" TEXT,
  "promptId" TEXT,
  "task" TEXT NOT NULL,
  "input" JSONB NOT NULL,
  "plan" JSONB,
  "status" "AgentJobStatus" NOT NULL DEFAULT 'queued',
  "currentStepIndex" INTEGER NOT NULL DEFAULT 0,
  "progress" INTEGER NOT NULL DEFAULT 0,
  "currentStep" TEXT,
  "result" JSONB,
  "error" TEXT,
  "retryCount" INTEGER NOT NULL DEFAULT 0,
  "maxRetries" INTEGER NOT NULL DEFAULT 4,
  "startedAt" TIMESTAMP(3),
  "completedAt" TIMESTAMP(3),
  "lastHeartbeatAt" TIMESTAMP(3),
  "pauseRequested" BOOLEAN NOT NULL DEFAULT FALSE,
  "cancelRequested" BOOLEAN NOT NULL DEFAULT FALSE,
  "metadata" JSONB,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "AgentStep" (
  "id" TEXT PRIMARY KEY,
  "jobId" TEXT NOT NULL REFERENCES "AgentJob"("id") ON DELETE CASCADE,
  "sequence" INTEGER NOT NULL,
  "name" TEXT NOT NULL,
  "action" TEXT NOT NULL,
  "selector" JSONB,
  "selectorText" TEXT,
  "payload" JSONB,
  "verification" JSONB,
  "result" JSONB,
  "status" "AgentStepStatus" NOT NULL DEFAULT 'pending',
  "retryCount" INTEGER NOT NULL DEFAULT 0,
  "failureType" "FailureType" NOT NULL DEFAULT 'NONE',
  "failureMessage" TEXT,
  "hash" TEXT NOT NULL,
  "previousHash" TEXT NOT NULL,
  "startedAt" TIMESTAMP(3),
  "finishedAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "ApprovalRequest" (
  "id" TEXT PRIMARY KEY,
  "jobId" TEXT NOT NULL REFERENCES "AgentJob"("id") ON DELETE CASCADE,
  "stepId" TEXT,
  "action" TEXT NOT NULL,
  "target" JSONB,
  "policyReason" TEXT,
  "requestedBy" TEXT,
  "status" "ApprovalStatus" NOT NULL DEFAULT 'pending',
  "decisionBy" TEXT,
  "decisionComment" TEXT,
  "expiresAt" TIMESTAMP(3),
  "decidedAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "ReplayChunk" (
  "id" TEXT PRIMARY KEY,
  "jobId" TEXT NOT NULL REFERENCES "AgentJob"("id") ON DELETE CASCADE,
  "stepId" TEXT,
  "sequence" INTEGER NOT NULL,
  "eventType" TEXT NOT NULL,
  "payload" JSONB NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "CorrectionMemory" (
  "id" TEXT PRIMARY KEY,
  "jobId" TEXT NOT NULL REFERENCES "AgentJob"("id") ON DELETE CASCADE,
  "domain" TEXT NOT NULL,
  "actionType" TEXT NOT NULL,
  "failureType" "FailureType" NOT NULL,
  "failedSelector" JSONB,
  "correctedSelector" JSONB,
  "notes" TEXT,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "MetricRollup" (
  "id" TEXT PRIMARY KEY,
  "jobId" TEXT NOT NULL REFERENCES "AgentJob"("id") ON DELETE CASCADE,
  "metricKey" TEXT NOT NULL,
  "metricValue" DOUBLE PRECISION NOT NULL,
  "labels" JSONB,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX "AgentStep_jobId_sequence_key" ON "AgentStep"("jobId", "sequence");
CREATE INDEX "AgentStep_jobId_status_idx" ON "AgentStep"("jobId", "status");
CREATE INDEX "ApprovalRequest_jobId_status_idx" ON "ApprovalRequest"("jobId", "status");
CREATE UNIQUE INDEX "ReplayChunk_jobId_sequence_key" ON "ReplayChunk"("jobId", "sequence");
CREATE INDEX "ReplayChunk_jobId_stepId_idx" ON "ReplayChunk"("jobId", "stepId");
CREATE INDEX "CorrectionMemory_domain_actionType_idx" ON "CorrectionMemory"("domain", "actionType");
CREATE INDEX "MetricRollup_jobId_metricKey_idx" ON "MetricRollup"("jobId", "metricKey");
