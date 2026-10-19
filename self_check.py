"""
Dependency Self-Check — the bot pings its own arms so nothing rots silently.

The Jupiter v6 endpoint died at the DNS level once and nothing noticed for
who knows how long. This module runs every external dependency check on a
schedule (default 12h) and Telegram-pings ONLY on changes:
  • a dependency that was up is now DOWN  → alert
  • a dependency that was down is back UP → recovery notice
All-up results stay silent. `run_self_check` tool = on-demand report.

Checked: Jupiter swap+price, Helius RPC+webhooks, Alchemy RPCs (per enabled
chain), OpenSea API, LI.FI, Mistral keys, Telegram Bot API.
"""

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).parent / "data" / "self_check_state.json"
CHECK_INTERVAL_H = 12
TIMEOUT = 12
# Cloudflare-fronted APIs (Jupiter price, LI.FI, Helius dashboard API) 403
# urllib's default "Python-urllib" user-agent — identify ourselves properly.
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) aesir-agent/1.0",
       "accept": "application/json"}

_notifier = None  # set by telegram_bot at startup (copytrade._ping)


def set_notifier(fn) -> None:
    global _notifier
    _notifier = fn


def _alert(text: str) -> None:
    try:
        if _notifier:
            _notifier(text)
    except Exception:
        pass


def _get(url: str, headers: dict = None) -> tuple:
    """(status_code, body) — never raises."""
    try:
        req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode()[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200] if e.fp else ""
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _post_json(url: str, payload: dict, headers: dict = None) -> tuple:
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={**_UA, "content-type": "application/json",
                                              **(headers or {})})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode()[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200] if e.fp else ""
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _env(key: str) -> str:
    """Read .env FIRST (what the bot actually loads), then fall back to
    os.environ — an ambient exported var (e.g. a stale revoked token in a
    shell profile) must not mask the truth."""
    p = Path(__file__).parent / ".env"
    try:
        for line in p.read_text().splitlines():
            if line.strip().startswith(key + "="):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    except Exception:
        pass
    return os.environ.get(key, "")


# ============================================================
# Individual checks — each returns (ok, detail)
# ============================================================

def check_jupiter_swap() -> tuple:
    SOL = "So11111111111111111111111111111111111111112"
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    url = (f"https://lite-api.jup.ag/swap/v1/quote?inputMint={SOL}"
           f"&outputMint={USDC}&amount=1000000&slippageBps=50")
    code, body = _get(url)
    ok = code == 200 and "outAmount" in body
    return ok, f"quote 0.001 SOL→USDC: HTTP {code}" + ("" if ok else f" — {body[:100]}")


def check_jupiter_price() -> tuple:
    code, body = _get("https://lite-api.jup.ag/price/v3?ids=So11111111111111111111111111111111111111112")
    ok = code == 200 and "So111" in body
    return ok, f"price/v3: HTTP {code}" + ("" if ok else f" — {body[:100]}")


def check_helius_rpc() -> tuple:
    key = _env("HELIUS_API_KEY")
    if not key:
        return True, "SKIP — no HELIUS_API_KEY"
    code, body = _post_json(f"https://mainnet.helius-rpc.com/?api-key={key}",
                            {"jsonrpc": "2.0", "id": 1, "method": "getHealth"})
    ok = code == 200 and '"ok"' in body
    return ok, f"RPC getHealth: HTTP {code}" + ("" if ok else f" — {body[:100]}")


def check_helius_webhooks() -> tuple:
    key = _env("HELIUS_API_KEY")
    if not key:
        return True, "SKIP — no HELIUS_API_KEY"
    code, body = _get(f"https://api.helius.xyz/v0/webhooks?api-key={key}")
    ok = code == 200 and body.startswith("[")
    return ok, f"webhook API: HTTP {code}" + ("" if ok else f" — {body[:100]}")


