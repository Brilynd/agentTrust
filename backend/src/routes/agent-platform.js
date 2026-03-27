const express = require('express');

const store = require('../services/agentPlatformStore');
const { emitPlatformEvent } = require('../services/platformSocket');
const workerManager = require('../services/workerManager');
const { clearPendingApprovals } = require('./approvals');

const router = express.Router();

const DEFAULT_CONFIG_HIGH_RISK_KEYWORDS = [
  'payment',
  'billing',
  'submit',
  'delete',
  'refund',
  'transfer',
  'wire',
  'bank',
  'ssn',
  'password'
];
const DEFAULT_CONFIG_AUDITOR_KEYWORDS = [
  'login',
  'log in',
  'sign in',
  'form',
  'account',
  'summary',
  'description',
  'search',
  'navigate',
  'upload'
];

function normalizeJobInput(body) {
  const raw = body && typeof body === 'object' ? body : {};
  const details = raw.details && typeof raw.details === 'object' && !Array.isArray(raw.details)
    ? raw.details
    : {};

  const merged = {
    ...details,
    ...raw,
    metadata: {
      ...(details.metadata || {}),
      ...(raw.metadata || {})
    }
  };
  delete merged.details;

  const task = String(merged.task || '').trim();
  if (!task) {
    throw new Error('Task prompt is required');
  }
  const steps = Array.isArray(merged.steps) ? merged.steps : [];

  return {
    task,
    agentId: merged.agentId ? String(merged.agentId) : undefined,
    sessionId: merged.sessionId ? String(merged.sessionId) : undefined,
    promptId: merged.promptId ? String(merged.promptId) : undefined,
    allowedDomains: Array.isArray(merged.allowedDomains) ? merged.allowedDomains.map((value) => String(value)) : undefined,
    startUrl: merged.startUrl ? String(merged.startUrl) : undefined,
    verifyText: merged.verifyText ? String(merged.verifyText) : undefined,
    steps,
    metadata: merged.metadata && typeof merged.metadata === 'object' ? merged.metadata : undefined
  };
}

function uniqueStrings(values) {
  return Array.from(new Set(values.map((value) => String(value).trim()).filter(Boolean)));
}

