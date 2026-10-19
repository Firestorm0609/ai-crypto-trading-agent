"""
Copytrade + mint-watch — mirror tracked wallets in real time via Helius push.

Flow:
  Helius webhook (enhanced tx) -> webhook_server.py -> handle_tx()
    -> classify (SWAP / mint / transfer)
    -> if copy enabled and the wallet mirrors a tracked one:
         mirror the trade on Jupiter (capped size, only per your rules)
    -> Telegram alert to ADMIN_USER_ID either way

Copied trades are REAL trades: they spend real SOL from wallets/sol_wallet.json.
Caps are enforced (max SOL per copy, only N copies per hour) so a tracked
wallet dumping its bag can't nuke your balance in one block.
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

HELIUS_KEY = os.getenv("HELIUS_API_KEY", "")
HELius_API = f"https://api.helius.xyz/v0"
TRACK_FILE = os.path.join(os.path.dirname(__file__), "watched_wallets.json")

# ---- Copy-trade safety caps ----
MAX_COPY_SOL = float(os.getenv("COPY_MAX_SOL", "0.05"))   # per copied trade
MAX_COPIES_PER_HOUR = int(os.getenv("COPY_MAX_PER_HOUR", "6"))
COPY_ENABLED = os.getenv("COPY_ENABLED", "1") == "1"

# Telegram ping target (set at startup by telegram_bot.main)
_bot_app = None
ADMIN_ID = None


def set_bot(app, admin_id):
    global _bot_app, ADMIN_ID
    _bot_app, ADMIN_ID = app, admin_id


def _ping(text: str):
    """Fire-and-forget Telegram DM to the admin."""
    if not _bot_app or not ADMIN_ID:
        return
    try:
        import asyncio
        loop = globals().get("BOT_LOOP")  # bot's real loop (set in post_init)
        coro = _bot_app.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            asyncio.run(coro)
    except Exception as e:
        print(f"[copytrade] ping failed: {e}")


# ============================================================
# Watchlist (persisted)
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


def wallet_label(address: str) -> str:
    for w in _load():
        if w["address"] == address:
            return w.get("label") or address[:8] + "…"
    return address[:8] + "…"


# ============================================================
# Helius webhook management
# ============================================================

def _helius_webhook_url() -> str:
    from webhook_server import public_webhook_url
    return public_webhook_url()


def _sync_webhook(addresses: list):
    """Point one Helius webhook at all watched addresses (upsert)."""
    if not HELIUS_KEY:
        raise RuntimeError("HELIUS_API_KEY not set")
    url = _helius_webhook_url()
    if not url:
        raise RuntimeError("PUBLIC_IP not set — cannot register webhook. "
                           "Add PUBLIC_IP=8.221.120.192 to .env")

    existing = requests.get(f"{HELius_API}/webhooks",
                            params={"api-key": HELIUS_KEY}, timeout=15).json()
    mine = [w for w in existing if url.split("/helius/")[-1] in w.get("webhookURL", "")]

    body = {
        "webhookURL": url,
        "transactionTypes": ["SWAP", "NFT_SALE", "NFT_LISTING", "NFT_MINT", "TRANSFER"],
        "accountAddresses": addresses or ["11111111111111111111111111111111"],
        "webhookType": "enhanced",
    }
    if mine:
        wid = mine[0]["webhookID"]
        r = requests.patch(f"{HELius_API}/webhooks/{wid}",
                           params={"api-key": HELIUS_KEY}, json=body, timeout=15)
    else:
        r = requests.post(f"{HELius_API}/webhooks",
                          params={"api-key": HELIUS_KEY}, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


# ============================================================
# Commands (called from the LLM tools)
# ============================================================

def watch_wallet(address: str, label: str = "", copy: bool = False) -> str:
    address = (address or "").strip()
    if len(address) < 32:
        return "❌ That doesn't look like a Solana address."
    lst = _load()
    if any(w["address"] == address for w in lst):
        return f"⚠️ Already watching {wallet_label(address)}."
    lst.append({"address": address, "label": label or address[:8] + "…",
                "copy": bool(copy), "added": datetime.now(timezone.utc).isoformat()})
    _save(lst)
    try:
        _sync_webhook([w["address"] for w in lst])
        mode = "COPYING trades" if copy else "alerts only"
        return f"👁️ Now watching {lst[-1]['label']} ({mode}). Push events enabled."
    except Exception as e:
        return (f"⚠️ Saved locally but Helius webhook sync failed: {e}\n"
                f"Check PUBLIC_IP in .env and that port {os.getenv('WEBHOOK_PORT', '2095')} is open.")


def unwatch_wallet(address: str) -> str:
    lst = [w for w in _load() if w["address"] != address.strip()]
    _save(lst)
    try:
        _sync_webhook([w["address"] for w in lst])
    except Exception:
        pass
    return f"🗑️ Stopped watching. {len(lst)} wallet(s) remain."


def list_watched() -> str:
    lst = _load()
    if not lst:
        return "No watched wallets. Add one: watch_wallet(address, copy=True)."
    lines = ["👁️ Watched wallets:"]
    for w in lst:
        mode = " 📋 COPY" if w.get("copy") else ""
        lines.append(f"  • {w['label']} — `{w['address'][:12]}…{w['address'][-6:]}`{mode}")
    return "\n".join(lines)


def toggle_copy(address: str, enabled: bool) -> str:
    lst = _load()
    for w in lst:
        if w["address"] == address.strip():
            w["copy"] = bool(enabled)
            _save(lst)
            try:
                _sync_webhook([x["address"] for x in lst])
            except Exception:
                pass
            return (f"{'📋 Copy ON' if enabled else '👁️ Copy OFF'} for {w['label']} — "
                    f"capped at {MAX_COPY_SOL} SOL/trade, {MAX_COPIES_PER_HOUR}/hour.")
    return f"❌ Not watching {address[:10]}…"


# ============================================================
# Event classification + copy execution
# ============================================================

_copy_times: list = []   # timestamps of copies in the last hour


def _copy_allowed() -> bool:
    global _copy_times
    now = time.time()
    _copy_times = [t for t in _copy_times if now - t < 3600]
    return len(_copy_times) < MAX_COPIES_PER_HOUR


def _extract_swap(tx: dict):
    """(token_in_sym, amount_in, token_out_sym, amount_out) from an enhanced SWAP."""
    try:
        ts = tx.get("tokenTransfers", [])
        if len(ts) >= 2:
            a, b = ts[0], ts[1]
            return (a.get("mint", "?"), a.get("tokenAmount", 0),
                    b.get("mint", "?"), b.get("tokenAmount", 0))
    except Exception:
        pass
    return None


def _looks_like_mint(tx: dict) -> bool:
    types = tx.get("type", "") or ""
    return "MINT" in str(types).upper()


def _mint_contract(tx: dict) -> str:
    for ev in tx.get("events", {}).get("nft", []):
        return ev.get("mint", "")
    for tt in tx.get("tokenTransfers", []):
        return tt.get("mint", "")
    return ""


def handle_tx(tx: dict):
    """Registered with webhook_server; runs for every fresh enhanced tx."""
    sig = (tx.get("signature") or [""])[0] if isinstance(tx.get("signature"), list) else tx.get("signature", "")
    fee_payer = (tx.get("feePayer") or tx.get("signer", [""])[0] if isinstance(tx.get("signer"), list) else tx.get("feePayer", "")) or ""
    desc = tx.get("description", "") or ""
    txtype = str(tx.get("type", "")).upper()

    # Which watched wallet fired?
    watched = {w["address"]: w for w in _load()}
    source = None
    for addr, w in watched.items():
        if addr in desc or addr == fee_payer:
            source = w
            break
    if not source:
        return  # not one of ours

    label = source["label"]

    # ---- Classify ----
    if txtype in ("SWAP",) or "swap" in desc.lower():
        sw = _extract_swap(tx)
        _ping(f"🔁 *{label}* swapped\n`{sig}`")
        if source.get("copy") and COPY_ENABLED and _copy_allowed():
            _mirror_swap(sw, label)
    elif "MINT" in txtype or "mint" in desc.lower():
        mint = _mint_contract(tx)
        _ping(f"🪄 *{label}* minted{' ' + mint if mint else ''}\n`{sig}`")
        if source.get("copy"):
            result = _copy_mint(mint)
            if result:
                _ping(result)
    else:
        _ping(f"📦 *{label}* {txtype.lower() or 'activity'}\n{desc[:180]}\n`{sig}`")


def _mirror_swap(sw, label: str = ""):
    """Mirror a tracked swap on Jupiter with our caps. Real money.
    `label` is the tracked wallet's name, only used for journal notes."""
    if not sw:
        return _ping("⚠️ Copy: couldn't parse the swap legs — skipped.")
    in_mint, in_amt, out_mint, out_amt = sw
    try:
        from solana_trader import get_swap_quote, get_swap_transaction, sign_and_send_transaction, rugcheck_gate
        # Honeypot/rug gate: never mirror-buy a token the checker flags.
        verdict = rugcheck_gate(out_mint)
        if verdict != "ok":
            try:
                import trade_journal
                trade_journal.log_trade(
                    kind="copy", chain="solana", side="buy",
                    token=out_mint[:10] + "…", token_addr=out_mint,
                    amount=MAX_COPY_SOL, native=f"{MAX_COPY_SOL} SOL",
                    status="failed", source="copytrade",
                    note=f"RUG GATE: {verdict}")
            except Exception:
                pass
            _ping(f"🚫 *Copy skipped — rug gate*\n`{out_mint[:12]}…`\n{verdict[:180]}")
            return
        # Copy proportionally but capped: use our fixed cap in SOL terms by
        # swapping the capped SOL amount into whatever they bought.
        # Simplest robust mirror: buy `out` token with COPY_MAX_SOL of SOL
        quote = get_swap_quote("So11111111111111111111111111111111111111112", out_mint,
                               int(MAX_COPY_SOL * 1e9), slippage_bps=200)
        tx = get_swap_transaction(quote)
        result = sign_and_send_transaction(
            tx.get("swapTransaction", ""),
            journal_info={"kind": "copy", "side": "buy", "token": out_mint[:10] + "…",
                          "token_addr": out_mint, "amount": MAX_COPY_SOL,
                          "native": f"{MAX_COPY_SOL} SOL", "source": "copytrade",
                          "wallet": label or "unknown"})
        _copy_times.append(time.time())
        _ping(f"📋 *COPIED* buy of their token with {MAX_COPY_SOL} SOL\n{str(result)[:120]}")
    except Exception as e:
        _ping(f"❌ Copy failed: {str(e)[:200]}")


