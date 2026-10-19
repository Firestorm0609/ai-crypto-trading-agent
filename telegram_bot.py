#!/usr/bin/env python3
"""
Trading Agent Telegram Bot — full-featured with key rotation.

Features:
- Price alerts with background monitoring
- Portfolio analytics/stats
- Auto-trading strategies (RSI, MA, DCA)
- News sentiment analysis
- Fear & Greed Index
- Risk management
- Multi-provider with Groq key rotation
"""

import sys
import json
import logging
import time
import threading
import asyncio
import base64
from typing import Optional, Union
from openai import OpenAI

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (MISTRAL_API_KEYS, MISTRAL_MODEL, XAI_API_KEY, XAI_MODEL,
                    XAI_BASE_URL, AUTO_TRADE_LIVE, AUTO_TRADE_MAX_USD, TOOL_SCOPING)
from prompt_manager import get_active_prompt
from dspy_optimizer import load_optimized_prompt
from registry import TOOLS as ALL_TOOLS, dispatch_tool, TOOL_MAP
from tool_scoping import select_tools
from guardrails import ActionTracker, review_reply, portfolio_check_message, TRADE_EXECUTION_TOOLS
from solana_commands import (
    cmd_wallet, cmd_buytoken, cmd_selltoken,
    cmd_solprice, cmd_tokenprice, cmd_rugcheck, cmd_newwallet,
    cmd_privatekey, cmd_importwallet,
)
from perps_tools import (
    get_perps_platforms, get_perps_pairs, get_perps_risk_guide,
    open_perps_position, close_perps_position, get_perps_positions,
)
from auto_trading_rules import (
    evaluate_rules as _evaluate_rules, _update_dca_last_buy,
)
from smolagents_agent import run_smolagents_query
from multi_agent import run_multi_agent, get_framework_status, classify_task
from specialized_agents import create_orchestrator
from memory import extract_memories
from features import (
    check_alerts, run_strategies, save_daily_snapshot,
    check_risk, get_stats, add_alert, get_alerts, cancel_alert,
    add_strategy, get_strategies, get_performance_chart,
    get_fear_greed, get_crypto_news, get_risk_status,
)
from trading_tools import (
    get_price, get_top_coins, get_portfolio,
    buy as paper_buy, sell as paper_sell,
    get_trade_history, reset_portfolio,
)
from solana_trader import (
    buy_token as live_buy_token, sell_token as live_sell_token,
    KNOWN_TOKENS as SOL_KNOWN_TOKENS,
)
from evm_swap import (
    real_swap_execute as evm_swap_execute, CHAINS as EVM_CHAINS,
    _load_wallet as _evm_load_wallet, _get_w3 as _evm_get_w3,
    _resolve_token as _evm_resolve_token, _from_units as _evm_from_units,
)
from multichain_tools import KNOWN_EVM_TOKENS


# ============================================================
# Auto-trade execution router (paper → live lane)
# ============================================================

def _execute_autotrade(signal: dict) -> str:
    """Execute one rule/strategy signal from the 60s auto-trade loop.

    Paper by default. With AUTO_TRADE_LIVE=1 (owner-armed in .env), Solana-
    executable signals route to the real Jupiter swap via buy_token/sell_token,
    capped at AUTO_TRADE_MAX_USD per trade.

    The live lane ONLY takes coins with a known Solana mint (SOL_KNOWN_TOKENS) —
    the auto lane never guesses mints by name (impersonation risk), so unknown
    symbols fall back to paper with a note. buy_token/sell_token keep their own
    balance/liquidity/ambiguity refusals, which land in the Telegram message.
    """
    coin = (signal.get("coin") or "").upper()
    action = (signal.get("action") or "").upper()

    if not AUTO_TRADE_LIVE:
        return _paper_autotrade(signal, "flag off")

    if AUTO_TRADE_LIVE:
        logger.info("Auto-trade: routing %s %s", action, coin or "?")
        # EVM_lite first (ETH/native tokens live there); Solana next; else paper
        route = _choose_route(coin, action)
        if route == "sol":
            return _live_sol_trade(signal, coin)
        if route is not None:  # an EVM chain name
            return _live_evm_trade(signal, coin, route)
        return _paper_autotrade(signal, f"no known on-chain token for {coin or '?'} in live lane")
    return _paper_autotrade(signal, "flag off")


def _choose_route(coin: str, action: str):
    """Pick the live lane for an auto-trade signal. Returns 'sol', an EVM
    chain name (base/ethereum/robinhood), or None for paper.

    Same rule as the Solana lane: ONLY coins with a known mint/contract
    match — the auto lane never resolves by name (impersonation risk).
    ETH/WETH live on EVM (base is the cheapest-gas chain); a BUY of ETH
    isn't routable live (nothing to spend but ETH → not a live BUY target);
    a SELL dumps native ETH into USDC. All other coins route by the Solana
    mint map first, then the EVM token registry.
    """
    coin = (coin or "").upper()
    if coin == "USDC":
        return None  # never blind-buy the quote currency itself
    if coin in ("ETH", "WETH"):
        return None if action == "BUY" else "base"  # BUY ETH→USDC is the sensible live sell
    if coin in SOL_KNOWN_TOKENS:
        return "sol"
    for chain in ("base", "ethereum", "robinhood"):
        if coin in KNOWN_EVM_TOKENS.get(chain, {}):
            return chain
    return None


def _live_sol_trade(signal: dict, coin: str, capped_desc: str = "") -> str:
    """Real Jupiter swap from a rule/strategy signal (Solana lane).
    BUYs spend SOL capped at AUTO_TRADE_MAX_USD; SELLs dump the signal's
    percentage. Executor refusals (balance/liquidity/ambiguity) surface to
    the user — never silently papered.
    """
    amount_usd = float(signal.get("amount_usd") or 0)
    capped = min(amount_usd, AUTO_TRADE_MAX_USD) if amount_usd > 0 else None
    cap_note = f" (capped ${amount_usd:.0f} → ${capped:.0f})" if (
        capped is not None and capped < amount_usd) else ""

    try:
        if signal.get("action") == "BUY":
            result = live_buy_token(coin, usd_amount=capped)
        else:
            result = live_sell_token(coin, percentage=float(signal.get("percentage") or 100))
    except Exception as e:
        result = f"❌ Live auto-trade error: {str(e)[:120]}"
    return f"🔴 LIVE{cap_note}\n{result}"


def _live_evm_trade(signal: dict, coin: str, chain: str) -> str:
    """Real EVM swap from a rule/strategy signal. BUYs spend ETH (capped
    in USD); SELLs dump the signal's percentage of the held token for ETH
    (auto-unwrapped). Executor refusals surface to the user, no paper fallback
    for partial state.
    """
    amount_usd = float(signal.get("amount_usd") or 0)
    capped = min(amount_usd, AUTO_TRADE_MAX_USD) if amount_usd > 0 else None
    cap_note = f" (capped ${amount_usd:.0f} → ${capped:.0f})" if (
        capped is not None and capped < amount_usd) else ""

    try:
        if signal.get("action") == "BUY":
            result = evm_swap_execute(chain, "ETH", coin.upper(),
                                      amount=None, usd_amount=capped)
        else:
            pct = float(signal.get("percentage") or 100)
            amount = _evm_sell_amount(chain, coin, pct)
            result = evm_swap_execute(chain, coin.upper(), "ETH", amount=amount) if amount else (
                f"❌ Wallet has no {coin.upper()} balance to sell on {chain}.")
    except Exception as e:
        result = f"❌ Live EVM auto-trade error: {str(e)[:120]}"
    return f"🔴 LIVE EVM ({chain}){cap_note}\n{result}"


