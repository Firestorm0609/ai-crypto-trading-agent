"""
Trading Tools — crypto price data, portfolio tracking, simulated trading.

Uses CoinGecko (free, no API key) for real-time crypto prices.
Portfolio is stored locally in a JSON file.
"""

import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from google.generativeai.types import FunctionDeclaration

# Portfolio storage
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"
ALERTS_FILE = Path(__file__).parent / "alerts.json"


# ============================================================
# Price Data (CoinGecko free API)
# ============================================================

def get_price(coin: str) -> str:
    """Get current price and 24h stats for a cryptocurrency."""
    try:
        coin = coin.lower().strip()
        # Map common names
        aliases = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
            "dot": "polkadot", "matic": "matic-network",
            "avax": "avalanche-2", "link": "chainlink",
            "bnb": "binancecoin", "usdt": "tether", "usdc": "usd-coin",
            "shib": "shiba-inu", "pepe": "pepe", "arb": "arbitrum",
            "op": "optimism", "sui": "sui", "near": "near",
        }
        coin_id = aliases.get(coin, coin)

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if coin_id not in data:
            return f"Coin '{coin}' not found. Try: bitcoin, ethereum, solana, etc."

        info = data[coin_id]
        price = info.get("usd", 0)
        change = info.get("usd_24h_change", 0)
        vol = info.get("usd_24h_vol", 0)
        mcap = info.get("usd_market_cap", 0)

        emoji = "🟢" if change >= 0 else "🔴"
        change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"

        result = f"""
{emoji} {coin.upper()} — ${price:,.2f}

24h Change: {change_str}
24h Volume: ${vol:,.0f}
Market Cap: ${mcap:,.0f}
"""
        return result.strip()
    except Exception as e:
        return f"Error fetching price: {str(e)}"


def get_top_coins(n: int = 10) -> str:
    """Get top N cryptocurrencies by market cap."""
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={n}&page=1&sparkline=false&price_change_percentage=24h"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        lines = [f"📊 Top {n} Cryptocurrencies\n"]
        for i, coin in enumerate(data, 1):
            price = coin.get("current_price", 0)
            change = coin.get("price_change_percentage_24h", 0) or 0
            emoji = "🟢" if change >= 0 else "🔴"
            change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
            lines.append(f"{i}. {coin['name']} ({coin['symbol'].upper()}) — ${price:,.2f} {emoji}{change_str}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


def search_coin(query: str) -> str:
    """Search for a cryptocurrency by name or symbol."""
    try:
        url = f"https://api.coingecko.com/api/v3/search?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        coins = data.get("coins", [])[:5]
        if not coins:
            return f"No coins found for '{query}'"

        lines = [f"🔍 Search results for '{query}':\n"]
        for c in coins:
            lines.append(f"• {c['name']} ({c['symbol'].upper()}) — ID: {c['id']}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# Portfolio Management (simulated / paper trading)
# ============================================================

def _load_portfolio() -> dict:
    """Load portfolio from file."""
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text())
    return {"balance": 10000.0, "positions": {}, "trades": []}


def _save_portfolio(portfolio: dict):
    """Save portfolio to file."""
    PORTFOLIO_FILE.write_text(json.dumps(portfolio, indent=2))


def get_portfolio() -> str:
    """Show current portfolio with live values."""
    try:
        portfolio = _load_portfolio()
        balance = portfolio["balance"]
        positions = portfolio["positions"]

        lines = [f"💼 Portfolio Summary\n"]
        lines.append(f"Cash: ${balance:,.2f}\n")

        if not positions:
            lines.append("No open positions.")
            total_value = balance
        else:
            lines.append("Positions:")
            total_value = balance
            for coin, pos in positions.items():
                # Get current price
                try:
                    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
                    req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        price_data = json.loads(resp.read().decode())
                    current_price = price_data.get(coin, {}).get("usd", 0)
                except:
                    current_price = pos.get("avg_price", 0)

                qty = pos.get("quantity", 0)
                avg_price = pos.get("avg_price", 0)
                market_value = qty * current_price
                pnl = (current_price - avg_price) * qty
                pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0

                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"  • {coin.upper()}: {qty:.6f} units")
                lines.append(f"    Avg: ${avg_price:,.2f} → Now: ${current_price:,.2f}")
                lines.append(f"    Value: ${market_value:,.2f} | PnL: {emoji} ${pnl:+,.2f} ({pnl_pct:+.1f}%)")
                total_value += market_value

        lines.append(f"\n💰 Total Value: ${total_value:,.2f}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


def buy(coin: str, amount_usd: float) -> str:
    """Buy cryptocurrency with paper money."""
    try:
        portfolio = _load_portfolio()
        coin = coin.lower().strip()

        # Alias mapping
        aliases = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
            "bnb": "binancecoin", "link": "chainlink",
        }
        coin_id = aliases.get(coin, coin)

        if amount_usd <= 0:
            return "Error: Amount must be positive"
        if amount_usd > portfolio["balance"]:
            return f"Error: Insufficient balance. You have ${portfolio['balance']:,.2f}"

        # Get current price
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if coin_id not in data:
            return f"Error: Coin '{coin}' not found"

        price = data[coin_id]["usd"]
        quantity = amount_usd / price

        # Update portfolio
        if coin_id in portfolio["positions"]:
            pos = portfolio["positions"][coin_id]
            total_qty = pos["quantity"] + quantity
            total_cost = (pos["avg_price"] * pos["quantity"]) + (price * quantity)
            pos["avg_price"] = total_cost / total_qty
            pos["quantity"] = total_qty
        else:
            portfolio["positions"][coin_id] = {
                "quantity": quantity,
                "avg_price": price,
            }

        portfolio["balance"] -= amount_usd

        # Record trade
        portfolio["trades"].append({
            "type": "BUY",
            "coin": coin_id,
            "quantity": quantity,
            "price": price,
            "amount_usd": amount_usd,
            "time": datetime.now().isoformat(),
        })

        _save_portfolio(portfolio)

        return f"""✅ BUY ORDER EXECUTED

{quantity:.6f} {coin_id.upper()} @ ${price:,.2f}
Total: ${amount_usd:,.2f}
Remaining Balance: ${portfolio['balance']:,.2f}"""
    except Exception as e:
        return f"Error: {str(e)}"


