import json
import subprocess
import urllib.request
import urllib.parse
import os
from pathlib import Path
from google.generativeai.types import FunctionDeclaration
from config import WORKSPACE_DIR


# ============================================================
# Tool Registry
# ============================================================

TOOLS = [
    FunctionDeclaration(
        name="web_search",
        description="Search the web for information. Returns search results with titles, URLs, and snippets.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    ),
    FunctionDeclaration(
        name="web_fetch",
        description="Fetch and read the content of a URL. Returns the page text content.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "url": {
                    "type": "STRING",
                    "description": "The URL to fetch"
                }
            },
            "required": ["url"]
        }
    ),
    FunctionDeclaration(
        name="read_file",
        description="Read the contents of a file in the workspace.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "File path relative to workspace"
                }
            },
            "required": ["path"]
        }
    ),
    FunctionDeclaration(
        name="write_file",
        description="Write content to a file in the workspace. Creates parent directories if needed.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "File path relative to workspace"
                },
                "content": {
                    "type": "STRING",
                    "description": "The content to write"
                }
            },
            "required": ["path", "content"]
        }
    ),
    FunctionDeclaration(
        name="list_files",
        description="List files and directories in a workspace path.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Directory path relative to workspace (default: root)"
                }
            }
        }
    ),
    FunctionDeclaration(
        name="run_python",
        description="Execute Python code and return the output. Use this for calculations, data processing, or testing code.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "code": {
                    "type": "STRING",
                    "description": "Python code to execute"
                }
            },
            "required": ["code"]
        }
    ),
    FunctionDeclaration(
        name="run_shell",
        description="Run a shell command and return the output. Use for system operations, package installs, git commands, etc.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Shell command to execute"
                }
            },
            "required": ["command"]
        }
    )
]


# ============================================================
# Tool Implementations
# ============================================================

def web_search(query: str) -> str:
    """Search the web using DuckDuckGo Lite."""
    try:
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        results = []
        lines = html.split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if '<a rel="nofollow" class="result-link" href="' in line:
                start = line.find('href="') + 6
                end = line.find('"', start)
                result_url = line[start:end] if start > 5 else ""
                snippet = ""
                for j in range(i+1, min(i+5, len(lines))):
                    if lines[j].strip() and '<' not in lines[j]:
                        snippet = lines[j].strip()
                        break
                if result_url:
                    results.append(f"URL: {result_url}\nSnippet: {snippet}")

        if results:
            return "\n\n".join(results[:5])
        return "No results found for: " + query
    except Exception as e:
        return f"Search error: {str(e)}"


def web_fetch(url: str) -> str:
    """Fetch and extract text from a URL."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Agent/1.0)"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        import re
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
        content = re.sub(r'<[^>]+>', ' ', content)
        content = re.sub(r'\s+', ' ', content).strip()

        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"
        return content
    except Exception as e:
        return f"Fetch error: {str(e)}"


def read_file(path: str) -> str:
    """Read a file from workspace."""
    try:
        full_path = WORKSPACE_DIR / path
        if not full_path.exists():
            return f"Error: File not found: {path}"
        if not str(full_path.resolve()).startswith(str(WORKSPACE_DIR.resolve())):
            return "Error: Access denied - path outside workspace"
        content = full_path.read_text(errors="ignore")
        if len(content) > 10000:
            content = content[:10000] + "\n... [truncated]"
        return content
    except Exception as e:
        return f"Read error: {str(e)}"


def write_file(path: str, content: str) -> str:
    """Write content to a file in workspace."""
    try:
        full_path = WORKSPACE_DIR / path
        if not str(full_path.resolve()).startswith(str(WORKSPACE_DIR.resolve())):
            return "Error: Access denied - path outside workspace"
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Write error: {str(e)}"


def list_files(path: str = ".") -> str:
    """List files in a directory."""
    try:
        full_path = WORKSPACE_DIR / path
        if not full_path.exists():
            return f"Error: Directory not found: {path}"
        items = []
        for item in sorted(full_path.iterdir()):
            prefix = "📁 " if item.is_dir() else "📄 "
            items.append(f"{prefix}{item.name}")
        if not items:
            return "Empty directory"
        return "\n".join(items)
    except Exception as e:
        return f"List error: {str(e)}"


def run_python(code: str) -> str:
    """Execute Python code in a subprocess."""
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(WORKSPACE_DIR)
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}" if output else result.stderr
        if not output.strip():
            output = "(no output)"
        if len(output) > 5000:
            output = output[:5000] + "\n... [truncated]"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (30s limit)"
    except Exception as e:
        return f"Execution error: {str(e)}"


def run_shell(command: str) -> str:
    """Run a shell command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(WORKSPACE_DIR)
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}" if output else result.stderr
        if not output.strip():
            output = "(no output)"
        if len(output) > 5000:
            output = output[:5000] + "\n... [truncated]"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (30s limit)"
    except Exception as e:
        return f"Shell error: {str(e)}"


# Tool dispatcher
TOOL_MAP = {
    "web_search": lambda args: web_search(args["query"]),
    "web_fetch": lambda args: web_fetch(args["url"]),
    "read_file": lambda args: read_file(args["path"]),
    "write_file": lambda args: write_file(args["path"], args["content"]),
    "list_files": lambda args: list_files(args.get("path", ".")),
    "run_python": lambda args: run_python(args["code"]),
    "run_shell": lambda args: run_shell(args["command"]),
}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name with given arguments."""
    if name in TOOL_MAP:
        return TOOL_MAP[name](args)
    return f"Error: Unknown tool '{name}'"
