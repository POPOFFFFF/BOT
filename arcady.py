import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from typing import List, Tuple, Dict
import aiomysql
import random
import ssl
import re
import aiohttp
import io
from bs4 import BeautifulSoup

TOKEN = os.getenv("BOT_TOKEN")
CHAT_IDS_STR = os.getenv("CHAT_ID", "")
ALLOWED_CHAT_IDS = [int(x.strip()) for x in CHAT_IDS_STR.split(",") if x.strip()]
DEFAULT_CHAT_ID = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else 0
ALLOWED_USERS = [5228681344, 7620086223]
SPECIAL_USER_ID = []
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


def is_allowed_chat(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS

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
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS nicknames (
                user_id BIGINT PRIMARY KEY,
                nickname VARCHAR(255)
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS publish_times (
                id INT AUTO_INCREMENT PRIMARY KEY,
                hour INT NOT NULL,
                minute INT NOT NULL
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS anekdoty (
                id INT AUTO_INCREMENT PRIMARY KEY,
                text TEXT NOT NULL
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                rK BOOLEAN DEFAULT FALSE
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS special_users (
                user_id BIGINT PRIMARY KEY,
                signature VARCHAR(255) NOT NULL
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
            CREATE TABLE IF NOT EXISTS current_week_type (
                chat_id BIGINT PRIMARY KEY,
                week_type INT NOT NULL DEFAULT 1,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS teacher_messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                message_id BIGINT,
                from_user_id BIGINT,
                signature VARCHAR(255),
                message_text TEXT,
                message_type VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            await conn.commit()
async def ensure_columns(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM week_setting LIKE 'set_at'")
            row = await cur.fetchone()
            if not row:
                await cur.execute("ALTER TABLE week_setting ADD COLUMN set_at DATE")
async def set_nickname(pool, user_id: int, nickname: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO nicknames (user_id, nickname) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE nickname=%s
            """, (user_id, nickname, nickname))
async def get_nickname(pool, user_id: int) -> str | None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT nickname FROM nicknames WHERE user_id=%s", (user_id,))
            row = await cur.fetchone()
            return row[0] if row else None
async def add_publish_time(pool, hour: int, minute: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO publish_times (hour, minute) VALUES (%s, %s)", 
                (hour, minute)
            )
            await conn.commit() 
async def get_publish_times(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, hour, minute FROM publish_times ORDER BY hour, minute")
            rows = await cur.fetchall()
            return rows 
async def delete_publish_time(pool, pid: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM publish_times WHERE id=%s", (pid,))
async def clear_publish_times(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM publish_times")
async def set_week_type(pool, chat_id, week_type):
    today = datetime.datetime.now(TZ).date()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO week_setting (chat_id, week_type, set_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE week_type=%s, set_at=%s
            """, (chat_id, week_type, today, week_type, today))

async def load_special_users(pool):
    """Загружает список спец-пользователей из базы данных"""
    global SPECIAL_USER_ID
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT user_id FROM special_users")
            rows = await cur.fetchall()
            SPECIAL_USER_ID = [row[0] for row in rows]
    print(f"Загружено {len(SPECIAL_USER_ID)} спец-пользователей: {SPECIAL_USER_ID}")




@dp.message(Command("акик", "акick"))
async def cmd_admin_kick(message: types.Message):

    if not is_allowed_chat(message.chat.id):
        return

    # Проверяем ID пользователя
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    # Проверяем, что команда в групповом чате
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    # Проверяем, что бот админ в чате
    try:
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await message.answer("❌ Бот должен быть администратором в чате")
            return
    except Exception:
        await message.answer("❌ Ошибка проверки прав бота")
        return
    
    # Проверяем реплай
    if not message.reply_to_message:
        await message.answer("⚠ Использование: Ответьте на сообщение пользователя командой /акик")
        return
    
    try:
        user_id = message.reply_to_message.from_user.id
        user_to_kick = message.reply_to_message.from_user
        
        # Исключаем кик самого себя
        if user_id == message.from_user.id:
            await message.answer("❌ Нельзя кикнуть самого себя")
            return
        
        # Исключаем кик других админов из ALLOWED_USERS
        if user_id in ALLOWED_USERS:
            await message.answer("❌ Нельзя кикнуть другого администратора")
            return
        
        # Проверяем, не пытаемся ли кикнуть создателя чата
        try:
            target_member = await bot.get_chat_member(message.chat.id, user_id)
            if target_member.status == "creator":
                await message.answer("❌ Не могу кикнуть создателя чата")
                return
        except Exception as e:
            print(f"Ошибка проверки прав цели: {e}")
        
        # Выполняем кик
        await bot.ban_chat_member(message.chat.id, user_id)
        await message.answer(f"🚫 Пользователь {user_to_kick.first_name} (@{user_to_kick.username or 'нет'}) был кикнут администратором")
        
        # Разбаниваем через 30 секунд, чтобы можно было вернуться
        await asyncio.sleep(30)
        await bot.unban_chat_member(message.chat.id, user_id)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при кике: {e}")

@dp.message(Command("амут", "аmut"))
async def cmd_admin_mute(message: types.Message):
    # Проверяем ID пользователя

    if not is_allowed_chat(message.chat.id):
        return

    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    # Проверяем, что команда в групповом чате
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    # Проверяем, что бот админ в чате
    try:
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await message.answer("❌ Бот должен быть администратором в чате")
            return
    except Exception:
        await message.answer("❌ Ошибка проверки прав бота")
        return
    
    # Парсим аргументы
    args = message.text.split()
    
    # Проверяем минимальное количество аргументов
    if len(args) < 3:
        await message.answer(
            "⚠ Использование:\n"
            "• /амут 10 секунд (в ответ на сообщение)\n"
            "• /амут 2 часа (в ответ на сообщение)\n"
            "• /амут 30 минут (в ответ на сообщение)\n"
            "• /амут 1 день (в ответ на сообщение)\n\n"
            "Доступные единицы: секунды, минуты, часы, дни"
        )
        return
    
    # Проверяем реплай
    if not message.reply_to_message:
        await message.answer("⚠ Ответьте на сообщение пользователя, которого нужно замутить")
        return
    
    try:
        user_id = message.reply_to_message.from_user.id
        user_to_mute = message.reply_to_message.from_user
        
        # Исключаем мут самого себя
        if user_id == message.from_user.id:
            await message.answer("❌ Нельзя замутить самого себя")
            return
        
        # Исключаем мут других админов из ALLOWED_USERS
        if user_id in ALLOWED_USERS:
            await message.answer("❌ Нельзя замутить другого администратора")
            return
        
        # Проверяем, не пытаемся ли замутить создателя чата
        try:
            target_member = await bot.get_chat_member(message.chat.id, user_id)
            if target_member.status == "creator":
                await message.answer("❌ Не могу замутить создателя чата")
                return
        except Exception as e:
            print(f"Ошибка проверки прав цели: {e}")
        
        # Парсим время - берем второй и третий аргумент
        number_str = args[1]
        unit = args[2].lower()
        
        # Проверяем, что число валидно
        try:
            number = int(number_str)
        except ValueError:
            await message.answer("❌ Неверное число. Пример: /амут 10 секунд")
            return
        
        # Конвертируем в секунды
        duration = 0
        if unit in ['секунд', 'секунды', 'секунду', 'сек', 'с']:
            duration = number
        elif unit in ['минут', 'минуты', 'минуту', 'мин', 'м']:
            duration = number * 60
        elif unit in ['час', 'часа', 'часов', 'ч']:
            duration = number * 3600
        elif unit in ['день', 'дня', 'дней', 'дн']:
            duration = number * 86400
        else:
            await message.answer("❌ Неизвестная единица времени. Используйте: секунды, минуты, часы, дни")
            return
        
        # Проверяем максимальное время (30 дней)
        if duration > 2592000:  # 30 дней в секундах
            await message.answer("❌ Максимальное время мута - 30 дней")
            return
        
        # Проверяем минимальное время (10 секунд)
        if duration < 10:
            await message.answer("❌ Минимальное время мута - 10 секунд")
            return
        
        # Устанавливаем мут
        until_date = datetime.datetime.now() + datetime.timedelta(seconds=duration)
        
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_send_polls=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_change_info=False
            ),
            until_date=until_date
        )
        
        # Форматируем время для ответа
        time_display = format_duration(duration)
        await message.answer(f"🔇 Пользователь {user_to_mute.first_name} (@{user_to_mute.username or 'нет'}) замьючен на {time_display} администратором")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при муте: {e}")

@dp.message(Command("аразмут", "аunmute"))
async def cmd_admin_unmute(message: types.Message):

    if not is_allowed_chat(message.chat.id):
        return
    # Проверяем ID пользователя
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    # Проверяем, что команда в групповом чате
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    # Проверяем, что бот админ в чате
    try:
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await message.answer("❌ Бот должен быть администратором в чате")
            return
    except Exception:
        await message.answer("❌ Ошибка проверки прав бота")
        return
    
    # Проверяем реплай
    if not message.reply_to_message:
        await message.answer("⚠ Использование: Ответьте на сообщение пользователя командой /аразмут")
        return
    
    try:
        user_id = message.reply_to_message.from_user.id
        user_to_unmute = message.reply_to_message.from_user
        
        # Восстанавливаем все права
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
                can_invite_users=True,
                can_pin_messages=False,
                can_change_info=False
            )
        )
        
        await message.answer(f"🔊 Пользователь {user_to_unmute.first_name} (@{user_to_unmute.username or 'нет'}) размьючен администратором")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при размуте: {e}")

@dp.message(Command("аспам", "аspam"))
async def cmd_admin_spam_clean(message: types.Message):
    if not is_allowed_chat(message.chat.id):
        return

    # Проверяем ID пользователя
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    # Проверяем, что команда в групповом чате
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    # Проверяем реплай
    if not message.reply_to_message:
        await message.answer("⚠ Использование: Ответьте на спам-сообщение командой /аспам")
        return
    
    try:
        spam_user_id = message.reply_to_message.from_user.id
        spam_user = message.reply_to_message.from_user
        
        # Удаляем сообщение с командой
        await message.delete()
        
        # Удаляем спам-сообщение
        await message.reply_to_message.delete()
        
        # Кикаем спамера
        await bot.ban_chat_member(message.chat.id, spam_user_id)
        
        await message.answer(f"🧹 Спам от {spam_user.first_name} (@{spam_user.username or 'нет'}) удален, пользователь кикнут")
        
        # Разбаниваем через минуту
        await asyncio.sleep(60)
        await bot.unban_chat_member(message.chat.id, spam_user_id)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при очистке спама: {e}")


def format_duration(seconds: int) -> str:
    """Форматирует время в читаемый вид с правильным склонением"""
    if seconds < 60:
        if seconds == 1:
            return "1 секунду"
        elif 2 <= seconds <= 4:
            return f"{seconds} секунды"
        else:
            return f"{seconds} секунд"
    elif seconds < 3600:
        minutes = seconds // 60
        if minutes == 1:
            return "1 минуту"
        elif 2 <= minutes <= 4:
            return f"{minutes} минуты"
        else:
            return f"{minutes} минут"
    elif seconds < 86400:
        hours = seconds // 3600
        if hours == 1:
            return "1 час"
        elif 2 <= hours <= 4:
            return f"{hours} часа"
        else:
            return f"{hours} часов"
    else:
        days = seconds // 86400
        if days == 1:
            return "1 день"
        elif 2 <= days <= 4:
            return f"{days} дня"
        else:
            return f"{days} дней"


async def get_current_week_type(pool, chat_id: int) -> int:
    """Просто получаем текущую четность из базы"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT week_type FROM current_week_type WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                return row[0]
            else:
                # Если запись не существует, создаем по умолчанию нечетную неделю
                await cur.execute("INSERT INTO current_week_type (chat_id, week_type) VALUES (%s, %s)", (chat_id, 1))
                return 1

async def set_current_week_type(pool, chat_id: int, week_type: int):
    """Устанавливаем четность недели"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO current_week_type (chat_id, week_type) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE week_type=%s, updated_at=CURRENT_TIMESTAMP
            """, (chat_id, week_type, week_type))


async def save_teacher_message(pool, message_id: int, from_user_id: int, 
                              signature: str, message_text: str, message_type: str):
    """Сохраняет сообщение преподавателя (без привязки к чату)"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO teacher_messages (message_id, from_user_id, signature, message_text, message_type)
                VALUES (%s, %s, %s, %s, %s)
            """, (message_id, from_user_id, signature, message_text, message_type))

async def get_teacher_messages(pool, offset: int = 0, limit: int = 10) -> List[Tuple]:
    """Получает сообщения преподавателей (все чаты)"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, message_id, signature, message_text, message_type, created_at
                FROM teacher_messages 
                ORDER BY created_at DESC 
                LIMIT %s OFFSET %s
            """, (limit, offset))
            return await cur.fetchall()

async def get_teacher_messages_count(pool) -> int:
    """Получает общее количество сообщений преподавателей"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM teacher_messages")
            result = await cur.fetchone()
            return result[0] if result else 0




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

class ViewMessagesState(StatesGroup):
    browsing = State()
class SendMessageState(StatesGroup):
    active = State()
class SetChetState(StatesGroup):
    week_type = State()
class AddSubjectState(StatesGroup):
    name = State()
    type_choice = State()
    cabinet = State()
class DeleteTeacherMessageState(StatesGroup):
    message_id = State()
class DeleteSubjectState(StatesGroup):
    subject_choice = State()

class AddSpecialUserState(StatesGroup):
    user_id = State()
    signature = State()

class SetPublishTimeState(StatesGroup):
    time = State()  

class AddLessonState(StatesGroup):
    subject = State()
    week_type = State()
    day = State()
    pair_number = State()
    cabinet = State()

class SetCabinetState(StatesGroup):
    week_type = State()
    day = State()
    lesson = State()
    cabinet = State()
    pair_num = State()

class SetCabinetState(StatesGroup):
    week_type = State()
    day = State()
    subject = State()
    pair_number = State()
    cabinet = State()
class ClearPairState(StatesGroup):
    week_type = State()
    day = State()
    pair_number = State()
class ForwardModeState(StatesGroup):
    active = State()


async def get_special_user_signature(pool, user_id: int) -> str | None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT signature FROM special_users WHERE user_id=%s", (user_id,))
            row = await cur.fetchone()
            return row[0] if row else None

async def set_special_user_signature(pool, user_id: int, signature: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO special_users (user_id, signature) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE signature=%s
            """, (user_id, signature, signature))

async def delete_teacher_message(pool, message_id: int) -> bool:
    """Удаляет сообщение преподавателя по ID (из всех чатов)"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM teacher_messages WHERE id = %s", (message_id,))
            await conn.commit()
            return cur.rowcount > 0

@dp.callback_query(F.data == "send_message_chat")
async def send_message_chat_start(callback: types.CallbackQuery, state: FSMContext):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
    if callback.from_user.id not in SPECIAL_USER_ID or callback.message.chat.type != "private":
        await callback.answer("⛔ Доступно только конкретному пользователю", show_alert=True)
        return

    # Получаем подпись пользователя
    signature = await get_special_user_signature(pool, callback.from_user.id)
    if not signature:
        signature = "ПРОВЕРКА"  # значение по умолчанию

    await state.update_data(
        signature=signature,
        start_time=datetime.datetime.now(TZ)
    )
    
    # Активируем режим пересылки на 180 секунд
    await state.set_state(SendMessageState.active)
    
    # Сообщаем о начале режима с кнопкой отмены
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹️ Закончить пересылку", callback_data="stop_forward_mode")]
    ])
    
    await callback.message.edit_text(
        f"✅ Режим пересылки активирован на 180 секунд!\n"
        f"📝 Подпись: {signature}\n"
        f"⏰ Время до: {(datetime.datetime.now(TZ) + datetime.timedelta(seconds=180)).strftime('%H:%M:%S')}\n\n"
        f"Все ваши сообщения будут пересылаться в беседу. Режим автоматически отключится через 3 минуты.",
        reply_markup=kb
    )
    
    # Запускаем таймер отключения
    asyncio.create_task(disable_forward_mode_after_timeout(callback.from_user.id, state))
    
    await callback.answer()