def sell(coin: str, quantity: float = None, percentage: float = None) -> str:
    """Sell cryptocurrency. Specify quantity or percentage of holdings."""
    try:
        portfolio = _load_portfolio()
        coin = coin.lower().strip()

        aliases = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
            "bnb": "binancecoin", "link": "chainlink",
        }
        coin_id = aliases.get(coin, coin)

        if coin_id not in portfolio["positions"]:
            return f"Error: No position in {coin.upper()}"

        pos = portfolio["positions"][coin_id]
        held_qty = pos["quantity"]

        if percentage:
            sell_qty = held_qty * (percentage / 100)
        elif quantity:
            sell_qty = quantity
        else:
            sell_qty = held_qty  # Sell all

        if sell_qty > held_qty:
            return f"Error: You only hold {held_qty:.6f} {coin_id.upper()}"

        # Get current price
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        price = data[coin_id]["usd"]
        proceeds = sell_qty * price
        pnl = (price - pos["avg_price"]) * sell_qty

        # Update portfolio
        pos["quantity"] -= sell_qty
        if pos["quantity"] < 1e-10:
            del portfolio["positions"][coin_id]

        portfolio["balance"] += proceeds

        # Record trade
        portfolio["trades"].append({
            "type": "SELL",
            "coin": coin_id,
            "quantity": sell_qty,
            "price": price,
            "amount_usd": proceeds,
            "pnl": pnl,
            "time": datetime.now().isoformat(),
        })

        _save_portfolio(portfolio)

        emoji = "🟢" if pnl >= 0 else "🔴"
        return f"""✅ SELL ORDER EXECUTED

{sell_qty:.6f} {coin_id.upper()} @ ${price:,.2f}
Proceeds: ${proceeds:,.2f}
PnL: {emoji} ${pnl:+,.2f}
New Balance: ${portfolio['balance']:,.2f}"""
    except Exception as e:
        return f"Error: {str(e)}"


