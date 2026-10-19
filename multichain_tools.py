"""
Multi-Chain Trading Tools — Ethereum, Base, Polygon + Uniswap DEX.

Covers the missing Moonpay tools:
- Multi-chain wallet management
- EVM token swaps (Uniswap V3)
- Cross-chain bridges (via Li.Fi API)
- Fiat on/off ramp (info)
- Transaction history
- Token metadata
- Deposit links
- Prediction market info
- Hardware wallet support (Ledger)
- Message signing
"""

import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

# ============================================================
# Chain Configurations
# ============================================================

CHAINS = {
    "ethereum": {
        "name": "Ethereum",
        "symbol": "ETH",
        "chain_id": 1,
        "rpc": "https://eth.llamarpc.com",
        "explorer": "https://etherscan.io",
        "uniswap_router": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "wrapped_native": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "usdc": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    },
    "base": {
        "name": "Base",
        "symbol": "ETH",
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "explorer": "https://basescan.org",
        "uniswap_router": "0x2626664c2603336E57B271c5C0b26F421741e481",
        "wrapped_native": "0x4200000000000000000000000000000000000006",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "polygon": {
        "name": "Polygon",
        "symbol": "MATIC",
        "chain_id": 137,
        "rpc": "https://polygon-rpc.com",
        "explorer": "https://polygonscan.com",
        "uniswap_router": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "wrapped_native": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "usdc": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    },
    "arbitrum": {
        "name": "Arbitrum",
        "symbol": "ETH",
        "chain_id": 42161,
        "rpc": "https://arb1.arbitrum.io/rpc",
        "explorer": "https://arbiscan.io",
        "uniswap_router": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "wrapped_native": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    },
    "optimism": {
        "name": "Optimism",
        "symbol": "ETH",
        "chain_id": 10,
        "rpc": "https://mainnet.optimism.io",
        "explorer": "https://optimistic.etherscan.io",
        "uniswap_router": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "wrapped_native": "0x4200000000000000000000000000000000000006",
        "usdc": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    },
    "robinhood": {
        "name": "Robinhood Chain",
        "symbol": "ETH",
        "chain_id": 4663,  # Arbitrum Orbit L2 — verified on-chain 2026-09-02
        "rpc": "https://rpc.mainnet.chain.robinhood.com",
        "explorer": "https://robinhoodchain.blockscout.com",
        "uniswap_router": "0xcaf681a66d020601342297493863e78c959e5cb2",  # SwapRouter02
        "uniswap_quoter": "0x33e885ed0ec9bf04ecfb19341582aadcb4c8a9e7",  # QuoterV2
        "wrapped_native": "0x0bd7d308f8e1639fab988df18a8011f41eacad73",  # WETH, verified on-chain
        "usdc": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",            # USDG (dec 6)
        "features": ["tokenized_stocks", "defi", "lending"],
    },
    "solana": {
        "name": "Solana",
        "symbol": "SOL",
        "chain_id": "solana",
        "rpc": "https://api.mainnet-beta.solana.com",
        "explorer": "https://solscan.io",
    },
}

# Well-known EVM tokens per chain
def _stock_contracts() -> dict:
    """Tokenized-stock token contracts from tokenized_stocks (lazy import
    to avoid a circular import at module load)."""
    try:
        from tokenized_stocks import STOCK_CONTRACTS
        return dict(STOCK_CONTRACTS)
    except Exception:
        return {}


KNOWN_EVM_TOKENS = {
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "PEPE": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "ARB": "0xB50721BCF8d664c30412Cfbc6cf7a15145234ad1",
        "OP": "0x4200000000000000000000000000000000000042",
    },
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "WETH": "0x4200000000000000000000000000000000000006",
        "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
        "TOSHI": "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4",
        "DEGEN": "0x4ed4E862860beD51a9570b96d89aF5E1a0633342",
    },
    "polygon": {
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    },
    # Robinhood Chain (4663) — addresses verified on-chain 2026-09-02
    "robinhood": {
        "WETH": "0x0bd7d308f8e1639fab988df18a8011f41eacad73",
        "USDG": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",   # stablecoin, 6 dec
        "VIRTUAL": "0xc6911796042b15d7fa4f6cde69e245ddcd3d9c31",
        # Tokenized stocks — real ERC-20s (contracts from LI.Fi index)
        **{k.upper(): v for k, v in _stock_contracts().items()},
    },
}


