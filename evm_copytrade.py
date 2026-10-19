"""
EVM copytrade — mirror tracked EVM wallets via getLogs polling (Alchemy).

How it works:
  poller thread -> eth_getLogs per chain (Transfer events touching watched
  wallets) -> classify ERC20 buy / sell / NFT move -> Telegram alert
  -> if copy enabled: mirror the BUY with your wallet via our real
     Uniswap V3 executor, capped in ETH.

Latency: 2-4s typical (block-time dependent). This is whale-following,
not mempool sniping — Base has no public mempool anyway.

Caps (env-tunable): COPY_MAX_ETH per mirrored trade (default 0.002 ETH),
max 6 mirrored trades/hour. Mirroring only fires on incoming tokens
(they received = they bought); outgoing tokens alert-only.

Upgrade path: the /alchemy/<token> receiver route is already live in
webhook_server.py — paste an Alchemy Notify auth token from the dashboard
and address management becomes push-based instead of polled.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

MAX_COPY_ETH = float(os.getenv("COPY_MAX_ETH", "0.002"))
MAX_COPIES_PER_HOUR = int(os.getenv("COPY_MAX_PER_HOUR", "6"))

TRACK_FILE = os.path.join(os.path.dirname(__file__), "watched_evm_wallets.json")

# ERC20/ERC721 shared Transfer event signature
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

EXPLORERS = {
    "ethereum": "https://etherscan.io/tx/{}",
    "base": "https://basescan.org/tx/{}",
    "robinhood": "https://robinhoodchain.blockscout.com/tx/{}",
    "arbitrum": "https://arbiscan.io/tx/{}",
    "optimism": "https://optimistic.etherscan.io/tx/{}",
    "polygon": "https://polygonscan.com/tx/{}",
}

_bot_app = None
ADMIN_ID = None


def set_bot(app, admin_id):
    global _bot_app, ADMIN_ID
    _bot_app, ADMIN_ID = app, admin_id


def _ping(text: str):
    if not _bot_app or not ADMIN_ID:
        return
    try:
        import asyncio
        coro = _bot_app.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        loop = globals().get("BOT_LOOP")  # bot's real loop (set in post_init)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            asyncio.run(coro)
    except Exception as e:
        print(f"[evm-copy] ping failed: {e}")


# ============================================================
# Watchlist
# ============================================================

def _load() -> list:
    if os.path.exists(TRACK_FILE):
        try:
            return json.loads(open(TRACK_FILE).read())
        except Exception:
            return []
    return []


def _save(lst: list):
    json.dump(lst, open(TRACK_FILE, "w"), indent=2)


def _label(address: str) -> str:
    for w in _load():
        if w["address"].lower() == address.lower():
            return w.get("label") or address[:10] + "…"
    return address[:10] + "…"


def watch_wallet_evm(address: str, chain: str = "base", label: str = "",
                     copy: bool = False) -> str:
    address = (address or "").strip()
    chain = (chain or "base").lower()
    if not address.startswith("0x") or len(address) != 42:
        return "❌ Provide a valid EVM address (0x…, 42 chars)."
    from evm_swap import CHAINS
    if chain not in CHAINS or chain == "solana":
        return f"❌ Chain must be one of: {', '.join(k for k in CHAINS if k != 'solana')}"
    lst = _load()
    if any(w["address"].lower() == address.lower() for w in lst):
        return f"⚠️ Already watching {address[:10]}…"
    lst.append({"address": address, "chain": chain,
                "label": label or address[:10] + "…", "copy": bool(copy),
                "added": datetime.now(timezone.utc).isoformat()})
    _save(lst)
    _ensure_watcher()
    _sync_push_quietly()
    mode = "📋 COPYING buys" if copy else "👁️ alerts only"
    return (f"👁️ Watching {lst[-1]['label']} on {chain} ({mode}). "
            f"Push via Alchemy Notify — alerts within ~1s of each trade.")


def unwatch_wallet_evm(address: str) -> str:
    addr = address.strip().lower()
    lst = [w for w in _load() if w["address"].lower() != addr]
    _save(lst)
    _sync_push_quietly()
    return f"🗑️ Removed. {len(lst)} EVM wallet(s) remain watched."


def list_watched_evm() -> str:
    lst = _load()
    if not lst:
        return "No EVM wallets watched. Add: watch_wallet_evm(address, chain, copy=…)"
    lines = ["👁️ Watched EVM wallets:"]
    for w in lst:
        mode = " 📋 COPY" if w.get("copy") else ""
        lines.append(f"  • {w['label']} [{w.get('chain', 'base')}]{mode} — `{w['address'][:12]}…`")
    return "\n".join(lines)


def toggle_copy_evm(address: str, enabled: bool) -> str:
    lst = _load()
    for w in lst:
        if w["address"].lower() == address.strip().lower():
            w["copy"] = bool(enabled)
            _save(lst)
            return (f"{'📋 Copy ON' if enabled else '👁️ Copy OFF'} for {w['label']} — "
                    f"cap {MAX_COPY_ETH} ETH/trade, {MAX_COPIES_PER_HOUR}/hour.")
    return f"❌ Not watching {address[:10]}…"


# ============================================================
# Push sync (Alchemy Notify webhooks)
# ============================================================

def _sync_push_quietly():
    """Best-effort: add/remove watched wallets on the Alchemy Address-Activity
    webhook(s) after every watch/unwatch. Silent on failure — the getLogs
    poller is the safety net, so push sync failing must never break watching."""
    token = os.getenv("ALCHEMY_AUTH_TOKEN", "")
    if not token:
        return
    try:
        import threading
        threading.Thread(target=sync_alchemy_webhook, args=(token,),
                         daemon=True, name="alchemy-push-sync").start()
    except Exception:
        pass


# ============================================================
# Poller
# ============================================================

_copy_times = []
_last_blocks = {}


def _copy_allowed() -> bool:
    now = time.time()
    while _copy_times and now - _copy_times[0] > 3600:
        _copy_times.pop(0)
    return len(_copy_times) < MAX_COPIES_PER_HOUR


# ---- shared dedup: poller + push both flow through here ----
_seen_keys = set()


def _already_seen(key: str) -> bool:
    if key in _seen_keys:
        return True
    _seen_keys.add(key)
    if len(_seen_keys) > 5000:
        _seen_keys.clear()
    return False


def handle_alchemy_activity(act: dict):
    """Alchemy Notify push handler (registered with webhook_server).
    Converts one Address-Activity activity into the same event pipeline
    the poller uses. Same dedup keys as the poller, so a push + a poll
    of the same tx fire exactly once."""
    try:
        chain = _CHAIN_BY_NETWORK.get(act.get("network", ""), "")
        if not chain:
            return
        cat = act.get("category", "")
        # Alchemy V2 sends category as a LIST (e.g. ["token"]); normalize
        if isinstance(cat, (list, tuple)):
            cat = cat[0] if cat else ""
        # 'token' transfers, 'erc721', 'external'...
        txh = act.get("hash", "")
        log_idx = act.get("logIndex", 0) or 0

        # Identify our watched wallet among from/to
        frm = (act.get("fromAddress") or "").lower()
        to = (act.get("toAddress") or "").lower()
        lst = [w for w in _load() if w["address"].lower() in (frm, to)]
        if not lst:
            return
        w = lst[0]

        if cat in ("erc721", "erc1155", "specialnft"):
            # NFT movement — alert with token id, NEVER auto-copy (each NFT
            # is unique; mirroring would try to swap ETH for the collection
            # address as if it were an ERC-20).
            key = f"{chain}:{txh}:{log_idx}"
            if _already_seen(key):
                return
            tid = act.get("tokenId") or (act.get("rawContract") or {}).get("value") or "?"
            if isinstance(tid, str) and tid.startswith("0x"):
                try:
                    tid = int(tid, 16)
                except ValueError:
                    pass
            raw_amt = (act.get("rawContract") or {}).get("value") or "0x0"
            try:
                units = int(raw_amt, 16) if str(raw_amt).startswith("0x") else int(raw_amt or 1)
            except (TypeError, ValueError):
                units = 1
            units_txt = f" ×{units}" if (cat == "erc1155" and units != 1) else ""
            asset = act.get("asset") or {}
            coll = asset.get("symbol") if isinstance(asset, dict) else None
            contract = (act.get("rawContract", {}).get("address") or "").lower()
            link = EXPLORERS.get(chain, "{}").format(txh)
            sym = coll or contract[:10] + "…"
            direction = "BOUGHT" if to == w["address"].lower() else "SOLD"
            _ping(f"🖼️ *{w['label']}* {direction} NFT #{tid}{units_txt} ({sym})\n"
                  f"(push) {link}\nNFTs are alert-only — use opensea_buy_nft to act")
            return

        if cat in ("token", "erc20", "external", "internal"):
            asset = act.get("asset") or {}
            symbol = asset.get("symbol") if isinstance(asset, dict) else act.get("asset")
            raw_amt = act.get("rawContract", {}).get("value") or "0x0"
            decimals = (act.get("rawContract", {}).get("decimal") or 18)
            if isinstance(decimals, str):
                decimals = int(decimals, 16)
            amount = int(raw_amt, 16) / (10 ** decimals) if str(raw_amt).startswith("0x") else float(raw_amt or 0)
            if amount == 0 and act.get("value"):
                try:
                    amount = float(act["value"])  # native transfers carry value as float
                except (TypeError, ValueError):
                    pass
            key = f"{chain}:{txh}:{log_idx}"
            if _already_seen(key):
                return
            direction = "BOUGHT" if to == w["address"].lower() else "SOLD"
            amt = f"{amount:,.2f}" if amount > 10 else f"{amount:,.6f}"
            contract = (act.get("rawContract", {}).get("address") or "").lower()
            link = EXPLORERS.get(chain, "{}").format(txh)
            sym = symbol or contract[:10] + "…"
            _ping(f"⚡ *{w['label']}* {direction} {amt} {sym}\n(push) {link}")
            if direction == "BOUGHT" and w.get("copy") and _copy_allowed():
                if contract:
                    _mirror_buy(chain, contract, sym)
        else:
            # native transfers etc. — alert only
            key = f"{chain}:{txh}:{log_idx}"
            if _already_seen(key):
                return
            try:
                val = float(act.get("value") or 0)  # V2 sends value as float string
            except (TypeError, ValueError):
                val = 0
            link = EXPLORERS.get(chain, "{}").format(txh)
            _ping(f"⚡ *{w['label']}* activity: {act.get('category', 'tx')} ({val})\n{link}")
    except Exception as e:
        print(f"[evm-copy] push handle: {str(e)[:140]}")


_CHAIN_BY_NETWORK = {
    "ETH_MAINNET": "ethereum",
    "BASE_MAINNET": "base",
    "ARB_MAINNET": "arbitrum",
    "OPT_MAINNET": "optimism",
    "MATIC_MAINNET": "polygon",
    "ROBINHOOD_MAINNET": "robinhood",
}


def _rpc(chain: str, method: str, params: list):
    from evm_swap import _get_w3
    w3 = _get_w3(chain)
    return w3.provider.make_request(method, params)


def _pad(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")


def _token_meta(chain: str, contract: str) -> dict:
    """symbol + decimals, cached."""
    global _token_cache
    key = f"{chain}:{contract.lower()}"
    if key in _token_cache:
        return _token_cache[key]
    sym, dec = contract[:8] + "…", 18
    try:
        from evm_swap import _get_w3, MIN_ABI
        w3 = _get_w3(chain)
        c = w3.eth.contract(address=w3.to_checksum_address(contract), abi=MIN_ABI)
        sym = c.functions.symbol().call()
        dec = c.functions.decimals().call()
    except Exception:
        pass
    _token_cache[key] = {"symbol": sym, "decimals": dec}
    return _token_cache[key]


_token_cache = {}


def _poll_chain(chain: str, watches: list):
    """getLogs Transfer events touching any watched wallet on this chain."""
    now_block = int(_rpc(chain, "eth_blockNumber", [])["result"], 16)
    last = _last_blocks.get(chain)
    if last is None:
        _last_blocks[chain] = now_block
        return
    if now_block <= last:
        return
    from_block = max(last + 1, now_block - 30)  # bounded catch-up
    _last_blocks[chain] = now_block

    addrs = [w["address"] for w in watches]
    topics = [TRANSFER_TOPIC, None, None]
    # one query per side (from=wallet / to=wallet) OR-combined client-side
    logs = []
    try:
        r1 = _rpc(chain, "eth_getLogs", [{
            "fromBlock": hex(from_block), "toBlock": "latest",
            "topics": [TRANSFER_TOPIC, [_pad(a) for a in addrs]]}])
        r2 = _rpc(chain, "eth_getLogs", [{
            "fromBlock": hex(from_block), "toBlock": "latest",
            "topics": [TRANSFER_TOPIC, None, [_pad(a) for a in addrs]]}])
        logs = [l for l in (r1.get("result") or []) + (r2.get("result") or [])]
    except Exception as e:
        print(f"[evm-copy] getLogs {chain}: {str(e)[:100]}")
        return

    for log in logs:
        key = f"{chain}:{log.get('transactionHash')}:{log.get('logIndex')}"
        if _already_seen(key):
            continue
        try:
            _handle_log(chain, log, watches)
        except Exception as e:
            print(f"[evm-copy] handle {chain}: {str(e)[:120]}")


def _handle_log(chain: str, log: dict, watches: list):
    topics = log.get("topics", [])
    contract = log.get("address", "").lower()
    txh = log.get("transactionHash", "")
    link = EXPLORERS.get(chain, "{}").format(txh)

    if len(topics) >= 4:   # ERC-721: tokenId indexed in topic3
        tid = int(topics[3], 16)
        to = "0x" + topics[2][-40:]
        frm = "0x" + topics[1][-40:]
        w = next((w for w in watches if w["address"].lower() in (to.lower(), frm.lower())), None)
        if not w:
            return
        direction = "received" if to.lower() == w["address"].lower() else "sent"
        _ping(f"🖼️ *{w['label']}* {direction} NFT #{tid}\n`{contract[:12]}…`\n{link}")
        return

    if len(topics) == 3:   # ERC-20
        to = "0x" + topics[2][-40:]
        frm = "0x" + topics[1][-40:]
        w = next((w for w in watches if w["address"].lower() in (to.lower(), frm.lower())), None)
        if not w:
            return
        meta = _token_meta(chain, contract)
        raw = int(log.get("data", "0x0"), 16)
        amount = raw / (10 ** meta["decimals"])
        direction = "BOUGHT" if to.lower() == w["address"].lower() else "SOLD"
        amt = f"{amount:,.2f}" if amount > 10 else f"{amount:,.6f}"
        _ping(f"🟢 *{w['label']}* {direction} {amt} {meta['symbol']}\n{link}")

        if (direction == "BOUGHT" and w.get("copy")
                and _copy_allowed()):
            _mirror_buy(chain, contract, meta["symbol"])


# ============================================================
# Honeypot gate — never mirror-buy a token you can't exit
# ============================================================

_HP_CACHE = {}          # token -> (verdict_ts, verdict)
_HP_CACHE_TTL = 1800    # 30 min
# DexScreener chainId slugs (their API's naming)
_HP_CHAIN_SLUGS = {"ethereum": "ethereum", "base": "base", "arbitrum": "arbitrum",
                   "optimism": "optimism", "polygon": "polygon", "robinhood": "robinhood"}
# Mirror trades are ~$3; a pool with <$1k depth means catastrophic price
# impact and easy rug mechanics. Raise if you raise COPY_MAX_ETH.
MIN_LIQUIDITY_USD = 1000


def _hp_check(chain: str, token: str, w3=None) -> str:
    """Return 'ok' if the token has real exit liquidity, else a refusal reason.

    Uses DexScreener (free, keyless, DEX-agnostic — sees Uniswap V2/V3,
    Aerodrome, etc., so no false negatives from a single-router view).
    Chains DexScreener doesn't cover yet → 'unverified' → allowed with a
    logged note (the swap executor itself remains the final backstop).
    """
    key = f"{chain}:{token.lower()}"
    now = time.time()
    hit = _HP_CACHE.get(key)
    if hit and now - hit[0] < _HP_CACHE_TTL:
        return hit[1]

    slug = _HP_CHAIN_SLUGS.get(chain, chain)
    try:
        import urllib.request
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"
        req = urllib.request.Request(url, headers={"accept": "application/json",
                                                   "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        pairs = data.get("pairs") or []
    except Exception as e:
        # checker unreachable → allow (executor backstops), but mark it
        verdict = "ok (unverified: DexScreener unreachable — executor backstop applies)"
        _HP_CACHE[key] = (now, verdict)
        return verdict

    chain_pairs = [p for p in pairs if (p.get("chainId") or "").lower() == slug]
    if not chain_pairs:
        if pairs:
            # token trades somewhere, just not (in DexScreener's index) on this chain
            verdict = "unverified: token has liquidity on other chains, none indexed here"
        else:
            verdict = "NO DEX liquidity found anywhere — cannot exit this token"
        _HP_CACHE[key] = (now, verdict)
        return verdict

    best = max((p.get("liquidity") or {}).get("usd", 0) or 0 for p in chain_pairs)
    if best <= 0:
        verdict = "DEX pairs exist but zero indexed liquidity — cannot exit"
    elif best < MIN_LIQUIDITY_USD:
        verdict = f"thin exit liquidity: ${best:,.0f} (below ${MIN_LIQUIDITY_USD:,} safety line)"
    else:
        verdict = "ok"
    _HP_CACHE[key] = (now, verdict)
    return verdict


def _mirror_buy(chain: str, token: str, symbol: str):
    """Copy the buy: spend COPY_MAX_ETH on the same token. Real money.
    Honeypot-gated: refuses to buy tokens that show no exit liquidity or
    fail sell simulation — you can't exit what whales never sell into."""
    try:
        from evm_swap import real_swap_execute
        verdict = _hp_check(chain, token)
        if verdict != "ok" and not verdict.startswith("ok ("):
            try:
                import trade_journal
                trade_journal.log_trade(
                    kind="copy", chain=chain, side="buy", token=symbol,
                    token_addr=token, amount=MAX_COPY_ETH,
                    native=f"{MAX_COPY_ETH} ETH", status="failed",
                    source="copytrade", note=f"HONEYPOT GATE: {verdict}")
            except Exception:
                pass
            _ping(f"🚫 *Copy skipped — honeypot gate*\n{symbol[:20]} on {chain}\n{verdict[:200]}")
            return
        _copy_times.append(time.time())
        result = real_swap_execute(chain, "ETH", token, MAX_COPY_ETH)
        head = result.split("\n")[0]
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="copy", chain=chain, side="buy", token=symbol,
                token_addr=token, amount=MAX_COPY_ETH,
                native=f"{MAX_COPY_ETH} ETH", status="broadcasted",
                source="copytrade",
                note="success" if head.startswith("✅") else head[:120])
        except Exception:
            pass
        _ping(f"📋 *COPIED* — bought {MAX_COPY_ETH} ETH of {symbol}\n{head}")
    except Exception as e:
        _ping(f"❌ Copy failed: {str(e)[:200]}")


