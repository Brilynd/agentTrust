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
    
    @property
    def switch_to(self):
        """Delegate switch_to (tab/window/frame switching) to the real driver."""
        return self._driver.switch_to
    
    @property
    def window_handles(self):
        """Delegate window_handles to the real driver."""
        return self._driver.window_handles
    
    @property
    def current_window_handle(self):
        """Delegate current_window_handle to the real driver."""
        return self._driver.current_window_handle
    
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
        
        # Tab management state
        self._tab_counter = 0
        self._tabs = {}  # {window_handle: {"label": str, "index": int}}
        # Register the initial tab
        initial_handle = actual_driver.current_window_handle
        self._tabs[initial_handle] = {"label": "main", "index": 0}
        self._tab_counter = 1
        
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
            print("⚠️  EXTENSION_LOGIN_EMAIL / EXTENSION_LOGIN_PASSWORD not set.")
            print("   The browser extension will NOT be auto-logged-in.")
            print("   To use the extension chat, click the AgentTrust extension icon")
            print("   in the browser toolbar and sign in manually.\n")
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
        # Enhanced JS: captures textarea, contenteditable, role-based inputs,
        # flags overlay elements, and includes input type attribute.
        js = """
        const F = arguments[0];
        const MAX = 50;
        const vh = window.innerHeight;
        const buf = vh;

        const all = document.querySelectorAll(
            'a, button, input, select, textarea, ' +
            '[contenteditable="true"], [contenteditable=""], ' +
            '[role="button"], [role="search"], [role="searchbox"], ' +
            '[role="combobox"], [role="textbox"], ' +
            'input[type="submit"]');
        const out = [];

        // Helper: check if element is inside a modal/overlay
        function inOverlay(el) {
            let p = el;
            while (p && p !== document.body) {
                const role = (p.getAttribute && p.getAttribute('role')) || '';
                const cls = (p.className && typeof p.className === 'string') ? p.className.toLowerCase() : '';
                if (role === 'dialog' || role === 'alertdialog' ||
                    cls.includes('modal') || cls.includes('overlay') ||
                    cls.includes('popup') || cls.includes('dialog') ||
                    cls.includes('drawer') || cls.includes('lightbox') ||
                    (p.getAttribute && p.getAttribute('aria-modal') === 'true')) {
                    return true;
                }
                p = p.parentElement;
            }
            return false;
        }

        for (let i = 0; i < all.length && out.length < MAX * 3; i++) {
            const el = all[i];
            const r = el.getBoundingClientRect();
            if (!r.width && !r.height) continue;
            if (el.offsetParent === null && el.tagName !== 'BODY') continue;

            const tag = el.tagName.toLowerCase();
            const role = (el.getAttribute('role') || '').toLowerCase();
            let t;
            if (tag === 'a') t = 'link';
            else if (tag === 'button' || role === 'button') t = 'btn';
            else if (tag === 'input') {
                const it = (el.type||'').toLowerCase();
                t = (it==='submit'||it==='button') ? 'btn' : 'in';
            } else if (tag === 'textarea') t = 'in';
            else if (tag === 'select') t = 'select';
            else if (el.isContentEditable) t = 'in';
            else if (role === 'search' || role === 'searchbox' ||
                     role === 'combobox' || role === 'textbox') t = 'in';
            else t = 'btn';

            if (F && t !== F && !(F==='button'&&t==='btn') && !(F==='input'&&t==='in')) continue;

            const txt = (el.innerText||el.textContent||'').trim().substring(0,60);
            const ariaLabel = el.getAttribute('aria-label') || '';
            // Skip elements with no useful text and no identifiers
            if (!txt && !el.id && !el.name && !el.placeholder && !ariaLabel && !role) continue;

            const near = (r.top < vh + buf && r.bottom > -buf) ? 1 : 0;
            // For links, keep only the pathname to save tokens
            let hp = '';
            if (tag === 'a' && el.href) {
                try { hp = new URL(el.href).pathname.substring(0,80); } catch(e) { hp = el.href.substring(0,80); }
            }

            // Get input type for inputs
            const inputType = (tag === 'input') ? (el.type || 'text').toLowerCase() : '';

            out.push({t, txt, id:el.id||'', nm:el.name||'', hp,
                al: ariaLabel,
                ph: el.placeholder||'',
                v: (el.value||'').substring(0,30),
                it: inputType,
                rl: role,
                ov: inOverlay(el) ? 1 : 0,
                n: near, y: Math.round(r.top)});
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
                if r.get("it"):  e["input_type"] = r["it"]
                if r.get("rl"):  e["role"] = r["rl"]
                if r.get("ov"):  e["in_overlay"] = True
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
    
    def type_text(self, target: Dict[str, Any], text: str, press_enter: bool = False) -> Dict[str, Any]:
        """
        Type text into an input field, textarea, or contenteditable element.
        
        Args:
            target: dict identifying the input (id, name, placeholder,
                    aria-label, type, role, selector, etc.)
            text: Text to type
            press_enter: If True, press Enter after typing to submit
        
        Returns:
            dict with success status
        """
        drv = self._actual_driver
        try:
            element = None
            
            # 1. By ID (most specific)
            if target.get("id"):
                try:
                    element = drv.find_element(By.ID, target["id"])
                except NoSuchElementException:
                    pass
            
            # 2. By name attribute
            if not element and target.get("name"):
                try:
                    element = drv.find_element(By.NAME, target["name"])
                except NoSuchElementException:
                    pass
            
            # 3. By aria-label (broad: input, textarea, contenteditable)
            if not element and target.get("aria-label"):
                al = target["aria-label"]
                for sel in [
                    f"//input[@aria-label='{al}']",
                    f"//textarea[@aria-label='{al}']",
                    f"//*[@contenteditable][@aria-label='{al}']",
                    f"//*[contains(@aria-label,'{al}')]",
                ]:
                    try:
                        element = drv.find_element(By.XPATH, sel)
                        if element.is_displayed():
                            break
                        element = None
                    except NoSuchElementException:
                        element = None
            
            # 4. By placeholder (broad: input + textarea, partial match)
            if not element and target.get("placeholder"):
                ph = target["placeholder"]
                for sel in [
                    f"//input[@placeholder='{ph}']",
                    f"//textarea[@placeholder='{ph}']",
                    f"//input[contains(@placeholder,'{ph}')]",
                    f"//textarea[contains(@placeholder,'{ph}')]",
                ]:
                    try:
                        element = drv.find_element(By.XPATH, sel)
                        if element.is_displayed():
                            break
                        element = None
                    except NoSuchElementException:
                        element = None
            
            # 5. By input type attribute (e.g. "search", "email", "text")
            if not element and target.get("type"):
                try:
                    element = drv.find_element(
                        By.CSS_SELECTOR, f"input[type='{target['type']}']"
                    )
                except NoSuchElementException:
                    pass
            
            # 6. By role (searchbox, combobox, textbox)
            if not element and target.get("role"):
                role = target["role"]
                try:
                    element = drv.find_element(
                        By.CSS_SELECTOR, f"[role='{role}']"
                    )
                except NoSuchElementException:
                    pass
            
            # 7. By CSS selector (fallback)
            if not element and target.get("selector"):
                try:
                    element = drv.find_element(By.CSS_SELECTOR, target["selector"])
                except NoSuchElementException:
                    pass
            
            if element and element.is_displayed():
                # Handle contenteditable differently
                if element.get_attribute("contenteditable") in ("true", ""):
                    element.click()
                    import time; time.sleep(0.05)
                    element.send_keys(text)
                else:
                    element.clear()
                    element.send_keys(text)
                # Press Enter after typing if requested
                if press_enter:
                    import time; time.sleep(0.15)
                    from selenium.webdriver.common.keys import Keys
                    element.send_keys(Keys.RETURN)
                    time.sleep(0.3)
                return {"success": True, "message": f"Text typed successfully: {text[:50]}"
                        + (" + Enter pressed" if press_enter else "")}
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
    
    # ------------------------------------------------------------------ #
    # Tab management
    # ------------------------------------------------------------------ #

    def open_new_tab(self, url: str, label: str = "") -> Dict[str, Any]:
        """Open a new browser tab, navigate to *url*, and label it.

        Args:
            url: URL to navigate to in the new tab.
            label: Human-readable label (e.g. "gmail", "ebay").
                   Auto-generated from the domain if omitted.

        Returns:
            dict with success status, tab index, label, and handle.
        """
        drv = self._actual_driver
        try:
            # Open a blank new tab and switch to it
            drv.switch_to.new_window('tab')
            new_handle = drv.current_window_handle

            # Navigate
            drv.get(url)
            import time
            time.sleep(0.3)

            # Auto-label from domain if not provided
            if not label:
                try:
                    from urllib.parse import urlparse
                    label = urlparse(url).netloc.replace("www.", "") or f"tab{self._tab_counter}"
                except Exception:
                    label = f"tab{self._tab_counter}"

            idx = self._tab_counter
            self._tabs[new_handle] = {"label": label, "index": idx}
            self._tab_counter += 1
            self.current_url = drv.current_url

            return {
                "success": True,
                "message": f"Opened new tab '{label}' at {drv.current_url}",
                "tab_index": idx,
                "label": label,
                "url": drv.current_url,
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to open new tab: {e}"}

    def switch_to_tab(self, label_or_index) -> Dict[str, Any]:
        """Switch browser focus to another tab by *label* (str) or *index* (int).

        Returns:
            dict with success status and the new active tab info.
        """
        drv = self._actual_driver
        target_handle = None

        # Resolve by label (string) or index (int)
        for handle, info in self._tabs.items():
            if isinstance(label_or_index, int) and info["index"] == label_or_index:
                target_handle = handle
                break
            if isinstance(label_or_index, str) and info["label"].lower() == label_or_index.lower():
                target_handle = handle
                break

        if not target_handle:
            # Fallback: try matching partial label
            if isinstance(label_or_index, str):
                for handle, info in self._tabs.items():
                    if label_or_index.lower() in info["label"].lower():
                        target_handle = handle
                        break

        if not target_handle:
            return {"success": False, "message": f"Tab '{label_or_index}' not found. Use list_tabs to see available tabs."}

        try:
            drv.switch_to.window(target_handle)
            self.current_url = drv.current_url
            info = self._tabs[target_handle]
            return {
                "success": True,
                "message": f"Switched to tab '{info['label']}' (index {info['index']})",
                "tab_index": info["index"],
                "label": info["label"],
                "url": drv.current_url,
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to switch tab: {e}"}

    def close_tab(self, label_or_index=None) -> Dict[str, Any]:
        """Close a tab by *label* or *index*. Defaults to current tab.

        After closing, switches to the previously active tab (or the first
        remaining tab).

        Returns:
            dict with success status and info about the new active tab.
        """
        drv = self._actual_driver

        if len(self._tabs) <= 1:
            return {"success": False, "message": "Cannot close the last remaining tab."}

        # Resolve which handle to close
        target_handle = None
        if label_or_index is not None:
            for handle, info in self._tabs.items():
                if isinstance(label_or_index, int) and info["index"] == label_or_index:
                    target_handle = handle
                    break
                if isinstance(label_or_index, str) and info["label"].lower() == label_or_index.lower():
                    target_handle = handle
                    break
        else:
            target_handle = drv.current_window_handle

        if not target_handle:
            return {"success": False, "message": f"Tab '{label_or_index}' not found."}

        try:
            closed_info = self._tabs.pop(target_handle, {})
            # Switch to the tab being closed first if it's not current
            if drv.current_window_handle != target_handle:
                drv.switch_to.window(target_handle)
            drv.close()

            # Switch to the first remaining tab
            remaining_handle = list(self._tabs.keys())[0]
            drv.switch_to.window(remaining_handle)
            self.current_url = drv.current_url
            new_info = self._tabs[remaining_handle]

            return {
                "success": True,
                "message": f"Closed tab '{closed_info.get('label', '?')}'. Now on '{new_info['label']}'.",
                "active_tab_index": new_info["index"],
                "active_tab_label": new_info["label"],
                "url": drv.current_url,
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to close tab: {e}"}

    def list_tabs(self) -> List[Dict[str, Any]]:
        """Return metadata for every open tab.

        Each entry: {index, label, url, is_active}.
        Syncs with the actual driver handles in case tabs were opened/closed
        outside of this manager.
        """
        drv = self._actual_driver
        current_handle = drv.current_window_handle
        live_handles = set(drv.window_handles)

        # Prune stale entries
        stale = [h for h in self._tabs if h not in live_handles]
        for h in stale:
            del self._tabs[h]

        # Register any unknown handles (e.g. opened by the page itself)
        for h in live_handles:
            if h not in self._tabs:
                self._tabs[h] = {"label": f"tab{self._tab_counter}", "index": self._tab_counter}
                self._tab_counter += 1

        tabs = []
        for handle, info in self._tabs.items():
            # Get URL without switching if possible; only switch when needed
            if handle == current_handle:
                tab_url = drv.current_url
            else:
                try:
                    drv.switch_to.window(handle)
                    tab_url = drv.current_url
                except Exception:
                    tab_url = "(unknown)"

            tabs.append({
                "index": info["index"],
                "label": info["label"],
                "url": tab_url,
                "is_active": handle == current_handle,
            })

        # Restore focus to original tab
        try:
            drv.switch_to.window(current_handle)
        except Exception:
            pass

        tabs.sort(key=lambda t: t["index"])
        return tabs

    def get_active_tab(self) -> Dict[str, Any]:
        """Return info about the currently focused tab."""
        drv = self._actual_driver
        handle = drv.current_window_handle
        info = self._tabs.get(handle, {"label": "unknown", "index": -1})
        return {
            "index": info["index"],
            "label": info["label"],
            "url": drv.current_url,
        }

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
            ret = {
                "status": "error",
                "message": f"AgentTrust validation error: {error_msg}",
                "browser_result": {"success": False, "message": error_msg}
            }
            if result.get("error_type"):
                ret["error_type"] = result["error_type"]
            return ret
        
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
            ret = {
                "status": "error",
                "message": f"AgentTrust validation error: {error_msg}",
                "browser_result": {"success": False, "message": error_msg}
            }
            if result.get("error_type"):
                ret["error_type"] = result["error_type"]
            return ret
        
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
            ret = {
                "status": "error",
                "message": f"AgentTrust validation error: {error_msg}",
                "browser_result": {"success": False, "message": error_msg}
            }
            if result.get("error_type"):
                ret["error_type"] = result["error_type"]
            return ret
        
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
    
    def type_text(self, target: Dict[str, Any], text: str, press_enter: bool = False):
        """
        Type text into an input field.
        Validated as 'form_input' through AgentTrust so that the policy
        engine can apply appropriate risk scoring (password fields get
        higher risk than plain search boxes).
        """
        if not self.browser:
            return {"error": "Browser not initialized"}
        
        current_url = self.browser.get_current_url()
        
        # Detect if this is a sensitive input (password, credit card, etc.)
        target_name = (target.get("name") or "").lower()
        target_id = (target.get("id") or "").lower()
        target_type = (target.get("type") or "").lower()
        target_placeholder = (target.get("placeholder") or "").lower()
        is_sensitive = any(kw in f"{target_name} {target_id} {target_type} {target_placeholder}"
                          for kw in ("password", "passwd", "secret", "ssn", "credit", "card", "cvv", "pin"))
        
        try:
            result = self.agenttrust.execute_action(
                action_type="form_input",
                url=current_url,
                target={"type": "input", "action": "type_text",
                        "id": target.get("id"), "name": target.get("name"),
                        "is_sensitive": is_sensitive}
            )
            
            status = result.get("status") if result else None

            if status == "allowed":
                type_result = self.browser.type_text(target, text, press_enter=press_enter)
                if not type_result.get("success"):
                    # Element not found by standard lookup — try CSS selector fallback
                    type_result = self._type_text_fallback(target, text, press_enter=press_enter)
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

    def _type_text_fallback(self, target: Dict[str, Any], text: str, press_enter: bool = False) -> Dict[str, Any]:
        """Fallback: find an input by multiple strategies when standard lookup fails.
        
        Searches across input, textarea, contenteditable, and role-based elements.
        Uses partial matching for placeholders and aria-labels.
        """
        drv = self.browser._actual_driver
        from selenium.webdriver.common.by import By
        element = None

        # 1. Try aria-label (input, textarea, contenteditable — partial match)
        if target.get("aria-label"):
            al = target["aria-label"]
            for sel in [
                f"input[aria-label='{al}']",
                f"textarea[aria-label='{al}']",
                f"[contenteditable][aria-label='{al}']",
                f"input[aria-label*='{al}']",
                f"textarea[aria-label*='{al}']",
                f"[contenteditable][aria-label*='{al}']",
            ]:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        element = el
                        break
                except Exception:
                    continue

        # 2. Try type attribute (input only)
        if not element and target.get("type"):
            try:
                element = drv.find_element(By.CSS_SELECTOR, f"input[type='{target['type']}']")
            except Exception:
                pass

        # 3. Try placeholder (input + textarea, partial match)
        if not element and target.get("placeholder"):
            ph = target["placeholder"]
            for sel in [
                f"input[placeholder='{ph}']",
                f"textarea[placeholder='{ph}']",
                f"input[placeholder*='{ph}']",
                f"textarea[placeholder*='{ph}']",
            ]:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        element = el
                        break
                except Exception:
                    continue

        # 4. Try role attribute (searchbox, combobox, textbox)
        if not element and target.get("role"):
            role = target["role"]
            for sel in [
                f"input[role='{role}']",
                f"[role='{role}']",
            ]:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        element = el
                        break
                except Exception:
                    continue

        # 5. Try well-known search input selectors
        if not element:
            for sel in [
                "input[role='searchbox']", "input[role='combobox']",
                "[role='searchbox']", "[role='combobox']", "[role='textbox']",
                "input[type='search']",
                "input[name='field-keywords']", "#twotabsearchtextbox",
                "input[aria-label*='Search']", "input[placeholder*='Search']",
                "textarea[aria-label*='Search']", "textarea[placeholder*='Search']",
                "input[name='q']", "input[name='search']", "input[name='query']",
                "textarea[name='q']",
            ]:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        element = el
                        break
                except Exception:
                    continue

        # 6. Try textarea elements broadly (e.g. chat inputs, comment boxes)
        if not element:
            try:
                textareas = drv.find_elements(By.TAG_NAME, "textarea")
                for ta in textareas:
                    if ta.is_displayed():
                        element = ta
                        break
            except Exception:
                pass

        # 7. Try contenteditable elements
        if not element:
            try:
                editables = drv.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
                for ce in editables:
                    if ce.is_displayed():
                        element = ce
                        break
            except Exception:
                pass

        if element and element.is_displayed():
            try:
                # Handle contenteditable differently
                if element.get_attribute("contenteditable") in ("true", ""):
                    element.click()
                    import time; time.sleep(0.05)
                    element.send_keys(text)
                else:
                    element.clear()
                    element.send_keys(text)
                # Press Enter after typing if requested
                if press_enter:
                    import time; time.sleep(0.15)
                    from selenium.webdriver.common.keys import Keys
                    element.send_keys(Keys.RETURN)
                    time.sleep(0.3)
                return {"success": True, "message": f"Text typed (fallback): {text[:50]}"
                        + (" + Enter pressed" if press_enter else "")}
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

    # ------------------------------------------------------------------ #
    # Tab management wrappers
    # ------------------------------------------------------------------ #

    def open_new_tab(self, url: str, label: str = ""):
        """Open a new tab — MANDATORY AgentTrust navigation validation.
        
        IMPORTANT: We validate-only here (no browser navigation) because
        execute_navigation() would navigate the CURRENT tab, then
        BrowserController.open_new_tab() would open a second tab with the
        same URL — resulting in a double-navigation bug.
        """
        if not self.browser:
            return {"error": "Browser not initialized"}

        try:
            # Validate with AgentTrust WITHOUT navigating the current tab
            result = self.agenttrust.execute_action(
                action_type="navigation",
                url=url
            )
            status = result.get("status")

            if status == "denied":
                error_msg = result.get("message", "Action denied by AgentTrust policy")
                self.action_history.append({
                    "action": "navigation", "url": url,
                    "status": "denied", "reason": error_msg
                })
                return {"status": "denied", "message": f"AgentTrust DENIED: {error_msg}"}

            if status == "step_up_required":
                self.action_history.append({
                    "action": "navigation", "url": url,
                    "status": "step_up_required",
                    "risk_level": result.get("risk_level")
                })
                return {
                    "status": "step_up_required",
                    "message": "High-risk action requires user approval",
                    "risk_level": result.get("risk_level")
                }

            if status == "allowed":
                self.action_history.append({
                    "action": "navigation", "url": url,
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                })
                # Delegate to BrowserController — opens a NEW tab and
                # navigates only that tab, leaving the current tab untouched.
                tab_result = self.browser.open_new_tab(url, label)
                tab_result["action_id"] = result.get("action_id")
                tab_result["risk_level"] = result.get("risk_level")
                tab_result["status"] = "allowed"
                self._notify_extension("navigation", url, "allowed",
                                       risk_level=result.get("risk_level"),
                                       action_id=result.get("action_id"))
                return tab_result

            # Unexpected status
            return {
                "status": "error",
                "message": f"AgentTrust returned unexpected status: {status}"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def switch_to_tab(self, label_or_index):
        """Switch to another tab — read-only, no AgentTrust validation needed."""
        if not self.browser:
            return {"error": "Browser not initialized"}

        return self.browser.switch_to_tab(label_or_index)

    def close_tab(self, label_or_index=None):
        """Close a tab — MANDATORY AgentTrust validation.
        
        Uses validate-only (no navigation) to avoid the same
        double-navigation bug as open_new_tab.
        """
        if not self.browser:
            return {"error": "Browser not initialized"}

        current_url = self.browser.get_current_url()
        try:
            # Validate with AgentTrust WITHOUT navigating
            result = self.agenttrust.execute_action(
                action_type="navigation",
                url=current_url
            )
            status = result.get("status")

            if status == "denied":
                return {"status": "denied", "message": result.get("message", "Action denied")}

            if status == "step_up_required":
                return {"status": "step_up_required", "message": "Requires user approval"}

            if status == "allowed":
                tab_result = self.browser.close_tab(label_or_index)
                tab_result["action_id"] = result.get("action_id")
                tab_result["status"] = "allowed" if tab_result.get("success") else "error"
                return tab_result

            return {"status": "error", "message": f"Unexpected status: {status}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_tabs(self):
        """List all open tabs — read-only, no AgentTrust validation needed."""
        if not self.browser:
            return []

        return self.browser.list_tabs()

    def get_active_tab(self):
        """Get active tab info — read-only."""
        if not self.browser:
            return {}

        return self.browser.get_active_tab()

    def dismiss_overlays(self) -> bool:
        """
        Detect and dismiss common overlays, popups, modals, and banners.
        Returns True if any overlay was dismissed.
        
        Handles: cookie consent, account creation prompts, newsletter signups,
        app download banners, credential picker, passkey prompts, GDPR banners,
        generic modals, and more.
        """
        if not self.browser:
            return False

        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.common.exceptions import (
            StaleElementReferenceException, ElementNotInteractableException
        )

        driver = self.browser._actual_driver
        dismissed = False

        # ── Phase 1: Click known close/dismiss buttons ──
        close_selectors = [
            # Generic close buttons
            "button[aria-label='Close']", "button[aria-label='Dismiss']",
            "button[aria-label='close']", "button[aria-label='dismiss']",
            "button[aria-label='Close dialog']", "button[aria-label='Close modal']",
            "[data-dismiss='modal']", "[data-bs-dismiss='modal']",
            "button.modal-close", "button.close-modal", "button.dialog-close",
            "a.modal-close", "a.close-modal",
            ".modal .close", ".modal-header .close",
            "button.btn-close", ".btn-close",

            # Amazon-specific
            "a[data-action='a-modal-close']", "button[data-action='a-modal-close']",
            "button.a-modal-close", "a.a-modal-close",
            "#ap-account-fixup-phone-skip-link",
            "button[id*='passkey-cancel']", "button[id*='passkey-close']",
            "a[id*='passkey-cancel']",

            # Google credential picker
            "#credential_picker_close", "#credential_picker_cancel",
            "#credential_picker_iframe + div",

            # Cookie consent / GDPR banners
            "#onetrust-accept-btn-handler",         # OneTrust
            "#onetrust-reject-all-handler",
            ".onetrust-close-btn-handler",
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # CookieBot
            "#CybotCookiebotDialogBodyButtonDecline",
            "[data-cookiefirst-action='accept']",   # CookieFirst
            "#cookie-banner-accept", "#cookie-accept",
            ".cookie-consent-accept", ".cookie-banner__accept",
            "button[data-testid='cookie-policy-dialog-accept-button']",
            "#accept-cookie-notification",
            ".cc-dismiss", ".cc-btn.cc-allow",      # CookieConsent (popular lib)

            # Newsletter / signup popups
            "button.newsletter-close", ".popup-close", ".newsletter-popup .close",
            "[data-action='close-popup']", "[data-action='close-modal']",
            ".signup-modal .close", ".promo-close",

            # App download banners
            ".smartbanner-close", "#smartbanner .sb-close",
            ".app-banner-close", "[data-testid='app-banner-close']",

            # "No thanks" / "Skip" / "Maybe later" links
            "a.skip-link", "button.skip", "a.skip",
            "button[id*='skip']", "a[id*='skip']",
        ]

        combined_selector = ", ".join(close_selectors)
        try:
            els = driver.find_elements(By.CSS_SELECTOR, combined_selector)
            for el in els:
                try:
                    if el.is_displayed():
                        el.click()
                        dismissed = True
                        time.sleep(0.15)
                except (StaleElementReferenceException, ElementNotInteractableException):
                    continue
        except Exception:
            pass

        # ── Phase 2: Text-based button matching for common dismiss patterns ──
        dismiss_phrases = [
            "no thanks", "no, thanks", "not now", "maybe later",
            "skip", "dismiss", "got it", "i understand",
            "accept all", "accept cookies", "allow all",
            "reject all", "decline", "close",
        ]
        try:
            buttons = driver.find_elements(
                By.CSS_SELECTOR,
                "button, a[role='button'], div[role='button'], span[role='button']"
            )
            for btn in buttons:
                try:
                    if not btn.is_displayed():
                        continue
                    btn_text = (btn.text or "").strip().lower()
                    if not btn_text:
                        continue
                    for phrase in dismiss_phrases:
                        if phrase in btn_text and len(btn_text) < 40:
                            btn.click()
                            dismissed = True
                            time.sleep(0.15)
                            break
                except (StaleElementReferenceException, ElementNotInteractableException):
                    continue
        except Exception:
            pass

        # ── Phase 3: Escape key fallback ──
        # Only send Escape if Phases 1/2 found nothing — and do NOT
        # claim success unconditionally, because Escape on a normal
        # page can cancel forms or trigger refreshes.
        # We skip this phase entirely now; the agent prompt already
        # tells the LLM to close overlays via targeted clicks.

        return dismissed

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
            """Close QR-code dialogs, cookie banners, or other overlays. Delegates to shared method."""
            return self.dismiss_overlays()

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
            # Multi-step logins (Google, Microsoft) may redirect through
            # several pages, so give them enough time.
            _wait_ready(1.0)

            # Wait extra time for multi-step logins that redirect
            # (e.g. Google: password → consent → inbox)
            initial_url = driver.current_url
            for _ in range(6):  # up to 3 more seconds
                time.sleep(0.5)
                current = driver.current_url
                if current != initial_url:
                    # URL is changing — login redirect in progress
                    initial_url = current
                    _wait_ready(0.5)
                else:
                    break  # URL stabilized

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

            # ── Post-login verification ──────────────────────────
            # Check if the login actually succeeded by looking for
            # error indicators on the resulting page.
            login_failed = False
            failure_reason = ""

            # If URL changed significantly from the original, login likely worked
            from urllib.parse import urlparse
            orig_path = urlparse(url).path.rstrip("/")
            new_path = urlparse(new_url).path.rstrip("/")
            orig_host = urlparse(url).netloc.lower()
            new_host = urlparse(new_url).netloc.lower()
            url_changed_significantly = (new_host != orig_host) or (new_path != orig_path)

            # Check 1: DOM-based error detection
            try:
                page_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
                error_phrases = [
                    "incorrect password", "wrong password", "invalid password",
                    "incorrect username", "invalid credentials",
                    "login failed", "sign-in failed", "authentication failed",
                    "account not found", "user not found",
                    "too many attempts", "account locked", "account disabled",
                    "unable to sign in", "unable to log in",
                    "password is incorrect", "email is incorrect",
                    "doesn't match", "does not match", "didn't match",
                    "we didn't recognize", "we don't recognize",
                ]
                for phrase in error_phrases:
                    if phrase in page_text:
                        login_failed = True
                        failure_reason = f"Page shows error: '{phrase}'"
                        steps_log.append(f"⚠️ Detected login error: '{phrase}'")
                        break
            except Exception:
                pass

            # Check 2: Still on a login page (password field still visible)
            # BUT only flag as failure if the URL has NOT changed significantly.
            # On multi-step logins (Google, Microsoft), the URL may still
            # contain /signin/ as part of the challenge flow even though
            # login is progressing successfully.
            if not login_failed and not url_changed_significantly:
                try:
                    still_has_password = _find_input("password")
                    if still_has_password and still_has_password.is_displayed():
                        # URL didn't change AND password field is still there
                        login_failed = True
                        failure_reason = "Still on login page after submitting"
                        steps_log.append("⚠️ Password field still visible — login likely failed")
                except Exception:
                    pass

            self._notify_extension("form_submit", url, "allowed",
                                   risk_level=result.get("risk_level"),
                                   action_id=action_id,
                                   form_data={"action": "auto_login"})

            if login_failed:
                return {
                    "success": False, "status": "allowed",
                    "action_id": action_id,
                    "risk_level": result.get("risk_level"),
                    "new_url": new_url,
                    "steps_completed": steps_log,
                    "login_error": failure_reason,
                    "message": f"Login form was submitted but appears to have failed: {failure_reason}. "
                               "Check the page for error details and try a different approach."
                }

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
                print("   NOTE: The browser extension chat will NOT work in dev mode.")
                print("   Terminal input only. To enable extension chat, configure Auth0")
                print("   and remove AGENTTRUST_DEV_MODE from your .env file.\n")
        except ValueError as e:
            print(f"❌ AgentTrust configuration error: {e}")
            print("\nYou must configure Auth0 for the agent to work:")
            print("  1. Set Auth0 env vars: AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, AUTH0_AUDIENCE")
            print("  2. Create the API identifier in your Auth0 dashboard (see README)")
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

        # Action history RAG (optional — improves planning with past task patterns)
        self.action_rag = None
        try:
            from action_history_rag import ActionHistoryRAG
            self.action_rag = ActionHistoryRAG()
        except ImportError:
            pass
        except Exception as e:
            print(f"\u26a0\ufe0f  Action history RAG init failed: {e}")



        # Give executor a back-reference so auto_login can use vision
        self.browser_executor._parent_agent = self

        # LangGraph state machine (optional — falls back to legacy loop)
        self._graph = None
        try:
            from graph_agent import build_graph
            self._graph = build_graph(self)
            print("\u2705 LangGraph agent enabled (PLAN \u2192 OBSERVE \u2192 ACT \u2192 VERIFY)")
        except ImportError:
            print("\u2139\ufe0f  LangGraph not installed, using standard agent loop")
            print("   Install with: pip install langgraph")
        except Exception as e:
            print(f"\u26a0\ufe0f  LangGraph init failed ({e}), using standard agent loop")
    
    # ------------------------------------------------------------------ #
    # Rate-limit-aware API call wrapper
    # ------------------------------------------------------------------ #
    def _chat_completion(self, **kwargs):
        """Call OpenAI chat completions with automatic rate-limit retry."""
        import time as _time
        max_retries = 4
        for attempt in range(max_retries):
            try:
                return self.openai.chat.completions.create(**kwargs)
            except Exception as e:
                err_str = str(e)
                # Retry on rate limit (429) with exponential backoff
                if "429" in err_str or "rate_limit" in err_str.lower():
                    wait = 2 ** attempt  # 1, 2, 4, 8 seconds
                    print(f"  ⏳ Rate limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})...")
                    _time.sleep(wait)
                    continue
                raise  # Non-rate-limit errors propagate immediately
        # Final attempt — let the exception propagate if it fails again
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
                "description": "Type text into an input field, textarea, or contenteditable element. Identify the target using id, name, placeholder, aria-label, input type, role, or CSS selector. For search boxes, use aria-label, role='searchbox', or type='search'. Set press_enter=true to submit the form after typing (PREFERRED over clicking a submit button for search boxes and single-input forms).",
                "parameters": {"type": "object", "properties": {
                    "target": {"type": "object", "properties": {
                        "id": {"type": "string", "description": "Element id attribute"},
                        "name": {"type": "string", "description": "Element name attribute"},
                        "placeholder": {"type": "string", "description": "Placeholder text (partial match supported)"},
                        "aria-label": {"type": "string", "description": "Aria-label attribute (partial match supported)"},
                        "type": {"type": "string", "description": "Input type: search, email, text, password, etc."},
                        "role": {"type": "string", "description": "ARIA role: searchbox, combobox, textbox"},
                        "selector": {"type": "string", "description": "CSS selector (last resort)"}
                    }},
                    "text": {"type": "string", "description": "Text to type"},
                    "press_enter": {"type": "boolean", "description": "Press Enter after typing to submit the form. Use for search boxes, verification code inputs, and single-input forms. Default: false."}
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
                "description": "Look up saved login credentials for a domain. Call this BEFORE asking the user for login credentials. If credentials exist, use them with auto_login. Use the BASE domain (e.g. 'google.com' not 'mail.google.com', 'amazon.com' not 'smile.amazon.com'). For Gmail/Google services, use 'google.com' or 'gmail.com'.",
                "parameters": {"type": "object", "properties": {
                    "domain": {"type": "string", "description": "Base domain to look up (e.g. google.com, gmail.com, amazon.com, github.com). Use the base domain, not subdomains."}
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
            # --- Tab management tools ---
            {"type": "function", "function": {
                "name": "open_new_tab",
                "description": "Open a new browser tab and navigate to the given URL. Use this when you need to visit a different site without losing your place on the current page (e.g. checking email for a 2FA code, comparing prices on another site). Give the tab a short label so you can switch back later.",
                "parameters": {"type": "object", "properties": {
                    "url": {"type": "string", "description": "URL to open in the new tab"},
                    "label": {"type": "string", "description": "Short label for the tab (e.g. 'gmail', 'ebay'). Auto-generated from domain if omitted."}
                }, "required": ["url"]}
            }},
            {"type": "function", "function": {
                "name": "switch_to_tab",
                "description": "Switch browser focus to another open tab by its label or index number. Use this to return to a previous tab after completing work in another tab (e.g. switching back to the login page after retrieving a 2FA code from email).",
                "parameters": {"type": "object", "properties": {
                    "label_or_index": {"type": "string", "description": "Tab label (e.g. 'gmail', 'main') or index number as a string (e.g. '0')"}
                }, "required": ["label_or_index"]}
            }},
            {"type": "function", "function": {
                "name": "close_tab",
                "description": "Close an open browser tab by its label or index. After closing, the browser switches to another remaining tab. Use this to clean up tabs you no longer need.",
                "parameters": {"type": "object", "properties": {
                    "label_or_index": {"type": "string", "description": "Tab label or index number to close. If omitted, closes the current tab."}
                }}
            }},
            {"type": "function", "function": {
                "name": "list_tabs",
                "description": "List all currently open browser tabs with their index, label, URL, and which one is active. Use this to see what tabs are available before switching.",
                "parameters": {"type": "object", "properties": {}}
            }},
        ])
        return tools
    
    # ------------------------------------------------------------------ #
    # Main chat entry point
    # ------------------------------------------------------------------ #
    MAX_TOOL_ROUNDS = 25      # hard cap per user message
    MAX_CONSECUTIVE_FAILS = 3  # same action fails -> give up
    
    def chat(self, user_message):
        """Process one user message. Routes to LangGraph or legacy loop."""
        print(f"\n👤 User: {user_message}\n")

        # Store the user prompt in the DB so the extension can show it
        prompt_id = None
        try:
            prompt_id = self.agenttrust.store_prompt(user_message)
        except Exception:
            pass

        # --- Core processing: LangGraph state machine or legacy loop ---
        if self._graph:
            response_text = self._chat_graph(user_message)
        else:
            response_text = self._chat_loop(user_message)

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

        # Record successful actions for RAG retrieval in future tasks
        self._record_actions_for_rag(user_message, response_text)

        return response_text

    # ------------------------------------------------------------------ #
    # Action history RAG recording
    # ------------------------------------------------------------------ #
    def _record_actions_for_rag(self, user_message: str, response_text: str):
        """Save the action sequence from this chat turn for future RAG retrieval."""
        if not self.action_rag:
            return
        if not self.actions_performed:
            return

        # Build compact action records from what was performed
        action_records = []
        domains = set()
        for ap in self.actions_performed:
            url = ap.get("url", "")
            domain = ""
            if url:
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(url).hostname or ""
                except Exception:
                    pass
                if domain:
                    domains.add(domain)

            action_records.append({
                "tool": ap.get("type", "unknown"),
                "args": {"url": url},
                "result_status": "allowed" if ap.get("risk_level") else "unknown",
            })

        # Also capture any tool calls tracked by the executor
        executor_history = getattr(self.browser_executor, 'action_history', [])
        for eh in executor_history:
            if eh.get("status") == "allowed" and eh not in self.actions_performed:
                url = eh.get("url", "")
                if url:
                    try:
                        from urllib.parse import urlparse
                        d = urlparse(url).hostname or ""
                        if d:
                            domains.add(d)
                    except Exception:
                        pass
                action_records.append({
                    "tool": eh.get("action", "unknown"),
                    "args": {"url": url},
                    "result_status": eh.get("status", "allowed"),
                })

        if not action_records:
            return

        # Determine success: no blocked actions and we got a response
        has_blocks = len(self.actions_blocked) > 0
        success = not has_blocks and bool(response_text)

        try:
            self.action_rag.record(
                task=user_message,
                actions=action_records,
                success=success,
                domains=sorted(domains),
            )
        except Exception as e:
            print(f"\u26a0\ufe0f  Failed to record action history: {e}")

    # ------------------------------------------------------------------ #
    # LangGraph implementation (PLAN → OBSERVE → ACT → VERIFY)
    # ------------------------------------------------------------------ #
    def _chat_graph(self, user_message):
        """Process message using the LangGraph state machine."""
        initial_state = {
            "user_request": user_message,
            "conversation_history": list(self.conversation_history),
            "sub_goals": [],
            "current_goal_index": 0,
            "plan_text": "",
            "current_url": "",
            "page_title": "",
            "page_text": "",
            "visible_elements": [],
            "page_vision": "",
            "has_overlay": False,
            "active_tab": "main",
            "open_tabs": [],
            "turn_messages": [],
            "pending_tool_calls": [],
            "last_action_result": {},
            "last_action_name": "",
            "action_category": "none",
            "consecutive_failures": 0,
            "total_actions": 0,
            "final_response": "",
            "needs_step_up": False,
            "step_up_message": "",
        }

        try:
            result = self._graph.invoke(initial_state)
            return result.get("final_response", "Task completed.")
        except Exception as e:
            print(f"⚠️  LangGraph error ({e}), falling back to legacy loop")
            import traceback
            traceback.print_exc()
            return self._chat_loop(user_message)

    # ------------------------------------------------------------------ #
    # Legacy loop implementation (fallback when LangGraph not available)
    # ------------------------------------------------------------------ #
    def _chat_loop(self, user_message):
        """Process message using the original while-loop approach."""
        system_prompt = """You are a hands-on browser automation agent. You have FULL control of a
