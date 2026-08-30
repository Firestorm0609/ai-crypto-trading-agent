"""
Jupiter Swap Execution — Real swaps on Solana

Uses:
- Jupiter V6 Swap API for getting swap transactions
- Solana RPC for sending transactions
- Solders for transaction signing
"""

import json
import urllib.request
import base64
from pathlib import Path

WALLETS_DIR = Path(__file__).parent / "wallets"
WALLETS_DIR.mkdir(exist_ok=True)

SOLANA_WALLET_FILE = WALLETS_DIR / "solana_wallet.json"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"


def _load_solana_wallet() -> dict:
    """Load the Solana wallet."""
    if SOLANA_WALLET_FILE.exists():
        return json.loads(SOLANA_WALLET_FILE.read_text())
    return None


def _get_sol_balance(pubkey: str) -> float:
    """Get SOL balance."""
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "getBalance",
            "params": [pubkey]
        })
        req = urllib.request.Request(
            SOLANA_RPC, data=payload.encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        lamports = data.get("result", {}).get("value", 0)
        return lamports / 1e9
    except Exception:
        return 0


def execute_swap(token_in: str, token_out: str, amount: float, slippage: int = 50) -> str:
    """
    Execute a swap on Jupiter.
    
    Args:
        token_in: Input token symbol or mint address (e.g. 'SOL' or mint address)
        token_out: Output token symbol or mint address
        amount: Amount to swap
        slippage: Slippage tolerance in bps (50 = 0.5%)
    """
    from jupiter_tools import SOLANA_TOKENS

    wallet = _load_solana_wallet()
    if not wallet:
        return (
            "No Solana wallet found.\n"
            "Create one: /newwallet solana\n"
            "Then fund it with SOL for gas."
        )

    pubkey = wallet["public_key"]

    # Resolve token mints
    mint_in = SOLANA_TOKENS.get(token_in.upper(), token_in)
    mint_out = SOLANA_TOKENS.get(token_out.upper(), token_out)

    # Get decimals
    decimals_in = 9
    if token_in.upper() in ("USDC", "USDT"):
        decimals_in = 6

    # Calculate lamports
    amount_lamports = int(amount * (10 ** decimals_in))

    # Check balance
    balance = _get_sol_balance(pubkey)
    if balance < 0.01:
        return (
            f"Insufficient SOL for gas.\n"
            f"Balance: {balance:.4f} SOL\n"
            f"Need: ~0.01 SOL\n\n"
            f"Fund wallet: {pubkey}"
        )

    # Get swap transaction from Jupiter
    try:
        params = {
            "inputMint": mint_in,
            "outputMint": mint_out,
            "amount": str(amount_lamports),
            "slippageBps": str(slippage),
            "userPublicKey": pubkey,
        }
        url = "https://quote-api.jup.ag/v6/quote?" + "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            quote = json.loads(resp.read().decode())

        if "error" in quote:
            return f"Quote error: {quote['error']}"

        # Get swap transaction
        swap_body = json.dumps({
            "quoteResponse": quote,
            "userPublicKey": pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        })

        swap_req = urllib.request.Request(
            "https://quote-api.jup.ag/v6/swap",
            data=swap_body.encode(),
            headers={"Content-Type": "application/json", "User-Agent": "TradingAgent/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(swap_req, timeout=15) as resp:
            swap_data = json.loads(resp.read().decode())

        swap_transaction = swap_data.get("swapTransaction")
        if not swap_transaction:
            return "Failed to get swap transaction from Jupiter"

        # Sign and send transaction
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction

        keypair = Keypair.from_bytes(bytes(wallet["private_key"]))
        tx_bytes = base64.b64decode(swap_transaction)
        tx = VersionedTransaction.from_bytes(tx_bytes)

        # Sign the transaction
        signed_tx = VersionedTransaction(tx.message, [keypair])

        # Send transaction
        send_payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode(), {"encoding": "base64"}]
        })
        send_req = urllib.request.Request(
            SOLANA_RPC, data=send_payload.encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(send_req, timeout=30) as resp:
            send_result = json.loads(resp.read().decode())

        tx_hash = send_result.get("result", "")
        if tx_hash:
            # Get output amount
            out_amount = int(quote.get("outAmount", 0))
            decimals_out = 6 if token_out.upper() in ("USDC", "USDT") else 9
            out_readable = out_amount / (10 ** decimals_out)

            return (
                f"Swap Executed!\n\n"
                f"Sold: {amount:.4f} {token_in.upper()}\n"
                f"Bought: {out_readable:.4f} {token_out.upper()}\n"
                f"Slippage: {slippage/100:.1f}%\n\n"
                f"TX: {tx_hash}\n"
                f"View: solscan.io/tx/{tx_hash}"
            )
        else:
            error = send_result.get("error", {}).get("message", "Unknown error")
            return f"Transaction failed: {error}"

    except Exception as e:
        return f"Swap error: {str(e)}"


def buy_token(token: str, amount_sol: float) -> str:
    """Buy a token with SOL on Jupiter."""
    return execute_swap("SOL", token, amount_sol)


def sell_token(token: str, percentage: float = 100) -> str:
    """Sell a token for SOL on Jupiter."""
    from jupiter_tools import SOLANA_TOKENS

    wallet = _load_solana_wallet()
    if not wallet:
        return "No Solana wallet found. Create: /newwallet solana"

    mint = SOLANA_TOKENS.get(token.upper(), token)

    # Get token balance
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet["public_key"],
                {"mint": mint},
                {"encoding": "jsonParsed"}
            ]
        })
        req = urllib.request.Request(
            SOLANA_RPC, data=payload.encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        accounts = data.get("result", {}).get("value", [])
        if not accounts:
            return f"No {token.upper()} balance found"

        amount = int(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        decimals = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["decimals"]
        sell_amount = int(amount * (percentage / 100))

        if sell_amount <= 0:
            return f"Nothing to sell"

        # Execute sell (token -> SOL)
        return execute_swap(token, "SOL", sell_amount / (10 ** decimals))

    except Exception as e:
        return f"Error getting balance: {str(e)}"


# ============================================================
# Tool Registry
# ============================================================

SWAP_TOOLS = [
    {"type": "function", "function": {"name": "jupiter_buy", "description": "Buy a Solana token with SOL on Jupiter. Real swap execution.", "parameters": {"type": "object", "properties": {"token": {"type": "string", "description": "Token symbol or mint address"}, "amount_sol": {"type": "number", "description": "Amount of SOL to spend"}}, "required": ["token", "amount_sol"]}}},
    {"type": "function", "function": {"name": "jupiter_sell", "description": "Sell a Solana token for SOL on Jupiter. Real swap execution.", "parameters": {"type": "object", "properties": {"token": {"type": "string", "description": "Token symbol or mint address"}, "percentage": {"type": "number", "description": "Percentage to sell (default 100)"}}, "required": ["token"]}}},
    {"type": "function", "function": {"name": "check_sol_balance", "description": "Check SOL balance in the Solana wallet.", "parameters": {"type": "object", "properties": {}}}},
]

SWAP_TOOL_MAP = {
    "jupiter_buy": lambda a: buy_token(a["token"], float(a["amount_sol"])),
    "jupiter_sell": lambda a: sell_token(a["token"], float(a.get("percentage", 100))),
    "check_sol_balance": lambda a: _check_balance(),
}


def _check_balance() -> str:
    """Check wallet SOL balance."""
    wallet = _load_solana_wallet()
    if not wallet:
        return "No wallet. Create: /newwallet solana"
    balance = _get_sol_balance(wallet["public_key"])
    return f"Wallet: {wallet['public_key'][:20]}...\nSOL Balance: {balance:.4f}\nAddress: {wallet['public_key']}"
