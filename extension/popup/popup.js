const API_URL = 'http://localhost:3000/api';
let autoRefreshInterval = null;
let chatRefreshInterval = null;
let approvalPollInterval = null;
let activeSessionId = null;
let currentTab = 'monitor';
let currentPolicies = null;
let currentApproval = null;

// Pending chat messages sent locally but not yet confirmed in the DB.
// Each entry: { text, sentAt (timestamp) }
let pendingChatMessages = [];
let pendingWarningTimer = null;

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

  // Routines
  $('newRoutineBtn').addEventListener('click', () => openRoutineEditor(null));
  $('routineBackBtn').addEventListener('click', showRoutineListView);
  $('saveRoutineBtn').addEventListener('click', saveRoutine);
  $('deleteRoutineBtn').addEventListener('click', deleteRoutine);
  $('routineSearch').addEventListener('keydown', e => { if (e.key === 'Enter') loadRoutines(); });
  $('routineSearch').addEventListener('input', debounce(loadRoutines, 300));

  // Credentials vault
  $('addCredentialBtn').addEventListener('click', handleAddCredential);
  ['credDomainInput', 'credUsernameInput', 'credPasswordInput'].forEach(id => {
    $(id).addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); $('addCredentialBtn').click(); }
    });
  });
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
  $('routinesPanel').hidden     = (tab !== 'routines');
  $('permissionsPanel').hidden  = (tab !== 'permissions');

  if (tab === 'chat') {
    loadChatHistory();
    startChatRefresh();
  } else {
    stopChatRefresh();
  }

  if (tab === 'routines') {
    loadRoutines();
  }

  if (tab === 'permissions') {
    loadPolicies();
    loadCredentials();
    loadConnections();
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
      // Still show pending messages even when no session exists yet
      if (pendingChatMessages.length > 0) return;
      $('chatMessages').innerHTML = '<div class="state-empty">No active session. Start the agent to begin chatting.</div>';
      activeSessionId = null;
      return;
    }

    const session = res.sessions[0];
    activeSessionId = session.id;

    const prompts = (session.prompts || []).slice().sort((a, b) => ts(a.createdAt) - ts(b.createdAt));
    const actions = (session.actions || []).slice().sort((a, b) => ts(a.timestamp) - ts(b.timestamp));

    // Reconcile: remove pending messages that now appear in DB prompts
    if (pendingChatMessages.length > 0) {
      const dbTexts = new Set(prompts.map(p => p.content));
      pendingChatMessages = pendingChatMessages.filter(pm => !dbTexts.has(pm.text));
      if (pendingChatMessages.length === 0) {
        clearTimeout(pendingWarningTimer);
        pendingWarningTimer = null;
      }
    }

    // Expire very old pending messages (> 60s) to avoid stale UI
    const now = Date.now();
    pendingChatMessages = pendingChatMessages.filter(pm => now - pm.sentAt < 60000);

    if (prompts.length === 0 && pendingChatMessages.length === 0) {
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

    // Append any pending messages that haven't appeared in DB yet
    for (const pm of pendingChatMessages) {
      html += `<div class="chat-bubble user pending-msg"><span class="bubble-label">You</span>${esc(pm.text)}</div>`;
      html += `<div class="chat-thinking" id="thinkingIndicator"><span class="thinking-dots"><span></span><span></span><span></span></span> Agent is working&hellip;</div>`;
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

  // Always refresh to the latest session before sending, so the command
  // reaches whichever Python agent session is currently polling.
  try {
    const { userToken } = await chrome.storage.local.get(['userToken']);
    const sessRes = await apiFetch('/sessions?limit=1', { token: userToken });
    if (sessRes.success && sessRes.sessions && sessRes.sessions.length > 0) {
      activeSessionId = sessRes.sessions[0].id;
    }
  } catch (_) { /* keep existing activeSessionId */ }

  if (!activeSessionId) {
    await loadChatHistory();
    if (!activeSessionId) return;
  }

  // Handle /run command for routines
  const runMatch = text.match(/^\/run\s+(.+)$/i);
  if (runMatch) {
    input.value = '';
    btn.disabled = true;
    await handleRunRoutineFromChat(runMatch[1].trim());
    btn.disabled = false;
    input.focus();
    return;
  }

  input.value = '';
  btn.disabled = true;

  // Track locally so loadChatHistory preserves it until the DB catches up
  pendingChatMessages.push({ text, sentAt: Date.now() });

  const container = $('chatMessages');
  const emptyState = container.querySelector('.state-empty');
  if (emptyState) emptyState.remove();

  container.insertAdjacentHTML('beforeend',
    `<div class="chat-bubble user pending-msg"><span class="bubble-label">You</span>${esc(text)}</div>`
    + `<div class="chat-thinking" id="thinkingIndicator"><span class="thinking-dots"><span></span><span></span><span></span></span> Agent is working&hellip;</div>`
  );
  container.scrollTop = container.scrollHeight;

  // Start a timeout — if no response within 15s, warn the user
  clearTimeout(pendingWarningTimer);
  pendingWarningTimer = setTimeout(() => {
    const indicator = $('thinkingIndicator');
    if (indicator) {
      indicator.innerHTML = '<span class="chat-warning">Agent may not be running or connected. Check that the Python script is active.</span>';
    }
  }, 15000);

  try {
    const cmdRes = await apiFetch('/commands', {
      method: 'POST',
      body: { content: text, sessionId: activeSessionId }
    });
    if (!cmdRes.success) {
      const indicator = $('thinkingIndicator');
      if (indicator) {
        const reason = cmdRes.error || 'Unknown error';
        indicator.innerHTML = `<span class="chat-warning">Command failed: ${esc(reason)}</span>`;
      }
      pendingChatMessages = pendingChatMessages.filter(pm => pm.text !== text);
    }
  } catch (err) {
    console.error('Send command error:', err);
    const indicator = $('thinkingIndicator');
    if (indicator) {
      indicator.innerHTML = '<span class="chat-warning">Failed to send command. Is the backend running?</span>';
    }
    pendingChatMessages = pendingChatMessages.filter(pm => pm.text !== text);
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

// ─── Credentials vault ────────────────────────────────
async function loadCredentials() {
  try {
    const res = await apiFetch('/credentials');
    if (res.success) {
      renderCredentials(res.credentials || []);
    }
  } catch (err) {
    console.error('Failed to load credentials:', err);
  }
}

function renderCredentials(creds) {
  const container = $('credentialsList');
  if (!creds || creds.length === 0) {
    container.innerHTML = '<div class="cred-empty">No saved logins yet.</div>';
    return;
  }
  container.innerHTML = creds.map(c =>
    `<div class="cred-row">
      <span class="cred-domain">${esc(c.domain)}</span>
      <span class="cred-user">${esc(c.username)}</span>
      <span class="cred-password">&bull;&bull;&bull;&bull;&bull;&bull;</span>
      <div class="cred-actions">
        <button class="cred-delete" data-id="${esc(c.id)}" title="Delete">&times;</button>
      </div>
    </div>`
  ).join('');

  container.querySelectorAll('.cred-delete').forEach(btn => {
    btn.addEventListener('click', () => deleteCredential(btn.dataset.id));
  });
}

async function handleAddCredential() {
  const domain = $('credDomainInput').value.trim();
  const username = $('credUsernameInput').value.trim();
  const password = $('credPasswordInput').value;

  if (!domain || !username || !password) {
    showPermStatus('All fields are required', 'error');
    return;
  }

  try {
    const res = await apiFetch('/credentials', {
      method: 'POST',
      body: { domain, username, password }
    });
    console.log('Save credential response:', res);
    if (res.success) {
      $('credDomainInput').value = '';
      $('credUsernameInput').value = '';
      $('credPasswordInput').value = '';
      loadCredentials();
      showPermStatus('Login saved', 'success');
    } else {
      showPermStatus(res.error || 'Failed to save', 'error');
    }
  } catch (err) {
    console.error('Save credential error:', err);
    showPermStatus('Failed to save login: ' + err.message, 'error');
  }
}

async function deleteCredential(id) {
  try {
    const res = await apiFetch(`/credentials/${id}`, { method: 'DELETE' });
    if (res.success) {
      loadCredentials();
      showPermStatus('Login removed', 'success');
    }
  } catch (err) {
    showPermStatus('Failed to delete', 'error');
  }
}

// ─── Connected accounts (Token Vault) ─────────────────
const PROVIDERS = [
  { id: 'github', name: 'GitHub', icon: '🐙' },
  { id: 'google-oauth2', name: 'Google', icon: '🔵' },
  { id: 'slack', name: 'Slack', icon: '💬' },
  { id: 'windowslive', name: 'Microsoft', icon: '🟦' }
];

async function loadConnections() {
  const container = $('connectionsList');
  try {
    const res = await apiFetch('/token-vault/connections');
    const connected = (res.success && res.connections) ? res.connections : [];
    const connectedIds = new Set(connected.map(c => c.provider));

    container.innerHTML = PROVIDERS.map(p => {
      const isConnected = connectedIds.has(p.id);
      return `<div class="connection-card">
        <span class="connection-icon">${p.icon}</span>
        <div class="connection-info">
          <div class="connection-name">${esc(p.name)}</div>
          <div class="connection-status ${isConnected ? 'connected' : ''}">${isConnected ? 'Connected' : 'Not connected'}</div>
        </div>
        <button class="connection-btn ${isConnected ? 'disconnect' : ''}" data-provider="${esc(p.id)}" data-connected="${isConnected}">
          ${isConnected ? 'Disconnect' : 'Connect'}
        </button>
      </div>`;
    }).join('');

    container.querySelectorAll('.connection-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.connected === 'true') {
          disconnectProvider(btn.dataset.provider);
        } else {
          connectProvider(btn.dataset.provider);
        }
      });
    });
  } catch {
    container.innerHTML = PROVIDERS.map(p =>
      `<div class="connection-card">
        <span class="connection-icon">${p.icon}</span>
        <div class="connection-info">
          <div class="connection-name">${esc(p.name)}</div>
          <div class="connection-status">Not connected</div>
        </div>
        <button class="connection-btn" data-provider="${esc(p.id)}">Connect</button>
      </div>`
    ).join('');
  }
}

