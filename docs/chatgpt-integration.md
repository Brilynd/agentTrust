# AgentTrust Integration with ChatGPT's Agentic Web Browser

## Overview

This guide explains how to integrate AgentTrust with ChatGPT's browsing capabilities, enabling ChatGPT to perform browser actions through AgentTrust's policy-enforced, identity-bound system.

---

## Architecture

### Integration Options

There are two main approaches to integrate AgentTrust with ChatGPT:

1. **API Integration** (Recommended): ChatGPT calls AgentTrust API directly
2. **Chrome Extension Bridge**: Use AgentTrust extension as a bridge between ChatGPT and browser

### Recommended: API Integration

```
ChatGPT → AgentTrust API → Policy Engine → Browser Actions → Audit Log
```

---

## Setup Instructions

### Step 1: Configure AgentTrust Backend

1. **Start the AgentTrust backend**:
   ```bash
   cd backend
   npm install
   npm start
   ```

2. **Verify backend is running**:
   ```bash
   curl http://localhost:3000/health
   ```

### Step 2: Create ChatGPT Agent Identity in Auth0

1. **Create Machine-to-Machine Application in Auth0**:
   - Go to Auth0 Dashboard → Applications → Create Application
   - Choose "Machine to Machine Applications"
   - Authorize it for your API
   - Grant scopes: `browser.basic`, `browser.form.submit`, `browser.high_risk`

2. **Get Credentials**:
   - Client ID
   - Client Secret
   - API Audience

3. **Store credentials securely** (for ChatGPT to use)

### Step 3: Create ChatGPT Custom Action/Function

ChatGPT can use AgentTrust via custom functions/actions. Here's how to set it up:

#### Option A: OpenAI Function Calling

Create a custom function for ChatGPT to call AgentTrust:

```python
# chatgpt_agenttrust_integration.py
import requests
import json
from openai import OpenAI

# AgentTrust API configuration
AGENTTRUST_API_URL = "http://localhost:3000/api"
AUTH0_CLIENT_ID = "your-client-id"
AUTH0_CLIENT_SECRET = "your-client-secret"
AUTH0_DOMAIN = "your-tenant.auth0.com"
AUTH0_AUDIENCE = "your-api-identifier"

# Get Auth0 token
def get_auth0_token():
    response = requests.post(
        f"https://{AUTH0_DOMAIN}/oauth/token",
        json={
            "client_id": AUTH0_CLIENT_ID,
            "client_secret": AUTH0_CLIENT_SECRET,
            "audience": AUTH0_AUDIENCE,
            "grant_type": "client_credentials"
        }
    )
    return response.json()["access_token"]

# AgentTrust function for ChatGPT
def agenttrust_browser_action(action_type, url, target=None, form_data=None):
    """
    Execute a browser action through AgentTrust.
    
    Args:
        action_type: 'click', 'form_submit', or 'navigation'
        url: Full URL of the page
        target: Target element info (for clicks)
        form_data: Form data (for form submissions)
    """
    token = get_auth0_token()
    
    action_data = {
        "type": action_type,
        "url": url,
        "domain": url.split('/')[2],
        "timestamp": datetime.now().isoformat()
    }
    
    if target:
        action_data["target"] = target
    
    if form_data:
        action_data["form"] = {"fields": form_data}
    
    response = requests.post(
        f"{AGENTTRUST_API_URL}/actions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=action_data
    )
    
    result = response.json()
    
    if not result.get("success"):
        if result.get("requiresStepUp"):
            return {
                "status": "step_up_required",
                "message": "High-risk action requires user approval",
                "risk_level": result.get("riskLevel")
            }
        else:
            return {
                "status": "denied",
                "message": result.get("error"),
                "reason": result.get("reason")
            }
    
    return {
        "status": "allowed",
        "action_id": result["action"]["id"],
        "risk_level": result["action"]["riskLevel"]
    }

# Define function for ChatGPT
functions = [
    {
        "type": "function",
        "function": {
            "name": "agenttrust_browser_action",
            "description": "Execute a browser action (click, form submit, navigation) through AgentTrust's policy-enforced system. Returns whether action is allowed, denied, or requires step-up authentication.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["click", "form_submit", "navigation"],
                        "description": "Type of browser action"
                    },
                    "url": {
                        "type": "string",
                        "description": "Full URL of the page where action occurs"
                    },
                    "target": {
                        "type": "object",
                        "description": "Target element information (for clicks)",
                        "properties": {
                            "tagName": {"type": "string"},
                            "id": {"type": "string"},
                            "className": {"type": "string"},
                            "text": {"type": "string"}
                        }
                    },
                    "form_data": {
                        "type": "object",
                        "description": "Form data (for form submissions)"
                    }
                },
                "required": ["action_type", "url"]
            }
        }
    }
]

# Use with ChatGPT
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a browser automation assistant. Use AgentTrust to perform browser actions safely."},
        {"role": "user", "content": "Click the submit button on https://example.com"}
    ],
    functions=functions,
    function_call="auto"
)
```

#### Option B: ChatGPT Actions (OpenAI Actions)

If using ChatGPT with Actions, create an action definition:

