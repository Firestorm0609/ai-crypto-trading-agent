"""
10 Super Cool Crypto Tools

1. Whale Tracker — Track whale wallets
2. Token Scanner — Scan for rug pulls
3. Social Sentiment — Twitter/Reddit mood
4. Gas Tracker — Real-time gas fees
5. Price Prediction — ML price direction
6. On-Chain Analytics — Exchange flows, miner reserves
7. News Sentiment — Headline analysis
8. Multi-Wallet Manager — Track multiple wallets
9. Airdrop Hunter — Find upcoming airdrops
10. DCA Optimizer — Smart dollar-cost averaging
"""

import json
import urllib.request
import urllib.parse
import sqlite3
import time
import re
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "trading.db"


def _cg_request(endpoint: str) -> dict:
    """CoinGecko API request."""
    url = f"https://api.coingecko.com/api/v3{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _get_price(coin: str) -> float:
    """Get current price."""
    aliases = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana", "doge": "dogecoin", "xrp": "ripple"}
    coin_id = aliases.get(coin.lower(), coin.lower())
    try:
        data = _cg_request(f"/simple/price?ids={coin_id}&vs_currencies=usd")
        return data.get(coin_id, {}).get("usd", 0)
    except Exception:
        return 0


# ============================================================
# 1. Whale Tracker
# ============================================================

