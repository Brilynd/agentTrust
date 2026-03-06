"""
AgentTrust Client for ChatGPT Integration
Provides a Python client for ChatGPT to interact with AgentTrust API

Auth0 for AI Agents Hackathon: Built with Token Vault for OAuth flows,
token management, and consent delegation.
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, Optional, Any
import os

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    _dir = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(os.path.dirname(_dir))
    for p in [os.path.join(_root, 'backend', '.env'), os.path.join(_root, '.env'), os.path.join(_dir, '.env')]:
        if os.path.isfile(p):
            load_dotenv(p)
except ImportError:
    pass


class AgentTrustClient:
    """Client for interacting with AgentTrust API from ChatGPT"""
    
    def __init__(
        self,
        api_url: str = None,
        auth0_domain: str = None,
        auth0_client_id: str = None,
        auth0_client_secret: str = None,
        auth0_audience: str = None
    ):
        """
        Initialize AgentTrust client
        
        Args:
            api_url: AgentTrust API URL (default: from env or http://localhost:3000/api)
            auth0_domain: Auth0 domain
            auth0_client_id: Auth0 client ID
            auth0_client_secret: Auth0 client secret
            auth0_audience: Auth0 API audience
        """
        self.api_url = api_url or os.getenv('AGENTTRUST_API_URL', 'http://localhost:3000/api')
        self.auth0_domain = auth0_domain or os.getenv('AUTH0_DOMAIN')
        self.auth0_client_id = auth0_client_id or os.getenv('AUTH0_CLIENT_ID')
        self.auth0_client_secret = auth0_client_secret or os.getenv('AUTH0_CLIENT_SECRET')
        self.auth0_audience = auth0_audience or os.getenv('AUTH0_AUDIENCE')
        self.dev_mode = os.getenv('AGENTTRUST_DEV_MODE', 'false').lower() == 'true'
        
        self._token = None
        self._token_expiry = None
        self.current_session_id = None
        self.current_prompt_id = None
        
        if not self.dev_mode and not all([self.auth0_domain, self.auth0_client_id, 
                   self.auth0_client_secret, self.auth0_audience]):
            raise ValueError(
                "Auth0 credentials must be provided or set in environment. "
                "Or set AGENTTRUST_DEV_MODE=true to run without backend (browser only)."
            )
    
    def _get_token(self) -> str:
        """Get Auth0 access token (with caching)"""
        # Check if token is still valid
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._token
        
        # Request new token
        response = requests.post(
            f"https://{self.auth0_domain}/oauth/token",
            json={
                "client_id": self.auth0_client_id,
                "client_secret": self.auth0_client_secret,
                "audience": self.auth0_audience,
                "grant_type": "client_credentials"
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to get Auth0 token: {response.text}")
        
        data = response.json()
        self._token = data["access_token"]
        
        # Set expiry (with 5 minute buffer)
        expires_in = data.get("expires_in", 3600)
        from datetime import timedelta
        self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
        
        return self._token
    
    def create_session(self) -> Optional[str]:
        """Create a new session on the backend and store its ID. Returns session ID."""
        if self.dev_mode:
            self.current_session_id = f"dev-session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            return self.current_session_id
        try:
            token = self._get_token()
            response = requests.post(
                f"{self.api_url}/sessions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={},
                timeout=5
            )
            if response.status_code == 201:
                sid = response.json().get("session", {}).get("id")
                self.current_session_id = sid
                return sid
        except Exception as e:
            print(f"Warning: Failed to create session: {e}")
        return None

    def end_session(self) -> None:
        """Close the current session on the backend."""
        if self.dev_mode or not self.current_session_id:
            return
        try:
            token = self._get_token()
            requests.post(
                f"{self.api_url}/sessions/{self.current_session_id}/end",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={},
                timeout=5
            )
        except Exception as e:
            print(f"Warning: Failed to end session: {e}")
        finally:
            self.current_session_id = None

    def execute_action(
        self,
        action_type: str,
        url: str,
        target: Optional[Dict] = None,
        form_data: Optional[Dict] = None,
        domain: Optional[str] = None,
        screenshot: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a browser action through AgentTrust
        
        Args:
            action_type: 'click', 'form_submit', or 'navigation'
            url: Full URL of the page
            target: Target element info (for clicks)
            form_data: Form data (for form submissions)
            domain: Domain (auto-extracted from URL if not provided)
        
        Returns:
            Dict with status, action_id, risk_level, etc.
        """
        if action_type not in ['click', 'form_submit', 'navigation']:
            raise ValueError(f"Invalid action_type: {action_type}")
        
        # Extract domain from URL if not provided
        if not domain:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
        
        # Dev mode: allow all actions without backend (for browser automation testing)
        if self.dev_mode:
            return {
                "status": "allowed",
                "action_id": f"dev-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "risk_level": "low",
                "message": "Action allowed (dev mode - no backend)"
            }
        
        # Build action data
        action_data = {
            "type": action_type,
            "url": url,
            "domain": domain,
            "timestamp": datetime.now().isoformat()
        }
        
        if self.current_session_id:
            action_data["sessionId"] = self.current_session_id

        if self.current_prompt_id:
            action_data["promptId"] = self.current_prompt_id
        
        if target:
            action_data["target"] = target
        
        if form_data:
            action_data["form"] = {"fields": form_data}
        
        if screenshot:
            action_data["screenshot"] = screenshot
        
        # Make request
        try:
            token = self._get_token()
        except Exception as e:
            return {
                "status": "error",
                "message": f"Auth failed: {e}. Set AGENTTRUST_DEV_MODE=true to run without backend."
            }
        try:
            response = requests.post(
                f"{self.api_url}/actions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=action_data,
                timeout=10
            )
        except requests.exceptions.RequestException as e:
            return {
                "status": "error",
                "message": f"Backend unreachable: {e}. Is it running? Set AGENTTRUST_DEV_MODE=true to run without backend."
            }
        
        try:
            result = response.json()
        except Exception:
            result = {"error": response.text or "Unknown error"}
        
        if response.status_code == 201:
            return {
                "status": "allowed",
                "action_id": result.get("action", {}).get("id"),
                "risk_level": result.get("action", {}).get("riskLevel"),
                "message": "Action allowed and logged"
            }
        elif response.status_code == 403:
            if result.get("requiresStepUp") and result.get("approvalId"):
                approval_id = result["approvalId"]
                print(f"🔐 High-risk action requires user approval (approvalId={approval_id}). Waiting...")
                approval_result = self.wait_for_approval(approval_id, timeout=60)

                if approval_result.get("approved"):
                    print("✅ Action approved by user. Retrying...")
                    return self._retry_with_approval(action_data, approval_id)
                else:
                    reason = approval_result.get("reason", "User denied the action")
                    print(f"❌ Action denied by user: {reason}")
                    return {
                        "status": "denied",
                        "message": f"Action denied by user: {reason}",
                        "risk_level": result.get("riskLevel"),
                        "approval_denied": True
                    }
            elif result.get("requiresStepUp"):
                return {
                    "status": "step_up_required",
                    "message": "High-risk action requires user approval",
                    "risk_level": result.get("riskLevel"),
                    "error": result.get("error")
                }
            else:
                return {
                    "status": "denied",
                    "message": result.get("error", "Action denied by policy"),
                    "reason": result.get("reason")
                }
        elif response.status_code == 401:
            return {
                "status": "unauthorized",
                "message": "Authentication failed",
                "error": result.get("error")
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", "Unknown error"),
                "status_code": response.status_code
            }
    
    def wait_for_approval(self, approval_id: str, timeout: int = 60) -> Dict[str, Any]:
        """Long-poll the backend waiting for the user to approve or deny an action.
        
        Args:
            approval_id: The approval request ID from a step_up_required response
            timeout: Maximum seconds to wait for user decision
            
        Returns:
            Dict with 'approved' bool and optional 'reason'
        """
        if self.dev_mode:
            return {"approved": False, "reason": "Dev mode - no approval flow"}
        try:
            token = self._get_token()
            response = requests.get(
                f"{self.api_url}/approvals/{approval_id}/wait",
                headers={"Authorization": f"Bearer {token}"},
                params={"timeout": timeout * 1000},
                timeout=timeout + 10
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "approved": data.get("approved", False),
                    "reason": data.get("reason"),
                    "approvalId": approval_id,
                    "actionId": data.get("actionId")
                }
            elif response.status_code == 404:
                return {"approved": False, "reason": "Approval request not found or expired"}
            else:
                return {"approved": False, "reason": f"Unexpected status: {response.status_code}"}
        except requests.exceptions.Timeout:
            return {"approved": False, "reason": "Approval wait timed out"}
        except Exception as e:
            print(f"⚠️  Approval wait error: {e}")
            return {"approved": False, "reason": str(e)}

    def _retry_with_approval(self, action_data: Dict, approval_id: str) -> Dict[str, Any]:
        """Retry a previously blocked action after receiving user approval."""
        action_data["approvalId"] = approval_id
        try:
            token = self._get_token()
            response = requests.post(
                f"{self.api_url}/actions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=action_data,
                timeout=10
            )
            result = response.json() if response.status_code != 204 else {}
            if response.status_code == 201:
                return {
                    "status": "allowed",
                    "action_id": result.get("action", {}).get("id"),
                    "risk_level": result.get("action", {}).get("riskLevel"),
                    "message": "Action allowed after user approval"
                }
            else:
                return {
                    "status": "error",
                    "message": result.get("error", "Retry after approval failed"),
                    "status_code": response.status_code
                }
        except Exception as e:
            return {"status": "error", "message": f"Retry failed: {e}"}

    def request_step_up(
        self,
        action_data: Dict,
        reason: str
    ) -> Dict[str, Any]:
        """
        Request step-up token for high-risk action
        
        Args:
            action_data: Original action data
            reason: User-provided reason for step-up
        
        Returns:
            Dict with step-up token and expiration
        """
        token = self._get_token()
        response = requests.post(
            f"{self.api_url}/auth/stepup",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "action": action_data,
                "reason": reason
            }
        )
        
        result = response.json()
        
        if response.status_code == 200:
            return {
                "success": True,
                "token": result.get("token"),
                "expires_in": result.get("expiresIn"),
                "scopes": result.get("scopes")
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Step-up failed")
            }
    
    def _update_action_screenshot(self, action_id: str, screenshot: str) -> None:
        """
        Update an action with a screenshot (internal method)
        
        Args:
            action_id: ID of the action to update
            screenshot: Base64 encoded screenshot
        """
        if self.dev_mode:
            return
        try:
            token = self._get_token()
            response = requests.patch(
                f"{self.api_url}/actions/{action_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={"screenshot": screenshot}
            )
            if response.status_code != 200:
                detail = ""
                try:
                    detail = f" - {response.json().get('error', response.text[:200])}"
                except Exception:
                    pass
                print(f"⚠️  Failed to update action with screenshot: {response.status_code}{detail}")
        except Exception as e:
            print(f"⚠️  Error updating screenshot: {e}")
    
    def store_prompt(self, content: str, session_id: Optional[str] = None) -> Optional[str]:
        """Store a user prompt and return the prompt ID."""
        if self.dev_mode:
            return None
        try:
            token = self._get_token()
            payload = {"content": content}
            sid = session_id or self.current_session_id
            if sid:
                payload["sessionId"] = sid
            response = requests.post(
                f"{self.api_url}/prompts",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=5
            )
            if response.status_code == 201:
                pid = response.json().get("prompt", {}).get("id")
                if pid:
                    self.current_prompt_id = pid
                return pid
        except Exception as e:
            print(f"⚠️  Failed to store prompt: {e}")
        return None

    def update_prompt_response(self, prompt_id: str, response_text: str) -> None:
        """Update a stored prompt with the agent's response."""
        if self.dev_mode or not prompt_id:
            return
        try:
            token = self._get_token()
            requests.patch(
                f"{self.api_url}/prompts/{prompt_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={"response": response_text},
                timeout=5
            )
        except Exception as e:
            print(f"⚠️  Failed to update prompt response: {e}")

    def poll_command(self, timeout: int = 30) -> Optional[Dict]:
        """Long-poll the backend for a pending command from the browser extension.
        Returns the command dict if one arrives, or None on timeout."""
        if self.dev_mode or not self.current_session_id:
            return None
        try:
            token = self._get_token()
            response = requests.get(
                f"{self.api_url}/commands/pending",
                headers={"Authorization": f"Bearer {token}"},
                params={"sessionId": self.current_session_id, "timeout": timeout * 1000},
                timeout=timeout + 5
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("command"):
                    return data["command"]
        except requests.exceptions.Timeout:
            pass
        except (requests.exceptions.ConnectionError, ConnectionResetError, ConnectionError):
            pass
        except Exception as e:
            print(f"⚠️  Command poll error: {e}")
        return None

    def get_audit_log(
        self,
        agent_id: Optional[str] = None,
        domain: Optional[str] = None,
        risk_level: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get audit log
        
        Args:
            agent_id: Filter by agent ID
            domain: Filter by domain
            risk_level: Filter by risk level (low, medium, high)
            start_date: Start date (ISO 8601)
            end_date: End date (ISO 8601)
            limit: Maximum results
        
        Returns:
            Dict with actions array
        """
        if self.dev_mode:
            return {"actions": [], "message": "Dev mode - no audit log"}
        token = self._get_token()
        params = {"limit": limit}
        
        if agent_id:
            params["agentId"] = agent_id
        if domain:
            params["domain"] = domain
        if risk_level:
            params["riskLevel"] = risk_level
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        
        response = requests.get(
            f"{self.api_url}/actions",
            headers={"Authorization": f"Bearer {token}"},
            params=params
        )
        
        return response.json()
    
    def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate a JWT token
        
        Args:
            token: JWT token to validate
        
        Returns:
            Validation result
        """
        response = requests.post(
            f"{self.api_url}/auth/validate",
            headers={"Content-Type": "application/json"},
            json={"token": token}
        )
        
        return response.json()


# OpenAI Function definition for ChatGPT
AGENTTRUST_FUNCTION_DEFINITION = {
    "type": "function",
    "function": {
        "name": "agenttrust_browser_action",
        "description": "MANDATORY: Execute a browser action (click, form submit, navigation) through AgentTrust's policy-enforced system. This is the ONLY way to perform browser actions - AgentTrust validation is enforced 100% of the time. Returns whether action is allowed, denied, or requires step-up authentication. You MUST call this function before performing ANY browser automation - there is no alternative or bypass.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["click", "form_submit", "navigation"],
                    "description": "Type of browser action to perform"
                },
                "url": {
                    "type": "string",
                    "description": "Full URL of the page where the action occurs"
                },
                "target": {
                    "type": "object",
                    "description": "Target element information (required for click actions)",
                    "properties": {
                        "tagName": {"type": "string", "description": "HTML tag name"},
                        "id": {"type": "string", "description": "Element ID"},
                        "className": {"type": "string", "description": "CSS class name"},
                        "text": {"type": "string", "description": "Element text content"}
                    }
                },
                "form_data": {
                    "type": "object",
                    "description": "Form data fields (required for form_submit actions)"
                }
            },
            "required": ["action_type", "url"]
        }
    }
}


# Example usage
if __name__ == "__main__":
    # Initialize client
    client = AgentTrustClient()
    
    # Example: Click action
    result = client.execute_action(
        action_type="click",
        url="https://github.com/user/repo",
        target={
            "tagName": "BUTTON",
            "id": "submit-btn",
            "text": "Submit"
        }
    )
    
    print(f"Action status: {result['status']}")
    if result['status'] == 'allowed':
        print(f"Action ID: {result['action_id']}")
        print(f"Risk Level: {result['risk_level']}")
    elif result['status'] == 'step_up_required':
        print("Step-up authentication required")
        # Request step-up
        step_up_result = client.request_step_up(
            action_data={"type": "click", "url": "https://github.com/user/repo"},
            reason="User requested repository deletion after archiving"
        )
        if step_up_result['success']:
            print("Step-up token obtained")
    else:
        print(f"Action denied: {result['message']}")
