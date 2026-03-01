"""
Test Agent for AgentTrust
Simulates an agent performing browser actions through AgentTrust

Usage:
    python test_agent.py
"""

import os
import sys
from datetime import datetime
from agenttrust_client import AgentTrustClient


class TestAgent:
    """Simple test agent that uses AgentTrust"""
    
    def __init__(self, agent_name="Test-Agent"):
        self.agent_name = agent_name
        try:
            self.agenttrust = AgentTrustClient()
        except ValueError as e:
            print(f"❌ Configuration Error: {e}")
            print("\nPlease set the following environment variables:")
            print("  - AUTH0_DOMAIN")
            print("  - AUTH0_CLIENT_ID")
            print("  - AUTH0_CLIENT_SECRET")
            print("  - AUTH0_AUDIENCE")
            print("  - AGENTTRUST_API_URL (optional, defaults to http://localhost:3000/api)")
            sys.exit(1)
        
        self.actions_performed = []
        self.actions_denied = []
        self.step_ups_required = []
    
    def log(self, message):
        """Log message with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.agent_name}: {message}")
    
    def perform_action(self, action_type, url, target=None, form_data=None):
        """
        Perform browser action through AgentTrust
        
        Returns:
            dict with status and action details
        """
        self.log(f"Requesting {action_type} action on {url}")
        
        try:
            result = self.agenttrust.execute_action(
                action_type=action_type,
                url=url,
                target=target,
                form_data=form_data
            )
            
            status = result.get("status")
            
            if status == "allowed":
                self.log(f"✅ Action ALLOWED (Risk: {result.get('risk_level', 'unknown')})")
                self.actions_performed.append({
                    "type": action_type,
                    "url": url,
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                })
                return {"success": True, "result": result}
            
            elif status == "step_up_required":
                self.log(f"⚠️  STEP-UP REQUIRED (Risk: {result.get('risk_level', 'unknown')})")
                self.step_ups_required.append({
                    "type": action_type,
                    "url": url,
                    "risk_level": result.get("risk_level")
                })
                return {"success": False, "requires_approval": True, "result": result}
            
            elif status == "denied":
                self.log(f"❌ Action DENIED: {result.get('message', 'Unknown reason')}")
                self.actions_denied.append({
                    "type": action_type,
                    "url": url,
                    "reason": result.get("message")
                })
                return {"success": False, "denied": True, "result": result}
            
            else:
                self.log(f"❓ Unknown status: {status}")
                return {"success": False, "result": result}
        
        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def request_step_up(self, action_data, reason):
        """Request step-up token for high-risk action"""
        self.log(f"Requesting step-up approval: {reason}")
        
        try:
            result = self.agenttrust.request_step_up(
                action_data=action_data,
                reason=reason
            )
            
            if result.get("success"):
                self.log(f"✅ Step-up token obtained (expires in {result.get('expires_in')}s)")
                return result
            else:
                self.log(f"❌ Step-up failed: {result.get('error')}")
                return result
        
        except Exception as e:
            self.log(f"❌ Step-up error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Agent: {self.agent_name}")
        print(f"Actions Performed: {len(self.actions_performed)}")
        print(f"Actions Denied: {len(self.actions_denied)}")
        print(f"Step-Ups Required: {len(self.step_ups_required)}")
        print("\nActions Performed:")
        for action in self.actions_performed:
            print(f"  - {action['type']} on {action['url']} (Risk: {action['risk_level']})")
        if self.actions_denied:
            print("\nActions Denied:")
            for action in self.actions_denied:
                print(f"  - {action['type']} on {action['url']}: {action['reason']}")
        if self.step_ups_required:
            print("\nStep-Ups Required:")
            for action in self.step_ups_required:
                print(f"  - {action['type']} on {action['url']} (Risk: {action['risk_level']})")
        print("="*60)


def main():
    """Run test scenarios"""
    print("="*60)
    print("AgentTrust Test Agent")
    print("="*60)
    print()
    
    # Initialize agent
    agent = TestAgent(agent_name="Test-Agent-001")
    
    # Test Scenario 1: Low-Risk Action (Should be allowed)
    print("\n" + "-"*60)
    print("SCENARIO 1: Low-Risk Action (Navigation)")
    print("-"*60)
    result1 = agent.perform_action(
        action_type="navigation",
        url="https://github.com/user/repo"
    )
    
    # Test Scenario 2: Low-Risk Click (Should be allowed)
    print("\n" + "-"*60)
    print("SCENARIO 2: Low-Risk Click")
    print("-"*60)
    result2 = agent.perform_action(
        action_type="click",
        url="https://github.com/user/repo",
        target={
            "tagName": "BUTTON",
            "id": "view-btn",
            "text": "View Code"
        }
    )
    
    # Test Scenario 3: Medium-Risk Form Submit (Should be allowed with scope)
    print("\n" + "-"*60)
    print("SCENARIO 3: Medium-Risk Form Submit")
    print("-"*60)
    result3 = agent.perform_action(
        action_type="form_submit",
        url="https://github.com/user/repo/issues/new",
        form_data={
            "title": "Test Issue",
            "body": "This is a test issue"
        }
    )
    
    # Test Scenario 4: High-Risk Action (Should require step-up)
    print("\n" + "-"*60)
    print("SCENARIO 4: High-Risk Action (Delete)")
    print("-"*60)
    result4 = agent.perform_action(
        action_type="click",
        url="https://github.com/user/repo/settings",
        target={
            "tagName": "BUTTON",
            "text": "Delete Repository"
        }
    )
    
    # If step-up required, test step-up flow
    if result4.get("requires_approval"):
        print("\n" + "-"*60)
        print("SCENARIO 5: Step-Up Approval Flow")
        print("-"*60)
        step_up_result = agent.request_step_up(
            action_data={
                "type": "click",
                "url": "https://github.com/user/repo/settings",
                "target": {"text": "Delete Repository"}
            },
            reason="Repository is archived and no longer needed. User requested deletion."
        )
        
        if step_up_result.get("success"):
            print("\n✅ Step-up successful! Agent can now perform high-risk action.")
            # In real scenario, agent would retry the action with step-up token
    
    # Test Scenario 6: Blocked Domain (Should be denied if in policy)
    print("\n" + "-"*60)
    print("SCENARIO 6: Test Domain Policy")
    print("-"*60)
    result6 = agent.perform_action(
        action_type="click",
        url="https://example.com",
        target={"tagName": "BUTTON", "text": "Click"}
    )
    
    # Print summary
    agent.print_summary()
    
    # Query audit log
    print("\n" + "-"*60)
    print("AUDIT LOG QUERY")
    print("-"*60)
    try:
        audit_log = agent.agenttrust.get_audit_log(limit=10)
        actions = audit_log.get('actions', [])
        print(f"Total actions in audit log: {len(actions)}")
        for action in actions[:5]:
            print(f"  - {action.get('type')} on {action.get('domain')} at {action.get('timestamp', 'N/A')}")
    except Exception as e:
        print(f"Error querying audit log: {e}")
        print("(This is normal if audit log query is not fully implemented)")


if __name__ == "__main__":
    main()
