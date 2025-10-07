#!/usr/bin/env python3
"""
Telegram bot optimized + cleaned-up for deployment (FastAPI + python-telegram-bot v20+).
Features:
 - /p [ticker]  -> crypto price (optimized via /coins/markets, fallback to /coins/{id})
 - /cv [amount] [from] [to] -> convert
 - Admin: /kick, /ban, /mute (with improved admin checks & bot permission checks)
 - Webhook endpoint: /webhook/{TOKEN}
"""

import logging
import os
import time
from math import floor, log10
from typing import Optional

import requests
import uvicorn
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Config / constants ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
COINGECKO_API = "https://api.coingecko.com/api/v3"

app = FastAPI()
application: Optional[Application] = None  # will be set in initialize_bot()


# --- Helpers ---

def round_significant(x: float, sig: int = 4) -> str:
    """Return a string representing x rounded to 'sig' significant digits with thousand separators.
    Always returns a string to avoid mixed-type formatting issues."""
    try:
        if x == 0:
            return "0"
        if abs(x) < 1e-10:
            # very tiny, show with more decimals
            return f"{x:.8f}"
        digits = sig - int(floor(log10(abs(x)))) - 1
        rounded = round(x, digits)
        # If rounded is effectively an integer, format without decimal places, else keep decimals.
        if abs(rounded - int(rounded)) < 1e-12:
            return f"{int(rounded):,}"
        # Use general formatting but maintain separators
        # Determine decimal places to show (max digits)
        fmt = f"{{:,.{max(digits, 0)}f}}"
        return fmt.format(rounded)
    except Exception:
        # Fallback safe formatting
        return str(x)


def get_coin_id(ticker: str) -> str:
    """Map common tickers to CoinGecko IDs; default to lowercase input."""
    t = ticker.lower()
    if t == "idr":
        return "idr"
    if t == "btc":
        return "bitcoin"
    if t == "eth":
        return "ethereum"
    if t == "usdt":
        return "tether"
    # add more aliases here if needed
    return t


async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if user is admin/creator in the chat."""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.error("Failed to check user admin status: %s", e)
        return False


async def is_bot_admin(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the bot is admin in the chat."""
    try:
        bot_id = context.bot.id
        member = await context.bot.get_chat_member(chat_id, bot_id)
        return member.status == "administrator"
    except Exception as e:
        logger.error("Failed to check bot admin status: %s", e)
        return False


