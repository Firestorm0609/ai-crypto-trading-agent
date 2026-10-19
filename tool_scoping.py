"""
Tool Scoping — send the model only the tools it plausibly needs.

Why: telegram_bot used to send all 162 tool schemas to Mistral on every
call. Mistral-small degrades when choosing among that many options, and
the token burn is enormous on free-tier keys.

How: tools are grouped into families. For each user message we select a
small set of families based on cheap, fast heuristics (a Mistral "nano"
classifier with regex fallback, plus always-on core tools). The model
sees ~25-40 schemas instead of 162.

Fail-safe: if anything in the pipeline errors, we fall back to ALL tools.
"""

import json
import logging
import re
import urllib.request

logger = logging.getLogger(__name__)

from config import MISTRAL_API_KEYS


# ============================================================
# Tool families — every registered tool name must live somewhere.
# Order doesn't matter; membership does.
# ============================================================

TOOL_FAMILIES = {
    "market_data": {
        "get_price", "get_top_coins", "search_coin", "get_trending",
        "get_fear_greed", "get_crypto_news", "get_sol_price",
        "get_token_price", "get_uniswap_price", "get_uniswap_pool",
        "get_top_pools", "get_token_info", "get_sol_trending",
        "search_sol_token", "scan_coingecko_trending",
        "get_prediction_market_info", "evm_token_info",
    },
    "portfolio": {
        "get_portfolio", "get_trade_history", "get_stats",
        "get_performance", "get_performance_chart", "get_real_trade_journal",
        "get_risk_status", "export_trades",
        "rh_portfolio", "rh_account", "rh_buying_power", "rh_orders",
        "rh_mcp_portfolio", "rh_mcp_quote", "get_nft_portfolio",
        "get_multichain_portfolio", "get_evm_balance", "get_tx_history",
        "check_sol_balance", "get_wallet_balance", "get_wallet_address",
        "evm_token_info",
    },
    "paper_trading": {
        "buy", "sell", "add_limit_order", "get_limit_orders",
        "add_stop_loss", "add_take_profit", "add_dca", "reset_portfolio",
        "smart_dca",
    },
    "real_trading": {
        "buy_token", "sell_token", "jupiter_buy", "jupiter_sell",
        "swap_evm_token", "rh_buy", "rh_sell", "rh_mcp_buy", "rh_mcp_sell",
        "place_order", "rh_auth", "buy_stock", "sell_stock",
        "get_available_stocks", "get_stock_price", "get_stock_info",
        "get_swap_quote", "get_sol_swap_quote", "get_bridge_quote",
        "buy_nft", "sell_nft", "estimate_gas", "rh_quote", "rh_products",
        "rh_search", "rh_chain_check",
        "execute_bridge", "lifi_quote", "lifi_token_price", "lifi_tokens",
    },
    "risk_scanning": {
        "scan_token", "scan_sol_token", "rug_check", "rugcheck_report", "run_self_check", "get_gas_tracker",
        "get_whale_activity", "get_onchain_analytics", "get_token_metadata",
        "predict_price", "get_social_sentiment", "get_news_sentiment",
        "scan_pumpfun_search", "get_nft_floor", "check_airdrop_eligibility",
        "get_upcoming_airdrops",
    },
    "alerts_rules": {
        "add_alert", "get_alerts", "cancel_alert",
        "add_trading_rule", "get_trading_rules", "cancel_trading_rule",
    },
    "perps": {
        "get_perps_platforms", "get_perps_pairs", "get_perps_quote",
        "open_long", "open_short", "close_position",
        "get_perps_risk_guide",
    },
    "trend_research": {
        "web_search", "scrape_url", "read_url", "search_twitter",
        "github_search_repos", "github_get_repo", "github_get_readme",
        "github_search_issues", "detect_viral_trend", "get_trend_alerts",
        "scan_all_viral", "scan_pumpfun_new", "scan_pumpfun_top",
    },
    "wallets": {
        "generate_wallet", "create_evm_wallet", "new_wallet", "import_evm_wallet",
        "import_solana_wallet",
        "set_api_key", "list_api_keys",
        "add_wallet", "remove_wallet", "list_wallets", "track_wallet",
        "get_private_key", "sign_message", "create_deposit_link",
        "get_fiat_onramp_info", "get_hardware_wallet_info",
        "watch_wallet", "unwatch_wallet", "list_watched", "toggle_copy",
        "watch_wallet_evm", "unwatch_wallet_evm", "list_watched_evm", "toggle_copy_evm",
        "sync_alchemy_webhook",
    },
    "nfts_mints": {
        "mint_nft", "create_collection", "get_popular_nfts",
        "get_upcoming_mints", "transfer_nft", "get_nft_portfolio",
        "get_nft_floor", "opensea_floor", "opensea_best_listings",
        "opensea_holdings", "opensea_list_nft", "opensea_buy_nft",
        "opensea_top_offer", "opensea_place_offer",
        "opensea_cancel_listing", "opensea_drops", "opensea_mint_drop",
        "opensea_eligibility", "opensea_watch_drop", "opensea_mint_queue",
        "opensea_free_mints", "scan_contract_mint", "mint_contract",
        "opensea_unwatch_drop",
    },
    "memory": {
        "remember_preference", "get_memory",
    },
    "meta": {
        "create_plan", "update_plan", "get_current_plan",
        "suggest_followups", "verify_action", "ask_user",
    },
    "coding": {
        "list_files", "read_file", "write_file", "edit_file",
        "code_search", "find_function", "find_class",
        "find_all_references", "multi_file_edit", "batch_read_files",
        "run_safe_command", "run_terminal_command", "restart_bot",
        "git_status", "git_diff", "git_log", "git_commit",
        "create_todos", "update_todos", "get_todos",
    },
}

