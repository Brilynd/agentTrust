# Agent Integration Guide

## Overview

AgentTrust is designed to **monitor and govern AI agents** performing automated browser actions, not human users. This guide explains how to set up agents to use AgentTrust for policy-enforced browser automation.

---

## Architecture: Agent-First Design

### How It Works

```
AI Agent → AgentTrust API → Policy Check → Browser Action → Audit Log
                ↓
         (Allowed/Denied/Step-Up)
```

**Key Point**: Agents call AgentTrust API **before** performing browser actions. AgentTrust validates, logs, and controls what agents can do.

---

## Integration Patterns

### Pattern 1: API-First (Recommended)

Agents call AgentTrust API to:
1. **Check if action is allowed** (pre-execution validation)
2. **Get approval** for high-risk actions
3. **Log actions** after execution

### Pattern 2: Browser Extension Bridge

Chrome extension intercepts agent actions and validates through AgentTrust API.

### Pattern 3: Proxy Layer

Agent actions go through AgentTrust proxy that enforces policies.

---

## Setup for Agent Monitoring

### Step 1: Configure Agent Identity in Auth0

Each agent needs its own identity:

1. **Create M2M Application per Agent**:
   - Go to Auth0 Dashboard → Applications
   - Create new M2M application
   - Name: `Agent-{agent-name}` (e.g., `Agent-ChatGPT`, `Agent-AutoGPT`)
   - Authorize for AgentTrust API
   - Grant appropriate scopes

2. **Agent Credentials**:
   - Each agent gets: `CLIENT_ID`, `CLIENT_SECRET`
   - Store securely (environment variables, secrets manager)

### Step 2: Agent Integration Code

Agents should integrate AgentTrust **before** performing browser actions.

#### Example: Python Agent

```python
from agenttrust_client import AgentTrustClient

class BrowserAgent:
    def __init__(self, agent_name):
        self.agenttrust = AgentTrustClient()
        self.agent_name = agent_name
    
    async def click(self, url, selector):
        """Click with AgentTrust validation"""
        # 1. Check with AgentTrust first
        result = self.agenttrust.execute_action(
            action_type="click",
            url=url,
            target={"selector": selector}
        )
        
        if result["status"] == "denied":
            raise Exception(f"Action denied: {result['message']}")
        
        if result["status"] == "step_up_required":
            # Request user approval
            approval = await self.request_approval(result)
            if not approval:
                raise Exception("Action not approved")
            
            # Get step-up token
            step_up = self.agenttrust.request_step_up(
                action_data={"type": "click", "url": url},
                reason=approval["reason"]
            )
            if not step_up["success"]:
                raise Exception("Step-up failed")
        
        # 2. Action is allowed - perform it
        action_id = result.get("action_id")
        await self.perform_click(url, selector)
        
        # 3. Log completion (optional - AgentTrust already logged)
        return {"success": True, "action_id": action_id}
    
    async def request_approval(self, result):
        """Request user approval for high-risk action"""
        # Implement your approval UI/API
        # Return: {"approved": True, "reason": "..."}
        pass
```

#### Example: JavaScript/Node.js Agent

```javascript
const { AgentTrustClient } = require('./agenttrust-client');

class BrowserAgent {
  constructor(agentName) {
    this.agenttrust = new AgentTrustClient();
    this.agentName = agentName;
  }
  
  async click(url, selector) {
    // 1. Check with AgentTrust
    const result = await this.agenttrust.executeAction({
      type: 'click',
      url: url,
      target: { selector: selector }
    });
    
    if (result.status === 'denied') {
      throw new Error(`Action denied: ${result.message}`);
    }
    
    if (result.status === 'step_up_required') {
      // Request approval
      const approval = await this.requestApproval(result);
      if (!approval.approved) {
        throw new Error('Action not approved');
      }
      
      // Get step-up token
      const stepUp = await this.agenttrust.requestStepUp(
        { type: 'click', url: url },
        approval.reason
      );
      
      if (!stepUp.success) {
        throw new Error('Step-up failed');
      }
    }
    
    // 2. Perform action
    await this.performClick(url, selector);
    
    return { success: true, actionId: result.action_id };
  }
}
```

---

## Agent Setup Examples

### Example 1: Selenium Agent

