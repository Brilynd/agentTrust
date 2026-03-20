# AgentTrust NeMoClaw Integration

## Overview

This integration ports `AgentTrust` toward a native OpenClaw/NeMoClaw runtime without removing the existing security control plane.

There are two deployment modes:

1. **Guarded runtime mode**
   - OpenClaw uses AgentTrust-wrapped tools.
   - Good for development and controlled integrations.
   - Not fully deterministic if raw mutating tools still exist elsewhere in the runtime.
2. **Deterministic executor mode**
   - OpenClaw/NeMoClaw provides the hosted sandbox and UI.
   - AgentTrust becomes the only actor allowed to mutate browser or write-capable API state.
   - This is the recommended production model for NVIDIA-hosted NeMoClaw.

For deterministic security, the core rule becomes:

1. The agent proposes an action.
2. `AgentTrust` validates it before execution.
3. If allowed, the backend issues a short-lived execution lease for that exact action.
4. The isolated executor verifies the lease and performs the action.
5. If it runs, the action is audited and its screenshot is attached afterward.

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

### Deterministic executor

`integrations/nemoclaw/src/executor-server.js`

This is the production-facing deterministic execution path:

- receives browser/API execution requests on a local loopback port
- verifies a signed execution lease before acting
- rejects actions whose lease is missing, expired, reused, or bound to different action parameters
- uploads screenshots back to AgentTrust after execution

Supporting files:

- `integrations/nemoclaw/src/browser-provider.example.js`
- `integrations/nemoclaw/env.example`

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

## Deterministic Deployment

If security is not optional, do **not** rely on skills or prompt instructions as enforcement.

Deterministic deployment requires all of the following:

- OpenClaw does not have direct raw browser mutation capability
- OpenClaw does not have direct write-capable API tools
- the executor is the only process that can mutate browser or API state
- the backend signs a lease for each exact action
- the executor verifies the lease before running
- no alternate shell/tool path exists for the agent to reproduce the same action

What NeMoClaw still provides in this model:

- OpenShell sandboxing
- network policy enforcement
- hosted NVIDIA runtime environment
- OpenClaw gateway/UI
- deployment and operational tooling

What AgentTrust provides:

- pre-execution action validation
- approvals
- audit and screenshots
- identity-bound execution
- deterministic execution control

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
AGENTTRUST_EXECUTOR_HOST=127.0.0.1
AGENTTRUST_EXECUTOR_PORT=3101
AGENTTRUST_EXECUTION_LEASE_SECRET=replace_with_long_random_secret
AGENTTRUST_BROWSER_PROVIDER_MODULE=/sandbox/agenttrust/workspace/browser-provider.js

AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your_client_id
AUTH0_CLIENT_SECRET=your_client_secret
AUTH0_AUDIENCE=https://agenttrust.api

