"""
Robinhood Crypto Trading API Integration.

Features:
- View crypto portfolio/holdings
- Place market orders (buy/sell)
- View order history
- Get market data/quotes
- Fee tier support (v2 API)

Requirements:
- Robinhood account with crypto enabled
- API key from Robinhood web classic
"""

import json
import time
import hashlib
import hmac
import base64
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

# ============================================================
# Configuration
# ============================================================

ROBINHOOD_API_BASE = "https://api.robinhood.com"
ROBINHOOD_CONFIG = Path(__file__).parent / "robinhood_config.json"

# Supported cryptos on Robinhood
# NO HARDCODED LIST — agent discovers dynamically
# The agent uses web_search and API calls to find what's available
# This is how an agent should work — not from a static dictionary


# ============================================================
# Authentication
# ============================================================

def load_robinhood_config() -> dict:
    """Load Robinhood API config."""
    if ROBINHOOD_CONFIG.exists():
        return json.loads(ROBINHOOD_CONFIG.read_text())
    return {"api_key": "", "api_secret": ""}

def save_robinhood_config(config: dict):
    """Save Robinhood API config."""
    ROBINHOOD_CONFIG.write_text(json.dumps(config, indent=2))

def robinhood_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Make an authenticated Robinhood API request."""
    config = load_robinhood_config()
    if not config.get("api_key"):
        return {"error": "Robinhood API key not configured. Use /rhsetup to set up."}

    url = f"{ROBINHOOD_API_BASE}{endpoint}"

    # Build headers
    headers = {
        "Authorization": f"Api-Key {config['api_key']}",
        "Content-Type": "application/json",
    }

    # Build request
    if data:
        payload = json.dumps(data).encode()
    else:
        payload = None

    req = urllib.request.Request(url, data=payload, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return {"error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Account & Portfolio
# ============================================================

def get_robinhood_account() -> str:
    """Get Robinhood account info."""
    result = robinhood_request("GET", "/crypto/accounts/")
    if "error" in result:
        return f"❌ {result['error']}"

    accounts = result.get("results", [])
    if not accounts:
        return "No Robinhood crypto accounts found."

    lines = ["🏦 *Robinhood Crypto Account*\n"]
    for acc in accounts:
        lines.append(f"Account: {acc.get('id', 'N/A')[:12]}...")
        lines.append(f"Status: {acc.get('status', 'N/A')}")
        lines.append(f"Cash: ${float(acc.get('cash', 0)):,.2f}")

    return "\n".join(lines)

def get_robinhood_portfolio() -> str:
    """Get Robinhood crypto portfolio."""
    result = robinhood_request("GET", "/crypto/holdings/")
    if "error" in result:
        return f"❌ {result['error']}"

    holdings = result.get("results", [])
    if not holdings:
        return "No crypto holdings found."

    lines = ["💼 *Robinhood Portfolio*\n"]
    total_value = 0

    for h in holdings:
        symbol = h.get("currency", {}).get("code", "?")
        quantity = float(h.get("quantity", 0))
        avg_price = float(h.get("average_buy_price", 0))
        market_value = float(h.get("market_value", 0))
        pnl = float(h.get("unrealized_pnl", 0))
        pnl_pct = float(h.get("unrealized_pnl_pct", 0))

        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"• {symbol}: {quantity:.6f}")
        lines.append(f"  Avg: ${avg_price:,.2f} → Value: ${market_value:,.2f}")
        lines.append(f"  PnL: {emoji} ${pnl:+,.2f} ({pnl_pct:+.1f}%)")
        total_value += market_value

    lines.append(f"\n💰 Total Value: ${total_value:,.2f}")
    return "\n".join(lines)

def get_robinhood_buying_power() -> str:
    """Get available buying power."""
    result = robinhood_request("GET", "/crypto/accounts/")
    if "error" in result:
        return f"❌ {result['error']}"

    accounts = result.get("results", [])
    if not accounts:
        return "No account found."

    buying_power = float(accounts[0].get("cash", 0))
    return f"💵 Buying Power: ${buying_power:,.2f}"


# ============================================================
# Market Data
# ============================================================

def get_robinhood_quote(symbol: str) -> str:
    """Get Robinhood crypto quote."""
    symbol = symbol.upper()
    result = robinhood_request("GET", f"/crypto_quotes/?symbol={symbol}")
    if "error" in result:
        return f"❌ {result['error']}"

    quotes = result.get("results", [])
    if not quotes:
        return f"No quote found for {symbol}"

    q = quotes[0]
    price = float(q.get("last_trade_price", 0))
    bid = float(q.get("bid_price", 0))
    ask = float(q.get("ask_price", 0))
    high_24h = float(q.get("high_24h", 0))
    low_24h = float(q.get("low_24h", 0))
    vol_24h = float(q.get("volume_24h", 0))

    return (
        f"📊 *{symbol} Quote (Robinhood)*\n\n"
        f"Price: ${price:,.2f}\n"
        f"Bid: ${bid:,.2f} | Ask: ${ask:,.2f}\n"
        f"24h High: ${high_24h:,.2f} | Low: ${low_24h:,.2f}\n"
        f"24h Volume: {vol_24h:,.0f}"
    )

def get_robinhood_products() -> str:
    """List all tradeable cryptos on Robinhood."""
    result = robinhood_request("GET", "/crypto/products/")
    if "error" in result:
        return f"❌ {result['error']}"

    products = result.get("results", [])
    lines = ["🪙 *Tradeable on Robinhood:*\n"]
    for p in products[:50]:
        symbol = p.get("symbol", "?")
        name = p.get("name", "?")
        min_order = p.get("min_order_size", "?")
        lines.append(f"• {symbol} — {name} (min: {min_order})")

    return "\n".join(lines)


def search_robinhood_token(query: str) -> str:
    """Search if a token is available on Robinhood. Dynamic — no hardcoded list."""
    query_upper = query.upper()
    
    # Try API first
    result = robinhood_request("GET", f"/crypto/products/?symbol={query_upper}")
    if "error" not in result:
        products = result.get("results", [])
        if products:
            p = products[0]
            return f"✅ {p.get('symbol')} ({p.get('name')}) IS available on Robinhood!"
    
    # Try name search
    result2 = robinhood_request("GET", f"/crypto/products/?name={query}")
    if "error" not in result2:
        products = result2.get("results", [])
        if products:
            lines = [f"Found {len(products)} matches on Robinhood:\n"]
            for p in products[:5]:
                lines.append(f"• {p.get('symbol')} — {p.get('name')}")
            return "\n".join(lines)
    
    # If API fails or no key, tell agent to search web
    return f"Couldn't verify {query} via API. Agent should use web_search to check Robinhood."


def check_robinhood_chain_token(query: str) -> str:
    """Check if a token is on Robinhood Chain (their L2)."""
    # Robinhood Chain tokens are tokenized versions of stocks/memecoins
    # They use a different API endpoint
    result = robinhood_request("GET", "/crypto/products/")
    if "error" in result:
        return f"❌ {result['error']}"
    
    products = result.get("results", [])
    query_lower = query.lower()
    
    # Search through all products
    matches = []
    for p in products:
        name = p.get("name", "").lower()
        symbol = p.get("symbol", "").lower()
        if query_lower in name or query_lower in symbol:
            matches.append(p)
    
    if matches:
        lines = [f"Found {len(matches)} matches on Robinhood:\n"]
        for p in matches[:10]:
            lines.append(f"• {p.get('symbol')} — {p.get('name')}")
        return "\n".join(lines)
    
    return f"❌ {query} not found on Robinhood. Try web_search to check Robinhood Chain."


# ============================================================
# Trading
# ============================================================

def robinhood_buy(symbol: str, amount_usd: float) -> str:
    """Buy crypto on Robinhood. Dynamic — no hardcoded list."""
    symbol = symbol.upper()

    # Get quote first
    quote_result = robinhood_request("GET", f"/crypto_quotes/?symbol={symbol}")
    if "error" in quote_result:
        return f"❌ Could not get quote: {quote_result['error']}"

    quotes = quote_result.get("results", [])
    if not quotes:
        return f"❌ No quote for {symbol}"

    price = float(quotes[0].get("last_trade_price", 0))
    quantity = amount_usd / price if price > 0 else 0

    # Place order (v2 with fee tiers)
    order_data = {
        "type": "market",
        "side": "buy",
        "symbol": symbol,
        "quantity": str(quantity),
        "amount_in_usd": str(amount_usd),
    }

    result = robinhood_request("POST", "/crypto/orders/v2/", order_data)
    if "error" in result:
        return f"❌ Order failed: {result['error']}"

    order_id = result.get("id", "N/A")
    return (
        f"✅ *BUY ORDER PLACED*\n\n"
        f"Token: {symbol}\n"
        f"Amount: ${amount_usd:,.2f}\n"
        f"Est. Quantity: {quantity:.6f}\n"
        f"Price: ${price:,.2f}\n"
        f"Order ID: `{order_id}`\n\n"
        f"⏳ Order is processing..."
    )

def robinhood_sell(symbol: str, amount_usd: float = None, quantity: float = None) -> str:
    """Sell crypto on Robinhood. Dynamic — no hardcoded list."""
    symbol = symbol.upper()

    # If no amount specified, sell all
    if amount_usd is None and quantity is None:
        # Get holdings to find quantity
        holdings_result = robinhood_request("GET", "/crypto/holdings/")
        if "error" in holdings_result:
            return f"❌ {holdings_result['error']}"

        for h in holdings_result.get("results", []):
            if h.get("currency", {}).get("code") == symbol:
                quantity = float(h.get("quantity", 0))
                break

        if quantity is None or quantity <= 0:
            return f"❌ No {symbol} holdings found."

    # Get quote
    quote_result = robinhood_request("GET", f"/crypto_quotes/?symbol={symbol}")
    if "error" in quote_result:
        return f"❌ {quote_result['error']}"

    quotes = quote_result.get("results", [])
    price = float(quotes[0].get("last_trade_price", 0)) if quotes else 0

    # Calculate quantity if amount_usd provided
    if amount_usd and not quantity:
        quantity = amount_usd / price if price > 0 else 0

    # Place sell order
    order_data = {
        "type": "market",
        "side": "sell",
        "symbol": symbol,
        "quantity": str(quantity),
    }

    result = robinhood_request("POST", "/crypto/orders/v2/", order_data)
    if "error" in result:
        return f"❌ Order failed: {result['error']}"

    proceeds = quantity * price
    return (
        f"✅ *SELL ORDER PLACED*\n\n"
        f"Token: {symbol}\n"
        f"Quantity: {quantity:.6f}\n"
        f"Est. Proceeds: ${proceeds:,.2f}\n"
        f"Price: ${price:,.2f}\n"
        f"Order ID: `{result.get('id', 'N/A')}`\n\n"
        f"⏳ Order is processing..."
    )


# ============================================================
# Order History
# ============================================================

def get_robinhood_orders(limit: int = 10) -> str:
    """Get recent Robinhood orders."""
    result = robinhood_request("GET", f"/crypto/orders/?limit={limit}")
    if "error" in result:
        return f"❌ {result['error']}"

    orders = result.get("results", [])
    if not orders:
        return "No orders found."

    lines = [f"📜 *Recent Robinhood Orders*\n"]
    for o in orders[:limit]:
        side = o.get("side", "?").upper()
        symbol = o.get("symbol", "?")
        status = o.get("state", "?")
        quantity = o.get("quantity", "?")
        price = o.get("price", "?")
        created = o.get("created_at", "?")[:16]

        emoji = "🟢" if side == "BUY" else "🔴"
        status_emoji = "✅" if status == "filled" else "⏳" if status == "pending" else "❌"
        lines.append(f"{emoji} {side} {quantity} {symbol} @ ${price} | {status_emoji} {status} | {created}")

    return "\n".join(lines)


# ============================================================
# Tool Registry
# ============================================================

ROBINHOOD_TOOLS = [
    {"type": "function", "function": {"name": "rh_portfolio", "description": "View Robinhood crypto portfolio.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "rh_account", "description": "View Robinhood account info.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "rh_buying_power", "description": "Check Robinhood buying power.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "rh_quote", "description": "Get Robinhood crypto quote.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "rh_products", "description": "List tradeable cryptos on Robinhood.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "rh_search", "description": "Search if a token is available on Robinhood.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "rh_chain_check", "description": "Check if a token is on Robinhood Chain (their L2).", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "rh_buy", "description": "Buy crypto on Robinhood. REAL MONEY.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "amount_usd": {"type": "number"}}, "required": ["symbol", "amount_usd"]}}},
    {"type": "function", "function": {"name": "rh_sell", "description": "Sell crypto on Robinhood. REAL MONEY.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "amount_usd": {"type": "number"}, "quantity": {"type": "number"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "rh_orders", "description": "View Robinhood order history.", "parameters": {"type": "object", "properties": {"limit": {"type": "number"}}}}},
]

ROBINHOOD_TOOL_MAP = {
    "rh_portfolio": lambda a: get_robinhood_portfolio(),
    "rh_account": lambda a: get_robinhood_account(),
    "rh_buying_power": lambda a: get_robinhood_buying_power(),
    "rh_quote": lambda a: get_robinhood_quote(a["symbol"]),
    "rh_products": lambda a: get_robinhood_products(),
    "rh_search": lambda a: search_robinhood_token(a["query"]),
    "rh_chain_check": lambda a: check_robinhood_chain_token(a["query"]),
    "rh_buy": lambda a: robinhood_buy(a["symbol"], float(a["amount_usd"])),
    "rh_sell": lambda a: robinhood_sell(a["symbol"], a.get("amount_usd"), a.get("quantity")),
    "rh_orders": lambda a: get_robinhood_orders(int(a.get("limit", 10))),
}
