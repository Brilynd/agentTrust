#!/usr/bin/env node
const { AgentTrustBridge } = require('./agenttrust-client');
const { ApprovalPresenter } = require('./approval-presenter');
const { SessionMonitor } = require('./session-monitor');

function getArg(flag, fallback = null) {
  const idx = process.argv.indexOf(flag);
  if (idx === -1 || idx + 1 >= process.argv.length) {
    return fallback;
  }
  return process.argv[idx + 1];
}

function hasFlag(flag) {
  return process.argv.includes(flag);
}

async function main() {
  const command = process.argv[2];
  const bridge = new AgentTrustBridge({
    apiBaseUrl: getArg('--api-base-url') || process.env.AGENTTRUST_API_URL,
    auth0Domain: getArg('--auth0-domain') || process.env.AUTH0_DOMAIN,
    auth0ClientId: getArg('--auth0-client-id') || process.env.AUTH0_CLIENT_ID,
    auth0ClientSecret: getArg('--auth0-client-secret') || process.env.AUTH0_CLIENT_SECRET,
    auth0Audience: getArg('--auth0-audience') || process.env.AUTH0_AUDIENCE,
    userEmail: getArg('--email') || process.env.AGENTTRUST_USER_EMAIL,
    userPassword: getArg('--password') || process.env.AGENTTRUST_USER_PASSWORD,
    userToken: getArg('--user-token') || process.env.AGENTTRUST_USER_TOKEN,
  });

  if (command === 'approvals') {
    const presenter = new ApprovalPresenter({ agentTrust: bridge });
    await presenter.run({ sessionId: getArg('--session') || undefined });
    return;
  }

  if (command === 'monitor') {
    const sessionId = getArg('--session');
    if (!sessionId) {
      throw new Error('monitor requires --session <id>');
    }

    await bridge.ensureUserToken();
    await bridge.claimSession(sessionId);
    const monitor = new SessionMonitor({ agentTrust: bridge });
    const screenshotsDir = getArg('--screenshots-dir') || undefined;

    do {
      await monitor.printSnapshot(sessionId, { screenshotsDir });
      if (!hasFlag('--follow')) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    } while (true);
    return;
  }

  if (command === 'send') {
    const sessionId = getArg('--session');
    const message = getArg('--message');
    if (!sessionId || !message) {
      throw new Error('send requires --session <id> and --message "<text>"');
    }

    await bridge.ensureUserToken();
    await bridge.claimSession(sessionId);
    const result = await bridge.sendCommand(message, sessionId);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  process.stdout.write(
    [
      'Usage:',
      '  agenttrust-nemoclaw approvals --email <email> --password <password> [--session <id>]',
      '  agenttrust-nemoclaw monitor --email <email> --password <password> --session <id> [--follow] [--screenshots-dir <dir>]',
      '  agenttrust-nemoclaw send --email <email> --password <password> --session <id> --message "<text>"',
    ].join('\n') + '\n'
  );
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
