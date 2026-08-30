"""
Uniswap Tools — DEX Data, Pool Info, Swap Quotes

Uses:
- CoinGecko for basic price data (fallback)
- Web search for Uniswap-specific info
- Known contract addresses for popular tokens
"""

import json
import urllib.request
import urllib.parse
from pathlib import Path

# Load API key from .env
UNISWAP_API_KEY = ""
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("UNISWAP_API_KEY="):
            UNISWAP_API_KEY = line.split("=", 1)[1].strip()

# Popular token addresses on Ethereum
UNISWAP_TOKENS = {
    "ETH": {"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "decimals": 18},
    "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    "USDT": {"address": "0xdAC17F958D2ee523a2206206994597c13D831ec7", "decimals": 6},
    "DAI": {"address": "0x6B175474E89094C44Da98b954EedeAC495271d0F", "decimals": 18},
    "WBTC": {"address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "decimals": 8},
    "UNI": {"address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", "decimals": 18},
    "LINK": {"address": "0x514910771AF9Ca656af840dff83E8264EcF986CA", "decimals": 18},
    "AAVE": {"address": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9", "decimals": 18},
    "WETH": {"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "decimals": 18},
}

# Uniswap V3 Pool addresses (ETH pairs)
UNISWAP_POOLS = {
    "ETH/USDC": "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
    "ETH/USDT": "0x11b815efB8f5811Ca4d703764653E1453B226e0E",
    "ETH/DAI": "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc",
    "WBTC/ETH": "0xBb2b8038a16Ba0CD2aff22266776160C7A3477Cb",
    "UNI/ETH": "0x1d4267C07316012fB1F1d26B7D6C428C3f0608C4",
    "LINK/ETH": "0xa6cc3fc208D9A49188ce88b99E5aE58c216d5084",
}


def get_uniswap_price(token: str) -> str:
    """Get token price from Uniswap."""
    token = token.upper()
    token_info = UNISWAP_TOKENS.get(token)

    if not token_info:
        return f"Token {token} not found. Available: {', '.join(UNISWAP_TOKENS.keys())}"

    # Try Uniswap API with key
    if UNISWAP_API_KEY:
        try:
            url = f"https://api.uniswap.org/v1/prices/token/{token_info['address']}?chain=1"
            req = urllib.request.Request(url, headers={
                "User-Agent": "TradingAgent/1.0",
                "Authorization": f"Bearer {UNISWAP_API_KEY}",
                "x-api-key": UNISWAP_API_KEY,
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            price = float(data.get("price", {}).get("value", 0))
            if price > 0:
                return f"Uniswap {token}: ${price:,.2f}"
        except Exception:
            pass

    # Fallback to CoinGecko
    try:
        aliases = {"ETH": "ethereum", "BTC": "bitcoin", "SOL": "solana", "UNI": "uniswap", "LINK": "chainlink", "AAVE": "aave", "WBTC": "wrapped-bitcoin", "USDC": "usd-coin", "USDT": "tether", "DAI": "dai"}
        coin_id = aliases.get(token, token.lower())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if coin_id in data:
            price = data[coin_id].get("usd", 0)
            change = data[coin_id].get("usd_24h_change", 0) or 0
            emoji = "🟢" if change >= 0 else "🔴"
            return f"{emoji} {token}: ${price:,.2f} ({change:+.1f}%)"
    except Exception:
        pass

    return f"Could not fetch price for {token}"


def get_uniswap_pool(pair: str) -> str:
    """Get Uniswap V3 pool info."""
    pool_address = UNISWAP_POOLS.get(pair)
    if not pool_address:
        return f"Pool {pair} not found. Available: {', '.join(UNISWAP_POOLS.keys())}"

    # Get basic info from Etherscan (free, limited)
    try:
        url = f"https://api.etherscan.io/api?module=account&action=balance&address={pool_address}&tag=latest"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        balance_eth = int(data.get("result", 0)) / 1e18

        return (
            f"Uniswap V3 Pool: {pair}\n\n"
            f"Pool Address: {pool_address}\n"
            f"ETH in Pool: {balance_eth:.4f} ETH\n"
            f"Network: Ethereum Mainnet\n\n"
            f"View on Uniswap: app.uniswap.org"
        )
    except Exception:
        return f"Pool: {pair}\nAddress: {pool_address}\nView: app.uniswap.org/pool/{pool_address}"


def get_swap_quote(token_in: str, token_out: str, amount: float = 1.0) -> str:
    """Get a swap quote from Uniswap."""
    token_in = token_in.upper()
    token_out = token_out.upper()

    in_info = UNISWAP_TOKENS.get(token_in)
    out_info = UNISWAP_TOKENS.get(token_out)

    if not in_info or not out_info:
        return f"Token not found. Available: {', '.join(UNISWAP_TOKENS.keys())}"

    # Try Uniswap API with key
    if UNISWAP_API_KEY:
        try:
            amount_wei = int(amount * (10 ** in_info["decimals"]))
            url = f"https://api.uniswap.org/v1/quote?tokenIn={in_info['address']}&tokenOut={out_info['address']}&amount={amount_wei}&type=EXACT_INPUT&chain=1"
            req = urllib.request.Request(url, headers={
                "User-Agent": "TradingAgent/1.0",
                "Authorization": f"Bearer {UNISWAP_API_KEY}",
                "x-api-key": UNISWAP_API_KEY,
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            amount_out = int(data.get("quote", {}).get("amountOut", 0)) / (10 ** out_info["decimals"])
            gas_estimate = float(data.get("gasEstimate", 0)) / 1e18 * 2500  # ETH price

            if amount_out > 0:
                value_in = amount * _get_price(token_in)
                value_out = amount_out * _get_price(token_out)

                return (
                    f"Uniswap Swap Quote\n\n"
                    f"Sell: {amount:.4f} {token_in} (${value_in:,.2f})\n"
                    f"Buy: {amount_out:.4f} {token_out} (${value_out:,.2f})\n\n"
                    f"Rate: 1 {token_in} = {amount_out/amount:.6f} {token_out}\n"
                    f"Fee: 0.3%\n"
                    f"Est. Gas: ${gas_estimate:.2f}\n\n"
                    f"To swap: app.uniswap.org"
                )
        except Exception:
            pass

    # Fallback: calculate from prices
    price_in = _get_price(token_in)
    price_out = _get_price(token_out)

    # Use hardcoded stablecoin prices as fallback
    if price_out <= 0 and token_out in ("USDC", "USDT", "DAI"):
        price_out = 1.0
    if price_in <= 0 and token_in in ("USDC", "USDT", "DAI"):
        price_in = 1.0

    if price_in <= 0 or price_out <= 0:
        return f"Could not get prices for {token_in} or {token_out}"

    value_in = amount * price_in
    amount_out = value_in / price_out

    return (
        f"Uniswap Swap Quote\n\n"
        f"Sell: {amount:.4f} {token_in} (${value_in:,.2f})\n"
        f"Buy: {amount_out:.4f} {token_out} (${amount_out:,.2f})\n\n"
        f"Rate: 1 {token_in} = {amount_out/amount:.6f} {token_out}\n"
        f"Fee: 0.3%\n"
        f"To swap: app.uniswap.org"
    )


def _get_price(token: str) -> float:
    """Get token price."""
    aliases = {"ETH": "ethereum", "BTC": "bitcoin", "SOL": "solana", "UNI": "uniswap", "LINK": "chainlink", "AAVE": "aave", "WBTC": "wrapped-bitcoin", "USDC": "usd-coin", "USDT": "tether", "DAI": "dai"}
    coin_id = aliases.get(token.upper(), token.lower())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get(coin_id, {}).get("usd", 0)
    except Exception:
        return 0


def get_token_info(token: str) -> str:
    """Get detailed token info for Uniswap."""
    token = token.upper()
    info = UNISWAP_TOKENS.get(token)

    if not info:
        return f"Token {token} not found. Available: {', '.join(UNISWAP_TOKENS.keys())}"

    # Get price
    price = _get_price(token)

    return (
        f"Token: {token}\n\n"
        f"Contract: {info['address']}\n"
        f"Decimals: {info['decimals']}\n"
        f"Network: Ethereum\n"
        f"Price: ${price:,.2f}\n\n"
        f"Add to Uniswap: app.uniswap.org"
    )


def get_top_pools() -> str:
    """Get top Uniswap V3 pools."""
    lines = ["Top Uniswap V3 Pools:\n"]

    pools = [
        ("ETH/USDC", "$2B+ TVL"),
        ("ETH/USDT", "$500M+ TVL"),
        ("WBTC/ETH", "$300M+ TVL"),
        ("ETH/DAI", "$200M+ TVL"),
        ("UNI/ETH", "$100M+ TVL"),
        ("LINK/ETH", "$50M+ TVL"),
    ]

    for pair, tvl in pools:
        lines.append(f"  {pair} — {tvl}")

    lines.append("\nView all: app.uniswap.org/pools")
    return "\n".join(lines)


# ============================================================
# Tool Registry
# ============================================================

UNISWAP_TOOLS = [
    {"type": "function", "function": {"name": "get_uniswap_price", "description": "Get token price from Uniswap ecosystem.", "parameters": {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}}},
    {"type": "function", "function": {"name": "get_uniswap_pool", "description": "Get Uniswap V3 pool info.", "parameters": {"type": "object", "properties": {"pair": {"type": "string"}}, "required": ["pair"]}}},
    {"type": "function", "function": {"name": "get_swap_quote", "description": "Get swap quote from Uniswap.", "parameters": {"type": "object", "properties": {"token_in": {"type": "string"}, "token_out": {"type": "string"}, "amount": {"type": "number"}}, "required": ["token_in", "token_out"]}}},
    {"type": "function", "function": {"name": "get_token_info", "description": "Get detailed token info for Uniswap.", "parameters": {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}}},
    {"type": "function", "function": {"name": "get_top_pools", "description": "Get top Uniswap V3 pools.", "parameters": {"type": "object", "properties": {}}}},
]

UNISWAP_TOOL_MAP = {
    "get_uniswap_price": lambda a: get_uniswap_price(a["token"]),
    "get_uniswap_pool": lambda a: get_uniswap_pool(a["pair"]),
    "get_swap_quote": lambda a: get_swap_quote(a["token_in"], a["token_out"], float(a.get("amount", 1.0))),
    "get_token_info": lambda a: get_token_info(a["token"]),
    "get_top_pools": lambda a: get_top_pools(),
}