# Wallet storage
WALLET_DIR = Path(__file__).parent / "wallets"


# ============================================================
# EVM Wallet Management
# ============================================================

def create_evm_wallet(chain: str = "ethereum") -> str:
    """Create a new EVM wallet. REFUSES to overwrite an existing one —
    generating a fresh key over a funded wallet is fund loss."""
    from eth_account import Account

    if chain not in CHAINS:
        return f"❌ Unknown chain {chain!r}. Supported: {', '.join(k for k in CHAINS if k != 'solana')}"

    wallet_path = WALLET_DIR / f"evm_{chain}.json"
    if wallet_path.exists():
        existing = load_evm_wallet(chain) or {}
        return (f"🛑 A {chain} wallet already exists ({existing.get('address', '?')[:10]}…). "
                f"Refusing to overwrite it — that would lose any funds on it. "
                f"Use import_evm_wallet to replace it deliberately.")

    account = Account.create()
    private_key = account.key.hex()
    address = account.address

    wallet = {
        "private_key": private_key,
        "address": address,
        "chain": chain,
        "created_at": datetime.now().isoformat(),
    }

    WALLET_DIR.mkdir(exist_ok=True)
    wallet_path = WALLET_DIR / f"evm_{chain}.json"
    wallet_path.write_text(json.dumps(wallet, indent=2))

    return (
        f"✅ New {CHAINS[chain]['name']} wallet created!\n"
        f"Address: `{address}`\n"
        f"Fund with {CHAINS[chain]['symbol']} to start trading!"
    )

def load_evm_wallet(chain: str = "ethereum") -> dict:
    """Load EVM wallet."""
    wallet_path = WALLET_DIR / f"evm_{chain}.json"
    if wallet_path.exists():
        return json.loads(wallet_path.read_text())
    return None

def get_evm_balance(chain: str = "ethereum") -> str:
    """Get EVM wallet balance."""
    try:
        from web3 import Web3

        wallet = load_evm_wallet(chain)
        if not wallet:
            return f"No {chain} wallet found. Create one first."

        w3 = Web3(Web3.HTTPProvider(CHAINS[chain]["rpc"]))
        address = wallet["address"]

        # Native balance
        balance_wei = w3.eth.get_balance(address)
        balance = w3.from_wei(balance_wei, 'ether')

        lines = [f"💼 *{CHAINS[chain]['name']} Wallet*\n"]
        lines.append(f"Address: `{address[:12]}...{address[-8:]}`")
        lines.append(f"💰 {CHAINS[chain]['symbol']}: {float(balance):.6f}")

        # Token balances (ERC-20)
        erc20_abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},{"constant":True,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}]

        tokens = KNOWN_EVM_TOKENS.get(chain, {})
        if tokens:
            lines.append(f"\n🪙 Tokens:")
            for symbol, contract_addr in tokens.items():
                try:
                    contract = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=erc20_abi)
                    decimals = contract.functions.decimals().call()
                    raw_balance = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
                    token_balance = raw_balance / (10 ** decimals)
                    if token_balance > 0:
                        lines.append(f"  • {symbol}: {token_balance:,.4f}")
                except:
                    continue

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# EVM Token Swaps (Uniswap)
# ============================================================