async def send_message_to_all_chats(message_text: str, photo=None, document=None, video=None, audio=None, voice=None, sticker=None, caption: str = ""):
    """Отправляет сообщение во все разрешенные чаты"""
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            if photo:
                await bot.send_photo(chat_id, photo, caption=message_text + caption)
            elif document:
                await bot.send_document(chat_id, document, caption=message_text + caption)
            elif video:
                await bot.send_video(chat_id, video, caption=message_text + caption)
            elif audio:
                await bot.send_audio(chat_id, audio, caption=message_text + caption)
            elif voice:
                await bot.send_voice(chat_id, voice, caption=message_text + caption)
            elif sticker:
                await bot.send_sticker(chat_id, sticker)
            else:
                await bot.send_message(chat_id, message_text + caption)
        except Exception as e:
            print(f"Ошибка отправки сообщения в чат {chat_id}: {e}")

async def save_teacher_message_to_all_chats(message_ids: dict, from_user_id: int, signature: str, message_text: str, message_type: str):
    """Сохраняет сообщение преподавателя для всех чатов"""
    for chat_id, message_id in message_ids.items():
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO teacher_messages (chat_id, message_id, from_user_id, signature, message_text, message_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (chat_id, message_id, from_user_id, signature, message_text, message_type))

# Обработчик кнопки остановки пересылки
@dp.callback_query(F.data == "stop_forward_mode")
async def stop_forward_mode_handler(callback: types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state == SendMessageState.active.state:
        await state.clear()
        await callback.message.edit_text("⏹️ Режим пересылки досрочно завершен.")
    else:
        await callback.answer("❌ Режим пересылки не активен", show_alert=True)
    await callback.answer()

@dp.message(SendMessageState.active)
async def process_forward_message(message: types.Message, state: FSMContext):
    # Фильтрация сообщений, начинающихся с /
    if message.text and message.text.startswith('/'):
        await message.answer("❌ Сообщения, начинающиеся с /, не отправляются.")
        return
    
    data = await state.get_data()
    signature = data.get("signature", "ПРОВЕРКА")
    
    prefix = f"Сообщение от {signature}: "

    try:
        message_text = ""
        message_type = "text"
        sent_message_ids = []  # Список для хранения ID отправленных сообщений
        
        if message.text:
            message_text = message.text
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_message(chat_id, f"{prefix}{message.text}")
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки в чат {chat_id}: {e}")
                    
        elif message.photo:
            message_text = message.caption or ""
            message_type = "photo"
            if message.caption and message.caption.startswith('/'):
                await message.answer("❌ Подписи к фото, начинающиеся с /, не отправляются.")
                return
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_photo(chat_id, message.photo[-1].file_id, caption=prefix + (message.caption or ""))
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки фото в чат {chat_id}: {e}")
                    
        elif message.document:
            message_text = message.caption or ""
            message_type = "document"
            if message.caption and message.caption.startswith('/'):
                await message.answer("❌ Подписи к документам, начинающиеся с /, не отправляются.")
                return
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_document(chat_id, message.document.file_id, caption=prefix + (message.caption or ""))
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки документа в чат {chat_id}: {e}")
                    
        elif message.video:
            message_text = message.caption or ""
            message_type = "video"
            if message.caption and message.caption.startswith('/'):
                await message.answer("❌ Подписи к видео, начинающиеся с /, не отправляются.")
                return
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_video(chat_id, message.video.file_id, caption=prefix + (message.caption or ""))
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки видео в чат {chat_id}: {e}")
                    
        elif message.audio:
            message_text = message.caption or ""
            message_type = "audio"
            if message.caption and message.caption.startswith('/'):
                await message.answer("❌ Подписи к аудио, начинающиеся с /, не отправляются.")
                return
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_audio(chat_id, message.audio.file_id, caption=prefix + (message.caption or ""))
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки аудио в чат {chat_id}: {e}")
                    
        elif message.voice:
            message_text = "голосовое сообщение"
            message_type = "voice"
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_voice(chat_id, message.voice.file_id, caption=prefix)
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки голосового сообщения в чат {chat_id}: {e}")
                    
        elif message.sticker:
            message_text = "стикер"
            message_type = "sticker"
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_sticker(chat_id, message.sticker.file_id)
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки стикера в чат {chat_id}: {e}")
                    
        else:
            await message.answer("⚠ Не удалось распознать тип сообщения.")
            return

        # Сохраняем сообщение в базу ОДИН РАЗ (без привязки к чату)
        # Используем первый успешный message_id для сохранения
        if sent_message_ids:
            await save_teacher_message(
                pool, 
                sent_message_ids[0],  # Используем первый ID
                message.from_user.id,
                signature,
                message_text,
                message_type
            )

        success_chats = len(sent_message_ids)
        total_chats = len(ALLOWED_CHAT_IDS)
        await message.answer(f"✅ Сообщение переслано в {success_chats} из {total_chats} бесед!")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при пересылке: {e}")


@dp.callback_query(F.data == "view_teacher_messages")
async def view_teacher_messages_start(callback: types.CallbackQuery, state: FSMContext):
    # Разрешаем просмотр в разрешенных чатах
    if callback.message.chat.id not in ALLOWED_CHAT_IDS:
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    # Проверяем, что это групповой чат
    if callback.message.chat.type not in ["group", "supergroup"]:
        await callback.answer("⛔ Эта функция доступна только в беседе", show_alert=True)
        return

    await show_teacher_messages_page(callback, state, page=0)
    await callback.answer()


@dp.callback_query(F.data == "menu_back_from_messages")
async def menu_back_from_messages_handler(callback: types.CallbackQuery, state: FSMContext):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
    await menu_back_handler(callback, state)


async def show_teacher_messages_page(callback: types.CallbackQuery, state: FSMContext, page: int = 0):
    limit = 10
    offset = page * limit
    
    # Получаем сообщения для всех чатов
    messages = await get_teacher_messages(pool, offset, limit)
    total_count = await get_teacher_messages_count(pool)
    
    if not messages:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await callback.message.edit_text(
            "📝 Сообщения от преподавателей\n\n"
            "Пока нет сохраненных сообщений от преподавателей.",
            reply_markup=kb
        )
        return
    
    # Создаем клавиатуру с сообщениями
    keyboard = []
    for i, (msg_id, message_id, signature, text, msg_type, created_at) in enumerate(messages):
        # Обрезаем длинный текст
        display_text = text[:50] + "..." if len(text) > 50 else text
        if not display_text:
            display_text = f"{msg_type} сообщение"
        
        emoji = "📝" if msg_type == "text" else "🖼️" if msg_type == "photo" else "📎" if msg_type == "document" else "🎵"
        button_text = f"{emoji} {signature}: {display_text}"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"view_message_{msg_id}"
        )])
    
    # Добавляем кнопки навигации
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅ Назад", callback_data=f"messages_page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text="🔙 В меню", callback_data="menu_back"))
    
    if (page + 1) * limit < total_count:
        nav_buttons.append(InlineKeyboardButton(text="Дальше ➡", callback_data=f"messages_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    page_info = f" (страница {page + 1})" if total_count > limit else ""
    await callback.message.edit_text(
        f"📝 Сообщения от преподавателей{page_info}\n\n"
        f"Всего сообщений: {total_count}\n"
        f"Выберите сообщение для просмотра:",
        reply_markup=kb
    )
    
    await state.update_data(current_page=page)

@dp.callback_query(F.data.startswith("view_message_"))
async def view_specific_message(callback: types.CallbackQuery):
    try:
        message_db_id = int(callback.data.split("_")[2])
        current_chat_id = callback.message.chat.id
        
        # Получаем информацию о сообщении
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT message_id, signature, message_text, message_type, created_at
                    FROM teacher_messages 
                    WHERE id = %s
                """, (message_db_id,))
                
                message_data = await cur.fetchone()
        
        if not message_data:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return
        
        message_id, signature, text, msg_type, created_at = message_data
        
        # Форматируем дату
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            date_str = str(created_at)
        
        # Создаем ссылку на сообщение в ТЕКУЩЕЙ беседе
        message_link = f"https://t.me/c/{str(current_chat_id).replace('-100', '')}/{message_id}"
        
        # Создаем клавиатуру
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Перейти к сообщению", url=message_link)],
            [InlineKeyboardButton(text="⬅ Назад к списку", callback_data="back_to_messages_list")]
        ])
        
        # Формируем текст сообщения
        message_info = f"👨‍🏫 От: {signature}\n"
        message_info += f"📅 Дата: {date_str}\n"
        message_info += f"📊 Тип: {msg_type}\n\n"
        
        if text and text != "голосовое сообщение" and text != "стикер":
            message_info += f"📝 Текст: {text}\n\n"
        
        message_info += "Нажмите кнопку ниже чтобы перейти к сообщению в беседе."
        
        await callback.message.edit_text(message_info, reply_markup=kb)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    await callback.answer()
async def show_teacher_messages_page(callback: types.CallbackQuery, state: FSMContext, page: int = 0):
    limit = 10
    offset = page * limit
    
    # Получаем сообщения для всех чатов
    messages = await get_teacher_messages(pool, offset, limit)
    total_count = await get_teacher_messages_count(pool)
    
    if not messages:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await callback.message.edit_text(
            "📝 Сообщения от преподавателей\n\n"
            "Пока нет сохраненных сообщений от преподавателей.",
            reply_markup=kb
        )
        return
    
    # Создаем клавиатуру с сообщениями
    keyboard = []
    for i, (msg_id, message_id, signature, text, msg_type, created_at) in enumerate(messages):
        # Обрезаем длинный текст
        display_text = text[:50] + "..." if len(text) > 50 else text
        if not display_text:
            display_text = f"{msg_type} сообщение"
        
        emoji = "📝" if msg_type == "text" else "🖼️" if msg_type == "photo" else "📎" if msg_type == "document" else "🎵"
        button_text = f"{emoji} {signature}: {display_text}"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"view_message_{msg_id}"
        )])
    
    # Добавляем кнопки навигации
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅ Назад", callback_data=f"messages_page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text="🔙 В меню", callback_data="menu_back"))
    
    if (page + 1) * limit < total_count:
        nav_buttons.append(InlineKeyboardButton(text="Дальше ➡", callback_data=f"messages_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    page_info = f" (страница {page + 1})" if total_count > limit else ""
    await callback.message.edit_text(
        f"📝 Сообщения от преподавателей{page_info}\n\n"
        f"Всего сообщений: {total_count}\n"
        f"Выберите сообщение для просмотра:",
        reply_markup=kb
    )
    
    await state.update_data(current_page=page)

@dp.callback_query(F.data.startswith("view_message_"))
async def view_specific_message(callback: types.CallbackQuery):
    try:
        message_db_id = int(callback.data.split("_")[2])
        current_chat_id = callback.message.chat.id
        
        # Получаем информацию о сообщении
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT message_id, signature, message_text, message_type, created_at
                    FROM teacher_messages 
                    WHERE id = %s
                """, (message_db_id,))
                
                message_data = await cur.fetchone()
        
        if not message_data:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return
        
        message_id, signature, text, msg_type, created_at = message_data
        
        # Форматируем дату
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            date_str = str(created_at)
        
        # Создаем ссылку на сообщение в ТЕКУЩЕЙ беседе
        message_link = f"https://t.me/c/{str(current_chat_id).replace('-100', '')}/{message_id}"
        
        # Создаем клавиатуру
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Перейти к сообщению", url=message_link)],
            [InlineKeyboardButton(text="⬅ Назад к списку", callback_data="back_to_messages_list")]
        ])
        
        # Формируем текст сообщения
        message_info = f"👨‍🏫 От: {signature}\n"
        message_info += f"📅 Дата: {date_str}\n"
        message_info += f"📊 Тип: {msg_type}\n\n"
        
        if text and text != "голосовое сообщение" and text != "стикер":
            message_info += f"📝 Текст: {text}\n\n"
        
        message_info += "Нажмите кнопку ниже чтобы перейти к сообщению в беседе."
        
        await callback.message.edit_text(message_info, reply_markup=kb)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data == "back_to_messages_list")
