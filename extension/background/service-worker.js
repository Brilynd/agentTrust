// Background Service Worker for AgentTrust Extension
// Handles coordination between content scripts, popup, and backend API

const API_URL = 'http://localhost:3000/api';

chrome.runtime.onInstalled.addListener(() => {
  console.log('AgentTrust extension installed');
  
  // Set default configuration
  chrome.storage.local.set({
    apiUrl: API_URL,
    enabled: true
  });
});

// Listen for messages from content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'ACTION_CAPTURED') {
    handleActionCapture(request.data, sender.tab)
      .then(result => sendResponse({ success: true, result }))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true; // Keep channel open for async response
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
  }
  
  return false;
});

async function getAuthToken() {
  // Get token from storage
  const stored = await chrome.storage.local.get(['authToken', 'tokenExpiry']);
  
  if (stored.authToken && stored.tokenExpiry && Date.now() < stored.tokenExpiry) {
    return stored.authToken;
  }
  
  // Token expired or missing - user needs to authenticate
  throw new Error('No valid token. Please authenticate in the extension popup.');
}

async function captureScreenshot(tabId) {
  try {
    if (!tabId) {
      return null;
    }
    
    // Get the tab to capture
    const tab = await chrome.tabs.get(tabId);
    if (!tab || !tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      return null; // Can't capture chrome:// pages
    }
    
    // Capture visible tab as screenshot
    // Note: captureVisibleTab requires active window, so we use the tab's windowId
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: 'png',
      quality: 80
    });
    
    // Convert to base64 (remove data:image/png;base64, prefix)
    const base64 = dataUrl.split(',')[1];
    return base64;
  } catch (error) {
    console.warn('Failed to capture screenshot:', error);
    return null;
  }
}

async function handleActionCapture(actionData, tab) {
  try {
    // Get configuration
    const config = await chrome.storage.local.get(['apiUrl', 'enabled', 'authToken']);
    
    if (!config.enabled) {
      console.log('AgentTrust extension is disabled');
      return { skipped: true };
    }
    
    if (!config.apiUrl) {
      throw new Error('API URL not configured');
    }
    
    // Capture screenshot if tab is available
    let screenshot = null;
    if (tab && tab.id) {
      screenshot = await captureScreenshot(tab.id);
    }
    
    // Get auth token
    let token;
    try {
      token = await getAuthToken();
    } catch (error) {
      console.warn('No auth token available, action logged without authentication');
      // Continue without auth for monitoring purposes
    }
    
    // Send action to backend
    const headers = {
      'Content-Type': 'application/json'
    };
    
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
        screenshot: screenshot // Include screenshot
      })
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP ${response.status}`);
    }
    
    const result = await response.json();
    
    // Update session stats
    updateSessionStats(actionData, result);
    
    // If step-up required, notify user
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
  // Open step-up authentication UI
  try {
    // Create step-up window
    const stepUpUrl = chrome.runtime.getURL('stepup/stepup.html');
    
    // Store action data for step-up flow
    await chrome.storage.local.set({
      pendingStepUp: {
        action: actionData,
        tabId: tab?.id,
        timestamp: Date.now()
      }
    });
    
    // Open step-up UI
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
}
