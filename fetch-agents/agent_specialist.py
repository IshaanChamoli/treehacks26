"""
HackOverflow Specialist uAgent — ASI:One compatible.
Expert agent for Q&A and code help; receives delegated queries from the coordinator.
"""
import os
from collections import Counter, deque
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

SPECIALIST_SEED = os.getenv("AGENT_SPECIALIST_SEED", "hackoverflow-specialist-agent-seed-phrase")
PORT = int(os.getenv("AGENT_PORT_SPECIALIST", "8102"))
COORDINATOR_ADDRESS = os.getenv("COORDINATOR_AGENT_ADDRESS", "").strip()

specialist = Agent(
    name="hackoverflow_specialist",
    seed=SPECIALIST_SEED,
    port=PORT,
    mailbox=True,  # Required: mailbox is the only method for Agentverse/ASI:One
    network=agent_network(),
    registration_policy=api_only_registration_policy(),
    publish_agent_details=True,
)

chat_proto = Protocol(spec=chat_protocol_spec)
signal_proto = Protocol(name="hackoverflow_signals", version="1.0.0")

_started_at = datetime.now(timezone.utc)
_metrics = {
    "in_total": 0,
    "out_total": 0,
    "in_by_type": Counter(),
    "out_by_type": Counter(),
    "senders": Counter(),
    "destinations": Counter(),
    "recent_in": deque(maxlen=10),
    "recent_out": deque(maxlen=10),
}


def _specialist_peers() -> list[str]:
    peers: list[str] = []
    if COORDINATOR_ADDRESS:
        peers.append(COORDINATOR_ADDRESS)
    return peers


def _preview(text: str, limit: int = 140) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


def _record_in(sender: str, msg_type: str, preview_text: str = "") -> None:
    _metrics["in_total"] += 1
    _metrics["in_by_type"][msg_type] += 1
    if sender:
        _metrics["senders"][sender] += 1
    _metrics["recent_in"].append(f"{msg_type} from {sender}: {_preview(preview_text)}")


def _record_out(destination: str, msg_type: str, preview_text: str = "") -> None:
    _metrics["out_total"] += 1
    _metrics["out_by_type"][msg_type] += 1
    if destination:
        _metrics["destinations"][destination] += 1
    _metrics["recent_out"].append(f"{msg_type} to {destination}: {_preview(preview_text)}")


async def _send_payload(ctx: Context, destination: str, payload, msg_type: str, preview_text: str = ""):
    _record_out(destination, msg_type, preview_text)
    await ctx.send(destination, payload)


def _looks_like_traffic_query(query: str) -> bool:
    q = (query or "").lower()
    markers = (
        "messages in",
        "messages out",
        "message in",
        "message out",
        "traffic",
        "heartbeat",
        "status",
        "health",
        "inspect",
    )
    return any(m in q for m in markers)


def _top_counter_lines(counter: Counter, max_items: int = 5) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{k} ({v})" for k, v in counter.most_common(max_items))


def _traffic_report() -> str:
    uptime_seconds = int((datetime.now(timezone.utc) - _started_at).total_seconds())
    recent_in = list(_metrics["recent_in"])
    recent_out = list(_metrics["recent_out"])
    recent_in_line = " | ".join(recent_in[-3:]) if recent_in else "none"
    recent_out_line = " | ".join(recent_out[-3:]) if recent_out else "none"
    return (
        "HackOverflow Specialist live traffic report\n"
        f"- Address: {specialist.address}\n"
        f"- Uptime: {uptime_seconds}s\n"
        f"- Messages in: {_metrics['in_total']}\n"
        f"- Messages out: {_metrics['out_total']}\n"
        f"- Incoming types: {_top_counter_lines(_metrics['in_by_type'])}\n"
        f"- Outgoing types: {_top_counter_lines(_metrics['out_by_type'])}\n"
        f"- Top senders: {_top_counter_lines(_metrics['senders'])}\n"
        f"- Top destinations: {_top_counter_lines(_metrics['destinations'])}\n"
        f"- Recent in: {recent_in_line}\n"
        f"- Recent out: {recent_out_line}"
    )


