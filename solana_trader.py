"""
Solana Memecoin Trading via Jupiter DEX.

Features:
- Buy any SPL token with SOL
- Sell any SPL token for SOL
- Check wallet SOL balance
- Check token balances
- Price quotes
- Rug pull risk indicators
"""

import json
import time
import base64
import base58
import urllib.request
import urllib.parse
from pathlib import Path

# ============================================================
# Configuration
# ============================================================

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
SOLANA_WS_RPC = "wss://api.mainnet-beta.solana.com"
JUPITER_API = "https://quote-api.jup.ag/v6"
WALLET_DIR = Path(__file__).parent / "wallets"

# Well-known token mint addresses
KNOWN_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "PEPE": "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "FARTCOIN": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    "TRUMP": "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN",
    "MYRO": "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4",
    "BOME": "ukHH6cRDm1RjDhoDT1sarVf7fMRMnEgipwZoDNKcG23",
    "W": "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "MNGO": "MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "ORCA": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "SAMO": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    "FLOKI": "4T9S2NpA3EKGbZMnDmVTFqLwiE6Tz7U3jBQ4v5W3nq6",
}

# Rug pull risk indicators
HIGH_RISK_INDICATORS = [
    "meme", "inu", "baby", "safe", "moon", "rocket", "shib",
    "pepe", "doge", "cat", "frog", "ape", "diamond",
]


# ============================================================
# Wallet Management
# ============================================================

