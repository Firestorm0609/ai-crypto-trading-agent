"""
Delegation — the main agent can spawn a specialized subagent mid-task.

Codebuff-style: instead of a keyword router deciding upfront, the main
LLM gets a `delegate` tool. When it hits something a specialist handles
better (deep research, code editing, planning), it calls:

    delegate(agent="researcher", task="find the contract address for X",
             context="user is trying to buy but scan failed")

The subagent runs its own tool loop with ONLY its scoped tools, sees the
conversation summary for continuity, and returns its findings as a tool
result. The main agent stays in control and answers the user.

Safety: recursion is blocked (subagents can't delegate), and depth is
capped. All real execution still goes through registry.dispatch_tool.
"""

import json
import logging

logger = logging.getLogger(__name__)

from config import MISTRAL_API_KEYS, MISTRAL_MODEL


# ============================================================
# Subagent definitions (scoped tool families from tool_scoping)
# ============================================================

SUBAGENTS = {
    "researcher": {
        "description": "Deep web research: search, scrape, GitHub, Twitter, trends",
        "families": ["trend_research", "market_data"],
        "prompt": (
            "You are a research subagent. Find the requested information "
            "using web_search, scrape_url, and related tools. Try multiple "
            "queries if the first fails. Return a concise factual summary "
            "with sources. Plain text, under 150 words."
        ),
    },
    "scanner": {
        "description": "Token safety and on-chain analysis: rug checks, whales, sentiment",
        "families": ["risk_scanning", "market_data"],
        "prompt": (
            "You are a token analysis subagent. Scan the token for risk "
            "(scan_token / scan_sol_token), check prices and on-chain data, "
            "and give a clear risk verdict with reasoning. Plain text, "
            "under 150 words."
        ),
    },
    "planner": {
        "description": "Breaks complex multi-step tasks into an explicit plan",
        "families": ["meta", "portfolio"],
        "prompt": (
            "You are a planning subagent. Use create_plan to structure the "
            "task into 3-7 steps, then update_plan as you assess each one. "
            "Return the numbered plan and what's next. Plain text."
        ),
    },
    "coder": {
        "description": "Reads and edits the bot's own code, runs safe commands",
        "families": ["coding"],
        "prompt": (
            "You are a coding subagent. ALWAYS read_file before edit_file. "
            "Use code_search to locate things. Verify after editing. "
            "Report exactly what you changed. Plain text."
        ),
    },
}

DELEGATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "delegate",
        "description": (
            "Delegate a focused subtask to a specialist subagent. Use when "
            "a task needs deep research, token scanning, planning, or code "
            "edits. The subagent gets its own tools and returns its findings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": sorted(SUBAGENTS.keys()),
                    "description": "Which specialist to use",
                },
                "task": {
                    "type": "string",
                    "description": "Exactly what the subagent should do",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant conversation context for continuity",
                },
            },
            "required": ["agent", "task"],
        },
    },
}

MAX_SUBAGENT_STEPS = 12


def _mistral_chat(messages, tools=None):
    """One Mistral call. Returns the response message dict."""
    from openai import OpenAI
    client = OpenAI(
        api_key=MISTRAL_API_KEYS[0],
        base_url="https://api.mistral.ai/v1",
        max_retries=0,
        timeout=45.0,
    )
    kwargs = dict(
        model=MISTRAL_MODEL,
        messages=messages,
        tool_choice="auto",
        max_tokens=1500,
        temperature=0.4,
    )
    if tools is not None:
        kwargs["tools"] = tools
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    return {
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
            for tc in (msg.tool_calls or [])
        ],
    }


def run_subagent(agent_name: str, task: str, context: str = "",
                 user_id: int = 0, max_steps: int = MAX_SUBAGENT_STEPS) -> str:
    """
    Run one specialized subagent on a task. Called via the delegate tool
    (or directly by tests). Returns the subagent's final text.
    """
    spec = SUBAGENTS.get(agent_name)
    if not spec:
        return f"Unknown subagent: {agent_name}. Available: {', '.join(sorted(SUBAGENTS))}"

    # Import here to avoid circular imports at module load
    import tool_scoping
    import registry

    # Scoped tool set: only this agent's families + the real dispatcher
    sub_tools = tool_scoping.select_tools(
        task,
        registry.TOOLS,
        use_llm=False,  # subagents get deterministic scoping
    )
    # Narrow further to the agent's own families
    allow = set()
    for fam in spec["families"]:
        allow |= tool_scoping.TOOL_FAMILIES.get(fam, set())
    sub_tools = [t for t in sub_tools if t["function"]["name"] in allow]
    if not sub_tools:
        return f"Subagent {agent_name} has no tools available"

    messages = [
        {"role": "system", "content": spec["prompt"]},
    ]
    if context:
        messages.append({
            "role": "user",
            "content": f"[Conversation context]\n{context}",
        })
    messages.append({"role": "user", "content": task})

    try:
        for _step in range(max_steps):
            msg = _mistral_chat(messages, tools=sub_tools)

            if not msg["tool_calls"]:
                return msg["content"] or "(subagent returned no text)"

            messages.append({
                "role": "assistant",
                "content": msg["content"],
                "tool_calls": msg["tool_calls"],
            })

            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                if name == "delegate":
                    result = "(delegation is not allowed inside subagents)"
                else:
                    try:
                        args = json.loads(tc["function"]["arguments"]) \
                            if tc["function"]["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = registry.dispatch_tool(name, args, user_id=user_id)
                    except Exception as e:
                        result = f"Tool error: {e}"
                result = str(result)[:2000]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        return "(subagent hit max steps without a final answer)"
    except Exception as e:
        logger.warning(f"Subagent {agent_name} failed: {e}")
        return f"Subagent error: {e}"


def dispatch_delegate(args: dict, user_id: int = 0) -> str:
    """Entry point used by registry.dispatch_tool for the delegate tool."""
    return run_subagent(
        agent_name=str(args.get("agent", "")),
        task=str(args.get("task", "")),
        context=str(args.get("context", "") or ""),
        user_id=user_id,
    )
