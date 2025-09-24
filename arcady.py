import asyncio
import os
import datetime
import re
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

TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_CHAT_ID = int(os.getenv("CHAT_ID", "0"))
ALLOWED_USERS = [5228681344, 7620086223]
SPECIAL_USER_ID = [, ]

SPECIAL_USERS = {
    7059079404: "Тест",
    7228927149: "Анжелики Олеговной (Препод Математики)"
}


DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
TZ = ZoneInfo("Asia/Omsk")
scheduler = AsyncIOScheduler(timezone=TZ)

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

async def init_db(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasp_detailed (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                week_type INT,
                pair_number INT,
                subject_id INT,
                cabinet VARCHAR(50),
                FOREIGN KEY (subject_id) REFERENCES subjects(id)
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS week_setting (
                chat_id BIGINT PRIMARY KEY,
                week_type INT,
                set_at DATE
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS publish_times (
                id INT AUTO_INCREMENT PRIMARY KEY,
                hour INT NOT NULL,
                minute INT NOT NULL
            )""")
            await conn.commit()

# ------------------ Состояния ------------------

class AddLessonState(StatesGroup):
    subject = State()
    week_type = State()
    day = State()
    pair_number = State()
    cabinet = State()

class SetCabinetState(StatesGroup):
    week_type = State()
    day = State()
    pair_number = State()
    cabinet = State()

class ClearPairState(StatesGroup):
    week_type = State()
    day = State()
    pair_number = State()

class ForwardModeState(StatesGroup):
    active = State()

class SetChetState(StatesGroup):
    week_type = State()

class SetPublishTimeState(StatesGroup):
    time = State()

# ------------------ Меню ------------------

DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

def main_menu(is_admin=False, is_special_user=False):
    buttons = [
        [InlineKeyboardButton(text="📅 Расписание", callback_data="menu_rasp")],
        [InlineKeyboardButton(text="⏰ Звонки", callback_data="menu_zvonki")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙ Админка", callback_data="menu_admin")])
    if is_special_user:
        buttons.append([InlineKeyboardButton(text="✉ Режим пересылки", callback_data="send_message_chat")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Установить четность", callback_data="admin_setchet")],
        [InlineKeyboardButton(text="📌 Узнать четность недели", callback_data="admin_show_chet")],
        [InlineKeyboardButton(text="🕒 Время публикаций", callback_data="admin_list_publish_times")],
        [InlineKeyboardButton(text="📝 Задать время публикации", callback_data="admin_set_publish_time")],
        [InlineKeyboardButton(text="🕐 Узнать мое время", callback_data="admin_my_publish_time")],
        [InlineKeyboardButton(text="➕ Добавить урок", callback_data="admin_add_lesson")],
        [InlineKeyboardButton(text="🏫 Установить кабинет", callback_data="admin_set_cabinet")],
        [InlineKeyboardButton(text="🧹 Очистить пару", callback_data="admin_clear_pair")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])

# ------------------ Основные функции ------------------

async def greet_and_send(user: types.User, text: str, message: types.Message = None,
                         callback: types.CallbackQuery = None, markup=None, chat_id: int | None = None):
    if callback:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except:
            await callback.message.answer(text, reply_markup=markup)
    elif message:
        await message.answer(text, reply_markup=markup)
    elif chat_id is not None:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
    else:
        await bot.send_message(chat_id=user.id, text=text, reply_markup=markup)

async def get_rasp_formatted(day, week_type):
    msg_lines = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.pair_number, COALESCE(r.cabinet, '') as cabinet, s.name
                   FROM rasp_detailed r
                   LEFT JOIN subjects s ON r.subject_id = s.id
                   WHERE r.chat_id=%s AND r.day=%s AND r.week_type=%s
                   ORDER BY r.pair_number""",
                (DEFAULT_CHAT_ID, day, week_type)
            )
            rows = await cur.fetchall()

    last_pair = max([r[0] for r in rows], default=0)
    if last_pair == 0:
        return "Расписание пустое."

    for i in range(1, last_pair + 1):
        row = next((r for r in rows if r[0] == i), None)
        if row and row[2]:
            msg_lines.append(f"{i}. {row[1]} {row[2]}".strip())
        else:
            msg_lines.append(f"{i}. Свободно")

    return "\n".join(msg_lines)

# ------------------ Админ: четность недели ------------------

@dp.callback_query(F.data == "admin_setchet")
async def admin_setchet(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="setchet_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="setchet_2")]
    ])
    await greet_and_send(callback.from_user, "Выберите четность недели:", callback=callback, markup=kb)
    await state.set_state(SetChetState.week_type)

@dp.callback_query(F.data.startswith("setchet_"))
async def setchet_value(callback: types.CallbackQuery, state: FSMContext):
    week_type = int(callback.data[-1])
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO week_setting (chat_id, week_type, set_at)
                VALUES (%s, %s, CURDATE())
                ON DUPLICATE KEY UPDATE week_type=VALUES(week_type), set_at=VALUES(set_at)
            """, (DEFAULT_CHAT_ID, week_type))
    await greet_and_send(callback.from_user, f"✅ Четность недели установлена: {week_type}", callback=callback)
    await state.clear()

@dp.callback_query(F.data == "admin_show_chet")
async def admin_show_chet(callback: types.CallbackQuery):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT week_type, set_at FROM week_setting WHERE chat_id=%s", (DEFAULT_CHAT_ID,))
            row = await cur.fetchone()
    if not row:
        await callback.message.answer("Четность недели не установлена.")
    else:
        await callback.message.answer(f"Текущая четность: {row[0]}, установлена {row[1]}")

# ------------------ Админ: публикации ------------------

@dp.callback_query(F.data == "admin_list_publish_times")
async def admin_list_publish_times(callback: types.CallbackQuery):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT hour, minute FROM publish_times ORDER BY hour, minute")
            rows = await cur.fetchall()
    if not rows:
        msg = "Нет установленных времен публикации."
    else:
        msg = "\n".join([f"{h:02d}:{m:02d}" for h, m in rows])
    await callback.message.answer("Время публикаций:\n" + msg)

@dp.callback_query(F.data == "admin_set_publish_time")
async def admin_set_publish_time(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите время публикации в формате ЧЧ:ММ")
    await state.set_state(SetPublishTimeState.time)

@dp.message(SetPublishTimeState.time)
async def save_publish_time(message: types.Message, state: FSMContext):
    match = re.match(r"^(\d{1,2}):(\d{2})$", message.text)
    if not match:
        await message.answer("Неверный формат. Введите ЧЧ:ММ")
        return
    h, m = map(int, match.groups())
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO publish_times (hour, minute) VALUES (%s, %s)", (h, m))
    await message.answer(f"✅ Время публикации {h:02d}:{m:02d} сохранено")
    await state.clear()

@dp.callback_query(F.data == "admin_my_publish_time")
async def admin_my_publish_time(callback: types.CallbackQuery):
    now = datetime.datetime.now(TZ)
    await callback.message.answer(f"Ваше текущее время: {now.strftime('%H:%M')}")

# ------------------ Админ: очистка пары ------------------

@dp.callback_query(F.data == "admin_clear_pair")
async def admin_clear_pair_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="clr_week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="clr_week_2")]
    ])
    await greet_and_send(callback.from_user, "Выберите четность недели:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.week_type)

@dp.callback_query(F.data.startswith("clr_week_"))
async def clear_pair_week(callback: types.CallbackQuery, state: FSMContext):
    week_type = int(callback.data[-1])
    await state.update_data(week_type=week_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=day, callback_data=f"clr_day_{i+1}")] for i, day in enumerate(DAYS)
    ])
    await greet_and_send(callback.from_user, "Выберите день недели:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.day)

@dp.callback_query(F.data.startswith("clr_day_"))
async def clear_pair_day(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data[len("clr_day_"):])
    await state.update_data(day=day)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"clr_pair_{i}")] for i in range(1, 7)
    ])
    await greet_and_send(callback.from_user, "Выберите номер пары:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.pair_number)

@dp.callback_query(F.data.startswith("clr_pair_"))
async def clear_pair_number(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("clr_pair_"):])
    data = await state.get_data()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id FROM rasp_detailed
                WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
            """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], pair_number))
            row = await cur.fetchone()
            if row:
                await cur.execute("""
                    UPDATE rasp_detailed SET subject_id=NULL, cabinet=NULL WHERE id=%s
                """, (row[0],))
            else:
                await cur.execute("""
                    INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                    VALUES (%s, %s, %s, %s, NULL, NULL)
                """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], pair_number))
    await greet_and_send(callback.from_user,
                         f"✅ Пара {pair_number} ({DAYS[data['day']-1]}, неделя {data['week_type']}) очищена. Теперь там 'Свободно'.",
                         callback=callback)
    await state.clear()