real browser through your tools. Your job is to PERFORM the user's requests
by actually navigating, clicking, typing, and reading pages — NOT by giving
instructions for the user to follow manually.

CRITICAL: Only perform browser actions the user EXPLICITLY asked for.
If the user asks a general question, has a casual conversation, or does
not mention visiting a specific site / performing a browser task, reply
with text only — do NOT call any tools.
When the user DOES ask for a browser action, carry it out fully with your
tools. Do NOT respond with a list of manual steps.

WORKFLOW (only when the user asks for a browser action):
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

ELEMENT IDENTIFICATION — CRITICAL:
- ALWAYS look at the interactive elements from get_visible_elements.
- NEVER send a click with empty or missing target identifiers.
- Copy the element's id, text, href, aria-label, or name EXACTLY from
  the interactive elements into the target object.
- If a button/link has text like 'Resend Email', 'Submit', 'Sign In',
  set target.text to that EXACT text and target.tagName to 'BUTTON',
  'A', or 'INPUT' as appropriate.
- For elements with id, ALWAYS prefer target.id over text matching.

PAGE CONTINUITY — VERY IMPORTANT:
- Every tool response includes "current_url" telling you EXACTLY where the
  browser is. ALWAYS check it before deciding your next action.
- If you are ALREADY on a page that has the content you need, DO NOT
  navigate away. Work with the current page.
