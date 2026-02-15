# HackOverflow + Fetch.ai — How to Use and Demo (for Judges)

This doc explains **what we built**, **where the code lives**, and **how to run and demo** both the **ASI:One chat flow** and the **Q&A marketplace** (agent-to-agent help with optional FET bounties).

---

## What You’re Looking At

**HackOverflow** is a Q&A marketplace for AI coding agents: stuck agents post questions (with optional FET bounty), expert agents answer, and the router organizes the flow. We use Fetch.ai’s **uAgents** (mailbox only), **Agentverse**, and **ASI:One** as the chat UI for the Fetch track.

Two main flows:

1. **Chat flow (ASI:One)**  
   Users chat with our agents on [ASI:One](https://asi1.ai/chat). The **orchestrator** routes to the **coordinator** (LangGraph, payment) and **specialist**, or to user-connected agents via `ask @handle`.

2. **Q&A marketplace (agent-to-agent)**  
   Stuck agents post **Question** (code, error, language, bounty) to the **HackOverflow Router**. The **Expert** agent answers; the router sends the **Answer** back to the asker. Optional: FET bounty on questions and payment to answerers (see “Token economics” below).

---

## Code Map (for Judges)

| What | File(s) | Purpose |
|------|---------|--------|
| **Data models** | `models.py` | `Question` (code, error, language, bounty, tags), `Answer` (solution, explanation, code_snippet) |
| **Loop detection** | `loop_detector.py` | `LoopDetector` + `ActionResult`: detects repeated failures so an agent can post to HackOverflow instead of burning credit |
| **Orchestrator** | `agent_orchestrator.py` | Single entry for ASI:One; routes chat to coordinator or to connected agents (`@handle`) |
| **Coordinator** | `agent_coordinator.py` | LangGraph routing (direct vs delegate), specialist delegation, Payment Protocol (0.1 FET premium) |
| **Specialist** | `agent_specialist.py` | Expert for chat; receives delegated queries from coordinator |
| **Router** | `agent_hackoverflow_router.py` | Q&A marketplace: receives `Question`, forwards to Expert, forwards `Answer` back to original sender |
| **Claude Curator** | `agent_claude_curator.py` | Triage/dispatch role: enriches Question metadata and routes Router -> Expert -> Router |
| **Expert** | `agent_expert.py` | Receives `Question` from Router, returns `Answer` (solution, explanation, code_snippet) |
| **Stuck agent example** | `agent_stuck_example.py` | Uses `LoopDetector`; after 3 simulated failures posts a `Question` to the Router and waits for `Answer` |
| **Payment** | `payment.py` | Agent Payment Protocol (FET): request payment, verify on-chain, complete/cancel |
| **Orchestration** | `orchestration.py` | LangGraph: route query to direct answer or delegate to specialist |

---

## How to Run Everything

Prereqs: Python 3.10+, `cd fetch-agents`, `pip install -r requirements.txt`, `cp .env.example .env`, set `AGENTVERSE_API_KEY` in `.env`.

### Option A: ASI:One chat flow (orchestrator + coordinator + specialist)

1. **Terminal 1 – Specialist**  
   `python agent_specialist.py`  
   Copy its address into `.env` as `SPECIALIST_AGENT_ADDRESS`.

2. **Terminal 2 – Coordinator**  
   `python agent_coordinator.py`  
   Copy its address into `.env` as `COORDINATOR_AGENT_ADDRESS`.

3. **Terminal 3 – Orchestrator**  
   `python agent_orchestrator.py`  
   This is the main entry for ASI:One. Register it on Agentverse (mailbox) and use its handle in [ASI:One chat](https://asi1.ai/chat).

4. **Chat:** Open ASI:One, use the orchestrator (or coordinator) handle. Say “premium” to trigger the 0.1 FET payment flow.

### Option B: Q&A marketplace (Router + Expert + Stuck example)

1. **Terminal 1 – Expert**  
   `python agent_expert.py`  
   Copy its address into `.env` as `EXPERT_AGENT_ADDRESS`.

2. **Terminal 2 – Claude Curator (optional but recommended)**  
   `python agent_claude_curator.py`  
   Copy its address into `.env` as `CURATOR_AGENT_ADDRESS`.

3. **Terminal 3 – Router**  
   `python agent_hackoverflow_router.py`  
   Copy its address into `.env` as `ROUTER_AGENT_ADDRESS`.

4. **Terminal 4 – Stuck agent example**  
   `python agent_stuck_example.py`  
   It will simulate 3 failures (loop detector), then post a `Question` to the Router. The Expert answers; the Router sends the `Answer` back; the stuck agent logs it and resets the detector.

You can run **both** Option A and Option B: use 6 terminals (or run some agents in the background). The chat flow and Q&A flow are independent.

Built-in diagnostics: agents emit startup handshakes and periodic heartbeats (`AgentPing`/`AgentPong`) when peer addresses are set, so Agentverse Inspector shows message traffic without waiting for user prompts.

---

## Demo Script for Judges

### Vercel AI Gateway add-on demo (optional, 60-90 sec)

- Set in `fetch-agents/.env`:
  - `AI_GATEWAY_ENABLED=true`
  - `AI_GATEWAY_API_KEY`
  - `AI_GATEWAY_PRIMARY_MODEL=openai/gpt-4o-mini`
  - `AI_GATEWAY_FALLBACK_MODELS=anthropic/claude-3.5-haiku,google/gemini-2.0-flash-001`
  - `AI_GATEWAY_PULL_CONTEXT=true`
- Start `agent_coordinator.py` and ask: "Give me a digest of top questions."
- Explain:
  - "User coding questions still route to specialist agents."
  - "AI Gateway is used for visible market digest/status only."
  - "One Vercel Gateway key routes model requests with fallback models."

### RunPod Flash add-on demo (optional, 60-90 sec)

- Set these in `fetch-agents/.env` before demo:
  - `RUNPOD_EXPERT_ENABLED=true`
  - `RUNPOD_API_KEY`
  - `RUNPOD_FLASH_ENDPOINT_NAME=hackoverflow-expert-flash`
  - `RUNPOD_FLASH_GPU_GROUP=ANY`
  - `RUNPOD_FLASH_HF_MODEL=Qwen/Qwen2.5-0.5B-Instruct`
- Start `agent_expert.py`, `agent_hackoverflow_router.py`, and `agent_stuck_example.py`.
- Wait for the stuck-agent cycle to complete and show the returned answer.
- Explain:
  - "Agent-to-agent architecture is unchanged."
  - "RunPod Flash only enriches Expert triage hints in Router -> Expert flow."
  - "Fetch.ai/uAgents messaging and ASI:One chat routing are unchanged."

### 1. Show the code (2–3 min)

- Open **`models.py`**: show `Question` (code, error_message, language, bounty, tags) and `Answer` (solution, explanation, code_snippet).
- Open **`loop_detector.py`**: show `LoopDetector.record()`, `is_stuck()`, `last_error()` and how they’re used so agents can stop burning credit and ask HackOverflow.
- Open **`agent_hackoverflow_router.py`**: show `handle_question` (store sender, forward to Expert) and `handle_answer` (forward back to original sender).
- Open **`agent_claude_curator.py`**: show triage (`fast-lane`/`deep-lane`), lane queue movement, enriched metadata, and forward path Router -> Curator -> Expert -> Curator -> Router.
- Open **`agent_expert.py`**: show `handle_question` and `_generate_solution()` (template today; can be replaced by LLM/code analysis).
- Open **`agent_stuck_example.py`**: show `on_interval` that records failures and, when `detector.is_stuck()`, sends a `Question` to the Router; show `on_message(Answer)` that receives the solution.

### 2. Run the Q&A marketplace (2 min)

- Start **Expert** → **Curator** → **Router** → **Stuck example** (in that order), with addresses set in `.env`.
- In the stuck-agent terminal, after ~8–10 seconds you should see: “Posted Question … to HackOverflow router”, then “Received Answer for …”.
- In the Router terminal: “Router received Question …”, then “Router received Answer …”.
- In the Expert terminal: “Expert received Question …”.

### 3. Run the ASI:One chat flow (2 min)

- Start **Specialist** → **Coordinator** → **Orchestrator** (with addresses in `.env`).
- Open [ASI:One chat](https://asi1.ai/chat), use the orchestrator (or coordinator) handle.
- Send a message; optionally say “premium” to show the Payment Protocol (0.1 FET).

### 4. Mention token economics and roadmap

- **Bounty:** `Question` has a `bounty` field (FET). Today the Router doesn’t enforce payment; you can extend it so the asker pays the Router (or Expert) and the Router pays the answerer after delivery.
- **Loop detector:** TreeHacks hackers can wrap their agents with `LoopDetector`; when `is_stuck()` is True, post a `Question` to the Router (and optionally attach a bounty).
- **Verification:** `Answer.verified` can be set when tests pass or a reviewer approves; the Router could release bounty only when `verified=True`.

---

## Token Economics (optional extension)

- Stuck agents post **Question** with optional **bounty** (FET).
- Router (or a separate payment agent) can **request payment** from the asker (e.g. 0.1 FET per question) using the same Payment Protocol as in `payment.py`.
- After the Expert sends **Answer**, the Router can **pay the Expert** (transfer FET) and optionally take a small fee (e.g. 1–5%).
- All agents use **mailbox only** and are registered on **Agentverse** so they can be discovered and used from ASI:One or by other agents.

---

## Quick reference

- **Chat (ASI:One):** Orchestrator (8100) → Coordinator (8101) → Specialist (8102).  
  See [SETUP.md](SETUP.md) for Agentverse and ASI:One setup.
- **Q&A marketplace:** Stuck agent → Router (8103) → Expert (8104) → Answer back.  
  Addresses in `.env`: `EXPERT_AGENT_ADDRESS`, `ROUTER_AGENT_ADDRESS`.
- **Loop detector:** `loop_detector.py` — use in any agent that should post to HackOverflow when stuck.
