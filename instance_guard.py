"""
Instance Guard — kernel-level single-instance lock for the bot.

Telegram allows exactly ONE poller per bot token. Two pollers = the
'Conflict: terminated by other getUpdates request' error.

This lock is acquired via fcntl.flock, which the OS releases
automatically if the holder dies — no stale-lock cleanup ever needed.

Because the guard is enforced in telegram_bot.main() (the choke point
every launch path goes through — main.py, screen, tmux, direct runs),
NO launch method can start a second poller. screen -dmS re-launches
from other AI sessions now fail fast with a clear message instead of
fighting over getUpdates.
"""

import fcntl
import os
import sys
from pathlib import Path

LOCK_FILE = Path(__file__).parent / ".bot_instance.lock"
_lock_fd = None  # module-level so the lock survives for the process lifetime


def acquire_instance_lock() -> bool:
    """
    Try to become the one-and-only bot instance.

    Returns True if the lock was acquired (caller may poll Telegram).
    Returns False if another instance is already running (caller must exit).
    The lock is held until the process exits — intentionally never released.
    """
    global _lock_fd
    try:
        # "a+" does NOT truncate on open — a failed grab must not wipe
        # the current holder's PID from the file.
        _lock_fd = open(LOCK_FILE, "a+")
        fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Lock acquired — safely rewrite diagnostics now
        _lock_fd.seek(0)
        _lock_fd.truncate()
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except OSError:
        # Someone else holds the lock
        if _lock_fd:
            try:
                _lock_fd.close()
            except Exception:
                pass
            _lock_fd = None
        return False


def get_lock_holder_pid():
    """Best-effort read of the current holder's PID for error messages."""
    try:
        return LOCK_FILE.read_text().strip()
    except Exception:
        return "unknown"


def ensure_single_instance():
    """Exit the process if another bot instance already holds the lock."""
    if acquire_instance_lock():
        return True
    print(
        f"✗ Another bot instance is already running (lock holder PID "
        f"{get_lock_holder_pid()}).\n"
        f"  Telegram allows only ONE poller per token.\n"
        f"  Stop it with:  python3 main.py stop\n"
        f"  Or:  screen -S trading-bot -X quit   /   tmux kill-session -t <name>"
    )
    sys.exit(1)
