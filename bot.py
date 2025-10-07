import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from math import log10, floor

# Konfigurasi Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Atur TOKEN bot Telegram Anda di sini
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN" 

# URL Dasar CoinGecko API (Versi Gratis)
COINGECKO_API = "https://api.coingecko.com/api/v3"

# --- Fungsi Pembantu ---

# Untuk membulatkan angka desimal, agar tidak terlalu panjang
def round_significant(x, sig=4):
    """Membulatkan angka ke sejumlah angka penting tertentu."""
    if x == 0:
        return 0
    return round(x, sig - int(floor(log10(abs(x)))) - 1)

def get_coin_id(ticker):
    """Fungsi sederhana untuk memetakan ticker/simbol ke CoinGecko ID.
    API CoinGecko menggunakan ID (misal: 'bitcoin') bukan ticker (misal: 'BTC').
    Untuk bot yang lebih kompleks, gunakan endpoint /coins/list.
    """
    # Mengambil ID untuk IDR, BTC, dan USDT
    if ticker.lower() == 'idr': return 'idr'
    if ticker.lower() == 'btc': return 'bitcoin'
    if ticker.lower() == 'eth': return 'ethereum'
    if ticker.lower() == 'usdt': return 'tether'
    
    # Asumsi: Untuk ticker lain, CoinGecko ID adalah nama lowercase-nya.
    # Contoh: 'ENA' -> 'ena'
    return ticker.lower()

# --- Handler Perintah /p (Harga Kripto Detail) ---

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan detail harga kripto."""
    
    if not context.args:
        await update.message.reply_text("Format: /p [Ticker Kripto]. Contoh: /p ENA")
        return

    # Ambil ticker dari argumen
    ticker = context.args[0].upper()
    coin_id = get_coin_id(ticker)

    try:
        # Panggil CoinGecko API: /coins/{id}
        url = f"{COINGECKO_API}/coins/{coin_id}"
        params = {
            'localization': 'false',
            'tickers': 'false',
            'market_data': 'true',
            'community_data': 'false',
            'developer_data': 'false',
            'sparkline': 'false'
        }
        response = requests.get(url, params=params)
        response.raise_for_status() # Cek error HTTP
        data = response.json()
        
        # Ambil data yang dibutuhkan
        market_data = data.get('market_data', {})
        current_price = market_data.get('current_price', {})
        
        # Cek apakah data tersedia
        if not current_price:
            await update.message.reply_text(f"❌ Data untuk {ticker} tidak ditemukan.")
            return

        # --- Formatting Data ---
        
        # Harga
        price_usd = current_price.get('usd', 0)
        price_btc = current_price.get('btc', 0)
        price_eth = current_price.get('eth', 0)
        
        # Perubahan
        p_1h = market_data.get('price_change_percentage_1h_in_currency', {}).get('usd', 0)
        p_24h = market_data.get('price_change_percentage_24h', 0)
        p_7d = market_data.get('price_change_percentage_7d', 0)
        
        # High/Low
        high_24h = market_data.get('high_24h', {}).get('usd', 0)
        low_24h = market_data.get('low_24h', {}).get('usd', 0)
        
        # Cap
        market_cap_usd = market_data.get('market_cap', {}).get('usd', 0)
        fdv_usd = market_data.get('fully_diluted_valuation', {}).get('usd', 0)
        total_volume_usd = market_data.get('total_volume', {}).get('usd', 0)
        rank = market_data.get('market_cap_rank', 'N/A')

        # Fungsi emoji
        def get_emoji(percentage):
            if percentage is None: return ''
            if percentage >= 5: return '🍻'
            if percentage > 0: return '😀'
            if percentage < 0: return '😔'
            return ''

        # Format output string
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
        
    except requests.exceptions.RequestException as e:
        logging.error(f"CoinGecko API Error: {e}")
        await update.message.reply_text(f"Terjadi kesalahan saat mengambil data untuk {ticker}. Coba lagi.")
    except Exception as e:
        logging.error(f"Internal Error: {e}")
        await update.message.reply_text("Terjadi kesalahan internal. Coba periksa kembali format input Anda.")

# --- Handler Perintah /cv (Konversi Kripto) ---

async def handle_convert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengkonversi nilai kripto."""

    args = context.args
    # Format: /cv [jumlah] [koin_asal] [koin_tujuan/idr]
    if len(args) < 2:
        await update.message.reply_text("Format: /cv [Jumlah] [Koin Asal] [Koin Tujuan (opsional, default: IDR)]\nContoh: /cv 1 btc idr atau /cv 1 btc usdt")
        return

    try:
        amount = float(args[0])
        from_ticker = args[1].lower()
        to_ticker = args[2].lower() if len(args) > 2 else 'idr' # Default ke IDR
        
    except ValueError:
        await update.message.reply_text("Jumlah harus berupa angka.")
        return

    from_id = get_coin_id(from_ticker)
    to_id = get_coin_id(to_ticker)

    # API CoinGecko menggunakan simple/price untuk konversi cepat
    url = f"{COINGECKO_API}/simple/price"
    params = {
        'ids': from_id,
        'vs_currencies': to_id
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Ambil harga 1 koin asal dalam koin tujuan
        price = data.get(from_id, {}).get(to_id, None)

        if price is None:
            await update.message.reply_text(f"❌ Tidak dapat mengkonversi {from_ticker.upper()} ke {to_ticker.upper()}. Pastikan kedua ticker valid.")
            return

        result = amount * price
        
        # Formatting hasil
        if to_ticker == 'idr':
            result_formatted = f"Rp{result:,.0f}"
        elif result < 1:
            result_formatted = f"{round_significant(result, 6)}"
        else:
            result_formatted = f"{result:,.2f}"

        output = (
            f"*{amount:,.4f} {from_ticker.upper()}* sama dengan:\n"
            f"*{result_formatted} {to_ticker.upper()}*"
        )
        
        await update.message.reply_text(output, parse_mode="Markdown")

    except requests.exceptions.RequestException as e:
        logging.error(f"CoinGecko API Error: {e}")
        await update.message.reply_text("Terjadi kesalahan saat mengambil data konversi. Coba lagi.")

# --- Main Function ---

def main() -> None:
    """Menjalankan bot."""
    # Buat Aplikasi
    application = Application.builder().token(TOKEN).build()

    # Daftarkan Handlers Perintah
    application.add_handler(CommandHandler("p", handle_price))
    application.add_handler(CommandHandler("cv", handle_convert))

    # Mulai Bot
    logging.info("Bot sedang berjalan...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