async def back_to_messages_list(callback: types.CallbackQuery, state: FSMContext):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
    data = await state.get_data()
    current_page = data.get('current_page', 0)
    await show_teacher_messages_page(callback, state, current_page)
    await callback.answer()


@dp.callback_query(F.data == "admin_add_special_user")
async def admin_add_special_user_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])

    await callback.message.edit_text(
        "👤 Добавление спец-пользователя\n\n"
        "Введите Telegram ID пользователя (только цифры):",
        reply_markup=kb
    )
    await state.set_state(AddSpecialUserState.user_id)
    await callback.answer()

@dp.message(AddSpecialUserState.user_id)
async def process_special_user_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        if user_id <= 0:
            raise ValueError("ID должен быть положительным числом")
        
        await state.update_data(user_id=user_id)
        await message.answer(
            f"✅ ID пользователя: {user_id}\n\n"
            "Теперь введите подпись для этого пользователя "
            "(как будет отображаться при отправке сообщений):"
        )
        await state.set_state(AddSpecialUserState.signature)
        
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите только цифры:")



@dp.message(AddSpecialUserState.signature)
async def process_special_user_signature(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data["user_id"]
    signature = message.text.strip()
    
    if not signature:
        await message.answer("❌ Подпись не может быть пустой. Введите подпись:")
        return
    
    try:
        # Добавляем пользователя в базу
        await set_special_user_signature(pool, user_id, signature)
        
        # Обновляем список SPECIAL_USER_ID для текущей сессии
        if user_id not in SPECIAL_USER_ID:
            SPECIAL_USER_ID.append(user_id)
        
        await message.answer(
            f"✅ Спец-пользователь добавлен!\n\n"
            f"👤 ID: {user_id}\n"
            f"📝 Подпись: {signature}\n\n"
            f"Пользователь теперь может отправлять сообщения в беседу через кнопку в меню."
        )
        
        # Показываем админ-меню
        await message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении пользователя: {e}")
    
    await state.clear()


def get_zvonki(is_saturday: bool):
    return "\n".join(ZVONKI_SATURDAY if is_saturday else ZVONKI_DEFAULT)

def main_menu(is_admin=False, is_special_user=False, is_group_chat=False):
    buttons = []
    
    # Добавляем кнопку просмотра сообщений только в беседе
    if is_group_chat:
        buttons.append([InlineKeyboardButton(text="👨‍🏫 Посмотреть сообщения преподов", callback_data="view_teacher_messages")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание", callback_data="menu_rasp")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание на сегодня", callback_data="today_rasp")]),  # Новая кнопка
        buttons.append([InlineKeyboardButton(text="📅 Расписание на завтра", callback_data="tomorrow_rasp")]),
        buttons.append([InlineKeyboardButton(text="⏰ Звонки", callback_data="menu_zvonki")]),
        buttons.append([InlineKeyboardButton(text="🌤️ Узнать погоду", callback_data="menu_weather")])

    
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙ Админка", callback_data="menu_admin")])
    if is_special_user:
        buttons.append([InlineKeyboardButton(text="✉ Отправить сообщение в беседу", callback_data="send_message_chat")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Установить четность", callback_data="admin_setchet")],
        [InlineKeyboardButton(text="📌 Узнать четность недели", callback_data="admin_show_chet")],

        [InlineKeyboardButton(text="🕒 Время публикаций", callback_data="admin_list_publish_times")],
        [InlineKeyboardButton(text="📝 Задать время публикации", callback_data="admin_set_publish_time")],
        [InlineKeyboardButton(text="🕐 Узнать мое время", callback_data="admin_my_publish_time")],

        [InlineKeyboardButton(text="➕ Добавить пару", callback_data="admin_add_lesson")],
        [InlineKeyboardButton(text="🧹 Очистить пару", callback_data="admin_clear_pair")],

        [InlineKeyboardButton(text="🏫 Установить кабинет", callback_data="admin_set_cabinet")],

        [InlineKeyboardButton(text="📚 Добавить предмет", callback_data="admin_add_subject")],
        [InlineKeyboardButton(text="🗑️ Удалить предмет", callback_data="admin_delete_subject")],

        [InlineKeyboardButton(text="👤 Добавить спец-пользователя", callback_data="admin_add_special_user")],
        [InlineKeyboardButton(text="🗑️ Удалить сообщение преподавателя", callback_data="admin_delete_teacher_message")],  # Новая кнопка
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    return kb

@dp.callback_query(F.data == "today_rasp")
async def today_rasp_handler(callback: types.CallbackQuery):
    # Проверяем, что запрос из разрешенного чата
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
    
    # Используем chat_id из callback
    chat_id = callback.message.chat.id
    
    now = datetime.datetime.now(TZ)
    target_date = now.date()
    day_to_show = now.isoweekday()
    
    # Если сегодня воскресенье, показываем понедельник
    if day_to_show == 7:
        target_date += datetime.timedelta(days=1)
        day_to_show = 1
        day_name = "завтра (Понедельник)"
    else:
        day_name = "сегодня"
    
    # Получаем тип недели для конкретного чата
    week_type = await get_current_week_type(pool, chat_id, target_date)
    
    # Получаем расписание для конкретного чата
    text = await get_rasp_formatted(day_to_show, week_type, chat_id)
    
    # Формируем сообщение
    day_names = {
        1: "Понедельник",
        2: "Вторник", 
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота"
    }
    
    week_name = "нечетная" if week_type == 1 else "четная"
    message = f"📅 Расписание на {day_name} ({day_names[day_to_show]}) | Неделя: {week_name}\n\n{text}"
    
    # Добавляем анекдот
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                message += f"\n\n😂 Анекдот:\n{row[0]}"
    
    # Отправляем сообщение с кнопкой "Назад"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await greet_and_send(callback.from_user, message, callback=callback, markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "menu_weather")
async def menu_weather_handler(callback: types.CallbackQuery):
    """Обработчик кнопки погоды в главном меню"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌤️ Погода на сегодня", callback_data="weather_today")],
        [InlineKeyboardButton(text="🌤️ Погода на завтра", callback_data="weather_tomorrow")],
        [InlineKeyboardButton(text="📅 Погода на 7 дней", callback_data="weather_week")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await greet_and_send(
        callback.from_user,
        "🌤️ Выберите период для прогноза погоды:",
        callback=callback,
        markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("weather_"))
async def weather_period_handler(callback: types.CallbackQuery):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
    """Обработчик выбора периода погоды"""
    period = callback.data
    
    # Показываем сообщение о загрузке
    await callback.message.edit_text("🌤️ Получаю актуальные данные о погоде...")
    
    try:
        if period == "weather_today":
            weather_data = await get_weather_today_formatted()
            title = "🌤️ Погода в Омске на сегодня"
        elif period == "weather_tomorrow":
            weather_data = await get_weather_tomorrow_formatted()
            title = "🌤️ Погода в Омске на завтра"
        elif period == "weather_week":
            weather_data = await get_weather_week_formatted()
            title = "📅 Погода в Омске на 7 дней"
        else:
            await callback.answer("❌ Неизвестный период", show_alert=True)
            return
        
        message = f"{title}\n\n{weather_data}"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌤️ Выбрать другой период", callback_data="menu_weather")],
            [InlineKeyboardButton(text="⬅ Назад в меню", callback_data="menu_back")]
        ])
        
        await callback.message.edit_text(message, reply_markup=kb)
        
    except Exception as e:
        error_message = f"❌ Ошибка при получении погоды: {str(e)}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_weather")]
        ])
        await callback.message.edit_text(error_message, reply_markup=kb)
    
    await callback.answer()


async def get_weather_today_formatted() -> str:
    """Красивый формат погоды на сегодня"""
    try:
        soup = await get_weather_soup()
        if not soup:
            return "❌ Не удалось получить данные"
        
        result = "📊 Сейчас:\n"
        
        # Текущая температура
        temp = await extract_current_temp(soup)
        if temp:
            result += f"🌡 {temp}\n"
        
        # Ощущается как
        feels_like = await extract_feels_like(soup)
        if feels_like:
            result += f"💭 {feels_like}\n"
        
        # Ветер
        wind = await extract_wind(soup)
        if wind:
            result += f"💨 {wind}\n"
        
        # Давление и влажность
        pressure = await extract_pressure(soup)
        humidity = await extract_humidity(soup)
        
        if pressure and humidity:
            result += f"📊 {pressure}, {humidity}\n"
        
        result += "\n📈 По времени суток:\n"
        
        # Прогноз по времени
        time_forecast = await extract_time_forecast(soup)
        if time_forecast:
            result += time_forecast
        else:
            result += "• Данные временно недоступны\n"
        
        return result
        
    except Exception as e:
        print(f"Ошибка форматирования сегодняшней погоды: {e}")
        return "❌ Не удалось получить данные на сегодня"

async def get_weather_tomorrow_formatted() -> str:
    """Красивый формат погоды на завтра"""
    try:
        soup = await get_weather_soup()
        if not soup:
            return "❌ Не удалось получить данные"
        
        result = "📅 Завтра:\n\n"
        
        # Ищем данные на завтра
        tomorrow_data = await extract_tomorrow_data(soup)
        if tomorrow_data:
            result += tomorrow_data
        else:
            # Альтернативный метод
            result += await extract_tomorrow_alternative(soup)
        
        return result
        
    except Exception as e:
        print(f"Ошибка форматирования завтрашней погоды: {e}")
        return "❌ Не удалось получить данные на завтра"

async def get_weather_week_formatted() -> str:
    """Красивый формат погоды на неделю"""
    try:
        soup = await get_weather_soup()
        if not soup:
            return "❌ Не удалось получить данные"
        
        result = "📅 На неделю:\n\n"
        
        weekly_data = await extract_weekly_data(soup)
        if weekly_data:
            result += weekly_data
        else:
            result += "📊 Данные на неделю временно недоступны\n\n"
            result += "💡 Используйте приложение погоды для подробного прогноза"
        
        return result
        
    except Exception as e:
        print(f"Ошибка форматирования недельной погоды: {e}")
        return "❌ Не удалось получить данные на неделю"


async def get_weather_soup():
    """Получает BeautifulSoup объект с данными погоды"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8'
        }
        
        url = "https://yandex.ru/pogoda/omsk"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    return None
                html = await response.text()
        
        return BeautifulSoup(html, 'html.parser')
    except Exception:
        return None

async def extract_current_temp(soup) -> str:
    """Извлекает текущую температуру"""
    try:
        # Попробуем разные селекторы
        selectors = [
            '.temp__value',
            '[class*="temp__value"]',
            '[class*="current-weather__temp"]',
            '.weather__temp'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                temp = elem.text.strip().replace('−', '-')
                return f"{temp}°C"
        
        return None
    except Exception:
        return None

async def extract_feels_like(soup) -> str:
    """Извлекает 'ощущается как'"""
    try:
        # Ищем текст с "ощущается"
        elements = soup.find_all(string=re.compile(r'ощущается', re.IGNORECASE))
        for elem in elements:
            parent = elem.parent
            if parent:
                text = parent.get_text(strip=True)
                # Упрощаем текст
                if 'ощущается' in text.lower():
                    # Извлекаем только числовое значение
                    temp_match = re.search(r'[+-]?\d+°', text)
                    if temp_match:
                        return f"Ощущается как {temp_match.group()}"
        return None
    except Exception:
        return None

async def extract_condition(soup) -> str:
    """Извлекает описание погоды"""
    try:
        selectors = [
            '[class*="condition"]',
            '[class*="weather__condition"]',
            '[class*="description"]'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                text = elem.text.strip()
                if len(text) < 50:  # Не слишком длинный текст
                    return text.capitalize()
        return None
    except Exception:
        return None

async def extract_wind(soup) -> str:
    """Извлекает данные о ветре"""
    try:
        elements = soup.find_all(string=re.compile(r'ветер|wind', re.IGNORECASE))
        for elem in elements:
            parent = elem.parent
            if parent:
                text = parent.get_text(strip=True)
                # Упрощаем текст
                if 'ветер' in text.lower():
                    # Ищем скорость ветра
                    wind_match = re.search(r'(\d+[,.]?\d*)\s*м/с', text)
                    if wind_match:
                        return f"Ветер {wind_match.group(1)} м/с"
        return None
    except Exception:
        return None

async def extract_pressure(soup) -> str:
    """Извлекает давление"""
    try:
        elements = soup.find_all(string=re.compile(r'давление|pressure', re.IGNORECASE))
        for elem in elements:
            parent = elem.parent
            if parent:
                text = parent.get_text(strip=True)
                if 'давление' in text.lower():
                    # Ищем значение давления
                    press_match = re.search(r'(\d+)\s*мм', text)
                    if press_match:
                        return f"Давление {press_match.group(1)} мм"
        return None
    except Exception:
        return None

async def extract_humidity(soup) -> str:
    """Извлекает влажность"""
    try:
        elements = soup.find_all(string=re.compile(r'влажность|humidity', re.IGNORECASE))
        for elem in elements:
            parent = elem.parent
            if parent:
                text = parent.get_text(strip=True)
                if 'влажность' in text.lower():
                    # Ищем значение влажности
                    hum_match = re.search(r'(\d+)%', text)
                    if hum_match:
                        return f"Влажность {hum_match.group(1)}%"
        return None
    except Exception:
        return None

async def extract_time_forecast(soup) -> str:
    """Извлекает прогноз по времени суток"""
    try:
        result = ""
        
        # Ищем блоки с утром/днем/вечером/ночью
        time_periods = {
            'утром': '🌅 Утро',
            'днем': '☀ День', 
            'вечером': '🌇 Вечер',
            'ночью': '🌙 Ночь'
        }
        
        for period_ru, period_emoji in time_periods.items():
            elements = soup.find_all(string=re.compile(period_ru, re.IGNORECASE))
            for elem in elements:
                parent_text = elem.parent.get_text(strip=True) if elem.parent else ""
                # Ищем температуру в тексте
                temp_match = re.search(r'([+-]?\d+)°', parent_text)
                if temp_match:
                    result += f"• {period_emoji}: {temp_match.group(1)}°C\n"
                    break
        
        return result if result else None
    except Exception:
        return None

async def extract_tomorrow_data(soup) -> str:
    """Извлекает данные на завтра"""
    try:
        # Ищем завтрашний день
        elements = soup.find_all(string=re.compile(r'завтра|tomorrow', re.IGNORECASE))
        
        for elem in elements:
            parent = elem.parent
            if parent:
                # Ищем температуру в родительском элементе
                parent_text = parent.get_text()
                temp_matches = re.findall(r'([+-]?\d+)°', parent_text)
                
                if len(temp_matches) >= 2:
                    day_temp = temp_matches[0]
                    night_temp = temp_matches[1]
                    
                    result = f"🌅 Днем: {day_temp}°C\n"
                    result += f"🌙 Ночью: {night_temp}°C\n\n"
                    
                    # Ищем описание погоды
                    condition_match = re.search(r'([а-яё]+(?:\s+[а-яё]+){0,3})', parent_text.lower())
                    if condition_match and 'завтра' not in condition_match.group(1):
                        result += f"☁ {condition_match.group(1).capitalize()}\n"
                    
                    return result
        
        return "📊 Данные на завтра временно недоступны\n\n💡 Используйте приложение погоды для точного прогноза"
    except Exception:
        return "❌ Не удалось получить данные на завтра"

async def extract_tomorrow_alternative(soup) -> str:
    """Альтернативный метод получения данных на завтра"""
    try:
        # Ищем все температурные данные
        all_text = soup.get_text()
        temp_matches = re.findall(r'([+-]?\d+)°', all_text)
        
        if len(temp_matches) >= 4:
            # Предполагаем, что первые 4 значения - сегодня и завтра
            tomorrow_day = temp_matches[2] if len(temp_matches) > 2 else "?"
            tomorrow_night = temp_matches[3] if len(temp_matches) > 3 else "?"
            
            result = f"🌅 Днем: {tomorrow_day}°C\n"
            result += f"🌙 Ночью: {tomorrow_night}°C\n\n"
            result += "💡 Примерный прогноз, уточните в приложении погоды"
            
            return result
        
        return "📊 Данные на завтра временно недоступны"
    except Exception:
        return "❌ Не удалось получить данные на завтра"

async def extract_weekly_data(soup) -> str:
    """Извлекает данные на неделю"""
    try:
        # Ищем все температурные данные
        all_text = soup.get_text()
        temp_matches = re.findall(r'([+-]?\d+)°', all_text)
        
        if len(temp_matches) >= 14:
            result = ""
            days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            
            for i in range(7):
                if i * 2 + 1 < len(temp_matches):
                    day_temp = temp_matches[i * 2]
                    night_temp = temp_matches[i * 2 + 1]
                    result += f"• {days[i]}: {day_temp}° / {night_temp}°\n"
            
            return result
        else:
            return None
    except Exception:
        return None

@dp.callback_query(F.data == "admin_add_lesson")
async def admin_add_lesson_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM subjects")
            subjects = await cur.fetchall()
    
    buttons = []
    for subj in subjects:
        buttons.append([InlineKeyboardButton(text=subj[0], callback_data=f"choose_subject_{subj[0]}")])
    
    # Добавляем кнопку отмены
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text("Выберите предмет:", reply_markup=kb)
    await state.set_state(AddLessonState.subject)

# Добавляем кнопки отмены на каждом шаге
@dp.callback_query(F.data.startswith("choose_subject_"))
async def choose_subject(callback: types.CallbackQuery, state: FSMContext):
    subject = callback.data[len("choose_subject_"):]
    await state.update_data(subject=subject)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    await callback.message.edit_text("Выберите четность недели:", reply_markup=kb)
    await state.set_state(AddLessonState.week_type)

@dp.callback_query(F.data.startswith("week_"))
async def choose_week(callback: types.CallbackQuery, state: FSMContext):
    week_type = int(callback.data[-1])
    await state.update_data(week_type=week_type)
    
    buttons = []
    for i, day in enumerate(DAYS):
        buttons.append([InlineKeyboardButton(text=day, callback_data=f"day_{i+1}")])
    
    # Добавляем кнопку отмены
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text("Выберите день недели:", reply_markup=kb)
    await state.set_state(AddLessonState.day)

@dp.callback_query(F.data.startswith("day_"))
async def choose_day(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data[len("day_"):])
    await state.update_data(day=day)
    
    buttons = []
    for i in range(1, 7):
        buttons.append([InlineKeyboardButton(text=str(i), callback_data=f"pair_{i}")])
    
    # Добавляем кнопку отмены
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text("Выберите номер пары:", reply_markup=kb)
    await state.set_state(AddLessonState.pair_number)


@dp.callback_query(F.data == "admin_add_subject")
async def admin_add_subject_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])

    await callback.message.edit_text(
        "📚 Добавление нового предмета\n\n"
        "Введите название предмета:",
        reply_markup=kb
    )
    await state.set_state(AddSubjectState.name)
    await callback.answer()

@dp.message(AddSubjectState.name)
async def process_subject_name(message: types.Message, state: FSMContext):
    subject_name = message.text.strip()
    
    # Добавляем проверку на команду отмены
    if subject_name.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
        
    if not subject_name:
        await message.answer("❌ Название предмета не может быть пустым. Введите название:")
        return
    
    await state.update_data(name=subject_name)
    
    # Предлагаем выбрать тип предмета с кнопкой отмены
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏫 С фиксированным кабинетом", callback_data="subject_type_fixed")],
        [InlineKeyboardButton(text="🔢 С запросом кабинета (rK)", callback_data="subject_type_rk")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await message.answer(
        f"📝 Предмет: {subject_name}\n\n"
        "Выберите тип предмета:",
        reply_markup=kb
    )
    await state.set_state(AddSubjectState.type_choice)

@dp.message(AddSubjectState.cabinet)
async def process_subject_cabinet(message: types.Message, state: FSMContext):
    cabinet = message.text.strip()
    
    # Добавляем проверку на команду отмены
    if cabinet.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
        
    data = await state.get_data()
    subject_name = data["name"]
    
    if not cabinet:
        await message.answer("❌ Номер кабинета не может быть пустым. Введите кабинет:")
        return
    
    # Формируем полное название предмета с кабинетом
    full_subject_name = f"{subject_name} {cabinet}"
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO subjects (name, rK) VALUES (%s, %s)", (full_subject_name, False))
    
    await message.answer(
        f"✅ Предмет добавлен!\n\n"
        f"📚 Название: {full_subject_name}\n"
        f"🏫 Тип: с фиксированным кабинетом\n\n"
        f"Теперь при добавлении этого предмета в расписание "
        f"кабинет будет подставляться автоматически."
    )
    
    # Показываем админ-меню
    await message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
    await state.clear()
    
    await callback.answer()

@dp.message(AddSubjectState.cabinet)
async def process_subject_cabinet(message: types.Message, state: FSMContext):
    cabinet = message.text.strip()
    data = await state.get_data()
    subject_name = data["name"]
    
    if not cabinet:
        await message.answer("❌ Номер кабинета не может быть пустым. Введите кабинет:")
        return
    
    # Формируем полное название предмета с кабинетом
    full_subject_name = f"{subject_name} {cabinet}"
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO subjects (name, rK) VALUES (%s, %s)", (full_subject_name, False))
    
    await message.answer(
        f"✅ Предмет добавлен!\n\n"
        f"📚 Название: {full_subject_name}\n"
        f"🏫 Тип: с фиксированным кабинетом\n\n"
        f"Теперь при добавлении этого предмета в расписание "
        f"кабинет будет подставляться автоматически."
    )
    
    # Показываем админ-меню
    await message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
    await state.clear()

@dp.callback_query(F.data == "admin_delete_subject")
async def admin_delete_subject_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    # Получаем список всех предметов
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name, rK FROM subjects ORDER BY name")
            subjects = await cur.fetchall()
    
    if not subjects:
        await callback.message.edit_text("❌ В базе нет предметов для удаления.")
        await callback.answer()
        return
    
    # Создаем кнопки для выбора предмета
    keyboard = []
    for subject_id, name, rk in subjects:
        type_icon = "🔢" if rk else "🏫"
        button_text = f"{type_icon} {name}"
        keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"delete_subject_{subject_id}")])
    
    # Добавляем кнопку отмены
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.edit_text(
        "🗑️ Удаление предмета\n\n"
        "Выберите предмет для удаления:\n"
        "🏫 - с фиксированным кабинетом\n"
        "🔢 - с запросом кабинета (rK)",
        reply_markup=kb
    )
    await state.set_state(DeleteSubjectState.subject_choice)
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_subject_"))
async def process_delete_subject(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "menu_admin":
        await callback.message.edit_text("⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        await callback.answer()
        return
    
    subject_id = int(callback.data[len("delete_subject_"):])
    
    # Получаем информацию о предмете
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name, rK FROM subjects WHERE id=%s", (subject_id,))
            subject = await cur.fetchone()
            
            if not subject:
                await callback.message.edit_text("❌ Предмет не найден.")
                await callback.answer()
                return
            
            name, rk = subject
            
            # Проверяем, используется ли предмет в расписании
            await cur.execute("SELECT COUNT(*) FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
            usage_count = (await cur.fetchone())[0]
            
            if usage_count > 0:
                # Предмет используется - предупреждаем
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Да, удалить вместе с уроками", callback_data=f"confirm_delete_subject_{subject_id}")],
                    [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="cancel_delete_subject")]
                ])
                
                await callback.message.edit_text(
                    f"⚠️ Внимание!\n\n"
                    f"Предмет '{name}' используется в {usage_count} урок(ах) расписания.\n\n"
                    f"Удалить предмет и все связанные уроки?",
                    reply_markup=kb
                )
            else:
                # Предмет не используется - удаляем сразу
                await cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
                await callback.message.edit_text(f"✅ Предмет '{name}' удален.")
                
                # Возвращаем в админ-меню
                await callback.message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
                await state.clear()
    
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete_subject_"))
async def confirm_delete_subject(callback: types.CallbackQuery):
    subject_id = int(callback.data[len("confirm_delete_subject_"):])
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Получаем название предмета перед удалением
            await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
            subject_name = (await cur.fetchone())[0]
            
            # Удаляем уроки с этим предметом
            await cur.execute("DELETE FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
            
            # Удаляем сам предмет
            await cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
    
    await callback.message.edit_text(
        f"✅ Предмет '{subject_name}' и все связанные уроки удалены."
    )
    
    # Возвращаем в админ-меню
    await callback.message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "menu_back")
