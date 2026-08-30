"""
Solana trading tools that the AI agent can invoke via natural language.
"""

import json
from solana_trader import (
    generate_wallet, load_wallet, get_wallet_address,
    get_sol_balance, get_token_balances, get_sol_price,
    get_token_price, buy_token, sell_token,
    check_rug_risk, KNOWN_TOKENS,
)

# ============================================================
# Tool Definitions (OpenAI function calling format)
# ============================================================

SOLANA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_wallet",
            "description": "Generate a new Solana wallet for trading memecoins. Returns the wallet address.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_wallet_balance",
            "description": "Check SOL and token balances in the Solana wallet.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sol_price",
            "description": "Get the current SOL price in USD.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_token_price",
            "description": "Get the price of any SPL token in USD.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Token symbol like WIF, BONK, PEPE, POPCAT"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buy_token",
            "description": "Buy a Solana token with SOL. REAL MONEY. Executes a swap on Jupiter DEX.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Token to buy (e.g., WIF, BONK, PEPE)"},
                    "sol_amount": {"type": "number", "description": "Amount of SOL to spend"}
                },
                "required": ["symbol", "sol_amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sell_token",
            "description": "Sell a Solana token for SOL. REAL MONEY. Executes a swap on Jupiter DEX.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Token to sell (e.g., WIF, BONK)"},
                    "percentage": {"type": "number", "description": "Percentage to sell (100 = sell all, 50 = sell half)"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rug_check",
            "description": "Check rug pull risk indicators for a token before buying.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Token symbol to check"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_wallet_address",
            "description": "Get the current wallet's Solana address.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_private_key",
            "description": "Get the private key of the current Solana wallet. Use this when the user asks for their private key or secret key.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
]


# ============================================================
# Tool Dispatcher
# ============================================================

def execute_solana_tool(name: str, args: dict) -> str:
    """Execute a Solana trading tool."""
    try:
        if name == "generate_wallet":
            wallet = generate_wallet()
            return (
                f"✅ New Solana wallet generated!\n"
                f"Address: {wallet['public_key']}\n"
                f"🔑 Private Key: {wallet['private_key']}\n\n"
                f"⚠️ SAVE THIS PRIVATE KEY SECURELY! It won't be shown again.\n"
                f"Fund it with SOL to start trading!"
            )

        elif name == "get_wallet_balance":
            address = get_wallet_address()
            sol = get_sol_balance()
            sol_price = get_sol_price()
            sol_usd = sol * sol_price
            balances = get_token_balances()

            lines = [f"💼 Wallet: {address[:12]}...{address[-8:]}"]
            lines.append(f"💰 SOL: {sol:.4f} (~${sol_usd:.2f})")

            if balances:
                lines.append(f"\n🪙 Tokens ({len(balances)}):")
                for b in balances[:10]:
                    symbol = "Unknown"
                    for s, m in KNOWN_TOKENS.items():
                        if m == b["mint"]:
                            symbol = s
                            break
                    lines.append(f"  • {symbol}: {b['amount']:,.2f}")
            else:
                lines.append("No token balances")

            return "\n".join(lines)

        elif name == "get_sol_price":
            price = get_sol_price()
            return f"SOL: ${price:,.2f}"

        elif name == "get_token_price":
            symbol = args.get("symbol", "").upper()
            mint = KNOWN_TOKENS.get(symbol)
            if not mint:
                return f"Unknown token: {symbol}. Known: {', '.join(KNOWN_TOKENS.keys())}"
            price = get_token_price(mint)
            if price > 0:
                return f"{symbol}: ${price:,.6f}"
            return f"Unable to get price for {symbol}"

        elif name == "buy_token":
            symbol = args.get("symbol", "").upper()
            sol_amount = float(args.get("sol_amount", 0))
            if sol_amount <= 0:
                return "Error: sol_amount must be positive"
            return buy_token(symbol, sol_amount)

        elif name == "sell_token":
            symbol = args.get("symbol", "").upper()
            percentage = float(args.get("percentage", 100))
            return sell_token(symbol, percentage)

        elif name == "rug_check":
            symbol = args.get("symbol", "").upper()
            return check_rug_risk(symbol)

        elif name == "get_wallet_address":
            return f"Wallet address: {get_wallet_address()}"

        elif name == "get_private_key":
            wallet = load_wallet()
            return (
                f"🔑 *Private Key (handle with care!):*\n"
                f"`{wallet['private_key']}`\n\n"
                f"⚠️ NEVER share this key with anyone!"
            )

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Error: {str(e)}"
