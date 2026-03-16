## Inspiration

Every week there's a new AI agent demo — booking flights, filing taxes, managing calendars. They're impressive until you ask one question: **who authorized that?** Today's AI agents either operate in sandboxes too restrictive to be useful, or they're given unrestricted access to real accounts with zero accountability. There's no identity layer, no policy enforcement, no audit trail. If an agent clicks "confirm purchase" on your behalf, there's no cryptographic proof of what happened, why, or who approved it.

We built AgentTrust because we believe autonomous agents will never leave the demo stage until they have a trust infrastructure as rigorous as what humans rely on — authentication, authorization, and audit. Auth0 already solved this problem for human users. We wanted to extend that same trust model to AI agents acting on a user's behalf.

## What it does

AgentTrust is the identity, policy, and audit layer that sits between an AI agent and the browser. Every single browser action — click, navigation, form submission — must pass through AgentTrust validation **before** it executes. There is no bypass.

- **Identity-bound execution**: Every action carries an Auth0 M2M JWT. The agent authenticates as a machine client, not a user, creating a clear separation of identity.
- **Pre-execution risk classification**: A policy engine scores every action across domain sensitivity, keyword matching, URL patterns, and form field analysis. Actions are classified as low, medium, high, or blocked before they run.
- **Human-in-the-loop step-up approval**: High-risk actions (deleting a repo, submitting payment, transferring funds) trigger a real-time approval flow in the Chrome extension. The agent long-polls while the user approves or denies. Approvals auto-expire after 2 minutes.
- **Cryptographic audit trail**: Every action is linked in a SHA-256 hash chain — tamper with one record and the entire chain breaks. Each entry includes agent identity, risk level, session, and screenshot.
- **API-first external access**: For GitHub and Google Calendar, the agent calls APIs directly through Auth0's identity infrastructure (Management API token resolution with Token Vault fallback), bypassing the browser entirely.
- **Encrypted credential vault**: Saved login credentials are encrypted with AES-256-GCM with per-credential IVs. Passwords are used by the auto-login engine directly — they never enter the LLM context.
- **Chrome extension dashboard**: A Manifest V3 extension with Monitor, Chat, Routines, and Permissions tabs. Users see live action feeds, risk badges, screenshots, a conversational chat interface with a real-time thinking breakdown, and full control over policies and connected OAuth accounts.
- **CloudWatch integration**: All record types (actions, sessions, prompts, credentials, routines, connections) are streamed to AWS CloudWatch Logs for centralized monitoring alongside the RDS audit trail.

## How we built it

AgentTrust is three systems working together:

**Python Agent** — The AI brain. A LangGraph state machine orchestrates a structured pipeline: CLASSIFY (GPT-4.1-nano for intent), PLAN (GPT-4.1-mini for task decomposition), OBSERVE (Selenium page capture), ACT (GPT-4.1 for action selection), VERIFY (retry/advance logic). An `InterceptedWebDriver` wraps Selenium so every `.get()`, `.click()`, and `.send_keys()` call is intercepted and routed through AgentTrust validation. A TF-IDF-based action history RAG retrieves similar past tasks to improve planning consistency over time.

**Node.js Backend** — The trust layer. Express with a layered security middleware stack (Helmet, CORS, rate limiting, mongo-sanitize, HPP, input validation). Auth0 JWKS validation on every request. A policy engine classifies risk with a multi-signal scoring system. The audit service maintains a SHA-256 hash chain. Credentials are encrypted at rest with AES-256-GCM. CloudWatch Logs receives fire-and-forget structured records for every significant event. PostgreSQL on AWS RDS stores everything.

**Chrome Extension** — The user interface. Manifest V3 with a service worker, content scripts, and a popup dashboard. The Chat tab renders user prompts, a collapsible live thinking breakdown (updated via backend polling with DOM diffing to prevent flicker), and agent responses. The Permissions tab manages domains, keywords, saved credentials, and OAuth account connections (GitHub, Google) through Auth0's social login flows.

Key technology decisions:
- **Three-tier model architecture** — GPT-4.1 for complex reasoning, GPT-4.1-mini for planning and responses, GPT-4.1-nano for sub-millisecond intent classification. Cost-efficient without sacrificing quality where it matters.
- **Auth0 as the sole identity provider** — M2M tokens for the agent, user JWTs for the extension, Management API for provider token resolution, JWKS for validation. One identity backbone for everything.
- **LangGraph over a freeform ReAct loop** — Forced observation before every action, structured verification after every action, goal tracking with sub-task decomposition. Eliminated the wandering behavior typical of unconstrained agent loops.

## Challenges we ran into

