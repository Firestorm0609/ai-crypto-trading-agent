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
from typing import Optional
from openai import OpenAI

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import MISTRAL_API_KEYS, MISTRAL_MODEL
from prompt_manager import get_active_prompt
from dspy_optimizer import load_optimized_prompt
from all_tools import ALL_TOOLS, TOOL_MAP
from solana_commands import (
    cmd_wallet, cmd_buytoken, cmd_selltoken,
    cmd_solprice, cmd_tokenprice, cmd_rugcheck, cmd_newwallet,
    cmd_privatekey,
)
from solana_tools import SOLANA_TOOLS, execute_solana_tool
from multichain_tools import MULTICHAIN_TOOLS, MULTICHAIN_TOOL_MAP
from robinhood_tools import ROBINHOOD_TOOLS, ROBINHOOD_TOOL_MAP
from tokenized_stocks import STOCK_TOOLS, STOCK_TOOL_MAP
from nft_tools import NFT_TOOLS, NFT_TOOL_MAP, new_wallet as _new_wallet, get_upcoming_mints as _get_upcoming_mints
from auto_trading_rules import AUTO_TRADING_TOOLS, execute_auto_trading_tool, evaluate_rules as _evaluate_rules, _update_dca_last_buy
from perps_tools import (
    PERPS_TOOLS, PERPS_TOOL_MAP,
    get_perps_platforms, get_perps_pairs, get_perps_quote,
    get_perps_risk_guide, open_long as _open_long, open_short as _open_short,
    close_position as _close_position_text,
    open_perps_position, close_perps_position, get_perps_positions,
    get_perps_position,
)
from robinhood_mcp import RH_MCP_TOOLS, RH_MCP_TOOL_MAP
from file_tools import FILE_TOOLS, execute_file_tool
from smolagents_agent import run_smolagents_query
from multi_agent import run_multi_agent, get_framework_status, classify_task
from super_tools import SUPER_TOOLS, SUPER_TOOL_MAP
from uniswap_tools import UNISWAP_TOOLS, UNISWAP_TOOL_MAP
from jupiter_tools import JUPITER_TOOLS, JUPITER_TOOL_MAP
from swap_tools import SWAP_TOOLS, SWAP_TOOL_MAP
from trend_scanner import TREND_TOOLS, TREND_TOOL_MAP
from web_tools import WEB_TOOLS, WEB_TOOL_MAP
from agent_tools import AGENT_TOOLS, AGENT_TOOL_MAP, suggest_followups as suggest_followups_tool
from specialized_agents import create_orchestrator
from full_agent_tools import FULL_AGENT_TOOLS, FULL_AGENT_TOOL_MAP
from memory import MEMORY_TOOLS, MEMORY_TOOL_MAP, extract_memories, set_current_user
from features import (
    check_alerts, run_strategies, save_daily_snapshot,
    check_risk, get_stats, add_alert, get_alerts, cancel_alert,
    add_strategy, get_strategies, get_performance_chart,
    get_fear_greed, get_crypto_news,
)
from trading_tools import (
    get_price, get_top_coins, get_portfolio,
    buy as paper_buy, sell as paper_sell,
    get_trade_history, reset_portfolio,
)

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
SYSTEM_PROMPT = load_optimized_prompt() or get_active_prompt()

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
6. The bot files are in /root/gemini-agent/
7. Always explain what you changed after making the edit.
8. If user says "fix" or "edit" or "modify" or "change" code, you MUST call read_file tool first."""


# ============================================================
# Mistral Key Rotator (primary provider)
# ============================================================
# Groq keys are disabled but preserved in .env for future use
# To re-enable: uncomment GROQ_API_KEY lines in .env


class MistralKeyRotator:
    def __init__(self, keys):
        self.keys = keys
        self.current_index = 0
        self.key_usage = {i: {"requests": 0, "last_error": 0} for i in range(len(keys))}
        self.base_url = "https://api.mistral.ai/v1"

    def get_client(self):
        if not self.keys:
            return None
        key = self.keys[self.current_index]
        return OpenAI(api_key=key, base_url=self.base_url, max_retries=0, timeout=15.0)

    def rotate(self, reason=""):
        if len(self.keys) <= 1:
            return False
        old_index = self.current_index
        self.current_index = (self.current_index + 1) % len(self.keys)
        logger.info(f"Rotated Mistral key: {old_index} -> {self.current_index} ({reason})")
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
        
        # Mistral only — simpler, more reliable, 1B tokens/month
        if not MISTRAL_API_KEYS:
            raise Exception("No Mistral API keys configured!")
        
        self.mistral_rotator = MistralKeyRotator(MISTRAL_API_KEYS)
        logger.info(f"Initialized with {len(MISTRAL_API_KEYS)} Mistral keys")
        
        # Multi-agent orchestrator (Codebuff-style)
        self.orchestrator = create_orchestrator(
            self.mistral_rotator.get_client(),
            MISTRAL_MODEL
        )
        logger.info("Specialized agents initialized")

    def _clean_history(self, history):
        """History cleanup with 1-sentence summary when truncating."""
        if len(history) <= 12:
            return
        # Keep system prompt + last 10 messages
        system = history[0]
        kept = history[-10:]
        # Build summary from messages being dropped
        dropped = history[1:-10]
        summary = self._summarize_dropped(dropped)
        history.clear()
        history.append(system)
        if summary:
            history.append({"role": "user", "content": f"[Previous context: {summary}]"})
        history.extend(kept)
        logger.info(f"History trimmed to {len(history)} messages with summary")

    def _summarize_dropped(self, dropped_messages):
        """Extract key topics from dropped messages into a 1-sentence summary."""
        if not dropped_messages:
            return ""
        topics = []
        for msg in dropped_messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if content and len(content) > 5:
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
        # Keep system prompt + last 10 messages max (~5 turns)
        if len(history) > 12:
            system = history[0]
            kept = history[-10:]
            # Summarize what we're dropping
            dropped = history[1:-10]
            summary = self._summarize_dropped(dropped)
            history.clear()
            history.append(system)
            if summary:
                history.append({"role": "user", "content": f"[Previous context: {summary}]"})
            history.extend(kept)
            self.user_histories[user_id] = history
            logger.info(f"History loaded: {len(history)} messages (with summary)")
        return history

    def _get_tools(self):
        # All tools — Groq may413 but will rotate to Mistral which handles larger payloads
        return ALL_TOOLS + SOLANA_TOOLS + MULTICHAIN_TOOLS + ROBINHOOD_TOOLS + STOCK_TOOLS + NFT_TOOLS + PERPS_TOOLS + RH_MCP_TOOLS + FILE_TOOLS + AUTO_TRADING_TOOLS + SUPER_TOOLS + MEMORY_TOOLS + UNISWAP_TOOLS + JUPITER_TOOLS + SWAP_TOOLS + TREND_TOOLS + WEB_TOOLS + AGENT_TOOLS + FULL_AGENT_TOOLS

    def _execute_tool(self, name, args):
        # Solana tools
        if name in ["generate_wallet", "get_wallet_balance", "get_sol_price",
                    "get_token_price", "buy_token", "sell_token",
                    "rug_check", "get_wallet_address"]:
            return execute_solana_tool(name, args)
        # Robinhood MCP tools
        if name in RH_MCP_TOOL_MAP:
            return RH_MCP_TOOL_MAP[name](args)
        # NFT tools
        if name in NFT_TOOL_MAP:
            return NFT_TOOL_MAP[name](args)
        # Perps tools
        if name in PERPS_TOOL_MAP:
            return PERPS_TOOL_MAP[name](args)
        # Tokenized stocks
        if name in STOCK_TOOL_MAP:
            return STOCK_TOOL_MAP[name](args)
        # Robinhood tools
        if name in ROBINHOOD_TOOL_MAP:
            return ROBINHOOD_TOOL_MAP[name](args)
        # Multichain tools
        if name in MULTICHAIN_TOOL_MAP:
            return MULTICHAIN_TOOL_MAP[name](args)
        # File tools (sandboxed)
        if name in ["list_files", "read_file", "write_file", "edit_file", "run_safe_command", "restart_bot"]:
            return execute_file_tool(name, args)
        # Auto-trading rules
        if name in ["add_trading_rule", "get_trading_rules", "cancel_trading_rule"]:
            args["user_id"] = getattr(self, '_current_user_id', 0)
            return execute_auto_trading_tool(name, args)
        # Super tools (whale, scanner, sentiment, gas, etc.)
        if name in SUPER_TOOL_MAP:
            return SUPER_TOOL_MAP[name](args)
        # Uniswap tools
        if name in UNISWAP_TOOL_MAP:
            return UNISWAP_TOOL_MAP[name](args)
        # Jupiter tools
        if name in JUPITER_TOOL_MAP:
            return JUPITER_TOOL_MAP[name](args)
        # Swap tools (real execution)
        if name in SWAP_TOOL_MAP:
            return SWAP_TOOL_MAP[name](args)
        # Trend scanner tools
        if name in TREND_TOOL_MAP:
            return TREND_TOOL_MAP[name](args)
        # Web access tools (GitHub, scrape, Twitter)
        if name in WEB_TOOL_MAP:
            return WEB_TOOL_MAP[name](args)
        # Agent intelligence tools (plan, ask, suggest, verify)
        if name in AGENT_TOOL_MAP:
            args["user_id"] = getattr(self, '_current_user_id', 0)
            return AGENT_TOOL_MAP[name](args)
        # Full agent tools (read_url, code_search, git, etc.)
        if name in FULL_AGENT_TOOL_MAP:
            args["user_id"] = getattr(self, '_current_user_id', 0)
            return FULL_AGENT_TOOL_MAP[name](args)
        # Memory tools
        if name in MEMORY_TOOL_MAP:
            set_current_user(getattr(self, '_current_user_id', 0))
            return MEMORY_TOOL_MAP[name](args)
        # Paper trading + general tools
        if name in TOOL_MAP:
            return TOOL_MAP[name](args)
        return f"Unknown tool: {name}"

    def _call_llm(self, history, tools):
        """Call Mistral with automatic key rotation."""
        client = self.mistral_rotator.get_client()
        if not client:
            raise Exception("No Mistral keys available")
        
        try:
            response = client.chat.completions.create(
                model=MISTRAL_MODEL, messages=history, tools=tools,
                tool_choice="auto", max_tokens=2000, temperature=0.7,
                timeout=15.0,
            )
            self.mistral_rotator.key_usage[self.mistral_rotator.current_index]["requests"] += 1
            return response
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate" in error_str.lower():
                self.mistral_rotator.mark_error()
                logger.warning("Mistral rate limited, rotating key...")
                # Retry with next key
                client = self.mistral_rotator.get_client()
                if client:
                    return client.chat.completions.create(
                        model=MISTRAL_MODEL, messages=history, tools=tools,
                        tool_choice="auto", max_tokens=2000, temperature=0.7,
                        timeout=15.0,
                    )
            raise
        last_error = None
        for attempt in range(30):
            for provider in self.providers:
                try:
                    if provider["type"] == "groq":
                        client = self.groq_rotator.get_client()
                        if not client:
                            continue
                        response = client.chat.completions.create(
                            model=provider["model"], messages=history, tools=tools,
                            tool_choice="auto", max_tokens=2000, temperature=0.7,
                            timeout=10.0,
                        )
                        self.groq_rotator.key_usage[self.groq_rotator.current_index]["requests"] += 1
                        return response
                    elif provider["type"] == "mistral":
                        client = self.mistral_rotator.get_client()
                        if not client:
                            continue
                        response = client.chat.completions.create(
                            model=provider["model"], messages=history, tools=tools,
                            tool_choice="auto", max_tokens=2000, temperature=0.7,
                            timeout=15.0,
                        )
                        self.mistral_rotator.key_usage[self.mistral_rotator.current_index]["requests"] += 1
                        return response
                    else:
                        response = provider["client"].chat.completions.create(
                            model=provider["model"], messages=history, tools=tools,
                            tool_choice="auto", max_tokens=2000, temperature=0.7,
                            timeout=15.0,
                        )
                        return response
                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "rate" in error_str.lower():
                        if provider["type"] == "groq":
                            self.groq_rotator.mark_error()
                            logger.warning("Groq rate limited, rotating key...")
                        elif provider["type"] == "mistral":
                            self.mistral_rotator.mark_error()
                            logger.warning("Mistral rate limited, rotating key...")
                        continue
                    last_error = e
                    continue
        raise Exception(f"All providers failed. Last: {last_error}")

    async def handle_message(self, user_id: int, message: str) -> str:
        # Set user ID for auto-trading rules
        self._current_user_id = user_id
        
        # Extract memories from user message
        try:
            extract_memories(message, user_id)
        except Exception:
            pass
        
        # Try multi-agent orchestrator first (Codebuff-style)
        agent_result = self._handle_with_orchestrator(user_id, message)
        if agent_result:
            return agent_result
        
        # Fall back to single-agent approach
        # No keyword hacking — the LLM decides when to use tools.
        history = self._get_history(user_id)
        history.append({"role": "user", "content": message})
        tools = self._get_tools()
        
        # Max steps — 30 is enough for any task
        max_steps = 30
        
        for attempt in range(3):  # Up to 3 key rotations
            try:
                response = self._call_llm(history, tools)
                
                for step in range(max_steps):
                    msg = response.choices[0].message
                    if not msg.tool_calls:
                        history.append({"role": "assistant", "content": msg.content or ""})
                        return msg.content or "(No response)"
                    
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
                        result = self._execute_tool(tool_name, tool_args)
                        if len(result) > 600:
                            result = result[:600] + "... (truncated)"
                        history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    
                    try:
                        response = self._call_llm(history, tools)
                    except Exception as e:
                        logger.warning(f"LLM call failed: {e}")
                        self._clean_history(history)
                        break
                
                return "(Max steps reached)"
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                self._clean_history(history)
                continue
        
        return "(All attempts failed)"

    def _handle_with_orchestrator(self, user_id: int, message: str) -> Optional[str]:
        """Try to handle message with specialized agents."""
        try:
            tools = self._get_tools()
            result = self.orchestrator.handle_message(message, tools, self._execute_tool_map)
            # Fall back to main loop if orchestrator failed or hit max steps
            if result and result != "(No response)" and "error" not in result.lower() and "max steps" not in result.lower():
                return result
        except Exception as e:
            logger.warning(f"Orchestrator failed: {e}")
        return None

    @property
    def _execute_tool_map(self) -> dict:
        """Build a merged tool map for the orchestrator."""
        from all_tools import TOOL_MAP
        from super_tools import SUPER_TOOL_MAP
        from web_tools import WEB_TOOL_MAP
        from trend_scanner import TREND_TOOL_MAP
        from uniswap_tools import UNISWAP_TOOL_MAP
        from jupiter_tools import JUPITER_TOOL_MAP
        from swap_tools import SWAP_TOOL_MAP
        from agent_tools import AGENT_TOOL_MAP
        from memory import MEMORY_TOOL_MAP
        
        merged = {}
        merged.update(TOOL_MAP)
        merged.update(SUPER_TOOL_MAP)
        merged.update(WEB_TOOL_MAP)
        merged.update(TREND_TOOL_MAP)
        merged.update(UNISWAP_TOOL_MAP)
        merged.update(JUPITER_TOOL_MAP)
        merged.update(SWAP_TOOL_MAP)
        merged.update(AGENT_TOOL_MAP)
        merged.update(FULL_AGENT_TOOL_MAP)
        merged.update(MEMORY_TOOL_MAP)
        return merged


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
                    if signal["action"] == "BUY":
                        result = paper_buy(signal["coin"], signal["amount_usd"])
                    else:
                        result = paper_sell(signal["coin"], percentage=signal.get("percentage", 50))

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
                    if signal["action"] == "BUY":
                        result = paper_buy(signal["coin"], signal["amount_usd"])
                    else:
                        result = paper_sell(signal["coin"], percentage=signal.get("percentage", 50))
                    
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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mistral_count = len(MISTRAL_API_KEYS)
    await update.message.reply_text(
        f"🤖 *Trading Agent Bot*\n\n"
        f"Providers: Groq ({mistral_count} keys) + OpenRouter\n"
        f"Auto-failover & key rotation enabled!\n\n"
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
        "🔴 REAL Trading (Solana):\n"
        "/wallet — View wallet\n"
        "/buytoken WIF 0.5 — Buy with SOL\n"
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
        "/upcomingmints — Upcoming NFT drops\n\n"
        "🔔 Alerts:\n"
        "/alert COIN above/below PRICE\n"
        "/alerts — List alerts\n"
        "/cancelalert ID — Cancel\n\n"
        "📈 Analysis:\n"
        "/fear — Fear & Greed\n"
        "/news COIN — News\n"
        "/risk — Risk status\n\n"
        "💬 Or chat naturally!",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global agent_mode
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
    await application.bot.set_my_commands([
        BotCommand("start", "Welcome"),
        BotCommand("portfolio", "View holdings"),
        BotCommand("price", "Check price"),
        BotCommand("top", "Top 10 coins"),
        BotCommand("buy", "Buy crypto"),
        BotCommand("sell", "Sell crypto"),
        BotCommand("trades", "Trade history"),
        BotCommand("stats", "Portfolio analytics"),
        BotCommand("chart", "Performance chart"),
        BotCommand("alert", "Set price alert"),
        BotCommand("alerts", "View alerts"),
        BotCommand("fear", "Fear & Greed Index"),
        BotCommand("news", "Crypto news"),
        BotCommand("strategy", "Auto-trading"),
        BotCommand("strategies", "List strategies"),
        BotCommand("risk", "Risk status"),
        BotCommand("wallet", "Solana wallet"),
        BotCommand("buytoken", "Buy token (REAL)"),
        BotCommand("selltoken", "Sell token (REAL)"),
        BotCommand("solprice", "SOL price"),
        BotCommand("tokenprice", "Token price"),
        BotCommand("rugcheck", "Rug check"),
        BotCommand("newwallet", "New wallet"),
        BotCommand("reset", "Reset portfolio"),
        BotCommand("agent", "Switch AI mode (function/smolagents/multi)"),
        BotCommand("agentstatus", "Show AI frameworks status"),
        BotCommand("help", "Show commands"),
    ])


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
    """Create or view NFT wallet: /nftwallet solana"""
    from nft_tools import new_wallet as _new_wallet
    chain = context.args[0].lower() if context.args else "solana"
    if chain not in ("solana", "ethereum", "base"):
        await update.message.reply_text("Usage: /nftwallet solana|ethereum|base")
        return
    # If wallet exists, show portfolio
    from nft_tools import get_nft_portfolio
    from pathlib import Path
    wallet_file = Path(__file__).parent / "wallets" / f"{chain}_wallet.json" if chain != "solana" else Path(__file__).parent / "wallets" / "solana_wallet.json"
    if wallet_file.exists():
        await update.message.reply_text(get_nft_portfolio(chain))
    else:
        await update.message.reply_text(_new_wallet(chain))


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

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("cancelalert", cmd_cancel_alert))
    app.add_handler(CommandHandler("fear", cmd_fear))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("strategy", cmd_strategy))
    app.add_handler(CommandHandler("strategies", cmd_strategies))
    # Perps / leverage commands
    app.add_handler(CommandHandler("perps", cmd_perps))
    app.add_handler(CommandHandler("perpslong", cmd_perps_long))
    app.add_handler(CommandHandler("perpsshort", cmd_perps_short))
    app.add_handler(CommandHandler("perpsclose", cmd_perps_close))
    app.add_handler(CommandHandler("perpspositions", cmd_perps_positions))
    app.add_handler(CommandHandler("perpsrisk", cmd_perps_risk))
    app.add_handler(CommandHandler("perp", cmd_perps))
    # Auto-trading rules
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("addrule", cmd_addrule))
    app.add_handler(CommandHandler("cancelrule", cmd_cancelrule))
    # NFT commands
    app.add_handler(CommandHandler("nftwallet", cmd_nftwallet))
    app.add_handler(CommandHandler("mintnft", cmd_mintnft))
    app.add_handler(CommandHandler("upcomingmints", cmd_upcomingmints))
    app.add_handler(CommandHandler("agent", cmd_agent))
    app.add_handler(CommandHandler("agentstatus", cmd_agent_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("search", cmd_search))
    # Solana trading commands
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("buytoken", cmd_buytoken))
    app.add_handler(CommandHandler("selltoken", cmd_selltoken))
    app.add_handler(CommandHandler("solprice", cmd_solprice))
    app.add_handler(CommandHandler("tokenprice", cmd_tokenprice))
    app.add_handler(CommandHandler("rugcheck", cmd_rugcheck))
    app.add_handler(CommandHandler("newwallet", cmd_newwallet))
    app.add_handler(CommandHandler("privatekey", cmd_privatekey))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start background workers
    bot = app.bot
    threading.Thread(target=alert_checker, args=(bot,), daemon=True).start()
    threading.Thread(target=strategy_runner, args=(bot,), daemon=True).start()
    threading.Thread(target=daily_snapshot, daemon=True).start()

    mistral_count = len(MISTRAL_API_KEYS)
    print("=" * 50)
    print("  🤖 Trading Agent Bot (Full Feature Set)")
    print("=" * 50)
    print(f"  Provider: Mistral ({len(MISTRAL_API_KEYS)} keys)")
    print(f"  Features: Alerts, Stats, Strategies, News, Fear/Greed, Risk")
    print(f"  Background: Alert checker, Strategy runner, Daily snapshots")
    print(f"  Press Ctrl+C to stop\n")

    # drop_pending_updates=True clears old queued messages on startup
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
