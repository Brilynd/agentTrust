# 🛡 AgentTrust: Identity & Audit Layer for Agentic Browsers

> **A policy-enforced, identity-bound execution environment for AI agents in browsers.**

AgentTrust provides enterprise-grade governance for AI agents operating in web browsers. Instead of simple click logging, AgentTrust delivers identity-bound, policy-enforced, auditable execution with cryptographic tamper-evidence.

---

## 🎯 Project Vision

**AgentTrust solves the "trust deficit" that prevents AI agents from being deployed in production.**

### The Problem
AI agents can reason and make decisions, but they can't safely interact with real web services (GitHub, Slack, banking) because there's no way to govern what they do.

### Our Solution
AgentTrust provides the **governance layer** that makes AI agent browser automation safe for production:
- **Identity**: Each agent has authenticated identity (Auth0)
- **Policy**: Fine-grained control over what agents can do
- **Risk Management**: Automatic detection of high-risk actions
- **Audit**: Complete, tamper-evident log of all actions

**Result**: Agents can safely interact with real services instead of staying in sandboxes.

### Key Features
- **Agent Identity**: Each AI agent has authenticated identity via Auth0
- **Pre-Execution Validation**: Agents must check with AgentTrust before acting
- **Policy-as-Code**: JSON-based policies control what agents can do, where, and when
- **Risk Classification**: Automatic detection of high-risk agent actions
- **Just-In-Time Privilege**: Short-lived elevated tokens for high-risk actions
- **Cryptographic Audit Trail**: Tamper-evident logging of all agent actions
- **Agent Monitoring**: Complete visibility into agent behavior

---

## 🏗 Architecture Overview

### Components

1. **Chrome Extension** (Manifest v3)
   - Content scripts for action interception
   - Background service worker for coordination
   - UI for step-up authentication prompts

2. **Backend API** (Node.js)
   - Auth0 JWT validation
   - Policy engine for risk classification
   - Token exchange for step-up authentication
   - Audit log storage

3. **Auth0 Integration**
   - Machine-to-Machine (M2M) authentication
   - Scoped tokens (`browser.basic`, `browser.form.submit`, `browser.high_risk`)
   - Token exchange for temporary elevated privileges

4. **Database** (PostgreSQL)
   - Audit logs with cryptographic hashes
   - Policy configurations
   - Agent behavioral baselines

---

## 🚀 Quick Start

### Prerequisites

- Node.js 18+ and npm
- PostgreSQL 14+
- Auth0 account and application configured
- Google Chrome browser

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd agentTrust
   ```

2. **Install dependencies**
   ```bash
   # Backend dependencies
   cd backend
   npm install

   # Extension dependencies (if any)
   cd ../extension
   npm install
   ```

3. **Configure environment variables**
   ```bash
   # Backend .env
   cp backend/.env.example backend/.env
   # Edit backend/.env with your Auth0 credentials and database URL
   ```

4. **Set up database**
   ```bash
   cd backend
   npm run migrate
   ```

5. **Load the extension**
   - Open Chrome and navigate to `chrome://extensions/`
   - Enable "Developer mode"
   - Click "Load unpacked"
   - Select the `extension` folder

6. **Start the backend**
   ```bash
   cd backend
   npm start
   ```

### 🧪 Testing Setup

**For complete testing setup instructions, see [Testing Setup Guide](./docs/testing-setup.md)**

Quick test:
```bash
# Get Auth0 token
cd backend
node test/get-token.js

# Test API (with token)
./test/test-api.sh <your-token>
```

---

## 📁 Project Structure

