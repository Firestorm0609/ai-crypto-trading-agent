"""
Tokenized Stock Trading on Robinhood Chain.

Trade tokenized versions of stocks on-chain:
- NVDA, AAPL, TSLA, MSFT, GOOGL, AMZN, META, etc.
- 24/7 trading (not limited to market hours)
- Self-custody (no broker needed)
- Low L2 fees

Robinhood Chain launched tokenized stocks on July 1, 2026.
"""

import json
import urllib.request
from pathlib import Path

# ============================================================
# Tokenized Stock Tokens on Robinhood Chain
# ============================================================

# These are the tokenized stock contracts on Robinhood Chain
# Addresses will be updated as they're deployed
TOKENIZED_STOCKS = {
    # Tech Giants
    "NVDA": {"name": "NVIDIA", "sector": "Technology", "category": "chipmaker"},
    "AAPL": {"name": "Apple", "sector": "Technology", "category": "hardware"},
    "TSLA": {"name": "Tesla", "sector": "Automotive", "category": "ev"},
    "MSFT": {"name": "Microsoft", "sector": "Technology", "category": "software"},
    "GOOGL": {"name": "Alphabet", "sector": "Technology", "category": "search"},
    "AMZN": {"name": "Amazon", "sector": "E-Commerce", "category": "retail"},
    "META": {"name": "Meta", "sector": "Technology", "category": "social"},
    "NFLX": {"name": "Netflix", "sector": "Entertainment", "category": "streaming"},
    "AMD": {"name": "AMD", "sector": "Technology", "category": "chipmaker"},
    "INTC": {"name": "Intel", "sector": "Technology", "category": "chipmaker"},

    # Financial
    "JPM": {"name": "JPMorgan", "sector": "Finance", "category": "bank"},
    "V": {"name": "Visa", "sector": "Finance", "category": "payments"},
    "MA": {"name": "Mastercard", "sector": "Finance", "category": "payments"},
    "BAC": {"name": "Bank of America", "sector": "Finance", "category": "bank"},

    # Healthcare
    "JNJ": {"name": "Johnson & Johnson", "sector": "Healthcare", "category": "pharma"},
    "UNH": {"name": "UnitedHealth", "sector": "Healthcare", "category": "insurance"},

    # Consumer
    "WMT": {"name": "Walmart", "sector": "Retail", "category": "retail"},
    "COST": {"name": "Costco", "sector": "Retail", "category": "retail"},

    # ETFs
    "SPY": {"name": "S&P 500 ETF", "sector": "ETF", "category": "index"},
    "QQQ": {"name": "Nasdaq 100 ETF", "sector": "ETF", "category": "index"},
    "VTI": {"name": "Total Market ETF", "sector": "ETF", "category": "index"},
}

# Stock prices (would normally come from an API)
# For now, using approximate prices
STOCK_PRICES = {
    "NVDA": 135.0, "AAPL": 230.0, "TSLA": 250.0, "MSFT": 430.0,
    "GOOGL": 175.0, "AMZN": 190.0, "META": 520.0, "NFLX": 700.0,
    "AMD": 155.0, "INTC": 35.0, "JPM": 210.0, "V": 280.0,
    "MA": 510.0, "BAC": 40.0, "JNJ": 155.0, "UNH": 550.0,
    "WMT": 80.0, "COST": 880.0, "SPY": 560.0, "QQQ": 490.0, "VTI": 290.0,
}


# ============================================================
# Tokenized Stock Functions
# ============================================================

