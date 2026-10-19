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
import re
import time
import base64
import base58
import urllib.request
import urllib.parse
from pathlib import Path

# ============================================================
# Configuration
# ============================================================

from evm_swap import solana_rpc, solana_ws_rpc

SOLANA_RPC = solana_rpc()          # Helius -> Alchemy -> public (best available)
SOLANA_WS_RPC = solana_ws_rpc()
SOLANA_WS_RPC = "wss://api.mainnet-beta.solana.com"
JUPITER_API = "https://lite-api.jup.ag/swap/v1"
WALLET_DIR = Path(__file__).parent / "wallets"

# Well-known token mint addresses
KNOWN_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    # NOTE: PEPE removed 2026-09-03 — the old entry pointed at the OFFICIAL
    # TRUMP mint (copy-paste bug: buying "PEPE" bought TRUMP). No canonical
    # Solana PEPE exists (DexScreener shows 5 lookalikes at similar
    # liquidity) — the live resolver in buy_token handles it with
    # user confirmation instead of guessing.
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "FARTCOIN": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    "TRUMP": "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN",  # OFFICIAL TRUMP (verified DexScreener)
    "MYRO": "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4",
    "BOME": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",    # BOOK OF MEME (verified; old entry was a fake lookalike)
    "W": "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "MNGO": "MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "ORCA": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "SAMO": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    # FLOKI removed — no liquid Solana market under the stored mint.
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


def import_solana_wallet(key_material: str) -> str:
    """Import an EXISTING Solana wallet from any common export format:
      • Phantom/exodus: base58 of the full 64-byte keypair (most common)
      • Solana CLI: JSON byte array [17, 23, …] (64 = keypair, 32 = seed)
      • bare 32-byte seed (base58 or hex)
    Validates by deriving the keypair, backs up existing wallet files,
    writes BOTH on-disk formats (solana_trader's main_wallet.json base58
    keypair + nft_tools' solana_wallet.json seed list), never echoes the key.
    """
    import base58 as b58lib
    from solders.keypair import Keypair
    from datetime import datetime as _dt

    raw_key = (key_material or "").strip().strip('"').strip("'")
    if not raw_key:
        return "❌ No key provided."

    raw = None
    if raw_key.startswith("["):
        try:
            arr = json.loads(raw_key)
            if not isinstance(arr, list) or not all(isinstance(x, int) and 0 <= x <= 255 for x in arr):
                raise ValueError("not a byte array")
            raw = bytes(arr)
        except Exception:
            return "❌ Byte-array key must be a JSON list of 0-255 ints, e.g. [17, 23, …]"
    else:
        # hex seed?
        if re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", raw_key):
            raw = bytes.fromhex(raw_key.removeprefix("0x"))
        else:
            try:
                raw = b58lib.b58decode(raw_key)
            except Exception:
                return ("❌ Could not decode the key. Expected: base58 keypair "
                        "(Phantom export), base58/hex 32-byte seed, or a JSON "
                        "byte array from solana-keygen.")
    if len(raw) == 64:
        try:
            kp = Keypair.from_bytes(raw)
        except Exception as e:
            return f"❌ Invalid 64-byte keypair: {type(e).__name__}"
    elif len(raw) == 32:
        try:
            kp = Keypair.from_seed(raw)
        except Exception as e:
            return f"❌ Invalid 32-byte seed: {type(e).__name__}"
    else:
        return (f"❌ Decoded key is {len(raw)} bytes — expected 64 (keypair) "
                "or 32 (seed). Phantom exports are 64-byte base58.")

    addr = str(kp.pubkey())
    b58_full = b58lib.b58encode(bytes(kp)).decode()   # 64-byte keypair, b58
    seed_list = list(kp.secret())                      # 32-byte seed, list

    # Existing state (for the replace report) + backups
    main_f = WALLET_DIR / "main_wallet.json"
    sol_f = WALLET_DIR / "solana_wallet.json"
    old_addrs = {}
    for f in (main_f, sol_f):
        if f.exists():
            try:
                old_addrs[f.name] = json.loads(f.read_text()).get("public_key", "?")
            except Exception:
                old_addrs[f.name] = "(unreadable)"
    try:
        bdir = WALLET_DIR / "backups"
        bdir.mkdir(exist_ok=True)
        tag = _dt.now().strftime("%Y%m%d_%H%M%S")
        for f in (main_f, sol_f):
            if f.exists():
                (bdir / f"{tag}_{f.name}").write_text(f.read_text())
    except Exception:
        pass

    WALLET_DIR.mkdir(exist_ok=True)
    now = _dt.now().isoformat()
    # solana_trader reads base58 keypair string
    main_f.write_text(json.dumps({"private_key": b58_full, "public_key": addr,
                                  "created_at": now}, indent=2))
    # nft_tools reads a 32-byte seed list
    sol_f.write_text(json.dumps({"public_key": addr, "private_key": seed_list,
                                 "created_at": now, "chain": "solana"}, indent=2))

    lines = ["✅ Solana wallet imported", "",
             f"Address: {addr}",
             "• main_wallet.json (trader): written (base58 keypair)",
             "• solana_wallet.json (NFT tools): written (seed)"]
    replaced = [f"{n} (was {a[:8]}…)" for n, a in old_addrs.items() if a != addr]
    if replaced:
        lines.append(f"• REPLACED previous wallet(s): {', '.join(replaced)} — backups in wallets/backups/")
    else:
        lines.append("• Existing files already matched this key — refreshed")
    lines += ["",
              "🔒 Key stored locally, never displayed.",
              "⚠️ If this key was pasted into any chat, treat the wallet as hot: keep only trading funds here.",
              "", "Fund with SOL to trade. /wallet to verify."]
    return "\n".join(lines)

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
    """Get all SPL token balances — legacy SPL **and** Token-2022.

    Newer mints (PumpSwap-era tokens, most 2026 launches) live under the
    Token-2022 program (TokenzQdBN…); wallets hold accounts under both
    programs, so scanning only the legacy program makes most positions
    invisible. Query each and merge by mint."""
    address = get_wallet_address()
    token_programs = (
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # legacy SPL
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",  # token-2022
    )
    merged: dict = {}
    for program_id in token_programs:
        try:
            result = solana_rpc("getTokenAccountsByOwner", [
                address,
                {"programId": program_id},
                {"encoding": "jsonParsed"},
            ])
        except Exception:
            continue  # one program failing must not hide the other
        for account in (result.get("result") or {}).get("value", []):
            try:
                info = account["account"]["data"]["parsed"]["info"]
                token_amount = info["tokenAmount"]
                amount = float(token_amount["uiAmount"] or 0)
                if amount <= 0:
                    continue
                mint = info["mint"]
                if mint in merged:
                    merged[mint]["amount"] = float(merged[mint]["amount"]) + amount
                else:
                    merged[mint] = {
                        "mint": mint,
                        "amount": amount,
                        "decimals": token_amount["decimals"],
                    }
            except (KeyError, TypeError, ValueError):
                continue
    return list(merged.values())

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
    url = f"{JUPITER_API}/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={slippage_bps}"
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

