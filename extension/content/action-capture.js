// Action Capture Module
// Intercepts and captures browser actions (clicks, form submits, navigation)

(function() {
  'use strict';
  
  // Capture click events
  document.addEventListener('click', (event) => {
    const actionData = {
      type: 'click',
      timestamp: new Date().toISOString(),
      target: {
        tagName: event.target.tagName,
        id: event.target.id,
        className: event.target.className,
        text: event.target.textContent?.substring(0, 100),
        href: event.target.href || null
      },
      url: window.location.href,
      domain: window.location.hostname
    };
    
    sendActionToBackground(actionData);
  }, true); // Use capture phase
  
  // Capture form submit events
  document.addEventListener('submit', (event) => {
    const formData = extractFormData(event.target);
    
    const actionData = {
      type: 'form_submit',
      timestamp: new Date().toISOString(),
      form: {
        id: event.target.id,
        action: event.target.action,
        method: event.target.method,
        fields: formData
      },
      url: window.location.href,
      domain: window.location.hostname
    };
    
    sendActionToBackground(actionData);
  }, true);
  
  // Capture navigation events
  let lastUrl = window.location.href;
  const observer = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      const actionData = {
        type: 'navigation',
        timestamp: new Date().toISOString(),
        from: lastUrl,
        to: window.location.href,
        domain: window.location.hostname
      };
      
      sendActionToBackground(actionData);
      lastUrl = window.location.href;
    }
  });
  
  observer.observe(document, { subtree: true, childList: true });
  
  function extractFormData(form) {
    const formData = {};
    const inputs = form.querySelectorAll('input, textarea, select');
    
    inputs.forEach(input => {
      if (input.type !== 'password') { // Don't capture passwords
        formData[input.name || input.id] = {
          type: input.type,
          value: input.value?.substring(0, 200) // Limit length
        };
      } else {
        formData[input.name || input.id] = {
          type: 'password',
          hasValue: !!input.value
        };
      }
    });
    
    return formData;
  }
  
  function sendActionToBackground(actionData) {
    chrome.runtime.sendMessage({
      type: 'ACTION_CAPTURED',
      data: actionData
    }).catch(err => {
      console.error('Failed to send action to background:', err);
    });
  }
})();
