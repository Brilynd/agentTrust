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

    # --- Turn messages (OpenAI API) ---
    turn_messages: list               # Tool call/result pairs this turn
    pending_tool_calls: list          # Tool calls awaiting execution

    # --- Action tracking ---
    last_action_result: dict
    last_action_name: str
    action_category: str              # "mutating" | "read_only" | "none"
    consecutive_failures: int
    total_actions: int

    # --- Output ---
    final_response: str

    # --- Control ---
    needs_step_up: bool
    step_up_message: str


# Actions that change page state → require re-observation
MUTATING_ACTIONS = {
    "agenttrust_browser_action",
    "open_link",
    "type_text",
    "auto_login",
    "go_back",
    "go_forward",
}

# Read-only actions → agent can continue without re-observing
READ_ONLY_ACTIONS = {
    "get_saved_credentials",
    "wait_for_element",
    "scroll_page",
    "call_external_api",
}

MAX_ACTIONS = 25
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
    #  PLAN node                                                          #
    # ================================================================== #
    def plan_node(state: AgentState) -> dict:
        """Use the LLM to decompose the user request into sub-goals.

        First classifies whether the request actually needs browser
        automation.  If not (e.g. casual chat, general questions),
        produce a plain-text answer and skip the action pipeline.
        """

        # ---- Intent gate: does the request need browser actions? ----
        req = state["user_request"]
        try:
            gate_resp = agent._chat_completion(
                model=agent.model,
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
                            "  CHAT     — if it can be answered with text alone\n"
                        ),
                    },
                    {"role": "user", "content": req},
                ],
                temperature=0,
            )
            intent = (gate_resp.choices[0].message.content or "").strip().upper()
        except Exception:
            intent = "BROWSER"  # default to browser on error

        if intent.startswith("CHAT"):
            # No browser needed — answer conversationally
            try:
                chat_resp = agent._chat_completion(
                    model=agent.model,
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

        plan_prompt = (
            "Break down this user request into 2-6 concrete sub-goals for "
            "browser automation. Each sub-goal should be ONE action or a small "
            "related group (e.g. typing + pressing enter).\n"
            "Return ONLY a JSON array of strings — no commentary.\n\n"
            f"User request: {state['user_request']}{browser_ctx}\n\n"
            "Example: [\"Navigate to amazon.com\", \"Search for 'wireless "
            "headphones'\", \"Click the first result\", \"Add to cart\"]\n"
            + (rag_context + "\n" if rag_context else "")
            + (cred_hint if cred_hint else "") +
            "\nJSON array:"
        )

        try:
            response = agent._chat_completion(
                model=agent.model,
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
        }

    # ================================================================== #
    #  OBSERVE node                                                       #
    # ================================================================== #
    def observe_node(state: AgentState) -> dict:
        """Read current browser state. Pure function — no LLM call."""
        executor = agent.browser_executor

        url = ""
        title = ""
        text = ""
        elements = []

        if executor.browser:
            try:
                url = executor.get_current_url() or ""
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

        label = url[:80] if url else "(no page loaded)"
        print(f"  OBSERVE: {label}")

        return {
            "current_url": url,
            "page_title": title,
            "page_text": text,
            "visible_elements": elements,
        }

    # ================================================================== #
    #  AGENT node — LLM decides the next action                           #
    # ================================================================== #
    def agent_node(state: AgentState) -> dict:
        """Call the LLM with current context and available tools."""

        # Current goal
        goal_idx = state.get("current_goal_index", 0)
        sub_goals = state.get("sub_goals", [])
        current_goal = (
            sub_goals[goal_idx] if goal_idx < len(sub_goals) else "Complete the task"
        )
        remaining = sub_goals[goal_idx + 1 :] if goal_idx + 1 < len(sub_goals) else []

        # Format visible elements compactly
        elements_str = ""
        if state.get("visible_elements"):
            els = state["visible_elements"][:25]
            elements_str = json.dumps(els, separators=(",", ":"))

        observation = (
            f"\n[PAGE STATE]\n"
            f"URL: {state.get('current_url', 'not loaded')}\n"
            f"Title: {state.get('page_title', '')}\n"
            f"Content (truncated):\n{state.get('page_text', '')[:2000]}\n\n"
            f"Interactive elements:\n{elements_str}\n\n"
            f"[TASK PROGRESS]\n"
            f"Plan:\n{state.get('plan_text', '')}\n"
            f"Current goal ({goal_idx + 1}/{len(sub_goals)}): {current_goal}\n"
            f"Remaining goals: {remaining if remaining else '(this is the last goal)'}\n"
            f"Actions used: {state.get('total_actions', 0)}/{MAX_ACTIONS}\n"
        )

        system_prompt = (
            "You are a browser automation agent with FULL control of a real browser.\n"
            "You perform tasks by actually navigating, clicking, typing, and reading.\n\n"
            "WORKFLOW — follow strictly:\n"
            "1. LOOK at the page state provided below.\n"
            "2. Pick ONE tool call that advances the current goal.\n"
            "3. Use the most SPECIFIC element identifier available:\n"
            "   id > href > aria-label > text.\n"
            "4. Fill target objects completely (id, text, href, tagName, etc.).\n\n"
            "RULES:\n"
            "- ONLY perform actions the user EXPLICITLY asked for. Do NOT\n"
            "  browse, search, or navigate on your own initiative.\n"
            "- If the user did not ask you to go to a website or perform a\n"
            "  specific browser action, reply with text only — no tool calls.\n"
            "- Execute exactly ONE tool call per turn.\n"
            "- NEVER guess deep URLs (e.g. /ap/signin). Navigate to homepages\n"
            "  first, then find and click links.\n"
            "- If a page_error was returned, the URL is wrong. Go to the homepage.\n"
            "- If login is needed: call get_saved_credentials first, then auto_login.\n"
            "- If the current goal is COMPLETE based on the page state, respond\n"
            "  with text saying the goal is done. Do NOT call another tool.\n"
            "- If ALL goals are complete, give a brief final summary.\n"
            "- If AgentTrust blocks an action (denied/step-up), explain and stop.\n"
            "- If the same action keeps failing, try a DIFFERENT approach.\n"
            "- For GitHub/Google/Slack/Microsoft, prefer call_external_api.\n"
            "- Keep text replies short and action-oriented.\n"
            "- If you are ALREADY on a page with the content you need, do NOT\n"
            "  navigate away. Work with the current page.\n\n"
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
            # LLM returned text — current goal may be complete
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

            # Execute via parent agent's existing handler
            fc = type("FC", (), {"name": name, "arguments": tc["arguments"]})()
            result = agent.handle_function_call(fc)
            last_result = result if isinstance(result, dict) else {"result": result}

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

        return {
            "turn_messages": new_turn,
            "pending_tool_calls": [],
            "last_action_result": last_result,
            "last_action_name": last_name,
            "action_category": category,
            "total_actions": total,
        }

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

        # Check for login_error from auto_login post-verification
        if not failed and result.get("login_error"):
            failed = True
            fail_reason = result["login_error"]

        consecutive = state.get("consecutive_failures", 0)
        if failed:
            consecutive += 1
            print(
                f"  VERIFY: FAILED (#{consecutive}/{MAX_CONSECUTIVE_FAILS}) — {fail_reason[:100]}"
            )
        else:
            consecutive = 0
            name = state.get("last_action_name", "action")
            print(f"  VERIFY: OK ({name})")

        return {
            "consecutive_failures": consecutive,
        }

    # ================================================================== #
    #  RESPOND node — produce final output                                #
    # ================================================================== #
    def respond_node(state: AgentState) -> dict:
        """Generate or pass through the final response."""

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
        """After the LLM call: execute tools or go straight to respond."""
        if state.get("pending_tool_calls"):
            return "tools"
        return "respond"

    def route_after_verify(state: AgentState) -> str:
        """After verification: re-observe, continue acting, or respond."""
        # Step-up required → respond to inform the user
        if state.get("needs_step_up"):
            return "respond"

        # Too many consecutive failures → stop
        if state.get("consecutive_failures", 0) >= MAX_CONSECUTIVE_FAILS:
            return "respond"

        # Hit the action budget → stop
        if state.get("total_actions", 0) >= MAX_ACTIONS:
            return "respond"

        # After a mutating action → re-observe the page
        if state.get("action_category") == "mutating":
            return "observe"

        # After a read-only action → let the agent decide next
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

    # agent → tools (if tool calls) or respond (if text)
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "respond": "respond"},
    )

    # tools → verify (always check results)
    graph.add_edge("tools", "verify")

    # verify → observe (re-read page) | agent (continue) | respond (stop)
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"observe": "observe", "agent": "agent", "respond": "respond"},
    )

    # respond → END
    graph.add_edge("respond", END)

    return graph.compile()
