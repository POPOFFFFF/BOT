import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = os.getenv("CHAT_ID")
ALLOWED_USERS = [5228681344]

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Хранилище напоминаний {chat_id: [(время, текст), ...]}
schedules = {}

# Хранилище расписаний {chat_id: {(day, week_type): text}}
# week_type: 0=всегда, 1=чётная, 2=нечётная
rasps = {}

def is_allowed(user_id):
    return user_id in ALLOWED_USERS

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

@dp.message(Command("new"))
async def cmd_add_schedule(message: types.Message):
    if not is_allowed(message.from_user.id):
        return
    await message.answer("Напиши в формате:\n\nЧАТ_ID HH:MM ТЕКСТ")

@dp.message(Command("addrasp"))
async def cmd_add_rasp(message: types.Message):
    if not is_allowed(message.from_user.id):
        return
    
    try:
        parts = message.text.split(" ", 3)
        if len(parts) < 4:
            return await message.answer("⚠ Формат: /addrasp <день> <тип недели> <текст>")

        day = int(parts[1])  # 1=понедельник, ..., 7=воскресенье
        week_type = int(parts[2])  # 0=всегда, 1=чётная, 2=нечётная
        text = parts[3].replace("\\n", "\n")  # поддержка переноса строк
        chat_id = int(DEFAULT_CHAT_ID)

        rasps.setdefault(chat_id, {})[(day, week_type)] = text

        await message.answer(
            f"✅ Расписание добавлено!\n\n"
            f"День: {day}, Неделя: {week_type}\n{text}"
        )

    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}\nФормат: /addrasp <день> <тип недели> <текст>")

@dp.message(Command("rasp"))
async def cmd_rasp(message: types.Message):
    chat_id = message.chat.id
    today = datetime.date.today()
    week_number = today.isocalendar()[1]
    is_even_week = (week_number % 2 == 0)  # True=чётная, False=нечётная
    week_type = 1 if is_even_week else 2
    day = today.isoweekday()  # 1=понедельник ... 7=воскресенье

    # Если команда в чате → показываем расписание на сегодня
    if message.chat.type in ["group", "supergroup"]:
        if chat_id not in rasps:
            return await message.reply("ℹ️ Для этой беседы расписание пока не задано.")

        options = rasps[chat_id]
        text = None
        # приоритет: конкретный день+тип → конкретный день+0 (всегда)
        if (day, week_type) in options:
            text = options[(day, week_type)]
        elif (day, 0) in options:
            text = options[(day, 0)]

        if not text:
            return await message.reply("ℹ️ На сегодня расписания нет.")
        await message.reply(f"📅 Расписание на сегодня:\n\n{text}")

    # Если команда в ЛС → показываем все сохранённые
    elif message.chat.type == "private":
        if not is_allowed(message.from_user.id):
            return
        if not rasps:
            return await message.answer("ℹ️ Пока нет заданных расписаний.")

        text = "📋 Все расписания:\n\n"
        for cid, items in rasps.items():
            text += f"🆔 Chat {cid}\n"
            for (d, w), msg in items.items():
                text += f"  День {d}, Неделя {w}\n{msg}\n\n"
        await message.answer(text)

# Показываем chat_id при любом сообщении в чате
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

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
