"""
Mem0 Integration — Persistent Memory for the Bot

The bot remembers:
- User preferences (favorite coins, risk tolerance)
- Past conversations
- Trading patterns
- Important facts users share

Memory is stored locally (no API credits for storage).
Only uses credits when extracting memories from conversations.
"""

import json
from pathlib import Path

MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)


class SimpleMemory:
    """Simple file-based memory (no API credits needed)."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.memory_file = MEMORY_DIR / f"user_{user_id}.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.memory_file.exists():
            return json.loads(self.memory_file.read_text())
        return {
            "preferences": {},
            "facts": [],
            "conversations": [],
            "trading_patterns": [],
        }

    def _save(self):
        self.memory_file.write_text(json.dumps(self.data, indent=2))

    def remember(self, key: str, value: str):
        """Remember a preference or fact."""
        self.data["preferences"][key] = value
        self._save()

    def remember_fact(self, fact: str):
        """Remember an important fact."""
        if fact not in self.data["facts"]:
            self.data["facts"].append(fact)
            self._save()

    def remember_trading(self, pattern: str):
        """Remember a trading pattern."""
        if pattern not in self.data["trading_patterns"]:
            self.data["trading_patterns"].append(pattern[-50:])  # Keep last 50
            self._save()

    def get_preference(self, key: str) -> str:
        """Get a remembered preference."""
        return self.data["preferences"].get(key, "")

    def get_facts(self) -> list:
        """Get all remembered facts."""
        return self.data["facts"]

    def get_trading_patterns(self) -> list:
        """Get remembered trading patterns."""
        return self.data["trading_patterns"]

    def get_context(self) -> str:
        """Get memory context for the LLM."""
        lines = []

        if self.data["preferences"]:
            lines.append("User Preferences:")
            for k, v in self.data["preferences"].items():
                lines.append(f"  - {k}: {v}")

        if self.data["facts"]:
            lines.append("Known Facts:")
            for f in self.data["facts"][-10:]:
                lines.append(f"  - {f}")

        if self.data["trading_patterns"]:
            lines.append("Trading Patterns:")
            for p in self.data["trading_patterns"][-5:]:
                lines.append(f"  - {p}")

        return "\n".join(lines) if lines else "No memories yet."


def extract_memories(message: str, user_id: int) -> list:
    """Extract memories from a user message."""
    memory = SimpleMemory(user_id)
    extracted = []

    msg_lower = message.lower()

    # Extract preferences
    if "my favorite" in msg_lower or "i like" in msg_lower or "i prefer" in msg_lower:
        if "btc" in msg_lower or "bitcoin" in msg_lower:
            memory.remember("favorite_coin", "bitcoin")
            extracted.append("Remembered: favorite coin is Bitcoin")
        elif "eth" in msg_lower or "ethereum" in msg_lower:
            memory.remember("favorite_coin", "ethereum")
            extracted.append("Remembered: favorite coin is Ethereum")
        elif "sol" in msg_lower or "solana" in msg_lower:
            memory.remember("favorite_coin", "solana")
            extracted.append("Remembered: favorite coin is Solana")

    # Extract risk tolerance
    if "conservative" in msg_lower or "safe" in msg_lower:
        memory.remember("risk_tolerance", "conservative")
        extracted.append("Remembered: conservative risk tolerance")
    elif "aggressive" in msg_lower or "risky" in msg_lower:
        memory.remember("risk_tolerance", "aggressive")
        extracted.append("Remembered: aggressive risk tolerance")

    # Extract portfolio size
    if "small portfolio" in msg_lower or "just starting" in msg_lower:
        memory.remember("portfolio_size", "small")
        extracted.append("Remembered: small portfolio")
    elif "large portfolio" in msg_lower or "whale" in msg_lower:
        memory.remember("portfolio_size", "large")
        extracted.append("Remembered: large portfolio")

    # Extract goals
    if "long term" in msg_lower or "hodl" in msg_lower:
        memory.remember("goal", "long_term")
        extracted.append("Remembered: long-term investor")
    elif "day trade" in msg_lower or "short term" in msg_lower:
        memory.remember("goal", "day_trader")
        extracted.append("Remembered: day trader")

    return extracted


# ============================================================
# Tool Registry
# ============================================================

MEMORY_TOOLS = [
    {"type": "function", "function": {"name": "remember_preference", "description": "Remember a user preference for future conversations.", "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}}},
    {"type": "function", "function": {"name": "get_memory", "description": "Get all remembered information about a user.", "parameters": {"type": "object", "properties": {}}}},
]

MEMORY_TOOL_MAP = {
    "remember_preference": lambda a: _remember(a.get("key", ""), a.get("value", "")),
    "get_memory": lambda a: _get_memory(),
}

_user_id_cache = 0

def set_current_user(user_id: int):
    global _user_id_cache
    _user_id_cache = user_id

def _remember(key: str, value: str) -> str:
    memory = SimpleMemory(_user_id_cache)
    memory.remember(key, value)
    return f"Remembered: {key} = {value}"

def _get_memory() -> str:
    memory = SimpleMemory(_user_id_cache)
    return memory.get_context()
