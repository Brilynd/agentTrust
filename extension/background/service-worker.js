const API_URL = 'http://localhost:3000/api';

chrome.runtime.onInstalled.addListener(() => {
  console.log('AgentTrust extension installed');
  chrome.storage.local.set({
    apiUrl: API_URL,
    enabled: true,
    sessionStats: { actions: 0, highRisk: 0, blocked: 0 }
  });
  updateBadge(0);
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'ACTION_CAPTURED') {
    handleActionCapture(request.data, sender.tab)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  } else if (request.type === 'STEP_UP_REQUIRED') {
    handleStepUpRequest(request.data, sender.tab)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  } else if (request.type === 'GET_TOKEN') {
    getAuthToken()
      .then(token => sendResponse({ success: true, token }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  } else if (request.type === 'STORE_CREDENTIALS') {
    chrome.storage.local.set({
      userToken: request.userToken,
      userEmail: request.userEmail,
      authToken: request.userToken,
      tokenExpiry: request.tokenExpiry || Date.now() + (7 * 24 * 60 * 60 * 1000)
    }).then(() => sendResponse({ success: true }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  } else if (request.type === 'GET_STATS') {
    chrome.storage.local.get(['sessionStats']).then(stored => {
      sendResponse({ success: true, stats: stored.sessionStats || { actions: 0, highRisk: 0, blocked: 0 } });
    });
    return true;
  }
  
  return false;
});

async function getAuthToken() {
  const stored = await chrome.storage.local.get(['authToken', 'tokenExpiry']);
  
  if (stored.authToken && stored.tokenExpiry && Date.now() < stored.tokenExpiry) {
    return stored.authToken;
  }
  
  throw new Error('No valid token. Please authenticate in the extension popup.');
}

async function captureScreenshot(tabId) {
  try {
    if (!tabId) return null;
    
    const tab = await chrome.tabs.get(tabId);
    if (!tab || !tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      return null;
    }
    
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: 'png',
      quality: 80
    });
    
    return dataUrl.split(',')[1];
  } catch (error) {
    console.warn('Failed to capture screenshot:', error);
    return null;
  }
}

async function handleActionCapture(actionData, tab) {
  try {
    const config = await chrome.storage.local.get(['apiUrl', 'enabled', 'authToken']);

    if (!config.enabled) {
      return { skipped: true };
    }

    // Actions dispatched by the Python agent (fromAgent flag):
    // Successful actions are already logged via the agent's M2M-authenticated
    // POST.  Error/failed actions never made it to the DB, so we log those
    // through a user-auth endpoint so they appear in the extension.
    if (actionData.fromAgent) {
      await updateSessionStats(actionData, { action: actionData });

      const isError = actionData.status === 'error' || actionData.status === 'unauthorized';
      if (isError && config.authToken) {
        try {
          await fetch(`${config.apiUrl}/actions/extension-log`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${config.authToken}`
            },
            body: JSON.stringify({
              type: actionData.type,
              url: actionData.url,
              domain: actionData.domain,
              status: actionData.status || 'error',
              target: actionData.target,
              formData: actionData.formData,
              riskLevel: actionData.riskLevel,
              reason: actionData.reason || actionData.message,
              timestamp: actionData.timestamp
            })
          });
        } catch { /* non-critical */ }
      }
      return { skipped: false, fromAgent: true };
    }

    if (!config.apiUrl) {
      throw new Error('API URL not configured');
    }

    let screenshot = null;
    if (tab && tab.id) {
      screenshot = await captureScreenshot(tab.id);
    }

    let token;
    try {
      token = await getAuthToken();
    } catch (error) {
      console.warn('No auth token available, action logged without authentication');
    }

    const headers = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${config.apiUrl}/actions`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        type: actionData.type,
        url: actionData.url,
        domain: actionData.domain,
        target: actionData.target,
        form: actionData.form,
        timestamp: actionData.timestamp,
        screenshot: screenshot
      })
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP ${response.status}`);
    }

    const result = await response.json();

    await updateSessionStats(actionData, result);

    if (result.action?.stepUpRequired || result.requiresStepUp) {
      await handleStepUpRequest(actionData, tab);
    }

    return result;
  } catch (error) {
    console.error('Failed to log action:', error);
    throw error;
  }
}

async function handleStepUpRequest(actionData, tab) {
  try {
    const stepUpUrl = chrome.runtime.getURL('stepup/stepup.html');
    
    await chrome.storage.local.set({
      pendingStepUp: {
        action: actionData,
        tabId: tab?.id,
        timestamp: Date.now()
      }
    });
    
    chrome.windows.create({
      url: stepUpUrl,
      type: 'popup',
      width: 500,
      height: 600
    });
    
    return { stepUpWindowOpened: true };
  } catch (error) {
    console.error('Failed to open step-up UI:', error);
    throw error;
  }
}

async function updateSessionStats(actionData, result) {
  const stored = await chrome.storage.local.get(['sessionStats']);
  const stats = stored.sessionStats || { actions: 0, highRisk: 0, blocked: 0 };
  
  stats.actions = (stats.actions || 0) + 1;
  
  if (result.action?.riskLevel === 'high' || result.riskLevel === 'high') {
    stats.highRisk = (stats.highRisk || 0) + 1;
  }
  
  if (result.status === 'denied' || result.status === 'blocked') {
    stats.blocked = (stats.blocked || 0) + 1;
  }
  
  await chrome.storage.local.set({ sessionStats: stats });
  updateBadge(stats.actions);
}

function updateBadge(count) {
  const text = count > 0 ? String(count) : '';
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color: count > 0 ? '#667eea' : '#999' });
}

// Periodically poll for new agent actions and update badge
const POLL_INTERVAL_MS = 10000;

async function pollForAgentActions() {
  try {
    const stored = await chrome.storage.local.get(['authToken', 'tokenExpiry', 'lastKnownActionCount']);
    if (!stored.authToken || (stored.tokenExpiry && Date.now() >= stored.tokenExpiry)) {
      return;
    }
    
    const response = await fetch(`${API_URL}/actions/user?limit=1`, {
      headers: { 'Authorization': `Bearer ${stored.authToken}` }
    });
    
    if (!response.ok) return;
    
    const data = await response.json();
    if (!data.success) return;
    
    const currentCount = data.count || 0;
    const lastCount = stored.lastKnownActionCount || 0;
    
    if (currentCount > lastCount) {
      await chrome.storage.local.set({ lastKnownActionCount: currentCount });
      updateBadge(currentCount);
    }
  } catch (error) {
    // Polling failures are non-critical
  }
}

setInterval(pollForAgentActions, POLL_INTERVAL_MS);
