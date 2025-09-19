import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo
import aiomysql
import ssl

# ======================
# Конфиг из переменных окружения
# ======================
TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = int(os.getenv("CHAT_ID", "0"))
ALLOWED_USERS = [5228681344]

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# ======================
# Инициализация
# ======================
bot = Bot(token=TOKEN)
dp = Dispatcher()
TZ = ZoneInfo("Asia/Omsk")
scheduler = AsyncIOScheduler(timezone=TZ)

# SSL для Aiven
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

async def get_pool():
    return await aiomysql.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        db=DB_NAME,
        ssl=ssl_ctx,
        autocommit=True
    )

# ======================
# Работа с БД
# ======================
async def init_db(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasp (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                week_type INT,
                text TEXT
            )
            """)

async def add_rasp(pool, chat_id, day, week_type, text):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO rasp (chat_id, day, week_type, text) VALUES (%s, %s, %s, %s)",
                (chat_id, day, week_type, text)
            )

async def get_rasp_for_day(pool, chat_id, day, week_type):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT text FROM rasp WHERE chat_id=%s AND day=%s AND week_type=%s LIMIT 1",
                (chat_id, day, week_type)
            )
            row = await cur.fetchone()
            if row:
                return row[0]
            await cur.execute(
                "SELECT text FROM rasp WHERE chat_id=%s AND day=%s AND week_type=0 LIMIT 1",
                (chat_id, day)
            )
            row = await cur.fetchone()
            return row[0] if row else None

async def get_all_rasp(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT chat_id, day, week_type, text FROM rasp")
            return await cur.fetchall()

# ======================
# Команды
# ======================
@dp.message(Command("addrasp"))
async def cmd_add_rasp(message: types.Message):
    if not (message.from_user.id in ALLOWED_USERS):
        return
    try:
        parts = message.text.split(" ", 3)
        if len(parts) < 4:
            return await message.answer("⚠ Формат: /addrasp <день> <тип недели> <текст>")

        day = int(parts[1])
        week_type = int(parts[2])
        text = parts[3].replace("\\n", "\n")
        chat_id = int(DEFAULT_CHAT_ID)

        await add_rasp(pool, chat_id, day, week_type, text)
        await message.answer(f"✅ Добавлено!\nДень {day}, Неделя {week_type}\n{text}")
    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}")

@dp.message(Command("rasp"))
async def cmd_rasp(message: types.Message):
    now = datetime.datetime.now(TZ)
    week_number = now.isocalendar()[1]
    week_type = 1 if (week_number % 2 == 0) else 2
    day = now.isoweekday()

    if message.chat.type in ["group", "supergroup"]:
        text = await get_rasp_for_day(pool, message.chat.id, day, week_type)
        if not text:
            return await message.reply("ℹ️ На сегодня расписания нет.")
        return await message.reply(f"📅 Расписание:\n\n{text}")

    elif message.chat.type == "private":
        if not (message.from_user.id in ALLOWED_USERS):
            return
        rows = await get_all_rasp(pool)
        if not rows:
            return await message.answer("ℹ️ Пока нет расписаний.")
        msg = "📋 Все расписания:\n\n"
        for cid, d, w, txt in rows:
            msg += f"🆔 Chat {cid} | День {d}, Неделя {w}\n{txt}\n\n"
        await message.answer(msg)

# ======================
# Main
# ======================
async def main():
    global pool
    pool = await get_pool()
    await init_db(pool)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
