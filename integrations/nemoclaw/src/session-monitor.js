const fs = require('fs/promises');
const path = require('path');

function summarizeAction(action) {
  const screenshotState = action.screenshot ? 'screenshot' : 'no-screenshot';
  return [
    `${action.timestamp} ${action.status || 'allowed'}`,
    `${action.type} ${action.domain || action.url}`,
    `risk=${action.riskLevel || 'unknown'}`,
    screenshotState,
  ].join(' | ');
}

async function maybeWriteScreenshot(baseDir, action) {
  if (!baseDir || !action.screenshot || typeof action.screenshot !== 'string') {
    return;
  }

  const filename = `${action.id}.png`;
  const outputPath = path.join(baseDir, filename);
  const data = action.screenshot.includes(',')
    ? action.screenshot.split(',', 2)[1]
    : action.screenshot;

  await fs.mkdir(baseDir, { recursive: true });
  await fs.writeFile(outputPath, Buffer.from(data, 'base64'));
}

class SessionMonitor {
  constructor({ agentTrust, output = process.stdout } = {}) {
    if (!agentTrust) {
      throw new Error('SessionMonitor requires an agentTrust bridge.');
    }

    this.agentTrust = agentTrust;
    this.output = output;
    this.lastActionCount = 0;
    this.lastPromptCount = 0;
  }

  async printSnapshot(sessionId, { screenshotsDir } = {}) {
    const session = await this.agentTrust.getSession(sessionId);
    const prompts = session.prompts || [];
    const actions = session.actions || [];

    if (prompts.length !== this.lastPromptCount) {
      const prompt = prompts[prompts.length - 1];
      if (prompt) {
        this.output.write(`\nPrompt: ${prompt.content}\n`);
        if (prompt.progress) {
          this.output.write(`Progress:\n${prompt.progress}\n`);
        }
        if (prompt.response) {
          this.output.write(`Response:\n${prompt.response}\n`);
        }
      }
      this.lastPromptCount = prompts.length;
    }

    if (actions.length !== this.lastActionCount) {
      const newActions = actions.slice(this.lastActionCount);
      for (const action of newActions) {
        this.output.write(`${summarizeAction(action)}\n`);
        await maybeWriteScreenshot(screenshotsDir, action);
      }
      this.lastActionCount = actions.length;
    }

    return session;
  }
}

module.exports = {
  SessionMonitor,
};
