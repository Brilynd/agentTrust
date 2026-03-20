const { loadAgentTrustNemoclawEnv } = require('./load-env');
const { AgentTrustBridge } = require('./agenttrust-client');

loadAgentTrustNemoclawEnv();

function mask(value) {
  if (!value) return '(missing)';
  const text = String(value);
  if (text.length <= 6) return '***';
  return `${text.slice(0, 3)}***${text.slice(-2)}`;
}

async function main() {
  const bridge = new AgentTrustBridge({
    apiBaseUrl: process.env.AGENTTRUST_API_URL,
    auth0Domain: process.env.AUTH0_DOMAIN,
    auth0ClientId: process.env.AUTH0_CLIENT_ID,
    auth0ClientSecret: process.env.AUTH0_CLIENT_SECRET,
    auth0Audience: process.env.AUTH0_AUDIENCE,
    userEmail: process.env.AGENTTRUST_USER_EMAIL,
    userPassword: process.env.AGENTTRUST_USER_PASSWORD,
    userToken: process.env.AGENTTRUST_USER_TOKEN,
  });

  console.log('AgentTrust / NeMoClaw config');
  console.log(`AGENTTRUST_API_URL=${process.env.AGENTTRUST_API_URL || '(missing)'}`);
  console.log(`AUTH0_DOMAIN=${process.env.AUTH0_DOMAIN || '(missing)'}`);
  console.log(`AUTH0_CLIENT_ID=${mask(process.env.AUTH0_CLIENT_ID)}`);
  console.log(`AUTH0_CLIENT_SECRET=${process.env.AUTH0_CLIENT_SECRET ? '***present***' : '(missing)'}`);
  console.log(`AUTH0_AUDIENCE=${process.env.AUTH0_AUDIENCE || '(missing)'}`);
  console.log(`AGENTTRUST_USER_EMAIL=${process.env.AGENTTRUST_USER_EMAIL || '(missing)'}`);
  console.log(`AGENTTRUST_USER_PASSWORD=${process.env.AGENTTRUST_USER_PASSWORD ? '***present***' : '(missing)'}`);

  try {
    await bridge.verifyConnectivity();
    console.log('Connectivity check: OK');
  } catch (error) {
    console.error(`Connectivity check failed: ${error.message || error}`);
    process.exitCode = 1;
  }
}

main();
