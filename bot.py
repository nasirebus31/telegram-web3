import logging
import requests
import os
import uvicorn
import time  # <--- IMPORT BARU UNTUK FITUR ADMIN
from math import log10, floor

# Import dari library python-telegram-bot dan FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI

# --- Konfigurasi Awal ---

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Ambil Token dari Environment Variable (Wajib untuk Hosting seperti Choreo)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
# Penghapusan pengecekan TOKEN di sini; dipindahkan ke initialize_bot
# URL Dasar CoinGecko API (Versi Gratis)
COINGECKO_API = "https://api.coingecko.com/api/v3"

# Inisialisasi Aplikasi Telegram secara global (dengan penanganan TOKEN di initialize_bot)
# Inisialisasi awal harus dilakukan di dalam initialize_bot jika TOKEN bisa None
application = None 
# Inisialisasi FastAPI untuk menerima Webhook
app = FastAPI()


# --- Fungsi Pembantu ---

def round_significant(x, sig=4):
    """Membulatkan angka ke sejumlah angka penting tertentu."""
    if x == 0:
        return 0
    if abs(x) < 1e-10:
        return f"{x:.8f}"
    
    return round(x, sig - int(floor(log10(abs(x)))) - 1)

def get_coin_id(ticker):
    """Fungsi sederhana untuk memetakan ticker/simbol ke CoinGecko ID."""
    if ticker.lower() == 'idr': return 'idr'
    if ticker.lower() == 'btc': return 'bitcoin'
    if ticker.lower() == 'eth': return 'ethereum'
    if ticker.lower() == 'usdt': return 'tether'
    
    return ticker.lower()

# --- Handler Perintah /p (Harga Kripto Detail) ---

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (Isi handle_price, kode sudah benar) ...
    if not context.args:
        await update.message.reply_text("Format: /p [Ticker Kripto]. Contoh: /p ENA")
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
            await update.message.reply_text(f"❌ Data untuk {ticker} tidak ditemukan. Cek apakah ticker tersebut benar di CoinGecko.")
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

        def get_emoji(percentage):
            if percentage is None or percentage == 0: return ''
            if percentage >= 5: return '🍻'
            if percentage > 0: return '😀'
            if percentage < 0: return '😔'
            return ''

        output = (
            f"*{ticker}*\n"
            f"${round_significant(price_usd, 4):,}\n"
            f"₿: {round_significant(price_btc, 8)}\n"
            f"Ξ: {round_significant(price_eth, 8)}\n"
            f"H|L: ${round_significant(high_24h, 2):,}|${round_significant(low_24h, 2):,}\n"
            f"1h: {p_1h:.2f}% {get_emoji(p_1h)}\n"
            f"24h: {p_24h:.2f}% {get_emoji(p_24h)}\n"
            f"7d: {p_7d:.2f}% {get_emoji(p_7d)}\n"
            f"Cap: #{rank} | ${market_cap_usd:,.0f}\n"
            f"FDV: ${fdv_usd:,.0f}\n"
            f"Vol: ${total_volume_usd:,.0f}"
        )
        
        await update.message.reply_text(output, parse_mode="Markdown")
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            await update.message.reply_text(f"❌ Koin dengan ticker '{ticker}' tidak ditemukan.")
        else:
            logging.error(f"CoinGecko API HTTP Error: {e}")
            await update.message.reply_text("Terjadi kesalahan API. Coba lagi.")
    except Exception as e:
        logging.error(f"Internal Error: {e}")
        await update.message.reply_text("Terjadi kesalahan internal. Coba periksa format input Anda.")

# --- Handler Perintah /cv (Konversi Kripto) ---

