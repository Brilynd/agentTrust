# AgentTrust API Documentation

## Base URL

```
http://localhost:3000/api
```

## Authentication

All endpoints (except `/api/auth/validate`) require an `Authorization` header:

```
Authorization: Bearer <JWT_TOKEN>
```

## Endpoints

### Actions

#### POST /api/actions

Log a browser action.

**Request Body**:
```json
{
  "type": "click",
  "timestamp": "2024-01-15T10:30:00Z",
  "domain": "github.com",
  "url": "https://github.com/user/repo",
  "target": {
    "tagName": "BUTTON",
    "id": "delete-btn",
    "className": "btn btn-danger",
    "text": "Delete Repository"
  }
}
```

**Response**:
```json
{
  "success": true,
  "action": {
    "id": "action_1234567890_abc123",
    "agentId": "agent_123",
    "type": "click",
    "timestamp": "2024-01-15T10:30:00Z",
    "domain": "github.com",
    "url": "https://github.com/user/repo",
    "riskLevel": "high",
    "hash": "abc123...",
    "previousHash": "def456..."
  }
}
```

#### GET /api/actions

Query audit log.

**Query Parameters**:
- `agentId` (optional): Filter by agent ID
- `domain` (optional): Filter by domain
- `riskLevel` (optional): Filter by risk level (low, medium, high)
- `startDate` (optional): Start date (ISO 8601)
- `endDate` (optional): End date (ISO 8601)
- `limit` (optional): Maximum results (default: 100)

**Response**:
```json
{
  "success": true,
  "actions": [...],
  "count": 42
}
```

### Authentication

#### POST /api/auth/validate

Validate a JWT token.

**Request Body**:
```json
{
  "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response**:
```json
{
  "success": true,
  "valid": true,
  "sub": "agent_123",
  "scopes": ["browser.basic", "browser.form.submit"],
  "exp": 1234567890,
  "iat": 1234567890
}
```

#### POST /api/auth/stepup

Request a step-up token for high-risk actions.

**Request Headers**:
```
Authorization: Bearer <CURRENT_TOKEN>
```

**Request Body**:
```json
{
  "action": {
    "type": "click",
    "domain": "github.com",
    "target": {
      "text": "Delete Repository"
    }
  },
  "reason": "Repository is no longer needed and has been archived"
}
```

**Response**:
```json
{
  "success": true,
  "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expiresIn": 60,
  "scopes": ["browser.basic", "browser.form.submit", "browser.high_risk"]
}
```

### Policies

#### GET /api/policies

Get current policy configuration.

**Response**:
```json
{
  "success": true,
  "policies": {
    "allowed_domains": ["github.com", "slack.com"],
    "blocked_domains": [],
    "high_risk_keywords": ["delete", "merge", "transfer"],
    "medium_risk_keywords": ["submit", "post", "send"],
    "financial_domains": ["bank", "paypal", "stripe"],
    "requires_step_up": ["high"],
    "domain_trust_profiles": {
      "github.com": {
        "risk_multiplier": 0.5,
        "allowed_actions": ["click", "form_submit", "navigation"]
      }
    }
  }
}
```

#### PUT /api/policies

Update policy configuration.

**Request Body**:
```json
{
  "policies": {
    "allowed_domains": ["github.com", "slack.com", "example.com"],
    "high_risk_keywords": ["delete", "remove", "merge"]
  }
}
```

**Response**:
```json
{
  "success": true,
  "message": "Policies updated successfully"
}
```

### Audit

#### GET /api/audit/chain

Get cryptographic action chain.

**Query Parameters**:
- `agentId` (optional): Filter by agent ID
- `limit` (optional): Maximum results (default: 100)

**Response**:
```json
{
  "success": true,
  "chain": [
    {
      "id": "action_1",
      "hash": "abc123...",
      "previousHash": "0",
      "agentId": "agent_123",
      "type": "click",
      "timestamp": "2024-01-15T10:30:00Z"
    },
    {
      "id": "action_2",
      "hash": "def456...",
      "previousHash": "abc123...",
      "agentId": "agent_123",
      "type": "form_submit",
      "timestamp": "2024-01-15T10:31:00Z"
    }
  ]
}
```

#### GET /api/audit/agent/:agentId

Get agent-specific audit log.

**Path Parameters**:
- `agentId`: Agent identifier

**Query Parameters**:
- `startDate` (optional): Start date (ISO 8601)
- `endDate` (optional): End date (ISO 8601)
- `riskLevel` (optional): Filter by risk level
- `domain` (optional): Filter by domain

**Response**:
```json
{
  "success": true,
  "auditLog": [...]
}
```

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "success": false,
  "error": "Error message here"
}
```

**HTTP Status Codes**:
- `400`: Bad Request (invalid input)
- `401`: Unauthorized (invalid or missing token)
- `403`: Forbidden (policy violation)
- `500`: Internal Server Error

## Rate Limiting

(To be implemented)

## Webhooks

(To be implemented)
