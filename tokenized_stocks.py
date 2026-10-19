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

# REAL tokenized-stock contracts on Robinhood Chain (4663).
# Addresses pulled from LI.Fi's token index (li.quest/v1/tokens?chain=4663)
# and verified to have live USD prices 2026-09-02. These are actual ERC-20s
# tradable on-chain via Uniswap V3 / LI.Fi routes.
STOCK_CONTRACTS = {
    "NVDA":  "0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC",
    "AAPL":  "0xaF3D76f1834A1d425780943C99Ea8A608f8a93f9",
    "TSLA":  "0x322F0929c4625eD5bAd873c95208D54E1c003b2d",
    "MSFT":  "0xe93237C50D904957Cf27E7B1133b510C669c2e74",
    "GOOGL": "0x2e0847E8910a9732eB3fb1bb4b70a580ADAD4FE3",
    "AMZN":  "0x12f190a9F9d7D37a250758b26824B97CE941bF54",
    "META":  "0xc0D6457C16Cc70d6790Dd43521C899C87ce02f35",
    "NFLX":  "0xE0444EF8BF4eD74f74FD73686e2ddF4C1c5591E8",
    "AMD":   "0x86923f96303D656E4aa86D9d42D1e57ad2023fdC",
    "INTC":  "0xc72b96e0E48ecd4DC75E1e45396e26300BC39681",
    "COST":  "0x4EA005168D7F09a7A0Ba9D1DEf21a479950E44C2",
    "SPY":   "0x117cc2133c37B721F49dE2A7a74833232B3B4C0C",
    "QQQ":   "0xD5f3879160bc7c32ebb4dC785F8a4F505888de68",
}

# Stock prices — FALLBACK ONLY when the live LI.Fi price is unreachable.
# Values are stale reference points, not live feeds.
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

def _live_price(ticker: str):
    """Live USD price from LI.Fi's token index; None if unavailable."""
    addr = STOCK_CONTRACTS.get(ticker.upper())
    if not addr:
        return None
    try:
        import requests
        r = requests.get("https://li.quest/v1/token",
                         params={"chain": 4663, "token": addr}, timeout=20)
        if r.status_code == 200:
            p = r.json().get("priceUSD")
            if p:
                return float(p)
    except Exception:
        pass
    return None


def _eth_price_usd() -> float:
    """ETH price on Robinhood Chain via LI.Fi (fallback: hardcoded)."""
    try:
        import requests
        r = requests.get("https://li.quest/v1/token",
                         params={"chain": 4663,
                                 "token": "0x0000000000000000000000000000000000000000"},
                         timeout=20)
        if r.status_code == 200:
            p = r.json().get("priceUSD")
            if p:
                return float(p)
    except Exception:
        pass
    return 2400.0


def get_stock_price(ticker: str) -> str:
    """Get tokenized stock price on Robinhood Chain (live via LI.Fi)."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not available. Available: {', '.join(list(TOKENIZED_STOCKS.keys())[:10])}"

    stock = TOKENIZED_STOCKS[ticker]
    live = _live_price(ticker)
    tradable = ticker in STOCK_CONTRACTS
    if live is not None:
        price_line = f"Price: ${live:,.2f} (live)"
    else:
        price_line = f"Price: ${STOCK_PRICES.get(ticker, 0):,.2f} (stale reference — live feed unreachable)"

    return (
        f"📈 *{ticker} ({stock['name']})*\n\n"
        f"{price_line}\n"
        f"Sector: {stock['sector']}\n"
        f"Chain: Robinhood Chain (4663)\n"
        f"Tradable on-chain here: {'✅ yes' if tradable else '❌ no contract indexed yet'}\n\n"
        + (f"💡 Trade with: buy_stock {ticker} 100" if tradable else "")
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
        lines.append(f"*{cat.title()}*")
        for t in tickers:
            if t in STOCK_CONTRACTS:
                lines.append(f"  • {t} ({TOKENIZED_STOCKS[t]['name']}) — tradable ✅")
            else:
                lines.append(f"  • {t} ({TOKENIZED_STOCKS[t]['name']}) — no contract yet ❌")
        lines.append("")

    lines.append("💡 Real on-chain buys: buy_stock NVDA 100 (works for ✅ tickers)")
    return "\n".join(lines)

def _stock_swap(ticker: str, sell_token: str, amount: float) -> str:
    """Execute a stock-token swap on Robinhood Chain: direct Uniswap V3 first,
    LI.Fi aggregated route as fallback. amount = ETH to spend OR token qty to sell."""
    from evm_swap import real_swap_execute
    if sell_token == "ETH":
        result = real_swap_execute("robinhood", "ETH", STOCK_CONTRACTS[ticker], amount)
    else:
        result = real_swap_execute("robinhood", sell_token, "ETH", amount)
    if result.startswith("❌") and "pool" in result.lower():
        from lifi_tools import execute_bridge
        if sell_token == "ETH":
            result = execute_bridge("robinhood", "robinhood", "ETH",
                                    STOCK_CONTRACTS[ticker], amount)
        else:
            result = execute_bridge("robinhood", "robinhood", sell_token, "ETH", amount)
    return result


def buy_stock(ticker: str, amount_usd: float) -> str:
    """REAL purchase of a tokenized stock on Robinhood Chain.
    Converts USD -> ETH -> stock token via on-chain swap."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not available"
    if ticker not in STOCK_CONTRACTS:
        return (f"❌ {ticker} has no verified token contract indexed yet, so it "
                f"cannot be bought on-chain here. Index with tradable stocks: "
                f"{', '.join(sorted(STOCK_CONTRACTS))}")
    if amount_usd < 5:
        return "❌ Minimum purchase is $5 (gas makes smaller buys uneconomical)."

    stock = TOKENIZED_STOCKS[ticker]
    price = _live_price(ticker)
    if price is None:
        return f"❌ Live price for {ticker} unavailable — refusing to trade blind."
    eth_price = _eth_price_usd()
    eth_amount = round(amount_usd / eth_price, 8)
    est_qty = amount_usd / price

    result = _stock_swap(ticker, "ETH", eth_amount)
    header = (
        f"📊 Buying {ticker} ({stock['name']}) on Robinhood Chain\n"
        f"Live price: ${price:,.2f} | ETH: ${eth_price:,.2f}\n"
        f"Spending ~{eth_amount:.8f} ETH (${amount_usd:,.2f}) ≈ {est_qty:.6f} {ticker}\n\n"
    )
    return header + result