**The agent kept going in circles.** Early on, the agent would navigate to a page, click back, navigate again, and repeat indefinitely. We solved this with multi-layered loop detection: tracking recent action signatures, capping consecutive failures at 3 per sub-goal, and adding programmatic URL rewriting guards (Google Images redirected to Web Search, login pages redirected to root).

**Step-up approval timing was fragile.** The agent would fire off an action, get a 403 requiring approval, but then immediately retry before the user had time to respond. We implemented long-polling with a 60-second timeout on the agent side and 2-minute auto-expiry on the backend, so the agent genuinely waits for human input.

**Live progress kept disappearing.** Showing real-time thinking in the extension sounds simple — poll the backend, render the steps. In practice, prompt IDs weren't propagating reliably across LangGraph nodes, HTTP ETag caching caused 304 responses with stale data, and replacing `innerHTML` every 3 seconds caused visible flicker. We fixed it by storing progress in a closure-level list outside LangGraph state, bypassing ETags on session endpoints, stripping screenshots from polling payloads to reduce size, and implementing DOM diffing so the UI only updates when content actually changes.

**External API token resolution was complex.** Getting the agent to call GitHub's API required extracting the user's `sub` claim from the Auth0 JWT, fetching the user profile via the Management API, pulling the provider access token from the `identities` array, and proxying the actual API call — all while sanitizing the response to ensure no tokens leak back to the LLM.

**The agent hallucinated search results.** When asked about current events, the intent classifier would categorize the request as "CHAT" (no browser needed) and the agent would fabricate an answer from its training data. We added real-time keyword detection (weather, today, latest, stock price, news) to force browser classification for anything requiring live information.

## Accomplishments that we're proud of

- **Zero-bypass enforcement.** The `InterceptedWebDriver` wrapper means there is genuinely no code path that can perform a browser action without AgentTrust validation. This isn't a suggestion or a middleware that can be skipped — it's structural.
- **The SHA-256 hash chain is real cryptography, not a checkbox.** Every action's hash depends on the previous action's hash. You can verify the entire chain at any time. Tamper with one record and every subsequent hash is invalid.
- **The multi-model pipeline actually saves money and time.** Intent classification with GPT-4.1-nano returns in milliseconds. Planning with GPT-4.1-mini is 4x cheaper than the full model. Only action selection uses GPT-4.1. A single task costs roughly 60-70% less than running everything through GPT-4.1.
- **The live thinking UI.** Watching the agent's reasoning steps appear in real-time in the extension — planning, observing, acting, verifying — makes the system feel transparent rather than opaque. You can see exactly what the agent is doing and why.
- **Auth0 as a complete identity backbone.** M2M authentication, JWKS validation, social connections, Management API token resolution, Token Vault fallback, step-up approval — all through one provider. Auth0 handles every trust decision in the system.

## What we learned

- **Trust is an infrastructure problem, not an AI problem.** The AI model doesn't need to be "more trustworthy" — it needs to operate within infrastructure that enforces trust externally. The same way a web app doesn't trust user input, an agent governance layer shouldn't trust agent decisions.
- **Structured agent pipelines beat freeform loops.** Moving from a while-loop ReAct agent to a LangGraph state machine with forced observation, verification, and goal tracking eliminated entire categories of bugs (loops, goal drift, skipped steps).
- **Identity separation matters.** Having the agent authenticate as a machine (M2M) while the human authenticates as a user means the agent can never approve its own high-risk actions. This separation is fundamental to the security model.
- **Browser automation is adversarial.** Websites actively fight automation — cookie banners, passkey dialogs, QR code popups, dynamic DOM changes. A production agent needs overlay dismissal, stale element recovery, multi-step login handling, and passkey suppression just to function on modern websites.
- **Payload size kills real-time UIs.** Screenshots in API responses were the single biggest cause of extension performance issues. Stripping them from polling endpoints and only including them on demand was the fix that made the live progress UI actually work smoothly.

## What's next for AgentTrust

- **More providers** — Expanding beyond GitHub and Google Calendar to Slack, Notion, Linear, Jira, and other tools teams use daily, all through Auth0's Connected Accounts and Token Vault.
- **Multi-agent governance** — Supporting multiple agents with different identity scopes operating in the same session, with cross-agent audit trails and policy enforcement.
- **Reinforcement learning from audit data** — Using the cryptographic audit trail as a training signal. Actions that were approved can reinforce good behavior; denied and step-up actions can train the agent to avoid risky patterns.
- **Policy templates and marketplace** — Pre-built policy configurations for common use cases (e-commerce browsing, financial research, social media management) so teams can deploy agents with appropriate guardrails out of the box.
- **Enterprise SSO and RBAC** — Integrating Auth0 Organizations for multi-tenant deployments where different teams have different agent permissions and approval workflows.
