"""
Real ChatGPT Agent with AgentTrust Integration
This is a real-world example of ChatGPT using AgentTrust to govern browser actions

100% ENFORCEMENT: All browser actions MUST go through AgentTrust validation.
There is no way to perform a browser action without AgentTrust approval.

Browser Automation: Uses Selenium to actually interact with the browser and get page content.

Usage:
    pip install openai requests selenium
    python chatgpt_agent_with_agenttrust.py
"""

import os
import json
import sys
import base64
from typing import Optional, Dict, List, Any
from openai import OpenAI
from agenttrust_client import AgentTrustClient, AGENTTRUST_FUNCTION_DEFINITION

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env from the same directory as this script
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    # python-dotenv not installed, will use system environment variables only
    pass

# Browser automation - optional import
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️  Selenium not installed. Browser automation disabled.")
    print("   Install with: pip install selenium")


class BrowserController:
    """
    Browser automation controller using Selenium.
    Provides methods to interact with the browser and get page content.
    """
    
    def __init__(self, headless: bool = False):
        """Initialize browser controller"""
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium is required for browser automation. Install with: pip install selenium")
        
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        self.driver = webdriver.Chrome(options=options)
        self.current_url = None
    
    def navigate(self, url: str):
        """Navigate to URL"""
        self.driver.get(url)
        self.current_url = self.driver.current_url
        return {"success": True, "url": self.current_url}
    
    def get_current_url(self) -> str:
        """Get current page URL"""
        self.current_url = self.driver.current_url
        return self.current_url
    
    def get_page_title(self) -> str:
        """Get page title"""
        return self.driver.title
    
    def get_page_content(self, include_html: bool = False) -> Dict[str, Any]:
        """
        Get page content - text and optionally HTML
        
        Returns:
            dict with text content, title, url, and optionally html
        """
        content = {
            "url": self.driver.current_url,
            "title": self.driver.title,
            "text": self.driver.find_element(By.TAG_NAME, "body").text[:5000]  # Limit to 5000 chars
        }
        
        if include_html:
            content["html"] = self.driver.page_source[:10000]  # Limit to 10000 chars
        
        return content
    
    def get_visible_elements(self, element_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get visible interactive elements on the page
        
        Args:
            element_type: Filter by type ('button', 'link', 'input', 'form', etc.)
        
        Returns:
            List of element information
        """
        elements = []
        
        try:
            # Get buttons
            if not element_type or element_type == 'button':
                buttons = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons[:20]:  # Limit to 20
                    if btn.is_displayed():
                        elements.append({
                            "type": "button",
                            "text": btn.text[:100],
                            "id": btn.get_attribute("id"),
                            "class": btn.get_attribute("class")
                        })
            
            # Get links
            if not element_type or element_type == 'link':
                links = self.driver.find_elements(By.TAG_NAME, "a")
                for link in links[:20]:  # Limit to 20
                    if link.is_displayed():
                        elements.append({
                            "type": "link",
                            "text": link.text[:100],
                            "href": link.get_attribute("href"),
                            "id": link.get_attribute("id")
                        })
            
            # Get inputs
            if not element_type or element_type == 'input':
                inputs = self.driver.find_elements(By.TAG_NAME, "input")
                for inp in inputs[:20]:  # Limit to 20
                    if inp.is_displayed():
                        elements.append({
                            "type": "input",
                            "input_type": inp.get_attribute("type"),
                            "name": inp.get_attribute("name"),
                            "id": inp.get_attribute("id"),
                            "placeholder": inp.get_attribute("placeholder")
                        })
        
        except Exception as e:
            print(f"⚠️  Error getting elements: {e}")
        
        return elements
    
    def click_element(self, target: Dict[str, Any]) -> Dict[str, Any]:
        """
        Click an element based on target information
        
        Args:
            target: dict with id, text, class, or other identifiers
        
        Returns:
            dict with success status
        """
        try:
            element = None
            
            # Try to find by ID first
            if target.get("id"):
                element = self.driver.find_element(By.ID, target["id"])
            # Try by text
            elif target.get("text"):
                element = self.driver.find_element(By.XPATH, f"//*[contains(text(), '{target['text'][:50]}')]")
            # Try by class
            elif target.get("className"):
                element = self.driver.find_element(By.CLASS_NAME, target["className"])
            
            if element and element.is_displayed():
                element.click()
                return {"success": True, "message": "Element clicked successfully"}
            else:
                return {"success": False, "message": "Element not found or not visible"}
        
        except Exception as e:
            return {"success": False, "message": f"Error clicking element: {str(e)}"}
    
    def submit_form(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a form with provided data
        
        Args:
            form_data: dict with field names and values
        
        Returns:
            dict with success status
        """
        try:
            # Find form fields and fill them
            for field_name, field_value in form_data.items():
                try:
                    field = self.driver.find_element(By.NAME, field_name)
                    field.clear()
                    field.send_keys(str(field_value))
                except NoSuchElementException:
                    # Try by ID
                    try:
                        field = self.driver.find_element(By.ID, field_name)
                        field.clear()
                        field.send_keys(str(field_value))
                    except NoSuchElementException:
                        print(f"⚠️  Form field '{field_name}' not found")
            
            # Submit form
            submit_button = self.driver.find_element(By.XPATH, "//input[@type='submit'] | //button[@type='submit']")
            submit_button.click()
            
            return {"success": True, "message": "Form submitted successfully"}
        
        except Exception as e:
            return {"success": False, "message": f"Error submitting form: {str(e)}"}
    
    def take_screenshot(self, save_path: Optional[str] = None) -> str:
        """
        Take a screenshot of the current page
        
        Args:
            save_path: Optional path to save screenshot
        
        Returns:
            Base64 encoded screenshot or file path
        """
        if save_path:
            self.driver.save_screenshot(save_path)
            return save_path
        else:
            # Return base64 encoded screenshot
            screenshot = self.driver.get_screenshot_as_base64()
            return screenshot
    
    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()


class BrowserActionExecutor:
    """
    MANDATORY browser action executor that enforces 100% AgentTrust validation.
    
    This is the ONLY way to perform browser actions. All actions MUST be validated
    by AgentTrust before execution. There is no bypass.
    
    After AgentTrust validation, actions are actually executed in the browser.
    """
    
    def __init__(self, agenttrust_client: AgentTrustClient, browser_controller: Optional[BrowserController] = None):
        """Initialize with AgentTrust client and optional browser controller"""
        if not agenttrust_client:
            raise ValueError("AgentTrust client is required - no actions can be performed without it")
        self.agenttrust = agenttrust_client
        self.browser = browser_controller
        self.action_history = []
    
    def execute_click(self, url: str, target: dict, **kwargs):
        """
        Execute a click action - MANDATORY AgentTrust validation
        
        This method CANNOT be bypassed. AgentTrust validation is enforced.
        
        Returns:
            dict with status and action_id if allowed
        Raises:
            PermissionError: If AgentTrust denies the action
            ValueError: If AgentTrust validation fails
        """
        # MANDATORY: Validate with AgentTrust first
        result = self.agenttrust.execute_action(
            action_type="click",
            url=url,
            target=target
        )
        
        status = result.get("status")
        
        # ENFORCEMENT: Action cannot proceed without AgentTrust approval
        if status == "denied":
            error_msg = result.get("message", "Action denied by AgentTrust policy")
            self.action_history.append({
                "action": "click",
                "url": url,
                "status": "denied",
                "reason": error_msg
            })
            raise PermissionError(f"❌ AgentTrust DENIED: {error_msg}")
        
        if status == "step_up_required":
            # Step-up required - action cannot proceed without approval
            self.action_history.append({
                "action": "click",
                "url": url,
                "status": "step_up_required",
                "risk_level": result.get("risk_level")
            })
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: High-risk action requires user approval. "
                f"Risk level: {result.get('risk_level')}"
            )
        
        if status != "allowed":
            # Unknown status - fail safe
            raise ValueError(f"AgentTrust validation failed with status: {status}")
        
        # Action is allowed - log and return
        self.action_history.append({
            "action": "click",
            "url": url,
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level")
        })
        
        # Actually perform the click if browser is available
        browser_result = None
        if self.browser and target:
            browser_result = self.browser.click_element(target)
        
        return {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Click action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result
        }
    
    def execute_form_submit(self, url: str, form_data: dict, **kwargs):
        """
        Execute a form submit action - MANDATORY AgentTrust validation
        
        This method CANNOT be bypassed. AgentTrust validation is enforced.
        
        Returns:
            dict with status and action_id if allowed
        Raises:
            PermissionError: If AgentTrust denies the action
            ValueError: If AgentTrust validation fails
        """
        # MANDATORY: Validate with AgentTrust first
        result = self.agenttrust.execute_action(
            action_type="form_submit",
            url=url,
            form_data=form_data
        )
        
        status = result.get("status")
        
        # ENFORCEMENT: Action cannot proceed without AgentTrust approval
        if status == "denied":
            error_msg = result.get("message", "Action denied by AgentTrust policy")
            self.action_history.append({
                "action": "form_submit",
                "url": url,
                "status": "denied",
                "reason": error_msg
            })
            raise PermissionError(f"❌ AgentTrust DENIED: {error_msg}")
        
        if status == "step_up_required":
            # Step-up required - action cannot proceed without approval
            self.action_history.append({
                "action": "form_submit",
                "url": url,
                "status": "step_up_required",
                "risk_level": result.get("risk_level")
            })
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: High-risk action requires user approval. "
                f"Risk level: {result.get('risk_level')}"
            )
        
        if status != "allowed":
            # Unknown status - fail safe
            raise ValueError(f"AgentTrust validation failed with status: {status}")
        
        # Action is allowed - log and return
        self.action_history.append({
            "action": "form_submit",
            "url": url,
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level")
        })
        
        # Actually perform the form submit if browser is available
        browser_result = None
        if self.browser and form_data:
            browser_result = self.browser.submit_form(form_data)
        
        return {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Form submit action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result
        }
    
    def execute_navigation(self, url: str, **kwargs):
        """
        Execute a navigation action - MANDATORY AgentTrust validation
        
        This method CANNOT be bypassed. AgentTrust validation is enforced.
        
        Returns:
            dict with status and action_id if allowed
        Raises:
            PermissionError: If AgentTrust denies the action
            ValueError: If AgentTrust validation fails
        """
        # MANDATORY: Validate with AgentTrust first
        result = self.agenttrust.execute_action(
            action_type="navigation",
            url=url
        )
        
        status = result.get("status")
        
        # ENFORCEMENT: Action cannot proceed without AgentTrust approval
        if status == "denied":
            error_msg = result.get("message", "Action denied by AgentTrust policy")
            self.action_history.append({
                "action": "navigation",
                "url": url,
                "status": "denied",
                "reason": error_msg
            })
            raise PermissionError(f"❌ AgentTrust DENIED: {error_msg}")
        
        if status == "step_up_required":
            # Step-up required - action cannot proceed without approval
            self.action_history.append({
                "action": "navigation",
                "url": url,
                "status": "step_up_required",
                "risk_level": result.get("risk_level")
            })
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: High-risk action requires user approval. "
                f"Risk level: {result.get('risk_level')}"
            )
        
        if status != "allowed":
            # Unknown status - fail safe
            raise ValueError(f"AgentTrust validation failed with status: {status}")
        
        # Action is allowed - log and return
        self.action_history.append({
            "action": "navigation",
            "url": url,
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level")
        })
        
        # Actually perform the navigation if browser is available
        browser_result = None
        if self.browser:
            browser_result = self.browser.navigate(url)
        
        return {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Navigation action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result
        }
    
    def get_page_content(self, include_html: bool = False) -> Dict[str, Any]:
        """
        Get current page content - NO AgentTrust validation needed (read-only)
        
        Returns:
            dict with page content, title, url, text, and optionally html
        """
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        return self.browser.get_page_content(include_html=include_html)
    
    def get_visible_elements(self, element_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get visible elements on the page - NO AgentTrust validation needed (read-only)
        
        Args:
            element_type: Optional filter ('button', 'link', 'input', etc.)
        
        Returns:
            List of visible elements
        """
        if not self.browser:
            return []
        
        return self.browser.get_visible_elements(element_type)
    
    def get_current_url(self) -> str:
        """Get current page URL - NO AgentTrust validation needed (read-only)"""
        if not self.browser:
            return ""
        
        return self.browser.get_current_url()
    
    def take_screenshot(self) -> str:
        """Take screenshot - NO AgentTrust validation needed (read-only)"""
        if not self.browser:
            return ""
        
        return self.browser.take_screenshot()


class ChatGPTAgentWithAgentTrust:
    """
    Real ChatGPT agent that uses AgentTrust to validate browser actions
    
    This demonstrates the real-world scenario:
    - ChatGPT makes decisions about what to do
    - Before each browser action, ChatGPT calls AgentTrust
    - AgentTrust validates and controls what ChatGPT can do
    - ChatGPT only performs allowed actions
    """
    
    def __init__(self, enable_browser: bool = True, headless: bool = False):
        """
        Initialize ChatGPT agent with AgentTrust - 100% enforcement
        
        Args:
            enable_browser: Whether to enable browser automation (requires Selenium)
            headless: Run browser in headless mode
        """
        try:
            self.openai = OpenAI()
        except Exception as e:
            print(f"❌ OpenAI client error: {e}")
            print("   Make sure OPENAI_API_KEY is set in environment")
            sys.exit(1)
        
        try:
            agenttrust_client = AgentTrustClient()
        except ValueError as e:
            print(f"❌ AgentTrust configuration error: {e}")
            print("\nPlease set the following environment variables:")
            print("  - AUTH0_DOMAIN")
            print("  - AUTH0_CLIENT_ID")
            print("  - AUTH0_CLIENT_SECRET")
            print("  - AUTH0_AUDIENCE")
            sys.exit(1)
        
        # Initialize browser controller if enabled
        browser_controller = None
        if enable_browser:
            try:
                browser_controller = BrowserController(headless=headless)
                print("✅ Browser automation enabled")
            except ImportError:
                print("⚠️  Browser automation disabled (Selenium not available)")
            except Exception as e:
                print(f"⚠️  Browser automation disabled: {e}")
        
        # CRITICAL: Create mandatory browser action executor
        # This is the ONLY way to perform browser actions - 100% AgentTrust enforcement
        self.browser_executor = BrowserActionExecutor(agenttrust_client, browser_controller)
        self.agenttrust = agenttrust_client  # Keep reference for audit log queries
        
        self.conversation_history = []
        self.actions_performed = []
        self.actions_blocked = []
    
    def chat(self, user_message):
        """
        Chat with user, using AgentTrust for browser actions
        
        This is the real-world flow:
        1. User asks ChatGPT to do something
        2. ChatGPT decides what browser actions are needed
        3. For each action, ChatGPT calls AgentTrust function
        4. AgentTrust validates
        5. ChatGPT acts based on validation result
        """
        print(f"\n👤 User: {user_message}\n")
        
        # System prompt - AgentTrust is MANDATORY, not optional
        system_prompt = """You are a browser automation assistant with AgentTrust integration.

CRITICAL: AgentTrust validation is MANDATORY for ALL browser actions. There is no way to bypass it.

BROWSER INTERACTION:
- You can see what's on the page using get_page_content and get_visible_elements functions
- These are READ-ONLY functions - no AgentTrust validation needed
- Use these to understand the page before taking actions

WORKFLOW:
1. First, use get_page_content or get_visible_elements to see what's on the page
2. When you want to perform ANY browser action (click, form submit, navigation), you MUST call the agenttrust_browser_action function
3. The function will return one of three statuses:
   - "allowed": Action is approved by AgentTrust - you can proceed
   - "step_up_required": High-risk action requires user approval - ask the user
   - "denied": Action is blocked by AgentTrust policy - explain why and stop
4. You CANNOT perform browser actions without calling this function first
5. The function is the ONLY way to validate actions - there is no alternative

IMPORTANT:
- Every browser action MUST go through AgentTrust validation
- Reading page content does NOT require validation (it's read-only)
- If validation fails, the action cannot proceed
- Always explain what you're doing and why
- Report AgentTrust validation results to the user"""
        
        messages = [
            {"role": "system", "content": system_prompt}
        ] + self.conversation_history + [
            {"role": "user", "content": user_message}
        ]
        
        # Build function definitions - include page content functions
        tools = [AGENTTRUST_FUNCTION_DEFINITION]
        
        # Add page content functions if browser is available
        if self.browser_executor.browser:
            tools.extend([
                {
                    "type": "function",
                    "function": {
                        "name": "get_page_content",
                        "description": "Get the current page content including text, title, and URL. This is READ-ONLY - no AgentTrust validation needed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "include_html": {
                                    "type": "boolean",
                                    "description": "Whether to include HTML source (default: false)"
                                }
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_visible_elements",
                        "description": "Get visible interactive elements on the current page (buttons, links, inputs, etc.). This is READ-ONLY - no AgentTrust validation needed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "element_type": {
                                    "type": "string",
                                    "enum": ["button", "link", "input", "form"],
                                    "description": "Filter by element type (optional)"
                                }
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_url",
                        "description": "Get the current page URL. This is READ-ONLY - no AgentTrust validation needed.",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                }
            ])
        
        # Get ChatGPT's response
        response = self.openai.chat.completions.create(
            model="gpt-4",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        # Handle tool calls (AgentTrust validation or page content)
        while message.tool_calls:
            # Handle all tool calls in this message
            for tool_call in message.tool_calls:
                function_call = type('obj', (object,), {
                    'name': tool_call.function.name,
                    'arguments': tool_call.function.arguments
                })()
                result = self.handle_function_call(function_call)
                
                # Add tool call and result to conversation
                messages.append(message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": json.dumps(result)
                })
            
            # Get ChatGPT's response to the validation result
            tools = [AGENTTRUST_FUNCTION_DEFINITION]
            if self.browser_executor.browser:
                tools.extend([
                    {
                        "type": "function",
                        "function": {
                            "name": "get_page_content",
                            "description": "Get the current page content",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "include_html": {"type": "boolean"}
                                }
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "get_visible_elements",
                            "description": "Get visible interactive elements",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "element_type": {"type": "string"}
                                }
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "get_current_url",
                            "description": "Get current page URL",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    }
                ])
            
            response = self.openai.chat.completions.create(
                model="gpt-4",
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            message = response.choices[0].message
        
        # Regular text response
        response_text = message.content
        print(f"🤖 ChatGPT: {response_text}\n")
        
        # Update conversation history
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": response_text})
        
        return response_text
    
    def handle_function_call(self, function_call):
        """
        Handle all function calls from ChatGPT
        
        CRITICAL: Browser actions MUST go through AgentTrust validation.
        Page content functions are read-only and don't need validation.
        """
        function_name = function_call.name
        
        # Handle page content functions (read-only, no validation needed)
        if function_name == "get_page_content":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            content = self.browser_executor.get_page_content(
                include_html=args.get("include_html", False)
            )
            print(f"📄 Page content retrieved: {content.get('title', 'N/A')}")
            return content
        
        elif function_name == "get_visible_elements":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            elements = self.browser_executor.get_visible_elements(
                element_type=args.get("element_type")
            )
            print(f"🔍 Found {len(elements)} visible elements")
            return {"elements": elements, "count": len(elements)}
        
        elif function_name == "get_current_url":
            url = self.browser_executor.get_current_url()
            print(f"🌐 Current URL: {url}")
            return {"url": url}
        
        # Handle browser action function (requires AgentTrust validation)
        elif function_name == "agenttrust_browser_action":
            return self.handle_agenttrust_function(function_call)
        
        else:
            return {"error": f"Unknown function: {function_name}"}
    
    def handle_agenttrust_function(self, function_call):
        """
        Handle AgentTrust function calls from ChatGPT
        
        CRITICAL: This is the ONLY entry point for browser actions.
        All actions MUST go through AgentTrust validation via the BrowserActionExecutor.
        There is no way to bypass this.
        """
        
        # Parse arguments
        args = json.loads(function_call.arguments)
        action_type = args.get("action_type")
        url = args.get("url")
        target = args.get("target")
        form_data = args.get("form_data")
        
        print(f"🔍 ChatGPT wants to: {action_type} on {url}")
        if target:
            print(f"   Target: {target.get('text', target.get('id', 'N/A'))}")
        
        # MANDATORY: Use BrowserActionExecutor - this enforces 100% AgentTrust validation
        try:
            if action_type == "click":
                result = self.browser_executor.execute_click(url=url, target=target)
                print(f"   ✅ AgentTrust: ALLOWED (Risk: {result.get('risk_level', 'unknown')})")
                self.actions_performed.append({
                    "type": action_type,
                    "url": url,
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                })
                return {
                    "status": "allowed",
                    "message": f"Action allowed by AgentTrust. Risk level: {result.get('risk_level')}",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                }
            
            elif action_type == "form_submit":
                result = self.browser_executor.execute_form_submit(url=url, form_data=form_data)
                print(f"   ✅ AgentTrust: ALLOWED (Risk: {result.get('risk_level', 'unknown')})")
                self.actions_performed.append({
                    "type": action_type,
                    "url": url,
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                })
                return {
                    "status": "allowed",
                    "message": f"Action allowed by AgentTrust. Risk level: {result.get('risk_level')}",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                }
            
            elif action_type == "navigation":
                result = self.browser_executor.execute_navigation(url=url)
                print(f"   ✅ AgentTrust: ALLOWED (Risk: {result.get('risk_level', 'unknown')})")
                self.actions_performed.append({
                    "type": action_type,
                    "url": url,
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                })
                return {
                    "status": "allowed",
                    "message": f"Action allowed by AgentTrust. Risk level: {result.get('risk_level')}",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                }
            
            else:
                return {
                    "status": "error",
                    "message": f"Unknown action type: {action_type}"
                }
        
        except PermissionError as e:
            # AgentTrust denied or requires step-up
            error_msg = str(e)
            
            if "STEP-UP REQUIRED" in error_msg:
                print(f"   ⚠️  AgentTrust: STEP-UP REQUIRED")
                self.actions_blocked.append({
                    "type": action_type,
                    "url": url,
                    "reason": "Step-up required"
                })
                return {
                    "status": "step_up_required",
                    "message": error_msg,
                    "requires_user_approval": True
                }
            else:
                # Denied
                print(f"   ❌ AgentTrust: DENIED")
                self.actions_blocked.append({
                    "type": action_type,
                    "url": url,
                    "reason": error_msg
                })
                return {
                    "status": "denied",
                    "message": error_msg,
                    "reason": "Policy violation"
                }
        
        except Exception as e:
            # Any other error - fail safe
            print(f"   ❌ AgentTrust validation error: {e}")
            return {
                "status": "error",
                "message": f"AgentTrust validation failed: {str(e)}"
            }
    
    def print_summary(self):
        """Print conversation summary"""
        print("\n" + "="*70)
        print("CONVERSATION SUMMARY")
        print("="*70)
        print(f"Actions Performed: {len(self.actions_performed)}")
        print(f"Actions Blocked: {len(self.actions_blocked)}")
        
        if self.actions_performed:
            print("\n✅ Actions ChatGPT Performed (with AgentTrust approval):")
            for action in self.actions_performed:
                print(f"  - {action['type']} on {action['url']} (Risk: {action['risk_level']})")
        
        if self.actions_blocked:
            print("\n❌ Actions Blocked by AgentTrust:")
            for action in self.actions_blocked:
                print(f"  - {action['type']} on {action['url']}: {action['reason']}")
        print("="*70)


def main():
    """
    Run real ChatGPT agent with AgentTrust - 100% enforcement
    
    CRITICAL: AgentTrust validation is MANDATORY for all browser actions.
    The BrowserActionExecutor enforces this - there is no way to bypass it.
    """
    print("="*70)
    print("ChatGPT Agent with AgentTrust - 100% Enforcement")
    print("="*70)
    print("\nThis is a REAL AI agent (ChatGPT) using AgentTrust to govern")
    print("browser actions. ChatGPT makes decisions, AgentTrust controls execution.")
    print("\n🔒 ENFORCEMENT: All browser actions MUST go through AgentTrust validation.")
    print("   There is no way to bypass AgentTrust - it's enforced at the execution level.")
    print("\n👁️  BROWSER AUTOMATION: ChatGPT can see page content and interact with the browser.")
    print("   - get_page_content: See what's on the page (read-only)")
    print("   - get_visible_elements: See buttons, links, inputs (read-only)")
    print("   - agenttrust_browser_action: Perform actions (requires validation)")
    print()
    
    # Enable browser automation by default
    enable_browser = os.getenv("ENABLE_BROWSER", "true").lower() == "true"
    headless = os.getenv("HEADLESS_BROWSER", "false").lower() == "true"
    
    agent = ChatGPTAgentWithAgentTrust(enable_browser=enable_browser, headless=headless)
    
    try:
        # Example conversation
        print("Example conversation:\n")
        
        # User request
        agent.chat("I want to navigate to GitHub and view my repositories")
        
        # ChatGPT will:
        # 1. Decide to navigate to GitHub
        # 2. Call agenttrust_browser_action for navigation
        # 3. AgentTrust validates (should be allowed)
        # 4. ChatGPT reports success
        
        # Another request
        agent.chat("Now I want to delete my test repository")
        
        # ChatGPT will:
        # 1. Decide to click delete button
        # 2. Call agenttrust_browser_action for delete click
        # 3. AgentTrust detects high-risk (should require step-up)
        # 4. ChatGPT asks for approval
        
        # Interactive mode
        print("\n" + "="*70)
        print("Interactive Mode")
        print("="*70)
        print("Type your requests. ChatGPT will use AgentTrust for browser actions.")
        print("Type 'quit' to exit.\n")
        
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            
            if user_input:
                agent.chat(user_input)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        agent.print_summary()
        
        # Close browser if it was opened
        if agent.browser_executor.browser:
            try:
                agent.browser_executor.browser.close()
                print("\n✅ Browser closed")
            except Exception as e:
                print(f"\n⚠️  Error closing browser: {e}")
        
        # Query audit log
        print("\n" + "-"*70)
        print("AUDIT LOG")
        print("-"*70)
        try:
            audit_log = agent.agenttrust.get_audit_log(limit=10)
            actions = audit_log.get('actions', [])
            print(f"Total actions logged: {len(actions)}")
            for action in actions[:5]:
                print(f"  - {action.get('type')} on {action.get('domain')} at {action.get('timestamp', 'N/A')}")
        except Exception as e:
            print(f"Note: {e}")


if __name__ == "__main__":
    main()
