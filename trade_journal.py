"""
Trade Journal — append-only JSONL record of every REAL executed action.

Every swap, mint, NFT buy/sell/list, bridge, transfer, and copy-trade mirror
that actually reaches the chain gets one line here. Paper trades and failed
pre-flight checks (insufficient balance, cap refusal) are NOT logged — only
broadcast attempts and their outcome.

Format: one JSON object per line in data/trade_journal.jsonl
  ts        — ISO-8601 UTC timestamp
  kind      — swap | copy | mint | nft_buy | nft_sell | nft_list | nft_transfer
              | bridge | allowance
  chain     — solana | ethereum | base | robinhood | arbitrum | optimism | polygon
  side      — buy | sell | (blank for mint/bridge/etc.)
  token     — human-readable token/collection symbol or name
  token_addr— mint/contract address when known
  amount    — float amount of `token` (or native currency spent)
  native    — native currency spent, e.g. "0.05 SOL", "0.001 ETH" (blank if n/a)
  tx        — tx signature/hash (may be blank if broadcast failed)
  status    — broadcasted | confirmed | failed | unknown
  source    — manual | copytrade | drop_watch | auto_rule
  wallet    — counterpart wallet label/address for copies
  note      — extra context (slippage, cap, error snippet)

Never raises: journaling must never break a trade path.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_FILE = Path(__file__).parent / "data" / "trade_journal.jsonl"
MAX_LINES = 20000  # rotate point; keeps the file forever-manageable


def _file():
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    return _FILE


def log_trade(kind: str, chain: str = "", side: str = "", token: str = "",
              token_addr: str = "", amount=None, native: str = "",
              tx: str = "", status: str = "unknown", source: str = "manual",
              wallet: str = "", note: str = "", **extra) -> None:
    """Append one entry. Swallows every error — logging must never break trading."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind, "chain": chain, "side": side,
            "token": token, "token_addr": token_addr,
            "amount": amount, "native": native,
            "tx": tx, "status": status, "source": source, "wallet": wallet,
            "note": note,
        }
        entry.update(extra)
        line = json.dumps(entry, default=str)
        with _LOCK:
            f = _file()
            # crude rotation: if huge, keep the last half
            try:
                if f.exists() and f.stat().st_size > 8_000_000:
                    lines = f.read_text().splitlines()
                    f.write_text("\n".join(lines[-MAX_LINES // 2:]) + "\n")
            except Exception:
                pass
            with f.open("a") as fh:
                fh.write(line + "\n")
    except Exception:
        pass


def recent(limit: int = 20, chain: str = "", kind: str = "") -> str:
    """Human-readable recent history for the /trades command."""
    try:
        f = _file()
        if not f.exists():
            return "📭 No trades logged yet. Every real swap/mint/copy will appear here."
        with _LOCK:
            lines = f.read_text().splitlines()
        entries = []
        for ln in reversed(lines):
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if chain and e.get("chain") != chain:
                continue
            if kind and e.get("kind") != kind:
                continue
            entries.append(e)
            if len(entries) >= max(1, min(int(limit), 100)):
                break
        if not entries:
            return "📭 No matching trades in the journal."
        out = [f"📒 Last {len(entries)} logged action(s)" + (f" on {chain}" if chain else "") + (f" [{kind}]" if kind else "") + ":\n"]
        for e in entries:
            amt = f"{e['amount']:g} " if isinstance(e.get("amount"), (int, float)) else ""
            tok = e.get("token") or "?"
            side = f"{e['side'].upper()} " if e.get("side") else ""
            nat = f" ({e['native']})" if e.get("native") else ""
            src = f" · {e['source']}" if e.get("source") and e["source"] != "manual" else ""
            wlt = f" · {e['wallet']}" if e.get("wallet") else ""
            stat = {"confirmed": "✅", "broadcasted": "📤", "failed": "❌"}.get(e.get("status"), "❔")
            out.append(f"{e.get('ts', '?')[:16]} {stat} {e.get('kind', '?')} · {e.get('chain', '?')} · {side}{amt}{tok}{nat}{src}{wlt}")
        out.append("\nFilter: /trades [chain] — e.g. /trades base, /trades solana")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Journal read error: {e}"


def stats(days: int = 7) -> str:
    """Quick counts by kind/chain for the recent window (rough, informational)."""
    try:
        f = _file()
        if not f.exists():
            return "📭 No trades logged yet."
        with _LOCK:
            lines = f.read_text().splitlines()
        from collections import Counter
        kinds, chains = Counter(), Counter()
        for ln in lines[-500:]:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            kinds[e.get("kind", "?")] += 1
            chains[e.get("chain", "?")] += 1
        out = ["📊 Recent journal activity (last ~500 entries):"]
        out += [f"  {k}: {v}" for k, v in kinds.most_common()]
        out.append("  by chain: " + ", ".join(f"{c}: {n}" for c, n in chains.most_common()))
        return "\n".join(out)
    except Exception as e:
        return f"❌ {e}"