def _evm_sell_amount(chain: str, coin: str, pct: float) -> float:
    """Amount of `coin` owned on `chain` for a percentage SELL (0 = none)."""
    try:
        wallet = _evm_load_wallet(chain)
        if not wallet or not wallet.get("private_key"):
            return 0.0
        w3 = _evm_get_w3(chain)
        token = _evm_resolve_token(chain, coin.upper(), w3)
        if token["native"]:
            raw = w3.eth.get_balance(w3.eth.account.from_key(wallet["private_key"]).address)
        else:
            raw = w3.eth.contract(address=token["address"], abi=[
                {"name": "balanceOf", "type": "function", "stateMutability": "view",
                 "inputs": [{"name": "owner", "type": "address", "internalType": "address"}],
                 "outputs": [{"type": "uint256", "internalType": "uint256"}]},
            ]).functions.balanceOf(_evm_wcs(w3, wallet)).call()
        held = _evm_from_units(raw, token)
        held = max(0.0, held - 0.001 if token["native"] else held)  # keep gas
        return held * min(pct, 100.0) / 100.0
    except Exception:
        return 0.0


def _evm_wcs(w3, wallet):
    return w3.eth.account.from_key(wallet["private_key"]).address


def _paper_autotrade(signal: dict, why: str) -> str:
    """Paper fallback for the auto-trade loop, with the reason shown."""
    try:
        if signal.get("action") == "BUY":
            result = paper_buy(signal["coin"], signal["amount_usd"])
        else:
            result = paper_sell(signal["coin"], percentage=signal.get("percentage", 50))
    except Exception as e:
        result = f"❌ Paper trade error: {str(e)[:120]}"
    return f"📄 PAPER ({why})\n{result}"

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# System Prompt
# ============================================================

# Load prompt from prompt manager (versioned, swappable)
# Use: python3 prompt_manager.py use v3 to switch versions
# Load prompt: DSPy optimized > prompt_manager > hardcoded fallback
# Operational-honesty rules — appended at load time so DSPy prompt
# regeneration can never drop them.
SYSTEM_PROMPT = (load_optimized_prompt() or get_active_prompt()) + """

OPERATIONAL HONESTY — how to report infrastructure problems:
- Transient rate limits (429), key rotation, and brief retries are HANDLED AUTOMATICALLY by the system. If a call eventually succeeds, never mention the hiccup — just answer normally.
- Only report an API/system problem if the final result genuinely failed or is incomplete, and then say exactly WHAT failed (which API, which step) and what the user can do (retry in a minute).
- NEVER invent vague phrases like "API issues", "can't verify", "technical difficulties" when you have the data or the call succeeded. If you don't know, say what you don't know and which tool would tell you.
- Never guess or fabricate prices, balances, or statuses. Use the tools; if a tool errors, report its actual error text briefly.
- DATA PROVENANCE: every number you show (price, floor, supply, owners, balance) MUST come from a tool result in THIS conversation. If no tool call produced that number, you do not know it — call the tool. NEVER repeat collection stats from training memory (they are always stale or wrong). If a tool fails, say so and show its error.
FULL TOOLSET — NEVER HOLD BACK (the rule the owner cares about most):
- The COMPLETE tool registry is open to you on every call — trading, perps, NFTs, wallets, files, code, web, memory, automation. Nothing is gated.
- Reach for ANY tool the moment it helps. Don't pre-filter, don't ask permission, don't say 'I don't have a tool for that' unless you checked and none fits — if unsure, TRY the most plausible tool and read the result.
- Chain tool calls freely in one turn (check → verify → act). One call is rarely enough; do the whole job.
- Answering from memory when a tool exists for the fact is a failure. Tools first, always.

CHAIN KNOWLEDGE — get these right:
- 'Robinhood chain' is an ETHEREUM LAYER-2 network — specifically an Arbitrum Orbit rollup, chainId 4663 (0x1237), explorer robinhoodchain.blockscout.com. It is NOT the Robinhood stock brokerage. It supports normal EVM things: ERC-20s, ERC-721/1155 NFTs, Uniswap V2/V3 swaps, direct contract mints. Every EVM tool accepts chain='robinhood' — just pass it like base or arbitrum. Do NOT redirect Robinhood-chain NFT/token questions to stock tools or say it's unsupported.
- One EVM key works on ALL EVM chains (ethereum, base, arbitrum, optimism, polygon, robinhood). The wallet files are already synced per chain.
- EVM NFTs are NOT Seaport-only: OpenSea drops and direct contract mints (scan_contract_mint → mint_contract) work on every chain above, robinhood included.
- NFT collections are PER-CHAIN: 'hood-remilias' exists on robinhood, not ethereum. When a floor/holdings lookup returns not-found, retry with the other chains the user might mean (opensea_floor has a chain param) before saying a collection doesn't exist. Never silently report ethereum data for a collection the user asked about on another chain.
- MONEY UNITS: when the user says '$20', '50 dollars', or any $ amount, that is USD — pass it as max_price_usd on NFT buys/mints, NEVER as max_price_eth. A $20 budget is 20 USD (~0.0085 ETH), not 20 ETH (~$47k). Only use max_price_eth when the user explicitly says 'ETH'.

MONEY & BALANCES — NEVER FROM MEMORY (these are the rules you cannot break):
1. Balance, portfolio total, USDC/ETH/token amounts: ONLY from get_evm_balance, get_multichain_portfolio, or get_wallet_balance called in THIS turn. No tool call = you do not know the number. Never compute it from a price × amount you remembered.
2. A balance stated ANYWHERE earlier in this conversation (by you or the user) is EXPIRED. Re-query before using it in any money decision — funds move.
3. Never invent requirements like 'you need USDC' or 'deposit more X'. What a pool trades against is a fact from the quote/swap tool, not from your head. If a buy failed, report the tool's actual error.
4. If tool calls keep failing (429s, timeouts), say exactly that and stop. NEVER fall back to answering money questions from memory — a wrong balance is worse than no answer.
5. Currency of a pool = what the quote tool says. ABCD-style robinhood pools are usually ETH/WETH-denominated; claiming USDC is required when the tool never said so is a fabrication.
"""

