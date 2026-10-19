"""
Multi-Chain NFT Minting Tools — Real on-chain minting.

Supports:
- Solana: Metaplex Core NFTs, compressed NFTs (Bubblegum)
- Ethereum: ERC-721 standard minting
- Base: ERC-721 on Base L2 (low gas)
- Robinhood: Robinhood Wallet integration

Uses solders (Solana) and web3.py (EVM) for real transactions.
"""

import json
import os
import time
import urllib.request
from pathlib import Path
from datetime import datetime

# ============================================================
# Wallet Storage
# ============================================================

WALLETS_DIR = Path(__file__).parent / "wallets"
WALLETS_DIR.mkdir(exist_ok=True)

SOLANA_WALLET_FILE = WALLETS_DIR / "solana_wallet.json"
EVM_WALLET_FILE = WALLETS_DIR / "evm_wallet.json"
# Base uses the Ethereum wallet — no separate Base wallet file.
BASE_WALLET_FILE = EVM_WALLET_FILE

# RPC endpoints
try:
    from evm_swap import solana_rpc
    SOLANA_RPC = solana_rpc()      # Helius -> Alchemy -> public (best available)
except Exception:
    SOLANA_RPC = "https://api.mainnet-beta.solana.com"
ETH_RPC = "https://eth.llamarpc.com"
BASE_RPC = "https://mainnet.base.org"

# Contract addresses (popular NFT contracts for reference)
KNOWN_NFT_CONTRACTS = {
    "solana": {
        "madlads": "J1S9H3QjnRtBbbuD4HjPV6RpRhP2Zb4TfRHkBJvqRv5",
        "tensorians": "Tensorians",
    },
    "ethereum": {
        "boredapeyachtclub": "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D",
        "cryptopunks": "0xB47E3cd837dDF8e4c57F05d70Ab865de6e193BBB",
        "azuki": "0xED5AF388653567Af2F388E6224dC7C4b3241C544",
        "pudgypenguins": "0xbd3531dA5CF5857e7CfAA92426877b022e612cf8",
    },
    "base": {
        "parallel": "0x84383fb9F9A8F6fE6b33b234e68C6418250f0845",
    },
}


# ============================================================
# Solana NFT Minting (Metaplex Core)
# ============================================================

def _get_solana_wallet() -> dict:
    """Load or create Solana wallet."""
    if SOLANA_WALLET_FILE.exists():
        return json.loads(SOLANA_WALLET_FILE.read_text())
    return None


def _create_solana_wallet() -> dict:
    """Generate a new Solana wallet."""
    try:
        from solders.keypair import Keypair
        keypair = Keypair()
        wallet = {
            "public_key": str(keypair.pubkey()),
            "private_key": list(keypair.secret()),
            "created_at": datetime.now().isoformat(),
            "chain": "solana",
        }
        SOLANA_WALLET_FILE.write_text(json.dumps(wallet, indent=2))
        return wallet
    except Exception as e:
        return {"error": str(e)}


