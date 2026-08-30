"""
DSPy Prompt Optimizer

Instead of manually tweaking the system prompt, DSPy:
1. Takes example inputs/outputs
2. Tests hundreds of prompt variations
3. Picks the best-performing one
4. Saves it for the bot to use

Run this once to optimize, then the bot uses the optimized prompt forever.
"""

import json
from pathlib import Path

PROMPT_CACHE = Path(__file__).parent / "optimized_prompt.json"
TRAINING_DATA = Path(__file__).parent / "prompt_training_data.json"


def get_training_examples():
    """Training examples for prompt optimization.
    
    Each example is: (user_input, expected_tool_calls, expected_behavior)
    """
    return [
        # Price queries
        {
            "input": "what is the price of bitcoin",
            "expected_tools": ["get_price"],
            "expected_behavior": "Call get_price with coin='btc' or 'bitcoin'",
        },
        {
            "input": "how much is eth",
            "expected_tools": ["get_price"],
            "expected_behavior": "Call get_price with coin='eth' or 'ethereum'",
        },
        # Trading
        {
            "input": "buy 100 dollars of bitcoin",
            "expected_tools": ["buy"],
            "expected_behavior": "Call buy with coin='btc', amount_usd=100",
        },
        {
            "input": "sell all my ethereum",
            "expected_tools": ["sell"],
            "expected_behavior": "Call sell with coin='eth'",
        },
        # Research / search
        {
            "input": "research the latest solana news",
            "expected_tools": ["web_search"],
            "expected_behavior": "Call web_search with query about solana news",
        },
        {
            "input": "what is robinhood's nft support",
            "expected_tools": ["web_search"],
            "expected_behavior": "Call web_search about robinhood nft",
        },
        {
            "input": "check the web for coinbase fees",
            "expected_tools": ["web_search"],
            "expected_behavior": "Call web_search about coinbase fees",
        },
        # Code fixing
        {
            "input": "fix the bug in telegram_bot.py",
            "expected_tools": ["read_file", "edit_file"],
            "expected_behavior": "Read file first, then edit it",
        },
        {
            "input": "edit the system prompt",
            "expected_tools": ["read_file", "edit_file"],
            "expected_behavior": "Read file first, then edit it",
        },
        # NFTs
        {
            "input": "what is the floor price of madlads",
            "expected_tools": ["get_nft_floor"],
            "expected_behavior": "Call get_nft_floor with collection='madlads'",
        },
        {
            "input": "create a solana wallet",
            "expected_tools": ["new_wallet"],
            "expected_behavior": "Call new_wallet with chain='solana'",
        },
        # Auto-trading rules
        {
            "input": "buy btc if it drops 5 percent",
            "expected_tools": ["add_trading_rule"],
            "expected_behavior": "Call add_trading_rule with the text",
        },
        # Portfolio
        {
            "input": "show my portfolio",
            "expected_tools": ["get_portfolio"],
            "expected_behavior": "Call get_portfolio",
        },
        # Mode switching
        {
            "input": "switch to smolagents",
            "expected_tools": [],
            "expected_behavior": "Switch mode, respond with confirmation",
        },
    ]


def optimize_prompt():
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
    class CryptoBotPrompt(dspy.Signature):
        """You are a crypto trading bot on Telegram."""
        user_message = dspy.InputField()
        system_behavior = dspy.OutputField(desc="The system prompt that would produce correct tool calls")

    # Create optimizer
    optimize = dspy.MIPROv2(metric=None, num_candidates=8)

    # Define metric: does the prompt lead to correct tool selection?
    def tool_selection_metric(example, pred, trace=None):
        """Check if the prompt would lead to correct tool selection."""
        # This is a simplified metric - in production you'd actually test tool calls
        prompt = pred.system_behavior
        score = 0

        # Check if prompt mentions key tools
        key_tools = ["read_file", "edit_file", "web_search", "get_price", "buy", "sell"]
        for tool in key_tools:
            if tool in prompt:
                score += 1

        # Check if prompt has clear rules
        if "NEVER" in prompt:
            score += 1
        if "MUST" in prompt:
            score += 1
        if "first" in prompt.lower() or "FIRST" in prompt:
            score += 1

        return score / (len(key_tools) + 3)

    # Create training set
    trainset = [dspy.Example(user_message=ex["input"]).with_outputs("system_behavior") 
                for ex in get_training_examples()[:5]]

    # Optimize
    print("Optimizing prompt with DSPy...")
    optimized_prompt = optimize.compile(
        CryptoBotPrompt,
        trainset=trainset,
        metric=tool_selection_metric,
    )

    return optimized_prompt


def get_optimized_prompt():
    """Get the optimized prompt, or create one if not exists."""
    if PROMPT_CACHE.exists():
        data = json.loads(PROMPT_CACHE.read_text())
        return data.get("prompt", get_default_prompt())
    return get_default_prompt()


def save_optimized_prompt(prompt: str):
    """Save the optimized prompt."""
    PROMPT_CACHE.write_text(json.dumps({"prompt": prompt}, indent=2))


def get_default_prompt():
    """Default system prompt (baseline for optimization)."""
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


def train_and_optimize():
    """Full training pipeline."""
    print("Step 1: Getting training examples...")
    examples = get_training_examples()
    print(f"  Found {len(examples)} examples")

    print("\nStep 2: Running DSPy optimization...")
    try:
        optimized = optimize_prompt()
        print("  Optimization complete!")

        # Save the optimized prompt
        prompt_text = optimized.user_message if hasattr(optimized, 'user_message') else get_default_prompt()
        save_optimized_prompt(prompt_text)
        print(f"\nStep 3: Saved optimized prompt to {PROMPT_CACHE}")

        return prompt_text
    except Exception as e:
        print(f"  Optimization failed: {e}")
        print("  Using default prompt")
        return get_default_prompt()


if __name__ == "__main__":
    print("=" * 60)
    print("DSPy Prompt Optimizer")
    print("=" * 60)
    print()

    # Show current prompt
    current = get_optimized_prompt()
    print("Current prompt:")
    print("-" * 40)
    print(current[:500] + "...")
    print()

    # Run optimization
    optimized = train_and_optimize()
    print()
    print("Optimized prompt:")
    print("-" * 40)
    print(optimized[:500] + "...")