# Fallback if prompt manager fails
if not SYSTEM_PROMPT:
    SYSTEM_PROMPT = """You are a crypto trading bot on Telegram. Be concise, use emoji. Keep responses SHORT (under 100 words).

CRITICAL FORMATTING RULES — BREAK THESE = FAIL:
- NEVER use ** (double asterisks) for bold
- NEVER use # for headers
- NEVER use ``` for code blocks
- NEVER use * (single asterisks) for italic
- Use ONLY plain text with emoji
- Example good: BTC: $78,000 (+0.5%)
- Example bad: **BTC** — $78,000

YOUR TOOLS — USE THEM PROACTIVELY:
- get_price: Get any crypto price
- get_top_coins: Top coins by market cap
- get_trending: Trending coins right now
- get_fear_greed: Market sentiment index
- buy/sell: Paper trading
- get_portfolio: Show holdings
- web_search: Search the internet for ANYTHING you don't know
- add_trading_rule: Set auto-trading rules from natural language
- mint_nft: Mint NFTs on Solana, Ethereum, or Base
- new_wallet: Create wallets for any chain
- list_files/read_file/edit_file: Read and modify your own code

RULES:
1. Use tools PROACTIVELY. Don't wait to be told.
2. If user asks about price, call get_price FIRST.
3. If user asks to trade, confirm then call buy/sell.
4. If user asks about something you don't know, call web_search.
5. If user asks about platforms, compatibility, support — call web_search.
6. If user asks about NFTs, call the NFT tools.
7. If user asks about rules/automation, call auto-trading tools.
8. NEVER guess. NEVER make up answers. ALWAYS use tools.
9. When in doubt, SEARCH. Search is always better than guessing wrong.
10. Keep responses under 100 words. Plain text only, no markdown.
- Example: user says "search for solana news" -> you MUST call web_search("solana news")
- Example: user says "check if robinhood supports nfts" -> you MUST call web_search("robinhood nft support 2026")

WHEN FIXING CODE - THIS IS CRITICAL:
1. You MUST use read_file tool FIRST to read the actual file content
2. You MUST use edit_file tool to make the change
3. You MUST use restart_bot tool to apply
4. NEVER make up code. NEVER guess what the code looks like. ALWAYS use read_file first.
5. NEVER ask permission - just do it. Use the tools immediately.
6. The bot files are in /root/Aesir/ (physically /root/op/ai-crypto-trading-agent)
7. Always explain what you changed after making the edit.
8. If user says "fix" or "edit" or "modify" or "change" code, you MUST call read_file tool first."""


# ============================================================
# LLM Key Rotator (xAI grok — primary; Mistral — fallback)
# ============================================================


class LLMKeyRotator:
    def __init__(self, keys, base_url="https://api.mistral.ai/v1"):
        self.keys = keys
        self.current_index = 0
        self.key_usage = {i: {"requests": 0, "last_error": 0} for i in range(len(keys))}
        self.base_url = base_url

    def get_client(self):
        if not self.keys:
            return None
        key = self.keys[self.current_index]
        return OpenAI(api_key=key, base_url=self.base_url, max_retries=0, timeout=60.0)

    def rotate(self, reason=""):
        if len(self.keys) <= 1:
            return False
        old_index = self.current_index
        self.current_index = (self.current_index + 1) % len(self.keys)
        logger.info(f"Rotated LLM key: {old_index} -> {self.current_index} ({reason})")
        return True

    def mark_error(self):
        self.key_usage[self.current_index]["last_error"] = time.time()
        self.rotate("error")


# ============================================================
# Multi-Provider Trading Agent
# ============================================================

