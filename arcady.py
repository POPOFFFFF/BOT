import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
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
dp = Dispatcher(storage=MemoryStorage())
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
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasp (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                week_type INT,
                text TEXT
            )
            """)
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

async def delete_rasp(pool, day=None):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if day:
                await cur.execute("DELETE FROM rasp WHERE chat_id=%s AND day=%s", (DEFAULT_CHAT_ID, day))
            else:
                await cur.execute("DELETE FROM rasp WHERE chat_id=%s", (DEFAULT_CHAT_ID,))

# ======================
# Четность недели
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
# Вспомогательные
# ======================
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

def format_rasp_message(day_num, week_type, text):
    day_name = DAYS[day_num-1]
    week_name = "нечетная" if week_type==1 else "четная"
    return f"📅 {day_name} | Неделя: {week_name}\n\n{text}"

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
# Кнопки
# ======================
def main_menu(is_admin=False):
    buttons = [
        [InlineKeyboardButton(text="📅 Расписание", callback_data="menu_rasp")],
        [InlineKeyboardButton(text="⏰ Звонки", callback_data="menu_zvonki")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙ Админка", callback_data="menu_admin")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ======================
# FSM для админки
# ======================
class AddRaspState(StatesGroup):
    day = State()
    week_type = State()
    text = State()

class ClearRaspState(StatesGroup):
    day = State()

class SetChetState(StatesGroup):
    week_type = State()

# ======================
# Хендлеры
# ======================
@dp.message(F.text == "/аркадий")
async def cmd_arkadiy(message: types.Message):
    is_admin = message.from_user.id in ALLOWED_USERS
    await message.answer("Выберите действие:", reply_markup=main_menu(is_admin))

# Главное меню
@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "menu_rasp":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=day, callback_data=f"rasp_day_{i+1}")]
                             for i, day in enumerate(DAYS)]
            + [[InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]]
        )
        await callback.message.edit_text("📅 Выберите день:", reply_markup=kb)


    elif action == "menu_zvonki":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 Будние дни", callback_data="zvonki_weekday")],
                [InlineKeyboardButton(text="📅 Суббота", callback_data="zvonki_saturday")],
                [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
            ]
        )


        await callback.message.edit_text("⏰ Выберите день:", reply_markup=kb)

    elif action == "menu_admin":
        if callback.from_user.id not in ALLOWED_USERS:
            return await callback.answer("⛔ Нет доступа", show_alert=True)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить расписание", callback_data="admin_add")],
            [InlineKeyboardButton(text="🗑 Очистить расписание", callback_data="admin_clear")],
            [InlineKeyboardButton(text="🔄 Установить четность", callback_data="admin_setchet")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])

        await callback.message.edit_text("⚙ Админ-панель:", reply_markup=kb)

    elif action == "menu_back":
        # Очистим возможные состояния FSM (если админ был в процессе)
        try:
            await state.clear()
        except Exception:
            pass

        is_admin = callback.from_user.id in ALLOWED_USERS

        # Попробуем удалить предыдущее сообщение (если оно принадлежит боту).
        # Если удаление не получилось — пробуем edit_text, а если и это не получится — просто отправим новое сообщение.
        try:
            await callback.message.delete()
        except Exception as e:
            # не удалось удалить — пробуем редактировать
            try:
                await callback.message.edit_text("Выберите действие:", reply_markup=main_menu(is_admin))
            except Exception:
                # как запасной вариант отправим новое сообщение
                await bot.send_message(chat_id=callback.message.chat.id, text="Выберите действие:", reply_markup=main_menu(is_admin))
        else:
            # если удалили успешно — отправляем новое сообщение с меню
            await bot.send_message(chat_id=callback.message.chat.id, text="Выберите действие:", reply_markup=main_menu(is_admin))

        await callback.answer()




# ======================
# Расписание (пользователи)
# ======================

@dp.callback_query(F.data.startswith("rasp_day_"))
async def rasp_day_handler(callback: types.CallbackQuery):
    day = int(callback.data.split("_")[2])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Любая", callback_data=f"rasp_show_{day}_0")],
            [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data=f"rasp_show_{day}_1")],
            [InlineKeyboardButton(text="2️⃣ Четная", callback_data=f"rasp_show_{day}_2")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_rasp")]
        ]
    )
    await callback.message.edit_text("📅 Выберите четность недели:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("rasp_show_"))
async def rasp_show_handler(callback: types.CallbackQuery):
    _, _, day, week_type = callback.data.split("_")
    day = int(day)
    week_type = int(week_type)

    if week_type == 0:  # если выбрана "любая"
        now = datetime.datetime.now(TZ)
        week_type = await get_week_type(pool, callback.message.chat.id)
        if not week_type:
            week_type = 1 if now.isocalendar()[1] % 2 else 2

    text = await get_rasp_for_day(pool, DEFAULT_CHAT_ID, day, week_type)
    if not text:
        await callback.answer("ℹ На этот день нет расписания", show_alert=True)
    else:
        await callback.message.edit_text(format_rasp_message(day, week_type, text))

    await callback.answer()


@dp.callback_query(F.data.startswith("rasp_"))
async def rasp_handler(callback: types.CallbackQuery):
    day = int(callback.data.split("_")[1])
    now = datetime.datetime.now(TZ)
    week_type = await get_week_type(pool, callback.message.chat.id)
    if not week_type:
        week_type = 1 if now.isocalendar()[1] % 2 else 2
    text = await get_rasp_for_day(pool, DEFAULT_CHAT_ID, day, week_type)
    if not text:
        await callback.answer("ℹ На этот день нет расписания", show_alert=True)
    else:
        await callback.message.edit_text(format_rasp_message(day, week_type, text))
    await callback.answer()

# ======================
# Звонки
# ======================
@dp.callback_query(F.data.startswith("zvonki_"))
async def zvonki_handler(callback: types.CallbackQuery):
    action = callback.data

    if action == "zvonki_weekday":
        schedule = "\n".join(ZVONKI_DEFAULT)
        await callback.message.edit_text(f"📌 Расписание звонков (будние дни):\n{schedule}")

    elif action == "zvonki_saturday":
        schedule = "\n".join(ZVONKI_SATURDAY)
        await callback.message.edit_text(f"📌 Расписание звонков (суббота):\n{schedule}")

    await callback.answer()

# ======================
# Админка — Добавить расписание
# ======================
@dp.callback_query(F.data == "admin_add")
async def admin_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите день недели (1-7):")
    await state.set_state(AddRaspState.day)
    await callback.answer()

@dp.message(AddRaspState.day)
async def add_rasp_day(message: types.Message, state: FSMContext):
    try:
        day = int(message.text)
        if not 1 <= day <= 7:
            raise ValueError
        await state.update_data(day=day)
        await message.answer("Введите тип недели (0 - любая, 1 - нечетная, 2 - четная):")
        await state.set_state(AddRaspState.week_type)
    except ValueError:
        await message.answer("⚠ Введите число от 1 до 7.")

@dp.message(AddRaspState.week_type)
async def add_rasp_week_type(message: types.Message, state: FSMContext):
    try:
        week_type = int(message.text)
        if week_type not in [0, 1, 2]:
            raise ValueError
        await state.update_data(week_type=week_type)
        await message.answer("Введите текст расписания:")
        await state.set_state(AddRaspState.text)
    except ValueError:
        await message.answer("⚠ Введите 0, 1 или 2.")

@dp.message(AddRaspState.text)
async def add_rasp_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.replace("\\n", "\n")
    await add_rasp(pool, DEFAULT_CHAT_ID, data["day"], data["week_type"], text)
    await message.answer("✅ Расписание добавлено!")
    await state.clear()

# ======================
# Админка — Очистить расписание
# ======================
@dp.callback_query(F.data == "admin_clear")
async def admin_clear_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите день недели (1-7) или 0 для удаления всех:")
    await state.set_state(ClearRaspState.day)
    await callback.answer()

@dp.message(ClearRaspState.day)
async def clear_rasp_day(message: types.Message, state: FSMContext):
    try:
        day = int(message.text)
        if day == 0:
            await delete_rasp(pool)
        elif 1 <= day <= 7:
            await delete_rasp(pool, day)
        else:
            raise ValueError
        await message.answer("✅ Расписание удалено!")
        await state.clear()
    except ValueError:
        await message.answer("⚠ Введите 0 или число от 1 до 7.")

# ======================
# Админка — Установить четность
# ======================
@dp.callback_query(F.data == "admin_setchet")
async def admin_setchet_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите четность (1 - нечетная, 2 - четная):")
    await state.set_state(SetChetState.week_type)
    await callback.answer()

@dp.message(SetChetState.week_type)
async def setchet_handler(message: types.Message, state: FSMContext):
    try:
        week_type = int(message.text)
        if week_type not in [1, 2]:
            raise ValueError
        await set_week_type(pool, message.chat.id, week_type)
        await message.answer(f"✅ Четность установлена: {week_type} ({'нечетная' if week_type==1 else 'четная'})")
        await state.clear()
    except ValueError:
        await message.answer("⚠ Введите 1 или 2.")

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

scheduler.add_job(send_today_rasp, CronTrigger(hour=1, minute=0))
scheduler.add_job(send_today_rasp, CronTrigger(hour=14, minute=0))

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
