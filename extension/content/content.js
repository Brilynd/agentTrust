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
        tokenExpiry: Date.now() + (7 * 24 * 60 * 60 * 1000) // 7 days
      }).catch(err => console.warn('Failed to store credentials:', err));
    }
  });
  
  // Initialize action capture
  if (typeof window.agentTrustInitialized === 'undefined') {
    window.agentTrustInitialized = true;
    
    // Import action capture module
    // Note: In manifest v3, modules need to be bundled or loaded differently
    // This is a placeholder structure
  }
})();
