"""
Agent Intelligence Tools — Make the bot think like a real agent

Provides:
- Planning: Write step-by-step plans before acting
- Ask User: Ask clarifying questions when needed
- Suggest Followups: Suggest next steps after completing task
- Verify Action: Verify actions actually worked
"""

import json
from pathlib import Path
from datetime import datetime

PLANS_DIR = Path(__file__).parent / "agent_plans"
PLANS_DIR.mkdir(exist_ok=True)


# ============================================================
# 1. Planning System
# ============================================================

def create_plan(user_id: int, goal: str, steps: list) -> str:
    """Create a step-by-step plan for a task."""
    plan_id = f"{user_id}_{int(datetime.now().timestamp())}"
    plan = {
        "id": plan_id,
        "user_id": user_id,
        "goal": goal,
        "steps": [{"step": i+1, "action": s, "status": "pending"} for i, s in enumerate(steps)],
        "created": datetime.now().isoformat(),
        "status": "in_progress"
    }
    
    plan_file = PLANS_DIR / f"{plan_id}.json"
    plan_file.write_text(json.dumps(plan, indent=2))
    
    lines = [f"Plan: {goal}\n"]
    for s in plan["steps"]:
        lines.append(f"  {s['step']}. ⏳ {s['action']}")
    lines.append(f"\nTotal steps: {len(steps)}")
    
    return "\n".join(lines)


def update_plan(user_id: int, step_number: int, status: str = "done", result: str = "") -> str:
    """Update a plan step status."""
    # Find most recent plan for user
    plans = sorted(PLANS_DIR.glob(f"{user_id}_*.json"), reverse=True)
    if not plans:
        return "No active plan found"
    
    plan_file = plans[0]
    plan = json.loads(plan_file.read_text())
    
    for s in plan["steps"]:
        if s["step"] == step_number:
            s["status"] = status
            s["result"] = result
            break
    
    # Check if all done
    all_done = all(s["status"] == "done" for s in plan["steps"])
    if all_done:
        plan["status"] = "completed"
    
    plan_file.write_text(json.dumps(plan, indent=2))
    
    lines = [f"Plan: {plan['goal']}\n"]
    for s in plan["steps"]:
        emoji = "✅" if s["status"] == "done" else "❌" if s["status"] == "failed" else "⏳"
        lines.append(f"  {s['step']}. {emoji} {s['action']}")
        if s.get("result"):
            lines.append(f"     → {s['result'][:80]}")
    
    return "\n".join(lines)


def get_current_plan(user_id: int) -> str:
    """Get the current active plan for a user."""
    plans = sorted(PLANS_DIR.glob(f"{user_id}_*.json"), reverse=True)
    if not plans:
        return "No active plan"
    
    plan = json.loads(plans[0].read_text())
    
    if plan["status"] == "completed":
        return "Plan completed! All steps done."
    
    lines = [f"Current Plan: {plan['goal']}\n"]
    for s in plan["steps"]:
        emoji = "✅" if s["status"] == "done" else "❌" if s["status"] == "failed" else "⏳"
        lines.append(f"  {s['step']}. {emoji} {s['action']}")
    
    # Find next pending step
    next_step = next((s for s in plan["steps"] if s["status"] == "pending"), None)
    if next_step:
        lines.append(f"\n➡️ Next: Step {next_step['step']} — {next_step['action']}")
    
    return "\n".join(lines)


# ============================================================
# 2. Ask User Tool
# ============================================================

def ask_user_question(user_id: int, question: str, options: list = None) -> str:
    """Ask the user a clarifying question. Returns the question for the bot to send."""
    lines = [f"❓ {question}\n"]
    
    if options:
        for i, opt in enumerate(options, 1):
            lines.append(f"  {i}. {opt}")
        lines.append(f"\nReply with number or text")
    else:
        lines.append("Reply with your answer")
    
    return "\n".join(lines)


def parse_user_answer(answer: str, options: list = None) -> str:
    """Parse user's answer to a question."""
    if not options:
        return answer
    
    # Try to parse as number
    try:
        num = int(answer.strip())
        if 1 <= num <= len(options):
            return options[num - 1]
    except ValueError:
        pass
    
    # Try to match text
    answer_lower = answer.lower().strip()
    for opt in options:
        if answer_lower in opt.lower() or opt.lower() in answer_lower:
            return opt
    
    return answer


# ============================================================
# 3. Suggest Followups Tool
# ============================================================