function extractPromptUrls(prompt) {
  return uniqueStrings(prompt.match(/https?:\/\/[^\s"')\]}]+/gi) || []);
}

function extractPromptDomains(prompt, urls) {
  const domains = urls
    .map((value) => {
      try {
        return new URL(value).hostname.replace(/^www\./, '');
      } catch {
        return '';
      }
    })
    .filter(Boolean);
  const inlineDomains = prompt.match(/\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b/gi) || [];
  return uniqueStrings([...domains, ...inlineDomains.map((value) => value.replace(/^www\./, '').toLowerCase())]);
}

function extractPromptVerifyText(prompt) {
  const lower = prompt.toLowerCase();
  const verifyCue = lower.includes('verify') || lower.includes('confirm') || lower.includes('ensure') || lower.includes('look for') || lower.includes('check for');
  const quoted = prompt.match(/"([^"]+)"|'([^']+)'/);
  if (verifyCue && quoted) {
    return (quoted[1] || quoted[2] || '').trim();
  }
  return '';
}

function buildConfigurationName(prompt, domains) {
  const subject = domains[0]
    ? domains[0].split('.')[0]
    : prompt.replace(/[^a-z0-9 ]/gi, ' ').split(/\s+/).filter(Boolean).slice(0, 4).join(' ');
  const title = subject.split(/\s+/).filter(Boolean).map((value) => value.charAt(0).toUpperCase() + value.slice(1)).join(' ');
  return `${title || 'Generated'} Bot`;
}

function generateConfigurationDraftFallback(prompt) {
  const trimmed = prompt.trim();
  const urls = extractPromptUrls(trimmed);
  const domains = extractPromptDomains(trimmed, urls);
  const lower = trimmed.toLowerCase();
  return {
    name: buildConfigurationName(trimmed, domains),
    description: trimmed,
    task: trimmed,
    allowedDomains: domains,
    startUrl: urls[0] || '',
    verifyText: extractPromptVerifyText(trimmed),
    highRiskKeywords: DEFAULT_CONFIG_HIGH_RISK_KEYWORDS.filter((keyword) => lower.includes(keyword)),
    auditorKeywords: DEFAULT_CONFIG_AUDITOR_KEYWORDS.filter((keyword) => lower.includes(keyword)),
    advancedJson: {
      metadata: {
        intentSummary: trimmed,
        completionCriteria: extractPromptVerifyText(trimmed) || 'Complete the requested task and verify the expected user-visible outcome.',
        planningHints: urls[0] ? [`Prefer starting at ${urls[0]}`] : [],
        recoveryHints: ['If the first approach stalls, inspect the visible page state and continue toward the intended end state instead of stopping early.'],
        generatedFromPrompt: true,
        sourcePrompt: trimmed
      }
    }
  };
}

function parseJsonObject(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    const match = raw.match(/\{[\s\S]*\}/);
    if (!match) return null;
    try {
      const parsed = JSON.parse(match[0]);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }
}

function normalizeGeneratedDraft(prompt, draft) {
  const fallback = generateConfigurationDraftFallback(prompt);
  const candidate = draft || {};
  const advancedJson = candidate.advancedJson && typeof candidate.advancedJson === 'object' && !Array.isArray(candidate.advancedJson)
    ? candidate.advancedJson
    : fallback.advancedJson;
  return {
    name: String(candidate.name || fallback.name).trim() || fallback.name,
    description: String(candidate.description || fallback.description).trim() || fallback.description,
    task: String(candidate.task || fallback.task).trim() || fallback.task,
    allowedDomains: Array.isArray(candidate.allowedDomains)
      ? uniqueStrings(candidate.allowedDomains.map((value) => String(value)))
      : fallback.allowedDomains,
    startUrl: String(candidate.startUrl || fallback.startUrl).trim(),
    verifyText: String(candidate.verifyText || fallback.verifyText).trim(),
    highRiskKeywords: Array.isArray(candidate.highRiskKeywords)
      ? uniqueStrings(candidate.highRiskKeywords.map((value) => String(value)))
      : fallback.highRiskKeywords,
    auditorKeywords: Array.isArray(candidate.auditorKeywords)
      ? uniqueStrings(candidate.auditorKeywords.map((value) => String(value)))
      : fallback.auditorKeywords,
    advancedJson: {
      ...advancedJson,
      metadata: {
        ...(advancedJson.metadata && typeof advancedJson.metadata === 'object' && !Array.isArray(advancedJson.metadata)
          ? advancedJson.metadata
          : {}),
        generatedFromPrompt: true,
        sourcePrompt: prompt.trim()
      }
    }
  };
}

async function generateConfigurationDraft(prompt) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    console.warn('OPENAI_API_KEY not set; using fallback configuration generation');
    return generateConfigurationDraftFallback(prompt);
  }

  const model = process.env.OPENAI_MODEL_FAST || process.env.OPENAI_MODEL || 'gpt-4.1-mini';
  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      temperature: 0.2,
      response_format: { type: 'json_object' },
      messages: [
        {
          role: 'system',
          content:
            'You generate reusable browser-bot configurations for AgentTrust. ' +
            'Infer all fields from the user prompt. Return strict JSON only with keys: ' +
            'name, description, task, allowedDomains, startUrl, verifyText, highRiskKeywords, auditorKeywords, advancedJson. ' +
            'Do not create rigid browser steps. Instead, put richer planner guidance inside advancedJson.metadata, including intentSummary, completionCriteria, planningHints, recoveryHints, and startingContext when useful.'
        },
        {
          role: 'user',
          content:
            `Generate a full bot configuration draft for this prompt:\n\n${prompt}\n\n` +
            'Return JSON only.'
        }
      ]
    })
  });
  if (!response.ok) {
    throw new Error(`OpenAI configuration generation failed (${response.status}): ${await response.text()}`);
  }
  const payload = await response.json();
  return normalizeGeneratedDraft(prompt, parseJsonObject(payload.choices?.[0]?.message?.content || ''));
}

