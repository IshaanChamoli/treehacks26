# What you need to do: uAgents, Agentverse, ASI:One

Follow these steps in order. Do them once; then your agents are registered and chat works via ASI:One.

---

## 1. uAgents (run the agents locally)

**Goal:** Get the Python agents running and see their addresses in the logs.

**Mailbox only:** All agents use the **mailbox** method only (no proxy or custom endpoints). This is required for Agentverse and ASI:One: messages go through Agentverse’s mailbox so your agents can be reached from the internet.

1. **Open a terminal and go to the agents folder:**
   ```bash
   cd fetch-agents
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Copy env and add your keys:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set at least:
   - `AGENTVERSE_API_KEY` (you get this in step 2 below)

4. **Run the agents in order (use 3 terminals):**
   - **Terminal 1 – Specialist:**  
     `python agent_specialist.py`  
     Copy the line that says `Starting agent with address: agent1q...` and put that value in `.env` as `SPECIALIST_AGENT_ADDRESS`.
   - **Terminal 2 – Coordinator:**  
     `python agent_coordinator.py`  
     Copy its address and set `COORDINATOR_AGENT_ADDRESS` in `.env` (needed for the orchestrator).
   - **Terminal 3 – Orchestrator:**  
     `python agent_orchestrator.py`  
     This is the single entry point; copy its address for ASI:One.

5. **Set peer addresses for visible message traffic (Inspector):**
   - In `.env`, set:
     - `ORCHESTRATOR_AGENT_ADDRESS`
     - `COORDINATOR_AGENT_ADDRESS`
     - `SPECIALIST_AGENT_ADDRESS`
     - `ROUTER_AGENT_ADDRESS`
     - `EXPERT_AGENT_ADDRESS`
     - `CURATOR_AGENT_ADDRESS`
   - Keep diagnostics enabled:
     - `AGENT_STARTUP_SIGNAL_ENABLED=true`
     - `AGENT_HEARTBEAT_ENABLED=true`
     - `AGENT_HEARTBEAT_SECONDS=45`
   - Restart agents after changing `.env`.
   - Agents will emit startup handshakes and heartbeat pings (`AgentPing`/`AgentPong`) so **Messages in/out** is non-empty in Agentverse Inspector.

5. **Optional:** To connect **your own agent**, add to `.env`:
   ```bash
   CONNECTED_AGENTS=@mybot:agent1q...your_agent_address
   ```
   Your agent must also use **mailbox** (and be registered on Agentverse) so the orchestrator can reach it. Restart the orchestrator. Users can then say `ask @mybot hello` and the orchestrator will forward to your agent. Your agent should reply with a normal ChatMessage (or with `ORCH_REPLY|user_address|request_id|response` if you want to follow the same protocol).

---

## 2. Agentverse (mailbox only — register so ASI:One can reach agents)

**Goal:** So that ASI:One (and other agents) can send messages to your agents. We use **mailbox only** (no proxy or other connection types).

1. **Sign up and get an API key:**
   - Go to [https://agentverse.ai](https://agentverse.ai) and sign up / log in.
   - In the dashboard, create or copy an **API key**. Put it in `.env` as `AGENTVERSE_API_KEY`.

2. **Connect each agent via Mailbox (required):**
   - When you run each agent (`agent_specialist.py`, `agent_coordinator.py`, `agent_orchestrator.py`), the logs print an **Inspector** link, e.g.  
     `Agent inspector available at https://agentverse.ai/inspect/?uri=...`
   - Open that link in a browser, click **Connect**, and choose **Mailbox** (this is the only method we use). Follow the instructions so the agent registers with Agentverse and is reachable from the internet.

3. **Launch agents on Agentverse (Chat Protocol):**
   - In Agentverse, go to **Agents** → **Launch an Agent**.
   - Choose **Chat Protocol**.
   - Enter:
     - **Agent name** (e.g. `hackoverflow_orchestrator`).
     - **Agent endpoint**: the URL where the agent is reachable. For local dev this is usually your tunnel URL (e.g. from ngrok or the Inspector), or later your deployed VM URL (e.g. `http://your-server:8100`).
   - Click through to get the registration script if needed; with uAgents you often just need to have the agent running with mailbox and the Inspector connected.
   - Repeat for the **orchestrator** (main entry), **coordinator**, and **specialist** if you want them all discoverable.

4. **Improve discovery (README + handle):**
   - Open each agent’s profile on Agentverse → **Overview** → **Edit**.
   - In the README, paste the same badges and short description as in the repo (see main README or `fetch-agents/README.md`).
   - Set a **handle** (e.g. `@hackoverflow-orchestrator`) so users can type it in ASI:One.

---

## 3. ASI:One (chat UI – where people talk to your agents)

**Goal:** Users (and you) chat with your agents in one place.

1. **Get an ASI:One API key (optional, for LLM-backed answers):**
   - Go to [https://asi1.ai](https://asi1.ai) and sign up / log in.
   - In the dashboard, create an API key. Put it in `.env` as `ASI_ONE_API_KEY` so the coordinator can use the ASI:One model for direct answers.

2. **Chat with your agents:**
   - Open [https://asi1.ai/chat](https://asi1.ai/chat).
   - In the chat, either:
     - Type your **agent’s handle** (e.g. `@hackoverflow-orchestrator`) and then your question, or  
     - Start a conversation; ASI:One may suggest your agent if the query matches.
   - Your messages go to Agentverse → your agent (orchestrator → coordinator/specialist or connected agents). Replies come back in the same chat.

3. **Tell others how to reach you:**
   - Share the ASI:One chat link and your agent handle(s) (e.g. in your app’s Fetch page or README).

---

## Quick checklist

| Step | What you do |
|------|---------------------|
| **uAgents** | All agents use **mailbox only**. `pip install -r requirements.txt`, set `.env`, run specialist → coordinator → orchestrator, copy addresses into `.env`. |
| **Agentverse** | Sign up, set `AGENTVERSE_API_KEY`. For each agent: open Inspector link and connect **Mailbox** (required; we do not use proxy or other methods). Launch Agent (Chat Protocol), set endpoint; add README + handle. |
| **ASI:One** | (Optional) Get API key and set `ASI_ONE_API_KEY`; go to asi1.ai/chat and use your agent handle to talk to your agents. |

After this, the **orchestrator** is the single entry point: it organizes conversations and routes to the coordinator (and specialist) or to any agent you added in `CONNECTED_AGENTS`.

For Q&A marketplace routing, you can optionally insert the curator role:
- run `agent_claude_curator.py`
- set `CURATOR_AGENT_ADDRESS` in `.env`
- Router will forward Question to Curator first, then Curator forwards to Expert.
