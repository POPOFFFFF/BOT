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
import re

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

# ======================
# Работа с БД (добавим никнеймы, publish_times и расширим week_setting)
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
            # week_setting теперь хранит дату установки set_at (DATE) и базовую week_type
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS week_setting (
                chat_id BIGINT PRIMARY KEY,
                week_type INT,
                set_at DATE
            )
            """)
            # новая таблица никнеймов
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS nicknames (
                user_id BIGINT PRIMARY KEY,
                nickname VARCHAR(255)
            )
            """)
            # таблица для времён публикаций (по Омску)
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS publish_times (
                id INT AUTO_INCREMENT PRIMARY KEY,
                hour INT NOT NULL,
                minute INT NOT NULL
            )
            """)

# ----------------------
# Nicknames
# ----------------------

async def ensure_nicknames_column(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Добавляем колонку locked, если её нет
            await cur.execute("SHOW COLUMNS FROM nicknames LIKE 'locked'")
            row = await cur.fetchone()
            if not row:
                await cur.execute("ALTER TABLE nicknames ADD COLUMN locked BOOLEAN DEFAULT FALSE")
            # всем существующим записям присваиваем FALSE
            await cur.execute("UPDATE nicknames SET locked=FALSE WHERE locked IS NULL")

async def ensure_columns(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Проверяем, есть ли колонка set_at
            await cur.execute("SHOW COLUMNS FROM week_setting LIKE 'set_at'")
            row = await cur.fetchone()
            if not row:
                # добавляем колонку
                await cur.execute("ALTER TABLE week_setting ADD COLUMN set_at DATE")


async def set_nickname(pool, user_id: int, nickname: str, locked: bool = False):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO nicknames (user_id, nickname, locked)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    nickname = IF(locked=0, VALUES(nickname), nickname),
                    locked = locked
            """, (user_id, nickname, locked))

async def get_nickname(pool, user_id: int) -> str | None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT nickname FROM nicknames WHERE user_id=%s", (user_id,))
            row = await cur.fetchone()
            return row[0] if row else None

# ----------------------
# Publish times
# ----------------------
async def add_publish_time(pool, hour: int, minute: int):
    """Добавляет время публикации в БД."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Вставляем запись с commit
            await cur.execute(
                "INSERT INTO publish_times (hour, minute) VALUES (%s, %s)", 
                (hour, minute)
            )
            await conn.commit()  # обязательный commit для сохранения


async def get_publish_times(pool):
    """Возвращает список всех времен публикаций."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, hour, minute FROM publish_times ORDER BY hour, minute")
            rows = await cur.fetchall()
            return rows  # [(id, hour, minute), ...]


