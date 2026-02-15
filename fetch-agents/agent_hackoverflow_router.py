"""
HackOverflow Router Agent — central Q&A marketplace.
Receives Question from stuck agents, forwards to Expert, returns Answer to sender.
Optional: request FET bounty from asker and pay answerer (see payment flow in DEMO.md).
"""
import os
import uuid
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from models import Question, Answer
from agent_runtime import (
    agent_network,
    api_only_registration_policy,
    heartbeat_enabled,
    heartbeat_period_seconds,
    startup_signal_enabled,
)
from signals import AgentPing, AgentPong, build_ping, build_pong

load_dotenv()

ROUTER_SEED = os.getenv("AGENT_ROUTER_SEED", "hackoverflow-router-agent-seed-phrase")
PORT = int(os.getenv("AGENT_PORT_ROUTER", "8103"))
EXPERT_ADDRESS = os.getenv("EXPERT_AGENT_ADDRESS", "").strip()
CURATOR_ADDRESS = os.getenv("CURATOR_AGENT_ADDRESS", "").strip()

router = Agent(
    name="hackoverflow_router",
    seed=ROUTER_SEED,
    port=PORT,
    mailbox=True,
    network=agent_network(),
    registration_policy=api_only_registration_policy(),
    publish_agent_details=True,
)

# Protocol for Q&A (agent-to-agent)
qa_proto = Protocol(name="hackoverflow_qa", version="1.0.0")
signal_proto = Protocol(name="hackoverflow_signals", version="1.0.0")

# question_id -> original sender address (so we can forward Answer back)
_pending: dict[str, str] = {}


def _router_peers() -> list[str]:
    peers: list[str] = []
    target = CURATOR_ADDRESS or EXPERT_ADDRESS
    if target:
        peers.append(target)
    return peers


@qa_proto.on_message(Question)
async def handle_question(ctx: Context, sender: str, msg: Question):
    ctx.logger.info(f"Router received Question {msg.question_id} from {sender}")
    target = CURATOR_ADDRESS or EXPERT_ADDRESS
    if not target:
        ctx.logger.warning("No CURATOR_AGENT_ADDRESS or EXPERT_AGENT_ADDRESS set; cannot forward question")
        return
    _pending[msg.question_id] = sender
    if CURATOR_ADDRESS:
        ctx.logger.info(f"Router forwarding Question {msg.question_id} to Curator.")
    else:
        ctx.logger.info(f"Router forwarding Question {msg.question_id} directly to Expert.")
    await ctx.send(target, msg)


@qa_proto.on_message(Answer)
async def handle_answer(ctx: Context, sender: str, msg: Answer):
    ctx.logger.info(f"Router received Answer for {msg.question_id} from {sender}")
    original_sender = _pending.pop(msg.question_id, None)
    if not original_sender:
        ctx.logger.warning(f"No pending question_id {msg.question_id}")
        return
    await ctx.send(original_sender, msg)


@signal_proto.on_message(AgentPing)
async def handle_ping(ctx: Context, sender: str, msg: AgentPing):
    ctx.logger.info(f"Router received ping {msg.ping_id} from {msg.source} ({sender})")
    await ctx.send(
        sender,
        build_pong(
            ping_id=msg.ping_id,
            responder=str(router.address),
            detail="router-ok",
        ),
    )


@signal_proto.on_message(AgentPong)
async def handle_pong(ctx: Context, sender: str, msg: AgentPong):
    ctx.logger.info(f"Router received pong {msg.ping_id} from {msg.responder} ({sender})")


@router.on_event("startup")
async def router_startup(ctx: Context):
    if not startup_signal_enabled():
        return
    peers = _router_peers()
    if not peers:
        ctx.logger.info("Router startup signal skipped: no peers configured.")
        return
    for peer in peers:
        ping = build_ping(
            source=str(router.address),
            purpose="startup-handshake",
            detail="router-online",
        )
        await ctx.send(peer, ping)
    ctx.logger.info(f"Router startup handshake sent to {len(peers)} peer(s).")


@router.on_interval(period=heartbeat_period_seconds())
async def router_heartbeat(ctx: Context):
    if not heartbeat_enabled():
        return
    peers = _router_peers()
    if not peers:
        return
    for peer in peers:
        ping = build_ping(
            source=str(router.address),
            purpose="heartbeat",
            detail="router-heartbeat",
        )
        await ctx.send(peer, ping)


router.include(qa_proto)
router.include(signal_proto)

if __name__ == "__main__":
    router.run()