def evm_token_info(chain: str, token: str) -> str:
    """Identify any EVM token (0x address or symbol): on-chain identity
    (symbol/name/decimals/supply) + market data (price, liquidity, volume
    via DexScreener). This is how the agent 'looks up' an unknown token
    instead of claiming it can't be identified."""
    chain = (chain or "").lower()
    if chain not in ("ethereum", "base", "robinhood", "arbitrum", "optimism", "polygon"):
        return f"❌ Unknown chain {chain!r}. Use ethereum, base, robinhood, arbitrum, optimism or polygon."
    token = (token or "").strip()
    if not token:
        return "❌ Pass a token: 0x address or symbol."
    try:
        from evm_swap import _get_w3, _resolve_token
        w3 = _get_w3(chain)
        # Raw address: verify a contract actually exists before trusting
        # _resolve_token's silent fallbacks (it defaults to 18/"0x1111…" on
        # call failure, which would fabricate an identity for nothing).
        if token.startswith("0x") and len(token) == 42:
            from web3 import Web3 as _W3
            code = w3.eth.get_code(_W3.to_checksum_address(token))
            if not code or code in (b"", b"0x"):
                return (f"❌ No contract deployed at {token[:14]}… on {chain}. "
                        f"Check the address — or maybe the token lives on another chain.")
        t = _resolve_token(chain, token, w3)
    except Exception as e:
        return (f"❌ No contract at {token[:14]}… on {chain} ({str(e)[:80]}). "
                f"Check the address and chain.")
    lines = [f"🪙 {t['symbol']} on {chain}"]
    try:
        tok = w3.eth.contract(address=t["address"], abi=[
            {"constant": True, "inputs": [], "name": "name",
             "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "totalSupply",
             "outputs": [{"name": "", "type": "uint256"}], "type": "function"}])
        try:
            lines.append(f"   name: {tok.functions.name().call()}")
        except Exception:
            pass
        try:
            supply = tok.functions.totalSupply().call() / (10 ** t["decimals"])
            lines.append(f"   supply: {supply:,.0f} {t['symbol']}")
        except Exception:
            pass
    except Exception:
        pass
    lines.append(f"   decimals: {t['decimals']} | contract: {t['address']}")

    # Market data via DexScreener (covers all our chains incl. robinhood)
    try:
        import requests as _rq
        r = _rq.get(f"https://api.dexscreener.com/latest/dex/tokens/{t['address']}",
                    timeout=12, headers={"User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
        pairs = (r.json() or {}).get("pairs") or []
        mine = [p for p in pairs if p.get("chainId") == chain]
        if not mine:
            lines.append("   ⚠️ No DEX pool found — token exists but appears untradeable (no liquidity).")
            return "\n".join(lines)
        # Only pairs where OUR token is the base (a pair with our token as
        # quote prices the OTHER token — using it would print nonsense).
        mine = [p for p in mine
                if (p.get("baseToken") or {}).get("address", "").lower() == t["address"].lower()]
        if not mine:
            lines.append("   ⚠️ Token exists but no DEX pair prices it directly (only appears as a quote side) — treat as untradeable.")
            return "\n".join(lines)
        best = max(mine, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))
        liq = ((best.get("liquidity") or {}).get("usd")) or 0
        price = best.get("priceUsd") or "?"
        vol = ((best.get("volume") or {}).get("h24")) or 0
        chg = ((best.get("priceChange") or {}).get("h24"))
        lines.append(f"   price: ${price}  (24h: {f'{chg:+.1f}%' if chg is not None else '?'})")
        lines.append(f"   liquidity: ${liq:,.0f} on {best.get('dexId', '?')}  |  24h vol: ${vol:,.0f}")
        if liq < 10_000:
            lines.append("   🚨 Thin liquidity (<$10k) — slippage will be brutal and exits can be impossible.")
    except Exception as e:
        lines.append(f"   market data unavailable ({str(e)[:60]})")
    return "\n".join(lines)


def swap_evm_token(chain: str, token_in: str, token_out: str, amount: float,
                   usd_amount: float = None) -> str:
    """
    REAL swap on Ethereum/Base via Uniswap V3 (SwapRouter02).
    Signs with the local EVM wallet and broadcasts on-chain.
    When the user states a size in DOLLARS, pass usd_amount — converted at
    the live ETH rate. Other chains: not supported (was previously simulated).
    """
    chain = (chain or "").lower()
    if chain not in ("ethereum", "base", "robinhood"):
        return (f"❌ Real swaps are supported on ethereum, base and robinhood "
                f"only. {chain!r} has no verified router — refusing to simulate.")
    try:
        from evm_swap import real_swap_execute
        return real_swap_execute(chain, token_in, token_out, amount,
                                 usd_amount=usd_amount)
    except Exception as e:
        return f"❌ Swap failed: {e}"


# ============================================================
# Cross-Chain Bridge (Li.Fi)
# ============================================================

def get_bridge_quote(from_chain: str, to_chain: str, token: str, amount: float) -> str:
    """Get a cross-chain bridge quote."""
    try:
        from lifi_tools import lifi_quote
        return lifi_quote(from_chain, to_chain, token, token, amount)
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# Transaction History
# ============================================================

def get_tx_history(chain: str = "ethereum", limit: int = 10) -> str:
    """Get transaction history for a wallet."""
    try:
        wallet = load_evm_wallet(chain)
        if not wallet:
            return f"No {chain} wallet found."

        explorer = CHAINS[chain]["explorer"]
        address = wallet["address"]

        return (
            f"📜 *Transaction History ({CHAINS[chain]['name']})*\n\n"
            f"View all transactions on the explorer:\n"
            f"{explorer}/address/{address}\n\n"
            f"Use the explorer link above for full history."
        )
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# Token Metadata
# ============================================================

def get_token_metadata(chain: str, token_address: str) -> str:
    """Get token metadata from on-chain."""
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(CHAINS[chain]["rpc"]))
        erc20_abi = [
            {"constant":True,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"type":"function"},
            {"constant":True,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},
            {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
            {"constant":True,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"type":"function"},
        ]

        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=erc20_abi)

        name = contract.functions.name().call()
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        total_supply = contract.functions.totalSupply().call() / (10 ** decimals)

        explorer = CHAINS[chain]["explorer"]

        return (
            f"🪙 *Token Metadata*\n\n"
            f"Name: {name}\n"
            f"Symbol: {symbol}\n"
            f"Decimals: {decimals}\n"
            f"Total Supply: {total_supply:,.0f}\n"
            f"Contract: `{token_address}`\n"
            f"Explorer: {explorer}/token/{token_address}"
        )
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# Fiat On/Off Ramp Info
# ============================================================

