"""
LI.Fi integration — keyless DEX aggregator + bridge executor.

LI.Fi (https://li.quest) aggregates bridges and DEXes across EVM chains.
Its public API needs NO API key (verified 2026-09-02: /quote returned real
routes for chain 4663 both same-chain and cross-chain, and /token returned
live prices for Robinhood Chain tokens).

What this gives the bot:
1. execute_bridge  — REAL bridge execution (Relay, Stargate, ACross, ...)
2. lifi_quote      — real route quotes incl. same-chain swaps on chains
                     where our direct Uniswap path has no pool (this is how
                     "0x tokens" / long-tail memecoins become tradable —
                     LI.Fi routes them through whichever DEX has liquidity)
3. lifi_token_price / lifi_tokens — live token prices & market data

Execution model (same trust model as evm_swap.py):
    GET /quote -> validate route -> (approve router if needed) -> sign the
    returned calldata locally with the EVM wallet -> broadcast via the
    chain's public RPC -> wait for receipt.

Only chains with a known public RPC are executable. Everything else
refuses honestly.
"""

import time

import requests

LIFI_API = "https://li.quest/v1"

# Chains we can EXECUTE on: must have a reachable public RPC.
# chain name -> (chain id, rpc endpoints)
EXECUTABLE_CHAINS = {
    "ethereum": (1, ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"]),
    "base": (8453, ["https://mainnet.base.org", "https://base-rpc.publicnode.com"]),
    "robinhood": (4663, ["https://rpc.mainnet.chain.robinhood.com"]),
    "arbitrum": (42161, ["https://arb1.arbitrum.io/rpc"]),
    "optimism": (10, ["https://mainnet.optimism.io"]),
    "polygon": (137, ["https://polygon-rpc.com"]),
}

NATIVE = "0x0000000000000000000000000000000000000000"  # LI.Fi's native token address

ERC20_ABI = [
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
]

TIMEOUT = 25


# ============================================================
# Helpers
# ============================================================

def _wallet(chain: str):
    """EVM wallet for a chain (per-chain file, falling back to shared)."""
    from evm_swap import _load_wallet
    return _load_wallet(chain)


def _w3(chain: str):
    from web3 import Web3
    from evm_swap import alchemy_rpc
    _, rpcs = EXECUTABLE_CHAINS[chain]
    alt = alchemy_rpc(chain)
    rpcs = ([alt] if alt else []) + list(rpcs)
    last = None
    for rpc in rpcs:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, {"timeout": 15}))
            if w3.is_connected():
                return w3
        except Exception as e:
            last = e
    raise ConnectionError(f"All RPCs for {chain} unreachable (last: {last})")


def _as_int(v) -> int:
    """LI.Fi returns numeric fields as int, float-string or 0x-hex — accept all."""
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if s.startswith("0x"):
        return int(s, 16)
    try:
        return int(float(s))
    except ValueError:
        return int(s, 10)


def _resolve_token(chain: str, token: str) -> str:
    """Symbol or address -> address LI.Fi understands (native = 0x000...0)."""
    cfg_t = (token or "").strip()
    if not cfg_t:
        raise ValueError("Empty token")
    if cfg_t.lower() in ("eth", "native"):
        return NATIVE
    if cfg_t.lower() == "weth":
        from evm_swap import CHAINS
        if chain in CHAINS:
            return CHAINS[chain]["weth"]
        return cfg_t  # let LI.Fi resolve
    if cfg_t.upper() == "USDC":
        from evm_swap import CHAINS
        if chain in CHAINS:
            return CHAINS[chain]["usdc"]
    if cfg_t.startswith("0x") and len(cfg_t) == 42:
        return cfg_t.lower()
    # multichain symbol registry (VIRTUAL, USDG, PEPE, ...)
    try:
        from multichain_tools import KNOWN_EVM_TOKENS
        addr = KNOWN_EVM_TOKENS.get(chain, {}).get(cfg_t.upper())
        if addr:
            return addr.lower()
    except ImportError:
        pass
    return cfg_t  # last resort: hand to LI.Fi (it resolves many symbols)