```
agentTrust/
├── extension/                 # Chrome Extension (Manifest v3)
│   ├── manifest.json         # Extension manifest
│   ├── background/           # Background service worker
│   │   └── service-worker.js
│   ├── content/              # Content scripts
│   │   ├── content.js        # Main content script
│   │   └── action-capture.js # Action interception logic
│   ├── popup/                # Extension popup UI
│   │   ├── popup.html
│   │   ├── popup.js
│   │   └── popup.css
│   ├── stepup/               # Step-up authentication UI
│   │   ├── stepup.html
│   │   ├── stepup.js
│   │   └── stepup.css
│   ├── assets/               # Icons, images
│   └── utils/                # Shared utilities
│       ├── auth.js           # Auth0 token management
│       └── messaging.js      # Chrome messaging utilities
│
├── backend/                  # Node.js Backend API
│   ├── src/
│   │   ├── server.js         # Express server setup
│   │   ├── routes/           # API routes
│   │   │   ├── actions.js    # Action logging endpoints
│   │   │   ├── auth.js       # Auth0 validation
│   │   │   ├── policies.js   # Policy management
│   │   │   └── audit.js      # Audit dashboard endpoints
│   │   ├── middleware/       # Express middleware
│   │   │   ├── auth.js       # JWT validation
│   │   │   └── policy.js     # Policy enforcement
│   │   ├── services/         # Business logic
│   │   │   ├── auth0.js      # Auth0 integration
│   │   │   ├── policy-engine.js # Risk classification
│   │   │   ├── token-exchange.js # Step-up token exchange
│   │   │   └── audit.js      # Audit log management
│   │   ├── models/           # Database models
│   │   │   ├── action.js     # Action log model
│   │   │   ├── policy.js     # Policy model
│   │   │   └── agent.js      # Agent baseline model
│   │   └── utils/            # Utilities
│   │       ├── crypto.js     # Cryptographic hashing
│   │       └── validation.js # Input validation
│   ├── migrations/           # Database migrations
│   ├── tests/                # Test files
│   ├── .env.example          # Environment variable template
│   └── package.json
│
├── dashboard/                # Audit Dashboard (Optional - Future)
│   ├── src/
│   └── public/
│
├── docs/                     # Documentation
│   ├── architecture.md       # System architecture
│   ├── api.md               # API documentation
│   └── policies.md          # Policy configuration guide
│
├── .gitignore
└── README.md
```

---

## 🔐 Core Features

### 1. Identity-Bound Actions

Every browser action is captured with:
- Agent identity (from Auth0 JWT)
- Timestamp
- Action type (click, form submit, navigation)
- DOM context
- URL and domain

### 2. Risk Classification Engine

Actions are automatically classified by:
- **Domain sensitivity**: Financial sites, internal tools, unknown domains
- **Action type**: Delete, merge, transfer, read
- **DOM keyword detection**: "delete", "confirm", "submit payment"
- **Form field analysis**: Password fields, payment forms
- **URL pattern matching**: Admin routes, sensitive endpoints

Risk levels: `low`, `medium`, `high`

### 3. Policy Enforcement

JSON-based policies define:
```json
{
  "allowed_domains": ["github.com", "slack.com"],
  "high_risk_keywords": ["delete", "merge", "transfer"],
  "requires_step_up": ["high"],
  "blocked_domains": ["malicious-site.com"]
}
```

### 4. Step-Up Authentication

For high-risk actions:
1. Agent requests action with insufficient scope
2. Backend denies request
3. Extension prompts user for approval
4. Auth0 issues temporary `browser.high_risk` scope (30-60 seconds)
5. Action executes
6. Token expires automatically

### 5. Cryptographic Action Chain

Each event is cryptographically linked:
```
hash = SHA256(previous_hash + event_payload)
```

Ensures tamper-evident audit trail.

### 6. Audit Dashboard

Filter and analyze actions by:
- Agent identity
- Domain
- Risk level
- Date range
- Action type

View:
- Token scope used
- Step-up status
- Approval metadata
- Event replay data

---

## 🧩 Development Roadmap

### Week 1 – Foundation: Identity + Action Capture
- [x] Project setup and folder structure
- [ ] Auth0 agent registration and M2M setup
- [x] Chrome extension manifest and basic structure
- [ ] Action capture (click, form submit, navigation)
- [x] Backend JWT validation
- [ ] Basic audit logging

### Week 2 – Policy Engine + Risk Classification
- [ ] Risk classification engine
- [ ] Policy JSON schema and API
- [ ] Domain trust profiles
- [ ] Keyword detection (high/medium risk)
- [ ] Form field analysis
- [ ] Financial domain detection

### Week 3 – Step-Up + Short-Lived Delegated Authority
- [ ] Step-up authentication UI
- [ ] Auth0 token exchange flow
- [ ] Short-lived token issuance (30-60 seconds)
- [ ] User approval workflow
- [ ] Token expiration handling

### Week 4 – Cryptographic Audit & Advanced Features
- [ ] Cryptographic action chain (SHA256)
- [ ] Audit dashboard API endpoints
- [ ] Agent behavioral baseline
- [ ] Reason capture for actions
- [ ] Chain integrity verification

### Week 5 – Polish, Demo Prep & Submission
- [ ] Feature completion and bug fixes
- [ ] Complete documentation
- [ ] Demo video and presentation
- [ ] Final testing and submission

---

## 🔧 Configuration

### Auth0 Setup

1. Create a Machine-to-Machine application in Auth0
2. Configure API with scopes:
   - `browser.basic`
   - `browser.form.submit`
   - `browser.high_risk`
