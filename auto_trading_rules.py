"""
Auto-Trading Rules System — Advanced rule-based trading.

Supports:
- Price triggers (buy/sell when price crosses threshold)
- Percentage triggers (buy when drops X%, sell when gains X%)
- Conditional rules (if coin A > price, sell coin B)
- Portfolio rebalancing (keep allocation at X%)
- Time-based (DCA, scheduled buys)
- Stop loss / Take profit (auto-execute)

Rules are stored in SQLite and checked by background worker.
"""

import json
import sqlite3
import time
import urllib.request
import re
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "trading.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_rules_db():
    """Create auto_trading_rules table if not exists."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS auto_trading_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL,
            coin TEXT NOT NULL,
            params TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            last_triggered TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


init_rules_db()


# ============================================================
# Price Helpers
# ============================================================

COINGECKO_ALIASES = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
    "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
    "dot": "polkadot", "matic": "matic-network", "avax": "avalanche-2",
    "link": "chainlink", "bnb": "binancecoin", "usdt": "tether",
    "usdc": "usd-coin", "shib": "shiba-inu", "pepe": "pepe",
    "arb": "arbitrum", "op": "optimism", "sui": "sui", "near": "near",
    "wif": "dogwifhat", "bonk": "bonk", "popcat": "popcat",
}


def get_current_price(coin: str) -> float:
    """Get current USD price for a coin."""
    coin_id = COINGECKO_ALIASES.get(coin.lower().strip(), coin.lower().strip())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get(coin_id, {}).get("usd", 0)
    except Exception:
        return 0


def get_24h_change(coin: str) -> float:
    """Get 24h price change percentage."""
    coin_id = COINGECKO_ALIASES.get(coin.lower().strip(), coin.lower().strip())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get(coin_id, {}).get("usd_24h_change", 0) or 0
    except Exception:
        return 0


# ============================================================
# Rule CRUD
# ============================================================

def add_rule(user_id: int, rule_type: str, coin: str, params: dict) -> str:
    """Add a new auto-trading rule."""
    conn = get_db()
    conn.execute(
        "INSERT INTO auto_trading_rules (user_id, rule_type, coin, params) VALUES (?, ?, ?, ?)",
        (user_id, rule_type, coin.lower(), json.dumps(params))
    )
    conn.commit()
    conn.close()
    return _describe_rule(rule_type, coin, params)


def get_rules(user_id: int) -> str:
    """List all active rules for a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM auto_trading_rules WHERE user_id = ? AND active = 1 ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return "No active trading rules."

    lines = ["🤖 Active Trading Rules:\n"]
    for r in rows:
        params = json.loads(r["params"])
        lines.append(f"#{r['id']} {_describe_rule(r['rule_type'], r['coin'], params)}")
    return "\n".join(lines)


def cancel_rule(user_id: int, rule_id: int) -> str:
    """Cancel a trading rule."""
    conn = get_db()
    conn.execute(
        "UPDATE auto_trading_rules SET active = 0 WHERE id = ? AND user_id = ?",
        (rule_id, user_id)
    )
    conn.commit()
    conn.close()
    return f"Rule #{rule_id} cancelled."


def _describe_rule(rule_type: str, coin: str, params: dict) -> str:
    """Human-readable rule description."""
    coin = coin.upper()
    if rule_type == "price_above":
        return f"📈 Buy {coin} when price > ${params['target_price']:,.2f} (amount: ${params.get('amount_usd', 100)})"
    elif rule_type == "price_below":
        return f"📉 Buy {coin} when price < ${params['target_price']:,.2f} (amount: ${params.get('amount_usd', 100)})"
    elif rule_type == "sell_above":
        return f"📈 Sell {coin} when price > ${params['target_price']:,.2f} ({params.get('percentage', 100)}%)"
    elif rule_type == "sell_below":
        return f"📉 Sell {coin} when price < ${params['target_price']:,.2f} ({params.get('percentage', 100)}%)"
    elif rule_type == "drop_pct":
        return f"🔻 Buy {coin} if it drops {params['drop_pct']}% from current (${params.get('amount_usd', 100)})"
    elif rule_type == "gain_pct":
        return f"🔺 Sell {coin} if it gains {params['gain_pct']}% from entry ({params.get('percentage', 50)}%)"
    elif rule_type == "stop_loss":
        return f"🛑 Stop loss: Sell {coin} if price drops {params['loss_pct']}% from avg entry"
    elif rule_type == "take_profit":
        return f"🎯 Take profit: Sell {coin} if price gains {params['profit_pct']}% from avg entry"
    elif rule_type == "dca":
        return f"💰 DCA: Buy ${params.get('amount_usd', 100)} of {coin} every {params.get('interval', 'daily')}"
    elif rule_type == "rebalance":
        return f"⚖️ Rebalance: Keep {coin} at {params['target_pct']}% of portfolio"
    elif rule_type == "conditional":
        trigger = params.get("trigger_desc", "")
        action = params.get("action_desc", "")
        return f"🔀 IF {trigger} THEN {action}"
    else:
        return f"Rule: {rule_type} on {coin}"


