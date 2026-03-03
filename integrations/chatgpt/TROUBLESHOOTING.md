# Troubleshooting: ChatGPT Agent with AgentTrust

## Quick Fix: Run Without Backend

If the extension or backend setup is failing, run in **dev mode** to get the browser automation working:

Add to your `.env` file (in `integrations/chatgpt/`, project root, or `backend/`):

```env
AGENTTRUST_DEV_MODE=true
OPENAI_API_KEY=your-openai-key
```

Then run:

```bash
cd integrations/chatgpt
python chatgpt_agent_with_agenttrust.py
```

This allows the agent to control the browser without the AgentTrust backend or Auth0.

---

## Extension Not Loading

The script loads the **browser extension** (not a website). Flow:

1. Tries Chrome with the extension
2. If Chrome 137+ blocks it, tries **Edge** (supports extensions)
3. If both fail, starts browser without extension – sign in via the extension popup after loading manually

**Manual extension loading (Chrome/Edge):**

1. Open `chrome://extensions/` or `edge://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select the `extension` folder in the project
5. Click the extension icon to sign in

**Disable extension loading:** Add `AGENTTRUST_LOAD_EXTENSION=false` to `.env`

---

## Agent Not Controlling Browser

Common causes:

### 1. Backend Not Running

The agent calls the AgentTrust API before each browser action. If the backend is down:

- **Fix:** Set `AGENTTRUST_DEV_MODE=true` in `.env` (see Quick Fix above)
- Or start the backend: `cd backend && npm start`

### 2. Auth0 Not Configured

If you see "Auth0 credentials must be provided":

- **Fix:** Set `AGENTTRUST_DEV_MODE=true` to skip Auth0
- Or configure Auth0: `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_AUDIENCE` in `.env`

### 3. Connection Refused to Backend

If the agent can't reach `http://localhost:3000`:

- Start the backend: `cd backend && npm start`
- Or use dev mode: `AGENTTRUST_DEV_MODE=true`

---

## Required for Full Stack

For full AgentTrust (with validation and audit):

1. **Backend** running on port 3000
2. **PostgreSQL** database
3. **Auth0** M2M application configured
4. **Chrome** with extension loaded (manually if auto-load fails)

See [TESTING_REQUIREMENTS.md](./TESTING_REQUIREMENTS.md) for full setup.