def get_trade_history(n: int = 10) -> str:
    """Show last N trades."""
    portfolio = _load_portfolio()
    trades = portfolio.get("trades", [])[-n:]

    if not trades:
        return "No trades yet."

    lines = [f"📜 Last {len(trades)} Trades:\n"]
    for t in reversed(trades):
        # Handle both regular trades (type: BUY/SELL) and perps trades (action: open_long etc)
        trade_type = t.get("type") or t.get("action", "?")
        coin = t.get("coin") or t.get("asset", "?")
        quantity = t.get("quantity", t.get("size_usd", 0))
        price = t.get("price", t.get("entry_price", 0))
        amount = t.get("amount_usd", t.get("margin", 0))
        time_str = t.get("time", t.get("timestamp", "?"))[:16]
        
        if trade_type in ["BUY", "buy"]:
            emoji = "🟢"
        elif trade_type in ["SELL", "sell"]:
            emoji = "🔴"
        else:
            emoji = "⚡"
        
        pnl_str = f" | PnL: ${t['pnl']:+,.2f}" if "pnl" in t else ""
        leverage_str = f" ({t['leverage']}x)" if "leverage" in t else ""
        lines.append(f"{emoji} [{time_str}] {trade_type} {quantity:.6f} {coin.upper()} @ ${price:,.2f} (${amount:,.2f}){leverage_str}{pnl_str}")

    return "\n".join(lines)


def reset_portfolio(starting_balance: float = 10000.0) -> str:
    """Reset portfolio to a fresh state."""
    portfolio = {"balance": starting_balance, "positions": {}, "trades": []}
    _save_portfolio(portfolio)
    return f"🔄 Portfolio reset! Starting balance: ${starting_balance:,.2f}"


# ============================================================
# Trading Tools Registry (for agent integration)
# ============================================================

TRADING_TOOLS = [
    FunctionDeclaration(
        name="get_price",
        description="Get current price, 24h change, volume, and market cap for a cryptocurrency. Use coin names like 'bitcoin', 'ethereum', or symbols like 'btc', 'eth'.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "coin": {
                    "type": "STRING",
                    "description": "Cryptocurrency name or symbol (e.g., 'bitcoin', 'btc', 'eth', 'solana')"
                }
            },
            "required": ["coin"]
        }
    ),
    FunctionDeclaration(
        name="get_top_coins",
        description="Get the top N cryptocurrencies by market cap with prices and 24h changes.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "n": {
                    "type": "NUMBER",
                    "description": "Number of top coins to show (default: 10)"
                }
            }
        }
    ),
    FunctionDeclaration(
        name="search_coin",
        description="Search for a cryptocurrency by name or symbol to find its ID.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Search query (name or symbol)"
                }
            },
            "required": ["query"]
        }
    ),
    FunctionDeclaration(
        name="get_portfolio",
        description="Show current portfolio with holdings, live values, and profit/loss.",
        parameters={
            "type": "OBJECT",
            "properties": {}
        }
    ),
    FunctionDeclaration(
        name="buy",
        description="Buy cryptocurrency with paper money (simulated trading). Specify the coin and USD amount to spend.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "coin": {
                    "type": "STRING",
                    "description": "Coin to buy (e.g., 'btc', 'eth', 'solana')"
                },
                "amount_usd": {
                    "type": "NUMBER",
                    "description": "Amount in USD to spend"
                }
            },
            "required": ["coin", "amount_usd"]
        }
    ),
    FunctionDeclaration(
        name="sell",
        description="Sell cryptocurrency holdings. Specify coin and either quantity or percentage.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "coin": {
                    "type": "STRING",
                    "description": "Coin to sell (e.g., 'btc', 'eth')"
                },
                "quantity": {
                    "type": "NUMBER",
                    "description": "Quantity to sell (omit to sell all)"
                },
                "percentage": {
                    "type": "NUMBER",
                    "description": "Percentage of holdings to sell (e.g., 50 for 50%)"
                }
            },
            "required": ["coin"]
        }
    ),
    FunctionDeclaration(
        name="get_trade_history",
        description="Show recent trade history.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "n": {
                    "type": "NUMBER",
                    "description": "Number of recent trades to show (default: 10)"
                }
            }
        }
    ),
    FunctionDeclaration(
        name="reset_portfolio",
        description="Reset the portfolio to a fresh state with a starting balance.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "starting_balance": {
                    "type": "NUMBER",
                    "description": "Starting balance in USD (default: 10000)"
                }
            }
        }
    ),
]

TRADING_TOOL_MAP = {
    "get_price": lambda args: get_price(args["coin"]),
    "get_top_coins": lambda args: get_top_coins(int(args.get("n", 10))),
    "search_coin": lambda args: search_coin(args["query"]),
    "get_portfolio": lambda args: get_portfolio(),
    "buy": lambda args: buy(args["coin"], float(args["amount_usd"])),
    "sell": lambda args: sell(args["coin"], args.get("quantity"), args.get("percentage")),
    "get_trade_history": lambda args: get_trade_history(int(args.get("n", 10))),
    "reset_portfolio": lambda args: reset_portfolio(float(args.get("starting_balance", 10000))),
}
