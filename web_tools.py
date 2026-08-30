"""
Web Access Tools — Full internet access for the agent

Provides:
- GitHub: repos, issues, README, search
- Web scraping: any URL
- Twitter/X: search, trends
- General web search
"""

import json
import urllib.request
import urllib.parse
import re
from pathlib import Path


# ============================================================
# 1. GitHub Tools
# ============================================================

def github_search_repos(query: str, limit: int = 5) -> str:
    """Search GitHub repositories."""
    try:
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=stars&per_page={limit}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "TradingAgent/1.0",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        repos = data.get("items", [])
        if not repos:
            return f"No repos found for '{query}'"

        lines = [f"GitHub Repos: '{query}'\n"]
        for repo in repos:
            name = repo.get("full_name", "?")
            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description", "No description")[:80]
            lang = repo.get("language", "?")
            url = repo.get("html_url", "")

            lines.append(f"⭐ {name} ({stars:,} stars)")
            lines.append(f"  {desc}")
            lines.append(f"  Language: {lang}")
            lines.append(f"  {url}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"GitHub search error: {str(e)}"


def github_get_repo(owner: str, repo: str) -> str:
    """Get GitHub repo details."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "TradingAgent/1.0",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        name = data.get("full_name", "?")
        stars = data.get("stargazers_count", 0)
        forks = data.get("forks_count", 0)
        issues = data.get("open_issues_count", 0)
        desc = data.get("description", "No description")
        lang = data.get("language", "?")
        created = data.get("created_at", "?")[:10]
        updated = data.get("updated_at", "?")[:10]
        topics = data.get("topics", [])

        lines = [f"GitHub: {name}\n"]
        lines.append(f"⭐ Stars: {stars:,}")
        lines.append(f"🍴 Forks: {forks:,}")
        lines.append(f"🐛 Issues: {issues:,}")
        lines.append(f"📝 Description: {desc}")
        lines.append(f"💻 Language: {lang}")
        lines.append(f"📅 Created: {created}")
        lines.append(f"🔄 Updated: {updated}")
        if topics:
            lines.append(f"🏷️ Topics: {', '.join(topics[:10])}")

        return "\n".join(lines)
    except Exception as e:
        return f"GitHub repo error: {str(e)}"


def github_get_readme(owner: str, repo: str) -> str:
    """Get GitHub repo README content."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        req = urllib.request.Request(url, headers={
            "User-Agent": "TradingAgent/1.0",
            "Accept": "application/vnd.github.v3.raw"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            readme = resp.read().decode("utf-8", errors="ignore")

        # Clean up markdown
        readme = re.sub(r'!\[.*?\]\(.*?\)', '', readme)  # Remove images
        readme = re.sub(r'<[^>]+>', '', readme)  # Remove HTML
        readme = re.sub(r'\n{3,}', '\n\n', readme)  # Remove extra newlines

        return f"README: {owner}/{repo}\n\n{readme[:3000]}"
    except Exception as e:
        return f"README error: {str(e)}"


def github_search_issues(owner: str, repo: str, query: str = "", limit: int = 5) -> str:
    """Search GitHub issues."""
    try:
        q = f"repo:{owner}/{repo}"
        if query:
            q += f" {query}"
        url = f"https://api.github.com/search/issues?q={urllib.parse.quote(q)}&per_page={limit}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "TradingAgent/1.0",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        issues = data.get("items", [])
        if not issues:
            return f"No issues found for {owner}/{repo}"

        lines = [f"GitHub Issues: {owner}/{repo}\n"]
        for issue in issues:
            title = issue.get("title", "?")
            state = issue.get("state", "?")
            number = issue.get("number", "?")
            created = issue.get("created_at", "?")[:10]
            emoji = "🟢" if state == "open" else "🔴"

            lines.append(f"{emoji} #{number}: {title}")
            lines.append(f"  State: {state} | Created: {created}")

        return "\n".join(lines)
    except Exception as e:
        return f"GitHub issues error: {str(e)}"


# ============================================================
# 2. Web Scraping Tools
# ============================================================

def scrape_url(url: str) -> str:
    """Scrape any URL and extract readable content."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Extract text content
        # Remove scripts and styles
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        # Extract text from common tags
        text = ""
        for tag in ['h1', 'h2', 'h3', 'p', 'li', 'td', 'th', 'div', 'span']:
            matches = re.findall(f'<{tag}[^>]*>(.*?)</{tag}>', html, re.DOTALL)
            for m in matches:
                clean = re.sub(r'<[^>]+>', '', m).strip()
                if clean and len(clean) > 10:
                    text += clean + "\n"

        if not text:
            # Fallback: just strip all HTML
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text).strip()

        return f"Content from {url}:\n\n{text[:3000]}"
    except Exception as e:
        return f"Scrape error: {str(e)}"


# ============================================================
# 3. Twitter/X Tools
# ============================================================

def search_twitter(query: str, limit: int = 5) -> str:
    """Search Twitter/X for crypto content."""
    try:
        # Use web search to find Twitter content
        search_query = f"{query} site:x.com OR site:twitter.com"
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(search_query)}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        results = data.get("RelatedTopics", [])
        if not results:
            return f"No Twitter results for '{query}'"

        lines = [f"Twitter/X Search: '{query}'\n"]
        for r in results[:limit]:
            text = r.get("Text", "")
            url = r.get("FirstURL", "")
            if text:
                lines.append(f"• {text[:150]}")
                if url:
                    lines.append(f"  {url}")
                lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Twitter search error: {str(e)}"


# ============================================================
# Tool Registry
# ============================================================

WEB_TOOLS = [
    {"type": "function", "function": {"name": "github_search_repos", "description": "Search GitHub repositories. Use when user asks about repos, projects, tools, or anything on GitHub.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "github_get_repo", "description": "Get details of a GitHub repository. Use when user asks about a specific repo.", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}}, "required": ["owner", "repo"]}}},
    {"type": "function", "function": {"name": "github_get_readme", "description": "Get README content of a GitHub repository.", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}}, "required": ["owner", "repo"]}}},
    {"type": "function", "function": {"name": "github_search_issues", "description": "Search GitHub issues in a repository.", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "number"}}, "required": ["owner", "repo"]}}},
    {"type": "function", "function": {"name": "scrape_url", "description": "Scrape any URL and extract readable content. Use when user gives a URL or asks to check a website.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "search_twitter", "description": "Search Twitter/X for crypto content. Use when user asks about Twitter sentiment or mentions.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number"}}, "required": ["query"]}}},
]

WEB_TOOL_MAP = {
    "github_search_repos": lambda a: github_search_repos(a["query"], int(a.get("limit", 5))),
    "github_get_repo": lambda a: github_get_repo(a["owner"], a["repo"]),
    "github_get_readme": lambda a: github_get_readme(a["owner"], a["repo"]),
    "github_search_issues": lambda a: github_search_issues(a["owner"], a["repo"], a.get("query", ""), int(a.get("limit", 5))),
    "scrape_url": lambda a: scrape_url(a["url"]),
    "search_twitter": lambda a: search_twitter(a["query"], int(a.get("limit", 5))),
}