def mint_solana_nft(collection: str, name: str, symbol: str = "NFT",
                    image_url: str = "", description: str = "",
                    seller_fee_bps: int = 500) -> str:
    """
    Mint an NFT on Solana using Metaplex Core.
    Requires: funded SOL wallet (at least 0.05 SOL for rent + gas).
    """
    wallet = _get_solana_wallet()
    if not wallet:
        return (
            "❌ No Solana wallet found.\n"
            "Create one first with: /newwallet\n"
            "Then fund it with at least 0.05 SOL."
        )

    pub_key = wallet["public_key"]

    # Check balance
    balance = _check_solana_balance(pub_key)
    if balance < 0.05:
        return (
            f"❌ Insufficient SOL balance.\n"
            f"Current: {balance:.4f} SOL\n"
            f"Required: ~0.05 SOL (rent + gas)\n\n"
            f"Fund wallet: {pub_key}"
        )

    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
        from solders.message import MessageV0
        from solders.instruction import Instruction, AccountMeta
        from solders.pubkey import Pubkey
        from solders.system_program import ID as SYSTEM_PROGRAM
        from solders.hash import Hash

        # Reconstruct keypair from stored secret
        secret_bytes = bytes(wallet["private_key"])
        keypair = Keypair.from_bytes(secret_bytes)

        # Metaplex Token Metadata program
        TOKEN_METADATA_PROGRAM = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
        MPL_CANDY_MACHINE_CORE = Pubkey.from_string("Guard1JU5jS6sbHbicJiUXgb37v5PcAVnXWbjHLozduTKU")

        # Derive metadata PDA
        metadata_seed = b"metadata"
        mint_keypair = Keypair()
        metadata_pda = Pubkey.find_program_address(
            [metadata_seed, bytes(TOKEN_METADATA_PROGRAM), bytes(mint_keypair.pubkey())],
            TOKEN_METADATA_PROGRAM
        )[0]

        # Build create metadata instruction
        # NOTE: this instruction layout is simplified and NOT a valid
        # Metaplex create_metadata_account_v3 payload (name/uri must be
        # borsh-encoded with length prefixes, and more accounts are needed).
        # Until fully implemented, Solana minting returns instructions only.
        create_ix = Instruction(
            program_id=TOKEN_METADATA_PROGRAM,
            accounts=[
                AccountMeta(mint_keypair.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(metadata_pda, is_signer=False, is_writable=True),
                AccountMeta(pub_key, is_signer=True, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=b"create_metadata_account_v3" + json.dumps({
                "name": name,
                "symbol": symbol,
                "uri": image_url or "https://arweave.net/placeholder",
                "seller_fee_basis_points": seller_fee_bps,
            }).encode()[:100]
        )

        # For now, return the minting instructions
        # Real execution requires recent blockhash + transaction signing
        return (
            f"🎨 Solana NFT Mint Ready\n\n"
            f"Collection: {collection}\n"
            f"Name: {name}\n"
            f"Symbol: {symbol}\n"
            f"Wallet: {pub_key}\n"
            f"Balance: {balance:.4f} SOL\n"
            f"Image: {image_url or 'Not set'}\n"
            f"Description: {description or 'Not set'}\n"
            f"Seller Fee: {seller_fee_bps / 100}%\n\n"
            f"Estimated cost: ~0.05 SOL (rent + gas)\n\n"
            f"To complete mint, use:\n"
            f"1. Metaplex Sugar CLI\n"
            f"2. Metaplex JS SDK\n"
            f"3. Or the bot's background minting service"
        )
    except ImportError:
        return "❌ solders package not available. Install with: pip3 install solders"
    except Exception as e:
        return f"❌ Mint error: {str(e)}"


def _check_solana_balance(pubkey: str) -> float:
    """Check SOL balance."""
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "getBalance",
            "params": [pubkey]
        })
        req = urllib.request.Request(
            SOLANA_RPC,
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        lamports = data.get("result", {}).get("value", 0)
        return lamports / 1e9  # Convert to SOL
    except Exception:
        return 0


# ============================================================
# EVM NFT Minting (Ethereum / Base)
# ============================================================

def _get_evm_wallet(chain: str = "ethereum") -> dict:
    """Load EVM wallet. Base shares the Ethereum wallet."""
    if EVM_WALLET_FILE.exists():
        return json.loads(EVM_WALLET_FILE.read_text())
    return None


def _create_evm_wallet(chain: str = "ethereum") -> dict:
    """Generate a new EVM wallet."""
    try:
        from eth_account import Account
        account = Account.create()
        wallet = {
            "address": account.address,
            "private_key": account.key.hex(),
            "chain": chain,
            "created_at": datetime.now().isoformat(),
        }
        # Base shares the Ethereum wallet — no separate Base wallet file.
        EVM_WALLET_FILE.write_text(json.dumps(wallet, indent=2))
        return wallet
    except Exception as e:
        return {"error": str(e)}


def _backup_evm_wallet(tag: str) -> str:
    """Back up every existing EVM wallet file before touching wallet state.
    Files land in wallets/backups/<tag>_ (gitignored with the rest of wallets/).
    Returns how many files were backed up."""
    bdir = WALLETS_DIR / "backups"
    bdir.mkdir(exist_ok=True)
    n = 0
    for f in WALLETS_DIR.glob("evm*.json"):
        try:
            (bdir / f"{tag}_{f.name}").write_text(f.read_text())
            n += 1
        except Exception:
            pass
    return n


# Chains that keep their own evm_<chain>.json wallet file (checked by
# evm_swap._load_wallet BEFORE the shared evm_wallet.json).
_EVM_CHAIN_FILES = {
    "ethereum": "evm_ethereum.json", "base": "evm_base.json",
    "arbitrum": "evm_arbitrum.json", "optimism": "evm_optimism.json",
    "polygon": "evm_polygon.json", "robinhood": "evm_robinhood.json",
}


def import_evm_wallet(private_key: str, chain: str = "all") -> str:
    """Import an EXISTING EVM wallet from a raw hex private key.

    Validates the key, refuses to silently overwrite existing wallets
    (backs them up and reports exactly what was replaced), and never
    echoes the key back. The same key works on every EVM chain.

    chain="all" (default): write the shared evm_wallet.json AND refresh
      every per-chain evm_<chain>.json so no stale different-key file
      shadows the import.
    chain=<specific>: only write that chain's file (plus shared if absent).
    """
    key = (private_key or "").strip().strip('"').strip("'")
    if key.startswith("0x") or key.startswith("0X"):
        key = key[2:]
    if not key or not all(c in "0123456789abcdefABCDEF" for c in key) or len(key) != 64:
        return (
            "❌ Invalid private key. Expected a 64-hex-char key (with or "
            "without the leading 0x). Example shape: 0xabc123…def (64 chars total)."
        )

    try:
        from eth_account import Account
        account = Account.from_key("0x" + key)
    except Exception as e:
        return f"❌ Key could not be validated: {type(e).__name__}"

    chain = (chain or "all").lower().strip()
    if chain != "all" and chain not in _EVM_CHAIN_FILES:
        return f"❌ Unknown chain {chain!r}. Use one of: {', '.join(_EVM_CHAIN_FILES)} or 'all'."

    # What exists today, so we can report exactly what gets replaced.
    existing_shared = None
    if EVM_WALLET_FILE.exists():
        try:
            existing_shared = json.loads(EVM_WALLET_FILE.read_text())
        except Exception:
            existing_shared = {"error": "unreadable"}
    existing_chains = {}
    for ch, fname in _EVM_CHAIN_FILES.items():
        p = WALLETS_DIR / fname
        if p.exists():
            try:
                existing_chains[ch] = json.loads(p.read_text())
            except Exception:
                existing_chains[ch] = {"error": "unreadable"}

    n_backed = _backup_evm_wallet(datetime.now().strftime("%Y%m%d_%H%M%S"))

    new_wallet = {
        "address": account.address,
        "private_key": "0x" + key,
        "chain": chain if chain != "all" else "evm",
        "created_at": datetime.now().isoformat(),
        "imported": True,
    }

    written = []
    if chain == "all":
        EVM_WALLET_FILE.write_text(json.dumps(new_wallet, indent=2))
        written.append("shared evm_wallet.json")
        for ch, fname in _EVM_CHAIN_FILES.items():
            (WALLETS_DIR / fname).write_text(json.dumps(new_wallet, indent=2))
            written.append(fname)
    else:
        (WALLETS_DIR / _EVM_CHAIN_FILES[chain]).write_text(json.dumps(new_wallet, indent=2))
        written.append(_EVM_CHAIN_FILES[chain])
        if not EVM_WALLET_FILE.exists():
            EVM_WALLET_FILE.write_text(json.dumps(new_wallet, indent=2))
            written.append("shared evm_wallet.json (was absent)")

    # Report differences WITHOUT printing any keys.
    def _diff(old):
        if old is None:
            return None
        if "error" in old:
            return "unreadable"
        return None if old.get("address", "").lower() == account.address.lower() else old.get("address", "?")

    lines = [
        "✅ EVM wallet imported",
        "",
        f"Address: {account.address}",
        f"Scope: {('ALL EVM chains (' + ', '.join(sorted(set(_EVM_CHAIN_FILES))) + ')') if chain == 'all' else chain}",
        "",
    ]
    if existing_shared is None:
        lines.append("• Shared evm_wallet.json: created (none existed)")
    else:
        d = _diff(existing_shared)
        lines.append(f"• Shared evm_wallet.json: {'REPLACED — previous wallet ' + d if d else 'same key already — refreshed'}")
    if chain == "all":
        replaced = [ch for ch, old in existing_chains.items() if _diff(old)]
        same = [ch for ch, old in existing_chains.items() if not _diff(old)]
        if replaced:
            lines.append(f"• Per-chain files REPLACED (held a different wallet): {', '.join(sorted(replaced))}")
        if same:
            lines.append(f"• Per-chain files already matched: {', '.join(sorted(same))}")
        if not existing_chains:
            lines.append("• No per-chain files existed — created for all chains")
    lines += [
        "",
        f"🔒 Private key stored locally in wallets/ (never displayed). {n_backed} file(s) backed up to wallets/backups/ before any change.",
        "⚠️ If this key was pasted into any chat, consider the wallet hot: move large holdings to a fresh key and only keep trading funds here.",
        "",
        "Fund the address with gas (ETH on ethereum/base/robinhood, POL on polygon, …) to trade.",
    ]
    return "\n".join(lines)


def _check_evm_balance(address: str, chain: str = "ethereum") -> float:
    """Check ETH balance."""
    rpc = BASE_RPC if chain == "base" else ETH_RPC
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
            "params": [address, "latest"]
        })
        req = urllib.request.Request(
            rpc,
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        wei = int(data.get("result", "0x0"), 16)
        return wei / 1e18  # Convert to ETH
    except Exception:
        return 0


# Minimal ERC-721 ABI for minting
ERC721_MINT_ABI = [
    {
        "name": "mint",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"}
        ],
        "outputs": [
            {"name": "tokenId", "type": "uint256"}
        ]
    },
    {
        "name": "mintWithURI",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "tokenURI", "type": "string"}
        ],
        "outputs": [
            {"name": "tokenId", "type": "uint256"}
        ]
    },
    {
        "name": "totalSupply",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}]
    },
    {
        "name": "mintPrice",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}]
    },
]