async function connectProvider(provider) {
  try {
    const res = await apiFetch('/token-vault/connect', {
      method: 'POST',
      body: { provider }
    });
    if (res.success && res.authorizeUrl) {
      const authWindow = window.open(res.authorizeUrl, '_blank');
      // Poll until the auth window closes, then refresh connections
      const pollClosed = setInterval(() => {
        if (!authWindow || authWindow.closed) {
          clearInterval(pollClosed);
          loadConnections();
        }
      }, 1000);
    } else {
      showPermStatus(res.error || 'Token Vault not configured', 'error');
    }
  } catch {
    showPermStatus('Failed to start connection', 'error');
  }
}

async function disconnectProvider(provider) {
  try {
    const res = await apiFetch(`/token-vault/connections/${encodeURIComponent(provider)}`, {
      method: 'DELETE'
    });
    if (res.success) {
      showPermStatus('Disconnected', 'success');
      loadConnections();
    } else {
      showPermStatus(res.error || 'Failed to disconnect', 'error');
    }
  } catch {
    showPermStatus('Failed to disconnect', 'error');
  }
}

// ─── Routines ─────────────────────────────────────────
let editingRoutineId = null;
let routineSteps = [];

async function loadRoutines() {
  const search = $('routineSearch') ? $('routineSearch').value.trim() : '';
  try {
    const params = search ? `?search=${encodeURIComponent(search)}` : '';
    const res = await apiFetch(`/routines${params}`);
    if (res.success) {
      renderRoutinesList(res.routines || []);
    }
  } catch (err) {
    console.error('Failed to load routines:', err);
  }
}

