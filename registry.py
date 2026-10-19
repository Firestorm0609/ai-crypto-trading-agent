"""
Unified Tool Registry — single source of truth for all agent tools.

Before: telegram_bot.py, test_agent.py, agent_loop.py, multi_agent.py each
hand-merged 15+ tool lists and re-implemented dispatch. A new tool module
had to be wired into every one of them.

Now: every agent imports TOOLS (definitions) and dispatch_tool (executor).

Precedence order matters: the first map containing a tool name wins.
  solana (hardcoded) > robinhood_mcp > nft > perps > stocks > robinhood >
  multichain > file > auto_trading > super > uniswap > jupiter > swap >
  trend > web > agent_tools > full_agent_tools > memory > all_tools
"""

import logging

logger = logging.getLogger(__name__)

from all_tools import ALL_TOOLS, TOOL_MAP as CORE_TOOL_MAP
from solana_tools import SOLANA_TOOLS, execute_solana_tool
from multichain_tools import MULTICHAIN_TOOLS, MULTICHAIN_TOOL_MAP
from robinhood_tools import ROBINHOOD_TOOLS, ROBINHOOD_TOOL_MAP
from tokenized_stocks import STOCK_TOOLS, STOCK_TOOL_MAP
from nft_tools import NFT_TOOLS, NFT_TOOL_MAP
from auto_trading_rules import AUTO_TRADING_TOOLS, execute_auto_trading_tool
from perps_tools import PERPS_TOOLS, PERPS_TOOL_MAP
from robinhood_mcp import RH_MCP_TOOLS, RH_MCP_TOOL_MAP
from file_tools import FILE_TOOLS, execute_file_tool
from memory import MEMORY_TOOLS, MEMORY_TOOL_MAP, set_current_user
from super_tools import SUPER_TOOLS, SUPER_TOOL_MAP
from uniswap_tools import UNISWAP_TOOLS, UNISWAP_TOOL_MAP
from lifi_tools import LIFI_TOOLS, LIFI_TOOL_MAP
from opensea_tools import OPENSEA_TOOLS, OPENSEA_TOOL_MAP
from copytrade import COPYTRADE_TOOLS, COPYTRADE_TOOL_MAP
from evm_copytrade import EVM_COPYTRADE_TOOLS, EVM_COPYTRADE_TOOL_MAP
from jupiter_tools import JUPITER_TOOLS, JUPITER_TOOL_MAP
from swap_tools import SWAP_TOOLS, SWAP_TOOL_MAP
from trend_scanner import TREND_TOOLS, TREND_TOOL_MAP
from web_tools import WEB_TOOLS, WEB_TOOL_MAP
from agent_tools import AGENT_TOOLS, AGENT_TOOL_MAP
from full_agent_tools import FULL_AGENT_TOOLS, FULL_AGENT_TOOL_MAP
from self_check import SELF_CHECK_TOOLS, SELF_CHECK_TOOL_MAP as SELF_CHECK_MAP
from key_manager import KEY_MANAGER_TOOLS, KEY_MANAGER_TOOL_MAP as KEY_MANAGER_MAP

# Tools that don't live in a *_TOOL_MAP: dispatched by name to a function.
SOLANA_TOOL_NAMES = [
    "generate_wallet", "get_wallet_balance", "get_sol_price",
    "get_token_price", "buy_token", "sell_token", "get_private_key",
    "rug_check", "get_wallet_address", "rugcheck_report", "import_solana_wallet",
]
FILE_TOOL_NAMES = [
    "list_files", "read_file", "write_file", "edit_file",
    "run_safe_command", "restart_bot",
]
AUTO_TRADING_TOOL_NAMES = [
    "add_trading_rule", "get_trading_rules", "cancel_trading_rule",
]

# ============================================================
# Merged tool definitions (for the LLM's function-calling list)
# ============================================================

TOOLS = (
    ALL_TOOLS
    + SOLANA_TOOLS
    + MULTICHAIN_TOOLS
    + ROBINHOOD_TOOLS
    + STOCK_TOOLS
    + NFT_TOOLS
    + PERPS_TOOLS
    + RH_MCP_TOOLS
    + FILE_TOOLS
    + AUTO_TRADING_TOOLS
    + SUPER_TOOLS
    + MEMORY_TOOLS
    + UNISWAP_TOOLS
    + LIFI_TOOLS
    + OPENSEA_TOOLS
    + COPYTRADE_TOOLS
    + EVM_COPYTRADE_TOOLS
    + JUPITER_TOOLS
    + SWAP_TOOLS
    + TREND_TOOLS
    + WEB_TOOLS
    + AGENT_TOOLS
    + FULL_AGENT_TOOLS
    + SELF_CHECK_TOOLS
    + KEY_MANAGER_TOOLS
)

# Delegate tool — lets the main agent spawn specialist subagents mid-task
from delegation import DELEGATE_TOOL_DEF
TOOLS = TOOLS + [DELEGATE_TOOL_DEF]

