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
from tools import TOOLS, execute_tool
from trading_tools import TRADING_TOOL_MAP


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """You are an AI crypto trading assistant with access to tools.

MARKET DATA:
- get_price: Get real-time price for any cryptocurrency (use coin IDs like 'bitcoin', 'ethereum', 'solana')
- get_top_coins: See top cryptocurrencies by market cap
- search_coin: Find a coin by name or symbol

PORTFOLIO:
- get_portfolio: View holdings with live P&L
- buy: Buy crypto with paper money (simulated). Args: coin, amount_usd
- sell: Sell crypto holdings. Args: coin, quantity OR percentage
- get_trade_history: See recent trades
- reset_portfolio: Start fresh with paper money

GENERAL TOOLS:
- web_search: Search the web
- web_fetch: Fetch web page content
- run_python: Execute Python code
- run_shell: Run shell commands

RULES:
1. Always check prices before recommending trades.
2. Never give financial advice — this is paper trading only.
3. Always confirm the user wants to execute a trade.
4. Show P&L when discussing positions.
5. Be concise — users are on Telegram.
6. Use emoji to make responses scannable."""


# ============================================================
# Agent Core (OpenAI-compatible)
# ============================================================

class TradingAgent:
    def __init__(self):
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

    def _format_tools_for_api(self):
        """Convert our tool dicts to OpenAI function calling format."""
        api_tools = []

        # Trading tools
        for name, desc_info in [
            ("get_price", "Get current price, 24h change, volume, and market cap for a cryptocurrency."),
            ("get_top_coins", "Get the top N cryptocurrencies by market cap with prices."),
            ("search_coin", "Search for a cryptocurrency by name or symbol."),
            ("get_portfolio", "Show current portfolio with holdings, live values, and P&L."),
            ("buy", "Buy cryptocurrency with paper money. Args: coin (string), amount_usd (number)."),
            ("sell", "Sell cryptocurrency. Args: coin (string), quantity (number, optional), percentage (number, optional)."),
            ("get_trade_history", "Show recent trade history."),
            ("reset_portfolio", "Reset portfolio. Args: starting_balance (number, optional, default 10000)."),
        ]:
            params = {"type": "object", "properties": {}, "required": []}
            if name == "get_price":
                params["properties"]["coin"] = {"type": "string", "description": "Coin name or symbol (e.g., bitcoin, btc, eth)"}
                params["required"] = ["coin"]
            elif name == "get_top_coins":
                params["properties"]["n"] = {"type": "number", "description": "Number of coins (default 10)"}
            elif name == "search_coin":
                params["properties"]["query"] = {"type": "string", "description": "Search query"}
                params["required"] = ["query"]
            elif name == "buy":
                params["properties"]["coin"] = {"type": "string", "description": "Coin to buy (e.g., btc, eth)"}
                params["properties"]["amount_usd"] = {"type": "number", "description": "USD amount to spend"}
                params["required"] = ["coin", "amount_usd"]
            elif name == "sell":
                params["properties"]["coin"] = {"type": "string", "description": "Coin to sell"}
                params["properties"]["quantity"] = {"type": "number", "description": "Quantity to sell (omit to sell all)"}
                params["properties"]["percentage"] = {"type": "number", "description": "Percentage to sell (e.g., 50)"}
                params["required"] = ["coin"]
            elif name == "reset_portfolio":
                params["properties"]["starting_balance"] = {"type": "number", "description": "Starting balance (default 10000)"}
            elif name == "get_trade_history":
                params["properties"]["n"] = {"type": "number", "description": "Number of trades to show"}

            api_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc_info,
                    "parameters": params,
                }
            })

        # General tools
        api_tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search query"}},
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch and read a URL's content.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string", "description": "URL to fetch"}},
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "Execute Python code and return output.",
                    "parameters": {
                        "type": "object",
                        "properties": {"code": {"type": "string", "description": "Python code to run"}},
                        "required": ["code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_shell",
                    "description": "Run a shell command.",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string", "description": "Shell command"}},
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file from workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "File path"}},
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "content": {"type": "string", "description": "Content to write"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List files in workspace.",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}
                }
            },
        ])

        return api_tools

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool by name."""
        if name in TRADING_TOOL_MAP:
            return TRADING_TOOL_MAP[name](args)
        return execute_tool(name, args)

    def handle_message(self, user_id: int, message: str) -> str:
        """Process a user message through the agent loop."""
        history = self._get_history(user_id)
        history.append({"role": "user", "content": message})
        tools = self._format_tools_for_api()

        # Agent loop — no rate limit worries!
        for step in range(10):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=history,
                    tools=tools,
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

                result = self._execute_tool(tool_name, tool_args)
                display = result[:150] + "..." if len(result) > 150 else result
                print(f"     -> {display}")

                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Extract final response
        final = ""
        for msg in reversed(history):
            if msg.get("role") == "assistant" and msg.get("content"):
                final = msg["content"]
                break

        return final or "(Max steps reached)"


# ============================================================
# Interactive Mode
# ============================================================

def main():
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        agent = TradingAgent()
        print(f"Running: {task}\n")
        result = agent.handle_message(0, task)
        print(f"\nResult:\n{result}")
    else:
        print("=" * 50)
        print("  🤖 DeepSeek Trading Agent")
        print("=" * 50)
        print(f"  Model: {DEEPSEEK_MODEL}")
        print(f"  Cost: ~$0.0003 per request")
        print(f"  Rate limits: None!")
        print(f"  Type 'quit' to exit\n")

        agent = TradingAgent()

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
            result = agent.handle_message(0, user_input)
            print(f"\nAgent: {result}\n")
            print("-" * 50)


if __name__ == "__main__":
    main()
