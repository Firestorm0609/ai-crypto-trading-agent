#!/usr/bin/env python3
"""
Gemini AI Agent — a free-tier agent with tool-calling capabilities.

Usage:
    python3 agent.py              # Interactive mode
    python3 agent.py "your task"  # Single task mode
"""

import sys
import json
from smolagents import Agent

from config import MAX_AGENT_STEPS
from all_tools import TOOLS


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """You are a capable AI assistant with access to tools.

You can:
- Search the web and fetch web pages
- Read, write, and list files
- Execute Python code
- Run shell commands

RULES:
1. Always think step by step before acting.
2. Use tools when you need real information or to perform actions.
3. If a tool fails, try a different approach.
4. When you're done, give a clear final answer.
5. Never run destructive commands without asking first.
6. Keep file writes within the workspace.
7. For web searches, try to be specific with your queries.
8. When writing code, test it with run_python before telling the user it's done."""


# ============================================================
# Agent Core
# ============================================================

class Agent:
    def __init__(self):
        self.mode = "Standard"
        self.status = "Active"
        
    def show_agent_status(self):
        return f"🤖 Status: {self.status}"
        
    def show_mode(self):
        return f"🎯 Mode: {self.mode}"
        if not GEMINI_API_KEY:
            print("Error: GEMINI_API_KEY not set!")
            print("   Get one free at: https://aistudio.google.com/apikey")
            print("   Then add it to the .env file.")
            sys.exit(1)

        genai.configure(api_key=GEMINI_API_KEY)

        # TOOLS is already a list of FunctionDeclaration objects
        tools = [Tool(function_declarations=TOOLS)]

        # Configure model with tools
        self.model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
        )

        self.chat = self.model.start_chat(history=[])
        self.step_count = 0

    def run(self, user_message: str) -> str:
        """Run the agent loop: send message -> handle tool calls -> repeat."""
        self.step_count = 0

        try:
            self.chat.send_message(user_message)
        except Exception as e:
            return f"Error sending message: {str(e)}"

        while self.step_count < MAX_AGENT_STEPS:
            self.step_count += 1
            response = self.chat.history[-1]

            # Check if the model made function calls
            if not response.parts:
                break

            # Check for function calls in the response
            has_function_calls = False
            for part in response.parts:
                if hasattr(part, "function_call") and part.function_call:
                    has_function_calls = True
                    fc = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}

                    # Show what the agent is doing
                    args_str = json.dumps(tool_args, default=str)[:100]
                    if len(json.dumps(tool_args, default=str)) > 100:
                        args_str += "..."
                    print(f"  [{self.step_count}] {tool_name}({args_str})")

                    # Execute the tool
                    result = execute_tool(tool_name, tool_args)

                    # Truncate long results for display
                    display_result = result[:200] + "..." if len(result) > 200 else result
                    print(f"     -> {display_result}")

                    # Send the tool result back to the model
                    try:
                        self.chat.send_message(
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=tool_name,
                                    response={"result": result}
                                )
                            )
                        )
                    except Exception as e:
                        return f"Error processing tool result: {str(e)}"

            if not has_function_calls:
                break

        # Extract final text response
        final_response = ""
        for part in self.chat.history[-1].parts:
            if hasattr(part, "text") and part.text:
                final_response += part.text

        if not final_response:
            final_response = "(Agent completed without a final text response)"

        return final_response


# ============================================================
# CLI Interface
# ============================================================

def print_banner():
    print("=" * 50)
    print("  Gemini AI Agent - Free-tier with tool-calling")
    print("=" * 50)
    print(f"  Model: {GEMINI_MODEL}")
    print(f"  Max steps: {MAX_AGENT_STEPS}")
    print(f"  Type 'quit' or 'exit' to stop.\n")


def interactive_mode():
    """Run the agent in interactive chat mode."""
    print_banner()
    agent = Agent()

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
    agent = Agent()
    response = agent.run(task)
    print(f"\nResult:\n{response}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        single_task_mode(task)
    else:
        interactive_mode()