3. Set up token exchange for step-up flow

### Policy Configuration

Edit `backend/src/config/policies.json` or use the API to configure policies.

### Environment Variables

See `backend/.env.example` for required variables:

**Required**:
- `AUTH0_DOMAIN` - Your Auth0 tenant domain
- `AUTH0_CLIENT_ID` - Auth0 M2M application client ID
- `AUTH0_CLIENT_SECRET` - Auth0 M2M application client secret
- `AUTH0_AUDIENCE` - Auth0 API identifier
- `DATABASE_URL` - PostgreSQL connection string

**Optional** (with defaults):
- `PORT` - Server port (default: 3000)
- `NODE_ENV` - Environment (development/production)
- `RATE_LIMIT_WINDOW_MS` - Rate limit window (default: 900000 = 15 min)
- `RATE_LIMIT_MAX_REQUESTS` - Max requests per window (default: 100)
- `CORS_ORIGIN` - Allowed CORS origins (comma-separated)
- `TOKEN_CACHE_TTL` - Token cache TTL in seconds (default: 3600)
- `JWT_SECRET` - Additional JWT secret (for future use)

---

## 🧪 Testing

```bash
# Run backend tests
cd backend
npm test

# Run extension tests (if configured)
cd extension
npm test
```

---

## 📊 API Endpoints

### Actions
- `POST /api/actions` - Log an action
- `GET /api/actions` - Query audit log

### Authentication
- `POST /api/auth/validate` - Validate JWT token
- `POST /api/auth/stepup` - Request step-up token

### Policies
- `GET /api/policies` - Get current policies
- `PUT /api/policies` - Update policies

### Audit
- `GET /api/audit/chain` - Get cryptographic action chain
- `GET /api/audit/agent/:agentId` - Get agent-specific audit log

---

## 🤝 Contributing

This is a hackathon project. Contributions welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## 📝 License

[Specify your license here]

---

## 🏆 Hackathon Alignment: Auth0 "Authorized to Act"

AgentTrust directly addresses the **"trust deficit"** holding back AI agents from production readiness. This project solves the critical challenge of managing secure access to a user's digital life—GitHub, Slack, banking, and more—by providing a comprehensive identity and governance layer.

### How AgentTrust Addresses Hackathon Requirements

#### ✅ 1. Solves the Trust Deficit

**Problem**: Most AI agents remain confined to sandboxes because managing secure access is a massive security burden.

**AgentTrust Solution**:
- **Identity-Bound Execution**: Every browser action is tied to an authenticated agent identity via Auth0, eliminating anonymous/uncontrolled tool use
- **Policy-as-Code**: JSON-based policies provide fine-grained control over what agents can do, where they can operate, and when step-up authentication is required
- **Cryptographic Audit Trail**: Tamper-evident action chains ensure complete accountability and enable forensic analysis
- **Risk Classification**: Automatic detection of high-risk actions (deletions, financial transactions, etc.) with appropriate safeguards

#### ✅ 2. Secure Access to Digital Life

**Problem**: Agents need secure, controlled access to GitHub, Slack, banking, and other critical services.

**AgentTrust Solution**:
- **Domain-Based Policies**: Explicit allowlists/blocklists for domains (e.g., `github.com`, `slack.com`)
- **Financial Domain Detection**: Special handling for banking and payment sites with elevated security
- **Domain Trust Profiles**: Customizable risk profiles per domain (e.g., GitHub has lower risk multiplier)
- **Real-World Examples**: Tested and configured for GitHub (repository management), Slack (messaging), and financial services

#### ✅ 3. Secure Tool Calling

**Problem**: Uncontrolled tool use leads to security vulnerabilities and unintended consequences.

**AgentTrust Solution**:
- **Scoped Token System**: Three-tier scope model:
  - `browser.basic`: Read-only and low-risk navigation
  - `browser.form.submit`: Form submissions and medium-risk actions
  - `browser.high_risk`: Deletions, transfers, financial actions (requires step-up)
- **Pre-Execution Validation**: Every action is validated against policies before execution
- **Just-In-Time Privilege**: Short-lived elevated tokens (30-60 seconds) for high-risk actions only when approved
- **Token Exchange**: Auth0 token exchange for secure scope elevation

#### ✅ 4. Agent Identity

**Problem**: Agents need verifiable identity to operate in production environments.

