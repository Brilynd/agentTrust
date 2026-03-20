const { loadAgentTrustNemoclawEnv } = require('./load-env');
const {
  AgentTrustBridge,
  OpenClawBrowserAdapter,
  AgentTrustOpenClawRuntime,
} = require('./index');

loadAgentTrustNemoclawEnv();

// Replace this with the actual browser provider from your NeMoClaw/OpenClaw runtime.
// The provider must implement:
// - navigate({ url })
// - click({ target })
// - type({ target, text, clearFirst, pressEnter })
// - submit({ target })
// - openTab({ url, label })
// - switchTab({ label, index })
// - getCurrentPage()
const browserProvider = {
  async navigate({ url }) {
    throw new Error(`Implement browserProvider.navigate({ url: "${url}" })`);
  },
  async click({ target }) {
    throw new Error(`Implement browserProvider.click(${JSON.stringify(target)})`);
  },
  async type({ target, text, clearFirst, pressEnter }) {
    throw new Error(
      `Implement browserProvider.type(${JSON.stringify({ target, text, clearFirst, pressEnter })})`
    );
  },
  async submit({ target }) {
    throw new Error(`Implement browserProvider.submit(${JSON.stringify(target)})`);
  },
  async openTab({ url, label }) {
    throw new Error(`Implement browserProvider.openTab(${JSON.stringify({ url, label })})`);
  },
  async switchTab({ label, index }) {
    throw new Error(`Implement browserProvider.switchTab(${JSON.stringify({ label, index })})`);
  },
  async getCurrentPage() {
    throw new Error('Implement browserProvider.getCurrentPage()');
  },
};

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

  await bridge.verifyConnectivity();
  await bridge.loginUser();

  const browser = new OpenClawBrowserAdapter(browserProvider);
  const runtime = new AgentTrustOpenClawRuntime({
    agentTrust: bridge,
    browser,
  });

  const session = await runtime.startSession();
  await bridge.claimSession(session.id);
  await runtime.startPrompt('Research AI agent security risks and create a GitHub issue');

  const tools = runtime.createGuardedToolset();

  console.log('AgentTrust NeMoClaw bootstrap ready.');
  console.log(`sessionId=${session.id}`);
  console.log('Available tools:', Object.keys(tools).join(', '));
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