function renderRoutinesList(routines) {
  const container = $('routinesList');
  if (!routines || routines.length === 0) {
    container.innerHTML = '<div class="state-empty" style="padding:24px">No routines yet. Create one from a past session.</div>';
    return;
  }

  container.innerHTML = routines.map(r => {
    const steps = typeof r.steps === 'string' ? JSON.parse(r.steps) : (r.steps || []);
    const scopeClass = r.scope === 'global' ? 'global' : '';
    return `<div class="routine-card" data-routine-id="${esc(r.id)}">
      <div class="routine-card-icon">&#9654;</div>
      <div class="routine-card-info">
        <div class="routine-card-name">${esc(r.name)}</div>
        <div class="routine-card-meta">
          ${steps.length} step${steps.length !== 1 ? 's' : ''}
          <span class="routine-scope-badge ${scopeClass}">${esc(r.scope || 'private')}</span>
          ${r.description ? ' &mdash; ' + esc(truncate(r.description, 40)) : ''}
        </div>
      </div>
      <div class="routine-card-actions">
        <button class="routine-run-btn" data-id="${esc(r.id)}" title="Run this routine">Run</button>
        <button class="routine-edit-btn" data-id="${esc(r.id)}" title="Edit">Edit</button>
      </div>
    </div>`;
  }).join('');

  container.querySelectorAll('.routine-run-btn').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); runRoutine(btn.dataset.id); });
  });
  container.querySelectorAll('.routine-edit-btn').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); openRoutineEditor(btn.dataset.id); });
  });
}

