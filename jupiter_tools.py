"""
Jupiter Tools — Solana DEX Scanner, Prices, Swaps

Uses Jupiter API (free, no key required for basic usage):
- Price API: Real-time token prices
- Quote API: Swap quotes
- Token listing: Find new tokens
"""

import json
import urllib.request
import urllib.parse
from pathlib import Path

# Known Solana token mints
SOLANA_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "ORCA": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "MNGO": "MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac",
    "BOME": "ukHH6cRDm1RJGqtBCsVMkZKf9eF5LJfGtn1JYV8RDcF",
    "W": "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ",
    "TNSR": "TNSRxcUzoT2zWMtqNVpkF3GJfNsAq3oBnKLGEPxRoLP",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "MYRO": "HhJpBhRRn4g56VsyLuT8DL5Bv31HkUqsRHgF4VVZrrt",
    "MEOW": "MeWjQRic6hP6FHkRkFdpMjUti9KT8dM9E10E2WE1R4Y",
}


def _jupiter_request(endpoint: str, params: dict = None) -> dict:
    """Make a Jupiter API request."""
    url = f"https://api.jup.ag{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ============================================================
# 1. Token Scanner (Solana)
# ============================================================

def _get_sol_token_name(mint: str) -> dict:
    """Get Solana token name from pump.fun or Jupiter."""
    # Try pump.fun first (for pump tokens)
    try:
        url = f"https://frontend-api-v3.pump.fun/coins/{mint}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return {"name": data.get("name", "?"), "symbol": data.get("symbol", "?")}
    except Exception:
        pass
    # Try Jupiter token list
    try:
        url = f"https://api.jup.ag/tokens/v1/{mint}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return {"name": data.get("name", "?"), "symbol": data.get("symbol", "?")}
    except Exception:
        pass
    return {"name": "?", "symbol": "?"}


def scan_sol_token(token_address: str) -> str:
    """Scan a Solana token for safety using Jupiter data."""
    risk_score = 0
    flags = []

    # Get token name
    token_info = _get_sol_token_name(token_address)
    token_name = token_info.get("name", "?")
    token_symbol = token_info.get("symbol", "?")

    try:
        data = _jupiter_request("/price/v3", {"ids": token_address})
        token_data = data.get(token_address)

        if not token_data:
            return f"Token {token_name} ({token_symbol}) not found on Jupiter"

        price = token_data.get("usdPrice", 0)
        liquidity = token_data.get("liquidity", 0)
        change_24h = token_data.get("priceChange24h", 0) or 0

        # Check liquidity
        if liquidity < 10000:
            risk_score += 40
            flags.append("Very low liquidity (<$10K)")
        elif liquidity < 100000:
            risk_score += 20
            flags.append("Low liquidity (<$100K)")

        # Check volatility
        if abs(change_24h) > 50:
            risk_score += 30
            flags.append("Extreme volatility (>50% in 24h)")
        elif abs(change_24h) > 20:
            risk_score += 15
            flags.append("High volatility (>20% in 24h)")

        # Check price
        if price < 0.00001:
            risk_score += 20
            flags.append("Very low price (micro-cap)")

        if risk_score >= 70:
            level = "HIGH RISK"
        elif risk_score >= 40:
            level = "MEDIUM RISK"
        else:
            level = "LOW RISK"

        emoji = "🔴" if risk_score >= 70 else "🟡" if risk_score >= 40 else "🟢"

        lines = [
            f"Solana Token Scanner (Jupiter)\n",
            f"Name: {token_name} ({token_symbol})",
            f"Mint: {token_address[:20]}...",
            f"Price: ${price:.8f}",
            f"Liquidity: ${liquidity:,.0f}",
            f"24h Change: {change_24h:+.1f}%",
            f"Risk Score: {risk_score}/100",
            f"Level: {emoji} {level}\n",
        ]

        if flags:
            lines.append("Flags:")
            for f in flags:
                lines.append(f"  ⚠️ {f}")
        else:
            lines.append("✅ No red flags detected")

        return "\n".join(lines)

    except Exception as e:
        return f"Scanner error: {str(e)}"


