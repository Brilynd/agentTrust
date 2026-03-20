const fs = require('fs');
const path = require('path');

function parseEnv(content) {
  const lines = String(content || '').split(/\r?\n/);
  const out = {};

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    const eq = trimmed.indexOf('=');
    if (eq === -1) {
      continue;
    }

    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    out[key] = value;
  }

  return out;
}

function loadEnvFiles(paths) {
  for (const filePath of paths) {
    if (!filePath || !fs.existsSync(filePath)) {
      continue;
    }

    const parsed = parseEnv(fs.readFileSync(filePath, 'utf8'));
    for (const [key, value] of Object.entries(parsed)) {
      if (!process.env[key]) {
        process.env[key] = value;
      }
    }
  }
}

function loadAgentTrustNemoclawEnv() {
  const here = __dirname;
  const integrationRoot = path.resolve(here, '..');
  const projectRoot = path.resolve(integrationRoot, '..', '..');
  const backendRoot = path.resolve(projectRoot, 'backend');

  loadEnvFiles([
    path.join(integrationRoot, '.env'),
    path.join(integrationRoot, 'env.local'),
    path.join(projectRoot, '.env'),
    path.join(backendRoot, '.env'),
  ]);
}

module.exports = {
  loadAgentTrustNemoclawEnv,
};
