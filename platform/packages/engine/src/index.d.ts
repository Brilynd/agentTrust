import { type PolicyEvaluation } from "@agenttrust/policy";
import type { AgentTaskInput, BrowserStep, FailureType, ReplayEventPayload, SelectorDescriptor } from "@agenttrust/shared";
export interface EngineHooks {
    onStepStart?(step: BrowserStep, sequence: number): Promise<void> | void;
    onStepUpdate?(payload: {
        step: BrowserStep;
        sequence: number;
        status: "running" | "succeeded" | "failed" | "waiting_approval";
        retryCount: number;
        failureType: FailureType;
        message: string;
        policy?: PolicyEvaluation;
    }): Promise<void> | void;
    onReplayEvent?(event: ReplayEventPayload): Promise<void> | void;
    awaitApproval?(payload: {
        step: BrowserStep;
        sequence: number;
        reason: string;
    }): Promise<"approved" | "rejected">;
    lookupCorrection?(payload: {
        domain: string;
        actionType: string;
    }): Promise<SelectorDescriptor | null>;
}
export interface EngineRunResult {
    success: boolean;
    currentUrl: string;
    extractedText?: string;
}
export declare class PlaywrightExecutionEngine {
    private browser?;
    private context?;
    private page?;
    run(task: AgentTaskInput, hooks?: EngineHooks): Promise<EngineRunResult>;
    dispose(): Promise<void>;
}
