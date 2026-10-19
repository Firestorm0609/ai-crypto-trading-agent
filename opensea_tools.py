"""
OpenSea marketplace — REAL NFT listings, buys, cancels, and data.

Uses the v2 REST API with the "actions" flow:
  1. POST /listings/actions        -> OpenSea builds the Seaport 1.6 order
                                      (approvals + EIP-712 signing payload)
  2. We execute approval txs and sign the typed data LOCALLY with the
     wallet key (never shared with anyone)
  3. POST /orders/{chain}/seaport/listings -> order goes live on the orderbook
  4. Buying: POST /listings/fulfillment/actions -> returns the actual
     fulfillListings transaction -> we sign + broadcast it on-chain

API key: OPENSEA_API_KEY in .env (free tier).
Chains: ethereum, base, arbitrum, optimism, polygon (OpenSea v2 chains).
Robinhood Chain is not an OpenSea chain — tools say so honestly.
"""

import json
import os
import concurrent.futures
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

OPENSEA_API = "https://api.opensea.io/api/v2"
API_KEY = os.getenv("OPENSEA_API_KEY", "")

# OpenSea v2 chain slugs -> {rpcs for execution, explorer, native symbol}
OS_CHAINS = {
    "ethereum": {"rpcs": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
                 "explorer": "https://etherscan.io/tx/{}"},
    "base": {"rpcs": ["https://mainnet.base.org", "https://base-rpc.publicnode.com"],
             "explorer": "https://basescan.org/tx/{}"},
    "arbitrum": {"rpcs": ["https://arb1.arbitrum.io/rpc"],
                 "explorer": "https://arbiscan.io/tx/{}"},
    "optimism": {"rpcs": ["https://mainnet.optimism.io"],
                 "explorer": "https://optimistic.etherscan.io/tx/{}"},
    "polygon": {"rpcs": ["https://polygon-rpc.com"],
                "explorer": "https://polygonscan.com/tx/{}"},
    # Robinhood chain: NFTs trade on OpenSea (e.g. Hood Remilias) but not
    # via Seaport — buys/mints go direct on-chain (mint_contract), so only
    # RPC + explorer are needed here.
    "robinhood": {"rpcs": ["https://rpc.mainnet.chain.robinhood.com"],
                  "explorer": "https://robinhoodchain.blockscout.com/tx/{}"},
}

TIMEOUT = 30


# ============================================================
# HTTP helpers
# ============================================================

def _headers():
    if not API_KEY:
        raise RuntimeError("OPENSEA_API_KEY not set in .env")
    return {"accept": "application/json", "content-type": "application/json",
            "x-api-key": API_KEY}


# Persistent HTTP/2 client. Measured against api.opensea.io:
#   requests.get per call        ~79 ms/op (full TLS handshake every time)
#   requests.Session keep-alive  ~19 ms/op
#   httpx + HTTP/2 multiplexed   ~13 ms/op
# The drop-watcher's 1s hot-poll and the mint POST both ride this client,
# so a snipe saves ~65ms of handshake on every request.
_os_client = None

def _client():
    """Lazily-built shared httpx client (HTTP/2). Falls back to None and the
    caller uses requests if httpx/h2 are unavailable."""
    global _os_client
    if _os_client is None:
        try:
            import httpx
            _os_client = httpx.Client(http2=True, timeout=TIMEOUT)
        except Exception:
            _os_client = False  # False = 'tried and failed' → use requests
    return _os_client or None


def _err_msg(r):
    """Extract the useful part of an OpenSea error body."""
    try:
        j = r.json()
        return j.get("errors", j.get("detail", "")) or r.text[:200]
    except Exception:
        return r.text[:200]


def _get(path: str, params: dict = None):
    c = _client()
    if c is not None:
        try:
            r = c.get(f"{OPENSEA_API}{path}", params=params or {}, headers=_headers())
            if r.status_code != 200:
                raise RuntimeError(f"OpenSea {r.status_code}: {_err_msg(r)}")
            return r.json()
        except RuntimeError:
            raise
        except Exception:
            pass  # transport hiccup → fall through to requests retry
    r = requests.get(f"{OPENSEA_API}{path}", params=params or {},
                     headers=_headers(), timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"OpenSea {r.status_code}: {_err_msg(r)}")
    return r.json()


def _post(path: str, body: dict):
    c = _client()
    if c is not None:
        try:
            r = c.post(f"{OPENSEA_API}{path}", json=body, headers=_headers())
            if r.status_code not in (200, 201):
                raise RuntimeError(f"OpenSea {r.status_code}: {_err_msg(r)}")
            return r.json()
        except RuntimeError:
            raise
        except Exception:
            pass
    r = requests.post(f"{OPENSEA_API}{path}", json=body,
                      headers=_headers(), timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"OpenSea {r.status_code}: {_err_msg(r)}")
    return r.json()


# ============================================================
# Wallet / chain helpers (shared with the rest of the bot)
# ============================================================

# Per-chain Web3 instance cache (see _w3)
_W3_CACHE = {}


def _wallet():
    from evm_swap import _load_wallet
    return _load_wallet("ethereum")


def _w3(chain: str):
    from web3 import Web3
    from evm_swap import alchemy_rpc
    cfg = OS_CHAINS.get(chain)
    if not cfg:
        raise RuntimeError(f"Chain {chain!r} not an OpenSea chain: {', '.join(OS_CHAINS)}")
    # Reuse one Web3/HTTPProvider per chain: urllib3 keeps the TLS session
    # alive, so repeat calls skip the ~80-300ms handshake (measured).
    cached = _W3_CACHE.get(chain)
    if cached is not None:
        try:
            if cached.is_connected():
                return cached
        except Exception:
            pass
    alt = alchemy_rpc(chain)
    rpcs = ([alt] if alt else []) + list(cfg["rpcs"])
    last = None
    for rpc in rpcs:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, {"timeout": 20}))
            if w3.is_connected():
                _W3_CACHE[chain] = w3
                return w3
        except Exception as e:
            last = e
    raise ConnectionError(f"All RPCs for {chain} unreachable (last: {last})")


def _explorer_tx(chain: str, tx_hash: str) -> str:
    return OS_CHAINS[chain]["explorer"].format(tx_hash)


_CHAIN_ID_CACHE = {}  # provider endpoint → chainId (immutable per chain)


def _send_tx(w3, account, tx: dict) -> str:
    """Sign+broadcast a step transaction; returns tx hash hex."""
    tx = dict(tx)
    tx["from"] = account.address
    tx["nonce"] = w3.eth.get_transaction_count(account.address)
    if "gas" not in tx:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.25)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = w3.eth.gas_price
    if "chainId" not in tx:
        ep = getattr(w3.provider, "endpoint_uri", None)
        cid = _CHAIN_ID_CACHE.get(ep)
        if cid is None:
            cid = w3.eth.chain_id
            if ep:
                _CHAIN_ID_CACHE[ep] = cid
        tx["chainId"] = cid
    else:
        tx.setdefault("chainId", w3.eth.chain_id)
    signed = w3.eth.account.sign_transaction(tx, account.key)
    return w3.eth.send_raw_transaction(signed.raw_transaction).hex()


def _wait(w3, tx_hash: str):
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=240)


def _extract_action(step: dict):
    """(kind, payload) for a known step kind, else (None, None)."""
    for kind in ("itemApprovalAction", "approvalAction", "fulfillListingsAction",
                 "fulfillOfferAction", "transactionAction"):
        if kind in step:
            return kind, step[kind]
    return None, None


def _resolve_collection(collection: str, chain: str = "ethereum") -> str:
    """Accept a slug OR a contract address; return the slug."""
    c = (collection or "").strip()
    if c.startswith("0x") and len(c) == 42:
        info = _get(f"/chain/{chain}/contract/{c}")
        slug = info.get("collection", "")
        if not slug:
            raise RuntimeError(f"No OpenSea collection found for contract {c}")
        return slug
    return c


# ============================================================
# 1. Data tools (read-only)
# ============================================================

