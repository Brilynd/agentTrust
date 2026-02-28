// Background Service Worker for AgentTrust Extension
// Handles coordination between content scripts, popup, and backend API

chrome.runtime.onInstalled.addListener(() => {
  console.log('AgentTrust extension installed');
});

// Listen for messages from content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'ACTION_CAPTURED') {
    handleActionCapture(request.data, sender.tab);
  } else if (request.type === 'STEP_UP_REQUIRED') {
    handleStepUpRequest(request.data, sender.tab);
  }
  
  return true; // Keep channel open for async response
});

async function handleActionCapture(actionData, tab) {
  // Send action to backend for validation and logging
  // TODO: Implement backend communication
  console.log('Action captured:', actionData);
}

async function handleStepUpRequest(actionData, tab) {
  // Open step-up authentication UI
  // TODO: Implement step-up flow
  console.log('Step-up required for:', actionData);
}