def _explorer(chain: str, tx_hash: str) -> str:
    return {
        "ethereum": f"https://etherscan.io/tx/{tx_hash}",
        "base": f"https://basescan.org/tx/{tx_hash}",
        "robinhood": f"https://robinhoodchain.blockscout.com/tx/{tx_hash}",
        "arbitrum": f"https://arbiscan.io/tx/{tx_hash}",
        "optimism": f"https://optimistic.etherscan.io/tx/{tx_hash}",
        "polygon": f"https://polygonscan.com/tx/{tx_hash}",
    }.get(chain, tx_hash)


def _fmt_route(q: dict) -> str:
    """Human-readable summary of a LI.Fi quote."""
    action = q.get("action", {})
    est = q.get("estimate", {})
    ft = action.get("fromToken", {})
    tt = action.get("toToken", {})
    tool = q.get("toolDetails", {}).get("name", q.get("tool", "?"))
    from_dec = int(ft.get("decimals", 18) or 18)
    to_dec = int(tt.get("decimals", 18) or 18)
    from_amt = _as_int(action.get("fromAmount", 0)) / (10 ** from_dec)
    to_amt = _as_int(est.get("toAmount", 0)) / (10 ** to_dec)
    to_min = _as_int(est.get("toAmountMin", 0)) / (10 ** to_dec)
    usd = est.get("fromAmountUSD")
    secs = est.get("executionDuration", 0)
    lines = [
        "🛣️ REAL LI.Fi route (no API key)",
        "",
        f"Via: {tool}",
        f"In:  {from_amt:g} {ft.get('symbol', '?')}",
        f"Out: {to_amt:,.6f} {tt.get('symbol', '?')}  (min {to_min:,.6f})",
    ]
    if usd:
        try:
            lines.append(f"Value: ~${float(usd):,.2f}")
        except ValueError:
            pass
    if secs:
        lines.append(f"Est. time: ~{int(secs) // 60}m {int(secs) % 60}s")
    if q.get("instruction"):  # cross-chain: user may need to wait for the far side
        lines.append("Cross-chain: destination execution is handled by the bridge.")
    return "\n".join(lines)


# ============================================================
# 1. Quote (real, keyless)
# ============================================================

def lifi_quote(from_chain: str, to_chain: str, from_token: str,
               to_token: str, amount: float) -> str:
    """Real swap/bridge quote from LI.Fi. Works same-chain and cross-chain."""
    from_chain, to_chain = (from_chain or "").lower(), (to_chain or "").lower()
    if from_chain not in EXECUTABLE_CHAINS or to_chain not in EXECUTABLE_CHAINS:
        known = ", ".join(EXECUTABLE_CHAINS)
        return f"❌ Unsupported chain. Executable chains: {known}."
    if amount <= 0:
        return "❌ Amount must be positive."
    try:
        from evm_swap import CHAINS, real_swap_quote
        if from_chain == to_chain and from_chain in CHAINS:
            # Direct Uniswap path is free of aggregator fees — try it first.
            direct = real_swap_quote(from_chain, from_token, to_token, amount)
            if not direct.startswith("❌"):
                return direct
    except Exception:
        pass

    wallet = _wallet(from_chain)
    params = {
        "fromChain": EXECUTABLE_CHAINS[from_chain][0],
        "toChain": EXECUTABLE_CHAINS[to_chain][0],
        "fromToken": _resolve_token(from_chain, from_token),
        "toToken": _resolve_token(to_chain, to_token),
        "fromAmount": str(int(amount * 10 ** 18)),  # refined below for non-18 tokens
        "fromAddress": wallet["address"] if wallet else "0x000000000000000000000000000000000000dEaD",
    }
    # Correct fromAmount decimals using LI.Fi's own token metadata
    try:
        t = requests.get(f"{LIFI_API}/token", params={
            "chain": EXECUTABLE_CHAINS[from_chain][0],
            "token": params["fromToken"]}, timeout=TIMEOUT).json()
        dec = int(t.get("decimals", 18))
        params["fromAmount"] = str(int(amount * 10 ** dec))
    except Exception:
        pass

    try:
        r = requests.get(f"{LIFI_API}/quote", params=params, timeout=TIMEOUT,
                         headers={"accept": "application/json"})
        if r.status_code != 200:
            detail = ""
            try:
                detail = r.json().get("message", "")
            except Exception:
                pass
            return f"❌ LI.Fi quote failed (HTTP {r.status_code}): {detail or r.text[:200]}"
        return _fmt_route(r.json())
    except Exception as e:
        return f"❌ LI.Fi quote failed: {e}"


