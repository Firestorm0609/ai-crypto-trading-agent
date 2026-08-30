"""
Agent Loop — Simplified multi-agent approach

Instead of routing to specialized agents, we use ALL tools
and let the LLM decide what to call. The key improvements:
1. Better system prompt that forces tool usage
2. Retry logic when tools fail
3. Always suggest followups
"""

import json
import logging

logger = logging.getLogger(__name__)


class AgentLoop:
    """
    Simplified agent loop that uses all tools.
    The LLM decides what tools to call, not us.
    """
    
    def __init__(self, mistral_client, model: str = "mistral-small-latest"):
        self.client = mistral_client
        self.model = model
    
    def handle_message(self, user_message: str, tools: list, tool_map: dict) -> str:
        """
        Handle a user message using all available tools.
        """
        # System prompt that forces tool usage
        system_prompt = """You are a crypto trading agent with FULL WEB ACCESS.

CRITICAL RULES:
1. When user asks about a token: ALWAYS use scan_token or web_search to find info
2. When user says "check the web": IMMEDIATELY call web_search
3. When user asks "what is X": Use web_search if you don't know for certain
4. NEVER say "I can't find it" without searching first
5. NEVER give up — if one tool fails, try another approach
6. ALWAYS suggest next steps after completing a task
7. Plain text only — no markdown, no **, no #, no ```

TOOL USAGE:
- Token questions: scan_token, scan_sol_token, web_search
- Price questions: get_price, get_sol_price, web_search
- Trading: buy, sell, jupiter_buy, jupiter_sell
- Research: web_search, scrape_url, github_search_repos
- Always end with: suggest_followups

If you don't know something, SEARCH. If search fails, try different query.
Never say "not found" — keep trying until you find the answer."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # Run agent loop
        for step in range(30):  # Up to 30 steps
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=1000
                )
                
                choice = response.choices[0]
                
                # If no tool calls, return the response
                if not choice.message.tool_calls:
                    return choice.message.content or "(No response)"
                
                # Process tool calls
                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    # Execute tool
                    if tool_name in tool_map:
                        result = tool_map[tool_name](tool_args)
                        if len(result) > 1000:
                            result = result[:1000] + "... (truncated)"
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
                logger.warning(f"Agent step {step} failed: {e}")
                return f"Error: {str(e)}"
        
        return "(Max steps reached)"


def create_agent_loop(mistral_client, model: str = "mistral-small-latest") -> AgentLoop:
    """Create an agent loop instance."""
    return AgentLoop(mistral_client, model)
