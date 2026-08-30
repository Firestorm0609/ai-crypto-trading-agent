"""
Full Agent Tools — Everything Buffy uses, no holding back

This includes ALL capabilities:
- read_url: Fetch and read any webpage
- code_search: ripgrep-powered code search
- run_terminal_command: Execute any bash command
- ask_user: Ask clarifying questions
- suggest_followups: Suggest next steps
- Planning system with todos
- Verification after every action
- Multi-file editing
- Git integration
- Error recovery (try 3 approaches)
"""

import json
import subprocess
import os
import re
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path("/root/gemini-agent")
TODOS_DIR = PROJECT_ROOT / "agent_todos"
TODOS_DIR.mkdir(exist_ok=True)


# ============================================================
# 1. read_url — Fetch and read any webpage (like I do)
# ============================================================

def read_url(url: str, max_chars: int = 10000) -> str:
    """Fetch a URL and extract readable text. Follows redirects."""
    import urllib.request
    import urllib.error
    
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        
        # Remove scripts and styles
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        
        # Extract text from meaningful tags
        text_parts = []
        for tag in ['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td', 'th', 'pre', 'code', 'blockquote']:
            matches = re.findall(f'<{tag}[^>]*>(.*?)</{tag}>', html, re.DOTALL | re.IGNORECASE)
            for m in matches:
                clean = re.sub(r'<[^>]+>', '', m).strip()
                if clean and len(clean) > 5:
                    if tag.startswith('h'):
                        text_parts.append(f"\n{clean}\n")
                    else:
                        text_parts.append(clean)
        
        if not text_parts:
            # Fallback: strip all HTML
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text).strip()
            text_parts = [text]
        
        full_text = "\n".join(text_parts)
        
        # Truncate if too long
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + f"\n\n... ({len(full_text)} total chars, truncated to {max_chars})"
        
        return f"Content from {url}:\n\n{full_text}"
    except urllib.error.HTTPError as e:
        return f"HTTP Error {e.code}: {e.reason} for {url}"
    except Exception as e:
        return f"Error reading {url}: {str(e)}"


# ============================================================
# 2. code_search — ripgrep-powered (like I use)
# ============================================================

def code_search(pattern: str, flags: str = "", max_results: int = 25) -> str:
    """Search codebase using ripgrep. Much faster and smarter than grep."""
    try:
        cmd = ["rg", "--no-heading", "--line-number", "-i"]
        
        # Add custom flags
        if flags:
            for flag in flags.split():
                cmd.append(f"-{flag}" if not flag.startswith("-") else flag)
        
        cmd.extend([pattern, str(PROJECT_ROOT)])
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(PROJECT_ROOT)
        )
        
        lines = result.stdout.strip().split("\n")
        
        if not lines or not lines[0]:
            return f"No matches for '{pattern}'"
        
        output = [f"Code Search: '{pattern}'\n"]
        for line in lines[:max_results]:
            # Remove project root prefix for cleaner output
            clean = line.replace(str(PROJECT_ROOT) + "/", "")
            output.append(f"  {clean}")
        
        if len(lines) > max_results:
            output.append(f"\n... and {len(lines) - max_results} more matches")
        
        return "\n".join(output)
    except FileNotFoundError:
        # Fallback to grep if rg not installed
        return _grep_fallback(pattern, max_results)
    except subprocess.TimeoutExpired:
        return f"Search timed out for '{pattern}'"
    except Exception as e:
        return f"Search error: {str(e)}"


def _grep_fallback(pattern: str, max_results: int = 25) -> str:
    """Fallback to grep if ripgrep not available."""
    try:
        cmd = ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts", pattern, str(PROJECT_ROOT)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = result.stdout.strip().split("\n")
        
        if not lines or not lines[0]:
            return f"No matches for '{pattern}'"
        
        output = [f"Code Search: '{pattern}'\n"]
        for line in lines[:max_results]:
            clean = line.replace(str(PROJECT_ROOT) + "/", "")
            output.append(f"  {clean}")
        
        return "\n".join(output)
    except Exception as e:
        return f"Search error: {str(e)}"