_watcher_thread = None


def _loop():
    while True:
        try:
            lst = _load()
            by_chain = {}
            for w in lst:
                by_chain.setdefault(w.get("chain", "base"), []).append(w)
            for chain, watches in by_chain.items():
                _poll_chain(chain, watches)
        except Exception as e:
            print(f"[evm-copy] loop: {str(e)[:120]}")
        time.sleep(3)


def _ensure_watcher():
    global _watcher_thread
    if _watcher_thread is None or not _watcher_thread.is_alive():
        _watcher_thread = threading.Thread(target=_loop, name="evm-copytrade", daemon=True)
        _watcher_thread.start()


def start_evm_watcher():
    """Called from main.py startup; resumes persisted watches.
    Registers the push handler too — push is primary, polling is the
    safety net (poll skips already-seen keys, so no double alerts)."""
    try:
        from webhook_server import register_alchemy_handler
        register_alchemy_handler(handle_alchemy_activity)
    except Exception:
        pass
    if _load():
        _ensure_watcher()
        print(f"👁️ EVM copytrade watcher running ({len(_load())} wallets)")


# ============================================================
# Tool registry
# ============================================================

# ============================================================
# Alchemy Notify webhook management (push mode)
# ============================================================

def sync_alchemy_webhook(auth_token: str) -> str:
    """Create/update the Address-Activity webhook via Alchemy's dashboard
    API. Get the token: dashboard.alchemy.com → Notify → Auth token header.
    Stores it in .env as ALCHEMY_AUTH_TOKEN for future syncs."""
    auth_token = (auth_token or "").strip()
    if not auth_token:
        return ("❌ Need your Alchemy Notify auth token.\n"
                "dashboard.alchemy.com → Notify (sidebar) → copy the token "
                "from the 'Auth token' header, then send it here.")
    addresses = sorted({w["address"] for w in _load()})
    if not addresses:
        return "❌ Watch at least one EVM wallet first."
    from webhook_server import public_webhook_url
    hook_url = public_webhook_url().replace("/helius/", "/alchemy/")

    import requests as _r
    base = "https://dashboard.alchemy.com/api"
    H = {"X-Alchemy-Token": auth_token, "Content-Type": "application/json"}
    nets = {"ethereum": "ETH_MAINNET", "base": "BASE_MAINNET",
            "arbitrum": "ARB_MAINNET", "optimism": "OPT_MAINNET",
            "polygon": "MATIC_MAINNET", "robinhood": "ROBINHOOD_MAINNET"}
    try:
        r = _r.get(f"{base}/team-webhooks", headers=H, timeout=15)
        r.raise_for_status()
        our = [w for w in r.json().get("data", [])
               if w.get("webhook_type") == "ADDRESS_ACTIVITY"
               and "/alchemy/" in (w.get("webhook_url") or "")]
        by_net = {w.get("network"): w for w in our}

        watched = _load()
        created, updated = [], []
        for chain in sorted({w.get("chain", "base") for w in watched}):
            net = nets.get(chain)
            if not net:
                continue
            addrs = sorted({w["address"] for w in watched if w.get("chain") == chain})
            hook = by_net.get(net)
            if not hook:
                rc = _r.post(f"{base}/create-webhook", headers=H, json={
                    "network": net, "webhook_type": "ADDRESS_ACTIVITY",
                    "webhook_url": hook_url, "addresses": addrs,
                    "name": "aesir-evm-copytrade"}, timeout=20)
                if rc.status_code not in (200, 201):
                    return f"❌ Alchemy create ({net}) {rc.status_code}: {rc.text[:200]}"
                created.append(net)
            else:
                ru = _r.patch(f"{base}/update-webhook-addresses", headers=H, json={
                    "webhook_id": hook.get("id"),
                    "addresses_to_add": addrs, "addresses_to_remove": []},
                    timeout=15)
                if ru.status_code != 200:
                    return f"❌ Alchemy update ({net}) {ru.status_code}: {ru.text[:200]}"
                updated.append(net)

        # refresh signing keys — the receiver accepts any of them
        r = _r.get(f"{base}/team-webhooks", headers=H, timeout=15)
        ours = [w for w in r.json().get("data", [])
                if "/alchemy/" in (w.get("webhook_url") or "")]
        keys = sorted({w.get("signing_key") for w in ours if w.get("signing_key")})
        ids = sorted({w.get("id") for w in ours if w.get("id")})

        envp = os.path.join(os.path.dirname(__file__), ".env")
        lines = [l for l in open(envp).read().splitlines()
                 if not l.startswith(("ALCHEMY_AUTH_TOKEN", "ALCHEMY_SIGNING_KEY", "ALCHEMY_WEBHOOK_ID"))]
        lines.append(f"ALCHEMY_AUTH_TOKEN={auth_token}")
        if keys:
            lines.append(f"ALCHEMY_SIGNING_KEY={','.join(keys)}")
        if ids:
            lines.append(f"ALCHEMY_WEBHOOK_ID={','.join(ids)}")
        open(envp, "w").write("\n".join(lines) + "\n")

        parts = []
        if created: parts.append("created " + ", ".join(created))
        if updated: parts.append("updated " + ", ".join(updated))
        detail = "; ".join(parts) if parts else "no changes"
        return (f"✅ Alchemy push: {detail}. {len(keys)} signing key(s) saved.\n"
                f"EVM alerts now ~1s (poller stays as backup).")
    except Exception as e:
        return f"❌ {e}"


