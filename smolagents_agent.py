"""
smolagents Integration — HuggingFace's lightweight agent framework.

Key difference:
- Current bot: LLM calls pre-defined tools (function calling)
- smolagents: LLM writes Python code to solve problems

smolagents advantages:
- No tool limits — agent can call any function
- Creative combinations — chains tools in unexpected ways
- Self-healing — retries with different approaches on failure
- Code execution — can do math, data analysis, anything Python can do

This module wraps our existing tools as smolagents tools and provides
an alternative mode for complex tasks.
"""

import json
import urllib.request
import urllib.parse
from smolagents import CodeAgent, OpenAIModel, tool
from config import MISTRAL_API_KEYS, MISTRAL_MODEL


# ============================================================
# smolagents Tool Definitions (wrapping our existing tools)
# ============================================================

@tool
def get_crypto_price(coin: str) -> str:
    """Get current price for a cryptocurrency.

    Args:
        coin: The cryptocurrency name or symbol (e.g. 'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol')
    """
    from all_tools import get_price
    return get_price(coin)


@tool
def get_top_coins(n: int = 10) -> str:
    """Get top N cryptocurrencies by market cap.

    Args:
        n: Number of coins to return (default 10)
    """
    from all_tools import get_top_coins
    return get_top_coins(n)


@tool
def get_trending_coins() -> str:
    """Get trending cryptocurrencies right now."""
    from all_tools import get_trending
    return get_trending()


@tool
def get_fear_greed_index() -> str:
    """Get the Crypto Fear & Greed Index."""
    from all_tools import get_fear_greed
    return get_fear_greed()


@tool
def paper_buy(coin: str, amount_usd: float) -> str:
    """Buy cryptocurrency with paper money.

    Args:
        coin: Cryptocurrency symbol (e.g. 'btc', 'eth', 'sol')
        amount_usd: Amount in USD to spend
    """
    from all_tools import buy
    return buy(coin, amount_usd)


@tool
def paper_sell(coin: str, quantity: float = None, percentage: float = None) -> str:
    """Sell cryptocurrency holdings.

    Args:
        coin: Cryptocurrency symbol (e.g. 'btc', 'eth', 'sol')
        quantity: Amount to sell (optional, sells all if not specified)
        percentage: Percentage of holdings to sell (optional)
    """
    from all_tools import sell
    return sell(coin, quantity, percentage)


@tool
def get_portfolio() -> str:
    """Show current portfolio with holdings and P&L."""
    from all_tools import get_portfolio
    return get_portfolio()


@tool
def search_web(query: str) -> str:
    """Search the internet for any topic. Use when you need current information.

    Args:
        query: What to search for
    """
    from all_tools import web_search
    return web_search(query)


@tool
def get_crypto_news(coin: str = "crypto") -> str:
    """Get latest crypto news.

    Args:
        coin: Coin to get news for (default: general crypto news)
    """
    from all_tools import get_crypto_news
    return get_crypto_news(coin)


@tool
def check_robinhood_nft_support() -> str:
    """Check if Robinhood supports NFTs and what chains are available."""
    return (
        "Robinhood supports NFTs on Ethereum, Base, and Arbitrum via Robinhood Wallet app. "
        "Same EVM wallet works across all chains. Import wallet using private key."
    )


@tool
def get_nft_floor_price(collection: str, chain: str = "solana") -> str:
    """Get NFT collection floor price.

    Args:
        collection: Collection name or slug
        chain: Chain (solana, ethereum, base)
    """
    from nft_tools import get_nft_floor
    return get_nft_floor(collection, chain)


@tool
def get_popular_nfts(chain: str = "solana") -> str:
    """Get popular NFT collections.

    Args:
        chain: Chain to list NFTs for (solana, ethereum, base, robinhood)
    """
    from nft_tools import get_popular_nfts
    return get_popular_nfts(chain)


@tool
def list_bot_files() -> str:
    """List all files in the bot directory."""
    from file_tools import execute_file_tool
    return execute_file_tool("list_files", {})


@tool
def read_bot_file(filepath: str) -> str:
    """Read a file from the bot directory.

    Args:
        filepath: Path to the file (e.g. 'telegram_bot.py', 'config.py')
    """
    from file_tools import execute_file_tool
    return execute_file_tool("read_file", {"filepath": filepath})


@tool
def edit_bot_file(filepath: str, old_text: str, new_text: str) -> str:
    """Edit a file in the bot directory using find-and-replace.

    Args:
        filepath: Path to the file
        old_text: Text to find (exact match)
        new_text: Text to replace with
    """
    from file_tools import execute_file_tool
    return execute_file_tool("edit_file", {
        "filepath": filepath,
        "old_text": old_text,
        "new_text": new_text
    })


@tool
def run_python_code(code: str) -> str:
    """Execute Python code and return the result. Use for calculations, data analysis, etc.

    Args:
        code: Python code to execute
    """
    from all_tools import run_python
    return run_python({"code": code})


# ============================================================
# smolagents Agent Class
# ============================================================

class SmolAgentRunner:
    """Wrapper around smolagents CodeAgent for the trading bot."""

    def __init__(self):
        if not MISTRAL_API_KEYS:
            raise Exception("No Mistral API keys configured!")

        self.model = OpenAIModel(
            model_id=MISTRAL_MODEL,
            api_key=MISTRAL_API_KEYS[0],
            api_base='https://api.mistral.ai/v1',
        )

        self.tools = [
            # Market data
            get_crypto_price,
            get_top_coins,
            get_trending_coins,
            get_fear_greed_index,
            # Trading
            paper_buy,
            paper_sell,
            get_portfolio,
            # Research
            search_web,
            get_crypto_news,
            # NFTs
            check_robinhood_nft_support,
            get_nft_floor_price,
            get_popular_nfts,
            # Code
            list_bot_files,
            read_bot_file,
            edit_bot_file,
            run_python_code,
        ]

        self.agent = CodeAgent(
            tools=self.tools,
            model=self.model,
            max_steps=10,
        )

    def run(self, message: str) -> str:
        """Run a query using smolagents."""
        try:
            result = self.agent.run(message)
            # Format result nicely
            if isinstance(result, dict):
                return "\n".join(f"{k}: {v}" for k, v in result.items())
            return str(result)
        except Exception as e:
            return f"smolagents error: {str(e)}"


# ============================================================
# Singleton
# ============================================================

_smol_agent = None

def get_smol_agent():
    """Get or create the smolagents singleton."""
    global _smol_agent
    if _smol_agent is None:
        _smol_agent = SmolAgentRunner()
    return _smol_agent


def run_smolagents_query(message: str) -> str:
    """Run a query using smolagents."""
    agent = get_smol_agent()
    return agent.run(message)
