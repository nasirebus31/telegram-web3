from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests
from bs4 import BeautifulSoup
import locale

# Set number formatting locale (Indonesian)
locale.setlocale(locale.LC_ALL, 'id_ID.UTF-8')

TOKEN = os.getenv("TOKEN")

# 🔗 Telegram web links you want to pull text from
LINKS = {
    "alpha": "https://t.me/Retroactive_Indonesia/7556"  # <-- replace with your Telegram web link
}

# === /p command (crypto info) ===
def get_price_data(symbol):
    url = f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}"
    res = requests.get(url).json()

    price_usd = res["market_data"]["current_price"]["usd"]
    price_btc = res["market_data"]["current_price"]["btc"]
    price_eth = res["market_data"]["current_price"]["eth"]

    high_24h = res["market_data"]["high_24h"]["usd"]
    low_24h = res["market_data"]["low_24h"]["usd"]
    change_1h = res["market_data"]["price_change_percentage_1h_in_currency"]["usd"]
    change_24h = res["market_data"]["price_change_percentage_24h_in_currency"]["usd"]
    change_7d = res["market_data"]["price_change_percentage_7d_in_currency"]["usd"]

    cap = res["market_data"]["market_cap"]["usd"]
    fdv = res["market_data"]["fully_diluted_valuation"]["usd"]
    vol = res["market_data"]["total_volume"]["usd"]

    return f"""
<b>{symbol.upper()}</b>
${price_usd:.2f} | {price_btc:.8f}₿
Ξ {price_eth:.8f}

H | L: {high_24h:.2f} | {low_24h:.2f}
1h {change_1h:+.2f}% 😐
24h {change_24h:+.2f}% 💰
7d {change_7d:+.2f}% 🌕
Cap: ${cap/1e6:.1f}M
FDV: ${fdv/1e6:.1f}M
Vol: ${vol/1e6:.1f}M
"""

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /p <symbol>", parse_mode="HTML")
        return
    symbol = context.args[0]
    try:
        data = get_price_data(symbol)
        await update.message.reply_text(data, parse_mode="HTML")
    except Exception:
        await update.message.reply_text("⚠️ Gagal mengambil data.")

# === /cv command (convert to IDR) ===
async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /cv <jumlah> <symbol>\nContoh: /cv 1 btc")
        return
    try:
        amount = float(context.args[0])
        symbol = context.args[1].lower()
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=idr"
        res = requests.get(url).json()
        price_idr = res[symbol]["idr"]
        total = amount * price_idr
        formatted = locale.format_string("%0.2f", total, grouping=True)
        await update.message.reply_text(f"{amount} {symbol.upper()} = {formatted} IDR")
    except Exception:
        await update.message.reply_text("⚠️ Format salah atau simbol tidak ditemukan.")

# === /alpha command (fetch Telegram link text) ===
async def alpha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = LINKS.get("alpha")
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        # get latest text message from Telegram web page
        messages = soup.find_all("div", class_="tgme_widget_message_text")
        if not messages:
            await update.message.reply_text("⚠️ Tidak ada pesan ditemukan.")
            return

        latest_message = messages[-1].get_text(separator="\n")
        await update.message.reply_text(latest_message)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Gagal mengambil data dari link.\n{e}")

# === Run bot ===
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("p", price))
app.add_handler(CommandHandler("cv", convert))
app.add_handler(CommandHandler("alpha", alpha))

print("✅ Bot is running...")
app.run_polling()