# ============================================================
# 2. Price Scanner
# ============================================================

def get_sol_price(token: str) -> str:
    """Get Solana token price from Jupiter."""
    token = token.upper()

    # Check if it's a known token
    mint = SOLANA_TOKENS.get(token)
    if not mint:
        # Try as mint address directly
        mint = token

    # Get token name if it's a mint address
    display_name = token
    if len(mint) > 10:  # It's a mint address
        info = _get_sol_token_name(mint)
        if info.get("name") != "?":
            display_name = f"{info['name']} ({info['symbol']})"

    try:
        data = _jupiter_request("/price/v3", {"ids": mint})
        token_data = data.get(mint)

        if not token_data:
            return f"Token {display_name} not found on Jupiter"

        price = token_data.get("usdPrice", 0)
        change = token_data.get("priceChange24h", 0) or 0
        liquidity = token_data.get("liquidity", 0)

        emoji = "🟢" if change >= 0 else "🔴"
        return (
            f"{emoji} {display_name}: ${price:.8f}\n"
            f"24h: {change:+.1f}%\n"
            f"Liquidity: ${liquidity:,.0f}"
        )
    except Exception as e:
        return f"Price error: {str(e)}"


def get_multiple_prices(tokens: list) -> str:
    """Get prices for multiple tokens at once."""
    mints = []
    for t in tokens:
        t = t.upper()
        if t in SOLANA_TOKENS:
            mints.append(SOLANA_TOKENS[t])
        else:
            mints.append(t)

    try:
        ids_str = ",".join(mints)
        data = _jupiter_request("/price/v3", {"ids": ids_str})

        lines = ["Solana Token Prices (Jupiter):\n"]
        for t, mint in zip(tokens, mints):
            token_data = data.get(mint, {})
            price = token_data.get("usdPrice", 0)
            change = token_data.get("priceChange24h", 0) or 0
            emoji = "🟢" if change >= 0 else "🔴"
            lines.append(f"{emoji} {t.upper()}: ${price:.8f} ({change:+.1f}%)")

        return "\n".join(lines)
    except Exception as e:
        return f"Price error: {str(e)}"


# ============================================================
# 3. Swap Quote
# ============================================================

def get_sol_swap_quote(token_in: str, token_out: str, amount: float = 1.0) -> str:
    """Get swap quote from Jupiter."""
    token_in = token_in.upper()
    token_out = token_out.upper()

    mint_in = SOLANA_TOKENS.get(token_in)
    mint_out = SOLANA_TOKENS.get(token_out)

    if not mint_in or not mint_out:
        return f"Token not found. Available: {', '.join(SOLANA_TOKENS.keys())}"

    try:
        # Get quote
        data = _jupiter_request("/swap/v1/quote", {
            "inputMint": mint_in,
            "outputMint": mint_out,
            "amount": str(int(amount * (10 ** (6 if token_in in ["USDC", "USDT"] else 9)))),
            "slippageBps": 50,
        })

        in_amount = int(data.get("inAmount", 0))
        out_amount = int(data.get("outAmount", 0))
        price_impact = float(data.get("priceImpactPct", 0))

        # Get prices for USD values
        prices = _jupiter_request("/price/v3", {"ids": f"{mint_in},{mint_out}"})
        price_in = prices.get(mint_in, {}).get("usdPrice", 0)
        price_out = prices.get(mint_out, {}).get("usdPrice", 0)

        decimals_in = 6 if token_in in ["USDC", "USDT"] else 9
        decimals_out = 6 if token_out in ["USDC", "USDT"] else 9

        amount_in = in_amount / (10 ** decimals_in)
        amount_out = out_amount / (10 ** decimals_out)

        value_in = amount_in * price_in
        value_out = amount_out * price_out

        return (
            f"Jupiter Swap Quote\n\n"
            f"Sell: {amount_in:.4f} {token_in} (${value_in:,.2f})\n"
            f"Buy: {amount_out:.4f} {token_out} (${value_out:,.2f})\n\n"
            f"Rate: 1 {token_in} = {amount_out/amount_in:.6f} {token_out}\n"
            f"Price Impact: {price_impact:.2f}%\n"
            f"Slippage: 0.5%\n\n"
            f"To swap: jup.ag"
        )
    except Exception as e:
        return f"Quote error: {str(e)}"


