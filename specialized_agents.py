"""
Specialized Agents — Codebuff-style multi-agent architecture

Each agent has:
- Its own system prompt
- Its own subset of tools
- Its own behavior rules

The orchestrator routes tasks to the right agent.
"""

import json
import logging

logger = logging.getLogger(__name__)


# ============================================================
# Agent Definitions
# ============================================================

AGENTS = {
    "researcher": {
        "name": "Researcher",
        "description": "Searches the web, scrapes URLs, finds information, checks GitHub",
        "tools": ["web_search", "scrape_url", "github_search_repos", "github_get_repo", "github_get_readme", "github_search_issues", "search_twitter", "scan_coingecko_trending", "scan_pumpfun_new", "scan_pumpfun_top", "detect_viral_trend", "scan_all_viral"],
        "prompt": """You are a research agent. Your ONLY job is to find information.

RULES:
1. ALWAYS use web_search when you need to find something
2. If web_search fails, try scrape_url
3. If scrape_url fails, try different search queries
4. NEVER guess — always search first
5. NEVER say "I can't find it" — keep trying different approaches
6. Give clear, concise answers with sources
7. Plain text only — no markdown, no **, no #

TOOL USAGE:
- Token questions: web_search("token name crypto")
- GitHub questions: github_search_repos or github_get_repo
- Price data: scan_coingecko_trending or detect_viral_trend
- Any URL: scrape_url
- Twitter: search_twitter

You persist until you find the answer. Never give up.""",
    },
    
    "scanner": {
        "name": "Scanner",
        "description": "Scans tokens, checks prices, analyzes risk across chains",
        "tools": ["scan_token", "scan_sol_token", "get_price", "get_sol_price", "get_uniswap_price", "scan_pumpfun_search", "get_gas_tracker", "get_whale_activity", "get_onchain_analytics", "predict_price", "get_social_sentiment", "get_news_sentiment"],
        "prompt": """You are a token scanner agent. Your job is to analyze tokens and give risk assessments.

RULES:
1. Always show token name, price, and risk level
2. Use the right scanner for the chain:
   - Solana tokens: scan_sol_token
   - Ethereum/EVM tokens: scan_token
   - Uniswap tokens: get_uniswap_price
   - Pump.fun tokens: scan_pumpfun_search
3. Give clear risk assessment with reasoning
4. Plain text only — no markdown, no **, no #

SCANNER TOOLS:
- scan_token: EVM tokens (Ethereum, Base, etc.)
- scan_sol_token: Solana tokens
- get_price: Any crypto price
- get_gas_tracker: Gas fees
- get_whale_activity: Whale movements
- predict_price: Price prediction

Always give actionable advice after scanning.""",
    },
    
    "trader": {
        "name": "Trader",
        "description": "Executes trades, manages portfolio, handles swaps",
        "tools": ["buy", "sell", "get_portfolio", "get_trade_history", "get_stats", "get_performance", "jupiter_buy", "jupiter_sell", "robinhood_buy", "robinhood_sell", "get_swap_quote", "get_sol_swap_quote", "add_trading_rule", "get_trading_rules"],
        "prompt": """You are a trading agent. Your job is to execute trades and manage the portfolio.

RULES:
1. ALWAYS verify trades after executing (call get_portfolio)
2. Show portfolio impact before and after trade
3. Ask for confirmation on large trades (>$100)
4. Plain text only — no markdown, no **, no #

TRADING TOOLS:
- buy/sell: Paper trading
- jupiter_buy/sell: Real Solana swaps
- robinhood_buy/sell: Robinhood trades
- get_portfolio: Check holdings
- get_trade_history: See past trades
- add_trading_rule: Set auto-trading rules

Always suggest next steps after trading.""",
    },
    
    "planner": {
        "name": "Planner",
        "description": "Creates step-by-step plans for complex tasks",
        "tools": ["create_plan", "update_plan", "get_current_plan", "suggest_followups"],
        "prompt": """You are a planning agent. Your job is to break complex tasks into clear steps.

RULES:
1. Break complex tasks into 3-7 clear steps
2. Update plan status as you complete each step
3. Show progress to the user
4. Plain text only — no markdown, no **, no #

PLANNING TOOLS:
- create_plan: Create a new plan
- update_plan: Mark steps as done/failed
- get_current_plan: Show current plan
- suggest_followups: Suggest next steps

Always create a plan before starting complex tasks.""",
    },
    
    "coder": {
        "name": "Coder",
        "description": "Fixes bugs, edits code, manages files, restarts bot",
        "tools": ["list_files", "read_file", "write_file", "edit_file", "code_search", "find_function", "find_class", "multi_file_edit", "batch_read_files", "restart_bot", "run_safe_command"],
        "prompt": """You are a coding agent. Your job is to fix bugs and edit code.

RULES:
1. ALWAYS read_file BEFORE edit_file
2. Use code_search to find the problem first
3. Verify changes work after editing
4. Plain text only — no markdown, no **, no #

CODING TOOLS:
- list_files: See project structure
- read_file: Read file contents
- edit_file: Make changes
- code_search: Find patterns in code
- find_function: Locate function definitions
- restart_bot: Apply changes

Always read before editing. Always verify after editing.""",
    },
}