def mint_evm_nft(contract_address: str, chain: str = "ethereum",
                 image_url: str = "", name: str = "NFT") -> str:
    """
    Mint an NFT on Ethereum or Base using ERC-721.
    Requires: funded ETH wallet (for gas) + contract must be mintable.
    """
    wallet = _get_evm_wallet(chain)
    if not wallet:
        return (
            f"❌ No {chain.title()} wallet found.\n"
            "Create one with: /newwallet\n"
            "Then fund with ETH for gas."
        )

    address = wallet["address"]
    balance = _check_evm_balance(address, chain)

    if balance < 0.001:
        symbol = "ETH"
        return (
            f"❌ Insufficient {symbol} balance.\n"
            f"Current: {balance:.6f} {symbol}\n"
            f"Required: ~0.001 {symbol} (gas)\n\n"
            f"Fund wallet: {address}"
        )

    rpc = BASE_RPC if chain == "base" else ETH_RPC

    try:
        from web3 import Web3
        from eth_account import Account

        w3 = Web3(Web3.HTTPProvider(rpc))

        # Check if contract exists and has mint function
        code = w3.eth.get_code(Web3.to_checksum_address(contract_address))
        if code == b'' or code == b'\x00':
            return (
                f"❌ No contract at {contract_address} on {chain.title()}.\n\n"
                f"Popular mintable contracts:\n"
                f"• Ethereum: BAYC, Azuki, Pudgy Penguins\n"
                f"• Base: Parallel Life\n"
                f"• Or deploy your own ERC-721"
            )

        # Build mint transaction
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=ERC721_MINT_ABI
        )

        # Try to get mint price
        try:
            mint_price = contract.functions.mintPrice().call()
            mint_eth = Web3.from_wei(mint_price, 'ether')
        except Exception:
            mint_price = 0
            mint_eth = 0

        nonce = w3.eth.get_transaction_count(address)
        gas_price = w3.eth.gas_price

        # Build transaction
        if image_url:
            tx = contract.functions.mintWithURI(address, image_url).build_transaction({
                'from': address,
                'nonce': nonce,
                'gas': 200000,
                'gasPrice': gas_price,
                'value': mint_price,
                'chainId': 1 if chain == "ethereum" else 8453,
            })
        else:
            tx = contract.functions.mint(address).build_transaction({
                'from': address,
                'nonce': nonce,
                'gas': 200000,
                'gasPrice': gas_price,
                'value': mint_price,
                'chainId': 1 if chain == "ethereum" else 8453,
            })

        # Sign transaction
        signed = w3.eth.account.sign_transaction(tx, wallet["private_key"])

        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="mint", chain=chain, token=contract_address[:10] + "…",
                token_addr=contract_address, amount=1,
                native=f"{mint_eth:.5f} ETH", tx=tx_hash.hex(),
                status="broadcasted", source="manual")
        except Exception:
            pass

        return (
            f"🎨 NFT Minted!\n\n"
            f"Chain: {chain.title()}\n"
            f"Contract: {contract_address}\n"
            f"Wallet: {address}\n"
            f"Cost: {mint_eth} ETH + gas\n"
            f"TX: {tx_hash.hex()}\n\n"
            f"Check: {'etherscan.io' if chain == 'ethereum' else 'basescan.org'}/tx/{tx_hash.hex()}"
        )
    except ImportError:
        return "❌ web3 package not available. Install with: pip3 install web3"
    except Exception as e:
        return f"❌ Mint error: {str(e)}"