# Always included: cheap, tiny schemas the agent should never lose.
ALWAYS_ON = {"memory", "meta"}

# Delegate is always available too (defined in delegation.py)
DELEGATE_TOOL_NAME = "delegate"


# ============================================================
# Keyword routing — zero-cost, works offline
# ============================================================

FAMILY_KEYWORDS = {
    "market_data": [
        "price", "how much", "worth", "cost", "top coins", "top 10",
        "trending", "market cap", "fear", "greed", "rate", "quote",
    ],
    "portfolio": [
        "portfolio", "holdings", "my balance", "position", "pnl", "p&l",
        "history", "trades", "stats", "performance", "buying power",
    ],
    "paper_trading": [
        "buy", "sell", "purchase", "limit order", "stop loss",
        "take profit", "dca", "paper trade",
    ],
    "real_trading": [
        "swap", "jupiter", "uniswap", "robinhood", "execute", "real money",
        "bridge", "stock", "on-chain buy",
    ],
    "risk_scanning": [
        "scan", "rug", "safe", "scam", "risk", "honeypot", "audit",
        "whale", "gas", "on-chain", "sentiment", "honeypot check",
    ],
    "alerts_rules": [
        "alert", "notify me", "rule", "automate", "watch", "trigger",
        "when price",
    ],
    "perps": [
        "perp", "leverage", "long", "short", "futures", "margin",
    ],
    "trend_research": [
        "search", "look up", "news", "latest", "what's happening",
        "research", "find out", "google", "check the web", "github",
        "twitter", "viral", "pump.fun", "pumpfun",
    ],
    "wallets": [
        "wallet", "new address", "private key", "seed", "onramp",
        "deposit", "fund", "watch", "copytrade", "copy",
    ],
    "nfts_mints": [
        "nft", "mint", "collection", "floor", "opensea", "listing",
        "drop", "snipe", "allowlist",
    ],
    "coding": [
        "fix", "bug", "edit", "code", "file", "refactor", "restart",
        "git", "commit", "function", "error in",
    ],
}

# Words that mean the user is asking about trading something, so both
# market data and paper trading are relevant.
_TRADE_HINT = re.compile(
    r"\b(buy|sell|trade|swap|purchase|order)\b", re.IGNORECASE
)


