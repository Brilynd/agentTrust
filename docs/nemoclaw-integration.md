# AgentTrust NeMoClaw Integration

## Overview

This integration ports `AgentTrust` toward a native OpenClaw/NeMoClaw runtime without removing the existing security control plane.

The core rule stays the same:

1. The agent proposes an action.
2. `AgentTrust` validates it before execution.
3. The action is either allowed, denied, or blocked pending approval.
4. If it runs, the action is audited and its screenshot is attached afterward.

The implementation lives in:

- `integrations/nemoclaw/package.json`
- `integrations/nemoclaw/openclaw.plugin.json`
- `integrations/nemoclaw/src/`
- `integrations/nemoclaw/blueprint/blueprint.yaml`

## What Was Added

### Guarded runtime

`integrations/nemoclaw/src/runtime.js`

Provides a native runtime wrapper for OpenClaw-compatible browser tooling:

- `guarded_navigate`
- `guarded_click`
- `guarded_type`
- `guarded_submit`
- `guarded_open_tab`
- `guarded_switch_tab`
- `guarded_extract_page`
- `guarded_capture_screenshot`
- `guarded_external_api_call`

All mutating browser and API actions pass through the existing AgentTrust backend before they execute.

### Backend bridge

`integrations/nemoclaw/src/agenttrust-client.js`

Reuses the current backend contract for:

- Auth0 machine-to-machine auth
- session creation
- prompt creation and progress updates
- action enforcement
- approval waiting / retry
- screenshot upload
- external API proxying

### Browser adapter contract

`integrations/nemoclaw/src/browser-adapter.js`

The NeMoClaw/OpenClaw browser provider must expose:

- `navigate({ url })`
- `click({ target })`
- `type({ target, text, clearFirst, pressEnter })`
- `submit({ target })`
- `openTab({ url, label })`
- `switchTab({ label, index })`
- `getCurrentPage()`

`getCurrentPage()` should return:

```js
{
  url,
  title,
  text,
  untrustedContent,
  screenshot,
  elements,
  domain,
  activeTab,
  tabs
}
```

That lets AgentTrust keep inspecting page text, targets, and screenshots before or immediately after execution.

### Operator approval and monitoring tools

`integrations/nemoclaw/src/approval-presenter.js`

- Polls pending approvals
- prompts the operator in the terminal
- submits approve/deny decisions back to AgentTrust

`integrations/nemoclaw/src/session-monitor.js`

- loads sessions and prompts with user auth
- prints progress/thinking lines
- prints action/risk status
- can export screenshots to disk

`integrations/nemoclaw/src/cli.js`

Adds CLI commands:

```bash
agenttrust-nemoclaw approvals --email <email> --password <password> [--session <id>]
agenttrust-nemoclaw monitor --email <email> --password <password> --session <id> --follow [--screenshots-dir <dir>]
agenttrust-nemoclaw send --email <email> --password <password> --session <id> --message "..."
```

## Backend Change

Added explicit session claiming in:

- `backend/src/routes/sessions.js`

New endpoint:

```text
POST /api/sessions/:sessionId/claim
```

This lets a NeMoClaw operator bind an agent-created session to an authenticated user without relying on the Chrome extension path to do it implicitly.

## Security Invariants Preserved

The following behavior remains owned by the existing backend:

- pre-execution policy enforcement
- prompt-injection / malicious-content inspection
- high-risk approval gating
- audit log creation
- SHA-256 hash-chain continuity
- screenshot attachment to actions
- external API risk checks and approval flow
- prompt/session tracking

## Setup

### 1. Runtime prerequisites

NeMoClaw should be run on:

- Linux, or
- WSL2 Ubuntu 22.04+ on Windows

### 2. Backend

Start the existing backend the same way as before:

```bash
cd agentTrust/backend
npm install
npm run dev
```

### 3. Integration package

```bash
cd agentTrust/integrations/nemoclaw
npm install
npm run check
```

### 4. Required environment

```env
AGENTTRUST_API_URL=http://localhost:3000/api

AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your_client_id
AUTH0_CLIENT_SECRET=your_client_secret
AUTH0_AUDIENCE=https://agenttrust.api

AGENTTRUST_USER_EMAIL=operator@example.com
AGENTTRUST_USER_PASSWORD=your-password
```

Store those values in `integrations/nemoclaw/env.local` or `.env` for the local helper scripts.

### 5. Wire into an OpenClaw browser provider

Example shape:

```js
const {
  AgentTrustBridge,
  OpenClawBrowserAdapter,
  AgentTrustOpenClawRuntime,
} = require('./integrations/nemoclaw/src');

const bridge = new AgentTrustBridge();
const browser = new OpenClawBrowserAdapter(openClawBrowserProvider);
const runtime = new AgentTrustOpenClawRuntime({
  agentTrust: bridge,
  browser,
});

await bridge.loginUser();
await runtime.startSession();
await runtime.startPrompt('Research AI agent security and create a GitHub issue');

const tools = runtime.createGuardedToolset();
```

In a native OpenClaw/NeMoClaw agent, register those guarded tools instead of raw browser mutation tools.

## Recommended Operating Model

Run three concurrent pieces:

1. Agent runtime using `AgentTrustOpenClawRuntime`
2. Approval presenter using `agenttrust-nemoclaw approvals`
3. Session monitor using `agenttrust-nemoclaw monitor --follow`

That preserves the old extension responsibilities with terminal-first tooling:

- approvals
- live progress / thinking
- audit visibility
- screenshot retrieval

## First Validation Flow

Use the current demo path first:

1. start a session
2. submit a prompt to research AI security risks
3. visit a live article
4. create a GitHub issue through the external API path
5. verify approval handling on the high-risk step
6. verify the monitor shows prompt progress and screenshots

## Related Document

See `docs/nemoclaw-feature-parity.md` for explicit parity, feature loss, and recovery notes.
