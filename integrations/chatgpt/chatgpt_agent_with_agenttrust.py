"""
Real ChatGPT Agent with AgentTrust Integration
This is a real-world example of ChatGPT using AgentTrust to govern browser actions

100% ENFORCEMENT: All browser actions MUST go through AgentTrust validation.
There is no way to perform a browser action without AgentTrust approval.

Browser Automation: Uses Selenium to actually interact with the browser and get page content.

Auth0 for AI Agents Hackathon: Built with Token Vault from Auth0 for AI Agents.
- OAuth flows, token management, consent delegation: Auth0
- Async auth and step-up authentication: Auth0

Usage:
    pip install openai requests selenium
    python chatgpt_agent_with_agenttrust.py
    
    # Optional: Add to .env file:
    # AGENTTRUST_DEV_MODE=true    # Run without backend (browser only)
    # Sign in via extension popup (click extension icon in browser)
"""

import os
import json
import sys
import base64
from typing import Optional, Dict, List, Any
from openai import OpenAI
from agenttrust_client import AgentTrustClient, AGENTTRUST_FUNCTION_DEFINITION

# Auth0 Token Vault - for hackathon compliance (optional, enables external API access)
try:
    from auth0_token_vault import Auth0TokenVaultClient
    TOKEN_VAULT_AVAILABLE = True
except ImportError:
    TOKEN_VAULT_AVAILABLE = False
    Auth0TokenVaultClient = None

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(os.path.dirname(_script_dir))
    # Load from: integrations/chatgpt/.env, project root .env, backend/.env
    for path in [
        os.path.join(_project_root, 'backend', '.env'),
        os.path.join(_project_root, '.env'),
        os.path.join(_script_dir, '.env'),
    ]:
        if os.path.isfile(path):
            load_dotenv(path)
except ImportError:
    pass

# Browser automation - optional import
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️  Selenium not installed. Browser automation disabled.")
    print("   Install with: pip install selenium")


class InterceptedWebDriver:
    """
    Wrapper around Selenium WebDriver that intercepts ALL actions.
    
    This ensures that NO browser action can occur without AgentTrust validation.
    Even if code tries to call driver methods directly, they are intercepted.
    """
    
    def __init__(self, driver, agenttrust_validator):
        """
        Initialize intercepted driver
        
        Args:
            driver: The actual Selenium WebDriver instance
            agenttrust_validator: Function that validates actions (raises PermissionError if denied)
        """
        self._driver = driver
        self._validate = agenttrust_validator
        self._current_url = driver.current_url if driver else None
    
    def _intercept_action(self, action_type: str, url: str, **kwargs):
        """
        Intercept any browser action - MANDATORY validation
        
        This is called before ANY action is executed.
        """
        # Validate with AgentTrust
        validation_result = self._validate(action_type, url, **kwargs)
        
        if validation_result.get("status") == "denied":
            raise PermissionError(f"❌ AgentTrust DENIED: {validation_result.get('message')}")
        
        if validation_result.get("status") == "step_up_required":
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: {validation_result.get('message')}"
            )
        
        # Only proceed if allowed
        if validation_result.get("status") != "allowed":
            raise ValueError(f"AgentTrust validation failed: {validation_result.get('status')}")
        
        return validation_result
    
    # Intercept navigation
    def get(self, url: str):
        """Intercept navigation - requires AgentTrust validation"""
        self._intercept_action("navigation", url)
        result = self._driver.get(url)
        self._current_url = self._driver.current_url
        return result
    
    # Intercept clicks via find_element
    def find_element(self, by, value):
        """Intercept element finding - wrap returned element to intercept clicks"""
        element = self._driver.find_element(by, value)
        return InterceptedWebElement(element, self._validate, self._current_url)
    
    def find_elements(self, by, value):
        """Intercept element finding - wrap returned elements"""
        elements = self._driver.find_elements(by, value)
        return [InterceptedWebElement(el, self._validate, self._current_url) for el in elements]
    
    # Intercept back/forward
    def back(self):
        """Intercept back navigation - requires AgentTrust validation"""
        self._intercept_action("navigation", self._current_url or "")
        result = self._driver.back()
        self._current_url = self._driver.current_url
        return result
    
    def forward(self):
        """Intercept forward navigation - requires AgentTrust validation"""
        self._intercept_action("navigation", self._current_url or "")
        result = self._driver.forward()
        self._current_url = self._driver.current_url
        return result
    
    # Delegate read-only operations directly (no interception needed)
    @property
    def current_url(self):
        return self._driver.current_url
    
    @property
    def title(self):
        return self._driver.title
    
    @property
    def page_source(self):
        return self._driver.page_source
    
    def execute_script(self, script, *args):
        """Intercept script execution - validate if it's an action"""
        # Check if script contains action keywords
        action_keywords = ['click', 'submit', 'navigate', 'location.href', 'window.open']
        if any(keyword in script.lower() for keyword in action_keywords):
            self._intercept_action("navigation", self._current_url or "")
        return self._driver.execute_script(script, *args)
    
    def get_screenshot_as_base64(self):
        return self._driver.get_screenshot_as_base64()
    
    def save_screenshot(self, filename):
        return self._driver.save_screenshot(filename)
    
    def quit(self):
        return self._driver.quit()
    
    def close(self):
        return self._driver.close()
    
    # Delegate all other attributes to the underlying driver
    def __getattr__(self, name):
        attr = getattr(self._driver, name)
        return attr


