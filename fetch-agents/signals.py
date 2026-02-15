"""
Shared signal models for agent-to-agent liveness and diagnostics traffic.
"""
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Model


class AgentPing(Model):
    ping_id: str
    source: str
    purpose: str = "heartbeat"
    detail: str = ""
    created_at: str


class AgentPong(Model):
    ping_id: str
    responder: str
    status: str = "ok"
    detail: str = ""
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_ping(source: str, purpose: str = "heartbeat", detail: str = "") -> AgentPing:
    return AgentPing(
        ping_id=str(uuid4()),
        source=source,
        purpose=purpose,
        detail=detail,
        created_at=_now_iso(),
    )


def build_pong(
    ping_id: str,
    responder: str,
    status: str = "ok",
    detail: str = "",
) -> AgentPong:
    return AgentPong(
        ping_id=ping_id,
        responder=responder,
        status=status,
        detail=detail,
        created_at=_now_iso(),
    )