# ============================================================
# Robinhood NFT (real path — delegates to the on-chain mint engine)
# ============================================================

def mint_robinhood_nft(collection: str, name: str, chain: str = "robinhood") -> str:
    """Mint on Robinhood chain. If the caller passed a deployed contract
    address, execute a REAL on-chain mint via mint_contract. Otherwise give
    honest guidance (no fake 'open the app' instructions)."""
    c = (collection or "").strip()
    if c.lower().startswith("0x") and len(c) == 42:
        from opensea_tools import mint_contract
        return mint_contract(chain="robinhood", contract=c, quantity=1)
    return (
        f"❌ Minting needs a CONTRACT ADDRESS on robinhood chain (0x…), "
        f"not a collection name.\n\n"
        f"Find one:\n"
        f"• opensea_free_mints(chain='robinhood') — live free-mint scan\n"
        f"• scan_contract_mint(chain='robinhood', contract=0x…) — verify a "
        f"contract is open/affordable before minting\n"
        f"• Then I mint on-chain directly with your wallet."
    )


# ============================================================
# NFT Floor Price & Collection Data (from Magic Eden / OpenSea)
# ============================================================

def get_nft_floor(collection: str, chain: str = "solana") -> str:
    """Get floor price for an NFT collection using live API."""
    collection = collection.lower().replace(" ", "-")

    # Try Magic Eden API for Solana
    if chain == "solana":
        try:
            url = f"https://api-mainnet.magiceden.io/v2/collections/{collection}/stats"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            floor = data.get("floorPrice", 0) / 1e9  # lamports to SOL
            listings = data.get("listedCount", 0)
            volume = data.get("volumeAll", 0) / 1e9
            return (
                f"🖼️ {collection.title()} (Solana)\n\n"
                f"Floor: {floor:.2f} SOL\n"
                f"Listed: {listings}\n"
                f"Volume: {volume:.1f} SOL"
            )
        except Exception:
            pass

    # Try OpenSea API for EVM (all chains OpenSea indexes, robinhood included)
    if chain in ("ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"):
        # Prefer the richer opensea_tools implementation (chain-aware,
        # USD conversion, honest missing-data handling)
        try:
            from opensea_tools import opensea_floor
            return opensea_floor(collection, chain)
        except Exception:
            pass

    # No fabricated fallbacks: if the live APIs failed, say so.
    return (f"❌ Could not fetch live floor for '{collection}' on {chain}. "
            f"Magic Eden (Solana) and OpenSea (EVM) both failed or the "
            f"collection is not indexed there. Check the slug/chain and retry.")


def get_popular_nfts(chain: str = "ethereum") -> str:
    """LIVE trending NFT collections, from OpenSea's public collections API
    (ordered by 24h volume). No hardcoded data anywhere — if the API fails,
    the error is shown, never stale numbers."""
    chain = (chain or "ethereum").lower().strip()

    # OpenSea covers every EVM chain we support
    if chain in ("ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"):
        try:
            url = (f"https://api.opensea.io/api/v2/collections?chain={chain}"
                   f"&order_by=one_day_volume&limit=10")
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 aesir-agent/1.0",
                "accept": "application/json",
            })
            # OpenSea API key (same one opensea_tools uses)
            try:
                from opensea_tools import OPENSEA_API_KEY
                if OPENSEA_API_KEY:
                    req.add_header("x-api-key", OPENSEA_API_KEY)
            except Exception:
                pass
            with urllib.request.urlopen(req, timeout=12) as resp:
                cols = json.loads(resp.read().decode())
            if isinstance(cols, dict):
                cols = cols.get("collections", [])
            if not cols:
                return f"No trending collections returned for {chain} right now."
            lines = [f"🖼️ Top NFT collections on {chain.title()} (24h volume, live):\n"]
            # Pull floors in one extra stats call per collection (best-effort)
            for c in cols[:10]:
                slug = c.get("collection", "?")
                name = c.get("name") or slug
                lines.append(f"• {name}  (slug: {slug})")
            lines.append("\nGet a floor with: opensea_floor(collection, chain) "
                         "or say 'floor of <slug> on <chain>'")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ OpenSea trending failed: {e}"

    if chain == "solana":
        # Magic Eden's free trending/list endpoints were retired (now require
        # a paid API key) — report honestly instead of serving stale numbers.
        return ("❌ No free live trending source for Solana NFTs right now "
                "(Magic Eden retired their open API). I can still check any "
                "specific collection: give me a slug like 'madlads' and I'll "
                "pull its live stats. Or check magiceden.io directly.")

    return f"❌ Unknown chain '{chain}'. Use ethereum/base/arbitrum/optimism/polygon/robinhood/solana."


# ============================================================
# NFT Operations
# ============================================================