async function runRoutine(routineId) {
  if (!activeSessionId) {
    const { userToken } = await chrome.storage.local.get(['userToken']);
    const res = await apiFetch('/sessions?limit=1', { token: userToken });
    if (res.success && res.sessions && res.sessions.length > 0) {
      activeSessionId = res.sessions[0].id;
    }
  }
  if (!activeSessionId) {
    alert('No active session. Start the agent first.');
    return;
  }

  try {
    const res = await apiFetch(`/routines/${routineId}/execute`, {
      method: 'POST',
      body: { sessionId: activeSessionId }
    });
    if (res.success) {
      switchTab('chat');
      const container = $('chatMessages');
      container.insertAdjacentHTML('beforeend',
        `<div class="chat-routine-progress">
          <div class="routine-progress-title">Running Routine: ${esc(res.routineName || 'routine')}</div>
          <div class="routine-step-item running">Executing ${res.stepCount || '?'} steps&hellip;</div>
        </div>`
      );
      container.scrollTop = container.scrollHeight;
    } else {
      alert(res.error || 'Failed to start routine');
    }
  } catch (err) {
    console.error('Run routine error:', err);
    alert('Failed to run routine');
  }
}

async function handleRunRoutineFromChat(name) {
  const container = $('chatMessages');
  const emptyState = container.querySelector('.state-empty');
  if (emptyState) emptyState.remove();

  container.insertAdjacentHTML('beforeend',
    `<div class="chat-bubble user"><span class="bubble-label">You</span>/run ${esc(name)}</div>`
  );

  try {
    const res = await apiFetch(`/routines?search=${encodeURIComponent(name)}`);
    if (!res.success || !res.routines || res.routines.length === 0) {
      container.insertAdjacentHTML('beforeend',
        `<div class="chat-bubble agent"><span class="bubble-label">System</span>No routine found matching "${esc(name)}"</div>`
      );
      container.scrollTop = container.scrollHeight;
      return;
    }

    const routine = res.routines[0];
    const steps = typeof routine.steps === 'string' ? JSON.parse(routine.steps) : (routine.steps || []);

    const stepsHtml = steps.map((s, i) =>
      `<div class="routine-step-item pending-step" id="rtnStep_${i}">&#9723; Step ${i + 1}: ${esc(s.label || s.actionType || 'action')}</div>`
    ).join('');

    container.insertAdjacentHTML('beforeend',
      `<div class="chat-routine-progress" id="routineProgressBlock">
        <div class="routine-progress-title">Running: ${esc(routine.name)}</div>
        ${stepsHtml}
      </div>`
    );
    container.scrollTop = container.scrollHeight;

    const execRes = await apiFetch(`/routines/${routine.id}/execute`, {
      method: 'POST',
      body: { sessionId: activeSessionId }
    });

    if (!execRes.success) {
      container.insertAdjacentHTML('beforeend',
        `<div class="chat-bubble agent"><span class="bubble-label">System</span>Failed: ${esc(execRes.error || 'unknown error')}</div>`
      );
    }
  } catch (err) {
    container.insertAdjacentHTML('beforeend',
      `<div class="chat-bubble agent"><span class="bubble-label">System</span>Error running routine: ${esc(err.message)}</div>`
    );
  }
  container.scrollTop = container.scrollHeight;
}

function showRoutineListView() {
  $('routinesListView').hidden = false;
  $('routinesEditView').hidden = true;
  editingRoutineId = null;
  routineSteps = [];
}

async function openRoutineEditor(routineId) {
  editingRoutineId = routineId || null;
  $('routinesListView').hidden = true;
  $('routinesEditView').hidden = false;
  $('routineEditTitle').textContent = routineId ? 'Edit Routine' : 'New Routine';
  $('deleteRoutineBtn').hidden = !routineId;

  // Reset form
  $('routineName').value = '';
  $('routineDesc').value = '';
  $('routineScope').value = 'private';
  routineSteps = [];

  if (routineId) {
    try {
      const res = await apiFetch(`/routines/${routineId}`);
      if (res.success && res.routine) {
        $('routineName').value = res.routine.name || '';
        $('routineDesc').value = res.routine.description || '';
        $('routineScope').value = res.routine.scope || 'private';
        routineSteps = typeof res.routine.steps === 'string' ? JSON.parse(res.routine.steps) : (res.routine.steps || []);
      }
    } catch (err) {
      console.error('Failed to load routine:', err);
    }
  }

  renderRoutineSteps();
  await loadSessionPicker();
}