async def handle_convert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (Isi handle_convert, kode sudah benar) ...
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Format: /cv [Jumlah] [Koin Asal] [Koin Tujuan (opsional, default: IDR)]\nContoh: /cv 1 btc idr atau /cv 1 btc usdt")
        return

    try:
        amount = float(args[0])
        from_ticker = args[1].lower()
        to_ticker = args[2].lower() if len(args) > 2 else 'idr'
        
    except ValueError:
        await update.message.reply_text("Jumlah harus berupa angka.")
        return

    from_id = get_coin_id(from_ticker)
    to_id = get_coin_id(to_ticker)

    url = f"{COINGECKO_API}/simple/price"
    params = {
        'ids': from_id,
        'vs_currencies': to_id
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        price = data.get(from_id, {}).get(to_id, None)

        if price is None:
            await update.message.reply_text(f"❌ Tidak dapat mengkonversi {from_ticker.upper()} ke {to_ticker.upper()}. Pastikan kedua ticker valid.")
            return

        result = amount * price
        
        if to_ticker == 'idr':
            result_formatted = f"Rp{result:,.0f}"
            amount_formatted = f"{amount:,.4f}"
        elif result < 1:
            result_formatted = f"{round_significant(result, 6)}"
            amount_formatted = f"{amount:,.4f}"
        else:
            result_formatted = f"{result:,.2f}"
            amount_formatted = f"{amount:,.2f}"

        output = (
            f"*{amount_formatted} {from_ticker.upper()}* sama dengan:\n"
            f"*{result_formatted} {to_ticker.upper()}*"
        )
        
        await update.message.reply_text(output, parse_mode="Markdown")

    except requests.exceptions.RequestException as e:
        logging.error(f"CoinGecko API Error: {e}")
        await update.message.reply_text("Terjadi kesalahan saat mengambil data konversi. Coba lagi.")

# ----------------------------------------------------------------------
# >>> FUNGSI ADMIN BARU DITAMBAHKAN DI SINI <<<
# ----------------------------------------------------------------------

# --- Handler Perintah /kick ---

async def handle_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengeluarkan (kick) pengguna dari grup."""
    if update.message.chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Perintah ini hanya dapat digunakan di dalam grup.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan pengguna yang ingin dikeluarkan (/kick).")
        return

    # Cek Admin
    admin_status = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if admin_status.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Anda harus menjadi Admin untuk menggunakan perintah ini.")
        return

    target_user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id

    try:
        # Ban sementara (ban + unban cepat) untuk 'kick'
        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            until_date=int(time.time()) + 60 # Ban 60 detik
        )
        # Unban agar bisa bergabung kembali
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        await update.message.reply_text(f"👋 {target_user.full_name} telah dikeluarkan (Kick) dari grup.")
    except Exception as e:
        logging.error(f"Error kicking user: {e}")
        await update.message.reply_text("❌ Gagal mengeluarkan pengguna. Pastikan bot adalah Admin dengan izin 'Ban Users'.")


# --- Handler Perintah /ban ---

async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Melarang (ban) pengguna secara permanen dari grup."""
    if update.message.chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Perintah ini hanya dapat digunakan di dalam grup.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan pengguna yang ingin dilarang (/ban).")
        return

    # Cek Admin
    admin_status = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if admin_status.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Anda harus menjadi Admin untuk menggunakan perintah ini.")
        return

    target_user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id

    try:
        # Melarang pengguna secara permanen (tanpa until_date)
        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_user.id
        )
        await update.message.reply_text(f"🔨 {target_user.full_name} telah dilarang (Ban) dari grup secara permanen.")
    except Exception as e:
        logging.error(f"Error banning user: {e}")
        await update.message.reply_text("❌ Gagal melarang pengguna. Pastikan bot adalah Admin dengan izin 'Ban Users'.")


# --- Handler Perintah /mute ---