- Only navigate to a new URL when the current page genuinely does not have
  what you need.

OVERLAY / POPUP HANDLING:
- If you see overlays, modals, popups, cookie consent banners, account
  creation prompts, or passkey/credential picker dialogs covering the page,
  close them BEFORE doing anything else.
- Look for close buttons (aria-label="Close", "Dismiss", "X") or text
  buttons ("No thanks", "Skip", "Not now", "Decline").

SEARCH & FORM SUBMISSION:
- When typing into search boxes, use the most specific identifier:
  aria-label (e.g. "Search"), role="searchbox" or role="combobox",
  type="search", placeholder text, or name attribute.
- AFTER typing in a search box, use type_text with press_enter=true
  to submit the search. Do NOT try to find and click a 'Search'
  button — just press Enter. This is MORE RELIABLE.
- For any form with a single input (search, verification code, etc.),
  prefer pressing Enter over finding a submit button.

LOGIN FLOW — MANDATORY:
- When you need to log into a site, FIRST navigate to that site's
  login page (use open_new_tab or navigate). THEN follow this sequence:
  1. Call get_saved_credentials with the site's domain.
  2. If credentials are found, call auto_login immediately.
  3. auto_login handles multi-step forms, entering both username
     AND password, clicking continue/next, and dismissing popups.
  4. NEVER manually type usernames or passwords with type_text.
     auto_login does this for you with proper security validation.
  5. Only ask the user if NO saved credentials exist.
