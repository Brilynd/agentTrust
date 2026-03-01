# Testing Requirements for ChatGPT Agent with AgentTrust

Complete guide on what's required to test the ChatGPT agent integration.

---

## 📋 Prerequisites Checklist

### 1. Software Requirements

- ✅ **Python 3.8+** - [Download Python](https://www.python.org/downloads/)
- ✅ **Node.js 18+** - [Download Node.js](https://nodejs.org/)
- ✅ **PostgreSQL 14+** - [Download PostgreSQL](https://www.postgresql.org/download/)
- ✅ **Google Chrome** - [Download Chrome](https://www.google.com/chrome/)
- ✅ **ChromeDriver** - For Selenium (auto-installed or manual)

### 2. Account Requirements

- ✅ **OpenAI API Key** - [Get API Key](https://platform.openai.com/api-keys)
  - Required for ChatGPT integration
  - Paid account needed (uses GPT-4 API)
  
- ✅ **Auth0 Account** - [Sign up for Auth0](https://auth0.com)
  - Free tier works
  - Need to create API and Machine-to-Machine application

---

## 🔧 Setup Steps

### Step 1: Backend Setup

#### 1.1 Install Backend Dependencies

```bash
cd backend
npm install
```

#### 1.2 Set Up PostgreSQL Database

**Option A: Local PostgreSQL** (requires installation)
```bash
# Create database using Node.js script (no psql needed)
cd backend
npm run create-db

# Or see: backend/SETUP_DATABASE_NO_PSQL.md
```

**Option B: AWS RDS** (recommended, no local installation)
- See: `backend/SETUP_AWS_RDS.md`
- No local PostgreSQL needed
- Free tier available (12 months)
- Managed service with automatic backups

#### 1.3 Configure Backend Environment

Create `backend/.env` file:

```bash
# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/agenttrust

# Auth0 Configuration
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_AUDIENCE=https://agenttrust.api
JWKS_URI=https://your-tenant.us.auth0.com/.well-known/jwks.json

# Server
PORT=3000
NODE_ENV=development

# Security
JWT_ALGORITHM=RS256
RATE_LIMIT_WINDOW_MS=900000
RATE_LIMIT_MAX_REQUESTS=100
```

#### 1.4 Run Database Migrations

```bash
cd backend
npm run migrate
```

#### 1.5 Start Backend Server

```bash
cd backend
npm start
```

**Verify**: Backend should be running at `http://localhost:3000`

---

### Step 2: Auth0 Configuration

#### 2.1 Create API (Resource Server)

1. Go to Auth0 Dashboard → **Applications** → **APIs**
2. Click **Create API**
3. Fill in:
   - **Name**: `AgentTrust API`
   - **Identifier**: `https://agenttrust.api`
   - **Signing Algorithm**: `RS256`
4. Click **Create**
5. **Save the Identifier** → This is your `AUTH0_AUDIENCE`

#### 2.2 Create Scopes

Quick steps:
1. Go to **APIs** → **AgentTrust API** → **Scopes** tab
2. Click **+ Create** (or **Add Scope**)
3. Add each scope:
   - **Name**: `browser.basic` | **Description**: "Basic browser actions"
   - **Name**: `browser.form.submit` | **Description**: "Form submission actions"
   - **Name**: `browser.high_risk` | **Description**: "High-risk actions"
4. Click **Add** for each scope

**Verify**: You should see all three scopes listed in the Scopes tab.

#### 2.3 Create Machine-to-Machine Application

1. Go to **Applications** → **Applications**
2. Click **Create Application**
3. Fill in:
   - **Name**: `AgentTrust Agent`
   - **Application Type**: **Machine to Machine Applications**
4. Click **Create**
5. **Authorize** for `AgentTrust API`
6. **Grant permissions**:
   - ✅ `browser.basic`
   - ✅ `browser.form.submit`
   - ✅ `browser.high_risk`
7. **Save credentials**:
   - **Client ID** → `AUTH0_CLIENT_ID`
   - **Client Secret** → `AUTH0_CLIENT_SECRET`
   - **Domain** → `AUTH0_DOMAIN` (e.g., `your-tenant.us.auth0.com`)

---

### Step 3: Python Agent Setup

#### 3.1 Install Python Dependencies

```bash
cd integrations/chatgpt
pip install openai requests selenium
```

**Optional**: Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install openai requests selenium
```

#### 3.2 Install ChromeDriver

**Option A: Automatic (using webdriver-manager)**

```bash
pip install webdriver-manager
```

Then update the code to use:
```python
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)
```

**Option B: Manual**

1. Check Chrome version: `chrome://version/`
2. Download matching ChromeDriver: [ChromeDriver Downloads](https://chromedriver.chromium.org/downloads)
3. Add to PATH or place in project directory

#### 3.3 Set Environment Variables

**📖 See [ENV_FILE_LOCATIONS.md](./ENV_FILE_LOCATIONS.md) for complete guide on where to place .env files.**

**Quick setup**: You need environment variables for the Python agent. You can either:

**Option A: Set environment variables in terminal** (Recommended):

```bash
# OpenAI Configuration
export OPENAI_API_KEY="sk-..."

# Auth0 Configuration
export AUTH0_DOMAIN="your-tenant.us.auth0.com"
export AUTH0_CLIENT_ID="your-client-id"
export AUTH0_CLIENT_SECRET="your-client-secret"
export AUTH0_AUDIENCE="https://agenttrust.api"

# AgentTrust API
export AGENTTRUST_API_URL="http://localhost:3000/api"

# Browser Options (Optional)
export ENABLE_BROWSER="true"      # Enable browser automation
export HEADLESS_BROWSER="false"   # Run browser in headless mode
```

**Windows PowerShell:**
```powershell
$env:OPENAI_API_KEY="sk-..."
$env:AUTH0_DOMAIN="your-tenant.us.auth0.com"
$env:AUTH0_CLIENT_ID="your-client-id"
$env:AUTH0_CLIENT_SECRET="your-client-secret"
$env:AUTH0_AUDIENCE="https://agenttrust.api"
$env:AGENTTRUST_API_URL="http://localhost:3000/api"
```

**Windows CMD:**
```cmd
set OPENAI_API_KEY=sk-...
set AUTH0_DOMAIN=your-tenant.us.auth0.com
set AUTH0_CLIENT_ID=your-client-id
set AUTH0_CLIENT_SECRET=your-client-secret
set AUTH0_AUDIENCE=https://agenttrust.api
set AGENTTRUST_API_URL=http://localhost:3000/api
```

---

## ✅ Verification Checklist

Before testing, verify:

- [ ] Backend is running on `http://localhost:3000`
- [ ] PostgreSQL database is running and accessible
- [ ] Database migrations completed successfully
- [ ] Auth0 API created with correct identifier
- [ ] Auth0 M2M application created and authorized
- [ ] Auth0 scopes configured (`browser.basic`, `browser.form.submit`, `browser.high_risk`)
- [ ] All environment variables set correctly
- [ ] Python dependencies installed (`openai`, `requests`, `selenium`)
- [ ] ChromeDriver installed and accessible
- [ ] OpenAI API key is valid and has credits

---

## 🚀 Running Tests

### Test 1: Basic API Test (No Browser)

```bash
cd integrations/chatgpt
ENABLE_BROWSER=false python chatgpt_agent_with_agenttrust.py
```

This tests:
- ✅ AgentTrust API connectivity
- ✅ Auth0 authentication
- ✅ Function calling with ChatGPT
- ✅ AgentTrust validation flow

### Test 2: Full Browser Automation Test

```bash
cd integrations/chatgpt
python chatgpt_agent_with_agenttrust.py
```

This tests:
- ✅ All of Test 1
- ✅ Browser automation (Selenium)
- ✅ Page content retrieval
- ✅ Actual browser interactions
- ✅ Real-world agent behavior

### Test 3: Headless Browser Test

```bash
cd integrations/chatgpt
HEADLESS_BROWSER=true python chatgpt_agent_with_agenttrust.py
```

Runs browser in headless mode (no visible window).

---

## 🧪 Example Test Scenarios

### Scenario 1: Simple Navigation

**User Input**: "Navigate to https://example.com"

**Expected Flow**:
1. ChatGPT calls `get_page_content()` → Sees page
2. ChatGPT calls `agenttrust_browser_action(navigation)` → AgentTrust validates
3. If allowed → Browser navigates
4. ChatGPT reports success

### Scenario 2: High-Risk Action

**User Input**: "Delete my test repository on GitHub"

**Expected Flow**:
1. ChatGPT navigates to GitHub
2. ChatGPT finds delete button
3. ChatGPT calls `agenttrust_browser_action(click)` → AgentTrust requires step-up
4. ChatGPT asks for approval
5. User approves → Step-up token obtained
6. Action proceeds with elevated token

### Scenario 3: Denied Action

**User Input**: "Navigate to blocked-domain.com"

**Expected Flow**:
1. ChatGPT calls `agenttrust_browser_action(navigation)`
2. AgentTrust denies (policy violation)
3. ChatGPT reports denial to user

---

## 🔍 Troubleshooting

### Backend Issues

**Problem**: Backend won't start
- ✅ Check PostgreSQL is running: `pg_isready`
- ✅ Verify database exists: `psql -l | grep agenttrust`
- ✅ Check `.env` file has correct DATABASE_URL
- ✅ Verify port 3000 is not in use

**Problem**: Auth0 token validation fails
- ✅ Verify `AUTH0_DOMAIN` matches your tenant
- ✅ Check `AUTH0_AUDIENCE` matches API identifier
- ✅ Ensure JWKS URI is correct: `https://{domain}/.well-known/jwks.json`

### Python Agent Issues

**Problem**: Selenium/ChromeDriver errors
- ✅ Install ChromeDriver: `pip install webdriver-manager`
- ✅ Verify Chrome is installed: `google-chrome --version`
- ✅ Check ChromeDriver version matches Chrome version

**Problem**: OpenAI API errors
- ✅ Verify API key is valid: `sk-...`
- ✅ Check account has credits
- ✅ Ensure using GPT-4 model (not GPT-3.5)

**Problem**: Auth0 authentication fails
- ✅ Verify all Auth0 env vars are set
- ✅ Check M2M application is authorized for API
- ✅ Ensure scopes are granted

### Browser Issues

**Problem**: Browser doesn't open
- ✅ Set `ENABLE_BROWSER=true`
- ✅ Check ChromeDriver is installed
- ✅ Try headless mode: `HEADLESS_BROWSER=true`

**Problem**: Page content not retrieved
- ✅ Verify browser automation is enabled
- ✅ Check page has loaded (wait for elements)
- ✅ Verify URL is accessible

---

## 📊 Expected Output

When running successfully, you should see:

```
======================================================================
ChatGPT Agent with AgentTrust - 100% Enforcement
======================================================================

This is a REAL AI agent (ChatGPT) using AgentTrust to govern
browser actions. ChatGPT makes decisions, AgentTrust controls execution.

🔒 ENFORCEMENT: All browser actions MUST go through AgentTrust validation.
   There is no way to bypass AgentTrust - it's enforced at the execution level.

👁️  BROWSER AUTOMATION: ChatGPT can see page content and interact with the browser.
   - get_page_content: See what's on the page (read-only)
   - get_visible_elements: See buttons, links, inputs (read-only)
   - agenttrust_browser_action: Perform actions (requires validation)

✅ Browser automation enabled

👤 User: Navigate to https://example.com

🔍 ChatGPT wants to: navigation on https://example.com
   ✅ AgentTrust: ALLOWED (Risk: low)

🤖 ChatGPT: I've successfully navigated to https://example.com...
```

---

## 📝 Quick Start Summary

**Minimum requirements to test:**

1. ✅ Backend running (`npm start` in `backend/`)
2. ✅ PostgreSQL database created
3. ✅ Auth0 configured (API + M2M app)
4. ✅ Environment variables set
5. ✅ Python dependencies installed
6. ✅ Run: `python chatgpt_agent_with_agenttrust.py`

**For browser automation, also need:**
7. ✅ Selenium installed
8. ✅ ChromeDriver installed

---

## 🔗 Related Documentation

- [Complete Testing Setup Guide](../../docs/testing-setup.md)
- [Real Agent Integration Guide](../../docs/real-agent-integration.md)
- [Agent Integration Guide](../../docs/agent-integration.md)
- [ChatGPT Integration Guide](../../docs/chatgpt-integration.md)