```python
from selenium import webdriver
from agenttrust_client import AgentTrustClient

class AgentTrustSelenium:
    def __init__(self):
        self.driver = webdriver.Chrome()
        self.agenttrust = AgentTrustClient()
    
    def click_with_validation(self, element):
        """Click element with AgentTrust validation"""
        url = self.driver.current_url
        element_info = {
            "tagName": element.tag_name,
            "id": element.get_attribute("id"),
            "text": element.text
        }
        
        # Check with AgentTrust
        result = self.agenttrust.execute_action(
            action_type="click",
            url=url,
            target=element_info
        )
        
        if result["status"] != "allowed":
            if result["status"] == "step_up_required":
                # Handle step-up
                raise Exception("Step-up required - implement approval flow")
            else:
                raise Exception(f"Action denied: {result['message']}")
        
        # Action allowed - proceed
        element.click()
        return result["action_id"]
```

### Example 2: Playwright Agent

```python
from playwright.sync_api import sync_playwright
from agenttrust_client import AgentTrustClient

class AgentTrustPlaywright:
    def __init__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.page = self.browser.new_page()
        self.agenttrust = AgentTrustClient()
    
    def click_with_validation(self, selector):
        """Click with AgentTrust validation"""
        url = self.page.url
        element = self.page.locator(selector)
        
        element_info = {
            "selector": selector,
            "text": element.inner_text() if element.count() > 0 else None
        }
        
        # Validate with AgentTrust
        result = self.agenttrust.execute_action(
            action_type="click",
            url=url,
            target=element_info
        )
        
        if result["status"] != "allowed":
            raise Exception(f"Action not allowed: {result['message']}")
        
        # Perform action
        element.click()
        return result["action_id"]
```

### Example 3: Puppeteer Agent

```javascript
const puppeteer = require('puppeteer');
const { AgentTrustClient } = require('./agenttrust-client');

class AgentTrustPuppeteer {
  constructor() {
    this.agenttrust = new AgentTrustClient();
  }
  
  async init() {
    this.browser = await puppeteer.launch();
    this.page = await this.browser.newPage();
  }
  
  async clickWithValidation(selector) {
    const url = this.page.url();
    const element = await this.page.$(selector);
    
    const elementInfo = {
      selector: selector,
      text: await this.page.evaluate(el => el.textContent, element)
    };
    
    // Validate with AgentTrust
    const result = await this.agenttrust.executeAction({
      type: 'click',
      url: url,
      target: elementInfo
    });
    
    if (result.status !== 'allowed') {
      throw new Error(`Action not allowed: ${result.message}`);
    }
    
    // Perform action
    await element.click();
    return result.action_id;
  }
}
```

---

## Chrome Extension for Agent Actions

The Chrome extension can also monitor agent actions if agents are running in the browser:

### Setup Extension for Agent Monitoring

1. **Extension intercepts all actions** (already implemented)
2. **Extension validates with AgentTrust API**
3. **Extension blocks/allows based on policy**

### Configuration

Update `extension/background/service-worker.js` to:
- Accept agent identity from actions
- Validate actions through AgentTrust API
- Block actions that are denied

---

## Agent Registration Flow

### 1. Register Agent in Auth0

```bash
# Each agent gets its own M2M application
# Store credentials securely
AGENT_NAME="ChatGPT-Browser-Agent"
AUTH0_CLIENT_ID="agent-client-id"
AUTH0_CLIENT_SECRET="agent-client-secret"
```

### 2. Agent Initialization

```python
# Agent initializes with its credentials
agenttrust = AgentTrustClient(
    auth0_client_id=os.getenv("AUTH0_CLIENT_ID"),
    auth0_client_secret=os.getenv("AUTH0_CLIENT_SECRET"),
    auth0_domain=os.getenv("AUTH0_DOMAIN"),
    auth0_audience=os.getenv("AUTH0_AUDIENCE")
)
```

### 3. Agent Performs Actions

```python
# Before every browser action:
result = agenttrust.execute_action(...)

# If allowed, proceed
# If denied, stop
# If step-up required, request approval
```

---

## Policy Configuration for Agents

Configure policies to control what agents can do:

```json
{
  "allowed_domains": [
    "github.com",
    "slack.com"
  ],
  "blocked_domains": [],
  "high_risk_keywords": [
    "delete",
    "remove",
    "merge",
    "transfer"
  ],
  "requires_step_up": ["high"],
  "agent_restrictions": {
    "ChatGPT-Agent": {
      "max_actions_per_hour": 100,
      "allowed_domains": ["github.com", "slack.com"],
      "blocked_actions": ["delete"]
    },
    "AutoGPT-Agent": {
      "max_actions_per_hour": 50,
      "allowed_domains": ["github.com"]
    }
  }
}
```

