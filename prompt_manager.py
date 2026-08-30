"""
Prompt Manager — Versioned, Swappable Prompts

Instead of one giant SYSTEM_PROMPT that you keep tweaking:
1. Store prompts in a JSON file
2. Version them (v1, v2, v3...)
3. Swap instantly without code changes
4. Track which version works best

Usage:
    python3 prompt_manager.py list          # List all versions
    python3 prompt_manager.py use v3        # Switch to version 3
    python3 prompt_manager.py diff v2 v3    # Compare versions
    python3 prompt_manager.py save          # Save current as new version
"""

import json
from pathlib import Path
from datetime import datetime

PROMPTS_FILE = Path(__file__).parent / "prompts.json"
ACTIVE_PROMPT_FILE = Path(__file__).parent / "active_prompt.txt"


def load_prompts() -> dict:
    """Load all prompt versions."""
    if PROMPTS_FILE.exists():
        return json.loads(PROMPTS_FILE.read_text())
    return {}


def save_prompts(prompts: dict):
    """Save all prompt versions."""
    PROMPTS_FILE.write_text(json.dumps(prompts, indent=2))


def get_active_prompt() -> str:
    """Get the currently active prompt."""
    if ACTIVE_PROMPT_FILE.exists():
        return ACTIVE_PROMPT_FILE.read_text()
    return get_default_prompt()


def set_active_prompt(prompt: str):
    """Set the active prompt."""
    ACTIVE_PROMPT_FILE.write_text(prompt)


def save_version(version: str, prompt: str, notes: str = ""):
    """Save a prompt version."""
    prompts = load_prompts()
    prompts[version] = {
        "prompt": prompt,
        "notes": notes,
        "created_at": datetime.now().isoformat(),
    }
    save_prompts(prompts)
    print(f"Saved prompt version: {version}")


def list_versions():
    """List all prompt versions."""
    prompts = load_prompts()
    if not prompts:
        print("No saved prompt versions.")
        return

    print("Prompt Versions:")
    print("-" * 40)
    for version, data in sorted(prompts.items()):
        notes = data.get("notes", "")
        created = data.get("created_at", "?")[:10]
        prompt_preview = data["prompt"][:80].replace("\n", " ")
        print(f"  {version} ({created}) — {notes}")
        print(f"    Preview: {prompt_preview}...")
        print()


def use_version(version: str):
    """Switch to a prompt version."""
    prompts = load_prompts()
    if version not in prompts:
        print(f"Version '{version}' not found.")
        return

    set_active_prompt(prompts[version]["prompt"])
    print(f"Switched to prompt version: {version}")


def diff_versions(v1: str, v2: str):
    """Compare two prompt versions."""
    prompts = load_prompts()
    if v1 not in prompts or v2 not in prompts:
        print(f"One or both versions not found.")
        return

    prompt1 = prompts[v1]["prompt"]
    prompt2 = prompts[v2]["prompt"]

    print(f"Diff: {v1} vs {v2}")
    print("-" * 40)

    lines1 = prompt1.split("\n")
    lines2 = prompt2.split("\n")

    for i, (l1, l2) in enumerate(zip(lines1, lines2)):
        if l1 != l2:
            print(f"  Line {i+1}:")
            print(f"    {v1}: {l1}")
            print(f"    {v2}: {l2}")

    if len(lines1) != len(lines2):
        print(f"  {v2} has {len(lines2) - len(lines1)} more lines")


def get_default_prompt() -> str:
    """The default system prompt."""
    return """You are a crypto trading bot on Telegram. Be concise, use emoji. Keep responses SHORT (under 100 words).

CRITICAL FORMATTING:
- NEVER use **, #, ```, or * for formatting
- Use ONLY plain text with emoji

YOUR TOOLS — USE PROACTIVELY:
- get_price: Get any crypto price
- buy/sell: Paper trading
- web_search: Search the internet
- read_file/edit_file: Fix code
- add_trading_rule: Auto-trading
- mint_nft/new_wallet: NFT operations

WHEN FIXING CODE:
1. FIRST use read_file to read the file
2. THEN use edit_file to fix it
3. THEN use restart_bot to apply
NEVER make up code. ALWAYS read first.

WHEN UNSURE:
- Use web_search instead of guessing
- Never make up answers

RULES:
1. Use tools PROACTIVELY
2. Keep responses under 100 words
3. Plain text only, no markdown"""


# ============================================================
# Pre-built prompt versions
# ============================================================

PROMPT_V1 = get_default_prompt()

PROMPT_V2 = """You are a crypto trading bot on Telegram. Be concise, use emoji. Keep responses SHORT (under 100 words).

TOOLS — USE THEM, DONT DESCRIBE THEM:
- get_price: Get crypto price (call this when user asks about price)
- buy/sell: Paper trading (call this when user wants to trade)
- web_search: Search internet (call this when you dont know something)
- read_file/edit_file: Fix code (read FIRST, then edit)
- add_trading_rule: Auto-trading from natural language
- mint_nft/new_wallet: NFT operations

CRITICAL RULES:
1. If user asks price → call get_price tool
2. If user asks to buy/sell → call buy/sell tool
3. If user asks about something you dont know → call web_search
4. If user asks to fix code → call read_file FIRST, then edit_file
5. NEVER make up answers. ALWAYS use tools.
6. NEVER use **, #, or ``` in responses. Plain text only.

You have tools. Use them. Dont ask permission. Just do it."""


PROMPT_V3 = """You are a crypto bot. Short responses. Use emoji. No markdown.

Tools you MUST use:
- get_price(coin) — when user asks about price
- buy(coin, amount) — when user wants to buy
- sell(coin) — when user wants to sell
- web_search(query) — when you dont know something
- read_file(filepath) — FIRST step when fixing code
- edit_file(filepath, old, new) — SECOND step when fixing code
- restart_bot() — THIRD step when fixing code
- add_trading_rule(text) — when user sets auto-trading rules
- get_nft_floor(collection) — when user asks about NFTs
- new_wallet(chain) — when user wants a wallet

Rules:
- Use tools immediately, dont ask permission
- Read files before editing them
- Search when unsure, never guess
- 100 words max. Plain text. No markdown."""


def init_default_prompts():
    """Initialize with default prompt versions."""
    save_version("v1", PROMPT_V1, "Original default prompt")
    save_version("v2", PROMPT_V2, "Simplified, tool-focused")
    save_version("v3", PROMPT_V3, "Minimal, imperative style")
    set_active_prompt(PROMPT_V3)
    print("Initialized 3 prompt versions (v1, v2, v3)")
    print("Active: v3")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 prompt_manager.py init     — Initialize with defaults")
        print("  python3 prompt_manager.py list     — List all versions")
        print("  python3 prompt_manager.py use v3   — Switch to version")
        print("  python3 prompt_manager.py diff v1 v2 — Compare versions")
        print("  python3 prompt_manager.py current  — Show current prompt")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init":
        init_default_prompts()
    elif cmd == "list":
        list_versions()
    elif cmd == "use" and len(sys.argv) > 2:
        use_version(sys.argv[2])
    elif cmd == "diff" and len(sys.argv) > 3:
        diff_versions(sys.argv[2], sys.argv[3])
    elif cmd == "current":
        print(get_active_prompt())
    else:
        print(f"Unknown command: {cmd}")
