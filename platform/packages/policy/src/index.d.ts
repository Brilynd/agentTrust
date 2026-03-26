import type { PolicyDecision, SelectorDescriptor } from "@agenttrust/shared";
export interface ProposedAction {
    type: string;
    url?: string;
    domain?: string;
    target?: SelectorDescriptor;
    form?: Record<string, unknown>;
    allowedDomains?: string[];
}
export interface PolicyEvaluation {
    decision: PolicyDecision;
    riskLevel: "low" | "medium" | "high";
    reason: string;
}
export declare function evaluatePolicy(action: ProposedAction): PolicyEvaluation;