# --- Command Handlers ---

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/p [TICKER] - fetch price + stats from CoinGecko (optimized)."""
    if not context.args:
        await update.message.reply_text("Format: /p [Ticker Kripto]. Contoh: /p BTC")
        return

    ticker = context.args[0].upper()
    coin_id = get_coin_id(ticker)

    # Try faster endpoint: /coins/markets
    try:
        markets_url = f"{COINGECKO_API}/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": coin_id,
            # include 1h,24h,7d changes if available
            "price_change_percentage": "1h,24h,7d"
        }
        resp = requests.get(markets_url, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json()
        if items:
            data = items[0]
            price_usd = data.get("current_price", 0)
            price_btc = None
            price_eth = None
            # markets endpoint doesn't return btc/eth price by default; try calculate via tickers or fallback
            # We'll attempt to fetch simple/price for BTC and ETH if needed
            # Get percent changes (may be under keys like price_change_percentage_1h_in_currency)
            p_1h = None
            p_24h = data.get("price_change_percentage_24h", None)
            # price_change_percentage_1h_in_currency may be present as a nested property
            p_1h = data.get("price_change_percentage_1h_in_currency", None)
            p_7d = data.get("price_change_percentage_7d_in_currency", None)

            high_24h = data.get("high_24h", 0)
            low_24h = data.get("low_24h", 0)
            market_cap_usd = data.get("market_cap", 0) or 0
            total_volume_usd = data.get("total_volume", 0) or 0
            fdv_usd = data.get("fully_diluted_valuation", 0) or 0
            rank = data.get("market_cap_rank", "N/A")

            # Try to fetch btc/eth equivalent via simple/price if needed
            try:
                sp = requests.get(
                    f"{COINGECKO_API}/simple/price",
                    params={
                        "ids": coin_id,
                        "vs_currencies": "btc,eth,usd"
                    },
                    timeout=8
                )
                sp.raise_for_status()
                spj = sp.json().get(coin_id, {})
                price_btc = spj.get("btc", None)
                price_eth = spj.get("eth", None)
            except Exception:
                price_btc = price_eth = None

            def get_emoji(x):
                try:
                    if x is None:
                        return ""
                    if x >= 5:
                        return "🍻"
                    if x > 0:
                        return "😀"
                    if x < 0:
                        return "😔"
                except Exception:
                    pass
                return ""

            # Format outputs
            usd_str = round_significant(price_usd, 4)
            btc_str = round_significant(price_btc, 8) if price_btc is not None else "N/A"
            eth_str = round_significant(price_eth, 8) if price_eth is not None else "N/A"

            output = (
                f"*{ticker}*\n"
                f"${usd_str}\n"
                f"₿: {btc_str}\n"
                f"Ξ: {eth_str}\n"
                f"H|L: ${round_significant(high_24h, 4)}|${round_significant(low_24h, 4)}\n"
                f"1h: {p_1h:.2f}% {get_emoji(p_1h) if p_1h is not None else ''}\n"
                f"24h: {p_24h:.2f}% {get_emoji(p_24h) if p_24h is not None else ''}\n"
                f"7d: {p_7d:.2f}% {get_emoji(p_7d) if p_7d is not None else ''}\n"
                f"Cap: #{rank} | ${market_cap_usd:,.0f}\n"
                f"FDV: ${fdv_usd:,.0f}\n"
                f"Vol: ${total_volume_usd:,.0f}"
            )
            await update.message.reply_text(output, parse_mode="Markdown")
            return

        # If markets returned empty, fallback to coins/{id}
        raise ValueError("markets endpoint returned empty list; fallback")
    except requests.exceptions.HTTPError as e:
        logger.warning("Markets endpoint HTTP error: %s", e)
    except Exception as e:
        logger.info("Falling back to detailed coin endpoint due to: %s", e)

    # Fallback detailed endpoint /coins/{id}
    try:
        url = f"{COINGECKO_API}/coins/{coin_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false"
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        market_data = data.get("market_data", {})

        current_price = market_data.get("current_price", {})
        price_usd = current_price.get("usd", 0)
        price_btc = current_price.get("btc", 0)
        price_eth = current_price.get("eth", 0)

        p_1h = market_data.get("price_change_percentage_1h_in_currency", {}).get("usd", None)
        p_24h = market_data.get("price_change_percentage_24h", None)
        p_7d = market_data.get("price_change_percentage_7d", None)

        high_24h = market_data.get("high_24h", {}).get("usd", 0)
        low_24h = market_data.get("low_24h", {}).get("usd", 0)

        market_cap_usd = market_data.get("market_cap", {}).get("usd", 0) or 0
        fdv_usd = market_data.get("fully_diluted_valuation", {}).get("usd", 0) or 0
        total_volume_usd = market_data.get("total_volume", {}).get("usd", 0) or 0
        rank = market_data.get("market_cap_rank", "N/A")

        def get_emoji(percentage):
            if percentage is None:
                return ""
            if percentage >= 5:
                return "🍻"
            if percentage > 0:
                return "😀"
            if percentage < 0:
                return "😔"
            return ""

        output = (
            f"*{ticker}*\n"
            f"${round_significant(price_usd, 4)}\n"
            f"₿: {round_significant(price_btc, 8)}\n"
            f"Ξ: {round_significant(price_eth, 8)}\n"
            f"H|L: ${round_significant(high_24h, 4)}|${round_significant(low_24h, 4)}\n"
            f"1h: {p_1h:.2f}% {get_emoji(p_1h)}\n"
            f"24h: {p_24h:.2f}% {get_emoji(p_24h)}\n"
            f"7d: {p_7d:.2f}% {get_emoji(p_7d)}\n"
            f"Cap: #{rank} | ${market_cap_usd:,.0f}\n"
            f"FDV: ${fdv_usd:,.0f}\n"
            f"Vol: ${total_volume_usd:,.0f}"
        )
        await update.message.reply_text(output, parse_mode="Markdown")
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status == 404:
            await update.message.reply_text(f"❌ Koin dengan ticker '{ticker}' tidak ditemukan.")
        else:
            logger.error("CoinGecko HTTP error: %s", e)
            await update.message.reply_text("Terjadi kesalahan API. Coba lagi nanti.")
    except Exception as e:
        logger.exception("Internal error in handle_price: %s", e)
        await update.message.reply_text("Terjadi kesalahan internal. Coba periksa format input Anda.")


async def handle_convert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cv [amount] [from] [to(optional=idr)]"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Format: /cv [Jumlah] [Koin Asal] [Koin Tujuan (opsional, default: IDR)]\n"
            "Contoh: /cv 1 btc idr atau /cv 1 btc usdt"
        )
        return

    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text("Jumlah harus berupa angka.")
        return

    from_ticker = args[1].lower()
    to_ticker = args[2].lower() if len(args) > 2 else "idr"

    from_id = get_coin_id(from_ticker)
    to_id = get_coin_id(to_ticker)

    try:
        resp = requests.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": from_id, "vs_currencies": to_id},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        price = data.get(from_id, {}).get(to_id, None)
        if price is None:
            await update.message.reply_text(
                f"❌ Tidak dapat mengkonversi {from_ticker.upper()} ke {to_ticker.upper()}. Pastikan kedua ticker valid."
            )
            return

        result = amount * price

        if to_ticker == "idr":
            result_formatted = f"Rp{result:,.0f}"
            amount_formatted = f"{amount:,.4f}"
        elif result < 1:
            result_formatted = round_significant(result, 6)
            amount_formatted = f"{amount:,.4f}"
        else:
            result_formatted = f"{result:,.2f}"
            amount_formatted = f"{amount:,.2f}"

        output = f"*{amount_formatted} {from_ticker.upper()}* sama dengan:\n*{result_formatted} {to_ticker.upper()}*"
        await update.message.reply_text(output, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error in handle_convert: %s", e)
        await update.message.reply_text("Terjadi kesalahan saat mengambil data konversi. Coba lagi.")


# ---------------- Admin handlers ----------------

async def handle_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/kick: kick user (reply to target message)."""
    if update.message.chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Perintah ini hanya dapat digunakan di dalam grup.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan pengguna yang ingin dikeluarkan (/kick).")
        return

    chat_id = update.effective_chat.id
    invoker = update.effective_user.id

    if not await is_user_admin(chat_id, invoker, context):
        await update.message.reply_text("❌ Anda harus menjadi Admin untuk menggunakan perintah ini.")
        return

    if not await is_bot_admin(chat_id, context):
        await update.message.reply_text("❌ Bot harus menjadi Admin dengan izin 'Ban Users' untuk melakukan tindakan ini.")
        return

    target_user = update.message.reply_to_message.from_user

    try:
        # Ban for short period to simulate kick (ban + unban)
        until_date = int(time.time()) + 60
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id, until_date=until_date)
        # quick unban so they can rejoin
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        await update.message.reply_text(f"👋 {target_user.full_name} telah dikeluarkan (Kick) dari grup.")
    except Exception as e:
        logger.exception("Error kicking user: %s", e)
        await update.message.reply_text("❌ Gagal mengeluarkan pengguna. Pastikan bot memiliki izin yang diperlukan.")


