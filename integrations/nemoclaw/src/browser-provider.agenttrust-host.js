const { requestJson } = require('./http');

function getServiceUrl() {
  return String(
    process.env.AGENTTRUST_HOST_BROWSER_SERVICE_URL || 'http://127.0.0.1:4100'
  ).replace(/\/+$/, '');
}

async function request(method, pathname, body) {
  const url = `${getServiceUrl()}${pathname}`;
  return requestJson(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function getCurrentPage() {
  return request('GET', '/current-page', undefined);
}

async function navigate({ url }) {
  return request('POST', '/navigate', { url });
}

async function click({ target }) {
  return request('POST', '/click', { target });
}

async function type({ target, text, clearFirst = true, pressEnter = false }) {
  return request('POST', '/type', { target, text, clearFirst, pressEnter });
}

async function submit({ target, formData }) {
  return request('POST', '/submit', { target, formData });
}

async function openTab({ url, label }) {
  return request('POST', '/open-tab', { url, label });
}

async function switchTab({ label, index }) {
  return request('POST', '/switch-tab', { label, index });
}

module.exports = {
  browserProvider: {
    navigate,
    click,
    type,
    submit,
    openTab,
    switchTab,
    getCurrentPage,
  },
};
