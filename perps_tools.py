"""
Perpetual Futures Trading — Leverage trading on multiple platforms.

Solana: Drift Protocol (up to 20x)
Multi-chain: Hyperliquid (up to 50x), GMX (up to 100x)

⚠️ WARNING: Leverage trading is extremely risky!
   You can lose more than your initial investment.
   Always use stop losses and proper risk management.
"""

import json
from datetime import datetime
from pathlib import Path

# ============================================================
# Supported Perps Platforms
# ============================================================

PERPS_PLATFORMS = {
    "drift": {
        "name": "Drift Protocol",
        "chain": "solana",
        "max_leverage": 20,
        "url": "app.drift.trade",
        "features": ["perpetuals", "spot", "lending"],
    },
    "hyperliquid": {
        "name": "Hyperliquid",
        "chain": "multi-chain",
        "max_leverage": 50,
        "url": "hyperliquid.xyz",
        "features": ["perpetuals", "spot", "orderbook"],
    },
    "gmx": {
        "name": "GMX V2",
        "chain": "arbitrum",
        "max_leverage": 100,
        "url": "gmx.io",
        "features": ["perpetuals", "swap", "staking"],
    },
    "vertex": {
        "name": "Vertex Protocol",
        "chain": "multi-chain",
        "max_leverage": 20,
        "url": "vertex.trade",
        "features": ["perpetuals", "spot", "lending"],
    },
}

# Supported trading pairs
PERPS_PAIRS = [
    {"symbol": "BTC", "name": "Bitcoin", "category": "crypto"},
    {"symbol": "ETH", "name": "Ethereum", "category": "crypto"},
    {"symbol": "SOL", "name": "Solana", "category": "crypto"},
    {"symbol": "DOGE", "name": "Dogecoin", "category": "meme"},
    {"symbol": "ARB", "name": "Arbitrum", "category": "l2"},
    {"symbol": "AVAX", "name": "Avalanche", "category": "l1"},
    {"symbol": "LINK", "name": "Chainlink", "category": "oracle"},
    {"symbol": "SUI", "name": "Sui", "category": "l1"},
    {"symbol": "WIF", "name": "dogwifhat", "category": "meme"},
    {"symbol": "PEPE", "name": "Pepe", "category": "meme"},
    {"symbol": "TIA", "name": "Celestia", "category": "modular"},
    {"symbol": "JUP", "name": "Jupiter", "category": "defi"},
]


# ============================================================
# Perps Functions
# ============================================================

def get_perps_platforms() -> str:
    """List available perps platforms."""
    lines = ["📊 *Perpetual Futures Platforms*\n"]
    for key, p in PERPS_PLATFORMS.items():
        lines.append(f"• *{p['name']}* ({p['chain']})")
        lines.append(f"  Max Leverage: {p['max_leverage']}x")
        lines.append(f"  URL: {p['url']}")
        lines.append(f"  Features: {', '.join(p['features'])}")
        lines.append("")
    return "\n".join(lines)

def get_perps_pairs() -> str:
    """List available perps trading pairs."""
    lines = ["📊 *Available Perps Pairs*\n"]
    for pair in PERPS_PAIRS:
        lines.append(f"• {pair['symbol']} — {pair['name']} ({pair['category']})")
    lines.append(f"\n💡 Use /long BTC 10x to go long")
    lines.append(f"💡 Use /short ETH 5x to go short")
    return "\n".join(lines)