async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ban: permanently ban user (reply to target message)."""
    if update.message.chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Perintah ini hanya dapat digunakan di dalam grup.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan pengguna yang ingin dilarang (/ban).")
        return

    chat_id = update.effective_chat.id
    invoker = update.effective_user.id

    if not await is_user_admin(chat_id, invoker, context):
        await update.message.reply_text("❌ Anda harus menjadi Admin untuk menggunakan perintah ini.")
        return

    if not await is_bot_admin(chat_id, context):
        await update.message.reply_text("❌ Bot harus menjadi Admin dengan izin 'Ban Users' untuk melakukan tindakan ini.")
        return

    target_user = update.message.reply_to_message.from_user

    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
        await update.message.reply_text(f"🔨 {target_user.full_name} telah dilarang (Ban) dari grup secara permanen.")
    except Exception as e:
        logger.exception("Error banning user: %s", e)
        await update.message.reply_text("❌ Gagal melarang pengguna. Pastikan bot memiliki izin yang diperlukan.")


async def handle_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mute [<time>] - mute user reply target. Default 1 hour. Accepts formats: 10m, 2h, 1d"""
    if update.message.chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Perintah ini hanya dapat digunakan di dalam grup.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan pengguna yang ingin dibisukan (/mute [menit/jam/hari], default 1h).")
        return

    chat_id = update.effective_chat.id
    invoker = update.effective_user.id

    if not await is_user_admin(chat_id, invoker, context):
        await update.message.reply_text("❌ Anda harus menjadi Admin untuk menggunakan perintah ini.")
        return

    if not await is_bot_admin(chat_id, context):
        await update.message.reply_text("❌ Bot harus menjadi Admin dengan izin 'Restrict Members' untuk melakukan tindakan ini.")
        return

    target_user = update.message.reply_to_message.from_user

    # default 1 hour
    mute_seconds = 3600
    duration_text = "1 jam"

    if context.args:
        ts = context.args[0].lower()
        try:
            if ts.endswith("m"):
                minutes = int(ts[:-1])
                mute_seconds = max(60, minutes * 60)
                duration_text = f"{minutes} menit"
            elif ts.endswith("h"):
                hours = int(ts[:-1])
                mute_seconds = max(60, hours * 3600)
                duration_text = f"{hours} jam"
            elif ts.endswith("d"):
                days = int(ts[:-1])
                mute_seconds = max(60, days * 86400)
                duration_text = f"{days} hari"
            else:
                # If just a number, assume minutes
                minutes = int(ts)
                mute_seconds = max(60, minutes * 60)
                duration_text = f"{minutes} menit"
        except Exception:
            await update.message.reply_text("Format waktu tidak dikenali. Gunakan contoh: 10m, 2h, 1d atau /mute untuk default 1 jam.")
            return

    permissions = {
        "can_send_messages": False,
        "can_send_media_messages": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": False,
        "can_pin_messages": False,
    }

    try:
        until_date = int(time.time()) + mute_seconds
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=permissions,
            until_date=until_date
        )
        await update.message.reply_text(f"🔇 {target_user.full_name} telah dibisukan selama {duration_text}.")
    except Exception as e:
        logger.exception("Error muting user: %s", e)
        await update.message.reply_text("❌ Gagal membisukan pengguna. Pastikan bot memiliki izin yang diperlukan.")