async def menu_back_handler(callback: types.CallbackQuery, state: FSMContext):
    # Разрешаем в ЛС и разрешенных чатах
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    try:
        await state.clear()
    except Exception:
        pass
    
    is_admin = (callback.from_user.id in ALLOWED_USERS) and is_private
    
    # Проверяем спец-пользователей через базу данных
    is_special_user = False
    if is_private:
        signature = await get_special_user_signature(pool, callback.from_user.id)
        is_special_user = signature is not None
    
    try:
        await callback.message.delete()
        await greet_and_send(
            callback.from_user, 
            "Выберите действие:", 
            chat_id=callback.message.chat.id, 
            markup=main_menu(is_admin=is_admin, is_special_user=is_special_user, is_group_chat=not is_private)
        )
    except Exception:
        try:
            await greet_and_send(
                callback.from_user, 
                "Выберите действие:", 
                callback=callback, 
                markup=main_menu(is_admin=is_admin, is_special_user=is_special_user, is_group_chat=not is_private)
            )
        except Exception:
            await greet_and_send(
                callback.from_user, 
                "Выберите действие:", 
                chat_id=callback.message.chat.id, 
                markup=main_menu(is_admin=is_admin, is_special_user=is_special_user, is_group_chat=not is_private)
            )

    await callback.answer()



