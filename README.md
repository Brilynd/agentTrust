<div align="center">

# AgentTrust

**Identity & Audit Layer for Agentic Browsers**

[![Auth0](https://img.shields.io/badge/Auth0-Authorized_to_Act-EB5424?style=for-the-badge&logo=auth0&logoColor=white)](https://auth0.com)
[![Node.js](https://img.shields.io/badge/Node.js-18+-339933?style=for-the-badge&logo=node.js&logoColor=white)](https://nodejs.org)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![OpenAI](https://img.shields.io/badge/GPT--4.1-Multi--Model-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-AWS_RDS-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://aws.amazon.com/rds/)
[![Chrome](https://img.shields.io/badge/Chrome-Extension_MV3-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

</div>

---

> **Built for the Auth0 "Authorized to Act" Hackathon** — AgentTrust proves that autonomous AI agents and production-grade security are not mutually exclusive. Every browser action is identity-bound, policy-enforced, and cryptographically audited before it executes.

---

## Live Demo

<div align="center">

[![Watch the Demo](https://img.youtube.com/vi/RZO4ZZ3n2r0/maxresdefault.jpg)](https://youtu.be/RZO4ZZ3n2r0)

**[Watch the Auth0 hackathon demo submission on YouTube](https://youtu.be/RZO4ZZ3n2r0)**

*This demo showcases AgentTrust researching AI security vulnerabilities, reading relevant findings on the web, and creating a GitHub issue with the summary — all with real-time policy enforcement, step-up approval, and a live thinking breakdown in the extension.*

</div>

---

## What is AgentTrust?

AI agents can reason, but they can't be trusted. Today's agents are either sandboxed into uselessness or given uncontrolled access to real accounts. Neither is deployable.

**AgentTrust is the missing infrastructure layer.** It sits between the AI agent and the browser, enforcing identity, policy, and audit on every single action — click, navigation, form submission — before it executes. For supported providers like GitHub and Google Calendar, the agent calls APIs directly through Auth0's identity infrastructure, bypassing the browser entirely.

We didn't build another agent. We built **the governance platform that makes agents safe to deploy.**

### Highlights

| | |
|---|---|
| **Zero-trust execution** | Every action requires an Auth0 M2M JWT. No anonymous execution, ever. |
| **Pre-execution policy engine** | Risk classification (low / medium / high) with keyword, URL, and form-field analysis — before the action runs |
| **Human-in-the-loop** | High-risk actions trigger real-time step-up approval via the Chrome extension |
| **Cryptographic audit trail** | SHA-256 hash chain links every action with agent identity, session, risk level, and screenshot |
| **API-first external access** | GitHub and Google Calendar via Auth0 Management API — no browser scraping |
| **Credential vault** | AES-256-GCM encrypted storage. Passwords never reach the LLM context. |
| **Multi-model pipeline** | GPT-4.1 for reasoning, GPT-4.1-mini for planning, GPT-4.1-nano for classification |

---

## Auth0 Integration

AgentTrust is built on Auth0 as its identity backbone. Every trust decision flows through Auth0's infrastructure.

| Hackathon Requirement | Implementation |
|----------------------|----------------|
| **Token Vault** | `external-api.js` exchanges tokens for GitHub/Google API access via Auth0 Management API + Token Vault fallback |
| **OAuth flows** | Users connect GitHub/Google accounts through the extension; Auth0 manages consent, token issuance, and refresh |
| **Agent identity** | Auth0 M2M authentication — every action carries a verifiable JWT with agent identity and scopes |
| **Secure tool calling** | Three-tier scope model (`browser.basic`, `browser.form.submit`, `browser.high_risk`) enforced pre-execution |
| **Step-up authentication** | Real-time approval flow with long-polling, auto-expiry (2 min TTL), and `approved_override` audit status |
| **Consent delegation** | Auth0 Connected Accounts for third-party API consent with provider-specific scopes (repo, calendar) |
| **Audit trail** | SHA-256 hash chain with full action context, agent identity, and screenshots — verifiable at any time |

---

## Architecture

### High-Level Network Diagram

<p align="center">
  <img src="docs/agenttrust-architecture.png" alt="AgentTrust Architecture Diagram" width="100%" />
</p>

### End-to-End Flow

<p align="center">
  <img src="docs/agenttrust-end-to-end-flow.png" alt="AgentTrust End-to-End Flow" width="100%" />
</p>

<details>
<summary><strong>Data Flow: Browser Action</strong> (click, navigate, form submit)</summary>

```
Agent                    Backend                     Extension
  │                         │                            │
  │ 1. POST /api/actions    │                            │
  │    {type, url, target}  │                            │
  │    [M2M JWT Bearer]     │                            │
  │ ───────────────────────>│                            │
  │                         │ 2. validateAction()        │
  │                         │    verify Auth0 JWT        │
  │                         │    via JWKS                │
  │                         │                            │
  │                         │ 3. enforcePolicy()         │
  │                         │    classifyRisk() ─────┐   │
  │                         │    ┌───────────────────┘   │
  │                         │    │ • domain check        │
  │                         │    │ • keyword matching     │
  │                         │    │ • URL pattern scan     │
  │                         │    │ • form field analysis  │
  │                         │    │ • form control detect  │
  │                         │    ▼                        │
  │                         │  riskLevel: low|med|high    │
  │                         │                            │
  │                         │ 4. checkPolicy()           │
  │                         │    scope verification      │
  │                         │                            │
  │                  ┌──────┤ 5a. If ALLOWED:            │
  │                  │      │     logAction() → hash     │
  │  6a. 201 OK ◄───┘      │     chain + DB write       │
  │  {action_id,            │                            │
  │   riskLevel}            │                            │
  │                         │                            │
  │  7. Execute in browser  │                            │
  │  8. Screenshot capture  │                            │
  │  9. PATCH screenshot    │                            │
  │  10. DOM event ─────────┼───────────────────────────>│
  │                         │                     11. Update popup
  │                         │                         badge/log
  │                  ┌──────┤                            │
  │                  │      │ 5b. If HIGH RISK:          │
  │  6b. 403 ◄──────┘      │     createApproval()       │
  │  {approvalId,           │                            │
  │   requiresStepUp}       │                            │
  │                         │              ◄─────────────│ User sees banner
  │  12. GET /approvals/    │                            │
  │      :id/wait           │              ◄─────────────│ POST /approvals/
  │  (long-poll 60s)        │                            │   :id/respond
  │ ───────────────────────>│                            │   {approved: true}
  │                         │                            │
  │  13. {approved: true} ◄─┤                            │
  │                         │                            │
  │  14. Retry POST         │                            │
  │      /api/actions       │                            │
  │      + approvalId       │                            │
  │ ───────────────────────>│ 15. Verify approval        │
  │                         │     → status:              │
  │  16. 201 OK ◄───────────┤       approved_override    │
  │                         │                            │
```

</details>

<details>
<summary><strong>Data Flow: External API Call</strong> (GitHub / Google Calendar)</summary>

```
Agent                    Backend                  Auth0         Provider API
  │                         │                       │                │
  │ 1. POST /api/           │                       │                │
  │    external/call        │                       │                │
  │    {provider, method,   │                       │                │
  │     url}                │                       │                │
  │    [M2M JWT Bearer]     │                       │                │
  │ ───────────────────────>│                       │                │
  │                         │ 2. validateAction()   │                │
  │                         │                       │                │
  │                         │ 3. classifyApiRisk()  │                │
  │                         │    DELETE → high      │                │
  │                         │    POST/PUT → medium  │                │
  │                         │    GET → low          │                │
  │                         │                       │                │
  │                         │ 4. If high: return    │                │
  │                         │    403 + approvalId   │                │
  │                         │    (same step-up flow │                │
  │                         │     as browser actions)│               │
  │                         │                       │                │
  │                         │ 5. Token resolution:  │                │
  │                         │    DB → auth0_access_ │                │
  │                         │         token (JWT)   │                │
  │                         │    extract sub claim  │                │
  │                         │ ─────────────────────>│                │
  │                         │ 6. GET /api/v2/       │                │
  │                         │    users/{sub}        │                │
  │                         │    [Mgmt API Bearer]  │                │
  │                         │ <─────────────────────│                │
  │                         │ 7. Extract provider   │                │
  │                         │    access_token from  │                │
  │                         │    identities[]       │                │
  │                         │                       │                │
  │                         │ 8. Proxy API call ────┼───────────────>│
  │                         │    [Provider Bearer]  │                │
  │                         │ <─────────────────────┼────────────────│
  │                         │                       │                │
  │                         │ 9. sanitizeApiResponse│                │
  │                         │    strip tokens,      │                │
  │                         │    secrets, truncate   │                │
  │  10. {data} ◄───────────┤                       │                │
  │      (sanitized)        │                       │                │
```

</details>

<details>
<summary><strong>Endpoint Security Matrix</strong> (click to expand)</summary>

Every request passes through the global middleware stack before reaching any route handler:

| Layer | Protection |
|-------|-----------|
| **Helmet** | CSP, X-Frame-Options, X-Content-Type-Options, HSTS, referrer policy |
| **CORS** | Whitelist-only origins (backend URL + extension ID) |
| **Rate limiter** | Configurable per-IP limit (default: 10,000 req / 15 min) |
| **Body parser** | 10 MB request size cap |
| **mongo-sanitize** | Strips `$` and `.` operators from input (NoSQL injection) |
| **HPP** | Blocks HTTP parameter pollution |
| **Request ID** | Unique ID injected into every request for tracing |
| **Input validation** | Sanitizes strings, rejects malformed payloads |

Route-level authentication and authorization:

| Endpoint Group | Auth Method | Key Security Measures |
|---------------|------------|----------------------|
| **POST /api/actions** | M2M JWT (Auth0 JWKS) | `enforcePolicy` middleware: risk classification on every action; high-risk → step-up approval; SHA-256 hash chain audit; blocked domains flat-denied |
| **PATCH /api/actions/:id** | M2M JWT | Agent ownership verified (action.agentId must match token sub) |
| **POST /api/external/call** | M2M JWT | `classifyApiRisk`: DELETE → high (requires approval), POST/PUT/PATCH → medium, GET → low; destructive URL keywords escalate; response sanitized |
| **GET /api/credentials/lookup** | M2M JWT | Returns credentials for auto-login; **passwords never sent to LLM** — stored in internal cache, redacted from tool results |
| **CRUD /api/credentials** | User JWT | AES-256-GCM encryption at rest; per-credential IV; passwords masked in list responses; user-scoped |
| **POST /api/auth/login** | None (public) | bcrypt password verification; rate-limited; returns short-lived JWT |
| **POST /api/auth/register** | None (public) | bcrypt password hashing (salt rounds); rate-limited |
| **GET /api/approvals/:id/wait** | M2M JWT | Long-poll with configurable timeout; approvals auto-expire after 2 min |
| **POST /api/approvals/:id/respond** | User JWT | Only authenticated users can approve/deny; prevents agent self-approval |
| **GET /api/token-vault/callback** | None (OAuth) | State parameter validated; tokens stored encrypted in DB |
| **POST /api/token-vault/connect** | User JWT | Initiates Auth0 OAuth with scoped permissions; audience parameter ensures JWT tokens |
| **GET /api/audit/chain** | M2M JWT | Read-only; SHA-256 chain integrity verifiable |
| **CRUD /api/routines** | User JWT | Owner-only mutation; non-owner global routines require upfront domain validation |
| **POST /api/commands** | User JWT | Only authenticated extension users can send commands to the agent |
| **GET /api/commands/pending** | M2M JWT | Only authenticated agents can receive commands; long-poll prevents busy-waiting |
| **GET/PUT /api/policies** | User JWT / M2M JWT | Policy changes take effect within 5s (TTL cache); file-persisted |

</details>

---

## How the Agent Works

1. **User sends a message** via the Chat tab or the agent receives a command
2. **Intent classification** (gpt-4.1-nano) — determines if the task needs the browser or is conversational
3. **Planning** (gpt-4.1-mini) — breaks the request into 2-6 sub-goals; API tasks prioritized over browser automation
4. **RAG context** — similar past tasks retrieved and injected as planning hints
5. **Observation** — captures current page state, visible elements, screenshot, and tab info
6. **Action selection** (gpt-4.1) — picks the best tool call for the current sub-goal
7. **AgentTrust validation** — `POST /api/actions` checks policy, classifies risk, logs to audit chain
8. **Execution** — if allowed, the browser action executes and a screenshot is captured; API tasks are proxied via Auth0
9. **Verification** — confirms the action succeeded or triggers retries (up to 3 per goal)
10. **Step-up flow** — if required, the agent long-polls while the user approves/denies in the extension
11. **Results flow back** to the LLM for the next reasoning step
12. **Extension updates in real time** via DOM events dispatched by the agent

---

## Features

### 1. Identity-Bound Execution

Every browser action is tied to an authenticated agent identity via Auth0 Machine-to-Machine (M2M) authentication. Actions cannot execute anonymously.

- Auth0 JWT validation on every API request
- Agent identity embedded in every audit log entry
- Scoped token system: `browser.basic`, `browser.form.submit`, `browser.high_risk`
- User authentication (JWT) for the Chrome extension

### 2. Pre-Execution Policy Enforcement

All browser actions (navigation, click, form submission) are validated against configurable policies **before** execution. The `InterceptedWebDriver` wrapper ensures no code path can bypass validation.

- **Allowed domains** — whitelist of permitted domains
- **Blocked domains** — actions are always denied
- **High-risk keywords** — trigger step-up approval (e.g., "delete", "transfer", "merge")
- **Financial domain detection** — elevated risk scoring for banking/payment sites
- **Form field analysis** — password fields and payment forms increase risk
- **URL pattern matching** — admin routes and sensitive endpoints

### 3. Risk Classification Engine

Every action is automatically classified as `low`, `medium`, `high`, or `blocked` based on:

- Domain sensitivity (financial sites, unknown domains)
- Action type (form submission scores higher)
- DOM keyword detection across element text, class, ID, aria-label, and URL
- URL path patterns (`/delete`, `/admin`, `/transfer`)
- Form field analysis (password fields, payment data)

### 4. Step-Up Authentication & Human-in-the-Loop Approval

High-risk actions trigger a step-up approval flow rather than being silently denied:

1. Agent requests an action that exceeds its current scope
2. Backend returns `step_up_required` with risk details
3. Chrome extension shows an approval banner with action context
4. User approves or denies in real time
5. Agent long-polls for the decision and proceeds if approved
6. Manual overrides are logged as `approved_override` in the audit trail

Approvals auto-expire after 2 minutes if not acted upon.

### 5. Cryptographic Audit Trail

Every action produces a tamper-evident log entry linked in a SHA-256 hash chain:

```
hash = SHA256(previous_hash + agent_id + type + timestamp + domain + url + risk_level)
```

- Chain integrity can be verified at any time
- Each entry includes agent identity, session, prompt, risk level, and status
- Screenshots are captured after each action and attached to the audit entry
- The full chain is queryable by agent, domain, risk level, date range, and action type

### 6. Credential Vault

Encrypted credential storage for autonomous login:

- Credentials encrypted at rest with **AES-256-GCM**
- Stored per-user in PostgreSQL with separate IV per credential
- **Fuzzy domain matching** — `amazon.com` matches `https://www.amazon.com/ap/signin`
- Agent looks up credentials via M2M-authenticated API at login time
- Credentials are never sent to the LLM; the auto-login engine uses them directly
- CRUD management via the Chrome extension Permissions tab

### 7. Intelligent Auto-Login Engine

A dedicated `auto_login` tool handles complex real-world login flows without LLM involvement per keystroke:

- **Multi-step form detection** — handles username-then-continue-then-password flows
- **Overlay/popup dismissal** — closes QR code dialogs, cookie banners, passkey prompts
- **Passkey suppression** — Chrome DevTools Protocol commands and JavaScript injection disable native WebAuthn/passkey dialogs
- **Stale element recovery** — retries on `StaleElementReferenceException`
- **Smart button detection** — finds continue/submit buttons while explicitly skipping passkey, biometric, and security-key buttons
- **Form submission via Enter key** — prefers pressing Enter on the password field over hunting for submit buttons, avoiding misclicks
- **Credential Vault integration** — auto-resolves stored credentials by domain

### 8. Reusable Routines

Record, save, and replay browser action sequences deterministically — without involving ChatGPT for each step:

- **Create from session** — cherry-pick specific actions from a past session to build a routine
- **Private and global scopes** — private routines are user-only; global routines are shared
- **Deterministic replay** — actions execute directly via the browser controller, not through the LLM
- **Trust model**:
  - Private routines and owner-run global routines bypass policy validation entirely (trusted execution)
  - Non-owner global routines perform a single upfront domain validation, then proceed in trusted mode
- **Credential resolution** — `auto_login` steps in routines automatically look up credentials from the vault
- **Page-ready waits** — `WebDriverWait` on `document.readyState` between steps for reliability
- **Chat UI integration** — run routines via `/run <routine_name>` in the chat panel
- **Full CRUD** — create, edit, delete, and search routines from the extension

### 9. External API Calls (API-First Architecture)

For supported providers, the agent calls external APIs directly instead of automating the browser:

- **API-first routing** — the planner and agent system prompt prioritize `call_external_api` over browser automation for GitHub and Google Calendar tasks
- **Auth0 Management API** — retrieves provider access tokens from user identity records; no Token Vault exchange grant required
- **Automatic token resolution** — the backend looks up the user's stored Auth0 JWT, extracts the `sub` claim, and fetches the provider token via the Management API
- **Token Vault fallback** — if Management API is unavailable, falls back to standard Token Vault token exchange
- **Supported providers**:
  - **GitHub** — repos, issues, PRs, user profile, organizations (`api.github.com`)
  - **Google Calendar** — events, scheduling, availability (`googleapis.com/calendar`)

### 10. Connected OAuth Accounts

Users link their GitHub and Google accounts through the extension, granting the agent API access:

- **OAuth flow via extension** — click "Connect" in the Permissions tab to initiate Auth0 social login
- **Stored in database** — Auth0 access tokens and refresh tokens persisted in the `user_connections` table
- **Disconnect support** — one-click disconnect per provider
- **Auto-refresh UI** — connection list refreshes automatically after completing OAuth
- **Scoped permissions** — GitHub requests `repo read:user user:email`; Google requests Calendar and profile scopes

### 11. LangGraph Agent Pipeline

The agent uses a structured state-machine graph (via LangGraph) for reliable multi-step task execution:

```
CLASSIFY → PLAN → OBSERVE → ACT → VERIFY → (loop or complete)
```

- **Intent classifier** (gpt-4.1-nano) — determines BROWSER vs CHAT intent in microseconds
- **Planner** (gpt-4.1-mini) — breaks user requests into 2-6 concrete sub-goals
- **Observer** — captures page state, visible elements, screenshots, tab info
- **Actor** (gpt-4.1) — selects and executes the best tool call for the current goal
- **Verifier** — confirms actions succeeded or triggers retries (up to 3 attempts per goal)
- **CAPTCHA detection** (gpt-4.1-mini) — identifies and handles checkbox CAPTCHAs via vision

### 12. Multi-Model Architecture

Different model tiers for different tasks, optimizing cost and speed:

| Task | Model | TPM | Rationale |
|------|-------|-----|-----------|
| Action selection & reasoning | `gpt-4.1` | 450K | Best instruction following for complex decisions |
| Planning & CAPTCHA detection | `gpt-4.1-mini` | 2M | Fast and cheap for structured outputs |
| Intent classification | `gpt-4.1-nano` | 2M | One-word output; near-instant response |
| Chat responses | `gpt-4.1-mini` | 2M | Conversational answers don't need the heavy model |

All models are configurable via environment variables (`OPENAI_MODEL`, `OPENAI_MODEL_FAST`, `OPENAI_MODEL_NANO`).

Rate-limit retry logic automatically falls back to the mini model if the primary model hits token limits, then trims older messages as a last resort.

### 13. Action History RAG

Past successful task patterns are stored and retrieved to improve planning:

- **Embedding-based retrieval** — user requests are matched against historical action sequences
- **Top-K similar tasks** — the 3 most similar past tasks are injected into the planner and agent prompts
- **Continuous learning** — every completed task is indexed for future retrieval

### 14. Real-Time Monitoring Dashboard

The Chrome extension popup provides a live dashboard:

- **Monitor tab** — session list, action feed with risk badges, screenshot viewer, filters by risk/type/domain
- **Chat tab** — conversation view showing User Request → ChatGPT Response → Action Screenshot, with `/run` command support
- **Routines tab** — routine list, search, create/edit/delete, import from session, one-click execution
- **Permissions tab** — manage allowed/blocked/financial domains, high-risk keywords, step-up toggles, saved credentials, connected OAuth accounts (GitHub, Google)
- **Pop-out window** — detach the panel into a standalone window that persists across page navigations
- **Live auto-refresh** — toggle real-time polling for new actions
- **Approval banner** — step-up approval prompts appear inline with approve/deny buttons

### 15. Session Management

Each agent run creates a distinct session for organized tracking:

- Sessions are created and ended via API (`POST /api/sessions`, `PATCH /api/sessions/:id/end`)
- All actions, prompts, and screenshots are associated with the active session
- Sessions are listed and browsable in the Monitor tab
- Routines are executed within the context of the current session

### 16. Prompt Tracking

User prompts and ChatGPT responses are stored and linked to their resulting actions:

- Each user message is stored via `POST /api/prompts`
- Actions reference their originating `promptId`
- ChatGPT's response is updated on the prompt record after generation
- The Chat tab renders the full prompt → response → action → screenshot flow

### 17. Command Queue & Long Polling

Bidirectional communication between the extension and the agent:

- Extension sends commands (chat messages, routine executions) via `POST /api/commands`
- Agent long-polls `GET /api/commands/pending` with configurable timeout
- Instant delivery when the agent is already polling; queued otherwise
- Same pattern for approvals: agent long-polls `GET /api/approvals/:id/wait`

---

<details>
<summary><h2>Project Structure</h2></summary>

```
agentTrust/
├── backend/                          # Node.js Backend API
│   ├── src/
│   │   ├── server.js                 # Express app setup, middleware, routes
│   │   ├── config/
│   │   │   └── database.js           # PostgreSQL connection pool
│   │   ├── middleware/
│   │   │   ├── auth.js               # JWT validation (M2M + user)
│   │   │   ├── policy.js             # Policy enforcement middleware
│   │   │   └── security.js           # Request ID, headers, input validation
│   │   ├── models/
│   │   │   ├── action.js             # Action audit log model
│   │   │   ├── prompt.js             # Prompt storage model
│   │   │   ├── session.js            # Session model
│   │   │   └── user.js               # User model (bcrypt passwords)
│   │   ├── routes/
│   │   │   ├── actions.js            # Action logging + screenshot PATCH
│   │   │   ├── approvals.js          # Step-up approval queue + long polling
│   │   │   ├── audit.js              # Audit chain query + verification
│   │   │   ├── auth.js               # User login/register, token issue
│   │   │   ├── commands.js           # Agent command queue + long polling
│   │   │   ├── credentials.js        # Encrypted credential vault CRUD
│   │   │   ├── external-api.js       # External API proxy (Management API + Token Vault)
│   │   │   ├── policies.js           # Policy CRUD
│   │   │   ├── prompts.js            # Prompt storage + response update
│   │   │   ├── routines.js           # Routine CRUD, from-session, execute
│   │   │   ├── sessions.js           # Session create/end/list
│   │   │   ├── token-vault.js        # OAuth connect/disconnect, callback, connections
│   │   │   └── users.js              # User management
│   │   ├── services/
│   │   │   ├── audit.js              # Audit log + hash chain logic
│   │   │   ├── auth0.js              # Auth0 JWT validation (JWKS)
│   │   │   ├── policy-engine.js      # Risk classification + policy check
│   │   │   └── token-exchange.js     # Auth0 token exchange for step-up
│   │   └── utils/
│   │       ├── crypto.js             # SHA-256 hash chain
│   │       ├── security.js           # Rate limiting, headers
│   │       └── validation.js         # Input sanitization
│   ├── config/
│   │   └── policies.json             # Default policy configuration
│   ├── migrations/
│   │   └── migrate.js                # Database migration runner (incl. user_connections)
│   ├── scripts/                      # DB setup scripts
│   └── package.json
│
├── extension/                        # Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background/
│   │   └── service-worker.js         # Background coordination
│   ├── content/
│   │   ├── content.js                # Main content script
│   │   └── action-capture.js         # DOM event interception
│   ├── popup/
│   │   ├── popup.html                # Dashboard UI (4 tabs)
│   │   ├── popup.js                  # All client-side logic (incl. OAuth account linking)
│   │   └── popup.css                 # Styles
│   ├── stepup/
│   │   ├── stepup.html               # Step-up approval page
│   │   ├── stepup.js
│   │   └── stepup.css
│   ├── utils/
│   │   ├── auth.js                   # Token management
│   │   └── messaging.js              # Chrome messaging utilities
│   └── assets/                       # Icons (16, 32, 128)
│
├── integrations/
│   └── chatgpt/                      # AI Agent Integration
│       ├── chatgpt_agent_with_agenttrust.py   # Main agent (4500+ lines)
│       │   ├── InterceptedWebDriver           # Mandatory validation wrapper
│       │   ├── InterceptedWebElement           # Click/type interception
│       │   ├── BrowserController               # Selenium browser operations
│       │   ├── BrowserActionExecutor           # AgentTrust-validated execution
│       │   │   ├── execute_click()
│       │   │   ├── execute_navigation()
│       │   │   ├── execute_form_submit()
│       │   │   ├── auto_login()               # Multi-step login engine
│       │   │   ├── replay_routine()           # Deterministic routine replay
│       │   │   └── _notify_extension()        # Real-time DOM events
│       │   └── ChatGPTAgentWithAgentTrust     # Multi-model chat loop + tool calling
│       ├── graph_agent.py                     # LangGraph state machine
│       │   ├── build_graph()                  # CLASSIFY → PLAN → OBSERVE → ACT → VERIFY
│       │   ├── plan_node()                    # Task decomposition (gpt-4.1-mini)
│       │   ├── observe_node()                 # Page state capture
│       │   ├── agent_node()                   # Action selection (gpt-4.1)
│       │   └── verify_node()                  # Result verification + retry
│       ├── agenttrust_client.py               # Python API client
│       │   ├── Auth0 M2M token management
│       │   ├── execute_action()
│       │   ├── Session management
│       │   ├── Prompt storage
│       │   ├── Credential lookup
│       │   ├── External API calls (call_external_api)
│       │   ├── Step-up approval polling
│       │   └── Async screenshot upload
│       ├── action_history_rag.py              # Embedding-based task pattern retrieval
│       ├── auth0_token_vault.py               # Token Vault client
│       ├── requirements.txt
│       └── test_agent.py
│
└── docs/                             # Documentation
    ├── architecture.md
    ├── api.md
    ├── agent-integration.md
    ├── policies.md
    └── security.md
```

</details>

---

## Quick Start

### Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.9+ with pip
- **PostgreSQL** 14+ on AWS RDS (or local for development)
- **Auth0** account with M2M application configured
- **Google Chrome** browser
- **OpenAI API key** (Tier 2+ recommended for comfortable TPM limits)

### 1. Clone and Install

```bash
git clone <repository-url>
cd agentTrust

# Backend
cd backend
npm install

# Python agent
cd ../integrations/chatgpt
pip install -r requirements.txt
```

### 2. Configure Environment

**Backend** (`backend/.env`):

```env
# Auth0
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your_client_id
AUTH0_CLIENT_SECRET=your_client_secret
AUTH0_AUDIENCE=https://agenttrust.api

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/agenttrust

# Security
JWT_SECRET=your-jwt-secret-for-user-auth
CREDENTIAL_ENCRYPTION_KEY=<64-char hex string for AES-256-GCM>

# Optional
PORT=3000
CORS_ORIGIN=http://localhost:3000,chrome-extension://<extension-id>
RATE_LIMIT_MAX_REQUESTS=10000
```

**Agent** (`integrations/chatgpt/.env`):

```env
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1            # Main model (action selection, reasoning)
OPENAI_MODEL_FAST=gpt-4.1-mini  # Fast model (planning, chat, captcha)
OPENAI_MODEL_NANO=gpt-4.1-nano  # Nano model (intent classification)

# AgentTrust
AGENTTRUST_API_URL=http://localhost:3000/api
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your_client_id
AUTH0_CLIENT_SECRET=your_client_secret
AUTH0_AUDIENCE=https://agenttrust.api

# Optional: auto-load extension and sign in
EXTENSION_PATH=../../extension
EXTENSION_LOGIN_EMAIL=admin@agenttrust.local
EXTENSION_LOGIN_PASSWORD=your-password
```

### 3. Set Up Database

```bash
cd backend
npm run setup-db
# Or: npm run migrate
```

This creates all required tables including `user_connections` for linked OAuth accounts.

### 4. Configure Auth0

1. Create an **Application** (Regular Web Application) in Auth0 Dashboard
2. Enable **Client Credentials** grant type under Advanced Settings → Grant Types
3. Create an **API** with identifier `https://agenttrust.api`
4. Under **Applications → APIs → Auth0 Management API → Machine to Machine Applications**, authorize your application with scopes: `read:users`, `read:user_idp_tokens`
5. Set up **Social Connections** for GitHub and Google with purpose set to "Authentication and Connected Accounts for Token Vault"
6. Add `http://localhost:3000/api/token-vault/callback` to the application's **Allowed Callback URLs**

### 5. Load the Chrome Extension

1. Open `chrome://extensions/` in Chrome
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `extension/` folder

### 6. Start the Backend

```bash
cd backend
npm run dev
# Server runs on http://localhost:3000
```

### 7. Run the Agent

```bash
cd integrations/chatgpt
python chatgpt_agent_with_agenttrust.py
```

The agent will:
- Launch a Chrome instance with the AgentTrust extension loaded
- Create a new session
- Auto-sign-in to the extension (if credentials are configured)
- Suppress passkey/WebAuthn dialogs via Chrome DevTools Protocol
- Begin listening for commands from the extension Chat tab

---

<details>
<summary><h2>API Reference</h2></summary>

### Actions
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/actions` | M2M | Log and validate a browser action |
| `GET` | `/api/actions` | M2M | Query the audit log (filters: session, type, risk, domain) |
| `PATCH` | `/api/actions/:id` | M2M | Attach screenshot to an action |

### Sessions
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/sessions` | M2M | Create a new session |
| `GET` | `/api/sessions` | User | List all sessions |
| `PATCH` | `/api/sessions/:id/end` | M2M | End a session |

### Prompts
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/prompts` | M2M | Store a user prompt |
| `PATCH` | `/api/prompts/:id` | M2M | Update with agent response |
| `GET` | `/api/prompts` | User | List prompts (by session) |

### Commands
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/commands` | User | Send command to agent |
| `GET` | `/api/commands/pending` | M2M | Long-poll for pending commands |

### Approvals
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/approvals/pending` | User | List pending approvals |
| `POST` | `/api/approvals/:id/respond` | User | Approve or deny |
| `GET` | `/api/approvals/:id/wait` | M2M | Long-poll for user decision |

### Credentials
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/credentials` | User | List saved credentials (masked) |
| `POST` | `/api/credentials` | User | Store a new credential (encrypted) |
| `PUT` | `/api/credentials/:id` | User | Update a credential |
| `DELETE` | `/api/credentials/:id` | User | Delete a credential |
| `GET` | `/api/credentials/lookup?domain=` | M2M | Agent looks up credentials by domain |

### Routines
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/routines` | User | List routines (private + global) |
| `GET` | `/api/routines/:id` | User | Get a single routine |
| `POST` | `/api/routines` | User | Create a routine |
| `PUT` | `/api/routines/:id` | User | Update a routine (owner only) |
| `DELETE` | `/api/routines/:id` | User | Delete a routine (owner only) |
| `POST` | `/api/routines/from-session/:sessionId` | User | Create routine from session actions |
| `POST` | `/api/routines/:id/execute` | User | Queue routine for agent execution |

### Policies
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/policies` | User | Get current policies |
| `PUT` | `/api/policies` | User | Update policies |

### External API
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/external/call` | M2M | Proxy external API call (GitHub, Google) via provider token |

### Token Vault / Connected Accounts
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/token-vault/exchange` | M2M | Token exchange for provider access |
| `POST` | `/api/token-vault/connect` | User | Initiate OAuth connection for a provider |
| `GET` | `/api/token-vault/callback` | None | OAuth callback handler |
| `GET` | `/api/token-vault/connections` | User | List connected providers |
| `DELETE` | `/api/token-vault/connections/:provider` | User | Disconnect a provider |

### Audit
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/audit/chain` | M2M | Get cryptographic action chain |
| `GET` | `/api/audit/verify` | M2M | Verify chain integrity |

### Auth
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/auth/login` | None | User login (returns JWT) |
| `POST` | `/api/auth/register` | None | User registration |
| `POST` | `/api/auth/stepup` | M2M | Request step-up token |

</details>

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Agent | Python 3.9+, OpenAI GPT-4.1 / GPT-4.1-mini / GPT-4.1-nano |
| Agent Framework | LangGraph (state machine: PLAN → OBSERVE → ACT → VERIFY) |
| Browser Automation | Selenium 4.41, Chrome DevTools Protocol |
| Backend | Node.js 18+, Express 4 |
| Database | PostgreSQL 14+ on AWS RDS (TLS in transit, encrypted at rest) |
| Authentication | Auth0 (M2M + Management API + Social Connections), JWT, bcrypt |
| Encryption | AES-256-GCM (credentials), SHA-256 (audit chain) |
| Extension | Chrome Manifest V3 |
| Security | Helmet, express-rate-limit, CORS, HPP, mongo-sanitize |

---

<div align="center">

**AgentTrust** — because autonomous agents need accountability, not just capability.

MIT License

</div>
