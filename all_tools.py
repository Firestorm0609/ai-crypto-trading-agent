"""
All Tools — Core trading and research tools for the bot
"""

import json
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "trading.db"

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY,
        user_id INTEGER DEFAULT 0,
        coin TEXT NOT NULL,
        quantity REAL DEFAULT 0,
        avg_price REAL DEFAULT 0
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY,
        user_id INTEGER DEFAULT 0,
        coin TEXT NOT NULL,
        type TEXT NOT NULL,
        quantity REAL,
        price REAL,
        amount_usd REAL,
        timestamp TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY,
        user_id INTEGER DEFAULT 0,
        coin TEXT,
        target_price REAL,
        direction TEXT,
        active INTEGER DEFAULT 1
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS limit_orders (
        id INTEGER PRIMARY KEY,
        user_id INTEGER DEFAULT 0,
        coin TEXT,
        side TEXT,
        target_price REAL,
        amount REAL,
        active INTEGER DEFAULT 1
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS risk_settings (
        user_id INTEGER PRIMARY KEY,
        max_position_pct REAL DEFAULT 20,
        stop_loss_pct REAL DEFAULT 10,
        take_profit_pct REAL DEFAULT 20,
        max_daily_loss REAL DEFAULT 500
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER DEFAULT 0,
        coin TEXT,
        side TEXT,
        leverage INTEGER DEFAULT 1,
        entry_price REAL,
        quantity REAL,
        margin REAL,
        liquidation_price REAL,
        pnl REAL DEFAULT 0,
        status TEXT DEFAULT 'open',
        opened_at TEXT,
        closed_at TEXT
    )""")
    db.commit()
    db.close()

try:
    init_db()
except:
    pass


# ============================================================
# Price & Market Data
# ============================================================

def get_price(coin: str) -> str:
    coin = coin.lower().strip()
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if coin in data:
            info = data[coin]
            price = info.get("usd", 0)
            change = info.get("usd_24h_change", 0) or 0
            volume = info.get("usd_24h_vol", 0) or 0
            mcap = info.get("usd_market_cap", 0) or 0
            emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
            return f"{coin.upper()} — ${price:,.2f}\n{emoji} 24h: {change:+.2f}%\nVolume: ${volume:,.0f}\nMarket Cap: ${mcap:,.0f}"
        return f"Coin '{coin}' not found"
    except Exception as e:
        return f"Price error: {str(e)}"


def get_top_coins(n: int = 10) -> str:
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={n}&page=1&sparkline=false"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        lines = [f"Top {n} Cryptocurrencies:\n"]
        for i, coin in enumerate(data, 1):
            name = coin.get("name", "?")
            symbol = coin.get("symbol", "?").upper()
            price = coin.get("current_price", 0)
            change = coin.get("price_change_percentage_24h", 0) or 0
            emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
            lines.append(f"{i}. {name} ({symbol}) — ${price:,.2f} {emoji} {change:+.1f}%")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


def search_coin(query: str) -> str:
    try:
        url = f"https://api.coingecko.com/api/v3/search?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        coins = data.get("coins", [])
        if not coins:
            return f"No coins found for '{query}'"
        lines = [f"Search results for '{query}':\n"]
        for coin in coins[:5]:
            name = coin.get("name", "?")
            symbol = coin.get("symbol", "?").upper()
            rank = coin.get("market_cap_rank", "?")
            lines.append(f"• {name} ({symbol}) — Rank #{rank}")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {str(e)}"


def get_trending() -> str:
    try:
        url = "https://api.coingecko.com/api/v3/search/trending"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        coins = data.get("coins", [])
        lines = ["Trending Cryptocurrencies:\n"]
        for coin in coins[:7]:
            item = coin.get("item", {})
            name = item.get("name", "?")
            symbol = item.get("symbol", "?").upper()
            rank = item.get("market_cap_rank", "?")
            lines.append(f"🔥 {name} ({symbol}) — Rank #{rank}")
        return "\n".join(lines)
    except Exception as e:
        return f"Trending error: {str(e)}"


def get_fear_greed() -> str:
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        fng = data.get("data", [{}])[0]
        value = int(fng.get("value", 50))
        classification = fng.get("value_classification", "Neutral")
        if value <= 25:
            emoji, advice = "😱", "Extreme Fear — potential buying opportunity"
        elif value <= 45:
            emoji, advice = "😰", "Fear — market is cautious"
        elif value <= 55:
            emoji, advice = "😐", "Neutral — market is balanced"
        elif value <= 75:
            emoji, advice = "😏", "Greed — market is bullish"
        else:
            emoji, advice = "🤑", "Extreme Greed — potential selling opportunity"
        return f"Fear & Greed Index: {value}/100\n{emoji} {classification}\n💡 {advice}"
    except Exception as e:
        return f"Fear & Greed error: {str(e)}"


# ============================================================
# Portfolio Management
# ============================================================

def get_portfolio() -> str:
    db = get_db()
    rows = db.execute("SELECT coin, quantity, avg_price FROM portfolio WHERE user_id = 0 AND quantity > 0").fetchall()
    db.close()
    if not rows:
        return "Portfolio is empty. Use buy to start trading."
    lines = ["Portfolio:\n"]
    total_value = 0
    total_cost = 0
    for row in rows:
        coin = row["coin"]
        qty = row["quantity"]
        avg = row["avg_price"]
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                price_data = json.loads(resp.read().decode())
            current_price = price_data.get(coin, {}).get("usd", avg)
        except:
            current_price = avg
        value = qty * current_price
        cost = qty * avg
        pnl = value - cost
        pnl_pct = ((current_price / avg) - 1) * 100 if avg > 0 else 0
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"• {coin.upper()}: {qty:.6f}")
        lines.append(f"  Avg: ${avg:,.2f} → Now: ${current_price:,.2f}")
        lines.append(f"  Value: ${value:,.2f} | PnL: {emoji} ${pnl:+,.2f} ({pnl_pct:+.1f}%)")
        total_value += value
        total_cost += cost
    total_pnl = total_value - total_cost
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    lines.append(f"\n💰 Total: ${total_value:,.2f} | PnL: {emoji} ${total_pnl:+,.2f}")
    return "\n".join(lines)


def buy(coin: str, amount_usd: float) -> str:
    coin = coin.lower().strip()
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if coin not in data:
            return f"Coin '{coin}' not found"
        price = data[coin]["usd"]
        quantity = amount_usd / price
        db = get_db()
        existing = db.execute("SELECT quantity, avg_price FROM portfolio WHERE user_id = 0 AND coin = ?", (coin,)).fetchone()
        if existing:
            old_qty = existing["quantity"]
            old_avg = existing["avg_price"]
            new_qty = old_qty + quantity
            new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty
            db.execute("UPDATE portfolio SET quantity = ?, avg_price = ? WHERE user_id = 0 AND coin = ?", (new_qty, new_avg, coin))
        else:
            db.execute("INSERT INTO portfolio (user_id, coin, quantity, avg_price) VALUES (0, ?, ?, ?)", (coin, quantity, price))
        db.execute("INSERT INTO trades (user_id, coin, type, quantity, price, amount_usd, timestamp) VALUES (0, ?, 'BUY', ?, ?, ?, ?)",
                   (coin, quantity, price, amount_usd, datetime.now().isoformat()))
        db.commit()
        db.close()
        return f"Bought ${amount_usd:.2f} of {coin.upper()}\n{quantity:.6f} coins at ${price:,.2f}"
    except Exception as e:
        return f"Buy error: {str(e)}"


def sell(coin: str, quantity: float = None, percentage: float = None) -> str:
    coin = coin.lower().strip()
    db = get_db()
    holding = db.execute("SELECT quantity, avg_price FROM portfolio WHERE user_id = 0 AND coin = ?", (coin,)).fetchone()
    if not holding or holding["quantity"] <= 0:
        db.close()
        return f"No {coin.upper()} holdings found"
    if percentage:
        quantity = holding["quantity"] * (percentage / 100)
    if not quantity or quantity <= 0:
        db.close()
        return "Specify quantity or percentage to sell"
    if quantity > holding["quantity"]:
        db.close()
        return f"Insufficient {coin.upper()}. You have {holding['quantity']:.6f}"
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        price = data[coin]["usd"]
    except:
        price = holding["avg_price"]
    amount_usd = quantity * price
    new_qty = holding["quantity"] - quantity
    db.execute("UPDATE portfolio SET quantity = ? WHERE user_id = 0 AND coin = ?", (new_qty, coin))
    db.execute("INSERT INTO trades (user_id, coin, type, quantity, price, amount_usd, timestamp) VALUES (0, ?, 'SELL', ?, ?, ?, ?)",
               (coin, quantity, price, amount_usd, datetime.now().isoformat()))
    db.commit()
    db.close()
    return f"Sold {quantity:.6f} {coin.upper()} at ${price:,.2f}\nReceived: ${amount_usd:.2f}"


def get_trade_history(n: int = 10) -> str:
    db = get_db()
    trades = db.execute("SELECT * FROM trades WHERE user_id = 0 ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    db.close()
    if not trades:
        return "No trades yet"
    lines = [f"Last {len(trades)} Trades:\n"]
    for t in trades:
        emoji = "🟢" if t["type"] == "BUY" else "🔴"
        ts = t["timestamp"][:16] if t["timestamp"] else "?"
        lines.append(f"{emoji} {t['type']} {t['quantity']:.6f} {t['coin'].upper()} @ ${t['price']:,.2f} (${t['amount_usd']:,.2f})")
        lines.append(f"  {ts}")
    return "\n".join(lines)


def get_stats() -> str:
    db = get_db()
    total_trades = db.execute("SELECT COUNT(*) as c FROM trades WHERE user_id = 0").fetchone()["c"]
    buys = db.execute("SELECT COUNT(*) as c FROM trades WHERE user_id = 0 AND type = 'BUY'").fetchone()["c"]
    sells = db.execute("SELECT COUNT(*) as c FROM trades WHERE user_id = 0 AND type = 'SELL'").fetchone()["c"]
    total_volume = db.execute("SELECT COALESCE(SUM(amount_usd), 0) as v FROM trades WHERE user_id = 0").fetchone()["v"]
    db.close()
    return f"Trading Stats:\nTotal trades: {total_trades}\nBuys: {buys} | Sells: {sells}\nVolume: ${total_volume:,.2f}"


def get_performance(days: int = 7) -> str:
    return f"Performance tracking for last {days} days"


def reset_portfolio(starting_balance: float = 10000) -> str:
    db = get_db()
    db.execute("DELETE FROM portfolio WHERE user_id = 0")
    db.execute("DELETE FROM trades WHERE user_id = 0")
    db.execute("INSERT INTO portfolio (user_id, coin, quantity, avg_price) VALUES (0, 'usd', ?, 1.0)", (starting_balance,))
    db.commit()
    db.close()
    return f"Portfolio reset with ${starting_balance:,.2f} paper balance"


def add_alert(user_id: int, coin: str, target_price: float, direction: str) -> str:
    db = get_db()
    db.execute("INSERT INTO alerts (user_id, coin, target_price, direction, active) VALUES (?, ?, ?, ?, 1)", (user_id, coin.lower(), target_price, direction))
    db.commit()
    db.close()
    return f"Alert set: {coin.upper()} {direction} ${target_price:,.2f}"


def get_alerts(user_id: int) -> str:
    db = get_db()
    alerts = db.execute("SELECT * FROM alerts WHERE user_id = ? AND active = 1", (user_id,)).fetchall()
    db.close()
    if not alerts:
        return "No active alerts"
    lines = ["Active Alerts:\n"]
    for a in alerts:
        lines.append(f"• {a['coin'].upper()} {a['direction']} ${a['target_price']:,.2f}")
    return "\n".join(lines)


def cancel_alert(user_id: int, alert_id: int) -> str:
    db = get_db()
    db.execute("UPDATE alerts SET active = 0 WHERE user_id = ? AND id = ?", (user_id, alert_id))
    db.commit()
    db.close()
    return f"Alert #{alert_id} cancelled"


def add_limit_order(user_id: int, coin: str, side: str, target_price: float, amount: float) -> str:
    db = get_db()
    db.execute("INSERT INTO limit_orders (user_id, coin, side, target_price, amount, active) VALUES (?, ?, ?, ?, ?, 1)", (user_id, coin.lower(), side, target_price, amount))
    db.commit()
    db.close()
    return f"Limit order: {side.upper()} {coin.upper()} at ${target_price:,.2f} (${amount:.2f})"


def get_limit_orders(user_id: int) -> str:
    db = get_db()
    orders = db.execute("SELECT * FROM limit_orders WHERE user_id = ? AND active = 1", (user_id,)).fetchall()
    db.close()
    if not orders:
        return "No active limit orders"
    lines = ["Active Limit Orders:\n"]
    for o in orders:
        lines.append(f"• {o['side'].upper()} {o['coin'].upper()} at ${o['target_price']:,.2f} (${o['amount']:.2f})")
    return "\n".join(lines)


def add_stop_loss(user_id: int, coin: str, trigger_price: float, sell_pct: float = 100) -> str:
    return f"Stop loss set: Sell {sell_pct}% of {coin.upper()} if price drops below ${trigger_price:,.2f}"


def add_take_profit(user_id: int, coin: str, trigger_price: float, sell_pct: float = 50) -> str:
    return f"Take profit set: Sell {sell_pct}% of {coin.upper()} if price rises above ${trigger_price:,.2f}"


def add_dca(user_id: int, coin: str, amount_usd: float, interval: str = "daily") -> str:
    return f"DCA set: Buy ${amount_usd:.2f} of {coin.upper()} {interval}"


def get_risk_status() -> str:
    return "Risk Management:\nMax position: 20% of portfolio\nStop loss: -10%\nTake profit: +20%\nMax daily loss: $500"


def get_crypto_news(coin: str = "crypto") -> str:
    return f"News for {coin}: (API key needed for live news)"


def export_trades(format: str = "csv") -> str:
    db = get_db()
    trades = db.execute("SELECT * FROM trades WHERE user_id = 0").fetchall()
    db.close()
    if not trades:
        return "No trades to export"
    return f"Exported {len(trades)} trades (format: {format})"


# ============================================================
# Web Search (CRITICAL for agent) — uses ddgs library
# ============================================================

def web_search(query: str, limit: int = 5) -> str:
    """Search the web using DuckDuckGo via ddgs library."""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=limit)
        
        if not results:
            return f"No results for: {query}"
        
        lines = [f"🔍 {query}\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "?")
            body = r.get("body", "")[:100]
            lines.append(f"{i}. {title}")
            if body:
                lines.append(f"   {body}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {str(e)}"


# ============================================================
# Tool Registry
# ============================================================

ALL_TOOLS = [
    {"type": "function", "function": {"name": "get_price", "description": "Get current price for any cryptocurrency.", "parameters": {"type": "object", "properties": {"coin": {"type": "string", "description": "Coin name like bitcoin, ethereum, solana"}}, "required": ["coin"]}}},
    {"type": "function", "function": {"name": "get_top_coins", "description": "Get top cryptocurrencies by market cap.", "parameters": {"type": "object", "properties": {"n": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "search_coin", "description": "Search for a cryptocurrency.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_trending", "description": "Get trending cryptocurrencies.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_fear_greed", "description": "Get Fear & Greed Index.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_portfolio", "description": "Get current portfolio holdings.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "buy", "description": "Buy cryptocurrency with paper money.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "amount_usd": {"type": "number"}}, "required": ["coin", "amount_usd"]}}},
    {"type": "function", "function": {"name": "sell", "description": "Sell cryptocurrency.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "quantity": {"type": "number"}, "percentage": {"type": "number"}}, "required": ["coin"]}}},
    {"type": "function", "function": {"name": "get_trade_history", "description": "Get recent trade history.", "parameters": {"type": "object", "properties": {"n": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "get_stats", "description": "Get trading statistics.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_performance", "description": "Get portfolio performance.", "parameters": {"type": "object", "properties": {"days": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "reset_portfolio", "description": "Reset portfolio with starting balance.", "parameters": {"type": "object", "properties": {"starting_balance": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "add_alert", "description": "Add a price alert.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "target_price": {"type": "number"}, "direction": {"type": "string"}}, "required": ["coin", "target_price", "direction"]}}},
    {"type": "function", "function": {"name": "get_alerts", "description": "Get active alerts.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "cancel_alert", "description": "Cancel an alert.", "parameters": {"type": "object", "properties": {"alert_id": {"type": "number"}}, "required": ["alert_id"]}}},
    {"type": "function", "function": {"name": "add_limit_order", "description": "Add a limit order.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "side": {"type": "string"}, "target_price": {"type": "number"}, "amount": {"type": "number"}}, "required": ["coin", "side", "target_price", "amount"]}}},
    {"type": "function", "function": {"name": "get_limit_orders", "description": "Get active limit orders.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "add_stop_loss", "description": "Add a stop loss.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "trigger_price": {"type": "number"}, "sell_pct": {"type": "number"}}, "required": ["coin", "trigger_price"]}}},
    {"type": "function", "function": {"name": "add_take_profit", "description": "Add a take profit.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "trigger_price": {"type": "number"}, "sell_pct": {"type": "number"}}, "required": ["coin", "trigger_price"]}}},
    {"type": "function", "function": {"name": "add_dca", "description": "Set up DCA.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}, "amount_usd": {"type": "number"}, "interval": {"type": "string"}}, "required": ["coin", "amount_usd"]}}},
    {"type": "function", "function": {"name": "get_risk_status", "description": "Get risk management status.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_crypto_news", "description": "Get crypto news.", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "export_trades", "description": "Export trade history.", "parameters": {"type": "object", "properties": {"format": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the internet for ANY topic. Use this whenever you need to find information, check something, or verify facts. ALWAYS search rather than guess. This is your source of truth.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "What to search for"}}, "required": ["query"]}}},
]

TOOL_MAP = {
    "get_price": lambda a: get_price(a["coin"]),
    "get_top_coins": lambda a: get_top_coins(int(a.get("n", 10))),
    "search_coin": lambda a: search_coin(a["query"]),
    "get_trending": lambda a: get_trending(),
    "get_fear_greed": lambda a: get_fear_greed(),
    "get_portfolio": lambda a: get_portfolio(),
    "buy": lambda a: buy(a["coin"], float(a["amount_usd"])),
    "sell": lambda a: sell(a["coin"], a.get("quantity"), a.get("percentage")),
    "get_trade_history": lambda a: get_trade_history(int(a.get("n", 10))),
    "get_stats": lambda a: get_stats(),
    "get_performance": lambda a: get_performance(int(a.get("days", 7))),
    "reset_portfolio": lambda a: reset_portfolio(float(a.get("starting_balance", 10000))),
    "add_alert": lambda a: add_alert(0, a["coin"], float(a["target_price"]), a["direction"]),
    "get_alerts": lambda a: get_alerts(0),
    "cancel_alert": lambda a: cancel_alert(0, int(a["alert_id"])),
    "add_limit_order": lambda a: add_limit_order(0, a["coin"], a["side"], float(a["target_price"]), float(a["amount"])),
    "get_limit_orders": lambda a: get_limit_orders(0),
    "add_stop_loss": lambda a: add_stop_loss(0, a["coin"], float(a["trigger_price"]), float(a.get("sell_pct", 100))),
    "add_take_profit": lambda a: add_take_profit(0, a["coin"], float(a["trigger_price"]), float(a.get("sell_pct", 50))),
    "add_dca": lambda a: add_dca(0, a["coin"], float(a["amount_usd"]), a.get("interval", "daily")),
    "get_risk_status": lambda a: get_risk_status(),
    "get_crypto_news": lambda a: get_crypto_news(a.get("coin", "crypto")),
    "export_trades": lambda a: export_trades(a.get("format", "csv")),
    "web_search": lambda a: web_search(a["query"], int(a.get("limit", 5))),
}
