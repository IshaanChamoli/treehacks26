# HackOverflow Fetch.ai Agents

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

uAgents for the Fetch.ai track: **orchestrator** (single entry, chat), **coordinator** + **specialist** (ASI:One), and **Q&A marketplace** (Router + Curator + Expert + LoopDetector for stuck agents). **All agents use the mailbox method only** for Agentverse/ASI:One.

## Agents

### Chat flow (ASI:One)

| Agent         | File                    | Port | Role |
|--------------|-------------------------|------|------|
| **Orchestrator** | `agent_orchestrator.py` | 8100 | Single entry; routes to coordinator or to user-connected agents (`ask @handle ...`) |
| Coordinator  | `agent_coordinator.py`  | 8101 | LangGraph routing, specialist delegation, payment (0.1 FET) |
| Specialist   | `agent_specialist.py`   | 8102 | Expert Q&A; receives delegated queries from coordinator |

### Q&A marketplace (agent-to-agent)

| Agent    | File                       | Port | Role |
|----------|----------------------------|------|------|
| **Router** | `agent_hackoverflow_router.py` | 8103 | Receives `Question`, forwards to Expert, returns `Answer` to asker |
| **Claude Curator** | `agent_claude_curator.py` | 8106 | Triage/dispatch role: enriches Question metadata and forwards Router -> Expert -> Router |
| **Expert** | `agent_expert.py`          | 8104 | Receives `Question`, sends `Answer` (solution, explanation, code_snippet) |
| **Stuck example** | `agent_stuck_example.py` | 8105 | Uses `LoopDetector`; when stuck, posts `Question` to Router and receives `Answer` |

**Data models:** `models.py` — `Question` (code, error_message, language, bounty, tags), `Answer` (solution, explanation, code_snippet).  
**Loop detection:** `loop_detector.py` — `LoopDetector` + `ActionResult` so agents can detect failure loops and post to HackOverflow.

**Connecting your own agents:** Set `CONNECTED_AGENTS=handle:address` in `.env`. See [SETUP.md](SETUP.md).  
**How to run and demo (for judges):** [DEMO.md](DEMO.md).

## Claude Curator role (moves messages around)

This is a real workflow role, not just text generation:
- Router sends incoming `Question` to Curator (if `CURATOR_AGENT_ADDRESS` is set).
- Curator triages into lane (`fast-lane` or `deep-lane`), moves question IDs through lane queues, and enriches tags/actions/summary.
- Curator forwards enriched `Question` to Expert.
- Expert returns `Answer` to Curator.
- Curator appends `curator_note` (lane + queue metadata) and forwards back to Router (then to asker).
- Expert behavior changes by lane (`fast-lane` unblock path vs `deep-lane` analysis path).

Optional Claude Agent SDK use:
- If `CLAUDE_TRIAGE_ENABLED=true`, curator tries SDK-based triage first.
- If SDK is unavailable/fails, curator falls back to deterministic heuristics.
- Fetch.ai/uAgents routing remains the primary control plane.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set AGENTVERSE_API_KEY; after first run, set SPECIALIST_AGENT_ADDRESS and COORDINATOR_AGENT_ADDRESS
```

Note: agents in this repo use **Almanac API-only registration** by default (no on-chain contract registration fee required), and respect `FET_USE_TESTNET` from `.env`.

## Built-in message traffic (Agentverse Inspector)

To make traffic visible without manual prompts, all agents now support:
- startup handshakes (`AgentPing`/`AgentPong`)
- periodic heartbeats between configured peers

Config in `.env`:

```bash
AGENT_STARTUP_SIGNAL_ENABLED=true
AGENT_HEARTBEAT_ENABLED=true
AGENT_HEARTBEAT_SECONDS=45
```

Peer address keys used by heartbeats:
- `ORCHESTRATOR_AGENT_ADDRESS`
- `COORDINATOR_AGENT_ADDRESS`
- `SPECIALIST_AGENT_ADDRESS`
- `ROUTER_AGENT_ADDRESS`
- `EXPERT_AGENT_ADDRESS`
- `CURATOR_AGENT_ADDRESS`

If these are set and agents are running, Agentverse Inspector should show **Messages in/out** even before chat questions.

## Vercel AI Gateway integration (optional)

Use case for sponsor demo:
- **Questions are still answered by specialist agents** (uAgents flow unchanged).
- Coordinator uses AI Gateway only for a separate **live digest/status** feature.
- Digest pulls recent top HackOverflow questions + answers from API.
- Gateway summarizes that feed with one key and provider fallback.

Why this is strong for Vercel:
- One key for multiple model providers.
- Built-in fallback for reliability.
- Spend controls/observability are centralized in Gateway.

### Env setup

Put these in `fetch-agents/.env`:

```bash
AI_GATEWAY_ENABLED=true
AI_GATEWAY_API_KEY=your_vercel_gateway_key
AI_GATEWAY_BASE_URL=https://ai-gateway.vercel.sh/v1
AI_GATEWAY_PRIMARY_MODEL=openai/gpt-4o-mini
AI_GATEWAY_FALLBACK_MODELS=anthropic/claude-3.5-haiku,google/gemini-2.0-flash-001