router.get('/jobs', async (_req, res) => {
  try {
    const jobs = await store.listJobs();
    res.json({ success: true, jobs });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/jobs/:jobId', async (req, res) => {
  try {
    const job = await store.getJob(req.params.jobId);
    if (!job) {
      return res.status(404).json({ success: false, error: 'Job not found' });
    }
    res.json({ success: true, job });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/jobs', async (req, res) => {
  try {
    const input = normalizeJobInput(req.body);
    const job = await store.createJob(input);
    emitPlatformEvent('job.created', job);
    await workerManager.spawnWorkerForJob(job.id);
    res.status(202).json({ success: true, job });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/jobs/:jobId/context', async (req, res) => {
  try {
    const prompt = String(req.body?.prompt || '').trim();
    const details = req.body?.details && typeof req.body.details === 'object' && !Array.isArray(req.body.details)
      ? req.body.details
      : {};
    if (!prompt) {
      return res.status(400).json({ success: false, error: 'Prompt is required' });
    }
    const result = await store.appendJobContext(req.params.jobId, prompt, details);
    if (!result) {
      return res.status(404).json({ success: false, error: 'Job not found' });
    }
    emitPlatformEvent('job.context_added', { jobId: req.params.jobId, prompt, details });
    emitPlatformEvent('job.updated', result.job);
    res.status(202).json({ success: true, ...result });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/jobs/:jobId/correct', async (req, res) => {
  try {
    const prompt = String(req.body?.prompt || '').trim();
    const details = req.body?.details && typeof req.body.details === 'object' && !Array.isArray(req.body.details)
      ? req.body.details
      : {};
    if (!prompt) {
      return res.status(400).json({ success: false, error: 'Prompt is required' });
    }
    const contextResult = await store.appendJobContext(req.params.jobId, prompt, details);
    if (!contextResult) {
      return res.status(404).json({ success: false, error: 'Job not found' });
    }
    await store.updateJobControl(req.params.jobId, {
      pauseRequested: false,
      cancelRequested: false,
      status: 'running',
      error: null
    });
    await workerManager.spawnWorkerForJob(req.params.jobId);
    const job = await store.getJob(req.params.jobId);
    emitPlatformEvent('job.context_added', { jobId: req.params.jobId, prompt, details });
    emitPlatformEvent('job.updated', job);
    res.status(202).json({
      success: true,
      job,
      appendedSteps: contextResult.appendedSteps,
      context: contextResult.context
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/jobs/:jobId/pause', async (req, res) => {
  try {
    const job = await store.updateJobControl(req.params.jobId, { pauseRequested: true, status: 'paused' });
    emitPlatformEvent('job.updated', job);
    res.json({ success: true, job });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/jobs/:jobId/resume', async (req, res) => {
  try {
    const job = await store.updateJobControl(req.params.jobId, {
      pauseRequested: false,
      cancelRequested: false,
      status: 'running',
      error: null
    });
    await workerManager.spawnWorkerForJob(req.params.jobId);
    emitPlatformEvent('job.updated', job);
    res.json({ success: true, job });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/jobs/:jobId/cancel', async (req, res) => {
  try {
    const job = await store.updateJobControl(req.params.jobId, { cancelRequested: true, status: 'cancelled' });
    await workerManager.stopWorkerForJob(req.params.jobId);
    emitPlatformEvent('job.updated', job);
    res.json({ success: true, job });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/configurations', async (_req, res) => {
  try {
    const configurations = await store.listConfigurations();
    res.json({ success: true, configurations });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/configurations/generate', async (req, res) => {
  try {
    const prompt = String(req.body?.prompt || '').trim();
    if (!prompt) {
      return res.status(400).json({ success: false, error: 'Prompt is required' });
    }
    const draft = await generateConfigurationDraft(prompt);
    res.json({ success: true, draft });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/configurations', async (req, res) => {
  try {
    const name = String(req.body?.name || '').trim();
    const task = String(req.body?.task || '').trim();
    const description = String(req.body?.description || '').trim();
    const details = req.body?.details && typeof req.body.details === 'object' && !Array.isArray(req.body.details)
      ? req.body.details
      : null;
    if (!name || !task || !details) {
      return res.status(400).json({ success: false, error: 'name, task, and details are required' });
    }
    const configuration = await store.createConfiguration({ name, task, description, details });
    res.status(201).json({ success: true, configuration });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.put('/configurations/:configId', async (req, res) => {
  try {
    const existing = await store.getConfiguration(req.params.configId);
    if (!existing) {
      return res.status(404).json({ success: false, error: 'Configuration not found' });
    }
    const configuration = await store.updateConfiguration(req.params.configId, {
      name: String(req.body?.name || existing.name).trim(),
      description: String(req.body?.description || existing.description || '').trim() || undefined,
      task: String(req.body?.task || existing.task).trim(),
      details: req.body?.details && typeof req.body.details === 'object' && !Array.isArray(req.body.details)
        ? req.body.details
        : existing.details
    });
    res.json({ success: true, configuration });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/configurations/:configId/launch', async (req, res) => {
  try {
    const configuration = await store.getConfiguration(req.params.configId);
    if (!configuration) {
      return res.status(404).json({ success: false, error: 'Configuration not found' });
    }
    const taskOverride = String(req.body?.taskOverride || '').trim();
    const runtimeMetadata = req.body?.runtimeMetadata && typeof req.body.runtimeMetadata === 'object' && !Array.isArray(req.body.runtimeMetadata)
      ? req.body.runtimeMetadata
      : {};
    const input = normalizeJobInput({
      task: taskOverride || configuration.task,
      details: configuration.details
    });
    const job = await store.createJob(input, { runtimeMetadata, configuration });
    emitPlatformEvent('job.created', job);
    await workerManager.spawnWorkerForJob(job.id);
    res.status(202).json({ success: true, job, configuration });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/metrics/summary', async (_req, res) => {
  try {
    const metrics = await store.getMetricsSummary();
    res.json({ success: true, metrics });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/dashboard/reset-history', async (_req, res) => {
  try {
    clearPendingApprovals('Dashboard history reset');
    const cleared = await store.clearHistoricalActivity();
    emitPlatformEvent('dashboard.history_cleared', cleared);
    res.json({ success: true, cleared });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/replays/:jobId', async (req, res) => {
  try {
    const replay = await store.listReplay(req.params.jobId);
    res.json({ success: true, replay });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/corrections', async (_req, res) => {
  try {
    const corrections = await store.listCorrections();
    res.json({ success: true, corrections });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.post('/corrections', async (req, res) => {
  try {
    const correction = await store.createCorrection(req.body || {});
    res.status(201).json({ success: true, correction });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

router.get('/workers', async (_req, res) => {
  try {
    res.json({ success: true, workers: workerManager.listActiveWorkers() });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;