# ============================================================
# 2. Real bridge / aggregated swap execution
# ============================================================

def execute_bridge(from_chain: str, to_chain: str, from_token: str,
                   to_token: str, amount: float, slippage_bps: int = 100) -> str:
    """
    Execute a REAL route via LI.Fi: signs the returned calldata locally
    and broadcasts on-chain. Cross-chain and same-chain both supported.
    """
    from_chain, to_chain = (from_chain or "").lower(), (to_chain or "").lower()
    if from_chain not in EXECUTABLE_CHAINS or to_chain not in EXECUTABLE_CHAINS:
        known = ", ".join(EXECUTABLE_CHAINS)
        return f"❌ Unsupported chain. Executable chains: {known}."
    if amount <= 0:
        return "❌ Amount must be positive."

    wallet = _wallet(from_chain)
    if not wallet or not wallet.get("private_key"):
        return "❌ No EVM wallet. Create one first (new_wallet / create_evm_wallet)."

    try:
        w3 = _w3(from_chain)
        account = w3.eth.account.from_key(wallet["private_key"])
        from_addr = account.address

        token_in = _resolve_token(from_chain, from_token)
        # decimals for fromAmount
        dec = 18
        if token_in != NATIVE:
            dec = w3.eth.contract(address=w3.to_checksum_address(token_in),
                                  abi=ERC20_ABI).functions.decimals().call()
        params = {
            "fromChain": EXECUTABLE_CHAINS[from_chain][0],
            "toChain": EXECUTABLE_CHAINS[to_chain][0],
            "fromToken": token_in,
            "toToken": _resolve_token(to_chain, to_token),
            "fromAmount": str(int(amount * 10 ** dec)),
            "fromAddress": from_addr,
            "slippage": max(1, min(500, slippage_bps)) / 100,
            "order": "CHEAPEST",
        }
        q = requests.get(f"{LIFI_API}/quote", params=params, timeout=TIMEOUT,
                         headers={"accept": "application/json"})
        if q.status_code != 200:
            try:
                msg = q.json().get("message", q.text[:200])
            except Exception:
                msg = q.text[:200]
            return f"❌ LI.Fi route failed (HTTP {q.status_code}): {msg}"

        route = q.json()
        txr = route.get("transactionRequest") or {}
        if not txr.get("data") or not txr.get("to"):
            return "❌ LI.Fi returned a route without executable transaction data."

        # ---- Sanity checks before signing anything ----
        to_addr = str(txr["to"]).lower()
        to_code = w3.eth.get_code(w3.to_checksum_address(to_addr))
        if not to_code:
            return "❌ Refusing to sign: LI.Fi target address has no contract code."
        tx_chain = _as_int(txr.get("chainId", EXECUTABLE_CHAINS[from_chain][0]))
        if tx_chain != EXECUTABLE_CHAINS[from_chain][0]:
            return f"❌ Refusing to sign: route targets chain {tx_chain}, not {from_chain}."

        est = route.get("estimate", {})
        action = route.get("action", {})
        ft, tt = action.get("fromToken", {}), action.get("toToken", {})

        # ---- Approval if the input token is ERC-20 ----
        log = []
        nonce = w3.eth.get_transaction_count(from_addr)
        if token_in != NATIVE:
            tc = w3.eth.contract(address=w3.to_checksum_address(token_in), abi=ERC20_ABI)
            need = _as_int(action.get("fromAmount", params["fromAmount"]))
            if tc.functions.allowance(from_addr, w3.to_checksum_address(to_addr)).call() < need:
                ap = tc.functions.approve(w3.to_checksum_address(to_addr), need).build_transaction({})
                ap.update({"from": from_addr, "nonce": nonce,
                           "chainId": EXECUTABLE_CHAINS[from_chain][0],
                           "gasPrice": w3.eth.gas_price})
                ap["gas"] = int(w3.eth.estimate_gas(ap) * 1.2)
                signed = w3.eth.account.sign_transaction(ap, account.key)
                h = w3.eth.send_raw_transaction(signed.raw_transaction)
                w3.eth.wait_for_transaction_receipt(h, timeout=180)
                log.append(f"✅ approve: {_explorer(from_chain, h.hex())}")
                nonce += 1

        # ---- The route transaction itself ----
        tx = {
            "from": from_addr,
            "to": w3.to_checksum_address(to_addr),
            "data": txr["data"],
            "nonce": nonce,
            "chainId": EXECUTABLE_CHAINS[from_chain][0],
            "gasPrice": _as_int(txr.get("gasPrice", 0)) or w3.eth.gas_price,
        }
        val = _as_int(txr.get("value", 0))
        if val:
            tx["value"] = val
        tx["gas"] = _as_int(txr.get("gasLimit", 0)) or int(w3.eth.estimate_gas(tx) * 1.3)
        signed = w3.eth.account.sign_transaction(tx, account.key)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=300)
        ok = receipt.status == 1
        log.append(f"{'✅' if ok else '❌'} route tx: {_explorer(from_chain, h.hex())}")
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="bridge", chain=from_chain, token=f"→ {to_chain}",
                amount=_as_int(est.get("toAmount", 0)) / (10 ** int(tt.get("decimals", 18) or 18)),
                native=f"{params.get('fromAmount', '?')} from {from_chain}", tx=h.hex(),
                status="confirmed" if ok else "failed", note=f"bridge {from_chain}→{to_chain}")
        except Exception:
            pass
        if not ok:
            return "❌ Route transaction REVERTED on-chain.\n" + "\n".join(log)

        to_amt = _as_int(est.get("toAmount", 0)) / (10 ** int(tt.get("decimals", 18) or 18))
        to_min = _as_int(est.get("toAmountMin", 0)) / (10 ** int(tt.get("decimals", 18) or 18))
        same = from_chain == to_chain
        head = "✅ REAL swap executed via LI.Fi" if same else f"✅ REAL bridge sent {from_chain} → {to_chain} via LI.Fi"
        return (
            f"{head}\n\n"
            f"Via: {route.get('toolDetails', {}).get('name', route.get('tool'))}\n"
            f"In:  {amount:g} {ft.get('symbol', '?')}\n"
            f"Out: ~{to_amt:,.6f} {tt.get('symbol', '?')} (min {to_min:,.6f})\n\n"
            + "\n".join(log)
        )
    except Exception as e:
        return f"❌ Bridge/swap execution failed: {e}"