AGENTTRUST_USER_EMAIL=operator@example.com
AGENTTRUST_USER_PASSWORD=your-password
```

Store those values in `integrations/nemoclaw/env.local` or `.env` for the local helper scripts.

The backend also needs:

```env
AGENTTRUST_EXECUTION_LEASE_SECRET=replace_with_long_random_secret
```

The backend and executor must use the **same** lease secret.

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

For deterministic deployment, the browser provider should only be imported by the executor, not by the LLM-facing runtime directly.

### 6. NVIDIA-hosted NeMoClaw / OpenShell Community

For NVIDIA-hosted NeMoClaw using OpenShell Community, the files you actually need to touch are outside this repo:

- `NemoClaw/scripts/nemoclaw-start.sh`
- `NemoClaw/Dockerfile`
- the active OpenShell sandbox policy file
- the live sandbox config at `/sandbox/.openclaw/openclaw.json`

Recommended first deployment topology:

- NVIDIA instance host:
  - PostgreSQL
  - AgentTrust backend
- OpenShell sandbox:
  - OpenClaw gateway/UI
  - AgentTrust executor
  - browser provider module

### 7. Modify `NemoClaw/scripts/nemoclaw-start.sh`

That startup wrapper should:

- export `AGENTTRUST_API_URL`
- export `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_AUDIENCE`
- export `AGENTTRUST_USER_EMAIL`, `AGENTTRUST_USER_PASSWORD`
- export `AGENTTRUST_EXECUTION_LEASE_SECRET`
- ensure `/sandbox/agenttrust/workspace` exists
- patch `/sandbox/.openclaw/openclaw.json` so OpenClaw sees:
  - `agents.defaults.workspace = /sandbox/agenttrust/workspace`
  - `skills.load.extraDirs = ['/sandbox/.openclaw/skills/agenttrust']`
- start `agenttrust-executor`
- start `openclaw gateway run`

### 8. Modify `NemoClaw/Dockerfile`

The sandbox image must contain:

- the AgentTrust NeMoClaw integration code
- the browser provider module referenced by `AGENTTRUST_BROWSER_PROVIDER_MODULE`
- browser runtime dependencies needed by the executor

The sandbox image should copy the integration into a stable path such as:

- `/opt/agenttrust`
- `/sandbox/agenttrust/workspace`

### 9. Modify the OpenShell policy

The sandbox policy should allow only the endpoints needed for:

- AgentTrust backend
- Auth0
- NVIDIA inference routing
- explicitly-approved provider APIs such as GitHub or Google

Do **not** broadly allow browser/API mutation to arbitrary destinations.

### 10. Modify `/sandbox/.openclaw/openclaw.json`

This is the live OpenClaw config inside the sandbox.

Required fields:

```json
{
  "agents": {
    "defaults": {
      "workspace": "/sandbox/agenttrust/workspace"
    }
  },
  "skills": {
    "load": {
      "extraDirs": ["/sandbox/.openclaw/skills/agenttrust"]
    }
  }
}
```

This does **not** provide deterministic security on its own.
It only points OpenClaw at the correct AgentTrust-related paths.

### 11. Start the executor

From inside the sandbox or from `nemoclaw-start.sh`:

```bash
node /opt/agenttrust/integrations/nemoclaw/src/executor-server.js
```

Or from the integration package:

```bash
cd /opt/agenttrust/integrations/nemoclaw
npm run executor
```

### 12. Browser provider module

Set:

```env
AGENTTRUST_BROWSER_PROVIDER_MODULE=/sandbox/agenttrust/workspace/browser-provider.js
```

Use `integrations/nemoclaw/src/browser-provider.example.js` as the starting point.
Replace it with the actual browser bridge for your sandbox image.

### 13. Raw tool removal

For deterministic deployment, the active agent must not have:

- raw browser click/type/submit tools
- raw computer-use tools
- raw write-capable HTTP/API tools
- unrestricted shell access that can reproduce the same action

If those remain available, AgentTrust can be bypassed.

## Recommended Operating Model

For the simple guarded-runtime path, run three concurrent pieces:

1. Agent runtime using `AgentTrustOpenClawRuntime`
2. Approval presenter using `agenttrust-nemoclaw approvals`
3. Session monitor using `agenttrust-nemoclaw monitor --follow`

That preserves the old extension responsibilities with terminal-first tooling:

- approvals
- live progress / thinking
- audit visibility
- screenshot retrieval

For deterministic deployment on the NVIDIA instance, run:

1. AgentTrust backend
2. agenttrust-executor
3. OpenClaw gateway/UI
4. approval presenter
5. session monitor

## First Validation Flow

Use the current demo path first:

1. start a session
2. submit a prompt to research AI security risks
3. visit a live article
4. create a GitHub issue through the external API path
5. verify approval handling on the high-risk step
6. verify the monitor shows prompt progress and screenshots

For deterministic validation, also confirm:

7. a browser/API mutation fails if the executor is unavailable
8. a mutation fails if the lease is expired or tampered with
9. no alternate raw tool path is available to the agent

## Current Repo Status

This repo now contains:

- guarded runtime scaffolding
- deterministic executor scaffolding
- env templates for executor deployment
- local WSL setup docs

This repo does **not yet** contain the final NVIDIA-side changes to:

- `NemoClaw/Dockerfile`
- `NemoClaw/scripts/nemoclaw-start.sh`
- OpenShell sandbox policy
- the backend lease-issuance endpoint that signs per-action execution leases

Those changes must be applied in the NVIDIA/OpenShell environment itself.

## Related Document

See `docs/nemoclaw-feature-parity.md` for explicit parity, feature loss, and recovery notes.