def _copy_mint(mint: str):
    """Solana mint copying: alert-only for now — mirroring an arbitrary
    candy-machine mint needs the machine's ID, which enhanced txs don't
    reliably carry. The alert gives you the mint address to act on."""
    return None


# ============================================================
# Tool registry
# ============================================================

COPYTRADE_TOOLS = [
    {"type": "function", "function": {"name": "watch_wallet", "description": "Watch a Solana wallet in real time (Helius push): get Telegram alerts on every swap/mint it makes. copy=True also MIRRORS its trades with your wallet (capped size).", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "label": {"type": "string"}, "copy": {"type": "boolean", "description": "Mirror their trades with real money"}}, "required": ["address"]}}},
    {"type": "function", "function": {"name": "unwatch_wallet", "description": "Stop watching a Solana wallet.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]}}},
    {"type": "function", "function": {"name": "list_watched", "description": "List watched Solana wallets and copy mode.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "toggle_copy", "description": "Turn copy-trading on/off for a watched wallet.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "enabled": {"type": "boolean"}}, "required": ["address", "enabled"]}}},
]

COPYTRADE_TOOL_MAP = {
    "watch_wallet": lambda a: watch_wallet(a["address"], a.get("label", ""), bool(a.get("copy", False))),
    "unwatch_wallet": lambda a: unwatch_wallet(a["address"]),
    "list_watched": lambda a: list_watched(),
    "toggle_copy": lambda a: toggle_copy(a["address"], bool(a.get("enabled", True))),
}

# Push every Helius event through the classifier
from webhook_server import register_handler
register_handler(handle_tx)
