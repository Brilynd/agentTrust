const { spawn } = require("node:child_process");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");
const isWindows = process.platform === "win32";
const npmCommand = isWindows ? "npm run dev" : "npm";

function prefixStream(stream, prefix) {
  let buffer = "";
  stream.on("data", (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.length > 0) {
        process.stdout.write(`[${prefix}] ${line}\n`);
      }
    }
  });
  stream.on("end", () => {
    if (buffer.length > 0) {
      process.stdout.write(`[${prefix}] ${buffer}\n`);
    }
  });
}

function startProcess(name, cwd, env = {}) {
  const child = spawn(npmCommand, isWindows ? [] : ["run", "dev"], {
    cwd,
    env: {
      ...process.env,
      ...env
    },
    stdio: ["inherit", "pipe", "pipe"],
    shell: isWindows
  });

  prefixStream(child.stdout, name);
  prefixStream(child.stderr, name);
  return child;
}

const children = [
  startProcess("backend", path.join(repoRoot, "backend"), {
    PORT: process.env.PORT || "3000",
    AGENTTRUST_HEADLESS: process.env.AGENTTRUST_HEADLESS || "false"
  }),
  startProcess("dashboard", path.join(repoRoot, "platform", "apps", "dashboard"), {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:3000",
    NEXT_PUBLIC_SOCKET_URL: process.env.NEXT_PUBLIC_SOCKET_URL || "http://127.0.0.1:3000"
  })
];

let shuttingDown = false;

function shutdown(code = 0) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) {
      child.kill("SIGINT");
    }
  }
  setTimeout(() => process.exit(code), 300);
}

for (const child of children) {
  child.on("exit", (code, signal) => {
    if (shuttingDown) {
      return;
    }
    const exitCode = typeof code === "number" ? code : signal ? 1 : 0;
    console.error(`Process exited unexpectedly (${signal || exitCode}). Stopping dev stack.`);
    shutdown(exitCode);
  });
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