def get_fiat_onramp_info() -> str:
    """Get info about fiat on-ramp options."""
    return (
        "💵 *Fiat On/Off Ramp Options:*\n\n"
        "*Buy Crypto with Card:*\n"
        "• MoonPay: moonpay.com (50+ countries)\n"
        "• Transak: transak.com\n"
        "• Ramp: ramp.com\n"
        "• Wyre: sendwyre.com\n\n"
        "*Buy with Bank Transfer:*\n"
        "• Coinbase: coinbase.com\n"
        "• Kraken: kraken.com\n"
        "• Binance: binance.com\n\n"
        "*Peer-to-Peer:*\n"
        "• Bisq: bisq.network (decentralized)\n"
        "• HodlHodl: hodlhodl.com\n\n"
        "⚠️ Always verify you're on the official website!"
    )


# ============================================================
# Prediction Markets
# ============================================================

def get_prediction_market_info() -> str:
    """Get info about prediction markets."""
    return (
        "🎰 *Prediction Markets:*\n\n"
        "*Polymarket:*\n"
        "• Largest crypto prediction market\n"
        "• Trade on politics, sports, crypto\n"
        "• polymarket.com\n\n"
        "*Kalshi:*\n"
        "• US-regulated prediction market\n"
        "• kalshi.com\n\n"
        "*Overtime (Thales):*\n"
        "• Decentralized sports betting\n"
        "•/overtime.trade\n\n"
        "💡 Use these to hedge your crypto positions!"
    )


# ============================================================
# Deposit Links
# ============================================================

def create_deposit_link(chain: str, token: str = "USDC") -> str:
    """Create a deposit link for receiving crypto."""
    wallet = load_evm_wallet(chain)
    if not wallet:
        return f"No {chain} wallet found."

    address = wallet["address"]
    explorer = CHAINS[chain]["explorer"]

    return (
        f"💳 *Deposit Link ({CHAINS[chain]['name']})*\n\n"
        f"Send {token} to:\n"
        f"`{address}`\n\n"
        f"Explorer: {explorer}/address/{address}\n\n"
        f"⚠️ Only send {CHAINS[chain]['name']} network tokens!"
    )


# ============================================================
# Hardware Wallet (Ledger)
# ============================================================

def get_hardware_wallet_info() -> str:
    """Get info about hardware wallet integration."""
    return (
        "🔐 *Hardware Wallet Support:*\n\n"
        "*Supported Wallets:*\n"
        "• Ledger Nano S/X/S Plus\n"
        "• Trezor One/Model T\n\n"
        "*Setup:*\n"
        "1. Connect via USB/Bluetooth\n"
        "2. Install the app (Ethereum, Solana, etc.)\n"
        "3. Import seed phrase into the bot\n"
        "4. Sign transactions on the device\n\n"
        "*Security:*\n"
        "• Private keys never leave the device\n"
        "• Physical button press required for signing\n"
        "• Protection against phishing\n\n"
        "💡 Recommended for holdings > $1000"
    )


# ============================================================
# Message Signing
# ============================================================