# ============================================================
# Rule Evaluation Engine
# ============================================================

def evaluate_rules() -> list:
    """Check all active rules and return signals for trades."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM auto_trading_rules WHERE active = 1").fetchall()
    conn.close()

    signals = []

    for r in rows:
        params = json.loads(r["params"])
        rule_type = r["rule_type"]
        coin = r["coin"]
        user_id = r["user_id"]
        rule_id = r["id"]

        try:
            signal = _evaluate_single(rule_id, rule_type, coin, params, user_id)
            if signal:
                signals.append(signal)
                # Mark as triggered (prevent re-triggering within cooldown)
                _mark_triggered(rule_id)
        except Exception as e:
            continue

    return signals


def _evaluate_single(rule_id: int, rule_type: str, coin: str, params: dict, user_id: int) -> dict:
    """Evaluate a single rule and return a trade signal if triggered."""
    price = get_current_price(coin)
    if price <= 0:
        return None

    # Cooldown: don't re-trigger within 5 minutes
    conn = get_db()
    row = conn.execute("SELECT last_triggered FROM auto_trading_rules WHERE id = ?", (rule_id,)).fetchone()
    conn.close()
    if row and row["last_triggered"]:
        last = datetime.fromisoformat(row["last_triggered"])
        if (datetime.now() - last).total_seconds() < 300:
            return None

    if rule_type == "price_above":
        if price >= params["target_price"]:
            return {"user_id": user_id, "action": "BUY", "coin": coin, "amount_usd": params.get("amount_usd", 100),
                    "reason": f"Price ${price:,.2f} >= target ${params['target_price']:,.2f}", "strategy": "Price Rule", "rule_id": rule_id}

    elif rule_type == "price_below":
        if price <= params["target_price"]:
            return {"user_id": user_id, "action": "BUY", "coin": coin, "amount_usd": params.get("amount_usd", 100),
                    "reason": f"Price ${price:,.2f} <= target ${params['target_price']:,.2f}", "strategy": "Price Rule", "rule_id": rule_id}

    elif rule_type == "sell_above":
        if price >= params["target_price"]:
            return {"user_id": user_id, "action": "SELL", "coin": coin, "percentage": params.get("percentage", 100),
                    "reason": f"Price ${price:,.2f} >= target ${params['target_price']:,.2f}", "strategy": "Sell Target", "rule_id": rule_id}

    elif rule_type == "sell_below":
        if price <= params["target_price"]:
            return {"user_id": user_id, "action": "SELL", "coin": coin, "percentage": params.get("percentage", 100),
                    "reason": f"Price ${price:,.2f} <= target ${params['target_price']:,.2f}", "strategy": "Sell Target", "rule_id": rule_id}

    elif rule_type == "drop_pct":
        change_24h = get_24h_change(coin)
        if change_24h <= -params["drop_pct"]:
            return {"user_id": user_id, "action": "BUY", "coin": coin, "amount_usd": params.get("amount_usd", 100),
                    "reason": f"{coin.upper()} dropped {change_24h:.1f}% (trigger: -{params['drop_pct']}%)", "strategy": "Dip Buy", "rule_id": rule_id}

    elif rule_type == "gain_pct":
        change_24h = get_24h_change(coin)
        if change_24h >= params["gain_pct"]:
            return {"user_id": user_id, "action": "SELL", "coin": coin, "percentage": params.get("percentage", 50),
                    "reason": f"{coin.upper()} gained {change_24h:.1f}% (trigger: +{params['gain_pct']}%)", "strategy": "Profit Take", "rule_id": rule_id}

    elif rule_type == "stop_loss":
        from trading_tools import _load_portfolio
        portfolio = _load_portfolio()
        pos = portfolio.get("positions", {}).get(coin)
        if pos:
            avg = pos.get("avg_price", 0)
            if avg > 0:
                loss_pct = ((avg - price) / avg) * 100
                if loss_pct >= params["loss_pct"]:
                    return {"user_id": user_id, "action": "SELL", "coin": coin, "percentage": 100,
                            "reason": f"Stop loss triggered: {loss_pct:.1f}% loss from ${avg:,.2f}", "strategy": "Stop Loss", "rule_id": rule_id}

    elif rule_type == "take_profit":
        from trading_tools import _load_portfolio
        portfolio = _load_portfolio()
        pos = portfolio.get("positions", {}).get(coin)
        if pos:
            avg = pos.get("avg_price", 0)
            if avg > 0:
                gain_pct = ((price - avg) / avg) * 100
                if gain_pct >= params["profit_pct"]:
                    sell_pct = params.get("sell_pct", 50)
                    return {"user_id": user_id, "action": "SELL", "coin": coin, "percentage": sell_pct,
                            "reason": f"Take profit: {gain_pct:.1f}% gain from ${avg:,.2f}", "strategy": "Take Profit", "rule_id": rule_id}

    elif rule_type == "dca":
        # Check timing
        last = params.get("last_buy")
        interval = params.get("interval", "daily")
        if last:
            last_dt = datetime.fromisoformat(last)
            now = datetime.now()
            if interval == "hourly" and (now - last_dt).total_seconds() < 3600:
                return None
            elif interval == "daily" and (now - last_dt).days < 1:
                return None
            elif interval == "weekly" and (now - last_dt).days < 7:
                return None
            elif interval == "monthly" and (now - last_dt).days < 30:
                return None

        return {"user_id": user_id, "action": "BUY", "coin": coin, "amount_usd": params.get("amount_usd", 100),
                "reason": f"DCA {interval} buy", "strategy": "DCA", "rule_id": rule_id,
                "_update_last_buy": True}

    elif rule_type == "rebalance":
        from trading_tools import _load_portfolio
        portfolio = _load_portfolio()
        total_value = portfolio["balance"]
        for c, pos in portfolio.get("positions", {}).items():
            p = get_current_price(c)
            total_value += pos.get("quantity", 0) * (p if p > 0 else pos.get("avg_price", 0))

        pos = portfolio.get("positions", {}).get(coin)
        current_value = 0
        if pos:
            current_value = pos.get("quantity", 0) * price

        current_pct = (current_value / total_value * 100) if total_value > 0 else 0
        target_pct = params["target_pct"]

        if current_pct < target_pct - 2:  # Need more
            diff_usd = (target_pct - current_pct) / 100 * total_value
            return {"user_id": user_id, "action": "BUY", "coin": coin, "amount_usd": min(diff_usd, total_value * 0.1),
                    "reason": f"Rebalance: {current_pct:.1f}% -> {target_pct}%", "strategy": "Rebalance", "rule_id": rule_id}
        elif current_pct > target_pct + 2:  # Need less
            sell_pct = ((current_pct - target_pct) / current_pct) * 100
            return {"user_id": user_id, "action": "SELL", "coin": coin, "percentage": min(sell_pct, 100),
                    "reason": f"Rebalance: {current_pct:.1f}% -> {target_pct}%", "strategy": "Rebalance", "rule_id": rule_id}

    elif rule_type == "conditional":
        # Evaluate trigger condition
        trigger_coin = params.get("trigger_coin", coin)
        trigger_op = params.get("trigger_op", ">")
        trigger_price = params.get("trigger_price", 0)
        trigger_price_val = get_current_price(trigger_coin)

        condition_met = False
        if trigger_op == ">" and trigger_price_val > trigger_price:
            condition_met = True
        elif trigger_op == "<" and trigger_price_val < trigger_price:
            condition_met = True
        elif trigger_op == ">=" and trigger_price_val >= trigger_price:
            condition_met = True
        elif trigger_op == "<=" and trigger_price_val <= trigger_price:
            condition_met = True

        if condition_met:
            action = params.get("action", "buy")
            action_coin = params.get("action_coin", coin)
            if action == "buy":
                return {"user_id": user_id, "action": "BUY", "coin": action_coin, "amount_usd": params.get("amount_usd", 100),
                        "reason": f"Conditional: {trigger_coin.upper()} {trigger_op} ${trigger_price:,.2f}", "strategy": "Conditional", "rule_id": rule_id}
            elif action == "sell":
                return {"user_id": user_id, "action": "SELL", "coin": action_coin, "percentage": params.get("percentage", 50),
                        "reason": f"Conditional: {trigger_coin.upper()} {trigger_op} ${trigger_price:,.2f}", "strategy": "Conditional", "rule_id": rule_id}

    return None


def _mark_triggered(rule_id: int):
    """Mark a rule as last triggered now."""
    conn = get_db()
    conn.execute("UPDATE auto_trading_rules SET last_triggered = ? WHERE id = ?",
                 (datetime.now().isoformat(), rule_id))
    conn.commit()
    conn.close()


def _update_dca_last_buy(rule_id: int):
    """Update DCA last buy time."""
    conn = get_db()
    row = conn.execute("SELECT params FROM auto_trading_rules WHERE id = ?", (rule_id,)).fetchone()
    if row:
        params = json.loads(row["params"])
        params["last_buy"] = datetime.now().isoformat()
        conn.execute("UPDATE auto_trading_rules SET params = ? WHERE id = ?",
                     (json.dumps(params), rule_id))
    conn.commit()
    conn.close()


# ============================================================
# Natural Language Rule Parser
# ============================================================

def parse_rule_from_text(text: str) -> dict:
    """
    Parse natural language into a rule.
    Returns {"rule_type": ..., "coin": ..., "params": ...} or None.
    
    Examples:
    - "buy btc if it drops 5%" -> drop_pct rule
    - "sell eth when it hits 3000" -> sell_above rule  
    - "buy sol every day 100" -> dca rule
    - "stop loss btc at 20%" -> stop_loss rule
    - "if btc > 100000 sell eth" -> conditional rule
    """
    text = text.lower().strip()
    
    # DCA pattern: "buy X every day/week $Y" or "dca X daily 100"
    dca_match = re.search(r'(?:buy|dca)\s+(\w+)\s+(?:every\s+)?(daily|weekly|monthly|hourly)\s*\$?(\d+)?', text)
    if dca_match:
        return {
            "rule_type": "dca",
            "coin": dca_match.group(1),
            "params": {
                "interval": dca_match.group(2),
                "amount_usd": float(dca_match.group(3) or 100)
            }
        }
    
    # Stop loss: "stop loss X at Y%" or "stop loss X Y%"
    sl_match = re.search(r'stop\s*loss\s+(\w+)\s+(?:at\s+)?(\d+)%?', text)
    if sl_match:
        return {
            "rule_type": "stop_loss",
            "coin": sl_match.group(1),
            "params": {"loss_pct": float(sl_match.group(2))}
        }
    
    # Take profit: "take profit X at Y%" or "tp X Y%"
    tp_match = re.search(r'(?:take\s*profit|tp)\s+(\w+)\s+(?:at\s+)?(\d+)%?', text)
    if tp_match:
        return {
            "rule_type": "take_profit",
            "coin": tp_match.group(1),
            "params": {"profit_pct": float(tp_match.group(2)), "sell_pct": 50}
        }
    
    # Conditional: "if btc > 100000 sell eth" or "if btc < 50000 buy sol 200"
    cond_match = re.search(r'if\s+(\w+)\s*([><=]+)\s*\$?([\d,]+)\s+(?:sell|short)\s+(\w+)', text)
    if cond_match:
        return {
            "rule_type": "conditional",
            "coin": cond_match.group(4),
            "params": {
                "trigger_coin": cond_match.group(1),
                "trigger_op": cond_match.group(2),
                "trigger_price": float(cond_match.group(3).replace(",", "")),
                "action": "sell",
                "action_coin": cond_match.group(4),
                "percentage": 50,
                "trigger_desc": text[:50],
                "action_desc": text[50:]
            }
        }
    cond_match = re.search(r'if\s+(\w+)\s*([><=]+)\s*\$?([\d,]+)\s+(?:buy|long)\s+(\w+)\s*\$?(\d+)?', text)
    if cond_match:
        return {
            "rule_type": "conditional",
            "coin": cond_match.group(4),
            "params": {
                "trigger_coin": cond_match.group(1),
                "trigger_op": cond_match.group(2),
                "trigger_price": float(cond_match.group(3).replace(",", "")),
                "action": "buy",
                "action_coin": cond_match.group(4),
                "amount_usd": float(cond_match.group(5) or 100),
                "trigger_desc": text[:50],
                "action_desc": text[50:]
            }
        }
    
    # Drop percentage: "buy X if it drops Y%" or "buy X on Y% dip"
    drop_match = re.search(r'(?:buy|get)\s+(\w+)\s+(?:if\s+(?:it\s+)?(?:drops?|dips?|falls?))\s+(\d+)%', text)
    if not drop_match:
        drop_match = re.search(r'(?:buy|get)\s+(\w+)\s+on\s+(\d+)%\s+(?:dip|drop|dip)', text)
    if drop_match:
        amt_match = re.search(r'\$(\d+)', text)
        return {
            "rule_type": "drop_pct",
            "coin": drop_match.group(1),
            "params": {
                "drop_pct": float(drop_match.group(2)),
                "amount_usd": float(amt_match.group(1)) if amt_match else 100
            }
        }
    
    # Gain percentage: "sell X if it gains Y%" or "sell X on Y% pump"
    gain_match = re.search(r'sell\s+(\w+)\s+(?:if\s+(?:it\s+)?(?:gains?|pumps?|rises?))\s+(\d+)%', text)
    if not gain_match:
        gain_match = re.search(r'sell\s+(\w+)\s+on\s+(\d+)%\s+(?:gain|pump|rally)', text)
    if gain_match:
        pct_match = re.search(r'(\d+)%\s*(?:of|all|everything)', text)
        return {
            "rule_type": "gain_pct",
            "coin": gain_match.group(1),
            "params": {
                "gain_pct": float(gain_match.group(2)),
                "percentage": float(pct_match.group(1)) if pct_match else 50
            }
        }
    
    # Price above: "buy X when above Y" or "buy X at Y"
    above_match = re.search(r'(?:buy|long)\s+(\w+)\s+(?:when\s+)?(?:price\s+)?(?:above|over|>\s*)\s*\$?([\d,]+)', text)
    if above_match:
        amt_match = re.search(r'\$(\d+)(?!.*\$)', text)
        return {
            "rule_type": "price_above",
            "coin": above_match.group(1),
            "params": {
                "target_price": float(above_match.group(2).replace(",", "")),
                "amount_usd": float(amt_match.group(1)) if amt_match else 100
            }
        }
    
    # Price below: "buy X when below Y" or "buy X under Y" or "buy X dip to Y"
    below_match = re.search(r'(?:buy|long)\s+(\w+)\s+(?:when\s+)?(?:price\s+)?(?:below|under|<\s*|dip\s+to)\s*\$?([\d,]+)', text)
    if below_match:
        amt_match = re.search(r'\$(\d+)(?!.*\$)', text)
        return {
            "rule_type": "price_below",
            "coin": below_match.group(1),
            "params": {
                "target_price": float(below_match.group(2).replace(",", "")),
                "amount_usd": float(amt_match.group(1)) if amt_match else 100
            }
        }
    
    # Sell above: "sell X when above Y" or "sell X at Y"
    sell_above = re.search(r'sell\s+(\w+)\s+(?:when\s+)?(?:price\s+)?(?:above|over|at|>\s*)\s*\$?([\d,]+)', text)
    if sell_above:
        return {
            "rule_type": "sell_above",
            "coin": sell_above.group(1),
            "params": {
                "target_price": float(sell_above.group(2).replace(",", "")),
                "percentage": 100
            }
        }
    
    # Sell below: "sell X when below Y"
    sell_below = re.search(r'sell\s+(\w+)\s+(?:when\s+)?(?:price\s+)?(?:below|under|<\s*)\s*\$?([\d,]+)', text)
    if sell_below:
        return {
            "rule_type": "sell_below",
            "coin": sell_below.group(1),
            "params": {
                "target_price": float(sell_below.group(2).replace(",", "")),
                "percentage": 100
            }
        }
    
    return None


# ============================================================
# Tool Registry
# ============================================================

AUTO_TRADING_TOOLS = [
    {"type": "function", "function": {"name": "add_trading_rule", "description": "Add an auto-trading rule. Supports natural language like 'buy btc if it drops 5%', 'sell eth at 3000', 'stop loss sol 20%', 'dca eth daily 100', 'if btc > 100000 sell eth'.", "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Natural language rule"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "get_trading_rules", "description": "List all active auto-trading rules.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "cancel_trading_rule", "description": "Cancel an auto-trading rule by ID.", "parameters": {"type": "object", "properties": {"rule_id": {"type": "number"}}, "required": ["rule_id"]}}},
]


def execute_auto_trading_tool(name: str, args: dict) -> str:
    """Execute an auto-trading tool."""
    user_id = args.get("user_id", 0)

    if name == "add_trading_rule":
        text = args.get("text", "")
        parsed = parse_rule_from_text(text)
        if not parsed:
            return f"Could not parse rule from: {text}\nTry: 'buy btc if it drops 5%' or 'sell eth at 3000'"
        return add_rule(user_id, parsed["rule_type"], parsed["coin"], parsed["params"])

    elif name == "get_trading_rules":
        return get_rules(user_id)

    elif name == "cancel_trading_rule":
        return cancel_rule(user_id, int(args.get("rule_id", 0)))

    return f"Unknown auto-trading tool: {name}"
