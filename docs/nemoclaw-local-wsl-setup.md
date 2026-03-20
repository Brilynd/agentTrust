# Local WSL Setup For AgentTrust + NeMoClaw

This guide is for running AgentTrust from Ubuntu installed through the Microsoft Store (WSL Ubuntu) on your Windows PC.

## What Runs Where

### Windows host

- Docker Desktop
- your editor
- optional browser and Windows-side apps

### WSL Ubuntu

- `AgentTrust` backend
- `AgentTrust` NeMoClaw integration tools
- operator approval / monitor CLI

## Recommended Repo Location

Your repo currently lives in a Windows / OneDrive path.

That works, but WSL performance and file watching are usually better if you copy the repo into the Linux filesystem:

```bash
mkdir -p ~/projects
cp -r /mnt/c/Users/madey/OneDrive/Desktop/newagenttrust ~/projects/
cd ~/projects/newagenttrust/agentTrust
```

## 1. Install WSL packages

Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y curl git build-essential python3 python3-pip
```

Install Node 20+ if it is not already present.

## 2. Backend config

Use:

- `backend/env.example`

as the template for your backend `.env`.

Minimum required values:

- `AUTH0_DOMAIN`
- `AUTH0_CLIENT_ID`
- `AUTH0_CLIENT_SECRET`
- `AUTH0_AUDIENCE`
- `DATABASE_URL`
- `JWT_SECRET`
- `CREDENTIAL_ENCRYPTION_KEY`

## 3. Start the backend

```bash
cd ~/projects/newagenttrust/agentTrust/backend
npm install
npm run migrate
npm run dev
```

If NeMoClaw runs on the same machine or in the same WSL environment, use:

```env
AGENTTRUST_API_URL=http://localhost:3000/api
```

If NeMoClaw runs remotely on NVIDIA-hosted infrastructure, `localhost` will not work. In that case expose the backend with a reachable HTTPS URL.

## 4. NeMoClaw integration config

Use:

- `integrations/nemoclaw/env.example`

as the template for your local NeMoClaw integration env file. Copy it to `integrations/nemoclaw/env.local` or `.env`.

Then verify the config:

```bash
cd ~/projects/newagenttrust/agentTrust/integrations/nemoclaw
npm install
npm run verify
```

## 5. Bootstrap your runtime

Use:

- `integrations/nemoclaw/src/local-bootstrap.example.js`

as the starting point for your actual NeMoClaw runtime bootstrap.

Replace the stub `browserProvider` with the real browser provider from your OpenClaw / NeMoClaw runtime.

## 6. Operator tooling

Approvals:

```bash
cd ~/projects/newagenttrust/agentTrust/integrations/nemoclaw
npm run approvals -- --email you@example.com --password 'your-password'
```

Monitor:

```bash
npm run monitor -- --email you@example.com --password 'your-password' --session <session_id> --follow
```

Send command:

```bash
npm run send -- --email you@example.com --password 'your-password' --session <session_id> --message "Research AI agent security risks and create a GitHub issue"
```

## 7. Quick local validation

1. Start backend
2. Run `npm run verify` in `integrations/nemoclaw`
3. Launch your NeMoClaw runtime using the guarded tools
4. Start approvals CLI
5. Start monitor CLI
6. Send a test task
7. Confirm risky actions pause for approval and screenshots attach to actions
