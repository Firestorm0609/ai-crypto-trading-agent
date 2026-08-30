"""
Advanced Trading Features:
- Price alerts with background monitoring
- Portfolio analytics/stats
- Auto-trading strategies (RSI, MA, DCA)
- News sentiment analysis
- Fear & Greed Index
- Risk management
"""

import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from trading_tools import _load_portfolio, get_price, _save_portfolio

# ============================================================
# Database Setup
# ============================================================

DB_PATH = Path(__file__).parent / "trading.db"

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            coin TEXT NOT NULL,
            target_price REAL NOT NULL,
            direction TEXT NOT NULL,  -- 'above' or 'below'
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            triggered_at TEXT
        );
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            strategy_type TEXT NOT NULL,  -- 'rsi', 'ma_cross', 'dca'
            coin TEXT NOT NULL,
            params TEXT NOT NULL,  -- JSON
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            total_value REAL NOT NULL,
            balance REAL NOT NULL,
            positions TEXT NOT NULL  -- JSON
        );
    """)
    conn.commit()
    conn.close()

init_db()


# ============================================================
# Price Alerts
# ============================================================

def add_alert(user_id: int, coin: str, target_price: float, direction: str) -> str:
    """Add a price alert."""
    conn = get_db()
    conn.execute(
        "INSERT INTO alerts (user_id, coin, target_price, direction) VALUES (?, ?, ?, ?)",
        (user_id, coin.lower(), target_price, direction)
    )
    conn.commit()
    conn.close()
    emoji = "📈" if direction == "above" else "📉"
    return f"{emoji} Alert set: {coin.upper()} {direction} ${target_price:,.2f}"

def get_alerts(user_id: int) -> str:
    """List active alerts for a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE user_id = ? AND active = 1 ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return "No active alerts."

    lines = ["📢 *Active Price Alerts:\n"]
    for r in rows:
        emoji = "📈" if r["direction"] == "above" else "📉"
        lines.append(f"{emoji} #{r['id']}: {r['coin'].upper()} {r['direction']} ${r['target_price']:,.2f}")
    return "\n".join(lines)

def cancel_alert(user_id: int, alert_id: int) -> str:
    """Cancel an alert."""
    conn = get_db()
    conn.execute(
        "UPDATE alerts SET active = 0 WHERE id = ? AND user_id = ?",
        (alert_id, user_id)
    )
    conn.commit()
    conn.close()
    return f"Alert #{alert_id} cancelled."

def check_alerts() -> list:
    """Check all active alerts and return triggered ones."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM alerts WHERE active = 1").fetchall()
    triggered = []

    for r in rows:
        try:
            price_data = get_price(r["coin"])
            # Parse price from response
            import re
            price_match = re.search(r'\$[\d,]+\.?\d*', price_data)
            if price_match:
                current_price = float(price_match.group().replace("$", "").replace(",", ""))

                if r["direction"] == "above" and current_price >= r["target_price"]:
                    triggered.append({
                        "user_id": r["user_id"],
                        "coin": r["coin"],
                        "current_price": current_price,
                        "target_price": r["target_price"],
                        "direction": "above",
                    })
                    conn.execute("UPDATE alerts SET active = 0, triggered_at = ? WHERE id = ?",
                                (datetime.now().isoformat(), r["id"]))
                elif r["direction"] == "below" and current_price <= r["target_price"]:
                    triggered.append({
                        "user_id": r["user_id"],
                        "coin": r["coin"],
                        "current_price": current_price,
                        "target_price": r["target_price"],
                        "direction": "below",
                    })
                    conn.execute("UPDATE alerts SET active = 0, triggered_at = ? WHERE id = ?",
                                (datetime.now().isoformat(), r["id"]))
        except Exception as e:
            continue

    conn.commit()
    conn.close()
    return triggered


# ============================================================
# Portfolio Analytics
# ============================================================

def get_stats(user_id: int = 0) -> str:
    """Get portfolio analytics."""
    portfolio = _load_portfolio()
    trades = portfolio.get("trades", [])

    if not trades:
        return "No trades yet. Start trading to see stats!"

    # Calculate stats
    buys = [t for t in trades if t["type"] == "BUY"]
    sells = [t for t in trades if t["type"] == "SELL"]

    total_trades = len(trades)
    total_buys = len(buys)
    total_sells = len(sells)

    # P&L
    total_pnl = sum(t.get("pnl", 0) for t in sells)
    winning_trades = [t for t in sells if t.get("pnl", 0) > 0]
    losing_trades = [t for t in sells if t.get("pnl", 0) < 0]

    win_rate = (len(winning_trades) / len(sells) * 100) if sells else 0
    avg_win = sum(t["pnl"] for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t["pnl"] for t in losing_trades) / len(losing_trades) if losing_trades else 0

    # Best/worst trades
    best_trade = max(sells, key=lambda t: t.get("pnl", 0)) if sells else None
    worst_trade = min(sells, key=lambda t: t.get("pnl", 0)) if sells else None

    # Current holdings
    positions = portfolio.get("positions", {})
    total_invested = sum(t["amount_usd"] for t in buys)

    lines = [f"📊 *Portfolio Stats*\n"]
    lines.append(f"Total Trades: {total_trades} ({total_buys} buys, {total_sells} sells)")
    lines.append(f"Win Rate: {win_rate:.1f}% ({len(winning_trades)}W / {len(losing_trades)}L)")
    lines.append(f"Total P&L: {'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:+,.2f}")
    lines.append(f"Avg Win: ${avg_win:+,.2f} | Avg Loss: ${avg_loss:+,.2f}")

    if best_trade:
        lines.append(f"\n🏆 Best: {best_trade['coin'].upper()} ${best_trade['pnl']:+,.2f}")
    if worst_trade:
        lines.append(f"💀 Worst: {worst_trade['coin'].upper()} ${worst_trade['pnl']:+,.2f}")

    lines.append(f"\n💰 Total Invested: ${total_invested:,.2f}")
    lines.append(f"💵 Cash: ${portfolio['balance']:,.2f}")
    lines.append(f"📦 Positions: {len(positions)} coins")

    return "\n".join(lines)


# ============================================================
# Auto-Trading Strategies
# ============================================================

def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI from price list."""
    if len(prices) < period + 1:
        return 50.0  # Default neutral

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_price_history(coin: str, days: int = 30) -> list:
    """Get historical prices from CoinGecko."""
    try:
        coin_map = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
        }
        coin_id = coin_map.get(coin.lower(), coin.lower())

        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        return [p[1] for p in data.get("prices", [])]
    except Exception:
        return []

