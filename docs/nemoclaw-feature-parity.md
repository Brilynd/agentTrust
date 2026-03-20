# NeMoClaw Feature Parity

This document tracks what was preserved, what changed, what was weakened, and how to recover parity.

## Summary Table

| Feature | Status | Notes |
|---|---|---|
| Pre-execution action interception | Preserved | All guarded mutating actions call AgentTrust before execution |
| Policy engine and risk scoring | Preserved | Existing backend middleware remains authoritative |
| Human approval for high-risk actions | Preserved | Approval flow still blocks execution until approved |
| Prompt progress / live thinking | Preserved with UX change | Progress remains in prompt records, now surfaced via terminal monitor |
| Action screenshots | Preserved | Runtime uploads post-action screenshots back into existing action records |
| Audit chain | Preserved | Existing backend audit service still writes the chain |
| External API mediation | Preserved | Calls still route through AgentTrust backend |
| Session ownership | Improved | Added explicit session-claim route for non-extension operators |
| Chrome extension monitoring UX | Changed | Replaced by terminal approval presenter + monitor for this integration |
| Selenium-specific browser recovery tricks | Partial | Only portable behavior was moved into the generic OpenClaw runtime |
| Passkey suppression / custom Chrome hacks | Partial | Requires OpenClaw-native browser hooks to fully restore |

## Preserved Features

### 1. Pre-execution interception

Status: Preserved

Why:

- `integrations/nemoclaw/src/runtime.js` routes `guarded_navigate`, `guarded_click`, `guarded_type`, `guarded_submit`, and `guarded_external_api_call` through `AgentTrustBridge.executeAction()` or `AgentTrustBridge.callExternalApi()` before execution.

How to verify:

- Trigger a blocked domain or high-risk action and confirm the browser/API call does not run until approval is granted.

### 2. Approval semantics

Status: Preserved

Why:

- The backend approval lifecycle remains in `backend/src/routes/approvals.js`.
- The new terminal presenter consumes the same pending approvals and submits the same approve/deny decisions.

How to get back the original UX:

- Build a small web dashboard or OpenShell pane that reads the same approvals endpoints.
- The backend contract does not need to change again for that.

### 3. Live thinking / progress

Status: Preserved with UX change

Why:

- The runtime continues writing prompt progress through `PATCH /api/prompts/:promptId`.
- `agenttrust-nemoclaw monitor` reads those prompt records and prints progress lines live.

What changed:

- The current implementation does not render the old Chrome popup UI.
- It is terminal-first rather than extension-first.

How to get the richer UI back:

- Build a web dashboard that reads session and prompt data from the existing backend routes.
- Or connect the same prompt feed into an OpenShell/OpenClaw panel if the host UI supports it.

### 4. Screenshots

Status: Preserved

Why:

- The runtime captures a post-action snapshot and uploads it through the existing screenshot patch route.
- The monitor can export screenshots to a local directory.

How to verify:

- Run `agenttrust-nemoclaw monitor --follow --screenshots-dir <dir>` and confirm images appear for action records.

## Changed Or Partial Features

### 5. Chrome extension dashboard

Status: Changed

What was lost:

- The exact extension popup/monitor/chat tab UX is not part of the NeMoClaw integration.

Why it changed:

- NeMoClaw/OpenClaw is a different runtime and operator surface.
- The extension was tightly coupled to the Selenium/Chrome path.

Security impact:

- None in the current implementation. Approval, progress, and screenshot data are still preserved.

Recovery path:

- Rebuild a web dashboard against existing `sessions`, `prompts`, `actions`, and `approvals` endpoints.
- Or keep the extension as an optional companion UI outside the NeMoClaw sandbox.

### 6. Selenium-specific browser behavior

Status: Partial

What was lost:

- Selenium-targeted logic like custom passkey suppression, highly specific retry logic, and Chrome-for-Testing lifecycle management is not reproduced here.

Why it changed:

- Those behaviors depended on Selenium/CDP implementation details rather than on the trust layer itself.

Security impact:

- Low for trust semantics.
- Medium for automation reliability on sites with complex login/passkey flows.

Recovery path:

- Extend the OpenClaw browser provider contract with site-specific helpers.
- Add OpenClaw-native equivalents for passkey suppression and advanced form recovery if the runtime supports them.

### 7. Exact DOM targeting semantics

Status: Partial

What changed:

- Element metadata now depends on the OpenClaw browser provider contract instead of Selenium element wrappers.

Risk:

- Different providers may expose different levels of target detail, which can slightly affect risk classification fidelity.

Recovery path:

- Ensure `getCurrentPage()` returns rich `elements` data and that guarded tools send detailed target metadata.
- If needed, add provider-side normalization to map OpenClaw element descriptors into AgentTrust's preferred target shape.

## New Security Improvement

### Explicit session claiming

Status: Added

What changed:

- `POST /api/sessions/:sessionId/claim` was added.

Why:

- The extension used to claim sessions implicitly when a user sent a command.
- NeMoClaw operator tooling needs a direct way to bind a session to an authenticated user.

Benefit:

- More explicit operator ownership without weakening the existing session/audit model.

## Remaining Gaps

These are the main gaps still outside strict parity:

1. There is no rich graphical dashboard yet for approvals and monitoring.
2. OpenClaw browser-provider integration is generic and expects the host runtime to implement the provider contract.
3. Advanced Selenium-only automation tricks are not yet ported.

## Recommended Next Restorations

1. Add a web dashboard for approvals, prompts, actions, and screenshots.
2. Implement a concrete OpenClaw browser provider adapter for the exact browser runtime you plan to use.
3. Add OpenClaw-native login helpers for passkeys, multi-step auth, and difficult site recovery flows.