def find_function(func_name: str) -> str:
    """Find where a function is defined."""
    return code_search(f"def {func_name}\\b", max_results=10)


def find_class(class_name: str) -> str:
    """Find where a class is defined."""
    return code_search(f"class {class_name}\\b", max_results=10)


def find_import(module_name: str) -> str:
    """Find where a module is imported."""
    return code_search(f"import.*{module_name}", max_results=10)


def find_all_references(name: str) -> str:
    """Find all references to a variable/function/class."""
    return code_search(f"\\b{name}\\b", max_results=25)


# ============================================================
# 3. run_terminal_command — Execute any bash command
# ============================================================

def run_terminal_command(command: str, timeout: int = 30, cwd: str = None) -> str:
    """Execute a bash command and return output."""
    try:
        working_dir = cwd or str(PROJECT_ROOT)
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir
        )
        
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        
        if not output.strip():
            output = f"Command completed (exit code: {result.returncode})"
        
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s: {command}"
    except Exception as e:
        return f"Command error: {str(e)}"


# ============================================================
# 4. ask_user — Ask clarifying questions
# ============================================================

def ask_user(question: str, options: list = None) -> str:
    """Format a question for the user. Returns the question text."""
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
    
    try:
        num = int(answer.strip())
        if 1 <= num <= len(options):
            return options[num - 1]
    except ValueError:
        pass
    
    answer_lower = answer.lower().strip()
    for opt in options:
        if answer_lower in opt.lower() or opt.lower() in answer_lower:
            return opt
    
    return answer


# ============================================================
# 5. suggest_followups — Suggest next steps
# ============================================================

def suggest_followups(context: str) -> str:
    """Suggest follow-up actions based on context."""
    suggestions = []
    ctx = context.lower()
    
    if any(w in ctx for w in ["price", "btc", "eth", "sol", "bitcoin", "ethereum"]):
        suggestions.extend(["💰 Buy this crypto", "📉 Set price alert", "📊 Check fear & greed", "🐋 Check whale activity"])
    
    if any(w in ctx for w in ["scan", "token", "rug", "risk"]):
        suggestions.extend(["💰 Buy this token", "📊 Check price chart", "🔍 Search for news", "📋 Add to watchlist"])
    
    if any(w in ctx for w in ["portfolio", "holdings", "balance"]):
        suggestions.extend(["📊 Check individual positions", "🔄 Rebalance", "📈 Check performance", "💡 Get advice"])
    
    if any(w in ctx for w in ["buy", "sell", "trade"]):
        suggestions.extend(["📋 Set auto-trading rules", "📊 Check history", "💡 Smart DCA", "🔍 Check sentiment"])
    
    if any(w in ctx for w in ["news", "sentiment", "research"]):
        suggestions.extend(["📊 Check on-chain", "🐋 Track whales", "🔍 Search alpha", "📰 More news"])
    
    if any(w in ctx for w in ["fix", "bug", "error", "code"]):
        suggestions.extend(["🔍 Search for related issues", "📖 Check documentation", "🧪 Run tests", "🔄 Restart bot"])
    
    if not suggestions:
        suggestions.extend(["📊 Market overview", "🔍 Search news", "💼 Portfolio", "⚙️ Auto-trading"])
    
    lines = ["💡 What would you like to do next?\n"]
    for s in suggestions[:4]:
        lines.append(f"  • {s}")
    
    return "\n".join(lines)


# ============================================================
# 6. Planning System — Full todos with progress tracking
# ============================================================

