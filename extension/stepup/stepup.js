// Step-Up Authentication UI Script
// Handles user approval for high-risk actions

document.addEventListener('DOMContentLoaded', () => {
  // Get action data from URL parameters or storage
  const urlParams = new URLSearchParams(window.location.search);
  const actionData = {
    type: urlParams.get('type') || 'unknown',
    domain: urlParams.get('domain') || 'unknown',
    riskLevel: urlParams.get('risk') || 'high'
  };
  
  // Populate UI
  document.getElementById('actionType').textContent = actionData.type;
  document.getElementById('actionDomain').textContent = actionData.domain;
  document.getElementById('riskLevel').textContent = actionData.riskLevel.toUpperCase();
  
  // Event listeners
  document.getElementById('approve').addEventListener('click', () => {
    handleApproval(actionData);
  });
  
  document.getElementById('deny').addEventListener('click', () => {
    handleDenial(actionData);
  });
});

async function handleApproval(actionData) {
  const reason = document.getElementById('reason').value;
  
  if (!reason.trim()) {
    alert('Please provide a reason for this action');
    return;
  }
  
  try {
    // Request step-up token from backend
    const response = await chrome.runtime.sendMessage({
      type: 'REQUEST_STEPUP',
      data: {
        ...actionData,
        reason: reason
      }
    });
    
    if (response.success) {
      // Close modal and proceed with action
      window.close();
    } else {
      alert('Failed to obtain elevated privileges: ' + response.error);
    }
  } catch (error) {
    console.error('Step-up approval failed:', error);
    alert('An error occurred during step-up authentication');
  }
}

function handleDenial(actionData) {
  // Send denial message
  chrome.runtime.sendMessage({
    type: 'STEPUP_DENIED',
    data: actionData
  });
  
  window.close();
}
