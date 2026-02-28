# Policy Configuration Guide

## Overview

AgentTrust uses JSON-based policies to define rules for agent actions. Policies are stored in `backend/config/policies.json` and can be updated via the API.

## Policy Structure

```json
{
  "allowed_domains": [],
  "blocked_domains": [],
  "high_risk_keywords": [],
  "medium_risk_keywords": [],
  "financial_domains": [],
  "requires_step_up": [],
  "domain_trust_profiles": {}
}
```

## Policy Fields

### allowed_domains

Array of domain strings that are explicitly allowed. If this array is empty, all domains are allowed (unless blocked). If populated, only listed domains are allowed.

**Example**:
```json
"allowed_domains": ["github.com", "slack.com", "example.com"]
```

### blocked_domains

Array of domain strings that are explicitly blocked. Actions on these domains will be denied.

**Example**:
```json
"blocked_domains": ["malicious-site.com", "phishing-site.net"]
```

### high_risk_keywords

Array of keywords that, when detected in action context, classify the action as high-risk.

**Example**:
```json
"high_risk_keywords": ["delete", "remove", "merge", "transfer", "confirm", "purchase"]
```

### medium_risk_keywords

Array of keywords that, when detected, classify the action as medium-risk.

**Example**:
```json
"medium_risk_keywords": ["submit", "post", "send", "update", "edit"]
```

### financial_domains

Array of domain patterns that indicate financial services. Actions on these domains receive additional risk scoring.

**Example**:
```json
"financial_domains": ["bank", "paypal", "stripe", "venmo", "chase", "wells fargo"]
```

### requires_step_up

Array of risk levels that require step-up authentication.

**Example**:
```json
"requires_step_up": ["high"]
```

This means all high-risk actions require user approval via step-up authentication.

### domain_trust_profiles

Object mapping domains to trust profiles. Each profile can customize risk assessment for that domain.

**Example**:
```json
"domain_trust_profiles": {
  "github.com": {
    "risk_multiplier": 0.5,
    "allowed_actions": ["click", "form_submit", "navigation"]
  },
  "slack.com": {
    "risk_multiplier": 0.7,
    "allowed_actions": ["click", "form_submit", "navigation"]
  }
}
```

**Profile Fields**:
- `risk_multiplier`: Multiplier applied to risk score (0.0 - 1.0)
- `allowed_actions`: Array of action types allowed on this domain

## Risk Classification Logic

The policy engine calculates risk scores based on:

1. **Base Score**: 0
2. **Domain Check**: +3 if financial domain
3. **Keyword Check**: +3 for high-risk keywords, +1 for medium-risk keywords
4. **Form Check**: +2 if password field detected
5. **Trust Profile**: Apply risk multiplier if domain has a profile

**Risk Levels**:
- `low`: Score < 1
- `medium`: Score 1-2
- `high`: Score ≥ 3
- `blocked`: Domain is in blocked list

## Example Policies

### Strict Policy (Enterprise)

```json
{
  "allowed_domains": ["github.com", "slack.com", "jira.company.com"],
  "blocked_domains": [],
  "high_risk_keywords": ["delete", "remove", "merge", "transfer", "purchase", "buy", "pay"],
  "medium_risk_keywords": ["submit", "post", "send"],
  "financial_domains": ["bank", "paypal", "stripe"],
  "requires_step_up": ["high", "medium"],
  "domain_trust_profiles": {
    "github.com": {
      "risk_multiplier": 0.3,
      "allowed_actions": ["click", "form_submit", "navigation"]
    }
  }
}
```

### Permissive Policy (Development)

```json
{
  "allowed_domains": [],
  "blocked_domains": [],
  "high_risk_keywords": ["delete", "remove"],
  "medium_risk_keywords": ["submit"],
  "financial_domains": [],
  "requires_step_up": ["high"],
  "domain_trust_profiles": {}
}
```

## Updating Policies

### Via API

```bash
curl -X PUT http://localhost:3000/api/policies \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d @policies.json
```

### Via File

Edit `backend/config/policies.json` directly and restart the server.

## Best Practices

1. **Start Permissive**: Begin with minimal restrictions and tighten as needed
2. **Use Allowlists**: For production, use `allowed_domains` to restrict access
3. **Regular Updates**: Review and update keyword lists based on observed actions
4. **Domain Profiles**: Create trust profiles for frequently used domains
5. **Test Changes**: Test policy changes in development before deploying

## Policy Validation

The system validates policies on load and update:

- All arrays must be arrays
- All strings must be non-empty (where applicable)
- Risk multipliers must be between 0.0 and 1.0
- Action types must be valid: `click`, `form_submit`, `navigation`

Invalid policies will cause the server to fail to start or reject the update.
