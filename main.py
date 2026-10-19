#!/usr/bin/env python3
"""
main.py — single entry point for everything.

    python3 main.py            # Start the Telegram bot (all agents + workers)
    python3 main.py cli        # Chat with the agent in your terminal
    python3 main.py task ...   # Run a one-off task
    python3 main.py check      # Preflight checks only (keys, tools, DB)
    python3 main.py stop       # Kill any running bot instances
    python3 main.py status     # Is the bot running?

Everything runs on the free Mistral API — no paid services required.
"""

import os
import sys
from pathlib import Path

PID_FILE = Path(__file__).parent / "bot.pid"
PROJECT_DIR = str(Path(__file__).parent.resolve())


def _find_bot_pids() -> list:
    """PIDs of running bot instances belonging to THIS project.

    Matches only processes whose working directory is this project dir —
    other projects with their own main.py/bot.py are never touched.
    """
    pids = []
    me = os.getpid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == me:
            continue
        try:
            cwd = os.path.realpath(proc / "cwd")
            if cwd != PROJECT_DIR:
                continue
            cmdline = (proc / "cmdline").read_bytes().decode(errors="ignore")
        except Exception:
            continue
        args = [a for a in cmdline.split("\0") if a]
        script = args[0] if args and args[0].endswith(".py") else \
                 (args[1] if len(args) > 1 and args[1].endswith(".py") else "")
        if os.path.basename(script) in ("telegram_bot.py", "main.py"):
            pids.append(int(proc.name))
    return pids


# ============================================================
# Preflight — fail fast with clear messages
# ============================================================

def preflight(need_telegram: bool = True) -> bool:
    """Verify config before starting anything. Returns True when ready."""
    ok = True

    from config import XAI_API_KEY, XAI_MODEL, MISTRAL_API_KEYS, MISTRAL_MODEL
    if XAI_API_KEY:
        print(f"✓ LLM: xAI grok (main, model={XAI_MODEL})")
    elif MISTRAL_API_KEYS:
        print(f"✓ LLM: Mistral fallback ({len(MISTRAL_API_KEYS)} key(s)), model={MISTRAL_MODEL}")
    else:
        print("✗ No LLM key set — add XAI_API_KEY (or MISTRAL_API_KEY) to .env")
        ok = False

    # Tool registry — this imports every tool module, catching wiring errors
    try:
        import registry
        print(f"✓ Tool registry: {len(registry.TOOLS)} tools loaded")
    except Exception as e:
        print(f"✗ Tool registry failed to load: {e}")
        ok = False

    # Database — create tables if missing
    try:
        from all_tools import init_db
        init_db()
        print("✓ Database: trading.db ready")
    except Exception as e:
        print(f"✗ Database error: {e}")
        ok = False

    if need_telegram:
        import os
        from config import env_path  # noqa: F401 — ensures .env was loaded
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            print("✗ TELEGRAM_BOT_TOKEN not set — add it to .env")
            ok = False
        else:
            print("✓ Telegram: token present")

    return ok


# ============================================================
# Modes
# ============================================================

def run_bot():
    """The Telegram bot — this is 'everything': all agent modes, price
    alerts, auto-trading rules, strategies, and daily snapshots start
    inside it."""
    # Guard: Telegram allows only ONE poller per bot token. A second
    # instance causes 'Conflict: terminated by other getUpdates request'.
    existing = _find_bot_pids()
    if existing:
        print("✗ A bot instance is already running (PID "
              f"{', '.join(map(str, existing))}).")
        print("  Telegram only allows one instance per token.")
        print("  Stop it first:  python3 main.py stop")
        sys.exit(1)

    if not preflight(need_telegram=True):
        print("\nFix the issues above, then run: python3 main.py")
        sys.exit(1)

    PID_FILE.write_text(str(os.getpid()))
    print("\nStarting Telegram bot...\n")
    try:
        # Drop-watcher: resumes queued NFT drop mints across restarts
        try:
            from opensea_tools import start_drop_watcher
            start_drop_watcher()
        except Exception as e:
            print(f"(drop watcher not started: {e})")
        # Webhook receiver: Helius push events for copytrade/wallet watching
        try:
            from webhook_server import start_webhook_server
            start_webhook_server()
            from copytrade import list_watched  # registers event handlers
        except Exception as e:
            print(f"(webhook receiver not started: {e})")
        # EVM copytrade: getLogs polling via Alchemy for watched wallets
        try:
            from evm_copytrade import start_evm_watcher
            start_evm_watcher()
        except Exception as e:
            print(f"(evm copytrade not started: {e})")
        import telegram_bot
        telegram_bot.main()
    finally:
        PID_FILE.unlink(missing_ok=True)


def stop_bot():
    """Kill every running bot instance (politely, then firmly)."""
    import signal
    import time
    pids = _find_bot_pids()
    if not pids:
        print("No running bot instances.")
        PID_FILE.unlink(missing_ok=True)
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    for pid in pids:
        try:
            os.kill(pid, 0)  # liveness check
            os.kill(pid, signal.SIGKILL)
            print(f"Force-killed {pid}")
        except ProcessLookupError:
            print(f"Stopped {pid}")
    PID_FILE.unlink(missing_ok=True)


def run_cli():
    """Interactive terminal chat with the same tools as the bot."""
    if not preflight(need_telegram=False):
        sys.exit(1)
    from agent import interactive_mode
    interactive_mode()


def run_task(task: str):
    """One-off task, prints result and exits."""
    if not preflight(need_telegram=False):
        sys.exit(1)
    from agent import CLIAgent
    print(f"Running: {task}\n")
    result = CLIAgent().run(task)
    print(f"\nResult:\n{result}")


# ============================================================
# CLI
# ============================================================

def main():
    args = sys.argv[1:]

    if not args or args[0] == "bot":
        run_bot()
    elif args[0] == "cli":
        run_cli()
    elif args[0] == "task":
        if len(args) < 2:
            print("Usage: python3 main.py task \"your task here\"")
            sys.exit(1)
        run_task(" ".join(args[1:]))
    elif args[0] == "check":
        if preflight(need_telegram=True):
            print("\nAll good — python3 main.py to start the bot.")
    elif args[0] == "stop":
        stop_bot()
    elif args[0] == "status":
        pids = _find_bot_pids()
        if pids:
            print(f"Bot is RUNNING (PID {', '.join(map(str, pids))})")
        else:
            print("Bot is not running.")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
