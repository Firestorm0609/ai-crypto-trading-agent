"""
Real EVM Token Swaps — Uniswap V3 via SwapRouter02, no API keys.

Replaces the simulated swap in multichain_tools.swap_evm_token.

How it works (same trust model as the Solana side):
1. Quote via QuoterV2 (read-only eth_call) against real pool liquidity
2. Approve the router for the exact input amount (only if needed)
3. Build exactInputSingle with amountOutMinimum from real quote - slippage
4. Sign locally with the EVM wallet's private key (wallets/evm_wallet.json)
5. Broadcast via free public RPC (eth.llamarpc.com / mainnet.base.org)

Supported chains: ethereum (chain 1), base (chain 8453),
robinhood (chain 4663 — Arbitrum Orbit L2).
Native ETH input is auto-wrapped via the router; WETH output is
auto-unwrapped back to ETH.

Contract addresses verified from official Uniswap deployment docs
(developers.uniswap.org), Circle's USDC docs, and ON-CHAIN
(get_code / getPool / live QuoterV2 quote) for Robinhood Chain.
Do not change these without re-verifying.
"""

import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Alchemy key (free tier) — primary RPC where enabled: reliability/uptime
# over public endpoints. Falls back to public RPCs automatically.
ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "")

_ALCHEMY_SLUGS = {
    "ethereum": "eth-mainnet",
    "base": "base-mainnet",
    "arbitrum": "arb-mainnet",
    "optimism": "opt-mainnet",
    "polygon": "polygon-mainnet",
    "robinhood": "robinhood-mainnet",
}


def alchemy_rpc(chain: str) -> str:
    """Alchemy RPC URL for a chain ("" if no key or unknown chain)."""
    slug = _ALCHEMY_SLUGS.get((chain or "").lower())
    if not slug or not ALCHEMY_KEY:
        return ""
    return f"https://{slug}.g.alchemy.com/v2/{ALCHEMY_KEY}"