# ============================================================
# Specialized Agent Runner
# ============================================================

class SpecializedAgent:
    """Run a specialized agent with its own tools and prompt."""
    
    def __init__(self, agent_name: str, mistral_client, model: str = "mistral-small-latest"):
        self.agent_name = agent_name
        self.agent = AGENTS.get(agent_name)
        self.client = mistral_client
        self.model = model
    
    def run(self, user_message: str, all_tools: list, tool_map: dict) -> str:
        """Run the agent on a user message."""
        if not self.agent:
            return f"Unknown agent: {self.agent_name}"
        
        # Filter tools to only what this agent needs
        agent_tool_names = set(self.agent["tools"])
        agent_tools = [t for t in all_tools if t["function"]["name"] in agent_tool_names]
        
        if not agent_tools:
            return f"No tools available for agent: {self.agent_name}"
        
        # Build messages
        messages = [
            {"role": "system", "content": self.agent["prompt"]},
            {"role": "user", "content": user_message}
        ]
        
        # Run agent loop (up to 30 steps)
        for step in range(30):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=agent_tools,
                    tool_choice="auto",
                    max_tokens=1000
                )
                
                choice = response.choices[0]
                
                # If no tool calls, return the response
                if not choice.message.tool_calls:
                    return choice.message.content or "(No response)"
                
                # Execute tool calls
                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    # Execute tool
                    if tool_name in tool_map:
                        result = tool_map[tool_name](tool_args)
                        if len(result) > 1500:
                            result = result[:1500] + "... (truncated)"
                    else:
                        result = f"Tool {tool_name} not available"
                    
                    # Add to history
                    messages.append({
                        "role": "assistant",
                        "content": choice.message.content or "",
                        "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tool_name, "arguments": tc.function.arguments}}]
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result
                    })
                
            except Exception as e:
                logger.warning(f"Agent {self.agent_name} step {step} failed: {e}")
                return f"Agent error: {str(e)}"
        
        return "(Max steps reached)"


# ============================================================
# Orchestrator — Routes to the right agent
# ============================================================

class Orchestrator:
    """
    Routes tasks to specialized agents.
    Inspired by Codebuff's orchestrator pattern.
    """
    
    def __init__(self, mistral_client, model: str = "mistral-small-latest"):
        self.client = mistral_client
        self.model = model
        self.agents = {}
        for name in AGENTS:
            self.agents[name] = SpecializedAgent(name, mistral_client, model)
    
    def route_task(self, user_message: str) -> str:
        """Decide which agent should handle this task."""
        msg = user_message.lower()
        
        # Research queries
        if any(w in msg for w in ["search", "check the web", "look up", "find", "what is", "google", "research", "check online", "verify"]):
            return "researcher"
        
        # Scanning/token analysis
        if any(w in msg for w in ["scan", "token", "rug", "risk", "price of", "what's", "how much", "check price"]):
            return "scanner"
        
        # Trading
        if any(w in msg for w in ["buy", "sell", "trade", "swap", "portfolio", "holding", "position"]):
            return "trader"
        
        # Planning
        if any(w in msg for w in ["plan", "setup", "create", "build", "strategy", "step by step"]):
            return "planner"
        
        # Coding
        if any(w in msg for w in ["fix", "edit", "code", "bug", "file", "change", "update", "modify"]):
            return "coder"
        
        # Default to researcher (most common need)
        return "researcher"
    
    def handle_message(self, user_message: str, all_tools: list, tool_map: dict) -> str:
        """Route and execute with the right agent."""
        agent_name = self.route_task(user_message)
        logger.info(f"Routing to agent: {agent_name}")
        
        agent = self.agents.get(agent_name)
        if not agent:
            return f"Unknown agent: {agent_name}"
        
        return agent.run(user_message, all_tools, tool_map)


def create_orchestrator(mistral_client, model: str = "mistral-small-latest") -> Orchestrator:
    """Create an orchestrator instance."""
    return Orchestrator(mistral_client, model)