@dp.callback_query(F.data == "cancel_delete_subject")
async def cancel_delete_subject(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Удаление отменено.")
    await menu_back_handler(callback, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("pair_"))
async def choose_pair(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("pair_"):])
    await state.update_data(pair_number=pair_number)
    
    data = await state.get_data()
    subject_name = data["subject"]
    
    try:
        # Проверяем, есть ли у предмета фиксированный кабинет (rK)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT rK FROM subjects WHERE name=%s", (subject_name,))
                result = await cur.fetchone()
                is_rk = result[0] if result else False
        
        if is_rk:
            # Если предмет с rK - спрашиваем кабинет
            await callback.message.edit_text("Введите кабинет для этой пары:")
            await state.set_state(AddLessonState.cabinet)
        else:
            # Если предмет без rK - пытаемся извлечь кабинет из названия
            import re
            # Ищем кабинет в конце названия (учитываем точки, слеши, буквы)
            cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
            
            if cabinet_match:
                # Если нашли кабинет в названии - извлекаем его
                cabinet = cabinet_match.group(2)
                # Очищаем название предмета от кабинета только для отображения
                clean_subject_name = subject_name.replace(cabinet_match.group(0), '').strip()
            else:
                # Если кабинета в названии нет
                cabinet = "Не указан"
                clean_subject_name = subject_name
            
            # Сохраняем кабинет
            await state.update_data(cabinet=cabinet)
            
            # Добавляем урок (НЕ обновляем название в базе!)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Получаем ID предмета
                    await cur.execute("SELECT id FROM subjects WHERE name=%s", (subject_name,))
                    subject_result = await cur.fetchone()
                    if not subject_result:
                        await callback.message.edit_text("❌ Ошибка: предмет не найден в базе")
                        await state.clear()
                        return
                    
                    subject_id = subject_result[0]
                    
                    # Добавляем урок в расписание
                    await cur.execute("""
                        INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], pair_number, subject_id, cabinet))
            
            # Для отображения используем очищенное название
            display_name = clean_subject_name
            
            await callback.message.edit_text(
                f"✅ Урок '{display_name}' добавлен!\n"
                f"📅 День: {DAYS[data['day']-1]}\n"
                f"🔢 Пара: {pair_number}\n"
                f"🏫 Кабинет: {cabinet}\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
            await state.clear()
    
    except Exception as e:
        print(f"❌ Ошибка в choose_pair: {e}")
        await callback.message.edit_text(f"❌ Ошибка при добавлении урока: {e}")
        await state.clear()

@dp.message(AddLessonState.cabinet)
async def set_cabinet(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cabinet = message.text.strip()
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM subjects WHERE name=%s", (data["subject"],))
            subject_id = (await cur.fetchone())[0]
            await cur.execute("""
                INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], data["pair_number"], subject_id, cabinet))
    
    await message.answer(
        f"✅ Урок '{data['subject']}' добавлен!\n"
        f"📅 День: {DAYS[data['day']-1]}\n" 
        f"🔢 Пара: {data['pair_number']}\n"
        f"🏫 Кабинет: {cabinet} (вручную)\n\n"
        f"⚙ Админ-панель:",
        reply_markup=admin_menu()
    )
    await state.clear()