def add_strategy(user_id: int, strategy_type: str, coin: str, params: dict) -> str:
    """Add an auto-trading strategy."""
    conn = get_db()
    conn.execute(
        "INSERT INTO strategies (user_id, strategy_type, coin, params) VALUES (?, ?, ?, ?)",
        (user_id, strategy_type, coin.lower(), json.dumps(params))
    )
    conn.commit()
    conn.close()

    strategy_names = {
        "rsi": "RSI Oversold/Overbought",
        "ma_cross": "Moving Average Crossover",
        "dca": "Dollar Cost Averaging",
    }
    return f"✅ Strategy added: {strategy_names.get(strategy_type, strategy_type)} on {coin.upper()}"

def get_strategies(user_id: int) -> str:
    """List active strategies."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM strategies WHERE user_id = ? AND active = 1",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return "No active strategies."

    lines = ["🤖 *Active Strategies:\n"]
    for r in rows:
        params = json.loads(r["params"])
        if r["strategy_type"] == "rsi":
            lines.append(f"• RSI on {r['coin'].upper()}: Buy < {params.get('buy_threshold', 30)}, Sell > {params.get('sell_threshold', 70)}")
        elif r["strategy_type"] == "ma_cross":
            lines.append(f"• MA Cross on {r['coin'].upper()}: {params.get('fast', 20)} EMA / {params.get('slow', 50)} EMA")
        elif r["strategy_type"] == "dca":
            lines.append(f"• DCA on {r['coin'].upper()}: ${params.get('amount', 100)}/{params.get('interval', 'daily')}")
    return "\n".join(lines)

def run_strategies() -> list:
    """Run all active strategies and return trade signals."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM strategies WHERE active = 1").fetchall()
    conn.close()

    signals = []
    portfolio = _load_portfolio()

    for r in rows:
        params = json.loads(r["params"])
        coin = r["coin"]

        try:
            if r["strategy_type"] == "rsi":
                prices = get_price_history(coin, 30)
                if len(prices) >= 15:
                    rsi = calculate_rsi(prices)
                    current_price = prices[-1]

                    if rsi < params.get("buy_threshold", 30):
                        # Check if we already have a position
                        if coin not in portfolio.get("positions", {}):
                            amount = params.get("buy_amount", 100)
                            signals.append({
                                "user_id": r["user_id"],
                                "action": "BUY",
                                "coin": coin,
                                "amount_usd": amount,
                                "reason": f"RSI={rsi:.1f} (oversold)",
                                "strategy": "RSI",
                            })
                    elif rsi > params.get("sell_threshold", 70):
                        if coin in portfolio.get("positions", {}):
                            signals.append({
                                "user_id": r["user_id"],
                                "action": "SELL",
                                "coin": coin,
                                "percentage": 50,
                                "reason": f"RSI={rsi:.1f} (overbought)",
                                "strategy": "RSI",
                            })

            elif r["strategy_type"] == "dca":
                # Check if enough time has passed since last DCA buy
                last_buy_time = params.get("last_buy")
                interval = params.get("interval", "daily")

                if last_buy_time:
                    last_dt = datetime.fromisoformat(last_buy_time)
                    now = datetime.now()
                    if interval == "daily" and (now - last_dt).days < 1:
                        continue
                    elif interval == "weekly" and (now - last_dt).days < 7:
                        continue

                amount = params.get("amount", 100)
                signals.append({
                    "user_id": r["user_id"],
                    "action": "BUY",
                    "coin": coin,
                    "amount_usd": amount,
                    "reason": f"DCA {interval} buy",
                    "strategy": "DCA",
                })

                # Update last buy time
                conn = get_db()
                params["last_buy"] = datetime.now().isoformat()
                conn.execute("UPDATE strategies SET params = ? WHERE id = ?",
                            (json.dumps(params), r["id"]))
                conn.commit()
                conn.close()

        except Exception as e:
            continue

    return signals


