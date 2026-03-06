const API_URL = 'http://localhost:3000/api';
let autoRefreshInterval = null;
let chatRefreshInterval = null;
let approvalPollInterval = null;
let activeSessionId = null;
let currentTab = 'monitor';
let currentPolicies = null;
let currentApproval = null;

// ─── Bootstrap ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Detect pop-out window (opened via ?popout=1 or window width check)
  if (new URLSearchParams(window.location.search).has('popout')) {
    document.body.classList.add('popout');
  }
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
  $('popoutBtn').addEventListener('click', handlePopout);

  // Dashboard
  $('refreshActions').addEventListener('click', loadData);
  $('viewMode').addEventListener('change', loadData);
  $('riskFilter').addEventListener('change', loadData);
  $('typeFilter').addEventListener('change', loadData);
  $('domainFilter').addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });
  $('autoRefresh').addEventListener('change', e => e.target.checked ? startLive() : stopLive());

  // Tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  // Chat
  $('chatForm').addEventListener('submit', handleSendCommand);

  // Approval banner
  $('approvalApproveBtn').addEventListener('click', () => respondToApproval(true));
  $('approvalDenyBtn').addEventListener('click', () => respondToApproval(false));

  // Permissions panel — chip add buttons
  bindChipAdd('addBlockedDomainBtn', 'blockedDomainInput', 'blocked_domains');
  bindChipAdd('addAllowedDomainBtn', 'allowedDomainInput', 'allowed_domains');
  bindChipAdd('addHighRiskKeywordBtn', 'highRiskKeywordInput', 'high_risk_keywords');
  bindChipAdd('addFinancialDomainBtn', 'financialDomainInput', 'financial_domains');

  // Enter key on chip inputs
  ['blockedDomainInput', 'allowedDomainInput', 'highRiskKeywordInput', 'financialDomainInput'].forEach(id => {
    $(id).addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); $(id).nextElementSibling.click(); }
    });
  });

  // Step-up toggle checkboxes
  $('stepUpHigh').addEventListener('change', handleStepUpToggle);
  $('stepUpMedium').addEventListener('change', handleStepUpToggle);
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
  stopApprovalPolling();
  await chrome.storage.local.remove(['userToken', 'userEmail']);
  showLogin();
}

// ─── Pop-out window ──────────────────────────────────
function handlePopout() {
  chrome.windows.create({
    url: chrome.runtime.getURL('popup/popup.html?popout=1'),
    type: 'popup',
    width: 520,
    height: 780
  });
  window.close();
}

// ─── Screens ─────────────────────────────────────────
function showLogin()  {
  $('loginScreen').hidden = false;
  $('mainScreen').hidden = true;
  stopApprovalPolling();
}
function showDashboard(email) {
  $('loginScreen').hidden = true;
  $('mainScreen').hidden = false;
  $('userEmail').textContent = email;
  startApprovalPolling();
}

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
  const isOverride = action.status === 'approved_override';
  const isStepUp = action.status === 'step_up_required';
  const hasScreenshot = !!action.screenshot;

  if (!hasScreenshot && !isError && !isOverride && !isStepUp) return '';

  const target = describeTarget(action);
  const actionLabel = `${esc(fmtType(action.type))}${target ? ' &mdash; ' + target : ''}`;

  if (isError) {
    const badge = action.status === 'denied' ? 'BLOCKED' : 'ERROR';
    const img = hasScreenshot
      ? `<div class="turn-screenshot"><img src="data:image/png;base64,${action.screenshot}" alt="Screenshot"></div>`
      : '';
    return `<div class="turn-error"><span class="turn-error-badge">${badge}</span> ${actionLabel}</div>` + img;
  }

  if (isStepUp) {
    const reason = action.reason ? ` — ${esc(action.reason)}` : '';
    return `<div class="turn-stepup"><span class="turn-stepup-badge">AWAITING APPROVAL</span> ${actionLabel}${reason}</div>`;
  }

  const overrideBadge = isOverride
    ? `<span class="turn-override-badge">MANUAL OVERRIDE</span> `
    : '';

  return `<div class="turn-action-label">${overrideBadge}${actionLabel}</div>`
    + `<div class="turn-screenshot${isOverride ? ' override-border' : ''}"><img src="data:image/png;base64,${action.screenshot}" alt="Screenshot"></div>`;
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

// ─── Tab switching ───────────────────────────────────
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  $('monitorPanel').hidden      = (tab !== 'monitor');
  $('chatPanel').hidden         = (tab !== 'chat');
  $('permissionsPanel').hidden  = (tab !== 'permissions');

  if (tab === 'chat') {
    loadChatHistory();
    startChatRefresh();
  } else {
    stopChatRefresh();
  }

  if (tab === 'permissions') {
    loadPolicies();
  }
}

