// Main Content Script
// Initializes action capture and coordinates with background service worker

(function() {
  'use strict';
  
  console.log('AgentTrust content script loaded');
  
  // Listen for login success from login page - store credentials in extension
  window.addEventListener('agenttrust-login-success', (event) => {
    const { token, email } = event.detail || {};
    if (token && email && typeof chrome !== 'undefined' && chrome.runtime) {
      chrome.runtime.sendMessage({
        type: 'STORE_CREDENTIALS',
        userToken: token,
        userEmail: email,
        tokenExpiry: Date.now() + (7 * 24 * 60 * 60 * 1000)
      }).catch(err => console.warn('Failed to store credentials:', err));
    }
  });
  
  // Listen for agent action events dispatched by the Python agent via Selenium.
  // These events notify the extension in real-time when the agent performs,
  // gets denied, or needs step-up for a browser action.
  window.addEventListener('agenttrust-action-logged', (event) => {
    const detail = event.detail;
    if (detail && typeof chrome !== 'undefined' && chrome.runtime) {
      chrome.runtime.sendMessage({
        type: 'ACTION_CAPTURED',
        data: {
          type: detail.type,
          url: detail.url,
          domain: detail.domain,
          status: detail.status,
          riskLevel: detail.riskLevel,
          actionId: detail.actionId,
          target: detail.target,
          formData: detail.formData,
          timestamp: detail.timestamp || new Date().toISOString(),
          fromAgent: true
        }
      }).catch(err => console.warn('Failed to relay agent action:', err));
    }
  });
  
  if (typeof window.agentTrustInitialized === 'undefined') {
    window.agentTrustInitialized = true;
  }
})();