# ============================================================
# News Sentiment
# ============================================================

def get_crypto_news(coin: str = "crypto") -> str:
    """Fetch and analyze crypto news."""
    try:
        import urllib.parse
        query = f"{coin} cryptocurrency news today"
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Extract results
        results = []
        lines = html.split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if '<a rel="nofollow" class="result-link" href="' in line:
                start = line.find('href="') + 6
                end = line.find('"', start)
                result_url = line[start:end] if start > 5 else ""
                snippet = ""
                for j in range(i+1, min(i+5, len(lines))):
                    if lines[j].strip() and '<' not in lines[j]:
                        snippet = lines[j].strip()
                        break
                if result_url and snippet:
                    results.append(f"• {snippet}")

        if results:
            return f"📰 *Latest {coin.upper()} News:\n\n" + "\n\n".join(results[:5])
        return f"No recent news found for {coin}"
    except Exception as e:
        return f"Error fetching news: {str(e)}"


# ============================================================
# Fear & Greed Index
# ============================================================

def get_fear_greed() -> str:
    """Get the Crypto Fear & Greed Index."""
    try:
        url = "https://api.alternative.me/fng/?limit=7&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        entries = data.get("data", [])
        if not entries:
            return "Unable to fetch Fear & Greed Index"

        current = entries[0]
        value = int(current["value"])
        classification = current["value_classification"]

        # Emoji based on value
        if value <= 25:
            emoji = "🟢🟢🟢"  # Extreme Fear = buying opportunity
        elif value <= 45:
            emoji = "🟢🟢"
        elif value <= 55:
            emoji = "🟡"
        elif value <= 75:
            emoji = "🔴"
        else:
            emoji = "🔴🔴🔴"  # Extreme Greed = caution

        lines = [f"{emoji} *Fear & Greed Index*\n"]
        lines.append(f"Current: {value}/100 ({classification})")

        # 7-day history
        lines.append("\n📅 7-Day History:")
        for e in entries[:7]:
            date = datetime.fromtimestamp(int(e["timestamp"])).strftime("%b %d")
            val = int(e["value"])
            bar = "█" * (val // 5) + "░" * (20 - val // 5)
            lines.append(f"  {date}: [{bar}] {val}")

        # Interpretation
        if value <= 25:
            lines.append("\n💡 *Interpretation:* Extreme Fear — potential buying opportunity")
        elif value <= 45:
            lines.append("\n💡 *Interpretation:* Fear — market is cautious")
        elif value <= 55:
            lines.append("\n💡 *Interpretation:* Neutral — market is balanced")
        elif value <= 75:
            lines.append("\n💡 *Interpretation:* Greed — be cautious with new positions")
        else:
            lines.append("\n💡 *Interpretation:* Extreme Greed — consider taking profits")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching Fear & Greed: {str(e)}"


# ============================================================
# Risk Management
# ============================================================

def get_risk_settings(user_id: int = 0) -> dict:
    """Get risk management settings."""
    config_path = Path(__file__).parent / "risk_config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {
        "max_position_pct": 25,  # Max 25% of portfolio in one coin
        "max_total_exposure": 80,  # Max 80% invested
        "stop_loss_pct": 20,  # 20% stop loss
        "take_profit_pct": 50,  # 50% take profit
    }

def save_risk_settings(settings: dict):
    """Save risk management settings."""
    config_path = Path(__file__).parent / "risk_config.json"
    config_path.write_text(json.dumps(settings, indent=2))