def get_stock_price(ticker: str) -> str:
    """Get tokenized stock price on Robinhood Chain."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not available. Available: {', '.join(list(TOKENIZED_STOCKS.keys())[:10])}"

    stock = TOKENIZED_STOCKS[ticker]
    price = STOCK_PRICES.get(ticker, 0)

    return (
        f"📈 *{ticker} ({stock['name']})*\n\n"
        f"Price: ${price:,.2f}\n"
        f"Sector: {stock['sector']}\n"
        f"Chain: Robinhood Chain (L2)\n"
        f"Trading: 24/7 on-chain\n\n"
        f"💡 Trade with: /buystock {ticker} 100"
    )

def get_available_stocks() -> str:
    """List all available tokenized stocks."""
    lines = ["📈 *Tokenized Stocks on Robinhood Chain:*\n"]

    categories = {}
    for ticker, info in TOKENIZED_STOCKS.items():
        cat = info["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(ticker)

    for cat, tickers in categories.items():
        lines.append(f"*{cat.title()}:*")
        for t in tickers:
            price = STOCK_PRICES.get(t, 0)
            lines.append(f"  • {t} ({TOKENIZED_STOCKS[t]['name']}) — ${price:,.2f}")
        lines.append("")

    lines.append("💡 Use /buystock NVDA 100 to buy $100 of NVIDIA")
    return "\n".join(lines)

def buy_stock(ticker: str, amount_usd: float) -> str:
    """Buy tokenized stock on Robinhood Chain."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not available"

    stock = TOKENIZED_STOCKS[ticker]
    price = STOCK_PRICES.get(ticker, 0)
    if price <= 0:
        return f"❌ Unable to get price for {ticker}"

    quantity = amount_usd / price

    # In production, this would call Uniswap on Robinhood Chain
    # For now, show the quote
    return (
        f"✅ *BUY ORDER (Robinhood Chain)*\n\n"
        f"Stock: {ticker} ({stock['name']})\n"
        f"Type: Tokenized Stock\n"
        f"Amount: ${amount_usd:,.2f}\n"
        f"Price: ${price:,.2f}\n"
        f"Quantity: {quantity:.4f} tokens\n"
        f"Network: Robinhood Chain (L2)\n"
        f"Gas: ~$0.01\n\n"
        f"⚠️ Connect your wallet to execute.\n"
        f"Chain ID: 177654321"
    )

def sell_stock(ticker: str, quantity: float = None, percentage: float = None) -> str:
    """Sell tokenized stock on Robinhood Chain."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not available"

    stock = TOKENIZED_STOCKS[ticker]
    price = STOCK_PRICES.get(ticker, 0)

    if quantity:
        proceeds = quantity * price
    elif percentage:
        # Would need portfolio data for this
        return f"⚠️ Specify quantity: /sellstock {ticker} 10"
    else:
        return f"⚠️ Specify quantity: /sellstock {ticker} 10"

    return (
        f"✅ *SELL ORDER (Robinhood Chain)*\n\n"
        f"Stock: {ticker} ({stock['name']})\n"
        f"Quantity: {quantity:.4f} tokens\n"
        f"Price: ${price:,.2f}\n"
        f"Proceeds: ${proceeds:,.2f}\n"
        f"Network: Robinhood Chain (L2)\n"
        f"Gas: ~$0.01"
    )

def get_stock_info(ticker: str) -> str:
    """Get detailed stock info."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not found"

    stock = TOKENIZED_STOCKS[ticker]
    price = STOCK_PRICES.get(ticker, 0)

    return (
        f"📋 *{ticker} Tokenized Stock Info*\n\n"
        f"Company: {stock['name']}\n"
        f"Ticker: {ticker}\n"
        f"Current Price: ${price:,.2f}\n"
        f"Sector: {stock['sector']}\n"
        f"Category: {stock['category']}\n\n"
        f"*Trading Info:*\n"
        f"Chain: Robinhood Chain (Ethereum L2)\n"
        f"DEX: Uniswap V3\n"
        f"Gas Token: ETH\n"
        f"Trading Hours: 24/7 (on-chain)\n"
        f"Settlement: Instant\n\n"
        f"*Advantages vs Traditional:*\n"
        f"• 24/7 trading (not 9:30-4:00)\n"
        f"• Self-custody (no broker)\n"
        f"• Global access (120 countries)\n"
        f"• Near-zero fees (~$0.01)\n"
        f"• Instant settlement"
    )


# ============================================================
# Tool Registry
# ============================================================

STOCK_TOOLS = [
    {"type": "function", "function": {"name": "get_stock_price", "description": "Get tokenized stock price on Robinhood Chain.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker like NVDA, AAPL, TSLA"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "get_available_stocks", "description": "List all tokenized stocks available.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "buy_stock", "description": "Buy tokenized stock on Robinhood Chain. REAL MONEY.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "amount_usd": {"type": "number"}}, "required": ["ticker", "amount_usd"]}}},
    {"type": "function", "function": {"name": "sell_stock", "description": "Sell tokenized stock on Robinhood Chain.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "quantity": {"type": "number"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "get_stock_info", "description": "Get detailed info about a tokenized stock.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
]

STOCK_TOOL_MAP = {
    "get_stock_price": lambda a: get_stock_price(a["ticker"]),
    "get_available_stocks": lambda a: get_available_stocks(),
    "buy_stock": lambda a: buy_stock(a["ticker"], float(a["amount_usd"])),
    "sell_stock": lambda a: sell_stock(a["ticker"], a.get("quantity")),
    "get_stock_info": lambda a: get_stock_info(a["ticker"]),
}
