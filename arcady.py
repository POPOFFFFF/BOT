import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
import aiomysql
import ssl

# ======================
# Конфиг
# ======================
TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = int(os.getenv("CHAT_ID", "0"))
ALLOWED_USERS = [5228681344, 7620086223]

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

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# ======================
# Работа с БД
# ======================
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

async def init_db(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Таблица обычного расписания
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasp (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                week_type INT,
                text TEXT
            )
            """)
            # Таблица настройки недели
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS week_setting (
                chat_id BIGINT PRIMARY KEY,
                week_type INT
            )
            """)
            # Таблица распоряжений (однодневные)
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasporaz (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                text TEXT
            )
            """)

# Добавление распоряжения
async def add_rasporaz(pool, chat_id, day, text):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Сначала удаляем старое распоряжение на этот день
            await cur.execute(
                "DELETE FROM rasporaz WHERE chat_id=%s AND day=%s",
                (chat_id, day)
            )
            # Затем добавляем новое
            await cur.execute(
                "INSERT INTO rasporaz (chat_id, day, text) VALUES (%s, %s, %s)",
                (chat_id, day, text)
            )
# Получение распоряжения на день
async def get_rasporaz_for_day(pool, chat_id, day):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT text FROM rasporaz WHERE chat_id=%s AND day=%s",
                (chat_id, day)
            )
            rows = await cur.fetchall()
            return [r[0] for r in rows] if rows else []

# Удаление распоряжения
async def delete_rasporaz(pool, day=None):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if day:
                await cur.execute("DELETE FROM rasporaz WHERE chat_id=%s AND day=%s", (DEFAULT_CHAT_ID, day))
            else:
                await cur.execute("DELETE FROM rasporaz WHERE chat_id=%s", (DEFAULT_CHAT_ID,))





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

async def delete_rasp(pool, day=None):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if day:
                await cur.execute("DELETE FROM rasp WHERE chat_id=%s AND day=%s", (DEFAULT_CHAT_ID, day))
            else:
                await cur.execute("DELETE FROM rasp WHERE chat_id=%s", (DEFAULT_CHAT_ID,))

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
# Вспомогательные функции
# ======================
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

def format_rasp_message(day_num, week_type, text):
    day_name = DAYS[day_num-1]
    week_name = "нечетная" if week_type==1 else "четная"
    return f"📅 {day_name} | Неделя: {week_name}\n\n{text}"

# Расписание звонков: каждая пара — 2 урока
ZVONKI_DEFAULT = [
"1 пара: 1 урок 08:30-09:15, 2 урок 09:20-10:05", 
"2 пара: 1 урок 10:15-11:00, 2 урок 11:05-11:50", 
"3 пара: 1 урок 12:40-13:25, 2 урок 13:30-14:15", 
"4 пара: 1 урок 14:25-15:10, 2 урок 15:15-16:00", 
"5 пара: 1-2 урок 16:05-17:35", 
"6 пара: 1 урок 17:45-19:15"
]

ZVONKI_SATURDAY = [
"1 пара: 1 урок 08:30-09:15, 2 урок 09:20-10:05", 
"2 пара: 1 урок 10:15-11:00, 2 урок 11:05-11:50", 
"3 пара: 1 урок 12:00-12:45, 2 урок 12:50-13:35", 
"4 пара: 1-2 урок 13:45-15:15", 
"5 пара: 1-2 урок 15:25-16:55", 
"6 пара: 1-2 урок 17:05-18:50"
]

def get_zvonki(day):
    if day == 6:
        return "\n".join(ZVONKI_SATURDAY)
    else:
        return "\n".join(ZVONKI_DEFAULT)

# ======================
# Команды
# ======================
# ======================
# Команда /rasporaz — просмотр распоряжений
# ======================
@dp.message(Command("rasporaz"))
async def cmd_rasporaz_view(message: types.Message):
    parts = message.text.split()
    now = datetime.datetime.now(TZ)
    if len(parts) >= 2 and parts[1].isdigit():
        day = int(parts[1])
        if not 1 <= day <= 7:
            return await message.reply("⚠ День недели должен быть от 1 до 7.")
    else:
        day = now.isoweekday()

    rasporaz_list = await get_rasporaz_for_day(pool, DEFAULT_CHAT_ID, day)
    if rasporaz_list:
        day_name = DAYS[day-1]
        msg = f"📌 Распоряжения на {day_name}:\n"
        for r in rasporaz_list:
            msg += f"- {r}\n"
    else:
        msg = "ℹ️ Распоряжений на этот день нет."
    await message.reply(msg)

# ======================
# Команда /clear_rasporaz
# ======================
@dp.message(Command("clear_rasporaz"))
async def cmd_clear_rasporaz(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    parts = message.text.split()
    day = None
    if len(parts) >= 2:
        try:
            day = int(parts[1])
            if not 1 <= day <= 7:
                raise ValueError
        except ValueError:
            return await message.reply("⚠ День недели должен быть числом от 1 до 7.")
    confirm_text = f"Вы точно хотите удалить распоряжение {'для дня ' + str(day) if day else 'для всех дней'}? Отправьте 'да' для подтверждения."
    await message.answer(confirm_text)
    def check(m: types.Message):
        return m.from_user.id in ALLOWED_USERS and m.text.lower() == "да"
    try:
        msg = await bot.wait_for("message", timeout=30.0, check=check)
        await delete_rasporaz(pool, day)
        await message.answer("✅ Распоряжение удалено!")
    except asyncio.TimeoutError:
        await message.answer("⌛ Подтверждение не получено. Операция отменена.")



@dp.message(Command("addrasp"))
async def cmd_add_rasp(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        parts = message.text.split(" ", 3)
        if len(parts) < 4:
            return await message.answer("⚠ Формат: /addrasp <день> <тип недели> <текст>\nТип недели: 0 - любая, 1 - нечетная, 2 - четная")
        day = int(parts[1])
        week_type = int(parts[2])
        if week_type not in [0, 1, 2]:
            return await message.answer("⚠ Неверный тип недели! Используйте 0, 1 или 2.")
        text = parts[3].replace("\\n", "\n")
        await add_rasp(pool, DEFAULT_CHAT_ID, day, week_type, text)
        await message.answer(f"✅ Добавлено!\nДень {day}, Неделя {week_type}\n{text}")
    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}")

@dp.message(Command("clear_rasp"))
async def cmd_clear_rasp(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    parts = message.text.split()
    day = None
    if len(parts) >= 2:
        try:
            day = int(parts[1])
            if not 1 <= day <= 7:
                raise ValueError
        except ValueError:
            return await message.reply("⚠ День недели должен быть числом от 1 до 7.")
    confirm_text = f"Вы точно хотите удалить расписание {'для дня ' + str(day) if day else 'для всех дней'}? Отправьте 'да' для подтверждения."
    await message.answer(confirm_text)
    def check(m: types.Message):
        return m.from_user.id in ALLOWED_USERS and m.text.lower() == "да"
    try:
        msg = await bot.wait_for("message", timeout=30.0, check=check)
        await delete_rasp(pool, day)
        await message.answer("✅ Расписание удалено!")
    except asyncio.TimeoutError:
        await message.answer("⌛ Подтверждение не получено. Операция отменена.")

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

# ======================
# Изменения в /rasp для отображения и автоудаления
# ======================@dp.message(Command("rasp"))
async def cmd_rasp(message: types.Message):
    parts = message.text.split()
    now = datetime.datetime.now(TZ)
    # День
    if len(parts) >= 2 and parts[1].isdigit():
        day = int(parts[1])
        if not 1 <= day <= 7:
            return await message.reply("⚠ День недели должен быть от 1 до 7.")
    else:
        day = now.isoweekday()
    # Четность недели
    if len(parts) >= 3 and parts[2].isdigit():
        week_type = int(parts[2])
        if week_type not in [1, 2]:
            return await message.reply("⚠ Четность недели: 1 - нечетная, 2 - четная.")
    else:
        week_type = await get_week_type(pool, message.chat.id)
        if not week_type:
            week_number = now.isocalendar()[1]
            week_type = 1 if week_number % 2 else 2

    # Обычное расписание
    text = await get_rasp_for_day(pool, DEFAULT_CHAT_ID, day, week_type)
    msg = ""
    if text:
        msg += format_rasp_message(day, week_type, text)
    else:
        msg += "ℹ️ На этот день расписания нет.\n"

    # Добавляем распоряжение на этот день
    rasporaz_list = await get_rasporaz_for_day(pool, DEFAULT_CHAT_ID, day)
    if rasporaz_list:
        msg += "\n\n📌 Распоряжение на этот день:\n"
        msg += f"- {rasporaz_list[0]}\n"  # теперь только одно распоряжение

    await message.reply(msg)

    # Автоудаление распоряжений для прошедших дней
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            yesterday = now - datetime.timedelta(days=1)
            y_day = yesterday.isoweekday()
            # Удаляем распоряжение прошедшего дня
            await cur.execute(
                "DELETE FROM rasporaz WHERE chat_id=%s AND day=%s",
                (DEFAULT_CHAT_ID, y_day)
            )


@dp.message(Command("zvonki"))
async def cmd_zvonki(message: types.Message):
    parts = message.text.split()
    now = datetime.datetime.now(TZ)
    if len(parts) >= 2 and parts[1].isdigit():
        day = int(parts[1])
        if not 1 <= day <= 7:
            return await message.reply("⚠ День недели должен быть от 1 до 7.")
    else:
        day = now.isoweekday()
    schedule = get_zvonki(day)
    day_name = DAYS[day-1]
    await message.reply(f"📌 Расписание звонков на {day_name}:\n{schedule}")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if message.chat.type == "private":
        if message.from_user.id not in ALLOWED_USERS:
            return await message.answer("⚠ У вас нет доступа к админским командам.")
        text = (
            "📌 Команды администратора:\n"
            "/addrasp <день> <тип недели> <текст> — добавить расписание\n"
            "/clear_rasp [<день>] — удалить расписание (с подтверждением)\n"
            "/setchet <1|2> — установить четность недели для чата\n"
            "/rasp [<день> <четность>] — посмотреть расписание\n"
            "/zvonki [<день>] — посмотреть расписание звонков\n"
            "/chatid — узнать ID чата\n"
            "/rasporaz [<день>] — Добавить расспоряжение\n"
            "/clear_rasporaz — Удалить расспоряжение\n"
            "/help — показать это сообщение"
        )
    else:
        text = "ℹ️ Чтобы посмотреть расписание, используйте команду:\n/rasp [<день> <четность>]\n/zvonki [<день>]"
    await message.answer(text)

# ======================
# Автопостинг расписания
# ======================
async def send_today_rasp():
    now = datetime.datetime.now(TZ)
    day = now.isoweekday()
    week_number = now.isocalendar()[1]
    week_type = 1 if week_number % 2 else 2
    text = await get_rasp_for_day(pool, DEFAULT_CHAT_ID, day, week_type)
    if text:
        msg = format_rasp_message(day, week_type, text)
        await bot.send_message(DEFAULT_CHAT_ID, msg)

scheduler.add_job(send_today_rasp, CronTrigger(hour=7, minute=0))
scheduler.add_job(send_today_rasp, CronTrigger(hour=20, minute=0))

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