# --- Webhook endpoint for Telegram (FastAPI) ---
@app.post("/webhook/{token}")
async def telegram_webhook(token: str, raw_update: dict):
    """Webhook path: /webhook/{TOKEN}.
    NOTE: Keep this path secret (use your bot token). Example for Choreo or other platform:
      - Set webhook: https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<your-app>/webhook/<TELEGRAM_BOT_TOKEN>
    """
    if token != (TOKEN or ""):
        logger.warning("Webhook called with invalid token in path.")
        return {"message": "Invalid token"}

    if not raw_update:
        return {"message": "No update received"}

    if application is None:
        logger.error("Application is not initialized. Cannot process update.")
        return {"message": "Bot not ready"}

    try:
        update = Update.de_json(raw_update, application.bot)
        await application.process_update(update)
        return {"message": "OK"}
    except Exception as e:
        logger.exception("Failed to process update: %s", e)
        return {"message": "Error processing update"}


# --- Initialization ---
def initialize_bot() -> Optional[Application]:
    """Initialize the Telegram Application and register handlers.
    Returns Application instance or None if TOKEN missing."""
    global application

    if not TOKEN:
        logger.error("Initialization failed: TELEGRAM_BOT_TOKEN not set.")
        application = None
        return None

    app_obj = Application.builder().token(TOKEN).build()

    # Register handlers
    app_obj.add_handler(CommandHandler("p", handle_price))
    app_obj.add_handler(CommandHandler("cv", handle_convert))
    app_obj.add_handler(CommandHandler("kick", handle_kick))
    app_obj.add_handler(CommandHandler("ban", handle_ban))
    app_obj.add_handler(CommandHandler("mute", handle_mute))

    # initialize (prepare internal resources)
    app_obj.initialize()
    logger.info("Telegram Application initialized and handlers registered.")
    application = app_obj
    return application


# Run initialization at import time (so webhook endpoint can use application)
application = initialize_bot()


if __name__ == "__main__":
    if TOKEN is None:
        logger.error("TELEGRAM_BOT_TOKEN tidak ditemukan. Set environment variable dan jalankan ulang.")
    else:
        PORT = int(os.environ.get("PORT", 8080))
        logger.info("Starting Uvicorn on 0.0.0.0:%s ...", PORT)
        # NOTE: In production use the ASGI server recommended by your host (uvicorn is fine)
        uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