class TradingAgent:
    def __init__(self):
        self.user_histories = {}
        
        # Main LLM: grok via xAI (owner's call 2026-10-15); Mistral stays as fallback
        if XAI_API_KEY:
            self.llm_rotator = LLMKeyRotator([XAI_API_KEY], XAI_BASE_URL)
            self.llm_model = XAI_MODEL
            logger.info(f"LLM provider: xAI grok ({XAI_MODEL})")
        elif MISTRAL_API_KEYS:
            self.llm_rotator = LLMKeyRotator(MISTRAL_API_KEYS)
            self.llm_model = MISTRAL_MODEL
            logger.info(f"LLM provider: Mistral ({len(MISTRAL_API_KEYS)} keys)")
        else:
            raise Exception("No LLM API keys configured! Add XAI_API_KEY (or MISTRAL_API_KEY) to .env")
        
        # Multi-agent orchestrator (Codebuff-style)
        self.orchestrator = create_orchestrator(
            self.llm_rotator.get_client(),
            self.llm_model
        )
        logger.info("Specialized agents initialized")

    def _clean_history(self, history):
        """History cleanup with 1-sentence summary when truncating.
        Boundary-safe: the kept slice never starts inside an
        assistant(tool_calls)→tool block (Mistral rejects orphaned pieces)."""
        if len(history) <= 12:
            return
        has_system = bool(history) and history[0].get("role") == "system"
        system = history[0] if has_system else None
        body = history[1:] if has_system else list(history)
        cut = max(0, len(body) - 10)
        # Never start the kept slice on a tool result — slide forward to the
        # next assistant/user boundary (orphaned results are harmless;
        # _sanitize_history repairs the call side if needed).
        while cut < len(body) and body[cut].get("role") == "tool":
            cut += 1
        kept = body[cut:]
        dropped = body[:cut]
        summary = self._summarize_dropped(dropped)
        history.clear()
        if system:
            history.append(system)
        if summary:
            history.append({"role": "user", "content": f"[Previous context: {summary}]"})
        history.extend(kept)
        logger.info(f"History trimmed to {len(history)} messages with summary")

    def _sanitize_history(self, history):
        """Enforce Mistral's message-order invariants before every API call:
        • every assistant tool_call must be followed by a tool result
        • no tool result may appear without its assistant call preceding it
        • nothing between the system prompt and the first real message
        Repairs in place by synthesizing missing results and dropping
        orphans — self-heals histories poisoned by earlier crashes."""
        if not history:
            return history
        out = []
        idx = 0
        if history[0].get("role") == "system":
            out.append(history[0])
            idx = 1
        while idx < len(history):
            m = history[idx]
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                ids = [tc.get("id") for tc in m["tool_calls"] if tc.get("id")]
                results = {}
                j = idx + 1
                while j < len(history) and history[j].get("role") == "tool":
                    results[history[j].get("tool_call_id")] = history[j]
                    j += 1
                out.append(m)
                for tc_id in ids:
                    if tc_id in results:
                        out.append(results[tc_id])
                    else:
                        out.append({"role": "tool", "tool_call_id": tc_id,
                                    "content": "(no result recorded — call was interrupted)"})
                idx = j
            elif role == "tool":
                idx += 1  # orphan result — drop
            else:
                out.append(m)
                idx += 1
        history[:] = out
        return history

    def _summarize_dropped(self, dropped_messages):
        """Extract key topics from dropped messages into a 1-sentence summary."""
        if not dropped_messages:
            return ""
        topics = []
        for msg in dropped_messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Multimodal message (text + image parts) — keep only
                    # the text parts so the summary never sees a list.
                    text_parts = [p.get("text", "") for p in content
                                  if isinstance(p, dict) and p.get("type") == "text"]
                    content = " ".join(text_parts)
                if isinstance(content, str) and content and len(content) > 5:
                    # Take first sentence or first 80 chars
                    first_sentence = content.split(".")[0].split("?")[0].split("!")[0].strip()
                    if first_sentence and len(first_sentence) > 10:
                        topics.append(first_sentence[:80])
        if not topics:
            return ""
        # Pick last 2-3 meaningful topics
        recent = topics[-3:]
        if len(recent) == 1:
            return recent[0]
        return f"{' then '.join(recent[:-1])} and {recent[-1]}"

    def _get_history(self, user_id: int):
        if user_id not in self.user_histories:
            self.user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        history = self.user_histories[user_id]
        if len(history) > 12:
            self._clean_history(history)
        return history

    def _get_tools(self):
        # All tools — see registry.py (single source of truth)
        return ALL_TOOLS

    def _execute_tool(self, name, args):
        # Unified dispatch — user scoping handled inside registry.dispatch_tool
        return dispatch_tool(name, args, user_id=getattr(self, '_current_user_id', 0))

    def _call_llm(self, history, tools):
        """Call the active LLM (xAI grok, else Mistral) with key rotation.
        Rotates to the next key on rate limits (429) and transient overloads (503).
        """
        transient_hints = ("429", "rate", "503", "high load", "temporarily unavailable", "overloaded", "timed out", "timeout")

        if not self.llm_rotator.keys:
            raise Exception("No LLM keys available")

        last_error = None
        for _ in range(len(self.llm_rotator.keys)):
            client = self.llm_rotator.get_client()
            if not client:
                break
            try:
                response = client.chat.completions.create(
                    model=self.llm_model, messages=self._sanitize_history(history), tools=tools,
                    tool_choice="auto", max_tokens=2000, temperature=0.7,
                    timeout=60.0,
                )
                self.llm_rotator.key_usage[self.llm_rotator.current_index]["requests"] += 1
                return response
            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                if any(hint in error_str for hint in transient_hints):
                    self.llm_rotator.mark_error()
                else:
                    # Non-transient (auth, bad request, etc.) — don't burn other keys
                    raise

        if last_error:
            raise last_error
        raise Exception("No LLM keys available")

    async def handle_message(self, user_id: int, message, image_b64: str = None, image_mime: str = "image/jpeg") -> str:
        # Set user ID for auto-trading rules
        self._current_user_id = user_id

        scope_text = message if isinstance(message, str) else ""
        if image_b64 and not scope_text:
            scope_text = "user sent an image"

        # Extract memories from user message
        try:
            if isinstance(message, str) and message:
                extract_memories(message, user_id)
        except Exception:
            pass

        # Codebuff-style: tool scoping picks a small relevant subset, and
        # the LLM itself decides when to delegate via the delegate tool.
        history = self._get_history(user_id)
        if image_b64:
            caption = message if isinstance(message, str) and message.strip() else "Look at this image and tell me what you see. If it is a chart, token, wallet, or error, extract the useful details."
            history.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": caption},
                    {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}},
                ],
            })
        else:
            history.append({"role": "user", "content": message})
        tools = select_tools(scope_text, ALL_TOOLS) if TOOL_SCOPING else ALL_TOOLS
        tracker = ActionTracker()
        rate_limited = False
        
        # Max steps — 30 is enough for any task
        max_steps = 30
        last_exc_msg = ""
        
        for attempt in range(3):  # Up to 3 key rotations
            try:
                response = self._call_llm(history, tools)
                
                for step in range(max_steps):
                    msg = response.choices[0].message
                    if not msg.tool_calls:
                        history.append({"role": "assistant", "content": msg.content or ""})
                        return review_reply(tracker, msg.content or "(No response)")
                    
                    # Process tool calls
                    tool_calls_data = []
                    for tc in msg.tool_calls:
                        args = tc.function.arguments
                        if len(args) > 200:
                            args = args[:200]
                        tool_calls_data.append({"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": args}})
                    history.append({
                        "role": "assistant", "content": (msg.content or "")[:500],
                        "tool_calls": tool_calls_data
                    })
                    
                    for tc in msg.tool_calls:
                        tool_name = tc.function.name
                        try:
                            tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        except json.JSONDecodeError:
                            tool_args = {}
                        try:
                            result = self._execute_tool(tool_name, tool_args)
                        except Exception as tool_err:
                            # Always answer every tool_call — an unanswered
                            # assistant tool_calls block poisons the history
                            # for Mistral (400 on every later turn).
                            result = f"❌ Tool error: {str(tool_err)[:300]}"
                        tracker.record(tool_name, tool_args, result)

                        # After a real trade, attach fresh portfolio state
                        # to the SAME tool result (Mistral rejects a bare
                        # user message inserted after tool messages: 400)
                        if tool_name in TRADE_EXECUTION_TOOLS:
                            result = f"{result}\n\n{portfolio_check_message()}"
                        if len(result) > 600:
                            result = result[:600] + "... (truncated)"
                        history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    
                    try:
                        response = self._call_llm(history, tools)
                    except Exception as e:
                        # Likely all keys rate-limited (429). Back off once
                        # — per-minute quotas recover quickly — then retry.
                        logger.warning(f"LLM call failed mid-task: {e}")
                        rate_limited = True
                        time.sleep(20)
                        try:
                            response = self._call_llm(history, tools)
                            rate_limited = False
                        except Exception as e2:
                            logger.warning(f"Retry also failed: {e2}")
                            self._clean_history(history)
                            break
                    
                if rate_limited:
                    return ("(The LLM key hit its rate limit mid-task — "
                            "that task made a lot of AI calls. Wait ~1 minute and retry, "
                            "or break the task into smaller pieces.)")
                return "(Reached the step limit without finishing — try a smaller task.)"
            except Exception as e:
                last_exc_msg = str(e)
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                self._clean_history(history)
                continue
        
        if "429" in last_exc_msg or "rate limit" in last_exc_msg.lower():
            return ("The LLM is rate-limited right now — this is a "
                    "quota problem, not a bug. Wait for the quota window to reset.")
        return "(All attempts failed — try again shortly; if it persists, the logs have the details.)"

    def _handle_with_orchestrator(self, user_id: int, message: str) -> Optional[str]:
        """Deprecated: kept for compatibility. Delegation is now LLM-driven
        via the delegate tool, so the keyword orchestrator is not used."""
        return None

    @property
    def _execute_tool_map(self) -> dict:
        """Merged tool map for the orchestrator — from the unified registry."""
        return TOOL_MAP


# ============================================================
# Background Workers
# ============================================================

def alert_checker(bot):
    """Background thread that checks price alerts every 60 seconds."""
    while True:
        try:
            triggered = check_alerts()
            for alert in triggered:
                try:
                    emoji = "📈" if alert["direction"] == "above" else "📉"
                    text = (
                        f"{emoji} *ALERT TRIGGERED!*\n\n"
                        f"{alert['coin'].upper()} is now ${alert['current_price']:,.2f}\n"
                        f"Target: {alert['direction']} ${alert['target_price']:,.2f}"
                    )
                    bot.send_message(chat_id=alert["user_id"], text=text)
                except Exception as e:
                    logger.error(f"Failed to send alert: {e}")
        except Exception as e:
            logger.error(f"Alert checker error: {e}")

        time.sleep(60)

def strategy_runner(bot):
    """Background thread that runs strategies and auto-trading rules every 60 seconds."""
    while True:
        try:
            # Run existing strategies (RSI, DCA, MA Cross)
            signals = run_strategies()
            for signal in signals:
                try:
                    result = _execute_autotrade(signal)

                    text = (
                        f"🤖 Auto-Trade Executed\n\n"
                        f"Strategy: {signal['strategy']}\n"
                        f"Signal: {signal['reason']}\n"
                        f"Action: {signal['action']} {signal['coin'].upper()}\n\n"
                        f"{result}"
                    )
                    bot.send_message(chat_id=signal["user_id"], text=text)
                except Exception as e:
                    logger.error(f"Failed to execute strategy: {e}")
            
            # Run auto-trading rules (price triggers, drop/gain %, stop loss, take profit, conditional)
            rule_signals = _evaluate_rules()
            for signal in rule_signals:
                try:
                    result = _execute_autotrade(signal)
                    
                    # Update DCA last buy time if needed
                    if signal.get("_update_last_buy"):
                        _update_dca_last_buy(signal["rule_id"])

                    text = (
                        f"🤖 Trading Rule Triggered\n\n"
                        f"Strategy: {signal['strategy']}\n"
                        f"Signal: {signal['reason']}\n"
                        f"Action: {signal['action']} {signal['coin'].upper()}\n\n"
                        f"{result}"
                    )
                    bot.send_message(chat_id=signal["user_id"], text=text)
                except Exception as e:
                    logger.error(f"Failed to execute rule: {e}")
        except Exception as e:
            logger.error(f"Strategy runner error: {e}")

        time.sleep(60)  # Check every 60 seconds instead of 300