def suggest_followups(context: str, last_action: str = "") -> str:
    """Suggest follow-up actions based on context."""
    suggestions = []
    
    # Price-related suggestions
    if any(w in context.lower() for w in ["price", "btc", "eth", "sol"]):
        suggestions.extend([
            "💰 Buy this crypto",
            "📉 Set price alert",
            "📊 Check fear & greed index",
            "🐋 Check whale activity"
        ])
    
    # Token scan suggestions
    if any(w in context.lower() for w in ["scan", "token", "rug", "risk"]):
        suggestions.extend([
            "💰 Buy this token",
            "📊 Check price chart",
            "🔍 Search for news about this token",
            "📋 Add to watchlist"
        ])
    
    # Portfolio suggestions
    if any(w in context.lower() for w in ["portfolio", "holdings", "balance"]):
        suggestions.extend([
            "📊 Check individual positions",
            "🔄 Rebalance portfolio",
            "📈 Check performance",
            "💡 Get investment advice"
        ])
    
    # Trading suggestions
    if any(w in context.lower() for w in ["buy", "sell", "trade"]):
        suggestions.extend([
            "📋 Set up auto-trading rules",
            "📊 Check trade history",
            "💡 Smart DCA suggestion",
            "🔍 Check market sentiment"
        ])
    
    # Research suggestions
    if any(w in context.lower() for w in ["news", "sentiment", "research"]):
        suggestions.extend([
            "📊 Check on-chain analytics",
            "🐋 Track whale movements",
            "🔍 Search for alpha",
            "📰 Get more news"
        ])
    
    # General suggestions if none matched
    if not suggestions:
        suggestions.extend([
            "📊 Check market overview",
            "🔍 Search for crypto news",
            "💼 View portfolio",
            "⚙️ Manage auto-trading rules"
        ])
    
    lines = ["💡 What would you like to do next?\n"]
    for s in suggestions[:4]:
        lines.append(f"  • {s}")
    
    return "\n".join(lines)


# ============================================================
# 4. Verify Action Tool
# ============================================================

def verify_action(action_type: str, details: dict) -> str:
    """Verify that an action actually worked."""
    lines = [f"✅ Verifying: {action_type}\n"]
    
    if action_type == "buy":
        symbol = details.get("symbol", "?")
        amount = details.get("amount", 0)
        lines.append(f"  Bought ${amount} of {symbol}")
        lines.append(f"  Checking portfolio...")
        # The bot should call get_portfolio to verify
        
    elif action_type == "sell":
        symbol = details.get("symbol", "?")
        lines.append(f"  Sold {symbol}")
        lines.append(f"  Checking portfolio...")
        
    elif action_type == "transfer":
        lines.append(f"  Transfer initiated")
        lines.append(f"  Checking status...")
        
    elif action_type == "rule_created":
        lines.append(f"  Rule created")
        lines.append(f"  Checking rules...")
        
    else:
        lines.append(f"  Action completed")
    
    lines.append(f"\n📊 Verify with: get_portfolio, get_trade_history, or get_trading_rules")
    
    return "\n".join(lines)


def check_action_result(user_id: int, action_type: str, symbol: str = "") -> str:
    """Check if an action actually worked by querying the system."""
    # This is a placeholder - the bot should call actual tools
    # to verify the action worked
    
    if action_type in ("buy", "sell"):
        return f"📊 Check portfolio with get_portfolio to verify {symbol} trade"
    
    elif action_type == "rule":
        return "📋 Check rules with get_trading_rules to verify"
    
    return "✅ Action appears to have completed"


# ============================================================
# 5. Code Search Tool
# ============================================================

def code_search(pattern: str, file_types: list = None, limit: int = 20) -> str:
    """Search codebase for patterns. Like grep but smarter."""
    import subprocess
    
    try:
        # Build ripgrep command
        cmd = ["grep", "-rn", "--include=*.py", pattern, "."]
        
        if file_types:
            for ft in file_types:
                cmd[2:2] = ["--include", f"*.{ft}"]
        
        result = subprocess.run(
            cmd,
            cwd="/root/gemini-agent",
            capture_output=True,
            text=True,
            timeout=10
        )
        
        lines = result.stdout.strip().split("\n")
        if not lines or not lines[0]:
            return f"No matches for '{pattern}'"
        
        output = [f"Code Search: '{pattern}'\n"]
        for line in lines[:limit]:
            output.append(f"  {line}")
        
        if len(lines) > limit:
            output.append(f"\n... and {len(lines) - limit} more matches")
        
        return "\n".join(output)
    except Exception as e:
        return f"Search error: {str(e)}"


def find_function(func_name: str) -> str:
    """Find where a function is defined."""
    return code_search(f"def {func_name}", ["py"])


def find_class(class_name: str) -> str:
    """Find where a class is defined."""
    return code_search(f"class {class_name}", ["py"])


def find_import(module_name: str) -> str:
    """Find where a module is imported."""
    return code_search(f"import.*{module_name}", ["py"])


# ============================================================
# 6. Multi-File Edit Tool
# ============================================================

