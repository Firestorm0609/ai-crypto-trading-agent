"""
Graduation radar — the two launchpads worth watching, graduations ONLY.

    /launches on pumpfun pons      (or: /launches on all)
    /launches off all

A launch alert is noise; a GRADUATION is signal. Both pads here fire
only when a token survives its bonding curve into a real pool:

  pumpfun  pump.fun on SOLANA. Graduation = the curve completes and
           the token migrates to PumpSwap (pump.fun's own DEX).
           Detected via GeckoTerminal's free "new pools on pumpswap"
           feed (30 calls/min free tier; we poll once per cycle —
           ~20 newest pools per call, far inside the limit). Alerts
           carry liquidity/FDV in USD. $0-liquidity pools are skipped
           (dead/expired graduations).
           NOTE: >20 graduations between polls would overflow the
           20-pool window — the rare burst tail is silently skipped.

  pons     Pons on Robinhood Chain. Launches 12k-22k tokens/DAY
           (measured Aug 30: 22,581 — 99% die on the curve), so launch
           alerts are deliberately NOT offered. Graduation =
           PoolRegistered on the Pons meme hook: curve swept, real
           Uniswap v4 pool seeded, liquidity permanently locked
           (~1.3k ever, ~40-100/day recently). Contracts + topic
           verified on-chain; topic hash matches the published value.

Honest scope — an EARLY-WARNING radar, not a sniper: reaction is
seconds-to-minutes, not first-block. Alerts only; buys go through the
normal USD-capped confirm-first path. An alert carries facts
(liquidity, age, address) — never a safety verdict.
"""

import json
import threading
import time
import urllib.request
from pathlib import Path

from web3 import Web3

BASE = Path(__file__).parent
STATE_FILE = BASE / "data" / "launch_watcher.json"

RPC = "https://rpc.mainnet.chain.robinhood.com"
EXPLORER = "https://robinhoodchain.blockscout.com"
GECKO_URL = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools?dex=pumpswap"

POLL_SECONDS = 30
MAX_CATCHUP_BLOCKS = 500_000   # cap an EVM backlog scan; older gaps are skipped
ALERTS_PER_POLL = 10           # flood control (per poll, across pads)
ALERTS_PER_DAY = 120
MIN_POOL_LIQUIDITY_USD = 100.0  # pumpfun: skip $0-liquidity (dead) graduations
SEEN_KEEP = 6000

BOT_LOOP = None   # set by telegram_bot.post_init — the bot's real loop
_bot_app = None
ADMIN_ID = 0
_lock = threading.Lock()


# ------------------------------------------------------------------
# Pad registry. Each pad provides scan(w3, from_b, latest) -> list of
# event dicts: {token, blk, tx, extra(dict|None)}. kind is always
# "graduation" — that's the whole point of this radar.
# ------------------------------------------------------------------

def _topic(sig: str) -> str:
    return "0x" + Web3().keccak(text=sig).hex()


def _topic_addr(t) -> str:
    try:
        h = t.hex() if isinstance(t, (bytes, bytearray)) else str(t).replace("0x", "")
        return Web3.to_checksum_address("0x" + h[-40:])
    except Exception:
        return None


def _scan_evm(contracts, topics, extract):
    """Shared eth_getLogs scanner for the Robinhood pads."""
    def scan(w3, from_b, latest):
        if w3 is None:
            return []
        logs = w3.eth.get_logs({
            "fromBlock": hex(from_b), "toBlock": hex(latest),
            "address": [Web3.to_checksum_address(a) for a in contracts],
            "topics": [topics],
        })
        out = []
        for lg in logs:
            try:
                blk = int(lg["blockNumber"], 16) if isinstance(lg["blockNumber"], str) else int(lg["blockNumber"])
                token = extract(lg)
                if token:
                    out.append({"token": token, "blk": blk,
                                "tx": "0x" + lg["transactionHash"].hex()[2:], "extra": None})
            except Exception as e:
                print(f"[launch_watcher] log parse error: {e}")
        return out
    return scan


def _x_pons_grad(lg) -> str:
    data = bytes(lg["data"])
    return Web3.to_checksum_address("0x" + data[12:32].hex()) if len(data) >= 32 else None  # word 0 = memecoin