_EVM_ADDR_RE = None  # compiled lazily (module import cost)

def _families_from_keywords(message: str) -> set:
    """Map message text to tool families via keyword matching."""
    global _EVM_ADDR_RE
    msg = message.lower()
    selected = set()
    for family, keywords in FAMILY_KEYWORDS.items():
        for kw in keywords:
            if kw in msg:
                selected.add(family)
                break

    # Buying/selling implies wanting price context too
    if selected & {"paper_trading", "real_trading"} or _TRADE_HINT.search(message):
        selected.add("market_data")

    # Any EVM address in the message → the agent must be able to identify
    # what that contract is (this is exactly how 'identify 0x…' starved the
    # model of evm_token_info and it answered 'cannot identify').
    if _EVM_ADDR_RE is None:
        import re as _re
        _EVM_ADDR_RE = _re.compile(r"\b0x[0-9a-fA-F]{40}\b")
    if _EVM_ADDR_RE.search(message):
        selected.add("market_data")
        selected.add("real_trading")

    return selected


# ============================================================
# LLM classifier — catches phrasing regexes miss
# ============================================================

_CLASSIFIER_MODEL = "mistral-small-latest"
_CLASSIFIER_TIMEOUT = 3.0  # seconds; if slower, regex fallback wins anyway

_CLASSIFY_PROMPT = """Classify which tool families a user message needs.
Families: {families}
Reply with ONLY a JSON array of family names, e.g. ["market_data","risk_scanning"]
Message: {message}"""


def _families_from_llm(message: str) -> set:
    """Ask a tiny LLM call which families apply. Returns set (possibly empty)."""
    if not MISTRAL_API_KEYS:
        return set()
    try:
        prompt = _CLASSIFY_PROMPT.format(
            families=", ".join(sorted(TOOL_FAMILIES)),
            message=message[:500],
        )
        req = urllib.request.Request(
            "https://api.mistral.ai/v1/chat/completions",
            data=json.dumps({
                "model": _CLASSIFIER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 60,
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MISTRAL_API_KEYS[0]}",
            },
        )
        with urllib.request.urlopen(req, timeout=_CLASSIFIER_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"].strip()
        # Tolerate ```json fences etc.
        content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
        families = set(json.loads(content))
        return {f for f in families if f in TOOL_FAMILIES}
    except Exception as e:
        logger.debug(f"LLM classifier unavailable ({e}); using regex only")
        return set()


# ============================================================
# Public API
# ============================================================

def select_tools(message: str, all_tools: list, use_llm: bool = True) -> list:
    """
    Pick the tool schemas relevant to this message.

    Returns a list of OpenAI-format tool definition dicts. Never returns
    an empty list — falls back to all_tools on any failure.
    """
    try:
        selected_families = _families_from_keywords(message)
        if use_llm:
            selected_families |= _families_from_llm(message)
        selected_families |= ALWAYS_ON
        selected_families.add("delegation")  # delegate tool family marker

        if not selected_families - ALWAYS_ON - {"delegation"}:
            # Nothing matched — be safe, show everything
            return all_tools

        allow = set()
        for fam in selected_families:
            allow |= TOOL_FAMILIES.get(fam, set())

        scoped = [
            t for t in all_tools
            if t.get("function", {}).get("name") in allow
        ]

        # Add the delegate tool (always allowed; defined in delegation.py)
        try:
            from delegation import DELEGATE_TOOL_DEF
            if DELEGATE_TOOL_DEF not in scoped:
                scoped.append(DELEGATE_TOOL_DEF)
        except Exception:
            pass

        # Sanity: if scoping produced something absurdly small, widen
        if len(scoped) < 5:
            return all_tools

        return scoped
    except Exception as e:
        logger.warning(f"Tool scoping failed ({e}); using all tools")
        return all_tools


def families_for_message(message: str) -> list:
    """Debug helper: which families would be selected (no LLM call)."""
    fams = _families_from_keywords(message) | ALWAYS_ON
    return sorted(fams)