def check_alchemy() -> tuple:
    """One block-number probe per chain that has an Alchemy RPC configured."""
    try:
        from evm_swap import alchemy_rpc
    except Exception as e:
        return False, f"cannot import evm_swap: {e}"
    chains = ["ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"]
    results, all_ok = [], True
    for ch in chains:
        url = alchemy_rpc(ch)
        if not url:
            continue
        code, body = _post_json(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber"})
        ok = code == 200 and "result" in body
        all_ok &= ok
        results.append(f"{ch}: {'✅' if ok else f'❌ HTTP {code}'}")
    if not results:
        return True, "SKIP — no Alchemy chains configured"
    return all_ok, " ".join(results)


def check_opensea() -> tuple:
    key = _env("OPENSEA_API_KEY")
    if not key:
        return True, "SKIP — no OPENSEA_API_KEY"
    code, body = _get("https://api.opensea.io/api/v2/collections/pudgy-penguins",
                      headers={"accept": "application/json", "x-api-key": key})
    ok = code == 200 and "collection" in body
    return ok, f"collections API: HTTP {code}" + ("" if ok else f" — {body[:100]}")


def check_lifi() -> tuple:
    code, body = _get("https://li.quest/v1/chains")
    ok = code == 200 and "chains" in body
    return ok, f"chains API: HTTP {code}" + ("" if ok else f" — {body[:100]}")


def check_mistral() -> tuple:
    keys = []
    for k, v in os.environ.items():
        if k.upper().startswith("MISTRAL_API_KEY") and v:
            keys.append((k, v))
    if not keys:
        return False, "NO MISTRAL KEYS CONFIGURED"
    alive, dead = [], []
    for name, key in keys:
        code, _ = _get("https://api.mistral.ai/v1/models",
                       headers={"accept": "application/json", "Authorization": f"Bearer {key}"})
        (alive if code == 200 else dead).append(f"{name}({code or 'net'})")
    ok = bool(alive)
    detail = f"{len(alive)}/{len(keys)} keys alive" + (f" · dead: {', '.join(dead)}" if dead else "")
    return ok, detail


def check_telegram() -> tuple:
    tok = _env("TELEGRAM_BOT_TOKEN")
    if not tok:
        return False, "NO TELEGRAM_BOT_TOKEN"
    code, body = _get(f"https://api.telegram.org/bot{tok}/getMe")
    ok = code == 200 and '"ok":true' in body.replace(" ", "").lower()
    return ok, f"getMe: HTTP {code}" + ("" if ok else f" — {body[:80]}")


ALL_CHECKS = {
    "jupiter_swap": check_jupiter_swap,      # Solana trading
    "jupiter_price": check_jupiter_price,    # token prices
    "helius_rpc": check_helius_rpc,          # Solana push + RPC
    "helius_webhooks": check_helius_webhooks,
    "alchemy": check_alchemy,                # EVM RPCs (all chains)
    "opensea": check_opensea,                # NFTs
    "lifi": check_lifi,                      # bridges
    "mistral": check_mistral,                # the brain
    "telegram": check_telegram,              # the voice
}


# ============================================================
# State + scheduling
# ============================================================

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def run_all(notify_on_changes: bool = True) -> str:
    """Run every check. Alerts only on up→down and down→up transitions."""
    state = _load_state()
    prev = state.get("results", {})
    results, lines, changed = {}, [], []
    for name, fn in ALL_CHECKS.items():
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"check crashed: {e}"
        results[name] = {"ok": ok, "detail": detail, "ts": datetime.now(timezone.utc).isoformat()}
        was = prev.get(name, {}).get("ok") if name in prev else None
        if was is True and not ok:
            changed.append(f"🔻 {name} went DOWN — {detail}")
        elif was is False and ok:
            changed.append(f"🔺 {name} RECOVERED — {detail}")
        lines.append(f"{'✅' if ok else '❌'} {name}: {detail}")

    new_state = {"results": results,
                 "last_run": datetime.now(timezone.utc).isoformat(),
                 "last_ok": all(r["ok"] for r in results.values())}
    _save_state(new_state)

    if notify_on_changes and changed:
        _alert("🩺 *Self-check changes*\n" + "\n".join(changed))
    report = ("🩺 Self-check — " + ("all systems OK" if new_state["last_ok"] else "FAILURES PRESENT") + "\n\n"
              + "\n".join(lines))
    return report


def _loop() -> None:
    # small startup delay so the bot finishes booting
    time.sleep(90)
    while True:
        try:
            run_all(notify_on_changes=True)
        except Exception as e:
            print(f"[self-check] loop error: {e}")
        time.sleep(CHECK_INTERVAL_H * 3600)


_thread = None


def start_scheduler() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, daemon=True, name="self-check")
    _thread.start()


# Tool registration
SELF_CHECK_TOOLS = [
    {"type": "function", "function": {"name": "run_self_check",
     "description": "Run a health check on every external dependency (Jupiter, Helius, Alchemy, OpenSea, LI.FI, Mistral keys, Telegram) and report which are up or down.",
     "parameters": {"type": "object", "properties": {}}}},
]

SELF_CHECK_TOOL_MAP = {
    "run_self_check": lambda a: run_all(notify_on_changes=False),
}