async def delete_publish_time(pool, pid: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM publish_times WHERE id=%s", (pid,))

async def clear_publish_times(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM publish_times")

# ======================
# Работа с расписанием (rasp)
# ======================
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
            # fallback week_type = 0 (any)
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
    today = datetime.datetime.now(TZ).date()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO week_setting (chat_id, week_type, set_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE week_type=%s, set_at=%s
            """, (chat_id, week_type, today, week_type, today))

async def get_week_setting(pool, chat_id):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT week_type, set_at FROM week_setting WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if not row:
                return None
            wt, set_at = row
            if isinstance(set_at, datetime.datetime):
                set_at = set_at.date()
            return (wt, set_at)

# ======================
# Четность недели
# ======================
async def get_current_week_type(pool, chat_id: int, target_date: datetime.date | None = None):
    """
    Вычисляет четность недели для chat_id на конкретную дату target_date.
    Если target_date не указан, берется сегодняшняя дата.
    """
    setting = await get_week_setting(pool, chat_id)
    if target_date is None:
        target_date = datetime.datetime.now(TZ).date()

    if not setting:
        # fallback на календарный расчет ISO-недели
        week_number = target_date.isocalendar()[1]
        return 1 if week_number % 2 != 0 else 2

    base_week_type, set_at = setting
    if isinstance(set_at, datetime.datetime):
        set_at = set_at.date()

    # используем ISO номера недель
    base_week_number = set_at.isocalendar()[1]
    target_week_number = target_date.isocalendar()[1]

    # разница в неделях, учитывая переход года
    weeks_passed = target_week_number - base_week_number
    if weeks_passed % 2 == 0:
        return base_week_type
    else:
        return 1 if base_week_type == 2 else 2




# ======================
# Вспомогательные
# ======================
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

def format_rasp_message(day_num, week_type, text):
    day_name = DAYS[day_num - 1]
    week_name = "нечетная" if week_type == 1 else "четная"
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

def get_zvonki(is_saturday: bool):
    return "\n".join(ZVONKI_SATURDAY if is_saturday else ZVONKI_DEFAULT)

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

# расширенная админка: добавляем новые пункты
def admin_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить расписание", callback_data="admin_add")],
        [InlineKeyboardButton(text="🗑 Очистить расписание", callback_data="admin_clear")],
        [InlineKeyboardButton(text="🔄 Установить четность", callback_data="admin_setchet")],
        [InlineKeyboardButton(text="📌 Узнать четность недели", callback_data="admin_show_chet")],
        [InlineKeyboardButton(text="🕒 Время публикаций", callback_data="admin_list_publish_times")],
        [InlineKeyboardButton(text="📝 Задать время публикации", callback_data="admin_set_publish_time")],
        [InlineKeyboardButton(text="🕐 Узнать мое время", callback_data="admin_my_publish_time")],  # новая кнопка
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    return kb

@dp.callback_query(F.data == "admin_my_publish_time")
async def admin_my_publish_time(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return

    now = datetime.datetime.now(TZ)
    times = await get_publish_times(pool)

    if not times:
        await greet_and_send(callback.from_user, "Время публикаций ещё не задано.", callback=callback)
        return

    # находим ближайшее время после текущего
    future_times = sorted([(h, m) for _, h, m in times if (h, m) > (now.hour, now.minute)])
    if future_times:
        hh, mm = future_times[0]
        msg = f"Следующая публикация сегодня в Омске: {hh:02d}:{mm:02d}"
    else:
        # если сегодня уже все публикации прошли — берём первую следующего дня
        hh, mm = sorted([(h, m) for _, h, m in times])[0]
        msg = f"Сегодня публикаций больше нет. Следующая публикация завтра в Омске: {hh:02d}:{mm:02d}"

    await greet_and_send(callback.from_user, msg, callback=callback)
    await callback.answer()


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

class SetPublishTimeState(StatesGroup):
    time = State()  # ожидаем ввод в формате HH:MM

# ======================
# Хелпер для приветствия и отправки сообщений
# ======================
async def greet_and_send(user: types.User, text: str, message: types.Message = None, callback: types.CallbackQuery = None, markup=None, chat_id: int | None = None):
    nickname = await get_nickname(pool, user.id)
    if nickname:
        greet = f"👋 Салам, {nickname}!\n\n"
    else:
        greet = "👋 Салам!\n\n"
    full_text = greet + text

    # callback edit / answer
    if callback:
        try:
            await callback.message.edit_text(full_text, reply_markup=markup)
        except Exception:
            # fallback: send a new message in the same chat as callback
            try:
                await callback.message.answer(full_text, reply_markup=markup)
            except Exception:
                # as last resort use bot.send_message
                await bot.send_message(chat_id=callback.message.chat.id, text=full_text, reply_markup=markup)
    # message.answer
    elif message:
        try:
            await message.answer(full_text, reply_markup=markup)
        except Exception:
            # fallback direct send
            await bot.send_message(chat_id=message.chat.id, text=full_text, reply_markup=markup)
    # direct chat_id (used when we deleted old message and want to send a fresh one)
    elif chat_id is not None:
        await bot.send_message(chat_id=chat_id, text=full_text, reply_markup=markup)
    else:
        # nothing else provided: try sending to user's private chat
        try:
            await bot.send_message(chat_id=user.id, text=full_text, reply_markup=markup)
        except Exception:
            # ignore silently
            pass

# ======================
# Функция (re)создания задач планировщика по данным из БД
# ======================
def _job_id_for_time(hour: int, minute: int) -> str:
    return f"publish_{hour:02d}_{minute:02d}"

async def reschedule_publish_jobs(pool):
    # удаляем старые publish_* задачи
    try:
        for job in list(scheduler.get_jobs()):
            if job.id.startswith("publish_"):
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    pass
    except Exception:
        pass

    # читаем времена из БД и создаём задачи
    times = await get_publish_times(pool)
    for row in times:
        pid, hour, minute = row
        job_id = _job_id_for_time(hour, minute)
        # добавляем задачу send_today_rasp с нужным временем в TZ
        try:
            scheduler.add_job(send_today_rasp, CronTrigger(hour=hour, minute=minute, timezone=TZ), id=job_id)
        except Exception:
            # если задача с таким id уже есть — пропускаем
            pass

# ======================
# Хендлеры
# ======================
@dp.message(F.text.lower().in_(["/аркадий", "/акрадый", "/акрадий"]))
async def cmd_arkadiy(message: types.Message):
    is_private = message.chat.type == "private"
    is_admin = (message.from_user.id in ALLOWED_USERS) and is_private
    await greet_and_send(message.from_user, "Выберите действие:", message=message, markup=main_menu(is_admin))

# Главный обработчик меню
@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data

    # ---------- расписание: показать список дней (1..6) ----------
    if action == "menu_rasp":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=day, callback_data=f"rasp_day_{i+1}")]
                for i, day in enumerate(DAYS)
            ] + [[InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]]
        )
        await greet_and_send(callback.from_user, "📅 Выберите день:", callback=callback, markup=kb)
        await callback.answer()

    # ---------- звонки: будни / суббота ----------
    elif action == "menu_zvonki":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Будние дни", callback_data="zvonki_weekday")],
            [InlineKeyboardButton(text="📅 Суббота", callback_data="zvonki_saturday")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await greet_and_send(callback.from_user, "⏰ Выберите вариант:", callback=callback, markup=kb)
        await callback.answer()

    # ---------- админка (только в ЛС) ----------
    elif action == "menu_admin":
        if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
            await callback.answer("⛔ Админка доступна только в личных сообщениях админам", show_alert=True)
            return

        await greet_and_send(callback.from_user, "⚙ Админ-панель:", callback=callback, markup=admin_menu())
        await callback.answer()

    # ---------- назад в главное меню ----------
    elif action == "menu_back":
        # отменим FSM (если был)
        try:
            await state.clear()
        except Exception:
            pass

        is_private = callback.message.chat.type == "private"
        is_admin = (callback.from_user.id in ALLOWED_USERS) and is_private

        # удаляем старое сообщение, если можем, и отправляем новое меню
        try:
            await callback.message.delete()
            # если удалили — отправляем новое сообщение с приветствием в тот же чат
            await greet_and_send(callback.from_user, "Выберите действие:", chat_id=callback.message.chat.id, markup=main_menu(is_admin))
        except Exception:
            # если не удалось удалить — пробуем редактировать, иначе отправить новое
            try:
                await greet_and_send(callback.from_user, "Выберите действие:", callback=callback, markup=main_menu(is_admin))
            except Exception:
                await greet_and_send(callback.from_user, "Выберите действие:", chat_id=callback.message.chat.id, markup=main_menu(is_admin))

        await callback.answer()


@dp.callback_query(F.data.startswith("rasp_day_"))
async def on_rasp_day(callback: types.CallbackQuery):

    parts = callback.data.split("_")
    try:
        day = int(parts[-1])
    except Exception:
        await callback.answer("Ошибка выбора дня", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data=f"rasp_show_{day}_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data=f"rasp_show_{day}_2")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_rasp")]
    ])

    await greet_and_send(callback.from_user, f"📅 {DAYS[day-1]} — выберите неделю:", callback=callback, markup=kb)
    await callback.answer()

# ----------------------------
# Пользователь устанавливает свой ник
# ----------------------------
# Команда /никнейм
@dp.message(F.text.regexp(r"^/никнейм(@\w+)?\s+.+"))
async def user_set_nickname(message: types.Message):
    txt = message.text.strip()
    parts = txt.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply("⚠ Использование: /никнейм <ваш никнейм>")
        return

    user_id = message.from_user.id
    nickname = parts[1].strip()

    # проверяем, locked ли ник
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT locked FROM nicknames WHERE user_id=%s", (user_id,))
            row = await cur.fetchone()
            if row and row[0]:
                await message.reply("⚠ Ваш ник закреплён администратором и не может быть изменён.")
                return

    try:
        await set_nickname(pool, user_id, nickname)
        await message.reply(f"✅ Ваш никнейм установлен: {nickname}")
    except Exception as e:
        await message.reply(f"❌ Ошибка при установке: {e}")


# ----------------------------
# Админ устанавливает ник другому пользователю
# ----------------------------
@dp.message(Command("setnick"))
async def admin_setnick(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("⛔ У вас нет прав для этой команды")
        return

    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 3:
            await message.answer("⚠ Использование: /setnick <user_id> <никнейм> [true|false]")
            return
        user_id = int(parts[1])
        nickname = parts[2].strip()
        lock = False
        if len(parts) >= 4:
            lock = parts[3].lower() == "true"

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO nicknames (user_id, nickname, locked)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE nickname=%s, locked=%s
                """, (user_id, nickname, lock, nickname, lock))

        await message.answer(f"✅ Никнейм для пользователя {user_id} установлен: {nickname} | locked={lock}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.callback_query(F.data.startswith("rasp_show_"))
async def on_rasp_show(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Неверные данные", show_alert=True)
        return
    try:
        day = int(parts[2])
        week_type = int(parts[3])
    except Exception:
        await callback.answer("Неверные данные", show_alert=True)
        return

    text = await get_rasp_for_day(pool, DEFAULT_CHAT_ID, day, week_type)
    if not text:

        await callback.answer("ℹ На этот день нет расписания", show_alert=True)
        await greet_and_send(callback.from_user, "На этот день нет расписания", callback=callback)
    else:
        await greet_and_send(callback.from_user, format_rasp_message(day, week_type, text), callback=callback)
    await callback.answer()

@dp.callback_query(F.data.startswith("zvonki_"))
async def zvonki_handler(callback: types.CallbackQuery):
    action = callback.data

    if action == "zvonki_weekday":
        schedule = get_zvonki(is_saturday=False)
        await greet_and_send(callback.from_user, f"📌 Расписание звонков (будние дни):\n{schedule}", callback=callback)

    elif action == "zvonki_saturday":
        schedule = get_zvonki(is_saturday=True)
        await greet_and_send(callback.from_user, f"📌 Расписание звонков (суббота):\n{schedule}", callback=callback)

    await callback.answer()

@dp.callback_query(F.data == "admin_show_chet")
async def admin_show_chet(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return


    current = await get_current_week_type(pool, DEFAULT_CHAT_ID)
    current_str = "нечетная (1)" if current == 1 else "четная (2)"

    setting = await get_week_setting(pool, DEFAULT_CHAT_ID)
    if not setting:
        base_str = "не установлена (бот использует календарь)"
        set_at_str = "—"
    else:
        base_week_type, set_at = setting
        base_str = "нечетная (1)" if base_week_type == 1 else "четная (2)"
        set_at_str = set_at.isoformat()

    msg = f"Текущая четность (отталкиваясь от установки): {current_str}\n\nБазовая (сохранённая в week_setting): {base_str}\nДата установки (Омск): {set_at_str}"
    await greet_and_send(callback.from_user, msg, callback=callback)
    await callback.answer()

@dp.callback_query(F.data == "admin_list_publish_times")
async def admin_list_publish_times(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return

    rows = await get_publish_times(pool)
    if not rows:
        text = "Время публикаций не задано."
    else:
        lines = [f"{rid}: {hour:02d}:{minute:02d} (Омск)" for rid, hour, minute in rows]
        text = "Текущие времена публикаций (Омск):\n" + "\n".join(lines)
        text += "\n\nЧтобы удалить время, используйте команду /delptime <id>"

    await greet_and_send(callback.from_user, text, callback=callback)
    await callback.answer()

@dp.callback_query(F.data == "admin_set_publish_time")
async def admin_set_publish_time(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return

    await callback.answer() 
    await greet_and_send(
        callback.from_user,
        "Введите время публикации в формате ЧЧ:ММ по Омску (например: 20:00):",
        callback=callback
    )


    await state.set_state(SetPublishTimeState.time)

@dp.message(Command("delptime"))
async def cmd_delptime(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("⛔ У вас нет прав")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠ Использование: /delptime <id> (id из списка времен публикаций)")
        return
    try:
        pid = int(parts[1])
        await delete_publish_time(pool, pid)
        await reschedule_publish_jobs(pool)
        await message.answer(f"✅ Время публикации с id={pid} удалено и задачи пересозданы.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(SetPublishTimeState.time)
async def set_publish_time_handler(message: types.Message, state: FSMContext):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("⛔ У вас нет прав")
        await state.clear()
        return

    txt = message.text.strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", txt)
    if not m:
        await message.answer("⚠ Неверный формат. Введите в формате ЧЧ:ММ, например 20:00")
        return

    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        await message.answer("⚠ Часы 0-23, минуты 0-59.")
        return

    try:
        await add_publish_time(pool, hh, mm)
        await reschedule_publish_jobs(pool)  # пересоздаем задачи планировщика
        await message.answer(f"✅ Время публикации добавлено: {hh:02d}:{mm:02d} (Омск).")
    except Exception as e:
        await message.answer(f"❌ Ошибка при сохранении: {e}")
    finally:
        await state.clear()

@dp.callback_query(F.data == "admin_add")
async def admin_add_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в личных сообщениях админам", show_alert=True)
        return
    await greet_and_send(callback.from_user, "Введите день недели (1-6):", callback=callback)
    await state.set_state(AddRaspState.day)
    await callback.answer()

@dp.message(AddRaspState.day)
async def add_rasp_day(message: types.Message, state: FSMContext):
    try:
        day = int(message.text)
        if not 1 <= day <= 6:
            raise ValueError
        await state.update_data(day=day)
        await greet_and_send(message.from_user, "Введите тип недели (0 - любая, 1 - нечетная, 2 - четная):", message=message)
        await state.set_state(AddRaspState.week_type)
    except ValueError:
        await greet_and_send(message.from_user, "⚠ Введите число от 1 до 6.", message=message)

@dp.message(AddRaspState.week_type)
async def add_rasp_week_type(message: types.Message, state: FSMContext):
    try:
        week_type = int(message.text)
        if week_type not in [0, 1, 2]:
            raise ValueError
        await state.update_data(week_type=week_type)
        await greet_and_send(message.from_user, "Введите текст расписания (используйте \\n для переносов):", message=message)
        await state.set_state(AddRaspState.text)
    except ValueError:
        await greet_and_send(message.from_user, "⚠ Введите 0, 1 или 2.", message=message)

@dp.message(AddRaspState.text)
async def add_rasp_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.replace("\\n", "\n")
    await add_rasp(pool, DEFAULT_CHAT_ID, data["day"], data["week_type"], text)
    await greet_and_send(message.from_user, "✅ Расписание добавлено!", message=message)
    await state.clear()


@dp.callback_query(F.data == "admin_clear")
async def admin_clear_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в личных сообщениях админам", show_alert=True)
        return
    await greet_and_send(callback.from_user, "Введите день недели (1-6) или 0 для удаления всех:", callback=callback)
    await state.set_state(ClearRaspState.day)
    await callback.answer()

@dp.message(ClearRaspState.day)
async def clear_rasp_day(message: types.Message, state: FSMContext):
    try:
        day = int(message.text)
        if day == 0:
            await delete_rasp(pool)
        elif 1 <= day <= 6:
            await delete_rasp(pool, day)
        else:
            raise ValueError
        await greet_and_send(message.from_user, "✅ Расписание удалено!", message=message)
        await state.clear()
    except ValueError:
        await greet_and_send(message.from_user, "⚠ Введите 0 или число от 1 до 6.", message=message)


@dp.callback_query(F.data == "admin_setchet")
async def admin_setchet_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в личных сообщениях админам", show_alert=True)
        return
    await greet_and_send(callback.from_user, "Введите четность (1 - нечетная, 2 - четная):", callback=callback)
    await state.set_state(SetChetState.week_type)
    await callback.answer()

@dp.message(SetChetState.week_type)
async def setchet_handler(message: types.Message, state: FSMContext):
    try:
        week_type = int(message.text)
        if week_type not in [1, 2]:
            raise ValueError

        await set_week_type(pool, DEFAULT_CHAT_ID, week_type)
        await greet_and_send(
            message.from_user,
            f"✅ Четность установлена: {week_type} ({'нечетная' if week_type==1 else 'четная'})",
            message=message
        )
        await state.clear()
    except ValueError:
        await greet_and_send(message.from_user, "⚠ Введите 1 или 2.", message=message)

# ======================
# Функция публикации расписания
# ======================
async def send_today_rasp():
    now = datetime.datetime.now(TZ)
    day = now.isoweekday()

    if day == 7:  # воскресенье
        day_to_post = 1  # понедельник
        target_date = now.date() + datetime.timedelta(days=1)
        day_name = "завтра (Понедельник)"
    else:
        day_to_post = day
        target_date = now.date()
        day_name = "сегодня"

    # получаем корректную четность недели
    week_type = await get_current_week_type(pool, DEFAULT_CHAT_ID, target_date)
    text = await get_rasp_for_day(pool, DEFAULT_CHAT_ID, day_to_post, week_type)

    if text:
        msg = f"📌 Расписание на {day_name}:\n\n" + format_rasp_message(day_to_post, week_type, text)
        await bot.send_message(DEFAULT_CHAT_ID, msg)



async def main():
    global pool
    pool = await get_pool()
    await init_db(pool)
    await ensure_columns(pool)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