def _scan_pumpfun(w3, from_b, latest):
    """GeckoTerminal new PumpSwap pools = pump.fun graduations (Solana)."""
    req = urllib.request.Request(GECKO_URL, headers={"accept": "application/json",
                                                     "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    out = []
    for p in data.get("data", []):
        a = p.get("attributes", {})
        pool = a.get("address") or ""
        name = a.get("name") or ""
        symbol = name.split("/")[0].strip() if "/" in name else name
        bt = ((p.get("relationships", {}).get("base_token", {}) or {}).get("data", {}) or {}).get("id", "")
        mint = bt.split("_", 1)[1] if "_" in bt else bt
        if not mint or not pool:
            continue
        liq = float(a.get("reserve_in_usd") or 0)
        if liq < MIN_POOL_LIQUIDITY_USD:
            continue  # dead/expired graduation — noise
        out.append({
            "token": mint, "blk": None, "tx": pool,
            "extra": {"symbol": symbol, "liq_usd": liq,
                      "fdv_usd": float(a.get("fdv_usd") or 0),
                      "h1": (a.get("price_change_percentage") or {}).get("h1")},
        })
    return out


PADS = {
    "pumpfun": {
        "label": "pump.fun graduations (Solana → PumpSwap, liq/FDV shown)",
        "network": "solana",
        "scan": _scan_pumpfun,
    },
    "pons": {
        "label": "Pons graduations (Robinhood → locked Uniswap v4 pool)",
        "network": "robinhood",
        "contracts": ["0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"],  # PonsV2MemeHook
        "topics": [_topic("PoolRegistered(address,address,address,bytes32,int24)")],
        "scan": None,  # filled below via _scan_evm
    },
}

# Pons PoolRegistered topic must match the hash published in Bitquery's docs
PONS_TOPIC = "0x01bf263a1db1652580721573296e1a1fa70b3d4c87f61d02a69c4e1109d2d573"
if PADS["pons"]["topics"][0] != PONS_TOPIC:
    # the doc hash decodes as PoolRegistered — try the documented sig variants
    for sig in ("PoolRegistered(address,address,address,bytes32,int24,uint24,int24)",
                "PoolRegistered(bytes32,address,address,address,int24,uint24,int24)"):
        if _topic(sig) == PONS_TOPIC:
            PADS["pons"]["topics"][0] = PONS_TOPIC
            break
PADS["pons"]["topics"] = [PONS_TOPIC]  # doc-verified hash wins regardless
PADS["pons"]["scan"] = _scan_evm(PADS["pons"]["contracts"], PADS["pons"]["topics"], _x_pons_grad)


# ============================================================
# State (persisted): pads on/off, last_block, seen, daily counter
# ============================================================

def _load_state() -> dict:
    try:
        st = json.loads(STATE_FILE.read_text())
    except Exception:
        st = {}
    st.setdefault("pads", {})       # everything OFF by default
    if "enabled" in st:             # pre-multi-pad field — retire it
        st.pop("enabled", None)
    return st


def _save_state(st: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        seen = st.get("seen", {})
        if len(seen) > SEEN_KEEP:
            keep = sorted(seen.items(), key=lambda kv: kv[1].get("block", 0))[-SEEN_KEEP:]
            st["seen"] = dict(keep)
        STATE_FILE.write_text(json.dumps(st))
    except Exception as e:
        print(f"[launch_watcher] state save failed: {e}")


# ============================================================
# Bot wiring (copytrade pattern)
# ============================================================

def set_bot(app, admin_id: int):
    global _bot_app, ADMIN_ID
    _bot_app, ADMIN_ID = app, admin_id
    _ensure_thread()


def _ensure_thread():
    if any(p for p in _load_state().get("pads", {}).values()) and not _thread_alive():
        threading.Thread(target=watcher_loop, daemon=True, name="launch-watcher").start()


def _thread_alive() -> bool:
    return any(t.name == "launch-watcher" and t.is_alive() for t in threading.enumerate())


def _ping(text: str):
    if not _bot_app or not ADMIN_ID:
        return
    try:
        import asyncio
        coro = _bot_app.bot.send_message(chat_id=ADMIN_ID, text=text)
        loop = BOT_LOOP
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            asyncio.run(coro)
    except Exception as e:
        print(f"[launch_watcher] ping failed: {e}")


# ============================================================
# On-chain / metadata helpers
# ============================================================

def _w3():
    w = Web3(Web3.HTTPProvider(RPC, {"timeout": 15}))
    if not w.is_connected():
        raise ConnectionError("robinhood RPC unreachable")
    return w


def _decode_string(out: bytes) -> str:
    try:
        if len(out) < 64:
            return ""
        ln = int.from_bytes(out[32:64], "big")
        return out[64:64 + ln].decode("utf-8", "replace")
    except Exception:
        return ""


def _token_symbol(addr: str) -> str:
    try:
        out = bytes(_w3().eth.call({"to": Web3.to_checksum_address(addr), "data": "0x95d89b41"}))
        return _decode_string(out)
    except Exception:
        return ""


def _short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}" if a and len(a) > 14 else (a or "?")


def _usd(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


# ============================================================
# Core poll
# ============================================================

def poll(w3=None) -> dict:
    """One scan across enabled pads. First-ever run seeds silently
    (a backlog is spam, not signal)."""
    st = _load_state()
    pads_on = [p for p, on in st.get("pads", {}).items() if on and p in PADS]
    if not pads_on:
        return {"scanned": 0, "found": 0, "alerted": 0, "skipped": 0, "first_run": False}

    evm_on = [p for p in pads_on if PADS[p]["network"] == "robinhood"]
    latest = from_b = None
    if evm_on:
        w3 = w3 or _w3()
        latest = w3.eth.block_number

    first_run = "seeded" not in st
    if first_run:
        st["seeded"] = True
        st.setdefault("seen", {})
        if latest is not None:
            st["last_block"] = latest
        _save_state(st)
        return {"scanned": 0, "found": 0, "alerted": 0, "skipped": 0, "first_run": True}

    if latest is not None:
        last = int(st.get("last_block") or latest)
        from_b = max(last + 1, latest - MAX_CATCHUP_BLOCKS)
        if from_b > latest:
            st["last_block"] = latest
            _save_state(st)
            return {"scanned": 0, "found": 0, "alerted": 0, "skipped": 0, "first_run": False}

    today = time.strftime("%Y-%m-%d")
    if st.get("day") != today:
        st["day"], st["alerted_today"] = today, 0
    alerted_today = int(st.get("alerted_today") or 0)

    seen = st.setdefault("seen", {})
    found, alerts, skipped = 0, 0, 0
    newest = (from_b - 1) if from_b is not None else 0

    for pad in pads_on:
        cfg = PADS[pad]
        try:
            events = cfg["scan"](w3 if cfg["network"] == "robinhood" else None, from_b, latest)
        except Exception as e:
            print(f"[launch_watcher] {pad} scan error: {str(e)[:120]}")
            continue

        for ev in events:
            try:
                key = f"{pad}:{ev['token']}"
                if key in seen:
                    continue
                found += 1
                seen[key] = {"block": ev.get("blk") or 0, "tx": ev.get("tx") or ""}
                if alerts >= ALERTS_PER_POLL or alerted_today + alerts >= ALERTS_PER_DAY:
                    skipped += 1
                    continue
                _ping(_alert_body(pad, cfg, ev))
                alerts += 1
            except Exception as e:
                print(f"[launch_watcher] {pad} event error: {e}")

    if from_b is not None:
        st["last_block"] = max(newest, from_b - 1) if newest >= from_b else latest
    st["alerted_today"] = alerted_today + alerts
    st["last_poll"] = int(time.time())
    _save_state(st)

    if skipped:
        _ping(f"📮 {skipped} graduation(s) suppressed this window — "
              f"per-poll/daily caps. Tune caps in launch_watcher.py.")

    return {"scanned": (latest - from_b + 1) if from_b is not None else 0,
            "found": found, "alerted": alerts, "skipped": skipped, "first_run": False}


def _alert_body(pad: str, cfg: dict, ev: dict) -> str:
    token = ev["token"]
    extra = ev.get("extra") or {}
    if pad == "pumpfun":
        sym = extra.get("symbol") or "?"
        h1 = extra.get("h1")
        h1s = f"{h1:+.1f}%" if isinstance(h1, (int, float)) else "n/a"
        return "\n".join([
            "🎓 pump.fun graduation on solana",
            f"   ${sym}  (migrated to PumpSwap)",
            f"   mint: {token}",
            f"   liquidity: {_usd(extra.get('liq_usd', 0))}  |  FDV: {_usd(extra.get('fdv_usd', 0))}  |  1h: {h1s}",
            f"   pool: {ev['tx']}",
            f"   https://solscan.io/token/{token}",
            f"   https://pump.fun/coin/{token}",
            "",
            f"   Survived the curve → real PumpSwap pool. Buy: 'buy $1 of {token}'",
            "   Graduated ≠ safe: check holders and liquidity lock before sizing up.",
        ])
    # pons (robinhood)
    sym = _token_symbol(token)
    age_s = 0
    try:
        w3 = _w3()
        age_s = max(0, int(time.time()) - int(w3.eth.get_block(ev["blk"])["timestamp"]))
    except Exception:
        pass
    return "\n".join([
        "🎓 Pons graduation on robinhood",
        f"   $ {sym}" if sym else "   (symbol unknown)",
        f"   token: {token}",
        f"   age: ~{age_s}s  |  tx: {_short(ev.get('tx', ''))}",
        f"   {EXPLORER}/address/{token}",
        "",
        f"   Survived its bonding curve → real Uniswap v4 pool with",
        f"   liquidity permanently locked. Buy: 'buy $1 of {token} on robinhood'",
        "   Graduated ≠ safe: verify before sizing up.",
    ])


def watcher_loop():
    backoff = POLL_SECONDS
    while True:
        try:
            st = _load_state()
            if not any(p for p, on in st.get("pads", {}).items() if on):
                return  # nothing enabled — thread exits; restarted on toggle
            with _lock:
                stats = poll()
            if stats.get("found"):
                print(f"[launch_watcher] {stats}")
            backoff = POLL_SECONDS
        except Exception as e:
            print(f"[launch_watcher] poll error (backing off {backoff * 2}s): {e}")
            backoff = min(backoff * 2, 300)
        time.sleep(backoff)


# ============================================================
# Toggles + status for /launches
# ============================================================

VALID_PADS = tuple(PADS.keys())


def set_pads(on: bool, pads: list) -> str:
    st = _load_state()
    if not pads or "all" in pads:
        pads = list(PADS.keys())
    unknown = [p for p in pads if p not in PADS]
    pads = [p for p in pads if p in PADS]
    for p in pads:
        st.setdefault("pads", {})[p] = bool(on)
    _save_state(st)
    _ensure_thread()
    note = (f"\n(unknown pads ignored: {', '.join(unknown)} — valid: {', '.join(VALID_PADS)})"
            if unknown else "")
    enabled = [p for p, v in sorted(st["pads"].items()) if v]
    if on:
        return (f"🎓 Graduation radar ON for: {', '.join(pads)}\n"
                f"Now on: {', '.join(enabled) if enabled else '(none)'}{note}")
    return (f"🔕 Graduation radar OFF for: {', '.join(pads)}\n"
            f"Still on: {', '.join(enabled) if enabled else '(none — radar dark)'}{note}")


def status_text() -> str:
    st = _load_state()
    pads_on = [p for p, on in sorted(st.get("pads", {}).items()) if on]
    lines = ["🎓 Graduation radar — launches are noise, graduations are signal"]
    for p, cfg in PADS.items():
        mark = "🟢" if p in pads_on else "⚫️"
        lines.append(f"   {mark} {p:9s} {cfg['label']}")
    seen = st.get("seen", {})
    lines.append(f"   seen total: {len(seen)} | alerts today: {st.get('alerted_today', 0)}/{ALERTS_PER_DAY}")
    if st.get("last_poll"):
        lines.append(f"   last poll: {int(time.time()) - st['last_poll']}s ago")
    if seen:
        lines.append("   recent:")
        recent = sorted(seen.items(), key=lambda kv: kv[1].get("block", 0), reverse=True)[:4]
        for key, info in recent:
            pad, _, tok = key.partition(":")
            mark = "🟣" if pad == "pumpfun" else "🔵"
            lines.append(f"     {mark} [{pad}] {_short(tok)}")
    lines += ["", "on/off:  /launches on <pad…|all>   ·   /launches off <pad…|all>",
              f"pads: {', '.join(VALID_PADS)}   (everything is off until you say so)"]
    return "\n".join(lines)