def daily_snapshot():
    """Save daily portfolio snapshot."""
    while True:
        try:
            save_daily_snapshot()
        except Exception as e:
            logger.error(f"Snapshot error: {e}")
        time.sleep(86400)  # Once per day


# ============================================================
# Telegram Bot Commands
# ============================================================

TELEGRAM_TOKEN = ""
agent = None
application = None
agent_mode = "function"  # "function", "smolagents", or "multi"

ADMIN_USER_ID = 727210504  # owner — sensitive commands are restricted to this user


def admin_only(func):
    """Restrict a command to the bot owner's Telegram user ID."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user is None or update.effective_user.id != ADMIN_USER_ID:
            await update.message.reply_text("🔒 This command is restricted to the bot owner.")
            return
        return await func(update, context)
    return wrapper


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *Trading Agent Bot*\n\n"
        "*Quick Commands:*\n"
        "/portfolio — View holdings\n"
        "/price BTC — Check price\n"
        "/top — Top 10 coins\n"
        "/buy BTC 500 — Buy $500 BTC\n"
        "/sell ETH — Sell all ETH\n"
        "/trades — Trade history\n"
        "/reset — Reset portfolio\n\n"
        "*Advanced Features:*\n"
        "/stats — Portfolio analytics\n"
        "/alert BTC above 80000 — Set price alert\n"
        "/alerts — View active alerts\n"
        "/fear — Fear & Greed Index\n"
        "/news BTC — Crypto news\n"
        "/risk — Risk management status\n"
        "/strategy rsi BTC — Auto-trading\n"
        "/chart — Performance chart\n\n"
        "Or just chat with me naturally!",
    )


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import get_portfolio
    await update.message.reply_text(get_portfolio())


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/trades [chain|kind] — recent REAL executed actions from the journal."""
    from trade_journal import recent
    arg = (context.args[0].lower() if context.args else "")
    chains = {"solana", "ethereum", "base", "robinhood", "arbitrum",
              "optimism", "polygon"}
    kinds = {"swap", "copy", "mint", "nft_buy", "nft_sell", "nft_list",
             "nft_transfer", "bridge", "allowance"}
    if arg in chains:
        await update.message.reply_text(recent(20, chain=arg))
    elif arg in kinds:
        await update.message.reply_text(recent(20, kind=arg))
    else:
        await update.message.reply_text(recent(20))


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import get_price
    if not context.args:
        await update.message.reply_text("Usage: /price BTC")
        return
    await update.message.reply_text(get_price(context.args[0]))


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import get_top_coins
    n = int(context.args[0]) if context.args else 10
    await update.message.reply_text(get_top_coins(n))


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import buy
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /buy BTC 500")
        return
    coin = context.args[0]
    amount = float(context.args[1])

    # Risk check
    risk_check = check_risk(coin, amount)
    if "⚠️" in risk_check:
        await update.message.reply_text(f"{risk_check}\n\nUse /buy {coin} {amount} --force to override")
        return

    await update.message.reply_text(buy(coin, amount))


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import sell
    if not context.args:
        await update.message.reply_text("Usage: /sell BTC")
        return
    coin = context.args[0]
    if len(context.args) > 1 and "%" in context.args[1]:
        await update.message.reply_text(sell(coin, percentage=float(context.args[1].replace("%", ""))))
    elif len(context.args) > 1:
        await update.message.reply_text(sell(coin, quantity=float(context.args[1])))
    else:
        await update.message.reply_text(sell(coin))


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import get_trade_history
    n = int(context.args[0]) if context.args else 10
    await update.message.reply_text(get_trade_history(n))


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from trading_tools import reset_portfolio
    balance = float(context.args[0]) if context.args else 10000.0
    await update.message.reply_text(reset_portfolio(balance))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_stats())


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /alert BTC above 80000
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /alert BTC above 80000\nOr: /alert ETH below 2000")
        return
    coin = context.args[0]
    direction = context.args[1].lower()
    target = float(context.args[2])
    user_id = update.effective_user.id
    await update.message.reply_text(add_alert(user_id, coin, target, direction))


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(get_alerts(user_id))


async def cmd_cancel_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cancelalert 1")
        return
    alert_id = int(context.args[0])
    user_id = update.effective_user.id
    await update.message.reply_text(cancel_alert(user_id, alert_id))


async def cmd_fear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_fear_greed())


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = context.args[0] if context.args else "crypto"
    await update.message.reply_text(get_crypto_news(coin))


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_risk_status())


async def cmd_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /strategy rsi BTC or /strategy dca ETH 100 daily
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/strategy rsi BTC — RSI auto-trade\n"
            "/strategy dca ETH 100 daily — DCA $100/day\n"
            "/strategies — List active strategies"
        )
        return

    strategy_type = context.args[0].lower()
    coin = context.args[1]
    user_id = update.effective_user.id
    params = {}

    if strategy_type == "rsi":
        params = {"buy_threshold": 30, "sell_threshold": 70, "buy_amount": 100}
    elif strategy_type == "dca":
        params = {"amount": float(context.args[2]) if len(context.args) > 2 else 100,
                  "interval": context.args[3] if len(context.args) > 3 else "daily"}

    await update.message.reply_text(add_strategy(user_id, strategy_type, coin, params))


