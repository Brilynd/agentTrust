// Popup Script
// Handles UI interactions and displays agent status

document.addEventListener('DOMContentLoaded', async () => {
  await initializePopup();
  
  // Event listeners
  document.getElementById('viewAudit').addEventListener('click', () => {
    chrome.tabs.create({ url: 'http://localhost:3000/audit' });
  });
  
  document.getElementById('settings').addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });
});

async function initializePopup() {
  try {
    // Get agent identity from storage
    const result = await chrome.storage.local.get(['agentId', 'agentScopes', 'sessionStats']);
    
    if (result.agentId) {
      document.getElementById('agentId').textContent = result.agentId;
      document.getElementById('agentScopes').textContent = result.agentScopes?.join(', ') || 'None';
      updateStatus('connected', 'Connected');
    } else {
      updateStatus('disconnected', 'Not Authenticated');
    }
    
    // Update stats
    const stats = result.sessionStats || { actions: 0, highRisk: 0 };
    document.getElementById('actionsCount').textContent = stats.actions || 0;
    document.getElementById('highRiskCount').textContent = stats.highRisk || 0;
    
  } catch (error) {
    console.error('Failed to initialize popup:', error);
    updateStatus('error', 'Error');
  }
}

function updateStatus(status, text) {
  const indicator = document.getElementById('statusIndicator');
  const statusText = document.getElementById('statusText');
  
  indicator.className = `status-indicator ${status}`;
  statusText.textContent = text;
}
