"""
API Key Hot-Swap — replace exhausted/rotated keys at runtime, no restart.

The bot runs on free-tier keys, and they run out (Helius "max usage reached"
taught us that). Send the new key to the bot and it:
  1. VALIDATES the key against the live service (bad key → refused, nothing touched)
  2. Persists it to .env — the source of truth for future restarts
  3. Hot-patches the in-memory module globals so the new key is used immediately

Modules read keys through functions (no import-time snapshots), so patching
the module attribute is enough. Validation probes use a browser-ish
User-Agent — Cloudflare 403s the default Python-urllib one.

Keys never appear in chat output: masked as  ab12…wxyz  everywhere.
"""

import json
import os
import re
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

try:
    load_dotenv()
except Exception:
    pass

ENV_FILE = Path(__file__).parent / ".env"
TIMEOUT = 12
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) aesir-agent/1.0",
       "accept": "application/json"}

SUPPORTED = {
    "helius":   "Solana RPC + webhooks (HELIUS_API_KEY)",
    "alchemy":  "EVM RPCs, all chains (ALCHEMY_API_KEY)",
    "opensea":  "NFT marketplace API (OPENSEA_API_KEY)",
    "mistral":  "the AI brain (MISTRAL_API_KEY or comma-separated list)",
    "telegram": "bot token — applies on next restart (poller can't swap mid-run)",
}


def _mask(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 12:
        return k[:3] + "…" + k[-2:] if len(k) > 6 else "…"
    return k[:6] + "…" + k[-4:]


def _get(url: str, headers: dict = None) -> tuple:
    try:
        req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200] if e.fp else ""
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _post_json(url: str, payload: dict, headers: dict = None) -> tuple:
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     method="POST",
                                     headers={**_UA, "content-type": "application/json",
                                              **(headers or {})})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200] if e.fp else ""
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


# ============================================================
# Per-key validators — (ok, human detail)
# ============================================================

def _validate_helius(key: str) -> tuple:
    code, body = _post_json(f"https://mainnet.helius-rpc.com/?api-key={key}",
                            {"jsonrpc": "2.0", "id": 1, "method": "getHealth"})
    if code == 200 and '"ok"' in body:
        return True, "RPC getHealth OK"
    if code == 401 or code == 403:
        return False, f"key rejected (HTTP {code})"
    if code == 429:
        return False, "key valid but ALREADY rate-limited — sure you want this one?"
    return False, f"HTTP {code}: {body[:80]}"