@dp.callback_query(F.data.startswith("addlesson_"))
async def choose_lesson(callback: types.CallbackQuery, state: FSMContext):
    lesson = callback.data[len("addlesson_"):]
    await state.update_data(lesson=lesson)
    if lesson.endswith("rK"):
        await greet_and_send(callback.from_user, "Сначала выберите четность недели:", callback=callback,
                             markup=InlineKeyboardMarkup(inline_keyboard=[
                                 [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="cab_week_1")],
                                 [InlineKeyboardButton(text="2️⃣ Четная", callback_data="cab_week_2")]
                             ]))
        await state.set_state(SetCabinetState.week_type)
    else:
        await greet_and_send(callback.from_user, f"Урок '{lesson}' добавлен с кабинетом по умолчанию.", callback=callback)
        await state.clear()

@dp.callback_query(F.data == "admin_set_cabinet")
async def admin_set_cabinet_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="cab_week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="cab_week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    await greet_and_send(callback.from_user, "Выберите четность недели:", callback=callback, markup=kb)
    await state.set_state(SetCabinetState.week_type)
    await callback.answer()

@dp.callback_query(F.data.startswith("cab_week_"))
async def set_cab_week(callback: types.CallbackQuery, state: FSMContext):
    week_type = int(callback.data[-1])
    await state.update_data(week_type=week_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=day, callback_data=f"cab_day_{i+1}")] 
        for i, day in enumerate(DAYS)
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]  # Добавляем кнопку отмены
    )
    await greet_and_send(callback.from_user, "Выберите день недели:", callback=callback, markup=kb)
    await state.set_state(SetCabinetState.day)
    await callback.answer()

@dp.callback_query(F.data.startswith("cab_day_"))
async def set_cab_day(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data[len("cab_day_"):])
    await state.update_data(day=day)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"cab_pair_{i}")] for i in range(1, 7)
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]  # Добавляем кнопку отмены
    )
    await greet_and_send(callback.from_user, "Выберите номер пары:", callback=callback, markup=kb)
    await state.set_state(SetCabinetState.pair_number)
    await callback.answer()