def get_eth_usd_price() -> float:
    """Live ETH/USD via CoinGecko. Returns 0.0 on failure — callers must
    show balances WITHOUT usd rather than invent a rate."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
            headers={"accept": "application/json", "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return float(json.loads(r.read())["ethereum"]["usd"])
    except Exception:
        return 0.0


def get_evm_wallet_info() -> str:
    """Native-gas balances of the shared EVM wallet on every configured chain.
    Read-only, safe to call anytime."""
    wallet = _load_wallet("ethereum")
    if not wallet or not wallet.get("address"):
        return "❌ No EVM wallet — import one first (import_evm_wallet)."
    addr = wallet["address"]
    lines = [f"✳️ EVM wallet: {addr}"]
    total_lines = []
    eth_usd = get_eth_usd_price()
    total_usd = 0.0
    import urllib.request
    for ch, cfg in CHAINS.items():
        urls = ([alchemy_rpc(ch)] if alchemy_rpc(ch) else []) + list(cfg.get("rpcs", []))
        bal = None
        for url in urls:
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"jsonrpc": "2.0", "id": 1,
                                     "method": "eth_getBalance",
                                     "params": [addr, "latest"]}).encode(),
                    headers={"Content-Type": "application/json",
                             "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    wei = int(json.loads(r.read()).get("result", "0x0"), 16)
                bal = wei / 1e18
                break
            except Exception:
                continue
        sym = cfg.get("symbol", "?")
        usd = bal * eth_usd if (eth_usd and bal is not None) else None
        total_lines.append(f"  {ch:10} {bal:.6f} {sym}" + (f" (~${usd:,.2f})" if usd else "")
                           if bal is not None else f"  {ch:10} unreachable")
        if usd:
            total_usd += usd
    lines += total_lines
    if total_usd > 0:
        lines.append(f"  total ≈ ${total_usd:,.2f}")
    return "\n".join(lines)


# ---- Solana RPC: Helius first (lowest latency + no 429 hell), then
# Alchemy, then the rate-limited public endpoint. Env can override all. ----
HELIUS_KEY = os.getenv("HELIUS_API_KEY", "")

def solana_rpc() -> str:
    if os.getenv("SOLANA_RPC_URL"):
        return os.getenv("SOLANA_RPC_URL")
    if HELIUS_KEY:
        return f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
    if ALCHEMY_KEY:
        return f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"
    return "https://api.mainnet-beta.solana.com"


def solana_ws_rpc() -> str:
    if os.getenv("SOLANA_WS_RPC_URL"):
        return os.getenv("SOLANA_WS_RPC_URL")
    if HELIUS_KEY:
        return f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
    return "wss://api.mainnet-beta.solana.com"

WALLETS_DIR = Path(__file__).parent / "wallets"
EVM_WALLET_FILE = WALLETS_DIR / "evm_wallet.json"

# ---- Verified contract addresses (official Uniswap docs, Sep 2026) ----
# All addresses stored LOWERCASE — checksummed at use time via
# Web3.to_checksum_address() so a checksum typo can never break a swap.
CHAINS = {
    "ethereum": {
        "chain_id": 1,
        "rpcs": [
            "https://ethereum-rpc.publicnode.com",
            "https://eth.drpc.org",
            "https://eth.llamarpc.com",
        ],
        "router": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",   # SwapRouter02
        "quoter": "0x61ffe014ba17989e743c5f6cb21bf9697530b21e",   # QuoterV2
        "weth": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        "usdc": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "symbol": "ETH",
        "explorer": "https://etherscan.io",
    },
    "base": {
        "chain_id": 8453,
        "rpcs": [
            "https://mainnet.base.org",
            "https://base-rpc.publicnode.com",
        ],
        "router": "0x2626664c2603336e57b271c5c0b26f421741e481",   # SwapRouter02
        "quoter": "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",   # QuoterV2
        "weth": "0x4200000000000000000000000000000000000006",
        "usdc": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",     # Circle native USDC
        "symbol": "ETH",
        "explorer": "https://basescan.org",
    },
    # Robinhood Chain — Arbitrum Orbit L2, chain ID 4663, ETH gas token.
    # Verified ON-CHAIN 2026-09-02 via https://rpc.mainnet.chain.robinhood.com:
    #   chain_id=4663, all four contracts have code, WETH identified as the
    #   token paired in 34/40 of the first V2 factory pairs, and a live
    #   QuoterV2 quote returned 0.1 WETH -> 349.27 VIRTUAL (fee 0.05%).
    # Router/Quoter/Factory addresses also listed in official Uniswap docs.
    "robinhood": {
        "chain_id": 4663,
        "rpcs": [
            "https://rpc.mainnet.chain.robinhood.com",
        ],
        "router": "0xcaf681a66d020601342297493863e78c959e5cb2",    # SwapRouter02
        "quoter": "0x33e885ed0ec9bf04ecfb19341582aadcb4c8a9e7",    # QuoterV2
        "weth": "0x0bd7d308f8e1639fab988df18a8011f41eacad73",      # verified on-chain
        "usdc": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",      # USDG (Global Dollar), dec 6
        "symbol": "ETH",
        "explorer": "https://robinhoodchain.blockscout.com",
    },
}


def _get_w3(chain: str):
    """Web3 on the first reachable RPC for this chain — Alchemy first
    (reliability), then public fallbacks."""
    from web3 import Web3
    chain = (chain or "").lower()
    rpcs = ([alchemy_rpc(chain)] if alchemy_rpc(chain) else []) + CHAINS[chain]["rpcs"]
    last_err = None
    for rpc in rpcs:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, {"timeout": 15}))
            if w3.is_connected():
                return w3
        except Exception as e:
            last_err = e
    raise ConnectionError(f"All RPCs for {chain} unreachable (last: {last_err})")

# Pool fee tiers to try, in order (most liquid first for majors)
FEE_TIERS = [500, 3000, 100, 10000]

MIN_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint8"}]},
    {"name": "symbol", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "string"}]},
    {"name": "withdraw", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "wad", "type": "uint256"}], "outputs": []},
]

QUOTER_ABI = [
    {"name": "quoteExactInputSingle", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"components": [
         {"name": "tokenIn", "type": "address"},
         {"name": "tokenOut", "type": "address"},
         {"name": "amountIn", "type": "uint256"},
         {"name": "fee", "type": "uint24"},
         {"name": "sqrtPriceLimitX96", "type": "uint160"},
     ], "type": "tuple"}],
     "outputs": [
         {"name": "amountOut", "type": "uint256"},
         {"name": "sqrtPriceX96After", "type": "uint160"},
         {"name": "initializedTicksCrossed", "type": "uint32"},
         {"name": "gasEstimate", "type": "uint256"},
     ]},
]

ROUTER_ABI = [
    {"name": "exactInputSingle", "type": "function", "stateMutability": "payable",
     "inputs": [{"components": [
         {"name": "tokenIn", "type": "address"},
         {"name": "tokenOut", "type": "address"},
         {"name": "fee", "type": "uint24"},
         {"name": "recipient", "type": "address"},
         {"name": "amountIn", "type": "uint256"},
         {"name": "amountOutMinimum", "type": "uint256"},
         {"name": "sqrtPriceLimitX96", "type": "uint160"},
     ], "type": "tuple"}],
     "outputs": [{"name": "amountOut", "type": "uint256"}]},
]


# ============================================================
# Helpers
# ============================================================

def _load_wallet(chain: str = "ethereum"):
    """Load the per-chain wallet, falling back to the shared EVM wallet.
    Same key works on every EVM chain, so a chain-specific file is optional."""
    for path in (WALLETS_DIR / f"evm_{chain}.json", EVM_WALLET_FILE):
        if path.exists():
            return json.loads(path.read_text())
    return None


def _cs(w3, addr: str):
    """Checksum-convert any stored address (case-safe)."""
    return w3.to_checksum_address(addr)


def _resolve_token(chain: str, token: str, w3) -> dict:
    """Return {address, decimals, symbol, native} for a token symbol/address."""
    cfg = CHAINS[chain]
    t = (token or "").strip()
    native = cfg["symbol"]

    if t.upper() in (native, f"W{native}"):
        if t.upper() == f"W{native}":
            return {"address": _cs(w3, cfg["weth"]), "decimals": 18, "symbol": f"W{native}", "native": False}
        return {"address": _cs(w3, cfg["weth"]), "decimals": 18, "symbol": native, "native": True}
    if t.upper() == "USDC":
        usdc_sym = "USDC" if chain != "robinhood" else "USDC (USDG)"
        return {"address": _cs(w3, cfg["usdc"]), "decimals": 6, "symbol": usdc_sym, "native": False}
    # Symbol lookup from the multichain registry (PEPE, SHIB, VIRTUAL, USDG...)
    try:
        from multichain_tools import KNOWN_EVM_TOKENS
        addr = KNOWN_EVM_TOKENS.get(chain, {}).get(t.upper())
        if addr:
            token_contract = w3.eth.contract(address=_cs(w3, addr), abi=MIN_ABI)
            try:
                dec = token_contract.functions.decimals().call()
                sym = token_contract.functions.symbol().call()
            except Exception:
                dec, sym = 18, t.upper()
            return {"address": _cs(w3, addr), "decimals": dec, "symbol": sym, "native": False}
    except ImportError:
        pass
    if t.startswith("0x") and len(t) == 42:
        # Raw address — fetch decimals/symbol from chain
        token_contract = w3.eth.contract(address=_cs(w3, t), abi=MIN_ABI)
        try:
            dec = token_contract.functions.decimals().call()
            sym = token_contract.functions.symbol().call()
        except Exception:
            dec, sym = 18, t[:8]
        return {"address": _cs(w3, t), "decimals": dec, "symbol": sym, "native": False}
    raise ValueError(f"Unknown token {token!r} on {chain}. Use ETH, USDC, or a 0x contract address.")


def _to_units(amount: float, token: dict) -> int:
    return int(round(amount * (10 ** token["decimals"])))


def _from_units(units: int, token: dict) -> float:
    return units / (10 ** token["decimals"])


def _wait_receipt(w3, tx_hash, timeout=120):
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)


def _send(w3, account, tx):
    tx["from"] = account.address
    tx["nonce"] = w3.eth.get_transaction_count(account.address)
    tx["chainId"] = CHAINS[_current_chain]["chain_id"]
    if "gas" not in tx:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    tx["gasPrice"] = w3.eth.gas_price
    signed = w3.eth.account.sign_transaction(tx, account.key)
    return w3.eth.send_raw_transaction(signed.raw_transaction)


_current_chain = "ethereum"  # set per-call in the public functions


# ============================================================
# Public: real quote (replaces fabricated quotes)
# ============================================================

def real_swap_quote(chain: str, token_in: str, token_out: str, amount: float) -> str:
    """Real Uniswap V3 quote via QuoterV2 eth_call. No signing, no gas."""
    chain = (chain or "").lower()
    if chain not in CHAINS:
        return f"❌ Chain {chain!r} not supported. Use ethereum, base, or robinhood."
    if amount <= 0:
        return "❌ Amount must be positive."

    global _current_chain
    _current_chain = chain
    cfg = CHAINS[chain]

    try:
        w3 = _get_w3(chain)
        tin = _resolve_token(chain, token_in, w3)
        tout = _resolve_token(chain, token_out, w3)
        amount_in = _to_units(amount, tin)

        quoter = w3.eth.contract(address=_cs(w3, cfg["quoter"]), abi=QUOTER_ABI)
        for fee in FEE_TIERS:
            try:
                out = quoter.functions.quoteExactInputSingle((
                    tin["address"], tout["address"], amount_in, fee, 0
                )).call()
                amount_out = out[0]
                break
            except Exception:
                continue
        else:
            return (f"❌ No Uniswap V3 pool found for {tin['symbol']}→{tout['symbol']} "
                    f"on {chain} across fee tiers {FEE_TIERS}.")

        gas = out[3] if len(out) > 3 else 0
        eth_price_gwei = w3.eth.gas_price
        est_fee_eth = (gas * eth_price_gwei) / 1e18
        return (
            f"📋 REAL Uniswap V3 Quote ({cfg['explorer'].split('//')[1]})\n\n"
            f"Pool fee: {fee / 10000}%\n"
            f"In:  {amount:g} {tin['symbol']}\n"
            f"Out: {_from_units(amount_out, tout):.6f} {tout['symbol']}\n"
            f"Est. gas: {gas:,} units (~{est_fee_eth:.6f} {cfg['symbol']})\n\n"
            f"Execute with: swap_evm_token(chain, {tin['symbol']!r}, {tout['symbol']!r}, {amount})"
        )
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Quote failed: {e}"


# ============================================================
# Public: real swap execution
# ============================================================

def real_swap_execute(chain: str, token_in: str, token_out: str, amount: float,
                      slippage_bps: int = 100, usd_amount: float = None) -> str:
    """
    Execute a REAL swap on Uniswap V3 (SwapRouter02).

    Pass EITHER amount (in the token_in's native unit — ETH etc.) OR
    usd_amount (converted at the live rate — a failed conversion refuses
    rather than guesses).

    Flow: quote → approve (exact amount, if needed) → swap → confirm.
    Fails loudly before sending anything if wallet/balance/pool is missing.
    """
    chain = (chain or "").lower()
    if chain not in CHAINS:
        return f"❌ Chain {chain!r} not supported. Use ethereum, base, or robinhood."
    if usd_amount is not None:
        if amount and amount > 0:
            return "❌ Pass either amount or usd_amount, not both."
        try:
            import urllib.request
            _req = urllib.request.Request(
                "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
                headers={"accept": "application/json", "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
            with urllib.request.urlopen(_req, timeout=8) as _r:
                eth_usd = float(json.loads(_r.read())["ethereum"]["usd"])
            if eth_usd <= 0:
                raise ValueError("bad rate")
        except Exception:
            return ("❌ Couldn't fetch the live ETH price to convert your USD "
                    "amount — refusing to guess. State the size in ETH.")
        amount = round(float(usd_amount) / eth_usd, 8)
        if amount <= 0:
            return (f"❌ ${usd_amount} converts to ~0 ETH at the live rate "
                    f"(${eth_usd:,.2f}/ETH). Increase the amount.")
    if amount <= 0:
        return "❌ Amount must be positive."

    global _current_chain
    _current_chain = chain
    cfg = CHAINS[chain]

    wallet = _load_wallet(chain)
    if not wallet or not wallet.get("private_key"):
        return "❌ No EVM wallet. Create one first (new_wallet / create_evm_wallet)."

    try:
        w3 = _get_w3(chain)
        if not w3.is_connected():
            return f"❌ RPC for {chain} is unreachable right now."

        account = w3.eth.account.from_key(wallet["private_key"])
        tin = _resolve_token(chain, token_in, w3)
        tout = _resolve_token(chain, token_out, w3)
        amount_in = _to_units(amount, tin)

        # ---- Balance check ----
        if tin["native"]:
            bal = w3.eth.get_balance(account.address)
            if bal < amount_in:
                return (f"❌ Insufficient {cfg['symbol']} balance: "
                        f"{_from_units(bal, tin):.6f} < {amount:g}.")
        else:
            tc = w3.eth.contract(address=tin["address"], abi=MIN_ABI)
            bal = tc.functions.balanceOf(account.address).call()
            if bal < amount_in:
                return (f"❌ Insufficient {tin['symbol']} balance: "
                        f"{_from_units(bal, tin):.4f} < {amount:g}.")

        # ---- Real quote → min out ----
        quoter = w3.eth.contract(address=_cs(w3, cfg["quoter"]), abi=QUOTER_ABI)
        quoted_out, used_fee = None, None
        for fee in FEE_TIERS:
            try:
                out = quoter.functions.quoteExactInputSingle((
                    tin["address"], tout["address"], amount_in, fee, 0
                )).call()
                quoted_out, used_fee = out[0], fee
                break
            except Exception:
                continue
        if quoted_out is None:
            return (f"❌ No Uniswap V3 pool for {tin['symbol']}→{tout['symbol']} "
                    f"on {chain}. Cannot quote — refusing to swap blind.")

        min_out = int(quoted_out * (10_000 - slippage_bps) / 10_000)
        router = w3.eth.contract(address=_cs(w3, cfg["router"]), abi=ROUTER_ABI)
        recipient = account.address
        txs = []  # (label, tx)

        # ---- Approve (ERC20 input only, exact amount) ----
        if not tin["native"]:
            tc = w3.eth.contract(address=tin["address"], abi=MIN_ABI)
            allowance = tc.functions.allowance(account.address, _cs(w3, cfg["router"])).call()
            if allowance < amount_in:
                txs.append((f"approve {tin['symbol']}", tc.functions.approve(
                    _cs(w3, cfg["router"]), amount_in).build_transaction({})))

        # ---- Swap tx ----
        swap_tx = router.functions.exactInputSingle((
            tin["address"], tout["address"], used_fee, recipient,
            amount_in, min_out, 0,
        )).build_transaction({})
        if tin["native"]:
            swap_tx["value"] = amount_in
        txs.append((f"swap {tin['symbol']}→{tout['symbol']}", swap_tx))

        # ---- Send all txs in order ----
        # Track nonce locally: after broadcasting the approve, a fresh
        # get_transaction_count('latest') can still return the SAME nonce
        # (approve not mined yet) → the swap would collide/replace it.
        nonce = w3.eth.get_transaction_count(account.address, "pending")
        log = []
        for label, base_tx in txs:
            base_tx["from"] = account.address
            base_tx["nonce"] = nonce
            base_tx["chainId"] = cfg["chain_id"]
            if "gas" not in base_tx:
                base_tx["gas"] = int(w3.eth.estimate_gas(base_tx) * 1.2)
            base_tx["gasPrice"] = w3.eth.gas_price
            signed = w3.eth.account.sign_transaction(base_tx, account.key)
            h = w3.eth.send_raw_transaction(signed.raw_transaction)
            nonce += 1
            receipt = _wait_receipt(w3, h)
            ok = receipt.status == 1
            log.append(
                f"{'✅' if ok else '❌'} {label}: {cfg['explorer']}/tx/{h.hex()}"
            )
            if label == "swap":
                try:
                    import trade_journal
                    trade_journal.log_trade(
                        kind="swap", chain=chain, side="buy" if tin["native"] else "sell",
                        token=tout["symbol"] if tin["native"] else tin["symbol"],
                        token_addr=tout.get("address", ""), amount=amount,
                        native=f"{amount:g} {tin['symbol']}", tx=h.hex(),
                        status="confirmed" if ok else "failed",
                        note=f"min_out={_from_units(min_out, tout):.6f} {tout['symbol']}")
                except Exception:
                    pass
            if not ok:
                return "❌ Swap REVERTED on-chain.\n" + "\n".join(log)

        # ---- Unwrap WETH if the user wanted native ETH out ----
        if tout["native"]:
            # output arrived as WETH — withdraw to ETH
            weth = w3.eth.contract(address=cfg["weth"], abi=MIN_ABI)
            weth_bal = weth.functions.balanceOf(account.address).call()
            if weth_bal > 0:
                uw = weth.functions.withdraw(weth_bal).build_transaction({})
                uw["from"] = account.address
                uw["nonce"] = w3.eth.get_transaction_count(account.address, "pending")
                uw["chainId"] = cfg["chain_id"]
                uw["gas"] = int(w3.eth.estimate_gas(uw) * 1.2)
                uw["gasPrice"] = w3.eth.gas_price
                s = w3.eth.account.sign_transaction(uw, account.key)
                h2 = w3.eth.send_raw_transaction(s.raw_transaction)
                _wait_receipt(w3, h2)
                log.append(f"✅ unwrapped WETH→ETH: {cfg['explorer']}/tx/{h2.hex()}")

        return (
            f"✅ REAL swap executed on {chain} (Uniswap V3)\n\n"
            f"In:  {amount:g} {tin['symbol']}\n"
            f"Out: ≥{_from_units(min_out, tout):.6f} {tout['symbol']} "
            f"(slippage {slippage_bps / 100:.2f}%)\n\n"
            + "\n".join(log)
        )
    except Exception as e:
        return _decode_swap_error(e, chain, locals().get("tout", {}), locals().get("tin", {}))


def _decode_swap_error(e: Exception, chain: str, tout: dict = None,
                       tin: dict = None) -> str:
    """Translate raw swap reverts into honest, actionable guidance.
    VERIFIED ON-CHAIN 2026-09-03 (ABCD on robinhood): pools on Robinhood Chain
    are canonical Uniswap V3 (factory 0x1f7d7550… per Uniswap's official
    deployments) and our SwapRouter02 works for them — quote and swap both
    pass, and a real swap through our router exists on-chain. STF is therefore
    a TRANSIENT guard: launchpad tokens (Pools.trade etc.) enable trading
    after listing, and both the router and RPC nodes may serve briefly stale
    state. Guidance: re-check/retry before concluding anything; never
    recommend depositing more funds."""
    s = str(e)
    out_sym = (tout or {}).get("symbol", "token")
    in_sym = (tin or {}).get("symbol", "input")
    if "STF" in s or "SafeTransferFailed" in s or "TRANSFER_FAILED" in s:
        return (f"🚫 {in_sym} → {out_sym} reverted with STF (SafeTransferFailed) "
                f"— a transfer leg was refused. On Robinhood Chain the pools are "
                f"canonical Uniswap V3 and this router DOES trade them (verified "
                f"on-chain), so this is usually TRANSIENT: launchpad tokens open "
                f"trading shortly after listing and RPC state can lag a block or "
                f"two. Re-quote and retry once or twice over a minute before "
                f"concluding anything. If it persists: check the pool's dex + "
                f"trading-enabled status (evm_token_info / DexScreener). Do NOT "
                f"deposit more funds to brute-force this.")
    if "cannot estimate" in s or "gas required exceeds" in s:
        return (f"🚫 Swap cannot execute: a contract in the path reverts during "
                f"estimation. On Robinhood Chain this is usually transient for "
                f"launchpad tokens (trading opens after listing; RPC state may "
                f"lag). Re-quote and retry shortly. If it persists, check the "
                f"token (evm_token_info / DexScreener) for trading-enabled "
                f"status or transfer restrictions before trying anything else.")
    return f"❌ Swap failed: {e}"