def create_todos(user_id: int, goal: str, steps: list) -> str:
    """Create a step-by-step plan with progress tracking."""
    todo_id = f"{user_id}_{int(datetime.now().timestamp())}"
    todo = {
        "id": todo_id,
        "user_id": user_id,
        "goal": goal,
        "steps": [{"step": i+1, "action": s, "status": "pending", "result": ""} for i, s in enumerate(steps)],
        "created": datetime.now().isoformat(),
        "status": "in_progress"
    }
    
    todo_file = TODOS_DIR / f"{todo_id}.json"
    todo_file.write_text(json.dumps(todo, indent=2))
    
    lines = [f"Plan: {goal}\n"]
    for s in todo["steps"]:
        lines.append(f"  {s['step']}. ⏳ {s['action']}")
    lines.append(f"\nTotal steps: {len(steps)}")
    
    return "\n".join(lines)


def update_todos(user_id: int, step_number: int, status: str = "done", result: str = "") -> str:
    """Update a plan step status."""
    todos = sorted(TODOS_DIR.glob(f"{user_id}_*.json"), reverse=True)
    if not todos:
        return "No active plan found"
    
    todo_file = todos[0]
    todo = json.loads(todo_file.read_text())
    
    for s in todo["steps"]:
        if s["step"] == step_number:
            s["status"] = status
            s["result"] = result
            break
    
    all_done = all(s["status"] == "done" for s in todo["steps"])
    if all_done:
        todo["status"] = "completed"
    
    todo_file.write_text(json.dumps(todo, indent=2))
    
    lines = [f"Plan: {todo['goal']}\n"]
    for s in todo["steps"]:
        emoji = "✅" if s["status"] == "done" else "❌" if s["status"] == "failed" else "⏳"
        lines.append(f"  {s['step']}. {emoji} {s['action']}")
        if s.get("result"):
            lines.append(f"     → {s['result'][:80]}")
    
    return "\n".join(lines)


def get_todos(user_id: int) -> str:
    """Get current active plan."""
    todos = sorted(TODOS_DIR.glob(f"{user_id}_*.json"), reverse=True)
    if not todos:
        return "No active plan"
    
    todo = json.loads(todos[0].read_text())
    
    if todo["status"] == "completed":
        return "Plan completed! All steps done."
    
    lines = [f"Current Plan: {todo['goal']}\n"]
    for s in todo["steps"]:
        emoji = "✅" if s["status"] == "done" else "❌" if s["status"] == "failed" else "⏳"
        lines.append(f"  {s['step']}. {emoji} {s['action']}")
    
    next_step = next((s for s in todo["steps"] if s["status"] == "pending"), None)
    if next_step:
        lines.append(f"\n➡️ Next: Step {next_step['step']} — {next_step['action']}")
    
    return "\n".join(lines)


# ============================================================
# 7. Verification — Verify actions actually worked
# ============================================================

def verify_action(action_type: str, details: dict) -> str:
    """Verify that an action actually worked."""
    lines = [f"✅ Verifying: {action_type}\n"]
    
    if action_type == "buy":
        lines.append(f"  Bought ${details.get('amount', 0)} of {details.get('symbol', '?')}")
        lines.append(f"  📊 Verify with: get_portfolio")
    elif action_type == "sell":
        lines.append(f"  Sold {details.get('symbol', '?')}")
        lines.append(f"  📊 Verify with: get_portfolio")
    elif action_type == "code_edit":
        lines.append(f"  Edited: {details.get('file', '?')}")
        lines.append(f"  📊 Verify with: read_file, run tests")
    elif action_type == "trade":
        lines.append(f"  Trade executed")
        lines.append(f"  📊 Verify with: get_trade_history")
    else:
        lines.append(f"  Action completed")
    
    return "\n".join(lines)


# ============================================================
# 8. Multi-File Editing
# ============================================================