async def cmd_strategies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(get_strategies(user_id))


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args else 7
    await update.message.reply_text(get_performance_chart(days))


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search the web."""
    from all_tools import web_search
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /search bitcoin news")
        return
    await update.message.reply_text(web_search(query))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 All Commands:\n\n"
        "💰 Paper Trading:\n"
        "/portfolio — Holdings\n"
        "/price COIN — Price check\n"
        "/top — Top coins\n"
        "/buy COIN USD — Buy\n"
        "/sell COIN — Sell all\n"
        "/trades — History\n"
        "/stats — Analytics\n"
        "/chart — Performance\n\n"
        "🔴 REAL Trading (Solana + EVM):\n"
        "/wallet — All wallets: Solana + EVM balances\n"
        "/buytoken WIF 0.5 — Buy with SOL (Jupiter)\n"
        "/selltoken WIF — Sell for SOL\n"
        "/solprice — SOL price\n"
        "/tokenprice WIF — Token price\n"
        "/rugcheck WIF — Rug check\n"
        "/newwallet — Generate wallet\n\n"
        "📊 Auto-Trading Rules:\n"
        "/addrule buy btc if it drops 5%\n"
        "/addrule sell eth at 3000\n"
        "/addrule stop loss btc 20%\n"
        "/addrule dca eth daily 100\n"
        "/rules — List active rules\n"
        "/cancelrule ID — Cancel rule\n\n"
        "🖼️ NFTs:\n"
        "/nftwallet solana — Create/view NFT wallet\n"
        "/mintnft CONTRACT NAME chain — Mint NFT\n"
        "/upcomingmints — Upcoming NFT drops\n"
        "/launches on/off [pumpfun/pons/all] — Graduation radar\n\n"
        "🔔 Alerts:\n"
        "/alert COIN above/below PRICE\n"
        "/alerts — List alerts\n"
        "/cancelalert ID — Cancel\n\n"
        "📈 Analysis:\n"
        "/fear — Fear & Greed\n"
        "/news COIN — News\n"
        "/risk — Risk status\n\n"
        "🩺 System:\n"
        "run_self_check — Health of all APIs\n"
        "list_api_keys — Keys (masked)\n"
        "set_api_key(helius, NEW_KEY) — swap an exhausted\nkey instantly, validated first\n\n"
        "💬 Or chat naturally!",
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download a photo the owner sent and let Grok read it."""
    global agent_mode
    if update.effective_user is None or update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("\U0001f512 This bot is private.")
        return
    if not agent_mode or not agent:
        await update.message.reply_text("Agent is off. /agent to turn it on.")
        return

    await update.message.chat.send_action("typing")
    try:
        if update.message.photo:
            # Legacy/photo message — pick the largest size
            photo = update.message.photo[-1]
            media_mime = "image/jpeg"
        else:
            doc = update.message.document
            if doc is None:
                await update.message.reply_text("\u26a0\ufe0f That message has no image I can read.")
                return
            # Screenshots arrive as documents; check size before download
            if doc.file_size and doc.file_size > 8_000_000:
                await update.message.reply_text("\u26a0\ufe0f Image is over 8MB. Send a smaller one.")
                return
            media_mime = doc.mime_type or "image/png"
            photo = doc
        tg_file = await photo.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        if len(raw) > 8_000_000:
            await update.message.reply_text("\u26a0\ufe0f Image is over 8MB. Send a smaller one.")
            return
        b64 = base64.b64encode(raw).decode()
        caption = (update.message.caption or "").strip()
        reply = await agent.handle_message(
            update.effective_user.id,
            caption,
            image_b64=b64,
            image_mime=media_mime,
        )
    except Exception as e:
        logger.exception("photo handler failed")
        reply = f"\u26a0\ufe0f Could not read that image: {e}"

    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    else:
        await update.message.reply_text(reply)


async def _global_error_handler(update, context):
    """Last-resort error net: log the exception and TELL the owner, so a
    failing handler is never mistaken for 'typing & silence'."""
    logger.exception("unhandled update error")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                f"\u26a0\ufe0f Internal error: {context.error}"
            )
    except Exception:
        pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global agent_mode
    # Private bot: only the owner may talk to the agent (it has wallet,
    # trading and file access — strangers must never reach it).
    if update.effective_user is None or update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("🔒 Private bot — access is restricted to the owner.")
        return
    user_id = update.effective_user.id
    message = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Natural language mode switching
    msg_lower = message.lower().strip()
    if any(phrase in msg_lower for phrase in ["switch to smolagents", "use smolagents", "smolagents mode", "code mode", "switch to code"]):
        agent_mode = "smolagents"
        await update.message.reply_text("Switched to smolagents mode! Agent now writes Python code.")
        return
    if any(phrase in msg_lower for phrase in ["switch to function", "use function", "function mode", "normal mode", "standard mode"]):
        agent_mode = "function"
        await update.message.reply_text("Switched to function mode! Agent uses pre-defined tools.")
        return
    if any(phrase in msg_lower for phrase in ["switch to multi", "use multi", "multi mode", "all frameworks", "use all frameworks"]):
        agent_mode = "multi"
        await update.message.reply_text("Switched to multi-agent mode! All frameworks working together.")
        return
    
    # Route based on mode
    if agent_mode == "smolagents":
        try:
            response = run_smolagents_query(message)
        except Exception as e:
            response = f"smolagents error: {str(e)}\nFalling back to function mode..."
            response = await agent.handle_message(user_id, message)
    elif agent_mode == "multi":
        try:
            framework = classify_task(message)
            response = run_multi_agent(message, user_id)
            response = f"[Framework: {framework}]\n\n{response}"
        except Exception as e:
            response = f"Multi-agent error: {str(e)}\nFalling back to function mode..."
            response = await agent.handle_message(user_id, message)
    else:
        response = await agent.handle_message(user_id, message)
    
    if len(response) > 4000:
        response = response[:4000] + "\n\n... (truncated)"
    await update.message.reply_text(response)


async def post_init(application: Application):
    # Full menu — mirrors every registered CommandHandler (42 unique).
    # Keep in sync when adding commands.
    await application.bot.set_my_commands([
        BotCommand("start", "Welcome"),
        BotCommand("help", "Show all commands"),
        BotCommand("portfolio", "View holdings"),
        BotCommand("trades", "Real on-chain trade journal"),
        BotCommand("price", "Check price"),
        BotCommand("top", "Top 10 coins"),
        BotCommand("chart", "Performance chart"),
        BotCommand("stats", "Portfolio analytics"),
        BotCommand("fear", "Fear & Greed Index"),
        BotCommand("news", "Crypto news"),
        BotCommand("search", "Search web"),
        # Market / paper trading
        BotCommand("buy", "Buy crypto (paper)"),
        BotCommand("sell", "Sell crypto (paper)"),
        BotCommand("alert", "Set price alert"),
        BotCommand("alerts", "View alerts"),
        BotCommand("cancelalert", "Cancel alert by ID"),
        # Auto-trading rules
        BotCommand("strategy", "Auto-trading"),
        BotCommand("strategies", "List strategies"),
        BotCommand("addrule", "Add rule: buy btc if it drops 5%"),
        BotCommand("rules", "List active rules"),
        BotCommand("cancelrule", "Cancel rule by ID"),
        BotCommand("risk", "Risk dashboard"),
        # Solana + EVM — real trading
        BotCommand("wallet", "All wallets: Solana + EVM balances"),
        BotCommand("buytoken", "Buy token with SOL (Jupiter, REAL)"),
        BotCommand("selltoken", "Sell token for SOL (Jupiter, REAL)"),
        BotCommand("solprice", "SOL price"),
        BotCommand("tokenprice", "Token price"),
        BotCommand("rugcheck", "RugCheck.xyz report (REAL)"),
        BotCommand("newwallet", "New wallet (refuses overwrite)"),
        BotCommand("importwallet", "Import Solana key (Phantom/CLI/seed)"),
        BotCommand("privatekey", "Show private key"),
        # NFTs
        BotCommand("nftwallet", "NFT wallets + real holdings (all chains)"),
        BotCommand("mintnft", "Mint NFT on any chain"),
        BotCommand("upcomingmints", "Live mint drops (OpenSea)"),
        BotCommand("launches", "Graduation radar (pump.fun + Pons)"),
        # Perps
        BotCommand("perp", "Perps overview"),
        BotCommand("perps", "Perps markets"),
        BotCommand("perpslong", "Open long"),
        BotCommand("perpsshort", "Open short"),
        BotCommand("perpsclose", "Close position"),
        BotCommand("perpspositions", "Open positions"),
        BotCommand("perpsrisk", "Perps risk"),
        # System
        BotCommand("agent", "Switch AI mode (function/smolagents/multi)"),
        BotCommand("agentstatus", "Show AI frameworks status"),
        BotCommand("reset", "Reset paper portfolio"),
    ])
    # Background pingers (copytrade alerts, mint watcher) must schedule onto
    # THIS loop — PTB v20 Application has no .loop attribute.
    _bot_loop = asyncio.get_running_loop()
    try:
        import copytrade as _ct
        import evm_copytrade as _ect
        _ct.BOT_LOOP = _bot_loop
        _ect.BOT_LOOP = _bot_loop
        import launch_watcher as _lw
        _lw.BOT_LOOP = _bot_loop
        _lw.set_bot(application, ADMIN_USER_ID)  # starts the watcher thread
    except Exception as _e:
        logger.warning(f"launch watcher wiring failed: {_e}")
    # Dependency self-check: silent heartbeat, Telegram alert only when a
    # dependency flips up→down or down→up.
    try:
        import self_check as _sc
        _sc.set_notifier(_ct._ping if '_ct' in dir() else None)
        _sc.start_scheduler()
    except Exception:
        pass