async def handle_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Membisukan (mute) pengguna untuk waktu tertentu (default 1 jam)."""
    if update.message.chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Perintah ini hanya dapat digunakan di dalam grup.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Balas pesan pengguna yang ingin dibisukan (/mute [menit/jam/hari], default 1 jam).")
        return

    # Cek Admin
    admin_status = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if admin_status.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Anda harus menjadi Admin untuk menggunakan perintah ini.")
        return
        
    target_user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    
    mute_duration_seconds = 3600 
    duration_text = "1 jam"
    
    if context.args:
        try:
            time_str = context.args[0].lower()
            if 'm' in time_str:
                minutes = int(time_str.replace('m', ''))
                mute_duration_seconds = minutes * 60
                duration_text = f"{minutes} menit"
            elif 'h' in time_str:
                hours = int(time_str.replace('h', ''))
                mute_duration_seconds = hours * 3600
                duration_text = f"{hours} jam"
            elif 'd' in time_str:
                days = int(time_str.replace('d', ''))
                mute_duration_seconds = days * 86400
                duration_text = f"{days} hari"
        except ValueError:
            pass 

    permissions = {
        "can_send_messages": False, "can_send_media_messages": False,
        "can_send_polls": False, "can_send_other_messages": False,
        "can_add_web_page_previews": False, "can_change_info": False,
        "can_invite_users": False, "can_pin_messages": False,
    }

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=permissions,
            until_date=int(time.time()) + mute_duration_seconds 
        )
        await update.message.reply_text(f"🔇 {target_user.full_name} telah dibisukan selama {duration_text}.")
    except Exception as e:
        logging.error(f"Error muting user: {e}")
        await update.message.reply_text("❌ Gagal membisukan pengguna. Pastikan bot adalah Admin dengan izin 'Restrict Users'.")

# ----------------------------------------------------------------------
# >>> AKHIR FUNGSI ADMIN BARU <<<
# ----------------------------------------------------------------------


# --- Fungsi Webhook untuk FastAPI ---

@app.post("/")
async def telegram_webhook(raw_update: dict):
    """Menerima dan memproses Webhook dari Telegram."""
    if not raw_update:
        return {"message": "No update received"}
    
    # Cek apakah aplikasi sudah diinisialisasi
    if application is None:
        logging.error("Application is not initialized. Cannot process update.")
        return {"message": "Bot not ready"}
        
    update = Update.de_json(raw_update, application.bot)
    
    await application.process_update(update)
    
    return {"message": "OK"}


# --- Fungsi Utama Bot & Server Startup ---

def initialize_bot():
    """Menginisialisasi Handlers dan Application (dengan penanganan token)."""
    global application # Gunakan variabel global application

    if not TOKEN:
        logging.error("Inisialisasi bot gagal: TOKEN tidak ditemukan. Bot tidak akan berjalan.")
        # Mengembalikan objek Application yang tidak akan berfungsi jika TOKEN None
        return Application.builder().token("INVALID_TOKEN").build() 
        
    # Inisialisasi Aplikasi Telegram
    application = Application.builder().token(TOKEN).build()
    
    # Daftarkan Handlers Perintah Kripto
    application.add_handler(CommandHandler("p", handle_price))
    application.add_handler(CommandHandler("cv", handle_convert))
    
    # Daftarkan Handlers Perintah Admin
    application.add_handler(CommandHandler("kick", handle_kick))
    application.add_handler(CommandHandler("ban", handle_ban))
    application.add_handler(CommandHandler("mute", handle_mute))
    
    # Inisialisasi proses update
    application.initialize()
    logging.info("Handlers Telegram dimuat dan bot siap menerima Webhook.")
    return application

# Jalankan inisialisasi handlers dan simpan referensi
application = initialize_bot()


if __name__ == "__main__":
    if TOKEN is None:
        # Jika TOKEN tidak ada, jangan coba jalankan uvicorn karena pasti gagal
        logging.error("Tidak dapat menjalankan server: TELEGRAM_BOT_TOKEN tidak disetel.")
    else:
        PORT = int(os.environ.get("PORT", 8080))
        logging.info(f"Menjalankan server Uvicorn di port {PORT}...")
        
        # Jalankan server Webhook (FastAPI/Uvicorn)
        uvicorn.run(app, host="0.0.0.0", port=PORT)