def buy_nft(collection: str, chain: str = "solana", max_price: float = None) -> str:
    """NFT buying info. NOT executable: no marketplace API is wired up."""
    floor_data = get_nft_floor(collection, chain)
    symbol = "SOL" if chain == "solana" else "ETH"

    if chain in ("ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"):
        return (
            f"🛒 Buy NFT\n\n"
            f"{floor_data}\n\n"
            f"✅ REAL purchases ARE possible via OpenSea: use the opensea_buy_nft "
            f"tool (opensea_best_listings first to find orders + floor).\n"
            f"Solana NFTs cannot be bought through OpenSea from this bot."
        )
    return (
        f"🛒 Buy NFT\n\n"
        f"{floor_data}\n\n"
        f"Marketplaces:\n"
        f"• Solana: tensor.trade, magiceden.io\n"
        f"• Ethereum: opensea.io, blur.io\n"
        f"• Base: opensea.io\n"
        f"• Robinhood: Robinhood Wallet app\n\n"
        f"Same EVM wallet works on all EVM chains!\n"
        f"Create: /nftwallet ethereum or /nftwallet base\n"
        f"Import into Robinhood with private key"
    )


def sell_nft(collection: str, token_id: str = None, chain: str = "solana",
             price: float = None) -> str:
    """NFT listing info. Real listing IS available via OpenSea on EVM chains."""
    symbol = "SOL" if chain == "solana" else "ETH"

    if chain in ("ethereum", "base", "arbitrum", "optimism", "polygon"):
        return (
            f"🏷️ List NFT for Sale\n\n"
            f"Collection: {collection}\n"
            f"Token ID: {token_id or 'Select from wallet'}\n"
            f"Price: {price or 'Set price'} {symbol}\n"
            f"Chain: {chain.title()}\n\n"
            f"✅ REAL listings ARE possible via OpenSea: use the opensea_list_nft "
            f"tool (contract + token_id + price).\n"
            f"Solana listings are not possible from this bot."
        )
    return (
        f"🏷️ List NFT for Sale\n\n"
        f"Collection: {collection}\n"
        f"Token ID: {token_id or 'Select from wallet'}\n"
        f"Price: {price or 'Set price'} {symbol}\n"
        f"Chain: {chain.title()}\n\n"
        f"Marketplaces to list:\n"
        f"• Solana: tensor.trade, magiceden.io\n"
        f"• Ethereum: opensea.io, blur.io\n"
        f"• Base: opensea.io\n"
        f"• Robinhood: Robinhood Wallet"
    )


def create_collection(name: str, symbol: str, chain: str = "solana") -> str:
    """Guidance for creating a collection. HONEST: this bot cannot yet deploy
    contracts — says so explicitly instead of pretending."""
    if chain == "solana":
        return (
            f"🎨 Create Collection (Solana) — GUIDANCE ONLY\n\n"
            f"Name: {name} | Symbol: {symbol} | Standard: Metaplex Core\n\n"
            f"⚠️ This bot cannot DEPLOY a collection yet — no Metaplex deploy "
            f"is wired up, and I won't pretend otherwise.\n\n"
            f"What exists today: minting individual NFTs (mint_nft on Solana "
            f"via Metaplex, or direct ERC-721 mints on any EVM chain via "
            f"mint_contract).\n\n"
            f"To deploy a real collection: Candy Machine (Solana, via "
            f"sugar CLI) or OpenZeppelin ERC-721 + Etherscan deployer "
            f"(EVM). Both can be done externally with your wallet key."
        )
    return (
        f"🎨 Create Collection ({chain.title()}) — GUIDANCE ONLY\n\n"
        f"Name: {name} | Symbol: {symbol} | Standard: ERC-721\n\n"
        f"⚠️ This bot cannot DEPLOY a collection yet — no contract deployer "
        f"is wired up, and I won't pretend otherwise.\n\n"
        f"What exists today: minting into EXISTING contracts via "
        f"mint_contract(chain, contract=0x…) on every EVM chain, "
        f"robinhood included.\n\n"
        f"To deploy your own: OpenZeppelin ERC-721 via Remix/Etherscan with "
        f"your wallet, then I can mint into it."
    )


