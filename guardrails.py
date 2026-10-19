"""
Guardrails — verify consequential actions before reporting success.

The main loop records every consequential tool execution (real swaps,
wallet ops, perps, rule changes). When the agent is about to answer the
user, a reviewer pass checks the transcript against the recorded actions:
did the tool actually succeed? does the result contradict the plan?

For executed trades, a direct on-chain/portfolio check is appended to the
conversation so the model can confirm with fresh data, not vibes.

Fail-open philosophy: if the reviewer itself errors, we don't block the
reply — we add a warning note instead. Trading stays available.
"""

import json
import logging

logger = logging.getLogger(__name__)

from config import MISTRAL_API_KEYS, MISTRAL_MODEL


# ============================================================
# Which tools are consequential enough to track
# ============================================================

CONSEQUENTIAL_TOOLS = {
    # Real money / on-chain
    "buy_token", "sell_token", "jupiter_buy", "jupiter_sell",
    "swap_evm_token", "rh_buy", "rh_sell", "rh_mcp_buy", "rh_mcp_sell",
    "place_order", "buy_stock", "sell_stock", "buy_nft", "sell_nft",
    "swap_evm_token", "open_long", "open_short", "close_position",
    "execute_bridge", "transfer_nft", "opensea_list_nft", "opensea_buy_nft",
    "opensea_place_offer",
    "opensea_cancel_listing", "opensea_mint_drop", "opensea_watch_drop", "toggle_copy", "toggle_copy_evm",
    "mint_contract",
    # Wallet / key management
    "generate_wallet", "create_evm_wallet", "new_wallet", "import_evm_wallet",
    "import_solana_wallet",
    "get_private_key", "add_wallet", "remove_wallet", "set_api_key",
    # Automation
    "add_trading_rule", "cancel_trading_rule", "add_dca",
    "add_stop_loss", "add_take_profit",
}

# After a successful trade on these tools, force a portfolio re-check
TRADE_EXECUTION_TOOLS = {
    "buy_token", "sell_token", "jupiter_buy", "jupiter_sell",
    "rh_buy", "rh_sell", "rh_mcp_buy", "rh_mcp_sell", "place_order",
    "buy_stock", "sell_stock", "swap_evm_token",
}


class ActionTracker:
    """Per-turn record of consequential tool calls and their outcomes."""

    def __init__(self):
        self.events = []

    def record(self, tool_name: str, args: dict, result: str):
        if tool_name in CONSEQUENTIAL_TOOLS:
            self.events.append({
                "tool": tool_name,
                "args": args,
                "success": not _looks_failed(result),
                "result": str(result)[:300],
            })

    def has_events(self) -> bool:
        return bool(self.events)

    def summary(self) -> str:
        lines = []
        for e in self.events:
            status = "SUCCESS" if e["success"] else "FAILED"
            lines.append(f"- {e['tool']}({json.dumps(e['args'])[:120]}) -> {status}: {e['result'][:120]}")
        return "\n".join(lines)


def _looks_failed(result) -> bool:
    r = str(result).lower()
    markers = ("error", "failed", "insufficient", "rejected", "timeout",
               "denied", "invalid", "cannot", "unable")
    return any(m in r[:400] for m in markers)


# ============================================================
# Post-trade verification
# ============================================================

def portfolio_check_message() -> str:
    """Build a tool-role message with fresh portfolio state after a trade."""
    try:
        from registry import dispatch_tool
        fresh = dispatch_tool("get_portfolio", {})
        return (
            "[SYSTEM POST-TRADE CHECK — fresh portfolio state]\n"
            + str(fresh)[:800]
        )
    except Exception as e:
        return f"[SYSTEM POST-TRADE CHECK — unavailable: {e}]"


# ============================================================
# Reviewer pass
# ============================================================

_REVIEW_PROMPT = """You are a verification reviewer for a crypto trading agent.

Actions taken this turn:
{actions}

Final draft reply to the user:
{draft}

Question: does the draft make any CLAIM that contradicts the recorded
action results — e.g. claiming a trade succeeded when the result shows a
failure, quoting wrong amounts, or promising follow-ups nothing performed?

Reply with exactly one of:
OK — the draft is consistent with the actions
FLAG: <one short sentence naming the contradiction>"""


def review_reply(events: ActionTracker, draft: str) -> str:
    """
    Check the draft reply against recorded actions. Returns the draft
    unchanged if OK, or a flagged/adjusted version. Fail-open.
    """
    if not events.has_events():
        return draft

    # Cheap structural check first: draft claims success but a tracked
    # action failed → flag without an API call.
    failed = [e for e in events.events if not e["success"]]
    if failed:
        draft_lower = draft.lower()
        claims_success = any(
            w in draft_lower for w in ("success", "completed", "done", "executed", "✅")
        )
        if claims_success and not _draft_acknowledges_failure(draft_lower, failed):
            note = ", ".join(f"{e['tool']}" for e in failed)
            return (
                f"{draft}\n\n⚠️ Note: the following action(s) did not complete: "
                f"{note}. Double-check before acting."
            )

    # LLM review for the ambiguous middle ground — only on real activity
    if not MISTRAL_API_KEYS:
        return draft
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=MISTRAL_API_KEYS[0],
            base_url="https://api.mistral.ai/v1",
            max_retries=0,
            timeout=10.0,
        )
        resp = client.chat.completions.create(
            model=MISTRAL_MODEL,
            messages=[{
                "role": "user",
                "content": _REVIEW_PROMPT.format(
                    actions=events.summary()[:1500],
                    draft=draft[:2000],
                ),
            }],
            max_tokens=150,
            temperature=0,
        )
        verdict = resp.choices[0].message.content.strip()
        if verdict.upper().startswith("OK"):
            return draft
        if verdict.upper().startswith("FLAG"):
            return f"{draft}\n\n⚠️ Reviewer: {verdict[5:].strip()}"
        return draft
    except Exception as e:
        logger.warning(f"Reviewer pass unavailable ({e}); passing draft through")
        return draft


def _draft_acknowledges_failure(draft_lower: str, failed_events) -> bool:
    """Did the draft already admit the failure? Avoid double-flagging."""
    ack_words = ("did not", "couldn't", "could not", "failed", "unable",
                 "not completed", "error", "unsuccessful")
    return any(w in draft_lower for w in ack_words)
