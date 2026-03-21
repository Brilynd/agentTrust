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
AGENTTRUST_API_URL=http://10.138.0.147:3000/api
AGENTTRUST_EXECUTOR_HOST=127.0.0.1
AGENTTRUST_EXECUTOR_PORT=3101
AGENTTRUST_EXECUTOR_URL=http://10.138.0.147:3101
AGENTTRUST_EXECUTOR_MODE=host
AGENTTRUST_EXECUTION_LEASE_SECRET=replace_with_long_random_secret
AGENTTRUST_AGENT_TOKEN=preissued_agent_token
AGENTTRUST_BROWSER_PROVIDER_MODULE=/abs/path/to/agentTrust/integrations/nemoclaw/src/browser-provider.agenttrust-host.js
AGENTTRUST_HOST_BROWSER_SERVICE_URL=http://127.0.0.1:4100

# Required on the host if AGENTTRUST_AGENT_TOKEN is not already set:
# AUTH0_DOMAIN=your-tenant.us.auth0.com
# AUTH0_CLIENT_ID=your_client_id
# AUTH0_CLIENT_SECRET=your_client_secret
# AUTH0_AUDIENCE=https://agenttrust.api

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

For NVIDIA-hosted NeMoClaw, the recommended production workaround is **host executor mode**:

- NVIDIA instance host:
  - AgentTrust backend
  - Auth0 and RDS connectivity
  - deterministic `agenttrust-executor`
  - host browser service backed by the existing Selenium runtime
- OpenShell sandbox:
  - OpenClaw gateway/UI
  - AgentTrust runtime wrapper
  - policy proxy

This avoids the current OpenShell DNS limitation inside the sandbox while preserving the deterministic lease boundary.

### 7. Host executor mode

In host executor mode:

- the sandbox requests approvals and leases from the backend by host IP
- the sandbox sends approved actions to the host executor by host IP
- the host executor verifies the lease and performs the browser mutation
- the host executor uploads screenshots back to the backend
- the sandbox does **not** need direct Auth0 or RDS reachability

Required host-side components:

- `integrations/chatgpt/host_browser_service.py`
- `integrations/nemoclaw/src/browser-provider.agenttrust-host.js`
- `integrations/nemoclaw/src/executor-server.js`

### 8. Update the sandbox startup wrapper

For host mode, `openclaw-nvidia-start.sh` should:

- export `AGENTTRUST_API_URL`
- export `AGENTTRUST_EXECUTOR_URL`
- export `AGENTTRUST_EXECUTOR_MODE=host`
- export `AGENTTRUST_AGENT_TOKEN`
- export `AGENTTRUST_EXECUTION_LEASE_SECRET`
- ensure `/sandbox/agenttrust/workspace` exists
- patch `/sandbox/.openclaw/openclaw.json` so OpenClaw sees:
  - `agents.defaults.workspace = /sandbox/agenttrust/workspace`
  - `skills.load.extraDirs = ['/sandbox/.openclaw/skills/agenttrust']`
- patch the runtime policy for the backend and executor IPs
- skip local executor startup
- start `openclaw gateway run`

### 9. Update the sandbox image

The sandbox image still needs:

- the AgentTrust NeMoClaw integration code
- the runtime wrapper and CLI helpers
- the browser provider module path used for local fallback mode

The sandbox image does **not** need to run Selenium in host executor mode.

### 10. Modify the OpenShell policy

For host executor mode, the sandbox policy should allow only:

- the AgentTrust backend host IP and port
- the AgentTrust executor host IP and port
- NVIDIA inference routing
- any explicitly-approved provider APIs exposed through the backend

Avoid depending on broad sandbox DNS or direct RDS/Auth0 reachability in this mode.

### 11. Modify `/sandbox/.openclaw/openclaw.json`

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

### 12. Start the host services

Start these on the NVIDIA instance host:

```bash
cd agentTrust/backend
npm run dev
```

```bash
cd agentTrust/integrations/chatgpt
python host_browser_service.py
```

```bash
cd agentTrust/integrations/nemoclaw
AGENTTRUST_API_URL=http://127.0.0.1:3000/api \
AGENTTRUST_EXECUTOR_HOST=0.0.0.0 \
AGENTTRUST_EXECUTOR_PORT=3101 \
AGENTTRUST_EXECUTION_LEASE_SECRET=replace_with_long_random_secret \
AGENTTRUST_BROWSER_PROVIDER_MODULE="$(pwd)/src/browser-provider.agenttrust-host.js" \
AGENTTRUST_HOST_BROWSER_SERVICE_URL=http://127.0.0.1:4100 \
AGENTTRUST_AGENT_TOKEN="$(npm run --silent agent-token)" \
npm run executor
```

### 13. Browser provider module

For host mode, set:

```env
AGENTTRUST_BROWSER_PROVIDER_MODULE=/abs/path/to/agentTrust/integrations/nemoclaw/src/browser-provider.agenttrust-host.js
AGENTTRUST_HOST_BROWSER_SERVICE_URL=http://127.0.0.1:4100
```

The host browser service reuses the existing Selenium `BrowserController` from `integrations/chatgpt/chatgpt_agent_with_agenttrust.py`.

### 14. Raw tool removal

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
2. host browser service
3. host agenttrust-executor
4. OpenClaw gateway/UI
5. approval presenter
6. session monitor

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
- host executor mode for NVIDIA-hosted deployments
- a host browser bridge that reuses the existing Selenium runtime
- env templates for executor deployment
- host-mode setup docs

You still need to apply environment-specific values for:

- the reachable host IP used by the sandbox
- backend/Auth0/database credentials
- the exact OpenShell/NVIDIA deployment commands used on the target host

Those values must be applied in the NVIDIA/OpenShell environment itself.

## Related Document

See `docs/nemoclaw-feature-parity.md` for explicit parity, feature loss, and recovery notes.
