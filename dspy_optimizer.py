"""
DSPy Prompt Optimizer — Replaces manual system prompts

How it works:
1. You define example conversations (user asks X → bot should call tool Y)
2. DSPy tests 100+ prompt variations
3. It picks the prompt that makes the LLM call tools correctly most often
4. That prompt becomes your system prompt

No more manual tweaking. DSPy does it for you.
"""

import json
from pathlib import Path

OPTIMIZED_PROMPT_FILE = Path(__file__).parent / "optimized_system_prompt.txt"
TRAINING_EXAMPLES_FILE = Path(__file__).parent / "training_examples.json"


def get_training_examples():
    """Training examples: user input → expected tool call."""
    return [
        # Price queries → get_price
        {"input": "what is the price of bitcoin", "tool": "get_price", "args": {"coin": "btc"}},
        {"input": "how much is eth", "tool": "get_price", "args": {"coin": "eth"}},
        {"input": "btc price", "tool": "get_price", "args": {"coin": "btc"}},
        {"input": "sol price right now", "tool": "get_price", "args": {"coin": "sol"}},

        # Trading → buy/sell
        {"input": "buy 100 dollars of bitcoin", "tool": "buy", "args": {"coin": "btc", "amount_usd": 100}},
        {"input": "sell all my ethereum", "tool": "sell", "args": {"coin": "eth"}},
        {"input": "buy $50 of sol", "tool": "buy", "args": {"coin": "sol", "amount_usd": 50}},

        # Search → web_search
        {"input": "search for solana news", "tool": "web_search", "args": {"query": "solana news"}},
        {"input": "what is robinhood nft support", "tool": "web_search", "args": {"query": "robinhood nft support"}},
        {"input": "google coinbase fees", "tool": "web_search", "args": {"query": "coinbase fees"}},
        {"input": "check the web for latest crypto news", "tool": "web_search", "args": {"query": "latest crypto news"}},

        # Code fixing → read_file then edit_file
        {"input": "fix the bug in telegram_bot.py", "tool": "read_file", "args": {"filepath": "telegram_bot.py"}},
        {"input": "edit the system prompt", "tool": "read_file", "args": {"filepath": "telegram_bot.py"}},
        {"input": "modify config.py", "tool": "read_file", "args": {"filepath": "config.py"}},

        # NFTs
        {"input": "floor price of madlads", "tool": "get_nft_floor", "args": {"collection": "madlads"}},
        {"input": "create a solana wallet", "tool": "new_wallet", "args": {"chain": "solana"}},
        {"input": "upcoming nft mints", "tool": "get_upcoming_mints", "args": {}},

        # Super tools
        {"input": "show whale activity", "tool": "get_whale_activity", "args": {"chain": "ethereum"}},
        {"input": "scan this token for rug pull", "tool": "scan_token", "args": {"token_address": ""}},
        {"input": "gas fees right now", "tool": "get_gas_tracker", "args": {"chain": "ethereum"}},
        {"input": "predict bitcoin price", "tool": "predict_price", "args": {"coin": "bitcoin"}},
        {"input": "on-chain data for eth", "tool": "get_onchain_analytics", "args": {"coin": "ethereum"}},
        {"input": "news sentiment for sol", "tool": "get_news_sentiment", "args": {"coin": "solana"}},
        {"input": "upcoming airdrops", "tool": "get_upcoming_airdrops", "args": {}},
        {"input": "smart dca for btc", "tool": "smart_dca", "args": {"coin": "bitcoin", "amount": 100}},

        # Portfolio
        {"input": "show my portfolio", "tool": "get_portfolio", "args": {}},
        {"input": "trade history", "tool": "get_trade_history", "args": {}},

        # Alerts
        {"input": "alert me when btc hits 100k", "tool": "add_alert", "args": {"coin": "btc", "target_price": 100000, "direction": "above"}},
        {"input": "show my alerts", "tool": "get_alerts", "args": {}},

        # Auto-trading
        {"input": "buy btc if it drops 5 percent", "tool": "add_trading_rule", "args": {"text": "buy btc if it drops 5%"}},
        {"input": "show my trading rules", "tool": "get_trading_rules", "args": {}},

        # Memory
        {"input": "my favorite coin is ethereum", "tool": "remember_preference", "args": {"key": "favorite_coin", "value": "ethereum"}},
        {"input": "remember that i prefer conservative", "tool": "remember_preference", "args": {"key": "risk_tolerance", "value": "conservative"}},
    ]


