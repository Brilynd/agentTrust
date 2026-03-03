"""
Auth0 Token Vault Integration for AI Agents
===========================================
Auth0 for AI Agents hackathon compliance - Token Vault for OAuth flows,
token management, and consent delegation.

Built with Token Vault from Auth0 for AI Agents:
- OAuth flows handled by Auth0
- Token management (storage, refresh) by Auth0
- Consent delegation for connected accounts

References:
- https://auth0.com/ai/docs/intro/token-vault
- https://auth0.com/docs/secure/call-apis-on-users-behalf/token-vault
"""

import os
import requests
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass


class Auth0TokenVaultClient:
    """
    Client for Auth0 Token Vault - enables AI agents to securely access
    third-party APIs (GitHub, Google, Slack, etc.) on users' behalf.
    
    Auth0 handles: OAuth flows, token management, consent delegation.
    """
    
    def __init__(
        self,
        auth0_domain: Optional[str] = None,
        auth0_client_id: Optional[str] = None,
        auth0_client_secret: Optional[str] = None,
        auth0_audience: Optional[str] = None,
    ):
        self.auth0_domain = auth0_domain or os.getenv("AUTH0_DOMAIN")
        self.auth0_client_id = auth0_client_id or os.getenv("AUTH0_CLIENT_ID")
        self.auth0_client_secret = auth0_client_secret or os.getenv("AUTH0_CLIENT_SECRET")
        self.auth0_audience = auth0_audience or os.getenv("AUTH0_AUDIENCE")
        
        self._m2m_token = None
        self._m2m_token_expiry = None
    
    def _get_m2m_token(self) -> str:
        """Get Auth0 M2M access token (client credentials)."""
        if self._m2m_token and self._m2m_token_expiry and datetime.now() < self._m2m_token_expiry:
            return self._m2m_token
        
        if not all([self.auth0_domain, self.auth0_client_id, self.auth0_client_secret]):
            raise ValueError("Auth0 credentials required for Token Vault")
        
        resp = requests.post(
            f"https://{self.auth0_domain}/oauth/token",
            json={
                "client_id": self.auth0_client_id,
                "client_secret": self.auth0_client_secret,
                "audience": self.auth0_audience,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._m2m_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._m2m_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
        return self._m2m_token
    
    def get_external_token(
        self,
        user_access_token: str,
        connection_id: str,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exchange user's Auth0 token for external provider token (Token Vault).
        
        Uses Auth0 Token Vault - Auth0 handles token storage, refresh, consent.
        
        Args:
            user_access_token: User's Auth0 access token (from login/consent)
            connection_id: Auth0 connection ID for the external provider
            provider: Optional provider name (google-oauth2, github, etc.)
        
        Returns:
            dict with access_token, expires_in, token_type, or error
        """
        # Token Vault exchange - requires Auth0 dashboard setup:
        # 1. Enable "Use for Connected Accounts for Token Vault"
        # 2. Configure OAuth2 integration for the provider
        # 3. User must have authorized the connection (consent delegation)
        try:
            # Token Vault exchange - requires Auth0 app configured with grant type
            resp = requests.post(
                f"https://{self.auth0_domain}/oauth/token",
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token",
                    "client_id": self.auth0_client_id,
                    "client_secret": self.auth0_client_secret,
                    "subject_token": user_access_token,
                    "subject_token_type": "urn:auth0:params:oauth:token-type:access-token",
                    "connection": connection_id,
                    "audience": self.auth0_audience,
                },
            )
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": resp.json().get("error_description", resp.text),
                }
            data = resp.json()
            return {
                "success": True,
                "access_token": data.get("access_token"),
                "expires_in": data.get("expires_in"),
                "token_type": data.get("token_type", "Bearer"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def has_token_vault_config(self) -> bool:
        """Check if Token Vault is configured (Auth0 credentials present)."""
        return bool(
            self.auth0_domain
            and self.auth0_client_id
            and self.auth0_client_secret
        )


# Hackathon compliance: Auth0 for AI Agents - Token Vault
# This module integrates Token Vault for:
# - OAuth flows: Auth0 manages authorization with external providers
# - Token management: Auth0 stores and refreshes tokens securely
# - Consent delegation: Users authorize AI agents via Connected Accounts