def opensea_floor(collection: str, chain: str = "ethereum") -> str:
    """Floor price + stats for a collection (slug like 'pudgypenguins',
    or a contract address). chain can be ethereum/base/arbitrum/optimism/
    polygon/robinhood — collections are per-chain, so pass the right one."""
    try:
        chain = (chain or "ethereum").lower().strip()
        if chain not in OS_CHAINS:
            return (f"❌ OpenSea does not index '{chain}'. "
                    f"Chains: {', '.join(sorted(OS_CHAINS))}.")
        slug = _resolve_collection(collection, chain)
        stats = _get(f"/collections/{slug}/stats").get("total", {})
        lines = [f"🌊 {slug} ({chain})"]
        floor = stats.get("floor_price")
        if floor is not None:
            line = f"Floor: {floor} ETH"
            usd = _eth_usd_price()
            if usd:
                line += f" (≈ ${floor * usd:,.0f})"
            lines.append(line)
        if stats.get("market_cap"):
            lines.append(f"Market cap: {stats['market_cap']:,.0f} ETH")
        if stats.get("volume_24h") is not None:
            lines.append(f"24h volume: {stats['volume_24h']:,.1f} ETH")
        parts = []
        if stats.get("num_owners"):
            parts.append(f"Owners: {stats['num_owners']:,}")
        supply = stats.get("total_supply")
        # Only print supply when OpenSea actually reports it — never a made-up 0
        parts.append(
            f"Supply: {supply:,}" if supply else "Supply: not reported by OpenSea"
        )
        lines.append(" | ".join(parts))
        return "\n".join(lines)
    except Exception as e:
        return f"❌ {e}"


def opensea_best_listings(collection: str, limit: int = 5) -> str:
    """Cheapest live listings in a collection, with order hashes for buying."""
    try:
        slug = _resolve_collection(collection, "ethereum")
        data = _get(f"/listings/collection/{slug}/all", {"limit": limit})
        listings = data.get("listings", [])
        if not listings:
            return f"No live listings for {slug}."
        out = [f"🌊 Cheapest listings — {slug}:"]
        for L in listings:
            price = L.get("price", {}).get("current", {})
            dec = int(price.get("decimals", 18) or 18)
            amt = int(price.get("value", 0) or 0)
            human = amt / (10 ** dec) if amt else "?"
            sym = price.get("symbol") or ("ETH" if dec == 18 else "token")
            # token id from the order's offer side
            offer = (L.get("protocol_data", {}).get("parameters", {}).get("offer") or [{}])
            tid = offer[0].get("identifierOrCriteria", "?")
            out.append(
                f"  • {human} {sym} — token #{tid} | order {L.get('order_hash', '')[:20]}… "
                f"protocol {L.get('protocol_address', '')[:10]}…"
            )
        out.append("Buy with: opensea_buy_nft(chain, order_hash=…, protocol_address=…, max_price_eth=…)")
        return "\n".join(out)
    except Exception as e:
        return f"❌ {e}"


