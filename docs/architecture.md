# AgentTrust Architecture

## System Overview

AgentTrust is a multi-component system designed to provide identity-bound, policy-enforced execution for AI agents in web browsers.

## Components

### 1. Chrome Extension (Frontend)

**Location**: `extension/`

**Components**:
- **Content Scripts**: Intercept browser actions (clicks, form submits, navigation)
- **Background Service Worker**: Coordinates between components and communicates with backend
- **Popup UI**: Displays agent status and session statistics
- **Step-Up UI**: Modal for user approval of high-risk actions

**Key Files**:
- `manifest.json`: Extension configuration (Manifest v3)
- `content/action-capture.js`: Action interception logic
- `background/service-worker.js`: Background coordination
- `popup/`: User interface for extension
- `stepup/`: Step-up authentication UI

### 2. Backend API

**Location**: `backend/`

**Technology**: Node.js + Express

**Components**:
- **Routes**: API endpoints for actions, auth, policies, audit
- **Middleware**: JWT validation, policy enforcement
- **Services**: Auth0 integration, policy engine, token exchange, audit logging
- **Models**: Database models (placeholder for now)
- **Utils**: Cryptographic hashing, validation

**Key Files**:
- `src/server.js`: Express server setup
- `src/routes/`: API route handlers
- `src/middleware/`: Authentication and policy middleware
- `src/services/`: Business logic services
- `src/utils/crypto.js`: Cryptographic action chain

### 3. Database

**Technology**: PostgreSQL

**Schema**:
- `actions` table: Stores all captured actions with cryptographic hashes
- Indexes on: agent_id, timestamp, domain, risk_level

## Data Flow

### Action Capture Flow

1. User/Agent performs action in browser
2. Content script intercepts action
3. Action data sent to background service worker
4. Background worker sends to backend API with JWT token
5. Backend validates token and enforces policy
6. If allowed: Action logged with cryptographic hash
7. If denied: Return error or step-up requirement

### Step-Up Authentication Flow

1. Agent attempts high-risk action
2. Backend determines insufficient scope
3. Returns `requiresStepUp: true`
4. Extension displays step-up UI
5. User provides reason and approves
6. Extension requests step-up token from backend
7. Backend exchanges token with Auth0 for temporary elevated token
8. Action proceeds with elevated privileges
9. Token expires after 30-60 seconds

## Security Architecture

### Identity Layer
- Auth0 Machine-to-Machine (M2M) authentication
- JWT tokens with scopes
- Token validation on every request

### Policy Layer
- JSON-based policy configuration
- Risk classification engine
- Domain allowlist/blocklist
- Keyword-based detection

### Audit Layer
- Cryptographic action chain (SHA256)
- Tamper-evident logging
- Immutable audit trail

## API Endpoints

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

## Cryptographic Action Chain

Each action is cryptographically linked to the previous action:

```
hash = SHA256(previous_hash + action_payload)
```

This ensures:
- Tamper-evidence: Any modification breaks the chain
- Immutability: Historical actions cannot be altered
- Verification: Chain integrity can be verified at any time

## Policy Engine

The policy engine classifies actions by:

1. **Domain Analysis**
   - Financial domain detection
   - Allowlist/blocklist checking
   - Trust profile lookup

2. **Keyword Detection**
   - High-risk keywords: delete, merge, transfer
   - Medium-risk keywords: submit, post, send

3. **Form Analysis**
   - Password field detection
   - Payment form detection

4. **Risk Classification**
   - Low: Reading, basic navigation
   - Medium: Form submissions, posts
   - High: Deletions, transfers, financial actions

## Model Context Protocol (MCP) Alignment

AgentTrust is designed to align with the Model Context Protocol, providing a standardized interface for AI agents to interact with browser environments.

### MCP-Compatible Design

**Structured Action Model**:
All browser actions follow a consistent schema that can be exposed as MCP tools:

```json
{
  "type": "browser_action",
  "name": "click_element",
  "description": "Click on a DOM element",
  "parameters": {
    "selector": "string",
    "domain": "string",
    "risk_level": "low|medium|high"
  },
  "context": {
    "url": "string",
    "domain": "string",
    "agent_id": "string"
  }
}
```

**MCP Tool Exposure**:
- Browser actions can be exposed as MCP tools/resources
- Policy engine acts as MCP tool validator
- Audit trail provides MCP context history
- Risk classification informs MCP tool availability

**Future MCP Integration**:
- Expose browser actions as MCP tools for LLM agents
- Provide MCP server that wraps AgentTrust API
- Enable LLMs to safely interact with browsers through MCP
- Maintain audit trail for all MCP-mediated actions

### Secure Tool Calling via MCP

When integrated with MCP:
1. LLM agent requests browser action via MCP
2. AgentTrust validates agent identity (Auth0 JWT)
3. Policy engine evaluates action risk
4. If approved: Action executes, logged with MCP context
5. If denied/risky: Step-up required or action blocked
6. All actions appear in audit trail with MCP metadata

## Future Enhancements

- **MCP Server Implementation**: Full MCP server exposing browser actions
- **Agent behavioral baseline detection**: Advanced anomaly detection
- **Real-time anomaly detection**: Live monitoring of agent behavior
- **WebAuthn integration for step-up**: Biometric authentication
- **Audit dashboard UI**: Web-based audit visualization
- **Session isolation**: Prevent token reuse across domains
- **Token replay prevention**: One-time use tokens
- **MCP Context History**: Long-term context for LLM agents
