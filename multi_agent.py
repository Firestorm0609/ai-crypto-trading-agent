"""
Multi-Framework Agent Router

Routes tasks to the agent style that handles them best:

1. function  → Fast tool-calling queries (price, buy, sell) — the main
               TradingAgent loop in telegram_bot.py
2. smolagents → Complex code tasks (LLM writes Python)

CrewAI / LangChain / DSPy routing was removed: those packages are not
installed, so those paths could never run.
"""

from config import MISTRAL_MODEL


# ============================================================
# Task Router — decides which framework handles what
# ============================================================

TASK_PATTERNS = {
    # Code tasks → smolagents (writes Python)
    "smolagents": [
        "calculate", "compute", "analyze data",
        "run code", "execute", "python",
        "complex analysis", "multi-step",
        "plot", "chart data", "statistics",
    ],
}

# Everything not matching the above is a fast tool-calling task.
DEFAULT_FRAMEWORK = "function"


def classify_task(message: str) -> str:
    """Classify which framework should handle this task."""
    msg_lower = message.lower()

    for framework, patterns in TASK_PATTERNS.items():
        for pattern in patterns:
            if pattern in msg_lower:
                return framework

    return DEFAULT_FRAMEWORK


# ============================================================
# Function Calling Agent (fast path — reuses the main loop)
# ============================================================

def run_function_agent(message: str, user_id: int = 0) -> str:
    """Run task using the main TradingAgent loop (fastest)."""
    import asyncio
    from telegram_bot import TradingAgent

    agent = TradingAgent()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(agent.handle_message(user_id, message))
    finally:
        loop.close()


# ============================================================
# smolagents Agent (writes Python code)
# ============================================================

def run_smolagents_agent(message: str) -> str:
    """Run task using smolagents (code-writing)."""
    from smolagents_agent import run_smolagents_query
    return run_smolagents_query(message)


# ============================================================
# Main Router — orchestrates the frameworks
# ============================================================

def run_multi_agent(message: str, user_id: int = 0) -> str:
    """
    Main entry point. Routes to the best framework for the task.

    Flow:
    1. Classify the task
    2. Route to appropriate framework
    3. If framework fails, fall back to the other one
    """
    framework = classify_task(message)

    try:
        if framework == "function":
            return run_function_agent(message, user_id)
        if framework == "smolagents":
            return run_smolagents_agent(message)
    except Exception:
        pass

    # Fallback: the other framework
    fallbacks = [
        ("smolagents", run_smolagents_agent),
        ("function", lambda m: run_function_agent(m, user_id)),
    ]

    for name, runner in fallbacks:
        if name == framework:
            continue  # Skip the one that already failed
        try:
            return runner(message)
        except Exception:
            continue

    return "All frameworks failed. Try again later."


# ============================================================
# Framework Status
# ============================================================

def get_framework_status(current_mode: str = "function") -> str:
    """Get status of available agent modes."""

    frameworks = {
        "function": "Fast queries (price, buy, sell)",
        "smolagents": "Code tasks (analysis, calculations)",
        "multi": "All frameworks working together",
    }

    lines = ["AI Agent Status:\n"]
    lines.append(f"Active Mode: {current_mode}")
    lines.append("")
    lines.append("Available Modes:")
    for name, desc in frameworks.items():
        marker = " ← ACTIVE" if name == current_mode else ""
        lines.append(f"  {name}: {desc}{marker}")

    lines.append("")
    lines.append("Switch: /agent function|smolagents|multi")
    lines.append("Or say: switch to multi / switch to smolagents")

    return "\n".join(lines)
