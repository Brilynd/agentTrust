# ChatGPT Integration with AgentTrust

This directory contains the integration code for using AgentTrust with ChatGPT's agentic web browser.

## Quick Start

### 1. Install Dependencies

```bash
pip install requests openai
```

### 2. Set Environment Variables

```bash
export AUTH0_DOMAIN="your-tenant.auth0.com"
export AUTH0_CLIENT_ID="your-client-id"
export AUTH0_CLIENT_SECRET="your-client-secret"
export AUTH0_AUDIENCE="your-api-identifier"
export AGENTTRUST_API_URL="http://localhost:3000/api"
```

### 3. Use the Client

```python
from agenttrust_client import AgentTrustClient, AGENTTRUST_FUNCTION_DEFINITION

# Initialize client
client = AgentTrustClient()

# Execute action
result = client.execute_action(
    action_type="click",
    url="https://github.com/user/repo",
    target={"tagName": "BUTTON", "id": "submit-btn"}
)

print(result)
```

### 4. Use with OpenAI

```python
from openai import OpenAI
from agenttrust_client import AGENTTRUST_FUNCTION_DEFINITION, AgentTrustClient

client = OpenAI()
agenttrust = AgentTrustClient()

# Add function to ChatGPT
response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "Use AgentTrust for all browser actions."},
        {"role": "user", "content": "Click the submit button on https://example.com"}
    ],
    functions=[AGENTTRUST_FUNCTION_DEFINITION],
    function_call="auto"
)
```

## Files

- `agenttrust_client.py` - **Python client library for AgentTrust API** (required for agent integration)
- `README.md` - This file

## Documentation

- [Agent Integration Guide](../../docs/agent-integration.md) - Complete integration guide
- [ChatGPT Integration Guide](../../docs/chatgpt-integration.md) - ChatGPT-specific integration