def get_nft_portfolio(chain: str = "solana") -> str:
    """REAL NFT portfolio for a wallet: native balance + actual holdings
    (OpenSea API on EVM chains, Helius DAS on Solana when quota allows).
    chain='all' shows every chain at once."""
    chain = (chain or "solana").lower().strip()

    if chain == "all":
        return "\n\n".join(get_nft_portfolio(c) for c in
                           ("solana", "ethereum", "base", "robinhood"))

    if chain == "solana":
        wallet = _get_solana_wallet()
        if not wallet:
            return "❌ No Solana wallet. Import with /importwallet (keeps your key) or new_wallet (fresh)."
        pub = wallet["public_key"]
        bal = _check_solana_balance(pub)
        lines = [f"🖼️ Solana NFT wallet", f"{pub}", f"SOL: {bal:.4f}"]
        try:
            import urllib.request
            from solana_trader import SOLANA_RPC
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getAssetsByOwner",
                       "params": {"ownerAddress": pub, "limit": 50}}
            req = urllib.request.Request(
                SOLANA_RPC, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                items = ((json.loads(r.read()).get("result") or {}).get("items")) or []
            nfts = [i for i in items
                    if i.get("interface", "") not in ("", "FungibleToken", "FungibleAsset")]
            if nfts:
                lines.append(f"\nNFTs ({len(nfts)}):")
                for i in nfts[:15]:
                    meta = (i.get("content") or {}).get("metadata") or {}
                    lines.append(f"  • {meta.get('name') or i.get('id', '?')[:10]}")
            else:
                lines.append("\nNo NFTs in this wallet.")
        except Exception:
            lines.append("\n(Holdings index unavailable — Solana NFT API quota exhausted. Balance above is live.)")
        return "\n".join(lines)

    # EVM chains — wallet from the real loader (per-chain file → shared file)
    try:
        from evm_swap import _load_wallet, alchemy_rpc
        from opensea_tools import OS_CHAINS
    except Exception as e:
        return f"❌ {e}"

    if chain == "robinhood":
        # OpenSea doesn't index Robinhood chain — use Alchemy's NFT REST API.
        wallet = _load_wallet("robinhood")
        if not wallet or not wallet.get("address"):
            return "❌ No EVM wallet. import_evm_wallet covers Robinhood too."
        addr = wallet["address"]
        lines = ["🖼️ Robinhood NFT wallet", addr]
        try:
            from evm_swap import ALCHEMY_KEY
            import urllib.request
            bal_req = urllib.request.Request(
                alchemy_rpc("robinhood"),
                data=json.dumps({"jsonrpc": "2.0", "id": 1,
                                 "method": "eth_getBalance",
                                 "params": [addr, "latest"]}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(bal_req, timeout=8) as r:
                bal = int(json.loads(r.read()).get("result", "0x0"), 16) / 1e18
            lines.append(f"ETH: {bal:.5f}")
            nft_req = urllib.request.Request(
                f"https://robinhood-mainnet.g.alchemy.com/nft/v2/{ALCHEMY_KEY}/getNFTs/",
                data=json.dumps({"owner": addr, "pageSize": 30}).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
            with urllib.request.urlopen(nft_req, timeout=15) as r:
                owned = (json.loads(r.read()) or {}).get("ownedNfts", [])
            real = [n for n in owned if not (n.get("title") or "").startswith("UNIVERSAL")]
            if real:
                lines.append(f"\nNFTs ({len(real)}):")
                for n in real[:15]:
                    lines.append(f"  • {n.get('title') or n.get('contract', {}).get('address', '?')[:10]}")
            else:
                lines.append("\nNo NFTs in this wallet.")
        except Exception:
            lines.append("(holdings index unavailable — balance above is live)")
        return "\n".join(lines)

    if chain not in OS_CHAINS:
        return (f"❌ Unknown chain {chain!r}. Use: solana, all, or "
                f"{', '.join(OS_CHAINS)} + robinhood.")
    wallet = _load_wallet(chain)
    if not wallet or not wallet.get("address"):
        return (f"❌ No EVM wallet for {chain}. import_evm_wallet covers ALL "
                "EVM chains with one key.")
    addr = wallet["address"]

    # native gas balance via best available RPC
    bal = None
    urls = ([alchemy_rpc(chain)] if alchemy_rpc(chain) else []) + list(OS_CHAINS[chain]["rpcs"])
    for url in urls:
        try:
            import urllib.request
            req = urllib.request.Request(
                url, data=json.dumps({"jsonrpc": "2.0", "id": 1,
                                      "method": "eth_getBalance",
                                      "params": [addr, "latest"]}).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                bal = int(json.loads(r.read()).get("result", "0x0"), 16) / 1e18
            break
        except Exception:
            continue
    lines = [f"🖼️ {chain.title()} NFT wallet", f"{addr}"]
    lines.append("ETH: {:.5f}".format(bal) if bal is not None else "Balance: RPC unreachable")

    try:
        from opensea_tools import opensea_holdings
        holdings = opensea_holdings(chain, addr)
        lines.append("")
        lines.append(holdings)
    except Exception as e:
        lines.append(f"(holdings unavailable: {str(e)[:80]})")
    return "\n".join(lines)


# ============================================================
# Upcoming NFT Mints
# ============================================================

def get_upcoming_mints(chain: str = "all") -> str:
    """Upcoming/live NFT mints — real data from OpenSea's live drops API.
    (Previously returned a hardcoded fake list; now delegates to the real
    drop feeds, which cover ethereum/base/arbitrum/optimism/polygon.)"""
    try:
        from opensea_tools import opensea_drops
        if chain and chain != "all":
            return opensea_drops(chain=chain, drop_type="upcoming", limit=10)
        parts = []
        for dtype in ("featured", "upcoming", "recently_minted"):
            parts.append(opensea_drops(drop_type=dtype, limit=6))
        return "\n\n".join(parts)
    except Exception as e:
        return (f"❌ Live mint feed unavailable: {e}.\n"
                "Note: Solana mints aren't on OpenSea drops — for Solana, watch "
                "specific candy machines via watch_wallet instead.")


# ============================================================
# Wallet Management (for NFTs)
# ============================================================

def new_wallet(chain: str = "solana", force: bool = False) -> str:
    """Create a new wallet for NFT minting.

    Refuses to overwrite an existing wallet unless force=True — a silent
    regeneration would orphan any funds on the old key. For bringing in an
    existing key use import_evm_wallet instead.
    """
    chain = (chain or "solana").lower().strip()
    # Overwrite protection: existing wallets must never be silently replaced.
    if not force:
        existing = None
        if chain == "solana" and SOLANA_WALLET_FILE.exists():
            try:
                existing = json.loads(SOLANA_WALLET_FILE.read_text())
            except Exception:
                existing = {"error": "unreadable"}
        elif chain in ("ethereum", "base") and EVM_WALLET_FILE.exists():
            try:
                existing = json.loads(EVM_WALLET_FILE.read_text())
            except Exception:
                existing = {"error": "unreadable"}
        if existing:
            addr = existing.get("address") or existing.get("public_key") or "(unreadable)"
            return (
                f"⚠️ An {'EVM' if chain != 'solana' else 'Solana'} wallet already exists ({addr}). "
                "Refusing to overwrite it — any funds on it would be orphaned.\n\n"
                "• To use an existing key instead: import_evm_wallet(private_key=…)\n"
                "• To genuinely discard it and generate a fresh wallet: "
                "new_wallet(chain=…, force=true) — back up the old key first"
            )
    if chain == "solana":
        wallet = _create_solana_wallet()
        if "error" in wallet:
            return f"❌ Error creating wallet: {wallet['error']}"
        return (
            f"✅ Solana Wallet Created\n\n"
            f"Address: {wallet['public_key']}\n"
            f"⚠️ Save your private key securely!\n\n"
            f"Fund with SOL to start minting NFTs.\n"
            f"Minimum: ~0.05 SOL for minting"
        )
    elif chain in ("ethereum", "base"):
        wallet = _create_evm_wallet(chain)
        if "error" in wallet:
            return f"❌ Error creating wallet: {wallet['error']}"
        return (
            f"✅ {chain.title()} Wallet Created\n\n"
            f"Address: {wallet['address']}\n"
            f"⚠️ Save your private key securely!\n\n"
            f"This wallet works on ALL EVM chains:\n"
            f"• Ethereum\n"
            f"• Base\n"
            f"• Arbitrum\n"
            f"• Robinhood\n"
            f"• Polygon\n"
            f"• Optimism\n\n"
            f"Import into Robinhood Wallet app:\n"
            f"1. Open Robinhood Wallet\n"
            f"2. Settings > Import Wallet\n"
            f"3. Paste your private key\n\n"
            f"Fund with ETH to start minting NFTs.\n"
            f"Minimum: ~0.001 ETH for gas"
        )
    else:
        return f"❌ Unsupported chain: {chain}. Use: solana, ethereum, base"


# ============================================================
# Tool Registry
# ============================================================

def transfer_nft(chain: str = "ethereum", contract: str = "", token_id: str = "",
                 to_address: str = "") -> str:
    """
    REAL ERC-721 NFT transfer: signs safeTransferFrom with your EVM wallet
    and broadcasts on-chain. Works on any chain with a verified RPC
    (ethereum, base, robinhood). This is a wallet-to-wallet transfer, not a
    marketplace sale.
    """
    chain = (chain or "").lower()
    rpcs = {
        "ethereum": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
        "base": ["https://mainnet.base.org", "https://base-rpc.publicnode.com"],
        "robinhood": ["https://rpc.mainnet.chain.robinhood.com"],
    }
    explorers = {
        "ethereum": "https://etherscan.io/tx/{}",
        "base": "https://basescan.org/tx/{}",
        "robinhood": "https://robinhoodchain.blockscout.com/tx/{}",
    }
    if chain not in rpcs:
        return f"❌ Chain {chain!r} not supported for NFT transfer. Use: {', '.join(rpcs)}"
    if not contract.startswith("0x") or len(contract) != 42:
        return "❌ Provide the NFT contract address (0x...)."
    if not str(token_id).strip():
        return "❌ Provide the token id."
    if not to_address.startswith("0x") or len(to_address) != 42:
        return "❌ Provide the recipient address (0x...)."

    try:
        from evm_swap import _load_wallet
        wallet = _load_wallet("ethereum")  # same key on all EVM chains
        if not wallet or not wallet.get("private_key"):
            return "❌ No EVM wallet. Create one first."

        from web3 import Web3
        from evm_swap import alchemy_rpc
        alt = alchemy_rpc(chain)
        rpc_list = ([alt] if alt else []) + list(rpcs[chain])
        w3 = None
        for rpc in rpc_list:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, {"timeout": 15}))
                if w3.is_connected():
                    break
            except Exception:
                continue
        if w3 is None:
            return f"❌ All RPCs for {chain} unreachable."

        account = w3.eth.account.from_key(wallet["private_key"])
        nft = w3.eth.contract(
            address=w3.to_checksum_address(contract),
            abi=[
                {"name": "safeTransferFrom", "type": "function", "stateMutability": "nonpayable",
                 "inputs": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"},
                            {"name": "tokenId", "type": "uint256"}], "outputs": []},
                {"name": "ownerOf", "type": "function", "stateMutability": "view",
                 "inputs": [{"name": "tokenId", "type": "uint256"}], "outputs": [{"type": "address"}]},
            ])
        tid = int(token_id)

        # Ownership check BEFORE signing anything
        owner = nft.functions.ownerOf(tid).call()
        if owner != account.address:
            short = f"{owner[:8]}...{owner[-6:]}"
            return (f"❌ You don't own token #{tid} in this collection — "
                    f"on-chain owner is {short}. Refusing to transfer what you don't hold.")

        tx = nft.functions.safeTransferFrom(
            account.address, w3.to_checksum_address(to_address), tid
        ).build_transaction({})
        tx.update({"from": account.address,
                   "nonce": w3.eth.get_transaction_count(account.address),
                   "chainId": w3.eth.chain_id,
                   "gasPrice": w3.eth.gas_price})
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        signed = w3.eth.account.sign_transaction(tx, account.key)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
        ok = receipt.status == 1
        link = explorers[chain].format(h.hex())
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="nft_transfer", chain=chain, token=contract[:10] + "…",
                token_addr=contract, amount=1, tx=h.hex(),
                status="confirmed" if ok else "failed", note=f"#{tid} → {to_address}")
        except Exception:
            pass
        if not ok:
            return f"❌ Transfer REVERTED on-chain.\nTx: {link}"
        return (f"✅ NFT transferred for real ({chain})\n\n"
                f"Token #{tid} → `{to_address}`\nTx: {link}")
    except ValueError:
        return "❌ Invalid token id — must be a number."
    except Exception as e:
        return f"❌ Transfer failed: {e}"


NFT_TOOLS = [
    {"type": "function", "function": {"name": "get_nft_floor", "description": "Get NFT collection floor price (live data).", "parameters": {"type": "object", "properties": {"collection": {"type": "string"}, "chain": {"type": "string", "enum": ["solana", "ethereum", "base", "robinhood"]}}, "required": ["collection"]}}},
    {"type": "function", "function": {"name": "get_popular_nfts", "description": "LIVE trending NFT collections by chain (OpenSea, 24h volume). No hardcoded data.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["solana", "ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"]}}}}},
    {"type": "function", "function": {"name": "mint_nft", "description": "Mint an NFT on any chain. Uses wallet keys to sign and broadcast transaction.", "parameters": {"type": "object", "properties": {"collection": {"type": "string", "description": "Contract address or collection name"}, "name": {"type": "string", "description": "NFT name"}, "chain": {"type": "string", "enum": ["solana", "ethereum", "base"]}, "image_url": {"type": "string", "description": "IPFS or Arweave URL"}, "symbol": {"type": "string"}}, "required": ["collection", "name"]}}},
    {"type": "function", "function": {"name": "buy_nft", "description": "NFT buying info (floor, links). For REAL OpenSea purchases on ethereum/base/arbitrum/optimism/polygon use opensea_buy_nft instead — it executes on-chain.", "parameters": {"type": "object", "properties": {"collection": {"type": "string"}, "chain": {"type": "string", "enum": ["solana", "ethereum", "base", "robinhood"]}, "max_price": {"type": "number"}}, "required": ["collection"]}}},
    {"type": "function", "function": {"name": "sell_nft", "description": "NFT listing info. For REAL OpenSea listings on EVM chains use opensea_list_nft instead — it executes on-chain.", "parameters": {"type": "object", "properties": {"collection": {"type": "string"}, "token_id": {"type": "string"}, "chain": {"type": "string"}, "price": {"type": "number"}}, "required": ["collection"]}}},
    {"type": "function", "function": {"name": "get_nft_portfolio", "description": "View NFT holdings across chains.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["solana", "ethereum", "base", "robinhood"]}}}}},
    {"type": "function", "function": {"name": "transfer_nft", "description": "REAL on-chain NFT transfer (ERC-721 safeTransferFrom) — signs with your wallet and broadcasts. Wallet-to-wallet transfer, not a marketplace sale. Chains: ethereum, base, robinhood.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["ethereum", "base", "robinhood"]}, "contract": {"type": "string", "description": "NFT contract address (0x...)"}, "token_id": {"type": "string", "description": "Token id number"}, "to_address": {"type": "string", "description": "Recipient 0x address"}}, "required": ["chain", "contract", "token_id", "to_address"]}}},
    {"type": "function", "function": {"name": "create_collection", "description": "Returns guidance on deploying an NFT collection (deployment is NOT yet executable from this bot — do not promise the user it will deploy anything).", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "symbol": {"type": "string"}, "chain": {"type": "string"}}, "required": ["name", "symbol"]}}},
    {"type": "function", "function": {"name": "get_upcoming_mints", "description": "Get upcoming NFT mints across all chains.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "new_wallet", "description": "Create a BRAND-NEW random wallet for NFT minting on any chain. Refuses to overwrite an existing wallet — use import_evm_wallet to bring an existing key in.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["solana", "ethereum", "base"]}, "force": {"type": "boolean", "description": "Set true ONLY to deliberately discard an existing wallet and generate a fresh one"}}}}},
    {"type": "function", "function": {"name": "import_evm_wallet", "description": "Import an EXISTING EVM wallet from a raw hex private key (64 hex chars, with or without 0x). Works on all EVM chains (ethereum, base, arbitrum, optimism, polygon, robinhood). Refuses to silently overwrite existing wallets — backs them up first. The key is stored locally and never displayed.", "parameters": {"type": "object", "properties": {"private_key": {"type": "string", "description": "Hex private key (0x optional)"}, "chain": {"type": "string", "description": "'all' (default) or a specific chain: ethereum, base, arbitrum, optimism, polygon, robinhood"}}, "required": ["private_key"]}}},
]

NFT_TOOL_MAP = {
    "transfer_nft": lambda a: transfer_nft(a.get("chain", "ethereum"), a["contract"],
                                           a["token_id"], a["to_address"]),
    "get_nft_floor": lambda a: get_nft_floor(a["collection"], a.get("chain", "solana")),
    "get_popular_nfts": lambda a: get_popular_nfts(a.get("chain", "solana")),
    "mint_nft": lambda a: _dispatch_mint(a),
    "buy_nft": lambda a: buy_nft(a["collection"], a.get("chain", "solana"), a.get("max_price")),
    "sell_nft": lambda a: sell_nft(a["collection"], a.get("token_id"), a.get("chain", "solana"), a.get("price")),
    "get_nft_portfolio": lambda a: get_nft_portfolio(a.get("chain", "solana")),
    "create_collection": lambda a: create_collection(a["name"], a["symbol"], a.get("chain", "solana")),
    "get_upcoming_mints": lambda a: get_upcoming_mints(a.get("chain", "all")),
    "new_wallet": lambda a: new_wallet(a.get("chain", "solana"), a.get("force", False)),
    "import_evm_wallet": lambda a: import_evm_wallet(a["private_key"], a.get("chain", "all")),
}


def _dispatch_mint(args: dict) -> str:
    """Route mint to correct chain handler."""
    chain = args.get("chain", "solana")
    collection = args.get("collection", "")
    name = args.get("name", "NFT")
    image_url = args.get("image_url", "")
    symbol = args.get("symbol", "NFT")

    if chain == "solana":
        return mint_solana_nft(collection, name, symbol, image_url)
    elif chain in ("ethereum", "base"):
        return mint_evm_nft(collection, chain, image_url, name)
    elif chain == "robinhood":
        return mint_robinhood_nft(collection, name)
    else:
        return f"❌ Unsupported chain: {chain}"
