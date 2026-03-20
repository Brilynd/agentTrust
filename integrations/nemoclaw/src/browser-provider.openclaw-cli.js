const { execFile } = require('child_process');

function runCommand(args, { timeout = 30000 } = {}) {
  return new Promise((resolve, reject) => {
    execFile('openclaw', args, { timeout, maxBuffer: 10 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        reject(
          new Error(
            `openclaw ${args.join(' ')} failed: ${stderr || stdout || error.message}`
          )
        );
        return;
      }
      resolve((stdout || '').trim());
    });
  });
}

function parseJson(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function coerceElements(snapshot) {
  if (Array.isArray(snapshot?.elements)) {
    return snapshot.elements;
  }
  if (Array.isArray(snapshot?.nodes)) {
    return snapshot.nodes;
  }
  if (Array.isArray(snapshot?.refs)) {
    return snapshot.refs;
  }
  return [];
}

function elementText(element) {
  return (
    element?.text ||
    element?.label ||
    element?.name ||
    element?.title ||
    element?.ariaLabel ||
    element?.aria_label ||
    ''
  );
}

function normalizeElement(element) {
  return {
    ref: element?.ref || element?.id || element?.selector || null,
    text: elementText(element),
    role: element?.role || null,
    selector: element?.selector || null,
    href: element?.href || null,
    id: element?.id || null,
    ariaLabel: element?.ariaLabel || element?.aria_label || null,
    name: element?.name || null,
  };
}

function normalizeSnapshot(snapshot, screenshot) {
  const current =
    snapshot?.page ||
    snapshot?.currentPage ||
    snapshot?.snapshot ||
    snapshot ||
    {};

  return {
    url: current.url || current.location || '',
    title: current.title || '',
    text: current.text || current.content || current.markdown || '',
    untrustedContent: current.untrustedContent || current.text || current.content || '',
    screenshot: screenshot || current.screenshot || null,
    elements: coerceElements(current).map(normalizeElement),
    domain: current.domain || '',
    activeTab: current.activeTab || current.tab || null,
    tabs: Array.isArray(current.tabs) ? current.tabs : [],
  };
}

async function browserJson(args) {
  const raw = await runCommand(['browser', ...args, '--json']);
  return parseJson(raw) || { raw };
}

function candidateRefs(target) {
  return [
    target?.ref,
    target?.selector,
    target?.id,
    target?.text,
    target?.aria_label,
    target?.ariaLabel,
    target?.name,
  ].filter(Boolean);
}

async function resolveRef(target) {
  const candidates = candidateRefs(target);
  const directRef = candidates.find((value) => typeof value === 'string' && value.startsWith('@'));
  if (directRef) {
    return directRef;
  }

  const snapshot = await getCurrentPage();
  for (const candidate of candidates) {
    const match = snapshot.elements.find((element) => {
      return (
        element.ref === candidate ||
        element.selector === candidate ||
        element.id === candidate ||
        element.text === candidate ||
        element.ariaLabel === candidate ||
        element.name === candidate ||
        element.href === candidate
      );
    });
    if (match?.ref) {
      return match.ref;
    }
  }

  throw new Error(`Unable to resolve OpenClaw browser ref for target: ${JSON.stringify(target || {})}`);
}

async function getCurrentPage() {
  const [snapshot, screenshotResult, tabsResult] = await Promise.all([
    browserJson(['snapshot']),
    browserJson(['screenshot']),
    browserJson(['tabs']),
  ]);

  const screenshot =
    screenshotResult?.screenshot ||
    screenshotResult?.image ||
    screenshotResult?.data ||
    null;

  const normalized = normalizeSnapshot(snapshot, screenshot);
  if (Array.isArray(tabsResult?.tabs)) {
    normalized.tabs = tabsResult.tabs;
  } else if (Array.isArray(tabsResult)) {
    normalized.tabs = tabsResult;
  }
  return normalized;
}

async function navigate({ url }) {
  return browserJson(['navigate', url]);
}

async function click({ target }) {
  const ref = await resolveRef(target);
  return browserJson(['click', ref]);
}

async function type({ target, text, pressEnter = false }) {
  const ref = await resolveRef(target);
  const result = await browserJson(['type', ref, text]);
  if (pressEnter) {
    await browserJson(['press', 'Enter']);
  }
  return result;
}

async function submit({ target }) {
  if (target) {
    return click({ target });
  }
  return browserJson(['press', 'Enter']);
}

async function openTab({ url }) {
  return browserJson(['open', url]);
}

async function switchTab({ label, index }) {
  const tabsResult = await browserJson(['tabs']);
  const tabs = Array.isArray(tabsResult?.tabs) ? tabsResult.tabs : Array.isArray(tabsResult) ? tabsResult : [];
  let tab = null;

  if (typeof index === 'number') {
    tab = tabs[index] || null;
  } else if (label) {
    tab =
      tabs.find((entry) => entry?.label === label || entry?.title === label) ||
      null;
  }

  const focusTarget = tab?.id || tab?.ref || label || String(index ?? '');
  if (!focusTarget) {
    throw new Error('Unable to resolve tab to focus');
  }

  return browserJson(['focus', String(focusTarget)]);
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