def sign_message(chain: str, message: str) -> str:
    """Sign a message with the wallet."""
    try:
        from eth_account import Account

        wallet = load_evm_wallet(chain)
        if not wallet:
            return f"No {chain} wallet found."

        signed = Account.sign_message(
            Account.hash_message(text=message),
            wallet["private_key"]
        )

        return (
            f"✍️ *Message Signed*\n\n"
            f"Message: {message[:50]}{'...' if len(message) > 50 else ''}\n"
            f"Signature: `{signed.signature.hex()[:64]}...`\n"
            f"Signer: `{wallet['address']}`"
        )
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# Gas Estimation
# ============================================================

def estimate_gas(chain: str, from_token: str, to_token: str, amount: float) -> str:
    """Estimate gas for a swap."""
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(CHAINS[chain]["rpc"]))
        gas_price = w3.eth.gas_price
        gas_price_gwei = w3.from_wei(gas_price, 'gwei')

        # Rough estimates
        swap_gas = 150000  # Typical Uniswap swap
        gas_cost_eth = float(gas_price_gwei) * swap_gas / 1e9

        # Get ETH price for USD estimate
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                eth_price = json.loads(resp.read().decode())["ethereum"]["usd"]
            gas_cost_usd = gas_cost_eth * eth_price
        except:
            gas_cost_usd = gas_cost_eth * 3000  # Rough estimate

        return (
            f"⛽ *Gas Estimate ({CHAINS[chain]['name']})*\n\n"
            f"Gas Price: {float(gas_price_gwei):.1f} Gwei\n"
            f"Estimated Gas: {swap_gas:,}\n"
            f"Cost: ~{gas_cost_eth:.6f} {CHAINS[chain]['symbol']} (~${gas_cost_usd:.2f})"
        )
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# Portfolio Across Chains
# ============================================================

def get_multichain_portfolio() -> str:
    """Get portfolio across all chains."""
    lines = ["🌐 *Multi-Chain Portfolio*\n"]

    # Solana
    try:
        from solana_trader import get_sol_balance, get_sol_price
        sol = get_sol_balance()
        sol_price = get_sol_price()
        sol_usd = sol * sol_price
        lines.append(f"☀️ Solana: {sol:.4f} SOL (~${sol_usd:.2f})")
    except:
        lines.append("☀️ Solana: No wallet")

    # EVM chains
    for chain in ["ethereum", "base", "polygon", "arbitrum", "optimism", "robinhood"]:
        wallet = load_evm_wallet(chain)
        if wallet:
            try:
                from web3 import Web3
                w3 = Web3(Web3.HTTPProvider(CHAINS[chain]["rpc"]))
                balance = float(w3.from_wei(w3.eth.get_balance(wallet["address"]), 'ether'))
                lines.append(f"🔷 {CHAINS[chain]['name']}: {balance:.6f} {CHAINS[chain]['symbol']}")
            except:
                lines.append(f"🔷 {CHAINS[chain]['name']}: Error fetching balance")
        else:
            lines.append(f"🔷 {CHAINS[chain]['name']}: No wallet")

    return "\n".join(lines)


# ============================================================
# Tool Registry
# ============================================================

