"""
Sandboxed File Tools — Bot can only edit files in its own directory.

Tools:
- list_files: List files in the bot directory
- read_file: Read a file's contents
- write_file: Create or overwrite a file
- edit_file: Make targeted find-and-replace edits
- run_safe_command: Run limited safe shell commands
"""

import os
import re
from pathlib import Path

# Sandbox: only allow operations within this directory
BOT_DIR = Path(__file__).parent.resolve()

# Allowed safe commands (no rm, mv, sudo, etc.)
SAFE_COMMANDS = ["ls", "cat", "head", "tail", "grep", "find", "wc", "pwd", "echo", "date", "whoami"]


def _safe_path(filepath: str) -> Path:
    """Resolve path and ensure it's within BOT_DIR."""
    target = (BOT_DIR / filepath).resolve()
    if not str(target).startswith(str(BOT_DIR)):
        return None  # Path traversal attempt
    return target


# ============================================================
# Tool Definitions (OpenAI function calling format)
# ============================================================

FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the bot directory. Shows all .py files and other important files.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the bot directory. ALWAYS use this FIRST before editing any file. Never guess what the code looks like - read it first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path relative to bot directory (e.g., 'telegram_bot.py', 'config.py')"}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file in the bot directory. Use this to fix bugs or add features.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path relative to bot directory"},
                    "content": {"type": "string", "description": "Full file content to write"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Make a targeted edit to a file by replacing a specific string. ALWAYS use read_file FIRST to see the current code, then use this to fix it. Never guess what the code looks like.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path relative to bot directory"},
                    "old_string": {"type": "string", "description": "The exact string to find and replace"},
                    "new_string": {"type": "string", "description": "The replacement string"}
                },
                "required": ["filepath", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_safe_command",
            "description": "Run a safe shell command (ls, cat, grep, find, wc, head, tail, echo, pwd, date, whoami). No dangerous commands allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run (must start with a safe command)"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restart_bot",
            "description": "Restart the bot to apply code changes. Use this after making edits to .py files. The bot will restart in background.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
]


# ============================================================
# Tool Dispatcher
# ============================================================

def execute_file_tool(name: str, args: dict) -> str:
    """Execute a file operation tool."""
    try:
        if name == "list_files":
            files = []
            for item in sorted(BOT_DIR.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_file():
                    size = item.stat().st_size
                    files.append(f"📄 {item.name} ({size:,} bytes)")
                elif item.is_dir():
                    files.append(f"📁 {item.name}/")
            return f"📂 Files in bot directory:\n\n" + "\n".join(files)

        elif name == "read_file":
            filepath = args.get("filepath", "")
            target = _safe_path(filepath)
            if target is None:
                return "❌ Error: Path traversal not allowed. Stay within bot directory."
            if not target.exists():
                return f"❌ Error: File not found: {filepath}"
            if not target.is_file():
                return f"❌ Error: Not a file: {filepath}"
            content = target.read_text(errors="replace")
            if len(content) > 3000:
                content = content[:3000] + f"\n\n... (truncated, {len(content)} bytes total)"
            return f"📄 {filepath}:\n\n{content}"

        elif name == "write_file":
            filepath = args.get("filepath", "")
            content = args.get("content", "")
            if not filepath or not isinstance(filepath, str):
                return "❌ Error: filepath is required and must be a string"
            if not content or not isinstance(content, str):
                return "❌ Error: content is required and must be a string"
            target = _safe_path(filepath)
            if target is None:
                return "❌ Error: Path traversal not allowed."
            if not isinstance(target, Path):
                return f"❌ Error: Invalid path: {filepath}"
            # Create parent dirs if needed
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            return f"✅ Written {len(content)} bytes to {filepath}"

        elif name == "edit_file":
            filepath = args.get("filepath", "")
            old_string = args.get("old_string", "")
            new_string = args.get("new_string", "")
            target = _safe_path(filepath)
            if target is None:
                return "❌ Error: Path traversal not allowed."
            if not target.exists():
                return f"❌ Error: File not found: {filepath}"
            content = target.read_text(errors="replace")
            if old_string not in content:
                # Try to find close match
                return f"❌ Error: String not found in {filepath}. Make sure it matches exactly."
            count = content.count(old_string)
            if count > 1:
                return f"❌ Error: Found {count} matches. Be more specific."
            new_content = content.replace(old_string, new_string, 1)
            target.write_text(new_content)
            return f"✅ Edited {filepath} ({len(old_string)} → {len(new_string)} chars)"

        elif name == "run_safe_command":
            command = args.get("command", "").strip()
            # Check if command starts with a safe command
            cmd_parts = command.split()
            if not cmd_parts:
                return "❌ Error: Empty command"
            base_cmd = cmd_parts[0]
            if base_cmd not in SAFE_COMMANDS:
                return f"❌ Error: '{base_cmd}' not allowed. Safe commands: {', '.join(SAFE_COMMANDS)}"
            # Run the command
            import subprocess
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=10, cwd=str(BOT_DIR)
            )
            output = result.stdout + result.stderr
            if len(output) > 2000:
                output = output[:2000] + "\n... (truncated)"
            return output or "(no output)"

        elif name == "restart_bot":
            import subprocess
            import threading
            
            def do_restart():
                """Restart the bot in a new screen session."""
                import time
                time.sleep(2)  # Wait for response to be sent
                # Kill current process
                subprocess.run(['pkill', '-f', 'telegram_bot.py'], capture_output=True)
                time.sleep(1)
                # Start new process in screen
                subprocess.run(
                    ['screen', '-dmS', 'trading-bot', 'bash', '-c',
                     f'cd {BOT_DIR} && python3 -u telegram_bot.py >> {BOT_DIR}/bot.log 2>&1'],
                    capture_output=True
                )
            
            threading.Thread(target=do_restart, daemon=True).start()
            return (
                "🔄 Restarting bot in 2 seconds...\n"
                "Changes will be live when the bot comes back online!"
            )

        else:
            return f"Unknown file tool: {name}"

    except Exception as e:
        return f"Error: {str(e)}"