# Known whale wallets (public)
WHALE_WALLETS = {
    "ethereum": [
        {"name": "Vitalik Buterin", "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"},
        {"name": "Binance Hot Wallet", "address": "0x28C6c06298d514Db089934071355E5743bf21d60"},
        {"name": "Jump Trading", "address": "0xf584F87E8B12592A00940cCe0267C3CE0C7aAC0e"},
    ],
    "solana": [
        {"name": "Jump Trading Sol", "address": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"},
        {"name": "Alameda Research", "address": "/LSEQXrBhWf6oLVSEb4e1b1jBGMcVXHgbGLpYD7y2j6w"},
    ],
}


def get_whale_activity(chain: str = "ethereum", limit: int = 10) -> str:
    """Track recent whale transactions."""
    # Use Etherscan/BSCScan free API for recent large transfers
    if chain == "ethereum":
        try:
            url = "https://api.etherscan.io/api?module=account&action=txlist&address=0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045&startblock=0&endblock=99999999&page=1&offset=5&sort=desc"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            if data.get("result") and isinstance(data["result"], list):
                lines = ["🐋 Whale Activity (Ethereum)\n"]
                for tx in data["result"][:limit]:
                    value_eth = int(tx.get("value", 0)) / 1e18
                    if value_eth > 0:
                        direction = "OUT" if tx.get("from", "").lower() == "0xd8da6bf26964af9d7eed9e03e53415d37aa96045" else "IN"
                        lines.append(f"  {direction}: {value_eth:.2f} ETH")
                return "\n".join(lines)
        except Exception:
            pass

    # Fallback: show known whale wallets
    wallets = WHALE_WALLETS.get(chain, [])
    lines = [f"🐋 Known Whale Wallets ({chain.title()})\n"]
    for w in wallets:
        lines.append(f"  {w['name']}: {w['address'][:20]}...")
    return "\n".join(lines)


def track_wallet(address: str, chain: str = "ethereum") -> str:
    """Track a specific wallet's recent activity."""
    try:
        if chain == "ethereum":
            url = f"https://api.etherscan.io/api?module=account&action=balance&address={address}&tag=latest"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            balance_eth = int(data.get("result", 0)) / 1e18
            price = _get_price("eth")
            usd_value = balance_eth * price

            return (
                f"🐋 Wallet Tracker\n\n"
                f"Address: {address[:20]}...\n"
                f"Chain: {chain.title()}\n"
                f"Balance: {balance_eth:.4f} ETH\n"
                f"Value: ${usd_value:,.2f}"
            )
    except Exception:
        pass

    return f"Could not track wallet {address[:20]}... on {chain}"


# ============================================================
# 2. Token Scanner (Rug Pull Detection)
# ============================================================

def scan_token(token_address: str, chain: str = "ethereum") -> str:
    """Scan a token for rug pull risk factors."""
    risk_score = 0
    flags = []

    # Check 1: Is it on CoinGecko?
    try:
        data = _cg_request(f"/search?query={token_address}")
        coins = data.get("coins", [])
        if coins:
            coin = coins[0]
            market_cap = coin.get("market_cap_rank", 999999)
            if market_cap > 1000:
                risk_score += 30
                flags.append("⚠️ Low market cap rank")
    except Exception:
        risk_score += 20
        flags.append("⚠️ Not found on CoinGecko")

    # Check 2: Get token details from CoinGecko
    try:
        if coins:
            coin_id = coins[0].get("id", "")
            detail = _cg_request(f"/coins/{coin_id}")
            market_data = detail.get("market_data", {})

            # Check liquidity (total volume as proxy)
            volume = market_data.get("total_volume", {}).get("usd", 0)
            if volume < 10000:
                risk_score += 40
                flags.append("⚠️ Very low trading volume (<$10K)")
            elif volume < 100000:
                risk_score += 20
                flags.append("⚠️ Low trading volume (<$100K)")

            # Check price volatility
            change_24h = market_data.get("price_change_percentage_24h", 0) or 0
            if abs(change_24h) > 50:
                risk_score += 30
                flags.append("⚠️ Extreme price volatility (>50% in 24h)")

            # Check if contract is verified
            contract_address = detail.get("contract_address", "")
            if not contract_address:
                risk_score += 15
                flags.append("⚠️ No contract address found")
    except Exception:
        risk_score += 10
        flags.append("⚠️ Could not fetch token details")

    # Risk level
    if risk_score >= 70:
        level = "🔴 HIGH RISK"
        advice = "Do NOT buy this token"
    elif risk_score >= 40:
        level = "🟡 MEDIUM RISK"
        advice = "Proceed with caution"
    else:
        level = "🟢 LOW RISK"
        advice = "Looks relatively safe"

    lines = [
        f"🔍 Token Scanner\n",
        f"Token: {token_address[:20]}...",
        f"Chain: {chain.title()}",
        f"Risk Score: {risk_score}/100",
        f"Level: {level}\n",
        f"Flags:"
    ]
    for flag in flags:
        lines.append(f"  {flag}")
    if not flags:
        lines.append("  ✅ No red flags detected")

    lines.append(f"\n💡 {advice}")
    return "\n".join(lines)


# ============================================================
# 3. Social Sentiment
# ============================================================

def get_social_sentiment(coin: str = "bitcoin") -> str:
    """Get social sentiment for a cryptocurrency."""
    # Use CoinGecko sentiment data
    try:
        data = _cg_request(f"/coins/{coin.lower()}")
        sentiment = data.get("sentiment_votes_up_percentage", 50)
        sentiment_down = data.get("sentiment_votes_down_percentage", 50)

        if sentiment > 60:
            mood = "🟢 BULLISH"
            emoji = "📈"
        elif sentiment < 40:
            mood = "🔴 BEARISH"
            emoji = "📉"
        else:
            mood = "🟡 NEUTRAL"
            emoji = "➡️"

        return (
            f"{emoji} Social Sentiment: {coin.upper()}\n\n"
            f"Overall: {mood}\n"
            f"Bullish: {sentiment}%\n"
            f"Bearish: {sentiment_down}%\n\n"
            f"Source: CoinGecko community votes"
        )
    except Exception:
        return f"Could not fetch sentiment for {coin}"


# ============================================================
# 4. Gas Tracker
# ============================================================

def get_gas_tracker(chain: str = "ethereum") -> str:
    """Get real-time gas fees across chains."""
    lines = [f"⛽ Gas Tracker\n"]

    # Try multiple free APIs for ETH gas
    eth_fetched = False

    # Try 1: Blocknative (free, no key)
    try:
        url = "https://api.blocknative.com/gasprices/blockprices"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        block_prices = data.get("blockPrices", [{}])
        if block_prices:
            prices = block_prices[0].get("estimatedPrices", [])
            if prices:
                low = prices[-1].get("price", "?")
                avg = prices[1].get("price", "?") if len(prices) > 1 else "?"
                high = prices[0].get("price", "?")

                lines.append("Ethereum:")
                lines.append(f"  🟢 Low: {low} Gwei")
                lines.append(f"  🟡 Average: {avg} Gwei")
                lines.append(f"  🔴 Fast: {high} Gwei")
                eth_fetched = True
    except Exception:
        pass

    # Try 2: ETH Gas Station (scrape)
    if not eth_fetched:
        try:
            url = "https://ethgasstation.info/api/ethgasAPI.json"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            low = data.get("safeLow", 0) / 10
            avg = data.get("average", 0) / 10
            high = data.get("fast", 0) / 10

            lines.append("Ethereum:")
            lines.append(f"  🟢 Low: {low} Gwei")
            lines.append(f"  🟡 Average: {avg} Gwei")
            lines.append(f"  🔴 Fast: {high} Gwei")
            eth_fetched = True
        except Exception:
            pass

    # Try 3: Owlracle (free, no key)
    if not eth_fetched:
        try:
            url = "https://api.owlracle.info/v4/eth/gas?accept=90"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            speeds = data.get("speeds", [{}])
            if speeds:
                # Owlracle returns gas in Gwei already
                base_fee = speeds[0].get("baseFee", 0)
                max_fee = speeds[0].get("maxFeePerGas", 0)
                priority = speeds[0].get("maxPriorityFeePerGas", 0)

                lines.append("Ethereum:")
                lines.append(f"  🟢 Low: {base_fee:.4f} Gwei")
                lines.append(f"  🟡 Average: {max_fee:.4f} Gwei")
                lines.append(f"  🔴 Fast: {(max_fee * 1.5):.4f} Gwei")
                eth_fetched = True
        except Exception:
            pass

    if not eth_fetched:
        lines.append("Ethereum: Could not fetch (APIs limited)")

    # Other chains
    lines.append("\nOther Chains (typically):")
    lines.append("  Base: ~0.001 Gwei (very cheap)")
    lines.append("  Arbitrum: ~0.1 Gwei (cheap)")
    lines.append("  Polygon: ~30 Gwei (cheap)")
    lines.append("  Solana: ~0.00025 SOL (cheap)")

    return "\n".join(lines)


# ============================================================
# 5. Price Prediction (Simple ML)
# ============================================================

def predict_price(coin: str = "bitcoin", days: int = 7) -> str:
    """Simple price direction prediction based on momentum."""
    try:
        # Get historical prices
        coin_id = coin.lower()
        data = _cg_request(f"/coins/{coin_id}/market_chart?vs_currency=usd&days=30&interval=daily")
        prices = [p[1] for p in data.get("prices", [])]

        if len(prices) < 7:
            return f"Insufficient data for {coin}"

        # Simple momentum analysis
        current = prices[-1]
        week_ago = prices[-7]
        month_ago = prices[0]

        week_change = ((current - week_ago) / week_ago) * 100
        month_change = ((current - month_ago) / month_ago) * 100

        # Trend analysis
        recent_trend = sum(1 for i in range(-5, 0) if prices[i] > prices[i-1])
        trend_strength = recent_trend / 5

        # Prediction
        if trend_strength > 0.6 and week_change > 0:
            direction = "📈 UP"
            confidence = min(70 + trend_strength * 20, 90)
            reasoning = "Strong upward momentum"
        elif trend_strength < 0.4 and week_change < 0:
            direction = "📉 DOWN"
            confidence = min(70 + (1 - trend_strength) * 20, 90)
            reasoning = "Downward momentum"
        else:
            direction = "➡️ SIDEWAYS"
            confidence = 50
            reasoning = "Mixed signals"

        return (
            f"🔮 Price Prediction: {coin.upper()}\n\n"
            f"Current: ${current:,.2f}\n"
            f"7d Change: {week_change:+.1f}%\n"
            f"30d Change: {month_change:+.1f}%\n\n"
            f"Prediction ({days}d): {direction}\n"
            f"Confidence: {confidence}%\n"
            f"Reasoning: {reasoning}\n\n"
            f"⚠️ This is not financial advice. DYOR."
        )
    except Exception as e:
        return f"Prediction error: {str(e)}"


# ============================================================
# 6. On-Chain Analytics
# ============================================================

def get_onchain_analytics(coin: str = "bitcoin") -> str:
    """Get on-chain metrics."""
    try:
        data = _cg_request(f"/coins/{coin.lower()}")
        market_data = data.get("market_data", {})

        lines = [f"📊 On-Chain Analytics: {coin.upper()}\n"]

        # Market cap
        mcap = market_data.get("market_cap", {}).get("usd", 0)
        lines.append(f"Market Cap: ${mcap:,.0f}")

        # 24h volume
        vol = market_data.get("total_volume", {}).get("usd", 0)
        lines.append(f"24h Volume: ${vol:,.0f}")

        # Volume/MCap ratio
        if mcap > 0:
            ratio = (vol / mcap) * 100
            lines.append(f"Vol/MCap: {ratio:.2f}%")
            if ratio > 10:
                lines.append("  → High activity (bullish signal)")
            elif ratio < 1:
                lines.append("  → Low activity ( consolidation)")

        # Circulating supply
        circ = market_data.get("circulating_supply", 0)
        total = market_data.get("total_supply", 0)
        if total > 0:
            pct = (circ / total) * 100
            lines.append(f"Circulating: {pct:.1f}% of total supply")

        # ATH
        ath = market_data.get("ath", {}).get("usd", 0)
        ath_change = market_data.get("ath_change_percentage", {}).get("usd", 0)
        lines.append(f"ATH: ${ath:,.2f} ({ath_change:+.1f}% from ATH)")

        return "\n".join(lines)
    except Exception as e:
        return f"Analytics error: {str(e)}"


# ============================================================
# 7. News Sentiment
# ============================================================

def get_news_sentiment(coin: str = "crypto") -> str:
    """Analyze crypto news sentiment."""
    try:
        # Fetch news via DuckDuckGo
        query = f"{coin} cryptocurrency news today"
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Extract headlines
        headlines = []
        for line in html.split("\n"):
            if '<a rel="nofollow" class="result-link" href="' in line:
                start = line.find('href="') + 6
                end = line.find('"', start)
                snippet = ""
                for j in range(html.split("\n").index(line) + 1, min(html.split("\n").index(line) + 5, len(html.split("\n")))):
                    if html.split("\n")[j].strip() and '<' not in html.split("\n")[j]:
                        snippet = html.split("\n")[j].strip()
                        break
                if snippet:
                    headlines.append(snippet)

        if not headlines:
            return f"No news found for {coin}"

        # Simple sentiment analysis
        bullish_words = ["surge", "rally", "gain", "bull", "moon", "pump", "breakout", "high", "record", "buy", "adoption"]
        bearish_words = ["crash", "dump", "fall", "bear", "drop", "sell", "hack", "scam", "loss", "low", "fear"]

        bullish = 0
        bearish = 0
        for h in headlines[:5]:
            h_lower = h.lower()
            for w in bullish_words:
                if w in h_lower:
                    bullish += 1
            for w in bearish_words:
                if w in h_lower:
                    bearish += 1

        total = bullish + bearish
        if total > 0:
            score = (bullish / total) * 100
        else:
            score = 50

        if score > 60:
            mood = "🟢 BULLISH"
        elif score < 40:
            mood = "🔴 BEARISH"
        else:
            mood = "🟡 NEUTRAL"

        lines = [f"📰 News Sentiment: {coin.upper()}\n"]
        lines.append(f"Overall: {mood} ({score:.0f}% bullish)")
        lines.append(f"Bullish signals: {bullish}")
        lines.append(f"Bearish signals: {bearish}\n")
        lines.append("Top Headlines:")
        for i, h in enumerate(headlines[:3], 1):
            lines.append(f"  {i}. {h[:80]}")

        return "\n".join(lines)
    except Exception as e:
        return f"News sentiment error: {str(e)}"


# ============================================================
# 8. Multi-Wallet Manager
# ============================================================

WALLETS_FILE = Path(__file__).parent / "wallets" / "tracked_wallets.json"


def _load_tracked_wallets() -> dict:
    """Load tracked wallets."""
    if WALLETS_FILE.exists():
        return json.loads(WALLETS_FILE.read_text())
    return {"wallets": []}


def _save_tracked_wallets(data: dict):
    """Save tracked wallets."""
    WALLETS_FILE.parent.mkdir(exist_ok=True)
    WALLETS_FILE.write_text(json.dumps(data, indent=2))


def add_wallet(address: str, name: str = "", chain: str = "ethereum") -> str:
    """Add a wallet to track."""
    data = _load_tracked_wallets()

    # Check if already tracking
    for w in data["wallets"]:
        if w["address"].lower() == address.lower():
            return f"Already tracking this wallet: {w.get('name', address[:20])}"

    data["wallets"].append({
        "address": address,
        "name": name or f"Wallet {len(data['wallets']) + 1}",
        "chain": chain,
        "added_at": datetime.now().isoformat(),
    })
    _save_tracked_wallets(data)
    return f"Added wallet: {name or address[:20]}... ({chain})"


def remove_wallet(address: str) -> str:
    """Remove a tracked wallet."""
    data = _load_tracked_wallets()
    data["wallets"] = [w for w in data["wallets"] if w["address"].lower() != address.lower()]
    _save_tracked_wallets(data)
    return f"Removed wallet: {address[:20]}..."


def list_wallets() -> str:
    """List all tracked wallets."""
    data = _load_tracked_wallets()
    if not data["wallets"]:
        return "No wallets being tracked.\n\nAdd one: /addwallet ADDRESS NAME"

    lines = ["🏦 Tracked Wallets:\n"]
    for w in data["wallets"]:
        lines.append(f"  {w.get('name', 'Unknown')} ({w['chain']})")
        lines.append(f"    {w['address'][:30]}...")

    return "\n".join(lines)


# ============================================================
# 9. Airdrop Hunter
# ============================================================

def get_upcoming_airdrops() -> str:
    """Find upcoming airdrops."""
    # Known upcoming airdrops (would normally scrape airdrop calendars)
    airdrops = [
        {"name": "Monad", "chain": "Monad", "status": "Confirmed", "estimated": "Q4 2026"},
        {"name": "Berachain", "chain": "Berachain", "status": "Confirmed", "estimated": "Live"},
        {"name": "Linea", "chain": "Ethereum L2", "status": "Rumored", "estimated": "2026"},
        {"name": "Scroll", "chain": "Ethereum L2", "status": "Rumored", "estimated": "2026"},
        {"name": "B² Network", "chain": "Bitcoin L2", "status": "Active", "estimated": "Now"},
    ]

    lines = ["🪂 Upcoming Airdrops:\n"]
    for a in airdrops:
        status_emoji = {"Confirmed": "✅", "Rumored": "🔮", "Active": "🟢"}.get(a["status"], "❓")
        lines.append(f"  {status_emoji} {a['name']}")
        lines.append(f"    Chain: {a['chain']} | Status: {a['status']}")
        lines.append(f"    Estimated: {a['estimated']}")
        lines.append("")

    lines.append("💡 Tips:")
    lines.append("  • Use testnets when possible")
    lines.append("  • Bridge funds to new chains")
    lines.append("  • Use dApps on the chain regularly")
    lines.append("  • Hold governance tokens")

    return "\n".join(lines)


def check_airdrop_eligibility(chain: str = "all") -> str:
    """Check if you might be eligible for airdrops."""
    return (
        f"🪂 Airdrop Eligibility Check\n\n"
        f"To check eligibility:\n"
        f"1. Visit the project's website\n"
        f"2. Connect your wallet\n"
        f"3. Check if you qualify\n\n"
        f"Common eligibility criteria:\n"
        f"• Used the testnet\n"
        f"• Bridged to the chain\n"
        f"• Used dApps on the chain\n"
        f"• Held governance tokens\n"
        f"• Participated in governance\n\n"
        f"Use /addwallet to track your wallets"
    )


# ============================================================
# 10. DCA Optimizer
# ============================================================

def smart_dca(coin: str = "bitcoin", amount: float = 100) -> str:
    """Smart DCA — buy more when fear is high, less when greedy."""
    try:
        # Get Fear & Greed Index
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        fng_value = int(data["data"][0]["value"])
        classification = data["data"][0]["value_classification"]

        # Adjust DCA amount based on fear/greed
        if fng_value <= 25:
            multiplier = 1.5  # Buy 50% more (extreme fear = opportunity)
            reason = "Extreme Fear — buying aggressively"
        elif fng_value <= 40:
            multiplier = 1.25  # Buy 25% more
            reason = "Fear — good buying opportunity"
        elif fng_value <= 60:
            multiplier = 1.0  # Normal DCA
            reason = "Neutral — standard DCA"
        elif fng_value <= 75:
            multiplier = 0.75  # Buy 25% less
            reason = "Greed — reduce buying"
        else:
            multiplier = 0.5  # Buy 50% less
            reason = "Extreme Greed — minimal buying"

        adjusted_amount = amount * multiplier

        return (
            f"💰 Smart DCA: {coin.upper()}\n\n"
            f"Fear & Greed: {fng_value}/100 ({classification})\n"
            f"Base Amount: ${amount:.2f}\n"
            f"Multiplier: {multiplier}x\n"
            f"Adjusted Amount: ${adjusted_amount:.2f}\n\n"
            f"Reasoning: {reason}\n\n"
            f"💡 Smart DCA buys more when others are fearful"
        )
    except Exception as e:
        return f"DCA error: {str(e)}"


# ============================================================
# Tool Registry
# ============================================================

SUPER_TOOLS = [
    # Whale Tracker
    {"type": "function", "function": {"name": "get_whale_activity", "description": "Track whale wallet activity on any chain.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "limit": {"type": "number"}}, "required": []}}},
    {"type": "function", "function": {"name": "track_wallet", "description": "Track a specific wallet's balance and activity.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "chain": {"type": "string"}}, "required": ["address"]}}},
    # Token Scanner
    {"type": "function", "function": {"name": "scan_token", "description": "Scan a token for rug pull risk factors.", "parameters": {"type": "object", "properties": {"token_address": {"type": "string"}, "chain": {"type": "string"}}, "required": ["token_address"]}}},
    # Social Sentiment
    {"type": "function", "function": {"name": "get_social_sentiment", "description": "Get social sentiment for a cryptocurrency.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}}, "required": []}}},
    # Gas Tracker
    {"type": "function", "function": {"name": "get_gas_tracker", "description": "Get real-time gas fees across chains.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}}, "required": []}}},
    # Price Prediction
    {"type": "function", "function": {"name": "predict_price", "description": "Predict price direction based on momentum analysis.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "days": {"type": "number"}}, "required": []}}},
    # On-Chain Analytics
    {"type": "function", "function": {"name": "get_onchain_analytics", "description": "Get on-chain metrics for a cryptocurrency.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}}, "required": []}}},
    # News Sentiment
    {"type": "function", "function": {"name": "get_news_sentiment", "description": "Analyze crypto news sentiment.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}}, "required": []}}},
    # Multi-Wallet Manager
    {"type": "function", "function": {"name": "add_wallet", "description": "Add a wallet to track.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "name": {"type": "string"}, "chain": {"type": "string"}}, "required": ["address"]}}},
    {"type": "function", "function": {"name": "list_wallets", "description": "List all tracked wallets.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "remove_wallet", "description": "Remove a tracked wallet.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]}}},
    # Airdrop Hunter
    {"type": "function", "function": {"name": "get_upcoming_airdrops", "description": "Find upcoming airdrops.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "check_airdrop_eligibility", "description": "Check airdrop eligibility criteria.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}}, "required": []}}},
    # DCA Optimizer
    {"type": "function", "function": {"name": "smart_dca", "description": "Smart DCA that adjusts based on fear/greed index.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "amount": {"type": "number"}}, "required": []}}},
]

SUPER_TOOL_MAP = {
    "get_whale_activity": lambda a: get_whale_activity(a.get("chain", "ethereum"), int(a.get("limit", 10))),
    "track_wallet": lambda a: track_wallet(a["address"], a.get("chain", "ethereum")),
    "scan_token": lambda a: scan_token(a["token_address"], a.get("chain", "ethereum")),
    "get_social_sentiment": lambda a: get_social_sentiment(a.get("coin", "bitcoin")),
    "get_gas_tracker": lambda a: get_gas_tracker(a.get("chain", "ethereum")),
    "predict_price": lambda a: predict_price(a.get("coin", "bitcoin"), int(a.get("days", 7))),
    "get_onchain_analytics": lambda a: get_onchain_analytics(a.get("coin", "bitcoin")),
    "get_news_sentiment": lambda a: get_news_sentiment(a.get("coin", "crypto")),
    "add_wallet": lambda a: add_wallet(a["address"], a.get("name", ""), a.get("chain", "ethereum")),
    "list_wallets": lambda a: list_wallets(),
    "remove_wallet": lambda a: remove_wallet(a["address"]),
    "get_upcoming_airdrops": lambda a: get_upcoming_airdrops(),
    "check_airdrop_eligibility": lambda a: check_airdrop_eligibility(a.get("chain", "all")),
    "smart_dca": lambda a: smart_dca(a.get("coin", "bitcoin"), float(a.get("amount", 100))),
}