# ============================================================
# Perpetual Futures Commands
# ============================================================

async def cmd_perps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show perps platforms, pairs, and usage."""
    if context.args:
        cmd = context.args[0].lower()
        if cmd == "platforms":
            await update.message.reply_text(get_perps_platforms())
        elif cmd == "pairs":
            await update.message.reply_text(get_perps_pairs())
        elif cmd == "risk":
            await update.message.reply_text(get_perps_risk_guide())
        else:
            await update.message.reply_text(_build_perps_help())
    else:
        await update.message.reply_text(_build_perps_help())

def _build_perps_help() -> str:
    return (
        "📊 *Perpetual Futures (Paper Trading)*\n\n"
        "/perps — This help menu\n"
        "/perps platforms — Supported platforms\n"
        "/perps pairs — Available trading pairs\n"
        "/perps risk — Risk management guide\n"
        "/perps_long BTC 5 100 — Long BTC, 5x lev, $100 margin\n"
        "/perps_short BTC 25 5000 — Short BTC, 25x lev, $5K margin\n"
        "/perps_close BTC — Close BTC position\n"
        "/perps_positions — View all open positions\n"
        "⚠️ Leverage trading is high risk!"
    )

async def cmd_perps_long(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open a long position: /perps_long BTC 5 100"""
    try:
        if len(context.args) < 3:
            await update.message.reply_text("Usage: /perps_long BTC 5 100\n(Pair, leverage, margin USD)")
            return
        pair, lev, margin = context.args[0].upper(), int(context.args[1]), float(context.args[2])
        result = open_perps_position(pair, "long", lev, margin)
        await update.message.reply_text(result)
    except ValueError:
        await update.message.reply_text("❌ Invalid numbers. Usage: /perps_long BTC 5 100")