def check_risk(coin: str, amount_usd: float) -> str:
    """Check if a trade meets risk management rules."""
    settings = get_risk_settings()
    portfolio = _load_portfolio()

    total_value = portfolio["balance"]
    for c, pos in portfolio.get("positions", {}).items():
        try:
            price_data = get_price(c)
            import re
            price_match = re.search(r'\$[\d,]+\.?\d*', price_data)
            if price_match:
                price = float(price_match.group().replace("$", "").replace(",", ""))
                total_value += pos["quantity"] * price
        except:
            total_value += pos.get("quantity", 0) * pos.get("avg_price", 0)

    # Check max position size
    current_position = 0
    if coin.lower() in portfolio.get("positions", {}):
        pos = portfolio["positions"][coin.lower()]
        current_position = pos["quantity"] * pos.get("avg_price", 0)

    new_position = current_position + amount_usd
    position_pct = (new_position / total_value * 100) if total_value > 0 else 0

    if position_pct > settings["max_position_pct"]:
        return f"⚠️ Risk Warning: {coin.upper()} would be {position_pct:.1f}% of portfolio (max: {settings['max_position_pct']}%)"

    # Check total exposure
    total_invested = sum(
        pos.get("quantity", 0) * pos.get("avg_price", 0)
        for pos in portfolio.get("positions", {}).values()
    )
    new_total = total_invested + amount_usd
    exposure_pct = (new_total / total_value * 100) if total_value > 0 else 0

    if exposure_pct > settings["max_total_exposure"]:
        return f"⚠️ Risk Warning: Total exposure would be {exposure_pct:.1f}% (max: {settings['max_total_exposure']}%)"

    return "✅ Trade approved by risk management"

def get_risk_status() -> str:
    """Get current risk status."""
    settings = get_risk_settings()
    portfolio = _load_portfolio()

    total_value = portfolio["balance"]
    for c, pos in portfolio.get("positions", {}).items():
        total_value += pos.get("quantity", 0) * pos.get("avg_price", 0)

    total_invested = sum(
        pos.get("quantity", 0) * pos.get("avg_price", 0)
        for pos in portfolio.get("positions", {}).values()
    )

    exposure_pct = (total_invested / total_value * 100) if total_value > 0 else 0

    lines = [f"🛡️ *Risk Management Status*\n"]
    lines.append(f"Max Position Size: {settings['max_position_pct']}%")
    lines.append(f"Max Total Exposure: {settings['max_total_exposure']}%")
    lines.append(f"Stop Loss: {settings['stop_loss_pct']}%")
    lines.append(f"Take Profit: {settings['take_profit_pct']}%")
    lines.append(f"\nCurrent Exposure: {exposure_pct:.1f}% of ${total_value:,.2f}")

    if exposure_pct > settings['max_total_exposure']:
        lines.append("⚠️ WARNING: Over-exposed!")
    else:
        lines.append("✅ Within limits")

    return "\n".join(lines)


# ============================================================
# Daily Snapshot (for tracking performance over time)
# ============================================================

def save_daily_snapshot():
    """Save today's portfolio snapshot."""
    portfolio = _load_portfolio()
    total_value = portfolio["balance"]
    for c, pos in portfolio.get("positions", {}).items():
        total_value += pos.get("quantity", 0) * pos.get("avg_price", 0)

    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO daily_snapshots (date, total_value, balance, positions) VALUES (?, ?, ?, ?)",
        (today, total_value, portfolio["balance"], json.dumps(portfolio.get("positions", {})))
    )
    conn.commit()
    conn.close()

def get_performance_chart(days: int = 7) -> str:
    """Get performance over time as text chart."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM daily_snapshots ORDER BY date DESC LIMIT ?",
        (days,)
    ).fetchall()
    conn.close()

    if not rows:
        return "No historical data yet. Snapshots are saved daily."

    rows = list(reversed(rows))
    values = [r["total_value"] for r in rows]
    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val if max_val != min_val else 1

    lines = ["📈 *Portfolio Performance:\n"]
    for r in rows:
        date = r["date"]
        val = r["total_value"]
        bar_len = int((val - min_val) / val_range * 20) if val_range > 0 else 10
        bar = "█" * bar_len
        lines.append(f"  {date}: [{bar}] ${val:,.0f}")

    if len(values) >= 2:
        change = ((values[-1] - values[0]) / values[0] * 100) if values[0] > 0 else 0
        emoji = "🟢" if change >= 0 else "🔴"
        lines.append(f"\n{emoji} {days}-day change: {change:+,.1f}%")

    return "\n".join(lines)