# ------------------ Special user: forward mode ------------------
@dp.callback_query(F.data == "send_message_chat")
async def start_forward_mode(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in SPECIAL_USERS or callback.message.chat.type != "private":
        await callback.answer("⛔ Доступно только конкретному пользователю", show_alert=True)
        return
    await callback.message.answer("✅ Режим пересылки включен на 180 секунд.")
    await state.set_state(ForwardModeState.active)
    async def stop_after_delay():
        await asyncio.sleep(180)
        current = await state.get_state()
        if current == ForwardModeState.active:
            await state.clear()
            await callback.message.answer("⏰ Время пересылки истекло.")
    asyncio.create_task(stop_after_delay())
@dp.message(ForwardModeState.active)
async def handle_forward_mode(message: types.Message, state: FSMContext):
    if message.from_user.id not in SPECIAL_USERS:
        return
    user_label = SPECIAL_USERS.get(message.from_user.id, "Неизвестный")
    text_header = f"Сообщение от ({user_label}):\n"

    if message.text:
        await bot.send_message(chat_id=DEFAULT_CHAT_ID, text=text_header + message.text)
    elif message.caption or message.photo or message.document or message.video:
        caption = (message.caption or "")
        await bot.send_message(chat_id=DEFAULT_CHAT_ID, text=text_header + caption)
        # можно дополнительно пересылать сам медиафайл при необходимости
        await bot.forward_message(chat_id=DEFAULT_CHAT_ID,
                                  from_chat_id=message.chat.id,
                                  message_id=message.message_id)


# ------------------ Триггеры ------------------

TRIGGERS = ["/аркадий", "/акрадый", "/акрадий", "/аркаша", "/котов", "/arkadiy@arcadiyis07_bot", "/arkadiy"]

@dp.message(F.text.lower().in_(TRIGGERS))
async def trigger_handler(message: types.Message, state: FSMContext):
    is_private = message.chat.type == "private"
    is_admin = (message.from_user.id in ALLOWED_USERS) and is_private
    is_special_user = (message.from_user.id in SPECIAL_USER_ID) and is_private

    await greet_and_send(
        message.from_user,
        "Выберите действие:",
        message=message,
        markup=main_menu(is_admin=is_admin, is_special_user=is_special_user)
    )

# ------------------ main ------------------

async def main():
    global pool
    pool = await get_pool()
    await init_db(pool)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())