async def cmd_perps_short(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open a short position: /perps_short BTC 25 5000"""
    try:
        if len(context.args) < 3:
            await update.message.reply_text("Usage: /perps_short BTC 25 5000\n(Pair, leverage, margin USD)")
            return
        pair, lev, margin = context.args[0].upper(), int(context.args[1]), float(context.args[2])
        result = open_perps_position(pair, "short", lev, margin)
        await update.message.reply_text(result)
    except ValueError:
        await update.message.reply_text("❌ Invalid numbers. Usage: /perps_short BTC 25 5000")

async def cmd_perps_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close a position: /perps_close BTC"""
    if not context.args:
        await update.message.reply_text("Usage: /perps_close BTC")
        return
    pair = context.args[0].upper()
    result = close_perps_position(pair)
    await update.message.reply_text(result)

async def cmd_perps_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all open perps positions."""
    await update.message.reply_text(get_perps_positions())


async def cmd_perps_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show perps risk management guide."""
    await update.message.reply_text(get_perps_risk_guide())


# ============================================================
# Auto-Trading Rules Commands
# ============================================================

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List active trading rules."""
    from auto_trading_rules import get_rules
    user_id = update.effective_user.id
    await update.message.reply_text(get_rules(user_id))


async def cmd_addrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a trading rule: /addrule buy btc if it drops 5%"""
    from auto_trading_rules import parse_rule_from_text, add_rule
    if not context.args:
        await update.message.reply_text(
            "Usage: /addrule RULE_TEXT\n\n"
            "Examples:\n"
            "/addrule buy btc if it drops 5%\n"
            "/addrule sell eth at 3000\n"
            "/addrule stop loss btc 20%\n"
            "/addrule take profit sol 30%\n"
            "/addrule dca eth daily 100\n"
            "/addrule if btc > 100000 sell eth"
        )
        return
    text = " ".join(context.args)
    parsed = parse_rule_from_text(text)
    if not parsed:
        await update.message.reply_text(f"Could not parse rule: {text}\n\nTry: 'buy btc if it drops 5%' or 'sell eth at 3000'")
        return
    user_id = update.effective_user.id
    result = add_rule(user_id, parsed["rule_type"], parsed["coin"], parsed["params"])
    await update.message.reply_text(result)


async def cmd_cancelrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a trading rule: /cancelrule 1"""
    from auto_trading_rules import cancel_rule
    if not context.args:
        await update.message.reply_text("Usage: /cancelrule RULE_ID")
        return
    user_id = update.effective_user.id
    rule_id = int(context.args[0])
    await update.message.reply_text(cancel_rule(user_id, rule_id))


# ============================================================
# NFT Wallet Commands
# ============================================================

async def cmd_nftwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show NFT wallet + REAL holdings: /nftwallet [chain|all]"""
    from nft_tools import get_nft_portfolio
    chain = (context.args[0].lower() if context.args else "all")
    valid = ("solana", "all", "ethereum", "base", "robinhood", "arbitrum", "optimism", "polygon")
    if chain not in valid:
        await update.message.reply_text(f"Usage: /nftwallet [{'|'.join(valid)}]")
        return
    await update.message.reply_text(get_nft_portfolio(chain))


async def cmd_mintnft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mint NFT: /mintnft CONTRACT_NAME NFT_NAME chain"""
    from nft_tools import NFT_TOOL_MAP
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /mintnft COLLECTION NFT_NAME [chain]\n\n"
            "Examples:\n"
            "/mintnft madlads MyNFT solana\n"
            "/mintnft 0x123... MyNFT ethereum\n"
            "/mintnft 0x456... MyNFT base"
        )
        return
    args = {
        "collection": context.args[0],
        "name": context.args[1],
        "chain": context.args[2] if len(context.args) > 2 else "solana",
    }
    result = NFT_TOOL_MAP["mint_nft"](args)
    await update.message.reply_text(result)


async def cmd_upcomingmints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show upcoming NFT mints."""
    from nft_tools import get_upcoming_mints
    chain = context.args[0] if context.args else "all"
    await update.message.reply_text(get_upcoming_mints(chain))


# ============================================================
# Launch Watcher (Pools.trade on Robinhood chain)
# ============================================================

async def cmd_launches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Launch radar status, or toggle pads: /launches on <pad…|all> / off."""
    import launch_watcher
    args = [a.lower() for a in (context.args or [])]
    if args and args[0] in ("on", "off"):
        on = args[0] == "on"
        pads = args[1:]
        await update.message.reply_text(launch_watcher.set_pads(on, pads))
        return
    await update.message.reply_text(launch_watcher.status_text())


# ============================================================
# Agent Mode Toggle
# ============================================================

async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch agent mode: /agent function, smolagents, or multi"""
    global agent_mode
    if not context.args:
        await update.message.reply_text(
            f"Current mode: {agent_mode}\n\n"
            "Usage:\n"
            "/agent function — Fast, 85 tools, function calling\n"
            "/agent smolagents — Writes Python code, flexible\n"
            "/agent multi — All frameworks working together\n"
            "/agent status — Show current mode & frameworks"
        )
        return
    mode = context.args[0].lower()
    if mode == "status":
        from multi_agent import get_framework_status
        await update.message.reply_text(get_framework_status(agent_mode))
    elif mode in ("function", "smolagents", "multi"):
        agent_mode = mode
        await update.message.reply_text(f"Switched to {mode} mode!")
    else:
        await update.message.reply_text("Unknown mode. Use: function, smolagents, or multi")


async def cmd_agent_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show agent status."""
    from multi_agent import get_framework_status
    await update.message.reply_text(get_framework_status(agent_mode))


# ============================================================
# Main
# ============================================================

def main():
    global TELEGRAM_TOKEN, agent, application

    # Kernel-level single-instance lock. Every launch path (main.py,
    # screen -dmS, tmux, direct run) goes through here — a second poller
    # is now impossible; duplicates exit instantly with a clear message.
    import instance_guard
    instance_guard.ensure_single_instance()

    from pathlib import Path
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                TELEGRAM_TOKEN = line.split("=", 1)[1].strip()

    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    try:
        agent = TradingAgent()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Clear any old conversation histories on startup
    agent.user_histories.clear()

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )
    application = app

    # Private chats only: drop group/channel updates before any handler runs.
    # (ContextTypes has no private_only kwarg in PTB v22 — this gate is the
    # supported way; raising ApplicationHandlerStop skips all later groups.)
    from telegram.ext import TypeHandler, ApplicationHandlerStop

    async def _private_only_gate(update, context):
        chat = getattr(update, "effective_chat", None)
        if chat is not None and chat.type != "private":
            raise ApplicationHandlerStop

    app.add_handler(TypeHandler(Update, _private_only_gate), group=-1)

    # Give the copytrade modules the live bot handle for Telegram pings
    try:
        import copytrade as _ct
        _ct.set_bot(app, ADMIN_USER_ID)
        import evm_copytrade as _ect
        _ect.set_bot(app, ADMIN_USER_ID)
    except Exception as _e:
        logger.warning(f"copytrade wiring failed: {_e}")

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("portfolio", admin_only(cmd_portfolio)))
    app.add_handler(CommandHandler("price", admin_only(cmd_price)))
    app.add_handler(CommandHandler("top", admin_only(cmd_top)))
    app.add_handler(CommandHandler("buy", admin_only(cmd_buy)))
    app.add_handler(CommandHandler("sell", admin_only(cmd_sell)))
    app.add_handler(CommandHandler("trades", admin_only(cmd_trades)))
    app.add_handler(CommandHandler("stats", admin_only(cmd_stats)))
    app.add_handler(CommandHandler("chart", admin_only(cmd_chart)))
    app.add_handler(CommandHandler("alert", admin_only(cmd_alert)))
    app.add_handler(CommandHandler("alerts", admin_only(cmd_alerts)))
    app.add_handler(CommandHandler("cancelalert", admin_only(cmd_cancel_alert)))
    app.add_handler(CommandHandler("fear", cmd_fear))
    app.add_handler(CommandHandler("news", admin_only(cmd_news)))
    app.add_handler(CommandHandler("risk", admin_only(cmd_risk)))
    app.add_handler(CommandHandler("strategy", admin_only(cmd_strategy)))
    app.add_handler(CommandHandler("strategies", admin_only(cmd_strategies)))
    # Perps / leverage commands
    app.add_handler(CommandHandler("perps", admin_only(cmd_perps)))
    app.add_handler(CommandHandler("perpslong", admin_only(cmd_perps_long)))
    app.add_handler(CommandHandler("perpsshort", admin_only(cmd_perps_short)))
    app.add_handler(CommandHandler("perpsclose", admin_only(cmd_perps_close)))
    app.add_handler(CommandHandler("perpspositions", admin_only(cmd_perps_positions)))
    app.add_handler(CommandHandler("perpsrisk", admin_only(cmd_perps_risk)))
    app.add_handler(CommandHandler("perp", admin_only(cmd_perps)))
    # Auto-trading rules
    app.add_handler(CommandHandler("rules", admin_only(cmd_rules)))
    app.add_handler(CommandHandler("addrule", admin_only(cmd_addrule)))
    app.add_handler(CommandHandler("cancelrule", admin_only(cmd_cancelrule)))
    # NFT commands
    app.add_handler(CommandHandler("nftwallet", admin_only(cmd_nftwallet)))
    app.add_handler(CommandHandler("mintnft", admin_only(cmd_mintnft)))
    app.add_handler(CommandHandler("upcomingmints", admin_only(cmd_upcomingmints)))
    app.add_handler(CommandHandler("launches", admin_only(cmd_launches)))
    app.add_handler(CommandHandler("agent", admin_only(cmd_agent)))
    app.add_handler(CommandHandler("agentstatus", cmd_agent_status))
    app.add_handler(CommandHandler("reset", admin_only(cmd_reset)))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("search", admin_only(cmd_search)))
    # Solana trading commands
    app.add_handler(CommandHandler("wallet", admin_only(cmd_wallet)))
    app.add_handler(CommandHandler("buytoken", admin_only(cmd_buytoken)))
    app.add_handler(CommandHandler("selltoken", admin_only(cmd_selltoken)))
    app.add_handler(CommandHandler("solprice", admin_only(cmd_solprice)))
    app.add_handler(CommandHandler("tokenprice", admin_only(cmd_tokenprice)))
    app.add_handler(CommandHandler("rugcheck", admin_only(cmd_rugcheck)))
    app.add_handler(CommandHandler("newwallet", admin_only(cmd_newwallet)))
    app.add_handler(CommandHandler("importwallet", admin_only(cmd_importwallet)))
    app.add_handler(CommandHandler("privatekey", admin_only(cmd_privatekey)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.IMAGE, handle_photo
    ))
    app.add_error_handler(_global_error_handler)

    # Start background workers
    bot = app.bot
    threading.Thread(target=alert_checker, args=(bot,), daemon=True).start()
    threading.Thread(target=strategy_runner, args=(bot,), daemon=True).start()
    threading.Thread(target=daily_snapshot, daemon=True).start()

    # LLM provider summary — xAI grok when set, else Mistral fallback
    xai_count = 1 if XAI_API_KEY else 0
    print("=" * 50)
    print("  🤖 Trading Agent Bot (Full Feature Set)")
    print("=" * 50)
    if xai_count:
        print(f"  Provider: xAI grok ({XAI_MODEL})")
    else:
        print(f"  Provider: Mistral ({len(MISTRAL_API_KEYS)} keys)")
    print(f"  Features: Alerts, Stats, Strategies, News, Fear/Greed, Risk")
    print(f"  Background: Alert checker, Strategy runner, Daily snapshots")
    print(f"  Press Ctrl+C to stop\n")

    # drop_pending_updates=True clears old queued messages on startup
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
