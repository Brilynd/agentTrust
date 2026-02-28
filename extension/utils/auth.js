// Auth Utilities
// Handles Auth0 token management and validation

class AuthManager {
  constructor() {
    this.token = null;
    this.tokenExpiry = null;
  }
  
  async getToken() {
    // Check if token exists and is valid
    if (this.token && this.tokenExpiry && Date.now() < this.tokenExpiry) {
      return this.token;
    }
    
    // Fetch new token from storage or Auth0
    const stored = await chrome.storage.local.get(['authToken', 'tokenExpiry']);
    
    if (stored.authToken && stored.tokenExpiry && Date.now() < stored.tokenExpiry) {
      this.token = stored.authToken;
      this.tokenExpiry = stored.tokenExpiry;
      return this.token;
    }
    
    // TODO: Implement Auth0 token fetch
    throw new Error('No valid token available');
  }
  
  async validateToken(token) {
    // Send token to backend for validation
    try {
      const response = await fetch('http://localhost:3000/api/auth/validate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ token })
      });
      
      return await response.json();
    } catch (error) {
      console.error('Token validation failed:', error);
      throw error;
    }
  }
  
  async requestStepUpToken(actionData, reason) {
    // Request temporary elevated token
    try {
      const response = await fetch('http://localhost:3000/api/auth/stepup', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${await this.getToken()}`
        },
        body: JSON.stringify({
          action: actionData,
          reason: reason
        })
      });
      
      return await response.json();
    } catch (error) {
      console.error('Step-up token request failed:', error);
      throw error;
    }
  }
}

// Export singleton instance
const authManager = new AuthManager();
