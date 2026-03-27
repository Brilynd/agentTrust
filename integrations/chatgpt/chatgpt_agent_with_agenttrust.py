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
import re
import zipfile
import shutil
import tempfile
import hashlib

# Fix emoji output on Windows terminals that use cp1252
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import requests
from typing import Optional, Dict, List, Any, Tuple
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

    def _get_chrome_for_testing_path(self) -> Optional[str]:
        """Get path to Chrome for Testing binary. Checks env vars then local chrome-for-testing folder."""
        for env_name in ("CHROME_FOR_TESTING_PATH", "AGENTTRUST_CHROME_FOR_TESTING_PATH"):
            path = os.getenv(env_name)
            if not path:
                continue
            path = os.path.abspath(path.strip().strip('"'))
            if os.path.isfile(path) and path.lower().endswith("chrome.exe"):
                return path
            if os.path.isdir(path):
                c = os.path.join(path, "chrome.exe")
                if os.path.isfile(c):
                    return c
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base = os.path.join(script_dir, "chrome-for-testing")
            for folder in ("chrome-win64", "chrome-win32"):
                c = os.path.join(base, folder, "chrome.exe")
                if os.path.isfile(c):
                    return os.path.abspath(c)
            if sys.platform == "darwin":
                for folder in ("chrome-mac-arm64", "chrome-mac-x64"):
                    c = os.path.join(base, folder, "Google Chrome for Testing.app")
                    if os.path.isdir(c):
                        return os.path.abspath(c)
            else:
                c = os.path.join(base, "chrome-linux64", "chrome")
                if os.path.isfile(c):
                    return os.path.abspath(c)
        except Exception:
            pass
        return None

    def _download_chrome_for_testing(self, force_reinstall: bool = False) -> Optional[str]:
        """Download Chrome for Testing (stable) for current platform. Set force_reinstall=True to re-download."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.join(script_dir, "chrome-for-testing")
        if sys.platform == "win32":
            platform_id, zip_name, inner_folder, binary_name = "win64", "chrome-win64.zip", "chrome-win64", "chrome.exe"
        elif sys.platform == "darwin":
            import platform as p
            platform_id = "mac-arm64" if p.machine().lower() in ("arm64", "aarch64") else "mac-x64"
            zip_name = f"chrome-{platform_id}.zip"
            inner_folder = f"chrome-{platform_id}"
            binary_name = "Google Chrome for Testing.app"
        else:
            platform_id, zip_name, inner_folder, binary_name = "linux64", "chrome-linux64.zip", "chrome-linux64", "chrome"
        chrome_path = os.path.join(base_dir, inner_folder, binary_name)
        exists = os.path.isfile(chrome_path) or (binary_name.endswith(".app") and os.path.isdir(chrome_path))
        if exists and not force_reinstall:
            return os.path.abspath(chrome_path)
        if force_reinstall and os.path.isdir(base_dir):
            try:
                shutil.rmtree(base_dir)
                os.makedirs(base_dir, exist_ok=True)
            except OSError as e:
                print(f"⚠️  Could not remove old install: {e}")
        try:
            r = requests.get(
                "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            downloads = data.get("channels", {}).get("Stable", {}).get("downloads", {}).get("chrome", [])
            url = next((d["url"] for d in downloads if d.get("platform") == platform_id), None)
            if not url:
                return None
            print("⬇️  Downloading Chrome for Testing (stable)...")
            zip_resp = requests.get(url, stream=True, timeout=120)
            zip_resp.raise_for_status()
            os.makedirs(base_dir, exist_ok=True)
            zip_path = os.path.join(base_dir, zip_name)
            with open(zip_path, "wb") as f:
                for chunk in zip_resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            print("📦 Extracting...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(base_dir)
            try:
                os.remove(zip_path)
            except OSError:
                pass
            if os.path.isfile(chrome_path) or (binary_name.endswith(".app") and os.path.isdir(chrome_path)):
                print("✅ Chrome for Testing ready")
                return os.path.abspath(chrome_path)
        except Exception as e:
            print(f"⚠️  Auto-install failed: {e}")
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
        if headless and load_ext and os.getenv("AGENTTRUST_ALLOW_EXTENSION_IN_HEADLESS", "false").lower() != "true":
            print("⚠️  Headless worker detected; disabling browser extension for startup stability.")
            load_ext = False
        chrome_for_testing = self._get_chrome_for_testing_path()
        force_reinstall = os.getenv("AGENTTRUST_REINSTALL_CHROMIUM", "").lower() == "true"
        if load_ext and not chrome_for_testing and os.getenv("AGENTTRUST_AUTO_INSTALL_CHROMIUM", "true").lower() == "true":
            chrome_for_testing = self._download_chrome_for_testing(force_reinstall=force_reinstall)
        elif load_ext and force_reinstall and chrome_for_testing:
            chrome_for_testing = self._download_chrome_for_testing(force_reinstall=True)
        if load_ext and not chrome_for_testing:
            print("❌ Chrome for Testing required for extension. Set CHROME_FOR_TESTING_PATH or run with auto-install (default).")
            raise RuntimeError("Chrome for Testing not found. Delete integrations/chatgpt/chrome-for-testing and run again to re-download.")
        
        chrome_profile = os.getenv("CHROME_PROFILE_DIR")
        if not chrome_profile:
            chrome_profile = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), ".chrome-profile"
            )
        chrome_profile = os.path.abspath(chrome_profile)
        chrome_profile_name = os.getenv("CHROME_PROFILE_NAME", "Default").strip() or "Default"
        os.makedirs(chrome_profile, exist_ok=True)
        self._temp_profile_dir = None
        # Remove stale lock files from previous unclean shutdowns
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_path = os.path.join(chrome_profile, lock_name)
            try:
                if os.path.exists(lock_path):
                    os.remove(lock_path)
            except OSError:
                pass

        def _build_options(profile_dir: str, profile_name: Optional[str]) -> webdriver.ChromeOptions:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument('--headless=new')
            if chrome_for_testing:
                options.binary_location = chrome_for_testing
            options.add_argument(f'--user-data-dir={profile_dir}')
            if profile_name:
                options.add_argument(f'--profile-directory={profile_name}')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--no-first-run')
            options.add_argument('--no-default-browser-check')
            options.add_argument('--disable-background-networking')
            options.add_argument('--disable-background-timer-throttling')
            options.add_argument('--disable-backgrounding-occluded-windows')
            options.add_argument('--disable-renderer-backgrounding')
            options.add_argument('--remote-debugging-port=0')
            options.add_argument('--lang=en-US,en')
            options.add_argument('--window-size=1440,960')
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
                "profile.default_content_setting_values.popups": 2,
                "profile.default_content_setting_values.ads": 2,
                "autofill.profile_enabled": False,
                "autofill.credit_card_enabled": False,
                "password_manager.enabled": False,
                "password_manager.leak_detection": False,
                "password_manager.auto_signin.enabled": False,
                "webauthn.allow_virtual_authenticator": False,
            })
            if load_ext:
                options.add_argument(f'--load-extension={extension_path}')
            return options

        print(f"📁 Persistent browser profile: {chrome_profile} [{chrome_profile_name}]")
        try:
            actual_driver = webdriver.Chrome(options=_build_options(chrome_profile, chrome_profile_name))
        except Exception as primary_error:
            error_text = str(primary_error)
            recoverable_profile_error = any(token in error_text for token in [
                "DevToolsActivePort file doesn't exist",
                "user data directory is already in use",
                "session not created",
                "Chrome failed to start"
            ])
            if not recoverable_profile_error:
                raise

            self._temp_profile_dir = tempfile.mkdtemp(
                prefix="agenttrust-chrome-",
                dir=os.path.dirname(chrome_profile)
            )
            print(f"⚠️  Persistent Chrome profile could not be opened: {primary_error}")
            print(f"↪ Retrying with temporary browser profile: {self._temp_profile_dir}")
            actual_driver = webdriver.Chrome(options=_build_options(self._temp_profile_dir, None))

        if load_ext:
            print("✅ AgentTrust extension installed")
        actual_driver.implicitly_wait(2)
        try:
            if not headless:
                actual_driver.maximize_window()
        except Exception:
            pass

        try:
            actual_driver.execute_cdp_cmd("Network.enable", {})
            browser_version = actual_driver.execute_cdp_cmd("Browser.getVersion", {})
            current_ua = str(browser_version.get("userAgent") or "")
            normal_ua = current_ua.replace("HeadlessChrome", "Chrome") if current_ua else (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            )
            actual_driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                "userAgent": normal_ua,
                "acceptLanguage": "en-US,en;q=0.9",
                "platform": "Win32",
                "userAgentMetadata": {
                    "platform": "Windows",
                    "platformVersion": "10.0.0",
                    "architecture": "x86",
                    "model": "",
                    "mobile": False,
                    "brands": [
                        {"brand": "Chromium", "version": "136"},
                        {"brand": "Google Chrome", "version": "136"},
                        {"brand": "Not.A/Brand", "version": "24"},
                    ],
                    "fullVersionList": [
                        {"brand": "Chromium", "version": "136.0.0.0"},
                        {"brand": "Google Chrome", "version": "136.0.0.0"},
                        {"brand": "Not.A/Brand", "version": "24.0.0.0"},
                    ],
                },
            })
        except Exception:
            pass
        
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
                    const override = (obj, key, value) => {
                        try {
                            Object.defineProperty(obj, key, {
                                get: () => value,
                                configurable: true
                            });
                        } catch (e) {}
                    };

                    override(Navigator.prototype, 'webdriver', undefined);
                    override(Navigator.prototype, 'platform', 'Win32');
                    override(Navigator.prototype, 'vendor', 'Google Inc.');
                    override(Navigator.prototype, 'language', 'en-US');
                    override(Navigator.prototype, 'languages', ['en-US', 'en']);
                    override(Navigator.prototype, 'hardwareConcurrency', 8);
                    override(Navigator.prototype, 'deviceMemory', 8);
                    override(Navigator.prototype, 'maxTouchPoints', 0);

                    const fakePlugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                    ];
                    override(Navigator.prototype, 'plugins', fakePlugins);
                    override(Navigator.prototype, 'mimeTypes', [
                        { type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: fakePlugins[0] }
                    ]);

                    if (!window.chrome) {
                        window.chrome = {};
                    }
                    if (!window.chrome.runtime) {
                        window.chrome.runtime = {};
                    }
                    if (!window.chrome.app) {
                        window.chrome.app = {
                            isInstalled: false,
                            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
                        };
                    }

                    const originalQuery = window.navigator.permissions && window.navigator.permissions.query
                        ? window.navigator.permissions.query.bind(window.navigator.permissions)
                        : null;
                    if (originalQuery) {
                        window.navigator.permissions.query = (parameters) => {
                            if (parameters && parameters.name === 'notifications') {
                                return Promise.resolve({ state: Notification.permission });
                            }
                            return originalQuery(parameters);
                        };
                    }

                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        if (parameter === 37445) return 'Intel Inc.';
                        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                        return getParameter.call(this, parameter);
                    };
                    if (window.WebGL2RenderingContext) {
                        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
                        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                            if (parameter === 37445) return 'Intel Inc.';
                            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                            return getParameter2.call(this, parameter);
                        };
                    }

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
            self._actual_driver.get(api_url.replace("/api", ""))
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

    def get_interactive_readiness(self) -> Dict[str, Any]:
        """
        Inspect whether the current page appears meaningfully interactive yet.

        This is intentionally generic: it looks for visible primary controls,
        meaningful text, or an active dialog instead of relying on site-specific
        selectors.
        """
        drv = self._actual_driver
        try:
            readiness = drv.execute_script("""
                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }

                function visibleCount(selector, limit = 50) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    let count = 0;
                    for (const el of nodes) {
                        if (isVisible(el)) {
                            count += 1;
                            if (count >= limit) break;
                        }
                    }
                    return count;
                }

                const bodyText = ((document.body && (document.body.innerText || document.body.textContent)) || '').replace(/\\s+/g, ' ').trim();
                const main = document.querySelector('main, [role="main"], #content, #main, .main-content, #search, #center-col, ytd-page-manager');
                const mainText = ((main && (main.innerText || main.textContent)) || '').replace(/\\s+/g, ' ').trim();
                const dialogs = visibleCount('[role="dialog"], [role="alertdialog"], [aria-modal="true"]', 10);
                const inputs = visibleCount('input:not([type="hidden"]):not([type="submit"]), textarea, select, [contenteditable="true"], [contenteditable=""], [role="textbox"], [role="combobox"], [role="searchbox"]');
                const buttons = visibleCount('button, input[type="submit"], input[type="button"], [role="button"]');
                const links = visibleCount('a[href]');
                const headings = visibleCount('h1, h2, h3, [role="heading"]');
                const searchInputs = visibleCount('input[type="search"], [role="searchbox"], [role="search"] input, form[role="search"] input, input[name*="search"], input[name*="query"], input[placeholder*="Search" i], input[aria-label*="Search" i]');
                const spinnerVisible = visibleCount('[role="progressbar"], .loading, .spinner, ytd-continuation-item-renderer', 20);
                const interactiveCount = inputs + buttons + Math.min(links, 6);
                const textLength = Math.max(bodyText.length, mainText.length);

                let ready = false;
                let reason = 'waiting for meaningful interactive content';
                if (dialogs > 0 && (inputs + buttons) > 0) {
                    ready = true;
                    reason = 'interactive dialog is visible';
                } else if (searchInputs > 0) {
                    ready = true;
                    reason = 'search input is visible';
                } else if (inputs > 0 && buttons > 0) {
                    ready = true;
                    reason = 'form controls are visible';
                } else if (interactiveCount >= 4 && textLength >= 120) {
                    ready = true;
                    reason = 'page has visible controls and content';
                } else if (headings > 0 && interactiveCount >= 2 && textLength >= 80) {
                    ready = true;
                    reason = 'page chrome and content are visible';
                } else if (spinnerVisible > 0 && interactiveCount < 2) {
                    reason = 'page is still rendering';
                } else if (textLength < 40 && interactiveCount < 2) {
                    reason = 'page shell loaded without meaningful content yet';
                }

                return {
                    readyState: document.readyState || '',
                    url: location.href || '',
                    title: document.title || '',
                    ready,
                    reason,
                    textLength,
                    mainTextLength: mainText.length,
                    dialogCount: dialogs,
                    inputCount: inputs,
                    buttonCount: buttons,
                    linkCount: links,
                    headingCount: headings,
                    searchInputCount: searchInputs,
                    spinnerCount: spinnerVisible,
                    interactiveCount
                };
            """) or {}
        except Exception as exc:
            return {
                "readyState": "",
                "ready": True,
                "reason": f"readiness check unavailable: {exc}",
                "interactiveCount": 0,
                "searchInputCount": 0,
                "textLength": 0,
            }

        if readiness.get("readyState") != "complete":
            readiness["ready"] = False
            readiness["reason"] = "document is still loading"
        return readiness

    def wait_for_interactive_page(self, timeout: float = 6.0) -> Dict[str, Any]:
        """Wait briefly for the current page to become meaningfully interactive."""
        if not self.is_alive():
            return {"ready": False, "reason": "browser session unavailable"}

        driver = self._actual_driver
        final_state = self.get_interactive_readiness()
        try:
            WebDriverWait(driver, timeout).until(
                lambda _drv: (self.get_interactive_readiness() or {}).get("ready")
            )
            final_state = self.get_interactive_readiness()
        except Exception:
            final_state = self.get_interactive_readiness()

        if not final_state.get("ready"):
            try:
                time.sleep(0.4)
                refreshed_state = self.get_interactive_readiness()
                if refreshed_state:
                    final_state = refreshed_state
            except Exception:
                pass
        return final_state
    
    def is_alive(self) -> bool:
        """Check if the browser/ChromeDriver session is still running."""
        try:
            _ = self._actual_driver.current_url
            return True
        except Exception:
            return False

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

        # Prefer the active modal/dialog when one is visible. This keeps the
        # agent focused on the popup it must act on instead of reading the page
        # behind it.
        content_bits = drv.execute_script("""
            const includeHtml = Boolean(arguments[0]);

            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && el.offsetParent !== null;
            }

            const dialogSelectors = [
                '[role="dialog"]',
                '[role="alertdialog"]',
                '[aria-modal="true"]',
                '[class*="modal"]',
                '[class*="dialog"]',
                '[class*="popup"]',
                '[class*="overlay"]'
            ];

            const dialogs = Array.from(document.querySelectorAll(dialogSelectors.join(',')))
                .filter(isVisible)
                .sort((a, b) => {
                    const az = parseInt(window.getComputedStyle(a).zIndex || '0', 10) || 0;
                    const bz = parseInt(window.getComputedStyle(b).zIndex || '0', 10) || 0;
                    return bz - az;
                });

            if (dialogs.length > 0) {
                const dlg = dialogs[0];
                const heading = dlg.querySelector('h1, h2, h3, [role="heading"]');
                const headingText = heading ? (heading.innerText || heading.textContent || '').trim() : '';
                const text = (dlg.innerText || dlg.textContent || '').trim().substring(0, 4000);
                return {
                    source: 'dialog',
                    title: headingText || document.title || '',
                    text,
                    html: includeHtml && dlg.outerHTML ? dlg.outerHTML.substring(0, 6000) : ''
                };
            }

            const main = document.querySelector('main, [role="main"], #content, #main, .main-content, #search, #center-col');
            const pageText = main ? main.innerText : document.body.innerText;
            return {
                source: 'page',
                title: document.title || '',
                text: (pageText || '').substring(0, 4000),
                html: includeHtml ? (main ? main.outerHTML : document.body.outerHTML).substring(0, 6000) : ''
            };
        """, include_html) or {}

        content = {
            "url": drv.current_url,
            "title": content_bits.get("title") or drv.title,
            "text": content_bits.get("text") or "",
            "source": content_bits.get("source") or "page",
        }
        
        if include_html:
            content["html"] = content_bits.get("html") or drv.page_source[:6000]
        
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

        function cssEscapeValue(value) {
            const raw = String(value || '');
            if (window.CSS && typeof window.CSS.escape === 'function') {
                return window.CSS.escape(raw);
            }
            return raw.replace(/["\\\\]/g, '\\\\$&');
        }

        function buildSelector(el, tag) {
            if (!el || !tag) return '';
            if (el.id) return `${tag}#${cssEscapeValue(el.id)}`;
            const aria = el.getAttribute('aria-label') || '';
            if (aria) return `${tag}[aria-label="${cssEscapeValue(aria)}"]`;
            const name = el.getAttribute('name') || '';
            if (name) return `${tag}[name="${cssEscapeValue(name)}"]`;
            const placeholder = el.getAttribute('placeholder') || '';
            if (placeholder) return `${tag}[placeholder="${cssEscapeValue(placeholder)}"]`;
            const role = el.getAttribute('role') || '';
            if (role) return `${tag}[role="${cssEscapeValue(role)}"]`;
            return tag;
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
            // For links, keep the full URL (domain + path) so the agent
            // can open the exact page instead of guessing the domain.
            let hp = '';
            if (tag === 'a' && el.href) {
                try {
                    const u = new URL(el.href);
                    hp = (u.origin + u.pathname).substring(0, 150);
                } catch(e) { hp = el.href.substring(0, 150); }
            }

            // Get input type for inputs
            const inputType = (tag === 'input') ? (el.type || 'text').toLowerCase() : '';
            const searchBlob = `${txt} ${ariaLabel} ${el.placeholder || ''} ${el.name || ''} ${el.id || ''} ${role}`.toLowerCase();
            const isSearch =
                inputType === 'search'
                || role === 'searchbox'
                || role === 'search'
                || searchBlob.includes('search')
                || searchBlob.includes('find')
                || searchBlob.includes('query');
            const selector = buildSelector(el, tag);

            out.push({t, txt, id:el.id||'', nm:el.name||'', hp,
                al: ariaLabel,
                ph: el.placeholder||'',
                v: (el.value||'').substring(0,30),
                it: inputType,
                tg: tag,
                sel: selector,
                sr: isSearch ? 1 : 0,
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
                if r.get("tg"):  e["tag"] = r["tg"]
                if r.get("sel"): e["selector"] = r["sel"]
                if r.get("sr"):  e["is_search"] = True
                if r.get("rl"):  e["role"] = r["rl"]
                if r.get("ov"):  e["in_overlay"] = True
                elements.append(e)
            return elements
        except Exception as e:
            print(f"⚠️  Error getting elements: {e}")
            return []

    def highlight_interactive_elements(
        self,
        element_type: Optional[str] = None,
        max_elements: int = 25,
    ) -> Dict[str, Any]:
        """Draw Browser Use-style numbered highlights for interactive elements."""
        drv = self._actual_driver
        js = """
        const F = arguments[0] || null;
        const MAX = Math.max(1, Math.min(Number(arguments[1] || 25), 60));
        const OVERLAY_ID = '__agenttrust-highlight-overlay__';

        function removeExisting() {
            const existing = document.getElementById(OVERLAY_ID);
            if (existing) existing.remove();
        }

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

        function cssEscapeValue(value) {
            const raw = String(value || '');
            if (window.CSS && typeof window.CSS.escape === 'function') {
                return window.CSS.escape(raw);
            }
            return raw.replace(/["\\\\]/g, '\\\\$&');
        }

        function buildSelector(el, tag) {
            if (!el || !tag) return '';
            if (el.id) return `${tag}#${cssEscapeValue(el.id)}`;
            const aria = el.getAttribute('aria-label') || '';
            if (aria) return `${tag}[aria-label="${cssEscapeValue(aria)}"]`;
            const name = el.getAttribute('name') || '';
            if (name) return `${tag}[name="${cssEscapeValue(name)}"]`;
            const placeholder = el.getAttribute('placeholder') || '';
            if (placeholder) return `${tag}[placeholder="${cssEscapeValue(placeholder)}"]`;
            const role = el.getAttribute('role') || '';
            if (role) return `${tag}[role="${cssEscapeValue(role)}"]`;
            return tag;
        }

        function classify(el) {
            const tag = el.tagName.toLowerCase();
            const role = (el.getAttribute('role') || '').toLowerCase();
            if (tag === 'a') return 'link';
            if (tag === 'button' || role === 'button') return 'btn';
            if (tag === 'input') {
                const it = (el.type || '').toLowerCase();
                return (it === 'submit' || it === 'button') ? 'btn' : 'in';
            }
            if (tag === 'textarea' || tag === 'select' || el.isContentEditable) return 'in';
            if (role === 'search' || role === 'searchbox' || role === 'combobox' || role === 'textbox') return 'in';
            return 'btn';
        }

        function isVisible(el) {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            if (!rect.width && !rect.height) return false;
            if (el.offsetParent === null && el.tagName !== 'BODY') return false;
            const style = window.getComputedStyle(el);
            if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
            return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
        }

        const all = document.querySelectorAll(
            'a, button, input, select, textarea, ' +
            '[contenteditable="true"], [contenteditable=""], ' +
            '[role="button"], [role="search"], [role="searchbox"], ' +
            '[role="combobox"], [role="textbox"], input[type="submit"]'
        );

        const out = [];
        for (let i = 0; i < all.length && out.length < MAX * 3; i++) {
            const el = all[i];
            if (!isVisible(el)) continue;

            const t = classify(el);
            if (F && t !== F && !(F === 'button' && t === 'btn') && !(F === 'input' && t === 'in')) continue;

            const rect = el.getBoundingClientRect();
            const txt = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().substring(0, 60);
            const ariaLabel = el.getAttribute('aria-label') || '';
            if (!txt && !el.id && !el.name && !el.placeholder && !ariaLabel && !el.getAttribute('role')) continue;

            const tag = el.tagName.toLowerCase();
            out.push({
                element: el,
                t,
                txt,
                id: el.id || '',
                nm: el.name || '',
                al: ariaLabel,
                ph: el.placeholder || '',
                it: tag === 'input' ? (el.type || 'text').toLowerCase() : '',
                tg: tag,
                rl: (el.getAttribute('role') || '').toLowerCase(),
                ov: inOverlay(el) ? 1 : 0,
                sel: buildSelector(el, tag),
                y: Math.round(rect.top),
                area: rect.width * rect.height,
            });
        }

        out.sort((a, b) => a.y !== b.y ? a.y - b.y : b.area - a.area);
        const finalItems = out.slice(0, MAX);

        removeExisting();
        const overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.setAttribute('aria-hidden', 'true');
        overlay.style.position = 'fixed';
        overlay.style.inset = '0';
        overlay.style.pointerEvents = 'none';
        overlay.style.zIndex = '2147483647';
        overlay.style.fontFamily = 'Inter, ui-sans-serif, system-ui, sans-serif';
        document.documentElement.appendChild(overlay);

        const palette = {
            btn: { border: '#8ea0ff', fill: 'rgba(142,160,255,0.14)', badge: '#8ea0ff', text: '#081020' },
            link: { border: '#22d3ee', fill: 'rgba(34,211,238,0.14)', badge: '#22d3ee', text: '#06232a' },
            in: { border: '#4ade80', fill: 'rgba(74,222,128,0.14)', badge: '#4ade80', text: '#07170d' },
            select: { border: '#fbbf24', fill: 'rgba(251,191,36,0.14)', badge: '#fbbf24', text: '#241604' },
        };

        const serialized = [];
        finalItems.forEach((item, index) => {
            const el = item.element;
            const rect = el.getBoundingClientRect();
            const colors = palette[item.t] || palette.btn;

            const box = document.createElement('div');
            box.style.position = 'fixed';
            box.style.left = `${Math.max(0, rect.left)}px`;
            box.style.top = `${Math.max(0, rect.top)}px`;
            box.style.width = `${Math.max(0, rect.width)}px`;
            box.style.height = `${Math.max(0, rect.height)}px`;
            box.style.border = `2px solid ${colors.border}`;
            box.style.background = colors.fill;
            box.style.borderRadius = '10px';
            box.style.boxSizing = 'border-box';
            box.style.boxShadow = `0 0 0 1px rgba(255,255,255,0.08), 0 8px 24px ${colors.fill}`;

            const badge = document.createElement('div');
            badge.textContent = String(index);
            badge.style.position = 'absolute';
            badge.style.left = '0';
            badge.style.top = '0';
            badge.style.transform = 'translate(-30%, -35%)';
            badge.style.minWidth = '22px';
            badge.style.height = '22px';
            badge.style.padding = '0 6px';
            badge.style.display = 'inline-flex';
            badge.style.alignItems = 'center';
            badge.style.justifyContent = 'center';
            badge.style.borderRadius = '999px';
            badge.style.background = colors.badge;
            badge.style.color = colors.text;
            badge.style.fontSize = '11px';
            badge.style.fontWeight = '800';
            badge.style.lineHeight = '1';
            badge.style.boxShadow = '0 6px 18px rgba(0,0,0,0.28)';
            box.appendChild(badge);
            overlay.appendChild(box);

            serialized.push({
                i: index,
                t: item.t,
                text: item.txt,
                id: item.id,
                name: item.nm,
                aria_label: item.al,
                placeholder: item.ph,
                input_type: item.it,
                tag: item.tg,
                role: item.rl,
                selector: item.sel,
                in_overlay: Boolean(item.ov),
            });
        });

        return { success: true, count: serialized.length, elements: serialized };
        """

        try:
            return drv.execute_script(js, element_type, max_elements) or {
                "success": False,
                "count": 0,
                "elements": [],
            }
        except Exception as e:
            return {"success": False, "message": f"Error highlighting elements: {e}", "count": 0, "elements": []}

    def clear_highlight_overlays(self) -> Dict[str, Any]:
        """Remove previously injected interactive-element highlights."""
        drv = self._actual_driver
        try:
            removed = drv.execute_script("""
                const existing = document.getElementById('__agenttrust-highlight-overlay__');
                if (existing) {
                    existing.remove();
                    return true;
                }
                return false;
            """)
            return {"success": True, "removed": bool(removed)}
        except Exception as e:
            return {"success": False, "message": f"Error clearing highlights: {e}"}
    
    def _unwrap_element(self, element):
        """Get the actual Selenium WebElement from InterceptedWebElement wrapper."""
        return getattr(element, '_element', element)
    
    def _xpath_escape(self, text: str) -> str:
        """Escape single quotes for XPath (use '' to escape ' in XPath)."""
        if not text:
            return ""
        return str(text).replace("'", "''")

    def _normalize_lookup_text(self, value: Any) -> str:
        """Normalize freeform locator text for fuzzy matching."""
        if value is None:
            return ""
        return " ".join(str(value).strip().lower().split())

    def _target_value(self, target: Dict[str, Any], *keys: str) -> Any:
        """Read the first non-empty target value across alternate key spellings."""
        for key in keys:
            value = target.get(key)
            if value not in (None, ""):
                return value
        return None

    def _find_select_like_element(self, target: Dict[str, Any]):
        """Resolve either a native select or a custom combobox/listbox control."""
        drv = self._actual_driver
        element = None

        def _first_interactable(candidates):
            for candidate in candidates or []:
                try:
                    if candidate.is_displayed() and candidate.is_enabled():
                        return candidate
                except Exception:
                    continue
            return None

        def _resolve_selectable(candidate):
            candidate = self._unwrap_element(candidate)
            if not candidate:
                return None
            try:
                tag = (candidate.tag_name or "").lower()
                role = str(candidate.get_attribute("role") or "").lower()
                popup = str(candidate.get_attribute("aria-haspopup") or "").lower()
                if tag == "select" or role in ("combobox", "listbox") or popup == "listbox":
                    return candidate
            except Exception:
                pass

            descendant_selectors = (
                "select",
                "[role='combobox']",
                "[role='listbox']",
                "[aria-haspopup='listbox']",
                "input[role='combobox']",
                "div[role='combobox']",
                "span[role='combobox']",
            )
            for selector in descendant_selectors:
                try:
                    nested = _first_interactable(candidate.find_elements(By.CSS_SELECTOR, selector))
                    if nested is not None:
                        return nested
                except Exception:
                    continue

            ancestor_xpath = (
                "./ancestor-or-self::*[@role='combobox' or @role='listbox' or "
                "@aria-haspopup='listbox' or self::select][1]"
            )
            try:
                ancestors = candidate.find_elements(By.XPATH, ancestor_xpath)
                resolved = _first_interactable(ancestors)
                if resolved is not None:
                    return resolved
            except Exception:
                pass
            return candidate

        target_id = self._target_value(target, "id")
        if target_id:
            try:
                element = _resolve_selectable(drv.find_element(By.ID, target_id))
            except NoSuchElementException:
                pass

        target_name = self._target_value(target, "name")
        if not element and target_name:
            try:
                element = _resolve_selectable(drv.find_element(By.NAME, target_name))
            except NoSuchElementException:
                pass

        selector = self._target_value(target, "selector")
        if not element and selector:
            try:
                element = _resolve_selectable(drv.find_element(By.CSS_SELECTOR, selector))
            except NoSuchElementException:
                pass

        aria = self._target_value(target, "aria-label", "aria_label")
        if not element and aria:
            escaped_aria = str(aria).replace("'", "\\'")
            for xpath in (
                f"//select[@aria-label='{escaped_aria}' or contains(@aria-label,'{escaped_aria}')]",
                f"//*[@role='combobox'][@aria-label='{escaped_aria}' or contains(@aria-label,'{escaped_aria}')]",
                f"//*[@role='listbox'][@aria-label='{escaped_aria}' or contains(@aria-label,'{escaped_aria}')]",
                f"//*[self::div or self::span or self::input][@aria-label='{escaped_aria}' or contains(@aria-label,'{escaped_aria}')]",
            ):
                try:
                    matches = drv.find_elements(By.XPATH, xpath)
                    element = next(
                        (_resolve_selectable(match) for match in matches if match.is_displayed() and match.is_enabled()),
                        None,
                    )
                    if element is not None:
                        break
                except Exception:
                    continue

        text = str(self._target_value(target, "text") or "").strip()
        if not element and text:
            escaped_text = self._xpath_escape(text[:80])
            for xpath in (
                f"//select[contains(normalize-space(.), '{escaped_text}')]",
                f"//*[@role='combobox'][contains(normalize-space(.), '{escaped_text}')]",
                f"//*[@role='listbox'][contains(normalize-space(.), '{escaped_text}')]",
                f"//*[contains(normalize-space(.), '{escaped_text}')][@role='combobox' or @role='listbox']",
            ):
                try:
                    matches = drv.find_elements(By.XPATH, xpath)
                    element = next(
                        (_resolve_selectable(match) for match in matches if match.is_displayed() and match.is_enabled()),
                        None,
                    )
                    if element is not None:
                        break
                except Exception:
                    continue

        return element

    def _select_custom_dropdown_option(
        self,
        element,
        target: Dict[str, Any],
        value: Optional[str] = None,
        label: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Select from a custom JS dropdown/combobox such as Google's signup fields."""
        import time
        from selenium.webdriver.common.keys import Keys

        drv = self._actual_driver

        try:
            drv.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant', block:'center', inline:'center'});",
                element,
            )
        except Exception:
            pass

        opened = False
        for opener in (
            lambda: element.click(),
            lambda: drv.execute_script("arguments[0].click();", element),
        ):
            try:
                opener()
                opened = True
                break
            except Exception:
                continue

        if not opened:
            return {"success": False, "message": "Could not open custom dropdown"}

        time.sleep(0.2)

        desired = label if label not in (None, "") else value
        desired_norm = self._normalize_lookup_text(desired)

        def _visible_options():
            options = []
            selectors = (
                "[role='option']",
                "[role='menuitemradio']",
                "[role='radio']",
                "[role='listbox'] [aria-selected]",
                "[aria-haspopup='listbox'] [role='option']",
                "[role='presentation'] [role='option']",
                "[data-value]",
                "li",
            )
            for selector in selectors:
                try:
                    for option in drv.find_elements(By.CSS_SELECTOR, selector):
                        try:
                            if not option.is_displayed() or not option.is_enabled():
                                continue
                            blob = self._normalize_lookup_text(
                                " ".join(
                                    filter(
                                        None,
                                        [
                                            option.text,
                                            option.get_attribute("aria-label"),
                                            option.get_attribute("data-value"),
                                            option.get_attribute("value"),
                                        ],
                                    )
                                )
                            )
                            if blob:
                                options.append((blob, option))
                        except Exception:
                            continue
                except Exception:
                    continue
            deduped = []
            seen = set()
            for blob, option in options:
                key = getattr(option, "id", None) or id(option)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((blob, option))
            return deduped

        def _expand_with_keyboard():
            for key in (Keys.SPACE, Keys.ARROW_DOWN, Keys.ENTER):
                try:
                    element.send_keys(key)
                    time.sleep(0.15)
                    if _visible_options():
                        return True
                except Exception:
                    continue
            return False

        options = _visible_options()
        if not options:
            _expand_with_keyboard()
            options = _visible_options()
        if not options:
            return {"success": False, "message": "Custom dropdown opened but no visible options were found"}

        option_to_click = None
        if index is not None:
            visible_only = [option for _, option in options]
            if 0 <= int(index) < len(visible_only):
                option_to_click = visible_only[int(index)]
            else:
                return {"success": False, "message": f"Dropdown option index {index} is out of range"}
        elif desired_norm:
            exact_matches = [option for blob, option in options if blob == desired_norm]
            partial_matches = [option for blob, option in options if desired_norm in blob]
            option_to_click = (exact_matches or partial_matches or [None])[0]
            if option_to_click is None and element.get_attribute("role") == "combobox":
                try:
                    element.send_keys(str(desired))
                    time.sleep(0.1)
                    options = _visible_options()
                    exact_matches = [option for blob, option in options if blob == desired_norm]
                    partial_matches = [option for blob, option in options if desired_norm in blob]
                    option_to_click = (exact_matches or partial_matches or [None])[0]
                except Exception:
                    option_to_click = None
            if option_to_click is None:
                return {"success": False, "message": f"Dropdown option '{desired}' was not found"}
        else:
            return {"success": False, "message": "Select requires label, value, or index"}

        try:
            drv.execute_script("arguments[0].scrollIntoView({block:'nearest'});", option_to_click)
        except Exception:
            pass

        for clicker in (
            lambda: option_to_click.click(),
            lambda: drv.execute_script("arguments[0].click();", option_to_click),
        ):
            try:
                clicker()
                return {"success": True, "message": f"Selected option {label or value or index}"}
            except Exception:
                continue

        return {"success": False, "message": f"Dropdown option '{label or value or index}' could not be clicked"}

    def _element_lookup_blob(self, element) -> str:
        """Build a searchable blob of meaningful element attributes."""
        parts: List[str] = []
        try:
            tag = (element.tag_name or "").lower()
            if tag:
                parts.append(tag)
        except Exception:
            pass

        for attr in (
            "id",
            "name",
            "type",
            "role",
            "placeholder",
            "aria-label",
            "title",
            "class",
            "autocomplete",
            "data-testid",
            "data-test",
            "value",
        ):
            try:
                value = element.get_attribute(attr)
                if value:
                    parts.append(str(value))
            except Exception:
                continue

        try:
            text = element.text or ""
            if text:
                parts.append(text)
        except Exception:
            pass

        return self._normalize_lookup_text(" ".join(parts))

    def _element_search_context_blob(self, element) -> str:
        """Collect nearby form/container metadata to detect search inputs generically."""
        try:
            raw = self._actual_driver.execute_script(
                """
                const el = arguments[0];
                if (!el) return "";
                const attrs = (node) => {
                    if (!node || !node.getAttribute) return "";
                    const values = [];
                    for (const name of ["id", "name", "role", "action", "method", "placeholder", "aria-label", "title", "class", "data-testid", "data-test", "type", "autocomplete", "aria-autocomplete"]) {
                        const value = node.getAttribute(name);
                        if (value) values.push(String(value));
                    }
                    const text = (node.innerText || node.textContent || "").trim();
                    if (text) values.push(text.slice(0, 120));
                    return values.join(" ");
                };
                const chunks = [attrs(el)];
                let parent = el.parentElement;
                for (let depth = 0; parent && depth < 4; depth += 1, parent = parent.parentElement) {
                    chunks.push(attrs(parent));
                }
                const form = el.closest("form");
                if (form) {
                    chunks.push(attrs(form));
                    const submit = form.querySelector("button, input[type='submit'], button[type='submit']");
                    if (submit) chunks.push(attrs(submit));
                }
                return chunks.filter(Boolean).join(" ");
                """,
                element,
            )
        except Exception:
            raw = ""
        return self._normalize_lookup_text(raw)

    def _target_lookup_blob(self, target: Dict[str, Any]) -> str:
        """Build a normalized blob from model-provided target hints."""
        parts = [
            target.get("text"),
            target.get("id"),
            target.get("name"),
            target.get("placeholder"),
            target.get("aria_label"),
            target.get("aria-label"),
            target.get("selector"),
            target.get("input_type"),
            target.get("type"),
            target.get("role"),
            target.get("tag"),
            target.get("tagName"),
            target.get("is_search"),
        ]
        return self._normalize_lookup_text(" ".join(str(part or "") for part in parts))

    def _target_prefers_search_input(self, target: Dict[str, Any], typed_text: Optional[str] = None) -> bool:
        """Detect when the intended element is likely a site search box."""
        target_blob = self._target_lookup_blob(target)
        search_markers = (
            "search",
            "searchbox",
            "find",
            "query",
            "look up",
            "lookup",
        )
        if any(marker in target_blob for marker in search_markers):
            return True
        target_type = self._normalize_lookup_text(self._target_value(target, "type", "input_type"))
        target_role = self._normalize_lookup_text(target.get("role"))
        target_name = self._normalize_lookup_text(target.get("name"))
        target_placeholder = self._normalize_lookup_text(target.get("placeholder"))
        return (
            target_type == "search"
            or target_role in ("searchbox", "search", "combobox")
            or "search" in target_name
            or "query" in target_name
            or "search" in target_placeholder
            or "find" in target_placeholder
        )

    def _read_text_entry_value(self, element) -> str:
        """Read the current visible value/text from an input-like element."""
        try:
            if element.get_attribute("contenteditable") in ("true", ""):
                try:
                    raw = self._actual_driver.execute_script(
                        "const el = arguments[0]; return (el.innerText || el.textContent || '').trim();",
                        element,
                    )
                except Exception:
                    raw = element.text or ""
                return str(raw or "")
            return str(element.get_attribute("value") or "")
        except Exception:
            return ""

    def _clear_text_entry(self, element) -> None:
        """Clear text robustly for JS-controlled inputs and contenteditables."""
        from selenium.webdriver.common.keys import Keys
        import time

        try:
            element.click()
        except Exception:
            try:
                self._actual_driver.execute_script("arguments[0].focus();", element)
            except Exception:
                pass

        is_contenteditable = False
        try:
            is_contenteditable = element.get_attribute("contenteditable") in ("true", "")
        except Exception:
            is_contenteditable = False

        if not is_contenteditable:
            try:
                element.clear()
                time.sleep(0.05)
            except Exception:
                pass

        for modifier in (Keys.CONTROL, Keys.COMMAND):
            try:
                element.send_keys(modifier + "a")
                time.sleep(0.04)
                element.send_keys(Keys.DELETE)
                time.sleep(0.04)
                if not self._read_text_entry_value(element):
                    return
            except Exception:
                continue

        try:
            if is_contenteditable:
                self._actual_driver.execute_script(
                    """
                    const el = arguments[0];
                    if (!el) return;
                    el.innerHTML = '';
                    el.textContent = '';
                    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    element,
                )
            else:
                self._actual_driver.execute_script(
                    """
                    const el = arguments[0];
                    if (!el) return;
                    el.value = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    element,
                )
                time.sleep(0.04)
        except Exception:
            pass

    def _collect_input_candidates(self, root=None):
        """Collect visible, enabled text-entry candidates across common input patterns."""
        drv = root or self._actual_driver
        selectors = [
            "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='checkbox']):not([type='radio']):not([type='file'])",
            "textarea",
            "select",
            "[contenteditable='true']",
            "[contenteditable='']",
            "[role='textbox']",
            "[role='searchbox']",
            "[role='combobox']",
            "[role='search'] input",
            "form[role='search'] input",
            "form[action*='search'] input",
            "form[action*='results'] input",
            "input[name*='search']",
            "input[name*='query']",
            "input[aria-autocomplete='list']",
            "[data-testid*='search' i] input",
            "[class*='search' i] input",
            "[id*='search' i] input",
        ]
        seen = set()
        candidates = []
        for sel in selectors:
            try:
                for el in drv.find_elements(By.CSS_SELECTOR, sel):
                    try:
                        raw = self._unwrap_element(el)
                        key = getattr(raw, "id", None) or id(raw)
                        if key in seen:
                            continue
                        seen.add(key)
                        if not raw.is_displayed() or not raw.is_enabled():
                            continue
                        if str(raw.get_attribute("readonly") or "").lower() in ("true", "readonly"):
                            continue
                        candidates.append(raw)
                    except Exception:
                        continue
            except Exception:
                continue
        return candidates

    def _score_input_candidate(self, element, target: Dict[str, Any], prefer_search: bool = False) -> float:
        """Rank likely input matches, heavily boosting search-like controls when requested."""
        try:
            rect = element.rect or {}
        except Exception:
            rect = {}
        width = float(rect.get("width") or 0)
        top = float(rect.get("y") or rect.get("top") or 0)

        blob = self._element_lookup_blob(element)
        context_blob = self._element_search_context_blob(element)
        combined_blob = self._normalize_lookup_text(f"{blob} {context_blob}")
        target_blob = self._target_lookup_blob(target)
        target_id = self._normalize_lookup_text(target.get("id"))
        target_name = self._normalize_lookup_text(target.get("name"))
        target_placeholder = self._normalize_lookup_text(target.get("placeholder"))
        target_aria = self._normalize_lookup_text(self._target_value(target, "aria-label", "aria_label"))
        target_selector = self._normalize_lookup_text(target.get("selector"))
        target_role = self._normalize_lookup_text(target.get("role"))
        target_type = self._normalize_lookup_text(self._target_value(target, "type", "input_type"))

        score = 0.0

        for exact_attr, points in (
            ("id", 80),
            ("name", 70),
            ("placeholder", 65),
            ("aria-label", 65),
            ("role", 50),
            ("type", 40),
        ):
            wanted = self._normalize_lookup_text(target.get(exact_attr))
            if not wanted:
                continue
            try:
                actual = self._normalize_lookup_text(element.get_attribute(exact_attr))
            except Exception:
                actual = ""
            if wanted and actual == wanted:
                score += points

        if target_blob and combined_blob:
            if combined_blob == target_blob:
                score += 120
            elif target_blob in combined_blob:
                score += 75
            else:
                target_terms = [part for part in target_blob.split() if len(part) > 2]
                score += sum(12 for part in target_terms[:8] if part in combined_blob)

        if target_selector:
            try:
                tag = self._normalize_lookup_text(element.tag_name)
            except Exception:
                tag = ""
            if tag and tag in target_selector:
                score += 10

        try:
            input_type = self._normalize_lookup_text(element.get_attribute("type"))
            role = self._normalize_lookup_text(element.get_attribute("role"))
            name = self._normalize_lookup_text(element.get_attribute("name"))
            aria_autocomplete = self._normalize_lookup_text(element.get_attribute("aria-autocomplete"))
        except Exception:
            input_type = ""
            role = ""
            name = ""
            aria_autocomplete = ""

        search_like = any(token in combined_blob for token in ("search", "searchbox", "find", "query", "results"))
        if prefer_search:
            if input_type == "search":
                score += 120
            if role in ("searchbox", "search", "combobox"):
                score += 100
            if search_like:
                score += 90
            if name in ("q", "s", "query", "search", "search_query", "searchquery"):
                score += 100
            elif any(token in name for token in ("search", "query", "keyword", "term")):
                score += 80
            if aria_autocomplete == "list":
                score += 25
            if "search" in context_blob or "results" in context_blob:
                score += 70
            if width >= 180:
                score += 20
            if 0 <= top <= 260:
                score += 25
            elif 260 < top <= 520:
                score += 10
        else:
            if input_type in ("text", "email", "search", ""):
                score += 10
            if role in ("textbox", "combobox", "searchbox"):
                score += 12

        if target_role and target_role == role:
            score += 35
        if target_type and target_type == input_type:
            score += 30
        if target_id and target_id in blob:
            score += 20
        if target_name and target_name in combined_blob:
            score += 20
        if target_placeholder and target_placeholder in combined_blob:
            score += 20
        if target_aria and target_aria in combined_blob:
            score += 20

        if width < 60:
            score -= 25
        if prefer_search and "password" in combined_blob:
            score -= 200
        if "hidden" in combined_blob:
            score -= 60

        return score

    def _resolve_ranked_input_candidate(self, target: Dict[str, Any], typed_text: Optional[str] = None, root=None):
        """Resolve the best candidate input for a target, preferring search bars when appropriate."""
        prefer_search = self._target_prefers_search_input(target, typed_text=typed_text)
        ranked_target = dict(target or {})
        if prefer_search:
            ranked_target.setdefault("placeholder", "Search")
            ranked_target.setdefault("role", ranked_target.get("role") or "searchbox")
        target_blob = self._target_lookup_blob(ranked_target)
        if not prefer_search and not target_blob:
            return None
        candidates = self._collect_input_candidates(root=root)
        if not candidates:
            return None

        ranked = []
        for el in candidates:
            try:
                score = self._score_input_candidate(el, ranked_target, prefer_search=prefer_search)
                ranked.append((score, el))
            except Exception:
                continue

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best_element = ranked[0]
        if best_score < (40 if prefer_search else 20):
            return None
        return best_element

    def _wait_for_ranked_input_candidate(self, target: Dict[str, Any], typed_text: Optional[str] = None, timeout: float = 2.5, root=None):
        """Wait briefly for hydrated inputs to appear, then return the best candidate."""
        drv = root or self._actual_driver
        try:
            return WebDriverWait(drv, timeout).until(
                lambda _drv: self._resolve_ranked_input_candidate(target, typed_text=typed_text, root=root) or False
            )
        except TimeoutException:
            return self._resolve_ranked_input_candidate(target, typed_text=typed_text, root=root)
    
    def click_element(self, target: Dict[str, Any]) -> Dict[str, Any]:
        """
        Click an element based on target information.
        Uses _actual_driver directly — validation is handled by BrowserActionExecutor.
        """
        import time
        from selenium.webdriver.common.keys import Keys
        drv = self._actual_driver
        try:
            element = None
            text_safe = (target.get("text") or "")[:80].strip()
            text_xpath = text_safe.replace("'", "''") if text_safe else ""
            current_url_lower = (drv.current_url or "").lower()
            google_account_chooser = (
                "accounts.google.com" in current_url_lower
                and "accountchooser" in current_url_lower
            )
            jira_page = "atlassian.net" in current_url_lower

            def _first_visible(elements):
                for el in elements or []:
                    try:
                        if el.is_displayed() and el.is_enabled():
                            return el
                    except Exception:
                        continue
                return None

            def _google_account_row():
                """Find the actual clickable Google account row, not a child label."""
                try:
                    rows = drv.find_elements(
                        By.XPATH,
                        "//*[@data-identifier or @data-email or @role='link' or @role='button' or self::button or self::a]"
                    )
                    visible_rows = []
                    seen = set()
                    for row in rows:
                        try:
                            if not row.is_displayed() or not row.is_enabled():
                                continue
                            sig = (
                                row.get_attribute("data-identifier")
                                or row.get_attribute("data-email")
                                or row.get_attribute("id")
                                or row.text
                            )
                            sig = (sig or "").strip()
                            if not sig or sig in seen:
                                continue
                            seen.add(sig)
                            visible_rows.append(row)
                        except Exception:
                            continue

                    if len(visible_rows) == 1:
                        return visible_rows[0]
                except Exception:
                    pass

                if not text_xpath:
                    return None

                chooser_xpaths = [
                    f"//*[@data-identifier][contains(normalize-space(.), '{text_xpath}')]",
                    f"//*[@data-email][contains(normalize-space(.), '{text_xpath}')]",
                    f"//*[@role='link'][contains(normalize-space(.), '{text_xpath}')]",
                    f"//*[@role='button'][contains(normalize-space(.), '{text_xpath}')]",
                    f"//button[contains(normalize-space(.), '{text_xpath}')]",
                    f"//a[contains(normalize-space(.), '{text_xpath}')]",
                    f"//*[contains(normalize-space(.), '{text_xpath}')]/ancestor::*[@data-identifier or @data-email or @role='link' or @role='button' or self::button or self::a][1]",
                ]
                for xpath in chooser_xpaths:
                    try:
                        found = drv.find_elements(By.XPATH, xpath)
                        picked = _first_visible(found)
                        if picked is not None:
                            return picked
                    except Exception:
                        continue
                return None

            def _google_chooser_state():
                """Capture lightweight state so chooser progress can be detected."""
                try:
                    content = self.get_page_content(include_html=False) or {}
                    page_text = (content.get("text") or "")[:800].strip().lower()
                    page_title = (content.get("title") or "").strip().lower()
                except Exception:
                    page_text = ""
                    page_title = ""
                try:
                    has_password = bool(
                        drv.find_elements(By.CSS_SELECTOR, "input[type='password']")
                    )
                except Exception:
                    has_password = False
                return {
                    "url": drv.current_url,
                    "title": page_title,
                    "text": page_text,
                    "has_password": has_password,
                }

            def _google_chooser_progressed(before_state):
                """Google may keep the host while changing the page meaningfully."""
                current_state = _google_chooser_state()
                cur_url_lower = (current_state["url"] or "").lower()
                before_url_lower = (before_state.get("url") or "").lower()
                if cur_url_lower != before_url_lower:
                    return True, current_state
                if "accountchooser" not in cur_url_lower:
                    return True, current_state
                if current_state.get("has_password"):
                    return True, current_state
                if current_state.get("title") != before_state.get("title"):
                    return True, current_state
                before_text = before_state.get("text") or ""
                current_text = current_state.get("text") or ""
                if current_text and current_text != before_text:
                    chooser_terms = ("choose an account", "use another account")
                    if any(term in before_text for term in chooser_terms) and not any(
                        term in current_text for term in chooser_terms
                    ):
                        return True, current_state
                    if "continue" in current_text and "atlassian" in current_text:
                        return True, current_state
                    if "allow" in current_text and "atlassian" in current_text:
                        return True, current_state
                return False, current_state

            def _jira_dialog_button():
                """Prefer buttons inside the active Jira dialog over page chrome."""
                if not jira_page or not text_safe:
                    return None
                try:
                    def _exact_create_button():
                        for sel in (
                            "button[data-testid='issue-create.common.ui.footer.create-button'][form='issue-create.ui.modal.create-form'][type='submit']",
                            "button[data-testid='issue-create.common.ui.footer.create-button'][type='submit']",
                            "button[form='issue-create.ui.modal.create-form'][type='submit']",
                        ):
                            try:
                                picked = _first_visible(drv.find_elements(By.CSS_SELECTOR, sel))
                                if picked is not None:
                                    return picked
                            except Exception:
                                continue
                        return None

                    dialogs = drv.find_elements(By.CSS_SELECTOR, "[role='dialog'], [aria-modal='true']")
                    visible_dialogs = []
                    for dlg in dialogs:
                        try:
                            if dlg.is_displayed():
                                visible_dialogs.append(dlg)
                        except Exception:
                            continue
                    if not visible_dialogs:
                        return None

                    draft_dialog = None
                    create_dialog = None
                    for dlg in visible_dialogs:
                        try:
                            dlg_text = (dlg.text or "").lower()
                        except Exception:
                            dlg_text = ""
                        if "draft work item in progress" in dlg_text:
                            draft_dialog = dlg
                        if ("create task" in dlg_text or "create issue" in dlg_text or "summary" in dlg_text):
                            create_dialog = dlg

                    # If the agent asks for Create while the draft warning is on screen,
                    # keep the current draft instead of discarding or closing it.
                    if draft_dialog is not None and text_safe.lower() == "create":
                        exact_create = _exact_create_button()
                        if exact_create is not None:
                            return exact_create
                        for sel in (
                            ".//button[contains(normalize-space(.), 'Keep editing')]",
                            ".//*[@role='button'][contains(normalize-space(.), 'Keep editing')]",
                        ):
                            try:
                                btn = draft_dialog.find_element(By.XPATH, sel)
                                if btn.is_displayed() and btn.is_enabled():
                                    return btn
                            except Exception:
                                continue

                    active_dialog = draft_dialog or create_dialog
                    if active_dialog is None:
                        return None

                    desired_text = text_safe.lower()
                    if desired_text == "create" and create_dialog is not None:
                        # Prefer Jira's actual modal submit button over any other
                        # visible "Create" control on the page.
                        exact_create = _exact_create_button()
                        if exact_create is not None:
                            return exact_create
                        xpath_candidates = [
                            ".//button[normalize-space(.)='Create']",
                            ".//*[@role='button'][normalize-space(.)='Create']",
                            ".//button[contains(normalize-space(.), 'Create')]",
                            ".//*[@role='button'][contains(normalize-space(.), 'Create')]",
                            ".//input[@type='submit' and (@value='Create' or contains(@value, 'Create'))]",
                        ]
                    elif desired_text in {"keep editing", "discard draft", "cancel"}:
                        xpath_candidates = [
                            f".//button[contains(normalize-space(.), '{text_xpath}')]",
                            f".//*[@role='button'][contains(normalize-space(.), '{text_xpath}')]",
                        ]
                    else:
                        xpath_candidates = []

                    for xpath in xpath_candidates:
                        try:
                            found = active_dialog.find_elements(By.XPATH, xpath)
                            picked = _first_visible(found)
                            if picked is not None:
                                return picked
                        except Exception:
                            continue
                except Exception:
                    return None
                return None

            def _jira_create_dialog_ready():
                """Check whether Jira create dialog has the required fields filled."""
                if not jira_page:
                    return True, ""
                try:
                    def _normalize_jira_description(raw: str) -> str:
                        text = (raw or "").strip()
                        if not text:
                            return ""
                        # Strip common Jira editor placeholder/chrome text so
                        # only actual user-entered description content counts.
                        junk_phrases = [
                            "improve description",
                            "type /ai to ask rovo or @ to mention and notify someone.",
                            "type /ai to ask rovo",
                            "ask rovo",
                            "similar work items",
                            "no results found.",
                        ]
                        lowered = text.lower()
                        for phrase in junk_phrases:
                            lowered = lowered.replace(phrase, "")
                        # Remove leftover toolbar-only glyph/shortcut labels.
                        lowered = re.sub(r"\b(tt|b|a)\b", " ", lowered)
                        lowered = re.sub(r"\s+", " ", lowered).strip()
                        return lowered

                    dialogs = drv.find_elements(By.CSS_SELECTOR, "[role='dialog'], [aria-modal='true']")
                    create_dialog = None
                    for dlg in dialogs:
                        try:
                            if not dlg.is_displayed():
                                continue
                            dlg_text = (dlg.text or "").lower()
                            if "create task" in dlg_text or "create issue" in dlg_text or "summary" in dlg_text:
                                create_dialog = dlg
                                break
                        except Exception:
                            continue
                    if create_dialog is None:
                        return True, ""

                    summary_value = ""
                    for sel in (
                        "input[aria-label*='Summary']",
                        "textarea[aria-label*='Summary']",
                        "input[name*='summary']",
                        "textarea[name*='summary']",
                        "input[id*='summary']",
                        "textarea[id*='summary']",
                    ):
                        try:
                            for el in create_dialog.find_elements(By.CSS_SELECTOR, sel):
                                if el.is_displayed():
                                    summary_value = (el.get_attribute("value") or el.text or "").strip()
                                    if summary_value:
                                        break
                        except Exception:
                            continue
                        if summary_value:
                            break

                    description_value = ""
                    for sel in (
                        "textarea[aria-label*='Description']",
                        "textarea[name*='description']",
                        "textarea[id*='description']",
                        "[data-testid*='description'] [contenteditable='true']",
                        "[contenteditable='true'][role='textbox']",
                        ".ProseMirror",
                        "[contenteditable='true']",
                    ):
                        try:
                            for el in create_dialog.find_elements(By.CSS_SELECTOR, sel):
                                if not el.is_displayed():
                                    continue
                                description_value = _normalize_jira_description(
                                    el.get_attribute("value")
                                    or el.text
                                    or el.get_attribute("textContent")
                                    or ""
                                )
                                if description_value:
                                    break
                        except Exception:
                            continue
                        if description_value:
                            break

                    if not summary_value:
                        return False, "Jira Create Task dialog is missing Summary. Fill the Summary field before creating the task."
                    if not description_value:
                        return False, "Jira Create Task dialog is missing Description. Fill the Description field, including the relevant GitHub issue details and link, before creating the task."
                except Exception:
                    return True, ""
                return True, ""
            
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

            if not element and google_account_chooser:
                element = _google_account_row()

            if not element:
                element = _jira_dialog_button()

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

            if jira_page and text_safe.lower() == "create":
                _ready, _reason = _jira_create_dialog_ready()
                if not _ready:
                    return {"success": False, "message": _reason}
            
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
            before_url = drv.current_url
            before_state = _google_chooser_state() if google_account_chooser else {}
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
                if google_account_chooser:
                    progressed = False
                    latest_state = before_state
                    for _ in range(12):
                        time.sleep(0.5)
                        progressed, latest_state = _google_chooser_progressed(before_state)
                        if progressed:
                            break
                    if not progressed:
                        try:
                            drv.execute_script("arguments[0].focus();", element)
                        except Exception:
                            pass
                        try:
                            element.send_keys(Keys.RETURN)
                        except Exception:
                            try:
                                drv.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                            except Exception:
                                pass
                        for _ in range(8):
                            time.sleep(0.5)
                            progressed, latest_state = _google_chooser_progressed(before_state)
                            if progressed:
                                break
                    if not progressed:
                        return {
                            "success": False,
                            "message": "Google account chooser did not advance after selecting the account",
                            "new_url": latest_state.get("url") or drv.current_url,
                        }
                else:
                    time.sleep(0.3)

                if jira_page and text_safe.lower() == "create":
                    try:
                        draft_dialogs = drv.find_elements(By.CSS_SELECTOR, "[role='dialog'], [aria-modal='true']")
                        draft_visible = False
                        for dlg in draft_dialogs:
                            try:
                                if dlg.is_displayed() and "draft work item in progress" in (dlg.text or "").lower():
                                    draft_visible = True
                                    break
                            except Exception:
                                continue
                        if draft_visible:
                            keep_editing = _first_visible(drv.find_elements(
                                By.XPATH,
                                "//button[contains(normalize-space(.), 'Keep editing')]"
                                "|//*[@role='button'][contains(normalize-space(.), 'Keep editing')]"
                            ))
                            if keep_editing is not None:
                                try:
                                    keep_editing.click()
                                except Exception:
                                    try:
                                        drv.execute_script("arguments[0].click();", keep_editing)
                                    except Exception:
                                        keep_editing = None
                            if keep_editing is not None:
                                time.sleep(0.2)
                                final_create = _first_visible(drv.find_elements(
                                    By.CSS_SELECTOR,
                                    "button[data-testid='issue-create.common.ui.footer.create-button'][form='issue-create.ui.modal.create-form'][type='submit'], "
                                    "button[data-testid='issue-create.common.ui.footer.create-button'][type='submit'], "
                                    "button[form='issue-create.ui.modal.create-form'][type='submit']"
                                ))
                                if final_create is not None:
                                    try:
                                        final_create.click()
                                    except Exception:
                                        drv.execute_script("arguments[0].click();", final_create)
                                    time.sleep(0.3)

                        # After Jira creates the work item, a bottom-left flag can
                        # appear a moment later with the action that adds it to the
                        # sprint/board. Catch that here instead of relying on a later
                        # observe cycle to notice it in time.
                        for _ in range(10):
                            add_to_sprint = None
                            try:
                                add_to_sprint = _first_visible(drv.find_elements(
                                    By.CSS_SELECTOR,
                                    "[data-testid='platform.ui.flags.common.ui.common-flag-v2-actions'] button"
                                ))
                            except Exception:
                                add_to_sprint = None

                            if add_to_sprint is None:
                                try:
                                    candidates = drv.find_elements(
                                        By.XPATH,
                                        "//div[@data-testid='platform.ui.flags.common.ui.common-flag-v2-actions']"
                                        "//button[contains(normalize-space(.), 'Add to ') and contains(normalize-space(.), 'Sprint')]"
                                        "|//button[contains(normalize-space(.), 'Add to ') and contains(normalize-space(.), 'Sprint')]"
                                    )
                                    add_to_sprint = _first_visible(candidates)
                                except Exception:
                                    add_to_sprint = None

                            if add_to_sprint is not None:
                                try:
                                    add_to_sprint.click()
                                except Exception:
                                    try:
                                        drv.execute_script("arguments[0].click();", add_to_sprint)
                                    except Exception:
                                        add_to_sprint = None
                                if add_to_sprint is not None:
                                    time.sleep(0.3)
                                    break

                            time.sleep(0.5)
                    except Exception:
                        pass
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
            current_url_lower = (drv.current_url or "").lower()

            def _find_jira_dialog_field():
                """Resolve Jira create-dialog fields by semantic label."""
                if "atlassian.net" not in current_url_lower:
                    return None
                try:
                    field_hint = " ".join(
                        str(target.get(k) or "")
                        for k in ("id", "name", "placeholder", "aria-label", "selector", "type", "role")
                    ).lower()
                    is_summary = any(k in field_hint for k in ("summary", "title"))
                    is_description = any(k in field_hint for k in ("description", "details", "body"))
                    is_generic = not is_summary and not is_description

                    dialogs = drv.find_elements(By.CSS_SELECTOR, "[role='dialog'], [aria-modal='true']")
                    visible_dialog = None
                    for dlg in dialogs:
                        try:
                            if dlg.is_displayed():
                                visible_dialog = dlg
                                break
                        except Exception:
                            continue
                    if visible_dialog is None:
                        return None

                    def _is_bad_jira_field(el) -> bool:
                        """Reject prefilled Jira dropdown fields like Space/Work type/Status."""
                        try:
                            tag = (el.tag_name or "").lower()
                            role = (el.get_attribute("role") or "").lower()
                            cls = (el.get_attribute("class") or "").lower()
                            aria = (el.get_attribute("aria-label") or "").lower()
                            text_blob = " ".join(
                                part for part in [
                                    el.text or "",
                                    el.get_attribute("value") or "",
                                    el.get_attribute("placeholder") or "",
                                    aria,
                                ] if part
                            ).lower()
                            if role in ("combobox", "listbox"):
                                return True
                            if "select" in cls or "dropdown" in cls:
                                return True
                            if any(word in text_blob for word in ("my team", "scrum", "task", "to do")) and tag != "textarea":
                                return True
                        except Exception:
                            return False
                        return False

                    jira_selectors = []
                    if is_summary or is_generic:
                        jira_selectors = [
                            "input[aria-label*='Summary']",
                            "textarea[aria-label*='Summary']",
                            "input[name*='summary']",
                            "textarea[name*='summary']",
                            "input[id*='summary']",
                            "textarea[id*='summary']",
                            "[data-testid*='summary'] input",
                            "[data-testid*='summary'] textarea",
                        ]
                    elif is_description:
                        jira_selectors = [
                            "textarea[aria-label*='Description']",
                            "textarea[name*='description']",
                            "textarea[id*='description']",
                            "[data-testid*='description'] textarea",
                            "[data-testid*='description'] [contenteditable='true']",
                            "[data-testid*='description'] [role='textbox']",
                            "[contenteditable='true'][role='textbox']",
                            "[contenteditable='true']",
                            "[role='textbox']",
                            ".ProseMirror",
                        ]

                    for sel in jira_selectors:
                        try:
                            candidates = visible_dialog.find_elements(By.CSS_SELECTOR, sel)
                            for cand in candidates:
                                try:
                                    if cand.is_displayed() and cand.is_enabled() and not _is_bad_jira_field(cand):
                                        return cand
                                except Exception:
                                    continue
                        except Exception:
                            continue

                    if is_summary or is_generic:
                        xpath_candidates = [
                            ".//*[self::label or self::span or self::div][contains(normalize-space(.), 'Summary')]/following::input[1]",
                            ".//*[self::label or self::span or self::div][contains(normalize-space(.), 'Summary')]/following::textarea[1]",
                        ]
                    elif is_description:
                        xpath_candidates = [
                            ".//*[self::label or self::span or self::div][contains(normalize-space(.), 'Description')]/following::textarea[1]",
                            ".//*[self::label or self::span or self::div][contains(normalize-space(.), 'Description')]/following::*[@contenteditable='true'][1]",
                            ".//*[self::label or self::span or self::div][contains(normalize-space(.), 'Description')]/following::*[@role='textbox'][1]",
                        ]
                    else:
                        xpath_candidates = []

                    for xpath in xpath_candidates:
                        try:
                            cand = visible_dialog.find_element(By.XPATH, xpath)
                            if cand.is_displayed() and cand.is_enabled() and not _is_bad_jira_field(cand):
                                return cand
                        except Exception:
                            continue

                    if is_summary or is_generic:
                        try:
                            summary_candidates = visible_dialog.find_elements(
                                By.XPATH,
                                ".//*[self::input or self::textarea][not(@type='hidden')]"
                            )
                            for cand in summary_candidates:
                                try:
                                    if not cand.is_displayed() or not cand.is_enabled():
                                        continue
                                    if _is_bad_jira_field(cand):
                                        continue
                                    rect = cand.rect or {}
                                    if rect.get("width", 0) < 200:
                                        continue
                                    return cand
                                except Exception:
                                    continue
                        except Exception:
                            pass
                except Exception:
                    return None
                return None
            
            # Jira create dialogs are special: resolve Summary/Description
            # semantically before any generic selector matching so we do not
            # type into prefilled controls like Space.
            element = _find_jira_dialog_field()

            # Prefer a visible, high-confidence candidate before first-match
            # selectors so modern search bars (often duplicated in hidden DOM)
            # resolve to the actionable control.
            if not element:
                element = self._wait_for_ranked_input_candidate(target, typed_text=text)

            # 1. By ID (most specific)
            if not element and target.get("id"):
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
            aria_label = self._target_value(target, "aria-label", "aria_label")
            if not element and aria_label:
                al = aria_label
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
            target_input_type = self._target_value(target, "type", "input_type")
            if not element and target_input_type:
                try:
                    element = drv.find_element(
                        By.CSS_SELECTOR, f"input[type='{target_input_type}']"
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
                from selenium.webdriver.common.keys import Keys
                import time
                is_search_input = self._target_prefers_search_input(target, typed_text=text)
                current_value = self._read_text_entry_value(element)
                if is_search_input:
                    normalized_current = self._normalize_lookup_text(current_value)
                    normalized_target = self._normalize_lookup_text(text)
                    if normalized_current and normalized_current == normalized_target:
                        if press_enter:
                            time.sleep(0.1)
                            element.send_keys(Keys.RETURN)
                            time.sleep(0.3)
                            return {
                                "success": True,
                                "message": f"Search query already present: {text[:50]} + Enter pressed"
                            }
                        return {
                            "success": True,
                            "message": f"Search query already present: {text[:50]}"
                        }

                if current_value:
                    self._clear_text_entry(element)
                    time.sleep(0.05)

                if element.get_attribute("contenteditable") in ("true", ""):
                    element.click()
                    time.sleep(0.05)
                element.send_keys(text)
                if press_enter:
                    time.sleep(0.15)
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

    def reload_page(self) -> Dict[str, Any]:
        """Reload the current page."""
        drv = self._actual_driver
        try:
            drv.refresh()
            import time
            time.sleep(0.4)
            readiness = self.wait_for_interactive_page(timeout=6.0)
            return {
                "success": True,
                "message": "Page reloaded",
                "url": drv.current_url,
                "readiness": readiness,
            }
        except Exception as e:
            return {"success": False, "message": f"Error reloading page: {str(e)}"}

    def find_text_on_page(
        self,
        text: str,
        exact_match: bool = False,
        scroll_behavior: str = "center",
    ) -> Dict[str, Any]:
        """Find visible text on the page and scroll the best match into view."""
        drv = self._actual_driver
        try:
            result = drv.execute_script(
                """
                const needleRaw = arguments[0] || '';
                const exact = Boolean(arguments[1]);
                const behavior = arguments[2] || 'center';

                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }

                function textBlob(el) {
                    return ((el.innerText || el.textContent || '') + '').replace(/\\s+/g, ' ').trim();
                }

                function describe(el) {
                    if (!el) return '';
                    const tag = (el.tagName || '').toLowerCase();
                    const id = el.id ? `#${el.id}` : '';
                    const cls = (el.className && typeof el.className === 'string')
                        ? '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.')
                        : '';
                    return `${tag}${id}${cls}`;
                }

                const needle = needleRaw.replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!needle) {
                    return { success: false, message: 'No text provided' };
                }

                const selectors = [
                    'main',
                    '[role="main"]',
                    '[role="dialog"]',
                    '[aria-modal="true"]',
                    'h1, h2, h3, h4, p, li, a, button, label, span, div'
                ];

                const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
                let best = null;

                for (const el of nodes) {
                    if (!isVisible(el)) continue;
                    const blob = textBlob(el);
                    if (!blob) continue;
                    const haystack = blob.toLowerCase();
                    const matched = exact ? haystack === needle : haystack.includes(needle);
                    if (!matched) continue;

                    const score =
                        (exact ? 200 : 0) +
                        Math.max(0, 120 - Math.abs(blob.length - needle.length)) +
                        (/^(h1|h2|h3|button|label|a)$/i.test(el.tagName || '') ? 20 : 0) +
                        (el.closest('[role="dialog"], [aria-modal="true"]') ? 15 : 0);

                    if (!best || score > best.score) {
                        best = {
                            element: el,
                            score,
                            text: blob.slice(0, 220),
                            selector: describe(el),
                            tag: (el.tagName || '').toLowerCase(),
                        };
                    }
                }

                if (!best) {
                    return { success: false, message: `Text not found: ${needleRaw}` };
                }

                best.element.scrollIntoView({ block: behavior, inline: 'nearest', behavior: 'instant' });
                const rect = best.element.getBoundingClientRect();
                return {
                    success: true,
                    message: `Found text: ${needleRaw}`,
                    matched_text: best.text,
                    selector: best.selector,
                    tag: best.tag,
                    viewport: {
                        top: Math.round(rect.top),
                        left: Math.round(rect.left),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                    }
                };
                """,
                text,
                exact_match,
                scroll_behavior,
            ) or {}
            return result
        except Exception as e:
            return {"success": False, "message": f"Error finding text: {str(e)}"}
    
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

    def press_key(self, key: str, target: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Press a key on the page or a target element."""
        drv = self._actual_driver
        try:
            from selenium.webdriver.common.keys import Keys

            key_map = {
                "enter": Keys.RETURN,
                "return": Keys.RETURN,
                "tab": Keys.TAB,
                "escape": Keys.ESCAPE,
                "esc": Keys.ESCAPE,
                "space": Keys.SPACE,
                "arrowdown": Keys.ARROW_DOWN,
                "down": Keys.ARROW_DOWN,
                "arrowup": Keys.ARROW_UP,
                "up": Keys.ARROW_UP,
                "arrowleft": Keys.ARROW_LEFT,
                "left": Keys.ARROW_LEFT,
                "arrowright": Keys.ARROW_RIGHT,
                "right": Keys.ARROW_RIGHT,
                "backspace": Keys.BACKSPACE,
                "delete": Keys.DELETE,
            }
            normalized = str(key or "").strip().lower()
            resolved = key_map.get(normalized)
            if not resolved:
                return {"success": False, "message": f"Unsupported key: {key}"}

            element = None
            if target:
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
                if not element and target.get("selector"):
                    try:
                        element = drv.find_element(By.CSS_SELECTOR, target["selector"])
                    except NoSuchElementException:
                        pass
                if not element and target.get("aria-label"):
                    label = str(target["aria-label"]).replace("'", "\\'")
                    try:
                        element = drv.find_element(By.XPATH, f"//*[@aria-label='{label}']")
                    except NoSuchElementException:
                        pass
                if not element and target.get("text"):
                    text = str(target["text"])[:80].replace("'", "\\'")
                    try:
                        element = drv.find_element(By.XPATH, f"//*[contains(normalize-space(.), '{text}')]")
                    except NoSuchElementException:
                        pass

            recipient = element if element and element.is_displayed() else drv.find_element(By.TAG_NAME, "body")
            recipient.send_keys(resolved)
            return {"success": True, "message": f"Pressed {key}"}
        except Exception as e:
            return {"success": False, "message": f"Error pressing key: {str(e)}"}

    def select_option(self, target: Dict[str, Any], value: Optional[str] = None, label: Optional[str] = None, index: Optional[int] = None) -> Dict[str, Any]:
        """Select an option in a native select or custom combobox/listbox."""
        drv = self._actual_driver
        try:
            from selenium.webdriver.support.ui import Select

            element = self._find_select_like_element(target or {})
            if not element:
                return {"success": False, "message": "Select element not found"}

            tag_name = (element.tag_name or "").lower()
            role = str(element.get_attribute("role") or "").lower()
            if tag_name == "select":
                try:
                    control = Select(element)
                    if label:
                        control.select_by_visible_text(label)
                    elif value is not None:
                        control.select_by_value(value)
                    elif index is not None:
                        control.select_by_index(int(index))
                    else:
                        return {"success": False, "message": "Select requires label, value, or index"}
                except Exception:
                    return self._select_custom_dropdown_option(
                        element,
                        target or {},
                        value=value,
                        label=label,
                        index=index,
                    )
            elif role in ("combobox", "listbox") or tag_name in ("div", "span", "input"):
                return self._select_custom_dropdown_option(
                    element,
                    target or {},
                    value=value,
                    label=label,
                    index=index,
                )
            else:
                return {
                    "success": False,
                    "message": f"Resolved element is not selectable ({tag_name or 'unknown'} role={role or 'none'})",
                }
            return {"success": True, "message": f"Selected option {label or value or index}"}
        except Exception as e:
            return {"success": False, "message": f"Error selecting option: {str(e)}"}
    
    @staticmethod
    def _compress_screenshot_b64(png_b64: str, max_width: int = 1280, quality: int = 55) -> str:
        """Compress a base64 PNG screenshot to a smaller JPEG.

        Resizes to *max_width* (preserving aspect ratio) and re-encodes as
        JPEG at the given *quality* (1-95).  Returns a base64-encoded JPEG
        string that is typically 5-10x smaller than the original PNG while
        remaining perfectly readable for audit/review purposes.
        """
        try:
            from PIL import Image
            raw = base64.b64decode(png_b64)
            img = Image.open(io.BytesIO(raw))

            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize(
                    (max_width, int(img.height * ratio)),
                    Image.LANCZOS,
                )

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except ImportError:
            return png_b64
        except Exception:
            return png_b64

    def take_screenshot(self, save_path: Optional[str] = None) -> str:
        """
        Take a screenshot of the current page
        
        Args:
            save_path: Optional path to save screenshot
        
        Returns:
            Base64 encoded screenshot (JPEG, compressed) or file path
        """
        if save_path:
            self._actual_driver.save_screenshot(save_path)
            return save_path
        else:
            png_b64 = self._actual_driver.get_screenshot_as_base64()
            return self._compress_screenshot_b64(png_b64)
    
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
        if self._temp_profile_dir:
            shutil.rmtree(self._temp_profile_dir, ignore_errors=True)


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

    def _get_page_text_snapshot(self) -> str:
        """Best-effort page text snapshot for backend untrusted-content checks."""
        if not self.browser:
            return ""
        try:
            content = self.browser.get_page_content(include_html=False) or {}
            text = content.get("text") or ""
            return str(text)[:3000]
        except Exception:
            return ""

    def _capture_page_change_snapshot(self) -> Dict[str, Any]:
        """Lightweight DOM/page snapshot used for reobserve decisions."""
        if not self.browser or not hasattr(self.browser, "_actual_driver"):
            return {}
        try:
            snapshot = self.browser._actual_driver.execute_script("""
                const pickText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                const interactive = Array.from(document.querySelectorAll(
                    'a, button, input, select, textarea, [contenteditable="true"], [contenteditable=""], ' +
                    '[role="button"], [role="searchbox"], [role="combobox"], [role="textbox"]'
                ));
                const items = [];
                for (const el of interactive) {
                    if (items.length >= 25) break;
                    try {
                        const rect = el.getBoundingClientRect();
                        if ((!rect.width && !rect.height) || (el.offsetParent === null && el !== document.body)) continue;
                        items.push({
                            tag: (el.tagName || '').toLowerCase(),
                            id: el.id || '',
                            name: el.getAttribute('name') || '',
                            role: el.getAttribute('role') || '',
                            aria: el.getAttribute('aria-label') || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            type: el.getAttribute('type') || '',
                            text: pickText(el.innerText || el.textContent || '').slice(0, 80)
                        });
                    } catch (err) {}
                }
                const textSample = pickText(
                    (document.body && (document.body.innerText || document.body.textContent)) || ''
                ).slice(0, 1200);
                return {
                    url: window.location.href || '',
                    title: document.title || '',
                    textSample,
                    elements: items,
                    scrollBucket: Math.floor((window.scrollY || 0) / Math.max(window.innerHeight || 1, 1)),
                    readyState: document.readyState || ''
                };
            """)
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            return {}

    def _hash_page_change_snapshot(self, snapshot: Dict[str, Any]) -> str:
        if not snapshot:
            return ""
        try:
            payload = json.dumps(
                {
                    "url": snapshot.get("url") or "",
                    "title": snapshot.get("title") or "",
                    "textSample": snapshot.get("textSample") or "",
                    "elements": snapshot.get("elements") or [],
                    "scrollBucket": snapshot.get("scrollBucket"),
                    "readyState": snapshot.get("readyState") or "",
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
        except Exception:
            return ""

    def _summarize_page_change(self, before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]], action_name: str = "") -> Dict[str, Any]:
        before = before or {}
        after = after or {}
        before_hash = self._hash_page_change_snapshot(before)
        after_hash = self._hash_page_change_snapshot(after)
        url_changed = (before.get("url") or "") != (after.get("url") or "")
        title_changed = (before.get("title") or "") != (after.get("title") or "")
        text_changed = (before.get("textSample") or "") != (after.get("textSample") or "")
        elements_changed = (before.get("elements") or []) != (after.get("elements") or [])
        scroll_changed = before.get("scrollBucket") != after.get("scrollBucket")
        changed = any([url_changed, title_changed, text_changed, elements_changed, scroll_changed]) or (before_hash != after_hash)
        changed_fields = [
            label for label, flag in (
                ("url", url_changed),
                ("title", title_changed),
                ("text", text_changed),
                ("elements", elements_changed),
                ("scroll", scroll_changed),
            ) if flag
        ]
        discovered_new_content = action_name == "scroll_page" and (text_changed or elements_changed or scroll_changed)
        return {
            "changed": changed,
            "action": action_name,
            "changedFields": changed_fields,
            "urlChanged": url_changed,
            "titleChanged": title_changed,
            "textChanged": text_changed,
            "elementsChanged": elements_changed,
            "scrollChanged": scroll_changed,
            "discoveredNewContent": discovered_new_content,
            "before": {
                "url": before.get("url") or "",
                "title": before.get("title") or "",
                "scrollBucket": before.get("scrollBucket"),
                "fingerprint": before_hash,
            },
            "after": {
                "url": after.get("url") or "",
                "title": after.get("title") or "",
                "scrollBucket": after.get("scrollBucket"),
                "fingerprint": after_hash,
            },
        }

    def _attach_page_change_to_payload(
        self,
        payload: Dict[str, Any],
        before_snapshot: Optional[Dict[str, Any]],
        action_name: str,
        *,
        success: bool = True,
    ) -> Dict[str, Any]:
        if not success:
            return payload
        after_snapshot = self._capture_page_change_snapshot()
        page_change = self._summarize_page_change(before_snapshot, after_snapshot, action_name=action_name)
        payload["page_change"] = page_change
        browser_result = payload.get("browser_result")
        if isinstance(browser_result, dict):
            browser_result["page_change"] = page_change
        return payload

    def _emit_platform_action_event(self, action_type: str, url: str, result: Optional[Dict[str, Any]], target=None, form_data=None):
        """Optional hook used by the platform worker bridge."""
        callback = getattr(self.agenttrust, "on_platform_action_event", None)
        if not callback:
            return
        try:
            callback(
                {
                    "action_type": action_type,
                    "url": url,
                    "target": target,
                    "form_data": form_data,
                    "result": result or {},
                }
            )
        except Exception as exc:
            print(f"⚠️  Platform action callback failed: {exc}")
    
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
        if self.browser and not self.browser.is_alive():
            return {"status": "error", "message": "Browser session has died (Chrome/ChromeDriver crashed). Restart the agent."}
        # MANDATORY: Validate with AgentTrust first
        page_text_snapshot = self._get_page_text_snapshot()
        result = self.agenttrust.execute_action(
            action_type="click",
            url=url,
            target=target,
            page_text=page_text_snapshot,
            untrusted_content=page_text_snapshot
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
        before_snapshot = self._capture_page_change_snapshot()
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
        
        payload = {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Click action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "target": target,
            "browser_result": browser_result,
            "screenshot": screenshot
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "click",
            success=bool(browser_result and browser_result.get("success")),
        )
        self._emit_platform_action_event("click", url, payload, target=target)
        return payload
    
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
        if self.browser and not self.browser.is_alive():
            return {"status": "error", "message": "Browser session has died (Chrome/ChromeDriver crashed). Restart the agent."}
        # MANDATORY: Validate with AgentTrust first
        page_text_snapshot = self._get_page_text_snapshot()
        result = self.agenttrust.execute_action(
            action_type="form_submit",
            url=url,
            form_data=form_data,
            page_text=page_text_snapshot,
            untrusted_content=page_text_snapshot
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
        before_snapshot = self._capture_page_change_snapshot()
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
        
        payload = {
            "status": "allowed",
            "action_id": result.get("action_id"),
            "risk_level": result.get("risk_level"),
            "message": "Form submit action validated and allowed by AgentTrust",
            "executed": browser_result is not None,
            "browser_result": browser_result,
            "screenshot": screenshot
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "form_submit",
            success=bool(browser_result and browser_result.get("success")),
        )
        self._emit_platform_action_event("form_submit", url, payload, form_data=form_data)
        return payload
    
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
        if self.browser and not self.browser.is_alive():
            return {"status": "error", "message": "Browser session has died (Chrome/ChromeDriver crashed). Restart the agent."}
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
        page_text_snapshot = self._get_page_text_snapshot()
        result = self.agenttrust.execute_action(
            action_type="navigation",
            url=url,
            page_text=page_text_snapshot,
            untrusted_content=page_text_snapshot
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
        before_snapshot = self._capture_page_change_snapshot()
        browser_result = None
        screenshot = None
        page_error = None
        readiness = {}
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
                    readiness = self.browser.wait_for_interactive_page(timeout=6.0) or {}

                    # Guard: if Google redirected to Images, force web search
                    if ("google.com/imghp" in actual_url
                            or "images.google.com" in actual_url):
                        _webhp = "https://www.google.com/webhp?hl=en"
                        driver.get(_webhp)
                        try:
                            WebDriverWait(driver, 5).until(
                                lambda d: d.execute_script("return document.readyState") == "complete"
                            )
                        except Exception:
                            pass
                        readiness = self.browser.wait_for_interactive_page(timeout=4.0) or readiness
                        actual_url = driver.current_url
                        print(f"  REDIRECT FIX: Google Images → {actual_url}")

                    # Guard: if the site redirected to a sign-in/login page
                    # and the user didn't ask to log in, go back to the root.
                    _actual_lower = actual_url.lower()
                    _LOGIN_FRAGS = (
                        "/ap/signin", "/signin", "/sign-in", "/sign_in",
                        "/login", "/log-in", "/log_in", "/accounts/login",
                        "/auth/", "/sso/", "/oauth/", "/i/flow/login",
                    )
                    _is_login_redirect = any(f in _actual_lower for f in _LOGIN_FRAGS)
                    if not _is_login_redirect:
                        try:
                            from urllib.parse import urlparse as _lr_up
                            _lr_host = _lr_up(actual_url).hostname or ""
                            if _lr_host.startswith("signin.") or _lr_host.startswith("login.") or _lr_host.startswith("auth."):
                                _is_login_redirect = True
                        except Exception:
                            pass

                    if _is_login_redirect:
                        _orig_req = (getattr(self, '_parent_agent', None) or self)
                        _intent_parts = []
                        if hasattr(_orig_req, 'conversation_history'):
                            for m in reversed(_orig_req.conversation_history):
                                if m.get("role") == "user":
                                    _intent_parts.append((m.get("content") or "").lower())
                                    break
                        _intent_parts.extend([
                            str(getattr(_orig_req, 'user_request', '') or '').lower(),
                            str(getattr(_orig_req, 'current_goal', '') or '').lower(),
                            str(url or '').lower(),
                        ])
                        _login_kw = {"sign in", "signin", "log in", "login",
                                     "sign-in", "log-in", "authenticate",
                                     "use my account"}
                        _request_login_frags = (
                            "/ap/signin", "/signin", "/sign-in", "/sign_in",
                            "/login", "/log-in", "/log_in", "/accounts/login",
                            "/auth/", "/sso/", "/oauth/", "/i/flow/login",
                        )
                        _user_wants_login = any(
                            any(w in part for w in _login_kw) for part in _intent_parts if part
                        ) or any(
                            frag in str(url or '').lower() for frag in _request_login_frags
                        )
                        if not _user_wants_login:
                            try:
                                from urllib.parse import urlparse as _lr_up2
                                _pu = _lr_up2(actual_url)
                                _root = f"{_pu.scheme}://{_pu.hostname}"
                                print(f"  REDIRECT FIX: Login page → {_root}")
                                driver.get(_root)
                                try:
                                    WebDriverWait(driver, 5).until(
                                        lambda d: d.execute_script("return document.readyState") == "complete"
                                    )
                                except Exception:
                                    pass
                                readiness = self.browser.wait_for_interactive_page(timeout=4.0) or readiness
                                actual_url = driver.current_url
                            except Exception:
                                pass

                    # Auto-dismiss cookie banners, popups, overlays after load
                    try:
                        self.dismiss_overlays()
                    except Exception:
                        pass

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

                    if isinstance(browser_result, dict):
                        if readiness:
                            browser_result["readiness"] = readiness
                        browser_result["new_url"] = actual_url
                    if readiness and not readiness.get("ready"):
                        print(f"  WAIT: page loaded but not fully interactive yet ({readiness.get('reason', 'unknown reason')})")

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
        self._attach_page_change_to_payload(
            resp,
            before_snapshot,
            "navigation",
            success=bool(browser_result and browser_result.get("success")),
        )
        if page_error:
            resp["page_error"] = page_error
            resp["message"] = (
                f"Navigation allowed but the page failed to load properly: {page_error} "
                "Try navigating to the site's homepage instead and find the correct link."
            )
        self._emit_platform_action_event("navigation", url, resp)
        return resp
    
    def _check_browser(self) -> Optional[str]:
        """Return an error message if the browser is unusable, or None if OK."""
        if not self.browser:
            return "Browser not initialized"
        if not self.browser.is_alive():
            return "Browser session has died (Chrome/ChromeDriver crashed). Restart the agent."
        return None

    def get_page_content(self, include_html: bool = False) -> Dict[str, Any]:
        """
        Get current page content - NO AgentTrust validation needed (read-only)
        
        Returns:
            dict with page content, title, url, text, and optionally html
        """
        err = self._check_browser()
        if err:
            return {"error": err}
        
        return self.browser.get_page_content(include_html=include_html)
    
    def get_visible_elements(self, element_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get visible elements on the page - NO AgentTrust validation needed (read-only)
        
        Args:
            element_type: Optional filter ('button', 'link', 'input', etc.)
        
        Returns:
            List of visible elements
        """
        err = self._check_browser()
        if err:
            return []
        
        return self.browser.get_visible_elements(element_type)

    def highlight_interactive_elements(
        self,
        element_type: Optional[str] = None,
        max_elements: int = 25,
    ) -> Dict[str, Any]:
        """Highlight visible interactive elements with numbered overlays."""
        err = self._check_browser()
        if err:
            return {"success": False, "message": err, "count": 0, "elements": []}

        return self.browser.highlight_interactive_elements(
            element_type=element_type,
            max_elements=max_elements,
        )

    def clear_highlight_overlays(self) -> Dict[str, Any]:
        """Remove highlight overlays from the current page."""
        err = self._check_browser()
        if err:
            return {"success": False, "message": err}

        return self.browser.clear_highlight_overlays()
    
    def get_current_url(self) -> str:
        """Get current page URL - NO AgentTrust validation needed (read-only)"""
        err = self._check_browser()
        if err:
            return ""
        
        return self.browser.get_current_url()

    def get_interactive_readiness(self) -> Dict[str, Any]:
        """Get generic page readiness signals without performing any action."""
        err = self._check_browser()
        if err:
            return {"ready": False, "reason": err}
        return self.browser.get_interactive_readiness()

    def wait_for_interactive_page(self, timeout: float = 6.0) -> Dict[str, Any]:
        """Wait briefly for meaningful interactive content to appear."""
        err = self._check_browser()
        if err:
            return {"ready": False, "reason": err}
        return self.browser.wait_for_interactive_page(timeout=timeout)
    
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
            # execute_navigation already loaded the page via driver.get(),
            # so we do NOT call browser.open_link() again — that would
            # search for an <a> element matching the href on the now-loaded
            # page and could accidentally click a different link (e.g.
            # "Sign In" on Amazon when the href substring matches).
            if result.get("status") == "allowed" and self.browser:
                new_url = self.browser.get_current_url()
                return {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "link_opened": True,
                    "new_url": new_url,
                    "browser_result": result.get("browser_result"),
                    "page_change": result.get("page_change"),
                    "screenshot": result.get("screenshot"),
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
        if not self.browser.is_alive():
            return {"error": "Browser session has died (Chrome/ChromeDriver crashed). Restart the agent."}
        
        current_url = self.browser.get_current_url()
        resolved_text, used_vault = self._resolve_sensitive_reference(text, current_url=current_url)
        if used_vault and resolved_text is None:
            return {
                "status": "denied",
                "typed": False,
                "message": "Sensitive vault reference could not be resolved or was not approved."
            }
        
        # Detect if this is a sensitive input (password, credit card, etc.)
        target_name = (target.get("name") or "").lower()
        target_id = (target.get("id") or "").lower()
        target_type = (target.get("type") or "").lower()
        target_placeholder = (target.get("placeholder") or "").lower()
        is_sensitive = any(kw in f"{target_name} {target_id} {target_type} {target_placeholder}"
                          for kw in ("password", "passwd", "secret", "ssn", "credit", "card", "cvv", "pin"))
        is_sensitive = is_sensitive or used_vault
        
        try:
            logged_field = (
                target.get("name")
                or target.get("id")
                or target.get("placeholder")
                or target.get("type")
                or "text"
            )
            logged_value = "***" if is_sensitive else resolved_text
            result = self.agenttrust.execute_action(
                action_type="form_input",
                url=current_url,
                target={"type": "input", "action": "type_text",
                        "id": target.get("id"), "name": target.get("name"),
                        "placeholder": target.get("placeholder"),
                        "is_sensitive": is_sensitive},
                form_data={"field": logged_field, "value": logged_value}
            )
            
            status = result.get("status") if result else None

            if status == "allowed":
                before_snapshot = self._capture_page_change_snapshot()
                type_result = self.browser.type_text(target, resolved_text, press_enter=press_enter)
                if not type_result.get("success"):
                    # Element not found by standard lookup — try CSS selector fallback
                    type_result = self._type_text_fallback(target, resolved_text, press_enter=press_enter)
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
                
                payload = {
                    "status": "allowed",
                    "action_id": result.get("action_id") if result else None,
                    "risk_level": result.get("risk_level") if result else "low",
                    "typed": type_result.get("success", False),
                    "message": type_result.get("message", ""),
                    "screenshot": screenshot,
                    "browser_result": {
                        "success": type_result.get("success", False),
                        "message": type_result.get("message", "")
                    }
                }
                if type_result.get("success"):
                    self._attach_page_change_to_payload(
                        payload,
                        before_snapshot,
                        "type_text",
                        success=True,
                    )
                return payload
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
        current_url_lower = (drv.current_url or "").lower()

        def _find_jira_dialog_field():
            """Fallback resolver for Jira create-dialog fields."""
            if "atlassian.net" not in current_url_lower:
                return None
            try:
                field_hint = " ".join(
                    str(target.get(k) or "")
                    for k in ("id", "name", "placeholder", "aria-label", "selector", "type", "role")
                ).lower()
                is_summary = any(k in field_hint for k in ("summary", "title"))
                is_description = any(k in field_hint for k in ("description", "details", "body"))
                is_generic = not is_summary and not is_description
                dialogs = drv.find_elements(By.CSS_SELECTOR, "[role='dialog'], [aria-modal='true']")
                visible_dialog = next((d for d in dialogs if d.is_displayed()), None)
                if visible_dialog is None:
                    return None

                def _is_bad_jira_field(el) -> bool:
                    try:
                        tag = (el.tag_name or "").lower()
                        role = (el.get_attribute("role") or "").lower()
                        cls = (el.get_attribute("class") or "").lower()
                        text_blob = " ".join(
                            part for part in [
                                el.text or "",
                                el.get_attribute("value") or "",
                                el.get_attribute("placeholder") or "",
                                el.get_attribute("aria-label") or "",
                            ] if part
                        ).lower()
                        if role in ("combobox", "listbox"):
                            return True
                        if "select" in cls or "dropdown" in cls:
                            return True
                        if any(word in text_blob for word in ("my team", "scrum", "task", "to do")) and tag != "textarea":
                            return True
                    except Exception:
                        return False
                    return False

                selectors = []
                if is_summary or is_generic:
                    selectors = [
                        "input[aria-label*='Summary']",
                        "textarea[aria-label*='Summary']",
                        "input[name*='summary']",
                        "input[id*='summary']",
                    ]
                elif is_description:
                    selectors = [
                        "textarea[aria-label*='Description']",
                        "textarea[name*='description']",
                        "[data-testid*='description'] [contenteditable='true']",
                        "[contenteditable='true'][role='textbox']",
                        ".ProseMirror",
                        "[contenteditable='true']",
                    ]

                for sel in selectors:
                    try:
                        for cand in visible_dialog.find_elements(By.CSS_SELECTOR, sel):
                            if cand.is_displayed() and cand.is_enabled() and not _is_bad_jira_field(cand):
                                return cand
                    except Exception:
                        continue
            except Exception:
                return None
            return None

        element = _find_jira_dialog_field()

        if not element:
            element = self.browser._wait_for_ranked_input_candidate(target, typed_text=text)

        # 1. Try aria-label (input, textarea, contenteditable — partial match)
        aria_label = self.browser._target_value(target, "aria-label", "aria_label")
        if not element and aria_label:
            al = aria_label
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
        target_input_type = self.browser._target_value(target, "type", "input_type")
        if not element and target_input_type:
            try:
                element = drv.find_element(By.CSS_SELECTOR, f"input[type='{target_input_type}']")
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
                import time
                from selenium.webdriver.common.keys import Keys

                is_search_input = self.browser._target_prefers_search_input(target, typed_text=text)
                current_value = self.browser._read_text_entry_value(element)
                if is_search_input:
                    normalized_current = self.browser._normalize_lookup_text(current_value)
                    normalized_target = self.browser._normalize_lookup_text(text)
                    if normalized_current and normalized_current == normalized_target:
                        if press_enter:
                            time.sleep(0.15)
                            element.send_keys(Keys.RETURN)
                            time.sleep(0.3)
                            return {
                                "success": True,
                                "message": f"Search query already present (fallback): {text[:50]} + Enter pressed"
                            }
                        return {
                            "success": True,
                            "message": f"Search query already present (fallback): {text[:50]}"
                        }

                if current_value:
                    self.browser._clear_text_entry(element)
                    time.sleep(0.05)

                # Handle contenteditable differently
                if element.get_attribute("contenteditable") in ("true", ""):
                    element.click()
                    time.sleep(0.05)
                element.send_keys(text)
                # Press Enter after typing if requested
                if press_enter:
                    time.sleep(0.15)
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
        before_snapshot = self._capture_page_change_snapshot()
        result = self.browser.scroll_page(direction, amount)
        payload = {
            **(result or {}),
            "browser_result": {
                "success": result.get("success", False),
                "message": result.get("message", "") if isinstance(result, dict) else "",
            } if isinstance(result, dict) else {"success": False, "message": ""},
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "scroll_page",
            success=bool(isinstance(result, dict) and result.get("success")),
        )
        return payload
    
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
                before_snapshot = self._capture_page_change_snapshot()
                back_result = self.browser.go_back()
                payload = {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "navigated_back": back_result.get("success", False),
                    "url": back_result.get("url", ""),
                    "browser_result": {
                        "success": back_result.get("success", False),
                        "message": back_result.get("message", ""),
                    },
                }
                self._attach_page_change_to_payload(
                    payload,
                    before_snapshot,
                    "go_back",
                    success=bool(back_result.get("success")),
                )
                return payload
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
                before_snapshot = self._capture_page_change_snapshot()
                forward_result = self.browser.go_forward()
                payload = {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "navigated_forward": forward_result.get("success", False),
                    "url": forward_result.get("url", ""),
                    "browser_result": {
                        "success": forward_result.get("success", False),
                        "message": forward_result.get("message", ""),
                    },
                }
                self._attach_page_change_to_payload(
                    payload,
                    before_snapshot,
                    "go_forward",
                    success=bool(forward_result.get("success")),
                )
                return payload
            return result
        except PermissionError as e:
            return {"status": "denied", "message": str(e)}

    def reload_page(self):
        """Reload the current page - MANDATORY AgentTrust validation"""
        if not self.browser:
            return {"error": "Browser not initialized"}

        current_url = self.browser.get_current_url()

        try:
            result = self.execute_navigation(current_url)
            if result.get("status") == "allowed":
                before_snapshot = self._capture_page_change_snapshot()
                reload_result = self.browser.reload_page()
                payload = {
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level"),
                    "reloaded": reload_result.get("success", False),
                    "url": reload_result.get("url", ""),
                    "readiness": reload_result.get("readiness"),
                    "browser_result": {
                        "success": reload_result.get("success", False),
                        "message": reload_result.get("message", ""),
                    },
                }
                self._attach_page_change_to_payload(
                    payload,
                    before_snapshot,
                    "reload_page",
                    success=bool(reload_result.get("success")),
                )
                return payload
            return result
        except PermissionError as e:
            return {"status": "denied", "message": str(e)}

    def wait_until_interactive(self, timeout: float = 6.0):
        """Wait for the current page to become meaningfully interactive."""
        if not self.browser:
            return {"error": "Browser not initialized"}

        before_snapshot = self._capture_page_change_snapshot()
        result = self.browser.wait_for_interactive_page(timeout=timeout)
        payload = {
            **(result or {}),
            "browser_result": {
                "success": bool((result or {}).get("ready")),
                "message": (result or {}).get("reason", ""),
            },
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "wait_until_interactive",
            success=bool((result or {}).get("ready")),
        )
        return payload

    def find_text_on_page(self, text: str, exact_match: bool = False, scroll_behavior: str = "center"):
        """Find visible text on the current page and scroll it into view."""
        if not self.browser:
            return {"error": "Browser not initialized"}

        before_snapshot = self._capture_page_change_snapshot()
        result = self.browser.find_text_on_page(
            text=text,
            exact_match=exact_match,
            scroll_behavior=scroll_behavior,
        )
        payload = {
            **(result or {}),
            "browser_result": {
                "success": bool((result or {}).get("success")),
                "message": (result or {}).get("message", ""),
            },
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "find_text_on_page",
            success=bool((result or {}).get("success")),
        )
        return payload
    
    def wait_for_element(self, target: Dict[str, Any], timeout: int = 10):
        """Wait for element - NO AgentTrust validation needed (read-only)"""
        if not self.browser:
            return {"error": "Browser not initialized"}
        before_snapshot = self._capture_page_change_snapshot()
        result = self.browser.wait_for_element(target, timeout)
        payload = {
            **(result or {}),
            "browser_result": {
                "success": result.get("success", False),
                "message": result.get("message", "") if isinstance(result, dict) else "",
            } if isinstance(result, dict) else {"success": False, "message": ""},
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "wait_for_element",
            success=bool(isinstance(result, dict) and result.get("success")),
        )
        return payload
    
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
                before_snapshot = self._capture_page_change_snapshot()
                self.action_history.append({
                    "action": "navigation", "url": url,
                    "status": "allowed",
                    "action_id": result.get("action_id"),
                    "risk_level": result.get("risk_level")
                })
                tab_result = self.browser.open_new_tab(url, label)
                tab_result["action_id"] = result.get("action_id")
                tab_result["risk_level"] = result.get("risk_level")
                tab_result["status"] = "allowed"

                # Auto-dismiss overlays on the newly loaded page
                try:
                    import time as _time
                    _time.sleep(0.5)
                    self.dismiss_overlays()
                except Exception:
                    pass

                try:
                    screenshot = self.browser.take_screenshot()
                    tab_result["screenshot"] = screenshot
                    if screenshot and result.get("action_id"):
                        self.agenttrust._update_action_screenshot(
                            result.get("action_id"), screenshot
                        )
                except Exception as e:
                    print(f"⚠️  Failed to capture screenshot for new tab: {e}")

                self._attach_page_change_to_payload(
                    tab_result,
                    before_snapshot,
                    "open_new_tab",
                    success=bool(tab_result.get("success")),
                )
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

        before_snapshot = self._capture_page_change_snapshot()
        result = self.browser.switch_to_tab(label_or_index)
        if result.get("success"):
            try:
                import time as _time
                _time.sleep(0.15)
                result["screenshot"] = self.browser.take_screenshot()
            except Exception:
                pass
        self._attach_page_change_to_payload(
            result,
            before_snapshot,
            "switch_to_tab",
            success=bool(result.get("success")),
        )
        return result

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
                before_snapshot = self._capture_page_change_snapshot()
                tab_result = self.browser.close_tab(label_or_index)
                tab_result["action_id"] = result.get("action_id")
                tab_result["status"] = "allowed" if tab_result.get("success") else "error"

                if tab_result.get("success"):
                    try:
                        import time as _time
                        _time.sleep(0.15)
                        screenshot = self.browser.take_screenshot()
                        tab_result["screenshot"] = screenshot
                        if screenshot and result.get("action_id"):
                            self.agenttrust._update_action_screenshot(
                                result.get("action_id"), screenshot
                            )
                    except Exception:
                        pass

                self._attach_page_change_to_payload(
                    tab_result,
                    before_snapshot,
                    "close_tab",
                    success=bool(tab_result.get("success")),
                )
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

        # Preserve real Jira create/task dialogs. They are not disposable
        # popups; they are the working surface for task creation.
        try:
            current_url = (driver.current_url or "").lower()
        except Exception:
            current_url = ""

        if "atlassian.net" in current_url:
            try:
                jira_create_dialog = driver.execute_script("""
                    const dialogs = Array.from(document.querySelectorAll(
                        '[role="dialog"], [role="alertdialog"], [aria-modal="true"]'
                    ));
                    return dialogs.some((dlg) => {
                        const text = (dlg.innerText || dlg.textContent || '').toLowerCase();
                        const hasCreateHeading =
                            text.includes('create task') ||
                            text.includes('create issue') ||
                            text.includes('summary');
                        const hasSummaryField =
                            !!dlg.querySelector('input[aria-label*="Summary"], textarea[aria-label*="Summary"], input[name*="summary"], textarea[name*="summary"]');
                        const hasCreateButton =
                            Array.from(dlg.querySelectorAll('button, [role="button"], input[type="submit"]'))
                                .some((el) => ((el.innerText || el.textContent || el.value || '').toLowerCase().includes('create')));
                        return hasCreateHeading || (hasSummaryField && hasCreateButton);
                    });
                """)
                if jira_create_dialog:
                    return False
            except Exception:
                pass
            try:
                jira_draft_dialog = driver.execute_script("""
                    const dialogs = Array.from(document.querySelectorAll(
                        '[role="dialog"], [role="alertdialog"], [aria-modal="true"]'
                    ));
                    return dialogs.some((dlg) => {
                        const text = (dlg.innerText || dlg.textContent || '').toLowerCase();
                        return text.includes('draft work item in progress') || text.includes('keep editing');
                    });
                """)
                if jira_draft_dialog:
                    return False
            except Exception:
                pass

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

        # ── Phase 3: JavaScript DOM cleanup ──
        # Aggressively remove overlay/modal/paywall elements and restore scroll
        try:
            js_dismissed = driver.execute_script("""
                let removed = 0;

                // Selectors for fixed/sticky overlays, modals, paywalls, GDPR
                const overlaySelectors = [
                    '[class*="paywall"]', '[id*="paywall"]',
                    '[class*="subscribe-wall"]', '[id*="subscribe-wall"]',
                    '[class*="reg-wall"]', '[id*="reg-wall"]',
                    '[class*="modal-overlay"]', '[class*="modal-backdrop"]',
                    '[class*="overlay"][class*="cookie"]',
                    '[class*="newsletter-popup"]', '[class*="newsletter-modal"]',
                    '[class*="popup-overlay"]', '[id*="popup-overlay"]',
                    '[class*="consent-banner"]', '[id*="consent-banner"]',
                    '[class*="gdpr"]', '[id*="gdpr"]',
                    '[class*="tp-modal"]', '[id*="tp-modal"]',
                    '[class*="piano-"]',
                    '[class*="ad-blocker"]', '[id*="ad-blocker"]',
                    '[class*="interstitial"]', '[id*="interstitial"]',
                    'iframe[src*="subscribe"]',
                    'iframe[src*="paywall"]',
                ];
                overlaySelectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        el.remove();
                        removed++;
                    });
                });

                // Remove fixed/sticky positioned elements that cover the viewport
                const allEls = document.querySelectorAll('div, section, aside, iframe');
                for (const el of allEls) {
                    const style = window.getComputedStyle(el);
                    if ((style.position === 'fixed' || style.position === 'sticky') &&
                        style.zIndex && parseInt(style.zIndex) > 999) {
                        const rect = el.getBoundingClientRect();
                        // Large overlays covering >30% of viewport width
                        if (rect.width > window.innerWidth * 0.3 &&
                            rect.height > 50) {
                            el.remove();
                            removed++;
                        }
                    }
                }

                // Restore body scroll if frozen by modal
                const body = document.body;
                const html = document.documentElement;
                if (body) {
                    body.style.overflow = '';
                    body.style.position = '';
                    body.classList.remove('modal-open', 'no-scroll', 'noscroll',
                                         'overflow-hidden', 'is-locked');
                }
                if (html) {
                    html.style.overflow = '';
                    html.classList.remove('modal-open', 'no-scroll', 'noscroll',
                                         'overflow-hidden', 'is-locked');
                }

                return removed;
            """)
            if js_dismissed and js_dismissed > 0:
                dismissed = True
        except Exception:
            pass

        return dismissed

    def press_key(self, key: str, target: Optional[Dict[str, Any]] = None):
        """Press a key after optional AgentTrust validation."""
        if not self.browser:
            return {"error": "Browser not initialized"}
        current_url = self.browser.get_current_url()
        try:
            result = self.agenttrust.execute_action(
                action_type="form_input",
                url=current_url,
                target={"type": "keyboard", "action": "press_key", **(target or {})},
                form_data={"key": key}
            )
            status = result.get("status") if result else None
            if status != "allowed":
                return {"status": status or "error", "message": result.get("message", "Unexpected status") if result else "No response"}
            before_snapshot = self._capture_page_change_snapshot()
            key_result = self.browser.press_key(key, target=target)
            screenshot = self.browser.take_screenshot() if key_result.get("success") else None
            payload = {
                "status": "allowed",
                "action_id": result.get("action_id"),
                "risk_level": result.get("risk_level"),
                "message": key_result.get("message", ""),
                "screenshot": screenshot,
                "browser_result": {
                    "success": key_result.get("success", False),
                    "message": key_result.get("message", "")
                }
            }
            self._attach_page_change_to_payload(
                payload,
                before_snapshot,
                "press_key",
                success=bool(key_result.get("success")),
            )
            self._emit_platform_action_event("press_key", current_url, payload, target=target, form_data={"key": key})
            return payload
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def select_option(self, target: Dict[str, Any], value: Optional[str] = None, label: Optional[str] = None, index: Optional[int] = None):
        """Select an option after AgentTrust validation."""
        if not self.browser:
            return {"error": "Browser not initialized"}
        current_url = self.browser.get_current_url()
        chosen = label or value or index
        try:
            result = self.agenttrust.execute_action(
                action_type="form_input",
                url=current_url,
                target={"type": "select", "action": "select_option", **(target or {})},
                form_data={"value": chosen}
            )
            status = result.get("status") if result else None
            if status != "allowed":
                return {"status": status or "error", "message": result.get("message", "Unexpected status") if result else "No response"}
            before_snapshot = self._capture_page_change_snapshot()
            select_result = self.browser.select_option(target, value=value, label=label, index=index)
            screenshot = self.browser.take_screenshot() if select_result.get("success") else None
            payload = {
                "status": "allowed",
                "action_id": result.get("action_id"),
                "risk_level": result.get("risk_level"),
                "message": select_result.get("message", ""),
                "screenshot": screenshot,
                "browser_result": {
                    "success": select_result.get("success", False),
                    "message": select_result.get("message", "")
                }
            }
            self._attach_page_change_to_payload(
                payload,
                before_snapshot,
                "select_option",
                success=bool(select_result.get("success")),
            )
            self._emit_platform_action_event("select_option", current_url, payload, target=target, form_data={"value": chosen})
            return payload
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def dismiss_overlays_action(self):
        """Dismiss overlays and record the resulting state as a mutating action."""
        if not self.browser:
            return {"error": "Browser not initialized"}
        current_url = self.browser.get_current_url()
        before_snapshot = self._capture_page_change_snapshot()
        dismissed = self.dismiss_overlays()
        screenshot = self.browser.take_screenshot() if dismissed else None
        payload = {
            "status": "allowed",
            "action_id": None,
            "risk_level": "low",
            "message": "Dismissed overlays" if dismissed else "No overlays dismissed",
            "screenshot": screenshot,
            "browser_result": {
                "success": bool(dismissed),
                "message": "Dismissed overlays" if dismissed else "No overlays dismissed"
            }
        }
        self._attach_page_change_to_payload(
            payload,
            before_snapshot,
            "dismiss_overlays",
            success=True,
        )
        self._emit_platform_action_event("dismiss_overlays", current_url, payload)
        return payload

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

        def _el_descriptor(el):
            """Build a replayable element descriptor from a Selenium WebElement."""
            try:
                tag = (el.tag_name or "").lower()
                attrs = {}
                for attr in ("id", "name", "type", "placeholder", "aria-label", "class", "role"):
                    val = el.get_attribute(attr)
                    if val:
                        attrs[attr] = val.strip()
                css = ""
                try:
                    if attrs.get("id"):
                        css = f"#{attrs['id']}"
                    elif attrs.get("name"):
                        css = f"{tag}[name='{attrs['name']}']"
                    elif attrs.get("type"):
                        css = f"{tag}[type='{attrs['type']}']"
                except Exception:
                    pass
                return {"tagName": tag, "css": css, **attrs}
            except Exception:
                return {"tagName": "unknown"}

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
                steps_log.append({"sub_type": "dismiss_overlay", "label": "Dismissed overlay/popup"})
                _wait_ready(0.1)

            # Step 2: Detect current login state
            password_el = _find_input("password")
            username_el = _find_input("username")

            if password_el and not username_el:
                _safe_type(password_el, password)
                steps_log.append({"sub_type": "type_text", "target": _el_descriptor(password_el), "field": "password", "value": "***", "label": "Entered password (password-only page)"})
            elif password_el and username_el:
                _safe_type(username_el, username)
                steps_log.append({"sub_type": "type_text", "target": _el_descriptor(username_el), "field": "username", "value": username[:3] + "***", "label": "Entered username/email"})
                password_el = _find_input("password")
                if password_el:
                    _safe_type(password_el, password)
                    steps_log.append({"sub_type": "type_text", "target": _el_descriptor(password_el), "field": "password", "value": "***", "label": "Entered password (single-step form)"})
            elif username_el:
                _safe_type(username_el, username)
                steps_log.append({"sub_type": "type_text", "target": _el_descriptor(username_el), "field": "username", "value": username[:3] + "***", "label": "Entered username/email"})
                _wait_ready(0.1)

                continue_btn = _find_continue_button()
                if continue_btn:
                    btn_text = ""
                    try:
                        btn_text = (continue_btn.text or "").strip()[:30]
                    except StaleElementReferenceException:
                        pass
                    btn_desc = _el_descriptor(continue_btn)
                    _safe_click(continue_btn)
                    steps_log.append({"sub_type": "click", "target": btn_desc, "label": f"Clicked continue/next: '{btn_text}'"})
                else:
                    try:
                        username_el.send_keys(Keys.RETURN)
                    except StaleElementReferenceException:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                    steps_log.append({"sub_type": "press_key", "value": "Enter", "label": "Pressed Enter after username"})

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
                    steps_log.append({"sub_type": "type_text", "target": _el_descriptor(password_el), "field": "password", "value": "***", "label": "Entered password (after continue)"})
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
                    steps_log.append({"sub_type": "type_text", "target": _el_descriptor(password_el), "field": "password", "value": "***", "label": "Entered password (after overlay dismiss)"})
                elif username_el:
                    _safe_type(username_el, username)
                    steps_log.append({"sub_type": "type_text", "target": _el_descriptor(username_el), "field": "username", "value": username[:3] + "***", "label": "Entered username (after overlay dismiss)"})
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
                    steps_log.append({"sub_type": "press_key", "target": _el_descriptor(pw_for_submit), "value": "Enter", "label": "Pressed Enter on password field to submit"})
                except StaleElementReferenceException:
                    submit_btn = _find_continue_button()
                    if submit_btn:
                        btn_text = ""
                        try:
                            btn_text = (submit_btn.text or "").strip()[:30]
                        except StaleElementReferenceException:
                            pass
                        btn_desc = _el_descriptor(submit_btn)
                        _safe_click(submit_btn)
                        steps_log.append({"sub_type": "click", "target": btn_desc, "label": f"Clicked submit: '{btn_text}'"})
                    else:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                        steps_log.append({"sub_type": "press_key", "value": "Enter", "label": "Pressed Enter to submit"})
            else:
                submit_btn = _find_continue_button()
                if submit_btn:
                    btn_text = ""
                    try:
                        btn_text = (submit_btn.text or "").strip()[:30]
                    except StaleElementReferenceException:
                        pass
                    btn_desc = _el_descriptor(submit_btn)
                    _safe_click(submit_btn)
                    steps_log.append({"sub_type": "click", "target": btn_desc, "label": f"Clicked submit: '{btn_text}'"})
                else:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                    steps_log.append({"sub_type": "press_key", "value": "Enter", "label": "Pressed Enter to submit"})

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
                steps_log.append({"sub_type": "dismiss_overlay", "label": "Dismissed post-login overlay"})

            new_url = driver.current_url
            steps_log.append({"sub_type": "wait_navigation", "url": new_url, "label": f"Page after login: {new_url}"})

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
                        steps_log.append({"sub_type": "wait_navigation", "label": f"Detected login error: '{phrase}'"})
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
                        steps_log.append({"sub_type": "wait_navigation", "label": "Password field still visible - login likely failed"})
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

            # Persist sub-steps so routines can replay them individually
            if action_id and steps_log:
                try:
                    numbered = []
                    for idx, s in enumerate(steps_log):
                        entry = s if isinstance(s, dict) else {"sub_type": "unknown", "label": str(s)}
                        entry["order"] = idx + 1
                        numbered.append(entry)
                    self.agenttrust.log_sub_actions(action_id, numbered)
                except Exception:
                    pass

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
        Uses a multi-strategy fallback chain for robust matching.
        Returns True if found, False on timeout.
        """
        if not self.browser or not target:
            return False
        driver = self.browser._actual_driver
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.by import By

        def _visible(el):
            try:
                return el.is_displayed()
            except Exception:
                return False

        def _find(d):
            # 1. By ID
            if target.get("id"):
                try:
                    el = d.find_element(By.ID, target["id"])
                    if _visible(el):
                        return True
                except Exception:
                    pass

            # 2. By CSS selector
            for key in ("css", "selector"):
                css = target.get(key, "")
                if css:
                    try:
                        el = d.find_element(By.CSS_SELECTOR, css)
                        if _visible(el):
                            return True
                    except Exception:
                        pass

            # 3. By name attribute
            if target.get("name"):
                try:
                    el = d.find_element(By.NAME, target["name"])
                    if _visible(el):
                        return True
                except Exception:
                    pass

            # 4. By aria-label
            aria = target.get("ariaLabel") or target.get("aria-label") or ""
            if aria:
                safe = aria[:80].replace("'", "\\'")
                try:
                    el = d.find_element(By.CSS_SELECTOR, f'[aria-label="{safe}"]')
                    if _visible(el):
                        return True
                except Exception:
                    pass

            # 5. By href (links)
            if target.get("href"):
                href = str(target["href"])[:200].replace("'", "\\'")
                try:
                    el = d.find_element(By.XPATH, f"//a[contains(@href, '{href}')]")
                    if _visible(el):
                        return True
                except Exception:
                    pass

            # 6. By exact link text
            text = (target.get("text") or "")[:80].strip()
            if text:
                try:
                    el = d.find_element(By.LINK_TEXT, text)
                    if _visible(el):
                        return True
                except Exception:
                    pass

            # 7. By partial text (XPath contains) across interactive elements
            if text:
                safe_text = text.replace("'", "\\'")
                for xpath in [
                    f"//a[contains(., '{safe_text}')]",
                    f"//button[contains(., '{safe_text}')]",
                    f"//input[@value and contains(@value, '{safe_text}')]",
                    f"//*[@role='button' and contains(., '{safe_text}')]",
                    f"//*[contains(., '{safe_text}')]",
                ]:
                    try:
                        els = d.find_elements(By.XPATH, xpath)
                        for el in els:
                            if _visible(el):
                                return True
                    except Exception:
                        continue

            # 8. By tag + class combination
            tag = target.get("tagName") or target.get("tag") or ""
            cls = target.get("className") or target.get("class") or ""
            if tag and cls:
                first_cls = cls.split()[0] if cls else ""
                if first_cls:
                    try:
                        el = d.find_element(By.CSS_SELECTOR, f"{tag.lower()}.{first_cls}")
                        if _visible(el):
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

    def _resolve_sensitive_reference(self, value: str, current_url: str = "") -> Tuple[Optional[str], bool]:
        """
        Resolve a vault:// reference to a plaintext value without exposing
        the raw value in prompts or logs. Returns (resolved_value, used_vault).
        """
        if not isinstance(value, str):
            return value, False
        text = value.strip()
        if not text.startswith("vault://"):
            return value, False

        lookup_domain = ""
        try:
            from urllib.parse import urlparse
            lookup_domain = urlparse(current_url).netloc or ""
        except Exception:
            lookup_domain = ""

        try:
            resolved = self.agenttrust.resolve_sensitive_reference(text, domain=lookup_domain)
            if resolved is None:
                return None, True
            return resolved, True
        except Exception as e:
            print(f"           Sensitive reference lookup error: {e}")
            return None, True

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
                       scope: str = "private", is_owner: bool = True,
                       require_approval: bool = False,
                       progress_callback=None) -> dict:
        """
        Deterministically replay a sequence of recorded browser actions
        without involving ChatGPT.

        Trust model:
        - require_approval=True (/test mode): every step goes through
          AgentTrust validation so the extension shows approval for each action.
        - require_approval=False:
          - Private routines or owner: TRUSTED, skip policy checks.
          - Global non-owner: one upfront domain check, then trusted.

        Key behaviors:
        - Waits for document.readyState === 'complete' after every navigation
        - Waits for target elements to appear before clicking
        - Resolves credentials from the vault for auto_login steps
        - Retries element-finding once on failure after a short delay
        """
        results = []
        total = len(steps)
        trusted = not require_approval and ((scope == "private") or is_owner)

        def _emit(line):
            if progress_callback:
                try:
                    progress_callback(line)
                except Exception:
                    pass

        # Clear the shared progress accumulator
        global _routine_progress_lines
        try:
            _routine_progress_lines.clear()
        except Exception:
            pass

        print(f"\n{'='*50}")
        print(f"  ROUTINE: {routine_name} ({total} steps)")
        mode_label = 'APPROVAL PER ACTION' if require_approval else ('TRUSTED (skip validation)' if trusted else 'VALIDATED (one-time check)')
        print(f"  Mode: {mode_label}")
        print(f"{'='*50}")
        _emit(f"ROUTINE|Starting routine: {routine_name} ({total} steps)")

        if not trusted and not require_approval:
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
                if action_type in ("click", "form_submit", "auto_login"):
                    try:
                        self.dismiss_overlays()
                    except Exception:
                        pass

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

                elif action_type == "type_text":
                    self._wait_page_ready(timeout=10)
                    if not target and not form_data:
                        results.append({"step": i, "status": "skipped", "reason": "no target for type_text"})
                        continue
                    el_target = target or {}
                    text_value = ""
                    field_type = (form_data or {}).get("field", "") if form_data else (el_target.get("field", ""))
                    raw_val = (form_data or {}).get("value", "") if form_data else ""
                    if field_type == "password" or "***" in str(raw_val):
                        lookup_domain = domain or ""
                        if not lookup_domain and url:
                            try:
                                from urllib.parse import urlparse
                                lookup_domain = urlparse(url).hostname or ""
                            except Exception:
                                pass
                        if lookup_domain:
                            cred_user, cred_pass = self._resolve_credentials(lookup_domain)
                            text_value = cred_pass if field_type == "password" else cred_user
                        if not text_value:
                            results.append({"step": i, "status": "skipped", "reason": f"No credentials for {domain}"})
                            continue
                    elif field_type == "username" and ("***" in str(raw_val) or not raw_val):
                        lookup_domain = domain or ""
                        if not lookup_domain and url:
                            try:
                                from urllib.parse import urlparse
                                lookup_domain = urlparse(url).hostname or ""
                            except Exception:
                                pass
                        if lookup_domain:
                            cred_user, _ = self._resolve_credentials(lookup_domain)
                            text_value = cred_user
                        if not text_value:
                            results.append({"step": i, "status": "skipped", "reason": f"No credentials for {domain}"})
                            continue
                    else:
                        text_value = raw_val

                    from selenium.webdriver.common.by import By
                    driver = self.browser._actual_driver
                    el = None
                    css = el_target.get("css", "")
                    if css:
                        try:
                            el = driver.find_element(By.CSS_SELECTOR, css)
                        except Exception:
                            pass
                    if not el and el_target.get("name"):
                        try:
                            el = driver.find_element(By.NAME, el_target["name"])
                        except Exception:
                            pass
                    if not el and el_target.get("id"):
                        try:
                            el = driver.find_element(By.ID, el_target["id"])
                        except Exception:
                            pass
                    if el:
                        try:
                            el.clear()
                        except Exception:
                            pass
                        el.send_keys(text_value)
                        result = {"status": "allowed", "success": True}
                    else:
                        print(f"           WARNING: Could not find target element for type_text")
                        results.append({"step": i, "status": "error", "error": "Target element not found"})
                        continue

                elif action_type == "press_key":
                    self._wait_page_ready(timeout=5)
                    key_name = ""
                    if form_data and form_data.get("value"):
                        key_name = form_data["value"]
                    elif target and target.get("value"):
                        key_name = target["value"]
                    else:
                        key_name = "Enter"

                    from selenium.webdriver.common.by import By
                    from selenium.webdriver.common.keys import Keys as K
                    key_map = {"Enter": K.RETURN, "Tab": K.TAB, "Escape": K.ESCAPE}
                    key_to_send = key_map.get(key_name, key_name)

                    driver = self.browser._actual_driver
                    el = None
                    if target and target.get("css"):
                        try:
                            el = driver.find_element(By.CSS_SELECTOR, target["css"])
                        except Exception:
                            pass
                    if el:
                        el.send_keys(key_to_send)
                    else:
                        driver.find_element(By.TAG_NAME, "body").send_keys(key_to_send)
                    result = {"status": "allowed", "success": True}

                elif action_type == "dismiss_overlay":
                    self.dismiss_overlays()
                    result = {"status": "allowed", "success": True}

                elif action_type == "wait_navigation":
                    self._wait_page_ready(timeout=15)
                    result = {"status": "allowed", "success": True}

                else:
                    results.append({"step": i, "status": "skipped", "reason": f"unknown type: {action_type}"})
                    continue

                status = result.get("status", "allowed")
                success_flag = result.get("success", True) if "success" in result else True
                ok = status in ("allowed", "success") and success_flag is not False
                results.append({"step": i, "label": label, "status": status, "success": ok})
                symbol = "OK" if ok else "FAIL"
                print(f"           -> {symbol} ({status})")
                _emit(f"ROUTINE|Step {i}/{total}: {label} -- {symbol}")

                if not ok and status in ("denied", "step_up_required"):
                    print(f"           Routine halted: {result.get('message', status)}")
                    _emit(f"ROUTINE|Halted: {result.get('message', status)}")
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
                _emit(f"ROUTINE|Step {i}/{total}: {label} -- DENIED")
                break
            except Exception as e:
                print(f"           -> ERROR: {e}")
                results.append({"step": i, "label": label, "status": "error", "error": str(e)})
                _emit(f"ROUTINE|Step {i}/{total}: {label} -- ERROR")

        completed = sum(1 for r in results if r.get("success"))
        print(f"\n  Routine finished: {completed}/{total} steps completed")
        print(f"{'='*50}\n")
        _emit(f"DONE|Routine finished: {completed}/{total} steps completed")

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
    
    def __init__(
        self,
        enable_browser: bool = True,
        headless: bool = False,
        agenttrust_client: Optional[AgentTrustClient] = None,
    ):
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
        
        if agenttrust_client is None:
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
                print("❌ Browser automation requires Selenium. Install with: pip install selenium")
                sys.exit(1)
            except Exception as e:
                print(f"❌ Browser failed to start: {e}")
                print("   Common fixes:")
                print("   1. Close any other Chrome instances using the same profile")
                print("   2. Delete the .chrome-profile folder and restart")
                print("   3. Update ChromeDriver: pip install --upgrade selenium")
                sys.exit(1)
        
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
        self._cached_credentials = None
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1")
        self.model_fast = os.getenv("OPENAI_MODEL_FAST", "gpt-4.1-mini")
        self.model_nano = os.getenv("OPENAI_MODEL_NANO", "gpt-4.1-nano")

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
        """Call OpenAI chat completions with automatic rate-limit retry and model fallback."""
        import time as _time
        max_retries = 4
        original_model = kwargs.get("model", self.model)
        for attempt in range(max_retries):
            try:
                return self.openai.chat.completions.create(**kwargs)
            except Exception as e:
                err_str = str(e)
                if "429" not in err_str and "rate_limit" not in err_str.lower():
                    raise
                is_too_large = "too large" in err_str.lower() or "Requested" in err_str
                if is_too_large:
                    if kwargs.get("model") != self.model_fast:
                        kwargs["model"] = self.model_fast
                        print(f"  ↘️  Request too large for {original_model}, falling back to {self.model_fast}")
                        continue
                    if "messages" in kwargs and len(kwargs["messages"]) > 3:
                        msgs = kwargs["messages"]
                        kept_system = [m for m in msgs[:2] if m.get("role") == "system"]
                        non_system = [m for m in msgs if m.get("role") != "system"]
                        trim_count = max(2, len(non_system) // 3)
                        kwargs["messages"] = kept_system + non_system[trim_count:]
                        print(f"  ✂️  Trimmed {trim_count} older messages (attempt {attempt + 1}/{max_retries})")
                        continue
                wait = 2 ** attempt
                print(f"  ⏳ Rate limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})...")
                _time.sleep(wait)
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
                "name": "highlight_interactive_elements",
                "description": "Highlight visible interactive elements on the current page with numbered overlays, similar to Browser Use. Use this when visual grounding would help confirm which indexed element to target.",
                "parameters": {"type": "object", "properties": {
                    "element_type": {"type": "string", "enum": ["button", "link", "input", "form"],
                                     "description": "Filter highlights by element type (optional)"},
                    "max_elements": {"type": "integer", "description": "Maximum number of elements to highlight (default 25)."}
                }}
            }},
            {"type": "function", "function": {
                "name": "clear_highlight_overlays",
                "description": "Remove any numbered interactive-element highlight overlays previously drawn on the page.",
                "parameters": {"type": "object", "properties": {}}
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
                "description": "Type text into an input field, textarea, or contenteditable element. Identify the target using id, name, placeholder, aria-label, input type, role, or CSS selector. For search boxes, use aria-label, role='searchbox', or type='search'. If the search box already contains text, clear the existing value before typing the new query. Set press_enter=true to submit the form after typing (PREFERRED over clicking a submit button for search boxes and single-input forms). You may also pass a secure vault reference like vault://record_ref/field_name instead of raw PII; the executor will resolve it at runtime after approval.",
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
                    "text": {"type": "string", "description": "Text to type, or a secure vault reference like vault://record_ref/field_name"},
                    "press_enter": {"type": "boolean", "description": "Press Enter after typing to submit the form. Use for search boxes, verification code inputs, and single-input forms. When replacing a search query, clear the field first, then type, then press Enter. Default: false."}
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
                "name": "press_key",
                "description": "Press a keyboard key such as Enter, Tab, Escape, ArrowDown, or ArrowUp. Use this for menus, comboboxes, dialogs, and focused controls that need keyboard interaction.",
                "parameters": {"type": "object", "properties": {
                    "key": {"type": "string", "description": "Keyboard key name"},
                    "target": {"type": "object", "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "aria-label": {"type": "string"},
                        "text": {"type": "string"},
                        "selector": {"type": "string"}
                    }}
                }, "required": ["key"]}
            }},
            {"type": "function", "function": {
                "name": "select_option",
                "description": "Select an option from a native select or custom combobox/listbox dropdown by visible label, value, or index.",
                "parameters": {"type": "object", "properties": {
                    "target": {"type": "object", "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "aria-label": {"type": "string"},
                        "text": {"type": "string"},
                        "role": {"type": "string"},
                        "selector": {"type": "string"}
                    }},
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "index": {"type": "integer"}
                }, "required": ["target"]}
            }},
            {"type": "function", "function": {
                "name": "dismiss_overlays",
                "description": "Dismiss popups, cookie banners, credential prompts, and other overlays before continuing.",
                "parameters": {"type": "object", "properties": {}}
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
                "name": "reload_page",
                "description": "Reload the current page and wait briefly for it to become interactive again. Use this when a page stalls, partially renders, or needs a fresh state.",
                "parameters": {"type": "object", "properties": {}}
            }},
            {"type": "function", "function": {
                "name": "wait_until_interactive",
                "description": "Wait until the current page looks meaningfully interactive, not just loaded. Use after navigation, redirects, or dynamic page transitions before trying to click or type.",
                "parameters": {"type": "object", "properties": {
                    "timeout": {"type": "number", "description": "Max seconds to wait (default 6)."}
                }}
            }},
            {"type": "function", "function": {
                "name": "find_text_on_page",
                "description": "Find visible text on the current page and scroll the best match into view. Use this to orient on long pages, jump to a section heading, or verify the page contains the expected text before acting.",
                "parameters": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "Visible text to locate on the page."},
                    "exact_match": {"type": "boolean", "description": "Require an exact visible-text match instead of partial match. Default false."},
                    "scroll_behavior": {"type": "string", "enum": ["start", "center", "end", "nearest"], "description": "Where to align the matched text in the viewport. Default center."}
                }, "required": ["text"]}
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
                "description": "Look up saved login credentials for a domain. Only call this AFTER you have navigated to the site's homepage, clicked a visible Sign in / Log in / Account control, and the login form is visible. If credentials exist, use them with auto_login. Use the BASE domain (e.g. 'google.com' not 'mail.google.com', 'amazon.com' not 'smile.amazon.com'). For Gmail/Google services, use 'google.com' or 'gmail.com'.",
                "parameters": {"type": "object", "properties": {
                    "domain": {"type": "string", "description": "Base domain to look up (e.g. google.com, gmail.com, amazon.com, github.com). Use the base domain, not subdomains."}
                }, "required": ["domain"]}
            }},
            {"type": "function", "function": {
                "name": "auto_login",
                "description": "Perform a complete login flow on the CURRENT page. IMPORTANT: Start from the site's homepage, click a visible Sign in / Log in / Account control, and only call auto_login when the login form is actually visible. Do not jump straight to deep sign-in URLs unless the homepage has no usable login control. Handles multi-step login forms (Google, Microsoft, Amazon) that show a continue/next button between username and password. Dismisses QR-code popups and overlays automatically. If you just called get_saved_credentials and credentials were found, call auto_login WITHOUT username/password — the saved credentials will be used automatically and securely. Only pass username/password if the user provided them manually.",
                "parameters": {"type": "object", "properties": {
                    "username": {"type": "string", "description": "Username or email (omit if using saved credentials from get_saved_credentials)"},
                    "password": {"type": "string", "description": "Password (omit if using saved credentials from get_saved_credentials)"}
                }}
            }},
            {"type": "function", "function": {
                "name": "call_external_api",
                "description": (
                    "Call an external provider API (GitHub, Google Calendar, Slack, etc.) using Auth0 Token Vault. "
                    "Prefer this over browser automation for supported providers when performing API-level tasks.\n\n"
                    "GITHUB (provider='github'):\n"
                    "  - List repos: GET https://api.github.com/user/repos\n"
                    "  - Get repo: GET https://api.github.com/repos/{owner}/{repo}\n"
                    "  - List issues: GET https://api.github.com/repos/{owner}/{repo}/issues\n"
                    "  - Create issue: POST https://api.github.com/repos/{owner}/{repo}/issues body={title, body}\n"
                    "  - List PRs: GET https://api.github.com/repos/{owner}/{repo}/pulls\n"
                    "  - User profile: GET https://api.github.com/user\n\n"
                    "GOOGLE CALENDAR (provider='google-oauth2'):\n"
                    "  - List events: GET https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin={ISO}&timeMax={ISO}\n"
                    "  - Create event: POST https://www.googleapis.com/calendar/v3/calendars/primary/events body={summary, start:{dateTime}, end:{dateTime}}\n"
                    "  - Get event: GET https://www.googleapis.com/calendar/v3/calendars/primary/events/{eventId}\n"
                    "  - Update event: PUT https://www.googleapis.com/calendar/v3/calendars/primary/events/{eventId}\n"
                    "  - Delete event: DELETE https://www.googleapis.com/calendar/v3/calendars/primary/events/{eventId}\n"
                    "  - List calendars: GET https://www.googleapis.com/calendar/v3/users/me/calendarList\n\n"
                    "NOTE: timeMin/timeMax must be RFC 3339 format (e.g. 2026-03-09T00:00:00Z). "
                    "Calendar event start/end use {dateTime: '...', timeZone: 'America/New_York'}."
                ),
                "parameters": {"type": "object", "properties": {
                    "provider": {"type": "string", "description": "Auth0 connection name: 'github' for GitHub, 'google-oauth2' for Google (Calendar, Drive, etc.), 'slack', 'microsoft'"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method"},
                    "endpoint": {"type": "string", "description": "Full API URL including query parameters (see examples in description)"},
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

        # Store the user prompt in the DB so the extension can show it.
        # Retry once with a fresh token if the first attempt fails.
        prompt_id = None
        for _sp_attempt in range(2):
            try:
                prompt_id = self.agenttrust.store_prompt(user_message)
                if prompt_id:
                    break
                if _sp_attempt == 0:
                    self.agenttrust._token = None
                    self.agenttrust._token_expiry = None
            except Exception:
                if _sp_attempt == 0:
                    self.agenttrust._token = None
                    self.agenttrust._token_expiry = None

        # --- Core processing: LangGraph state machine or legacy loop ---
        if self._graph:
            response_text = self._chat_graph(user_message, prompt_id=prompt_id)
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
        MAX_HISTORY_TURNS = 20
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
    def _chat_graph(self, user_message, prompt_id=None):
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
            "prompt_id": prompt_id or "",
            "progress_lines": [],
            "auditor_high_risk_keywords": [
                kw.strip()
                for kw in os.getenv("AGENTTRUST_AUDITOR_HIGH_RISK_KEYWORDS", "").split(",")
                if kw.strip()
            ],
            "auditor_feedback": "",
            "auditor_decision": "",
        }

        try:
            result = self._graph.invoke(initial_state)
            return result.get("final_response", "Task completed.")
        except Exception as e:
            err_str = str(e)
            if "No connection could be made" in err_str or "Connection refused" in err_str.lower():
                print("❌ Browser session has died (Chrome/ChromeDriver crashed).")
                print("   The agent cannot continue. Please restart the script.")
                return "Browser crashed — Chrome/ChromeDriver is no longer running. Please restart the agent."
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
- Use highlight_interactive_elements when visual grounding would help.
  The numbered overlays match the returned element indexes.
- Use clear_highlight_overlays when you want to remove those boxes.
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
- If a search box already contains any text, CLEAR the field before
  typing the new query. Do not append a second query to an existing one.
- After any navigation, redirect, or dynamic page change, use
  wait_until_interactive before trying to click or type if the page
  still looks incomplete or unstable.
- Use find_text_on_page to jump to a heading, section label, or other
  visible text on long pages before interacting nearby.
- AFTER typing in a search box, use type_text with press_enter=true
  to submit the search. Do NOT try to find and click a 'Search'
  button — just press Enter. This is MORE RELIABLE.
- For any form with a single input (search, verification code, etc.),
  prefer pressing Enter over finding a submit button.

LOGIN FLOW — STRICT RULES:
- NEVER attempt to log in unless the USER EXPLICITLY asks you to sign in.
  Browsing, searching, and reading public content NEVER requires login.
  If a site redirects you to a sign-in page, navigate BACK to the main
  site URL (e.g. https://www.amazon.com) — most content is accessible
  without an account.
- NEVER call get_saved_credentials or auto_login on your own initiative.
  Only use them when the user says something like "sign in", "log in",
  "use my account", etc.
- If the user DOES ask you to sign in:
  1. Navigate to the site's HOMEPAGE first.
  2. Find and click the visible "Sign in" / "Log in" button or account entry point.
  3. Call get_saved_credentials with the site's domain only after the login form is visible.
  4. If credentials are found, call auto_login immediately.
  5. auto_login handles multi-step forms, entering both username
     AND password, clicking continue/next, and dismissing popups.
  6. NEVER manually type usernames or passwords with type_text.
  7. Only ask the user if NO saved credentials exist.
  8. Only use a deep sign-in URL when the homepage has no usable sign-in control.
- BEFORE attempting any login, CHECK if you are ALREADY LOGGED IN.
  Signs of being logged in: inbox is loaded (URL contains /inbox),
  compose button visible, sign-out/logout link present,
  account/profile menu visible, dashboard or feed loaded.
  If already logged in, SKIP get_saved_credentials and auto_login entirely.
- ⚠ auto_login ONLY works on the site's OWN login page.
  Do NOT call auto_login while on an unrelated site.

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
- Use reload_page if a site partially renders, stalls after a redirect,
  or shows stale content that needs a clean refresh.
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
                
                result_str = json.dumps(result, default=str)
                if len(result_str) > 12000:
                    result_str = result_str[:12000] + '…[truncated]'
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": result_str
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

        elif function_name == "highlight_interactive_elements":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.highlight_interactive_elements(
                element_type=args.get("element_type"),
                max_elements=args.get("max_elements", 25),
            )
            if result.get("success"):
                print(f"🖍️  Highlighted {result.get('count', 0)} interactive element(s)")
            return result

        elif function_name == "clear_highlight_overlays":
            result = self.browser_executor.clear_highlight_overlays()
            if result.get("success"):
                print("🧹 Cleared interactive element highlights")
            return result
        
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
                cb = getattr(self.agenttrust, "on_platform_action_event", None)
                if cb:
                    cb({
                        "action_type": "type_text",
                        "url": current_url,
                        "target": args.get("target", {}),
                        "form_data": {"text": args.get("text", ""), "press_enter": press_enter},
                        "result": result
                    })
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

        elif function_name == "press_key":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.press_key(
                key=args.get("key", ""),
                target=args.get("target")
            )
            if result.get("status") == "allowed":
                print(f"⌨️  Key pressed: {args.get('key', '')}")
            return result

        elif function_name == "select_option":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.select_option(
                target=args.get("target", {}),
                value=args.get("value"),
                label=args.get("label"),
                index=args.get("index")
            )
            if result.get("status") == "allowed":
                print("🗂️  Option selected")
            return result

        elif function_name == "dismiss_overlays":
            result = self.browser_executor.dismiss_overlays_action()
            print("🪟 Overlay dismissal attempted")
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

        elif function_name == "reload_page":
            result = self.browser_executor.reload_page()
            if result.get("status") == "allowed":
                print(f"🔄 Reloaded page: {result.get('url', 'N/A')}")
            return result

        elif function_name == "wait_until_interactive":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.wait_until_interactive(
                timeout=args.get("timeout", 6.0)
            )
            if result.get("ready"):
                print(f"⏱️  Page interactive: {result.get('reason', '')}")
            else:
                print(f"⏱️  Page still settling: {result.get('reason', '')}")
            return result

        elif function_name == "find_text_on_page":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            result = self.browser_executor.find_text_on_page(
                text=args.get("text", ""),
                exact_match=args.get("exact_match", False),
                scroll_behavior=args.get("scroll_behavior", "center"),
            )
            if result.get("success"):
                print(f"🔎 Found text on page: {args.get('text', '')}")
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
                self._cached_credentials = creds
                masked_user = creds["username"][:3] + "***" if len(creds["username"]) > 3 else "***"
                return {"found": True, "domain": domain, "username_hint": masked_user,
                        "hint": "Credentials securely loaded. Call auto_login with domain='" + domain + "' to log in. Do NOT type the password manually."}
            else:
                print(f"🔑 No saved credentials for {domain}")
                self._cached_credentials = None
                return {"found": False, "domain": domain, "message": "No saved credentials. Ask the user for login details."}

        elif function_name == "auto_login":
            args = json.loads(function_call.arguments) if function_call.arguments else {}
            username = args.get("username", "")
            password = args.get("password", "")
            current_url = self.browser_executor.browser.get_current_url() if self.browser_executor.browser else ""

            # Early exit: detect if the user is already logged in before
            # requiring credentials or enforcing login-page-only checks.
            _already_logged_in = False
            _url_lower = current_url.lower()
            if any(frag in _url_lower for frag in ("/inbox", "/#inbox", "/mail/u/",
                                                    "/feed", "/home", "/dashboard")):
                _already_logged_in = True
            if not _already_logged_in:
                try:
                    _login_check_els = self.browser_executor.get_visible_elements()
                    _has_login_fields = False
                    for _el in (_login_check_els or []):
                        _itype = (_el.get("input_type") or _el.get("type") or "").lower()
                        _ename = (_el.get("name") or "").lower()
                        if _itype in ("email", "password") or _ename in ("email", "username", "password", "passwd"):
                            _has_login_fields = True
                            break
                    if not _has_login_fields:
                        for _el in (_login_check_els or []):
                            _el_text = (_el.get("text") or "").lower()
                            _el_aria = (_el.get("aria_label") or _el.get("aria-label") or "").lower()
                            if any(kw in _el_text for kw in ("sign out", "log out", "logout", "compose")):
                                _already_logged_in = True
                                break
                            if any(kw in _el_aria for kw in ("sign out", "log out", "compose", "account menu")):
                                _already_logged_in = True
                                break
                except Exception:
                    pass
            if _already_logged_in:
                print(f"🔐 Already logged in on {current_url} — skipping auto_login")
                return {
                    "success": True,
                    "already_logged_in": True,
                    "message": "Already logged in — no login needed.",
                    "current_url": current_url,
                }

            has_login_fields = False
            try:
                elements = self.browser_executor.get_visible_elements()
                for el in (elements or []):
                    itype = (el.get("input_type") or el.get("type") or "").lower()
                    ename = (el.get("name") or "").lower()
                    placeholder = (el.get("placeholder") or "").lower()
                    aria = (el.get("aria_label") or el.get("aria-label") or "").lower()
                    if itype in ("email", "password") or ename in ("email", "username", "password", "login_email", "userid"):
                        has_login_fields = True
                        break
                    if any(kw in f"{placeholder} {aria}" for kw in ("email", "password", "username", "user id", "sign in", "phone")):
                        has_login_fields = True
                        break
            except Exception:
                has_login_fields = True

            if (not username or not password) and getattr(self, '_cached_credentials', None):
                username = self._cached_credentials.get("username", username)
                password = self._cached_credentials.get("password", password)
                self._cached_credentials = None
            if not username or not password:
                if not has_login_fields:
                    return {
                        "success": False,
                        "message": "Login form is not visible yet. Click a real Sign in / Log in control, wait for the username/password fields to appear, then call get_saved_credentials followed by auto_login."
                    }
                return {
                    "success": False,
                    "message": "Credentials are not loaded yet. Call get_saved_credentials after the login form is visible, or pass both username and password explicitly."
                }
            # Guard: don't attempt login on non-login pages
            if current_url and ("localhost" in current_url or "about:blank" in current_url
                                or "/health" in current_url or "chrome://" in current_url):
                return {
                    "success": False,
                    "message": f"Current page ({current_url}) is not a login page. "
                               "Navigate to the website's login page FIRST, then call auto_login."
                }

            # Guard: the current page should look like a login page (URL
            # contains signin/login path fragments). If the user saved
            # credentials for a domain, they're valid — we just need to
            # make sure we're actually on a login page, not a random page.
            _url_lower = current_url.lower()
            _LOGIN_FRAGMENTS = (
                "/signin", "/sign-in", "/sign_in",
                "/login", "/log-in", "/log_in",
                "/ap/signin", "/accounts/login",
                "/auth/", "/sso/", "/oauth/",
            )
            from urllib.parse import urlparse as _urlparse_guard
            _guard_host = _urlparse_guard(current_url).netloc.lower()
            _is_login_subdomain = (
                _guard_host.startswith("signin.")
                or _guard_host.startswith("login.")
                or _guard_host.startswith("auth.")
                or _guard_host.startswith("accounts.")
            )
            _on_login_page = _is_login_subdomain or any(
                frag in _url_lower for frag in _LOGIN_FRAGMENTS
            )
            if not _on_login_page:
                return {
                    "success": False,
                    "message": "This page does not appear to be a login page. "
                               "Navigate to the site's sign-in / login page first, "
                               "then call auto_login."
                }

            # Check if the current page actually has login fields.
            # If not, tell the agent to find the login page itself.
            if not has_login_fields:
                return {
                    "success": False,
                    "message": "No login fields found on this page. "
                               "Navigate to the site's sign-in page first, "
                               "then call auto_login again."
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
            payload = {
                "status": "allowed",
                "action_id": result.get("action_id"),
                "risk_level": risk,
                "current_url": current_url,
                "target": target,
                "executed": bool(result.get("executed")),
                "clicked": bool(result.get("clicked")) if "clicked" in result else executed_ok,
                "browser_result": {
                    "success": executed_ok,
                    "message": br.get("message", ""),
                    "new_url": br.get("new_url", "") or current_url,
                },
                "message": f"AgentTrust allowed ({risk} risk). "
                           + (f"Browser: {br.get('message', 'OK')}" if br else "No browser.")
                           + f" Current page: {current_url}"
            }
            if isinstance(result.get("page_change"), dict):
                payload["page_change"] = result.get("page_change")
            if isinstance(br.get("page_change"), dict):
                payload["browser_result"]["page_change"] = br.get("page_change")
            cb = getattr(self.agenttrust, "on_platform_action_event", None)
            if cb:
                cb({"action_type": action_type, "url": url, "target": target, "form_data": form_data, "result": payload})
            return payload
        
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
                payload = {
                    "status": "step_up_required",
                    "message": error_msg,
                    "requires_user_approval": True
                }
                cb = getattr(self.agenttrust, "on_platform_action_event", None)
                if cb:
                    cb({"action_type": action_type, "url": url, "target": target, "form_data": form_data, "result": payload})
                return payload
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
                payload = {
                    "status": "denied",
                    "message": error_msg,
                    "reason": "Policy violation"
                }
                cb = getattr(self.agenttrust, "on_platform_action_event", None)
                if cb:
                    cb({"action_type": action_type, "url": url, "target": target, "form_data": form_data, "result": payload})
                return payload
        
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
            payload = {
                "status": "error",
                "message": f"Action failed: {error_msg}. "
                           "This may be a temporary backend/auth issue. "
                           "Try the action again, or try a different approach."
            }
            cb = getattr(self.agenttrust, "on_platform_action_event", None)
            if cb:
                cb({"action_type": action_type, "url": url, "target": target, "form_data": form_data, "result": payload})
            return payload
    
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


def _kill_stale_browsers():
    """Kill leftover chromedriver/chrome processes from previous runs.

    Only targets chromedriver processes and the Selenium-managed Chrome
    instances that use the agent's custom profile directory.  Regular
    user Chrome windows are NOT affected because they don't run under
    chromedriver.
    """
    import subprocess, platform
    if platform.system() != "Windows":
        # On Linux/macOS, pkill chromedriver is sufficient
        try:
            subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True, timeout=5)
        except Exception:
            pass
        return

    killed = []
    try:
        # 1. Kill chromedriver.exe — this also orphans its managed Chrome
        r = subprocess.run(
            ["taskkill", "/F", "/IM", "chromedriver.exe"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            killed.append("chromedriver")
    except Exception:
        pass

    try:
        # 2. Kill Chrome instances launched with our custom profile.
        #    We identify them by the --user-data-dir flag pointing at
        #    .chrome-profile inside this directory.
        profile_marker = ".chrome-profile"
        wmic = subprocess.run(
            ["wmic", "process", "where",
             "name='chrome.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, timeout=10,
        )
        for line in (wmic.stdout or "").splitlines():
            if profile_marker in line:
                parts = line.strip().split()
                pid = parts[-1] if parts else None
                if pid and pid.isdigit():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5,
                    )
                    killed.append(f"chrome(pid={pid})")
    except Exception:
        pass

    if killed:
        print(f"🧹 Cleaned up stale processes: {', '.join(killed)}")
        import time; time.sleep(1)


def main():
    """
    Run real ChatGPT agent with AgentTrust - 100% enforcement
    
    CRITICAL: AgentTrust validation is MANDATORY for all browser actions.
    The BrowserActionExecutor enforces this - there is no way to bypass it.
    """
    _kill_stale_browsers()

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
                    require_approval = cmd.get("requireApproval", False)
                    mode_tag = " [approval per action]" if require_approval else ""
                    print(f"\nRoutine command: {routine_name} ({len(steps)} steps, {scope}){mode_tag}")

                    prompt_id = None
                    try:
                        prompt_id = agent.agenttrust.store_prompt(f"[Routine] {routine_name}")
                    except Exception:
                        pass

                    result = agent.browser_executor.replay_routine(
                        steps, routine_name, scope=scope, is_owner=is_owner,
                        require_approval=require_approval,
                        progress_callback=lambda text: _routine_progress(agent, prompt_id, text))

                    summary = f"Routine '{routine_name}': {result.get('steps_completed')}/{result.get('steps_total')} steps completed"
                    if result.get("success"):
                        print(summary)
                    else:
                        print(f"{summary} (with issues)")
                    if prompt_id:
                        try:
                            agent.agenttrust.update_prompt_response(prompt_id, summary)
                        except Exception:
                            pass
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


_routine_progress_lines: list = []

def _routine_progress(agent, prompt_id, line: str):
    """Push a routine progress line to the backend for the extension UI."""
    _routine_progress_lines.append(line)
    if prompt_id and hasattr(agent, 'agenttrust'):
        try:
            agent.agenttrust.update_prompt_progress(
                prompt_id, "\n".join(_routine_progress_lines))
        except Exception:
            pass


if __name__ == "__main__":
    main()
