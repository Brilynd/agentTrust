const API_URL = 'http://localhost:3000/api';
let autoRefreshInterval = null;

// ─── Bootstrap ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await checkAuth();
  bindEvents();
});

async function checkAuth() {
  const { userToken, userEmail } = await chrome.storage.local.get(['userToken', 'userEmail']);
  if (userToken && userEmail) {
    showDashboard(userEmail);
    await loadData();
  } else {
    showLogin();
  }
}

function bindEvents() {
  // Auth
  $('loginForm').addEventListener('submit', handleLogin);
  $('registerForm').addEventListener('submit', handleRegister);
  $('showRegister').addEventListener('click', e => { e.preventDefault(); $('loginForm').hidden = true; $('registerForm').hidden = false; });
  $('showLogin').addEventListener('click', e => { e.preventDefault(); $('registerForm').hidden = true; $('loginForm').hidden = false; });
  $('logoutBtn').addEventListener('click', handleLogout);

  // Dashboard
  $('refreshActions').addEventListener('click', loadData);
  $('viewMode').addEventListener('change', loadData);
  $('riskFilter').addEventListener('change', loadData);
  $('typeFilter').addEventListener('change', loadData);
  $('domainFilter').addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });
  $('autoRefresh').addEventListener('change', e => e.target.checked ? startLive() : stopLive());
}

