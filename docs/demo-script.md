# AgentTrust 3-Minute Demo Script

**Speakers:** Brilynd + Thomas  
**Goal:** Sound like a pitch, not a technical review  
**Style:** Natural, confident, fast-moving, with clear handoffs

---

## 0:00 - 0:20 | Brilynd

"AI agents are powerful, but people still don't trust them. Once an agent has access, there's usually no identity layer, no policy enforcement, and no clear record of what it actually did.

That's what AgentTrust solves. We built the trust layer for AI browser agents, powered by Auth0."

**Action:** Run `python chatgpt_agent_with_agenttrust.py`

"Instead of blind trust, users get control, approvals, and a full audit trail."

**Transition:**  
"Thomas will quickly show how it works."

---

## 0:20 - 0:40 | Thomas

"AgentTrust has three parts.

A Python agent powered by GPT-4.1 and LangGraph.  
A Node backend that validates every action before it runs.  
And a Chrome extension that gives the user visibility and control.

Together, they let the agent act, but only inside a system that's governed and observable."

**Transition:**  
"Now Brilynd can show what the user controls."

---

## 0:40 - 1:00 | Brilynd

"From the extension, the user decides exactly what the agent can access.

You can whitelist domains, blacklist domains, define high-risk keywords, and manage saved credentials. Those credentials are encrypted and protected, and connected accounts like GitHub and Google are handled through Auth0."

**Action:** Show allowed domains, blocked domains, keywords, credentials, and connected accounts.

**Transition:**  
"Now let's give it a real task."

---

## 1:00 - 1:40 | Thomas

**Action:** Send:

```text
Search Google for the latest AI agent security risks in 2026, read the top article, then create a GitHub issue in my AgentTrust repository summarizing the key findings
```

"You can see the agent thinking in real time.

It classifies the task, creates a plan, and starts navigating the browser. Every action is checked by the backend before it runs, and each step is logged with identity, risk level, and screenshots."

**Action:** Let it search Google and open an article.

"When it reaches the GitHub issue creation step, that's a higher-trust action."

**If approval appears:**  
"This is where the approval flow kicks in."

**Action:** Approve it.

"That approval is logged too, so there's a record that a human authorized the action."

**Transition:**  
"Brilynd can show why that matters."

---

## 1:40 - 2:20 | Brilynd

"This is what makes AgentTrust useful in the real world.

Security teams can investigate threats and document findings.  
Operations teams can automate repetitive workflows safely.  
Researchers, analysts, recruiters, and support teams can all save time on web tasks without losing oversight.

We're not choosing between automation and control. We're giving teams both."

**Transition:**  
"And Thomas can close with where this goes next."

---

## 2:20 - 2:50 | Thomas

"Our goal is simple: agents should be able to act, but only inside a system you can trust.

With Auth0 as the identity backbone, policy checks before execution, approvals for risky actions, and a full audit trail, AgentTrust makes AI agents deployable in real environments.

Next, we're expanding integrations, policy controls, and reusable trusted workflows across more use cases."

---

## 2:50 - 3:00 | Optional Final Line

**Brilynd:**  
"AgentTrust gives AI agents accountability."
