// Popup Script
// Handles login, logout, and action viewing

const API_URL = 'http://localhost:3000/api';

// Initialize popup
document.addEventListener('DOMContentLoaded', async () => {
  await checkAuthStatus();
  setupEventListeners();
});

async function checkAuthStatus() {
  const stored = await chrome.storage.local.get(['userToken', 'userEmail']);
  
  if (stored.userToken && stored.userEmail) {
    // User is logged in
    showMainScreen(stored.userEmail);
    await loadActions();
  } else {
    // Show login screen
    showLoginScreen();
  }
}

function setupEventListeners() {
  // Login form
  document.getElementById('loginForm').addEventListener('submit', handleLogin);
  document.getElementById('registerForm').addEventListener('submit', handleRegister);
  document.getElementById('showRegister').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('loginForm').style.display = 'none';
    document.getElementById('registerForm').style.display = 'block';
  });
  document.getElementById('showLogin').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('registerForm').style.display = 'none';
    document.getElementById('loginForm').style.display = 'block';
  });
  
  // Logout
  document.getElementById('logoutBtn').addEventListener('click', handleLogout);
  
  // Filters
  document.getElementById('applyFilters').addEventListener('click', loadActions);
  document.getElementById('refreshActions').addEventListener('click', loadActions);
  document.getElementById('viewMode').addEventListener('change', loadActions);
}

async function handleLogin(e) {
  e.preventDefault();
  
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const errorDiv = document.getElementById('loginError');
  const loginBtn = document.getElementById('loginBtn');
  
  errorDiv.style.display = 'none';
  loginBtn.disabled = true;
  loginBtn.textContent = 'Logging in...';
  
  try {
    const response = await fetch(`${API_URL}/users/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email, password })
    });
    
    const data = await response.json();
    
    if (data.success) {
      // Store token and user info
      await chrome.storage.local.set({
        userToken: data.token,
        userEmail: data.user.email
      });
      
      showMainScreen(data.user.email);
      await loadActions();
    } else {
      errorDiv.textContent = data.error || 'Login failed';
      errorDiv.style.display = 'block';
    }
  } catch (error) {
    errorDiv.textContent = 'Failed to connect to server. Make sure the backend is running.';
    errorDiv.style.display = 'block';
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = 'Login';
  }
}

async function handleRegister(e) {
  e.preventDefault();
  
  const name = document.getElementById('regName').value;
  const email = document.getElementById('regEmail').value;
  const password = document.getElementById('regPassword').value;
  const errorDiv = document.getElementById('registerError');
  const registerBtn = document.getElementById('registerBtn');
  
  errorDiv.style.display = 'none';
  registerBtn.disabled = true;
  registerBtn.textContent = 'Registering...';
  
  try {
    const response = await fetch(`${API_URL}/users/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email, password, name })
    });
    
    const data = await response.json();
    
    if (data.success) {
      // Store token and user info
      await chrome.storage.local.set({
        userToken: data.token,
        userEmail: data.user.email
      });
      
      showMainScreen(data.user.email);
      await loadActions();
    } else {
      errorDiv.textContent = data.error || 'Registration failed';
      errorDiv.style.display = 'block';
    }
  } catch (error) {
    errorDiv.textContent = 'Failed to connect to server. Make sure the backend is running.';
    errorDiv.style.display = 'block';
  } finally {
    registerBtn.disabled = false;
    registerBtn.textContent = 'Register';
  }
}

async function handleLogout() {
  await chrome.storage.local.remove(['userToken', 'userEmail']);
  showLoginScreen();
}

function showLoginScreen() {
  document.getElementById('loginScreen').style.display = 'block';
  document.getElementById('mainScreen').style.display = 'none';
}

function showMainScreen(email) {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('mainScreen').style.display = 'block';
  document.getElementById('userEmail').textContent = email;
}

async function loadActions() {
  const stored = await chrome.storage.local.get(['userToken', 'selectedAgentId']);
  
  if (!stored.userToken) {
    return;
  }
  
  const container = document.getElementById('actionsContainer');
  const viewMode = document.getElementById('viewMode').value;
  container.innerHTML = '<div class="loading">Loading...</div>';
  
  try {
    if (viewMode === 'sessions') {
      // Load sessions view
      await loadSessions(stored.selectedAgentId || 'all');
    } else {
      // Load flat actions view
      await loadActionsFlat();
    }
  } catch (error) {
    container.innerHTML = `<div class="error">Failed to load: ${error.message}</div>`;
  }
}

async function loadSessions(agentId) {
  const stored = await chrome.storage.local.get(['userToken']);
  const container = document.getElementById('actionsContainer');
  document.getElementById('listTitle').textContent = 'Recent Sessions';
  
  try {
    const params = new URLSearchParams({ limit: '20' });
    if (agentId && agentId !== 'all') {
      params.append('agentId', agentId);
    }
    
    const response = await fetch(`${API_URL}/sessions?${params}`, {
      headers: {
        'Authorization': `Bearer ${stored.userToken}`
      }
    });
    
    const data = await response.json();
    
    if (data.success) {
      displaySessions(data.sessions);
      // Calculate stats from all sessions
      const allActions = data.sessions.flatMap(s => s.actions || []);
      updateStats(allActions);
    } else {
      container.innerHTML = `<div class="error">Error: ${data.error}</div>`;
    }
  } catch (error) {
    container.innerHTML = `<div class="error">Failed to load sessions: ${error.message}</div>`;
  }
}

