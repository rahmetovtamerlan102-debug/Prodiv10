import os
import asyncio
import logging
import aiohttp
import re
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from bs4 import BeautifulSoup

# === КОНФИГ ===
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN обязателен')

ADMIN_IDS = list(map(int, os.environ.get('ADMIN_IDS', '').split(','))) if os.environ.get('ADMIN_IDS') else []

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === БАЗА ДАННЫХ ===
DB_PATH = 'nft_bot.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        total_requests INTEGER DEFAULT 0,
        banned BOOLEAN DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS cache (
        user_id INTEGER PRIMARY KEY,
        gifts_data TEXT,
        transfers_data TEXT,
        updated_at TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# === ФУНКЦИИ БАЗЫ ===
def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT balance, total_requests, banned FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'balance': row[0], 'total_requests': row[1], 'banned': row[2]}
    return None

def create_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, balance, total_requests, banned) VALUES (?, ?, ?, ?)',
              (user_id, 0, 0, 0))
    conn.commit()
    conn.close()

def add_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance + ? WHERE user_id=?', (amount, user_id))
    conn.commit()
    conn.close()

def deduct_request(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance - 1, total_requests = total_requests + 1 WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()

def set_ban(user_id, banned):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET banned=? WHERE user_id=?', (1 if banned else 0, user_id))
    conn.commit()
    conn.close()

def get_cache(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT gifts_data, transfers_data, updated_at FROM cache WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'gifts': json.loads(row[0]), 'transfers': json.loads(row[1]), 'updated_at': datetime.fromisoformat(row[2])}
    return None

def set_cache(user_id, gifts, transfers):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('REPLACE INTO cache (user_id, gifts_data, transfers_data, updated_at) VALUES (?, ?, ?, ?)',
              (user_id, json.dumps(gifts), json.dumps(transfers), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_top_users(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id, total_requests FROM users ORDER BY total_requests DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# === МЕТОДЫ ПОЛУЧЕНИЯ NFT ===
async def fetch_gifts_api(user_id):
    url = f'https://api.giftasset.io/v1/gifts?owner_id={user_id}&limit=50'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get('gifts', [])
    except:
        return None

async def fetch_transfers_api(gift_id):
    url = f'https://api.giftasset.io/v1/gifts/{gift_id}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get('transfers', [])
    except:
        return None

async def parse_gift_page(slug):
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
                            transfers.append({'from': from_user, 'to': to_user, 'timestamp': timestamp, 'date_str': date_str})
                return transfers
    except:
        return None

async def get_nft_transfers_ton(address):
    url = f'https://toncenter.com/api/v2/getTransactions?address={address}&limit=20&archival=true'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                if not data.get('ok'):
                    return []
                txs = data.get('result', [])
                transfers = []
                for tx in txs:
                    for out_msg in tx.get('out_msgs', []):
                        payload = out_msg.get('payload', '')
                        if payload:
                            try:
                                decoded = base64.b64decode(payload).decode('utf-8', errors='ignore')
                                if 'transfer' in decoded.lower() or 'nft' in decoded.lower():
                                    transfers.append({
                                        'from': tx.get('account', {}).get('address', '?'),
                                        'to': out_msg.get('destination', {}).get('address', '?'),
                                        'timestamp': tx.get('utime', None)
                                    })
                                    break
                            except:
                                pass
                return transfers
    except:
        return []

# === ОСНОВНАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ИСТОРИИ ===
async def get_history(user_id):
    cached = get_cache(user_id)
    if cached and (datetime.now() - cached['updated_at']) < timedelta(hours=24):
        return cached['transfers']

    gifts = await fetch_gifts_api(user_id)
    if gifts is None:
        return None
    if not gifts:
        return []

    all_transfers = []
    for gift in gifts:
        gift_id = gift.get('id')
        if not gift_id:
            continue
        gift_name = gift.get('name', 'Без имени')
        transfers = await fetch_transfers_api(gift_id)
        if transfers is not None and transfers:
            for tr in transfers:
                all_transfers.append({'gift': gift_name, 'from': tr.get('from', '?'), 'to': tr.get('to', '?'), 'timestamp': tr.get('timestamp')})
        else:
            slug = gift.get('slug') or gift_id
            parsed = await parse_gift_page(slug)
            if parsed:
                for tr in parsed:
                    all_transfers.append({'gift': gift_name, 'from': tr.get('from', '?'), 'to': tr.get('to', '?'), 'timestamp': tr.get('timestamp'), 'date_str': tr.get('date_str')})
            else:
                address = gift.get('address')
                if address:
                    ton_transfers = await get_nft_transfers_ton(address)
                    for tr in ton_transfers:
                        all_transfers.append({'gift': gift_name, 'from': tr.get('from', '?'), 'to': tr.get('to', '?'), 'timestamp': tr.get('timestamp')})
    set_cache(user_id, gifts, all_transfers)
    return all_transfers

# === ОБРАБОТЧИКИ КОМАНД ===
async def nft_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    create_user(user_id)
    user = get_user(user_id)
    if user['banned']:
        await update.message.reply_text("❌ Вы забанены.")
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /nft 123456789")
        return
    target = context.args[0].strip()
    if not target.isdigit():
        await update.message.reply_text("❌ ID должен быть числом.")
        return

    if user['balance'] < 1:
        keyboard = [[InlineKeyboardButton("💰 Купить запросы", callback_data="buy")]]
        await update.message.reply_text(
            "❌ Недостаточно баланса. Пополните баланс, чтобы сделать запрос.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    deduct_request(user_id)
    await update.message.reply_text(f"🔍 Ищу историю для ID {target}...")
    transfers = await get_history(int(target))
    if transfers is None:
        await update.message.reply_text("⚠️ Ошибка получения данных. Попробуйте позже.")
        return
    if not transfers:
        await update.message.reply_text("📭 Нет истории передач.")
        return

    transfers.sort(key=lambda x: x.get('timestamp') if isinstance(x.get('timestamp'), (int, float)) else 0, reverse=True)
    report = f"📜 *ИСТОРИЯ ПЕРЕДАЧ NFT* (ID: {target})\n"
    report += f"Всего передач: {len(transfers)}\n━━━━━━━━━━━━━━━━━━━━━\n"
    for tr in transfers[:30]:
        dt = None
        if isinstance(tr.get('timestamp'), (int, float)):
            dt = datetime.fromtimestamp(tr['timestamp']).strftime('%Y-%m-%d %H:%M')
        elif tr.get('date_str'):
            dt = tr['date_str']
        else:
            dt = '?'
        report += f"├ {tr['gift']}\n"
        report += f"├ 🕒 {dt}\n"
        report += f"├ От: {tr['from']}\n"
        report += f"└ Кому: {tr['to']}\n\n"
    if len(transfers) > 30:
        report += f"└ ... и ещё {len(transfers) - 30} передач"
    if len(report) > 4000:
        report = report[:4000] + '\n... (обрезано)'
    await update.message.reply_text(report, parse_mode='Markdown')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    create_user(user_id)
    user = get_user(user_id)
    if user['banned']:
        await update.message.reply_text("❌ Вы забанены.")
        return
    await update.message.reply_text(f"💰 Ваш баланс: {user['balance']} запросов.")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Пополните баланс:\n"
        "Переведите 10 Stars на @ваш_аккаунт или используйте команду /pay\n"
        "После оплаты ваш баланс пополнится автоматически (если настроен бот-кассир)."
    )

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = get_top_users(10)
    if not top_users:
        await update.message.reply_text("Пока нет активных пользователей.")
        return
    msg = "🏆 *ТОП-10 ПО ЗАПРОСАМ*\n"
    for i, (uid, count) in enumerate(top_users, 1):
        msg += f"{i}. {uid} — {count} запросов\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот для проверки NFT-подарков\n\n"
        "/nft <id> — показать историю передач\n"
        "/balance — ваш баланс\n"
        "/buy — купить запросы\n"
        "/top — топ пользователей"
    )

# === ДЕКОРАТОР АДМИНА ===
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("⛔ Нет прав.")
            return
        await func(update, context)
    return wrapper

@admin_only
async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /add_balance <user_id> <amount>")
        return
    uid = int(context.args[0])
    amount = int(context.args[1])
    add_balance(uid, amount)
    await update.message.reply_text(f"✅ Добавлено {amount} запросов пользователю {uid}.")

@admin_only
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /ban <user_id>")
        return
    uid = int(context.args[0])
    set_ban(uid, True)
    await update.message.reply_text(f"✅ Пользователь {uid} забанен.")

@admin_only
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /unban <user_id>")
        return
    uid = int(context.args[0])
    set_ban(uid, False)
    await update.message.reply_text(f"✅ Пользователь {uid} разбанен.")

@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /broadcast <текст>")
        return
    text = ' '.join(context.args)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users')
    rows = c.fetchall()
    conn.close()
    sent = 0
    for (uid,) in rows:
        try:
            await context.bot.send_message(uid, f"📢 {text}")
            sent += 1
        except:
            pass
    await update.message.reply_text(f"✅ Отправлено {sent} пользователям.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "buy":
        await query.edit_message_text("💳 Оплата временно недоступна. Свяжитесь с админом.")

# === ЗАПУСК ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("nft", nft_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("add_balance", add_balance_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    logger.info("Бот запущен.")
    app.run_polling()

if __name__ == '__main__':
    main()