@dp.message(SetCabinetState.cabinet)
async def set_cabinet_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cabinet = message.text.strip()
    
    # Добавляем проверку на команду отмены
    if cabinet.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id FROM rasp_detailed
                WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
            """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], data["pair_number"]))
            row = await cur.fetchone()
            if row:
                await cur.execute("""
                    UPDATE rasp_detailed
                    SET cabinet=%s
                    WHERE id=%s
                """, (cabinet, row[0]))
            else:
                await cur.execute("""
                    INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, cabinet)
                    VALUES (%s, %s, %s, %s, %s)
                """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], data["pair_number"], cabinet))
    await greet_and_send(message.from_user,
                         f"✅ Кабинет установлен: день {DAYS[data['day']-1]}, пара {data['pair_number']}, кабинет {cabinet}",
                         message=message)
    await greet_and_send(message.from_user, "⚙ Админ-панель:", message=message, markup=admin_menu())
    await state.clear()

@dp.callback_query(F.data == "admin_clear_pair")
async def admin_clear_pair_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="clr_week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="clr_week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    await greet_and_send(callback.from_user, "Выберите четность недели:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.week_type)
    await callback.answer()

@dp.callback_query(F.data.startswith("clr_week_"))
async def clear_pair_week(callback: types.CallbackQuery, state: FSMContext):
    week_type = int(callback.data[-1])
    await state.update_data(week_type=week_type)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=day, callback_data=f"clr_day_{i+1}")]
        for i, day in enumerate(DAYS)
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]  # Добавляем кнопку отмены
    )
    await greet_and_send(callback.from_user, "Выберите день недели:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.day)
    await callback.answer()

@dp.callback_query(F.data.startswith("clr_day_"))
async def clear_pair_day(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data[len("clr_day_"):])
    await state.update_data(day=day)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"clr_pair_{i}")] for i in range(1, 7)
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]  # Добавляем кнопку отмены
    )
    await greet_and_send(callback.from_user, "Выберите номер пары:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.pair_number)
    await callback.answer()

@dp.callback_query(F.data.startswith("clr_pair_"))
async def clear_pair_number(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("clr_pair_"):])
    data = await state.get_data()

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # проверяем, есть ли запись для этой пары
            await cur.execute("""
                SELECT id FROM rasp_detailed
                WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
            """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], pair_number))
            row = await cur.fetchone()

            if row:
                # обновляем предмет на NULL и кабинет на NULL → в выводе будет "Свободно"
                await cur.execute("""
                    UPDATE rasp_detailed
                    SET subject_id=NULL, cabinet=NULL
                    WHERE id=%s
                """, (row[0],))
            else:
                # создаём пустую запись, чтобы считалось "Свободно"
                await cur.execute("""
                    INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                    VALUES (%s, %s, %s, %s, NULL, NULL)
                """, (DEFAULT_CHAT_ID, data["day"], data["week_type"], pair_number))

    await greet_and_send(callback.from_user,
                         f"✅ Пара {pair_number} ({DAYS[data['day']-1]}, неделя {data['week_type']}) очищена. Теперь там 'Свободно'.",
                         callback=callback)
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "admin_delete_teacher_message")
async def admin_delete_teacher_message_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    # Получаем последние сообщения для выбора (БЕЗ chat_id параметра)
    messages = await get_teacher_messages(pool, limit=20)
    
    if not messages:
        await callback.message.edit_text(
            "🗑️ Удаление сообщения преподавателя\n\n"
            "❌ В базе нет сообщений для удаления."
        )
        await callback.answer()
        return
    
    # Создаем клавиатуру с сообщениями
    keyboard = []
    for i, (msg_id, message_id, signature, text, msg_type, created_at) in enumerate(messages):
        # Обрезаем длинный текст
        display_text = text[:30] + "..." if len(text) > 30 else text
        if not display_text:
            display_text = f"{msg_type}"
        
        # Форматируем дату
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m %H:%M")
        else:
            date_str = str(created_at)
        
        button_text = f"{signature}: {display_text} ({date_str})"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"delete_teacher_msg_{msg_id}"
        )])
    
    # Добавляем кнопку отмены
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.edit_text(
        "🗑️ Удаление сообщения преподавателя\n\n"
        "Выберите сообщение для удаления:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "menu_admin_from_delete")
async def menu_admin_from_delete_handler(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в админ-меню из процесса удаления сообщения"""
    await state.clear()
    await callback.message.edit_text("⚙ Админ-панель:", reply_markup=admin_menu())
    await callback.answer()

# Обработчик выбора сообщения для удаления
@dp.callback_query(F.data.startswith("delete_teacher_msg_"))
async def process_delete_teacher_message(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "menu_admin":
        await callback.message.edit_text("⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        await callback.answer()
        return
    
    try:
        message_db_id = int(callback.data[len("delete_teacher_msg_"):])
        
        # Получаем информацию о сообщении
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT signature, message_text, message_type, created_at
                    FROM teacher_messages WHERE id = %s
                """, (message_db_id,))
                message_data = await cur.fetchone()
        
        if not message_data:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return
        
        signature, text, msg_type, created_at = message_data
        
        # Форматируем дату
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            date_str = str(created_at)
        
        # Показываем подтверждение удаления
        # В функции process_delete_teacher_message замените клавиатуру на эту:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_msg_{message_db_id}")],
            [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="menu_admin_from_delete")]
        ])
                
        message_info = f"🗑️ Подтвердите удаление сообщения:\n\n"
        message_info += f"👨‍🏫 От: {signature}\n"
        message_info += f"📅 Дата: {date_str}\n"
        message_info += f"📊 Тип: {msg_type}\n"
        
        if text and text != "голосовое сообщение" and text != "стикер":
            message_info += f"📝 Текст: {text}\n"
        
        await callback.message.edit_text(message_info, reply_markup=kb)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    await callback.answer()

# Обработчик подтверждения удаления
@dp.callback_query(F.data.startswith("confirm_delete_msg_"))
async def confirm_delete_teacher_message(callback: types.CallbackQuery):
    try:
        message_db_id = int(callback.data[len("confirm_delete_msg_"):])
        
        # Удаляем сообщение
        success = await delete_teacher_message(pool, message_db_id)
        
        if success:
            await callback.message.edit_text(
                "✅ Сообщение преподавателя успешно удалено из базы данных.\n\n"
                "⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        else:
            await callback.message.edit_text(
                "❌ Не удалось удалить сообщение. Возможно, оно уже было удалено.\n\n"
                "⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
            
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при удалении: {e}\n\n"
            "⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
    await callback.answer()

# Обработчик отмены удаления
@dp.callback_query(F.data == "cancel_delete_msg")
async def cancel_delete_teacher_message(callback: types.CallbackQuery):
    # Вместо прямого возврата в админ-меню, используем menu_back для корректного отображения
    await menu_back_handler(callback, None)
    await callback.answer()


@dp.callback_query(F.data == "admin_my_publish_time")
async def admin_my_publish_time(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return
    
    now = datetime.datetime.now(TZ)
    times = await get_publish_times(pool)
    if not times:
        text = "Время публикаций ещё не задано."
    else:
        future_times = sorted([(h, m) for _, h, m in times if (h, m) > (now.hour, now.minute)])
        if future_times:
            hh, mm = future_times[0]
            msg = f"Следующая публикация сегодня в Омске: {hh:02d}:{mm:02d}"
        else:
            hh, mm = sorted([(h, m) for _, h, m in times])[0]
            msg = f"Сегодня публикаций больше нет. Следующая публикация завтра в Омске: {hh:02d}:{mm:02d}"
        text = msg
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_admin")]
    ])
    
    await greet_and_send(callback.from_user, text, callback=callback, markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "admin_edit")
async def admin_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в личных сообщениях админам", show_alert=True)
        return
    await greet_and_send(callback.from_user, "Введите день недели (1-6):", callback=callback)
    await state.set_state(EditRaspState.day)
    await callback.answer()

async def greet_and_send(user: types.User, text: str, message: types.Message = None, callback: types.CallbackQuery = None, markup=None, chat_id: int | None = None, include_joke: bool = False, include_week_info: bool = False):
    if include_joke:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
                row = await cur.fetchone()
                if row:
                    text += f"\n\n😂 Анекдот:\n{row[0]}"
    
    # Добавляем информацию о неделе если нужно
    week_info = ""
    if include_week_info:
        # Используем chat_id из параметра или из сообщения
        # Добавляем информацию о неделе если нужно
        week_info = ""
        if include_week_info:
            # Используем chat_id из параметра или из сообщения
            target_chat_id = chat_id or (message.chat.id if message else (callback.message.chat.id if callback else DEFAULT_CHAT_ID))
            current_week = await get_current_week_type(pool, target_chat_id)
            week_name = "Нечетная" if current_week == 1 else "Четная"
            week_info = f"\n\n📅 Сейчас неделя: {week_name}"
    
    nickname = await get_nickname(pool, user.id)
    greet = f"👋 Салам, {nickname}!\n\n" if nickname else "👋 Салам!\n\n"
    full_text = greet + text + week_info
    
    if callback:
        try:
            await callback.message.edit_text(full_text, reply_markup=markup)
        except:
            await callback.message.answer(full_text, reply_markup=markup)
    elif message:
        try:
            await message.answer(full_text, reply_markup=markup)
        except:
            await bot.send_message(chat_id=message.chat.id, text=full_text, reply_markup=markup)
    elif chat_id is not None:
        await bot.send_message(chat_id=chat_id, text=full_text, reply_markup=markup)
    else:
        # Если не указан chat_id, отправляем пользователю в ЛС
        await bot.send_message(chat_id=user.id, text=full_text, reply_markup=markup)

async def get_rasp_formatted(day, week_type, chat_id: int = DEFAULT_CHAT_ID):
    msg_lines = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.pair_number, COALESCE(r.cabinet, '') as cabinet, COALESCE(s.name, 'Свободно') as name
                   FROM rasp_detailed r
                   LEFT JOIN subjects s ON r.subject_id = s.id
                   WHERE r.chat_id=%s AND r.day=%s AND r.week_type=%s
                   ORDER BY r.pair_number""",
                (chat_id, day, week_type)  # Используем переданный chat_id
            )
            rows = await cur.fetchall()
    
    # Находим максимальный номер пары, которая есть в расписании
    max_pair = 0
    pairs_dict = {}
    for row in rows:
        pair_num = row[0]
        pairs_dict[pair_num] = row
        if pair_num > max_pair:
            max_pair = pair_num
    
    if max_pair == 0:
        return "Расписание пустое."
    
    for i in range(1, max_pair + 1):
        if i in pairs_dict:
            row = pairs_dict[i]
            cabinet = row[1]
            subject_name = row[2]
            
            if subject_name == "Свободно":
                msg_lines.append(f"{i}. Свободно")
            else:
                # Для предметов с кабинетом в названии - извлекаем чистое название
                import re
                # Обновленное регулярное выражение с учетом точек
                clean_subject_name = re.sub(r'\s+(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', '', subject_name).strip()
                
                if cabinet and cabinet != "Не указан":
                    # Если кабинет указан отдельно - используем его
                    msg_lines.append(f"{i}. {cabinet} {clean_subject_name}")
                else:
                    # Если кабинета нет - пытаемся извлечь из названия
                    cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
                    if cabinet_match:
                        extracted_cabinet = cabinet_match.group(2)
                        msg_lines.append(f"{i}. {extracted_cabinet} {clean_subject_name}")
                    else:
                        msg_lines.append(f"{i}. {clean_subject_name}")
        else:
            msg_lines.append(f"{i}. Свободно")
    
    return "\n".join(msg_lines)

def _job_id_for_time(hour: int, minute: int) -> str:
    return f"publish_{hour:02d}_{minute:02d}"
async def reschedule_publish_jobs(pool):
    try:
        for job in list(scheduler.get_jobs()):
            if job.id.startswith("publish_"):
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    pass
    except Exception:
        pass
    times = await get_publish_times(pool)
    for row in times:
        pid, hour, minute = row
        job_id = _job_id_for_time(hour, minute)
        try:
            scheduler.add_job(send_today_rasp, CronTrigger(hour=hour, minute=minute, timezone=TZ), id=job_id)
        except Exception:
            pass
@dp.message(Command("аркадий", "акрадый", "акрадий", "аркаша", "котов", "arkadiy", "arkadiy@arcadiyis07_bot"))
async def trigger_handler(message: types.Message):
    # Разрешаем команду в ЛС и разрешенных чатах
    is_private = message.chat.type == "private"
    is_allowed_chat = message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await message.answer("⛔ Бот не работает в этом чате")
        return
    
    is_admin = (message.from_user.id in ALLOWED_USERS) and is_private
    
    # Проверяем спец-пользователей через базу данных
    is_special_user = False
    if is_private:
        signature = await get_special_user_signature(pool, message.from_user.id)
        is_special_user = signature is not None

    # ИСПРАВЛЕНИЕ: используем chat_id текущего чата, а не DEFAULT_CHAT_ID
    current_chat_id = message.chat.id

    await greet_and_send(
        message.from_user,
        "Выберите действие:",
        message=message,
        markup=main_menu(is_admin=is_admin, is_special_user=is_special_user, is_group_chat=not is_private),
        include_week_info=True,
        chat_id=current_chat_id  # Добавляем правильный chat_id
    )

@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery, state: FSMContext):
    # Разрешаем в ЛС и разрешенных чатах
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
        
    action = callback.data
    if action == "menu_rasp":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=day, callback_data=f"rasp_day_{i+1}")]
                for i, day in enumerate(DAYS)
            ] + [[InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]]
        )
        await greet_and_send(callback.from_user, "📅 Выберите день:", callback=callback, markup=kb)
        await callback.answer()
    elif action == "menu_zvonki":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Будние дни", callback_data="zvonki_weekday")],
            [InlineKeyboardButton(text="📅 Суббота", callback_data="zvonki_saturday")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await greet_and_send(callback.from_user, "⏰ Выберите вариант:", callback=callback, markup=kb)
        await callback.answer()
    elif action == "menu_admin":
        if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
            await callback.answer("⛔ Админка доступна только в ЛС админам", show_alert=True)
            return
        await greet_and_send(callback.from_user, "⚙ Админ-панель:", callback=callback, markup=admin_menu())
        await callback.answer()
    elif action == "menu_back":
        await menu_back_handler(callback, state)

@dp.callback_query(F.data == "tomorrow_rasp")
async def tomorrow_rasp_handler(callback: types.CallbackQuery):

    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    now = datetime.datetime.now(TZ)
    hour = now.hour
    day = now.isoweekday()
    
    # Определяем день для показа (логика как в автопостинге)
    if hour >= 18:
        target_date = now.date() + datetime.timedelta(days=1)
        day_to_show = target_date.isoweekday()
        if day_to_show == 7:  # Воскресенье
            day_to_show = 1
            target_date += datetime.timedelta(days=1)
            day_name = "послезавтра (Понедельник)"
        else:
            day_name = "завтра"
    else:
        target_date = now.date()
        day_to_show = day
        day_name = "сегодня"
        if day_to_show == 7:  # Воскресенье
            day_to_show = 1
            target_date += datetime.timedelta(days=1)
            day_name = "завтра (Понедельник)"
        else:
            # Если сегодня не воскресенье и время до 18:00, показываем завтра
            target_date += datetime.timedelta(days=1)
            day_to_show = target_date.isoweekday()
            if day_to_show == 7:  # Если завтра воскресенье
                day_to_show = 1
                target_date += datetime.timedelta(days=1)
                day_name = "послезавтра (Понедельник)"
            else:
                day_name = "завтра"
    
    # Получаем тип недели
    week_type = await get_current_week_type(pool, DEFAULT_CHAT_ID, target_date)
    
    # Получаем расписание
    text = await get_rasp_formatted(day_to_show, week_type)
    
    # Формируем сообщение
    day_names = {
        1: "Понедельник",
        2: "Вторник", 
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота"
    }
    
    week_name = "нечетная" if week_type == 1 else "четная"
    message = f"📅 Расписание на {day_name} ({day_names[day_to_show]}) | Неделя: {week_name}\n\n{text}"
    
    # Добавляем анекдот
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                message += f"\n\n😂 Анекдот:\n{row[0]}"
    
    # Отправляем сообщение с кнопкой "Назад"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await greet_and_send(callback.from_user, message, callback=callback, markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("rasp_day_"))
async def on_rasp_day(callback: types.CallbackQuery):

    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

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

@dp.message(Command("никнейм"))
async def cmd_set_nickname(message: types.Message):

    if not is_allowed_chat(message.chat.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("⚠ Использование: /никнейм <ваш никнейм>")
        return
    nickname = parts[1].strip()
    user_id = message.from_user.id 
    try:
        await set_nickname(pool, user_id, nickname)
        await message.answer(f"✅ Ваш никнейм установлен: {nickname}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при установке никнейма: {e}")
@dp.message(Command("анекдот"))
async def cmd_anekdot(message: types.Message):

    if not is_allowed_chat(message.chat.id):
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                await message.answer(f"😂 Анекдот:\n\n{row[0]}")
            else:
                await message.answer("❌ В базе пока нет анекдотов.")
@dp.callback_query(F.data.startswith("rasp_show_"))
async def on_rasp_show(callback: types.CallbackQuery):

    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    parts = callback.data.split("_")
    day = int(parts[2])
    week_type = int(parts[3])
    text = await get_rasp_formatted(day, week_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data=f"rasp_day_{day}")]
    ])
    
    await greet_and_send(callback.from_user, f"📌 Расписание:\n{text}", callback=callback, markup=kb, include_joke=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("zvonki_"))