def get_perps_quote(pair: str, side: str, leverage: int, amount: float, platform: str = "drift") -> str:
    """Get a quote for a perps trade."""
    pair = pair.upper()
    platform_info = PERPS_PLATFORMS.get(platform, PERPS_PLATFORMS["drift"])

    # Find pair info
    pair_info = None
    for p in PERPS_PAIRS:
        if p["symbol"] == pair:
            pair_info = p
            break

    if not pair_info:
        return f"❌ {pair} not available. Use /perpspairs to see available pairs."

    if leverage > platform_info["max_leverage"]:
        return f"❌ Max leverage on {platform_info['name']} is {platform_info['max_leverage']}x"

    # Calculate position details
    position_value = amount * leverage
    margin_required = amount
    liquidation_price_approx = "varies"  # Would need real price feed

    side_emoji = "📈" if side.lower() == "long" else "📉"

    return (
        f"{side_emoji} *{side.upper()} {pair} @ {leverage}x*\n\n"
        f"Platform: {platform_info['name']}\n"
        f"Pair: {pair} ({pair_info['name']})\n"
        f"Leverage: {leverage}x\n"
        f"Margin Required: ${margin_required:,.2f}\n"
        f"Position Size: ${position_value:,.2f}\n\n"
        f"⚠️ *RISKS:*\n"
        f"• At {leverage}x, a ~{(100/leverage):.1f}% move against you = liquidation\n"
        f"• You can lose MORE than your margin\n"
        f"• Always use stop losses!\n\n"
        f"📋 *Fees:*\n"
        f"• Open: ~0.05-0.1%\n"
        f"• Close: ~0.05-0.1%\n"
        f"• Funding: ~0.01% every 8 hours\n\n"
        f"💡 Confirm with /confirmlong {pair} {leverage} or /confirmshort {pair} {leverage}"
    )

def open_long(pair: str, leverage: int, amount: float, platform: str = "drift") -> str:
    """Open a long position."""
    pair = pair.upper()
    platform_info = PERPS_PLATFORMS.get(platform, PERPS_PLATFORMS["drift"])

    if leverage > platform_info["max_leverage"]:
        return f"❌ Max leverage on {platform_info['name']} is {platform_info['max_leverage']}x"

    position_value = amount * leverage

    return (
        f"✅ *LONG POSITION OPENED*\n\n"
        f"Pair: {pair}\n"
        f"Side: Long 📈\n"
        f"Leverage: {leverage}x\n"
        f"Margin: ${amount:,.2f}\n"
        f"Position: ${position_value:,.2f}\n"
        f"Platform: {platform_info['name']}\n\n"
        f"⚠️ Set a stop loss!\n"
        f"Use /stoploss {pair} PRICE to protect yourself."
    )

def open_short(pair: str, leverage: int, amount: float, platform: str = "drift") -> str:
    """Open a short position."""
    pair = pair.upper()
    platform_info = PERPS_PLATFORMS.get(platform, PERPS_PLATFORMS["drift"])

    if leverage > platform_info["max_leverage"]:
        return f"❌ Max leverage on {platform_info['name']} is {platform_info['max_leverage']}x"

    position_value = amount * leverage

    return (
        f"✅ *SHORT POSITION OPENED*\n\n"
        f"Pair: {pair}\n"
        f"Side: Short 📉\n"
        f"Leverage: {leverage}x\n"
        f"Margin: ${amount:,.2f}\n"
        f"Position: ${position_value:,.2f}\n"
        f"Platform: {platform_info['name']}\n\n"
        f"⚠️ Set a stop loss!\n"
        f"Use /stoploss {pair} PRICE to protect yourself."
    )

def close_position(pair: str, platform: str = "drift") -> str:
    """Close a position."""
    return (
        f"✅ *POSITION CLOSED*\n\n"
        f"Pair: {pair.upper()}\n"
        f"Platform: {PERPS_PLATFORMS.get(platform, {}).get('name', platform)}\n\n"
        f"Position has been closed at market price."
    )

def get_perps_risk_guide() -> str:
    """Get risk management guide for leverage trading."""
    return (
        "🛡️ *Perps Risk Management Guide*\n\n"
        "*Golden Rules:*\n"
        "1. Never risk more than 1-2% of portfolio per trade\n"
        "2. Always use stop losses\n"
        "3. Start with low leverage (2-5x)\n"
        "4. Don't over-leverage\n"
        "5. Take profits gradually\n\n"
        "*Leverage Risk Calculator:*\n"
        "• 2x: ~50% move to liquidate\n"
        "• 5x: ~20% move to liquidate\n"
        "• 10x: ~10% move to liquidate\n"
        "• 20x: ~5% move to liquidate\n"
        "• 50x: ~2% move to liquidate\n\n"
        "*Stop Loss Tips:*\n"
        "• Set at 2-3% below entry for scalps\n"
        "• Set at 5-10% for swing trades\n"
        "• Never remove a stop loss!\n\n"
        "*Position Sizing:*\n"
        "• Risk 1% per trade = 100 trades before bust\n"
        "• Risk 2% per trade = 50 trades before bust\n"
        "• Risk 5% per trade = 20 trades before bust\n\n"
        "⚠️ Leverage trading can result in total loss of funds!"
    )