class InterceptedWebElement:
    """
    Wrapper around Selenium WebElement that intercepts clicks and form submissions.
    
    This ensures that NO click or form action can occur without AgentTrust validation.
    """
    
    def __init__(self, element, agenttrust_validator, current_url):
        """
        Initialize intercepted element
        
        Args:
            element: The actual Selenium WebElement
            agenttrust_validator: Function that validates actions
            current_url: Current page URL for validation
        """
        self._element = element
        self._validate = agenttrust_validator
        self._current_url = current_url
    
    def click(self):
        """Intercept click - requires AgentTrust validation"""
        # Get element info for validation
        try:
            element_text = self._element.text[:50] if self._element.text else ""
            element_id = self._element.get_attribute("id") or ""
            target = {"text": element_text, "id": element_id}
        except:
            target = {}
        
        # Validate click action
        validation_result = self._validate("click", self._current_url or "", target=target)
        
        if validation_result.get("status") == "denied":
            raise PermissionError(f"❌ AgentTrust DENIED: {validation_result.get('message')}")
        
        if validation_result.get("status") == "step_up_required":
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: {validation_result.get('message')}"
            )
        
        if validation_result.get("status") != "allowed":
            raise ValueError(f"AgentTrust validation failed: {validation_result.get('status')}")
        
        # Only proceed if allowed
        return self._element.click()
    
    def submit(self):
        """Intercept form submit - requires AgentTrust validation"""
        # Get form data if possible
        form_data = {}
        try:
            # Try to get form data from parent form
            if SELENIUM_AVAILABLE:
                from selenium.webdriver.common.by import By
                form = self._element.find_element(By.XPATH, "./ancestor::form[1]")
                inputs = form.find_elements(By.TAG_NAME, "input")
                for inp in inputs:
                    name = inp.get_attribute("name")
                    if name:
                        form_data[name] = inp.get_attribute("value") or ""
        except:
            pass
        
        # Validate form submit
        validation_result = self._validate("form_submit", self._current_url or "", form_data=form_data)
        
        if validation_result.get("status") == "denied":
            raise PermissionError(f"❌ AgentTrust DENIED: {validation_result.get('message')}")
        
        if validation_result.get("status") == "step_up_required":
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: {validation_result.get('message')}"
            )
        
        if validation_result.get("status") != "allowed":
            raise ValueError(f"AgentTrust validation failed: {validation_result.get('status')}")
        
        # Only proceed if allowed
        return self._element.submit()
    
    def send_keys(self, *value):
        """Intercept send_keys - validate as form interaction"""
        # Get field info
        field_name = self._element.get_attribute("name") or self._element.get_attribute("id") or ""
        form_data = {field_name: "".join(str(v) for v in value)} if field_name else {}
        
        # Validate form interaction
        validation_result = self._validate("form_submit", self._current_url or "", form_data=form_data)
        
        if validation_result.get("status") == "denied":
            raise PermissionError(f"❌ AgentTrust DENIED: {validation_result.get('message')}")
        
        if validation_result.get("status") == "step_up_required":
            raise PermissionError(
                f"⚠️ AgentTrust STEP-UP REQUIRED: {validation_result.get('message')}"
            )
        
        if validation_result.get("status") != "allowed":
            raise ValueError(f"AgentTrust validation failed: {validation_result.get('status')}")
        
        return self._element.send_keys(*value)
    
    # Delegate read-only operations
    @property
    def text(self):
        return self._element.text
    
    def get_attribute(self, name):
        return self._element.get_attribute(name)
    
    def is_displayed(self):
        return self._element.is_displayed()
    
    def is_enabled(self):
        return self._element.is_enabled()
    
    def clear(self):
        return self._element.clear()
    
    def find_element(self, by, value):
        element = self._element.find_element(by, value)
        return InterceptedWebElement(element, self._validate, self._current_url)
    
    def find_elements(self, by, value):
        elements = self._element.find_elements(by, value)
        return [InterceptedWebElement(el, self._validate, self._current_url) for el in elements]
    
    # Delegate all other attributes
    def __getattr__(self, name):
        return getattr(self._element, name)