def _general_answer(user_query: str) -> str:
    return (
        f"I am HackOverflow specialist. You asked: \"{user_query}\"\n\n"
        "Quick help:\n"
        "1) Share exact error + stack trace\n"
        "2) Share minimal code snippet\n"
        "3) I will return root cause + fix + verify steps"
    )


def _answer_query(user_query: str) -> str:
    if _looks_like_traffic_query(user_query):
        return _traffic_report()
    return _general_answer(user_query)


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    ctx.logger.info(f"Specialist received message from {sender}")
    await _send_payload(
        ctx,
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
        msg_type="chat_ack",
        preview_text="ack",
    )

    text_parts = []
    for item in msg.content:
        if isinstance(item, TextContent):
            text_parts.append(item.text)
    user_query = " ".join(text_parts).strip() if text_parts else ""
    _record_in(sender, "chat_message", user_query)

    # Internal delegation from coordinator: INTERNAL_DELEGATE|reply_to_address|session_id|query
    if user_query.startswith("INTERNAL_DELEGATE|"):
        parts = user_query.split("|", 3)
        if len(parts) >= 4:
            _reply_to, _session_id, delegated_query = parts[1], parts[2], parts[3]
            specialist_answer = _answer_query(delegated_query)
            internal_reply = f"INTERNAL_REPLY|{_reply_to}|{_session_id}|{specialist_answer}"
            await _send_payload(
                ctx,
                sender,
                ChatMessage(
                    timestamp=datetime.now(timezone.utc),
                    msg_id=uuid4(),
                    content=[
                        TextContent(type="text", text=internal_reply),
                        EndSessionContent(type="end-session"),
                    ],
                ),
                msg_type="chat_internal_reply",
                preview_text=specialist_answer,
            )
            return

    # Direct user message (e.g. from ASI:One)
    response = _answer_query(user_query)

    await _send_payload(
        ctx,
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=response),
                EndSessionContent(type="end-session"),
            ],
        ),
        msg_type="chat_response",
        preview_text=response,
    )


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"Specialist received ack from {sender} for {msg.acknowledged_msg_id}")
    _record_in(sender, "chat_ack", str(msg.acknowledged_msg_id))


@signal_proto.on_message(AgentPing)
async def handle_ping(ctx: Context, sender: str, msg: AgentPing):
    ctx.logger.info(f"Specialist received ping {msg.ping_id} from {msg.source} ({sender})")
    _record_in(sender, "signal_ping", msg.detail)
    await _send_payload(
        ctx,
        sender,
        build_pong(
            ping_id=msg.ping_id,
            responder=str(specialist.address),
            detail="specialist-ok",
        ),
        msg_type="signal_pong",
        preview_text=f"pong for {msg.ping_id}",
    )


@signal_proto.on_message(AgentPong)
async def handle_pong(ctx: Context, sender: str, msg: AgentPong):
    ctx.logger.info(f"Specialist received pong {msg.ping_id} from {msg.responder} ({sender})")
    _record_in(sender, "signal_pong", msg.detail)


@specialist.on_event("startup")
async def specialist_startup(ctx: Context):
    if not startup_signal_enabled():
        return
    peers = _specialist_peers()
    if not peers:
        ctx.logger.info("Specialist startup signal skipped: no peers configured.")
        return
    for peer in peers:
        ping = build_ping(
            source=str(specialist.address),
            purpose="startup-handshake",
            detail="specialist-online",
        )
        await _send_payload(
            ctx,
            peer,
            ping,
            msg_type="signal_ping",
            preview_text=f"startup {ping.ping_id}",
        )
    ctx.logger.info(f"Specialist startup handshake sent to {len(peers)} peer(s).")


@specialist.on_interval(period=heartbeat_period_seconds())
async def specialist_heartbeat(ctx: Context):
    if not heartbeat_enabled():
        return
    peers = _specialist_peers()
    if not peers:
        return
    for peer in peers:
        ping = build_ping(
            source=str(specialist.address),
            purpose="heartbeat",
            detail="specialist-heartbeat",
        )
        await _send_payload(
            ctx,
            peer,
            ping,
            msg_type="signal_ping",
            preview_text=f"heartbeat {ping.ping_id}",
        )


specialist.include(chat_proto, publish_manifest=True)
specialist.include(signal_proto, publish_manifest=False)

if __name__ == "__main__":
    specialist.run()