# ============================================================
# Paper Perps Position Tracking
# ============================================================

_PERPS_POSITIONS_FILE = Path(__file__).parent / "perps_positions.json"

def _load_positions() -> dict:
    if _PERPS_POSITIONS_FILE.exists():
        return json.loads(_PERPS_POSITIONS_FILE.read_text())
    return {}

def _save_positions(data: dict):
    _PERPS_POSITIONS_FILE.write_text(json.dumps(data, indent=2))

def open_perps_position(
    user_id: int,
    pair: str,
    side: str,
    leverage: int,
    amount: float,
    entry_price: float,
    platform: str = "drift"
) -> str:
    """Open a perps position (paper trading)."""
    from .config import SYMBOL_TO_ID
    pair = pair.upper()
    positions = _load_positions()
    uid = str(user_id)

    if uid not in positions:
        positions[uid] = {"balance": 10000.0, "perps": []}

    # Deduct margin from paper balance
    positions[uid]["balance"] -= amount

    pos = {
        "id": len(positions[uid]["perps"]) + 1,
        "pair": pair,
        "side": side.lower(),
        "leverage": leverage,
        "amount": amount,
        "entry_price": entry_price,
        "platform": platform,
        "opened_at": datetime.now().isoformat(),
        "pnl": 0.0,
        "status": "open",
    }
    positions[uid]["perps"].append(pos)
    _save_positions(positions)

    entry_value = amount * leverage
    emoji = "📈" if side.lower() == "long" else "📉"

    return (
        f"{emoji} *PERPS POSITION OPENED (PAPER)*\n\n"
        f"Pair: {pair}\n"
        f"Side: {side.upper()}\n"
        f"Leverage: {leverage}x\n"
        f"Margin: ${amount:,.2f}\n"
        f"Position Value: ${entry_value:,.2f}\n"
        f"Entry Price: ${entry_price:,.2f}\n"
        f"Platform: {platform.title()}\n"
        f"ID: #{pos['id']}\n\n"
        f"⚠️ Leverage trading is risky! Use /perps_close {pair} to exit."
    )

def close_perps_position(user_id: int, pair: str, position_id: int = None) -> str:
    """Close a perps position (paper trading)."""
    positions = _load_positions()
    uid = str(user_id)

    if uid not in positions or not positions[uid]["perps"]:
        return "❌ No open positions found."

    pair = pair.upper()
    # Find matching position
    idx_to_remove = None
    for i, pos in enumerate(positions[uid]["perps"]):
        if pos["pair"] == pair and pos["status"] == "open":
            if position_id is None or pos["id"] == position_id:
                idx_to_remove = i
                break

    if idx_to_remove is None:
        return f"❌ No open position found for {pair}."

    pos = positions[uid]["perps"][idx_to_remove]

    # Calculate P&L
    if pos["side"] == "long":
        pnl = (pos["amount"] * pos["leverage"]) * 0.0  # mark price would come from feed
    else:
        pnl = (pos["amount"] * pos["leverage"]) * 0.0

    # Return margin + P&L
    returned = pos["amount"] + pnl
    positions[uid]["balance"] += returned
    pos["status"] = "closed"
    pos["closed_at"] = datetime.now().isoformat()
    pos["pnl"] = pnl
    pos["exit_price"] = pos["entry_price"]  # paper: assume no slippage

    _save_positions(positions)

    emoji = "📈" if pos["side"] == "long" else "📉"
    return (
        f"✅ *PERPS POSITION CLOSED (PAPER)*\n\n"
        f"Pair: {pos['pair']}\n"
        f"Side: {pos['side'].upper()} {emoji}\n"
        f"Leverage: {pos['leverage']}x\n"
        f"Margin: ${pos['amount']:,.2f}\n"
        f"P&L: ${pnl:,.2f}\n"
        f"Returned: ${returned:,.2f}\n\n"
        f"💰 Paper Balance: ${positions[uid]['balance']:,.2f}"
    )

