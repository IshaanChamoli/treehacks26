"""
HackOverflow Coordinator uAgent — ASI:One compatible.
Uses LangGraph orchestration to route queries: answer directly or delegate to specialist.
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

from agent_runtime import (
    agent_network,
    api_only_registration_policy,
    heartbeat_enabled,
    heartbeat_period_seconds,
    startup_signal_enabled,
)
from orchestration import run_orchestration
from payment import payment_proto, request_payment_from_user, set_agent_wallet
from signals import AgentPing, AgentPong, build_ping, build_pong

load_dotenv()

COORDINATOR_SEED = os.getenv("AGENT_COORDINATOR_SEED", "hackoverflow-coordinator-agent-seed-phrase")
PORT = int(os.getenv("AGENT_PORT_COORDINATOR", "8101"))
SPECIALIST_ADDRESS = os.getenv("SPECIALIST_AGENT_ADDRESS", "").strip()
ORCHESTRATOR_ADDRESS = os.getenv("ORCHESTRATOR_AGENT_ADDRESS", "").strip()

coordinator = Agent(
    name="hackoverflow_coordinator",
    seed=COORDINATOR_SEED,
    port=PORT,
    mailbox=True,  # Required: mailbox is the only method for Agentverse/ASI:One
    network=agent_network(),
    registration_policy=api_only_registration_policy(),
    publish_agent_details=True,
)

chat_proto = Protocol(spec=chat_protocol_spec)
signal_proto = Protocol(name="hackoverflow_signals", version="1.0.0")


def _extract_text(msg: ChatMessage) -> str:
    parts = []
    for item in msg.content:
        if isinstance(item, TextContent):
            parts.append(item.text)
    return " ".join(parts).strip()


def _coordinator_peers() -> list[str]:
    peers: list[str] = []
    if SPECIALIST_ADDRESS:
        peers.append(SPECIALIST_ADDRESS)
    if ORCHESTRATOR_ADDRESS and ORCHESTRATOR_ADDRESS not in peers:
        peers.append(ORCHESTRATOR_ADDRESS)
    return peers


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    ctx.logger.info(f"Coordinator received message from {sender}")
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )

    user_text = _extract_text(msg)

    # Orchestrator delegation: ORCH_DELEGATE|orch_addr|user_addr|session_id|request_id|text
    # We run normal logic but send final reply to orchestrator as ORCH_REPLY|user_addr|request_id|response
    orch_user = orch_request_id = orch_reply_to = None
    if user_text.startswith("ORCH_DELEGATE|"):
        parts = user_text.split("|", 5)
        if len(parts) >= 6:
            orch_reply_to = parts[1]   # orchestrator address
            orch_user = parts[2]        # original user to reply to
            orch_request_id = parts[4]
            user_text = parts[5]
    else:
        orch_reply_to = sender  # will send normal ChatMessage to sender

    def _send_final(send_ctx: Context, content: str):
        if orch_user is not None and orch_request_id is not None and orch_reply_to:
            orch_msg = f"ORCH_REPLY|{orch_user}|{orch_request_id}|{content}"
            return send_ctx.send(
                orch_reply_to,
                ChatMessage(
                    timestamp=datetime.now(timezone.utc),
                    msg_id=uuid4(),
                    content=[TextContent(type="text", text=orch_msg)],
                ),
            )
        return send_ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[
                    TextContent(type="text", text=content),
                    EndSessionContent(type="end-session"),
                ],
            ),
        )

    # Premium: request 0.1 FET payment (send to actual user when via orchestrator)
    if user_text and user_text.strip().lower() in ("premium", "pay", "payment", "i want to pay"):
        payment_recipient = orch_user if orch_user is not None else sender
        await request_payment_from_user(
            ctx, payment_recipient, description="Pay 0.1 FET for a premium HackOverflow answer."
        )
        return

    # Internal reply from specialist: INTERNAL_REPLY|reply_to|session_id|response_text
    if user_text.startswith("INTERNAL_REPLY|"):
        parts = user_text.split("|", 3)
        if len(parts) >= 4:
            reply_to, _session, response_text = parts[1], parts[2], parts[3]
            # If we're in orchestrator mode, forward as ORCH_REPLY to orchestrator
            orch_pending = ctx.storage.get("orch_pending")
            if orch_pending and isinstance(orch_pending, dict):
                o_reply_to = orch_pending.get("reply_to")
                o_user = orch_pending.get("user")
                o_req_id = orch_pending.get("request_id")
                ctx.storage.remove("orch_pending")
                if o_reply_to and o_user is not None and o_req_id:
                    await ctx.send(
                        o_reply_to,
                        ChatMessage(
                            timestamp=datetime.now(timezone.utc),
                            msg_id=uuid4(),
                            content=[TextContent(type="text", text=f"ORCH_REPLY|{o_user}|{o_req_id}|{response_text}")],
                        ),
                    )
                    return
            await ctx.send(
                reply_to,
                ChatMessage(
                    timestamp=datetime.now(timezone.utc),
                    msg_id=uuid4(),
                    content=[
                        TextContent(type="text", text=response_text),
                        EndSessionContent(type="end-session"),
                    ],
                ),
            )
            return

    action, response = run_orchestration(user_text)

    if action == "direct":
        await _send_final(ctx, response)
        return

    if action == "delegate" and SPECIALIST_ADDRESS:
        session_id = str(ctx.session)
        delegate_sender = orch_user if orch_user is not None else sender
        if orch_reply_to and orch_user is not None and orch_request_id is not None:
            ctx.storage.set("orch_pending", {"reply_to": orch_reply_to, "user": orch_user, "request_id": orch_request_id})
        internal_msg = f"INTERNAL_DELEGATE|{delegate_sender}|{session_id}|{user_text}"
        await ctx.send(
            SPECIALIST_ADDRESS,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[TextContent(type="text", text=internal_msg)],
            ),
        )
        return

    # Delegate but no specialist configured — answer directly
    from orchestration import get_direct_response
    fallback = get_direct_response(user_text)
    await _send_final(ctx, fallback)


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"Coordinator received ack from {sender} for {msg.acknowledged_msg_id}")


@signal_proto.on_message(AgentPing)
async def handle_ping(ctx: Context, sender: str, msg: AgentPing):
    ctx.logger.info(f"Coordinator received ping {msg.ping_id} from {msg.source} ({sender})")
    await ctx.send(
        sender,
        build_pong(
            ping_id=msg.ping_id,
            responder=str(coordinator.address),
            detail="coordinator-ok",
        ),
    )


@signal_proto.on_message(AgentPong)
async def handle_pong(ctx: Context, sender: str, msg: AgentPong):
    ctx.logger.info(f"Coordinator received pong {msg.ping_id} from {msg.responder} ({sender})")


@coordinator.on_event("startup")
async def coordinator_startup(ctx: Context):
    if not startup_signal_enabled():
        return
    peers = _coordinator_peers()
    if not peers:
        ctx.logger.info("Coordinator startup signal skipped: no peers configured.")
        return
    for peer in peers:
        ping = build_ping(
            source=str(coordinator.address),
            purpose="startup-handshake",
            detail="coordinator-online",
        )
        await ctx.send(peer, ping)
    ctx.logger.info(f"Coordinator startup handshake sent to {len(peers)} peer(s).")


@coordinator.on_interval(period=heartbeat_period_seconds())
async def coordinator_heartbeat(ctx: Context):
    if not heartbeat_enabled():
        return
    peers = _coordinator_peers()
    if not peers:
        return
    for peer in peers:
        ping = build_ping(
            source=str(coordinator.address),
            purpose="heartbeat",
            detail="coordinator-heartbeat",
        )
        await ctx.send(peer, ping)


coordinator.include(chat_proto, publish_manifest=True)
coordinator.include(signal_proto, publish_manifest=False)
coordinator.include(payment_proto, publish_manifest=False)
set_agent_wallet(coordinator.wallet)

if __name__ == "__main__":
    coordinator.run()