MULTICHAIN_TOOLS = [
    # Token identification / info
    {"type": "function", "function": {"name": "evm_token_info", "description": "Identify ANY EVM token (0x address or symbol) on ethereum/base/robinhood/arbitrum/optimism/polygon: on-chain identity (name, symbol, decimals, supply) + live market data (price, liquidity, 24h volume/change via DexScreener). Use this BEFORE any swap with an unfamiliar token, and whenever asked what a token is.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "description": "ethereum, base, robinhood, arbitrum, optimism, polygon"}, "token": {"type": "string", "description": "0x contract address or symbol"}}, "required": ["chain", "token"]}}},
    # Multi-chain wallet
    {"type": "function", "function": {"name": "create_evm_wallet", "description": "Create EVM wallet for Ethereum/Base/Polygon.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "description": "ethereum, base, polygon, arbitrum, optimism"}}, "required": ["chain"]}}},
    {"type": "function", "function": {"name": "get_evm_balance", "description": "Check EVM wallet balance across chains.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}}, "required": ["chain"]}}},
    {"type": "function", "function": {"name": "get_multichain_portfolio", "description": "Portfolio across all chains.", "parameters": {"type": "object", "properties": {}}}},
    # Swaps
    {"type": "function", "function": {"name": "swap_evm_token", "description": "Execute a REAL token swap on Ethereum, Base, or Robinhood Chain via Uniswap V3. Signs with the local EVM wallet and broadcasts on-chain. Other chains are NOT supported. On Robinhood Chain, token_in/token_out must be 0x contract addresses (e.g. memecoins from the V2/V3 factories); ETH/USDC symbols also work. When the user states a size in DOLLARS (e.g. '$25 of PEPE'), pass usd_amount — converted at the live ETH rate; only pass amount when the user is explicit about the native unit.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["ethereum", "base", "robinhood"]}, "token_in": {"type": "string", "description": "ETH, USDC, WETH, or 0x address"}, "token_out": {"type": "string", "description": "ETH, USDC, WETH, or 0x address"}, "usd_amount": {"type": "number", "description": "Size in US dollars — PREFERRED when the user said '$X'"}, "amount": {"type": "number", "description": "Amount in token_in's native unit (only when user is explicit)"}}, "required": ["chain", "token_in", "token_out"]}}},
    # Bridge
    {"type": "function", "function": {"name": "get_bridge_quote", "description": "Get cross-chain bridge quote.", "parameters": {"type": "object", "properties": {"from_chain": {"type": "string"}, "to_chain": {"type": "string"}, "token": {"type": "string"}, "amount": {"type": "number"}}, "required": ["from_chain", "to_chain", "token", "amount"]}}},
    # Token data
    {"type": "function", "function": {"name": "get_token_metadata", "description": "Get token metadata from on-chain.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "token_address": {"type": "string"}}, "required": ["chain", "token_address"]}}},
    {"type": "function", "function": {"name": "estimate_gas", "description": "Estimate gas for a swap.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "from_token": {"type": "string"}, "to_token": {"type": "string"}, "amount": {"type": "number"}}, "required": ["chain", "from_token", "to_token", "amount"]}}},
    # Info
    {"type": "function", "function": {"name": "get_fiat_onramp_info", "description": "Fiat on/off ramp options.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_prediction_market_info", "description": "Prediction market info.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_hardware_wallet_info", "description": "Hardware wallet setup info.", "parameters": {"type": "object", "properties": {}}}},
    # Actions
    {"type": "function", "function": {"name": "create_deposit_link", "description": "Create deposit address.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "token": {"type": "string"}}, "required": ["chain"]}}},
    {"type": "function", "function": {"name": "sign_message", "description": "Sign a message with wallet.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "message": {"type": "string"}}, "required": ["chain", "message"]}}},
    {"type": "function", "function": {"name": "get_tx_history", "description": "Transaction history on explorer.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "limit": {"type": "number"}}, "required": ["chain"]}}},
]

MULTICHAIN_TOOL_MAP = {
    "evm_token_info": lambda a: evm_token_info(a.get("chain", "ethereum"), a["token"]),
    "create_evm_wallet": lambda a: create_evm_wallet(a.get("chain", "ethereum")),
    "get_evm_balance": lambda a: get_evm_balance(a.get("chain", "ethereum")),
    "get_multichain_portfolio": lambda a: get_multichain_portfolio(),
    "swap_evm_token": lambda a: swap_evm_token(
        a["chain"], a["token_in"], a["token_out"], float(a.get("amount", 0) or 0),
        usd_amount=(float(a["usd_amount"]) if a.get("usd_amount") is not None else None)),
    "get_bridge_quote": lambda a: get_bridge_quote(a["from_chain"], a["to_chain"], a["token"], float(a["amount"])),
    "get_token_metadata": lambda a: get_token_metadata(a["chain"], a["token_address"]),
    "estimate_gas": lambda a: estimate_gas(a["chain"], a["from_token"], a["to_token"], float(a["amount"])),
    "get_fiat_onramp_info": lambda a: get_fiat_onramp_info(),
    "get_prediction_market_info": lambda a: get_prediction_market_info(),
    "get_hardware_wallet_info": lambda a: get_hardware_wallet_info(),
    "create_deposit_link": lambda a: create_deposit_link(a["chain"], a.get("token", "USDC")),
    "sign_message": lambda a: sign_message(a["chain"], a["message"]),
    "get_tx_history": lambda a: get_tx_history(a.get("chain", "ethereum"), int(a.get("limit", 10))),
}