async function loadActionsFlat() {
  const stored = await chrome.storage.local.get(['userToken']);
  const container = document.getElementById('actionsContainer');
  document.getElementById('listTitle').textContent = 'Recent Actions';
  
  try {
    // Get filter values
    const riskLevel = document.getElementById('riskFilter').value;
    const type = document.getElementById('typeFilter').value;
    const domain = document.getElementById('domainFilter').value;
    
    // Build query string
    const params = new URLSearchParams({ limit: '50' });
    if (riskLevel) params.append('riskLevel', riskLevel);
    if (type) params.append('type', type);
    if (domain) params.append('domain', domain);
    
    const response = await fetch(`${API_URL}/actions/user?${params}`, {
      headers: {
        'Authorization': `Bearer ${stored.userToken}`
      }
    });
    
    const data = await response.json();
    
    if (data.success) {
      displayActions(data.actions);
      updateStats(data.actions);
    } else {
      container.innerHTML = `<div class="error">Error: ${data.error}</div>`;
    }
  } catch (error) {
    container.innerHTML = `<div class="error">Failed to load actions: ${error.message}</div>`;
  }
}

function displaySessions(sessions) {
  const container = document.getElementById('actionsContainer');
  
  if (sessions.length === 0) {
    container.innerHTML = '<div class="empty">No sessions found</div>';
    return;
  }
  
  container.innerHTML = sessions.map(session => {
    const startTime = formatTime(session.startedAt);
    const actionCount = session.actions?.length || 0;
    
    return `
    <div class="session-item">
      <div class="session-header">
        <div class="session-info">
          <strong>Session</strong>
          <span class="session-time">${startTime}</span>
          <span class="session-count">${actionCount} actions</span>
        </div>
      </div>
      <div class="session-actions">
        ${session.actions && session.actions.length > 0 ? 
          session.actions.map(action => renderAction(action)).join('') :
          '<div class="empty">No actions in this session</div>'
        }
      </div>
    </div>
    `;
  }).join('');
}

function renderAction(action) {
  const status = action.status || 'allowed';
  const isBlocked = status === 'denied' || status === 'step_up_required';
  const statusClass = isBlocked ? 'blocked' : status;
  const screenshotHtml = action.screenshot ? 
    `<div class="action-screenshot">
      <img src="data:image/png;base64,${action.screenshot}" alt="Screenshot" class="screenshot-img">
    </div>` : '';
  
  return `
    <div class="action-item ${action.riskLevel || 'unknown'} ${statusClass}">
      <div class="action-header">
        <span class="action-type">${action.type}</span>
        <span class="action-time">${formatTime(action.timestamp)}</span>
        ${action.riskLevel ? `<span class="risk-badge ${action.riskLevel}">${action.riskLevel}</span>` : ''}
        ${isBlocked ? `<span class="status-badge ${status}">${status === 'denied' ? 'BLOCKED' : 'STEP-UP REQUIRED'}</span>` : ''}
      </div>
      ${screenshotHtml}
      <div class="action-details">
        <div class="detail-item">
          <strong>Domain:</strong> ${action.domain || 'N/A'}
        </div>
        <div class="detail-item">
          <strong>URL:</strong> <a href="${action.url}" target="_blank">${truncateUrl(action.url)}</a>
        </div>
        ${action.target ? `<div class="detail-item"><strong>Target:</strong> ${JSON.stringify(action.target)}</div>` : ''}
        ${action.formData ? `<div class="detail-item"><strong>Form Data:</strong> ${JSON.stringify(action.formData)}</div>` : ''}
        ${action.reason ? `<div class="detail-item"><strong>Reason:</strong> ${action.reason}</div>` : ''}
        ${action.status ? `<div class="detail-item"><strong>Status:</strong> <span class="status-text ${status}">${status}</span></div>` : ''}
      </div>
    </div>
  `;
}

function displayActions(actions) {
  const container = document.getElementById('actionsContainer');
  
  if (actions.length === 0) {
    container.innerHTML = '<div class="empty">No actions found</div>';
    return;
  }
  
  container.innerHTML = actions.map(action => renderAction(action)).join('');
}

function updateStats(actions) {
  const total = actions.length;
  const highRisk = actions.filter(a => a.riskLevel === 'high').length;
  const blocked = actions.filter(a => a.status === 'denied' || a.status === 'step_up_required').length;
  
  document.getElementById('totalActions').textContent = total;
  document.getElementById('highRiskCount').textContent = highRisk;
  document.getElementById('blockedCount').textContent = blocked;
}

function formatTime(timestamp) {
  if (!timestamp) return 'N/A';
  const date = new Date(timestamp);
  return date.toLocaleString();
}

function truncateUrl(url) {
  if (!url) return 'N/A';
  if (url.length > 50) {
    return url.substring(0, 47) + '...';
  }
  return url;
}
