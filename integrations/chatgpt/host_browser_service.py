import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from chatgpt_agent_with_agenttrust import BrowserController


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


os.environ.setdefault("AGENTTRUST_LOAD_EXTENSION", "false")

HOST = os.getenv("AGENTTRUST_HOST_BROWSER_HOST", "127.0.0.1")
PORT = int(os.getenv("AGENTTRUST_HOST_BROWSER_PORT", "4100"))
HEADLESS = _truthy("AGENTTRUST_HOST_BROWSER_HEADLESS")

_browser = None


def _allow_all(*_args, **_kwargs):
    # The host executor is the deterministic enforcement boundary.
    return {"status": "allowed"}


def get_browser() -> BrowserController:
    global _browser
    if _browser is None or not _browser.is_alive():
        _browser = BrowserController(headless=HEADLESS, agenttrust_validator=_allow_all)
    return _browser


def _domain(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def current_page(include_screenshot: bool = True):
    browser = get_browser()
    page = browser.get_page_content(include_html=False) or {}
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": page.get("text", ""),
        "untrustedContent": page.get("text", ""),
        "screenshot": browser.take_screenshot() if include_screenshot else None,
        "elements": browser.get_visible_elements(),
        "domain": _domain(page.get("url", "")),
        "activeTab": browser.get_active_tab(),
        "tabs": browser.list_tabs(),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, status: int, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):
        try:
            if self.path.startswith("/health"):
                browser = get_browser()
                self._send(
                    200,
                    {
                        "ok": True,
                        "service": "agenttrust-host-browser",
                        "browserAlive": browser.is_alive(),
                    },
                )
                return

            if self.path.startswith("/current-page"):
                self._send(200, current_page(include_screenshot=True))
                return

            self._send(404, {"ok": False, "error": "Not found"})
        except Exception as error:
            self._send(500, {"ok": False, "error": str(error)})

    def do_POST(self):
        try:
            body = self._read_json()
            browser = get_browser()

            if self.path == "/navigate":
                self._send(200, browser.navigate(body["url"]))
                return

            if self.path == "/click":
                self._send(200, browser.click_element(body.get("target") or {}))
                return

            if self.path == "/type":
                self._send(
                    200,
                    browser.type_text(
                        body.get("target") or {},
                        body.get("text", ""),
                        press_enter=bool(body.get("pressEnter")),
                    ),
                )
                return

            if self.path == "/submit":
                form_data = body.get("formData") or {}
                target = body.get("target") or {}
                if form_data:
                    self._send(200, browser.submit_form(form_data))
                elif target:
                    self._send(200, browser.click_element(target))
                else:
                    self._send(400, {"success": False, "message": "submit requires target or formData"})
                return

            if self.path == "/open-tab":
                self._send(200, browser.open_new_tab(body["url"], body.get("label") or ""))
                return

            if self.path == "/switch-tab":
                label = body.get("label")
                index = body.get("index")
                self._send(200, browser.switch_to_tab(index if index is not None else label))
                return

            self._send(404, {"ok": False, "error": "Not found"})
        except Exception as error:
            self._send(500, {"ok": False, "error": str(error)})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"agenttrust-host-browser listening on http://{HOST}:{PORT}")
    server.serve_forever()
