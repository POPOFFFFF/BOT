import asyncio
import os
import datetime
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = os.getenv("CHAT_ID")
ALLOWED_USERS = [5228681344]

bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================
# Таймзона Омск (UTC+6)
# =========================
TZ = timezone("Asia/Omsk")
scheduler = AsyncIOScheduler(timezone=TZ)

# =========================
# Работа с БД
# =========================
DB_PATH = "rasp.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rasp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        day INTEGER,
        week_type INTEGER,
        text TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_rasp(chat_id, day, week_type, text):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO rasp (chat_id, day, week_type, text) VALUES (?, ?, ?, ?)",
                (chat_id, day, week_type, text))
    conn.commit()
    conn.close()

def get_rasp_for_day(chat_id, day, week_type):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT text FROM rasp WHERE chat_id=? AND day=? AND week_type=?", (chat_id, day, week_type))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    cur.execute("SELECT text FROM rasp WHERE chat_id=? AND day=? AND week_type=0", (chat_id, day))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_all_rasp():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id, day, week_type, text FROM rasp")
    rows = cur.fetchall()
    conn.close()
    return rows

# =========================
# Проверка доступа
# =========================
def is_allowed(user_id):
    return user_id in ALLOWED_USERS

# =========================
# Команды
# =========================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_allowed(message.from_user.id):
        return await message.answer("❌ У тебя нет доступа.")
    await message.answer(
        "✅ Привет! Я Секретарь Аркадий.\n\n"
        "📌 Команды:\n"
        "/new — добавить напоминание (по времени)\n"
        "/addrasp — добавить расписание (по дням)\n"
        "/rasp — показать расписание"
    )

@dp.message(Command("addrasp"))
async def cmd_add_rasp(message: types.Message):
    if not is_allowed(message.from_user.id):
        return
    
    try:
        parts = message.text.split(" ", 3)
        if len(parts) < 4:
            return await message.answer("⚠ Формат: /addrasp <день> <тип недели> <текст>")

        day = int(parts[1])        # 1=понедельник, ..., 7=воскресенье
        week_type = int(parts[2])  # 0=всегда, 1=чётная, 2=нечётная
        text = parts[3].replace("\\n", "\n")
        chat_id = int(DEFAULT_CHAT_ID)

        add_rasp(chat_id, day, week_type, text)

        await message.answer(
            f"✅ Расписание добавлено!\n\n"
            f"День: {day}, Неделя: {week_type}\n{text}"
        )

    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}\nФормат: /addrasp <день> <тип недели> <текст>")

@dp.message(Command("rasp"))
async def cmd_rasp(message: types.Message):
    chat_id = message.chat.id
    now = datetime.datetime.now(TZ)   # всегда берём Омское время
    week_number = now.isocalendar()[1]
    is_even_week = (week_number % 2 == 0)
    week_type = 1 if is_even_week else 2
    day = now.isoweekday()

    if message.chat.type in ["group", "supergroup"]:
        text = get_rasp_for_day(chat_id, day, week_type)
        if not text:
            return await message.reply("ℹ️ На сегодня расписания нет.")
        await message.reply(f"📅 Расписание на сегодня:\n\n{text}")

    elif message.chat.type == "private":
        if not is_allowed(message.from_user.id):
            return
        rows = get_all_rasp()
        if not rows:
            return await message.answer("ℹ️ Пока нет заданных расписаний.")

        text = "📋 Все расписания:\n\n"
        for cid, d, w, msg in rows:
            text += f"🆔 Chat {cid}\nДень {d}, Неделя {w}\n{msg}\n\n"
        await message.answer(text)

# =========================
# Логика для напоминаний
# =========================
schedules = {}

@dp.message(Command("new"))
async def cmd_add_schedule(message: types.Message):
    if not is_allowed(message.from_user.id):
        return
    await message.answer("Напиши в формате:\n\nЧАТ_ID HH:MM ТЕКСТ")

@dp.message()
async def add_schedule_handler(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        await message.reply(f"ℹ️ Chat ID этой беседы: `{message.chat.id}`")
        return

    if not is_allowed(message.from_user.id):
        return
    
    try:
        parts = message.text.split(" ", 2)
        chat_id = int(parts[0]) if parts[0].startswith("-") else int(DEFAULT_CHAT_ID)
        time = parts[1]
        text = parts[2]

        hour, minute = map(int, time.split(":"))
        
        schedules.setdefault(chat_id, []).append((time, text))

        scheduler.add_job(
            bot.send_message,
            "cron",
            hour=hour,
            minute=minute,
            args=[chat_id, text],
        )

        await message.answer(f"✅ Задание добавлено!\n{chat_id} {time} → {text}")

    except Exception:
        await message.answer("⚠ Ошибка. Формат: ЧАТ_ID HH:MM ТЕКСТ")

# =========================
# Main
# =========================
async def main():
    init_db()
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