# ============================================================
# 3. Token prices / market data (bonus — keyless)
# ============================================================

def lifi_token_price(chain: str, token: str) -> str:
    """Live price + market data for a token on any LI.Fi-supported chain."""
    chain = (chain or "").lower()
    if chain not in EXECUTABLE_CHAINS:
        return f"❌ Unknown chain {chain!r}. Supported: {', '.join(EXECUTABLE_CHAINS)}"
    try:
        r = requests.get(f"{LIFI_API}/token", params={
            "chain": EXECUTABLE_CHAINS[chain][0],
            "token": _resolve_token(chain, token)}, timeout=TIMEOUT)
        if r.status_code != 200:
            return f"❌ Token not found on {chain} (HTTP {r.status_code})."
        t = r.json()
        price = t.get("priceUSD")
        out = [f"💰 {t.get('symbol', '?')} ({t.get('name', '?')}) on {chain}",
               f"Address: `{t.get('address', '?')}`"]
        if price:
            out.append(f"Price: ${float(price):,.8f}")
        if t.get("marketCapUSD"):
            out.append(f"Market cap: ${t['marketCapUSD']:,.0f}")
        if t.get("volumeUSD24H"):
            out.append(f"24h volume: ${t['volumeUSD24H']:,.0f}")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Price lookup failed: {e}"


