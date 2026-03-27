import * as path from "node:path";

import { config as loadEnv } from "dotenv";

function loadEnvFile(filePath: string) {
  loadEnv({ path: filePath, override: false });
}

function hasValidDatabaseUrl(value?: string) {
  if (!value) {
    return false;
  }

  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "postgresql:" || parsed.protocol === "postgres:") &&
      parsed.hostname.length > 0 &&
      parsed.pathname.length > 1
    );
  } catch {
    return false;
  }
}

function buildDatabaseUrlFromParts() {
  const host = process.env.DB_HOST?.trim();
  const user = process.env.DB_USER?.trim();
  const password = process.env.DB_PASSWORD ?? "";

  if (!host || !user) {
    return null;
  }

  const port = process.env.DB_PORT?.trim() || "5432";
  const database = process.env.DB_NAME?.trim() || process.env.POSTGRES_DB?.trim() || user || "postgres";
  const sslmode =
    process.env.DB_SSLMODE?.trim() ||
    (host === "localhost" || host === "127.0.0.1" ? "" : "require");

  let url =
    `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(password)}` +
    `@${host}:${port}/${encodeURIComponent(database)}`;
  if (sslmode) {
    url += `?sslmode=${encodeURIComponent(sslmode)}`;
  }
  return url;
}

const platformRoot = process.cwd();
const repoRoot = path.resolve(platformRoot, "..");

[
  path.join(platformRoot, ".env"),
  path.join(platformRoot, ".env.local"),
  path.join(repoRoot, "backend", ".env"),
  path.join(repoRoot, "integrations", "chatgpt", ".env")
].forEach(loadEnvFile);

if (!hasValidDatabaseUrl(process.env.DATABASE_URL)) {
  const derived = buildDatabaseUrlFromParts();
  if (derived) {
    process.env.DATABASE_URL = derived;
  }
}
