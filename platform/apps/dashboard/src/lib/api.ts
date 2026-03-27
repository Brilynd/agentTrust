const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:3000";

type RequestOptions = {
  token?: string;
};

async function requestJson<T>(path: string, init?: RequestInit, options?: RequestOptions): Promise<T> {
  const headers = new Headers(init?.headers || {});
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }
  if (options?.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload?.error) {
        message = payload.error;
      }
    } catch {
      // Ignore JSON parsing errors and use the HTTP status fallback above.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string, options?: RequestOptions): Promise<T> {
  return requestJson<T>(path, undefined, options);
}

export async function postJson<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
  return requestJson<T>(
    path,
    {
      method: "POST",
      body: JSON.stringify(body || {})
    },
    options
  );
}

export async function putJson<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
  return requestJson<T>(
    path,
    {
      method: "PUT",
      body: JSON.stringify(body || {})
    },
    options
  );
}

export async function deleteJson<T>(path: string, options?: RequestOptions): Promise<T> {
  return requestJson<T>(
    path,
    {
      method: "DELETE"
    },
    options
  );
}
