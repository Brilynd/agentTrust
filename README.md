# AgentTrust — Identity & Audit Layer for Agentic Browsers

AgentTrust is a production-grade governance platform for AI agents operating in web browsers. It provides identity-bound, policy-enforced, auditable execution so that AI agents can safely interact with real web services — GitHub, Amazon, Slack, banking — without uncontrolled access.

Instead of building another agent that does tasks, AgentTrust builds **the infrastructure layer** that makes autonomous agents safe to deploy.

---

## The Problem

AI agents can reason and make decisions, but they cannot safely interact with real web services because there is no way to govern what they do. Most agents are either confined to sandboxes or given uncontrolled access. Neither is acceptable for production environments.

## The Solution

AgentTrust sits between the AI agent and the browser, enforcing identity, policy, and audit on every action before it executes. The agent must check with AgentTrust before performing any browser action — navigation, click, form submission — and AgentTrust decides whether to allow, deny, or escalate for human approval.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   User / Operator                       │
│         (Chrome Extension — monitor, approve,           │
│          manage policies, run routines)                  │
└────────────────────────┬────────────────────────────────┘
                         │  Approvals / Commands / Config
                         ▼
┌─────────────────────────────────────────────────────────┐
│              AgentTrust Backend API                      │
│   Node.js + Express + PostgreSQL                        │
│                                                         │
│  • Auth0 JWT validation   • Policy engine               │
│  • Risk classification    • Cryptographic audit chain    │
│  • Step-up approvals      • Credential vault            │
│  • Session management     • Routine storage             │
│  • Command queue          • Token exchange              │
└────────────────────────┬────────────────────────────────┘
                         │  validate / log / approve
                         ▼
┌─────────────────────────────────────────────────────────┐
│              ChatGPT Agent (Python)                      │
│   OpenAI GPT-4o + Selenium WebDriver                    │
│                                                         │
│  • AgentTrust client      • Browser controller          │
│  • Intercepted WebDriver  • Auto-login engine           │
│  • Routine replay engine  • Credential resolver         │
│  • Auth0 Token Vault      • Extension auto-login        │
└─────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Backend API** | Node.js, Express, PostgreSQL | Policy enforcement, audit logging, session management, credential vault, routine storage, command/approval queues |
| **Chrome Extension** | Manifest V3 | Real-time monitoring dashboard, step-up approval UI, policy management, credential management, routine management, chat interface |
| **ChatGPT Agent** | Python, OpenAI GPT-4o, Selenium | AI-driven browser automation with mandatory AgentTrust validation on every action |
| **Auth0 Integration** | M2M tokens, Token Vault | Agent identity, scoped tokens, token exchange for step-up and external APIs |
| **Database** | PostgreSQL (AWS RDS supported) | Actions, sessions, prompts, credentials (AES-256-GCM encrypted), routines, users, audit chain |

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

### 9. Real-Time Monitoring Dashboard

The Chrome extension popup provides a live dashboard:

- **Monitor tab** — session list, action feed with risk badges, screenshot viewer, filters by risk/type/domain
- **Chat tab** — conversation view showing User Request → ChatGPT Response → Action Screenshot, with `/run` command support
- **Routines tab** — routine list, search, create/edit/delete, import from session, one-click execution
- **Permissions tab** — manage allowed/blocked/financial domains, high-risk keywords, step-up toggles, saved credentials, connected OAuth accounts
- **Pop-out window** — detach the panel into a standalone window that persists across page navigations
- **Live auto-refresh** — toggle real-time polling for new actions
- **Approval banner** — step-up approval prompts appear inline with approve/deny buttons

### 10. Session Management

Each agent run creates a distinct session for organized tracking:

- Sessions are created and ended via API (`POST /api/sessions`, `PATCH /api/sessions/:id/end`)
- All actions, prompts, and screenshots are associated with the active session
- Sessions are listed and browsable in the Monitor tab
- Routines are executed within the context of the current session

### 11. Prompt Tracking

User prompts and ChatGPT responses are stored and linked to their resulting actions:

- Each user message is stored via `POST /api/prompts`
- Actions reference their originating `promptId`
- ChatGPT's response is updated on the prompt record after generation
- The Chat tab renders the full prompt → response → action → screenshot flow

### 12. Command Queue & Long Polling

Bidirectional communication between the extension and the agent:

- Extension sends commands (chat messages, routine executions) via `POST /api/commands`
- Agent long-polls `GET /api/commands/pending` with configurable timeout
- Instant delivery when the agent is already polling; queued otherwise
- Same pattern for approvals: agent long-polls `GET /api/approvals/:id/wait`

### 13. Auth0 Token Vault Integration

External API access via Auth0 Token Vault:

- Token exchange for provider-specific tokens (GitHub, Google, Slack)
- Auth0 manages OAuth flows, token refresh, and consent
- Step-up token exchange for elevated privileges
- Connected accounts managed via the extension Permissions tab

