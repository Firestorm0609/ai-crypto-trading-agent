"""
Helius webhook receiver — push events for copytrade and mint watching.

Helius POSTs enhanced transactions to /helius/<AUTH_TOKEN>. We:
  1. verify the shared-secret path (so randos can't feed us fake txs)
  2. deduplicate by transaction signature (Helius retries on failure)
  3. hand the event to copytrade.py (mirror + Telegram ping)

Runs as an aiohttp site INSIDE the main bot process — no extra process
to manage. One public port (default 2095) must be reachable from the
internet (firewall/DO firewall must allow it) since Helius delivers from
their cloud. Configure with:
    watch_wallet / copy_wallet  (in copytrade.py) -> registers the Helius
    webhook pointing at http://<public-ip>:2095/helius/<token>
"""

import asyncio
import json
import os
import secrets
import time

from aiohttp import web

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Shared secret embedded in the URL path. Generated once per install.
AUTH_FILE = os.path.join(os.path.dirname(__file__), ".webhook_token")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "2095"))


def get_or_create_token() -> str:
    if os.path.exists(AUTH_FILE):
        return open(AUTH_FILE).read().strip()
    tok = secrets.token_urlsafe(24)
    open(AUTH_FILE, "w").write(tok)
    return tok


WEBHOOK_TOKEN = get_or_create_token()

# Signatures seen in the last 10 minutes (Helius may retry delivery)
_SEEN: dict = {}
_SEEN_MAX_AGE = 600

# Handlers registered by copytrade.py (Helius) and evm_copytrade.py
# (Alchemy) at import time
_EVENT_HANDLERS = []
_ALCHEMY_HANDLERS = []


def register_handler(fn):
    """Solana enhanced-tx handler: fn(tx: dict) -> None (async or sync)."""
    _EVENT_HANDLERS.append(fn)
    return fn


def register_alchemy_handler(fn):
    """EVM Address-Activity handler: fn(activity: dict) -> None."""
    _ALCHEMY_HANDLERS.append(fn)
    return fn


# ============================================================
# Request handling
# ============================================================

async def _handle_helius(request: web.Request) -> web.Response:
    # Path auth: /helius/<token>
    if request.match_info.get("token") != WEBHOOK_TOKEN:
        return web.Response(status=403, text="forbidden")

    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    txs = payload if isinstance(payload, list) else [payload]

    now = time.time()
    for k in [k for k, t in _SEEN.items() if now - t > _SEEN_MAX_AGE]:
        _SEEN.pop(k, None)

    fresh = []
    for tx in txs:
        sig = (tx or {}).get("signature") or json.dumps(tx, sort_keys=True)[:120]
        if sig in _SEEN:
            continue
        _SEEN[sig] = now
        fresh.append(tx)

    for tx in fresh:
        for fn in _EVENT_HANDLERS:
            try:
                res = fn(tx)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                print(f"[webhook] handler {getattr(fn, '__name__', '?')} failed: {e}")

    return web.Response(status=200, text=f"ok ({len(fresh)} fresh)")


async def _handle_alchemy(request: web.Request) -> web.Response:
    """Alchemy Notify (Address Activity) receiver for EVM copytrade.
    Path-token auth + optional HMAC signature verification
    (ALCHEMY_SIGNING_KEY in .env, from the webhook's dashboard page)."""
    if request.match_info.get("token") != WEBHOOK_TOKEN:
        return web.Response(status=403, text="forbidden")

    raw = await request.read()
    signing_keys = [k.strip() for k in os.getenv("ALCHEMY_SIGNING_KEY", "").split(",") if k.strip()]
    if signing_keys:
        import hashlib
        import hmac as _hmac
        sig = request.headers.get("X-Alchemy-Signature", "")
        # one webhook per network, each with its own signing key — accept any
        valid = [_hmac.new(k.encode(), raw, hashlib.sha256).hexdigest() for k in signing_keys]
        if not any(_hmac.compare_digest(sig, e) for e in valid):
            return web.Response(status=403, text="bad signature")

    try:
        payload = json.loads(raw)
    except Exception:
        return web.Response(status=400, text="bad json")

    event = (payload or {}).get("event", {})
    activities = event.get("activity", []) if isinstance(event, dict) else []

    for act in activities:
        for fn in _ALCHEMY_HANDLERS:
            try:
                res = fn(act)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                print(f"[webhook] alchemy handler {getattr(fn, '__name__', '?')} failed: {e}")
    return web.Response(status=200, text=f"ok ({len(activities)} activities)")


async def health(request: web.Request) -> web.Response:
    return web.Response(text="webhook receiver alive")


# ============================================================
# Lifecycle
# ============================================================

_runner = None
_site = None

def public_webhook_url() -> str:
    """The URL to register with Helius (uses the server's public IP)."""
    ip = os.getenv("PUBLIC_IP", "")
    return f"http://{ip}:{WEBHOOK_PORT}/helius/{WEBHOOK_TOKEN}" if ip else ""


async def _start():
    global _site, _runner
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post("/helius/{token}", _handle_helius)
    app.router.add_post("/alchemy/{token}", _handle_alchemy)
    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, "0.0.0.0", WEBHOOK_PORT)
    await _site.start()
    print(f"🎣 Webhook receiver listening on 0.0.0.0:{WEBHOOK_PORT} "
          f"(path /helius/{WEBHOOK_TOKEN[:6]}…)")


def start_webhook_server():
    """Safe sync entry point for the bot startup (never raises)."""
    import threading

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_start())
            loop.run_forever()
        except Exception as e:
            print(f"[webhook] server stopped: {e}")

    t = threading.Thread(target=_run, name="helius-webhooks", daemon=True)
    t.start()
    return t
