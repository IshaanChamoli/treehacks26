"""
HackOverflow Claude Curator Agent.

Role:
- Receives Question from Router
- Triages and enriches metadata (lane/actions/summary)
- Forwards enriched Question to Expert
- Receives Answer from Expert and forwards back to Router with curator note

This keeps Fetch.ai uAgents routing primary while using Claude Agent SDK as an
optional triage helper.
"""
import os
from collections import deque
from typing import Any

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol

from agent_runtime import (
    agent_network,
    api_only_registration_policy,
    heartbeat_enabled,
    heartbeat_period_seconds,
    startup_signal_enabled,
)
from claude_triage import get_triage_plan
from models import Answer, Question
from signals import AgentPing, AgentPong, build_ping, build_pong

load_dotenv()

CURATOR_SEED = os.getenv("AGENT_CURATOR_SEED", "hackoverflow-curator-agent-seed-phrase")
PORT = int(os.getenv("AGENT_PORT_CURATOR", "8106"))
EXPERT_ADDRESS = os.getenv("EXPERT_AGENT_ADDRESS", "").strip()
ROUTER_ADDRESS = os.getenv("ROUTER_AGENT_ADDRESS", "").strip()

curator = Agent(
    name="hackoverflow_claude_curator",
    seed=CURATOR_SEED,
    port=PORT,
    mailbox=True,
    network=agent_network(),
    registration_policy=api_only_registration_policy(),
    publish_agent_details=True,
)

qa_proto = Protocol(name="hackoverflow_qa", version="1.0.0")
signal_proto = Protocol(name="hackoverflow_signals", version="1.0.0")

_pending: dict[str, dict[str, str]] = {}
_lane_queues: dict[str, deque[str]] = {
    "fast-lane": deque(),
    "deep-lane": deque(),
}


def _as_dict(model_obj) -> dict[str, Any]:
    if hasattr(model_obj, "model_dump"):
        return model_obj.model_dump()
    if hasattr(model_obj, "dict"):
        return model_obj.dict()
    return {}


def _curator_peers() -> list[str]:
    peers: list[str] = []
    if EXPERT_ADDRESS:
        peers.append(EXPERT_ADDRESS)
    if ROUTER_ADDRESS and ROUTER_ADDRESS not in peers:
        peers.append(ROUTER_ADDRESS)
    return peers


@qa_proto.on_message(Question)
async def handle_question(ctx: Context, sender: str, msg: Question):
    ctx.logger.info(f"Curator received Question {msg.question_id} from {sender}")
    if not EXPERT_ADDRESS:
        ctx.logger.warning("Curator cannot forward: EXPERT_AGENT_ADDRESS is not set.")
        return

    plan = await get_triage_plan(msg)
    lane = str(plan.get("lane", "deep-lane"))
    summary = str(plan.get("summary", "")).strip()
    actions = [str(x).strip() for x in plan.get("actions", []) if str(x).strip()]
    source = str(plan.get("source", "heuristic")).strip()

    msg_data = _as_dict(msg)
    tags = list(msg_data.get("tags", []) or [])
    tags.append("triaged")
    tags.append(lane)
    tags = sorted(set(tags))

    enriched = Question(
        **msg_data,
        tags=tags,
        route_lane=lane,
        triage_summary=summary,
        triage_actions=actions[:3],
        channel=msg.channel or msg.language or "general",
    )

    queue = _lane_queues.setdefault(lane, deque())
    queue.append(msg.question_id)
    queue_depth = len(queue)

    _pending[msg.question_id] = {
        "sender": sender,
        "lane": lane,
        "summary": summary,
        "source": source,
        "queue_depth": str(queue_depth),
    }
    ctx.logger.info(
        "Curator enqueued Question "
        f"{msg.question_id} in {lane} (depth={queue_depth}, source={source}) and forwarded to expert."
    )
    await ctx.send(EXPERT_ADDRESS, enriched)


@qa_proto.on_message(Answer)
async def handle_answer(ctx: Context, sender: str, msg: Answer):
    meta = _pending.pop(msg.question_id, None)
    if not meta:
        ctx.logger.warning(f"Curator got Answer for unknown question_id {msg.question_id}")
        return

    target = meta.get("sender", "")
    if not target:
        ctx.logger.warning(f"Curator has no return sender for {msg.question_id}")
        return

    note = (
        f"Curator lane={meta.get('lane','deep-lane')}; "
        f"source={meta.get('source','heuristic')}; "
        f"summary={meta.get('summary','n/a')}; "
        f"queue_depth_at_enqueue={meta.get('queue_depth','1')}"
    )

    lane = meta.get("lane", "deep-lane")
    lane_queue = _lane_queues.get(lane)
    remaining = 0
    if lane_queue is not None:
        try:
            lane_queue.remove(msg.question_id)
        except ValueError:
            pass
        remaining = len(lane_queue)

    answer_data = _as_dict(msg)
    updated = Answer(
        **answer_data,
        explanation=f"{msg.explanation}\n\nCurator note: {note}; queue_remaining={remaining}",
        curator_note=f"{note}; queue_remaining={remaining}",
    )
    ctx.logger.info(f"Curator forwarding Answer {msg.question_id} back to router flow.")
    await ctx.send(target, updated)


@signal_proto.on_message(AgentPing)
async def handle_ping(ctx: Context, sender: str, msg: AgentPing):
    ctx.logger.info(f"Curator received ping {msg.ping_id} from {msg.source} ({sender})")
    await ctx.send(
        sender,
        build_pong(
            ping_id=msg.ping_id,
            responder=str(curator.address),
            detail="curator-ok",
        ),
    )


@signal_proto.on_message(AgentPong)
async def handle_pong(ctx: Context, sender: str, msg: AgentPong):
    ctx.logger.info(f"Curator received pong {msg.ping_id} from {msg.responder} ({sender})")


@curator.on_event("startup")
async def curator_startup(ctx: Context):
    if not startup_signal_enabled():
        return
    peers = _curator_peers()
    if not peers:
        ctx.logger.info("Curator startup signal skipped: no peers configured.")
        return
    for peer in peers:
        ping = build_ping(
            source=str(curator.address),
            purpose="startup-handshake",
            detail="curator-online",
        )
        await ctx.send(peer, ping)
    ctx.logger.info(f"Curator startup handshake sent to {len(peers)} peer(s).")


@curator.on_interval(period=heartbeat_period_seconds())
async def curator_heartbeat(ctx: Context):
    if not heartbeat_enabled():
        return
    peers = _curator_peers()
    if not peers:
        return
    for peer in peers:
        ping = build_ping(
            source=str(curator.address),
            purpose="heartbeat",
            detail="curator-heartbeat",
        )
        await ctx.send(peer, ping)


curator.include(qa_proto)
curator.include(signal_proto)

if __name__ == "__main__":
    curator.run()
