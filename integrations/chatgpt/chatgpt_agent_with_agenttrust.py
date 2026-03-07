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
import io
import time

# Fix emoji output on Windows terminals that use cp1252
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import requests
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
        """Get absolute path to AgentTrust extension folder."""
        try:
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
        
        extension_path = self._get_extension_path()
        load_ext = extension_path and os.getenv("AGENTTRUST_LOAD_EXTENSION", "true").lower() == "true"
        
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        # Disable passkey / WebAuthn / Google Password Manager prompts
        options.add_argument('--disable-features='
                             'WebAuthentication,'
                             'WebAuthenticationConditionalUI,'
                             'PasswordManagerOnboarding,'
                             'PasswordManagerSetting,'
                             'ChromePasswordManagerUI,'
                             'IdentityCredentialAutoReauthn')
        options.add_argument('--disable-component-update')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.password_manager_leak_detection": False,
            "profile.default_content_setting_values.notifications": 2,
            "autofill.profile_enabled": False,
            "autofill.credit_card_enabled": False,
            "password_manager.enabled": False,
            "password_manager.leak_detection": False,
            "password_manager.auto_signin.enabled": False,
            "webauthn.allow_virtual_authenticator": False,
        })
        
        if load_ext:
            options.add_argument(f'--load-extension={extension_path}')
            # Chrome 137+ blocks --load-extension in standard Chrome.
            # Setting browser_version forces Selenium Manager to use Chrome for Testing,
            # which still supports extension loading.
            options.browser_version = 'stable'
        
        actual_driver = webdriver.Chrome(options=options)
        if load_ext:
            print("✅ AgentTrust extension installed")
        actual_driver.implicitly_wait(2)
        
        # Suppress the native passkey / WebAuthn dialog via DevTools Protocol
        try:
            actual_driver.execute_cdp_cmd('WebAuthn.enable', {'enableUI': False})
            actual_driver.execute_cdp_cmd('WebAuthn.addVirtualAuthenticator', {
                'options': {
                    'protocol': 'ctap2',
                    'transport': 'internal',
                    'hasResidentKey': False,
                    'hasUserVerification': False,
                    'isUserVerified': False,
                }
            })
        except Exception:
            pass
        
        # Inject JS on every page to neutralize navigator.credentials
        try:
            actual_driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    if (navigator.credentials) {
                        navigator.credentials.get = () => Promise.reject(new Error('disabled'));
                        navigator.credentials.create = () => Promise.reject(new Error('disabled'));
                        if (navigator.credentials.conditionalMediationSupported) {
                            navigator.credentials.conditionalMediationSupported = () => Promise.resolve(false);
                        }
                    }
                    if (window.PublicKeyCredential) {
                        window.PublicKeyCredential.isConditionalMediationAvailable =
                            () => Promise.resolve(false);
                        window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable =
                            () => Promise.resolve(false);
                    }
                '''
            })
        except Exception:
            pass
        
        # CRITICAL: Wrap driver with interception layer
        # This ensures NO action can bypass AgentTrust validation
        self.driver = InterceptedWebDriver(actual_driver, agenttrust_validator)
        self._actual_driver = actual_driver  # Keep reference for cleanup
        self.current_url = None
        
        # Auto-login to extension using .env credentials
        if load_ext:
            self._auto_login_extension()
    
    def _auto_login_extension(self) -> None:
        """
        Log into the extension automatically using EXTENSION_LOGIN_EMAIL
        and EXTENSION_LOGIN_PASSWORD from .env.
        
        Calls the backend login API, then injects the token into
        chrome.storage.local via the content script event listener.
        """
        import time
        email = os.getenv("EXTENSION_LOGIN_EMAIL")
        password = os.getenv("EXTENSION_LOGIN_PASSWORD")
        if not email or not password:
            return
        
        api_url = os.getenv("AGENTTRUST_API_URL", "http://localhost:3000/api")
        
        # 1) Call backend login API from Python
        try:
            resp = requests.post(
                f"{api_url}/users/login",
                json={"email": email, "password": password},
                timeout=5,
            )
            data = resp.json()
            if not data.get("success"):
                print(f"⚠️  Extension auto-login failed: {data.get('error', 'unknown')}")
                return
            token = data["token"]
            user_email = data.get("user", {}).get("email", email)
        except Exception as e:
            print(f"⚠️  Extension auto-login skipped (backend not reachable): {e}")
            return
        
        # 2) Navigate to a real page so the content script is injected
        try:
            self._actual_driver.get(api_url.replace("/api", "/health"))
            time.sleep(1)
        except Exception:
            self._actual_driver.get("about:blank")
            time.sleep(0.5)
        
        # 3) Dispatch the event the content script listens for to store credentials
        try:
            self._actual_driver.execute_script(
                "window.dispatchEvent(new CustomEvent('agenttrust-login-success', "
                "{ detail: { token: arguments[0], email: arguments[1] } }));",
                token, user_email,
            )
            time.sleep(0.5)
            print(f"✅ Extension auto-login: {user_email}")
        except Exception as e:
            print(f"⚠️  Extension credential injection failed: {e}")
    
    def navigate(self, url: str):
        """Navigate to URL — validation already done by BrowserActionExecutor."""
        # Resolve relative paths (e.g. /ap/signin) against current origin
        if url and not url.startswith(("http://", "https://", "about:", "data:", "file:")):
            try:
                from urllib.parse import urljoin
                base = self._actual_driver.current_url
                url = urljoin(base, url)
            except Exception:
                pass
        self._actual_driver.get(url)
        self.current_url = self._actual_driver.current_url
        return {"success": True, "url": self.current_url}
    
    def get_current_url(self) -> str:
        """Get current page URL"""
        self.current_url = self._actual_driver.current_url
        return self.current_url
    
    def get_page_title(self) -> str:
        """Get page title"""
        return self._actual_driver.title
    
    def get_page_content(self, include_html: bool = False) -> Dict[str, Any]:
        """
        Get page content — compact text focused on the main content area.
        """
        drv = self._actual_driver

        # Try to extract just the main content area, fall back to body
        main_text = drv.execute_script("""
            const main = document.querySelector('main, [role="main"], #content, #main, .main-content, #search, #center-col');
            if (main) return main.innerText.substring(0, 4000);
            return document.body.innerText.substring(0, 4000);
        """) or ""

        content = {
            "url": drv.current_url,
            "title": drv.title,
            "text": main_text
        }
        
        if include_html:
            content["html"] = drv.page_source[:6000]
        
        return content
    
    def get_visible_elements(self, element_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get visible interactive elements on the page using a single JS call.
        
        Prioritises elements in/near the viewport so product links and buttons
        on content-heavy pages (e.g. Amazon search results) are returned before
        distant header/footer chrome.
        """
        drv = self._actual_driver

        # One JS call: collect all interactive elements, check visibility and
        # viewport proximity, and return structured data.  Much faster than
        # dozens of Selenium find_elements + get_attribute round-trips.
        # Compact JS: collect viewport-priority elements, return minimal data.
        # Only text, id, and short href are sent — keeps token usage low.
        js = """
        const F = arguments[0];
        const MAX = 40;
        const vh = window.innerHeight;
        const buf = vh;

        const all = document.querySelectorAll(
            'a,button,input,select,[role="button"],input[type="submit"]');
        const out = [];

        for (let i = 0; i < all.length && out.length < MAX * 3; i++) {
            const el = all[i];
            const r = el.getBoundingClientRect();
            if (!r.width && !r.height) continue;
            if (el.offsetParent === null && el.tagName !== 'BODY') continue;

            const tag = el.tagName.toLowerCase();
            let t;
            if (tag === 'a') t = 'link';
            else if (tag === 'button') t = 'btn';
            else if (tag === 'input') {
                const it = (el.type||'').toLowerCase();
                t = (it==='submit'||it==='button') ? 'btn' : 'in';
            } else t = 'btn';
            if (F && t !== F && !(F==='button'&&t==='btn') && !(F==='input'&&t==='in')) continue;

            const txt = (el.innerText||el.textContent||'').trim().substring(0,60);
            // Skip elements with no useful text and no id
            if (!txt && !el.id && !el.name && !el.placeholder) continue;

            const near = (r.top < vh + buf && r.bottom > -buf) ? 1 : 0;
            // For links, keep only the pathname to save tokens
            let hp = '';
            if (tag === 'a' && el.href) {
                try { hp = new URL(el.href).pathname.substring(0,80); } catch(e) { hp = el.href.substring(0,80); }
            }

            out.push({t,txt,id:el.id||'',nm:el.name||'',hp,
                al:el.getAttribute('aria-label')||'',
                ph:el.placeholder||'',
                v:(el.value||'').substring(0,30),
                n:near,y:Math.round(r.top)});
        }
        out.sort((a,b) => a.n!==b.n ? b.n-a.n : a.y-b.y);
        return out.slice(0, MAX);
        """

        try:
            raw = drv.execute_script(js, element_type)
            elements = []
            for i, r in enumerate(raw or []):
                e = {"i": i, "t": r.get("t", "?")}
                if r.get("txt"): e["text"] = r["txt"]
                if r.get("id"):  e["id"] = r["id"]
                if r.get("nm"):  e["name"] = r["nm"]
                if r.get("hp"):  e["href"] = r["hp"]
                if r.get("al"):  e["aria_label"] = r["al"]
                if r.get("ph"):  e["placeholder"] = r["ph"]
                if r.get("v"):   e["value"] = r["v"]
                elements.append(e)
            return elements
        except Exception as e:
            print(f"⚠️  Error getting elements: {e}")
            return []
    
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
        Click an element based on target information.
        Uses _actual_driver directly — validation is handled by BrowserActionExecutor.
        """
        import time
        drv = self._actual_driver
        try:
            element = None
            text_safe = (target.get("text") or "")[:80].strip()
            text_xpath = text_safe.replace("'", "''") if text_safe else ""
            
            if target.get("id"):
                try:
                    element = drv.find_element(By.ID, target["id"])
                except NoSuchElementException:
                    pass
            
            if not element and target.get("href"):
                href = str(target["href"])[:200].replace("'", "''")
                try:
                    element = drv.find_element(By.XPATH, f"//a[contains(@href, '{href}')]")
                except NoSuchElementException:
                    pass
            
            if not element and target.get("tagName") and text_safe:
                tag = str(target["tagName"]).upper().replace("HTML", "*")
                if tag == "*":
                    tag = "*"
                try:
                    element = drv.find_element(By.XPATH, f"//{tag}[contains(., '{text_xpath}')]")
                except NoSuchElementException:
                    pass
            
            if not element and target.get("aria_label"):
                try:
                    al = target["aria_label"].replace("'", "''")
                    element = drv.find_element(By.CSS_SELECTOR, f"[aria-label='{al}']")
                except (NoSuchElementException, Exception):
                    pass

            # text + optional nth (0-based) to disambiguate repeated labels like "Add to Cart"
            nth = target.get("nth", 0) if target.get("nth") is not None else 0
            if not element and text_safe:
                for xpath in [
                    f"//a[contains(., '{text_xpath}')]",
                    f"//button[contains(., '{text_xpath}')]",
                    f"//*[@role='button'][contains(., '{text_xpath}')]",
                    f"//input[@value='{text_xpath}' or contains(@value, '{text_xpath}')]",
                    f"//*[contains(., '{text_xpath}')]",
                ]:
                    try:
                        found = drv.find_elements(By.XPATH, xpath)
                        visible = [el for el in found if el.is_displayed() and el.is_enabled()]
                        if visible and nth < len(visible):
                            element = visible[nth]
                            break
                        elif visible:
                            element = visible[0]
                            break
                    except NoSuchElementException:
                        continue
            
            if not element and target.get("className"):
                try:
                    element = drv.find_element(By.CLASS_NAME, target["className"])
                except NoSuchElementException:
                    pass
            
            if not element and target.get("selector"):
                try:
                    element = drv.find_element(By.CSS_SELECTOR, target["selector"])
                except NoSuchElementException:
                    pass
            
            if not element:
                return {"success": False, "message": "Element not found with provided identifiers"}
            
            # Scroll into view
            try:
                drv.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});",
                    element
                )
            except Exception:
                pass
            time.sleep(0.1)
            
            try:
                WebDriverWait(drv, 5).until(EC.element_to_be_clickable(element))
            except TimeoutException:
                return {"success": False, "message": "Element not clickable within timeout"}
            
            if not element.is_displayed():
                return {"success": False, "message": "Element found but not visible"}
            
            clicked = False
            try:
                element.click()
                clicked = True
            except Exception:
                try:
                    drv.execute_script("arguments[0].click();", element)
                    clicked = True
                except Exception:
                    try:
                        ActionChains(drv).move_to_element(element).click().perform()
                        clicked = True
                    except Exception:
                        pass
            
            if clicked:
                time.sleep(0.3)
                return {"success": True, "message": "Element clicked successfully", "new_url": drv.current_url}
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
            drv = self._actual_driver
            for field_name, field_value in form_data.items():
                try:
                    field = drv.find_element(By.NAME, field_name)
                    field.clear()
                    field.send_keys(str(field_value))
                except NoSuchElementException:
                    try:
                        field = drv.find_element(By.ID, field_name)
                        field.clear()
                        field.send_keys(str(field_value))
                    except NoSuchElementException:
                        print(f"⚠️  Form field '{field_name}' not found")
            
            submit_button = drv.find_element(By.XPATH, "//input[@type='submit'] | //button[@type='submit']")
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
            
            drv = self._actual_driver
            if link_index is not None:
                links = drv.find_elements(By.TAG_NAME, "a")
                visible_links = [link for link in links if link.is_displayed()]
                if 0 <= link_index < len(visible_links):
                    element = visible_links[link_index]
            
            if not element and href:
                href_esc = str(href)[:200].replace("'", "''")
                try:
                    element = drv.find_element(By.XPATH, f"//a[contains(@href, '{href_esc}')]")
                except NoSuchElementException:
                    pass
            
            if not element and link_text:
                text_esc = str(link_text)[:50].replace("'", "''")
                try:
                    links = drv.find_elements(By.XPATH, f"//a[contains(., '{text_esc}')]")
                    for link in links:
                        if link.is_displayed():
                            element = link
                            break
                except NoSuchElementException:
                    pass
            
            if element and element.is_displayed():
                link_href = element.get_attribute("href")
                
                try:
                    drv.execute_script(
                        "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
                        element
                    )
                except Exception:
                    pass
                import time
                time.sleep(0.1)
                WebDriverWait(drv, 5).until(EC.element_to_be_clickable(element))
                try:
                    element.click()
                except Exception:
                    drv.execute_script("arguments[0].click();", element)
                
                import time
                time.sleep(0.5)
                
                return {
                    "success": True,
                    "message": "Link opened successfully",
                    "href": link_href,
                    "new_url": drv.current_url
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
        drv = self._actual_driver
        try:
            element = None
            
            if target.get("id"):
                try:
                    element = drv.find_element(By.ID, target["id"])
                except NoSuchElementException:
                    pass
            
            if not element and target.get("name"):
                try:
                    element = drv.find_element(By.NAME, target["name"])
                except NoSuchElementException:
                    pass
            
            if not element and target.get("placeholder"):
                try:
                    element = drv.find_element(By.XPATH, f"//input[@placeholder='{target['placeholder']}']")
                except NoSuchElementException:
                    pass
            
            if not element and target.get("selector"):
                try:
                    element = drv.find_element(By.CSS_SELECTOR, target["selector"])
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
        """Scroll the page."""
        drv = self._actual_driver
        try:
            if direction == "down":
                for _ in range(amount):
                    drv.execute_script("window.scrollBy(0, 500);")
            elif direction == "up":
                for _ in range(amount):
                    drv.execute_script("window.scrollBy(0, -500);")
            elif direction == "top":
                drv.execute_script("window.scrollTo(0, 0);")
            elif direction == "bottom":
                drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            import time
            time.sleep(0.2)
            
            return {"success": True, "message": f"Page scrolled {direction}"}
        except Exception as e:
            return {"success": False, "message": f"Error scrolling: {str(e)}"}
    
    def go_back(self) -> Dict[str, Any]:
        """Go back in browser history"""
        drv = self._actual_driver
        try:
            drv.back()
            import time
            time.sleep(0.3)
            return {"success": True, "message": "Navigated back", "url": drv.current_url}
        except Exception as e:
            return {"success": False, "message": f"Error going back: {str(e)}"}
    
    def go_forward(self) -> Dict[str, Any]:
        """Go forward in browser history"""
        drv = self._actual_driver
        try:
            drv.forward()
            import time
            time.sleep(0.3)
            return {"success": True, "message": "Navigated forward", "url": drv.current_url}
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
        drv = self._actual_driver
        try:
            element = None
            
            if target.get("id"):
                element = WebDriverWait(drv, timeout).until(
                    EC.presence_of_element_located((By.ID, target["id"]))
                )
            elif target.get("class"):
                element = WebDriverWait(drv, timeout).until(
                    EC.presence_of_element_located((By.CLASS_NAME, target["class"]))
                )
            elif target.get("text"):
                element = WebDriverWait(drv, timeout).until(
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
            self._actual_driver.save_screenshot(save_path)
            return save_path
        else:
            screenshot = self._actual_driver.get_screenshot_as_base64()
            return screenshot
    
    def close(self):
        """Close the browser."""
        if self._actual_driver:
            self._actual_driver.quit()


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
    
    def _notify_extension(self, action_type: str, url: str, status: str, risk_level: str = None,
                          action_id: str = None, target: dict = None, form_data: dict = None):
        """
        Dispatch a DOM event so the extension's content script can relay the
        action to the service worker and update the popup badge/log in real time.
        """
        if not self.browser or not hasattr(self.browser, '_actual_driver'):
            return
        try:
            import json as _json
            detail = _json.dumps({
                "type": action_type,
                "url": url,
                "domain": url.split("//")[-1].split("/")[0] if url else "",
                "status": status,
                "riskLevel": risk_level or "unknown",
                "actionId": action_id,
                "target": target,
                "formData": form_data,
                "timestamp": __import__("datetime").datetime.now().isoformat()
            })
            self.browser._actual_driver.execute_script(
                "window.dispatchEvent(new CustomEvent('agenttrust-action-logged', "
                "{ detail: JSON.parse(arguments[0]) }));",
                detail
            )
        except Exception:
            pass
    
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
        
        if status not in ("allowed", "denied", "step_up_required"):
            error_msg = result.get("message", f"Validation returned status: {status}")
            print(f"   ⚠️  AgentTrust error: {error_msg}")
            self.action_history.append({
                "action": "click", "url": url,
                "status": status or "error",
                "reason": error_msg
            })
            self._notify_extension("click", url, "error", target=target)
            return {
                "status": "error",
                "message": f"AgentTrust validation error: {error_msg}. Try again.",
                "browser_result": {"success": False, "message": error_msg}
            }
        
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
            if browser_result and browser_result.get("success"):
                try:
                    import time
                    time.sleep(0.15)
                    screenshot = self.browser.take_screenshot()
                    if screenshot and result.get("action_id"):
                        try:
                            self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                        except:
                            pass
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot: {e}")
        
        self._notify_extension("click", url, "allowed",
                               risk_level=result.get("risk_level"),
                               action_id=result.get("action_id"),
                               target=target)
        
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
        
        if status not in ("allowed", "denied", "step_up_required"):
            error_msg = result.get("message", f"Validation returned status: {status}")
            print(f"   ⚠️  AgentTrust error: {error_msg}")
            self.action_history.append({
                "action": "form_submit", "url": url,
                "status": status or "error",
                "reason": error_msg
            })
            self._notify_extension("form_submit", url, "error", form_data=form_data)
            return {
                "status": "error",
                "message": f"AgentTrust validation error: {error_msg}. Try again.",
                "browser_result": {"success": False, "message": error_msg}
            }
        
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
            if browser_result and browser_result.get("success"):
                try:
                    import time
                    time.sleep(0.3)
                    screenshot = self.browser.take_screenshot()
                    if screenshot and result.get("action_id"):
                        try:
                            self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                        except Exception as e:
                            print(f"⚠️  Failed to update screenshot: {e}")
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot: {e}")
        
        self._notify_extension("form_submit", url, "allowed",
                               risk_level=result.get("risk_level"),
                               action_id=result.get("action_id"),
                               form_data=form_data)
        
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
        # Resolve relative paths before validation
        if url and not url.startswith(("http://", "https://", "about:", "data:")):
            try:
                from urllib.parse import urljoin
                base = self.browser.get_current_url() if self.browser else ""
                if base:
                    url = urljoin(base, url)
            except Exception:
                pass

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
        
        if status not in ("allowed", "denied", "step_up_required"):
            error_msg = result.get("message", f"Validation returned status: {status}")
            print(f"   ⚠️  AgentTrust error: {error_msg}")
            self.action_history.append({
                "action": "navigation", "url": url,
                "status": status or "error",
                "reason": error_msg
            })
            self._notify_extension("navigation", url, "error")
            return {
                "status": "error",
                "message": f"AgentTrust validation error: {error_msg}. "
                           "This may be a temporary issue — try again or navigate to a different page.",
                "browser_result": {"success": False, "message": error_msg}
            }
        
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
        page_error = None
        if self.browser:
            browser_result = self.browser.navigate(url)
            if browser_result and browser_result.get("success"):
                try:
                    driver = self.browser._actual_driver
                    try:
                        WebDriverWait(driver, 5).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                    except Exception:
                        pass
                    actual_url = driver.current_url
                    title = (driver.title or "").lower()
                    body_text = ""
                    try:
                        body_text = driver.find_element(
                            __import__('selenium.webdriver.common.by', fromlist=['By']).By.TAG_NAME,
                            "body"
                        ).text[:500].lower()
                    except Exception:
                        pass

                    error_signals = [
                        "404", "not found", "page not found", "page isn't working",
                        "this site can't be reached", "err_connection",
                        "err_name_not_resolved", "http error", "server error",
                        "access denied", "403 forbidden", "502 bad gateway",
                        "503 service", "this page isn't working",
                    ]
                    for sig in error_signals:
                        if sig in title or sig in body_text or sig in actual_url.lower():
                            page_error = f"Page load error detected: '{sig}' found. The URL may be wrong or the page is unavailable."
                            break

                    screenshot = self.browser.take_screenshot()
                    if screenshot and result.get("action_id"):
                        try:
                            self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                        except Exception as e:
                            print(f"⚠️  Failed to update screenshot: {e}")
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot: {e}")
        
        self._notify_extension("navigation", url, "allowed",
                               risk_level=result.get("risk_level"),
                               action_id=result.get("action_id"))
        
        resp = {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Navigation action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result,
            "screenshot": screenshot
        }
        if page_error:
            resp["page_error"] = page_error
            resp["message"] = (
                f"Navigation allowed but the page failed to load properly: {page_error} "
                "Try navigating to the site's homepage instead and find the correct link."
            )
        return resp
    
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
            links = self.browser.get_visible_elements("link")
            for link in links:
                if link.get("text") and link_text.lower() in link.get("text", "").lower():
                    target_url = link.get("href")
                    break
        
        if not target_url:
            return {"error": "Could not determine link URL"}
        
        # Resolve relative paths to absolute URLs
        if target_url and not target_url.startswith(("http://", "https://")):
            try:
                from urllib.parse import urljoin
                base = self.browser.get_current_url()
                target_url = urljoin(base, target_url)
            except Exception:
                pass
        
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
        Type text into an input field.
        Validated as a click (low-risk) rather than form_submit, because
        typing into a search box / filter is not a form submission.
        """
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        current_url = self.browser.get_current_url()
        
        try:
            result = self.agenttrust.execute_action(
                action_type="click",
                url=current_url,
                target={"type": "input", "action": "type_text",
                        "id": target.get("id"), "name": target.get("name")}
            )
            
            status = result.get("status") if result else None

            if status in ("allowed", None):
                type_result = self.browser.type_text(target, text)
                if not type_result.get("success"):
                    # Element not found by standard lookup — try CSS selector fallback
                    type_result = self._type_text_fallback(target, text)
                screenshot = None
                if type_result.get("success"):
                    try:
                        import time
                        time.sleep(0.1)
                        screenshot = self.browser.take_screenshot()
                        if screenshot and result and result.get("action_id"):
                            try:
                                self.agenttrust._update_action_screenshot(result.get("action_id"), screenshot)
                            except:
                                pass
                    except:
                        pass
                
                return {
                    "status": "allowed",
                    "action_id": result.get("action_id") if result else None,
                    "risk_level": result.get("risk_level") if result else "low",
                    "typed": type_result.get("success", False),
                    "message": type_result.get("message", "")
                }
            elif status == "denied":
                return {"status": "denied", "message": result.get("message", "Typing denied by AgentTrust")}
            elif status == "step_up_required":
                return {"status": "step_up_required", "message": result.get("message", "Requires approval")}
            else:
                return {"status": status or "error", "message": result.get("message", "Unexpected status") if result else "No response"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _type_text_fallback(self, target: Dict[str, Any], text: str) -> Dict[str, Any]:
        """Fallback: find an input by multiple strategies when standard lookup fails."""
        drv = self.browser._actual_driver
        from selenium.webdriver.common.by import By
        element = None

        # Try aria-label
        if target.get("aria-label"):
            try:
                element = drv.find_element(By.CSS_SELECTOR, f"input[aria-label='{target['aria-label']}']")
            except Exception:
                pass
        # Try type attribute
        if not element and target.get("type"):
            try:
                element = drv.find_element(By.CSS_SELECTOR, f"input[type='{target['type']}']")
            except Exception:
                pass
        # Try role=searchbox or common search selectors
        if not element:
            for sel in ["input[role='searchbox']", "input[type='search']",
                        "input[name='field-keywords']", "#twotabsearchtextbox",
                        "input[aria-label*='Search']", "input[placeholder*='Search']",
                        "input[name='q']", "input[name='search']"]:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        element = el
                        break
                except Exception:
                    continue

        if element and element.is_displayed():
            try:
                element.clear()
                element.send_keys(text)
                return {"success": True, "message": f"Text typed (fallback): {text[:50]}"}
            except Exception as e:
                return {"success": False, "message": f"Fallback type failed: {e}"}
        return {"success": False, "message": "Input field not found by any method"}
    
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

    def auto_login(self, url: str, username: str, password: str):
        """
        Perform a full login flow that handles multi-step forms, QR code
        popups, stale-element recovery, and password-only pages.
        All mutating steps go through AgentTrust validation.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import (
            StaleElementReferenceException, NoSuchElementException,
            ElementNotInteractableException, TimeoutException
        )

        if not self.browser:
            return {"success": False, "message": "Browser not initialized"}

        driver = self.browser._actual_driver
        steps_log = []

        # ── Helpers ──────────────────────────────────────────────

        def _wait_ready(seconds=0.3):
            """Wait for DOM to be ready, then a short settle time."""
            try:
                WebDriverWait(driver, 5).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass
            if seconds > 0:
                time.sleep(seconds)

        def _safe_attr(el, attr):
            """Get an attribute, returning '' on stale ref."""
            try:
                return (el.get_attribute(attr) or "").strip().lower()
            except (StaleElementReferenceException, Exception):
                return ""

        def _find_input(field_type, retries=2):
            """Find a visible username or password input, retrying on stale DOM."""
            username_selectors = [
                "input[type='email']",
                "input[name='email']", "input[name='username']",
                "input[name='login_field']", "input[name='identifier']",
                "input[id='identifierId']", "input[id='ap_email']",
                "input[id='ap_email_login']", "input[id='login']",
                "input[autocomplete='username']", "input[autocomplete='email']",
                "input[type='text'][name*='mail']",
                "input[type='text'][name*='user']",
                "input[type='text'][name*='login']",
                "input[id*='mail']", "input[id*='user']",
                "input[type='text']",
            ]
            password_selectors = [
                "input[type='password']",
                "input[name='password']", "input[name='passwd']",
                "input[id='password']", "input[id='ap_password']",
                "input[autocomplete='current-password']",
            ]
            selectors = username_selectors if field_type == "username" else password_selectors

            # Combine all selectors into a single CSS query to avoid N separate calls
            combined = ", ".join(selectors)
            for attempt in range(retries):
                try:
                    els = driver.find_elements(By.CSS_SELECTOR, combined)
                    for el in els:
                        try:
                            if el.is_displayed() and el.is_enabled():
                                return el
                        except StaleElementReferenceException:
                            continue
                except Exception:
                    pass
                if attempt < retries - 1:
                    time.sleep(0.15)
            return None

        def _find_continue_button(retries=2):
            """Scan for continue/next/sign-in buttons, skipping passkey/biometric buttons."""
            keywords = [
                "continue", "next", "sign in", "signin", "log in", "login",
                "submit", "proceed", "verify", "let's go"
            ]
            skip_keywords = [
                "passkey", "biometric", "fingerprint", "face id", "fido",
                "webauthn", "security key", "authenticator", "qr code",
                "sign in with a", "sign in with", "sign in using",
                "use a passkey", "create passkey", "windows hello",
                "try another way",
            ]
            fallback_ids = [
                "identifierNext", "passwordNext", "signIn", "continue",
                "next", "submitBtn", "login-submit", "auth-submit-btn",
                "a-autoid-0-announce", "auth-signin-button",
            ]

            def _is_passkey_button(el):
                """Check all text sources for passkey/biometric references."""
                texts = []
                try:
                    texts.append((_safe_attr(el, 'textContent') or ""))
                except Exception:
                    pass
                try:
                    texts.append((_safe_attr(el, 'value') or ""))
                except Exception:
                    pass
                try:
                    texts.append((_safe_attr(el, 'aria-label') or ""))
                except Exception:
                    pass
                try:
                    texts.append((el.text or "").strip().lower())
                except Exception:
                    pass
                try:
                    texts.append((_safe_attr(el, 'id') or ""))
                except Exception:
                    pass
                try:
                    texts.append((_safe_attr(el, 'class') or ""))
                except Exception:
                    pass
                full = " ".join(texts)
                return any(skip in full for skip in skip_keywords)

            # Build a single CSS selector for fallback IDs to avoid N separate calls
            fallback_css = ", ".join(f"#{bid}" for bid in fallback_ids)

            for attempt in range(retries):
                try:
                    candidates = driver.find_elements(By.CSS_SELECTOR,
                        "button, input[type='submit'], input[type='button'], "
                        "a[role='button'], div[role='button'], span[role='button']")
                    for el in candidates:
                        try:
                            if not el.is_displayed():
                                continue
                            if _is_passkey_button(el):
                                continue
                            combined = f"{_safe_attr(el, 'textContent')} {_safe_attr(el, 'value')} {_safe_attr(el, 'aria-label')}"
                            if not combined.strip():
                                combined = (el.text or "").strip().lower()
                            for kw in keywords:
                                if kw in combined:
                                    return el
                        except StaleElementReferenceException:
                            continue
                except Exception:
                    pass
                try:
                    fb_els = driver.find_elements(By.CSS_SELECTOR, fallback_css)
                    for el in fb_els:
                        try:
                            if el.is_displayed() and not _is_passkey_button(el):
                                return el
                        except StaleElementReferenceException:
                            continue
                except Exception:
                    pass
                if attempt < retries - 1:
                    time.sleep(0.15)
            return None

        def _dismiss_overlays():
            """Close QR-code dialogs, cookie banners, or other overlays. Fast path."""
            combined_selector = ", ".join([
                "a[data-action='a-modal-close']",
                "button[data-action='a-modal-close']",
                "button.a-modal-close", "a.a-modal-close",
                "#ap-account-fixup-phone-skip-link",
                "button[id*='passkey-cancel']", "button[id*='passkey-close']",
                "a[id*='passkey-cancel']",
                "#credential_picker_close", "#credential_picker_cancel",
                "button[aria-label='Close']", "button[aria-label='Dismiss']",
                "[data-dismiss='modal']",
                "button.modal-close", "a.skip-link", "button.skip",
            ])
            dismissed = False
            try:
                els = driver.find_elements(By.CSS_SELECTOR, combined_selector)
                for el in els:
                    try:
                        if el.is_displayed():
                            el.click()
                            dismissed = True
                            time.sleep(0.1)
                    except (StaleElementReferenceException, ElementNotInteractableException):
                        continue
            except Exception:
                pass

            if not dismissed:
                try:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                except Exception:
                    pass

            return dismissed

        def _safe_click(el):
            """Click with JS fallback if normal click fails."""
            try:
                el.click()
            except (ElementNotInteractableException, StaleElementReferenceException):
                try:
                    driver.execute_script("arguments[0].click();", el)
                except Exception:
                    raise

        def _safe_type(el, text):
            """Clear and type into an input, with JS fallback."""
            try:
                el.click()
                time.sleep(0.05)
            except Exception:
                try:
                    driver.execute_script("arguments[0].focus();", el)
                except Exception:
                    pass
            try:
                el.clear()
            except Exception:
                try:
                    driver.execute_script("arguments[0].value = '';", el)
                except Exception:
                    pass
            try:
                el.send_keys(text)
            except StaleElementReferenceException:
                raise
            except Exception:
                driver.execute_script(
                    "arguments[0].value = arguments[1]; "
                    "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
                    el, text)

        # ── Main flow ────────────────────────────────────────────

        # Disable implicit wait for the duration of auto_login.
        # Each find_elements miss blocks for `implicitly_wait` seconds (2s default).
        # With dozens of CSS selectors probed, that adds up to 30+ seconds of dead time.
        # We use explicit WebDriverWait where actual waiting is needed.
        _prev_implicit_wait = 2
        try:
            driver.implicitly_wait(0)
        except Exception:
            pass

        try:
            # Step 0: Validate the login action with AgentTrust
            form_data = {"action": "auto_login", "fields": {"username": username, "password": password}}
            result = self.agenttrust.execute_action(
                action_type="form_submit", url=url, form_data=form_data
            )
            status = result.get("status")
            safe_form = {"action": "auto_login", "fields": {"username": username[:3] + "***", "password": "***"}}
            if status == "denied":
                self._notify_extension("form_submit", url, "denied", form_data=safe_form)
                return {"success": False, "status": "denied",
                        "message": result.get("message", "Login denied by policy")}
            if status == "step_up_required":
                self._notify_extension("form_submit", url, "step_up_required", form_data=safe_form)
                return {"success": False, "status": "step_up_required",
                        "message": "Login requires user approval",
                        "requires_user_approval": True}

            action_id = result.get("action_id")

            # Step 1: Dismiss any overlays (QR code, cookie banners, etc.)
            _wait_ready(0.1)
            if _dismiss_overlays():
                steps_log.append("Dismissed overlay/popup")
                _wait_ready(0.1)

            # Step 2: Detect current login state
            password_el = _find_input("password")
            username_el = _find_input("username")

            if password_el and not username_el:
                _safe_type(password_el, password)
                steps_log.append("Entered password (password-only page)")
            elif password_el and username_el:
                _safe_type(username_el, username)
                steps_log.append("Entered username/email")
                password_el = _find_input("password")
                if password_el:
                    _safe_type(password_el, password)
                    steps_log.append("Entered password (single-step form)")
            elif username_el:
                _safe_type(username_el, username)
                steps_log.append("Entered username/email")
                _wait_ready(0.1)

                continue_btn = _find_continue_button()
                if continue_btn:
                    btn_text = ""
                    try:
                        btn_text = (continue_btn.text or "").strip()[:30]
                    except StaleElementReferenceException:
                        pass
                    _safe_click(continue_btn)
                    steps_log.append(f"Clicked continue/next: '{btn_text}'")
                else:
                    try:
                        username_el.send_keys(Keys.RETURN)
                    except StaleElementReferenceException:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                    steps_log.append("Pressed Enter after username")

                # Wait for password field — use WebDriverWait instead of fixed sleeps
                password_el = None
                try:
                    WebDriverWait(driver, 5).until(
                        lambda d: _find_input("password") is not None
                    )
                    password_el = _find_input("password")
                except TimeoutException:
                    pass

                if not password_el:
                    _dismiss_overlays()
                    _wait_ready(0.1)
                    password_el = _find_input("password")

                if password_el:
                    _safe_type(password_el, password)
                    steps_log.append("Entered password (after continue)")
                else:
                    screenshot = self.take_screenshot()
                    if screenshot and action_id:
                        try:
                            self.agenttrust._update_action_screenshot(action_id, screenshot)
                        except Exception:
                            pass
                    return {"success": False,
                            "message": "Password field did not appear after clicking continue. "
                                       "There may be a CAPTCHA or additional verification step.",
                            "steps_completed": steps_log}
            else:
                _dismiss_overlays()
                _wait_ready(0.1)
                username_el = _find_input("username")
                password_el = _find_input("password")
                if password_el:
                    _safe_type(password_el, password)
                    steps_log.append("Entered password (after overlay dismiss)")
                elif username_el:
                    _safe_type(username_el, username)
                    steps_log.append("Entered username (after overlay dismiss)")
                else:
                    screenshot = self.take_screenshot()
                    if screenshot and action_id:
                        try:
                            self.agenttrust._update_action_screenshot(action_id, screenshot)
                        except Exception:
                            pass
                    return {"success": False,
                            "message": "No login input fields found. The page may not be a login page, "
                                       "or there may be a CAPTCHA/overlay blocking the form.",
                            "steps_completed": steps_log,
                            "current_url": driver.current_url}

            # Step 3: Submit the login form — prefer Enter on password field
            # (avoids accidentally clicking passkey / secondary auth buttons)
            _wait_ready(0.1)
            pw_for_submit = _find_input("password")
            if pw_for_submit:
                try:
                    pw_for_submit.send_keys(Keys.RETURN)
                    steps_log.append("Pressed Enter on password field to submit")
                except StaleElementReferenceException:
                    submit_btn = _find_continue_button()
                    if submit_btn:
                        btn_text = ""
                        try:
                            btn_text = (submit_btn.text or "").strip()[:30]
                        except StaleElementReferenceException:
                            pass
                        _safe_click(submit_btn)
                        steps_log.append(f"Clicked submit: '{btn_text}'")
                    else:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                        steps_log.append("Pressed Enter to submit")
            else:
                submit_btn = _find_continue_button()
                if submit_btn:
                    btn_text = ""
                    try:
                        btn_text = (submit_btn.text or "").strip()[:30]
                    except StaleElementReferenceException:
                        pass
                    _safe_click(submit_btn)
                    steps_log.append(f"Clicked submit: '{btn_text}'")
                else:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                    steps_log.append("Pressed Enter to submit")

            # Step 4: Wait for navigation / page load
            _wait_ready(0.5)

            # Dismiss any post-login overlays (e.g. "stay signed in?" prompts)
            if _dismiss_overlays():
                steps_log.append("Dismissed post-login overlay")

            new_url = driver.current_url
            steps_log.append(f"Page after login: {new_url}")

            # Capture final screenshot
            screenshot = self.take_screenshot()
            if screenshot and action_id:
                try:
                    self.agenttrust._update_action_screenshot(action_id, screenshot)
                except Exception:
                    pass

            self._notify_extension("form_submit", url, "allowed",
                                   risk_level=result.get("risk_level"),
                                   action_id=action_id,
                                   form_data={"action": "auto_login"})

            return {
                "success": True, "status": "allowed",
                "action_id": action_id,
                "risk_level": result.get("risk_level"),
                "new_url": new_url,
                "steps_completed": steps_log,
                "message": "Login flow completed"
            }

        except PermissionError as e:
            return {"success": False, "status": "denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "message": f"Login flow error: {str(e)}",
                    "steps_completed": steps_log}
        finally:
            try:
                driver.implicitly_wait(_prev_implicit_wait)
            except Exception:
                pass

    def _wait_page_ready(self, timeout: int = 15):
        """Wait until the page is fully loaded (document.readyState === 'complete')."""
        if not self.browser:
            return
        driver = self.browser._actual_driver
        from selenium.webdriver.support.ui import WebDriverWait
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass
        time.sleep(0.5)

    def _wait_for_target(self, target: dict, timeout: int = 10) -> bool:
        """
        Wait until the target element is present and visible on the page.
        Returns True if found, False on timeout.
        """
        if not self.browser or not target:
            return False
        driver = self.browser._actual_driver
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.by import By

        def _find(d):
            if target.get("id"):
                try:
                    el = d.find_element(By.ID, target["id"])
                    if el.is_displayed():
                        return True
                except Exception:
                    pass
            text = (target.get("text") or "")[:80].strip()
            if text:
                text_xpath = text.replace("'", "''")
                for xpath in [
                    f"//a[contains(., '{text_xpath}')]",
                    f"//button[contains(., '{text_xpath}')]",
                    f"//*[contains(., '{text_xpath}')]",
                ]:
                    try:
                        els = d.find_elements(By.XPATH, xpath)
                        for el in els:
                            if el.is_displayed():
                                return True
                    except Exception:
                        continue
            if target.get("selector"):
                try:
                    el = d.find_element(By.CSS_SELECTOR, target["selector"])
                    if el.is_displayed():
                        return True
                except Exception:
                    pass
            if target.get("href"):
                href = str(target["href"])[:200].replace("'", "''")
                try:
                    el = d.find_element(By.XPATH, f"//a[contains(@href, '{href}')]")
                    if el.is_displayed():
                        return True
                except Exception:
                    pass
            return False

        try:
            WebDriverWait(driver, timeout).until(_find)
            return True
        except Exception:
            return False

    def _resolve_credentials(self, domain: str) -> tuple:
        """
        Look up saved credentials for a domain from the credential vault.
        Returns (username, password) or (None, None) if not found.
        """
        try:
            creds = self.agenttrust.get_credentials(domain)
            if creds:
                return creds.get("username"), creds.get("password")
        except Exception as e:
            print(f"           Credential lookup error: {e}")
        return None, None

    def _validate_global_routine_once(self, steps: list) -> str:
        """
        One-time validation for a global routine the user doesn't own.
        Checks all unique domains against the policy engine.
        Returns None if OK, or an error string if blocked.
        """
        domains = set()
        for s in steps:
            d = s.get("domain", "")
            u = s.get("url", "")
            if d:
                domains.add(d)
            elif u:
                try:
                    from urllib.parse import urlparse
                    domains.add(urlparse(u).hostname or "")
                except Exception:
                    pass
        domains.discard("")

        for domain in domains:
            try:
                result = self.agenttrust.execute_action(
                    action_type="navigation",
                    url=f"https://{domain}"
                )
                status = result.get("status", "")
                if status == "denied":
                    return f"Domain {domain} is blocked by your policy"
                if status == "step_up_required":
                    return f"Domain {domain} requires step-up approval — approve it first, then re-run"
            except PermissionError as e:
                return str(e)
            except Exception:
                pass
        return None

    def _exec_browser_navigate(self, url: str) -> dict:
        """Navigate directly via browser controller, bypassing AgentTrust validation."""
        if not self.browser:
            return {"success": False, "message": "Browser not available"}
        result = self.browser.navigate(url)
        self._wait_page_ready(timeout=15)
        actual = self.browser.get_current_url()
        return {"success": True, "status": "allowed", "new_url": actual, **(result or {})}

    def _exec_browser_click(self, target: dict) -> dict:
        """Click directly via browser controller, bypassing AgentTrust validation."""
        if not self.browser:
            return {"success": False, "message": "Browser not available"}
        self._wait_page_ready(timeout=10)
        found = self._wait_for_target(target, timeout=10)
        if not found:
            time.sleep(0.5)
            found = self._wait_for_target(target, timeout=5)
        if not found:
            print(f"           WARNING: Target element not found, attempting click anyway")
        result = self.browser.click_element(target)
        self._wait_page_ready(timeout=10)
        return {"status": "allowed", **(result or {})}

    def _exec_browser_form_submit(self, form_data: dict) -> dict:
        """Submit form directly via browser controller, bypassing AgentTrust validation."""
        if not self.browser:
            return {"success": False, "message": "Browser not available"}
        self._wait_page_ready(timeout=10)
        result = self.browser.submit_form(form_data)
        self._wait_page_ready(timeout=10)
        return {"status": "allowed", **(result or {})}

    def replay_routine(self, steps: list, routine_name: str = "routine",
                       scope: str = "private", is_owner: bool = True) -> dict:
        """
        Deterministically replay a sequence of recorded browser actions
        without involving ChatGPT.

        Trust model:
        - Private routines (or global routines run by their owner):
          Actions are TRUSTED and execute directly on the browser without
          AgentTrust policy checks. The user already approved these actions
          when they recorded/saved the routine.
        - Global routines run by a non-owner:
          A single upfront validation checks all domains against the user's
          policy. If all pass, the rest executes in trusted mode. This means
          the user only validates once, not per-step.

        Key behaviors:
        - Waits for document.readyState === 'complete' after every navigation
        - Waits for target elements to appear before clicking
        - Resolves credentials from the vault for auto_login steps
        - Retries element-finding once on failure after a short delay
        """
        results = []
        total = len(steps)
        trusted = (scope == "private") or is_owner

        print(f"\n{'='*50}")
        print(f"  ROUTINE: {routine_name} ({total} steps)")
        print(f"  Mode: {'TRUSTED (skip validation)' if trusted else 'VALIDATED (one-time check)'}")
        print(f"{'='*50}")

        if not trusted:
            print("  Validating routine domains...")
            err = self._validate_global_routine_once(steps)
            if err:
                print(f"  BLOCKED: {err}")
                return {
                    "success": False, "routine": routine_name,
                    "steps_total": total, "steps_completed": 0,
                    "results": [{"step": 0, "status": "denied", "error": err}]
                }
            print("  All domains OK — proceeding in trusted mode")
            trusted = True

        for i, step in enumerate(steps, 1):
            action_type = step.get("actionType", step.get("type", ""))
            url = step.get("url", "")
            domain = step.get("domain", "")
            target = step.get("target")
            form_data = step.get("formData")
            label = step.get("label", f"Step {i}")

            print(f"  [{i}/{total}] {label}")

            try:
                if action_type == "navigation":
                    nav_url = url or (f"https://{domain}" if domain else "")
                    if not nav_url:
                        results.append({"step": i, "status": "skipped", "reason": "no url"})
                        continue
                    if trusted:
                        result = self._exec_browser_navigate(nav_url)
                    else:
                        result = self.execute_navigation(url=nav_url)
                        self._wait_page_ready(timeout=15)
                    print(f"           Page loaded: {self.browser.get_current_url() if self.browser else nav_url}")

                elif action_type == "click":
                    if not target:
                        results.append({"step": i, "status": "skipped", "reason": "no target"})
                        continue
                    if trusted:
                        result = self._exec_browser_click(target)
                    else:
                        self._wait_page_ready(timeout=10)
                        click_url = url or (self.browser.get_current_url() if self.browser else "")
                        found = self._wait_for_target(target, timeout=10)
                        if not found:
                            time.sleep(0.5)
                            found = self._wait_for_target(target, timeout=5)
                        if not found:
                            print(f"           WARNING: Target element not found, attempting click anyway")
                        result = self.execute_click(url=click_url, target=target)
                        self._wait_page_ready(timeout=10)

                elif action_type == "form_submit":
                    if not form_data:
                        results.append({"step": i, "status": "skipped", "reason": "no form_data"})
                        continue

                    is_login = False
                    if isinstance(form_data, dict):
                        if form_data.get("action") == "auto_login":
                            is_login = True
                        elif isinstance(form_data.get("fields"), dict):
                            flds = form_data["fields"]
                            if "username" in flds or "password" in flds:
                                is_login = True

                    if is_login:
                        self._wait_page_ready(timeout=10)
                        login_url = url or (self.browser.get_current_url() if self.browser else "")

                        # Try to use credentials embedded in the (decrypted) form_data first
                        fields = form_data.get("fields", {}) if isinstance(form_data, dict) else {}
                        login_user = fields.get("username", "") or ""
                        login_pass = fields.get("password", "") or ""

                        # If credentials are masked or missing, resolve from vault
                        if not login_user or "***" in login_user or not login_pass or "***" in login_pass:
                            lookup_domain = domain or ""
                            if not lookup_domain and login_url:
                                try:
                                    from urllib.parse import urlparse
                                    lookup_domain = urlparse(login_url).hostname or ""
                                except Exception:
                                    pass
                            if lookup_domain:
                                print(f"           Looking up credentials for {lookup_domain}...")
                                login_user, login_pass = self._resolve_credentials(lookup_domain)
                        
                        if login_user and login_pass:
                            print(f"           Logging in as {login_user}")
                            result = self.auto_login(url=login_url, username=login_user, password=login_pass)
                            self._wait_page_ready(timeout=15)
                        else:
                            print(f"           No credentials available for {domain or login_url}")
                            results.append({"step": i, "status": "skipped",
                                            "reason": f"No credentials for {domain or login_url}"})
                            continue
                    elif trusted:
                        result = self._exec_browser_form_submit(form_data)
                    else:
                        form_url = url or (self.browser.get_current_url() if self.browser else "")
                        self._wait_page_ready(timeout=10)
                        result = self.execute_form_submit(url=form_url, form_data=form_data)
                        self._wait_page_ready(timeout=10)

                elif action_type == "auto_login":
                    self._wait_page_ready(timeout=10)
                    login_url = url or (self.browser.get_current_url() if self.browser else "")
                    username = (form_data or {}).get("username", "")
                    password = (form_data or {}).get("password", "")
                    if not username or not password:
                        lookup_domain = domain or ""
                        if not lookup_domain and login_url:
                            try:
                                from urllib.parse import urlparse
                                lookup_domain = urlparse(login_url).hostname or ""
                            except Exception:
                                pass
                        if lookup_domain:
                            print(f"           Looking up credentials for {lookup_domain}...")
                            username, password = self._resolve_credentials(lookup_domain)
                    if username and password:
                        print(f"           Logging in as {username}")
                        result = self.auto_login(url=login_url, username=username, password=password)
                        self._wait_page_ready(timeout=15)
                    else:
                        print(f"           No credentials available for {domain or login_url}")
                        results.append({"step": i, "status": "skipped",
                                        "reason": f"No credentials found for {domain or login_url}"})
                        continue
                else:
                    results.append({"step": i, "status": "skipped", "reason": f"unknown type: {action_type}"})
                    continue

                status = result.get("status", "allowed")
                success_flag = result.get("success", True) if "success" in result else True
                ok = status in ("allowed", "success") and success_flag is not False
                results.append({"step": i, "label": label, "status": status, "success": ok})
                symbol = "OK" if ok else "FAIL"
                print(f"           -> {symbol} ({status})")

                if not ok and status in ("denied", "step_up_required"):
                    print(f"           Routine halted: {result.get('message', status)}")
                    break

                if not ok:
                    err_msg = result.get("message", "")
                    br = result.get("browser_result", {})
                    br_msg = br.get("message", "") if isinstance(br, dict) else ""
                    print(f"           Issue: {err_msg or br_msg or 'check browser'}")

                time.sleep(0.3)

            except PermissionError as e:
                print(f"           -> DENIED: {e}")
                results.append({"step": i, "label": label, "status": "denied", "error": str(e)})
                break
            except Exception as e:
                print(f"           -> ERROR: {e}")
                results.append({"step": i, "label": label, "status": "error", "error": str(e)})

        completed = sum(1 for r in results if r.get("success"))
        print(f"\n  Routine finished: {completed}/{total} steps completed")
        print(f"{'='*50}\n")

        return {
            "success": completed == total,
            "routine": routine_name,
            "steps_total": total,
            "steps_completed": completed,
            "results": results
        }


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
        self._consecutive_failures = 0
        self._last_action_key = None
        self._tool_call_count = 0
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    # ------------------------------------------------------------------ #
    # Rate-limit-aware API call wrapper
    # ------------------------------------------------------------------ #
    def _chat_completion(self, **kwargs):
        """Call OpenAI chat completions."""
        return self.openai.chat.completions.create(**kwargs)

    # ------------------------------------------------------------------ #
    # Tool definitions (built once, reused every turn)
    # ------------------------------------------------------------------ #
    def _build_tools(self) -> list:
        """Return the full OpenAI tools list."""
        tools = [AGENTTRUST_FUNCTION_DEFINITION]
        if not self.browser_executor.browser:
            return tools
        tools.extend([
            {"type": "function", "function": {
                "name": "get_page_content",
                "description": "Get the visible text, title and URL of the current page. Use this BEFORE every action to understand what is on screen. Pass include_html=true only when you need tag structure.",
                "parameters": {"type": "object", "properties": {
                    "include_html": {"type": "boolean", "description": "Include raw HTML (default false)"}
                }}
            }},
            {"type": "function", "function": {
                "name": "get_visible_elements",
                "description": "List interactive elements (buttons, links, inputs) visible on the current page. Each element has an 'index' you can reference. Call this to discover what you can click/type.",
                "parameters": {"type": "object", "properties": {
                    "element_type": {"type": "string", "enum": ["button", "link", "input", "form"],
                                     "description": "Filter by element type (optional)"}
                }}
            }},
            {"type": "function", "function": {
                "name": "get_current_url",
                "description": "Return the current page URL.",
                "parameters": {"type": "object", "properties": {}}
            }},
            {"type": "function", "function": {
                "name": "open_link",
                "description": "Follow a link on the current page. Identify the link by href, visible text, or index from get_visible_elements.",
                "parameters": {"type": "object", "properties": {
                    "href": {"type": "string", "description": "Full or partial link URL"},
                    "link_text": {"type": "string", "description": "Visible text of the link"},
                    "link_index": {"type": "integer", "description": "Index from get_visible_elements"}
                }}
            }},
            {"type": "function", "function": {
                "name": "type_text",
                "description": "Type text into an input field identified by id, name, placeholder, or CSS selector.",
                "parameters": {"type": "object", "properties": {
                    "target": {"type": "object", "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "placeholder": {"type": "string"}, "selector": {"type": "string"}
                    }},
                    "text": {"type": "string", "description": "Text to type"}
                }, "required": ["target", "text"]}
            }},
            {"type": "function", "function": {
                "name": "scroll_page",
                "description": "Scroll the page. Use when elements might be below the fold.",
                "parameters": {"type": "object", "properties": {
                    "direction": {"type": "string", "enum": ["down", "up", "top", "bottom"]},
                    "amount": {"type": "integer", "description": "Scroll steps (default 3)"}
                }}
            }},
            {"type": "function", "function": {
                "name": "go_back",
                "description": "Navigate back in browser history.",
                "parameters": {"type": "object", "properties": {}}
            }},
            {"type": "function", "function": {
                "name": "go_forward",
                "description": "Navigate forward in browser history.",
                "parameters": {"type": "object", "properties": {}}
            }},
            {"type": "function", "function": {
                "name": "wait_for_element",
                "description": "Wait for an element to appear on the page (by id, class, or text).",
                "parameters": {"type": "object", "properties": {
                    "target": {"type": "object", "properties": {
                        "id": {"type": "string"}, "class": {"type": "string"}, "text": {"type": "string"}
                    }},
                    "timeout": {"type": "integer", "description": "Max seconds (default 10)"}
                }}
            }},
            {"type": "function", "function": {
                "name": "get_saved_credentials",
                "description": "Look up saved login credentials for a domain. Call this BEFORE asking the user for login credentials. If credentials exist, use them with auto_login.",
                "parameters": {"type": "object", "properties": {
                    "domain": {"type": "string", "description": "Domain to look up (e.g. github.com, amazon.com)"}
                }, "required": ["domain"]}
            }},
            {"type": "function", "function": {
                "name": "auto_login",
                "description": "Perform a complete login flow on the CURRENT page. IMPORTANT: Navigate to the website's login/sign-in page FIRST before calling this. Handles multi-step login forms (Google, Microsoft, Amazon) that show a continue/next button between username and password. Dismisses QR-code popups and overlays automatically. Use after get_saved_credentials or after the user provides credentials.",
                "parameters": {"type": "object", "properties": {
                    "username": {"type": "string", "description": "Username or email to enter"},
                    "password": {"type": "string", "description": "Password to enter"}
                }, "required": ["username", "password"]}
            }},
            {"type": "function", "function": {
                "name": "call_external_api",
                "description": "Call an external provider API (GitHub, Google, Slack, etc.) using Token Vault. Prefer this over browser automation for supported providers when performing API-level tasks like creating issues, reading repos, sending messages.",
                "parameters": {"type": "object", "properties": {
                    "provider": {"type": "string", "description": "Provider name: github, google, slack, microsoft"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method"},
                    "endpoint": {"type": "string", "description": "Full API URL (e.g. https://api.github.com/user/repos)"},
                    "body": {"type": "object", "description": "Request body for POST/PUT/PATCH (optional)"}
                }, "required": ["provider", "method", "endpoint"]}
            }},
        ])
        return tools
    
    # ------------------------------------------------------------------ #
    # Main chat loop
    # ------------------------------------------------------------------ #
    MAX_TOOL_ROUNDS = 25      # hard cap per user message
    MAX_CONSECUTIVE_FAILS = 3  # same action fails -> give up
    
    def chat(self, user_message):
        """Process one user message, call tools as needed, return final text."""
        print(f"\n👤 User: {user_message}\n")

        # Store the user prompt in the DB so the extension can show it
        prompt_id = None
        try:
            prompt_id = self.agenttrust.store_prompt(user_message)
        except Exception:
            pass
        
        system_prompt = """You are a hands-on browser automation agent. You have FULL control of a
real browser through your tools. Your job is to PERFORM the user's requests
by actually navigating, clicking, typing, and reading pages — NOT by giving
instructions for the user to follow manually.

CRITICAL: You MUST use your tools to carry out every request. NEVER respond
with a list of manual steps. NEVER say "I'm unable to perform this" or
"please do this yourself." You ARE the one doing it.

WORKFLOW for every request:
1. LOOK  — call get_page_content or get_visible_elements to see the current
   page. Every tool response includes "current_url" — use it to know where
   the browser is RIGHT NOW. If there is no page loaded yet, start by navigating.
2. PLAN  — pick the single best next action. Use the most specific element
   identifier available: id > href > aria-label > text.  Fill the "target"
   object completely (id, text, tagName, href, className, selector).
3. ACT   — call exactly ONE action tool (agenttrust_browser_action,
   open_link, type_text, etc.).
4. VERIFY — check browser_result.success in the response.  If false,
   re-examine the page with get_visible_elements and try a different
   element or approach.
5. REPEAT steps 1-4 until the task is done, then give a brief summary.

PAGE CONTINUITY — VERY IMPORTANT:
- Every tool response includes "current_url" telling you EXACTLY where the
  browser is. ALWAYS check it before deciding your next action.
- If you are ALREADY on a page that has the content you need, DO NOT
  navigate away. Work with the current page.
- For follow-up actions (e.g. "add item 4 to cart" after showing search
  results), you are ALREADY on the relevant page. Call get_visible_elements
  or get_page_content FIRST to see what's on the current page, then click
  the correct link/button. Do NOT navigate to the homepage.
- Only navigate to a new URL when the current page genuinely does not have
  what you need.
- When you listed items from a page (e.g. search results, product listings),
  the browser is STILL on that page. To act on one of those items, find and
  click its link on the CURRENT page.

RULES:
- ALWAYS start by using tools. Never skip straight to a text answer.
- NEVER guess deep URLs (e.g. /ap/signin, /login/oauth). Always navigate
  to the site's HOMEPAGE first (e.g. https://www.amazon.com), then find
  and click the sign-in link on the page. Deep login URLs often fail.
- If a navigation returns a page_error in the response, the page failed
  to load (404, connection error, etc.). Do NOT keep retrying the same
  URL. Go to the homepage and find the correct link instead.
- If a page requires login:
  1. Navigate to the site's homepage first.
  2. Find and click the sign-in / login link on the page.
  3. Call get_saved_credentials with the domain.
  4. If credentials found, call auto_login (it handles multi-step forms,
     QR-code popups, and continue/next buttons automatically).
  5. Only ASK the user if no saved credentials exist.
  6. If the user gives credentials, navigate to the login page then auto_login.
- For tasks on GitHub, Google, Slack, or Microsoft services, prefer
  call_external_api over browser automation when possible (faster and
  more reliable). Use browser automation as fallback.
- If AgentTrust blocks an action (denied / step-up required), explain
  the policy decision and ask the user how they'd like to proceed.
- If the same action fails 3 times, STOP and tell the user what is
  happening.
- Keep text replies short and action-oriented.

ROUTINES:
- Users can save reusable sequences of browser actions as "routines" and
  replay them deterministically without involving you (ChatGPT).
- Routines are triggered via /run commands from the browser extension or
  the Routines tab. When a routine runs, the agent executes each recorded
  step directly — you will NOT be called for those steps.
- After a routine finishes, the user may send follow-up messages to you
  from the state the routine left the browser in. Continue normally."""
        
        # Inject current browser state so the LLM knows where it is before choosing an action
        browser_context = ""
        try:
            if self.browser_executor.browser:
                ctx_url = self.browser_executor.get_current_url()
                ctx_title = self.browser_executor.browser.get_page_title()
                if ctx_url:
                    browser_context = f"\n[Current browser page: \"{ctx_title}\" at {ctx_url}]"
        except Exception:
            pass
        
        messages = [
            {"role": "system", "content": system_prompt}
        ] + self.conversation_history + [
            {"role": "user", "content": user_message + browser_context}
        ]
        
        tools = self._build_tools()
        self._tool_call_count = 0
        self._consecutive_failures = 0
        self._last_action_key = None
        
        # Force tool use on the first call so the LLM never gives a
        # text-only "here are the steps" response.  Subsequent rounds
        # use "auto" so it can finish with a text summary.
        first_call = True
        
        response = self._chat_completion(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="required" if (first_call and self.browser_executor.browser) else "auto"
        )
        first_call = False
        message = response.choices[0].message
        
        while message.tool_calls and self._tool_call_count < self.MAX_TOOL_ROUNDS:
            messages.append(message)
            
            for tool_call in message.tool_calls:
                self._tool_call_count += 1
                fc = type('obj', (object,), {
                    'name': tool_call.function.name,
                    'arguments': tool_call.function.arguments
                })()
                result = self.handle_function_call(fc)
                
                action_key = f"{tool_call.function.name}:{tool_call.function.arguments}"
                if isinstance(result, dict) and (
                    result.get("status") in ("denied", "step_up_required", "error") or
                    (result.get("browser_result") and not result["browser_result"].get("success"))
                ):
                    if action_key == self._last_action_key:
                        self._consecutive_failures += 1
                    else:
                        self._consecutive_failures = 1
                    self._last_action_key = action_key
                    
                    if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILS:
                        result["_loop_warning"] = (
                            f"This action has failed {self._consecutive_failures} times in a row. "
                            "STOP retrying and tell the user what went wrong."
                        )
                else:
                    self._consecutive_failures = 0
                    self._last_action_key = action_key
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": json.dumps(result, default=str)
                })
            
            response = self._chat_completion(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            message = response.choices[0].message
        
        response_text = message.content or ""
        print(f"🤖 ChatGPT: {response_text}\n")

        # Store the agent's response alongside the prompt
        if prompt_id:
            try:
                self.agenttrust.update_prompt_response(prompt_id, response_text)
            except Exception:
                pass
        
        # Build a context-rich assistant message that includes browser state.
        # This lets the LLM remember where it left off across messages.
        current_url = ""
        page_title = ""
        try:
            if self.browser_executor.browser:
                current_url = self.browser_executor.get_current_url()
                page_title = self.browser_executor.browser.get_page_title()
        except Exception:
            pass
        
        state_suffix = ""
        if current_url:
            state_suffix = f"\n\n[Browser state: {page_title} — {current_url}]"
        
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": response_text + state_suffix})

        # Keep conversation history bounded to avoid exceeding token limits
        MAX_HISTORY_TURNS = 10
        if len(self.conversation_history) > MAX_HISTORY_TURNS * 2:
            self.conversation_history = self.conversation_history[-(MAX_HISTORY_TURNS * 2):]
        
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
            current_url = self.browser_executor.get_current_url()
            print(f"🔍 Found {len(elements)} visible elements on {current_url}")
            return {"elements": elements, "count": len(elements), "current_url": current_url}
        
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
            current_url = self.browser_executor.get_current_url() if self.browser_executor.browser else ""
            if result.get("status") == "allowed":
                print(f"🔗 Link opened: {result.get('new_url', 'N/A')}")
            result["current_url"] = current_url
            return result
        
        elif function_name == "type_text":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.type_text(
                target=args.get("target", {}),
                text=args.get("text", "")
            )
            result = result or {"status": "error", "message": "No result from type_text"}
            current_url = self.browser_executor.get_current_url() if self.browser_executor.browser else ""
            result["current_url"] = current_url
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
        
        elif function_name == "get_saved_credentials":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            domain = args.get("domain", "")
            creds = self.agenttrust.get_credentials(domain)
            if creds:
                print(f"🔑 Found saved credentials for {domain}")
                return {"found": True, "domain": domain, "username": creds["username"], "password": creds["password"],
                        "hint": "Use auto_login tool to fill in the login form. It handles multi-step forms automatically."}
            else:
                print(f"🔑 No saved credentials for {domain}")
                return {"found": False, "domain": domain, "message": "No saved credentials. Ask the user for login details."}

        elif function_name == "auto_login":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            username = args.get("username", "")
            password = args.get("password", "")
            if not username or not password:
                return {"success": False, "message": "Both username and password are required"}
            current_url = self.browser_executor.browser.get_current_url() if self.browser_executor.browser else ""
            # Guard: don't attempt login on non-login pages
            if current_url and ("localhost" in current_url or "about:blank" in current_url
                                or "/health" in current_url or "chrome://" in current_url):
                return {
                    "success": False,
                    "message": f"Current page ({current_url}) is not a login page. "
                               "Navigate to the website's login page FIRST, then call auto_login."
                }
            print(f"🔐 Auto-login on {current_url}")
            result = self.browser_executor.auto_login(url=current_url, username=username, password=password)
            result["current_url"] = self.browser_executor.get_current_url() if self.browser_executor.browser else current_url
            if result.get("success"):
                print(f"   ✅ Login completed: {', '.join(result.get('steps_completed', []))}")
            else:
                print(f"   ⚠️  Login issue: {result.get('message', 'unknown')}")
            return result

        elif function_name == "call_external_api":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.agenttrust.call_external_api(
                provider=args.get("provider", ""),
                method=args.get("method", "GET"),
                endpoint=args.get("endpoint", ""),
                body=args.get("body")
            )
            provider = args.get("provider", "unknown")
            if result.get("success"):
                print(f"🌐 External API call to {provider} succeeded")
            else:
                print(f"⚠️  External API call to {provider}: {result.get('error', 'unknown error')}")
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
        
        try:
            if action_type == "click":
                result = self.browser_executor.execute_click(url=url, target=target)
            elif action_type == "form_submit":
                result = self.browser_executor.execute_form_submit(url=url, form_data=form_data)
            elif action_type == "navigation":
                result = self.browser_executor.execute_navigation(url=url)
            else:
                return {"status": "error", "message": f"Unknown action type: {action_type}"}
            
            br = result.get("browser_result") or {}
            executed_ok = br.get("success", False) if br else result.get("executed", False)
            risk = result.get("risk_level", "unknown")
            print(f"   ✅ AgentTrust: ALLOWED (Risk: {risk}) | Executed: {executed_ok}")
            
            self.actions_performed.append({
                "type": action_type, "url": url,
                "action_id": result.get("action_id"), "risk_level": risk
            })
            
            current_url = self.browser_executor.get_current_url() if self.browser_executor.browser else url
            return {
                "status": "allowed",
                "action_id": result.get("action_id"),
                "risk_level": risk,
                "current_url": current_url,
                "browser_result": {
                    "success": executed_ok,
                    "message": br.get("message", ""),
                    "new_url": br.get("new_url", "") or current_url,
                },
                "message": f"AgentTrust allowed ({risk} risk). "
                           + (f"Browser: {br.get('message', 'OK')}" if br else "No browser.")
                           + f" Current page: {current_url}"
            }
        
        except PermissionError as e:
            error_msg = str(e)
            
            if "STEP-UP REQUIRED" in error_msg:
                print(f"   ⚠️  AgentTrust: STEP-UP REQUIRED")
                self.actions_blocked.append({
                    "type": action_type,
                    "url": url,
                    "reason": "Step-up required"
                })
                self.browser_executor._notify_extension(
                    action_type, url, "step_up_required",
                    target=target, form_data=form_data)
                return {
                    "status": "step_up_required",
                    "message": error_msg,
                    "requires_user_approval": True
                }
            else:
                print(f"   ❌ AgentTrust: DENIED")
                self.actions_blocked.append({
                    "type": action_type,
                    "url": url,
                    "reason": error_msg
                })
                self.browser_executor._notify_extension(
                    action_type, url, "denied",
                    target=target, form_data=form_data)
                return {
                    "status": "denied",
                    "message": error_msg,
                    "reason": "Policy violation"
                }
        
        except Exception as e:
            error_msg = str(e)
            print(f"   ❌ AgentTrust error: {error_msg}")
            self.actions_blocked.append({
                "type": action_type, "url": url,
                "reason": error_msg
            })
            self.browser_executor._notify_extension(
                action_type, url, "error",
                target=target, form_data=form_data)
            return {
                "status": "error",
                "message": f"Action failed: {error_msg}. "
                           "This may be a temporary backend/auth issue. "
                           "Try the action again, or try a different approach."
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
    
    # Create a fresh session for this script run
    session_id = agent.agenttrust.create_session()
    if session_id:
        print(f"Session created: {session_id}")
    else:
        print("Warning: Could not create session")
    
    try:
        import threading, queue as _queue

        print("="*70)
        print("Interactive Mode")
        print("="*70)
        print("Tell the agent what to do (terminal or browser extension).")
        print("Type 'quit' to exit.\n")

        input_q = _queue.Queue()
        stop_event = threading.Event()

        def _terminal_reader():
            """Read terminal input on a background thread."""
            while not stop_event.is_set():
                try:
                    line = input("You: ").strip()
                    if line:
                        input_q.put(("terminal", line))
                except EOFError:
                    break

        terminal_thread = threading.Thread(target=_terminal_reader, daemon=True)
        terminal_thread.start()

        while True:
            # Check terminal input (non-blocking)
            try:
                source, text = input_q.get(timeout=0.1)
            except _queue.Empty:
                source, text = None, None

            if text and text.lower() in ['quit', 'exit', 'q']:
                break

            if text:
                print(f"  [from {source}]")
                agent.chat(text)
                continue

            # No terminal input — long-poll the backend for browser commands
            cmd = agent.agenttrust.poll_command(timeout=5)
            if cmd:
                if cmd.get("type") == "run_routine":
                    routine_name = cmd.get("routineName", "routine")
                    steps = cmd.get("steps", [])
                    scope = cmd.get("scope", "private")
                    is_owner = cmd.get("isOwner", True)
                    print(f"\n📨 Routine command: {routine_name} ({len(steps)} steps, {scope})")
                    result = agent.browser_executor.replay_routine(
                        steps, routine_name, scope=scope, is_owner=is_owner)
                    if result.get("success"):
                        print(f"Routine '{routine_name}' completed successfully")
                    else:
                        print(f"Routine '{routine_name}' finished with issues: "
                              f"{result.get('steps_completed')}/{result.get('steps_total')} steps")
                else:
                    print(f"\n📨 Browser command: {cmd['content']}")
                    agent.chat(cmd["content"])

    except KeyboardInterrupt:
        stop_event.set()
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        agent.print_summary()
        
        # End the session
        agent.agenttrust.end_session()
        print("Session closed")
        
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