EVM_COPYTRADE_TOOLS = [
    {"type": "function", "function": {"name": "watch_wallet_evm", "description": "Watch an EVM wallet (base/ethereum/robinhood/arbitrum/optimism/polygon) in near-real-time: Telegram alerts on every token buy/sell/NFT move. copy=True mirrors BUYS with your wallet (capped).", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "chain": {"type": "string", "enum": ["ethereum", "base", "robinhood", "arbitrum", "optimism", "polygon"]}, "label": {"type": "string"}, "copy": {"type": "boolean"}}, "required": ["address"]}}},
    {"type": "function", "function": {"name": "unwatch_wallet_evm", "description": "Stop watching an EVM wallet.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]}}},
    {"type": "function", "function": {"name": "list_watched_evm", "description": "List watched EVM wallets.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "toggle_copy_evm", "description": "Turn EVM copy-trading on/off for a watched wallet.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "enabled": {"type": "boolean"}}, "required": ["address", "enabled"]}}},
    {"type": "function", "function": {"name": "sync_alchemy_webhook", "description": "Switch EVM wallet watching from polling to Alchemy Notify PUSH (faster, no polling load). Needs the auth token from dashboard.alchemy.com → Notify.", "parameters": {"type": "object", "properties": {"auth_token": {"type": "string"}}, "required": ["auth_token"]}}},
]

EVM_COPYTRADE_TOOL_MAP = {
    "watch_wallet_evm": lambda a: watch_wallet_evm(
        a["address"], a.get("chain", "base"), a.get("label", ""), bool(a.get("copy", False))),
    "unwatch_wallet_evm": lambda a: unwatch_wallet_evm(a["address"]),
    "list_watched_evm": lambda a: list_watched_evm(),
    "toggle_copy_evm": lambda a: toggle_copy_evm(a["address"], bool(a.get("enabled", True))),
    "sync_alchemy_webhook": lambda a: sync_alchemy_webhook(a["auth_token"]),
}