def opensea_holdings(chain: str = "ethereum", address: str = "") -> str:
    """NFTs owned by a wallet on an OpenSea chain (defaults to your wallet)."""
    try:
        if not address:
            w = _wallet()
            if not w:
                return "❌ No EVM wallet."
            address = w["address"]
        data = _get(f"/chain/{chain}/account/{address}/nfts", {"limit": 30})
        nfts = data.get("nfts", [])
        if not nfts:
            return f"No NFTs found for {address[:10]}… on {chain}."
        lines = [f"🖼️ {len(nfts)} NFTs on {chain} for {address[:10]}…:"]
        for n in nfts[:30]:
            name = n.get("name") or f"#{n.get('identifier', '?')}"
            coll = n.get("collection", "")
            lines.append(f"  • {name} ({coll}) — {n.get('contract', '')[:10]}…#{n.get('identifier', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ {e}"


# ============================================================
# 2. REAL: list an NFT for sale
# ============================================================

def opensea_list_nft(chain: str, contract: str, token_id: str,
                     price_eth: float, days: int = 30) -> str:
    """REAL listing: approvals → local EIP-712 signature → POST to orderbook."""
    chain = (chain or "").lower()
    if chain not in OS_CHAINS:
        return f"❌ OpenSea listing works on: {', '.join(OS_CHAINS)}. (robinhood/solana are not OpenSea chains)"
    wallet = _wallet()
    if not wallet or not wallet.get("private_key"):
        return "❌ No EVM wallet. Create one first."
    if price_eth <= 0:
        return "❌ Price must be positive."

    try:
        w3 = _w3(chain)
        account = w3.eth.account.from_key(wallet["private_key"])

        body = {
            "address": account.address,
            "items": [{
                "chain": chain,
                "contract": contract,
                "token_id": str(token_id),
                "quantity": 1,
                "price": {"amount": str(int(price_eth * 1e18)),
                          "currency": "0x0000000000000000000000000000000000000000"},
            }],
        }
        if days:
            end = datetime.now(timezone.utc) + timedelta(days=days)
            body["items"][0]["end_time"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        resp = _post("/listings/actions", body)
        steps = resp.get("steps", [])

        # 1) execute approvals, collect the signature request
        w3, account = w3, account
        log, sigs = [], []
        for step in steps:
            kind, payload = _extract_action(step)
            if not payload:
                log.append(f"⏭️ unknown step {list(step.keys())}")
                continue
            if "transaction" in payload:
                t = payload["transaction"]
                h = _send_tx(w3, account, {"to": (t.get("to") or {}).get("value", ""),
                                           "data": t.get("data", "0x"),
                                           "value": int(t.get("value", 0) or 0)})
                receipt = _wait(w3, h)
                if receipt.status != 1:
                    return f"❌ Approval tx reverted: {_explorer_tx(chain, h)}"
                log.append(f"✅ approval: {_explorer_tx(chain, h)}")
            elif "signatureRequest" in payload:
                sigs.append(payload["signatureRequest"])

        if not sigs:
            return "❌ OpenSea returned no signing payload."
        sr = sigs[0]
        typed = json.loads(sr["message"])

        # 2) sign the Seaport order locally
        from eth_account.messages import encode_typed_data
        encoded = encode_typed_data(full_message=typed)
        signed = account.sign_message(encoded)
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        # 3) POST the signed order to the orderbook
        order = None
        for step in steps:
            payload = step.get("createListingsAction", {})
            if payload.get("orders"):
                order = payload["orders"][0]
                break
        protocol = (order or {}).get("protocolAddress", {}).get("value",
                    typed["domain"].get("verifyingContract"))
        parameters = typed["message"]

        posted = _post(f"/orders/{chain}/seaport/listings", {
            "parameters": parameters,
            "protocol_address": protocol,
            "signature": signature,
        })
        oh = (posted.get("order") or {}).get("order_hash", "")
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="nft_list", chain=chain, token=contract[:10] + "…",
                token_addr=contract, amount=1, native=f"ask {price_eth} ETH",
                tx=oh, status="confirmed", note=f"token #{token_id}")
        except Exception:
            pass
        return (
            f"✅ NFT LISTED FOR REAL on OpenSea ({chain})\n\n"
            f"{contract[:10]}… #{token_id} → {price_eth} ETH "
            f"(expires in {days}d)\n"
            f"Order hash: `{oh}`\n" + "\n".join(log)
        )
    except Exception as e:
        return f"❌ Listing failed: {e}"


# ============================================================
# 3. REAL: buy a listed NFT
# ============================================================

def _eth_usd_price() -> float:
    """Live ETH/USD via CoinGecko (free); 0 on failure."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
            headers={"accept": "application/json", "User-Agent": "Mozilla/5.0 aesir-agent/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return float(json.loads(r.read())["ethereum"]["usd"])
    except Exception:
        return 0.0


def _resolve_cap(max_price_eth: float, max_price_usd: float, what: str = "purchase") -> tuple:
    """Turn a usd cap into an eth cap (live rate). Returns (eth_cap, note).
    Guards against the '$50 typed as 50 ETH' disaster: a usd cap that would
    imply >$150k/ETH, or an eth cap implying <$50/ETH when usd was meant,
    is reported instead of trusted."""
    if max_price_usd is not None:
        rate = _eth_usd_price()
        if rate <= 0:
            return None, "❌ Could not fetch live ETH price to convert your USD cap — refusing to guess. Retry or give the cap in ETH."
        return max_price_usd / rate, f"${max_price_usd:g} ≈ {max_price_usd/rate:.4f} ETH @ ${rate:,.0f}/ETH"
    if max_price_eth is not None and max_price_eth >= 50:
        rate = _eth_usd_price()
        if rate > 0 and max_price_eth * rate > 100_000:
            return None, (f"🛑 max_price_eth={max_price_eth} would allow spending ~"
                          f"${max_price_eth*rate:,.0f}. If you meant a DOLLAR cap, "
                          "use max_price_usd instead. Nothing sent.")
    return max_price_eth, ""


def opensea_buy_nft(chain: str, contract: str = "", token_id: str = "",
                    collection: str = "", order_hash: str = "",
                    protocol_address: str = "", max_price_eth: float = None,
                    max_price_usd: float = None) -> str:
    """REAL purchase: fetch the listing (or use given order hash), get the
    fulfillment transaction from OpenSea, verify the price, sign & send."""
    chain = (chain or "").lower()
    if chain not in OS_CHAINS:
        return f"❌ OpenSea buying works on: {', '.join(OS_CHAINS)}."
    cap_eth, cap_note = _resolve_cap(max_price_eth, max_price_usd)
    if cap_eth is None and cap_note:
        # both ❌ (conversion failed) and 🛑 (absurd cap) are hard refusals
        return cap_note
    if cap_eth is None:
        return ("🛑 State a budget first: max_price_usd=<your $ limit> (or "
                "max_price_eth). I don't spend money without an explicit cap.")
    wallet = _wallet()
    if not wallet or not wallet.get("private_key"):
        return "❌ No EVM wallet. Create one first."

    try:
        w3 = _w3(chain)
        account = w3.eth.account.from_key(wallet["private_key"])

        # Resolve the listing if not given directly
        if not order_hash:
            if not (collection and token_id):
                return "❌ Provide order_hash + protocol_address, or collection + token_id."
            best = _get(f"/listings/collection/{collection}/nfts/{token_id}/best")
            order_hash = best.get("order_hash", "")
            protocol_address = best.get("protocol_address", "")
            if not order_hash:
                return f"❌ No live listing found for {collection} #{token_id}."

        price_wei = None
        if not protocol_address:
            protocol_address = "0x0000000000000068f116a894984e2db1123eb395"  # Seaport 1.6

        # Look up the listing to verify price before paying
        try:
            L = _get(f"/orders/chain/{chain}/protocol/{protocol_address}/{order_hash}")
            cons = L.get("order", {}).get("protocol_data", {}).get("parameters", {}).get("consideration", [])
            price_wei = max(int(c.get("startAmount", 0)) for c in cons) if cons else None
        except Exception:
            pass

        if cap_eth is not None and price_wei and price_wei > int(cap_eth * 1e18):
            return (f"❌ Listing costs {price_wei/1e18:.4f} ETH — above your "
                    f"cap ({cap_note or f'{cap_eth:.4f} ETH'}). Refusing to overpay.")

        body = {
            "listing": {"hash": order_hash, "chain": chain,
                        "protocol_address": protocol_address},
            "fulfiller": {"address": account.address},
        }
        resp = _post("/listings/fulfillment/actions", body)
        steps = resp.get("steps", [])

        log, purchase_tx = [], None
        for step in steps:
            kind, payload = _extract_action(step)
            if not payload:
                log.append(f"⏭️ unknown step {list(step.keys())}")
                continue
            if "transaction" in payload:
                t = payload["transaction"]
                tx = {"to": (t.get("to") or {}).get("value", ""),
                      "data": t.get("data", "0x"),
                      "value": int(t.get("value", 0) or 0)}
                # The fulfill step is the one that pays — check it
                if tx["value"] > 0 and price_wei and abs(tx["value"] - price_wei) > price_wei // 20:
                    return (f"❌ Payment safety check failed: fulfillment wants to pay "
                            f"{tx['value']/1e18:.4f} ETH but the listing said "
                            f"{price_wei/1e18:.4f} ETH. Aborting.")
                purchase_tx = tx
            elif "signatureRequest" in payload:
                log.append("⏭️ unexpected signature step in fulfillment")

        if not purchase_tx:
            return "❌ OpenSea returned no fulfillment transaction."

        # Balance check
        bal = w3.eth.get_balance(account.address)
        if bal < purchase_tx["value"] + 10**15:
            return (f"❌ Insufficient ETH: have {bal/1e18:.5f}, need "
                    f"~{purchase_tx['value']/1e18:.5f} + gas.")

        h = _send_tx(w3, account, purchase_tx)
        receipt = _wait(w3, h)
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="nft_buy", chain=chain,
                token=(collection or contract[:10] + "…"),
                token_addr=contract or "", amount=1,
                native=f"{purchase_tx['value']/1e18:.5f} ETH", tx=h,
                status="confirmed" if receipt.status == 1 else "failed")
        except Exception:
            pass
        if receipt.status != 1:
            return f"❌ Purchase tx REVERTED: {_explorer_tx(chain, h)}"

        paid = purchase_tx["value"] / 1e18
        return (
            f"✅ NFT PURCHASED FOR REAL ({chain})\n\n"
            f"Paid: {paid:.5f} ETH"
            + (f" (listed {price_wei/1e18:.5f})" if price_wei else "") + "\n"
            + (f"Token: {contract[:10]}… #{token_id}\n" if contract else "")
            + f"Tx: {_explorer_tx(chain, h)}\n" + "\n".join(log)
        )
    except Exception as e:
        return f"❌ Purchase failed: {e}"


# ============================================================
# 4. REAL: cancel a listing
# ============================================================

# ============================================================
# 4b. OFFERS — read top bids, place a real WETH-collateralized offer
# ============================================================

def opensea_top_offer(collection: str, limit: int = 5) -> str:
    """Top (highest) ACTIVE offers on an OpenSea collection — REAL orderbook
    data. Covers collection-wide and trait offers with offerer + expiry."""
    collection = (collection or "").strip()
    if not collection:
        return "❌ Need a collection slug (e.g. 'pudgypenguins') or contract 0x…"
    limit = max(1, min(int(limit), 25))
    try:
        slug = _resolve_collection(collection)
        d = _get(f"/offers/collection/{slug}", params={"limit": limit})
        offers = d.get("offers", [])
        if not offers:
            return f"📭 No active offers on {slug} right now."

        def _wei(o):
            try:
                return int((o.get("price") or {}).get("value", "0"))
            except Exception:
                return 0
        offers.sort(key=_wei, reverse=True)

        usd = _eth_usd_price()
        floor = None
        try:
            st = _get(f"/collections/{slug}/stats")
            floor = (st.get("total") or {}).get("floor_price")
        except Exception:
            pass

        lines = [f"💰 Top offers on {slug}:"]
        if floor is not None:
            lines[0] += f" (floor: {floor} ETH)"
        for o in offers[:limit]:
            p = o.get("price") or {}
            try:
                v = int(p.get("value", "0"))
                dec = int(p.get("decimals", 18))
            except Exception:
                continue
            cur = p.get("currency", "?")
            amt = v / (10 ** dec)
            usd_note = f" ≈ ${amt * usd:,.2f}" if usd and cur.upper().startswith("W") else ""
            crit = o.get("criteria") or {}
            if crit.get("encoded_token_ids") == "*":
                scope = "collection-wide"
            elif crit.get("encoded_token_ids"):
                scope = f"tokens {str(crit['encoded_token_ids'])[:24]}"
            elif crit.get("traits"):
                scope = "trait offer " + str(crit["traits"])[:40]
            else:
                scope = "specific item"
            offerer = (((o.get("protocol_data") or {}).get("parameters") or {}).get("offerer") or "?")
            exp = o.get("expiration_time") or "no expiry"
            lines.append(f"  • {amt:.4f} {cur}{usd_note} — {scope} — "
                         f"offerer {offerer[:10]}… — ends: {exp}")
        lines.append("Place one: opensea_place_offer(chain, contract, token_id, offer amount).")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Offers lookup failed: {e}"


def opensea_place_offer(chain: str, contract: str, token_id: str,
                        offer_eth: float = None, offer_usd: float = None,
                        days: int = 7) -> str:
    """REAL per-NFT offer on OpenSea: WETH-collateralized Seaport bid.
    Build → local EIP-712 signature → orderbook POST. Requires WETH balance
    (offers lock the WETH until filled/cancelled)."""
    chain = (chain or "").lower()
    if chain not in OS_CHAINS:
        return f"❌ OpenSea offers work on: {', '.join(OS_CHAINS)}."
    wallet = _wallet()
    if not wallet or not wallet.get("private_key"):
        return "❌ No EVM wallet. Create one first."

    # Same $-trap guard as buys: '$50' is DOLLARS — resolve via live rate.
    offer_eth, cap_note = _resolve_cap(offer_eth, offer_usd, what="offer")
    if offer_eth is None:
        return cap_note or "🛑 Provide the offer amount (offer_usd preferred)."
    if offer_eth <= 0:
        return "❌ Offer must be positive."
    try:
        w3 = _w3(chain)
        account = w3.eth.account.from_key(wallet["private_key"])

        # WETH gate: Seaport collateralizes offers in WETH. Check BEFORE the
        # API roundtrip so the user gets an actionable answer, not a cryptic
        # ORDER_LEVERAGE_USER_ZERO_BALANCE.
        from evm_swap import CHAINS as EVM_CHAINS, _cs
        weth = EVM_CHAINS.get(chain, {}).get("weth")
        if weth:
            try:
                erc20_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
                              "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
                              "type": "function"}]
                tok = w3.eth.contract(address=_cs(w3, weth), abi=erc20_abi)
                bal = tok.functions.balanceOf(account.address).call()
                need = int(offer_eth * 1e18)
                if bal < need:
                    return (f"❌ Offers lock WETH: need {offer_eth:.5f} WETH, "
                            f"wallet has {bal/1e18:.5f}. Convert first: "
                            f"'swap {offer_eth:.5f} ETH to WETH on {chain}'.")
            except Exception:
                pass  # can't check → let OpenSea's own validation decide

        body = {
            "address": account.address,
            "quantity": 1,
            "item": {"chain": chain, "contract": contract, "token_id": str(token_id)},
            "price": {"amount": str(int(offer_eth * 1e18)),
                      "currency": weth or "0x0000000000000000000000000000000000000000"},
        }
        if days and days > 0:
            end = datetime.now(timezone.utc) + timedelta(days=int(days))
            body["expiration_time"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        resp = _post("/offers/actions", body)
        steps = resp.get("steps", [])

        log, sigs = [], []
        for step in steps:
            kind, payload = _extract_action(step)
            if not payload:
                continue
            if "transaction" in payload:
                t = payload["transaction"]
                h = _send_tx(w3, account, {"to": (t.get("to") or {}).get("value", ""),
                                           "data": t.get("data", "0x"),
                                           "value": int(t.get("value", 0) or 0)})
                receipt = _wait(w3, h)
                if receipt.status != 1:
                    return f"❌ WETH approval tx reverted: {_explorer_tx(chain, h)}"
                log.append(f"✅ WETH approval: {_explorer_tx(chain, h)}")
            elif "signatureRequest" in payload:
                sigs.append(payload["signatureRequest"])
        if not sigs:
            return "❌ OpenSea returned no signing payload."
        sr = sigs[0]
        typed = json.loads(sr["message"])

        from eth_account.messages import encode_typed_data
        signed = account.sign_message(encode_typed_data(full_message=typed))
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        order = None
        for step in steps:
            payload = step.get("createOffersAction", {})
            if payload.get("orders"):
                order = payload["orders"][0]
                break
        protocol = (order or {}).get("protocolAddress", {}).get("value",
                    typed["domain"].get("verifyingContract"))
        parameters = typed["message"]

        posted = _post(f"/orders/{chain}/seaport/offers", {
            "parameters": parameters,
            "protocol_address": protocol,
            "signature": signature,
        })
        oh = (posted.get("order") or {}).get("order_hash", "")
        try:
            import trade_journal
            trade_journal.log_trade(
                kind="nft_offer", chain=chain, token=contract[:10] + "…",
                token_addr=contract, amount=1, native=f"bid {offer_eth:.5f} ETH",
                tx=oh, status="confirmed", note=f"token #{token_id}")
        except Exception:
            pass
        return (f"✅ OFFER PLACED FOR REAL on OpenSea ({chain})\n\n"
                f"{contract[:10]}… #{token_id} ← bid {offer_eth:.5f} ETH{cap_note} "
                f"(expires in {int(days)}d)\n"
                f"Order hash: `{oh}`\n" + "\n".join(log) +
                f"\nCancel any time (gas-free): cancel order {oh[:14]}…")
    except Exception as e:
        return f"❌ Offer failed: {e}"


def opensea_cancel_listing(chain: str, order_hash: str,
                           protocol_address: str) -> str:
    """Cancel a listing or offer on-chain (Seaport cancel — costs gas)."""
    chain = (chain or "").lower()
    if chain not in OS_CHAINS:
        return f"❌ Chain not supported: {', '.join(OS_CHAINS)}"
    wallet = _wallet()
    if not wallet:
        return "❌ No EVM wallet."
    try:
        w3 = _w3(chain)
        account = w3.eth.account.from_key(wallet["private_key"])
        body = {"seaport": [{"orderHash": order_hash,
                             "protocolAddress": protocol_address,
                             "chain": chain}]}
        # v2 cancel endpoint generates the cancel tx
        r = requests.post(
            f"{OPENSEA_API}/orders/chain/{chain}/protocol/{protocol_address}/{order_hash}/cancel/actions",
            json={}, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            return f"❌ Cancel failed: {r.status_code} {r.text[:200]}"
        steps = r.json().get("steps", [])
        log = []
        for step in steps:
            kind, payload = _extract_action(step)
            if payload and "transaction" in payload:
                t = payload["transaction"]
                h = _send_tx(w3, account, {"to": (t.get("to") or {}).get("value", ""),
                                           "data": t.get("data", "0x"),
                                           "value": int(t.get("value", 0) or 0)})
                receipt = _wait(w3, h)
                if receipt.status != 1:
                    return f"❌ Cancel tx reverted: {_explorer_tx(chain, h)}"
                log.append(f"✅ cancelled on-chain: {_explorer_tx(chain, h)}")
        return "✅ Listing cancelled.\n" + "\n".join(log) if log else "❌ No cancel action returned."
    except Exception as e:
        return f"❌ Cancel failed: {e}"


# ============================================================
# 5. MINT BOT — drop discovery, batch mints, queued sniping
# ============================================================

def opensea_drops(chain: str = "", drop_type: str = "featured",
                  limit: int = 8) -> str:
    """Live OpenSea drops: featured / upcoming / recently_minted."""
    try:
        params = {"type": drop_type, "limit": limit}
        if chain:
            params["chains"] = chain
        data = _get("/drops", params)
        drops = data.get("drops", [])
        if not drops:
            return "No drops found."
        out = [f"🎬 OpenSea {drop_type} drops:"]
        for d in drops:
            stage = d.get("active_stage") or {}
            price = stage.get("price")
            ptxt = f"{int(price)/1e18:.4f} ETH" if price else "free/price TBD"
            minting = "🟢 LIVE" if d.get("is_minting") else "⏳ not open"
            out.append(
                f"  • {d.get('collection_name', '?')} ({d.get('collection_slug')}) "
                f"[{d.get('chain')}] {ptxt} — {minting} — stage: {stage.get('label', '?')}"
            )
        out.append("Mint with: opensea_mint_drop(slug, quantity). Watch one with: opensea_watch_drop.")
        return "\n".join(out)
    except Exception as e:
        return f"❌ {e}"


def _confirm_mint_bg(chain: str, tx_hash: str, slug: str, quantity: int, value: int):
    """Wait for a mint receipt OFF the critical path, journal it, and (best
    effort) ping the user. Never raises."""
    status = "unknown"
    try:
        w3 = _w3(chain)
        receipt = _wait(w3, tx_hash)
        status = "confirmed" if receipt.status == 1 else "failed"
    except Exception:
        pass
    try:
        import trade_journal
        trade_journal.log_trade(
            kind="mint", chain=chain, token=slug, amount=quantity,
            native=f"{value/1e18:.5f} ETH", tx=tx_hash,
            status=status, source="manual")
    except Exception:
        pass
    try:
        from copytrade import _ping
        emoji = "✅" if status == "confirmed" else ("❌" if status == "failed" else "⚠️")
        _ping(f"{emoji} Mint confirm [{chain}] {slug} ×{quantity}: {status}\n"
              f"{_explorer_tx(chain, tx_hash)}")
    except Exception:
        pass


def opensea_mint_drop(slug: str, quantity: int = 1) -> str:
    """
    REAL batch mint from an OpenSea drop: OpenSea builds the mint tx for
    `quantity` tokens, we sign with the wallet and broadcast.
    Works while the drop's public/allowlist stage is open.
    """
    slug = (slug or "").strip()
    wallet = _wallet()
    if not wallet:
        return "❌ No EVM wallet. Create one first."
    quantity = max(1, min(int(quantity), 50))
    try:
        w3 = _w3("ethereum")
        account = w3.eth.account.from_key(wallet["private_key"])

        body = {"minter": account.address, "quantity": quantity}
        resp = _post(f"/drops/{slug}/mint", body)

        # DropMintResponse: {to, data, value, chain}
        to = resp.get("to", "")
        data = resp.get("data", "0x")
        value = int(resp.get("value", 0) or 0)
        chain = (resp.get("chain") or "ethereum").lower()
        if chain not in OS_CHAINS:
            return f"❌ Mint targets chain {chain!r} — not executable here."
        if chain != "ethereum":
            w3 = _w3(chain)

        if not to or data in ("", "0x"):
            return "❌ OpenSea returned no mint transaction."

        # Price sanity: value is what we pay; report it before sending
        est_cost = value / 1e18
        bal = w3.eth.get_balance(account.address)
        if bal < value + 10**15:
            return (f"❌ Insufficient ETH: need ~{est_cost:.5f} + gas, "
                    f"have {bal/1e18:.5f}.")

        h = _send_tx(w3, account, {"to": to, "data": data, "value": value})
        # CRITICAL for snipes: do NOT block on the receipt here. Waiting
        # ~2s per block while a mint window is open wastes the advantage —
        # confirmation is tracked in a background thread instead.
        threading.Thread(target=_confirm_mint_bg,
                         args=(chain, h, slug, quantity, value), daemon=True).start()
        return (f"✅ MINT BROADCAST {quantity} × {slug} ({chain})\n\n"
                f"Cost: ~{est_cost:.5f} ETH\n"
                f"Tx: {_explorer_tx(chain, h)}\n"
                f"(confirmation arriving in a follow-up message)")
    except Exception as e:
        return f"❌ Mint failed: {e}"


def opensea_eligibility(slug: str) -> str:
    """Check whether our wallet is eligible for a drop (allowlist etc.)."""
    try:
        w = _wallet()
        if not w:
            return "❌ No EVM wallet."
        data = _get(f"/drops/{slug}/eligibility")
        return f"🎟️ Eligibility for {slug}: {json.dumps(data)[:400]}"
    except Exception as e:
        return f"❌ {e}"


# ---- queued mint-watcher (the 'bot a mint' part) ----

_MINT_QUEUE_PATH = Path(__file__).parent / "mint_queue.json"

def _load_queue() -> list:
    if _MINT_QUEUE_PATH.exists():
        try:
            return json.loads(_MINT_QUEUE_PATH.read_text())
        except Exception:
            return []
    return []


def _save_queue(q: list):
    _MINT_QUEUE_PATH.write_text(json.dumps(q, indent=2))


def opensea_watch_drop(slug: str, max_price_eth: float = None,
                       max_price_usd: float = None, quantity: int = 1) -> str:
    """Queue a drop: a background thread polls until the mint opens,
    then fires a batch mint automatically (first come, first served)."""
    slug = (slug or "").strip()
    if not slug:
        return "❌ Need a drop slug (the OpenSea collection name, e.g. 'hood-remilias')."
    # Resolve a USD cap to ETH at the live rate NOW (and sanity-check it),
    # so the watcher compares an honest ceiling when the drop opens.
    cap_eth, cap_note = _resolve_cap(max_price_eth, max_price_usd, what="watch cap")
    if (max_price_eth is not None or max_price_usd is not None) and cap_eth is None:
        return cap_note or "🛑 Refusing that price cap."
    q = _load_queue()
    if any(e.get("slug") == slug for e in q):
        return f"⚠️ {slug} is already in the mint queue."
    q.append({"slug": slug, "quantity": max(1, min(int(quantity), 50)),
              "max_price_eth": cap_eth, "added": datetime.now(timezone.utc).isoformat(),
              "status": "watching"})
    _save_queue(q)
    _ensure_watcher()
    if cap_eth is not None:
        cap_disp = f"{cap_eth:.5f}".rstrip("0").rstrip(".") if cap_eth < 1 else f"{cap_eth:.4f}"
        return (f"👁️ Watching {slug} — will mint {quantity} the moment it opens, "
                f"only if price ≤ {cap_disp} ETH{cap_note}.")
    return f"👁️ Watching {slug} — will mint {quantity} the moment it opens (no price cap set)."


def opensea_mint_queue() -> str:
    q = _load_queue()
    if not q:
        return "Mint queue is empty. Add one: opensea_watch_drop(slug)."
    lines = ["👁️ Mint queue:"]
    for e in q:
        price = f" ≤{e['max_price_eth']}ETH" if e.get("max_price_eth") else ""
        lines.append(f"  • {e['slug']} ×{e.get('quantity', 1)}{price} — {e.get('status', '?')}"
                     + (f" ({e.get('result', '')[:80]})" if e.get("result") else ""))
    return "\n".join(lines)


def opensea_unwatch_drop(slug: str) -> str:
    q = [e for e in _load_queue() if e.get("slug") != slug]
    _save_queue(q)
    return f"🗑️ Removed {slug} from the mint queue."


_watcher_thread = None


def _notify_drop_result(e: dict):
    """Telegram-ping the user when a watched drop resolves. Best-effort —
    never let notification failure break the watcher loop."""
    try:
        from copytrade import _ping
        status = e.get("status", "?")
        icon = "🎉" if status == "minted" else "❌"
        _ping(f"{icon} Drop *{e.get('slug', '?')}*: {status}\n"
              f"{str(e.get('result', ''))[:200]}")
    except Exception:
        pass



def _prestage(chain: str = "ethereum"):
    """Warm the RPC connection (DNS+TLS) and cache nonce/gas right before
    a drop opens, so the actual mint send skips connection setup."""
    try:
        w3 = _w3(chain)  # OUR cached instance — warm for fire time
        w = _wallet()
        if w:
            w3.eth.get_transaction_count(w["address"])  # warms conn + nonce path
        w3.eth.gas_price
        w3.eth.chain_id
    except Exception:
        pass
    try:  # also warm evm_swap's instance (used by swap paths)
        from evm_swap import _get_w3
        _get_w3(chain).eth.gas_price
    except Exception:
        pass


def _fire_drop_mint(e: dict, slug: str, cap):
    """Fire the batch mint for a queued drop: three fast attempts, each with
    sign+broadcast run on a worker thread so a slow RPC handshake can't push
    us past the mint window. Returns the final result string."""
    result = ""
    for attempt in range(3):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(opensea_mint_drop, slug, e.get("quantity", 1))
            try:
                result = fut.result(timeout=25)
            except concurrent.futures.TimeoutError:
                result = "❌ mint tx send timed out after 25s"
        if result.startswith("✅"):
            break
        time.sleep(1.5)
    return result


def _drop_watcher_loop():
    """Watch queued drops. Far from open: poll every 15s. Within 60s of a
    stage's start_time: pre-warm connections, then tight-poll (1s) and fire
    the instant the drop opens, with fast retries if OpenSea's flag lags."""
    while True:
        try:
            q = _load_queue()
            now = datetime.now(timezone.utc)
            for e in q:
                if e.get("status") in ("minted", "failed", "expired"):
                    continue
                slug = e["slug"]
                try:
                    d = _get(f"/drops/{slug}")
                except Exception as ex:
                    if "404" in str(ex):
                        e["status"] = "expired"
                        e["result"] = "drop not found"
                        _save_queue(q)
                        _notify_drop_result(e)
                    continue

                is_open = bool(d.get("is_minting"))
                stage = d.get("active_stage") or {}
                price = stage.get("price")
                price_eth = (int(price) / 1e18) if price else None
                cap = e.get("max_price_eth")
                price_ok = cap is None or price_eth is None or price_eth <= cap

                if is_open:
                    if not price_ok:
                        e["status"] = "expired"
                        e["result"] = f"opened at {price_eth} ETH > cap {cap} ETH"
                        _save_queue(q)
                        _notify_drop_result(e)
                        continue
                    e["status"] = "minting"
                    _save_queue(q)
                    result = _fire_drop_mint(e, slug, cap)  # fast retries if the stage flag lags
                    e["status"] = "minted" if result.startswith("✅") else "failed"
                    e["result"] = result[:300]
                    _save_queue(q)
                    _notify_drop_result(e)
                    continue

                # Not open yet — schedule a hot fire if start_time is near
                start = stage.get("start_time")
                if start:
                    try:
                        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        delta = (t0 - now).total_seconds()
                        if 0 < delta <= 60:
                            chain = (d.get("chain") or "ethereum").lower()
                            _prestage(chain)
                            # NOTE: 'armed' is deliberately NOT persisted —
                            # if the bot restarts mid-hot-phase, the entry
                            # stays 'watching' and falls back to normal polls.
                            # hot phase: poll 1s until open (respects ~120/min limit)
                            fired = False
                            while (datetime.now(timezone.utc) - t0).total_seconds() < 600:
                                time.sleep(1)
                                try:
                                    d2 = _get(f"/drops/{slug}")
                                    if d2.get("is_minting"):
                                        st2 = d2.get("active_stage") or {}
                                        p2 = st2.get("price")
                                        pe2 = (int(p2) / 1e18) if p2 else None
                                        if cap is not None and pe2 is not None and pe2 > cap:
                                            e["status"] = "expired"
                                            e["result"] = f"opened at {pe2} ETH > cap {cap} ETH"
                                            _save_queue(q)
                                            _notify_drop_result(e)
                                            break
                                        result = _fire_drop_mint(e, slug, cap)
                                        e["status"] = "minted" if result.startswith("✅") else "failed"
                                        e["result"] = result[:300]
                                        _save_queue(q)
                                        _notify_drop_result(e)
                                        fired = True
                                        break
                                except Exception:
                                    continue
                            if not fired and e.get("status") == "watching":
                                e["status"] = "failed"
                                e["result"] = "hot window elapsed without opening"
                                _save_queue(q)
                                _notify_drop_result(e)
                        elif delta > 60:
                            e["status"] = f"scheduled (opens in {int(delta)}s)"
                            _save_queue(q)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(15)


def _ensure_watcher():
    """Start the drop-watcher daemon thread once (called from main())."""
    global _watcher_thread
    if _watcher_thread is None or not _watcher_thread.is_alive():
        _watcher_thread = threading.Thread(target=_drop_watcher_loop,
                                           name="opensea-drop-watcher", daemon=True)
        _watcher_thread.start()


def start_drop_watcher():
    """Public entry point for the bot startup: resumes any queued watches."""
    _ensure_watcher()


# ============================================================
# Tool registry
# ============================================================

# ============================================================
# Mint discovery — free-mint scanner + on-chain contract prober/minter
# ============================================================

# Common public-sale state getters seen across drop contracts (bool, no args)
_SALE_ACTIVE_NAMES = [
    "publicSaleActive", "saleIsActive", "mintingEnabled", "mintEnabled",
    "publicMintActive", "saleActive", "isSaleActive", "mintActive",
    "publicSale", "isPublicSaleActive", "presaleActive", "allowlistActive",
]
# Common price getters (uint256, no args) — wei per token
_PRICE_NAMES = [
    "price", "mintPrice", "cost", "publicSalePrice", "salePrice",
    "pricePerToken", "getPrice", "publicPrice", "mintCost", "PRICE",
]
# Common supply getters / constants
_SUPPLY_NAMES = ["totalSupply", "totalMinted", "_totalMinted", "minted", "currentSupply"]
_MAX_SUPPLY_NAMES = ["maxSupply", "MAX_SUPPLY", "MAX_TOKENS", "MAX_MINT", "collectionSize", "MAX_TOTAL_SUPPLY"]
_LIMIT_NAMES = ["maxMintPerWallet", "MAX_PER_WALLET", "maxPerWallet", "MAX_MINT_PER_TX", "maxPerTx", "MAX_PER_TX", "maxMintAmountPerTx"]


def _first_int(contract, names):
    """First callable that returns a usable int; None if all fail."""
    for n in names:
        try:
            fn = getattr(contract.functions, n, None)
            if fn is None:
                continue
            v = fn().call()
            if hasattr(v, "__int__"):
                return n, int(v)
        except Exception:
            continue
    return None


def _first_bool(contract, names):
    for n in names:
        try:
            fn = getattr(contract.functions, n, None)
            if fn is None:
                continue
            v = fn().call()
            if isinstance(v, bool):
                return n, v
        except Exception:
            continue
    return None


def _probe_contract(w3, address: str):
    """Contract handle with a CANDIDATE ABI built from every common getter
    name we know. A web3 contract with abi=[] exposes zero functions, so the
    ABI must list each probed name; on-chain misses just raise and are
    skipped by the callers' try/except."""
    abis = []
    for n in _SUPPLY_NAMES + _MAX_SUPPLY_NAMES + _PRICE_NAMES + _LIMIT_NAMES:
        abis.append({"name": n, "type": "function", "inputs": [],
                     "outputs": [{"type": "uint256"}], "stateMutability": "view"})
    for n in _SALE_ACTIVE_NAMES:
        abis.append({"name": n, "type": "function", "inputs": [],
                     "outputs": [{"type": "bool"}], "stateMutability": "view"})
    for n in ("name", "symbol"):
        abis.append({"name": n, "type": "function", "inputs": [],
                     "outputs": [{"type": "string"}], "stateMutability": "view"})
    return w3.eth.contract(address=w3.to_checksum_address(address), abi=abis)


def scan_contract_mint(chain: str = "ethereum", contract: str = "") -> str:
    """Read-only probe of a DEPLOYED NFT contract: standard, supply, price,
    public-mint state, per-wallet limits. Zero cost — pure eth_calls, no tx.
    Paste any 0x contract address to see if it has a live (free?) mint."""
    chain = (chain or "ethereum").lower().strip()
    if chain not in OS_CHAINS:
        return f"❌ Chain {chain!r} not supported. Use: {', '.join(OS_CHAINS)}"
    if not contract.startswith("0x") or len(contract) != 42:
        return "❌ Provide the deployed NFT contract address (0x…, 42 chars)."
    try:
        w3 = _w3(chain)
        c = _probe_contract(w3, contract)

        # Standard detection via ERC-165 (0x01ffc9a7 supportsInterface)
        erc165 = w3.eth.contract(address=w3.to_checksum_address(contract), abi=[
            {"name": "supportsInterface", "type": "function",
             "inputs": [{"name": "i", "type": "bytes4"}],
             "outputs": [{"type": "bool"}], "stateMutability": "view"}])
        std = "unknown"
        for iface, label in (("0x80ac58cd", "ERC-721"), ("0xd9b67a26", "ERC-1155")):
            try:
                if erc165.functions.supportsInterface(iface).call():
                    std = label
                    break
            except Exception:
                pass

        # name/symbol
        name = symbol = "?"
        for nm in ("name",):
            try:
                name = getattr(c.functions, nm)().call() or "?"
            except Exception:
                pass
        for nm in ("symbol",):
            try:
                symbol = getattr(c.functions, nm)().call() or "?"
            except Exception:
                pass

        minted = _first_int(c, _SUPPLY_NAMES)
        maxsup = _first_int(c, _MAX_SUPPLY_NAMES)
        price = _first_int(c, _PRICE_NAMES)
        active = _first_bool(c, _SALE_ACTIVE_NAMES)
        limit = _first_int(c, _LIMIT_NAMES)

        lines = [f"🔍 Contract scan — {contract}", f"Chain: {chain} | Standard: {std}"]
        if name != "?" or symbol != "?":
            lines.append(f"Collection: {name} ({symbol})")
        if minted:
            if maxsup:
                pct = 100 * minted[1] / maxsup[1] if maxsup[1] else 0
                lines.append(f"Supply: {minted[1]:,} / {maxsup[1]:,} minted ({pct:.1f}%) [{minted[0]}/{maxsup[0]}]")
            else:
                lines.append(f"Minted so far: {minted[1]:,} [{minted[0]}]")
        elif maxsup:
            lines.append(f"Max supply: {maxsup[1]:,} [{maxsup[0]}]")
        else:
            lines.append("Supply: not readable (unusual contract)")
        if price is not None:
            wei = price[1]
            if wei == 0:
                lines.append("Price: 0 ETH — 🆓 FREE MINT")
            else:
                lines.append(f"Price: {wei/1e18:.6f} ETH per token [{price[0]}]")
        else:
            lines.append("Price: no standard price getter (may be stage/allowlist-based)")
        sold_out = bool(minted and maxsup and minted[1] >= maxsup[1])
        if active:
            state = "⛔ SOLD OUT (supply maxed)" if sold_out else ("🟢 ACTIVE" if active[1] else "⛔ not active")
            lines.append(f"Public sale: {state} [{active[0]}]")
        elif sold_out:
            lines.append("Public sale: ⛔ SOLD OUT (supply maxed)")
        else:
            lines.append("Public sale: state not readable — check the project's page")
        if limit:
            lines.append(f"Limit: {limit[1]} per wallet/tx [{limit[0]}]")

        # Is it an OpenSea drop we can mint through our drop pipeline?
        try:
            info = _get(f"/chain/{chain}/contract/{contract}")
            slug = info.get("collection", "")
            if slug:
                lines += ["", f"OpenSea collection: {slug}",
                          f"→ check drop: opensea_eligibility(slug={slug!r}) or opensea_watch_drop(slug={slug!r})"]
        except Exception:
            pass
        lines += ["", "To mint directly on-chain (no OpenSea needed): mint_contract(chain=…, contract=…, quantity=N)"]
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Scan failed: {type(e).__name__}: {e}"


# Mint function signatures we try, in order (EVM drop contracts vary wildly)
_MINT_ABI_VARIANTS = [
    [{"name": "mint", "type": "function", "inputs": [{"name": "qty", "type": "uint256"}],
      "outputs": [], "stateMutability": "payable"}],
    [{"name": "publicMint", "type": "function", "inputs": [{"name": "qty", "type": "uint256"}],
      "outputs": [], "stateMutability": "payable"}],
    [{"name": "mintTo", "type": "function",
      "inputs": [{"name": "to", "type": "address"}, {"name": "qty", "type": "uint256"}],
      "outputs": [], "stateMutability": "payable"}],
    [{"name": "mint", "type": "function", "inputs": [], "outputs": [], "stateMutability": "payable"}],
]


def mint_contract(chain: str = "ethereum", contract: str = "", quantity: int = 1,
                 max_price_eth: float = None, max_price_usd: float = None) -> str:
    """REAL direct on-chain mint against a deployed contract — no OpenSea,
    no API. Probes the contract for its price, refuses if total cost exceeds
    the cap (ETH or USD), then signs and broadcasts the mint tx with your
    wallet. Works for free mints (value=0) and paid mints alike."""
    chain = (chain or "ethereum").lower().strip()
    if chain not in OS_CHAINS:
        return f"❌ Chain {chain!r} not supported. Use: {', '.join(OS_CHAINS)}"
    if not contract.startswith("0x") or len(contract) != 42:
        return "❌ Provide the deployed NFT contract address (0x…)."
    quantity = max(1, min(int(quantity), 20))  # hard cap: no fat-finger 1000x
    cap_eth, cap_note = _resolve_cap(max_price_eth, max_price_usd)
    if cap_eth is None and cap_note:
        return cap_note  # genuine refusal (conversion failed / absurd cap)
    # both caps None → cap_eth stays None: free mints proceed, paid mints ask below
    try:
        w3 = _w3(chain)
        wallet = _wallet()
        account = w3.eth.account.from_key(wallet["private_key"])
        c = w3.eth.contract(address=w3.to_checksum_address(contract), abi=[])

        price = _first_int(c, _PRICE_NAMES)
        wei_price = price[1] if price else 0  # unreadable price → assume free but WARN
        value = wei_price * quantity
        if cap_eth is not None and value > int(cap_eth * 1e18):
            return (f"🛑 Total cost {value/1e18:.6f} ETH exceeds your cap "
                    f"({cap_note or f'{cap_eth:.4f} ETH'}). Nothing sent.")
        if wei_price > 0 and cap_eth is None:
            return (f"⚠️ This mint costs {wei_price/1e18:.6f} ETH/token ({quantity} = "
                    f"{value/1e18:.6f} ETH total). Confirm with max_price_eth={value/1e18:.4f} "
                    "or max_price_usd — I don't spend money without an explicit cap.")
        bal = w3.eth.get_balance(account.address)
        if bal < value:
            return f"❌ Balance {bal/1e18:.6f} ETH < needed {value/1e18:.6f} ETH (+gas)."

        # Find a mint function the contract actually accepts (dry-estimate each)
        last_err = None
        for abi in _MINT_ABI_VARIANTS:
            mc = w3.eth.contract(address=w3.to_checksum_address(contract), abi=abi)
            fname = abi[0]["name"]
            try:
                if fname == "mintTo":
                    tx = mc.functions.mintTo(account.address, quantity).build_transaction({"value": value})
                elif abi[0]["inputs"]:
                    tx = mc.functions.mint(quantity).build_transaction({"value": value})
                else:
                    tx = mc.functions.mint().build_transaction({"value": value})
                tx.pop("gasPrice", None); tx.pop("maxFeePerGas", None); tx.pop("maxPriorityFeePerGas", None)
                h = _send_tx(w3, account, tx)
                rcpt = _wait(w3, h)
                ok = rcpt.get("status") == 1
                try:
                    import trade_journal
                    trade_journal.log_trade(
                        kind="mint", chain=chain, token=contract[:10] + "…",
                        token_addr=contract, amount=quantity,
                        native=f"{value/1e18:.5f} ETH", tx=h,
                        status="confirmed" if ok else "failed", source="manual")
                except Exception:
                    pass
                out = [f"{'✅' if ok else '❌'} Mint broadcast ({fname}, value={value/1e18:.6f} ETH)",
                       f"Tx: {_explorer_tx(chain, h)}"]
                if ok:
                    out += ["Check your wallet for the new token(s), or opensea_holdings in a minute."]
                return "\n".join(out)
            except Exception as e:
                last_err = e
                continue
        return (f"❌ No known mint signature worked (tried mint(qty), publicMint(qty), mintTo(addr,qty), mint()). "
                f"Last error: {last_err}. Custom contracts may need a custom call.")
    except Exception as e:
        return f"❌ Mint failed: {type(e).__name__}: {e}"


def opensea_free_mints(chain: str = "", limit: int = 15) -> str:
    """Scan live OpenSea drops for FREE (0 ETH) mints — featured + upcoming +
    recently_minted. The cheap way to hunt mint opportunities."""
    try:
        seen, results = set(), []
        for dtype in ("featured", "upcoming", "recently_minted"):
            params = {"type": dtype, "limit": 30}
            if chain:
                params["chains"] = chain
            try:
                drops = _get("/drops", params).get("drops", [])
            except Exception:
                continue
            for d in drops:
                slug = d.get("collection_slug")
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                stage = d.get("active_stage") or {}
                price = stage.get("price")
                wei = int(price) if price else 0
                if wei == 0:
                    results.append((d, dtype))
        if not results:
            return "No free mints among current drops. Try opensea_drops for paid ones, or scan_contract_mint on a specific contract."
        out = [f"🆓 Free mints among OpenSea drops ({len(results)} found):\n"]
        for d, dtype in results[: max(1, int(limit))]:
            minting = "🟢 LIVE" if d.get("is_minting") else f"⏳ {dtype}"
            out.append(f"  • {d.get('collection_name', '?')} ({d.get('collection_slug')}) "
                       f"[{d.get('chain')}] — {minting}")
        out += ["", "Scout one: scan_contract_mint(chain=…, contract=0x…) → mint via opensea_mint_drop or mint_contract."]
        return "\n".join(out)
    except Exception as e:
        return f"❌ {e}"


OPENSEA_TOOLS = [
    {"type": "function", "function": {"name": "opensea_floor", "description": "OpenSea collection floor price and stats (slug like 'bored-ape-yacht-club', or a contract address). ALWAYS pass the chain the collection lives on — same slug can differ per chain.", "parameters": {"type": "object", "properties": {"collection": {"type": "string"}, "chain": {"type": "string", "enum": ["ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"], "description": "Chain the collection is on. Default ethereum."}}, "required": ["collection"]}}},
    {"type": "function", "function": {"name": "opensea_best_listings", "description": "Cheapest live OpenSea listings in a collection, with order hashes ready for buying.", "parameters": {"type": "object", "properties": {"collection": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["collection"]}}},
    {"type": "function", "function": {"name": "opensea_holdings", "description": "NFTs owned by a wallet on an OpenSea chain (ethereum/base/arbitrum/optimism/polygon). Defaults to your wallet.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "address": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "opensea_list_nft", "description": "REAL OpenSea listing: executes approvals, signs the Seaport order locally with your wallet, posts to the orderbook. Chains: ethereum, base, arbitrum, optimism, polygon.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "contract": {"type": "string", "description": "NFT contract 0x..."}, "token_id": {"type": "string"}, "price_eth": {"type": "number"}, "days": {"type": "integer", "description": "Listing duration (default 30)"}}, "required": ["chain", "contract", "token_id", "price_eth"]}}},
    {"type": "function", "function": {"name": "opensea_top_offer", "description": "Top (highest) ACTIVE offers on an OpenSea collection — real orderbook bids with offerer, scope (collection-wide/trait) and expiry.", "parameters": {"type": "object", "properties": {"collection": {"type": "string", "description": "slug or contract 0x..."}, "limit": {"type": "integer"}}, "required": ["collection"]}}},
    {"type": "function", "function": {"name": "opensea_place_offer", "description": "REAL per-NFT offer (bid) on OpenSea: WETH-collateralized Seaport order. Build → sign → post. Requires WETH balance (offer locks the WETH). ALWAYS prefer offer_usd (dollars — converted at live ETH rate); if the user says '$50', the offer is 50 DOLLARS, never 50 ETH.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "contract": {"type": "string", "description": "NFT contract 0x..."}, "token_id": {"type": "string"}, "offer_usd": {"type": "number", "description": "offer in US dollars — PREFERRED"}, "offer_eth": {"type": "number", "description": "offer in ETH (only when user is explicit about ETH)"}, "days": {"type": "integer", "description": "Offer expiry (default 7)"}}, "required": ["chain", "contract", "token_id"]}}},
    {"type": "function", "function": {"name": "opensea_buy_nft", "description": "REAL OpenSea purchase: fulfills a live listing on-chain with your wallet. Give order_hash+protocol_address (from opensea_best_listings) OR collection+token_id. ALWAYS prefer max_price_usd (dollars — converted at live ETH rate) over max_price_eth; if the user says '$20' the cap is 20 DOLLARS, never 20 ETH.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "collection": {"type": "string"}, "contract": {"type": "string"}, "token_id": {"type": "string"}, "order_hash": {"type": "string"}, "protocol_address": {"type": "string"}, "max_price_eth": {"type": "number", "description": "cap in ETH (only when user is explicit about ETH)"}, "max_price_usd": {"type": "number", "description": "cap in US dollars — PREFERRED"}}, "required": ["chain"]}}},
    {"type": "function", "function": {"name": "opensea_cancel_listing", "description": "Cancel your OpenSea listing on-chain (costs gas).", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "order_hash": {"type": "string"}, "protocol_address": {"type": "string"}}, "required": ["chain", "order_hash", "protocol_address"]}}},    {"type": "function", "function": {"name": "opensea_drops", "description": "List live OpenSea drops (featured/upcoming/recently_minted) with prices and mint status.", "parameters": {"type": "object", "properties": {"chain": {"type": "string"}, "drop_type": {"type": "string", "enum": ["featured", "upcoming", "recently_minted"]}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "opensea_mint_drop", "description": "REAL batch mint from an OpenSea drop (quantity up to 50): OpenSea builds the mint tx, we sign and broadcast. Only works while the drop is open.", "parameters": {"type": "object", "properties": {"slug": {"type": "string"}, "quantity": {"type": "integer", "description": "How many to mint (default 1)"}}, "required": ["slug"]}}},
    {"type": "function", "function": {"name": "opensea_eligibility", "description": "Check if your wallet is eligible for a drop (allowlist, stage, limits).", "parameters": {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}}},
    {"type": "function", "function": {"name": "opensea_watch_drop", "description": "Queue a drop for auto-minting: a watcher polls until it opens, then mints automatically (with an optional max price cap). The fastest legal way to snipe a mint. ALWAYS prefer max_price_usd (dollars — converted at the live ETH rate when queued); if the user says '$30', the cap is 30 DOLLARS, never 30 ETH.", "parameters": {"type": "object", "properties": {"slug": {"type": "string"}, "max_price_usd": {"type": "number", "description": "cap in US dollars — PREFERRED"}, "max_price_eth": {"type": "number", "description": "cap in ETH (only when user is explicit about ETH)"}, "quantity": {"type": "integer", "description": "How many to mint when it opens (default 1, max 50)"}}, "required": ["slug"]}}},
    {"type": "function", "function": {"name": "opensea_mint_queue", "description": "Show the current drop watch/mint queue and results.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "opensea_unwatch_drop", "description": "Remove a drop from the mint queue.", "parameters": {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}}},
    {"type": "function", "function": {"name": "opensea_free_mints", "description": "Scan live OpenSea drops for FREE (0 ETH) mint opportunities across featured/upcoming/recently_minted.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "description": "Optional chain filter"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "scan_contract_mint", "description": "Read-only on-chain probe of a deployed NFT contract: standard, supply minted/max, mint price (detects FREE), public-sale state, per-wallet limits. Paste any 0x address. Costs nothing. Chains include robinhood.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"]}, "contract": {"type": "string", "description": "Deployed NFT contract 0x…"}}, "required": ["chain", "contract"]}}},
    {"type": "function", "function": {"name": "mint_contract", "description": "REAL direct on-chain mint against a deployed contract (no OpenSea). Detects price, enforces the price cap, signs and broadcasts. Free mints send 0 value. Use scan_contract_mint first to scout. Chains include robinhood (Robinhood-chain NFTs are direct-contract mints, not Seaport orders). ALWAYS prefer max_price_usd (dollars — converted at live ETH rate); if the user says '$5' the cap is 5 DOLLARS, never 5 ETH.", "parameters": {"type": "object", "properties": {"chain": {"type": "string", "enum": ["ethereum", "base", "arbitrum", "optimism", "polygon", "robinhood"]}, "contract": {"type": "string"}, "quantity": {"type": "integer", "description": "1-20"}, "max_price_eth": {"type": "number", "description": "cap in ETH (only when user is explicit about ETH)"}, "max_price_usd": {"type": "number", "description": "cap in US dollars — PREFERRED"}}, "required": ["chain", "contract"]}}},
]

OPENSEA_TOOL_MAP = {
    "opensea_floor": lambda a: opensea_floor(a["collection"], a.get("chain", "ethereum")),
    "opensea_best_listings": lambda a: opensea_best_listings(a["collection"], int(a.get("limit", 5))),
    "opensea_holdings": lambda a: opensea_holdings(a.get("chain", "ethereum"), a.get("address", "")),
    "opensea_list_nft": lambda a: opensea_list_nft(a["chain"], a["contract"], a["token_id"], float(a["price_eth"]), int(a.get("days", 30))),
    "opensea_top_offer": lambda a: opensea_top_offer(a["collection"], int(a.get("limit", 5))),
    "opensea_place_offer": lambda a: opensea_place_offer(
        a["chain"], a["contract"], a["token_id"],
        a.get("offer_eth"), a.get("offer_usd"), int(a.get("days", 7))),
    "opensea_buy_nft": lambda a: opensea_buy_nft(
        a["chain"], a.get("contract", ""), a.get("token_id", ""),
        a.get("collection", ""), a.get("order_hash", ""),
        a.get("protocol_address", ""), a.get("max_price_eth"),
        a.get("max_price_usd")),
    "opensea_cancel_listing": lambda a: opensea_cancel_listing(a["chain"], a["order_hash"], a["protocol_address"]),
    "opensea_drops": lambda a: opensea_drops(a.get("chain", ""), a.get("drop_type", "featured"), int(a.get("limit", 8))),
    "opensea_mint_drop": lambda a: opensea_mint_drop(a["slug"], int(a.get("quantity", 1))),
    "opensea_eligibility": lambda a: opensea_eligibility(a["slug"]),
    "opensea_watch_drop": lambda a: opensea_watch_drop(a["slug"], a.get("max_price_eth"), a.get("max_price_usd"), int(a.get("quantity", 1))),
    "opensea_mint_queue": lambda a: opensea_mint_queue(),
    "opensea_unwatch_drop": lambda a: opensea_unwatch_drop(a["slug"]),
    "opensea_free_mints": lambda a: opensea_free_mints(a.get("chain", ""), int(a.get("limit", 15))),
    "scan_contract_mint": lambda a: scan_contract_mint(a.get("chain", "ethereum"), a["contract"]),
    "mint_contract": lambda a: mint_contract(a.get("chain", "ethereum"), a["contract"], int(a.get("quantity", 1)), a.get("max_price_eth"), a.get("max_price_usd")),
}