def generate_wallet() -> dict:
    """Generate a new Solana wallet."""
    from solders.keypair import Keypair

    keypair = Keypair()
    private_key = base58.b58encode(bytes(keypair)).decode()
    public_key = str(keypair.pubkey())

    wallet = {
        "private_key": private_key,
        "public_key": public_key,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Save wallet
    WALLET_DIR.mkdir(exist_ok=True)
    wallet_path = WALLET_DIR / "main_wallet.json"
    wallet_path.write_text(json.dumps(wallet, indent=2))

    return wallet

def load_wallet() -> dict:
    """Load the main wallet."""
    wallet_path = WALLET_DIR / "main_wallet.json"
    if wallet_path.exists():
        return json.loads(wallet_path.read_text())
    return generate_wallet()

def get_wallet_address() -> str:
    """Get the wallet public address."""
    wallet = load_wallet()
    return wallet["public_key"]


# ============================================================
# Solana RPC Helpers
# ============================================================

def solana_rpc(method: str, params: list = None) -> dict:
    """Make a Solana RPC call."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        SOLANA_RPC,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def get_sol_balance() -> float:
    """Get SOL balance for the wallet."""
    address = get_wallet_address()
    result = solana_rpc("getBalance", [address])
    lamports = result.get("result", {}).get("value", 0)
    return lamports / 1e9  # Convert lamports to SOL

def get_token_balances() -> list:
    """Get all SPL token balances."""
    address = get_wallet_address()
    result = solana_rpc("getTokenAccountsByOwner", [
        address,
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        {"encoding": "jsonParsed"},
    ])

    balances = []
    for account in result.get("result", {}).get("value", []):
        info = account["account"]["data"]["parsed"]["info"]
        token_amount = info["tokenAmount"]
        if float(token_amount["uiAmount"] or 0) > 0:
            balances.append({
                "mint": info["mint"],
                "amount": token_amount["uiAmount"],
                "decimals": token_amount["decimals"],
            })
    return balances

def get_sol_price() -> float:
    """Get current SOL price in USD."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data["solana"]["usd"]
    except Exception:
        return 0.0

def get_token_price(mint: str) -> float:
    """Get token price via Jupiter quote."""
    try:
        # Use Jupiter to get a quote for 1 token -> USDC
        url = f"{JUPITER_API}/quote?inputMint={mint}&outputMint={KNOWN_TOKENS['USDC']}&amount=1000000&slippageBps=50"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        out_amount = int(data.get("outAmount", 0))
        return out_amount / 1e6  # USDC has 6 decimals
    except Exception:
        return 0.0


# ============================================================
# Jupiter DEX Swap
# ============================================================

def get_swap_quote(input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50) -> dict:
    """Get a swap quote from Jupiter."""
    url = f"{JUPITER_API}/quote?inputMint={input_mint}&output_mint={output_mint}&amount={amount}&slippageBps={slippage_bps}"
    req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def get_swap_transaction(quote: dict) -> dict:
    """Get the swap transaction from Jupiter."""
    url = f"{JUPITER_API}/swap"
    payload = json.dumps({
        "quoteResponse": quote,
        "userPublicKey": get_wallet_address(),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "TradingAgent/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def sign_and_send_transaction(tx_base64: str) -> str:
    """Sign and send a transaction."""
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction

    wallet = load_wallet()
    keypair = Keypair.from_base58_string(wallet["private_key"])

    # Decode transaction
    tx_bytes = base64.b64decode(tx_base64)
    tx = VersionedTransaction.from_bytes(tx_bytes)

    # Sign
    signed_tx = VersionedTransaction(tx.message, [keypair])

    # Send
    tx_base64_signed = base64.b64encode(bytes(signed_tx)).decode()
    result = solana_rpc("sendTransaction", [
        tx_base64_signed,
        {"encoding": "base64", "skipPreflight": True, "maxRetries": 3},
    ])

    return result.get("result", "Error: No transaction signature")


# ============================================================
# Trading Functions
# ============================================================

def buy_token(token_symbol: str, sol_amount: float, slippage_bps: int = 100) -> str:
    """Buy a token with SOL."""
    try:
        # Find mint address
        token_symbol = token_symbol.upper()
        mint = KNOWN_TOKENS.get(token_symbol)
        if not mint:
            # Try searching by name
            for symbol, address in KNOWN_TOKENS.items():
                if token_symbol.lower() in symbol.lower():
                    mint = address
                    token_symbol = symbol
                    break
            if not mint:
                return f"❌ Unknown token: {token_symbol}\nKnown tokens: {', '.join(KNOWN_TOKENS.keys())}"

        # Check SOL balance
        sol_balance = get_sol_balance()
        if sol_amount > sol_balance * 0.95:  # Keep 5% for gas
            return f"❌ Insufficient SOL. You have {sol_balance:.4f} SOL"

        # Get quote
        sol_mint = KNOWN_TOKENS["SOL"]
        lamports = int(sol_amount * 1e9)

        quote = get_swap_quote(sol_mint, mint, lamports, slippage_bps)

        if "error" in quote:
            return f"❌ Quote error: {quote['error']}"

        # Get expected output
        out_amount = int(quote.get("outAmount", 0))
        price_impact = float(quote.get("priceImpactPct", 0))

        if price_impact > 5:
            return f"⚠️ High price impact: {price_impact:.1f}% — trade may cause significant slippage"

        # Get swap transaction
        swap_tx = get_swap_transaction(quote)
        if "error" in swap_tx:
            return f"❌ Swap error: {swap_tx['error']}"

        # Sign and send
        tx_sig = sign_and_send_transaction(swap_tx["swapTransaction"])

        if "Error" in str(tx_sig):
            return f"❌ Transaction failed: {tx_sig}"

        sol_price = get_sol_price()
        usd_value = sol_amount * sol_price

        return (
            f"✅ *BUY EXECUTED*\n\n"
            f"Token: {token_symbol}\n"
            f"Spent: {sol_amount:.4f} SOL (~${usd_value:.2f})\n"
            f"Received: ~{out_amount} tokens\n"
            f"Price Impact: {price_impact:.2f}%\n"
            f"TX: `{tx_sig}`\n"
            f"🔒 Check: https://solscan.io/tx/{tx_sig}"
        )
    except Exception as e:
        return f"❌ Buy failed: {str(e)}"

def sell_token(token_symbol: str, percentage: float = 100, slippage_bps: int = 100) -> str:
    """Sell a token for SOL."""
    try:
        token_symbol = token_symbol.upper()
        mint = KNOWN_TOKENS.get(token_symbol)
        if not mint:
            for symbol, address in KNOWN_TOKENS.items():
                if token_symbol.lower() in symbol.lower():
                    mint = address
                    token_symbol = symbol
                    break
            if not mint:
                return f"❌ Unknown token: {token_symbol}"

        # Get token balance
        balances = get_token_balances()
        token_balance = None
        for b in balances:
            if b["mint"] == mint:
                token_balance = b
                break

        if not token_balance:
            return f"❌ No {token_symbol} balance found"

        # Calculate amount to sell
        total_amount = int(token_balance["amount"] * (10 ** token_balance["decimals"]))
        sell_amount = int(total_amount * (percentage / 100))

        if sell_amount <= 0:
            return f"❌ Amount too small to sell"

        # Get quote
        sol_mint = KNOWN_TOKENS["SOL"]
        quote = get_swap_quote(mint, sol_mint, sell_amount, slippage_bps)

        if "error" in quote:
            return f"❌ Quote error: {quote['error']}"

        out_lamports = int(quote.get("outAmount", 0))
        sol_received = out_lamports / 1e9
        price_impact = float(quote.get("priceImpactPct", 0))

        # Get swap transaction
        swap_tx = get_swap_transaction(quote)
        if "error" in swap_tx:
            return f"❌ Swap error: {swap_tx['error']}"

        # Sign and send
        tx_sig = sign_and_send_transaction(swap_tx["swapTransaction"])

        if "Error" in str(tx_sig):
            return f"❌ Transaction failed: {tx_sig}"

        sol_price = get_sol_price()
        usd_value = sol_received * sol_price

        return (
            f"✅ *SELL EXECUTED*\n\n"
            f"Token: {token_symbol}\n"
            f"Sold: {percentage}% of holdings\n"
            f"Received: {sol_received:.4f} SOL (~${usd_value:.2f})\n"
            f"Price Impact: {price_impact:.2f}%\n"
            f"TX: `{tx_sig}`\n"
            f"🔒 Check: https://solscan.io/tx/{tx_sig}"
        )
    except Exception as e:
        return f"❌ Sell failed: {str(e)}"


# ============================================================
# Wallet Display
# ============================================================

def get_wallet_info() -> str:
    """Get full wallet information."""
    try:
        address = get_wallet_address()
        sol_balance = get_sol_balance()
        sol_price = get_sol_price()
        sol_usd = sol_balance * sol_price

        lines = [f"💼 *Solana Wallet*\n"]
        lines.append(f"Address: `{address[:8]}...{address[-8:]}`")
        lines.append(f"Full: `{address}`\n")
        lines.append(f"💰 SOL: {sol_balance:.4f} (~${sol_usd:.2f})")

        # Token balances
        balances = get_token_balances()
        if balances:
            lines.append(f"\n🪙 *Tokens ({len(balances)}):*")
            for b in balances[:10]:
                try:
                    price = get_token_price(b["mint"])
                    value = b["amount"] * price
                    # Find symbol
                    symbol = "Unknown"
                    for s, m in KNOWN_TOKENS.items():
                        if m == b["mint"]:
                            symbol = s
                            break
                    lines.append(f"  • {symbol}: {b['amount']:,.2f} (~${value:.2f})")
                except:
                    lines.append(f"  • {b['mint'][:8]}...: {b['amount']:,.2f}")
        else:
            lines.append("\nNo token balances")

        return "\n".join(lines)
    except Exception as e:
        return f"Error getting wallet info: {str(e)}"


# ============================================================
# Risk Check
# ============================================================

def check_rug_risk(token_symbol: str) -> str:
    """Check basic rug pull risk indicators."""
    token_symbol = token_symbol.lower()
    warnings = []

    # Check name for risky patterns
    for indicator in HIGH_RISK_INDICATORS:
        if indicator in token_symbol:
            warnings.append(f"⚠️ Name contains '{indicator}' — common in rug pulls")

    # Check if it's a known legitimate token
    if token_symbol.upper() in ["SOL", "USDC", "USDT", "JUP", "RAY", "ORCA"]:
        return "✅ Known legitimate token"

    if not warnings:
        return "✅ No obvious risk indicators (but always DYOR!)"

    return "\n".join(warnings) + "\n\n⚠️ This is a memecoin — high risk! Always DYOR."
