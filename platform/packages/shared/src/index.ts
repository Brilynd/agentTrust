export type FailureType =
  | "NONE"
  | "ELEMENT_NOT_FOUND"
  | "TIMEOUT"
  | "NOT_INTERACTABLE"
  | "NAVIGATION_ERROR"
  | "GOAL_NOT_ACHIEVED"
  | "POLICY_DENIED"
  | "VERIFICATION_FAILED"
  | "UNKNOWN";

export type PolicyDecision = "allow" | "deny" | "require_approval";
export type AgentJobStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface SelectorDescriptor {
  role?: string;
  name?: string;
  text?: string;
  label?: string;
  placeholder?: string;
  selector?: string;
}

export interface BrowserStep {
  id: string;
  name: string;
  action: "goto" | "click" | "type" | "press" | "extract";
  goal?: string;
  optional?: boolean;
  url?: string;
  target?: SelectorDescriptor;
  value?: string;
  submit?: boolean;
  verification?: {
    urlIncludes?: string;
    textVisible?: string;
    selectorExists?: SelectorDescriptor;
    strict?: boolean;
  };
}

export interface AgentTaskInput {
  task: string;
  agentId?: string;
  sessionId?: string;
  promptId?: string;
  allowedDomains?: string[];
  steps: BrowserStep[];
  metadata?: Record<string, unknown>;
}

export interface OperatorPrompt {
  prompt: string;
  details?: Record<string, unknown>;
  createdAt: string;
}

export interface BotConfiguration {
  id: string;
  name: string;
  description?: string;
  task: string;
  details: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface StepLogEvent {
  jobId: string;
  stepId: string;
  sequence: number;
  action: string;
  selector?: SelectorDescriptor;
  result: string;
  retryCount: number;
  failureType: FailureType;
  timestamp: string;
}

export interface ApprovalPayload {
  jobId: string;
  stepId?: string;
  action: string;
  target?: SelectorDescriptor;
  reason: string;
}

export interface AgentMetricsSnapshot {
  successRate: number;
  totalJobs: number;
  completedJobs: number;
  failedJobs: number;
  waitingApproval: number;
  averageRetries: number;
  averageExecutionMs: number;
  failureBreakdown: Record<string, number>;
}

export interface ReplayEventPayload {
  sequence: number;
  eventType: string;
  payload: Record<string, unknown>;
}
