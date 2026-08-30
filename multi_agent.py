"""
Multi-Framework Agent Router

Each framework handles what it's best at:

1. Function calling → Fast queries (price, buy, sell)
2. smolagents → Complex code tasks (analysis, multi-step)
3. CrewAI → Research & analysis (team of specialists)
4. LangChain → Prompt management & memory
5. DSPy → Auto-optimized prompts

The router decides which framework to use based on the task.
"""

import json
from config import MISTRAL_API_KEYS, MISTRAL_MODEL


# ============================================================
# Task Router — decides which framework handles what
# ============================================================

TASK_PATTERNS = {
    # Fast tasks → function calling
    "function": [
        "price of", "what is the price", "how much is",
        "buy", "sell", "portfolio", "balance",
        "top coins", "trending", "fear greed",
        "alert", "alerts", "cancel alert",
        "trade history", "stats",
    ],

    # Research tasks → CrewAI (team of agents)
    "crewai": [
        "research", "analyze", "compare", "investigate",
        "news about", "latest on", "what's happening",
        "sentiment", "market analysis", "deep dive",
        "summarize", "report", "overview of",
    ],

    # Code tasks → smolagents (writes Python)
    "smolagents": [
        "calculate", "compute", "analyze data",
        "run code", "execute", "python",
        "complex analysis", "multi-step",
        "plot", "chart data", "statistics",
    ],
}


def classify_task(message: str) -> str:
    """Classify which framework should handle this task."""
    msg_lower = message.lower()

    # Check each pattern
    for framework, patterns in TASK_PATTERNS.items():
        for pattern in patterns:
            if pattern in msg_lower:
                return framework

    # Default: function calling (fastest)
    return "function"


# ============================================================
# Function Calling Agent (fast, 85 tools)
# ============================================================

def run_function_agent(message: str, user_id: int = 0) -> str:
    """Run task using function calling (fastest)."""
    from telegram_bot import TradingAgent
    agent = TradingAgent()
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(agent.handle_message(user_id, message))
        return result
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
# CrewAI Agent (team of specialists)
# ============================================================

def run_crewai_agent(message: str) -> str:
    """Run task using CrewAI (multi-agent team)."""
    from crewai import Agent, Task, Crew, LLM
    from config import MISTRAL_API_KEYS, MISTRAL_MODEL

    llm = LLM(
        model=f"openai/{MISTRAL_MODEL}",
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )

    # Create specialized agents
    researcher = Agent(
        role="Crypto Researcher",
        goal="Research and gather information about cryptocurrencies",
        backstory="Expert crypto researcher with deep market knowledge.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    analyst = Agent(
        role="Market Analyst",
        goal="Analyze market data and provide insights",
        backstory="Skilled market analyst with technical analysis expertise.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    # Create tasks based on the query
    research_task = Task(
        description=f"Research this topic thoroughly: {message}",
        agent=researcher,
        expected_output="Comprehensive research summary with key findings",
    )

    analysis_task = Task(
        description=f"Based on the research, provide analysis and recommendations for: {message}",
        agent=analyst,
        expected_output="Analysis with actionable insights and recommendations",
    )

    # Create crew and run
    crew = Crew(
        agents=[researcher, analyst],
        tasks=[research_task, analysis_task],
        verbose=False,
    )

    result = crew.kickoff()
    return str(result)


# ============================================================
# LangChain Agent (prompt management + memory)
# ============================================================

# Conversation memory per user
conversation_memories = {}

def run_langchain_agent(message: str, user_id: int = 0) -> str:
    """Run task using LangChain (memory + prompt templates)."""
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.messages import HumanMessage, AIMessage

    # Create model
    llm = ChatOpenAI(
        model=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )

    # Get or create memory for this user
    if user_id not in conversation_memories:
        conversation_memories[user_id] = []

    memory = conversation_memories[user_id]

    # Create prompt with memory
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a crypto trading bot. Be concise, use emoji.
        
You have access to these tools:
- get_crypto_price: Get any crypto price
- paper_buy/paper_sell: Paper trading
- web_search: Search the internet
- get_portfolio: Show holdings

Previous context from this conversation:
{memory}

Rules:
1. Use tools proactively
2. Never guess, always search when unsure
3. Keep responses under 100 words
4. Plain text only, no markdown"""),
        ("human", "{question}")
    ])

    # Format memory as string
    memory_str = "\n".join([f"{'User' if isinstance(m, HumanMessage) else 'Bot'}: {m.content[:100]}" for m in memory[-6:]])

    # Run chain
    chain = prompt | llm
    result = chain.invoke({
        "question": message,
        "memory": memory_str,
    })

    # Update memory
    memory.append(HumanMessage(content=message))
    memory.append(AIMessage(content=result.content))

    # Keep memory manageable
    if len(memory) > 20:
        memory[:] = memory[-12:]

    return result.content


# ============================================================
# DSPy Agent (auto-optimized prompts)
# ============================================================

_dspy_module = None

def _setup_dspy():
    """Setup DSPy with Mistral."""
    global _dspy_module
    import dspy

    lm = dspy.LM(
        f"openai/{MISTRAL_MODEL}",
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )
    dspy.configure(lm=lm)

    class CryptoAnalysis(dspy.Signature):
        """Analyze cryptocurrency and provide trading recommendations."""
        question = dspy.InputField()
        answer = dspy.OutputField(desc="crypto analysis with specific recommendations")

    _dspy_module = dspy.ChainOfThought(CryptoAnalysis)

def run_dspy_agent(message: str) -> str:
    """Run task using DSPy (auto-optimized prompts)."""
    global _dspy_module
    if _dspy_module is None:
        _setup_dspy()

    result = _dspy_module(question=message)
    return result.answer


# ============================================================
# Main Router — orchestrates all frameworks
# ============================================================

def run_multi_agent(message: str, user_id: int = 0) -> str:
    """
    Main entry point. Routes to the best framework for the task.

    Flow:
    1. Classify the task
    2. Route to appropriate framework
    3. If framework fails, fallback to next best
    """
    # Classify task
    framework = classify_task(message)

    # Try the selected framework
    try:
        if framework == "function":
            return run_function_agent(message, user_id)
        elif framework == "smolagents":
            return run_smolagents_agent(message)
        elif framework == "crewai":
            return run_crewai_agent(message)
        elif framework == "langchain":
            return run_langchain_agent(message, user_id)
        elif framework == "dspy":
            return run_dspy_agent(message)
    except Exception as e:
        # Fallback chain: smolagents → function → langchain
        pass

    # Fallback chain
    fallbacks = [
        ("smolagents", run_smolagents_agent),
        ("function", lambda m: run_function_agent(m, user_id)),
        ("langchain", lambda m: run_langchain_agent(m, user_id)),
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
    """Get status of all frameworks."""
    # Pass current_mode as parameter to avoid import caching issues

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
