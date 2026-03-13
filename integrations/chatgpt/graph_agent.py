"""
LangGraph Agent for AgentTrust Browser Automation
==================================================
Replaces the freeform while-loop with an explicit state graph:

    PLAN → OBSERVE → AGENT → TOOLS → VERIFY → (loop) → RESPOND

Key improvements over the raw ReAct loop:
  - Forced page observation before every action decision
  - Structured verification after every action
  - Goal tracking with sub-task decomposition
  - Automatic failure detection and re-routing
  - Clean routing on step-up auth and denials

Usage:
    from graph_agent import build_graph
    graph = build_graph(agent_instance)
    result = graph.invoke(initial_state)
"""

import json
import re
import time
from typing import TypedDict, List, Any, Optional
from langgraph.graph import StateGraph, END


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    """Full state for the agent graph. All keys are optional (total=False)."""

    # --- Input ---
    user_request: str
    conversation_history: list        # Previous turns from parent agent

    # --- Planning ---
    sub_goals: list                   # High-level steps for the task
    current_goal_index: int           # Which sub-goal we're working on
    plan_text: str                    # Human-readable plan summary

    # --- Observation ---
    current_url: str
    page_title: str
    page_text: str                    # Truncated visible text
    visible_elements: list            # Interactive elements on page
    page_vision: str                  # Vision LLM classification of the page
    has_overlay: bool                 # Whether an overlay/popup was detected
    login_state: str                  # "ALREADY LOGGED IN (...)" or ""

    # --- Turn messages (OpenAI API) ---
    turn_messages: list               # Tool call/result pairs this turn
    pending_tool_calls: list          # Tool calls awaiting execution

    # --- Action tracking ---
    last_action_result: dict
    last_action_name: str
    action_category: str              # "mutating" | "read_only" | "none"
    consecutive_failures: int
    total_actions: int
    recent_actions: list              # Last N action signatures for loop detection

    # --- Output ---
    final_response: str

    # --- Tab state ---
    active_tab: str                   # Label of the active tab
    open_tabs: list                   # List of {index, label, url, is_active}

    # --- Control ---
    needs_step_up: bool
    step_up_message: str

    # --- API context ---
    github_repos: list                # Cached [{full_name, owner, name}] from GET /user/repos

    # --- Progress tracking (live UI in extension) ---
    progress_lines: list              # Accumulated step descriptions


# Actions that change page state → require re-observation
MUTATING_ACTIONS = {
    "agenttrust_browser_action",
    "open_link",
    "type_text",
    "auto_login",
    "go_back",
    "go_forward",
    "open_new_tab",
    "switch_to_tab",
    "close_tab",
    "scroll_page",
}

# Subset of mutating actions that represent real task progress.
# Only these reset the consecutive failure counter on success.
# scroll_page is deliberately excluded — it changes viewport but
# doesn't indicate the agent is making forward progress.
PROGRESS_ACTIONS = {
    "agenttrust_browser_action",
    "open_link",
    "type_text",
    "auto_login",
    "open_new_tab",
    "switch_to_tab",
    "close_tab",
    "call_external_api",
}

# Read-only actions → agent can continue without re-observing
READ_ONLY_ACTIONS = {
    "get_saved_credentials",
    "wait_for_element",
    "call_external_api",
    "list_tabs",
}

