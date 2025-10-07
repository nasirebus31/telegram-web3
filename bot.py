import logging
import requests
import os
import uvicorn
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
if not TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN environment variable is missing. Bot cannot start.")

# URL Dasar CoinGecko API (Versi Gratis)
COINGECKO_API = "https://api.coingecko.com/api/v3"

# Inisialisasi Aplikasi Telegram secara global untuk digunakan oleh Webhook
application = Application.builder().token(TOKEN).build()
# Inisialisasi FastAPI untuk menerima Webhook
app = FastAPI()


# --- Fungsi Pembantu ---

def round_significant(x, sig=4):
    """Membulatkan angka ke sejumlah angka penting tertentu."""
    if x == 0:
        return 0
    # Mengatasi kasus float kecil
    if abs(x) < 1e-10:
        return f"{x:.8f}"
    
    return round(x, sig - int(floor(log10(abs(x)))) - 1)

def get_coin_id(ticker):
    """Fungsi sederhana untuk memetakan ticker/simbol ke CoinGecko ID."""
    # Mapping IDR, BTC, ETH, USDT
    if ticker.lower() == 'idr': return 'idr'
    if ticker.lower() == 'btc': return 'bitcoin'
    if ticker.lower() == 'eth': return 'ethereum'
    if ticker.lower() == 'usdt': return 'tether'
    
    # Asumsi: Untuk ticker lain, CoinGecko ID adalah nama lowercase-nya.
    return ticker.lower()

# --- Handler Perintah /p (Harga Kripto Detail) ---

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan detail harga kripto."""
    
    if not context.args:
        await update.message.reply_text("Format: /p [Ticker Kripto]. Contoh: /p ENA")
        return

    ticker = context.args[0].upper()
    coin_id = get_coin_id(ticker)

    try:
        # Panggil CoinGecko API: /coins/{id}
        url = f"{COINGECKO_API}/coins/{coin_id}"
        # Minta data market spesifik yang dibutuhkan
        params = {
            'localization': 'false',
            'tickers': 'false',
            'market_data': 'true',
            'community_data': 'false',
            'developer_data': 'false',
            'sparkline': 'false'
        }
        response = requests.get(url, params=params, timeout=10) # Tambahkan timeout
        response.raise_for_status()
        data = response.json()
        
        market_data = data.get('market_data', {})
        current_price = market_data.get('current_price', {})
        
        if not current_price:
            await update.message.reply_text(f"❌ Data untuk {ticker} tidak ditemukan. Cek apakah ticker tersebut benar di CoinGecko.")
            return

        # --- Formatting Data ---
        
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

        # Format output string sesuai permintaan
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
    """Mengkonversi nilai kripto."""

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
        
        # Formatting hasil
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

# --- Fungsi Webhook untuk FastAPI ---

# Fungsi untuk menerima POST request dari Telegram
@app.post("/")
async def telegram_webhook(raw_update: dict):
    """Menerima dan memproses Webhook dari Telegram."""
    if not raw_update:
        return {"message": "No update received"}
        
    # Mengkonversi dictionary mentah menjadi objek Update
    update = Update.de_json(raw_update, application.bot)
    
    # Memasukkan Update ke dalam antrian untuk diproses oleh Handlers
    await application.process_update(update)
    
    return {"message": "OK"}


# --- Fungsi Utama Bot & Server Startup ---

def initialize_bot():
    """Menginisialisasi Handlers sebelum server Webhook dijalankan."""
    
    if not TOKEN:
        logging.error("Inisialisasi bot gagal: TOKEN tidak ditemukan.")
        return False
    
    # Daftarkan Handlers Perintah
    application.add_handler(CommandHandler("p", handle_price))
    application.add_handler(CommandHandler("cv", handle_convert))
    
    # Inisialisasi proses update (harus dilakukan sebelum menerima Webhook)
    # Ini memastikan semua handlers dimuat
    application.initialize()
    logging.info("Handlers Telegram dimuat dan bot siap menerima Webhook.")
    return True

# Jalankan inisialisasi handlers
if not initialize_bot():
    logging.error("Gagal memulai bot.")


if __name__ == "__main__":
    # Fungsi main hanya digunakan saat dijalankan secara lokal (opsional)
    # Di Choreo, server Webhook (uvicorn) akan dijalankan melalui Procfile
    
    PORT = int(os.environ.get("PORT", 8080))
    logging.info(f"Menjalankan server Uvicorn di port {PORT}...")
    
    # Uvicorn harus dijalankan melalui Procfile di Choreo, tapi ini adalah fallback lokal
    uvicorn.run(app, host="0.0.0.0", port=PORT)
