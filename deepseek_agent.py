#!/usr/bin/env python3
"""
Trading Agent — powered by DeepSeek (OpenAI-compatible API).

No rate limits, very cheap ($0.14/M tokens), tool-calling support.

Usage:
    python3 deepseek_agent.py              # Interactive mode
    python3 deepseek_agent.py "your task"  # Single task mode
"""

import sys
import json
from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
from registry import TOOLS, dispatch_tool


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """You are an AI crypto trading assistant with access to tools.

You can:
- Get real-time prices, top coins, and market data
- Paper trade and check portfolio P&L
- Execute real Solana swaps and scan tokens for risk
- Search the web and fetch pages
- Read and write files

RULES:
1. Always check prices before recommending trades.
2. Never give financial advice.
3. Confirm with the user before executing real trades.
4. Show P&L when discussing positions.
5. Be concise — users are on Telegram.
6. Use emoji to make responses scannable."""


# ============================================================
# Agent Core (OpenAI-compatible)
# ============================================================

class TradingAgent:
    def __init__(self):
        if not DEEPSEEK_API_KEY:
            print("Error: DEEPSEEK_API_KEY not set!")
            print("   Get one at: https://platform.deepseek.com/")
            print("   Then add it to the .env file.")
            sys.exit(1)
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
        self.model = DEEPSEEK_MODEL
        # Per-user chat histories
        self.user_histories = {}

    def _get_history(self, user_id: int):
        if user_id not in self.user_histories:
            self.user_histories[user_id] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        return self.user_histories[user_id]

    def _execute_tool(self, name: str, args: dict, user_id: int = 0) -> str:
        """Execute any registered tool via the unified registry."""
        return dispatch_tool(name, args, user_id=user_id)

    def handle_message(self, user_id: int, message: str) -> str:
        """Process a user message through the agent loop."""
        history = self._get_history(user_id)
        history.append({"role": "user", "content": message})

        # Agent loop
        for step in range(10):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=history,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=2000,
                    temperature=0.7,
                )
            except Exception as e:
                return f"API Error: {str(e)}"

            choice = response.choices[0]
            msg = choice.message

            # If no tool calls, we're done
            if not msg.tool_calls:
                history.append({"role": "assistant", "content": msg.content or ""})
                return msg.content or "(No response)"

            # Add assistant message with tool calls
            history.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    } for tc in msg.tool_calls
                ]
            })

            # Execute each tool call
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    tool_args = {}

                print(f"  [{step+1}] {tool_name}({json.dumps(tool_args, default=str)[:120]})")

                try:
                    result = self._execute_tool(tool_name, tool_args, user_id=user_id)
                except Exception as e:
                    result = f"Tool error: {str(e)}"
                if len(result) > 2000:
                    result = result[:2000] + "... (truncated)"

                print(f"      -> {result[:150]}")

                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "(Max steps reached)"


# ============================================================
# CLI
# ============================================================

def print_banner():
    print("=" * 50)
    print("  DeepSeek Trading Agent")
    print("=" * 50)
    print(f"  Model: {DEEPSEEK_MODEL}")
    print("  Type 'quit' or 'exit' to stop.\n")


def interactive_mode():
    print_banner()
    agent = TradingAgent()
    print("Agent ready! Ask me anything.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        print()
        response = agent.handle_message(0, user_input)
        print(f"\nAgent: {response}\n")
        print("-" * 50)


def single_task_mode(task: str):
    print(f"Running: {task}\n")
    agent = TradingAgent()
    response = agent.handle_message(0, task)
    print(f"\nResult:\n{response}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        single_task_mode(" ".join(sys.argv[1:]))
    else:
        interactive_mode()
