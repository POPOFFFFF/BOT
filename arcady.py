import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os

TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = os.getenv("CHAT_ID")  # теперь чат ID берётся из переменных окружения
ALLOWED_USERS = [5228681344]  # твой Telegram ID

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Хранилище расписаний {chat_id: [(время, текст), ...]}
schedules = {}

# Проверка доступа
def is_allowed(user_id):
    return user_id in ALLOWED_USERS

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_allowed(message.from_user.id):
        return await message.answer("❌ У тебя нет доступа.")
    await message.answer("✅ Привет! Я Секретарь Аркадий.\nНапиши /new чтобы добавить задание.")

@dp.message(Command("new"))
async def cmd_add_schedule(message: types.Message):
    if not is_allowed(message.from_user.id):
        return
    await message.answer("Напиши в формате:\n\nЧАТ_ID HH:MM ТЕКСТ")

# Новая команда: показать расписание
@dp.message(Command("rasp"))
async def cmd_rasp(message: types.Message):
    chat_id = message.chat.id

    # Если команда в беседе
    if message.chat.type in ["group", "supergroup"]:
        if chat_id not in schedules:
            return await message.reply("ℹ️ Для этой беседы расписание пока не задано.")
        
        text = "📅 Расписание для этой беседы:\n\n"
        for t, msg in schedules[chat_id]:
            text += f"⏰ {t} → {msg}\n"
        await message.reply(text)
    
    # Если команда в личке
    elif message.chat.type == "private":
        if not is_allowed(message.from_user.id):
            return
        if not schedules:
            return await message.answer("ℹ️ Пока нет заданных расписаний.")

        text = "📋 Все расписания:\n\n"
        for cid, items in schedules.items():
            text += f"🆔 {cid}\n"
            for t, msg in items:
                text += f"  ⏰ {t} → {msg}\n"
            text += "\n"
        await message.answer(text)

# Показываем chat_id при любом сообщении в чате
@dp.message()
async def add_schedule_handler(message: types.Message):
    # Если это групповая беседа — выводим chat_id
    if message.chat.type in ["group", "supergroup"]:
        await message.reply(f"ℹ️ Chat ID этой беседы: `{message.chat.id}`")
        return

    # Личная переписка с админом
    if not is_allowed(message.from_user.id):
        return
    
    try:
        parts = message.text.split(" ", 2)

        # Если chat_id не указали явно, берём дефолтный из переменной окружения
        chat_id = int(parts[0]) if parts[0].startswith("-") else int(DEFAULT_CHAT_ID)
        time = parts[1]
        text = parts[2]

        hour, minute = map(int, time.split(":"))
        
        # Сохраняем
        schedules.setdefault(chat_id, []).append((time, text))

        # Запускаем задачу
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