// ─── Auth ────────────────────────────────────────────
async function handleLogin(e) {
  e.preventDefault();
  const email = $('email').value;
  const password = $('password').value;
  const btn = $('loginBtn');
  hideError('loginError');
  btn.disabled = true; btn.textContent = 'Signing in\u2026';

  try {
    const res = await apiFetch('/users/login', { method: 'POST', body: { email, password } });
    if (res.success) {
      await chrome.storage.local.set({ userToken: res.token, userEmail: res.user.email });
      showDashboard(res.user.email);
      await loadData();
    } else {
      showError('loginError', res.error || 'Login failed');
    }
  } catch {
    showError('loginError', 'Cannot reach server. Is the backend running?');
  } finally {
    btn.disabled = false; btn.textContent = 'Sign in';
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const name = $('regName').value;
  const email = $('regEmail').value;
  const password = $('regPassword').value;
  const btn = $('registerBtn');
  hideError('registerError');
  btn.disabled = true; btn.textContent = 'Creating\u2026';

  try {
    const res = await apiFetch('/users/register', { method: 'POST', body: { email, password, name } });
    if (res.success) {
      await chrome.storage.local.set({ userToken: res.token, userEmail: res.user.email });
      showDashboard(res.user.email);
      await loadData();
    } else {
      showError('registerError', res.error || 'Registration failed');
    }
  } catch {
    showError('registerError', 'Cannot reach server.');
  } finally {
    btn.disabled = false; btn.textContent = 'Create account';
  }
}

async function handleLogout() {
  stopLive();
  await chrome.storage.local.remove(['userToken', 'userEmail']);
  showLogin();
}

// ─── Screens ─────────────────────────────────────────
function showLogin()  { $('loginScreen').hidden = false; $('mainScreen').hidden = true; }
function showDashboard(email) { $('loginScreen').hidden = true; $('mainScreen').hidden = false; $('userEmail').textContent = email; }

// ─── Live refresh ────────────────────────────────────
function startLive()  { stopLive(); autoRefreshInterval = setInterval(loadData, 5000); }
function stopLive()   { if (autoRefreshInterval) { clearInterval(autoRefreshInterval); autoRefreshInterval = null; } }

// ─── Data loading ────────────────────────────────────
async function loadData() {
  const { userToken } = await chrome.storage.local.get(['userToken']);
  if (!userToken) return;

  const mode = $('viewMode').value;
  $('listTitle').textContent = mode === 'sessions' ? 'Sessions' : 'All Actions';

  try {
    if (mode === 'sessions') await loadSessions(userToken);
    else await loadActionsFlat(userToken);
  } catch (err) {
    $('actionsContainer').innerHTML = renderError(err.message);
  }
}

async function loadSessions(token) {
  const res = await apiFetch('/sessions?limit=20', { token });
  if (!res.success) throw new Error(res.error);

  const allActions = res.sessions.flatMap(s => s.actions || []);
  updateStats(allActions);
  renderSessions(res.sessions);
}

async function loadActionsFlat(token) {
  const params = new URLSearchParams({ limit: '50' });
  const risk = $('riskFilter').value;
  const type = $('typeFilter').value;
  const domain = $('domainFilter').value.trim();
  if (risk) params.set('riskLevel', risk);
  if (type) params.set('type', type);
  if (domain) params.set('domain', domain);

  const res = await apiFetch(`/actions/user?${params}`, { token });
  if (!res.success) throw new Error(res.error);

  updateStats(res.actions);
  renderActionsFlat(res.actions);
}

// ─── Stats ───────────────────────────────────────────
function updateStats(actions) {
  if (!actions) return;
  $('totalActions').textContent  = actions.length;
  $('highRiskCount').textContent = actions.filter(a => a.riskLevel === 'high').length;
  $('blockedCount').textContent  = actions.filter(a => a.status === 'denied' || a.status === 'step_up_required').length;
  $('agentCount').textContent    = new Set(actions.map(a => a.agentId).filter(Boolean)).size;
}

// ─── Render: Sessions ────────────────────────────────
function renderSessions(sessions) {
  const el = $('actionsContainer');
  const countEl = $('actionCountLabel');

  if (!sessions || sessions.length === 0) {
    el.innerHTML = renderEmpty('No sessions yet', 'Agent activity will appear here once the agent runs.');
    countEl.textContent = '';
    return;
  }

  countEl.textContent = `${sessions.length} session${sessions.length !== 1 ? 's' : ''}`;

  el.innerHTML = sessions.map((session, idx) => {
    const time = fmtTime(session.startedAt);
    const promptCount = (session.prompts || []).length;
    const actionCount = (session.actions || []).length;
    const hasHigh = (session.actions || []).some(a => a.riskLevel === 'high');
    const hasBlocked = (session.actions || []).some(a => a.status === 'denied' || a.status === 'step_up_required');

    // Build the first prompt's text as a session title preview
    const firstPrompt = (session.prompts || [])[0];
    const title = firstPrompt ? truncate(firstPrompt.content, 60) : `Session ${idx + 1}`;

    const turns = buildConversationTurns(session);

    return `
      <div class="session-card${hasHigh ? ' has-high-risk' : ''}${hasBlocked ? ' has-blocked' : ''}${idx === 0 ? ' open' : ''}" data-session>
        <div class="session-head" data-toggle-session>
          <div class="session-head-left">
            <span class="session-indicator"></span>
            <span class="session-head-title">${esc(title)}</span>
          </div>
          <div class="session-head-meta">
            <span class="meta-pill">${promptCount}p &middot; ${actionCount}a</span>
            <span class="meta-time">${time}</span>
            <svg class="session-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
          </div>
        </div>
        <div class="session-body">
          ${turns}
        </div>
      </div>`;
  }).join('');

  // Bind collapse/expand for sessions
  el.querySelectorAll('[data-toggle-session]').forEach(head => {
    head.addEventListener('click', () => head.closest('[data-session]').classList.toggle('open'));
  });

}

/**
 * Build conversation log by grouping actions to prompts via promptId.
 * Each prompt renders: user message → GPT response → each action's screenshot.
 * Actions link to prompts via action.promptId === prompt.id (set by the agent).
 */
function buildConversationTurns(session) {
  const prompts = (session.prompts || []).slice().sort((a, b) => ts(a.createdAt) - ts(b.createdAt));
  const actions = (session.actions || []).slice().sort((a, b) => ts(a.timestamp) - ts(b.timestamp));

  if (prompts.length === 0 && actions.length === 0) {
    return '<div class="state-empty" style="padding:20px">No activity in this session</div>';
  }

  // Group actions by their promptId
  const actionsByPrompt = {};
  const unlinked = [];
  for (const action of actions) {
    if (action.promptId) {
      if (!actionsByPrompt[action.promptId]) actionsByPrompt[action.promptId] = [];
      actionsByPrompt[action.promptId].push(action);
    } else {
      unlinked.push(action);
    }
  }

  // If there are no prompts, render actions flat
  if (prompts.length === 0) {
    return actions.map(renderActionBlock).join('')
      || '<div class="state-empty" style="padding:20px">No prompts recorded</div>';
  }

  let html = '';

  // Render each prompt with its linked actions
  for (const prompt of prompts) {
    const linked = actionsByPrompt[prompt.id] || [];
    html += renderTurn(prompt, linked);
  }

  // Render any unlinked actions (from before promptId was added) at the end
  if (unlinked.length > 0) {
    const visible = unlinked.filter(a => a.screenshot || a.status === 'error' || a.status === 'denied');
    if (visible.length > 0) {
      html += visible.map(renderActionBlock).join('');
    }
  }

  return html;
}

// ─── One turn: user message → GPT response → action screenshots ──
function renderTurn(prompt, actions) {
  const responseHtml = prompt.response
    ? `<div class="turn-response"><div class="turn-label">ChatGPT</div><div class="turn-response-text">${esc(prompt.response)}</div></div>`
    : '';

  const actionsHtml = actions.map(renderActionBlock).join('');

  return `<div class="conv-turn">`
    + `<div class="turn-request"><div class="turn-label">You</div><div class="turn-request-text">${esc(prompt.content)}</div></div>`
    + responseHtml
    + actionsHtml
    + `</div>`;
}

// ─── Render a single action (label + screenshot, or error) ──
function renderActionBlock(action) {
  const isError = action.status === 'error' || action.status === 'unauthorized' || action.status === 'denied';
  const hasScreenshot = !!action.screenshot;

  if (!hasScreenshot && !isError) return '';

  const target = describeTarget(action);
  const actionLabel = `${esc(fmtType(action.type))}${target ? ' &mdash; ' + target : ''}`;

  if (isError) {
    const badge = action.status === 'denied' ? 'BLOCKED' : 'ERROR';
    const img = hasScreenshot
      ? `<div class="turn-screenshot"><img src="data:image/png;base64,${action.screenshot}" alt="Screenshot"></div>`
      : '';
    return `<div class="turn-error"><span class="turn-error-badge">${badge}</span> ${actionLabel}</div>` + img;
  }

  return `<div class="turn-action-label">${actionLabel}</div>`
    + `<div class="turn-screenshot"><img src="data:image/png;base64,${action.screenshot}" alt="Screenshot"></div>`;
}

function describeTarget(action) {
  if (action.type === 'navigation' && action.url) {
    try { const u = new URL(action.url); return `<code>${esc(u.hostname + u.pathname)}</code>`; }
    catch { return `<code>${esc(truncate(action.url, 60))}</code>`; }
  }
  const t = parseTarget(action.target);
  if (!t) return '';
  if (t.text) return esc(truncate(t.text, 60));
  if (t.id)   return `<code>#${esc(t.id)}</code>`;
  if (t.href) return `<code>${esc(truncate(t.href, 60))}</code>`;
  return '';
}

// ─── Render: Flat actions view ───────────────────────
function renderActionsFlat(actions) {
  const el = $('actionsContainer');
  const countEl = $('actionCountLabel');

  if (!actions || actions.length === 0) {
    el.innerHTML = renderEmpty('No actions yet', 'Actions will appear here once the agent starts working.');
    countEl.textContent = '';
    return;
  }

  countEl.textContent = `${actions.length} action${actions.length !== 1 ? 's' : ''}`;

  const visible = actions.filter(a => a.screenshot || a.status === 'error' || a.status === 'denied');
  if (visible.length === 0) {
    el.innerHTML = renderEmpty('No screenshots', 'No screenshots captured yet.');
    return;
  }
  el.innerHTML = visible.map(a => renderActionBlock(a)).join('');
}

// ─── Icons ───────────────────────────────────────────
function typeIcon(type) {
  switch (type) {
    case 'click':       return '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 15l-2 5L9 9l11 4-5 2z"/></svg>';
    case 'form_submit': return '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>';
    case 'navigation':  return '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>';
    default:            return '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="3"/></svg>';
  }
}

function fmtType(type) {
  if (!type) return 'Unknown';
  return type.replace(/_/g, ' ');
}

// ─── Empty / error states ────────────────────────────
function renderEmpty(title, sub) {
  return `
    <div class="state-empty">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
      <strong>${esc(title)}</strong><br>${esc(sub)}
    </div>`;
}

function renderError(msg) {
  return `<div class="state-error">Failed to load: ${esc(msg)}</div>`;
}

// ─── Utilities ───────────────────────────────────────
function $(id) { return document.getElementById(id); }

function showError(id, msg) { const el = $(id); el.textContent = msg; el.hidden = false; }
function hideError(id) { $(id).hidden = true; }

function ts(v) { return new Date(v).getTime(); }

async function apiFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (opts.token) {
    headers['Authorization'] = `Bearer ${opts.token}`;
  } else {
    const { userToken } = await chrome.storage.local.get(['userToken']);
    if (userToken) headers['Authorization'] = `Bearer ${userToken}`;
  }
  const fetchOpts = { method: opts.method || 'GET', headers };
  if (opts.body) fetchOpts.body = JSON.stringify(opts.body);
  const res = await fetch(`${API_URL}${path}`, fetchOpts);
  return res.json();
}

function fmtTime(timestamp) {
  if (!timestamp) return '';
  const d = new Date(timestamp);
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function truncate(s, max) {
  if (!s) return '';
  s = String(s);
  return s.length > max ? s.slice(0, max - 1) + '\u2026' : s;
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function parseTarget(val) {
  if (!val) return null;
  if (typeof val === 'object') return val;
  try { return JSON.parse(val); } catch { return null; }
}
