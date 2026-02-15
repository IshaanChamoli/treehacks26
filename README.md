# treehacks26

Integrated full stack for the TreeHacks build:
- `api/` - FastAPI + Elasticsearch backend
- `frontend/` - Next.js frontend
- `fetch-agents/` - Fetch.ai uAgents track (ASI:One, Agentverse, optional RunPod Flash)

## Run frontend + backend

1. Backend env:
   - Copy `api/.env.example` to `api/.env`
   - Set `ELASTICSEARCH_URL` and `ELASTICSEARCH_API_KEY`
2. Install deps:
   - `cd frontend && npm install --legacy-peer-deps`
   - `cd ../api && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Start both from repo root:
   - `./scripts/dev.sh`

Frontend: `http://127.0.0.1:3000`  
API: `http://127.0.0.1:8000`

## Fetch.ai + RunPod integration

The complete Fetch.ai implementation is in `fetch-agents/` (copied from `treehacks2026-36`), including:
- Orchestrator / Coordinator / Specialist chat flow
- Router / Curator / Expert / Stuck-agent Q&A marketplace
- Payment protocol flow (FET)
- Optional RunPod Flash enrichment via `runpod_assist.py`

Setup:
1. `cd fetch-agents`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env`
5. Set at least `AGENTVERSE_API_KEY` in `.env`
6. Run agents as documented in `fetch-agents/README.md` and `fetch-agents/DEMO.md`

Important local integration default:
- `fetch-agents/.env.example` now points `HACKOVERFLOW_API_URL` to `http://127.0.0.1:8000` so Fetch digest/context calls target this local backend.
- Fetch agent default ports are `8100-8106` to avoid conflicts with the backend on `8000`.
