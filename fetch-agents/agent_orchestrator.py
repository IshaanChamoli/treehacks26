"""
Orchestrator agent — single entry point that organizes all conversations and routes to
coordinator, specialist, or user-connected agents. People can connect their own agents
via CONNECTED_AGENTS (handle:address,handle2:address2).
"""
import os
import re
import uuid
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
from signals import AgentPing, AgentPong, build_ping, build_pong
load_dotenv()

ORCHESTRATOR_SEED = os.getenv("AGENT_ORCHESTRATOR_SEED", "hackoverflow-orchestrator-agent-seed-phrase")
PORT = int(os.getenv("AGENT_PORT_ORCHESTRATOR", "8100"))
COORDINATOR_ADDRESS = os.getenv("COORDINATOR_AGENT_ADDRESS", "").strip()

# CONNECTED_AGENTS=@mybot:agent1q...,@helper:agent1q...
def _load_connected_agents() -> dict[str, str]:
    raw = os.getenv("CONNECTED_AGENTS", "").strip()
    out = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        handle, addr = part.split(":", 1)
        handle = handle.strip().lower().lstrip("@")
        addr = addr.strip()
        if handle and addr:
            out[handle] = addr
    return out


CONNECTED_AGENTS = _load_connected_agents()

orchestrator = Agent(
    name="hackoverflow_orchestrator",
    seed=ORCHESTRATOR_SEED,
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


def _parse_route_to_handle(text: str) -> tuple[str | None, str]:
    """If user said 'ask @handle ...' or '@handle ...' or 'to @handle: ...', return (handle, rest). Else (None, text)."""
    text = (text or "").strip()
    # @handle or @handle message
    m = re.match(r"^(?:ask\s+)?@(\w+)\s*[:\s]*(.*)$", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).lower(), (m.group(2) or "").strip()
    m = re.match(r"^to\s+@(\w+)\s*[:\s]*(.*)$", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).lower(), (m.group(2) or "").strip()
    if text.startswith("@"):
        idx = text.find(" ")
        if idx != -1:
            return text[1:idx].lower(), text[idx + 1 :].strip()
        return text[1:].lower(), ""
    return None, text


# ORCH_REPLY|user_address|request_id|response_text  (so we can forward to user)
def _is_orch_reply(text: str) -> bool:
    return text.startswith("ORCH_REPLY|")


def _parse_orch_reply(text: str) -> tuple[str, str, str] | None:
    parts = text.split("|", 3)
    if len(parts) < 4:
        return None
    return parts[1], parts[2], parts[3]  # user_addr, request_id, response_text


def _orchestrator_peers() -> list[str]:
    peers: list[str] = []
    if COORDINATOR_ADDRESS:
        peers.append(COORDINATOR_ADDRESS)
    for addr in CONNECTED_AGENTS.values():
        if addr and addr not in peers:
            peers.append(addr)
    return peers


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    ctx.logger.info(f"Orchestrator received message from {sender}")
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )

    user_text = _extract_text(msg)

    # Reply from coordinator or connected agent: forward to user
    if _is_orch_reply(user_text):
        parsed = _parse_orch_reply(user_text)
        if parsed:
            user_addr, request_id, response_text = parsed
            await ctx.send(
                user_addr,
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
    # Coordinator sometimes sends plain ChatMessage (e.g. payment success); forward to pending user
    if COORDINATOR_ADDRESS and sender == COORDINATOR_ADDRESS:
        pending = ctx.storage.get("pending_coordinator_user")
        if pending:
            ctx.storage.remove("pending_coordinator_user")
            await ctx.send(
                pending,
                ChatMessage(
                    timestamp=datetime.now(timezone.utc),
                    msg_id=uuid4(),
                    content=[
                        TextContent(type="text", text=user_text),
                        EndSessionContent(type="end-session"),
                    ],
                ),
            )
            return
    else:
        # Check if sender is a connected agent (they replied with plain text)
        for handle, addr in CONNECTED_AGENTS.items():
            if addr == sender:
                pending = ctx.storage.get("orch_pending") or {}
                reply_to = pending.get("reply_to")
                if reply_to:
                    ctx.storage.remove("orch_pending")
                    await ctx.send(
                        reply_to,
                        ChatMessage(
                            timestamp=datetime.now(timezone.utc),
                            msg_id=uuid4(),
                            content=[
                                TextContent(type="text", text=user_text),
                                EndSessionContent(type="end-session"),
                            ],
                        ),
                    )
                    return
                break

    # Route: @handle or default to coordinator
    handle, message_for_agent = _parse_route_to_handle(user_text)
    request_id = str(uuid.uuid4())
    session_id = str(ctx.session)
    orchestrator_addr = str(orchestrator.address)

    if handle and message_for_agent and handle in CONNECTED_AGENTS:
        target_addr = CONNECTED_AGENTS[handle]
        # Store so we can forward reply (if they use ORCH_REPLY we don't need this; if plain reply we use pending)
        ctx.storage.set("orch_pending", {"reply_to": sender})
        orch_msg = f"ORCH_DELEGATE|{orchestrator_addr}|{sender}|{session_id}|{request_id}|{message_for_agent}"
        await ctx.send(
            target_addr,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[TextContent(type="text", text=orch_msg)],
            ),
        )
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[
                    TextContent(type="text", text=f"Forwarded to @{handle}. Waiting for response."),
                    EndSessionContent(type="end-session"),
                ],
            ),
        )
        return

    if handle and handle not in CONNECTED_AGENTS:
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[
                    TextContent(
                        type="text",
                        text=f"Unknown agent @{handle}. Connected: {', '.join('@' + h for h in CONNECTED_AGENTS) or 'none'}. Just message without @ to use the default flow.",
                    ),
                    EndSessionContent(type="end-session"),
                ],
            ),
        )
        return
    # Default: send to coordinator (ORCH_DELEGATE so coordinator replies with ORCH_REPLY)
    if not COORDINATOR_ADDRESS:
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[
                    TextContent(type="text", text="No coordinator configured. Set COORDINATOR_AGENT_ADDRESS in .env."),
                    EndSessionContent(type="end-session"),
                ],
            ),
        )
        return
    ctx.storage.set("pending_coordinator_user", sender)
    orch_delegate = f"ORCH_DELEGATE|{orchestrator_addr}|{sender}|{session_id}|{request_id}|{user_text}"
    await ctx.send(
        COORDINATOR_ADDRESS,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[TextContent(type="text", text=orch_delegate)],
        ),
    )


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"Orchestrator received ack from {sender}")