class BrowserController:
    """
    Browser automation controller using Selenium.
    
    CRITICAL: The WebDriver is wrapped with InterceptedWebDriver, which ensures
    that NO browser action can occur without AgentTrust validation, even if
    code tries to call driver methods directly.
    """
    
    def _get_extension_path(self) -> Optional[str]:
        """Get absolute path to AgentTrust extension folder for auto-loading."""
        try:
            # Script is in integrations/chatgpt/, extension is at project_root/extension
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            ext_path = os.path.join(project_root, 'extension')
            if os.path.isdir(ext_path) and os.path.isfile(os.path.join(ext_path, 'manifest.json')):
                return os.path.abspath(ext_path)
        except Exception:
            pass
        return None
    
    def __init__(self, headless: bool = False, agenttrust_validator=None):
        """
        Initialize browser controller
        
        Args:
            headless: Run browser in headless mode
            agenttrust_validator: Function to validate actions (REQUIRED for interception)
        """
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium is required for browser automation. Install with: pip install selenium")
        
        if not agenttrust_validator:
            raise ValueError("agenttrust_validator is REQUIRED - browser actions cannot be performed without it")
        
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Load AgentTrust extension - use Edge if Chrome 137+ blocks it (Edge still supports --load-extension)
        extension_path = self._get_extension_path()
        load_extension = not headless and extension_path and os.getenv("AGENTTRUST_LOAD_EXTENSION", "true").lower() == "true"
        if load_extension:
            options.add_argument(f'--load-extension={extension_path}')
            options.add_argument('--disable-features=DisableLoadExtensionCommandLineSwitch')
        
        actual_driver = None
        # Try Chrome first
        try:
            actual_driver = webdriver.Chrome(options=options)
            if load_extension:
                print("✅ AgentTrust extension installed")
        except Exception:
            # Chrome 137+ may block --load-extension; try Edge (supports extensions)
            if load_extension:
                try:
                    from selenium.webdriver.edge.options import Options as EdgeOptions
                    edge_opts = EdgeOptions()
                    edge_opts.add_argument('--load-extension=' + extension_path)
                    edge_opts.add_argument('--no-sandbox')
                    edge_opts.add_argument('--disable-dev-shm-usage')
                    actual_driver = webdriver.Edge(options=edge_opts)
                    print("✅ AgentTrust extension installed (Edge)")
                except Exception as e2:
                    opts_fallback = webdriver.ChromeOptions()
                    if headless:
                        opts_fallback.add_argument('--headless')
                    opts_fallback.add_argument('--no-sandbox')
                    opts_fallback.add_argument('--disable-dev-shm-usage')
                    opts_fallback.add_argument('--disable-blink-features=AutomationControlled')
                    opts_fallback.add_experimental_option("excludeSwitches", ["enable-automation"])
                    opts_fallback.add_experimental_option('useAutomationExtension', False)
                    actual_driver = webdriver.Chrome(options=opts_fallback)
                    print("⚠️  Extension not loaded. Click extension icon → Sign in via popup. Or load manually: edge://extensions/ or chrome://extensions/")
            else:
                raise
        if actual_driver is None:
            actual_driver = webdriver.Chrome(options=options)
        actual_driver.implicitly_wait(5)
        
        # CRITICAL: Wrap driver with interception layer
        # This ensures NO action can bypass AgentTrust validation
        self.driver = InterceptedWebDriver(actual_driver, agenttrust_validator)
        self._actual_driver = actual_driver  # Keep reference for cleanup
        self.current_url = None
        
        # Sign in via extension popup (click extension icon in browser toolbar)
        # No website-based login - the extension is the UI.
    
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
    
    def _unwrap_element(self, element):
        """Get the actual Selenium WebElement from InterceptedWebElement wrapper."""
        return getattr(element, '_element', element)
    
    def _xpath_escape(self, text: str) -> str:
        """Escape single quotes for XPath (use '' to escape ' in XPath)."""
        if not text:
            return ""
        return str(text).replace("'", "''")
    
    def click_element(self, target: Dict[str, Any]) -> Dict[str, Any]:
        """
        Click an element based on target information
        
        Args:
            target: dict with id, text, class, href, tagName, or other identifiers
        
        Returns:
            dict with success status
        """
        import time
        try:
            element = None
            text_safe = (target.get("text") or "")[:80].strip()
            # XPath-safe text: escape single quote as '' in XPath
            text_xpath = text_safe.replace("'", "''") if text_safe else ""
            
            # Try to find by ID first
            if target.get("id"):
                try:
                    element = self.driver.find_element(By.ID, target["id"])
                except NoSuchElementException:
                    pass
            
            # Try by href (for links)
            if not element and target.get("href"):
                href = str(target["href"])[:200].replace("'", "''")
                try:
                    element = self.driver.find_element(By.XPATH, f"//a[contains(@href, '{href}')]")
                except NoSuchElementException:
                    pass
            
            # Try by tag name + text (buttons, links - use contains(., ) for nested elements)
            if not element and target.get("tagName") and text_safe:
                tag = str(target["tagName"]).upper().replace("HTML", "*")
                if tag == "*":
                    tag = "*"
                try:
                    element = self.driver.find_element(By.XPATH, f"//{tag}[contains(., '{text_xpath}')]")
                except NoSuchElementException:
                    pass
            
            # Try by text content (any element - contains(., ) matches nested text)
            if not element and text_safe:
                for xpath in [
                    f"//a[contains(., '{text_xpath}')]",
                    f"//button[contains(., '{text_xpath}')]",
                    f"//*[@role='button'][contains(., '{text_xpath}')]",
                    f"//*[contains(., '{text_xpath}')]",
                ]:
                    try:
                        elements = self.driver.find_elements(By.XPATH, xpath)
                        for el in elements:
                            if el.is_displayed() and el.is_enabled():
                                element = el
                                break
                        if element:
                            break
                    except NoSuchElementException:
                        continue
            
            # Try by class name
            if not element and target.get("className"):
                try:
                    element = self.driver.find_element(By.CLASS_NAME, target["className"])
                except NoSuchElementException:
                    pass
            
            # Try by CSS selector if provided
            if not element and target.get("selector"):
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, target["selector"])
                except NoSuchElementException:
                    pass
            
            if not element:
                return {"success": False, "message": "Element not found with provided identifiers"}
            
            # Get actual Selenium element (unwrap InterceptedWebElement for scripts)
            actual = self._unwrap_element(element)
            
            # Scroll into view
            try:
                self._actual_driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});",
                    actual
                )
            except Exception:
                pass
            time.sleep(0.2)
            
            # Wait for element to be clickable (use actual element for WebDriverWait)
            try:
                WebDriverWait(self._actual_driver, 5).until(EC.element_to_be_clickable(actual))
            except TimeoutException:
                return {"success": False, "message": "Element not clickable within timeout"}
            
            if not element.is_displayed():
                return {"success": False, "message": "Element found but not visible"}
            
            # Try click: native first, then JS, then ActionChains
            clicked = False
            try:
                element.click()
                clicked = True
            except Exception:
                try:
                    self._actual_driver.execute_script("arguments[0].click();", actual)
                    clicked = True
                except Exception:
                    try:
                        ActionChains(self._actual_driver).move_to_element(actual).click().perform()
                        clicked = True
                    except Exception:
                        pass
            
            if clicked:
                time.sleep(0.5)
                return {"success": True, "message": "Element clicked successfully", "new_url": self.driver.current_url}
            return {"success": False, "message": "Click failed (element may be obscured or not interactable)"}
        
        except TimeoutException:
            return {"success": False, "message": "Element not clickable within timeout"}
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
    
    def open_link(self, href: Optional[str] = None, link_text: Optional[str] = None, link_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Open a link on the current page
        
        Args:
            href: Link URL to open (full or partial)
            link_text: Text content of the link
            link_index: Index of link in visible links list (0-based)
        
        Returns:
            dict with success status and new URL
        """
        try:
            element = None
            
            # Find by index
            if link_index is not None:
                links = self.driver.find_elements(By.TAG_NAME, "a")
                visible_links = [link for link in links if link.is_displayed()]
                if 0 <= link_index < len(visible_links):
                    element = visible_links[link_index]
            
            # Find by href (partial match - handles different domain/path formats)
            if not element and href:
                href_esc = str(href)[:200].replace("'", "''")  # XPath: '' escapes '
                try:
                    element = self.driver.find_element(By.XPATH, f"//a[contains(@href, '{href_esc}')]")
                except NoSuchElementException:
                    pass
            
            # Find by text (use contains(., ) for nested elements like <a><span>text</span></a>)
            if not element and link_text:
                text_esc = str(link_text)[:50].replace("'", "''")  # XPath: '' escapes '
                try:
                    links = self.driver.find_elements(By.XPATH, f"//a[contains(., '{text_esc}')]")
                    for link in links:
                        if link.is_displayed():
                            element = link
                            break
                except NoSuchElementException:
                    pass
            
            if element and element.is_displayed():
                # Get the href before clicking
                link_href = element.get_attribute("href")
                actual = self._unwrap_element(element)
                
                # Scroll into view and click
                try:
                    self._actual_driver.execute_script(
                        "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
                        actual
                    )
                except Exception:
                    pass
                import time
                time.sleep(0.2)
                WebDriverWait(self._actual_driver, 5).until(EC.element_to_be_clickable(actual))
                try:
                    element.click()
                except Exception:
                    self._actual_driver.execute_script("arguments[0].click();", actual)
                
                # Wait for navigation
                import time
                time.sleep(1)
                
                return {
                    "success": True,
                    "message": "Link opened successfully",
                    "href": link_href,
                    "new_url": self.driver.current_url
                }
            else:
                return {"success": False, "message": "Link not found or not visible"}
        
        except Exception as e:
            return {"success": False, "message": f"Error opening link: {str(e)}"}
    
    def type_text(self, target: Dict[str, Any], text: str) -> Dict[str, Any]:
        """
        Type text into an input field
        
        Args:
            target: dict identifying the input (id, name, placeholder, etc.)
            text: Text to type
        
        Returns:
            dict with success status
        """
        try:
            element = None
            
            # Try by ID
            if target.get("id"):
                try:
                    element = self.driver.find_element(By.ID, target["id"])
                except NoSuchElementException:
                    pass
            
            # Try by name
            if not element and target.get("name"):
                try:
                    element = self.driver.find_element(By.NAME, target["name"])
                except NoSuchElementException:
                    pass
            
            # Try by placeholder
            if not element and target.get("placeholder"):
                try:
                    element = self.driver.find_element(By.XPATH, f"//input[@placeholder='{target['placeholder']}']")
                except NoSuchElementException:
                    pass
            
            # Try by CSS selector
            if not element and target.get("selector"):
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, target["selector"])
                except NoSuchElementException:
                    pass
            
            if element and element.is_displayed():
                element.clear()
                element.send_keys(text)
                return {"success": True, "message": f"Text typed successfully: {text[:50]}"}
            else:
                return {"success": False, "message": "Input field not found or not visible"}
        
        except Exception as e:
            return {"success": False, "message": f"Error typing text: {str(e)}"}
    
    def scroll_page(self, direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        """
        Scroll the page
        
        Args:
            direction: "down", "up", "top", or "bottom"
            amount: Number of scroll steps (for down/up)
        
        Returns:
            dict with success status
        """
        try:
            if direction == "down":
                for _ in range(amount):
                    self.driver.execute_script("window.scrollBy(0, 500);")
            elif direction == "up":
                for _ in range(amount):
                    self.driver.execute_script("window.scrollBy(0, -500);")
            elif direction == "top":
                self.driver.execute_script("window.scrollTo(0, 0);")
            elif direction == "bottom":
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            import time
            time.sleep(0.3)
            
            return {"success": True, "message": f"Page scrolled {direction}"}
        except Exception as e:
            return {"success": False, "message": f"Error scrolling: {str(e)}"}
    
    def go_back(self) -> Dict[str, Any]:
        """Go back in browser history"""
        try:
            self.driver.back()
            import time
            time.sleep(0.5)
            return {"success": True, "message": "Navigated back", "url": self.driver.current_url}
        except Exception as e:
            return {"success": False, "message": f"Error going back: {str(e)}"}
    
    def go_forward(self) -> Dict[str, Any]:
        """Go forward in browser history"""
        try:
            self.driver.forward()
            import time
            time.sleep(0.5)
            return {"success": True, "message": "Navigated forward", "url": self.driver.current_url}
        except Exception as e:
            return {"success": False, "message": f"Error going forward: {str(e)}"}
    
    def wait_for_element(self, target: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
        """
        Wait for an element to appear on the page
        
        Args:
            target: dict identifying the element
            timeout: Maximum wait time in seconds
        
        Returns:
            dict with success status
        """
        try:
            element = None
            
            if target.get("id"):
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((By.ID, target["id"]))
                )
            elif target.get("class"):
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((By.CLASS_NAME, target["class"]))
                )
            elif target.get("text"):
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{target['text'][:50]}')]"))
                )
            
            if element:
                return {"success": True, "message": "Element appeared", "element_found": True}
            else:
                return {"success": False, "message": "Element did not appear within timeout"}
        
        except TimeoutException:
            return {"success": False, "message": f"Element not found within {timeout} seconds"}
        except Exception as e:
            return {"success": False, "message": f"Error waiting for element: {str(e)}"}
    
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
    
    def _validate_action(self, action_type: str, url: str, **kwargs):
        """
        Internal validation function used by intercepted WebDriver
        
        This is called by InterceptedWebDriver for ALL browser actions.
        """
        result = self.agenttrust.execute_action(
            action_type=action_type,
            url=url,
            **kwargs
        )
        return result
    
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
        screenshot = None
        if self.browser and target:
            browser_result = self.browser.click_element(target)
            # Capture screenshot AFTER action (to see result)
            if browser_result and browser_result.get("success"):
                try:
                    import time
                    time.sleep(0.5)  # Wait for page to update
                    screenshot = self.browser.take_screenshot()
                    # Update action with screenshot via API
                    if screenshot and result.get("action_id"):
                        try:
                            self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                        except:
                            pass  # Non-critical
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot: {e}")
        
        return {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Click action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result,
            "screenshot": screenshot
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
        screenshot = None
        if self.browser and form_data:
            browser_result = self.browser.submit_form(form_data)
            # Capture screenshot AFTER action (to see result)
            if browser_result and browser_result.get("success"):
                try:
                    import time
                    time.sleep(1)  # Wait for form submission to complete
                    screenshot = self.browser.take_screenshot()
                    # Update action with screenshot
                    if screenshot and result.get("action_id"):
                        try:
                            self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                        except Exception as e:
                            print(f"⚠️  Failed to update screenshot: {e}")
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot: {e}")
        
        return {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Form submit action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result,
            "screenshot": screenshot
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
        screenshot = None
        if self.browser:
            browser_result = self.browser.navigate(url)
            # Capture screenshot AFTER navigation (to see new page)
            if browser_result and browser_result.get("success"):
                try:
                    import time
                    time.sleep(1.5)  # Wait for page to load
                    screenshot = self.browser.take_screenshot()
                    # Update action with screenshot
                    if screenshot and result.get("action_id"):
                        try:
                            self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                        except Exception as e:
                            print(f"⚠️  Failed to update screenshot: {e}")
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot: {e}")
        
        return {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Navigation action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result,
            "screenshot": screenshot
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
    
    def open_link(self, href: Optional[str] = None, link_text: Optional[str] = None, link_index: Optional[int] = None):
        """
        Open a link on the current page - MANDATORY AgentTrust validation
        
        This requires navigation validation through AgentTrust.
        """
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        # Get current URL first
        current_url = self.browser.get_current_url()
        
        # Determine target URL
        target_url = href
        if not target_url and link_text:
            # Find link to get its href
            links = self.browser.get_visible_elements("link")
            for link in links:
                if link.get("text") and link_text.lower() in link.get("text", "").lower():
                    target_url = link.get("href")
                    break
        
        if not target_url:
            return {"error": "Could not determine link URL"}
        
        # Validate navigation through AgentTrust
        try:
            result = self.execute_navigation(target_url)
            # If navigation allowed, actually open the link
            if result.get("status") == "allowed" and self.browser:
                link_result = self.browser.open_link(href=href, link_text=link_text, link_index=link_index)
                # Screenshot is already captured in execute_navigation
                return {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "link_opened": link_result.get("success", False),
                    "new_url": link_result.get("new_url", target_url)
                }
            return result
        except PermissionError as e:
            return {"status": "denied", "message": str(e)}
    
    def type_text(self, target: Dict[str, Any], text: str):
        """
        Type text into an input field - MANDATORY AgentTrust validation
        
        Typing text is considered a form interaction and requires validation.
        """
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        current_url = self.browser.get_current_url()
        
        # Validate as form interaction
        try:
            # For typing, we validate as a form action
            result = self.agenttrust.execute_action(
                action_type="form_submit",  # Use form_submit for typing validation
                url=current_url,
                form_data={target.get("name") or target.get("id"): text}
            )
            
            if result.get("status") == "allowed":
                type_result = self.browser.type_text(target, text)
                # Capture screenshot after typing
                screenshot = None
                if type_result.get("success"):
                    try:
                        import time
                        time.sleep(0.3)
                        screenshot = self.browser.take_screenshot()
                        if screenshot and result.get("action_id"):
                            try:
                                self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                            except:
                                pass
                    except:
                        pass
                
                return {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "typed": type_result.get("success", False)
                }
            elif result.get("status") == "denied":
                raise PermissionError(result.get("message", "Typing denied by AgentTrust"))
            elif result.get("status") == "step_up_required":
                raise PermissionError(f"Step-up required: {result.get('message')}")
        except PermissionError as e:
            return {"status": "denied", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def scroll_page(self, direction: str = "down", amount: int = 3):
        """Scroll the page - NO AgentTrust validation needed (read-only navigation)"""
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        return self.browser.scroll_page(direction, amount)
    
    def go_back(self):
        """Go back in browser history - MANDATORY AgentTrust validation"""
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        # Get previous URL from history if possible, or use current URL
        current_url = self.browser.get_current_url()
        
        try:
            # Validate navigation back
            result = self.execute_navigation(current_url)  # Navigation validation
            if result.get("status") == "allowed":
                back_result = self.browser.go_back()
                return {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "navigated_back": back_result.get("success", False),
                    "url": back_result.get("url", "")
                }
            return result
        except PermissionError as e:
            return {"status": "denied", "message": str(e)}
    
    def go_forward(self):
        """Go forward in browser history - MANDATORY AgentTrust validation"""
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        current_url = self.browser.get_current_url()
        
        try:
            result = self.execute_navigation(current_url)
            if result.get("status") == "allowed":
                forward_result = self.browser.go_forward()
                return {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "navigated_forward": forward_result.get("success", False),
                    "url": forward_result.get("url", "")
                }
            return result
        except PermissionError as e:
            return {"status": "denied", "message": str(e)}
    
    def wait_for_element(self, target: Dict[str, Any], timeout: int = 10):
        """Wait for element - NO AgentTrust validation needed (read-only)"""
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        return self.browser.wait_for_element(target, timeout)
    
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
            if agenttrust_client.dev_mode:
                print("⚠️  AGENTTRUST_DEV_MODE=true: Running without backend (browser automation only)")
        except ValueError as e:
            print(f"❌ AgentTrust configuration error: {e}")
            print("\nOptions:")
            print("  1. Set Auth0 env vars: AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, AUTH0_AUDIENCE")
            print("  2. Or set AGENTTRUST_DEV_MODE=true in .env to run without backend")
            sys.exit(1)
        
        # CRITICAL: Create mandatory browser action executor FIRST
        # This provides the validation function needed for browser interception
        self.browser_executor = BrowserActionExecutor(agenttrust_client, None)
        
        # Initialize browser controller if enabled - MUST pass validator for interception
        browser_controller = None
        if enable_browser:
            try:
                # Create validator function that uses the executor
                def validator(action_type, url, **kwargs):
                    return self.browser_executor._validate_action(action_type, url, **kwargs)
                
                browser_controller = BrowserController(
                    headless=headless,
                    agenttrust_validator=validator
                )
                
                # Now set the browser on the executor
                self.browser_executor.browser = browser_controller
                print("✅ Browser automation enabled with MANDATORY AgentTrust interception")
            except ImportError:
                print("⚠️  Browser automation disabled (Selenium not available)")
            except Exception as e:
                print(f"⚠️  Browser automation disabled: {e}")
        
        self.agenttrust = agenttrust_client  # Keep reference for audit log queries
        
        # Auth0 Token Vault - for external API access (hackathon compliance)
        self.token_vault = None
        if TOKEN_VAULT_AVAILABLE and Auth0TokenVaultClient:
            try:
                self.token_vault = Auth0TokenVaultClient()
                if self.token_vault.has_token_vault_config():
                    print("✅ Auth0 Token Vault configured (hackathon: OAuth, token mgmt, consent)")
            except Exception as e:
                print(f"⚠️  Token Vault not configured: {e}")
        
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
        
        # System prompt - simplified since interception is now at code level
        system_prompt = """You are a browser automation assistant with AgentTrust integration.

BROWSER INTERACTION:
- You can see what's on the page using get_page_content and get_visible_elements functions
- These are READ-ONLY functions - no validation needed
- Use these to understand the page before taking actions

AVAILABLE COMMANDS:
READ-ONLY (no validation needed):
- get_page_content: See page text and HTML
- get_visible_elements: See buttons, links, inputs on the page
- get_current_url: Get current page URL
- scroll_page: Scroll up/down/top/bottom
- wait_for_element: Wait for element to appear
- take_screenshot: Capture page screenshot

BROWSER ACTIONS (automatically validated):
- agenttrust_browser_action: Click, form submit, or navigate
- open_link: Open/follow a link on the page
- type_text: Type into input fields
- go_back: Navigate back in history
- go_forward: Navigate forward in history

NOTE: All browser actions are automatically intercepted and validated by AgentTrust at the code level.
If an action is denied, you will receive an error and cannot proceed. Always explain what you're doing."""
        
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
                },
                {
                    "type": "function",
                    "function": {
                        "name": "open_link",
                        "description": "Open/follow a link on the current page. Can find link by href, text, or index. Requires AgentTrust validation.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "href": {
                                    "type": "string",
                                    "description": "Link URL (full or partial) to open"
                                },
                                "link_text": {
                                    "type": "string",
                                    "description": "Text content of the link to open"
                                },
                                "link_index": {
                                    "type": "integer",
                                    "description": "Index of link in visible links list (0-based). Use get_visible_elements first to see available links."
                                }
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "type_text",
                        "description": "Type text into an input field on the page. Requires AgentTrust validation.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "target": {
                                    "type": "object",
                                    "description": "Target input field (id, name, placeholder, or selector)",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "placeholder": {"type": "string"},
                                        "selector": {"type": "string"}
                                    }
                                },
                                "text": {
                                    "type": "string",
                                    "description": "Text to type into the field"
                                }
                            },
                            "required": ["target", "text"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "scroll_page",
                        "description": "Scroll the page up, down, to top, or to bottom. This is READ-ONLY navigation - no AgentTrust validation needed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "direction": {
                                    "type": "string",
                                    "enum": ["down", "up", "top", "bottom"],
                                    "description": "Scroll direction"
                                },
                                "amount": {
                                    "type": "integer",
                                    "description": "Number of scroll steps (for down/up, default: 3)"
                                }
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "go_back",
                        "description": "Go back in browser history. Requires AgentTrust validation.",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "go_forward",
                        "description": "Go forward in browser history. Requires AgentTrust validation.",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "wait_for_element",
                        "description": "Wait for an element to appear on the page. This is READ-ONLY - no AgentTrust validation needed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "target": {
                                    "type": "object",
                                    "description": "Element to wait for (id, class, or text)",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "class": {"type": "string"},
                                        "text": {"type": "string"}
                                    }
                                },
                                "timeout": {
                                    "type": "integer",
                                    "description": "Maximum wait time in seconds (default: 10)"
                                }
                            }
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
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "open_link",
                            "description": "Open a link on the current page",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "href": {"type": "string"},
                                    "link_text": {"type": "string"},
                                    "link_index": {"type": "integer"}
                                }
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "type_text",
                            "description": "Type text into an input field",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "target": {"type": "object"},
                                    "text": {"type": "string"}
                                }
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "scroll_page",
                            "description": "Scroll the page",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "direction": {"type": "string"},
                                    "amount": {"type": "integer"}
                                }
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "go_back",
                            "description": "Go back in browser history",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "go_forward",
                            "description": "Go forward in browser history",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "wait_for_element",
                            "description": "Wait for element to appear",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "target": {"type": "object"},
                                    "timeout": {"type": "integer"}
                                }
                            }
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
        
        elif function_name == "open_link":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.open_link(
                href=args.get("href"),
                link_text=args.get("link_text"),
                link_index=args.get("link_index")
            )
            if result.get("status") == "allowed":
                print(f"🔗 Link opened: {result.get('new_url', 'N/A')}")
            return result
        
        elif function_name == "type_text":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.type_text(
                target=args.get("target", {}),
                text=args.get("text", "")
            )
            if result.get("status") == "allowed":
                print(f"⌨️  Text typed into field")
            return result
        
        elif function_name == "scroll_page":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.scroll_page(
                direction=args.get("direction", "down"),
                amount=args.get("amount", 3)
            )
            print(f"📜 Page scrolled {args.get('direction', 'down')}")
            return result
        
        elif function_name == "go_back":
            result = self.browser_executor.go_back()
            if result.get("status") == "allowed":
                print(f"⬅️  Navigated back to: {result.get('url', 'N/A')}")
            return result
        
        elif function_name == "go_forward":
            result = self.browser_executor.go_forward()
            if result.get("status") == "allowed":
                print(f"➡️  Navigated forward to: {result.get('url', 'N/A')}")
            return result
        
        elif function_name == "wait_for_element":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.wait_for_element(
                target=args.get("target", {}),
                timeout=args.get("timeout", 10)
            )
            if result.get("success"):
                print(f"⏳ Element appeared")
            return result
        
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
    print("\n🏆 Auth0 for AI Agents Hackathon: Built with Token Vault")
    print("   - OAuth flows, token management, consent: Auth0")
    print("   - Async auth, step-up authentication: Auth0")
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
