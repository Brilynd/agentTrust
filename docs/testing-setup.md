# AgentTrust Testing Setup Guide

Complete step-by-step guide to set up and test AgentTrust.

---

## 📋 Prerequisites

Before you begin, ensure you have:

- ✅ Node.js 18+ installed
- ✅ npm or yarn installed
- ✅ PostgreSQL 14+ installed and running
- ✅ Google Chrome browser
- ✅ Auth0 account (free tier works)
- ✅ Git (to clone repository)

---

## Step 1: Clone and Install

### 1.1 Clone Repository
```bash
git clone <repository-url>
cd agentTrust
```

### 1.2 Install Backend Dependencies
```bash
cd backend
npm install
```

### 1.3 Install Extension Dependencies (if any)
```bash
cd ../extension
# If package.json exists:
npm install
```

---

## Step 2: Set Up PostgreSQL Database

### 2.1 Create Database
```bash
# Using psql
psql -U postgres
CREATE DATABASE agenttrust;
\q

# Or using createdb
createdb agenttrust
```

### 2.2 Verify Database
```bash
psql -U postgres -d agenttrust -c "SELECT version();"
```

---

## Step 3: Configure Auth0

### 3.1 Create Auth0 Account
1. Go to [auth0.com](https://auth0.com) and sign up (free tier works)
2. Select your region
3. Complete account setup

### 3.2 Create API (Resource Server)
1. In Auth0 Dashboard, go to **Applications** → **APIs**
2. Click **Create API**
3. Fill in:
   - **Name**: `AgentTrust API`
   - **Identifier**: `https://agenttrust.api` (or your choice)
   - **Signing Algorithm**: `RS256`
4. Click **Create**
5. **Save the Identifier** - this is your `AUTH0_AUDIENCE`

### 3.3 Create Machine-to-Machine Application
1. Go to **Applications** → **Applications**
2. Click **Create Application**
3. Fill in:
   - **Name**: `AgentTrust Agent`
   - **Application Type**: Select **Machine to Machine Applications**
4. Click **Create**
5. **Authorize** the application for your API (AgentTrust API)
6. **Grant permissions**:
   - ✅ `browser.basic`
   - ✅ `browser.form.submit`
   - ✅ `browser.high_risk`
7. **Save the credentials**:
   - **Client ID** → `AUTH0_CLIENT_ID`
   - **Client Secret** → `AUTH0_CLIENT_SECRET`
   - **Domain** → `AUTH0_DOMAIN` (e.g., `your-tenant.us.auth0.com`)

### 3.4 Create Custom Scopes (if needed)
1. Go to **APIs** → **AgentTrust API** → **Scopes**
2. Add scopes:
   - `browser.basic` - "Basic browser actions"
   - `browser.form.submit` - "Form submission actions"
   - `browser.high_risk` - "High-risk browser actions"
3. Save

---

## Step 4: Configure Backend

### 4.1 Create Environment File
```bash
cd backend
cp .env.example .env
```

### 4.2 Edit `.env` File
```bash
# Use your favorite editor
nano .env
# or
code .env
```

### 4.3 Fill in Environment Variables
```env
# Auth0 Configuration
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your-client-id-here
AUTH0_CLIENT_SECRET=your-client-secret-here
AUTH0_AUDIENCE=https://agenttrust.api

# Database Configuration
DATABASE_URL=postgresql://postgres:password@localhost:5432/agenttrust

# Server Configuration
PORT=3000
NODE_ENV=development

# Security Configuration (optional - defaults provided)
RATE_LIMIT_WINDOW_MS=900000
RATE_LIMIT_MAX_REQUESTS=100
CORS_ORIGIN=http://localhost:3000,chrome-extension://*
TOKEN_CACHE_TTL=3600
```

**Important**: Replace all placeholder values with your actual credentials!

### 4.4 Run Database Migrations
```bash
cd backend
npm run migrate
```

You should see:
```
Running migrations...
Migrations completed successfully!
```

---

## Step 5: Start Backend Server

### 5.1 Start Server
```bash
cd backend
npm start
```

You should see:
```
AgentTrust backend server running on port 3000
```

### 5.2 Test Backend Health
Open a new terminal:
```bash
curl http://localhost:3000/health
```

Expected response:
```json
{"status":"ok","timestamp":"2026-03-15T10:30:00.000Z"}
```

---

## Step 6: Set Up Chrome Extension

### 6.1 Load Extension
1. Open Chrome
2. Navigate to `chrome://extensions/`
3. Enable **Developer mode** (toggle in top right)
4. Click **Load unpacked**
5. Select the `extension` folder from your project:
   ```
   agentTrust/extension
   ```

### 6.2 Verify Extension Loaded
- You should see "AgentTrust" in your extensions list
- Extension icon should appear in Chrome toolbar

### 6.3 Configure Extension (if needed)
- Click the extension icon
- Check if popup appears
- Note: Extension may show "Not Authenticated" initially (this is normal)

---

## Step 7: Get Auth0 Token for Testing

### 7.1 Get Test Token
You'll need a token to test the API. Use one of these methods:

#### Method A: Using curl
```bash
curl -X POST https://YOUR_AUTH0_DOMAIN/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "audience": "YOUR_AUDIENCE",
    "grant_type": "client_credentials"
  }'
```

Save the `access_token` from the response.

#### Method B: Using Postman
1. Create new POST request
2. URL: `https://YOUR_AUTH0_DOMAIN/oauth/token`
3. Body (JSON):
```json
{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "audience": "YOUR_AUDIENCE",
  "grant_type": "client_credentials"
}
```
4. Send request
5. Copy `access_token` from response

#### Method C: Using Node.js Script
Create `backend/test/get-token.js`:
```javascript
const axios = require('axios');
require('dotenv').config();

async function getToken() {
  const response = await axios.post(
    `https://${process.env.AUTH0_DOMAIN}/oauth/token`,
    {
      client_id: process.env.AUTH0_CLIENT_ID,
      client_secret: process.env.AUTH0_CLIENT_SECRET,
      audience: process.env.AUTH0_AUDIENCE,
      grant_type: 'client_credentials'
    }
  );
  
  console.log('Token:', response.data.access_token);
  console.log('Expires in:', response.data.expires_in, 'seconds');
}