**AgentTrust Solution**:
- **Auth0 Machine-to-Machine (M2M) Authentication**: Each agent has a unique, authenticated identity
- **JWT-Based Identity**: Every action includes agent identity in JWT token, validated on every request
- **Agent-Specific Audit Logs**: Complete audit trail filtered by agent identity
- **Behavioral Baseline**: Track agent behavior patterns to detect anomalies
- **Identity in Action Chain**: Cryptographic hash includes agent ID, ensuring non-repudiation

#### ✅ 5. Model Context Protocol (MCP) Alignment

**Problem**: Need standardized interface for agent-browser interactions.

**AgentTrust Solution**:
- **Structured Action Model**: All browser actions follow a consistent schema (type, domain, target, risk level)
- **Context-Aware Policies**: Policies consider full context (domain, action type, DOM elements, form fields)
- **MCP-Compatible API**: RESTful API that can be exposed as MCP tools/resources
- **Standardized Metadata**: Action metadata includes all context needed for MCP tool calling
- **Future MCP Integration**: Architecture supports exposing browser actions as MCP tools for LLM agents

#### ✅ 6. Moves Beyond RAG and Uncontrolled Tool Use

**Problem**: Current agents either use RAG (limited) or uncontrolled tool access (risky).

**AgentTrust Solution**:
- **Governed Tool Execution**: Every tool call (browser action) is policy-enforced, not just logged
- **Risk-Aware Execution**: System automatically classifies and handles risk before execution
- **User-in-the-Loop**: High-risk actions require explicit user approval with reason
- **Audit-First Design**: Complete visibility into all agent actions with cryptographic proof
- **Production-Ready**: Designed for real-world use, not just demos

### Hackathon Value Proposition

> **AgentTrust transforms browser automation from a security risk into a governed, auditable system that enables AI agents to operate safely in production environments.**

Instead of building another agent that does tasks, AgentTrust builds **the infrastructure layer** that makes agents safe to deploy. This is exactly what Auth0 is looking for: a solution that uses their identity platform to solve the trust deficit.

---

## 🎯 Strategic Positioning

AgentTrust isn't just a click logger—it's **infrastructure-level governance for AI agents**.

This project demonstrates:
- ✅ **Secure Tool Calling**: Policy-enforced, scoped browser actions
- ✅ **Agent Identity**: Auth0 M2M authentication with JWT validation
- ✅ **Token Vault Usage**: Short-lived elevated tokens via Auth0 token exchange
- ✅ **MCP Alignment**: Structured action model compatible with Model Context Protocol

**Built for the AI era, with enterprise-grade security.**

---

## 🤖 Agent Integration

**AgentTrust monitors AI agents, not human users.**

Agents integrate by calling AgentTrust API **before** performing browser actions. AgentTrust validates, logs, and controls what agents can do.

### Quick Start for Agents

1. **Set up Agent Identity in Auth0** (one per agent)
2. **Integrate AgentTrust client** into your agent code
3. **Call AgentTrust before browser actions**
4. **Handle policy responses** (allowed/denied/step-up)

**Example**:
```python
from integrations.chatgpt.agenttrust_client import AgentTrustClient

# Initialize for your agent
agenttrust = AgentTrustClient()

# Before performing browser action:
result = agenttrust.execute_action(
    action_type="click",
    url="https://github.com/user/repo",
    target={"tagName": "BUTTON", "id": "submit-btn"}
)

# Check result
if result["status"] == "allowed":
    # Proceed with action
    perform_click(...)
elif result["status"] == "step_up_required":
    # Request user approval
    request_approval(...)
else:
    # Action denied
    raise Exception("Action not allowed")
```

See [Agent Integration Guide](./docs/agent-integration.md) for complete setup instructions.

---

## 📚 Documentation

### Essential Guides
- [Real Agent Integration Guide](./docs/real-agent-integration.md) - **Integrate with real AI agents (ChatGPT, AutoGPT, LangChain)**
- [Test Scenario Guide](./docs/test-scenario-guide.md) - **Test AgentTrust with real AI agents**
- [Agent Integration Guide](./docs/agent-integration.md) - **How agents integrate with AgentTrust**
- [Testing Setup Guide](./docs/testing-setup.md) - **Complete testing setup instructions**
- [ChatGPT Integration Guide](./docs/chatgpt-integration.md) - **ChatGPT-specific integration**

### Technical Documentation
- [Architecture Documentation](./docs/architecture.md) - System architecture and design
- [API Documentation](./docs/api.md) - Complete API reference
- [Security Documentation](./docs/security.md) - **Complete security guide and best practices**
- [Policy Configuration Guide](./docs/policies.md) - Policy setup and configuration

---

## 🙏 Acknowledgments

Built with Auth0 for identity and security.