```yaml
# agenttrust_action.yaml
openapi: 3.0.0
info:
  title: AgentTrust Browser Actions
  version: 1.0.0
servers:
  - url: http://localhost:3000/api
    description: AgentTrust API

paths:
  /actions:
    post:
      summary: Execute browser action
      operationId: executeBrowserAction
      security:
        - BearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                type:
                  type: string
                  enum: [click, form_submit, navigation]
                url:
                  type: string
                domain:
                  type: string
                target:
                  type: object
                form:
                  type: object
      responses:
        '201':
          description: Action logged successfully
        '403':
          description: Action denied by policy
        '401':
          description: Authentication required

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
```

### Step 4: Configure ChatGPT to Use AgentTrust

1. **In ChatGPT Custom Instructions**:
   ```
   When performing browser actions, always use the AgentTrust API to ensure 
   policy compliance and audit logging. Use the agenttrust_browser_action 
   function for all browser interactions.
   ```

2. **Set Environment Variables** (for your integration script):
   ```bash
   export AUTH0_CLIENT_ID="your-client-id"
   export AUTH0_CLIENT_SECRET="your-client-secret"
   export AUTH0_DOMAIN="your-tenant.auth0.com"
   export AUTH0_AUDIENCE="your-api-identifier"
   export AGENTTRUST_API_URL="http://localhost:3000/api"
   ```

---

## Usage Examples

### Example 1: Simple Click Action

```python
# ChatGPT wants to click a button
result = agenttrust_browser_action(
    action_type="click",
    url="https://github.com/user/repo",
    target={
        "tagName": "BUTTON",
        "id": "submit-btn",
        "text": "Submit"
    }
)

if result["status"] == "allowed":
    # Proceed with actual browser action
    print(f"Action allowed: {result['action_id']}")
elif result["status"] == "step_up_required":
    # Request user approval
    print("Step-up required - waiting for user approval...")
else:
    print(f"Action denied: {result['message']}")
```

### Example 2: Form Submission

```python
# ChatGPT wants to submit a form
result = agenttrust_browser_action(
    action_type="form_submit",
    url="https://example.com/form",
    form_data={
        "email": "user@example.com",
        "message": "Hello"
    }
)
```

### Example 3: Navigation

```python
# ChatGPT wants to navigate
result = agenttrust_browser_action(
    action_type="navigation",
    url="https://github.com/user/repo/issues"
)
```

---

## Handling Step-Up Authentication

When ChatGPT receives a `step_up_required` response:

1. **Notify User**: ChatGPT should inform the user that approval is needed
2. **Request Reason**: Ask user why this action is necessary
3. **Call Step-Up Endpoint**:
   ```python
   def request_step_up(action_data, reason):
       token = get_auth0_token()
       response = requests.post(
           f"{AGENTTRUST_API_URL}/auth/stepup",
           headers={
               "Authorization": f"Bearer {token}",
               "Content-Type": "application/json"
           },
           json={
               "action": action_data,
               "reason": reason
           }
       )
       return response.json()
   ```

4. **Retry Action**: Once step-up token is obtained, retry the action

---

## Policy Configuration for ChatGPT

Configure policies to work with ChatGPT:

```json
{
  "allowed_domains": [
    "github.com",
    "slack.com",
    "example.com"
  ],
  "high_risk_keywords": [
    "delete",
    "remove",
    "merge",
    "transfer"
  ],
  "requires_step_up": ["high"],
  "domain_trust_profiles": {
    "github.com": {
      "risk_multiplier": 0.5,
      "allowed_actions": ["click", "form_submit", "navigation"]
    }
  }
}
```

---

## Audit Trail

All ChatGPT actions are logged in AgentTrust:

```python
# Query ChatGPT's audit log
def get_chatgpt_audit_log(agent_id="chatgpt-agent"):
    token = get_auth0_token()
    response = requests.get(
        f"{AGENTTRUST_API_URL}/audit/agent/{agent_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    return response.json()
```

---

## Troubleshooting

### Issue: "Invalid token"
- **Solution**: Ensure Auth0 credentials are correct and token is refreshed

### Issue: "Action denied"
- **Solution**: Check policy configuration, ensure domain is allowed

### Issue: "Step-up required"
- **Solution**: Implement step-up flow or adjust policies to lower risk threshold

### Issue: Connection refused
- **Solution**: Ensure AgentTrust backend is running on correct port

---

## Security Considerations

1. **Token Storage**: Store Auth0 credentials securely (use environment variables, not code)
2. **HTTPS**: In production, use HTTPS for all API calls
3. **Rate Limiting**: AgentTrust has rate limiting - handle 429 responses
4. **Error Handling**: Always handle API errors gracefully
5. **Audit Logging**: All actions are logged - review regularly

---

## Next Steps

1. Set up Auth0 M2M application
2. Configure AgentTrust backend
3. Create ChatGPT integration script
4. Test with simple actions
5. Implement step-up flow
6. Monitor audit logs

---

## Additional Resources

- [AgentTrust API Documentation](./api.md)
- [Security Documentation](./security.md)
- [Policy Configuration Guide](./policies.md)
- [OpenAI Function Calling Documentation](https://platform.openai.com/docs/guides/function-calling)

---

**Note**: This integration enables ChatGPT to use AgentTrust's policy-enforced browser actions. The actual browser automation still needs to be implemented (via Selenium, Playwright, or similar), but AgentTrust provides the governance layer.
