const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { randomUUID } = require('crypto');

const { emitPlatformEvent } = require('./platformSocket');
const store = require('./agentPlatformStore');

const activeWorkers = new Map();

function getPlatformRoot() {
  return path.resolve(__dirname, '..', '..', '..', 'platform');
}

function getRepoRoot() {
  return path.resolve(__dirname, '..', '..', '..');
}

function getWorkerLaunchSpec(jobId, workerId) {
  const repoRoot = getRepoRoot();
  const platformRoot = getPlatformRoot();
  const workerMode = process.env.PLATFORM_WORKER_MODE || 'python';
  if (workerMode === 'ts') {
    const workerEntry = path.join(platformRoot, 'apps', 'worker', 'src', 'local-worker.ts');
    return {
      platformRoot,
      workerEntry,
      command: process.execPath,
      args: ['--import', 'tsx', workerEntry, '--jobId', jobId, '--workerId', workerId]
    };
  }
  const workerEntry = path.join(repoRoot, 'integrations', 'chatgpt', 'platform_worker.py');
  const isWindows = process.platform === 'win32';
  return {
    platformRoot: repoRoot,
    workerEntry,
    command: process.env.PYTHON_EXECUTABLE || (isWindows ? 'py' : 'python3'),
    args: isWindows
      ? ['-3', workerEntry, '--jobId', jobId, '--workerId', workerId]
      : [workerEntry, '--jobId', jobId, '--workerId', workerId]
  };
}

async function spawnWorkerForJob(jobId) {
  if (!jobId) {
    throw new Error('jobId is required to spawn worker');
  }
  if (activeWorkers.has(jobId)) {
    return activeWorkers.get(jobId);
  }

  const workerId = randomUUID();
  const { platformRoot, command, args } = getWorkerLaunchSpec(jobId, workerId);
  const backendUrl = process.env.PLATFORM_BACKEND_URL || `http://127.0.0.1:${process.env.PORT || 3000}`;

  await store.registerWorkerProcess(workerId, {
    jobId,
    host: os.hostname(),
    status: 'starting',
    metadata: { backendUrl }
  });

  let child;
  try {
    child = spawn(command, args, {
      cwd: platformRoot,
      env: {
        ...process.env,
        PLATFORM_BACKEND_URL: backendUrl
      },
      stdio: ['ignore', 'pipe', 'pipe']
    });
  } catch (error) {
    await store.completeWorkerProcess(workerId, {
      status: 'failed',
      metadata: { backendUrl, startupError: String(error.message || error) }
    });
    throw error;
  }

  activeWorkers.set(jobId, { workerId, child });

  await store.registerWorkerProcess(workerId, {
    jobId,
    host: os.hostname(),
    pid: child.pid,
    status: 'running',
    metadata: { backendUrl }
  });
  emitPlatformEvent('worker.updated', { workerId, jobId, pid: child.pid, status: 'running' });

  child.stdout.on('data', (chunk) => {
    process.stdout.write(`[platform-worker:${jobId}] ${chunk}`);
  });
  child.stderr.on('data', (chunk) => {
    process.stderr.write(`[platform-worker:${jobId}] ${chunk}`);
  });
  child.on('error', async (error) => {
    activeWorkers.delete(jobId);
    await store.completeWorkerProcess(workerId, {
      status: 'failed',
      metadata: { backendUrl, startupError: String(error.message || error) }
    });
    emitPlatformEvent('worker.updated', { workerId, jobId, pid: child.pid, status: 'failed', error: String(error.message || error) });
  });
  child.on('exit', async (code) => {
    activeWorkers.delete(jobId);
    await store.completeWorkerProcess(workerId, { status: code === 0 ? 'completed' : 'failed', exitCode: code });
    emitPlatformEvent('worker.updated', { workerId, jobId, pid: child.pid, status: code === 0 ? 'completed' : 'failed', exitCode: code });
  });

  return { workerId, pid: child.pid };
}

async function stopWorkerForJob(jobId) {
  const active = activeWorkers.get(jobId);
  if (!active) {
    return false;
  }
  active.child.kill();
  activeWorkers.delete(jobId);
  await store.completeWorkerProcess(active.workerId, { status: 'stopped', exitCode: 0 });
  emitPlatformEvent('worker.updated', { workerId: active.workerId, jobId, status: 'stopped' });
  return true;
}

function listActiveWorkers() {
  return Array.from(activeWorkers.entries()).map(([jobId, value]) => ({
    jobId,
    workerId: value.workerId,
    pid: value.child.pid
  }));
}

async function recoverWorkers() {
  const jobs = await store.listRecoverableJobs();
  for (const job of jobs) {
    if (!activeWorkers.has(job.id)) {
      await spawnWorkerForJob(job.id);
    }
  }
}

module.exports = {
  spawnWorkerForJob,
  stopWorkerForJob,
  listActiveWorkers,
  recoverWorkers
};