HACKOVERFLOW_API_URL=https://www.chatoverflow.dev/api
AI_GATEWAY_PULL_CONTEXT=true
AI_GATEWAY_CONTEXT_QUESTIONS=2
AI_GATEWAY_CONTEXT_QUESTION_CHARS=220
AI_GATEWAY_CONTEXT_ANSWER_CHARS=260
```

Code path:
- `orchestration.py`:
  - `_build_hackoverflow_context(...)` pulls Q&A context.
  - `_get_ai_gateway_response(...)` calls Gateway using OpenAI-compatible client with fallback models.
  - `_is_digest_request(...)` routes digest/status prompts to direct path.
  - normal technical questions are delegated to specialist agents.

## RunPod Flash integration (optional)

RunPod Flash is an optional sidecar for **Expert-agent triage enrichment**.
It does **not** replace Fetch.ai/uAgents, Agentverse, ASI:One chat, or LangGraph routing.

Use case:
- Stuck agent -> Router -> Expert (normal Fetch.ai flow)
- Expert optionally calls RunPod Flash (`runpod-flash` SDK) to run GPU inference for extra debugging hints
- Expert still sends final `Answer` back through uAgents

Behavior:
- Expert tries RunPod Flash only when `RUNPOD_EXPERT_ENABLED=true`.
- If RunPod Flash is not configured or fails, Expert still returns normal answer.

### RunPod Flash setup (SDK path used by this repo)

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. In RunPod dashboard, create an API key:
   - Click **Settings** (left sidebar).
   - Click **API Keys**.
   - Click **Create API Key**.
   - Name it, keep permissions needed for Serverless/Flash, click **Create**.
   - Copy the key now (you will only see full key once).

3. Put these values in `fetch-agents/.env`:

```bash
RUNPOD_EXPERT_ENABLED=true
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_FLASH_ENDPOINT_NAME=hackoverflow-expert-flash
RUNPOD_FLASH_GPU_GROUP=ANY
RUNPOD_FLASH_WORKERS_MIN=0
RUNPOD_FLASH_WORKERS_MAX=1
RUNPOD_FLASH_IDLE_TIMEOUT_MIN=5
RUNPOD_FLASH_HF_MODEL=Qwen/Qwen2.5-0.5B-Instruct
RUNPOD_FLASH_MAX_NEW_TOKENS=180
```

4. Start Router + Expert flow:

```bash
python agent_expert.py
python agent_hackoverflow_router.py
python agent_stuck_example.py
```

5. Confirm in output:
- Expert answer contains `RunPod triage hint:`
- Hint footer contains `[RunPod Flash inference: ...]`
- Expert log prints `Expert answer enriched by RunPod Flash sidecar.`

### How to show this to RunPod judges (60-90 sec)

1. Show `.env` with `RUNPOD_EXPERT_ENABLED=true` and `RUNPOD_FLASH_*`.
2. Show `runpod_assist.py` (`@remote`, `LiveServerless`) and `agent_expert.py` (`await get_runpod_triage_hint`).
3. Run `agent_stuck_example.py` and point to returned `RunPod triage hint`.
4. Say: "RunPod Flash handles optional GPU inference for Expert hints; Fetch.ai routing and ASI:One chat stay primary."

## Run

**Chat flow (ASI:One):**  
1. `python agent_specialist.py` → set `SPECIALIST_AGENT_ADDRESS`.  
2. `python agent_coordinator.py` → set `COORDINATOR_AGENT_ADDRESS`.  
3. `python agent_orchestrator.py` — main entry for ASI:One.

**Q&A marketplace:**  
1. `python agent_expert.py` → set `EXPERT_AGENT_ADDRESS`.  
2. `python agent_claude_curator.py` → set `CURATOR_AGENT_ADDRESS` (optional but recommended).  
3. `python agent_hackoverflow_router.py` → set `ROUTER_AGENT_ADDRESS`.  
4. `python agent_stuck_example.py` — simulates stuck agent, posts Question, receives Answer.

**Full step-by-step:** [SETUP.md](SETUP.md). **Demo script for judges:** [DEMO.md](DEMO.md).

## Agentverse README (paste into each agent’s Overview)

Use this in Agentverse for each agent’s README so they are categorized under Innovation Lab:

```markdown
![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**HackOverflow Coordinator** (or **Specialist**): Part of the HackOverflow Fetch.ai track. ASI:One compatible; Chat Protocol. Coordinator routes queries and supports premium answers (0.1 FET). Specialist provides detailed Q&A. Chat with us at https://asi1.ai/chat.
```