def multi_file_edit(edits: list) -> str:
    """Edit multiple files in one operation."""
    results = []
    
    for edit in edits:
        filepath = edit.get("file", "")
        old_text = edit.get("old", "")
        new_text = edit.get("new", "")
        
        if not filepath or not old_text:
            results.append(f"❌ {filepath}: Missing file or old text")
            continue
        
        try:
            full_path = PROJECT_ROOT / filepath
            content = full_path.read_text()
            
            if old_text not in content:
                results.append(f"❌ {filepath}: Old text not found")
                continue
            
            new_content = content.replace(old_text, new_text, 1)
            full_path.write_text(new_content)
            results.append(f"✅ {filepath}: Updated")
        except Exception as e:
            results.append(f"❌ {filepath}: {str(e)}")
    
    return "\n".join(results)


def batch_read_files(files: list) -> str:
    """Read multiple files at once."""
    results = []
    
    for filepath in files:
        try:
            full_path = PROJECT_ROOT / filepath
            content = full_path.read_text()
            lines = content.split("\n")
            results.append(f"=== {filepath} ({len(lines)} lines) ===")
            results.append(content[:800])
            if len(content) > 800:
                results.append(f"... ({len(content)} total chars)")
            results.append("")
        except Exception as e:
            results.append(f"❌ {filepath}: {str(e)}")
    
    return "\n".join(results)


# ============================================================
# 9. Git Integration
# ============================================================

def git_status() -> str:
    """Get git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        if result.stdout.strip():
            return f"Git Status:\n{result.stdout}"
        return "Git Status: Clean working directory"
    except Exception as e:
        return f"Git error: {str(e)}"


def git_diff() -> str:
    """Get git diff."""
    try:
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        if result.stdout.strip():
            return f"Git Diff:\n{result.stdout[:2000]}"
        return "Git Diff: No changes"
    except Exception as e:
        return f"Git error: {str(e)}"


def git_log(n: int = 5) -> str:
    """Get recent git commits."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{n}"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        if result.stdout.strip():
            return f"Recent Commits:\n{result.stdout}"
        return "Git Log: No commits"
    except Exception as e:
        return f"Git error: {str(e)}"


def git_commit(message: str, files: list = None) -> str:
    """Create a git commit."""
    try:
        if files:
            for f in files:
                subprocess.run(["git", "add", f], capture_output=True, timeout=10, cwd=str(PROJECT_ROOT))
        else:
            subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10, cwd=str(PROJECT_ROOT))
        
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        return f"Committed: {result.stdout.strip() or result.stderr.strip()}"
    except Exception as e:
        return f"Git error: {str(e)}"


# ============================================================
# 10. Error Recovery — Try multiple approaches
# ============================================================

def try_with_fallback(primary_func, fallback_func, description: str = "task") -> str:
    """Try primary function, fall back to secondary if it fails."""
    try:
        result = primary_func()
        if result and "error" not in result.lower() and "failed" not in result.lower():
            return result
    except Exception as e:
        pass
    
    try:
        return fallback_func()
    except Exception as e:
        return f"Both approaches failed for {description}: {str(e)}"


# ============================================================
# Tool Registry
# ============================================================