getToken();
```

Run:
```bash
cd backend
node test/get-token.js
```

---

## Step 8: Test the API

### 8.1 Test Token Validation
```bash
TOKEN="your-access-token-here"

curl -X POST http://localhost:3000/api/auth/validate \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"$TOKEN\"}"
```

Expected response:
```json
{
  "success": true,
  "valid": true,
  "sub": "agent_123",
  "scopes": ["browser.basic", "browser.form.submit"]
}
```

### 8.2 Test Action Logging
```bash
TOKEN="your-access-token-here"

curl -X POST http://localhost:3000/api/actions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "click",
    "url": "https://github.com/user/repo",
    "domain": "github.com",
    "target": {
      "tagName": "BUTTON",
      "id": "submit-btn",
      "text": "Submit"
    }
  }'
```

Expected response:
```json
{
  "success": true,
  "action": {
    "id": "action_1234567890_abc123",
    "agentId": "agent_123",
    "type": "click",
    "riskLevel": "low",
    "hash": "abc123...",
    "previousHash": "0"
  }
}
```

### 8.3 Test Policy Enforcement
Try a high-risk action:
```bash
curl -X POST http://localhost:3000/api/actions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "click",
    "url": "https://github.com/user/repo",
    "domain": "github.com",
    "target": {
      "tagName": "BUTTON",
      "text": "Delete Repository"
    }
  }'
