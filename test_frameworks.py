"""
Demo: All 4 AI Frameworks installed in the bot.

1. LangChain — Prompt templates, memory, tool chains
2. smolagents — Agent writes Python code
3. CrewAI — Multiple AI agents as a team
4. DSPy — Auto-optimizes prompts
"""

from config import MISTRAL_API_KEYS, MISTRAL_MODEL


def demo_langchain():
    """LangChain: Prompt templates and memory."""
    print("=" * 60)
    print("1. LANGCHAIN — Prompt Templates & Memory")
    print("=" * 60)

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    # Create model
    llm = ChatOpenAI(
        model=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )

    # Create prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a crypto expert. Be concise."),
        ("user", "{question}")
    ])

    # Chain: prompt → model
    chain = prompt | llm

    # Run
    result = chain.invoke({"question": "What is Bitcoin?"})
    print(f"Result: {result.content[:200]}")
    print()
    print("What LangChain adds:")
    print("- Version-controlled prompts")
    print("- Memory between messages")
    print("- Tool chaining")
    print()


def demo_smolagents():
    """smolagents: Agent writes Python code."""
    print("=" * 60)
    print("2. SMOLAGENTS — Code-Writing Agent")
    print("=" * 60)

    from smolagents import CodeAgent, OpenAIModel, tool

    model = OpenAIModel(
        model_id=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEYS[0],
        api_base="https://api.mistral.ai/v1",
    )

    @tool
    def get_crypto_price(coin: str) -> str:
        """Get price for a cryptocurrency.

        Args:
            coin: The cryptocurrency symbol (e.g. 'btc', 'eth')
        """
        import urllib.request, json
        aliases = {'btc': 'bitcoin', 'eth': 'ethereum', 'sol': 'solana'}
        coin_id = aliases.get(coin.lower(), coin.lower())
        url = f'https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        price = data.get(coin_id, {}).get('usd', 0)
        return f'{coin.upper()}: ${price:,.2f}'

    agent = CodeAgent(
        tools=[get_crypto_price],
        model=model,
        max_steps=3,
    )

    result = agent.run("What is the price of bitcoin?")
    print(f"Result: {result}")
    print()
    print("What smolagents adds:")
    print("- Agent writes code to solve problems")
    print("- No tool limits")
    print("- Creative combinations")
    print()


def demo_crewai():
    """CrewAI: Multiple AI agents as a team."""
    print("=" * 60)
    print("3. CREWAI — Multi-Agent Team")
    print("=" * 60)

    from crewai import Agent, Task, Crew
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )

    # Create agents (roles)
    researcher = Agent(
        role="Crypto Researcher",
        goal="Research cryptocurrency news and trends",
        backstory="You are an expert crypto researcher.",
        llm=llm,
        verbose=False,
    )

    analyst = Agent(
        role="Market Analyst",
        goal="Analyze market data and provide insights",
        backstory="You are a skilled market analyst.",
        llm=llm,
        verbose=False,
    )

    # Create tasks
    research_task = Task(
        description="Research the latest news about Bitcoin",
        agent=researcher,
        expected_output="Summary of recent Bitcoin news",
    )

    analysis_task = Task(
        description="Based on the research, provide a market analysis",
        agent=analyst,
        expected_output="Market analysis and recommendation",
    )

    # Create crew (team)
    crew = Crew(
        agents=[researcher, analyst],
        tasks=[research_task, analysis_task],
        verbose=False,
    )

    result = crew.kickoff()
    print(f"Result: {str(result)[:300]}")
    print()
    print("What CrewAI adds:")
    print("- Multiple specialized agents")
    print("- Agents work together as a team")
    print("- Each agent has a role and expertise")
    print()


def demo_dspy():
    """DSPy: Auto-optimizes prompts."""
    print("=" * 60)
    print("4. DSPy — Auto-Optimized Prompts")
    print("=" * 60)

    import dspy

    # Configure DSPy to use Mistral
    lm = dspy.LM(
        f"openai/{MISTRAL_MODEL}",
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
    )
    dspy.configure(lm=lm)

    # Define a signature (what the AI should do)
    class CryptoAnalysis(dspy.Signature):
        """Analyze cryptocurrency and provide recommendation."""
        question = dspy.InputField()
        answer = dspy.OutputField(desc="crypto analysis and recommendation")

    # Create a module
    analyze = dspy.ChainOfThought(CryptoAnalysis)

    # Run
    result = analyze(question="Should I buy Bitcoin right now?")
    print(f"Result: {result.answer[:300]}")
    print()
    print("What DSPy adds:")
    print("- Automatically tests prompt variations")
    print("- Picks the best-performing prompt")
    print("- No manual prompt engineering")
    print()


if __name__ == "__main__":
    print("AI FRAMEWORKS DEMO")
    print("=" * 60)
    print()

    demos = [
        ("LangChain", demo_langchain),
        ("smolagents", demo_smolagents),
        ("CrewAI", demo_crewai),
        ("DSPy", demo_dspy),
    ]

    for name, demo_fn in demos:
        try:
            demo_fn()
        except Exception as e:
            print(f"Error in {name}: {e}")
            print()