def sign_and_send_transaction(tx_base64: str, journal_info: dict = None) -> str:
    """Sign and send a transaction. journal_info (optional) enriches the
    trade-journal entry: {kind, token, token_addr, amount, native, side,
    source, wallet, note}."""
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

    sig = result.get("result", "Error: No transaction signature")
    try:
        import trade_journal
        info = dict(journal_info or {})
        ok = isinstance(sig, str) and not sig.startswith("Error")
        trade_journal.log_trade(
            kind=info.get("kind", "swap"), chain="solana",
            side=info.get("side", ""), token=info.get("token", ""),
            token_addr=info.get("token_addr", ""), amount=info.get("amount"),
            native=info.get("native", ""), tx=sig if ok else "",
            status="broadcasted" if ok else "failed",
            source=info.get("source", "manual"), wallet=info.get("wallet", ""),
            note=info.get("note", ""))
    except Exception:
        pass
    return sig


# ============================================================
# Trading Functions
# ============================================================

def _resolve_token_live(symbol: str):  # noqa: C901
    """Resolve a token symbol to a mint via DexScreener, in two steps:
    1. search (broad, noisy) → candidate mints whose SYMBOL matches exactly
       (whitespace/$-normalized — impersonators love trailing-space tricks)
    2. batch-verify candidates via the accurate token endpoint → real per-mint
       liquidity for ranking, floor-checking and ambiguity detection.
    Returns (mint, display_name) or a refusal string. Never guesses on
    ambiguity: a wrong pick means buying a scam lookalike."""
    import requests as _rq
    H = {"User-Agent": "Mozilla/5.0 aesir-agent/1.0"}
    want = symbol.upper().strip().lstrip("$")
    try:
        r = _rq.get("https://api.dexscreener.com/latest/dex/search",
                    params={"q": symbol}, timeout=10, headers=H)
        pairs = (r.json() or {}).get("pairs") or []
    except Exception as e:
        return (f"❌ Couldn't look up {symbol} live ({str(e)[:60]}). Known "
                f"tokens: {', '.join(sorted(KNOWN_TOKENS))} — or paste the mint address.")
    candidates = {}
    for p in pairs:
        if p.get("chainId") != "solana":
            continue
        bt = p.get("baseToken") or {}
        m = bt.get("address")
        if not m:
            continue
        sym = (bt.get("symbol") or "").upper().strip().lstrip("$")
        if sym == want and m not in candidates:
            candidates[m] = bt.get("name") or want
    if not candidates:
        return (f"❌ No Solana token with symbol {want} found live. Known: "
                f"{', '.join(sorted(KNOWN_TOKENS))} — or paste the mint address.")
    # The table's canonical mint competes too (search is noisy — the real
    # token's pair may not surface while lookalikes do).
    canonical = KNOWN_TOKENS.get(want)
    if canonical and canonical not in candidates:
        candidates[canonical] = want
    # Step 2: verified liquidity (search numbers are unreliable). If the
    # verify call itself fails, REFUSE — degrading to search data would
    # rank scam lookalikes against real money.
    time.sleep(1.2)
    try:
        r2 = _rq.get(f"https://api.dexscreener.com/tokens/v1/solana/{','.join(list(candidates)[:30])}",
                     timeout=12, headers=H)
        if r2.status_code != 200:
            raise RuntimeError(f"verify HTTP {r2.status_code}")
        vpairs = r2.json()
    except Exception as e:
        return (f"❌ Couldn't verify live liquidity for {want} ({str(e)[:60]}) — "
                f"refusing to guess. Paste the exact mint address to proceed.")
    verified = {m: (0, candidates[m]) for m in candidates}
    for p in vpairs if isinstance(vpairs, list) else []:
        bt = p.get("baseToken") or {}
        m = bt.get("address")
        if m not in candidates:
            continue
        liq = ((p.get("liquidity") or {}).get("usd")) or 0
        cur = verified.get(m, (0, candidates[m]))
        if liq > cur[0]:
            verified[m] = (liq, bt.get("name") or candidates[m])
    ranked = sorted(verified.items(), key=lambda kv: -kv[1][0])
    top_mint, (top_liq, top_name) = ranked[0]
    MIN_LIQ = 50_000
    if top_liq < MIN_LIQ:
        return (f"❌ Best {want} market has only ${top_liq:,.0f} liquidity "
                f"(below the ${MIN_LIQ:,} safety floor) — refusing to guess. "
                f"For new tokens, paste the mint address and rugcheck it first.")
    runner_liq = ranked[1][1][0] if len(ranked) > 1 else 0
    if runner_liq > top_liq * 0.6:  # near-equal runners = impersonation territory
        alts = ", ".join(f"{m[:8]}… (${l:,.0f})" for m, (l, _) in ranked[1:4])
        return (f"⚠️ '{want}' is AMBIGUOUS — multiple tokens share the symbol. "
                f"Top: {top_mint[:8]}… (${top_liq:,.0f} liq, '{top_name}') vs {alts}. "
                f"Paste the exact mint address to proceed, or confirm "
                f"'{top_mint[:8]}' for the top one.")
    return top_mint, (top_name or want)


