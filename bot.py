import os
import asyncio
import logging
import re
import aiohttp
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from bs4 import BeautifulSoup
from telethon import TelegramClient
from telethon.sessions import StringSession

# === ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ===
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SESSION_STRING = os.environ.get('SESSION_STRING')

if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN обязателен')
if not SESSION_STRING:
    logging.warning("SESSION_STRING не задана — используйте /nft_manual")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ИНИЦИАЛИЗАЦИЯ TELEGRAM CLIENT ===
# Передаём заглушки 0 и '' — сессия уже содержит всё нужное.
client = TelegramClient(StringSession(SESSION_STRING), 0, '')

# ============================================================
# МЕТОД 1: TELEGRAM API (через Telethon)
# ============================================================
async def get_gifts_via_telethon(user_id: int):
    try:
        # Используем методы Telethon для получения подарков
        # Это требует доступа к внутреннему API Telegram
        # Пока оставляем заглушку — в Telethon нет прямого метода для подарков
        # Используем парсинг как основной метод
        return None
    except Exception as e:
        logger.error(f"Telethon error: {e}")
        return None

# ============================================================
# МЕТОД 2: ПАРСИНГ СТРАНИЦЫ t.me/nft/
# ============================================================
async def parse_gift_page(slug: str):
    url = f'https://t.me/nft/{slug}'
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
                soup = BeautifulSoup(html, 'lxml')
                transfers = []
                rows = soup.find_all(string=re.compile(r'→'))
                for row in rows:
                    parent = row.parent
                    if parent:
                        text = parent.get_text(separator=' ', strip=True)
                        match = re.search(r'(\S+)\s*→\s*(\S+)', text)
                        if match:
                            from_user = match.group(1).strip()
                            to_user = match.group(2).strip()
                            date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', text)
                            date_str = date_match.group(1) if date_match else None
                            timestamp = None
                            if date_str:
                                try:
                                    dt = datetime.strptime(date_str, '%d.%m.%Y')
                                    timestamp = int(dt.timestamp())
                                except:
                                    pass
                            transfers.append({
                                'from': from_user,
                                'to': to_user,
                                'timestamp': timestamp,
                                'date_str': date_str
                            })
                return transfers
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return None

# ============================================================
# КОМАНДА /nft
# ============================================================
async def nft_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите ID пользователя: /nft 123456789\n"
            "Или ссылку на подарок: /nft https://t.me/nft/ViceCream-299743"
        )
        return

    arg = context.args[0].strip()
    await update.message.reply_text(f"🔍 Проверяю...")

    # Если это ссылка
    if arg.startswith('https://t.me/nft/'):
        slug = arg.split('/')[-1]
        transfers = await parse_gift_page(slug)
        if not transfers:
            await update.message.reply_text("❌ Не удалось спарсить страницу.")
            return
        report = f"📜 *ИСТОРИЯ ПЕРЕДАЧ*\n\n"
        for tr in transfers[:30]:
            dt = tr.get('date_str', '?') if tr.get('date_str') else '?'
            report += f"├ {tr['from']} → {tr['to']} ({dt})\n"
        await update.message.reply_text(report, parse_mode='Markdown')
        return

    # Если это ID
    if not arg.isdigit():
        await update.message.reply_text("❌ Введите ID числом или ссылку на подарок.")
        return

    user_id = int(arg)
    await update.message.reply_text(f"🔍 Ищу подарки для ID {user_id}...")

    # Пытаемся найти подарки через Telethon (если есть сессия)
    # Пока используем заглушку, так как Telethon не даёт прямой доступ к подаркам
    await update.message.reply_text(
        "⚠️ Telethon не имеет прямого метода для получения подарков.\n"
        "Используйте ручной метод: /nft https://t.me/nft/НАЗВАНИЕ\n\n"
        "Пример: /nft https://t.me/nft/ViceCream-299743"
    )

# ============================================================
# КОМАНДА /nft_manual
# ============================================================
async def nft_manual_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите ссылку: /nft_manual https://t.me/nft/ViceCream-299743")
        return

    url = context.args[0].strip()
    slug = url.split('/')[-1]
    await update.message.reply_text(f"🔍 Парсим {slug}...")

    transfers = await parse_gift_page(slug)
    if not transfers:
        await update.message.reply_text("❌ История не найдена.")
        return

    report = f"📜 *ИСТОРИЯ ПЕРЕДАЧ*\n\n"
    for tr in transfers[:30]:
        dt = tr.get('date_str', '?') if tr.get('date_str') else '?'
        report += f"├ {tr['from']} → {tr['to']} ({dt})\n"
    await update.message.reply_text(report, parse_mode='Markdown')

# ============================================================
# ЗАПУСК
# ============================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("nft", nft_command))
    app.add_handler(CommandHandler("nft_manual", nft_manual_command))
    logger.info("Бот запущен.")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    asyncio.run(main())
