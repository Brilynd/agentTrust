const readline = require('readline');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function askQuestion(rl, text) {
  return new Promise((resolve) => rl.question(text, resolve));
}

class ApprovalPresenter {
  constructor({ agentTrust, pollIntervalMs = 2000, output = process.stdout } = {}) {
    if (!agentTrust) {
      throw new Error('ApprovalPresenter requires an agentTrust bridge.');
    }

    this.agentTrust = agentTrust;
    this.pollIntervalMs = pollIntervalMs;
    this.output = output;
    this.seen = new Set();
    this.running = false;
  }

  renderApproval(approval) {
    this.output.write('\n=== AgentTrust Approval Required ===\n');
    this.output.write(`ID: ${approval.id}\n`);
    this.output.write(`Risk: ${approval.riskLevel}\n`);
    this.output.write(`Type: ${approval.type}\n`);
    this.output.write(`Domain: ${approval.domain}\n`);
    this.output.write(`URL: ${approval.url}\n`);
    if (approval.impactSummary) {
      this.output.write(`Impact: ${approval.impactSummary}\n`);
    }
    if (approval.reason) {
      this.output.write(`Reason: ${approval.reason}\n`);
    }
    if (approval.preview) {
      this.output.write(`Preview: ${JSON.stringify(approval.preview, null, 2)}\n`);
    }
  }

  async promptForDecision(approval) {
    const rl = readline.createInterface({
      input: process.stdin,
      output: this.output,
    });

    try {
      const answer = await askQuestion(rl, 'Approve this action? [y/N] ');
      return /^y(es)?$/i.test(String(answer || '').trim());
    } finally {
      rl.close();
    }
  }

  async handleApproval(approval) {
    this.renderApproval(approval);
    const approved = await this.promptForDecision(approval);
    await this.agentTrust.respondToApproval(approval.id, approved);
    this.output.write(`Decision submitted: ${approved ? 'approved' : 'denied'}\n`);
  }

  async run({ sessionId } = {}) {
    this.running = true;
    await this.agentTrust.ensureUserToken();
    this.output.write('Polling for AgentTrust approvals...\n');

    while (this.running) {
      const approvals = await this.agentTrust.listPendingApprovals(sessionId);
      for (const approval of approvals) {
        if (this.seen.has(approval.id)) {
          continue;
        }
        this.seen.add(approval.id);
        await this.handleApproval(approval);
      }
      await sleep(this.pollIntervalMs);
    }
  }

  stop() {
    this.running = false;
  }
}

module.exports = {
  ApprovalPresenter,
};