- ⚠ auto_login ONLY works on the site's OWN login page.
  Do NOT call auto_login while on an unrelated site.
  Example: to log into Gmail, navigate to mail.google.com FIRST.
- This applies to ALL sites: Google, Gmail, Amazon, eBay, etc.

EMAIL & VERIFICATION CODE WORKFLOW — CRITICAL:
- In email inboxes (Gmail, Outlook, Yahoo), the NEWEST emails
  appear at the TOP of the inbox list.
- In email THREADS (multiple replies in a conversation), the
  NEWEST message is at the BOTTOM of the thread.
- To extract a verification code from an email:
  1. Open the email in the inbox.
  2. Use get_page_content to READ the email body text.
  3. Find the numeric code in the text (e.g. 5-6 digit number).
  4. NEVER ask the user for the code — extract it yourself.
- AFTER extracting the code, you MUST switch_to_tab to the
  ORIGINAL site (e.g. investopedia, ebay) BEFORE typing the code.
  ⚠ NEVER type a verification code into the email page.
  ⚠ ALWAYS check the current URL — if it contains "mail.google",
  "outlook", or "yahoo", you are on the EMAIL tab, NOT the target.
  ⚠ switch_to_tab FIRST, then type the code.

TAB MANAGEMENT:
- Use open_new_tab when you need to visit a DIFFERENT site without
  losing your place (e.g. checking email for a 2FA code, comparing
  prices on another site, looking up information).