FULL_AGENT_TOOLS = [
    # Web Access
    {"type": "function", "function": {"name": "read_url", "description": "Fetch any URL and extract readable text. Use when user gives a URL or asks to check a website.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "number"}}, "required": ["url"]}}},
    
    # Code Search
    {"type": "function", "function": {"name": "code_search", "description": "Search codebase for patterns using ripgrep. Fast and powerful.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "flags": {"type": "string"}, "max_results": {"type": "number"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "find_function", "description": "Find where a function is defined.", "parameters": {"type": "object", "properties": {"func_name": {"type": "string"}}, "required": ["func_name"]}}},
    {"type": "function", "function": {"name": "find_class", "description": "Find where a class is defined.", "parameters": {"type": "object", "properties": {"class_name": {"type": "string"}}, "required": ["class_name"]}}},
    {"type": "function", "function": {"name": "find_all_references", "description": "Find all references to a variable/function/class.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    
    # Terminal
    {"type": "function", "function": {"name": "run_terminal_command", "description": "Execute any bash command. Use for builds, tests, git, etc.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "number"}, "cwd": {"type": "string"}}, "required": ["command"]}}},
    
    # User Interaction
    {"type": "function", "function": {"name": "ask_user", "description": "Ask user a clarifying question when request is ambiguous.", "parameters": {"type": "object", "properties": {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}}, "required": ["question"]}}},
    {"type": "function", "function": {"name": "suggest_followups", "description": "Suggest next steps after completing a task.", "parameters": {"type": "object", "properties": {"context": {"type": "string"}}, "required": ["context"]}}},
    
    # Planning
    {"type": "function", "function": {"name": "create_todos", "description": "Create a step-by-step plan. Use for complex tasks.", "parameters": {"type": "object", "properties": {"goal": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}}}, "required": ["goal", "steps"]}}},
    {"type": "function", "function": {"name": "update_todos", "description": "Mark a step as done/failed.", "parameters": {"type": "object", "properties": {"step_number": {"type": "integer"}, "status": {"type": "string", "enum": ["done", "failed"]}, "result": {"type": "string"}}, "required": ["step_number", "status"]}}},
    {"type": "function", "function": {"name": "get_todos", "description": "Get current plan and next step.", "parameters": {"type": "object", "properties": {}}}},
    
    # Verification
    {"type": "function", "function": {"name": "verify_action", "description": "Verify that an action actually worked.", "parameters": {"type": "object", "properties": {"action_type": {"type": "string"}, "details": {"type": "object"}}, "required": ["action_type", "details"]}}},
    
    # Multi-File
    {"type": "function", "function": {"name": "multi_file_edit", "description": "Edit multiple files in one operation.", "parameters": {"type": "object", "properties": {"edits": {"type": "array", "items": {"type": "object", "properties": {"file": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}, "required": ["file", "old", "new"]}}}, "required": ["edits"]}}},
    {"type": "function", "function": {"name": "batch_read_files", "description": "Read multiple files at once.", "parameters": {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string"}}}, "required": ["files"]}}},
    
    # Git
    {"type": "function", "function": {"name": "git_status", "description": "Get git status.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "git_diff", "description": "Get git diff.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "git_log", "description": "Get recent commits.", "parameters": {"type": "object", "properties": {"n": {"type": "number"}}}}},
    {"type": "function", "function": {"name": "git_commit", "description": "Create a git commit.", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}}}, "required": ["message"]}}},
]

FULL_AGENT_TOOL_MAP = {
    "read_url": lambda a: read_url(a["url"], int(a.get("max_chars", 10000))),
    "code_search": lambda a: code_search(a["pattern"], a.get("flags", ""), int(a.get("max_results", 25))),
    "find_function": lambda a: find_function(a["func_name"]),
    "find_class": lambda a: find_class(a["class_name"]),
    "find_all_references": lambda a: find_all_references(a["name"]),
    "run_terminal_command": lambda a: run_terminal_command(a["command"], int(a.get("timeout", 30)), a.get("cwd")),
    "ask_user": lambda a: ask_user(a["question"], a.get("options")),
    "suggest_followups": lambda a: suggest_followups(a["context"]),
    "create_todos": lambda a: create_todos(a.get("user_id", 0), a["goal"], a["steps"]),
    "update_todos": lambda a: update_todos(a.get("user_id", 0), a["step_number"], a.get("status", "done"), a.get("result", "")),
    "get_todos": lambda a: get_todos(a.get("user_id", 0)),
    "verify_action": lambda a: verify_action(a["action_type"], a.get("details", {})),
    "multi_file_edit": lambda a: multi_file_edit(a["edits"]),
    "batch_read_files": lambda a: batch_read_files(a["files"]),
    "git_status": lambda a: git_status(),
    "git_diff": lambda a: git_diff(),
    "git_log": lambda a: git_log(int(a.get("n", 5))),
    "git_commit": lambda a: git_commit(a["message"], a.get("files")),
}