---

## Monitoring Agent Actions

### View Agent-Specific Audit Log

```python
# Get all actions by a specific agent
audit_log = agenttrust.get_audit_log(
    agent_id="chatgpt-agent-123",
    start_date="2026-03-01T00:00:00Z",
    end_date="2026-03-15T23:59:59Z"
)

for action in audit_log["actions"]:
    print(f"{action['timestamp']}: {action['type']} on {action['domain']}")
    print(f"  Risk: {action['riskLevel']}")
    print(f"  Status: {action['status']}")
```

### Real-Time Monitoring

```python
# Poll for recent actions
import time

while True:
    recent = agenttrust.get_audit_log(
        agent_id="chatgpt-agent-123",
        limit=10
    )
    
    for action in recent["actions"]:
        if action["riskLevel"] == "high":
            alert(f"High-risk action: {action['type']} on {action['domain']}")
    
    time.sleep(60)  # Check every minute
```

---

## Best Practices

### 1. Always Validate Before Acting

```python
# ❌ BAD: Perform action without validation
element.click()

# ✅ GOOD: Validate first
result = agenttrust.execute_action(...)
if result["status"] == "allowed":
    element.click()
```

### 2. Handle Step-Up Gracefully

```python
if result["status"] == "step_up_required":
    # Don't fail immediately
    # Request approval
    approval = await request_user_approval(result)
    if approval:
        # Get step-up token and retry
        step_up = agenttrust.request_step_up(...)
```

### 3. Log All Actions

AgentTrust logs automatically, but you can also log in your agent:

```python
action_id = result.get("action_id")
agent_log.info(f"Action {action_id} performed: {action_type} on {url}")
```

### 4. Monitor Agent Behavior

```python
# Track agent actions
stats = {
    "total_actions": 0,
    "denied_actions": 0,
    "step_up_required": 0
}

# Update stats based on AgentTrust responses
```

---

## Testing Agent Integration

### Test Script

```python
from agenttrust_client import AgentTrustClient

def test_agent_integration():
    agenttrust = AgentTrustClient()
    
    # Test 1: Low-risk action (should be allowed)
    result = agenttrust.execute_action(
        action_type="click",
        url="https://github.com/user/repo",
        target={"text": "View"}
    )
    assert result["status"] == "allowed"
    
    # Test 2: High-risk action (should require step-up)
    result = agenttrust.execute_action(
        action_type="click",
        url="https://github.com/user/repo",
        target={"text": "Delete Repository"}
    )
    assert result["status"] == "step_up_required"
    
    # Test 3: Blocked domain (should be denied)
    result = agenttrust.execute_action(
        action_type="click",
        url="https://blocked-site.com",
        target={"text": "Click"}
    )
    assert result["status"] == "denied"
    
    print("✅ All tests passed!")

if __name__ == "__main__":
    test_agent_integration()
```

---

## Troubleshooting

### Issue: "Agent not authenticated"
- **Solution**: Ensure agent has valid Auth0 credentials
- **Check**: Token is not expired, credentials are correct

### Issue: "All actions denied"
- **Solution**: Check policy configuration
- **Check**: Agent's domain is in allowed list
- **Check**: Agent has required scopes

### Issue: "Step-up always required"
- **Solution**: Adjust risk classification thresholds
- **Check**: Policy `requires_step_up` setting

---

## Summary

**Key Points**:
1. Agents call AgentTrust API **before** performing browser actions
2. Each agent has its own Auth0 identity
3. AgentTrust validates, logs, and controls agent actions
4. High-risk actions require step-up approval
5. All actions are logged with cryptographic proof

**AgentTrust monitors agents, not humans** - it's the governance layer for AI agent browser automation.

---

## Next Steps

1. Set up agent identities in Auth0
2. Integrate AgentTrust client into your agent code
3. Configure policies for your agents
4. Test with sample actions
5. Monitor agent behavior through audit logs

See also:
- [Testing Setup Guide](./testing-setup.md)
- [ChatGPT Integration](./chatgpt-integration.md)
- [API Documentation](./api.md)