def _validate_alchemy(key: str) -> tuple:
    code, body = _post_json(f"https://eth-mainnet.g.alchemy.com/v2/{key}",
                            {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber"})
    if code == 200 and "result" in body:
        return True, "eth_blockNumber OK on ethereum"
    if code in (401, 403):
        return False, f"key rejected (HTTP {code})"
    return False, f"HTTP {code}: {body[:80]}"


def _validate_opensea(key: str) -> tuple:
    code, body = _get("https://api.opensea.io/api/v2/collections/pudgy-penguins",
                      headers={"x-api-key": key})
    if code == 200 and "collection" in body:
        return True, "collections API OK"
    if code == 401:
        return False, "key rejected (401) — check the key"
    if code == 403:
        return False, "403 — key valid but lacking this endpoint's scope?"
    return False, f"HTTP {code}: {body[:80]}"


def _validate_mistral(keys: list) -> tuple:
    if not keys:
        return False, "no key given"
    alive, dead = [], []
    for k in keys:
        code, _ = _get("https://api.mistral.ai/v1/models",
                       headers={"Authorization": f"Bearer {k}"})
        (alive if code == 200 else dead).append(k)
    if alive and not dead:
        return True, f"{len(alive)} key(s) valid"
    if alive:
        return True, f"{len(alive)} valid, {len(dead)} INVALID: {', '.join(_mask(k) for k in dead)} — only valid ones applied"
    return False, f"all {len(dead)} key(s) rejected by api.mistral.ai"


def _validate_telegram(key: str) -> tuple:
    code, body = _get(f"https://api.telegram.org/bot{key}/getMe")
    if code == 200 and '"ok":true' in body.replace(" ", "").lower():
        return True, "getMe OK — will take effect on next restart"
    return False, f"HTTP {code}: {body[:80]}"


# ============================================================
# Persistence + hot-patching
# ============================================================

def persist_env(name: str, value: str) -> None:
    """Write KEY=value into .env (replace existing line or append). Never raises."""
    try:
        lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
        pattern = re.compile(rf"^{re.escape(name)}=.*$")
        new_lines, replaced = [], False
        for ln in lines:
            if pattern.match(ln):
                new_lines.append(f"{name}={value}")
                replaced = True
            else:
                new_lines.append(ln)
        if not replaced:
            new_lines.append(f"{name}={value}")
        ENV_FILE.write_text("\n".join(new_lines) + "\n")
        os.environ[name] = value
    except Exception:
        pass


def _apply_helius(key: str) -> list:
    applied = []
    import evm_swap
    evm_swap.HELIUS_KEY = key
    applied.append("evm_swap (Solana RPC/WS fallback chain)")
    # solana_trader snapshotted the URL at import — refresh it too
    import solana_trader
    solana_trader.SOLANA_RPC = evm_swap.solana_rpc()
    applied.append("solana_trader (live RPC URL refreshed)")
    import copytrade
    copytrade.HELIUS_KEY = key
    applied.append("copytrade (Solana webhook sync)")
    return applied


def _apply_alchemy(key: str) -> list:
    import evm_swap
    evm_swap.ALCHEMY_KEY = key
    return ["evm_swap (all EVM chains + Solana fallback)"]


def _apply_opensea(key: str) -> list:
    import opensea_tools
    opensea_tools.API_KEY = key
    return ["opensea_tools (API client)"]


def _apply_mistral(keys: list) -> list:
    applied = []
    import telegram_bot
    agent = getattr(telegram_bot, "agent", None)
    rot = getattr(agent, "mistral_rotator", None) if agent else None
    if rot is not None:
        rot.keys = list(keys)
        rot.current_index = 0
        rot.key_usage = {i: {"requests": 0, "last_error": 0} for i in range(len(keys))}
        applied.append(f"live rotator → {len(keys)} key(s), index reset to 0")
    else:
        applied.append("⚠️ rotator not found — new keys apply on restart")
    return applied


def _apply_telegram(key: str) -> list:
    import telegram_bot
    telegram_bot.TELEGRAM_TOKEN = key
    return ["telegram_bot.TELEGRAM_TOKEN patched — RESTART needed to take effect"]


_VALIDATORS = {
    "helius": lambda v: _validate_helius(v),
    "alchemy": lambda v: _validate_alchemy(v),
    "opensea": lambda v: _validate_opensea(v),
    "mistral": lambda v: _validate_mistral([k.strip() for k in v.split(",") if k.strip()]),
    "telegram": lambda v: _validate_telegram(v),
}
# The exact .env var name each service maps to
_ENV_NAMES = {
    "helius": "HELIUS_API_KEY", "alchemy": "ALCHEMY_API_KEY",
    "opensea": "OPENSEA_API_KEY", "telegram": "TELEGRAM_BOT_TOKEN",
}


def set_api_key(service: str, key: str) -> str:
    """Validate → persist → hot-apply. The public tool entry."""
    service = (service or "").lower().strip()
    key = (key or "").strip().strip('"').strip("'")
    if service not in SUPPORTED:
        return (f"❌ Unknown service {service!r}. Supported: "
                + ", ".join(f"{k} ({v})" for k, v in SUPPORTED.items()))
    if not key:
        return "❌ No key provided."
    if len(key) < 8:
        return "❌ That's too short to be a real key."

    if service == "mistral":
        keys = [k.strip() for k in key.split(",") if k.strip()]
        ok, detail = _VALIDATORS[service](key)
        if not ok:
            return f"🛑 Refused — nothing changed. Validation: {detail}"
        persist_env("MISTRAL_API_KEY", keys[0])
        for i, k in enumerate(keys, start=1):
            persist_env(f"MISTRAL_API_KEY_{i}", k)
        applied = _apply_mistral(keys)
        return ("✅ Mistral key(s) swapped (persisted to .env, hot-applied)\n"
                f"Keys: {', '.join(_mask(k) for k in keys)}\n"
                f"Validation: {detail}\nApplied: " + "; ".join(applied))

    ok, detail = _VALIDATORS[service](key)
    if not ok:
        return (f"🛑 Refused — nothing changed, old key stays active.\n"
                f"Validation: {detail}")

    persist_env(_ENV_NAMES[service], key)
    appliers = {"helius": _apply_helius, "alchemy": _apply_alchemy,
                "opensea": _apply_opensea, "telegram": _apply_telegram}
    applied = appliers[service](key)
    return (f"✅ {service} key swapped → {_mask(key)}\n"
            f"Validation: {detail}\n"
            f"Persisted: {_ENV_NAMES[service]} in .env\n"
            f"Hot-applied: " + "; ".join(applied))


def list_api_keys() -> str:
    """Masked overview of every managed key's presence."""
    out = ["🔑 API keys (masked):\n"]
    env_names = {"helius": "HELIUS_API_KEY", "alchemy": "ALCHEMY_API_KEY",
                 "opensea": "OPENSEA_API_KEY", "telegram": "TELEGRAM_BOT_TOKEN"}
    for svc, env_name in env_names.items():
        v = os.environ.get(env_name, "")
        # prefer the .env value if env is stale
        try:
            for ln in ENV_FILE.read_text().splitlines():
                if ln.startswith(env_name + "=") and len(ln) > len(env_name) + 1:
                    v = ln.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
        out.append(f"  {svc:9} {'set ' + _mask(v) if v else '— NOT SET'}")
    try:
        mistral = [ln.split("=", 1)[1].strip() for ln in ENV_FILE.read_text().splitlines()
                   if ln.startswith("MISTRAL_API_KEY") and len(ln.split('=', 1)[1].strip()) > 3]
        out.append(f"  mistral   {len(mistral)} key(s): " + (", ".join(_mask(k) for k in mistral[:5]) if mistral else "NOT SET"))
    except Exception:
        pass
    out.append("\nReplace any: set_api_key(service, key) — validated before applying.")
    return "\n".join(out)


# Tool registration
KEY_MANAGER_TOOLS = [
    {"type": "function", "function": {"name": "set_api_key",
     "description": "Replace an API key at runtime (helius, alchemy, opensea, mistral, telegram). The key is validated against the live service FIRST — invalid keys are refused and nothing changes. Valid keys are persisted to .env and hot-applied immediately (except telegram, which needs a restart).",
     "parameters": {"type": "object", "properties": {
         "service": {"type": "string", "enum": ["helius", "alchemy", "opensea", "mistral", "telegram"]},
         "key": {"type": "string", "description": "The new API key. For mistral, comma-separated list = multiple keys."}},
         "required": ["service", "key"]}}},
    {"type": "function", "function": {"name": "list_api_keys",
     "description": "Show which API keys are configured (masked, never full keys).",
     "parameters": {"type": "object", "properties": {}}}},
]

KEY_MANAGER_TOOL_MAP = {
    "set_api_key": lambda a: set_api_key(a["service"], a["key"]),
    "list_api_keys": lambda a: list_api_keys(),
}