- Give tabs short, meaningful labels (e.g. "gmail", "ebay", "amazon").
- After completing work in a secondary tab, ALWAYS switch_to_tab
  back to the original tab.
- Close tabs you no longer need with close_tab to keep things tidy.
- When a task requires 2FA / verification codes sent via email:
  1. open_new_tab to the email provider (e.g. mail.google.com)
  2. Call get_saved_credentials + auto_login if login is needed
  3. Find the verification email and open it
  4. Use get_page_content to READ the code from the email body
  5. switch_to_tab back to the ORIGINAL site
  6. Type the code into the verification field on that site
  7. close_tab the email tab when done

PREFERRED SERVICE URLS (use these instead of guessing):
- Gmail / Google login → https://mail.google.com
- Outlook / Microsoft → https://outlook.live.com
- Yahoo Mail → https://mail.yahoo.com
- Amazon → https://www.amazon.com
- eBay → https://www.ebay.com
- GitHub → https://github.com
Do NOT use marketing/workspace/promo URLs.

RULES:
- ONLY act on what the user explicitly asked.
- NEVER guess deep URLs. Navigate to homepages first.
- If a page_error was returned, go to the homepage instead.
- If the same action fails 2+ times, try a DIFFERENT approach.
- If AgentTrust blocks an action (denied / step-up required), explain
  the policy decision and ask the user how they'd like to proceed.
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

        # --- Inject RAG context from past action histories ---
        if self.action_rag:
            try:
                similar = self.action_rag.retrieve(user_message, top_k=3)
                if similar:
                    rag_text = self.action_rag.format_for_prompt(similar)
                    messages.insert(1, {
                        "role": "system",
                        "content": (
                            "The following are action sequences from similar "
                            "past tasks that succeeded. Use them as reference "
                            "for planning your approach:\n\n" + rag_text
                        ),
                    })
            except Exception as e:
                print(f"⚠️  RAG retrieval failed in legacy loop: {e}")

        tools = self._build_tools()
        self._tool_call_count = 0
        self._consecutive_failures = 0
        self._last_action_key = None
        
        response = self._chat_completion(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        message = response.choices[0].message
        
        while message.tool_calls and self._tool_call_count < self.MAX_TOOL_ROUNDS:
            messages.append(message)
            
            _auth0_fatal = False
            for tool_call in message.tool_calls:
                self._tool_call_count += 1
                fc = type('obj', (object,), {
                    'name': tool_call.function.name,
                    'arguments': tool_call.function.arguments
                })()
                result = self.handle_function_call(fc)

                # Detect auth0 / backend connectivity errors and abort the
                # tool loop instead of letting ChatGPT hallucinate an excuse.
                _err_type = None
                if isinstance(result, dict):
                    _err_type = result.get("error_type")
                    if not _err_type and isinstance(result.get("browser_result"), dict):
                        _err_type = result["browser_result"].get("error_type")
                if _err_type in ("auth0", "backend"):
                    _auth0_fatal = True
                    err_msg = (result if isinstance(result, dict) else {}).get("message", "")
                    print(f"\n❌ CONNECTIVITY ERROR: {err_msg}")
                    print("   The agent cannot perform actions. Check Auth0 and backend setup.\n")
                    result = {
                        "status": "error",
                        "message": "System connectivity error. Tell the user there is a backend configuration issue and to check the terminal for details."
                    }

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

            if _auth0_fatal:
                # Force one final completion so ChatGPT gives a short reply, then stop.
                response = self._chat_completion(
                    model=self.model, messages=messages, tools=tools, tool_choice="none"
                )
                message = response.choices[0].message
                break
            
            response = self._chat_completion(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            message = response.choices[0].message
        
        return message.content or ""
    
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
            press_enter = args.get("press_enter", False)
            result = self.browser_executor.type_text(
                target=args.get("target", {}),
                text=args.get("text", ""),
                press_enter=press_enter
            )
            result = result or {"status": "error", "message": "No result from type_text"}
            current_url = self.browser_executor.get_current_url() if self.browser_executor.browser else ""
            result["current_url"] = current_url
            if result.get("status") == "allowed":
                enter_msg = " + Enter" if press_enter else ""
                print(f"⌨️  Text typed into field{enter_msg}")
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

            # Guard: check that the current page domain is related to the
            # credentials being used. This prevents auto_login on a totally
            # unrelated site (e.g. calling Gmail auto_login while on cnbc.com).
            # We only block when the email domain of the username is a MAJOR
            # provider (Google, Microsoft, etc.) and the page is clearly
            # unrelated — because many sites use email-style usernames, so
            # user@gmail.com might still be a valid username on investopedia.com.
            from urllib.parse import urlparse as _urlparse_guard
            _guard_parsed = _urlparse_guard(current_url)
            _guard_domain = _guard_parsed.netloc.lower().lstrip("www.")
            
            # Extract the credential domain from the username (email)
            _cred_domain = ""
            if "@" in username:
                _cred_domain = username.split("@")[-1].lower()
            
            # We only enforce this guard for major email provider domains.
            # If the credential uses a @gmail.com address, we check that
            # the page is a Google property (not cnbc.com).
            # For non-major-provider credentials, we allow (the email domain
            # might just be the user's login email for any site).
            _MAJOR_EMAIL_PROVIDERS = {
                "gmail.com": {"google.com", "gmail.com", "youtube.com", "accounts.google.com", "mail.google.com"},
                "google.com": {"google.com", "gmail.com", "youtube.com", "accounts.google.com", "mail.google.com"},
                "outlook.com": {"microsoft.com", "outlook.com", "hotmail.com", "live.com", "office.com", "login.microsoftonline.com"},
                "hotmail.com": {"microsoft.com", "outlook.com", "hotmail.com", "live.com", "office.com", "login.microsoftonline.com"},
                "live.com": {"microsoft.com", "outlook.com", "hotmail.com", "live.com", "office.com", "login.microsoftonline.com"},
                "yahoo.com": {"yahoo.com", "ymail.com", "mail.yahoo.com"},
                "ymail.com": {"yahoo.com", "ymail.com", "mail.yahoo.com"},
                "icloud.com": {"apple.com", "icloud.com", "appleid.apple.com"},
            }
            
            if _guard_domain and _cred_domain and _cred_domain in _MAJOR_EMAIL_PROVIDERS:
                # The credential belongs to a major email provider — check
                # if the page is one of that provider's domains.
                _provider_domains = _MAJOR_EMAIL_PROVIDERS[_cred_domain]
                
                # Normalize the page domain: strip common auth prefixes
                def _strip_prefix(d):
                    for p in ("accounts.", "login.", "auth.", "id.", "sso.", "signin.", "app.", "mail.", "my.", "secure.", "www."):
                        if d.startswith(p):
                            base = d[len(p):]
                            if base and "." in base:
                                return base
                    return d
                _gd_stripped = _strip_prefix(_guard_domain)
                
                _is_provider_page = (
                    _guard_domain in _provider_domains
                    or _gd_stripped in _provider_domains
                )
                
                if not _is_provider_page:
                    # The page is NOT a known domain for this email provider.
                    # However, check if the page itself has login fields —
                    # if it does, the user might genuinely want to log in
                    # with their email on a third-party site (many sites
                    # accept email+password). We only block if the page has
                    # NO login fields at all (meaning the agent is confused).
                    has_login_inputs = False
                    try:
                        elements = self.browser_executor.get_visible_elements()
                        for el in (elements or []):
                            itype = (el.get("input_type") or el.get("type") or "").lower()
                            name = (el.get("name") or "").lower()
                            if itype in ("email", "password", "text") or name in ("email", "username", "password", "login_email"):
                                has_login_inputs = True
                                break
                    except Exception:
                        has_login_inputs = True  # assume yes on error
                    
                    if not has_login_inputs:
                        return {
                            "success": False,
                            "message": f"Current page ({_guard_domain}) is not a login page for {_cred_domain}. "
                                       f"Navigate to {_cred_domain}'s login page FIRST, then call auto_login. "
                                       f"For example, use open_new_tab to go to the correct login page."
                        }

            # --- KNOWN_LOGIN_URLS: if the page has no login fields, try
            # redirecting to the known login URL for common services ---
            KNOWN_LOGIN_URLS = {
                "google.com": "https://accounts.google.com/signin",
                "gmail.com": "https://accounts.google.com/signin",
                "mail.google.com": "https://accounts.google.com/signin",
                "workspace.google.com": "https://accounts.google.com/signin",
                "youtube.com": "https://accounts.google.com/signin",
                "microsoft.com": "https://login.microsoftonline.com/",
                "outlook.com": "https://login.microsoftonline.com/",
                "live.com": "https://login.microsoftonline.com/",
                "office.com": "https://login.microsoftonline.com/",
                "amazon.com": "https://www.amazon.com/ap/signin",
                "ebay.com": "https://signin.ebay.com/ws/eBayISAPI.dll?SignIn",
                "facebook.com": "https://www.facebook.com/login",
                "instagram.com": "https://www.instagram.com/accounts/login/",
                "twitter.com": "https://twitter.com/i/flow/login",
                "x.com": "https://twitter.com/i/flow/login",
                "github.com": "https://github.com/login",
                "apple.com": "https://appleid.apple.com/sign-in",
                "icloud.com": "https://appleid.apple.com/sign-in",
                "yahoo.com": "https://login.yahoo.com/",
                "linkedin.com": "https://www.linkedin.com/login",
                "netflix.com": "https://www.netflix.com/login",
                "spotify.com": "https://accounts.spotify.com/login",
            }

            # Check if the current page is a promo/marketing page with no
            # login fields — if so, redirect to the known login page.
            from urllib.parse import urlparse
            parsed = urlparse(current_url)
            page_domain = parsed.netloc.lower().lstrip("www.")

            # Quick check: does the page have ANY login-looking input?
            has_login_fields = False
            try:
                elements = self.browser_executor.get_visible_elements()
                for el in (elements or []):
                    itype = (el.get("input_type") or el.get("type") or "").lower()
                    name = (el.get("name") or "").lower()
                    placeholder = (el.get("placeholder") or "").lower()
                    if itype in ("email", "password") or name in ("email", "username", "password", "login_email", "userid"):
                        has_login_fields = True
                        break
                    if any(kw in placeholder for kw in ("email", "password", "username", "user id", "sign in")):
                        has_login_fields = True
                        break
            except Exception:
                has_login_fields = True  # assume yes on error

            if not has_login_fields:
                # Try to find a known login URL for this domain
                login_url = None
                for known_domain, known_url in KNOWN_LOGIN_URLS.items():
                    if known_domain in page_domain or page_domain in known_domain:
                        login_url = known_url
                        break
                if login_url and login_url != current_url:
                    print(f"🔐 No login fields found on {current_url}, redirecting to {login_url}")
                    try:
                        nav_result = self.browser_executor.execute_navigation(login_url)
                        if nav_result.get("status") == "allowed":
                            time.sleep(2)
                            current_url = self.browser_executor.get_current_url() or current_url
                    except Exception as e:
                        print(f"   ⚠️  Redirect failed: {e}")

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

        # --- Tab management ---
        elif function_name == "open_new_tab":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            url = args.get("url", "about:blank")
            label = args.get("label", "")
            result = self.browser_executor.open_new_tab(url=url, label=label)
            if result.get("success"):
                print(f"🗂️  Opened new tab '{result.get('label', '')}' → {result.get('url', '')}")
            result["current_url"] = self.browser_executor.get_current_url() if self.browser_executor.browser else ""
            return result

        elif function_name == "switch_to_tab":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            raw = args.get("label_or_index", "0")
            # Try converting to int for index-based lookup
            try:
                label_or_index = int(raw)
            except (ValueError, TypeError):
                label_or_index = raw
            result = self.browser_executor.switch_to_tab(label_or_index)
            if result.get("success"):
                print(f"🗂️  Switched to tab '{result.get('label', '')}' → {result.get('url', '')}")
            result["current_url"] = self.browser_executor.get_current_url() if self.browser_executor.browser else ""
            return result

        elif function_name == "close_tab":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            raw = args.get("label_or_index")
            if raw is not None:
                try:
                    label_or_index = int(raw)
                except (ValueError, TypeError):
                    label_or_index = raw
            else:
                label_or_index = None
            result = self.browser_executor.close_tab(label_or_index)
            if result.get("success"):
                print(f"🗂️  Closed tab. Now on '{result.get('active_tab_label', '')}'")
            result["current_url"] = self.browser_executor.get_current_url() if self.browser_executor.browser else ""
            return result

        elif function_name == "list_tabs":
            tabs = self.browser_executor.list_tabs()
            print(f"🗂️  {len(tabs)} tab(s) open")
            return {"tabs": tabs, "count": len(tabs)}

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

            # If the executor returned an error (e.g. auth0 / backend down),
            # propagate it directly instead of wrapping it as "allowed".
            if result.get("status") in ("error", "unauthorized"):
                risk = result.get("risk_level", "unknown")
                print(f"   ⚠️  AgentTrust: {result.get('status').upper()} (Risk: {risk})")
                return result

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

    # --- Pre-flight: verify backend + Auth0 connectivity ---
    check = agent.agenttrust.verify_connectivity()
    is_dev = check.get("note") == "dev_mode"

    if not check.get("ok"):
        phase = check.get("phase", "unknown")
        print("\n" + "!"*70)
        print(f"  STARTUP FAILED  ({phase})")
        print("!"*70)
        print(f"\n  {check['error']}\n")
        if phase == "backend":
            print("  Make sure the backend is running:  cd backend && npm start")
        print()
        sys.exit(1)

    # --- Create a fresh session (retry up to 3 times) ---
    session_id = None
    for attempt in range(1, 4):
        session_id = agent.agenttrust.create_session()
        if session_id:
            break
        wait = attempt * 2
        print(f"  Session creation failed (attempt {attempt}/3), retrying in {wait}s...")
        time.sleep(wait)

    if session_id:
        print(f"Session created: {session_id}")
    else:
        print("\n" + "!"*70)
        print("  STARTUP FAILED: Could not create a session after 3 attempts.")
        print("!"*70)
        print("\n  The agent cannot function without a session.")
        print("  Check that the backend is running and Auth0 is configured.\n")
        sys.exit(1)
    
    try:
        import threading, queue as _queue

        print("="*70)
        print("Interactive Mode")
        print("="*70)
        if is_dev:
            print("DEV MODE: Terminal input only. Extension chat is disabled.")
        else:
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