# ============================================================
# 4. Trending Tokens
# ============================================================

def get_sol_trending() -> str:
    """Get trending Solana tokens from Jupiter."""
    # Use the most traded tokens
    trending = [
        ("SOL", "So11111111111111111111111111111111111111112"),
        ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
        ("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),
        ("JUP", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"),
        ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"),
        ("W", "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ"),
        ("TNSR", "TNSRxcUzoT2zWMtqNVpkF3GJfNsAq3oBnKLGEPxRoLP"),
        ("BOME", "ukHH6cRDm1RJGqtBCsVMkZKf9eF5LJfGtn1JYV8RDcF"),
    ]

    mints = ",".join([m for _, m in trending])

    try:
        data = _jupiter_request("/price/v3", {"ids": mints})

        lines = ["Trending Solana Tokens (Jupiter):\n"]
        for name, mint in trending:
            token_data = data.get(mint, {})
            price = token_data.get("usdPrice", 0)
            change = token_data.get("priceChange24h", 0) or 0
            liquidity = token_data.get("liquidity", 0)
            emoji = "🟢" if change >= 0 else "🔴"
            lines.append(f"{emoji} {name}: ${price:.8f} ({change:+.1f}%) | Liq: ${liquidity:,.0f}")

        return "\n".join(lines)
    except Exception as e:
        return f"Trending error: {str(e)}"


# ============================================================
# 5. Token Search
# ============================================================

def search_sol_token(query: str) -> str:
    """Search for a Solana token by name or symbol."""
    # Check known tokens first
    results = []
    for symbol, mint in SOLANA_TOKENS.items():
        if query.upper() in symbol:
            results.append((symbol, mint))

    if not results:
        # Try all known tokens
        for symbol, mint in SOLANA_TOKENS.items():
            results.append((symbol, mint))

    if not results:
        return f"No tokens found for '{query}'"

    # Get prices for found tokens
    mints = ",".join([m for _, m in results[:5]])

    try:
        data = _jupiter_request("/price/v3", {"ids": mints})

        lines = [f"Token Search: '{query}'\n"]
        for symbol, mint in results[:5]:
            token_data = data.get(mint, {})
            price = token_data.get("usdPrice", 0)
            change = token_data.get("priceChange24h", 0) or 0
            emoji = "🟢" if change >= 0 else "🔴"
            lines.append(f"{emoji} {symbol}: ${price:.8f} ({change:+.1f}%)")

        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {str(e)}"


# ============================================================
# Tool Registry
# ============================================================

JUPITER_TOOLS = [
    {"type": "function", "function": {"name": "scan_sol_token", "description": "Scan a Solana token for rug pull risk using Jupiter data.", "parameters": {"type": "object", "properties": {"token_address": {"type": "string"}}, "required": ["token_address"]}}},
    {"type": "function", "function": {"name": "get_sol_price", "description": "Get Solana token price from Jupiter.", "parameters": {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}}},
    {"type": "function", "function": {"name": "get_sol_swap_quote", "description": "Get swap quote from Jupiter for Solana tokens.", "parameters": {"type": "object", "properties": {"token_in": {"type": "string"}, "token_out": {"type": "string"}, "amount": {"type": "number"}}, "required": ["token_in", "token_out"]}}},
    {"type": "function", "function": {"name": "get_sol_trending", "description": "Get trending Solana tokens from Jupiter.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "search_sol_token", "description": "Search for a Solana token by name or symbol.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

JUPITER_TOOL_MAP = {
    "scan_sol_token": lambda a: scan_sol_token(a["token_address"]),
    "get_sol_price": lambda a: get_sol_price(a["token"]),
    "get_sol_swap_quote": lambda a: get_sol_swap_quote(a["token_in"], a["token_out"], float(a.get("amount", 1.0))),
    "get_sol_trending": lambda a: get_sol_trending(),
    "search_sol_token": lambda a: search_sol_token(a["query"]),
}
