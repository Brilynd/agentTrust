const { loadAgentTrustNemoclawEnv } = require('./load-env');
const { AgentTrustBridge } = require('./agenttrust-client');

loadAgentTrustNemoclawEnv();

async function main() {
  const bridge = new AgentTrustBridge({
    apiBaseUrl: process.env.AGENTTRUST_API_URL,
    auth0Domain: process.env.AUTH0_DOMAIN,
    auth0ClientId: process.env.AUTH0_CLIENT_ID,
    auth0ClientSecret: process.env.AUTH0_CLIENT_SECRET,
    auth0Audience: process.env.AUTH0_AUDIENCE,
    agentToken: process.env.AGENTTRUST_AGENT_TOKEN,
  });

  const token = await bridge.getAgentToken();
  process.stdout.write(`${token}\n`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