def sell_stock(ticker: str, quantity: float = None, percentage: float = None) -> str:
    """REAL sale of a tokenized stock on Robinhood Chain (token -> ETH)."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not available"
    if ticker not in STOCK_CONTRACTS:
        return f"❌ {ticker} has no verified token contract — cannot sell on-chain here."

    from evm_swap import _load_wallet
    wallet = _load_wallet("robinhood")
    if not wallet:
        return "❌ No EVM wallet."

    from web3 import Web3
    try:
        w3 = Web3(Web3.HTTPProvider("https://rpc.mainnet.chain.robinhood.com", {"timeout": 15}))
        tok = w3.eth.contract(address=w3.to_checksum_address(STOCK_CONTRACTS[ticker]),
                              abi=[{"name": "balanceOf", "type": "function", "stateMutability": "view",
                                    "inputs": [{"name": "", "type": "address"}], "outputs": [{"type": "uint256"}]}])
        bal = tok.functions.balanceOf(wallet["address"]).call() / 1e18
    except Exception as e:
        return f"❌ Could not check balance: {e}"

    if percentage:
        quantity = bal * float(percentage) / 100.0
    if not quantity or quantity <= 0:
        return f"⚠️ Specify quantity or percentage. You hold {bal:.6f} {ticker}."
    if quantity > bal + 1e-9:
        return f"❌ You hold {bal:.6f} {ticker} — cannot sell {quantity:.6f}."

    price = _live_price(ticker) or 0
    proceeds = quantity * price
    result = _stock_swap(ticker, STOCK_CONTRACTS[ticker], round(quantity, 8))
    header = (
        f"📊 Selling {quantity:.6f} {ticker} on Robinhood Chain\n"
        f"Live price: ${price:,.2f} → est. ${proceeds:,.2f}\n\n"
    )
    return header + result

def get_stock_info(ticker: str) -> str:
    """Get detailed stock info."""
    ticker = ticker.upper()
    if ticker not in TOKENIZED_STOCKS:
        return f"❌ {ticker} not found"

    stock = TOKENIZED_STOCKS[ticker]
    live = _live_price(ticker)
    price = live if live is not None else STOCK_PRICES.get(ticker, 0)
    price_src = "live" if live is not None else "stale fallback"

    return (
        f"📋 *{ticker} Tokenized Stock Info*\n\n"
        f"Company: {stock['name']}\n"
        f"Ticker: {ticker}\n"
        f"Current Price: ${price:,.2f} ({price_src})\n"
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
    {"type": "function", "function": {"name": "buy_stock", "description": "REAL purchase of a tokenized stock on Robinhood Chain — executes an on-chain swap (USD amount converted to ETH, then swapped for the stock token with your wallet). Only tickers with verified contracts work: NVDA, AAPL, TSLA, MSFT, GOOGL, AMZN, META, NFLX, AMD, INTC, COST, SPY, QQQ.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "amount_usd": {"type": "number"}}, "required": ["ticker", "amount_usd"]}}},
    {"type": "function", "function": {"name": "sell_stock", "description": "REAL sale of a tokenized stock on Robinhood Chain (stock token -> ETH). Give quantity OR percentage of your holding.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "quantity": {"type": "number", "description": "Token quantity to sell"}, "percentage": {"type": "number", "description": "Percent of your holding to sell (e.g. 50)"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {"name": "get_stock_info", "description": "Get detailed info about a tokenized stock.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
]

STOCK_TOOL_MAP = {
    "get_stock_price": lambda a: get_stock_price(a["ticker"]),
    "get_available_stocks": lambda a: get_available_stocks(),
    "buy_stock": lambda a: buy_stock(a["ticker"], float(a["amount_usd"])),
    "sell_stock": lambda a: sell_stock(a["ticker"], a.get("quantity"), a.get("percentage")),
    "get_stock_info": lambda a: get_stock_info(a["ticker"]),
}