```

Expected response (if step-up required):
```json
{
  "success": false,
  "error": "High-risk action requires step-up authentication",
  "requiresStepUp": true,
  "riskLevel": "high"
}
```

### 8.4 Test Audit Log Query
```bash
curl -X GET "http://localhost:3000/api/actions?limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Step 9: Test Chrome Extension

### 9.1 Test Action Capture
1. Open any website (e.g., `https://github.com`)
2. Open Chrome DevTools (F12)
3. Go to **Console** tab
4. Look for messages like: `Action captured: {...}`
5. Click on a button or link
6. Check console for action capture logs

### 9.2 Test Extension Popup
1. Click AgentTrust extension icon
2. Popup should show:
   - Agent status
   - Session stats
   - Action count

### 9.3 Test Step-Up UI
1. Navigate to a page with a "delete" button
2. Click the button
3. Step-up UI should appear (if action is high-risk)
4. Enter reason and approve/deny

---

## Step 10: Test End-to-End Flow

### 10.1 Complete Test Scenario

1. **Start Backend**:
   ```bash
   cd backend
   npm start
   ```

2. **Load Extension** in Chrome

3. **Get Auth Token** (use method from Step 7)

4. **Configure Extension** (if needed):
   - Store token in extension storage
   - Or configure extension to get token automatically

5. **Perform Browser Action**:
   - Navigate to `https://github.com`
   - Click a button
   - Extension should capture and send to backend

6. **Check Backend Logs**:
   - Should see action logged
   - Check database for action record

7. **Query Audit Log**:
   ```bash
   curl -X GET "http://localhost:3000/api/actions" \
     -H "Authorization: Bearer $TOKEN"
   ```

---

## Troubleshooting

### Issue: "Cannot connect to backend"
- **Solution**: Ensure backend is running on port 3000
- Check: `curl http://localhost:3000/health`

### Issue: "Invalid token"
- **Solution**: 
  - Verify Auth0 credentials in `.env`
  - Get fresh token
  - Check token hasn't expired

### Issue: "Database connection failed"
- **Solution**:
  - Ensure PostgreSQL is running
  - Check `DATABASE_URL` in `.env`
  - Verify database exists: `psql -U postgres -l`

### Issue: "Extension not loading"
- **Solution**:
  - Check for errors in `chrome://extensions/`
  - Verify manifest.json is valid
  - Check browser console for errors

### Issue: "Actions not being captured"
- **Solution**:
  - Check content script is loaded
  - Verify extension has proper permissions
  - Check browser console for errors

### Issue: "Policy not enforcing"
- **Solution**:
  - Check `backend/config/policies.json`
  - Verify policy engine is running
  - Check backend logs for policy evaluation

---

## Quick Test Checklist

- [ ] Backend server starts without errors
- [ ] Health endpoint returns `{"status":"ok"}`
- [ ] Can get Auth0 token
- [ ] Token validation endpoint works
- [ ] Can log an action
- [ ] Policy enforcement works (high-risk action blocked)
- [ ] Extension loads in Chrome
- [ ] Extension captures browser actions
- [ ] Actions appear in audit log
- [ ] Step-up UI appears for high-risk actions

---

## Next Steps

Once basic testing works:

1. **Test with ChatGPT Integration**:
   - See `docs/chatgpt-integration.md`
   - Use `integrations/chatgpt/agenttrust_client.py`

2. **Test Policy Scenarios**:
   - Test domain allowlists
   - Test keyword detection
   - Test risk classification

3. **Test Audit Trail**:
   - Verify cryptographic chain
   - Test chain integrity verification

4. **Test Step-Up Flow**:
   - High-risk action → Step-up UI → Token exchange → Action execution

---

## Additional Resources

- [API Documentation](./api.md) - Complete API reference
- [Security Documentation](./security.md) - Security testing
- [Policy Configuration](./policies.md) - Policy testing
- [ChatGPT Integration](./chatgpt-integration.md) - Integration testing

---

**Happy Testing! 🚀**
