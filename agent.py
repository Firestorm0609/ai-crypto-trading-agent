#!/usr/bin/env python3
"""
CLI Agent — Mistral function-calling agent over the unified tool registry.

Usage:
    python3 agent.py              # Interactive mode
    python3 agent.py "your task"  # Single task mode

(For the Telegram bot, run telegram_bot.py. For the smolagents
code-writing agent, run smolagents_agent.py.)
"""

import sys
import json

from openai import OpenAI

from config import (MISTRAL_API_KEYS, MISTRAL_MODEL, MAX_AGENT_STEPS,
                    XAI_API_KEY, XAI_MODEL, XAI_BASE_URL, TOOL_SCOPING)
from registry import TOOLS, dispatch_tool
from tool_scoping import select_tools
from guardrails import ActionTracker, review_reply


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """You are a capable AI assistant with access to tools.

You can:
- Search the web and fetch web pages
- Trade crypto (paper and real swaps), scan tokens, check prices
- Read, write, and edit files
- Run shell commands and Python code
- Remember user preferences

RULES:
1. Always think step by step before acting.
2. Use tools when you need real information or to perform actions.
3. If a tool fails, try a different approach.
4. When you're done, give a clear final answer.
5. Never run destructive commands without asking first.
6. Confirm with the user before executing real trades."""


# ============================================================
# Agent Core
# ============================================================

class CLIAgent:
    """Simple function-calling agent loop for terminal use."""

    def __init__(self):
        if XAI_API_KEY:
            # Main LLM: grok via xAI (owner's call 2026-10-15)
            self.client = OpenAI(
                api_key=XAI_API_KEY,
                base_url=XAI_BASE_URL,
            )
            self.model = XAI_MODEL
        elif MISTRAL_API_KEYS:
            self.client = OpenAI(
                api_key=MISTRAL_API_KEYS[0],
                base_url="https://api.mistral.ai/v1",
            )
            self.model = MISTRAL_MODEL
        else:
            print("Error: no LLM key set! Add XAI_API_KEY (or MISTRAL_API_KEY) to .env.")
            sys.exit(1)
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def run(self, user_message: str, verbose: bool = True) -> str:
        """Run the agent loop: send message -> handle tool calls -> repeat."""
        self.history.append({"role": "user", "content": user_message})

        # Scope tools to what this message plausibly needs
        tools = select_tools(user_message, TOOLS) if TOOL_SCOPING else TOOLS
        tracker = ActionTracker()

        for step in range(MAX_AGENT_STEPS):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                tools=tools,
                tool_choice="auto",
                max_tokens=2000,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                self.history.append({"role": "assistant", "content": msg.content or ""})
                return review_reply(tracker, msg.content or "(No response)")

            # Record the assistant's tool-call turn
            self.history.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Execute each tool call and feed results back
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    tool_args = {}

                if verbose:
                    args_str = json.dumps(tool_args, default=str)
                    print(f"  [{step + 1}] {tool_name}({args_str[:100]}{'...' if len(args_str) > 100 else ''})")

                result = dispatch_tool(tool_name, tool_args)
                tracker.record(tool_name, tool_args, str(result))

                if verbose:
                    print(f"     -> {result[:200]}{'...' if len(result) > 200 else ''}")

                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result)[:4000],
                })

        return "(Max steps reached)"


# ============================================================
# CLI Interface
# ============================================================

def print_banner():
    print("=" * 50)
    print("  CLI Agent - Grok (xAI) + tool registry")
    print("=" * 50)
    print(f"  Model: {XAI_MODEL if XAI_API_KEY else MISTRAL_MODEL}")
    print(f"  Max steps: {MAX_AGENT_STEPS}")
    print("  Type 'quit' or 'exit' to stop.\n")


def interactive_mode():
    """Run the agent in interactive chat mode."""
    print_banner()
    agent = CLIAgent()

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
        response = agent.run(user_input)
        print(f"\nAgent: {response}\n")
        print("-" * 50)


def single_task_mode(task: str):
    """Run a single task and print the result."""
    print(f"Running: {task}\n")
    agent = CLIAgent()
    response = agent.run(task)
    print(f"\nResult:\n{response}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        single_task_mode(" ".join(sys.argv[1:]))
    else:
        interactive_mode()
