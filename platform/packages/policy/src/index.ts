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

const HIGH_RISK_TERMS = [
  "delete",
  "remove",
  "transfer",
  "payment",
  "billing",
  "checkout",
  "submit",
  "authorize",
  "send",
  "confirm"
];

const FORM_TERMS = ["card", "password", "security code", "cvv", "address", "email"];

function selectorText(target?: SelectorDescriptor): string {
  return [
    target?.role,
    target?.name,
    target?.text,
    target?.label,
    target?.placeholder,
    target?.selector
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function getDomain(input?: string): string {
  if (!input) return "";
  try {
    return new URL(input).hostname.toLowerCase();
  } catch {
    return input.toLowerCase();
  }
}

export function evaluatePolicy(action: ProposedAction): PolicyEvaluation {
  const domain = getDomain(action.domain || action.url);
  const allowed = new Set((action.allowedDomains || []).map((value) => value.toLowerCase()));
  const selector = selectorText(action.target);
  const combined = `${action.type} ${domain} ${selector}`.toLowerCase();

  if (allowed.size > 0 && domain && !Array.from(allowed).some((entry) => domain.endsWith(entry))) {
    return {
      decision: "deny",
      riskLevel: "high",
      reason: `Domain ${domain} is not in the allow-list`
    };
  }

  if (action.type === "goto" && !domain) {
    return {
      decision: "deny",
      riskLevel: "high",
      reason: "Navigation is missing a valid domain"
    };
  }

  if (FORM_TERMS.some((term) => combined.includes(term))) {
    return {
      decision: "require_approval",
      riskLevel: "high",
      reason: "Sensitive form interaction requires human approval"
    };
  }

  if (HIGH_RISK_TERMS.some((term) => combined.includes(term))) {
    return {
      decision: "require_approval",
      riskLevel: "high",
      reason: "High-risk action matched protected policy terms"
    };
  }

  if (action.type === "type" || action.type === "press") {
    return {
      decision: "allow",
      riskLevel: "medium",
      reason: "Interactive form step allowed with logging"
    };
  }

  return {
    decision: "allow",
    riskLevel: "low",
    reason: "Action allowed"
  };
}