def lifi_tokens(chain: str) -> str:
    """Top tokens tradable on a chain (per LI.Fi's index)."""
    chain = (chain or "").lower()
    if chain not in EXECUTABLE_CHAINS:
        return f"❌ Unknown chain {chain!r}. Supported: {', '.join(EXECUTABLE_CHAINS)}"
    try:
        r = requests.get(f"{LIFI_API}/tokens", params={
            "chain": EXECUTABLE_CHAINS[chain][0]}, timeout=TIMEOUT + 10,
            headers={"accept": "application/json"})
        if r.status_code != 200:
            return f"❌ LI.Fi token list failed (HTTP {r.status_code})."
        data = r.json().get("tokens", {})
        tokens = data.get(str(EXECUTABLE_CHAINS[chain][0]),
                          next(iter(data.values()), []) if isinstance(data, dict) else data)
        tokens = tokens or []
        priced = [t for t in tokens if t.get("priceUSD")]
        priced.sort(key=lambda t: float(t.get("priceUSD") or 0), reverse=True)
        if not priced:
            return f"No indexed tokens on {chain}."
        lines = [f"🪙 Top tokens on {chain} (LI.Fi index):"]
        for t in priced[:20]:
            p = float(t["priceUSD"])
            lines.append(f"  {t.get('symbol', '?'):12} ${p:,.6f}" if p < 1
                         else f"  {t.get('symbol', '?'):12} ${p:,.2f}")
        lines.append(f"\n{len(tokens)} tokens indexed. Quote any with lifi_quote.")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Token list failed: {e}"


# ============================================================
# Tool definitions + dispatch (registry pattern)
# ============================================================

LIFI_TOOLS = [
    {"type": "function", "function": {"name": "execute_bridge", "description": "Execute a REAL bridge or aggregated swap via LI.Fi (signs locally, broadcasts on-chain). Works same-chain (any DEX liquidity — good for memecoins with no Uniswap V3 pool) and cross-chain. No API key needed.", "parameters": {"type": "object", "properties": {"from_chain": {"type": "string", "enum": list(EXECUTABLE_CHAINS)}, "to_chain": {"type": "string", "enum": list(EXECUTABLE_CHAINS)}, "from_token": {"type": "string", "description": "Token symbol or 0x address (native = ETH)"}, "to_token": {"type": "string", "description": "Token symbol or 0x address"}, "amount": {"type": "number"}, "slippage_bps": {"type": "integer", "description": "Slippage in basis points (default 100 = 1%)"}, }, "required": ["from_chain", "to_chain", "from_token", "to_token", "amount"]}}},
    {"type": "function", "function": {"name": "lifi_quote", "description": "Get a REAL route quote via LI.Fi (same-chain swap or cross-chain bridge) without executing. No API key needed.", "parameters": {"type": "object", "properties": {"from_chain": {"type": "string"}, "to_chain": {"type": "string"}, "from_token": {"type": "string"}, "to_token": {"type": "string"}, "amount": {"type": "number"}}, "required": ["from_chain", "to_chain", "from_token", "to_token", "amount"]}}},
    {"type": "function", "function": {"name": "lifi_token_price", "description": "Live price, market cap and 24h volume for a token on any LI.Fi chain (incl. Robinhood Chain memecoins).", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "token": {"type": "string", "description": "Symbol or 0x address"}}, "required": ["chain", "token"]}}},
    {"type": "function", "function": {"name": "lifi_tokens", "description": "List top tradable tokens with live prices on a chain.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}}, "required": ["chain"]}}},
]

LIFI_TOOL_MAP = {
    "execute_bridge": lambda a: execute_bridge(
        a["from_chain"], a["to_chain"], a["from_token"], a["to_token"],
        float(a["amount"]), int(a.get("slippage_bps", 100))),
    "lifi_quote": lambda a: lifi_quote(
        a["from_chain"], a["to_chain"], a["from_token"], a["to_token"], float(a["amount"])),
    "lifi_token_price": lambda a: lifi_token_price(a["chain"], a["token"]),
    "lifi_tokens": lambda a: lifi_tokens(a["chain"]),
}