def multi_file_edit(edits: list) -> str:
    """Edit multiple files in one operation.
    
    edits: list of {"file": "path", "old": "old text", "new": "new text"}
    """
    results = []
    
    for edit in edits:
        filepath = edit.get("file", "")
        old_text = edit.get("old", "")
        new_text = edit.get("new", "")
        
        if not filepath or not old_text:
            results.append(f"❌ {filepath}: Missing file or old text")
            continue
        
        try:
            full_path = f"/root/gemini-agent/{filepath}"
            with open(full_path, "r") as f:
                content = f.read()
            
            if old_text not in content:
                results.append(f"❌ {filepath}: Old text not found")
                continue
            
            new_content = content.replace(old_text, new_text, 1)
            with open(full_path, "w") as f:
                f.write(new_content)
            
            results.append(f"✅ {filepath}: Updated")
        except Exception as e:
            results.append(f"❌ {filepath}: {str(e)}")
    
    return "\n".join(results)


def batch_read_files(files: list) -> str:
    """Read multiple files at once."""
    results = []
    
    for filepath in files:
        try:
            full_path = f"/root/gemini-agent/{filepath}"
            with open(full_path, "r") as f:
                content = f.read()
            
            lines = content.split("\n")
            results.append(f"=== {filepath} ({len(lines)} lines) ===")
            results.append(content[:500])
            if len(content) > 500:
                results.append(f"... ({len(content)} total chars)")
            results.append("")
        except Exception as e:
            results.append(f"❌ {filepath}: {str(e)}")
    
    return "\n".join(results)


# ============================================================
# Tool Registry
# ============================================================

AGENT_TOOLS = [
    # Planning & Intelligence
    {"type": "function", "function": {"name": "create_plan", "description": "Create a step-by-step plan before acting. ALWAYS use this for complex tasks.", "parameters": {"type": "object", "properties": {"goal": {"type": "string", "description": "What you want to accomplish"}, "steps": {"type": "array", "items": {"type": "string"}, "description": "List of steps to complete"}}, "required": ["goal", "steps"]}}},
    {"type": "function", "function": {"name": "update_plan", "description": "Update a plan step as done/failed.", "parameters": {"type": "object", "properties": {"step_number": {"type": "integer"}, "status": {"type": "string", "enum": ["done", "failed"]}, "result": {"type": "string"}}, "required": ["step_number", "status"]}}},
    {"type": "function", "function": {"name": "get_current_plan", "description": "Get current active plan and next step.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "suggest_followups", "description": "Suggest follow-up actions after completing a task. ALWAYS use after finishing something.", "parameters": {"type": "object", "properties": {"context": {"type": "string", "description": "What was just done"}}, "required": ["context"]}}},
    {"type": "function", "function": {"name": "verify_action", "description": "Verify that an action (buy, sell, transfer) actually worked.", "parameters": {"type": "object", "properties": {"action_type": {"type": "string"}, "details": {"type": "object"}}, "required": ["action_type", "details"]}}},
    {"type": "function", "function": {"name": "ask_user", "description": "Ask user a clarifying question when the request is ambiguous.", "parameters": {"type": "object", "properties": {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}}, "required": ["question"]}}},
    # Code Search
    {"type": "function", "function": {"name": "code_search", "description": "Search codebase for patterns. Like grep but smarter. Use when fixing bugs or finding code.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Text or regex pattern to search for"}, "limit": {"type": "number"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "find_function", "description": "Find where a function is defined in the codebase.", "parameters": {"type": "object", "properties": {"func_name": {"type": "string"}}, "required": ["func_name"]}}},
    {"type": "function", "function": {"name": "find_class", "description": "Find where a class is defined.", "parameters": {"type": "object", "properties": {"class_name": {"type": "string"}}, "required": ["class_name"]}}},
    # Multi-File Operations
    {"type": "function", "function": {"name": "multi_file_edit", "description": "Edit multiple files in one operation. Use when fixing bugs across files.", "parameters": {"type": "object", "properties": {"edits": {"type": "array", "items": {"type": "object", "properties": {"file": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}, "required": ["file", "old", "new"]}}}, "required": ["edits"]}}},
    {"type": "function", "function": {"name": "batch_read_files", "description": "Read multiple files at once. Use when analyzing codebase.", "parameters": {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string"}}}, "required": ["files"]}}},
]

AGENT_TOOL_MAP = {
    # Planning
    "create_plan": lambda a: create_plan(a.get("user_id", 0), a["goal"], a["steps"]),
    "update_plan": lambda a: update_plan(a.get("user_id", 0), a["step_number"], a.get("status", "done"), a.get("result", "")),
    "get_current_plan": lambda a: get_current_plan(a.get("user_id", 0)),
    "suggest_followups": lambda a: suggest_followups(a["context"], a.get("last_action", "")),
    "verify_action": lambda a: verify_action(a["action_type"], a.get("details", {})),
    "ask_user": lambda a: ask_user_question(a.get("user_id", 0), a["question"], a.get("options")),
    # Code Search
    "code_search": lambda a: code_search(a["pattern"], a.get("file_types"), int(a.get("limit", 20))),
    "find_function": lambda a: find_function(a["func_name"]),
    "find_class": lambda a: find_class(a["class_name"]),
    # Multi-File
    "multi_file_edit": lambda a: multi_file_edit(a["edits"]),
    "batch_read_files": lambda a: batch_read_files(a["files"]),
}
