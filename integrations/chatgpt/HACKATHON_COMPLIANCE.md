# Auth0 for AI Agents – Authorized to Act Hackathon Compliance

This integration meets the **Auth0 for AI Agents** hackathon requirements by building with **Token Vault from Auth0 for AI Agents**.

---

## Hackathon Requirements Met

> "The only requirement is to build with **Token Vault** from Auth0 for AI Agents. Let Auth0 handle the OAuth flows, token management, and consent delegation so you can stay focused. Need async auth or step-up authentication? Leave that to Auth0 for AI Agents as well."

### Token Vault Integration

| Requirement | Implementation |
|-------------|----------------|
| **Token Vault** | `auth0_token_vault.py` – client for Auth0 Token Vault token exchange |
| **OAuth flows** | Handled by Auth0; agents exchange tokens via Token Vault |
| **Token management** | Auth0 stores and refreshes tokens; no local refresh token storage |
| **Consent delegation** | Via Auth0 Connected Accounts and user consent flows |
| **Async auth** | Step-up authentication flow in AgentTrust (Auth0-backed) |
| **Step-up authentication** | `request_step_up()` in agenttrust_client; Auth0 token exchange |

### Implementation Details

1. **`auth0_token_vault.py`**
   - Uses Auth0 Token Vault for external API access (e.g., GitHub, Google, Slack).
   - Exchanges user tokens for provider-specific tokens.
   - Avoids handling refresh tokens directly; relies on Auth0.

2. **`chatgpt_agent_with_agenttrust.py`**
   - Loads the AgentTrust extension automatically when the agent starts.
   - Supports auto sign-in via `EXTENSION_LOGIN_EMAIL` and `EXTENSION_LOGIN_PASSWORD`.
   - Integrates Token Vault when configured for external API calls.

3. **AgentTrust backend**
   - Auth0 JWT validation for all actions.
   - Step-up authentication for high‑risk actions.
   - Policy-based control of agent behavior.

---

## Quick Start for Hackathon Demo

### 1. Configure Auth0 (Token Vault)

- Create an Auth0 application (M2M) for the agent.
- Configure an API with scopes: `browser.basic`, `browser.form.submit`, `browser.high_risk`.
- Enable Token Vault for Connected Accounts (in Auth0 Dashboard).
- Add OAuth2 integrations (e.g., GitHub, Google) with “Use for Connected Accounts for Token Vault”.

### 2. Environment Variables

```bash
# Required for AgentTrust + Token Vault
export AUTH0_DOMAIN=your-tenant.us.auth0.com
export AUTH0_CLIENT_ID=your_client_id
export AUTH0_CLIENT_SECRET=your_client_secret
export AUTH0_AUDIENCE=https://agenttrust.api

# Optional: Auto load extension and sign in
export EXTENSION_LOGIN_EMAIL=user@example.com
export EXTENSION_LOGIN_PASSWORD=yourpassword
export AGENTTRUST_API_URL=http://localhost:3000/api
```

### 3. Run the Agent

```bash
cd integrations/chatgpt
pip install openai requests selenium python-dotenv
python chatgpt_agent_with_agenttrust.py
```

- The AgentTrust extension loads automatically.
- If `EXTENSION_LOGIN_EMAIL` and `EXTENSION_LOGIN_PASSWORD` are set, the agent signs in to the extension automatically.

---

## Architecture: Auth0 for AI Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                    ChatGPT Agent (AI)                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  AgentTrust Client  │  Auth0 Token Vault Client                  │
│  - Action validation│  - External API token exchange             │
│  - Step-up auth     │  - OAuth, consent, token mgmt via Auth0    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Auth0 for AI Agents                                             │
│  - OAuth flows  - Token Vault  - Consent delegation              │
│  - Async auth   - Step-up authentication                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## References

- [Auth0 for AI Agents](https://auth0.com/ai/docs/intro/token-vault)
- [Token Vault – Calling APIs](https://auth0.com/docs/secure/call-apis-on-users-behalf/token-vault)
- [OAuth2 Integration – Auth0 for AI Agents](https://auth0.com/ai/docs/integrations/oauth2)