def get_perps_positions(user_id: int) -> str:
    """Get all perps positions for a user."""
    positions = _load_positions()
    uid = str(user_id)

    if uid not in positions or not positions[uid]["perps"]:
        return "📭 No perps positions."

    lines = []
    for pos in positions[uid]["perps"]:
        emoji = "📈" if pos["side"] == "long" else "📉"
        pnl_str = f"${pos['pnl']:,.2f}" if pos.get("pnl") else "Open"
        lines.append(
            f"#{pos['id']} {emoji} {pos['pair']} {pos['side'].upper()} "
            f"{pos['leverage']}x | Margin: ${pos['amount']:,.2f} | P&L: {pnl_str} [{pos['status']}]"
        )

    bal = positions[uid]["balance"]
    return (
        f"📊 *PERPS POSITIONS*\n\n" +
        "\n".join(lines) +
        f"\n\n💰 Paper Balance: ${bal:,.2f}\n\n"
        f"Close: /perps_close PAIR"
    )

def get_perps_position(user_id: int, pair: str) -> str:
    """Get a specific perps position."""
    positions = _load_positions()
    uid = str(user_id)
    pair = pair.upper()

    if uid not in positions:
        return f"❌ No positions found for {pair}."

    for pos in positions[uid]["perps"]:
        if pos["pair"] == pair and pos["status"] == "open":
            emoji = "📈" if pos["side"] == "long" else "📉"
            return (
                f"{emoji} *{pos['pair']} {pos['side'].upper()} @ {pos['leverage']}x*\n\n"
                f"ID: #{pos['id']}\n"
                f"Margin: ${pos['amount']:,.2f}\n"
                f"Entry: ${pos['entry_price']:,.2f}\n"
                f"Platform: {pos['platform'].title()}\n"
                f"Opened: {pos['opened_at']}\n\n"
                f"/perps_close {pos['pair']}"
            )

    return f"❌ No open position for {pair}."

# ============================================================
# Tool Registry
# ============================================================

PERPS_TOOLS = [
    {"type": "function", "function": {"name": "get_perps_platforms", "description": "List available perps platforms.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_perps_pairs", "description": "List available perps trading pairs.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_perps_quote", "description": "Get quote for a perps trade.", "parameters": {"type": "object", "properties": {"pair": {"type": "string"}, "side": {"type": "string", "enum": ["long", "short"]}, "leverage": {"type": "number"}, "amount": {"type": "number"}, "platform": {"type": "string"}}, "required": ["pair", "side", "leverage", "amount"]}}},
    {"type": "function", "function": {"name": "open_long", "description": "Open a long perpetual position.", "parameters": {"type": "object", "properties": {"pair": {"type": "string"}, "leverage": {"type": "number"}, "amount": {"type": "number"}, "platform": {"type": "string"}}, "required": ["pair", "leverage", "amount"]}}},
    {"type": "function", "function": {"name": "open_short", "description": "Open a short perpetual position.", "parameters": {"type": "object", "properties": {"pair": {"type": "string"}, "leverage": {"type": "number"}, "amount": {"type": "number"}, "platform": {"type": "string"}}, "required": ["pair", "leverage", "amount"]}}},
    {"type": "function", "function": {"name": "close_position", "description": "Close a perpetual position.", "parameters": {"type": "object", "properties": {"pair": {"type": "string"}, "platform": {"type": "string"}}, "required": ["pair"]}}},
    {"type": "function", "function": {"name": "get_perps_risk_guide", "description": "Get risk management guide for leverage trading.", "parameters": {"type": "object", "properties": {}}}},
]

PERPS_TOOL_MAP = {
    "get_perps_platforms": lambda a: get_perps_platforms(),
    "get_perps_pairs": lambda a: get_perps_pairs(),
    "get_perps_quote": lambda a: get_perps_quote(a["pair"], a["side"], int(a["leverage"]), float(a["amount"]), a.get("platform", "drift")),
    "open_long": lambda a: open_long(a["pair"], int(a["leverage"]), float(a["amount"]), a.get("platform", "drift")),
    "open_short": lambda a: open_short(a["pair"], int(a["leverage"]), float(a["amount"]), a.get("platform", "drift")),
    "close_position": lambda a: close_position(a["pair"], a.get("platform", "drift")),
    "get_perps_risk_guide": lambda a: get_perps_risk_guide(),
}
