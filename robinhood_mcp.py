"""
Robinhood Agentic Trading — MCP Integration.

Connects to Robinhood's Trading MCP for:
- Portfolio viewing
- Order placement (buy/sell crypto)
- Market analysis
- Account management

MCP URL: https://agent.robinhood.com/mcp/trading
"""

import json
import urllib.request

# ============================================================
# Robinhood MCP Client
# ============================================================

ROBINHOOD_MCP_URL = "https://agent.robinhood.com/mcp/trading"

class RobinhoodMCP:
    """Client for Robinhood Agentic Trading MCP."""

    def __init__(self):
        self.base_url = ROBINHOOD_MCP_URL
        self.authenticated = False

    def _request(self, method: str, params: dict = None) -> dict:
        """Make an MCP request."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}

    def authenticate(self, token: str = None) -> str:
        """Authenticate with Robinhood MCP."""
        if token:
            # Store token for future requests
            self.auth_token = token
            self.authenticated = True
            return "✅ Authenticated with Robinhood MCP"

        return (
            "🔐 *Robinhood MCP Authentication*\n\n"
            "To connect your Robinhood account:\n\n"
            "1. Go to robinhood.com\n"
            "2. Open Agentic Trading\n"
            "3. Click 'Connect Agent'\n"
            "4. Authenticate with your Robinhood credentials\n"
            "5. Copy the auth token\n"
            "6. Send it here\n\n"
            "Or visit: https://agent.robinhood.com/mcp/trading"
        )

    def get_portfolio(self) -> str:
        """Get Robinhood portfolio via MCP."""
        if not self.authenticated:
            return "❌ Not authenticated. Use /rhauth first."

        result = self._request("tools/call", {
            "name": "get_portfolio",
            "arguments": {}
        })

        if "error" in result:
            return f"❌ {result['error']}"

        # Parse MCP response
        content = result.get("result", {}).get("content", [])
        if content:
            return content[0].get("text", "No data")

        return "No portfolio data available"

    def buy_crypto(self, symbol: str, amount_usd: float) -> str:
        """Buy crypto on Robinhood via MCP."""
        if not self.authenticated:
            return "❌ Not authenticated. Use /rhauth first."

        result = self._request("tools/call", {
            "name": "place_order",
            "arguments": {
                "symbol": symbol.upper(),
                "side": "buy",
                "type": "market",
                "amount_in_usd": str(amount_usd),
            }
        })

        if "error" in result:
            return f"❌ Order failed: {result['error']}"

        return (
            f"✅ *ROBINHOOD ORDER PLACED*\n\n"
            f"Action: BUY {symbol.upper()}\n"
            f"Amount: ${amount_usd:,.2f}\n"
            f"Platform: Robinhood\n"
            f"Account: Agentic\n\n"
            f"⏳ Order is processing..."
        )

    def sell_crypto(self, symbol: str, amount_usd: float = None) -> str:
        """Sell crypto on Robinhood via MCP."""
        if not self.authenticated:
            return "❌ Not authenticated. Use /rhauth first."

        args = {
            "symbol": symbol.upper(),
            "side": "sell",
            "type": "market",
        }
        if amount_usd:
            args["amount_in_usd"] = str(amount_usd)
        else:
            args["quantity"] = "all"

        result = self._request("tools/call", {
            "name": "place_order",
            "arguments": args,
        })

        if "error" in result:
            return f"❌ Order failed: {result['error']}"

        return (
            f"✅ *ROBINHOOD ORDER PLACED*\n\n"
            f"Action: SELL {symbol.upper()}\n"
            f"Amount: {'All' if not amount_usd else f'${amount_usd:,.2f}'}\n"
            f"Platform: Robinhood\n"
            f"Account: Agentic\n\n"
            f"⏳ Order is processing..."
        )

    def get_quote(self, symbol: str) -> str:
        """Get Robinhood quote via MCP."""
        if not self.authenticated:
            return "❌ Not authenticated. Use /rhauth first."

        result = self._request("tools/call", {
            "name": "get_quote",
            "arguments": {"symbol": symbol.upper()}
        })

        if "error" in result:
            return f"❌ {result['error']}"

        content = result.get("result", {}).get("content", [])
        if content:
            return content[0].get("text", "No quote data")

        return "No quote available"


# Singleton
robinhood_mcp = RobinhoodMCP()


# ============================================================
# Tool Registry
# ============================================================

RH_MCP_TOOLS = [
    {"type": "function", "function": {"name": "rh_auth", "description": "Authenticate with Robinhood MCP.", "parameters": {"type": "object", "properties": {"token": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "rh_mcp_portfolio", "description": "View Robinhood portfolio via MCP.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "rh_mcp_buy", "description": "Buy crypto on Robinhood via MCP. REAL MONEY.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "amount_usd": {"type": "number"}}, "required": ["symbol", "amount_usd"]}}},
    {"type": "function", "function": {"name": "rh_mcp_sell", "description": "Sell crypto on Robinhood via MCP. REAL MONEY.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "amount_usd": {"type": "number"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "rh_mcp_quote", "description": "Get Robinhood quote via MCP.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
]

RH_MCP_TOOL_MAP = {
    "rh_auth": lambda a: robinhood_mcp.authenticate(a.get("token")),
    "rh_mcp_portfolio": lambda a: robinhood_mcp.get_portfolio(),
    "rh_mcp_buy": lambda a: robinhood_mcp.buy_crypto(a["symbol"], float(a["amount_usd"])),
    "rh_mcp_sell": lambda a: robinhood_mcp.sell_crypto(a["symbol"], a.get("amount_usd")),
    "rh_mcp_quote": lambda a: robinhood_mcp.get_quote(a["symbol"]),
}