MAX_ACTIONS = 20
MAX_CONSECUTIVE_FAILS = 3


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(agent):
    """
    Build and compile the LangGraph state graph.

    Args:
        agent: ChatGPTAgentWithAgentTrust instance — provides the LLM client,
               browser executor, tool definitions, and tool execution.

    Returns:
        Compiled LangGraph graph ready for .invoke().
    """

    # ================================================================== #
    #  Progress helper — pushes live step updates to the extension        #
    # ================================================================== #
    # Store progress lines on the agent so they persist reliably across
    # graph nodes without depending on LangGraph state propagation.
    _progress_lines: list = []

    def _emit_progress(state: AgentState, line: str) -> list:
        """Append a progress line and push the full log to the backend.
        Returns the updated progress_lines list (for convenience; the
        canonical store is ``_progress_lines`` on the closure).

        Uses agent.agenttrust.current_prompt_id directly (set by
        store_prompt before the graph runs).
        """
        _progress_lines.append(line)
        if hasattr(agent, "agenttrust"):
            pid = getattr(agent.agenttrust, "current_prompt_id", None)
            if pid:
                agent.agenttrust.update_prompt_progress(pid, "\n".join(_progress_lines))
            else:
                print(f"  [progress] skipped — no prompt_id (line: {line[:60]})")
        return list(_progress_lines)

    # ================================================================== #
    #  PLAN node                                                          #
    # ================================================================== #
    def plan_node(state: AgentState) -> dict:
        """Use the LLM to decompose the user request into sub-goals.

        First classifies whether the request actually needs browser
        automation.  If not (e.g. casual chat, general questions),
        produce a plain-text answer and skip the action pipeline.
        """
        _progress_lines.clear()

        # ---- Intent gate: does the request need browser actions? ----
        req = state["user_request"]

        # Gather browser context so the classifier knows if there is an
        # active browser session (which biases heavily toward BROWSER).
        browser_url = ""
        browser_title = ""
        try:
            if agent.browser_executor.browser:
                browser_url = agent.browser_executor.get_current_url() or ""
                browser_title = agent.browser_executor.browser.get_page_title() or ""
        except Exception:
            pass

        has_active_page = bool(
            browser_url
            and browser_url not in ("about:blank", "data:,", "")
            and "localhost" not in browser_url
        )

        # Keyword shortcut: if the request clearly involves browsing,
        # searching, emailing, or API calls, skip the classifier entirely.
        _req_lower = req.lower()
        _BROWSER_KEYWORDS = (
            "search", "find", "look up", "browse", "navigate",
            "go to", "open", "visit", "click", "send an email",
            "send email", "compose email", "schedule", "create event",
            "post to slack", "post a message", "call_external_api",
            "amazon", "google", "github", "ebay", "gmail",
            "calendar", "slack", "notion", "microsoft",
        )
        _force_browser = any(kw in _req_lower for kw in _BROWSER_KEYWORDS)

        if _force_browser:
            intent = "BROWSER"
        else:
            # Summarise recent conversation so the classifier sees context
            recent_history = ""
            conv = state.get("conversation_history") or []
            if conv:
                tail = conv[-4:]
                lines = []
                for m in tail:
                    role = m.get("role", "?")
                    text = (m.get("content") or "")[:200]
                    lines.append(f"  {role}: {text}")
                recent_history = "\n".join(lines)

            context_block = ""
            if has_active_page:
                context_block += (
                    f"\n\nCONTEXT — the browser is currently open on:\n"
                    f"  URL: {browser_url}\n"
                    f"  Title: {browser_title}\n"
                )
            if recent_history:
                context_block += (
                    f"\nRecent conversation:\n{recent_history}\n"
                )

            try:
                gate_resp = agent._chat_completion(
                    model=agent.model_nano,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an intent classifier. Given a user message "
                                "to a browser-automation agent, decide whether it "
                                "requires the agent to USE the browser (navigate, "
                                "click, type, search on a website, open a page, "
                                "log in, etc.).\n\n"
                                "Reply with EXACTLY one word:\n"
                                "  BROWSER  — if live browser interaction is needed\n"
                                "  CHAT     — if it can be answered with text alone\n\n"
                                "IMPORTANT RULES:\n"
                                "- If the browser is currently open on a real website "
                                "(not about:blank or localhost), almost ALL user "
                                "messages should be classified as BROWSER because the "
                                "user is likely giving follow-up instructions about "
                                "the current task.\n"
                                "- Short follow-up phrases like 'yes', 'do it', "
                                "'continue', 'go ahead', 'I clicked continue for you', "
                                "'you have them', 'try again', 'next', 'ok', 'done' "
                                "are ALWAYS BROWSER when a page is open.\n"
                                "- Requests involving 'find', 'search', 'send email', "
                                "'schedule', 'post', or any website name are ALWAYS "
                                "BROWSER.\n"
                                "- Only classify as CHAT if there is NO active browser "
                                "page AND the message is clearly a general knowledge "
                                "question with no browser intent (e.g. 'what is 2+2', "
                                "'explain quantum physics').\n"
                            ),
                        },
                        {"role": "user", "content": req + context_block},
                    ],
                    temperature=0,
                )
                intent = (gate_resp.choices[0].message.content or "").strip().upper()
            except Exception:
                intent = "BROWSER"

            # Safety net: if a page is open, force BROWSER
            if has_active_page and intent.startswith("CHAT"):
                print(f"  INTENT: Classifier said CHAT but browser is on {browser_url} — overriding to BROWSER")
                intent = "BROWSER"

        if intent.startswith("CHAT"):
            # No browser needed — answer conversationally
            progress = _emit_progress(state, "PLAN|Answering directly (no browser needed)")
            try:
                chat_resp = agent._chat_completion(
                    model=agent.model_fast,
                    messages=(
                        [{"role": "system", "content": "You are a helpful assistant."}]
                        + list(state.get("conversation_history") or [])
                        + [{"role": "user", "content": req}]
                    ),
                    temperature=0.5,
                )
                answer = chat_resp.choices[0].message.content or "I'm not sure."
            except Exception:
                answer = "Sorry, I wasn't able to process that."

            print(f"  PLAN: No browser action needed — answering directly.")
            return {
                "sub_goals": [],
                "current_goal_index": 0,
                "plan_text": "(no browser actions required)",
                "turn_messages": [],
                "pending_tool_calls": [],
                "consecutive_failures": 0,
                "total_actions": 0,
                "needs_step_up": False,
                "step_up_message": "",
                "action_category": "none",
                "final_response": answer,
                "progress_lines": progress,
            }

        # ---- Browser path: gather context & build sub-goals ----

        # Include current browser context so the planner knows where we are
        browser_ctx = ""
        try:
            if agent.browser_executor.browser:
                url = agent.browser_executor.get_current_url()
                title = agent.browser_executor.browser.get_page_title()
                if url and url not in ("about:blank", "data:,"):
                    browser_ctx = f"\nThe browser is currently on: \"{title}\" at {url}"
        except Exception:
            pass

        # Retrieve similar past tasks from action history RAG
        rag_context = ""
        try:
            if hasattr(agent, 'action_rag') and agent.action_rag:
                similar = agent.action_rag.retrieve(state['user_request'], top_k=3)
                if similar:
                    rag_context = "\n\n" + agent.action_rag.format_for_prompt(similar)
                    print(f"  RAG: Found {len(similar)} similar past tasks "
                          f"(best match: {similar[0]['similarity']:.0%})")
        except Exception as e:
            print(f"  RAG retrieval error: {e}")

        # Proactive credential check — detect login-related requests and
        # look up saved credentials so the planner knows upfront
        cred_hint = ""
        try:
            req_lower = state["user_request"].lower()
            login_keywords = ("log in", "login", "sign in", "signin", "authenticate",
                              "credentials", "password", "account")
            if any(kw in req_lower for kw in login_keywords):
                # Extract likely domain from the request
                import re as _re
                domain_match = _re.search(
                    r'(?:on|to|into|at)\s+([a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z]{2,})+)',
                    state["user_request"]
                )
                if domain_match:
                    target_domain = domain_match.group(1)
                    creds = agent.agenttrust.get_credentials(target_domain)
                    if creds:
                        cred_hint = (
                            f"\n\nNOTE: Saved credentials found for {target_domain}. "
                            "Include a step to call get_saved_credentials and auto_login "
                            "instead of asking the user for credentials."
                        )
                        print(f"  CREDS: Found saved credentials for {target_domain}")
                    else:
                        cred_hint = (
                            f"\n\nNOTE: No saved credentials for {target_domain}. "
                            "Still try get_saved_credentials (in case of domain alias), "
                            "and ask the user for credentials only if not found."
                        )
        except Exception:
            pass

        # Build a brief summary of recent conversation so the planner
        # knows what the agent already did (e.g. credentials found, login
        # attempted, pages visited).
        history_summary = ""
        conv = state.get("conversation_history") or []
        if conv:
            # Include the last 3 exchanges (6 messages) — enough to see
            # what was done without blowing the context window.
            tail = conv[-6:]
            summary_lines = []
            for m in tail:
                role = m.get("role", "?")
                text = (m.get("content") or "")[:300]
                summary_lines.append(f"  [{role}] {text}")
            history_summary = (
                "\n\nRecent conversation (what has already happened):\n"
                + "\n".join(summary_lines)
            )

        from datetime import datetime as _dt_plan
        _today_plan = _dt_plan.now().strftime("%A, %B %d, %Y")

        plan_prompt = (
            "Break down this user request into 2-4 broad sub-goals.\n"
            "Return ONLY a JSON array of strings — no commentary.\n"
            f"Today's date: {_today_plan}\n\n"
            "API-FIRST RULE (CRITICAL):\n"
            "If the request involves GitHub, Google Calendar, Slack, Microsoft "
            "(Outlook/OneDrive/ToDo), or Notion, the FIRST step MUST be "
            "\"Use call_external_api to ...\". Only fall back to browser "
            "automation if the API call fails or the task requires visual "
            "interaction (e.g. browsing a webpage, filling a form).\n"
            "- GitHub: provider='github' — ALWAYS list repos first to find the\n"
            "  correct owner/repo, then get issues, create issue, etc.\n"
            "- Google Calendar: provider='google-oauth2' — list/create events\n"
            "- Slack: provider='slack' — list channels, post messages\n"
            "- Microsoft: provider='windowslive' — send Outlook email, "
            "create To Do tasks, read/write OneDrive files\n"
            "- Notion: provider='notion' — create pages, search, update databases\n\n"
            "For all other tasks, use browser automation.\n\n"
            "PLANNING RULES:\n"
            "- COMBINE related steps into ONE goal. Search + reading articles = one goal.\n"
            "  Composing + sending an email = one goal. Do NOT split them.\n"
            "- When the task requires RESEARCH, say 'Search Google for X, visit\n"
            "  top results, and gather detailed findings' — always use\n"
            "  https://www.google.com, NEVER Images.\n"
            "- For research about SPECIFIC companies (OpenAI, Google, Anthropic,\n"
            "  etc.), prefer visiting their OFFICIAL sites/blogs directly after\n"
            "  a quick Google search. Skip aggregator/news-roundup sites.\n"
            "- Keep research to 2-3 pages MAX — read deeply, not broadly.\n"
            "- When the task requires EMAIL, say 'Navigate to Gmail, compose and send\n"
            "  an email to X with the findings'.\n"
            "- When visiting GitHub repos, always go to the REPO ROOT\n"
            "  (e.g. https://github.com/owner/repo) to read the README.\n"
            "  NEVER navigate to /actions, /issues, or /pulls unless specifically asked.\n"
            "- When COMPARING items across sites (prices, features, reviews),\n"
            "  combine ALL browsing into ONE goal. NEVER make 'compare the\n"
            "  results' a separate goal — include the comparison in the same\n"
            "  goal that visits the sites.\n"
            "- Goals must be in the correct ORDER. Research BEFORE email. Email BEFORE\n"
            "  calendar invites.\n"
            "- Keep to 2-4 goals maximum. Fewer is better.\n\n"
            "IMPORTANT: If the recent conversation shows that prior steps were "
            "already completed (e.g. credentials found, login attempted, page "
            "already loaded), do NOT repeat those steps. Start from where the "
            "agent left off.\n\n"
            f"User request: {state['user_request']}{browser_ctx}\n"
            + (history_summary + "\n" if history_summary else "\n")
            + "Examples:\n"
            "  Browser task: [\"Navigate to amazon.com, search for 'wireless "
            "headphones', and add the first result to cart\"]\n"
            "  Research + email: [\"Search https://www.google.com for the topic, "
            "visit top results to read articles, and gather detailed findings\", "
            "\"Navigate to mail.google.com, compose and send an email to X with "
            "the findings\"]\n"
            "  Research + email + calendar: [\"Search https://www.google.com for "
            "the topic, visit top articles, and gather detailed findings\", "
            "\"Navigate to mail.google.com, compose and send an email to X with "
            "the findings\", "
            "\"Use call_external_api to create a Google Calendar event\"]\n"
            "  API task: [\"Use call_external_api to list GitHub repos\"]\n"
            "  Slack: [\"Use call_external_api to post a message to #channel on Slack\"]\n"
            "  Microsoft: [\"Use call_external_api to send an Outlook email via Microsoft Graph\"]\n"
            "  Notion: [\"Use call_external_api to create a Notion page with findings\"]\n"
            "  Cross-service: [\"Search Google for AI news and gather findings\", "
            "\"Use call_external_api to post a summary to #engineering on Slack\", "
            "\"Use call_external_api to create a Google Calendar event for a review meeting\"]\n"
            "  Price comparison: [\"Search Amazon for X, open the product page "
            "and note the price, then search TCGplayer for the same product, "
            "open the product page and note the price, then summarize which "
            "site has the better deal\"]\n"
            + (rag_context + "\n" if rag_context else "")
            + (cred_hint if cred_hint else "") +
            "\nJSON array:"
        )

        try:
            response = agent._chat_completion(
                model=agent.model_fast,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a task planner for a browser automation agent. "
                            "Return only a JSON array of sub-goals."
                        ),
                    },
                    {"role": "user", "content": plan_prompt},
                ],
                temperature=0.2,
            )
            text = (response.choices[0].message.content or "").strip()

            # Strip markdown code fences if present
            if "```" in text:
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else parts[0]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            sub_goals = json.loads(text)
            if not isinstance(sub_goals, list) or not sub_goals:
                sub_goals = [state["user_request"]]
        except Exception as e:
            print(f"   Plan parsing failed ({e}), using single goal")
            sub_goals = [state["user_request"]]

        plan_text = "\n".join(f"  {i + 1}. {g}" for i, g in enumerate(sub_goals))
        print(f"\n{'='*50}")
        print(f"  PLAN ({len(sub_goals)} steps):")
        print(plan_text)
        print(f"{'='*50}\n")

        steps_summary = "; ".join(g[:60] for g in sub_goals)
        progress = _emit_progress(state, f"PLAN|Planning {len(sub_goals)} steps: {steps_summary}")

        return {
            "sub_goals": sub_goals,
            "current_goal_index": 0,
            "plan_text": plan_text,
            "turn_messages": [],
            "pending_tool_calls": [],
            "consecutive_failures": 0,
            "total_actions": 0,
            "needs_step_up": False,
            "step_up_message": "",
            "action_category": "none",
            "final_response": "",
            "github_repos": [],
            "progress_lines": progress,
        }

    # ================================================================== #
    #  OBSERVE node                                                       #
    # ================================================================== #
    def observe_node(state: AgentState) -> dict:
        """Read current browser state and classify via vision LLM."""
        executor = agent.browser_executor

        url = ""
        title = ""
        text = ""
        elements = []
        page_vision = ""
        has_overlay = False

        if executor.browser:
            try:
                url = executor.get_current_url() or ""
            except Exception:
                pass

            # Auto-dismiss cookie banners, popups, overlays before reading
            try:
                if hasattr(executor, 'dismiss_overlays'):
                    executor.dismiss_overlays()
            except Exception:
                pass

            try:
                content = executor.get_page_content()
                title = content.get("title", "")
                text = content.get("text", "")[:3000]
            except Exception:
                pass
            try:
                elements = executor.get_visible_elements() or []
            except Exception:
                pass

            # --- CAPTCHA-only vision check ---
            # General vision page-classification is disabled to save tokens.
            # We ONLY use vision when the page text hints at a CAPTCHA, so we
            # can detect and attempt to solve it.
            captcha_keywords = ("captcha", "recaptcha", "hcaptcha", "verify you're human",
                                "verify you are human", "i'm not a robot", "i am not a robot",
                                "prove you're human")
            page_lower = text.lower()
            if any(kw in page_lower for kw in captcha_keywords):
                try:
                    screenshot_b64 = executor.take_screenshot()
                    if screenshot_b64:
                        captcha_resp = agent._chat_completion(
                            model=agent.model_fast,
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a CAPTCHA detection assistant. "
                                        "Given a screenshot of a web page, determine:\n"
                                        "1. Is there a CAPTCHA on the page? (YES/NO)\n"
                                        "2. If YES, what type? (checkbox, image-select, text, slider, other)\n"
                                        "3. If it is a simple checkbox CAPTCHA ('I am not a robot'), "
                                        "   say CHECKBOX so the agent can click it.\n\n"
                                        "Reply in this exact format:\n"
                                        "  CAPTCHA: YES or NO\n"
                                        "  TYPE: checkbox / image-select / text / slider / other\n"
                                        "  ACTION: click_checkbox / needs_human / none\n"
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": f"URL: {url}\nIs there a CAPTCHA?"},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/png;base64,{screenshot_b64}",
                                                "detail": "low",
                                            },
                                        },
                                    ],
                                },
                            ],
                            temperature=0,
                            max_tokens=60,
                        )
                        captcha_text = (captcha_resp.choices[0].message.content or "").strip()
                        print(f"  CAPTCHA CHECK: {captcha_text}")

                        if "CAPTCHA: YES" in captcha_text.upper():
                            page_vision = f"captcha — {captcha_text.split(chr(10))[0]}"
                            # If it's a simple checkbox, try clicking it
                            if "click_checkbox" in captcha_text.lower():
                                try:
                                    from selenium.webdriver.common.by import By
                                    driver = executor.browser._actual_driver
                                    # Try clicking reCAPTCHA checkbox iframe
                                    iframes = driver.find_elements(By.CSS_SELECTOR,
                                        "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], "
                                        "iframe[title*='reCAPTCHA'], iframe[title*='hCaptcha']")
                                    for iframe in iframes:
                                        try:
                                            driver.switch_to.frame(iframe)
                                            checkbox = driver.find_element(By.CSS_SELECTOR,
                                                ".recaptcha-checkbox-border, .recaptcha-checkbox, "
                                                "#recaptcha-anchor, .checkbox")
                                            checkbox.click()
                                            time.sleep(1)
                                            driver.switch_to.default_content()
                                            print(f"  CAPTCHA: Clicked checkbox")
                                            # Re-read page after solving
                                            try:
                                                elements = executor.get_visible_elements() or []
                                            except Exception:
                                                pass
                                            try:
                                                content = executor.get_page_content()
                                                text = content.get("text", "")[:3000]
                                            except Exception:
                                                pass
                                            break
                                        except Exception:
                                            driver.switch_to.default_content()
                                            continue
                                except Exception as e:
                                    print(f"  CAPTCHA click failed: {e}")
                except Exception as e:
                    print(f"  CAPTCHA check skipped: {e}")

        # --- Login state detection ---
        login_state = ""
        if url and elements:
            logged_in_signals = []
            url_lower = url.lower()
            if any(frag in url_lower for frag in ("/inbox", "/#inbox", "/mail/u/",
                                                   "/feed", "/home", "/dashboard",
                                                   "/my-account", "/account")):
                logged_in_signals.append("authenticated page loaded")
            for el in elements:
                el_text = (el.get("text") or "").lower()
                el_aria = (el.get("aria_label") or el.get("aria-label") or "").lower()
                if any(kw in el_text for kw in ("sign out", "log out", "logout",
                                                 "signout", "sign off")):
                    logged_in_signals.append("sign-out link visible")
                    break
                if el_text == "compose" or el_aria == "compose":
                    logged_in_signals.append("compose button visible")
                    break
                if any(kw in el_aria for kw in ("my account", "account menu",
                                                 "profile", "user menu")):
                    logged_in_signals.append("account/profile menu visible")
                    break
            if logged_in_signals:
                login_state = f"ALREADY LOGGED IN ({', '.join(logged_in_signals)})"

        # --- Tab info ---
        active_tab = ""
        open_tabs = []
        if executor.browser:
            try:
                open_tabs = executor.list_tabs()
                active_info = executor.get_active_tab()
                active_tab = active_info.get("label", "main")
            except Exception:
                pass

        label = url[:80] if url else "(no page loaded)"
        tab_count = len(open_tabs) if open_tabs else 1
        print(f"  OBSERVE: {label}  [{active_tab}] ({tab_count} tab{'s' if tab_count != 1 else ''})")
        if login_state:
            print(f"  LOGIN: {login_state}")
        if page_vision:
            print(f"  VISION: {page_vision}")

        # Only emit OBSERVE progress when the URL changed (avoids noise
        # from repeated observations on the same page during scroll loops).
        _prev_url = state.get("current_url") or ""
        _obs_ret = {}
        if url and url != _prev_url:
            try:
                from urllib.parse import urlparse as _obs_up
                _obs_host = _obs_up(url).hostname or url[:50]
            except Exception:
                _obs_host = url[:50]
            progress = _emit_progress(state, f"OBSERVE|Viewing {_obs_host}")
            _obs_ret["progress_lines"] = progress

        return {
            "current_url": url,
            "page_title": title,
            "page_text": text,
            "visible_elements": elements,
            "page_vision": page_vision,
            "has_overlay": has_overlay,
            "login_state": login_state,
            "active_tab": active_tab,
            "open_tabs": open_tabs,
            **_obs_ret,
        }

    # ================================================================== #
    #  AGENT node — LLM decides the next action                           #
    # ================================================================== #
    def agent_node(state: AgentState) -> dict:
        """Call the LLM with current context and available tools."""

        elements_str = ""
        if state.get("visible_elements"):
            els = state["visible_elements"][:50]
            elements_str = json.dumps(els, separators=(",", ":"))
            if len(elements_str) > 8000:
                elements_str = elements_str[:8000] + "…]"

        # Vision context from screenshot analysis
        vision_info = ""
        if state.get("page_vision"):
            vision_info = f"Vision analysis: {state['page_vision']}\n"
        if state.get("has_overlay"):
            vision_info += "⚠ OVERLAY DETECTED: A popup, modal, or banner is covering the page. Dismiss it before interacting with underlying content.\n"

        # Tab context
        tabs_info = ""
        open_tabs = state.get("open_tabs") or []
        if len(open_tabs) > 1:
            tab_lines = []
            for t in open_tabs:
                marker = " ← ACTIVE" if t.get("is_active") else ""
                tab_lines.append(f"  [{t.get('index')}] {t.get('label')}: {t.get('url', '?')}{marker}")
            tabs_info = "Open tabs:\n" + "\n".join(tab_lines) + "\n"
            if len(open_tabs) >= 3:
                tabs_info += (
                    f"⚠ You have {len(open_tabs)} tabs open. Close tabs you "
                    "no longer need with close_tab to keep context manageable.\n"
                )
        elif open_tabs:
            tabs_info = f"Active tab: {open_tabs[0].get('label', 'main')}\n"

        login_info = ""
        if state.get("login_state"):
            login_info = f"⚠ {state['login_state']} — do NOT call get_saved_credentials or auto_login.\n"

        # Hint when the page has no interactive elements
        nav_hint = ""
        cur_url = state.get('current_url', '')
        if not elements_str or elements_str == "[]":
            nav_hint = (
                "⚠ NO INTERACTIVE ELEMENTS on this page. Use open_link to "
                "navigate to the site you need (e.g. https://www.google.com).\n"
            )
        elif cur_url and ("localhost" in cur_url or "about:blank" in cur_url
                          or cur_url == "data:,"):
            nav_hint = (
                "⚠ You are on the AgentTrust startup page. This is NOT a "
                "website for browsing. Use open_link to navigate to the site "
                "you need to accomplish your task (e.g. https://www.google.com).\n"
            )

        # Detect if the page has a search bar the agent can use.
        # Suppress the hint on Google search (agent should use Google's
        # search box naturally) and on sites whose search bar would only
        # cover that site's own content (e.g. blog.google searching for
        # Anthropic content is pointless).
        search_hint = ""
        _SEARCH_KEYWORDS = {"search", "query", "q", "keyword", "find", "lookup"}
        _cur_host = ""
        try:
            from urllib.parse import urlparse as _up
            _cur_host = _up(cur_url).hostname or ""
        except Exception:
            pass
        _SKIP_SEARCH_HINT_HOSTS = {
            "www.google.com", "google.com", "www.bing.com", "bing.com",
            "search.yahoo.com", "duckduckgo.com",
        }
        if _cur_host not in _SKIP_SEARCH_HINT_HOSTS:
            visible_els = state.get("visible_elements") or []
            for el in visible_els:
                if el.get("t") != "in":
                    continue
                _ph = (el.get("ph") or "").lower()
                _al = (el.get("al") or "").lower()
                _nm = (el.get("nm") or "").lower()
                _rl = (el.get("rl") or "").lower()
                _id = (el.get("id") or "").lower()
                combined = f"{_ph} {_al} {_nm} {_rl} {_id}"
                if any(kw in combined for kw in _SEARCH_KEYWORDS) or _rl in ("search", "searchbox", "combobox"):
                    label = el.get("ph") or el.get("al") or el.get("nm") or "search"
                    search_hint = (
                        f"🔍 This page has a SEARCH BAR ('{label}'). "
                        f"Use it ONLY to find content that belongs to THIS site "
                        f"({_cur_host}). Do NOT search here for other companies "
                        f"or unrelated topics — navigate directly to those sites instead.\n"
                    )
                    break

        # Extract dollar prices from page text so the LLM sees them immediately
        price_hint = ""
        _page_text = state.get("page_text") or ""
        _prices = re.findall(r"\$\d[\d,]*\.?\d{0,2}", _page_text)
        if _prices:
            unique_prices = list(dict.fromkeys(_prices))[:10]
            price_hint = f"💲 PRICES on page: {', '.join(unique_prices)}\n"

        # Hint when the agent has been scrolling the same page repeatedly
        scroll_hint = ""
        _recent = state.get("recent_actions") or []
        _scroll_count = sum(1 for s in _recent if s.startswith("scroll_page:"))
        if _scroll_count >= 3:
            scroll_hint = (
                f"⚠ You have scrolled this page {_scroll_count} times. "
                "You have enough data — READ the Content above and respond "
                "with a TEXT SUMMARY of what you found. STOP scrolling.\n"
            )

        goal_idx = state.get("current_goal_index", 0)
        sub_goals = state.get("sub_goals") or []
        current_goal = (
            sub_goals[goal_idx] if goal_idx < len(sub_goals) else "Complete the task"
        )
        remaining = sub_goals[goal_idx + 1:] if goal_idx + 1 < len(sub_goals) else []

        observation = (
            f"\n[PAGE STATE]\n"
            f"URL: {state.get('current_url', 'not loaded')}\n"
            f"Title: {state.get('page_title', '')}\n"
            f"{nav_hint}"
            f"{search_hint}"
            f"{price_hint}"
            f"{scroll_hint}"
            f"{login_info}"
            f"{vision_info}"
            f"{tabs_info}"
            f"Content (truncated):\n{state.get('page_text', '')[:4000]}\n\n"
            f"Interactive elements:\n{elements_str}\n\n"
            f"[TASK]\n"
            f">>> CURRENT GOAL ({goal_idx + 1}/{len(sub_goals)}): {current_goal}\n"
            f"Remaining: {remaining if remaining else '(none — this is the last goal)'}\n"
            f"Actions used: {state.get('total_actions', 0)}/{MAX_ACTIONS}\n"
        )

        from datetime import datetime as _dt
        _today = _dt.now().strftime("%A, %B %d, %Y")

        system_prompt = (
            "You are a browser automation agent with FULL control of a real browser.\n"
            "You perform tasks by actually navigating, clicking, typing, and reading.\n"
            f"Today's date: {_today}\n\n"
            "API-FIRST RULE (HIGHEST PRIORITY):\n"
            "When the current goal involves GitHub, Google Calendar, Slack,\n"
            "Microsoft (Outlook/OneDrive/ToDo), or Notion, ALWAYS use\n"
            "call_external_api FIRST instead of browser automation. Only fall\n"
            "back to the browser if the API call fails or the task requires\n"
            "visual interaction.\n"
            "- GitHub: provider='github'\n"
            "    GET https://api.github.com/user/repos  ← ALWAYS call this FIRST\n"
            "      to discover the user's username and available repos.\n"
            "    POST https://api.github.com/repos/{owner}/{repo}/issues\n"
            "    IMPORTANT: NEVER guess the {owner} or {repo}. Always list\n"
            "    repos first, find the matching repo name, then use the\n"
            "    exact owner/repo from the response.\n"
            "- Google Calendar: provider='google-oauth2'\n"
            "    GET https://www.googleapis.com/calendar/v3/calendars/primary/events\n"
            "    POST https://www.googleapis.com/calendar/v3/calendars/primary/events\n"
            "- Slack: provider='slack'\n"
            "    GET https://slack.com/api/conversations.list  ← call this FIRST\n"
            "      to get the channel ID for the channel name.\n"
            "    POST https://slack.com/api/chat.postMessage  (body: {channel, text})\n"
            "    IMPORTANT: The 'channel' field must be a channel ID (e.g.\n"
            "    'C0123456789'), NOT a name. List channels first to find it.\n"
            "- Microsoft (Outlook/OneDrive/ToDo): provider='windowslive'\n"
            "    POST https://graph.microsoft.com/v1.0/me/sendMail\n"
            "      body: {message: {subject, body: {contentType:'Text', content}, toRecipients: [{emailAddress: {address}}]}}\n"
            "    POST https://graph.microsoft.com/v1.0/me/todo/lists/{listId}/tasks  (body: {title})\n"
            "    GET https://graph.microsoft.com/v1.0/me/drive/root/children\n"
            "- Notion: provider='notion'\n"
            "    POST https://api.notion.com/v1/pages  (body: {parent: {database_id}, properties: {...}})\n"
            "    POST https://api.notion.com/v1/search  (body: {query})\n\n"
            "WORKFLOW — follow strictly:\n"
            "1. Check if the current goal can be done via call_external_api.\n"
            "2. If not, LOOK at the page state provided below.\n"
            "3. Pick ONE tool call that advances the current goal.\n"
            "4. Use the most SPECIFIC element identifier available:\n"
            "   id > name > aria-label > placeholder > href > text.\n"
            "5. Fill target objects completely (id, text, href, tagName, etc.).\n\n"
            "ELEMENT IDENTIFICATION — CRITICAL:\n"
            "- ALWAYS look at the Interactive elements list in [PAGE STATE].\n"
            "- NEVER send a click with empty or missing target identifiers.\n"
            "- Copy the element's id, text, href, aria-label, or name EXACTLY\n"
            "  from the interactive elements list into the target object.\n"
            "- If a button/link has text like 'Resend Email', 'Submit', 'Sign In',\n"
            "  set target.text to that EXACT text and target.tagName to 'BUTTON',\n"
            "  'A', or 'INPUT' as appropriate.\n"
            "- If you cannot find an element in the interactive elements list,\n"
            "  use get_page_content to read the page and try again.\n"
            "- For elements with id, ALWAYS prefer target.id over text matching.\n\n"
            "OVERLAY / POPUP HANDLING:\n"
            "- If you see overlays, modals, popups, cookie banners, or account\n"
            "  creation prompts covering the page, close them FIRST.\n"
            "- Look for close buttons in the interactive elements list with\n"
            "  text like 'Close', 'Dismiss', 'No thanks', 'Skip', 'X',\n"
            "  or aria-label='Close'.\n"
            "- Account creation popups and 'sign up' modals should be CLOSED,\n"
            "  NOT filled in (unless the user asked to sign up).\n\n"
            "SEARCH & FORM SUBMISSION:\n"
            "- When typing into search boxes, identify the correct input using:\n"
            "  aria-label (e.g. 'Search'), role='searchbox' or role='combobox',\n"
            "  type='search', placeholder text, or name attribute.\n"
            "- AFTER typing in a search box, use type_text with press_enter=true\n"
            "  to submit the search. Do NOT try to find and click a 'Search'\n"
            "  button — just press Enter. This is MORE RELIABLE.\n"
            "- For any form with a single input (search, verification code, etc.),\n"
            "  prefer pressing Enter over finding and clicking a submit button.\n\n"
            "LOGIN FLOW — MANDATORY:\n"
            "- BEFORE attempting any login, CHECK if you are ALREADY LOGGED IN.\n"
            "  The observation above includes a login-state line when the page\n"
            "  shows authenticated indicators (inbox loaded, compose button,\n"
            "  sign-out link, account/profile menu). If you see\n"
            "  '⚠ ALREADY LOGGED IN', SKIP get_saved_credentials and auto_login.\n"
            "- Only call get_saved_credentials + auto_login when you are on a\n"
            "  site's login page AND the page has login input fields.\n"
            "- When you DO need to log in:\n"
            "  1. Navigate to the site's OWN login page FIRST.\n"
            "  2. Call get_saved_credentials with the site's domain.\n"
            "  3. If credentials are found, call auto_login immediately.\n"
            "  4. auto_login handles multi-step forms, entering both username\n"
            "     AND password, clicking continue/next, and dismissing popups.\n"
            "  5. NEVER manually type usernames or passwords with type_text.\n"
            "  6. Only ask the user if NO saved credentials exist.\n"
            "- ⚠ auto_login ONLY works on the site's OWN login page.\n"
            "  Do NOT call auto_login while on an unrelated site.\n"
            "  Example: to log into Gmail, navigate to mail.google.com FIRST.\n"
            "- Do NOT pre-fetch credentials for sites you haven't navigated to yet.\n"
            "  Only look up credentials when you are ABOUT to log in.\n\n"
            "EMAIL & VERIFICATION CODE WORKFLOW — CRITICAL:\n"
            "- In email inboxes (Gmail, Outlook, Yahoo), the NEWEST emails\n"
            "  appear at the TOP of the inbox list.\n"
            "- In email THREADS (multiple replies in a conversation), the\n"
            "  NEWEST message is at the BOTTOM of the thread.\n"
            "- To extract a verification code from an email:\n"
            "  1. Open the email in the inbox.\n"
            "  2. Use get_page_content to READ the email body text.\n"
            "  3. Find the numeric code in the text (e.g. 5-6 digit number).\n"
            "  4. NEVER ask the user for the code — extract it yourself.\n"
            "- AFTER extracting the code, you MUST switch_to_tab to the\n"
            "  ORIGINAL site (e.g. investopedia, ebay) BEFORE typing the code.\n"
            "  ⚠ NEVER type a verification code into the email page.\n"
            "  ⚠ ALWAYS check the current URL — if it contains 'mail.google',\n"
            "  'outlook', or 'yahoo', you are on the EMAIL tab, NOT the target.\n"
            "  ⚠ switch_to_tab FIRST, then type the code.\n\n"
            "TAB MANAGEMENT:\n"
            "- Use open_new_tab when you need to visit a DIFFERENT site without\n"
            "  losing your place (e.g. checking email for a 2FA code, comparing\n"
            "  prices on another site, looking up information).\n"
            "- Give tabs short, meaningful labels (e.g. 'gmail', 'ebay', 'amazon').\n"
            "- After completing work in a secondary tab, ALWAYS switch_to_tab\n"
            "  back to the original tab.\n"
            "- Close tabs you no longer need with close_tab.\n"
            "- When a task requires 2FA / verification codes sent via email:\n"
            "  1. open_new_tab to the email provider (e.g. mail.google.com)\n"
            "  2. Call get_saved_credentials + auto_login if login is needed\n"
            "  3. Find the verification email and open it\n"
            "  4. Use get_page_content to READ the code from the email body\n"
            "  5. switch_to_tab back to the ORIGINAL site\n"
            "  6. Type the code into the verification field on that site\n"
            "  7. close_tab the email tab when done\n\n"
            "INFORMATION EXTRACTION — READ BEFORE ACTING:\n"
            "- The Content section in [PAGE STATE] contains the visible text on\n"
            "  the current page. READ IT before deciding your next action.\n"
            "- REMEMBER what you read! When you later compose an email or report,\n"
            "  use the information you already extracted from earlier pages.\n"
            "  Your full conversation history is preserved.\n\n"
            "WEB SEARCH & RESEARCH — MANDATORY STEPS:\n"
            "- To search the web, navigate to https://www.google.com (NOT imghp,\n"
            "  NOT images.google.com). Use the main search page.\n"
            "- Type your query into the search box and press Enter.\n"
            "- When typing into a search box that already has text, the field\n"
            "  is auto-cleared. Just provide your full new query.\n"
            "- After search results load, read the snippets for an overview.\n"
            "- Google snippets alone are NOT enough for research goals.\n"
            "  Open 1-2 of the top results to read full article content.\n"
            "- SPEED RULE: Visit at MOST 2-3 pages per research goal. Read\n"
            "  each page ONCE, extract what you need, then move on. Do NOT\n"
            "  visit 5+ pages — depth beats breadth for a demo.\n"
            "- PREFER OFFICIAL SOURCES: When researching specific companies\n"
            "  (OpenAI, Google, Anthropic, etc.), go directly to their official\n"
            "  blog/newsroom after the Google search. Skip news aggregators.\n"
            "- CRITICAL: When clicking search results, use the EXACT href\n"
            "  from the interactive elements list. The href contains the\n"
            "  full URL (e.g. https://reuters.com/technology/ai-breakthrough-2026).\n"
            "  Pass this full href to open_link. Do NOT guess or shorten URLs.\n"
            "  Do NOT navigate to generic section pages like /artificial-intelligence/.\n"
            "- After reading an article, move on. Do NOT go_back to search\n"
            "  results unless you found zero useful information.\n"
            "- NEVER go_back more than once. Try a DIFFERENT site with open_link.\n"
            "- Only AFTER you have read actual article content should you\n"
            "  consider the research goal complete.\n\n"
            "GITHUB NAVIGATION:\n"
            "- When visiting a GitHub repository, always navigate to the repo\n"
            "  ROOT (e.g. https://github.com/owner/repo), not to tabs like\n"
            "  /actions, /issues, or /pulls.\n"
            "- The README is displayed on the repo root page — scroll down\n"
            "  to read it. You do NOT need to open /blob/main/README.md.\n"
            "- When reading a long page (README, article), scrolling multiple\n"
            "  times is perfectly fine — keep scrolling until you've read\n"
            "  the content you need.\n\n"
            "ON-SITE SEARCH — USE IT WISELY:\n"
            "- When [PAGE STATE] shows a 🔍 SEARCH BAR hint, use it ONLY to\n"
            "  find content that BELONGS to the current site.\n"
            "- Example: on Amazon search for products, on GitHub search for\n"
            "  repos, on TCGplayer search for cards.\n"
            "- NEVER use a site's search bar to search for a DIFFERENT company\n"
            "  or unrelated topic (e.g. do NOT search for 'Anthropic' on\n"
            "  blog.google — navigate directly to anthropic.com instead).\n"
            "- Only go back to Google if the current site doesn't have what\n"
            "  you're looking for.\n\n"
            "PRODUCT SEARCH & PRICE COMPARISON:\n"
            "- On e-commerce sites (Amazon, eBay, etc.), product search result\n"
            "  pages ALREADY show product names, prices, and ratings in the\n"
            "  Content section. READ the Content — you do NOT need to scroll\n"
            "  endlessly. Scroll 1-2 times to see more results, then EXTRACT\n"
            "  the information and respond with a text summary.\n"
            "- If you need detailed info (full specs, reviews), click into ONE\n"
            "  product page, read it, then respond.\n"
            "- STOP SCROLLING RULE: If you have scrolled 3+ times on the same\n"
            "  page, you have enough data. Respond with what you found.\n"
            "- When comparing prices across sites, note the price on site A,\n"
            "  then open_new_tab or switch_to_tab to site B, find the product,\n"
            "  note that price, then give the comparison in a text response.\n"
            "- Close tabs you no longer need to keep context manageable.\n\n"
            "PREFERRED SERVICE URLS (use these instead of guessing):\n"
            "- Google Search → https://www.google.com\n"
            "- Gmail / Google login → https://mail.google.com\n"
            "- Outlook / Microsoft → https://outlook.live.com\n"
            "- Yahoo Mail → https://mail.yahoo.com\n"
            "- Amazon → https://www.amazon.com\n"
            "- eBay → https://www.ebay.com\n"
            "- GitHub → https://github.com\n"
            "Do NOT use marketing/workspace/promo/images URLs.\n\n"
            "GOAL FOCUS — CRITICAL:\n"
            "- [TASK] shows your CURRENT GOAL. Focus ONLY on that goal.\n"
            "- You MUST use browser tools (navigate, click, type, open_link)\n"
            "  to complete each goal. Do NOT answer from your training data.\n"
            "  The user wants real, current information from actual websites.\n"
            "- FINISH the current goal completely before moving on.\n"
            "- When the current goal is DONE (after performing browser actions),\n"
            "  respond with a brief TEXT summary of what you found/did. The\n"
            "  system will then give you the next goal.\n"
            "- Do NOT take actions for later goals — they are shown only\n"
            "  for context so you know what comes next.\n"
            "- When the LAST goal is done, respond with a full TEXT summary\n"
            "  of everything you accomplished across all goals.\n"
            "- Your full conversation history is preserved — reference info\n"
            "  from earlier goals when working on later ones.\n\n"
            "RULES:\n"
            "- ONLY perform actions the user EXPLICITLY asked for.\n"
            "- Execute exactly ONE tool call per turn.\n"
            "- NEVER guess deep URLs. Navigate to homepages first.\n"
            "- If a page_error was returned, go to the homepage instead.\n"
            "- If ALL goals are complete, give a brief final summary.\n"
            "- If AgentTrust blocks an action (denied/step-up), explain and stop.\n"
            "- If the same action fails 2+ times, try a DIFFERENT approach.\n"
            "- Keep text replies short and action-oriented.\n"
            "- If you are ALREADY on a page with what you need, do NOT navigate away.\n\n"
            "EFFICIENCY — SPEED IS CRITICAL:\n"
            "- Do NOT call get_saved_credentials or auto_login unless you are about\n"
            "  to log in AND you can see login fields on the page.\n"
            "- Do NOT repeat actions that already succeeded in earlier turns.\n"
            "- When reading a page, read it ONCE and move on. Do not\n"
            "  re-observe the same page multiple times.\n"
            "- MINIMIZE TABS: Do NOT open a new tab for every site. Use\n"
            "  open_link to navigate the CURRENT tab. Only use open_new_tab\n"
            "  when you need to compare two pages side-by-side.\n"
            "- MINIMIZE PAGE VISITS: For research, visit 2-3 pages total.\n"
            "  Read the Content section — it often has what you need. If it\n"
            "  does, summarize and move on. Do NOT visit 5+ pages.\n"
            "- ABANDON BROKEN PAGES: if a click or action fails on a page,\n"
            "  do NOT scroll-and-retry on the same page. Instead:\n"
            "  1. Try open_link to a direct URL if you have one, OR\n"
            "  2. Navigate to a DIFFERENT site entirely.\n"
            "- Do NOT scroll just to look around. Only scroll when you need\n"
            "  specific content that is below the fold.\n"
            "- When the current goal is DONE, immediately produce a text\n"
            "  summary so the system advances to the next goal. Do NOT\n"
            "  keep browsing after you have enough information.\n\n"
            "ROUTINES:\n"
            "- Users can save and replay browser action sequences as routines.\n"
            "- After a routine finishes, continue from the current browser state.\n"
            + observation
        )

        # Assemble messages
        messages = [{"role": "system", "content": system_prompt}]
        for msg in state.get("conversation_history") or []:
            messages.append(msg)
        messages.append({"role": "user", "content": state["user_request"]})
        for msg in state.get("turn_messages") or []:
            messages.append(msg)

        # Build tools list — exclude observation tools (observe node handles them)
        tools = agent._build_tools()
        tools = [
            t
            for t in tools
            if t.get("function", {}).get("name")
            not in ("get_page_content", "get_visible_elements", "get_current_url")
        ]

        response = agent._chat_completion(
            model=agent.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # Serialize assistant message for turn_messages
        assistant_msg = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        new_turn = list(state.get("turn_messages") or []) + [assistant_msg]

        if message.tool_calls:
            # Limit to ONE tool call per cycle
            tc = message.tool_calls[0]
            pending = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            ]

            # If LLM returned extra tool calls, send dummy responses so
            # OpenAI doesn't complain about missing tool results
            extra_msgs = []
            for extra_tc in message.tool_calls[1:]:
                extra_msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": extra_tc.id,
                        "name": extra_tc.function.name,
                        "content": json.dumps(
                            {
                                "skipped": True,
                                "message": "One action per turn. Will handle next cycle.",
                            }
                        ),
                    }
                )

            print(f"  ACT: {tc.function.name}")
            return {
                "turn_messages": new_turn + extra_msgs,
                "pending_tool_calls": pending,
                "action_category": "none",
            }
        else:
            # LLM returned text — task is complete
            text = (message.content or "")[:120]
            print(f"  AGENT: {text}")
            return {
                "turn_messages": new_turn,
                "pending_tool_calls": [],
                "final_response": message.content or "",
                "action_category": "none",
            }

    # ================================================================== #
    #  TOOLS node — execute pending tool calls                            #
    # ================================================================== #
    def tools_node(state: AgentState) -> dict:
        """Execute pending tool calls through the parent agent's handler."""

        pending = state.get("pending_tool_calls") or []
        new_turn = list(state.get("turn_messages") or [])
        last_result = {}
        last_name = ""
        category = "none"
        _gh_repos_update = None

        for tc in pending:
            name = tc["name"]
            last_name = name

            # Classify action
            if name in MUTATING_ACTIONS:
                category = "mutating"
            elif name in READ_ONLY_ACTIONS:
                category = "read_only"
            else:
                category = "read_only"

            # Block clicks with empty/N/A targets — always fail, waste time
            if name == "agenttrust_browser_action":
                try:
                    _args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    _target = _args.get("target") or {}
                    _target_text = (_target.get("text") or "").strip()
                    _has_id = bool(_target.get("id") or _target.get("href")
                                   or _target.get("aria-label") or _target.get("aria_label")
                                   or _target.get("name"))
                    if not _has_id and (not _target_text or _target_text.lower() == "n/a"):
                        print(f"  BLOCKED: click with empty target — read the page content instead")
                        new_turn.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": name,
                            "content": json.dumps({
                                "success": False,
                                "error": "Click target is empty/N/A. Look at the page Content "
                                         "in the observation — the information you need may "
                                         "already be there. If you need to click something, "
                                         "specify a real element from the Interactive elements list."
                            }),
                        })
                        last_result = {"success": False, "error": "empty target blocked"}
                        category = "read_only"
                        continue
                except Exception:
                    pass

            # Block auto-login when the user never asked to sign in.
            if name in ("get_saved_credentials", "auto_login"):
                _user_req_login = (state.get("user_request") or "").lower()
                _login_kw = {"sign in", "signin", "log in", "login",
                             "sign-in", "log-in", "authenticate",
                             "use my account", "my account"}
                if not any(w in _user_req_login for w in _login_kw):
                    msg = (
                        "Login was not requested by the user. Do NOT attempt "
                        "to sign in unless the user explicitly asks. Most "
                        "sites allow browsing and searching without an account. "
                        "Navigate to the site's main page instead."
                    )
                    print(f"  BLOCKED: {name} — user did not request login")
                    new_turn.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": name,
                        "content": json.dumps({"success": False, "error": msg}),
                    })
                    last_result = {"success": False, "error": msg}
                    category = "read_only"
                    continue

            # Goal-relevance guard for call_external_api: block API calls
            # whose provider doesn't match the current goal to prevent the
            # agent from jumping ahead to later goals.
            if name == "call_external_api":
                try:
                    _api_check = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    _api_prov = (_api_check.get("provider") or "").lower()
                    _api_endpoint = (_api_check.get("endpoint") or _api_check.get("url") or "").lower()
                    _goal_idx = state.get("current_goal_index", 0)
                    _goals = state.get("sub_goals") or []
                    _cur_goal = (_goals[_goal_idx] if _goal_idx < len(_goals) else "").lower()

                    _PROVIDER_KEYWORDS = {
                        "github": ["github"],
                        "google-oauth2": ["google calendar", "calendar event"],
                        "slack": ["slack"],
                        "windowslive": ["microsoft", "outlook", "onedrive", "todo"],
                        "notion": ["notion"],
                    }
                    _goal_providers = set()
                    for prov, kws in _PROVIDER_KEYWORDS.items():
                        if any(kw in _cur_goal for kw in kws):
                            _goal_providers.add(prov)

                    # Determine what provider this API call targets
                    if "github" in _api_endpoint:
                        _calling_provider = "github"
                    elif "slack" in _api_endpoint:
                        _calling_provider = "slack"
                    elif "googleapis" in _api_endpoint or "calendar" in _api_endpoint:
                        _calling_provider = "google-oauth2"
                    elif "graph.microsoft" in _api_endpoint:
                        _calling_provider = "windowslive"
                    elif "notion" in _api_endpoint:
                        _calling_provider = "notion"
                    else:
                        _calling_provider = _api_prov

                    # If goal mentions specific providers → only allow those.
                    # If goal has NO provider keywords (e.g. research/browse goal)
                    # → block ALL API calls; they belong to a later goal.
                    _goal_mentions_api = "call_external_api" in _cur_goal or "api" in _cur_goal
                    if _goal_providers and _calling_provider not in _goal_providers:
                        _should_block = True
                    elif not _goal_providers and not _goal_mentions_api:
                        _should_block = True
                    else:
                        _should_block = False

                    if _should_block:
                        _block_msg = (
                            f"This API call ({_calling_provider}) does not match the current "
                            f"goal: '{_goals[_goal_idx][:80]}'. Complete the current goal "
                            f"first by responding with a text summary, then the system will "
                            f"advance you to the next goal where you can make this call."
                        )
                        print(f"  BLOCKED: {name} ({_calling_provider}) — wrong goal ({_goal_idx + 1}/{len(_goals)})")
                        new_turn.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": name,
                            "content": json.dumps({"success": False, "error": _block_msg}),
                        })
                        last_result = {"success": False, "error": _block_msg}
                        category = "read_only"
                        continue
                except Exception:
                    pass

            # Rewrite Google Images URLs → Google web search.
            # Also rewrite GitHub tab URLs → repo root.
            # open_link uses "href"; others use "url".
            _tc_args = tc["arguments"]
            if name in ("open_link", "agenttrust_browser_action", "open_new_tab"):
                try:
                    _parsed = json.loads(_tc_args) if _tc_args else {}
                    _google_web = "https://www.google.com/webhp?hl=en"
                    _rewritten = False
                    for _key in ("url", "href"):
                        _val = _parsed.get(_key, "")
                        if not _val:
                            continue
                        if ("google.com/imghp" in _val
                                or "images.google.com" in _val):
                            print(f"  REWRITE: {_val} → {_google_web}")
                            _parsed[_key] = _google_web
                            _rewritten = True
                        elif (_val.rstrip("/") in (
                                "https://www.google.com",
                                "http://www.google.com",
                                "https://google.com",
                                "http://google.com")
                              or _val.startswith("https://www.google.com/?")
                              or _val.startswith("https://www.google.com?")
                        ):
                            _parsed[_key] = _google_web
                            _rewritten = True

                        # GitHub: strip tab suffixes to navigate to repo root.
                        _gh_tab = re.match(
                            r"(https?://github\.com/[^/]+/[^/]+)"
                            r"/(actions|issues|pulls|projects|wiki|settings|"
                            r"security|pulse|graphs|packages|releases|deployments)"
                            r"(/.*)?$",
                            _val
                        )
                        if _gh_tab:
                            _repo_root = _gh_tab.group(1)
                            print(f"  REWRITE: {_val} → {_repo_root}")
                            _parsed[_key] = _repo_root
                            _rewritten = True

                        # Generic sign-in redirect: if the URL contains a
                        # login/signin path and the user didn't ask to log
                        # in, strip it back to the site root.
                        _user_req = (state.get("user_request") or "").lower()
                        _login_words = {"sign in", "signin", "log in", "login",
                                        "sign-in", "log-in", "authenticate",
                                        "use my account"}
                        _user_wants_login = any(w in _user_req for w in _login_words)
                        if not _user_wants_login and not _rewritten:
                            from urllib.parse import urlparse as _urlparse
                            try:
                                _pu = _urlparse(_val)
                                _path_lower = _pu.path.lower()
                                _host = _pu.netloc.lower()
                                _LOGIN_PATH_FRAGMENTS = (
                                    "/signin", "/sign-in", "/sign_in",
                                    "/login", "/log-in", "/log_in",
                                    "/ap/signin", "/accounts/login",
                                    "/auth/", "/sso/", "/oauth/",
                                    "/i/flow/login",
                                )
                                _is_login_subdomain = _host.startswith("signin.") or _host.startswith("login.") or _host.startswith("auth.")
                                _is_login_path = any(frag in _path_lower for frag in _LOGIN_PATH_FRAGMENTS)
                                if _is_login_subdomain or _is_login_path:
                                    _main = f"{_pu.scheme}://{_pu.netloc}"
                                    if _is_login_subdomain:
                                        _main = f"{_pu.scheme}://www.{_host.split('.', 1)[1]}"
                                    print(f"  REWRITE (skip login): {_val[:80]} → {_main}")
                                    _parsed[_key] = _main
                                    _rewritten = True
                            except Exception:
                                pass
                    if _rewritten:
                        _tc_args = json.dumps(_parsed)
                except Exception:
                    pass

            # ── GitHub repo auto-fix for call_external_api ──
            # If the agent is about to POST to /repos/{owner}/{repo}/issues
            # but we have cached repos from a prior GET, validate and fix the
            # owner/repo path before executing.
            # NOTE: the LLM sends "endpoint" (not "url") for this tool.
            if name == "call_external_api":
                try:
                    _api_args = json.loads(_tc_args) if _tc_args else {}
                    _ep_key = "endpoint" if "endpoint" in _api_args else "url"
                    _api_url = (_api_args.get(_ep_key) or "").lower()
                    _api_method = (_api_args.get("method") or "GET").upper()

                    # Fix POST to wrong repo path
                    if _api_method == "POST" and "api.github.com/repos/" in _api_url and "/issues" in _api_url:
                        cached = state.get("github_repos") or []
                        if cached:
                            _user_req_lower = (state.get("user_request") or "").lower()
                            _url_parts = _api_url.split("api.github.com/repos/")[1]
                            _attempted_repo = _url_parts.split("/issues")[0]
                            repo_names = [r["full_name"] for r in cached]
                            if _attempted_repo not in [r.lower() for r in repo_names]:
                                best = None
                                for r in cached:
                                    if r["name"].lower() in _user_req_lower or r["full_name"].lower() in _user_req_lower:
                                        best = r["full_name"]
                                        break
                                if not best and cached:
                                    for r in cached:
                                        if "agenttrust" in r["name"].lower() or "agent-trust" in r["name"].lower() or "agent_trust" in r["name"].lower():
                                            best = r["full_name"]
                                            break
                                if best:
                                    _orig_url = _api_args[_ep_key]
                                    _fixed_url = _orig_url.split("api.github.com/repos/")[0] + f"api.github.com/repos/{best}/issues"
                                    print(f"  GITHUB FIX: {_orig_url} → {_fixed_url}")
                                    _api_args[_ep_key] = _fixed_url
                                    _tc_args = json.dumps(_api_args)
                except Exception:
                    pass

            # Execute via parent agent's existing handler
            fc = type("FC", (), {"name": name, "arguments": _tc_args})()
            result = agent.handle_function_call(fc)
            last_result = result if isinstance(result, dict) else {"result": result}

            # Cache GitHub repos from GET /user/repos response
            if name == "call_external_api":
                try:
                    _api_args2 = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    _url2 = (_api_args2.get("endpoint") or _api_args2.get("url") or "")
                    if "api.github.com/user/repos" in _url2 and isinstance(result, dict):
                        _data = result.get("data") or result.get("result")
                        if isinstance(_data, list):
                            _gh_repos_update = [
                                {"full_name": r.get("full_name", ""), "name": r.get("name", ""), "owner": (r.get("owner") or {}).get("login", "")}
                                for r in _data if isinstance(r, dict) and r.get("full_name")
                            ]
                            if _gh_repos_update:
                                print(f"  GITHUB CACHE: {len(_gh_repos_update)} repos discovered")
                except Exception:
                    pass

            # Check for fatal connectivity errors
            err_type = None
            if isinstance(result, dict):
                err_type = result.get("error_type")
                if not err_type and isinstance(result.get("browser_result"), dict):
                    err_type = result["browser_result"].get("error_type")
            if err_type in ("auth0", "backend"):
                print(f"\n  CONNECTIVITY ERROR: {last_result.get('message', '')}")
                last_result = {
                    "status": "error",
                    "error_type": err_type,
                    "message": "System connectivity error. Check backend and Auth0.",
                }

            new_turn.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": json.dumps(result, default=str),
                }
            )

        total = state.get("total_actions", 0) + (1 if category == "mutating" else 0)

        # Track recent action signatures for loop detection
        recent = list(state.get("recent_actions") or [])
        if last_name:
            args_str = pending[0]["arguments"] if pending else ""
            sig = f"{last_name}:{args_str[:100]}"
            recent.append(sig)
            if len(recent) > 10:
                recent = recent[-10:]

        # Build a human-readable description for the progress UI
        _act_desc = last_name
        if last_name == "open_link":
            try:
                _a = json.loads(pending[0]["arguments"]) if pending else {}
                _href = _a.get("href", "")
                if _href:
                    from urllib.parse import urlparse as _act_up
                    _act_desc = f"Opening {_act_up(_href).hostname or _href[:40]}"
            except Exception:
                pass
        elif last_name == "open_new_tab":
            try:
                _a = json.loads(pending[0]["arguments"]) if pending else {}
                _lbl = _a.get("label", "") or _a.get("url", "")[:40]
                _act_desc = f"New tab: {_lbl}"
            except Exception:
                pass
        elif last_name == "type_text":
            _act_desc = "Typing into field"
        elif last_name == "call_external_api":
            try:
                _a = json.loads(pending[0]["arguments"]) if pending else {}
                _p = _a.get("provider", "")
                _m = _a.get("method", "GET")
                _act_desc = f"API call: {_m} {_p}"
            except Exception:
                pass
        elif last_name == "scroll_page":
            _act_desc = "Scrolling page"
        elif last_name == "agenttrust_browser_action":
            try:
                _a = json.loads(pending[0]["arguments"]) if pending else {}
                _tgt = (_a.get("target") or {}).get("text", "")[:30]
                _act_desc = f"Clicking {_tgt}" if _tgt else "Clicking element"
            except Exception:
                pass
        elif last_name == "go_back":
            _act_desc = "Going back"
        elif last_name == "get_saved_credentials":
            _act_desc = "Checking credentials"

        progress = _emit_progress(state, f"ACT|{_act_desc}")

        ret = {
            "turn_messages": new_turn,
            "pending_tool_calls": [],
            "last_action_result": last_result,
            "last_action_name": last_name,
            "action_category": category,
            "total_actions": total,
            "recent_actions": recent,
            "progress_lines": progress,
        }
        if _gh_repos_update:
            ret["github_repos"] = _gh_repos_update
        return ret

    # ================================================================== #
    #  VERIFY node — check action result, track failures                  #
    # ================================================================== #
    def verify_node(state: AgentState) -> dict:
        """Check if the last action succeeded. Update failure tracking.

        Uses three layers of verification:
        1. Tool result status (AgentTrust allowed/denied)
        2. Tool result success flag (browser operation outcome)
        3. Vision analysis for critical actions (catches page-level errors
           like 'incorrect password' that the tool thinks succeeded)
        """

        result = state.get("last_action_result") or {}
        status = result.get("status", "")

        # Step-up required → halt and inform user
        if status == "step_up_required":
            return {
                "needs_step_up": True,
                "step_up_message": result.get(
                    "message", "Action requires user approval"
                ),
            }

        # Determine success / failure
        browser_result = result.get("browser_result", {})
        failed = False
        fail_reason = ""

        if status in ("denied", "error"):
            failed = True
            fail_reason = result.get("message", status)
        elif isinstance(browser_result, dict) and not browser_result.get(
            "success", True
        ):
            failed = True
            fail_reason = browser_result.get("message", "browser action failed")
        # Catch top-level {success: false} from API calls and other tools
        # that don't nest results inside browser_result
        elif result.get("success") is False:
            failed = True
            fail_reason = result.get("error") or result.get("message") or "action returned success=false"
        # Catch HTTP error status codes (e.g. 401, 403, 500) returned as integers
        elif isinstance(status, int) and status >= 400:
            failed = True
            fail_reason = result.get("error") or f"HTTP {status}"

        # Check for login_error from auto_login post-verification
        if not failed and result.get("login_error"):
            failed = True
            fail_reason = result["login_error"]

        # Detect repetitive action loops.
        # scroll_page gets a higher threshold (6) since reading long pages is normal.
        recent = state.get("recent_actions") or []
        action_name = state.get("last_action_name", "")
        if not failed and len(recent) >= 3:
            last_sig = recent[-1] if recent else ""
            if action_name == "scroll_page":
                repeat_count = sum(1 for s in recent if s == last_sig)
                threshold = 6
            else:
                repeat_count = sum(1 for s in recent[-4:] if s == last_sig)
                threshold = 3
            if repeat_count >= threshold:
                failed = True
                fail_reason = f"Repeated same action {repeat_count} times — likely stuck in a loop"

        consecutive = state.get("consecutive_failures", 0)
        _verify_progress = {}
        if failed:
            consecutive += 1
            print(
                f"  VERIFY: FAILED (#{consecutive}/{MAX_CONSECUTIVE_FAILS}) — {fail_reason[:100]}"
            )
            progress = _emit_progress(state, f"VERIFY|Failed: {fail_reason[:60]}")
            _verify_progress["progress_lines"] = progress
        else:
            name = state.get("last_action_name", "action")
            if name in PROGRESS_ACTIONS:
                consecutive = 0
            print(f"  VERIFY: OK ({name})")

        return {
            "consecutive_failures": consecutive,
            **_verify_progress,
        }

    # ================================================================== #
    #  ADVANCE GOAL node — move to next sub-goal, preserve context        #
    # ================================================================== #
    def advance_goal_node(state: AgentState) -> dict:
        """Increment goal index without clearing conversation history.

        If the agent hasn't performed any browser actions for the current
        goal (recent_actions is empty), refuse to advance and inject a
        nudge so the agent actually uses the browser.
        """
        goal_idx = state.get("current_goal_index", 0)
        recent = state.get("recent_actions") or []
        sub_goals = state.get("sub_goals") or []

        is_last_goal = (goal_idx + 1 >= len(sub_goals))
        prior_had_actions = state.get("total_actions", 0) > 0

        # Allow text-only completion when: (a) last goal with prior
        # actions, or (b) user explicitly asks to use existing page data.
        _user_req = (state.get("user_request") or "").lower()
        _analysis_keywords = {"use the info", "use the information", "just use",
                              "from the page", "on the page", "already on",
                              "summarize", "summarise", "analyze", "analyse",
                              "extract", "what do you see", "read the page"}
        _user_wants_analysis = any(kw in _user_req for kw in _analysis_keywords)

        if not recent and goal_idx < len(sub_goals):
            if _user_wants_analysis:
                print(f"  ANALYSIS PASS: user requested page analysis — allowing text-only completion")
            elif is_last_goal and prior_had_actions:
                print(f"  LAST-GOAL PASS: allowing text-only completion "
                      f"(prior actions: {state.get('total_actions', 0)})")
            else:
                current_goal = sub_goals[goal_idx]
                print(f"  NO-ACTION GUARD: agent tried to complete "
                      f"'{current_goal[:50]}' without any browser actions — retrying")
                new_turn = list(state.get("turn_messages") or [])
                new_turn.append({
                    "role": "user",
                    "content": (
                        "You have not performed any browser actions for this goal. "
                        "You MUST use at least one browser tool (scroll_page to read, "
                        "open_link, type_text, click, call_external_api) before "
                        "completing a goal. If you are already on the right page, "
                        "scroll down to read the content. "
                        f"Current goal: {current_goal}"
                    ),
                })
                return {
                    "turn_messages": new_turn,
                    "consecutive_failures": 0,
                    "final_response": "",
                }

        done_goal = sub_goals[min(goal_idx, len(sub_goals) - 1)]
        next_idx = goal_idx + 1
        next_goal = sub_goals[min(next_idx, len(sub_goals) - 1)]
        print(f"  GOAL {goal_idx + 1} DONE: '{done_goal[:60]}'")
        print(f"  NEXT GOAL {next_idx + 1}: '{next_goal[:60]}'")

        progress = _emit_progress(
            state,
            f"GOAL|Step {goal_idx + 1} of {len(sub_goals)} complete"
        )

        return {
            "current_goal_index": next_idx,
            "consecutive_failures": 0,
            "recent_actions": [],
            "final_response": "",
            "progress_lines": progress,
        }

    # ================================================================== #
    #  RESPOND node — produce final output                                #
    # ================================================================== #
    def respond_node(state: AgentState) -> dict:
        """Generate or pass through the final response."""

        # Emit a final "Done" progress line
        _emit_progress(state, "DONE|Done")

        # If agent_node already produced a text response, use it
        if state.get("final_response"):
            return {}

        if state.get("needs_step_up"):
            return {
                "final_response": (
                    f"This action requires additional approval: "
                    f"{state.get('step_up_message', 'Step-up authentication needed')}. "
                    "Please approve the action and try again."
                ),
            }

        if state.get("consecutive_failures", 0) >= MAX_CONSECUTIVE_FAILS:
            return {
                "final_response": (
                    "I encountered repeated failures trying to complete this task. "
                    f"Last action: {state.get('last_action_name', 'unknown')}. "
                    "Please check the browser state and try again with a "
                    "different approach."
                ),
            }

        if state.get("total_actions", 0) >= MAX_ACTIONS:
            return {
                "final_response": (
                    "I reached the maximum number of actions for this request. "
                    "The task may be partially complete."
                ),
            }

        return {"final_response": "Task completed."}

    # ================================================================== #
    #  Routing functions                                                  #
    # ================================================================== #
    def route_after_agent(state: AgentState) -> str:
        """After the LLM call: execute tools, advance goal, or respond."""
        if state.get("pending_tool_calls"):
            return "tools"
        # Agent returned text — check if there are more goals
        goal_idx = state.get("current_goal_index", 0)
        sub_goals = state.get("sub_goals") or []
        if goal_idx + 1 < len(sub_goals):
            return "advance_goal"
        return "respond"

    def route_after_verify(state: AgentState) -> str:
        """After verification: re-observe, continue acting, or respond."""
        if state.get("needs_step_up"):
            return "respond"

        if state.get("consecutive_failures", 0) >= MAX_CONSECUTIVE_FAILS:
            return "respond"

        if state.get("total_actions", 0) >= MAX_ACTIONS:
            return "respond"

        if state.get("action_category") == "mutating":
            return "observe"

        return "agent"

    # ================================================================== #
    #  Assemble the graph                                                 #
    # ================================================================== #
    graph = StateGraph(AgentState)

    graph.add_node("plan", plan_node)
    graph.add_node("observe", observe_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("verify", verify_node)
    graph.add_node("advance_goal", advance_goal_node)
    graph.add_node("respond", respond_node)

    # Entry: always start with planning
    graph.set_entry_point("plan")

    # plan → observe (if browser actions needed) or respond (if chat only)
    def route_after_plan(state: AgentState) -> str:
        """Skip the action pipeline when no browser actions are needed."""
        if state.get("final_response"):
            return "respond"
        return "observe"

    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {"observe": "observe", "respond": "respond"},
    )

    # observe → agent (LLM sees fresh page state)
    graph.add_edge("observe", "agent")

    # agent → tools | advance_goal (text + more goals) | respond (text + last goal)
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "advance_goal": "advance_goal", "respond": "respond"},
    )

    # tools → verify (always check results)
    graph.add_edge("tools", "verify")

    # verify → observe | agent | respond
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"observe": "observe", "agent": "agent", "respond": "respond"},
    )

    # advance_goal → observe (re-read page for the next goal)
    graph.add_edge("advance_goal", "observe")

    # respond → END
    graph.add_edge("respond", END)

    return graph.compile()