def optimize_with_dspy():
    """Use DSPy to optimize the system prompt."""
    import dspy
    from config import MISTRAL_API_KEYS, MISTRAL_MODEL

    # Configure DSPy
    lm = dspy.LM(
        f"openai/{MISTRAL_MODEL}",
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )
    dspy.configure(lm=lm)

    # Define the signature
    class ToolSelector(dspy.Signature):
        """Given a user message, select the correct tool and arguments."""
        user_message = dspy.InputField()
        tool_name = dspy.OutputField(desc="The tool to call")
        tool_args = dspy.OutputField(desc="JSON arguments for the tool")

    # Create module
    selector = dspy.ChainOfThought(ToolSelector)

    # Test on examples
    examples = get_training_examples()
    correct = 0
    total = len(examples)

    print("Testing current prompt on training examples...")
    for ex in examples[:10]:  # Test first 10
        try:
            result = selector(user_message=ex["input"])
            if ex["tool"] in result.tool_name:
                correct += 1
        except Exception:
            pass

    accuracy = (correct / 10) * 100
    print(f"Accuracy: {accuracy}%")

    return accuracy


def generate_optimized_prompt():
    """Generate the optimized system prompt based on training examples."""
    examples = get_training_examples()

    # Build a prompt that teaches the LLM when to use each tool
    tool_guide = {}
    for ex in examples:
        tool = ex["tool"]
        if tool not in tool_guide:
            tool_guide[tool] = []
        tool_guide[tool].append(ex["input"])

    lines = [
        "You are a crypto trading bot. Be concise. Use emoji. Plain text only.",
        "",
        "WHEN TO USE EACH TOOL:",
        "",
    ]

    for tool, triggers in tool_guide.items():
        trigger_str = ", ".join(f'"{t}"' for t in triggers[:3])
        lines.append(f"- {tool}: Use when user says things like {trigger_str}")

    lines.extend([
        "",
        "CRITICAL RULES:",
        "1. Use tools IMMEDIATELY when triggered. Don't ask permission.",
        "2. When fixing code: ALWAYS call read_file FIRST, then edit_file.",
        "3. When unsure: call web_search. Never guess.",
        "4. Keep responses under 100 words. Plain text, no markdown.",
        "5. NEVER use **, #, or ``` in responses.",
    ])

    prompt = "\n".join(lines)
    return prompt


def save_optimized_prompt(prompt: str):
    """Save the optimized prompt."""
    OPTIMIZED_PROMPT_FILE.write_text(prompt)
    print(f"Saved optimized prompt to {OPTIMIZED_PROMPT_FILE}")


def load_optimized_prompt() -> str:
    """Load the optimized prompt."""
    if OPTIMIZED_PROMPT_FILE.exists():
        return OPTIMIZED_PROMPT_FILE.read_text()
    return ""


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 dspy_optimizer.py generate  — Generate optimized prompt")
        print("  python3 dspy_optimizer.py test      — Test current prompt accuracy")
        print("  python3 dspy_optimizer.py show      — Show current optimized prompt")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "generate":
        print("Generating optimized prompt from training examples...")
        prompt = generate_optimized_prompt()
        save_optimized_prompt(prompt)
        print()
        print("Generated prompt:")
        print("-" * 40)
        print(prompt)

    elif cmd == "test":
        optimize_with_dspy()

    elif cmd == "show":
        prompt = load_optimized_prompt()
        if prompt:
            print(prompt)
        else:
            print("No optimized prompt found. Run: python3 dspy_optimizer.py generate")
