class HttpError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.data = data;
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const raw = await response.text();

  let data = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
  }

  if (!response.ok) {
    const message =
      (data && typeof data === 'object' && (data.error || data.message)) ||
      `HTTP ${response.status}`;
    throw new HttpError(message, response.status, data);
  }

  return data;
}

module.exports = {
  HttpError,
  requestJson,
};