@signal_proto.on_message(AgentPing)
async def handle_ping(ctx: Context, sender: str, msg: AgentPing):
    ctx.logger.info(f"Orchestrator received ping {msg.ping_id} from {msg.source} ({sender})")
    await ctx.send(
        sender,
        build_pong(
            ping_id=msg.ping_id,
            responder=str(orchestrator.address),
            detail="orchestrator-ok",
        ),
    )


@signal_proto.on_message(AgentPong)
async def handle_pong(ctx: Context, sender: str, msg: AgentPong):
    ctx.logger.info(f"Orchestrator received pong {msg.ping_id} from {msg.responder} ({sender})")


@orchestrator.on_event("startup")
async def orchestrator_startup(ctx: Context):
    if not startup_signal_enabled():
        return
    peers = _orchestrator_peers()
    if not peers:
        ctx.logger.info("Orchestrator startup signal skipped: no peers configured.")
        return
    for peer in peers:
        ping = build_ping(
            source=str(orchestrator.address),
            purpose="startup-handshake",
            detail="orchestrator-online",
        )
        await ctx.send(peer, ping)
    ctx.logger.info(f"Orchestrator startup handshake sent to {len(peers)} peer(s).")


@orchestrator.on_interval(period=heartbeat_period_seconds())
async def orchestrator_heartbeat(ctx: Context):
    if not heartbeat_enabled():
        return
    peers = _orchestrator_peers()
    if not peers:
        return
    for peer in peers:
        ping = build_ping(
            source=str(orchestrator.address),
            purpose="heartbeat",
            detail="orchestrator-heartbeat",
        )
        await ctx.send(peer, ping)


orchestrator.include(chat_proto, publish_manifest=True)
orchestrator.include(signal_proto, publish_manifest=False)

if __name__ == "__main__":
    orchestrator.run()