def buy_token(token_symbol: str, sol_amount: float, slippage_bps: int = 100,
              usd_amount: float = None) -> str:
    """Buy a token with SOL. Pass EITHER sol_amount OR usd_amount (converted
    at the live SOL rate — a failed conversion refuses rather than guesses)."""
    try:
        if usd_amount is None and (not sol_amount or sol_amount <= 0):
            return "❌ Pass a size: usd_amount (dollars, preferred) or sol_amount."
        if usd_amount is not None:
            if sol_amount and sol_amount > 0:
                return "❌ Pass either sol_amount or usd_amount, not both."
            p = get_sol_price()
            if p <= 0:
                return ("❌ Couldn't fetch the live SOL price to convert your "
                        "USD amount — refusing to guess. Give the size in SOL.")
            sol_amount = round(float(usd_amount) / p, 4)
            if sol_amount <= 0:
                return (f"❌ ${usd_amount} converts to ~0 SOL at the live rate "
                        f"(${p:,.2f}/SOL). Increase the amount.")
        # Find mint address
        token_symbol = token_symbol.upper()
        if 32 <= len(token_symbol) <= 44 and not token_symbol.startswith("0X") \
                and token_symbol != token_symbol.lower():
            # Looks like a raw base58 mint pasted directly
            mint = token_symbol
            token_symbol = token_symbol[:6] + "…"
        else:
            mint = KNOWN_TOKENS.get(token_symbol)
            if not mint:
                resolved = _resolve_token_live(token_symbol)
                if isinstance(resolved, str):
                    return resolved  # refusal / ambiguity question
                mint, token_symbol = resolved

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
        tx_sig = sign_and_send_transaction(
            swap_tx["swapTransaction"],
            journal_info={"kind": "swap", "side": "buy", "token": token_symbol,
                          "token_addr": mint, "amount": sol_amount,
                          "native": f"{sol_amount:.4f} SOL"})

        if "Error" in str(tx_sig):
            return f"❌ Transaction failed: {tx_sig}"

        sol_price = get_sol_price()
        usd_value = sol_amount * sol_price

        return (
            f"✅ *BUY EXECUTED*\n\n"
            f"Token: {token_symbol}\n"
            f"Spent: {sol_amount:.4f} SOL (~${usd_value:.2f}"
            + (f" — you asked for ${usd_amount:.2f}" if usd_amount is not None else "") + ")\n"
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
        if 32 <= len(token_symbol) <= 44 and not token_symbol.startswith("0X") \
                and token_symbol != token_symbol.lower():
            mint = token_symbol  # raw base58 mint
            token_symbol = token_symbol[:6] + "…"
        else:
            mint = KNOWN_TOKENS.get(token_symbol)
            if not mint:
                resolved = _resolve_token_live(token_symbol)
                if isinstance(resolved, str):
                    return resolved
                mint, token_symbol = resolved

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
        tx_sig = sign_and_send_transaction(
            swap_tx["swapTransaction"],
            journal_info={"kind": "swap", "side": "sell", "token": token_symbol,
                          "token_addr": mint, "amount": percentage,
                          "native": f"{sol_received:.4f} SOL out"})

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

def _rugcheck_fetch(mint: str):
    """RugCheck.xyz summary (free, keyless) — dict or None."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary",
            headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def rugcheck_gate(mint: str) -> str:
    """Return 'ok' if safe enough to auto-copy, else a refusal reason.
    Used by the Solana copytrade mirror before spending real SOL."""
    data = _rugcheck_fetch(mint)
    if data is None:
        # API down: don't block trading on the checker's availability —
        # note it in the journal ping instead.
        return "ok"
    score = data.get("score_normalised")
    if isinstance(score, (int, float)) and score >= 60:
        return f"RugCheck risk score {score}/100 (dangerous)"
    for r in data.get("risks", []):
        if str(r.get("level", "")).lower() == "danger":
            return f"RugCheck danger: {r.get('name', 'unknown risk')}"
    lp = data.get("lpLockedPct")
    if lp == 0:
        return "RugCheck: LP not locked — dev can pull liquidity"
    return "ok"


def rugcheck_report(token: str) -> str:
    """Full human report for /rugcheck — accepts a mint address or known symbol."""
    mint = token.strip()
    if len(mint) < 40 or not mint.replace("-", "").isalnum():
        mint = KNOWN_TOKENS.get(token.upper(), "")
    if not mint:
        return f"❌ Unknown token {token!r} — pass a mint address (or a known symbol)."
    data = _rugcheck_fetch(mint)
    if not data:
        return f"❌ RugCheck unreachable for {mint[:8]}… — try again later."
    score = data.get("score_normalised", "?")
    verdict = ("🟢 LOW" if isinstance(score, (int, float)) and score < 30
               else "🟡 ELEVATED" if isinstance(score, (int, float)) and score < 60
               else "🔴 HIGH")
    lines = [f"🔍 RugCheck — {mint[:8]}…{mint[-4:]}",
             f"Risk score: {score}/100 — {verdict}"]
    lp = data.get("lpLockedPct")
    if lp is not None:
        lines.append(f"LP locked: {float(lp):.1f}%")
    risks = data.get("risks", [])
    if risks:
        lines.append("\nFlagged risks:")
        for r in risks[:6]:
            lvl = {"danger": "🔴", "warn": "🟡"}.get(str(r.get("level", "")).lower(), "·")
            lines.append(f"  {lvl} {r.get('name', '?')}: {str(r.get('description', ''))[:80]}")
    else:
        lines.append("No risks flagged ✅")
    lines.append(f"\nDetails: https://rugcheck.xyz/tokens/{mint}")
    return "\n".join(lines)


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
