"""
Solana Trading Commands for Telegram Bot.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show wallet info and balances."""
    from solana_trader import get_wallet_info
    await update.message.reply_text(get_wallet_info(), parse_mode="Markdown")


async def cmd_buytoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buy a token with SOL. Usage: /buytoken WIF 0.5"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /buytoken TOKEN AMOUNT_SOL\n"
            "Example: /buytoken WIF 0.5\n\n"
            "Known tokens: WIF, BONK, PEPE, POPCAT, FARTCOIN, TRUMP, etc."
        )
        return

    token = context.args[0]
    sol_amount = float(context.args[1])

    # Confirm before trading
    await update.message.reply_text(
        f"🔄 Getting quote for {token.upper()}...\n"
        f"Spending: {sol_amount} SOL"
    )

    from solana_trader import buy_token
    result = buy_token(token, sol_amount)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_selltoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sell a token for SOL. Usage: /selltoken WIF 100"""
    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: /selltoken TOKEN [PERCENTAGE]\n"
            "Example: /selltoken WIF (sell all)\n"
            "Example: /selltoken WIF 50 (sell 50%)"
        )
        return

    token = context.args[0]
    percentage = float(context.args[1]) if len(context.args) > 1 else 100

    from solana_trader import sell_token
    result = sell_token(token, percentage)
    await update.message.reply_text(result, parse_mode="Markdown")


async def cmd_solprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get current SOL price."""
    from solana_trader import get_sol_price
    price = get_sol_price()
    await update.message.reply_text(f"💰 SOL: ${price:,.2f}")


async def cmd_rugcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check rug pull risk for a token."""
    if not context.args:
        await update.message.reply_text("Usage: /rugcheck WIF")
        return

    token = context.args[0]
    from solana_trader import check_rug_risk
    result = check_rug_risk(token)
    await update.message.reply_text(f"🔍 *Rug Check: {token.upper()}*\n\n{result}", parse_mode="Markdown")


async def cmd_newwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a new wallet."""
    from solana_trader import generate_wallet
    wallet = generate_wallet()
    await update.message.reply_text(
        f"🆕 *New Wallet Generated*\n\n"
        f"Address: `{wallet['public_key']}`\n"
        f"🔑 Private Key: `{wallet['private_key']}`\n\n"
        f"⚠️ *SAVE THIS PRIVATE KEY SECURELY!*\n"
        f"Fund this wallet with SOL to start trading!\n\n"
        f"Send SOL to: `{wallet['public_key']}`",
        parse_mode="Markdown",
    )


async def cmd_tokenprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get price of any SPL token."""
    if not context.args:
        await update.message.reply_text("Usage: /tokenprice WIF")
        return

    token = context.args[0].upper()
    from solana_trader import KNOWN_TOKENS, get_token_price

    mint = KNOWN_TOKENS.get(token)
    if not mint:
        await update.message.reply_text(f"Unknown token: {token}\nKnown: {', '.join(KNOWN_TOKENS.keys())}")
        return

    price = get_token_price(mint)
    if price > 0:
        await update.message.reply_text(f"💰 {token}: ${price:,.6f}")
    else:
        await update.message.reply_text(f"Unable to get price for {token}")


async def cmd_privatekey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the private key of the current wallet."""
    from solana_trader import load_wallet
    wallet = load_wallet()
    await update.message.reply_text(
        f"🔑 *Your Private Key:*\n"
        f"`{wallet['private_key']}`\n\n"
        f"⚠️ *DO NOT share this with anyone!*\n"
        f"Store it securely and never paste it in public chat.",
        parse_mode="Markdown",
    )


# Command list for registration
SOLANA_COMMANDS = [
    ("wallet", "View Solana wallet & balances"),
    ("buytoken", "Buy token with SOL (REAL trading)"),
    ("selltoken", "Sell token for SOL (REAL trading)"),
    ("solprice", "Get SOL price"),
    ("tokenprice", "Get any SPL token price"),
    ("rugcheck", "Check rug pull risk"),
    ("newwallet", "Generate new wallet"),
    ("privatekey", "Show wallet private key"),
]
