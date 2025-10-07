import logging
import requests
import os
import uvicorn
import time
from math import log10, floor

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI

# --- Konfigurasi Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- Konfigurasi Awal ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
COINGECKO_API = "https://api.coingecko.com/api/v3"

application = None  # Global app Telegram
app = FastAPI()     # Webhook FastAPI

# --- Fungsi Pembantu ---
def round_significant(x, sig=4):
    """Membulatkan angka ke sejumlah angka penting tertentu."""
    if x == 0:
        return 0
    if abs(x) < 1e-10:
        return f"{x:.8f}"
    return round(x, sig - int(floor(log10(abs(x)))) - 1)

def get_coin_id(ticker):
    """Map ticker ke CoinGecko ID."""
    mapping = {
        "idr": "idr",
        "btc": "bitcoin",
        "eth": "ethereum",
        "usdt": "tether"
    }
    return mapping.get(ticker.lower(), ticker.lower())

# --- Handler: /p (Price Info) ---
async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: /p [Ticker]. Contoh: /p ENA")
        return

    ticker = context.args[0].upper()
    coin_id = get_coin_id(ticker)

    try:
        url = f"{COINGECKO_API}/coins/{coin_id}"
        params = {
            'localization': 'false',
            'tickers': 'false',
            'market_data': 'true',
            'community_data': 'false',
            'developer_data': 'false',
            'sparkline': 'false'
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        market_data = data.get('market_data', {})
        current_price = market_data.get('current_price', {})

        if not current_price:
            await update.message.reply_text(f"❌ Data untuk {ticker} tidak ditemukan.")
            return

        price_usd = current_price.get('usd', 0)
        price_btc = current_price.get('btc', 0)
        price_eth = current_price.get('eth', 0)
        p_1h = market_data.get('price_change_percentage_1h_in_currency', {}).get('usd', 0)
        p_24h = market_data.get('price_change_percentage_24h', 0)
        p_7d = market_data.get('price_change_percentage_7d', 0)
        high_24h = market_data.get('high_24h', {}).get('usd', 0)
        low_24h = market_data.get('low_24h', {}).get('usd', 0)
        market_cap_usd = market_data.get('market_cap', {}).get('usd', 0)
        fdv_usd = market_data.get('fully_diluted_valuation', {}).get('usd', 0)
        total_volume_usd = market_data.get('total_volume', {}).get('usd', 0)
        rank = market_data.get('market_cap_rank', 'N/A')

        def emoji(p):
            if p is None or p == 0: return ''
            if p >= 5: return '🍻'
            if p > 0: return '😀'
            if p < 0: return '😔'
            return ''

        text = (
            f"*{ticker}*\n"
            f"${round_significant(price_usd, 4):,}\n"
            f"₿ {round_significant(price_btc, 8)} | Ξ {round_significant(price_eth, 8)}\n"
            f"H|L: ${round_significant(high_24h, 2):,}|${round_significant(low_24h, 2):,}\n"
            f"1h: {p_1h:.2f}% {emoji(p_1h)}\n"
            f"24h: {p_24h:.2f}% {emoji(p_24h)}\n"
            f"7d: {p_7d:.2f}% {emoji(p_7d)}\n"
            f"Cap: #{rank} | ${market_cap_usd:,.0f}\n"
            f"FDV: ${fdv_usd:,.0f}\n"
            f"Vol: ${total_volume_usd:,.0f}"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            await update.message.reply_text(f"❌ Koin '{ticker}' tidak ditemukan.")
        else:
            logging.error(e)
            await update.message.reply_text("❌ Kesalahan API CoinGecko.")
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("❌ Terjadi kesalahan internal.")

# --- Handler: /cv (Convert) ---
async def handle_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Format: /cv [Jumlah] [Koin Asal] [Koin Tujuan (opsional)]\nContoh: /cv 1 btc idr")
        return
    try:
        amount = float(args[0])
        from_ticker = args[1].lower()
        to_ticker = args[2].lower() if len(args) > 2 else 'idr'
    except ValueError:
        await update.message.reply_text("Jumlah harus berupa angka.")
        return

    url = f"{COINGECKO_API}/simple/price"
    params = {'ids': get_coin_id(from_ticker), 'vs_currencies': get_coin_id(to_ticker)}

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        price = data.get(get_coin_id(from_ticker), {}).get(get_coin_id(to_ticker))
        if not price:
            await update.message.reply_text("❌ Gagal konversi, pastikan ticker benar.")
            return

        result = amount * price
        if to_ticker == 'idr':
            res_fmt = f"Rp{result:,.0f}"
        elif result < 1:
            res_fmt = str(round_significant(result, 6))
        else:
            res_fmt = f"{result:,.2f}"

        text = f"*{amount} {from_ticker.upper()}* = *{res_fmt} {to_ticker.upper()}*"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("❌ Terjadi kesalahan saat konversi.")

# --- Handler Admin Commands (/kick, /ban, /mute) ---
async def handle_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Gunakan di grup.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan user untuk /kick.")
        return
    admin = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if admin.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Hanya admin bisa /kick.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id, until_date=int(time.time()) + 60)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"👋 {target.full_name} telah dikeluarkan.")
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("❌ Gagal /kick user.")

