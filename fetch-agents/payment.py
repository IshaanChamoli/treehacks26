"""
Agent Payment Protocol (FET) for monetization.
Request 0.1 FET for premium answers; verify on-chain when cosmpy is available.
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Context, Protocol
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
    payment_protocol_spec,
)
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent, EndSessionContent

from shared import create_text_chat

_agent_wallet = None


def set_agent_wallet(wallet):
    global _agent_wallet
    _agent_wallet = wallet


payment_proto = Protocol(spec=payment_protocol_spec, role="seller")

FET_FUNDS = Funds(currency="FET", amount="0.1", payment_method="fet_direct")
ACCEPTED_FUNDS = [FET_FUNDS]


def _verify_fet_payment(transaction_id: str, expected_amount_fet: str, sender_fet_address: str, logger) -> bool:
    """Verify FET payment on-chain if cosmpy is available; else accept for demo."""
    try:
        from cosmpy.aerial.client import LedgerClient, NetworkConfig
        testnet = os.getenv("FET_USE_TESTNET", "true").lower() == "true"
        network_config = NetworkConfig.fetchai_stable_testnet() if testnet else NetworkConfig.fetchai_mainnet()
        ledger = LedgerClient(network_config)
        expected_micro = int(float(expected_amount_fet) * 10**18)
        logger.info(f"Verifying payment of {expected_amount_fet} FET from {sender_fet_address}")
        tx_response = ledger.query_tx(transaction_id)
        if not tx_response.is_successful():
            logger.error(f"Transaction {transaction_id} was not successful")
            return False
        denom = "atestfet" if testnet else "afet"
        expected_recipient = str(_agent_wallet.address())
        recipient_found = amount_found = sender_found = False
        for event_type, event_attrs in tx_response.events.items():
            if event_type == "transfer":
                if event_attrs.get("recipient") == expected_recipient:
                    recipient_found = True
                if event_attrs.get("sender") == sender_fet_address:
                    sender_found = True
                amount_str = event_attrs.get("amount", "")
                if amount_str and amount_str.endswith(denom):
                    try:
                        amount_value = int(amount_str.replace(denom, ""))
                        if amount_value >= expected_micro:
                            amount_found = True
                    except Exception:
                        pass
        if recipient_found and amount_found and sender_found:
            logger.info(f"Payment verified: {transaction_id}")
            return True
        logger.error(f"Payment verification failed - recipient:{recipient_found}, amount:{amount_found}, sender:{sender_found}")
        return False
    except ImportError:
        logger.warning("cosmpy not installed; accepting payment for demo (set cosmpy for production)")
        return bool(transaction_id and sender_fet_address)
    except Exception as e:
        logger.error(f"FET payment verification failed: {e}")
        return False


async def request_payment_from_user(ctx: Context, user_address: str, description: str | None = None):
    """Send a payment request for 0.1 FET (premium answer)."""
    metadata = {}
    if _agent_wallet:
        metadata["provider_agent_wallet"] = str(_agent_wallet.address())
        metadata["fet_network"] = "stable-testnet" if os.getenv("FET_USE_TESTNET", "true").lower() == "true" else "mainnet"
    metadata["content"] = description or "Pay 0.1 FET for a premium HackOverflow answer."
    payment_request = RequestPayment(
        accepted_funds=ACCEPTED_FUNDS,
        recipient=str(_agent_wallet.address()) if _agent_wallet else "unknown",
        deadline_seconds=300,
        reference=str(uuid4()),
        description=description or "Premium answer: 0.1 FET",
        metadata=metadata,
    )
    ctx.logger.info(f"Sending payment request to {user_address}")
    await ctx.send(user_address, payment_request)


@payment_proto.on_message(CommitPayment)
async def handle_commit_payment(ctx: Context, sender: str, msg: CommitPayment):
    ctx.logger.info(f"Received payment commitment from {sender}")
    payment_verified = False
    if msg.funds.payment_method == "fet_direct" and msg.funds.currency == "FET":
        buyer_fet = None
        if isinstance(msg.metadata, dict):
            buyer_fet = msg.metadata.get("buyer_fet_wallet") or msg.metadata.get("buyer_fet_address")
        if not buyer_fet:
            ctx.logger.error("Missing buyer_fet_wallet in CommitPayment.metadata")
        elif _agent_wallet:
            payment_verified = _verify_fet_payment(
                msg.transaction_id,
                msg.funds.amount,
                buyer_fet,
                ctx.logger,
            )
    if payment_verified:
        await ctx.send(sender, CompletePayment(transaction_id=msg.transaction_id))
        premium_response = (
            "Thank you for your payment. Here is your premium answer: "
            "HackOverflow agents are deployed on Agentverse and discoverable via ASI:One. "
            "Use the Chat Protocol and optional Payment Protocol for monetization. "
            "Tree Hacks 2026 — Fetch.ai Innovation Lab."
        )
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[
                    TextContent(type="text", text=premium_response),
                    EndSessionContent(type="end-session"),
                ],
            ),
        )
    else:
        await ctx.send(
            sender,
            CancelPayment(transaction_id=msg.transaction_id, reason="Payment verification failed"),
        )


@payment_proto.on_message(RejectPayment)
async def handle_reject_payment(ctx: Context, sender: str, msg: RejectPayment):
    ctx.logger.info(f"Payment rejected by {sender}: {msg.reason}")
    await ctx.send(
        sender,
        create_text_chat("Payment declined. You can still use free chat. Say 'premium' anytime to try again."),
    )