# Dedupe by function name — first definition wins. xAI rejects duplicate
# function definitions with a 400 (Mistral silently kept the first), so
# the merged list must be unique before it reaches the LLM.
_seen, _deduped = set(), []
for _t in TOOLS:
    _n = _t.get("function", {}).get("name")
    if _n in _seen:
        continue
    _seen.add(_n)
    _deduped.append(_t)
TOOLS = _deduped

# ============================================================
# Merged name → executor map (for sub-agents that take a dict)
# agent_tools wins over full_agent_tools for shared names,
# matching TOOL_DISPATCH precedence.
# ============================================================

TOOL_MAP = {}
for _m in (
    # maps handled explicitly in dispatch_tool — merge them too so
    # sub-agents (TOOL_MAP consumers) can execute every advertised tool
    RH_MCP_TOOL_MAP, NFT_TOOL_MAP, PERPS_TOOL_MAP, STOCK_TOOL_MAP,
    ROBINHOOD_TOOL_MAP, MULTICHAIN_TOOL_MAP,
    CORE_TOOL_MAP, SUPER_TOOL_MAP, WEB_TOOL_MAP, TREND_TOOL_MAP,
    UNISWAP_TOOL_MAP, LIFI_TOOL_MAP, OPENSEA_TOOL_MAP, COPYTRADE_TOOL_MAP,
    EVM_COPYTRADE_TOOL_MAP, JUPITER_TOOL_MAP, SWAP_TOOL_MAP,
    FULL_AGENT_TOOL_MAP, AGENT_TOOL_MAP, MEMORY_TOOL_MAP,
    SELF_CHECK_MAP, KEY_MANAGER_MAP,
):
    TOOL_MAP.update(_m)


def dispatch_tool(name: str, args: dict, user_id: int = 0) -> str:
    """Execute any registered tool by name. Returns a string result."""
    args = dict(args or {})

    if name == "delegate":
        from delegation import dispatch_delegate
        return dispatch_delegate(args, user_id=user_id)
    if name in SOLANA_TOOL_NAMES:
        return execute_solana_tool(name, args)
    if name in RH_MCP_TOOL_MAP:
        return RH_MCP_TOOL_MAP[name](args)
    if name in NFT_TOOL_MAP:
        return NFT_TOOL_MAP[name](args)
    if name in PERPS_TOOL_MAP:
        return PERPS_TOOL_MAP[name](args)
    if name in STOCK_TOOL_MAP:
        return STOCK_TOOL_MAP[name](args)
    if name in ROBINHOOD_TOOL_MAP:
        return ROBINHOOD_TOOL_MAP[name](args)
    if name in MULTICHAIN_TOOL_MAP:
        return MULTICHAIN_TOOL_MAP[name](args)
    if name in FILE_TOOL_NAMES:
        return execute_file_tool(name, args)
    if name in AUTO_TRADING_TOOL_NAMES:
        args["user_id"] = user_id
        return execute_auto_trading_tool(name, args)
    if name in SUPER_TOOL_MAP:
        return SUPER_TOOL_MAP[name](args)
    if name in UNISWAP_TOOL_MAP:
        return UNISWAP_TOOL_MAP[name](args)
    if name in LIFI_TOOL_MAP:
        return LIFI_TOOL_MAP[name](args)
    if name in OPENSEA_TOOL_MAP:
        return OPENSEA_TOOL_MAP[name](args)
    if name in COPYTRADE_TOOL_MAP:
        return COPYTRADE_TOOL_MAP[name](args)
    if name in EVM_COPYTRADE_TOOL_MAP:
        return EVM_COPYTRADE_TOOL_MAP[name](args)
    if name in JUPITER_TOOL_MAP:
        return JUPITER_TOOL_MAP[name](args)
    if name in SWAP_TOOL_MAP:
        return SWAP_TOOL_MAP[name](args)
    if name in TREND_TOOL_MAP:
        return TREND_TOOL_MAP[name](args)
    if name in WEB_TOOL_MAP:
        return WEB_TOOL_MAP[name](args)
    if name in AGENT_TOOL_MAP:
        args["user_id"] = user_id
        return AGENT_TOOL_MAP[name](args)
    if name in FULL_AGENT_TOOL_MAP:
        args["user_id"] = user_id
        return FULL_AGENT_TOOL_MAP[name](args)
    if name in MEMORY_TOOL_MAP:
        set_current_user(user_id)
        return MEMORY_TOOL_MAP[name](args)
    if name in SELF_CHECK_MAP:
        return SELF_CHECK_MAP[name](args)
    if name in KEY_MANAGER_MAP:
        return KEY_MANAGER_MAP[name](args)
    if name in CORE_TOOL_MAP:
        return CORE_TOOL_MAP[name](args)
    return f"Unknown tool: {name}"


def tool_names() -> list:
    """Unique tool names in TOOLS (first occurrence wins)."""
    seen = []
    for t in TOOLS:
        n = t.get("function", {}).get("name")
        if n and n not in seen:
            seen.append(n)
    return seen


# Sanity check: duplicate-name definitions were dropped above, so nothing
# here is needed beyond a count for the logs.
logger.info("Tool registry: %d unique tools merged", len(TOOLS))