async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Gunakan di grup.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan user untuk /ban.")
        return
    admin = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if admin.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Hanya admin bisa /ban.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🔨 {target.full_name} diban permanen.")
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("❌ Gagal /ban user.")

async def handle_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Gunakan di grup.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan user untuk /mute [durasi, contoh: 30m / 1h / 1d].")
        return
    admin = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if admin.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Hanya admin bisa /mute.")
        return

    target = update.message.reply_to_message.from_user
    duration = 3600
    text_dur = "1 jam"
    if context.args:
        try:
            t = context.args[0].lower()
            if 'm' in t: duration, text_dur = int(t.replace('m', '')) * 60, f"{int(t.replace('m', ''))} menit"
            elif 'h' in t: duration, text_dur = int(t.replace('h', '')) * 3600, f"{int(t.replace('h', ''))} jam"
            elif 'd' in t: duration, text_dur = int(t.replace('d', '')) * 86400, f"{int(t.replace('d', ''))} hari"
        except: pass

    perms = {
        "can_send_messages": False, "can_send_media_messages": False,
        "can_send_polls": False, "can_send_other_messages": False,
        "can_add_web_page_previews": False
    }

    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, permissions=perms, until_date=int(time.time()) + duration)
        await update.message.reply_text(f"🔇 {target.full_name} dibisukan selama {text_dur}.")
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("❌ Gagal /mute user.")

# --- FastAPI Webhook Endpoint ---
@app.post("/")
async def telegram_webhook(raw_update: dict):
    if not raw_update:
        return {"message": "No update"}
    if application is None:
        return {"message": "Bot not ready"}
    update = Update.de_json(raw_update, application.bot)
    await application.process_update(update)
    return {"message": "OK"}

# --- Inisialisasi Bot Telegram ---
def initialize_bot():
    global application
    if not TOKEN:
        logging.error("TOKEN tidak ditemukan.")
        return Application.builder().token("INVALID").build()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("p", handle_price))
    application.add_handler(CommandHandler("cv", handle_convert))
    application.add_handler(CommandHandler("kick", handle_kick))
    application.add_handler(CommandHandler("ban", handle_ban))
    application.add_handler(CommandHandler("mute", handle_mute))
    application.initialize()
    logging.info("Bot siap menerima webhook.")
    return application

application = initialize_bot()

# --- Entry Point ---
if __name__ == "__main__":
    if TOKEN is None:
        logging.error("Tidak dapat menjalankan server: TELEGRAM_BOT_TOKEN tidak disetel.")
    else:
        PORT = int(os.environ.get("PORT", 8080))
        logging.info(f"Menjalankan server di port {PORT}...")
        uvicorn.run(app, host="0.0.0.0", port=PORT)