async def zvonki_handler(callback: types.CallbackQuery):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
    action = callback.data

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_zvonki")]
    ])

    if action == "zvonki_weekday":
        schedule = get_zvonki(is_saturday=False)
        await greet_and_send(
            callback.from_user,
            f"📌 Расписание звонков (будние дни):\n{schedule}",
            callback=callback,
            markup=kb,
            include_joke=True 
        )
    elif action == "zvonki_saturday":
        schedule = get_zvonki(is_saturday=True)
        await greet_and_send(
            callback.from_user,
            f"📌 Расписание звонков (суббота):\n{schedule}",
            callback=callback,
            markup=kb,
            include_joke=True  
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_show_chet")
async def admin_show_chet(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return
    
    chat_id = callback.message.chat.id
    current = await get_current_week_type(pool, chat_id)
    current_str = "нечетная (1)" if current == 1 else "четная (2)"
    
    msg = f"Текущая четность недели: {current_str}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_admin")]
    ])
    
    await greet_and_send(callback.from_user, msg, callback=callback, markup=kb)
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
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_admin")]
    ])
    
    await greet_and_send(callback.from_user, text, callback=callback, markup=kb)
    await callback.answer()
# В состояние добавления времени публикации
@dp.callback_query(F.data == "admin_set_publish_time")
async def admin_set_publish_time(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await greet_and_send(
        callback.from_user,
        "Введите время публикации в формате ЧЧ:ММ по Омску (например: 20:00):",
        callback=callback,
        markup=kb
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
        await reschedule_publish_jobs(pool) 
        await message.answer(f"✅ Время публикации добавлено: {hh:02d}:{mm:02d} (Омск).")
    except Exception as e:
        await message.answer(f"❌ Ошибка при сохранении: {e}")
    finally:
        await state.clear()

@dp.callback_query(F.data == "admin_setchet")
async def admin_setchet_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Нечетная неделя", callback_data="set_week_1")],
        [InlineKeyboardButton(text="🔵 Четная неделя", callback_data="set_week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await greet_and_send(
        callback.from_user, 
        "Выберите тип недели для установки:", 
        callback=callback, 
        markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("set_week_"))
async def set_week_type_handler(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    
    week_type = int(callback.data.split("_")[2])
    chat_id = callback.message.chat.id
    
    try:
        await set_current_week_type(pool, chat_id, week_type)
        week_name = "нечетная" if week_type == 1 else "четная"
        
        await callback.message.edit_text(
            f"✅ Четность установлена: {week_name} неделя\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при установке четности: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
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

async def send_today_rasp():
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            now = datetime.datetime.now(TZ)
            hour = now.hour
            
            # Определяем день для публикации
            if hour >= 18:
                target_date = now.date() + datetime.timedelta(days=1)
                day_to_post = target_date.isoweekday()
                day_name = "завтра"
                
                if day_to_post == 7:  # Воскресенье
                    target_date += datetime.timedelta(days=1)
                    day_to_post = 1
                    day_name = "послезавтра (Понедельник)"
            else:
                target_date = now.date()
                day_to_post = now.isoweekday()
                day_name = "сегодня"
                
                if day_to_post == 7:  # Воскресенье
                    target_date += datetime.timedelta(days=1)
                    day_to_post = 1
                    day_name = "завтра (Понедельник)"
            
            # Просто получаем текущую четность из базы
            week_type = await get_current_week_type(pool, chat_id)
            
            # Получаем расписание
            text = await get_rasp_formatted(day_to_post, week_type, chat_id)
            
            # Формируем сообщение
            day_names = {
                1: "Понедельник", 2: "Вторник", 3: "Среда",
                4: "Четверг", 5: "Пятница", 6: "Суббота"
            }
            
            week_name = "нечетная" if week_type == 1 else "четная"
            msg = f"📅 Расписание на {day_name} ({day_names[day_to_post]}) | Неделя: {week_name}\n\n{text}"
            
            # Добавляем анекдот
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
                    row = await cur.fetchone()
                    if row:
                        msg += f"\n\n😂 Анекдот:\n{row[0]}"
            
            await bot.send_message(chat_id, msg)
            
        except Exception as e:
            print(f"Ошибка отправки расписания в чат {chat_id}: {e}")  

async def main():
    global pool
    pool = await get_pool()
    await init_db(pool)
    await ensure_columns(pool)
    # Загружаем спец-пользователей из базы данных
    await load_special_users(pool)
    
    # Пересоздаем задания публикации при старте
    await reschedule_publish_jobs(pool)
    
    scheduler.start()
    print("Планировщик запущен")
    
    # Проверяем текущие задания
    jobs = scheduler.get_jobs()
    print(f"Активные задания: {len(jobs)}")
    for job in jobs:
        print(f"Задание: {job.id}, следующий запуск: {job.next_run_time}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())