"""
Viral Trend Scanner — Spot trends before they pump

Monitors:
- CoinGecko: Trending coins + new listings (reliable, free)
- Pump.fun: New Solana token launches
- Jupiter: Solana token prices
- Combined analysis: Cross-check across platforms

When something viral is spotted:
1. Checks if it's on pump.fun/any chain
2. If launched: shows token info + risk
3. If not launched: alerts about the viral trend
"""

import json
import urllib.request
import urllib.parse
import re
import time
from pathlib import Path
from datetime import datetime, timedelta

SCAN_RESULTS_FILE = Path(__file__).parent / "trend_alerts.json"


# ============================================================
# 1. CoinGecko Trending (reliable, free, no key)
# ============================================================

def scan_coingecko_trending(limit: int = 10) -> str:
    """Get trending coins from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/search/trending"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        coins = data.get("coins", [])
        if not coins:
            return "No trending coins found"

        lines = ["CoinGecko Trending Coins:\n"]
        for coin in coins[:limit]:
            item = coin.get("item", {})
            name = item.get("name", "?")
            symbol = item.get("symbol", "?")
            rank = item.get("market_cap_rank", "?")
            score = item.get("score", 0)

            if score <= 2:
                trend = "🔥 HOT"
            elif score <= 4:
                trend = "📈 Rising"
            else:
                trend = "📊 Trending"

            lines.append(f"• {name} ({symbol})")
            lines.append(f"  Rank: #{rank} | {trend}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"CoinGecko trending error: {str(e)}"


def scan_coingecko_new(limit: int = 10) -> str:
    """Get newly listed coins from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1&sparkline=false"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            return "No new coins found"

        lines = ["New / Notable Coins:\n"]
        for coin in data[:limit]:
            name = coin.get("name", "?")
            symbol = coin.get("symbol", "?").upper()
            price = coin.get("current_price", 0)
            change = coin.get("price_change_percentage_24h", 0) or 0
            mcap = coin.get("market_cap", 0)

            emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
            lines.append(f"• {name} ({symbol}) — #{coin.get('market_cap_rank', '?')}")
            lines.append(f"  Price: ${price:,.4f} | {emoji} {change:+.1f}% | MCap: ${mcap:,.0f}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"CoinGecko new coins error: {str(e)}"


# ============================================================
# 2. Pump.fun New Token Scanner
# ============================================================

def scan_pumpfun_new(limit: int = 10) -> str:
    """Scan pump.fun for newly launched tokens."""
    try:
        url = "https://frontend-api-v3.pump.fun/coins?limit=20&sort=created_timestamp&order=DESC&includeNsfw=false"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            return "No new tokens found on pump.fun"

        lines = ["New Pump.fun Tokens:\n"]
        for coin in data[:limit]:
            name = coin.get("name", "?")
            symbol = coin.get("symbol", "?")
            mint = coin.get("mint", "?")
            market_cap = coin.get("usd_market_cap", 0)
            complete = coin.get("complete", False)

            status = "🟢 Graduated" if complete else "🟡 Bonding"
            mcap_str = f"${market_cap:,.0f}" if market_cap else "$0"

            lines.append(f"• {name} ({symbol})")
            lines.append(f"  Mint: {mint[:20]}...")
            lines.append(f"  MCap: {mcap_str} | {status}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Pump.fun scan error: {str(e)}"


def scan_pumpfun_search(query: str) -> str:
    """Search pump.fun for a specific token."""
    try:
        url = f"https://frontend-api-v3.pump.fun/coins?query={urllib.parse.quote(query)}&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            return f"No results for '{query}' on pump.fun"

        lines = [f"Pump.fun Results: '{query}'\n"]
        for coin in data:
            name = coin.get("name", "?")
            symbol = coin.get("symbol", "?")
            mint = coin.get("mint", "?")
            market_cap = coin.get("usd_market_cap", 0)
            complete = coin.get("complete", False)

            status = "Graduated" if complete else "Bonding"
            lines.append(f"• {name} ({symbol}) - MCap: ${market_cap:,.0f} [{status}]")
            lines.append(f"  Mint: {mint}")

        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {str(e)}"


def scan_pumpfun_top(limit: int = 10) -> str:
    """Get top performing pump.fun tokens."""
    try:
        url = "https://frontend-api-v3.pump.fun/coins?limit=20&sort=market_cap&order=DESC&includeNsfw=false"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            return "No top tokens found on pump.fun"

        lines = ["Top Pump.fun Tokens:\n"]
        for coin in data[:limit]:
            name = coin.get("name", "?")
            symbol = coin.get("symbol", "?")
            mint = coin.get("mint", "?")
            market_cap = coin.get("usd_market_cap", 0)
            complete = coin.get("complete", False)

            status = "🟢" if complete else "🟡"
            lines.append(f"{status} {name} ({symbol}) — ${market_cap:,.0f}")
            lines.append(f"  Mint: {mint[:20]}...")

        return "\n".join(lines)
    except Exception as e:
        return f"Pump.fun top error: {str(e)}"


# ============================================================
# 3. Viral Trend Detector (combines all sources)
# ============================================================

def detect_viral_trend(topic: str) -> str:
    """
    Detect if a topic is viral across platforms + check if it's launched.
    
    Flow:
    1. Search CoinGecko for the token
    2. Check pump.fun for token
    3. Check Jupiter for price (if Solana)
    4. Report findings
    """
    lines = [f"Viral Trend Scan: {topic}\n"]

    # Step 1: Pump.fun
    pump_result = scan_pumpfun_search(topic)
    has_pump = "No results" not in pump_result
    if has_pump:
        lines.append("Pump.fun: FOUND")
        lines.append(pump_result[:300])
    else:
        lines.append("Pump.fun: Not found")

    # Step 2: Jupiter (if has mint address)
    if has_pump:
        mint_match = re.search(r'Mint: ([A-Za-z0-9]+)', pump_result)
        if mint_match:
            mint = mint_match.group(1)
            try:
                from jupiter_tools import get_sol_price
                price_result = get_sol_price(mint)
                lines.append(f"\nJupiter: {price_result}")
            except:
                pass

    # Step 3: Verdict
    lines.append("\n---")
    if has_pump:
        lines.append("VERDICT: Found on Pump.fun")
        lines.append("Check market cap and liquidity before trading.")
    else:
        lines.append("VERDICT: Not found on Pump.fun")
        lines.append("Could be pre-launch, on another chain, or not a token.")

    return "\n".join(lines)


def scan_all_viral() -> str:
    """Scan all sources for viral crypto trends."""
    lines = ["Viral Crypto Scan\n"]

    # CoinGecko trending
    lines.append("=== CoinGecko Trending ===")
    lines.append(scan_coingecko_trending(7))

    # Pump.fun new
    lines.append("\n=== Pump.fun New Launches ===")
    lines.append(scan_pumpfun_new(5))

    # Pump.fun top
    lines.append("\n=== Pump.fun Top Tokens ===")
    lines.append(scan_pumpfun_top(5))

    return "\n".join(lines)


# ============================================================
# 4. Background Trend Monitor
# ============================================================

def _load_alerts() -> dict:
    if SCAN_RESULTS_FILE.exists():
        return json.loads(SCAN_RESULTS_FILE.read_text())
    return {"alerts": []}

def _save_alerts(data: dict):
    SCAN_RESULTS_FILE.write_text(json.dumps(data, indent=2))

def save_trend_alert(topic: str, finding: str):
    """Save a trend alert."""
    data = _load_alerts()
    data["alerts"].append({
        "topic": topic,
        "finding": finding[:500],
        "timestamp": datetime.now().isoformat(),
    })
    data["alerts"] = data["alerts"][-50:]
    _save_alerts(data)

def get_trend_alerts() -> str:
    """Get recent trend alerts."""
    data = _load_alerts()
    if not data["alerts"]:
        return "No trend alerts yet."

    lines = ["Trend Alerts:\n"]
    for alert in reversed(data["alerts"][-10:]):
        lines.append(f"[{alert['timestamp'][:16]}] {alert['topic']}")
        lines.append(f"  {alert['finding'][:100]}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# Tool Registry
# ============================================================

TREND_TOOLS = [
    {"type": "function", "function": {"name": "scan_coingecko_trending", "description": "Get trending coins from CoinGecko. Shows what's hot in crypto right now.", "parameters": {"type": "object", "properties": {"limit": {"type": "number"}}, "required": []}}},
    {"type": "function", "function": {"name": "scan_pumpfun_new", "description": "Scan pump.fun for newly launched Solana tokens.", "parameters": {"type": "object", "properties": {"limit": {"type": "number"}}, "required": []}}},
    {"type": "function", "function": {"name": "scan_pumpfun_top", "description": "Get top performing pump.fun tokens by market cap.", "parameters": {"type": "object", "properties": {"limit": {"type": "number"}}, "required": []}}},
    {"type": "function", "function": {"name": "scan_pumpfun_search", "description": "Search pump.fun for a specific token.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "detect_viral_trend", "description": "Check if a topic/token is trending across platforms. Full analysis with verdict.", "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}},
    {"type": "function", "function": {"name": "scan_all_viral", "description": "Scan all sources (CoinGecko, pump.fun) for viral crypto trends at once.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_trend_alerts", "description": "Get recent trend alerts saved by the bot.", "parameters": {"type": "object", "properties": {}}}},
]

TREND_TOOL_MAP = {
    "scan_coingecko_trending": lambda a: scan_coingecko_trending(int(a.get("limit", 10))),
    "scan_pumpfun_new": lambda a: scan_pumpfun_new(int(a.get("limit", 10))),
    "scan_pumpfun_top": lambda a: scan_pumpfun_top(int(a.get("limit", 10))),
    "scan_pumpfun_search": lambda a: scan_pumpfun_search(a["query"]),
    "detect_viral_trend": lambda a: detect_viral_trend(a["topic"]),
    "scan_all_viral": lambda a: scan_all_viral(),
    "get_trend_alerts": lambda a: get_trend_alerts(),
}