function startChatRefresh() {
  stopChatRefresh();
  chatRefreshInterval = setInterval(loadChatHistory, 3000);
}

function stopChatRefresh() {
  if (chatRefreshInterval) { clearInterval(chatRefreshInterval); chatRefreshInterval = null; }
}

// ─── Chat: load history from active session ──────────
async function loadChatHistory() {
  const { userToken } = await chrome.storage.local.get(['userToken']);
  if (!userToken) return;

  try {
    const res = await apiFetch('/sessions?limit=1', { token: userToken });
    if (!res.success || !res.sessions || res.sessions.length === 0) {
      $('chatMessages').innerHTML = '<div class="state-empty">No active session. Start the agent to begin chatting.</div>';
      activeSessionId = null;
      return;
    }

    const session = res.sessions[0];
    activeSessionId = session.id;

    const prompts = (session.prompts || []).slice().sort((a, b) => ts(a.createdAt) - ts(b.createdAt));
    const actions = (session.actions || []).slice().sort((a, b) => ts(a.timestamp) - ts(b.timestamp));

    if (prompts.length === 0) {
      $('chatMessages').innerHTML = '<div class="state-empty">Session active. Send a command below.</div>';
      return;
    }

    // Group actions by promptId
    const actionsByPrompt = {};
    for (const a of actions) {
      if (a.promptId) {
        if (!actionsByPrompt[a.promptId]) actionsByPrompt[a.promptId] = [];
        actionsByPrompt[a.promptId].push(a);
      }
    }

    const container = $('chatMessages');
    const wasScrolledToBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 30;

    let html = '';
    for (const p of prompts) {
      html += `<div class="chat-bubble user"><span class="bubble-label">You</span>${esc(p.content)}</div>`;

      if (p.response) {
        const linked = actionsByPrompt[p.id] || [];
        const screenshots = linked.filter(a => a.screenshot);

        let screenshotHtml = '';
        for (const a of screenshots) {
          screenshotHtml += `<div class="chat-screenshot"><img src="data:image/png;base64,${a.screenshot}" alt="Screenshot"></div>`;
        }

        html += `<div class="chat-bubble agent"><span class="bubble-label">ChatGPT</span>${esc(p.response)}${screenshotHtml}</div>`;
      }
    }

    // Check if the last prompt has no response yet (agent is thinking)
    const lastPrompt = prompts[prompts.length - 1];
    if (lastPrompt && !lastPrompt.response) {
      html += `<div class="chat-thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Agent is working&hellip;</div>`;
    }

    container.innerHTML = html;

    if (wasScrolledToBottom) {
      container.scrollTop = container.scrollHeight;
    }
  } catch (err) {
    console.error('Chat load error:', err);
  }
}

// ─── Chat: send command ──────────────────────────────
async function handleSendCommand(e) {
  e.preventDefault();
  const input = $('chatInput');
  const btn = $('chatSendBtn');
  const text = input.value.trim();
  if (!text) return;

  if (!activeSessionId) {
    // Try to detect session
    await loadChatHistory();
    if (!activeSessionId) return;
  }

  input.value = '';
  btn.disabled = true;

  // Optimistic UI: add user bubble + thinking indicator immediately
  const container = $('chatMessages');
  const emptyState = container.querySelector('.state-empty');
  if (emptyState) emptyState.remove();

  container.insertAdjacentHTML('beforeend',
    `<div class="chat-bubble user"><span class="bubble-label">You</span>${esc(text)}</div>`
    + `<div class="chat-thinking" id="thinkingIndicator"><span class="thinking-dots"><span></span><span></span><span></span></span> Agent is working&hellip;</div>`
  );
  container.scrollTop = container.scrollHeight;

  try {
    await apiFetch('/commands', {
      method: 'POST',
      body: { content: text, sessionId: activeSessionId }
    });
  } catch (err) {
    console.error('Send command error:', err);
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

// ─── Permissions: load & save ─────────────────────────
async function loadPolicies() {
  try {
    const res = await apiFetch('/policies/user');
    if (res.success && res.policies) {
      currentPolicies = res.policies;
      renderPolicies(res.policies);
    }
  } catch (err) {
    console.error('Failed to load policies:', err);
    showPermStatus('Failed to load policies', 'error');
  }
}

async function savePolicies(policies) {
  try {
    const res = await apiFetch('/policies/user', {
      method: 'PUT',
      body: { policies }
    });
    if (res.success) {
      currentPolicies = policies;
      showPermStatus('Saved', 'success');
    } else {
      showPermStatus(res.error || 'Save failed', 'error');
    }
  } catch (err) {
    console.error('Failed to save policies:', err);
    showPermStatus('Failed to save', 'error');
  }
}

function showPermStatus(msg, type) {
  const el = $('permSaveStatus');
  el.textContent = msg;
  el.className = 'perm-status ' + type;
  setTimeout(() => { el.textContent = ''; el.className = 'perm-status'; }, 3000);
}

function renderPolicies(p) {
  renderChipList('blockedDomainsList', p.blocked_domains || [], 'blocked_domains');
  renderChipList('allowedDomainsList', p.allowed_domains || [], 'allowed_domains');
  renderChipList('highRiskKeywordsList', p.high_risk_keywords || [], 'high_risk_keywords');
  renderChipList('financialDomainsList', p.financial_domains || [], 'financial_domains');

  const stepUp = p.requires_step_up || [];
  $('stepUpHigh').checked = stepUp.includes('high');
  $('stepUpMedium').checked = stepUp.includes('medium');
}

function renderChipList(containerId, items, policyKey) {
  const container = $(containerId);
  container.innerHTML = items.map((item, idx) =>
    `<span class="chip" data-key="${esc(policyKey)}" data-idx="${idx}">${esc(item)}<button class="chip-remove" title="Remove">&times;</button></span>`
  ).join('');

  container.querySelectorAll('.chip-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      const chip = btn.closest('.chip');
      const key = chip.dataset.key;
      const idx = parseInt(chip.dataset.idx);
      removeChip(key, idx);
    });
  });
}