function renderRoutineSteps() {
  $('routineStepCount').textContent = routineSteps.length;
  const container = $('routineSteps');
  if (routineSteps.length === 0) {
    container.innerHTML = '<div style="font-size:11px;color:var(--c-text-3);padding:8px">No steps yet. Import from a session above.</div>';
    return;
  }

  container.innerHTML = routineSteps.map((s, i) =>
    `<div class="routine-step-row" data-idx="${i}">
      <span class="routine-step-order">${i + 1}</span>
      <span class="routine-step-label">${esc(s.label || s.actionType || 'Action')}</span>
      <span class="routine-step-type">${esc(s.actionType || '')}</span>
      <button class="routine-step-remove" data-idx="${i}" title="Remove">&times;</button>
    </div>`
  ).join('');

  container.querySelectorAll('.routine-step-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      routineSteps.splice(parseInt(btn.dataset.idx), 1);
      renderRoutineSteps();
    });
  });
}

async function loadSessionPicker() {
  try {
    const res = await apiFetch('/sessions?limit=10');
    if (!res.success) return;
    const select = $('sessionPicker');
    select.innerHTML = '<option value="">-- Select session --</option>'
      + (res.sessions || []).map((s, i) => {
        const title = (s.prompts && s.prompts[0]) ? truncate(s.prompts[0].content, 50) : `Session ${i + 1}`;
        return `<option value="${esc(s.id)}">${esc(title)} (${(s.actions || []).length} actions)</option>`;
      }).join('');

    select.onchange = () => loadSessionActions(select.value);
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

async function loadSessionActions(sessionId) {
  const container = $('sessionActionsList');
  if (!sessionId) { container.innerHTML = ''; return; }

  try {
    const res = await apiFetch(`/sessions?limit=20`);
    if (!res.success) return;
    const session = (res.sessions || []).find(s => s.id === sessionId);
    if (!session) return;

    const actions = (session.actions || []).filter(a => a.status === 'allowed' || a.status === 'approved_override');
    if (actions.length === 0) {
      container.innerHTML = '<div style="font-size:11px;color:var(--c-text-3);padding:6px">No allowed actions in this session.</div>';
      return;
    }

    container.innerHTML = actions.map(a => {
      const target = parseTarget(a.target);
      const desc = a.type === 'navigation' ? (a.url || a.domain || '')
        : (target?.text || target?.id || a.domain || '');
      return `<label class="session-action-row">
        <input type="checkbox" value="${esc(a.id)}" data-action='${esc(JSON.stringify({
          actionType: a.type,
          url: a.url,
          domain: a.domain,
          target: target,
          formData: parseTarget(a.form_data),
          label: `${fmtType(a.type)} — ${truncate(desc, 40)}`
        }))}'>
        <span class="action-type-tag">${esc(a.type)}</span>
        <span class="action-desc">${esc(truncate(desc, 50))}</span>
      </label>`;
    }).join('');

    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => updateStepsFromPicker());
    });
  } catch (err) {
    console.error('Failed to load session actions:', err);
  }
}

function updateStepsFromPicker() {
  const checkboxes = $('sessionActionsList').querySelectorAll('input[type="checkbox"]:checked');
  const pickedSteps = [];
  checkboxes.forEach((cb, i) => {
    try {
      const data = JSON.parse(cb.dataset.action);
      pickedSteps.push({ order: i + 1, type: 'action', ...data });
    } catch {}
  });
  routineSteps = pickedSteps;
  renderRoutineSteps();
}

async function saveRoutine() {
  const name = $('routineName').value.trim();
  const description = $('routineDesc').value.trim();
  const scope = $('routineScope').value;

  if (!name) {
    alert('Routine name is required');
    return;
  }
  if (routineSteps.length === 0) {
    alert('At least one step is required');
    return;
  }

  try {
    if (editingRoutineId) {
      const res = await apiFetch(`/routines/${editingRoutineId}`, {
        method: 'PUT',
        body: { name, description, scope, steps: routineSteps }
      });
      if (res.success) {
        showRoutineListView();
        loadRoutines();
      } else {
        alert(res.error || 'Failed to update');
      }
    } else {
      const res = await apiFetch('/routines', {
        method: 'POST',
        body: { name, description, scope, steps: routineSteps }
      });
      if (res.success) {
        showRoutineListView();
        loadRoutines();
      } else {
        alert(res.error || 'Failed to create');
      }
    }
  } catch (err) {
    console.error('Save routine error:', err);
    alert('Failed to save routine');
  }
}

async function deleteRoutine() {
  if (!editingRoutineId) return;
  if (!confirm('Delete this routine?')) return;

  try {
    const res = await apiFetch(`/routines/${editingRoutineId}`, { method: 'DELETE' });
    if (res.success) {
      showRoutineListView();
      loadRoutines();
    } else {
      alert(res.error || 'Failed to delete');
    }
  } catch (err) {
    alert('Failed to delete routine');
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

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}
