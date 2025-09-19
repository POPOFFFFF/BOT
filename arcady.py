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
ALLOWED_USERS = [5228681344,7620086223 ]

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
            # Таблица расписания
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasp (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                week_type INT,
                text TEXT
            )
            """)
            # Таблица для четности недели
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS week_setting (
                chat_id BIGINT PRIMARY KEY,
                week_type INT
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
# Работа с четностью недели
# ======================
async def set_week_type(pool, chat_id, week_type):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO week_setting (chat_id, week_type) 
                VALUES (%s, %s) 
                ON DUPLICATE KEY UPDATE week_type=%s
            """, (chat_id, week_type, week_type))

async def get_week_type(pool, chat_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT week_type FROM week_setting WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            return row[0] if row else None

# ======================
# Команды
# ======================
@dp.message(Command("addrasp"))
async def cmd_add_rasp(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        parts = message.text.split(" ", 3)
        if len(parts) < 4:
            return await message.answer("⚠ Формат: /addrasp <день> <тип недели> <текст>\n"
                                        "Тип недели: 0 - любая, 1 - нечетная, 2 - четная")
        day = int(parts[1])
        week_type = int(parts[2])
        if week_type not in [0, 1, 2]:
            return await message.answer("⚠ Неверный тип недели! Используйте 0, 1 или 2.")
        text = parts[3].replace("\\n", "\n")
        chat_id = DEFAULT_CHAT_ID
        await add_rasp(pool, chat_id, day, week_type, text)
        await message.answer(f"✅ Добавлено!\nДень {day}, Неделя {week_type}\n{text}")
    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}")

@dp.message(Command("clear_rasp"))
async def cmd_clear_rasp(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM rasp WHERE chat_id=%s", (DEFAULT_CHAT_ID,))
        await message.answer("✅ Все расписания очищены!")
    except Exception as e:
        await message.answer(f"⚠ Ошибка при очистке: {e}")

@dp.message(Command("setchet"))
async def cmd_setchet(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        parts = message.text.split()
        if len(parts) != 2 or parts[1] not in ["1", "2"]:
            return await message.answer("⚠ Формат: /setchet <1 - нечетная | 2 - четная>")
        week_type = int(parts[1])
        chat_id = message.chat.id
        await set_week_type(pool, chat_id, week_type)
        await message.answer(f"✅ Четность недели установлена: {week_type} ({'нечетная' if week_type==1 else 'четная'})")
    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}")

@dp.message(Command("chatid"))
async def cmd_chatid(message: types.Message):
    await message.answer(f"🆔 Chat ID: {message.chat.id}")

@dp.message(Command("rasp"))
async def cmd_rasp(message: types.Message):
    parts = message.text.split()
    now = datetime.datetime.now(TZ)
    
    # Определяем день
    if len(parts) >= 2:
        try:
            day = int(parts[1])
            if day < 1 or day > 7:
                raise ValueError
        except ValueError:
            return await message.reply("⚠ День недели должен быть числом от 1 (Пн) до 7 (Вс).")
    else:
        day = now.isoweekday()
    
    # Определяем четность
    if len(parts) >= 3:
        try:
            week_type = int(parts[2])
            if week_type not in [1, 2]:
                raise ValueError
        except ValueError:
            return await message.reply("⚠ Четность недели: 1 - нечетная, 2 - четная.")
    else:
        week_type = await get_week_type(pool, message.chat.id)
        if not week_type:
            week_number = now.isocalendar()[1]
            week_type = 1 if week_number % 2 else 2

    text = await get_rasp_for_day(pool, message.chat.id, day, week_type)
    if not text:
        return await message.reply("ℹ️ На этот день расписания нет.")
    
    await message.reply(f"📅 Расписание:\n\n{text}")

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