function removeChip(policyKey, idx) {
  if (!currentPolicies || !currentPolicies[policyKey]) return;
  currentPolicies[policyKey].splice(idx, 1);
  savePolicies(currentPolicies);
  renderPolicies(currentPolicies);
}

function bindChipAdd(btnId, inputId, policyKey) {
  $(btnId).addEventListener('click', () => {
    const input = $(inputId);
    const val = input.value.trim();
    if (!val) return;

    if (!currentPolicies) currentPolicies = {};
    if (!currentPolicies[policyKey]) currentPolicies[policyKey] = [];

    if (currentPolicies[policyKey].includes(val)) {
      input.value = '';
      return;
    }

    currentPolicies[policyKey].push(val);
    input.value = '';
    savePolicies(currentPolicies);
    renderPolicies(currentPolicies);
  });
}

function handleStepUpToggle() {
  if (!currentPolicies) currentPolicies = {};
  const levels = [];
  if ($('stepUpHigh').checked) levels.push('high');
  if ($('stepUpMedium').checked) levels.push('medium');
  currentPolicies.requires_step_up = levels;
  savePolicies(currentPolicies);
}

// ─── Approval polling ─────────────────────────────────
function startApprovalPolling() {
  stopApprovalPolling();
  pollApprovals();
  approvalPollInterval = setInterval(pollApprovals, 3000);
}

function stopApprovalPolling() {
  if (approvalPollInterval) { clearInterval(approvalPollInterval); approvalPollInterval = null; }
}

async function pollApprovals() {
  try {
    const params = activeSessionId ? `?sessionId=${activeSessionId}` : '';
    const res = await apiFetch(`/approvals/pending${params}`);
    if (res.success && res.approvals && res.approvals.length > 0) {
      const approval = res.approvals[0];
      currentApproval = approval;
      showApprovalBanner(approval);
    } else {
      currentApproval = null;
      hideApprovalBanner();
    }
  } catch (err) {
    // Silently ignore polling errors
  }
}

function showApprovalBanner(approval) {
  const desc = `${fmtType(approval.type)} on ${esc(approval.domain || 'unknown domain')} — Risk: ${approval.riskLevel || 'unknown'}`;
  $('approvalDesc').innerHTML = desc + (approval.reason ? `<br>${esc(approval.reason)}` : '');
  $('approvalBanner').hidden = false;
  $('approvalDot').hidden = false;
}

function hideApprovalBanner() {
  $('approvalBanner').hidden = true;
  $('approvalDot').hidden = true;
}

async function respondToApproval(approved) {
  if (!currentApproval) return;

  const approvalId = currentApproval.id;
  $('approvalApproveBtn').disabled = true;
  $('approvalDenyBtn').disabled = true;

  try {
    await apiFetch(`/approvals/${approvalId}/respond`, {
      method: 'POST',
      body: { approved }
    });
    currentApproval = null;
    hideApprovalBanner();
  } catch (err) {
    console.error('Failed to respond to approval:', err);
  } finally {
    $('approvalApproveBtn').disabled = false;
    $('approvalDenyBtn').disabled = false;
  }
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