---

## Project Structure

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
│   │   │   ├── external-api.js       # Proxied external API calls
│   │   │   ├── policies.js           # Policy CRUD
│   │   │   ├── prompts.js            # Prompt storage + response update
│   │   │   ├── routines.js           # Routine CRUD, from-session, execute
│   │   │   ├── sessions.js           # Session create/end/list
│   │   │   ├── token-vault.js        # Auth0 Token Vault endpoints
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
│   │   └── migrate.js                # Database migration runner
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
│   │   ├── popup.js                  # All client-side logic
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
│   └── chatgpt/                      # ChatGPT Agent Integration
│       ├── chatgpt_agent_with_agenttrust.py   # Main agent (3100+ lines)
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
│       │   └── ChatGPTAgentWithAgentTrust     # OpenAI chat loop + tool calling
│       ├── agenttrust_client.py               # Python API client
│       │   ├── Auth0 M2M token management
│       │   ├── execute_action()
│       │   ├── Session management
│       │   ├── Prompt storage
│       │   ├── Credential lookup
│       │   ├── Step-up approval polling
│       │   └── Async screenshot upload
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

---

## Quick Start

### Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.9+ with pip
- **PostgreSQL** 14+ (local or AWS RDS)
- **Auth0** account with M2M application configured
- **Google Chrome** browser
- **OpenAI API key** (GPT-4o access)

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
AUTH0_CLIENT_ID=your_m2m_client_id
AUTH0_CLIENT_SECRET=your_m2m_client_secret
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
OPENAI_MODEL=gpt-4o

# AgentTrust
AGENTTRUST_API_URL=http://localhost:3000/api
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your_m2m_client_id
AUTH0_CLIENT_SECRET=your_m2m_client_secret
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

### 4. Load the Chrome Extension

1. Open `chrome://extensions/` in Chrome
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `extension/` folder

### 5. Start the Backend

```bash
cd backend
npm start
# Server runs on http://localhost:3000
```

### 6. Run the Agent

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

## API Reference

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

---

## Security

- **Auth0 M2M JWT** validation on all agent-facing endpoints (JWKS-based)
- **User JWT** validation on all extension-facing endpoints
- **AES-256-GCM** encryption for credential storage with per-credential IVs
- **SHA-256 hash chain** for tamper-evident audit logs
- **Helmet** security headers
- **Rate limiting** (configurable per IP)
- **CORS** whitelisting
- **Input sanitization** (express-validator, mongo-sanitize, HPP)
- **bcrypt** password hashing for user accounts
- **Passkey/WebAuthn suppression** — Chrome DevTools Protocol and JavaScript injection prevent native browser dialogs from interfering with automation

---

## How the Agent Works

1. **User sends a message** via the Chat tab or the agent receives a command
2. **Prompt is stored** in the database via AgentTrust API
3. **OpenAI GPT-4o processes the message** with a system prompt that enforces tool use
4. **Agent calls tools** (navigate, click, type, auto_login, etc.)
5. **Each tool call validates with AgentTrust** — `POST /api/actions` checks policy, classifies risk, logs to audit chain
6. **If allowed**, the browser action executes and a screenshot is captured
7. **If step-up required**, the agent long-polls while the user approves/denies in the extension
8. **If denied**, the agent reports the denial to ChatGPT, which adapts its approach
9. **Results flow back** to ChatGPT for the next reasoning step
10. **Extension updates in real time** via DOM events dispatched by the agent

---

## Auth0 Hackathon Alignment

AgentTrust is built for the **Auth0 "Authorized to Act"** hackathon, directly addressing the trust deficit that prevents AI agents from production deployment.

| Hackathon Requirement | AgentTrust Implementation |
|----------------------|--------------------------|
| **Token Vault** | `auth0_token_vault.py` — exchanges tokens for external API access via Auth0 Token Vault |
| **OAuth flows** | Handled by Auth0; agents exchange tokens without managing refresh tokens |
| **Agent identity** | Auth0 M2M authentication — every action is identity-bound |
| **Secure tool calling** | Three-tier scope model with pre-execution validation |
| **Step-up authentication** | Real-time approval flow with long-polling and auto-expiry |
| **Consent delegation** | Auth0 Connected Accounts for third-party API consent |
| **Audit trail** | SHA-256 hash chain with full action context and screenshots |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Agent | Python 3.9+, OpenAI GPT-4o |
| Browser Automation | Selenium 4.41, Chrome DevTools Protocol |
| Backend | Node.js 18+, Express 4 |
| Database | PostgreSQL 14+ (AWS RDS compatible) |
| Authentication | Auth0 (M2M + Token Vault), JWT, bcrypt |
| Encryption | AES-256-GCM (credentials), SHA-256 (audit chain) |
| Extension | Chrome Manifest V3 |
| Security | Helmet, express-rate-limit, CORS, HPP, mongo-sanitize |

---

## License

MIT
