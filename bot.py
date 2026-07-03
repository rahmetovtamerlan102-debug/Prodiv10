import os
import asyncio
import logging
import aiohttp
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession

# === ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (настроить на Render) ===
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SESSION_STRING = os.environ.get('SESSION_STRING')

if not BOT_TOKEN or not SESSION_STRING:
    raise ValueError('BOT_TOKEN и SESSION_STRING обязательны')

# API_ID и API_HASH не нужны — они в сессии.
# Передаём заглушки (0 и ''), Telethon их проигнорирует.
client = TelegramClient(StringSession(SESSION_STRING), 0, '').start(bot_token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO)

# ============================================================
# ПОЛНЫЙ ПРОФИЛЬ
# ============================================================
async def get_full_profile(username: str):
    try:
        entity = await client.get_entity(username)
        if not isinstance(entity, types.User):
            return None
        full = await client(functions.users.GetFullUserRequest(entity))
        user = full.full_user
        photos = await client.get_profile_photos(entity, limit=1)
        flags = []
        if getattr(entity, 'scam', False):
            flags.append('SCAM')
        if getattr(entity, 'fake', False):
            flags.append('FAKE')
        if getattr(entity, 'verified', False):
            flags.append('VERIFIED')
        return {
            'id': entity.id,
            'username': entity.username,
            'first_name': entity.first_name,
            'last_name': entity.last_name or '',
            'bio': getattr(user, 'about', None),
            'premium': getattr(user, 'premium', False),
            'phone': getattr(user, 'phone', None),
            'dc_id': getattr(entity.photo, 'dc_id', None) if entity.photo else None,
            'flags': flags,
            'avatar_url': f"https://t.me/i/userpic/320/{entity.id}.jpg" if photos else None,
            'common_chats': getattr(user, 'common_chats_count', 0)
        }
    except Exception as e:
        logging.error(f"Profile error: {e}")
        return None

# ============================================================
# NFT-ПОДАРКИ
# ============================================================
async def get_nft_gifts(user_id: int):
    url = f'https://api.giftasset.io/v1/gifts?owner_id={user_id}&limit=20'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get('gifts', [])
    except:
        return []

# ============================================================
# ПРОВЕРКА В СКАМ-БАЗАХ
# ============================================================
async def check_scam_bases(user_id: int):
    url = f'https://smartuserinfo.onrender.com/info?id={user_id}'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {'error': 'API недоступен'}
                data = await resp.json()
                if not data.get('success'):
                    return {'error': 'Не удалось проверить'}
                return {
                    'scam': data.get('is_scam', False),
                    'fake': data.get('is_fake', False),
                    'verified': data.get('is_verified', False),
                    'premium': data.get('is_premium', False),
                    'age_days': data.get('account_age_days', 0),
                    'dc_location': data.get('dc_location', 'unknown')
                }
    except:
        return {'error': 'Ошибка соединения'}

# ============================================================
# КОМАНДА /check
# ============================================================
@client.on(events.NewMessage(pattern='/check (.+)'))
async def check_handler(event):
    username = event.pattern_match.group(1).strip()
    await event.reply('🔍 Проверяю аккаунт...')

    profile = await get_full_profile(username)
    if not profile:
        await event.reply('❌ Пользователь не найден')
        return

    scam = await check_scam_bases(profile['id'])
    nfts = await get_nft_gifts(profile['id'])

    report = f"""📋 *ОТЧЁТ ПО АККАУНТУ* @{username}
━━━━━━━━━━━━━━━━━━━━━

👤 *ПРОФИЛЬ*
├ ID: {profile['id']}
├ Имя: {profile['first_name']} {profile['last_name']}
├ Username: @{profile['username']}
├ Premium: {'✅ Да' if profile['premium'] else '❌ Нет'}
├ Флаги: {', '.join(profile['flags']) if profile['flags'] else '✅ Чистый'}
├ DC: {profile['dc_id'] or 'неизвестно'}
├ Общие чаты: {profile['common_chats']}
├ Био: {profile['bio'] or '—'}
└ Аватар: [ссылка]({profile['avatar_url']}) {'' if profile['avatar_url'] else '❌ Нет'}

🔍 *ПРОВЕРКА В БАЗАХ*
├ Скам: {'🚨 ДА' if scam.get('scam') else '✅ НЕТ'}
├ Фейк: {'🚨 ДА' if scam.get('fake') else '✅ НЕТ'}
├ Верифицирован: {'✅ ДА' if scam.get('verified') else '❌ НЕТ'}
├ Возраст: {scam.get('age_days', '?')} дней
└ DC локация: {scam.get('dc_location', '?')}

🎁 *NFT-ПОДАРКИ* ({len(nfts)} шт.)
"""
    for gift in nfts[:10]:
        report += f"├ {gift.get('name', 'Без имени')} (ID: {gift.get('id', '?')})\n"
    if len(nfts) > 10:
        report += f"└ ... и ещё {len(nfts) - 10}"

    if len(report) > 4000:
        report = report[:4000] + '\n... (обрезано)'
    await event.reply(report, parse_mode='markdown')

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    await client.start()
    logging.info('Бот запущен. Команда: /check @username')
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
