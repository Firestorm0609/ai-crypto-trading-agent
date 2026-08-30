"""
Test smolagents — HuggingFace's lightweight agent framework.

Key difference from our current approach:
- Current: LLM calls pre-defined tools (function calling)
- smolagents: LLM writes Python code to solve problems

This means:
- No need to pre-define every tool
- Agent can combine tools in creative ways
- More flexible, less maintenance
"""

from smolagents import CodeAgent, OpenAIModel, WebSearchTool, tool
from config import MISTRAL_API_KEYS, MISTRAL_MODEL


# Define tools using @tool decorator
@tool
def get_crypto_price(coin: str) -> str:
    """Get current price for a cryptocurrency.

    Args:
        coin: The cryptocurrency name or symbol (e.g. 'bitcoin', 'btc', 'ethereum', 'eth')
    """
    import urllib.request, json
    aliases = {'btc': 'bitcoin', 'eth': 'ethereum', 'sol': 'solana', 'doge': 'dogecoin'}
    coin_id = aliases.get(coin.lower(), coin.lower())
    url = f'https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    price = data.get(coin_id, {}).get('usd', 0)
    return f'{coin.upper()}: ${price:,.2f}'


@tool
def check_robinhood_nft_support() -> str:
    """Check if Robinhood supports NFTs and what chains are available."""
    return 'Robinhood supports NFTs on Ethereum, Base, and Arbitrum via Robinhood Wallet app. Same EVM wallet works across all chains.'


@tool
def get_top_coins(n: int = 5) -> str:
    """Get top N cryptocurrencies by market cap.

    Args:
        n: Number of coins to return (default 5)
    """
    import urllib.request, json
    url = f'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={n}&page=1'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    lines = []
    for i, coin in enumerate(data, 1):
        price = coin.get('current_price', 0)
        change = coin.get('price_change_percentage_24h', 0) or 0
        emoji = '🟢' if change >= 0 else '🔴'
        lines.append(f'{i}. {coin["name"]} ({coin["symbol"].upper()}) - ${price:,.2f} {emoji}{change:+.1f}%')
    return '\n'.join(lines)


def main():
    # Create model using Mistral (OpenAI-compatible)
    model = OpenAIModel(
        model_id=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEYS[0],
        api_base='https://api.mistral.ai/v1',
    )

    # Create agent with tools
    agent = CodeAgent(
        tools=[get_crypto_price, check_robinhood_nft_support, get_top_coins, WebSearchTool()],
        model=model,
        max_steps=5,
    )

    # Test 1: Multi-tool question
    print('=' * 50)
    print('Test 1: Multi-tool question')
    print('=' * 50)
    result = agent.run('What is the price of bitcoin and does Robinhood support NFTs?')
    print(f'Result: {result}')
    print()

    # Test 2: Research question
    print('=' * 50)
    print('Test 2: Research question')
    print('=' * 50)
    result = agent.run('Search for the latest news about Solana and tell me the top 3 coins by market cap')
    print(f'Result: {result}')
    print()

    # Test 3: Complex analysis
    print('=' * 50)
    print('Test 3: Complex analysis')
    print('=' * 50)
    result = agent.run('Compare the prices of Bitcoin and Ethereum, then search for which one has better gas fees')
    print(f'Result: {result}')


if __name__ == '__main__':
    main()
