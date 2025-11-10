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
import decimal
from bs4 import BeautifulSoup
import time
from collections import defaultdict
from aiogram.exceptions import TelegramRetryAfter

TOKEN = os.getenv("BOT_TOKEN")
CHAT_IDS_STR = os.getenv("CHAT_ID", "")
ALLOWED_CHAT_IDS = [int(x.strip()) for x in CHAT_IDS_STR.split(",") if x.strip()]
DEFAULT_CHAT_ID = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else 0
ALLOWED_USERS = [5228681344, 7620086223, 1422286970]
FUND_MANAGER_USER_ID = 5228681344
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

user_last_action = defaultdict(float)
FLOOD_DELAY = 1.0  # 1 секунда между действиями

def check_flood(user_id: int) -> bool:
    """Проверяет флуд, возвращает True если нужно блокировать"""
    current_time = time.time()
    if current_time - user_last_action[user_id] < FLOOD_DELAY:
        return True
    user_last_action[user_id] = current_time
    return False

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
            CREATE TABLE IF NOT EXISTS birthdays (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_name VARCHAR(255) NOT NULL,
                birth_date DATE NOT NULL,
                added_by_user_id BIGINT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS nicknames (
                user_id BIGINT PRIMARY KEY,
                nickname VARCHAR(255)
            )""")
            # В функции init_db() добавляем:
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS static_rasp (
                id INT AUTO_INCREMENT PRIMARY KEY,
                day INT,
                week_type INT,
                pair_number INT,
                subject_id INT,
                cabinet VARCHAR(50),
                FOREIGN KEY (subject_id) REFERENCES subjects(id)
            )""")

            await cur.execute("""
            CREATE TABLE IF NOT EXISTS rasp_modifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                day INT,
                week_type INT,
                pair_number INT,
                subject_id INT,
                cabinet VARCHAR(50),
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject_id) REFERENCES subjects(id)
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
            # После существующих таблиц
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS group_fund_balance (
                id INT AUTO_INCREMENT PRIMARY KEY,
                current_balance DECIMAL(10, 2) DEFAULT 0.00,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")

            await cur.execute("""
            CREATE TABLE IF NOT EXISTS group_fund_members (
                id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                balance DECIMAL(10, 2) DEFAULT 0.00,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")

            await cur.execute("""
            CREATE TABLE IF NOT EXISTS group_fund_purchases (
                id INT AUTO_INCREMENT PRIMARY KEY,
                item_name VARCHAR(255) NOT NULL,
                item_url VARCHAR(500),
                price DECIMAL(10, 2) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )""")
            # Новая таблица для домашних заданий (без chat_id - общие для всех)
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS homework (
                id INT AUTO_INCREMENT PRIMARY KEY,
                subject_id INT,
                due_date DATE,
                task_text TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject_id) REFERENCES subjects(id)
            )""")

            await conn.commit()


async def safe_edit_message(callback: types.CallbackQuery, text: str, markup=None):
    """Безопасное редактирование сообщения с обработкой RetryAfter"""
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramRetryAfter as e:
        # Если Telegram просит подождать
        wait_time = e.retry_after
        print(f"⏳ Telegram просит подождать {wait_time} секунд")
        await asyncio.sleep(wait_time)
        # Пробуем еще раз после ожидания
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception as retry_error:
            print(f"Ошибка при повторной попытке: {retry_error}")
    except Exception as e:
        print(f"Ошибка редактирования: {e}")
        # Пробуем отправить новое сообщение
        try:
            await callback.message.answer(text, reply_markup=markup)
        except Exception as answer_error:
            print(f"Ошибка отправки нового сообщения: {answer_error}")

async def ensure_columns(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM week_setting LIKE 'set_at'")
            row = await cur.fetchone()
            if not row:
                await cur.execute("ALTER TABLE week_setting ADD COLUMN set_at DATE")

async def ensure_birthday_columns(pool):
    """Добавляет недостающие колонки в таблицу birthdays"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Проверяем наличие колонки added_by_user_id
            await cur.execute("SHOW COLUMNS FROM birthdays LIKE 'added_by_user_id'")
            row = await cur.fetchone()
            if not row:
                await cur.execute("ALTER TABLE birthdays ADD COLUMN added_by_user_id BIGINT")
                print("✅ Добавлена колонка added_by_user_id в таблицу birthdays")


async def save_static_rasp(pool, day: int, week_type: int, pair_number: int, subject_id: int, cabinet: str):
    """Сохраняет пару в статичное расписание с проверкой на дубликаты"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Сначала удаляем существующую запись для этой пары (если есть)
            await cur.execute("""
                DELETE FROM static_rasp 
                WHERE day=%s AND week_type=%s AND pair_number=%s
            """, (day, week_type, pair_number))
            
            # Затем добавляем новую
            await cur.execute("""
                INSERT INTO static_rasp (day, week_type, pair_number, subject_id, cabinet)
                VALUES (%s, %s, %s, %s, %s)
            """, (day, week_type, pair_number, subject_id, cabinet))


async def get_static_rasp(pool, day: int, week_type: int):
    """Получает статичное расписание для дня и недели БЕЗ ДУБЛИКАТОВ"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT DISTINCT sr.pair_number, s.name, sr.cabinet, sr.subject_id
                FROM static_rasp sr
                JOIN subjects s ON sr.subject_id = s.id
                WHERE sr.day=%s AND sr.week_type=%s
                ORDER BY sr.pair_number
            """, (day, week_type))
            return await cur.fetchall()

async def save_rasp_modification(pool, chat_id: int, day: int, week_type: int, pair_number: int, subject_id: int, cabinet: str):
    """Сохраняет изменение расписания"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO rasp_modifications (chat_id, day, week_type, pair_number, subject_id, cabinet)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (chat_id, day, week_type, pair_number, subject_id, cabinet))

async def get_rasp_modifications(pool, chat_id: int, day: int, week_type: int):
    """Получает модификации расписания"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT pair_number, subject_id, cabinet
                FROM rasp_modifications 
                WHERE chat_id=%s AND day=%s AND week_type=%s
            """, (chat_id, day, week_type))
            return await cur.fetchall()

async def clear_rasp_modifications(pool, week_type: int):
    """Очищает все модификации для определенной недели"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM rasp_modifications WHERE week_type=%s", (week_type,))

async def sync_rasp_to_all_chats(source_chat_id: int):
    """Синхронизирует расписание из исходного чата во все остальные"""
    try:
        synced_count = 0
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Копируем расписание из исходного чата во все остальные
                for chat_id in ALLOWED_CHAT_IDS:
                    if chat_id == source_chat_id:
                        continue  # Пропускаем исходный чат
                    
                    # Очищаем расписание в целевом чате
                    await cur.execute("DELETE FROM rasp_detailed WHERE chat_id=%s", (chat_id,))
                    
                    # Копируем из исходного чата
                    await cur.execute("""
                        INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                        SELECT %s, day, week_type, pair_number, subject_id, cabinet 
                        FROM rasp_detailed 
                        WHERE chat_id=%s
                    """, (chat_id, source_chat_id))
                    
                    synced_count += 1
        
        print(f"✅ Расписание синхронизировано! Обновлено {synced_count} чатов.")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка синхронизации расписания: {e}")
        return False

async def get_fund_balance(pool) -> float:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT current_balance FROM group_fund_balance ORDER BY id DESC LIMIT 1")
            row = await cur.fetchone()
            if row:
                # Конвертируем decimal.Decimal в float
                balance = row[0]
                if isinstance(balance, decimal.Decimal):
                    return float(balance)
                return float(balance)
            else:
                # Инициализируем баланс
                await cur.execute("INSERT INTO group_fund_balance (current_balance) VALUES (0)")
                return 0.0

async def update_fund_balance(pool, amount: float):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            current_balance = await get_fund_balance(pool)
            new_balance = current_balance + amount  # Теперь оба float
            await cur.execute("INSERT INTO group_fund_balance (current_balance) VALUES (%s)", (new_balance,))
            
# Функции для работы с участниками
async def add_fund_member(pool, full_name: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO group_fund_members (full_name) VALUES (%s)", (full_name,))

async def get_all_fund_members(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, full_name, balance FROM group_fund_members ORDER BY full_name")
            rows = await cur.fetchall()
            # Конвертируем decimal в float правильно
            result = []
            for row in rows:
                member_id, full_name, balance = row
                if isinstance(balance, decimal.Decimal):
                    balance = float(balance)
                elif hasattr(balance, '__float__'):
                    balance = float(balance)
                else:
                    balance = float(str(balance))  # Последний вариант
                result.append((member_id, full_name, balance))
            return result

async def delete_fund_member(pool, member_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_fund_members WHERE id = %s", (member_id,))

async def update_member_balance(pool, member_id: int, amount: float):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Конвертируем amount в Decimal для точных вычислений
            amount_decimal = decimal.Decimal(str(amount))
            await cur.execute("UPDATE group_fund_members SET balance = balance + %s WHERE id = %s", (amount_decimal, member_id))

# Функции для работы с покупками
async def add_purchase(pool, item_name: str, item_url: str, price: float):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_fund_purchases (item_name, item_url, price) VALUES (%s, %s, %s)",
                (item_name, item_url, price)
            )
            # Обновляем баланс фонда
            await update_fund_balance(pool, -price)

async def get_all_purchases(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, item_name, item_url, price FROM group_fund_purchases WHERE is_active = TRUE ORDER BY created_at DESC")
            return await cur.fetchall()

async def delete_purchase(pool, purchase_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Получаем цену покупки для возврата в фонд
            await cur.execute("SELECT price FROM group_fund_purchases WHERE id = %s", (purchase_id,))
            row = await cur.fetchone()
            if row:
                price = float(row[0])
                # Возвращаем деньги в фонд
                await update_fund_balance(pool, price)
                # Помечаем покупку как неактивную
                await cur.execute("UPDATE group_fund_purchases SET is_active = FALSE WHERE id = %s", (purchase_id,))

# Функции для работы с домашними заданиями
async def add_homework(pool, subject_id: int, due_date: str, task_text: str):
    """Добавляет домашнее задание в базу (общее для всех чатов)"""
    # Конвертируем дату из DD.MM.YYYY в YYYY-MM-DD для MySQL
    try:
        due_date_mysql = datetime.datetime.strptime(due_date, '%d.%m.%Y').strftime('%Y-%m-%d')
    except ValueError:
        raise ValueError("Неверный формат даты. Используйте ДД.ММ.ГГГГ")
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO homework (subject_id, due_date, task_text)
                VALUES (%s, %s, %s)
            """, (subject_id, due_date_mysql, task_text))

async def get_all_homework(pool, limit: int = 50) -> List[Tuple]:
    """Получает все домашние задания (общие для всех чатов)"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT h.id, s.name, h.due_date, h.task_text, h.created_at
                FROM homework h
                JOIN subjects s ON h.subject_id = s.id
                ORDER BY h.due_date ASC, h.created_at DESC
                LIMIT %s
            """, (limit,))
            return await cur.fetchall()

async def get_homework_by_date(pool, date: str) -> List[Tuple]:
    """Получает домашние задания на конкретную дату (общие для всех чатов)"""
    # Конвертируем дату если нужно
    if '.' in date:
        try:
            date = datetime.datetime.strptime(date, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            return []
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT h.id, s.name, h.due_date, h.task_text, h.created_at
                FROM homework h
                JOIN subjects s ON h.subject_id = s.id
                WHERE h.due_date = %s
                ORDER BY h.created_at DESC
            """, (date,))
            return await cur.fetchall()

async def get_homework_by_id(pool, homework_id: int) -> Tuple:
    """Получает домашнее задание по ID"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT h.id, s.name, h.due_date, h.task_text, h.created_at, h.subject_id
                FROM homework h
                JOIN subjects s ON h.subject_id = s.id
                WHERE h.id = %s
            """, (homework_id,))
            return await cur.fetchone()

async def update_homework(pool, homework_id: int, subject_id: int, due_date: str, task_text: str):
    """Обновляет домашнее задание"""
    # Получаем текущие данные
    current_hw = await get_homework_by_id(pool, homework_id)
    if not current_hw:
        raise ValueError("Задание не найдено")
    
    # Если subject_id не указан (None), используем текущий
    if subject_id is None:
        subject_id = current_hw[5]  # current_subject_id
    
    # Если due_date не указан (None), используем текущий
    if due_date is None:
        due_date = current_hw[2]  # current_due_date
        if isinstance(due_date, datetime.date):
            due_date = due_date.strftime('%Y-%m-%d')
    
    # Обрабатываем дату (может быть уже в формате YYYY-MM-DD или DD.MM.YYYY)
    if isinstance(due_date, str) and '.' in due_date:
        due_date_mysql = datetime.datetime.strptime(due_date, '%d.%m.%Y').strftime('%Y-%m-%d')
    else:
        due_date_mysql = due_date
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                UPDATE homework 
                SET subject_id=%s, due_date=%s, task_text=%s
                WHERE id=%s
            """, (subject_id, due_date_mysql, task_text, homework_id))

async def delete_homework(pool, homework_id: int):
    """Удаляет домашнее задание"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM homework WHERE id=%s", (homework_id,))

async def has_homework_for_date(pool, date: str) -> bool:
    """Проверяет, есть ли домашние задания на указанную дату"""
    # Конвертируем дату если нужно
    if '.' in date:
        try:
            date = datetime.datetime.strptime(date, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            return False
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM homework WHERE due_date=%s", (date,))
            result = await cur.fetchone()
            return result[0] > 0 if result else False

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


async def get_current_week_type(pool, chat_id: int = None) -> int:
    """Получаем текущую четность с автоматической сменой при наступлении понедельника"""
    COMMON_CHAT_ID = 0
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Получаем текущую запись
            await cur.execute("SELECT week_type, updated_at FROM current_week_type WHERE chat_id=%s", (COMMON_CHAT_ID,))
            row = await cur.fetchone()
            
            now = datetime.datetime.now(TZ)
            today = now.date()
            current_weekday = today.isoweekday()  # 1-понедельник, 7-воскресенье
            
            if row:
                week_type, last_updated = row
                
                # Конвертируем last_updated в date
                if isinstance(last_updated, datetime.datetime):
                    last_updated_date = last_updated.date()
                else:
                    last_updated_date = last_updated
                
                # ОПРЕДЕЛЯЕМ КОГДА МЕНЯТЬ ЧЕТНОСТЬ:
                # Меняем четность в ПОНЕДЕЛЬНИК, если последнее обновление было ДО этого понедельника
                if current_weekday == 1:  # Сегодня понедельник
                    # Находим дату этого понедельника (сегодня)
                    this_monday = today
                    
                    # Если последнее обновление было ДО этого понедельника - меняем четность
                    if last_updated_date < this_monday:
                        week_type = 2 if week_type == 1 else 1
                        await cur.execute("""
                            UPDATE current_week_type 
                            SET week_type=%s, updated_at=%s 
                            WHERE chat_id=%s
                        """, (week_type, today, COMMON_CHAT_ID))
                        print(f"✅ Автоматически переключена неделя на: {'нечетная' if week_type == 1 else 'четная'}")
                
                return week_type
            else:
                # Если запись не существует, создаем по умолчанию нечетную неделю
                week_type = 1
                await cur.execute("INSERT INTO current_week_type (chat_id, week_type, updated_at) VALUES (%s, %s, %s)", 
                                 (COMMON_CHAT_ID, week_type, today))
                return week_type

async def set_current_week_type(pool, chat_id: int = None, week_type: int = None):
    """Устанавливаем четность недели (общую для всех чатов)"""
    # Используем фиксированный chat_id для хранения общей четности
    COMMON_CHAT_ID = 0  # Специальный ID для общей четности
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO current_week_type (chat_id, week_type) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE week_type=%s, updated_at=CURRENT_TIMESTAMP
            """, (COMMON_CHAT_ID, week_type, week_type))

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
class AddHomeworkState(StatesGroup):
    due_date = State()
    subject = State()
    task_text = State()
class EditHomeworkState(StatesGroup):
    homework_id = State()
    due_date = State()
    subject = State()
    task_text = State()
class DeleteHomeworkState(StatesGroup):
    homework_id = State()
# Добавь в существующие StatesGroup
class GroupFundStates(StatesGroup):
    # Для управления участниками
    add_member_name = State()
    delete_member_confirm = State()
    # Для изменения баланса
    select_member_for_balance = State()
    enter_balance_change = State()
    # Для управления покупками
    add_purchase_name = State()
    add_purchase_url = State()
    add_purchase_price = State()
    delete_purchase_confirm = State()
async def add_birthday(pool, user_name: str, birth_date: str, added_by_user_id: int):
    """Добавляет день рождения в базу (без привязки к чату)"""
    try:
        # Конвертируем дату из DD.MM.YYYY в YYYY-MM-DD для MySQL
        birth_date_mysql = datetime.datetime.strptime(birth_date, '%d.%m.%Y').strftime('%Y-%m-%d')
    except ValueError:
        raise ValueError("Неверный формат даты. Используйте ДД.ММ.ГГГГ")
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO birthdays (user_name, birth_date, added_by_user_id)
                VALUES (%s, %s, %s)
            """, (user_name, birth_date_mysql, added_by_user_id))

async def get_today_birthdays(pool):
    """Получает все дни рождения на сегодня"""
    today = datetime.datetime.now(TZ).date()
    today_str = today.strftime('%m-%d')  # Формат для сравнения
    
    print(f"🔍 Проверяем дни рождения на дату: {today_str}")
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Экранируем % в SQL запросе - используем %% вместо %
            await cur.execute("""
                SELECT id, user_name, birth_date
                FROM birthdays 
                WHERE DATE_FORMAT(birth_date, '%%m-%%d') = %s
            """, (today_str,))
            results = await cur.fetchall()
            
            print(f"📅 Найдено дней рождений: {len(results)}")
            for result in results:
                print(f"  - {result[1]}: {result[2]}")
            
            return results

async def get_all_birthdays(pool):
    """Получает все дни рождения"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, user_name, birth_date, added_by_user_id, created_at
                FROM birthdays 
                ORDER BY DATE_FORMAT(birth_date, '%m-%d')
            """)
            return await cur.fetchall()

async def format_birthday_footer(pool):
    """Формирует подпись с именами именинников на сегодня"""
    birthdays = await get_today_birthdays(pool)
    
    print(f"🎂 format_birthday_footer: найдено {len(birthdays)} дней рождений")
    
    if not birthdays:
        return ""
    
    names = [b[1] for b in birthdays]
    count = len(names)
    if count == 1:
        return f"\n\n🎉 Сегодня у 1 человека День рождения\nСчастливчик: {names[0]}"
    else:
        names_str = ", ".join(names)
        return f"\n\n🎉 Сегодня у {count} человек День рождения\nСчастливчики: {names_str}"


async def delete_birthday(pool, birthday_id: int):
    """Удаляет день рождения"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM birthdays WHERE id=%s", (birthday_id,))

@dp.message(Command("adddr"))
async def cmd_add_birthday(message: types.Message):
    """Добавление дня рождения - только админы в ЛС (формат: /adddr Имя ДД.ММ.ГГГГ)"""
    # Проверяем, что это ЛС и пользователь админ
    if message.chat.type != "private" or message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ Эта команда доступна только администраторам в личных сообщениях")
        return

    # Разбиваем сообщение на части
    parts = message.text.split()
    
    if len(parts) < 3:
        await message.answer(
            "⚠ Использование: /adddr Имя ДД.ММ.ГГГГ\n\n"
            "Пример:\n"
            "/adddr Егор 15.05.1990\n"
            "/adddr Иван_Иванов 20.12.1985"
        )
        return

    # Дата всегда последний элемент
    date_str = parts[-1]
    
    # Имя - это всё между командой и датой
    name_parts = parts[1:-1]  # Все части кроме первой (команда) и последней (дата)
    name = ' '.join(name_parts)
    
    if not name:
        await message.answer("❌ Имя не может быть пустым.")
        return

    try:
        # Проверяем формат даты
        birth_date = datetime.datetime.strptime(date_str, '%d.%m.%Y').date()
        
        # Проверяем, что дата не в будущем
        today = datetime.datetime.now(TZ).date()
        if birth_date > today:
            await message.answer("❌ Дата рождения не может быть в будущем.")
            return
        
        # Добавляем в базу
        await add_birthday(pool, name, date_str, message.from_user.id)
        
        # Вычисляем возраст
        age = today.year - birth_date.year
        if today.month < birth_date.month or (today.month == birth_date.month and today.day < birth_date.day):
            age -= 1
        
        await message.answer(
            f"✅ День рождения добавлен!\n\n"
            f"👤 Имя: {name}\n"
            f"📅 Дата рождения: {date_str}\n"
            f"🎂 Возраст: {age} лет\n\n"
            f"Теперь {name} будет получать поздравления автоматически во всех беседах!"
        )
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ\n\n"
            "Пример: /adddr Егор 15.05.1990"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении: {e}")

async def check_birthdays():
    """Проверяет дни рождения и отправляет поздравления во все беседы"""
    try:
        print(f"🎂 [{datetime.datetime.now(TZ)}] Запуск проверки дней рождения...")
        
        birthdays = await get_today_birthdays(pool)
        
        print(f"🎂 Найдено дней рождений: {len(birthdays)}")
        
        if not birthdays:
            print("🎂 Сегодня нет дней рождения")
            return True
            
        for birthday in birthdays:
            birthday_id, user_name, birth_date = birthday
            
            # Обрабатываем дату
            if isinstance(birth_date, datetime.datetime):
                birth_date_obj = birth_date.date()
            elif isinstance(birth_date, datetime.date):
                birth_date_obj = birth_date
            elif isinstance(birth_date, str):
                birth_date_obj = datetime.datetime.strptime(birth_date, '%Y-%m-%d').date()
            else:
                print(f"❌ Неизвестный формат даты: {type(birth_date)}")
                continue
            
            # Вычисляем возраст
            today = datetime.datetime.now(TZ).date()
            age = today.year - birth_date_obj.year
            if today.month < birth_date_obj.month or (today.month == birth_date_obj.month and today.day < birth_date_obj.day):
                age -= 1
            
            print(f"🎂 Поздравляем {user_name}, возраст: {age}")
            
            # Создаем текст поздравления
            message_text = f"🎉 С ДНЕМ РОЖДЕНИЯ, {user_name.upper()}! 🎉\n\nВ этом году тебе исполнилось {age} лет!\n\nПоздравляю! 🎂"
            
            # Отправляем во все чаты
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    await bot.send_message(chat_id, message_text)
                    print(f"✅ Отправлено поздравление для {user_name} в чат {chat_id}")
                except Exception as e:
                    print(f"❌ Ошибка отправки поздравления для {user_name} в чат {chat_id}: {e}")
        
        print("✅ Проверка дней рождения завершена")
        return True
                
    except Exception as e:
        print(f"❌ Ошибка проверки дней рождения: {e}")
        return False


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

def main_menu(is_admin=False, is_special_user=False, is_group_chat=False, is_fund_manager=False):
    buttons = []
    
    # Добавляем кнопку просмотра сообщений только в беседе
    if is_group_chat:
        buttons.append([InlineKeyboardButton(text="👨‍🏫 Посмотреть сообщения преподов", callback_data="view_teacher_messages")]),
        buttons.append([InlineKeyboardButton(text="📚 Домашнее задание", callback_data="menu_homework")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание", callback_data="menu_rasp")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание на сегодня", callback_data="today_rasp")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание на завтра", callback_data="tomorrow_rasp")]),
        buttons.append([InlineKeyboardButton(text="⏰ Звонки", callback_data="menu_zvonki")]),
        buttons.append([InlineKeyboardButton(text="🎂 Дни рожденья", callback_data="menu_birthdays")]),
        buttons.append([InlineKeyboardButton(text="💰 Фонд Группы", callback_data="menu_group_fund")])  # Новая кнопка

    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙ Админка", callback_data="menu_admin")])
    if is_special_user:
        buttons.append([InlineKeyboardButton(text="✉ Отправить сообщение в беседу", callback_data="send_message_chat")])
    if is_fund_manager:
        buttons.append([InlineKeyboardButton(text="💰 Управление Фондом", callback_data="menu_fund_management")])
    
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

        [InlineKeyboardButton(text="💾 Сохранить статичное расписание", callback_data="admin_save_static_rasp")],
        # Новые кнопки для домашних заданий
        [InlineKeyboardButton(text="📝 Добавить домашнее задание", callback_data="admin_add_homework")],
        [InlineKeyboardButton(text="✏️ Редактировать домашнее задание", callback_data="admin_edit_homework")],
        [InlineKeyboardButton(text="🗑️ Удалить домашнее задание", callback_data="admin_delete_homework")],

        [InlineKeyboardButton(text="👤 Добавить спец-пользователя", callback_data="admin_add_special_user")],
        [InlineKeyboardButton(text="🗑️ Удалить сообщение преподавателя", callback_data="admin_delete_teacher_message")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    return kb

# Меню фонда группы (для всех в беседе)
@dp.callback_query(F.data == "menu_group_fund")
async def menu_group_fund_handler(callback: types.CallbackQuery):
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    balance = await get_fund_balance(pool)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Покупки", callback_data="fund_purchases")],
        [InlineKeyboardButton(text="👥 Список Пожертвований", callback_data="fund_donations")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await callback.message.edit_text(
        f"💰 Фонд Группы\n\n"
        f"💵 Текущий баланс: {balance:.2f} руб.\n\n"
        f"Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

# Список покупок
@dp.callback_query(F.data == "fund_purchases")
async def fund_purchases_handler(callback: types.CallbackQuery):
    purchases = await get_all_purchases(pool)
    
    if not purchases:
        text = "🛍️ Список покупок пуст."
    else:
        text = "🛍️ Список покупок:\n\n"
        for purchase_id, item_name, item_url, price in purchases:
            if item_url and item_url.strip():
                text += f"• {item_name} ({item_url}) - {price:.2f} руб.\n"
            else:
                text += f"• {item_name} - {price:.2f} руб.\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_group_fund")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "fund_donations")
async def fund_donations_handler(callback: types.CallbackQuery):
    members = await get_all_fund_members(pool)
    
    if not members:
        text = "👥 Список пожертвований пуст."
    else:
        text = "👥 Список участников и их балансов:\n\n"
        total_balance = 0
        
        for member_id, full_name, balance in members:
            text += f"• {full_name} = {balance:.2f} руб.\n"
            total_balance += balance
        
        text += f"\n💵 Общая сумма пожертвований: {total_balance:.2f} руб."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_group_fund")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# Меню управления фондом (только для спец-пользователя)
@dp.callback_query(F.data == "menu_fund_management")
async def menu_fund_management_handler(callback: types.CallbackQuery):
    if callback.from_user.id != FUND_MANAGER_USER_ID:
        await callback.answer("⛔ У вас нет прав для управления фондом", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Добавить/убрать человека", callback_data="fund_manage_members")],
        [InlineKeyboardButton(text="💰 Изменить баланс человека", callback_data="fund_manage_balance")],
        [InlineKeyboardButton(text="🛍️ Добавить/удалить покупку", callback_data="fund_manage_purchases")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await callback.message.edit_text(
        "💰 Управление Фондом Группы\n\n"
        "Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

# Управление участниками
@dp.callback_query(F.data == "fund_manage_members")
async def fund_manage_members_handler(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить человека", callback_data="fund_add_member")],
        [InlineKeyboardButton(text="➖ Удалить человека", callback_data="fund_delete_member")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
    ])
    
    await callback.message.edit_text(
        "👥 Управление участниками фонда\n\n"
        "Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "fund_add_member")
async def fund_add_member_start(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="fund_manage_members")]
    ])
    
    # Редактируем существующее сообщение
    await callback.message.edit_text(
        "👤 Добавление участника\n\n"
        "Введите Фамилию И.О. нового участника:",
        reply_markup=kb
    )
    await state.set_state(GroupFundStates.add_member_name)
    await callback.answer()

@dp.message(GroupFundStates.add_member_name)
async def fund_add_member_process(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    
    if not full_name:
        await message.answer("❌ Имя не может быть пустым. Введите Фамилию И.О.:")
        return
    
    try:
        await add_fund_member(pool, full_name)
        
        # Удаляем сообщение с запросом имени (если возможно)
        try:
            await message.delete()
        except:
            pass
        
        # Создаем клавиатуру для возврата
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        
        # Отправляем новое сообщение с результатом
        await message.answer(
            f"✅ Участник '{full_name}' добавлен!\n\n"
            f"💰 Управление Фондом Группы:",
            reply_markup=kb
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении участника: {e}")
    
    await state.clear()

# Удаление участника с пагинацией
@dp.callback_query(F.data == "fund_delete_member")
async def fund_delete_member_start(callback: types.CallbackQuery, state: FSMContext):
    members = await get_all_fund_members(pool)
    
    if not members:
        await callback.message.edit_text("❌ В базе нет участников для удаления.")
        await callback.answer()
        return
    
    await show_members_page(callback, members, page=0, action="delete")
    await callback.answer()

async def show_members_page(callback: types.CallbackQuery, members: list, page: int = 0, action: str = "delete"):
    limit = 10
    start_idx = page * limit
    end_idx = start_idx + limit
    page_members = members[start_idx:end_idx]
    
    keyboard = []
    for member_id, full_name, balance in page_members:
        if action == "delete":
            callback_data = f"confirm_delete_member_{member_id}"
        else:  # balance
            callback_data = f"select_member_balance_{member_id}"
        
        keyboard.append([InlineKeyboardButton(
            text=f"{full_name} ({balance:.2f} руб.)", 
            callback_data=callback_data
        )])
    
    # Остальной код остается таким же...
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅ Назад", callback_data=f"members_page_{page-1}_{action}"))
    
    nav_buttons.append(InlineKeyboardButton(text="🔙 Отмена", callback_data="fund_manage_members"))
    
    if end_idx < len(members):
        nav_buttons.append(InlineKeyboardButton(text="Дальше ➡", callback_data=f"members_page_{page+1}_{action}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    action_text = "удаления" if action == "delete" else "изменения баланса"
    await callback.message.edit_text(
        f"👥 Выберите участника для {action_text} (страница {page + 1}):",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("members_page_"))
async def members_page_handler(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = int(parts[2])
    action = parts[3]
    
    members = await get_all_fund_members(pool)
    await show_members_page(callback, members, page, action)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_member_"))
async def confirm_delete_member_handler(callback: types.CallbackQuery):
    member_id = int(callback.data.split("_")[3])
    
    # Получаем информацию об участнике
    members = await get_all_fund_members(pool)
    member_info = None
    for m_id, full_name, balance in members:
        if m_id == member_id:
            member_info = (full_name, balance)
            break
    
    if not member_info:
        await callback.answer("❌ Участник не найден", show_alert=True)
        return
    
    full_name, balance = member_info
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"final_delete_member_{member_id}")],
        [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="fund_delete_member")]
    ])
    
    await callback.message.edit_text(
        f"🗑️ Подтвердите удаление участника:\n\n"
        f"👤 {full_name}\n"
        f"💰 Баланс: {balance:.2f} руб.\n\n"
        f"Вы уверены, что хотите удалить этого участника?",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("final_delete_member_"))
async def final_delete_member_handler(callback: types.CallbackQuery):
    member_id = int(callback.data.split("_")[3])
    
    try:
        await delete_fund_member(pool, member_id)
        
        # Редактируем текущее сообщение вместо отправки нового
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        
        await callback.message.edit_text(
            "✅ Участник удален!\n\n💰 Управление Фондом Группы:",
            reply_markup=kb
        )
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при удалении участника: {e}")
    
    await callback.answer()

# Управление балансом участников
@dp.callback_query(F.data == "fund_manage_balance")
async def fund_manage_balance_start(callback: types.CallbackQuery, state: FSMContext):
    members = await get_all_fund_members(pool)
    
    if not members:
        await callback.message.edit_text("❌ В базе нет участников.")
        await callback.answer()
        return
    
    await show_members_page(callback, members, page=0, action="balance")
    await callback.answer()


@dp.callback_query(F.data.startswith("select_member_balance_"))
async def select_member_balance_handler(callback: types.CallbackQuery, state: FSMContext):
    member_id = int(callback.data.split("_")[3])
    
    # Получаем информацию об участнике
    members = await get_all_fund_members(pool)
    member_name = None
    current_balance = 0
    
    for m_id, full_name, balance in members:
        if m_id == member_id:
            member_name = full_name
            current_balance = balance
            break
    
    if not member_name:
        await callback.answer("❌ Участник не найден", show_alert=True)
        return
    
    await state.update_data(
        selected_member_id=member_id, 
        selected_member_name=member_name,
        current_balance=current_balance
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="fund_manage_balance")]
    ])
    
    await callback.message.edit_text(
        f"💰 Изменение баланса для: {member_name}\n"
        f"💵 Текущий баланс: {current_balance:.2f} руб.\n\n"
        f"Введите сумму:\n"
        f"• Положительное число (например: 300) - добавить\n"
        f"• Отрицательное число (например: -300) - убрать",
        reply_markup=kb
    )
    await state.set_state(GroupFundStates.enter_balance_change)
    await callback.answer()

@dp.message(GroupFundStates.enter_balance_change)
async def process_balance_change(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        
        data = await state.get_data()
        member_id = data['selected_member_id']
        member_name = data['selected_member_name']
        current_balance = data.get('current_balance', 0)
        
        print(f"🔍 DEBUG: amount={amount}, current_balance={current_balance}, type_current={type(current_balance)}")
        print(f"🔍 DEBUG: member_id={member_id}, member_name={member_name}")
        
        # Обновляем баланс участника
        await update_member_balance(pool, member_id, amount)
        
        # Обновляем общий баланс фонда
        await update_fund_balance(pool, amount)
        
        # Получаем обновленный баланс участника напрямую из базы
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT balance FROM group_fund_members WHERE id = %s", (member_id,))
                result = await cur.fetchone()
                new_balance = float(result[0]) if result else current_balance + amount
        
        print(f"🔍 DEBUG: Новый баланс участника: {new_balance}")
        
        # Создаем клавиатуру для возврата
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        
        # Отправляем сообщение с результатом
        await message.answer(
            f"✅ Баланс обновлен!\n\n"
            f"👤 Участник: {member_name}\n"
            f"💰 Изменение: {amount:+.2f} руб.\n"
            f"💵 Новый баланс: {new_balance:.2f} руб.",
            reply_markup=kb
        )
        
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число:")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка при обновлении баланса: {e}")
        print(f"🔍 DEBUG ERROR: {e}")
        import traceback
        print(f"🔍 DEBUG TRACEBACK: {traceback.format_exc()}")
    
    await state.clear()

# Управление покупками
@dp.callback_query(F.data == "fund_manage_purchases")
async def fund_manage_purchases_handler(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить покупку", callback_data="fund_add_purchase")],
        [InlineKeyboardButton(text="➖ Удалить покупку", callback_data="fund_delete_purchase")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
    ])
    
    await callback.message.edit_text(
        "🛍️ Управление покупками\n\n"
        "Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

# Добавление покупки
@dp.callback_query(F.data == "fund_add_purchase")
async def fund_add_purchase_start(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="fund_manage_purchases")]
    ])
    
    await callback.message.edit_text(
        "🛍️ Добавление покупки\n\n"
        "Введите название товара:",
        reply_markup=kb
    )
    await state.set_state(GroupFundStates.add_purchase_name)
    await callback.answer()

@dp.message(GroupFundStates.add_purchase_name)
async def fund_add_purchase_name(message: types.Message, state: FSMContext):
    item_name = message.text.strip()
    
    if not item_name:
        await message.answer("❌ Название товара не может быть пустым. Введите название:")
        return
    
    await state.update_data(item_name=item_name)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="fund_manage_purchases")]
    ])
    
    await message.answer(
        "Введите ссылку на товар (если есть) или отправьте /skip чтобы пропустить:",
        reply_markup=kb
    )
    await state.set_state(GroupFundStates.add_purchase_url)

@dp.message(GroupFundStates.add_purchase_url)
async def fund_add_purchase_url(message: types.Message, state: FSMContext):
    item_url = message.text.strip()
    
    if item_url.lower() == '/skip':
        item_url = ""
    
    await state.update_data(item_url=item_url)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="fund_manage_purchases")]
    ])
    
    await message.answer(
        "Введите цену товара в рублях:",
        reply_markup=kb
    )
    await state.set_state(GroupFundStates.add_purchase_price)

@dp.message(GroupFundStates.add_purchase_price)
async def fund_add_purchase_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        
        if price <= 0:
            await message.answer("❌ Цена должна быть положительным числом. Введите цену:")
            return
        
        data = await state.get_data()
        item_name = data['item_name']
        item_url = data.get('item_url', '')
        
        # Добавляем покупку
        await add_purchase(pool, item_name, item_url, price)
        
        balance = await get_fund_balance(pool)
        
        # Возвращаем в меню управления одним сообщением
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        
        try:
            await message.edit_text(
                f"✅ Покупка добавлена!\n\n"
                f"🛍️ Товар: {item_name}\n"
                f"🔗 Ссылка: {item_url if item_url else 'нет'}\n"
                f"💰 Цена: {price:.2f} руб.\n\n"
                f"💵 Новый баланс фонда: {balance:.2f} руб.\n\n"
                f"💰 Управление Фондом Группы:",
                reply_markup=kb
            )
        except:
            await message.answer(
                f"✅ Покупка добавлена!\n\n"
                f"🛍️ Товар: {item_name}\n"
                f"🔗 Ссылка: {item_url if item_url else 'нет'}\n"
                f"💰 Цена: {price:.2f} руб.\n\n"
                f"💵 Новый баланс фонда: {balance:.2f} руб.\n\n"
                f"💰 Управление Фондом Группы:",
                reply_markup=kb
            )
        
    except ValueError:
        await message.answer("❌ Неверный формат цены. Введите число:")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении покупки: {e}")
    
    await state.clear()

# Удаление покупки с пагинацией
@dp.callback_query(F.data == "fund_delete_purchase")
async def fund_delete_purchase_start(callback: types.CallbackQuery):
    purchases = await get_all_purchases(pool)
    
    if not purchases:
        await callback.message.edit_text("❌ В базе нет активных покупок.")
        await callback.answer()
        return
    
    await show_purchases_page(callback, purchases, page=0)
    await callback.answer()

async def show_purchases_page(callback: types.CallbackQuery, purchases: list, page: int = 0):
    limit = 10
    start_idx = page * limit
    end_idx = start_idx + limit
    page_purchases = purchases[start_idx:end_idx]
    
    keyboard = []
    for purchase_id, item_name, item_url, price in page_purchases:
        display_text = f"{item_name} - {price:.2f} руб."
        if len(display_text) > 30:
            display_text = display_text[:27] + "..."
        
        keyboard.append([InlineKeyboardButton(
            text=display_text, 
            callback_data=f"confirm_delete_purchase_{purchase_id}"
        )])
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅ Назад", callback_data=f"purchases_page_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text="🔙 Отмена", callback_data="fund_manage_purchases"))
    
    if end_idx < len(purchases):
        nav_buttons.append(InlineKeyboardButton(text="Дальше ➡", callback_data=f"purchases_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.edit_text(
        f"🗑️ Выберите покупку для удаления (страница {page + 1}):",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("purchases_page_"))
async def purchases_page_handler(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    
    purchases = await get_all_purchases(pool)
    await show_purchases_page(callback, purchases, page)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_purchase_"))
async def confirm_delete_purchase_handler(callback: types.CallbackQuery):
    purchase_id = int(callback.data.split("_")[3])
    
    # Получаем информацию о покупке
    purchases = await get_all_purchases(pool)
    purchase_info = None
    for p_id, item_name, item_url, price in purchases:
        if p_id == purchase_id:
            purchase_info = (item_name, item_url, price)
            break
    
    if not purchase_info:
        await callback.answer("❌ Покупка не найдена", show_alert=True)
        return
    
    item_name, item_url, price = purchase_info
    current_balance = await get_fund_balance(pool)
    new_balance = current_balance + price
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"final_delete_purchase_{purchase_id}")],
        [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="fund_delete_purchase")]
    ])
    
    await callback.message.edit_text(
        f"🗑️ Подтвердите удаление покупки:\n\n"
        f"🛍️ Товар: {item_name}\n"
        f"🔗 Ссылка: {item_url if item_url else 'нет'}\n"
        f"💰 Цена: {price:.2f} руб.\n\n"
        f"💵 Баланс до удаления: {current_balance:.2f} руб.\n"
        f"💵 Баланс после удаления: {new_balance:.2f} руб.\n\n"
        f"Вы уверены, что хотите удалить эту покупку?",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("final_delete_purchase_"))
async def final_delete_purchase_handler(callback: types.CallbackQuery):
    purchase_id = int(callback.data.split("_")[3])
    
    try:
        await delete_purchase(pool, purchase_id)
        current_balance = await get_fund_balance(pool)
        
        await callback.message.edit_text(
            f"✅ Покупка удалена!\n\n"
            f"💵 Текущий баланс фонда: {current_balance:.2f} руб."
        )
        
        # Возвращаем в меню управления
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        await callback.message.answer("💰 Управление Фондом Группы:", reply_markup=kb)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при удалении покупки: {e}")
    
    await callback.answer()

# Обработчики для домашних заданий в беседах
@dp.callback_query(F.data == "menu_homework")
async def menu_homework_handler(callback: types.CallbackQuery):
    """Показывает список домашних заданий"""
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    homework_list = await get_all_homework(pool)
    
    if not homework_list:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await callback.message.edit_text(
            "📚 Домашнее задание\n\n"
            "Пока нет заданных домашних заданий.",
            reply_markup=kb
        )
        return
    
    # Форматируем список домашних заданий - УБИРАЕМ ОБРЕЗАНИЕ
    homework_text = "📚 Домашнее задание:\n\n"
    for hw_id, subject_name, due_date, task_text, created_at in homework_list:
        # Форматируем дату
        due_date_obj = due_date if isinstance(due_date, datetime.date) else datetime.datetime.strptime(str(due_date), '%Y-%m-%d').date()
        due_date_str = due_date_obj.strftime("%d.%m.%Y")
        
        # УБИРАЕМ ОБРЕЗАНИЕ - показываем полный текст
        homework_text += f"📅 {due_date_str} | {subject_name}\n"
        homework_text += f"📝 {task_text}\n"
        homework_text += "─" * 30 + "\n"
    
    # Если текст слишком длинный, разбиваем на несколько сообщений
    if len(homework_text) > 4000:
        parts = []
        current_part = ""
        
        for line in homework_text.split('\n'):
            if len(current_part + line + '\n') > 4000:
                parts.append(current_part)
                current_part = line + '\n'
            else:
                current_part += line + '\n'
        
        if current_part:
            parts.append(current_part)
        
        # Отправляем первое сообщение с кнопкой
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await callback.message.edit_text(parts[0], reply_markup=kb)
        
        # Отправляем остальные части как отдельные сообщения
        for part in parts[1:]:
            await callback.message.answer(part)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await callback.message.edit_text(homework_text, reply_markup=kb)
    
    await callback.answer()

@dp.callback_query(F.data == "menu_birthdays")
async def menu_birthdays_handler(callback: types.CallbackQuery):
    """Показывает список всех дней рождений"""
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    birthdays = await get_all_birthdays(pool)
    if not birthdays:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
        ])
        await callback.message.edit_text(
            "🎂 Список дней рождений пуст.",
            reply_markup=kb
        )
        return

    text = "🎂 Дни рожденья:\n\n"
    for _, name, date, *_ in birthdays:
        if isinstance(date, datetime.date):
            date_str = date.strftime("%d.%m.%Y")
        else:
            date_str = datetime.datetime.strptime(str(date), "%Y-%m-%d").strftime("%d.%m.%Y")
        text += f"👤 {name}: {date_str}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()



# Админские обработчики для домашних заданий
@dp.callback_query(F.data == "admin_add_homework")
async def admin_add_homework_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])

    await callback.message.edit_text(
        "📝 Добавление домашнего задания\n\n"
        "Введите дату выполнения в формате ДД.ММ.ГГГГ (например: 15.12.2024):",
        reply_markup=kb
    )
    await state.set_state(AddHomeworkState.due_date)
    await callback.answer()

@dp.message(AddHomeworkState.due_date)
async def process_homework_due_date(message: types.Message, state: FSMContext):
    due_date_str = message.text.strip()
    
    # Проверка на отмену
    if due_date_str.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    # Проверяем формат даты и конвертируем для хранения
    try:
        due_date = datetime.datetime.strptime(due_date_str, '%d.%m.%Y').date()
        # Сохраняем в формате DD.MM.YYYY для отображения, но будем конвертировать при сохранении в БД
        await state.update_data(due_date=due_date_str)
        
        # Получаем список предметов
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, name FROM subjects ORDER BY name")
                subjects = await cur.fetchall()
        
        if not subjects:
            await message.answer("❌ В базе нет предметов. Сначала добавьте предметы.")
            await state.clear()
            return
        
        # Создаем кнопки выбора предмета
        keyboard = []
        for subject_id, name in subjects:
            keyboard.append([InlineKeyboardButton(text=name, callback_data=f"hw_subject_{subject_id}")])
        
        keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await message.answer(
            f"📅 Дата выполнения: {due_date_str}\n\n"
            "Выберите предмет:",
            reply_markup=kb
        )
        await state.set_state(AddHomeworkState.subject)
        
    except ValueError:
        await message.answer("❌ Неверный формат даты. Введите в формате ДД.ММ.ГГГГ (например: 15.12.2024):")

@dp.callback_query(F.data.startswith("hw_subject_"))
async def process_homework_subject(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data[len("hw_subject_"):])
    
    # Получаем название предмета
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
            subject_name = (await cur.fetchone())[0]
    
    await state.update_data(subject_id=subject_id, subject_name=subject_name)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await callback.message.edit_text(
        f"📅 Дата выполнения: {(await state.get_data())['due_date']}\n"
        f"📚 Предмет: {subject_name}\n\n"
        "Теперь введите текст задания:",
        reply_markup=kb
    )
    await state.set_state(AddHomeworkState.task_text)
    await callback.answer()

@dp.message(AddHomeworkState.task_text)
async def process_homework_task_text(message: types.Message, state: FSMContext):
    task_text = message.text.strip()
    
    # Проверка на отмену
    if task_text.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    if not task_text:
        await message.answer("❌ Текст задания не может быть пустым. Введите задание:")
        return
    
    data = await state.get_data()
    
    try:
        # Добавляем домашнее задание (без chat_id - общее для всех)
        await add_homework(pool, data['subject_id'], data['due_date'], task_text)
        
        await message.answer(
            f"✅ Домашнее задание добавлено!\n\n"
            f"📅 Дата выполнения: {data['due_date']}\n"
            f"📚 Предмет: {data['subject_name']}\n"
            f"📝 Задание: {task_text}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении задания: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "admin_edit_homework")
async def admin_edit_homework_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    homework_list = await get_all_homework(pool)
    
    if not homework_list:
        await callback.message.edit_text(
            "✏️ Редактирование домашнего задания\n\n"
            "❌ В базе нет домашних заданий для редактирования."
        )
        await callback.answer()
        return
    
    # Создаем кнопки выбора задания
    keyboard = []
    for hw_id, subject_name, due_date, task_text, created_at in homework_list:
        due_date_obj = due_date if isinstance(due_date, datetime.date) else datetime.datetime.strptime(str(due_date), '%Y-%m-%d').date()
        due_date_str = due_date_obj.strftime("%d.%m.%Y")
        
        short_task = task_text[:30] + "..." if len(task_text) > 30 else task_text
        button_text = f"{due_date_str} | {subject_name}: {short_task}"
        
        keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"edit_hw_{hw_id}")])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.edit_text(
        "✏️ Редактирование домашнего задания\n\n"
        "Выберите задание для редактирования:",
        reply_markup=kb
    )
    await state.set_state(EditHomeworkState.homework_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_hw_"))
async def process_edit_homework_select(callback: types.CallbackQuery, state: FSMContext):
    homework_id = int(callback.data[len("edit_hw_"):])
    
    # Получаем информацию о задании
    homework = await get_homework_by_id(pool, homework_id)
    if not homework:
        await callback.answer("❌ Задание не найдено", show_alert=True)
        return
    
    hw_id, subject_name, due_date, task_text, created_at, subject_id = homework
    
    await state.update_data(
        homework_id=hw_id,
        current_subject_id=subject_id,
        current_subject_name=subject_name,
        current_due_date=due_date,
        current_task_text=task_text
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    due_date_str = due_date.strftime("%d.%m.%Y") if isinstance(due_date, datetime.date) else due_date
    
    await callback.message.edit_text(
        f"✏️ Редактирование задания:\n\n"
        f"📅 Текущая дата: {due_date_str}\n"
        f"📚 Текущий предмет: {subject_name}\n"
        f"📝 Текущее задание: {task_text}\n\n"
        "Введите новую дату выполнения (ДД.ММ.ГГГГ) или нажмите /skip чтобы оставить текущую:",
        reply_markup=kb
    )
    await state.set_state(EditHomeworkState.due_date)
    await callback.answer()

@dp.message(EditHomeworkState.due_date)
async def process_edit_homework_due_date(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == '/skip':
        # Пропускаем изменение даты
        await state.update_data(new_due_date=None)
    else:
        due_date_str = message.text.strip()
        try:
            # Проверяем валидность даты
            datetime.datetime.strptime(due_date_str, '%d.%m.%Y')
            await state.update_data(new_due_date=due_date_str)
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введите в формате ДД.ММ.ГГГГ или /skip:")
            return
    
    data = await state.get_data()
    
    # Получаем список предметов для выбора
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM subjects ORDER BY name")
            subjects = await cur.fetchall()
    
    keyboard = []
    for subject_id, name in subjects:
        keyboard.append([InlineKeyboardButton(text=name, callback_data=f"edit_hw_subject_{subject_id}")])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    new_date_info = data.get('new_due_date', 'оставить текущую')
    await message.answer(
        f"📅 Новая дата: {new_date_info}\n\n"
        "Выберите новый предмет или введите /skip чтобы оставить текущий:",
        reply_markup=kb
    )
    await state.set_state(EditHomeworkState.subject)

@dp.callback_query(F.data.startswith("edit_hw_subject_"))
async def process_edit_homework_subject(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "menu_admin":
        await callback.message.edit_text("⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        await callback.answer()
        return
    
    subject_id = int(callback.data[len("edit_hw_subject_"):])
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
            subject_name = (await cur.fetchone())[0]
    
    await state.update_data(new_subject_id=subject_id, new_subject_name=subject_name)
    
    data = await state.get_data()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    new_date_info = data.get('new_due_date', 'текущая')
    new_subject_info = data.get('new_subject_name', 'текущий')
    
    await callback.message.edit_text(
        f"✏️ Редактирование задания:\n\n"
        f"📅 Дата: {new_date_info}\n"
        f"📚 Предмет: {new_subject_info}\n\n"
        "Введите новый текст задания или /skip чтобы оставить текущий:",
        reply_markup=kb
    )
    await state.set_state(EditHomeworkState.task_text)
    await callback.answer()

@dp.message(EditHomeworkState.subject)
async def process_edit_homework_subject_skip(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == '/skip':
        # Пропускаем изменение предмета
        data = await state.get_data()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
        ])
        
        new_date_info = data.get('new_due_date', 'текущая')
        
        await message.answer(
            f"✏️ Редактирование задания:\n\n"
            f"📅 Дата: {new_date_info}\n"
            f"📚 Предмет: текущий\n\n"
            "Введите новый текст задания или /skip чтобы оставить текущий:",
            reply_markup=kb
        )
        await state.set_state(EditHomeworkState.task_text)
    else:
        # Если введен не /skip, показываем список предметов снова
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, name FROM subjects ORDER BY name")
                subjects = await cur.fetchall()
        
        keyboard = []
        for subject_id, name in subjects:
            keyboard.append([InlineKeyboardButton(text=name, callback_data=f"edit_hw_subject_{subject_id}")])
        
        keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await message.answer(
            "Выберите новый предмет или введите /skip чтобы оставить текущий:",
            reply_markup=kb
        )


@dp.message(EditHomeworkState.task_text)
async def process_edit_homework_task_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    if message.text.strip().lower() == '/skip':
        new_task_text = data['current_task_text']
    else:
        new_task_text = message.text.strip()
        if not new_task_text:
            await message.answer("❌ Текст задания не может быть пустым. Введите задание или /skip:")
            return
    
    # Подготавливаем данные для обновления
    subject_id = data.get('new_subject_id', data['current_subject_id'])
    due_date = data.get('new_due_date', data['current_due_date'])
    
    # Если дата в формате DD.MM.YYYY, конвертируем в YYYY-MM-DD
    if isinstance(due_date, str) and '.' in due_date:
        try:
            due_date = datetime.datetime.strptime(due_date, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            await message.answer("❌ Ошибка в формате даты. Исправьте дату и попробуйте снова.")
            await state.clear()
            return
    
    try:
        await update_homework(pool, data['homework_id'], subject_id, due_date, new_task_text)
        
        # Получаем обновленную информацию для отображения
        updated_hw = await get_homework_by_id(pool, data['homework_id'])
        if updated_hw:
            hw_id, subject_name, due_date, task_text, created_at, subject_id = updated_hw
            due_date_str = due_date.strftime("%d.%m.%Y") if isinstance(due_date, datetime.date) else due_date
            
            await message.answer(
                f"✅ Домашнее задание обновлено!\n\n"
                f"📅 Дата выполнения: {due_date_str}\n"
                f"📚 Предмет: {subject_name}\n"
                f"📝 Задание: {task_text}\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        else:
            await message.answer(
                "✅ Домашнее задание обновлено!\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при обновлении задания: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "admin_delete_homework")
async def admin_delete_homework_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    homework_list = await get_all_homework(pool)
    
    if not homework_list:
        await callback.message.edit_text(
            "🗑️ Удаление домашнего задания\n\n"
            "❌ В базе нет домашних заданий для удаления."
        )
        await callback.answer()
        return
    
    # Создаем кнопки выбора задания
    keyboard = []
    for hw_id, subject_name, due_date, task_text, created_at in homework_list:
        due_date_obj = due_date if isinstance(due_date, datetime.date) else datetime.datetime.strptime(str(due_date), '%Y-%m-%d').date()
        due_date_str = due_date_obj.strftime("%d.%m.%Y")
        
        short_task = task_text[:30] + "..." if len(task_text) > 30 else task_text
        button_text = f"{due_date_str} | {subject_name}: {short_task}"
        
        keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"delete_hw_{hw_id}")])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.edit_text(
        "🗑️ Удаление домашнего задания\n\n"
        "Выберите задание для удаления:",
        reply_markup=kb
    )
    await state.set_state(DeleteHomeworkState.homework_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_hw_"))
async def process_delete_homework_select(callback: types.CallbackQuery, state: FSMContext):
    homework_id = int(callback.data[len("delete_hw_"):])
    
    # Получаем информацию о задании
    homework = await get_homework_by_id(pool, homework_id)
    if not homework:
        await callback.answer("❌ Задание не найдено", show_alert=True)
        return
    
    hw_id, subject_name, due_date, task_text, created_at, subject_id = homework
    
    due_date_str = due_date.strftime("%d.%m.%Y") if isinstance(due_date, datetime.date) else due_date
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_hw_{hw_id}")],
        [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="menu_admin")]
    ])
    
    await callback.message.edit_text(
        f"🗑️ Подтвердите удаление задания:\n\n"
        f"📅 Дата: {due_date_str}\n"
        f"📚 Предмет: {subject_name}\n"
        f"📝 Задание: {task_text}\n\n"
        "Вы уверены, что хотите удалить это задание?",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_hw_"))
async def process_confirm_delete_homework(callback: types.CallbackQuery):
    homework_id = int(callback.data[len("confirm_delete_hw_"):])
    
    try:
        # Получаем информацию перед удалением для сообщения
        homework = await get_homework_by_id(pool, homework_id)
        if homework:
            hw_id, subject_name, due_date, task_text, created_at, subject_id = homework
            due_date_str = due_date.strftime("%d.%m.%Y") if isinstance(due_date, datetime.date) else due_date
            
            await delete_homework(pool, homework_id)
            
            await callback.message.edit_text(
                f"✅ Домашнее задание удалено!\n\n"
                f"📅 Дата: {due_date_str}\n"
                f"📚 Предмет: {subject_name}\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        else:
            await callback.message.edit_text(
                "❌ Задание не найдено.\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
            
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при удалении задания: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
    await callback.answer()


@dp.callback_query(F.data == "admin_add_lesson")
async def admin_add_lesson_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM subjects ORDER BY name")
            subjects = await cur.fetchall()
    
    if not subjects:
        await callback.message.edit_text("❌ В базе нет предметов. Сначала добавьте предметы.")
        await callback.answer()
        return
    
    buttons = []
    for subject_id, subject_name in subjects:
        # Обрезаем название для отображения
        display_name = subject_name[:30] + "..." if len(subject_name) > 30 else subject_name
        
        # Используем ID предмета для callback_data чтобы избежать проблем с названиями
        buttons.append([InlineKeyboardButton(
            text=display_name, 
            callback_data=f"choose_subject_id_{subject_id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text("Выберите предмет:", reply_markup=kb)
    await state.set_state(AddLessonState.subject)

@dp.callback_query(F.data.startswith("choose_subject_id_"))
async def choose_subject_by_id(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data[len("choose_subject_id_"):])
    
    # Получаем полную информацию о предмете из базы
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name, rK FROM subjects WHERE id=%s", (subject_id,))
            result = await cur.fetchone()
            
            if not result:
                await callback.answer("❌ Предмет не найден в базе данных", show_alert=True)
                return
            
            subject_name, is_rk = result
    
    await state.update_data(
        subject=subject_name,
        subject_id=subject_id,
        is_rk=is_rk
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await callback.message.edit_text(
        f"📚 Выбран предмет: {subject_name}\n"
        f"🔧 Тип: {'с запросом кабинета (rK)' if is_rk else 'с фиксированным кабинетом'}\n\n"
        "Выберите четность недели:",
        reply_markup=kb
    )
    await state.set_state(AddLessonState.week_type)
    await callback.answer()

@dp.callback_query(F.data.startswith("choose_subject_"))
async def choose_subject(callback: types.CallbackQuery, state: FSMContext):
    # Получаем название предмета из callback_data (без префикса)
    callback_name = callback.data[len("choose_subject_"):]
    
    # Восстанавливаем оригинальное название (заменяем _ обратно на пробелы)
    original_name = callback_name.replace('_', ' ')
    
    # Находим точное название предмета в базе данных
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM subjects WHERE name LIKE %s", (f"%{original_name}%",))
            result = await cur.fetchone()
            
            if not result:
                await callback.answer("❌ Предмет не найден в базе данных", show_alert=True)
                return
            
            exact_subject_name = result[0]
    
    await state.update_data(subject=exact_subject_name)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data="week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data="week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await callback.message.edit_text(
        f"📚 Выбран предмет: {exact_subject_name}\n\n"
        "Выберите четность недели:",
        reply_markup=kb
    )
    await state.set_state(AddLessonState.week_type)
    await callback.answer()
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
            usage_count_rasp = (await cur.fetchone())[0]
            
            # Проверяем, используется ли предмет в домашних заданиях
            await cur.execute("SELECT COUNT(*) FROM homework WHERE subject_id=%s", (subject_id,))
            usage_count_homework = (await cur.fetchone())[0]
            
            total_usage = usage_count_rasp + usage_count_homework
            
            if total_usage > 0:
                # Предмет используется - предупреждаем
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Да, удалить ВСЕ связанные данные", callback_data=f"confirm_delete_subject_{subject_id}")],
                    [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="cancel_delete_subject")]
                ])
                
                usage_text = []
                if usage_count_rasp > 0:
                    usage_text.append(f"{usage_count_rasp} урок(ов) в расписании")
                if usage_count_homework > 0:
                    usage_text.append(f"{usage_count_homework} домашних заданий")
                
                await callback.message.edit_text(
                    f"⚠️ Внимание!\n\n"
                    f"Предмет '{name}' используется в:\n"
                    f"{', '.join(usage_text)}\n\n"
                    f"Удалить предмет и ВСЕ связанные данные?",
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
            
            # 1. Сначала удаляем уроки с этим предметом
            await cur.execute("DELETE FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
            
            # 2. Удаляем модификации с этим предметом
            await cur.execute("DELETE FROM rasp_modifications WHERE subject_id=%s", (subject_id,))
            
            # 3. Удаляем статичное расписание с этим предметом
            await cur.execute("DELETE FROM static_rasp WHERE subject_id=%s", (subject_id,))
            
            # 4. Удаляем домашние задания с этим предметом
            await cur.execute("DELETE FROM homework WHERE subject_id=%s", (subject_id,))
            
            # 5. Теперь удаляем сам предмет
            await cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
    
    await callback.message.edit_text(
        f"✅ Предмет '{subject_name}' и все связанные данные удалены."
    )
    
    # Возвращаем в админ-меню
    await callback.message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
    await callback.answer()

@dp.message(Command("safe_delete_subject"))
async def cmd_safe_delete_subject(message: types.Message):
    """Безопасное удаление предмета с проверкой всех связей"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("⚠ Использование: /safe_delete_subject <id_предмета>")
            return
        
        subject_id = int(parts[1])
        
        report = "📊 ОТЧЕТ ПО УДАЛЕНИЮ ПРЕДМЕТА:\n\n"
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Получаем информацию о предмете
                await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
                subject_row = await cur.fetchone()
                
                if not subject_row:
                    await message.answer("❌ Предмет не найден")
                    return
                
                subject_name = subject_row[0]
                report += f"📚 Предмет: {subject_name} (ID: {subject_id})\n\n"
                
                # Проверяем связи
                await cur.execute("SELECT COUNT(*) FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
                rasp_count = (await cur.fetchone())[0]
                report += f"📅 Уроков в расписании: {rasp_count}\n"
                
                await cur.execute("SELECT COUNT(*) FROM rasp_modifications WHERE subject_id=%s", (subject_id,))
                mod_count = (await cur.fetchone())[0]
                report += f"🔄 Модификаций: {mod_count}\n"
                
                await cur.execute("SELECT COUNT(*) FROM static_rasp WHERE subject_id=%s", (subject_id,))
                static_count = (await cur.fetchone())[0]
                report += f"📋 Статичных записей: {static_count}\n"
                
                await cur.execute("SELECT COUNT(*) FROM homework WHERE subject_id=%s", (subject_id,))
                homework_count = (await cur.fetchone())[0]
                report += f"📝 Домашних заданий: {homework_count}\n\n"
                
                total_records = rasp_count + mod_count + static_count + homework_count
                
                if total_records > 0:
                    report += f"⚠️ Всего связанных записей: {total_records}\n\n"
                    report += "Для удаления используйте команду:\n"
                    report += f"/force_delete_subject {subject_id}"
                else:
                    report += "✅ Нет связанных записей, можно безопасно удалить"
        
        await message.answer(report)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("force_delete_subject"))
async def cmd_force_delete_subject(message: types.Message):
    """Принудительное удаление предмета со всеми связями"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("⚠ Использование: /force_delete_subject <id_предмета>")
            return
        
        subject_id = int(parts[1])
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Получаем название предмета
                await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
                subject_name = (await cur.fetchone())[0]
                
                # Удаляем в правильном порядке (от зависимых к основным)
                deleted_counts = {}
                
                # 1. Домашние задания
                await cur.execute("DELETE FROM homework WHERE subject_id=%s", (subject_id,))
                deleted_counts['homework'] = cur.rowcount
                
                # 2. Статичное расписание
                await cur.execute("DELETE FROM static_rasp WHERE subject_id=%s", (subject_id,))
                deleted_counts['static_rasp'] = cur.rowcount
                
                # 3. Модификации
                await cur.execute("DELETE FROM rasp_modifications WHERE subject_id=%s", (subject_id,))
                deleted_counts['modifications'] = cur.rowcount
                
                # 4. Основное расписание
                await cur.execute("DELETE FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
                deleted_counts['rasp_detailed'] = cur.rowcount
                
                # 5. Сам предмет
                await cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
                deleted_counts['subject'] = 1
                
                # Формируем отчет
                report = f"✅ Предмет '{subject_name}' удален!\n\n"
                report += "Удаленные записи:\n"
                for table, count in deleted_counts.items():
                    report += f"• {table}: {count}\n"
                
                total_deleted = sum(deleted_counts.values())
                report += f"\nВсего удалено записей: {total_deleted}"
                
                await message.answer(report)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка удаления: {e}")
    
@dp.callback_query(F.data == "menu_back")
async def menu_back_handler(callback: types.CallbackQuery, state: FSMContext):
    # Проверка флуда
    if check_flood(callback.from_user.id):
        try:
            await callback.answer("⏳ Подождите немного...", show_alert=False)
        except:
            pass
        return
    # Разрешаем в ЛС и разрешенных чатах
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        try:
            await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        except:
            pass
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

    # Проверяем менеджера фонда
    is_fund_manager = (callback.from_user.id == FUND_MANAGER_USER_ID) and is_private

    try:
        # Удаляем старое сообщение если возможно
        await callback.message.delete()
    except Exception:
        pass  # Игнорируем ошибку удаления сообщения
    
    # Используем безопасную отправку
    await safe_send_message(
        callback.message.chat.id,
        "Выберите действие:",
        reply_markup=main_menu(
            is_admin=is_admin, 
            is_special_user=is_special_user, 
            is_group_chat=not is_private,
            is_fund_manager=is_fund_manager
        ),
        delay=0.2
    )
    
    try:
        await callback.answer()
    except:
        pass



@dp.callback_query(F.data == "cancel_delete_subject")
async def cancel_delete_subject(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Удаление отменено.")
    await menu_back_handler(callback, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("subject_type_"))
async def process_subject_type_choice(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора типа предмета"""
    try:
        subject_type = callback.data[len("subject_type_"):]
        data = await state.get_data()
        subject_name = data["name"]
        
        if subject_type == "fixed":
            # Предмет с фиксированным кабинетом
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
            ])
            
            await callback.message.edit_text(
                f"📝 Предмет: {subject_name}\n"
                f"🏫 Тип: с фиксированным кабинетом\n\n"
                "Введите номер кабинета:",
                reply_markup=kb
            )
            await state.set_state(AddSubjectState.cabinet)
            
        elif subject_type == "rk":
            # Предмет с запросом кабинета (rK)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("INSERT INTO subjects (name, rK) VALUES (%s, %s)", (subject_name, True))
            
            await callback.message.edit_text(
                f"✅ Предмет добавлен!\n\n"
                f"📚 Название: {subject_name}\n"
                f"🔢 Тип: с запросом кабинета (rK)\n\n"
                f"Теперь при добавлении этого предмета в расписание "
                f"кабинет будет запрашиваться отдельно.",
                reply_markup=admin_menu()
            )
            await state.clear()
        
        await callback.answer()
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при добавлении предмета: {e}")
        await state.clear()
        await callback.answer()

@dp.callback_query(F.data.startswith("pair_"))
async def choose_pair(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("pair_"):])
    await state.update_data(pair_number=pair_number)
    
    data = await state.get_data()
    subject_name = data["subject"]
    subject_id = data["subject_id"]
    is_rk = data["is_rk"]
    
    try:
        if is_rk:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
            ])
            await callback.message.edit_text(
                f"📚 Предмет: {subject_name}\n"
                f"🔢 Тип: с запросом кабинета\n\n"
                "Введите кабинет для этой пары:",
                reply_markup=kb
            )
            await state.set_state(AddLessonState.cabinet)
        else:
            cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
            
            if cabinet_match:
                cabinet = cabinet_match.group(2)
                clean_subject_name = subject_name.replace(cabinet_match.group(0), '').strip()
            else:
                cabinet = "Не указан"
                clean_subject_name = subject_name
            
            # Сохраняем как модификацию для всех чатов
            for chat_id in ALLOWED_CHAT_IDS:
                await save_rasp_modification(pool, chat_id, data["day"], data["week_type"], pair_number, subject_id, cabinet)
            
            display_name = clean_subject_name
            
            await callback.message.edit_text(
                f"✅ Урок '{display_name}' добавлен как изменение расписания!\n"
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

async def reset_rasp_for_new_week():
    """Сбрасывает модификации расписания при смене недели"""
    try:
        current_week = await get_current_week_type(pool)
        previous_week = 2 if current_week == 1 else 1
        
        # Очищаем модификации для предыдущей недели
        await clear_rasp_modifications(pool, previous_week)
        print(f"✅ Сброшены модификации расписания для недели {previous_week}")
        
    except Exception as e:
        print(f"❌ Ошибка при сбросе расписания: {e}")

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
    
    if cabinet.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    # Получаем данные из состояния
    day = data.get("day")
    week_type = data.get("week_type") 
    pair_number = data.get("pair_number")
    
    if not all([day, week_type, pair_number]):
        await message.answer("❌ Ошибка: не найдены данные о паре. Начните заново.")
        await state.clear()
        return
    
    # Устанавливаем кабинет для ВСЕХ чатов
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for chat_id in ALLOWED_CHAT_IDS:
                await cur.execute("""
                    SELECT id FROM rasp_detailed
                    WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
                """, (chat_id, day, week_type, pair_number))
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
                    """, (chat_id, day, week_type, pair_number, cabinet))
    
    # Автоматическая синхронизация
   # source_chat_id = ALLOWED_CHAT_IDS[0]
    # await sync_rasp_to_all_chats(source_chat_id)
    
    await message.answer(
        f"✅ Кабинет установлен для всех чатов!\n"
        f"📅 День: {DAYS[day-1]}\n"
        f"🔢 Пара: {pair_number}\n"
        f"🏫 Кабинет: {cabinet}\n\n"
        f"⚙ Админ-панель:",
        reply_markup=admin_menu()
    )
    await state.clear()

@dp.callback_query(F.data.startswith("cab_pair_"))
async def set_cab_pair_number(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("cab_pair_"):])
    await state.update_data(pair_number=pair_number)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    data = await state.get_data()
    day = data.get("day")
    week_type = data.get("week_type")
    
    await callback.message.edit_text(
        f"📅 День: {DAYS[day-1]}\n"
        f"🔢 Пара: {pair_number}\n"
        f"📊 Неделя: {'нечетная' if week_type == 1 else 'четная'}\n\n"
        "Введите номер кабинета:",
        reply_markup=kb
    )
    await state.set_state(SetCabinetState.cabinet)
    await callback.answer()

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

    try:
        # Очищаем пару для ВСЕХ чатов
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for chat_id in ALLOWED_CHAT_IDS:
                    # УДАЛЯЕМ запись вместо обновления на NULL
                    await cur.execute("""
                        DELETE FROM rasp_detailed
                        WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
                    """, (chat_id, data["day"], data["week_type"], pair_number))

        # Автоматическая синхронизация
        source_chat_id = ALLOWED_CHAT_IDS[0]
        await sync_rasp_to_all_chats(source_chat_id)

        await callback.message.edit_text(
            f"✅ Пара {pair_number} ({DAYS[data['day']-1]}, неделя {data['week_type']}) очищена во всех чатах.",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при очистке пары: {e}",
            reply_markup=admin_menu()
        )
    
    await state.clear()
    await callback.answer()

@dp.message(Command("sync_rasp"))
async def sync_rasp_all_chats(message: types.Message):
    """Синхронизирует расписание между всеми чатами"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    try:
        main_chat_id = ALLOWED_CHAT_IDS[0]
        synced_count = 0
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Копируем расписание из основного чата во все остальные
                for chat_id in ALLOWED_CHAT_IDS[1:]:  # Все кроме первого
                    # Очищаем расписание в целевом чате
                    await cur.execute("DELETE FROM rasp_detailed WHERE chat_id=%s", (chat_id,))
                    
                    # Копируем из основного чата
                    await cur.execute("""
                        INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                        SELECT %s, day, week_type, pair_number, subject_id, cabinet 
                        FROM rasp_detailed 
                        WHERE chat_id=%s
                    """, (chat_id, main_chat_id))
                    
                    synced_count += 1
        
        await message.answer(f"✅ Расписание синхронизировано! Обновлено {synced_count} чатов.")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка синхронизации расписания: {e}")


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
    # Добавляем небольшую задержку для избежания флуда
    await asyncio.sleep(0.1)
    
    try:
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
            try:
                current_week = await get_current_week_type(pool)
                week_name = "Нечетная" if current_week == 1 else "Четная"
                week_info = f"\n\n📅 Сейчас неделя: {week_name}"
            except Exception as e:
                print(f"Ошибка получения четности: {e}")
                week_info = f"\n\n📅 Информация о неделе временно недоступна"
        
        nickname = await get_nickname(pool, user.id)
        greet = f"👋 Салам, {nickname}!\n\n" if nickname else "👋 Салам!\n\n"
        full_text = greet + text + week_info
        
        # Ограничиваем длину текста для Telegram (4096 символов)
        if len(full_text) > 4000:
            full_text = full_text[:3990] + "\n\n... (сообщение обрезано)"
        
        if callback:
            try:
                # Сначала пробуем редактировать
                await callback.message.edit_text(full_text, reply_markup=markup)
            except Exception as edit_error:
                print(f"Не удалось редактировать сообщение: {edit_error}")
                try:
                    # Если не получилось редактировать, отправляем новое
                    await asyncio.sleep(0.1)
                    await callback.message.answer(full_text, reply_markup=markup)
                except Exception as answer_error:
                    print(f"Не удалось отправить сообщение: {answer_error}")
                        
        elif message:
            try:
                await message.answer(full_text, reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки сообщения: {e}")
        elif chat_id is not None:
            try:
                await bot.send_message(chat_id=chat_id, text=full_text, reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки в чат {chat_id}: {e}")
        else:
            try:
                await bot.send_message(chat_id=user.id, text=full_text, reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки в ЛС: {e}")
                
    except Exception as e:
        print(f"Общая ошибка в greet_and_send: {e}")

async def safe_send_message(chat_id: int, text: str, reply_markup=None, delay: float = 0.1):
    """Безопасная отправка сообщения с задержкой"""
    try:
        await asyncio.sleep(delay)  # Задержка между сообщениями
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return True
    except Exception as e:
        print(f"Ошибка отправки в чат {chat_id}: {e}")
        return False

async def get_rasp_formatted(day, week_type, chat_id: int = None, target_date: datetime.date = None):
    """Получаем расписание с учетом статичного и модификаций"""
    if chat_id is None:
        chat_id = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else DEFAULT_CHAT_ID
    
    msg_lines = []
    
    # Получаем статичное расписание как основу
    static_rasp = await get_static_rasp(pool, day, week_type)
    static_pairs = {row[0]: (row[1], row[2], row[3]) for row in static_rasp}
    
    # Получаем модификации (перезаписывают статичное)
    modifications = await get_rasp_modifications(pool, chat_id, day, week_type)
    modified_pairs = {row[0]: (row[1], row[2]) for row in modifications}
    
    # Определяем максимальную пару (обрезаем свободные в конце)
    max_pair = 0
    all_pairs = set(static_pairs.keys()) | set(modified_pairs.keys())
    if all_pairs:
        max_pair = max(all_pairs)
    
    # Если нет пар вообще, показываем сообщение
    if max_pair == 0:
        result = "Расписание пустое."
    else:
        has_modifications = False
        
        for i in range(1, max_pair + 1):
            line = ""
            
            if i in modified_pairs:
                # Используем модифицированную пару
                subject_id, cabinet = modified_pairs[i]
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
                        subject_row = await cur.fetchone()
                        subject_name = subject_row[0] if subject_row else "Свободно"
                
                if subject_name == "Свободно":
                    line = f"{i}. Свободно 🔄"
                else:
                    import re
                    clean_subject_name = re.sub(r'\s+(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', '', subject_name).strip()
                    
                    if cabinet and cabinet != "Не указан":
                        line = f"{i}. {cabinet} {clean_subject_name} 🔄"
                    else:
                        cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
                        if cabinet_match:
                            extracted_cabinet = cabinet_match.group(2)
                            line = f"{i}. {extracted_cabinet} {clean_subject_name} 🔄"
                        else:
                            line = f"{i}. {clean_subject_name} 🔄"
                has_modifications = True
                
            elif i in static_pairs:
                # Используем статичную пару
                subject_name, cabinet, subject_id = static_pairs[i]
                
                if subject_name == "Свободно":
                    line = f"{i}. Свободно"
                else:
                    import re
                    clean_subject_name = re.sub(r'\s+(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', '', subject_name).strip()
                    
                    if cabinet and cabinet != "Не указан":
                        line = f"{i}. {cabinet} {clean_subject_name}"
                    else:
                        cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
                        if cabinet_match:
                            extracted_cabinet = cabinet_match.group(2)
                            line = f"{i}. {extracted_cabinet} {clean_subject_name}"
                        else:
                            line = f"{i}. {clean_subject_name}"
            else:
                line = f"{i}. Свободно"
            
            msg_lines.append(line)
        
        result = "\n".join(msg_lines)
        
        # Добавляем информацию о домашних заданиях
        if target_date is None:
            target_date = datetime.datetime.now(TZ).date()
        
        target_date_str = target_date.strftime("%Y-%m-%d")
        has_hw = await has_homework_for_date(pool, target_date_str)
        
        if has_hw:
            result += "\n\n📚 Есть заданное домашнее задание"
        
        # Добавляем пометку о модификациях
        if has_modifications:
            result += "\n\n🔄 Отмечены измененные пары"
    
    return result

@dp.callback_query(F.data == "today_rasp")
async def today_rasp_handler(callback: types.CallbackQuery):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    chat_id = callback.message.chat.id
    now = datetime.datetime.now(TZ)
    today = now.date()
    current_weekday = today.isoweekday()
    
    # Определяем день для показа
    if current_weekday == 7:  # Воскресенье
        target_date = today + datetime.timedelta(days=1)
        day_to_show = 1
        day_name = "понедельник"
        display_text = "понедельник"
    else:
        target_date = today
        day_to_show = current_weekday
        day_name = "сегодня"
        # Получаем название дня недели для отображения
        day_names = {
            1: "понедельник",
            2: "вторник", 
            3: "среду",
            4: "четверг",
            5: "пятницу",
            6: "субботу"
        }
        display_text = f"{day_name} ({day_names[current_weekday]})"
    
    # Получаем актуальную четность недели
    week_type = await get_current_week_type(pool)
    
    # ВАЖНО: ЕСЛИ ПОКАЗЫВАЕМ ПОНЕДЕЛЬНИК И СЕЙЧАС ВОСКРЕСЕНЬЕ - МЕНЯЕМ ЧЕТНОСТЬ
    if day_to_show == 1 and current_weekday == 7:
        week_type = 2 if week_type == 1 else 1
    
    # Получаем расписание с информацией о домашних заданиях на target_date
    text = await get_rasp_formatted(day_to_show, week_type, chat_id, target_date)
    
    week_name = "нечетная" if week_type == 1 else "четная"
    
    # Формируем сообщение
    message = f"📅 Расписание на {display_text} | Неделя: {week_name}\n\n{text}"
    
    # Добавляем анекдот
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                message += f"\n\n😂 Анекдот:\n{row[0]}"
    
    # ДОБАВЛЯЕМ ПРОВЕРКУ ДНЕЙ РОЖДЕНИЯ
    birthday_footer = await format_birthday_footer(pool)
    if birthday_footer:
        message += birthday_footer
    
    # Отправляем сообщение с кнопкой "Назад"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await callback.message.edit_text(message, reply_markup=kb)
    await callback.answer()


async def initialize_static_rasp_from_current(pool, week_type: int):
    """Инициализирует статичное расписание из текущих данных БЕЗ ДУБЛИРОВАНИЯ"""
    try:
        print(f"🔄 Инициализация статичного расписания для недели {week_type}...")
        
        # Очищаем старое статичное расписание для этой недели
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM static_rasp WHERE week_type=%s", (week_type,))
        
        # Берем расписание только из ПЕРВОГО чата чтобы избежать дублирования
        main_chat_id = ALLOWED_CHAT_IDS[0]
        
        for day in range(1, 7):  # Пн-Сб
            # Получаем текущее расписание из rasp_detailed только из основного чата
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT pair_number, subject_id, cabinet 
                        FROM rasp_detailed 
                        WHERE chat_id=%s AND day=%s AND week_type=%s
                        ORDER BY pair_number
                    """, (main_chat_id, day, week_type))
                    current_rasp = await cur.fetchall()
            
            # Сохраняем в статичное расписание
            for pair_number, subject_id, cabinet in current_rasp:
                if subject_id:  # Если есть предмет (не свободно)
                    await save_static_rasp(pool, day, week_type, pair_number, subject_id, cabinet or "Не указан")
        
        print(f"✅ Статичное расписание для недели {week_type} инициализировано из чата {main_chat_id}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка инициализации статичного расписания: {e}")
        return False

@dp.callback_query(F.data == "tomorrow_rasp")
async def tomorrow_rasp_handler(callback: types.CallbackQuery):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    chat_id = callback.message.chat.id
    now = datetime.datetime.now(TZ)
    today = now.date()
    current_weekday = today.isoweekday()
    
    # Определяем день для показа (завтра)
    target_date = today + datetime.timedelta(days=1)
    day_to_show = target_date.isoweekday()
    
    # Если завтра воскресенье, показываем понедельник
    if day_to_show == 7:
        target_date += datetime.timedelta(days=1)
        day_to_show = 1
        display_text = "послезавтра (понедельник)"
    else:
        # Получаем название дня недели для отображения
        day_names = {
            1: "понедельник",
            2: "вторник", 
            3: "среду",
            4: "четверг",
            5: "пятницу",
            6: "субботу"
        }
        display_text = f"завтра ({day_names[day_to_show]})"
    
    # Получаем актуальную четность недели
    week_type = await get_current_week_type(pool)
    
    # ВАЖНО: ЕСЛИ ПОКАЗЫВАЕМ ПОНЕДЕЛЬНИК И СЕЙЧАС ВОСКРЕСЕНЬЕ ИЛИ СУББОТА - МЕНЯЕМ ЧЕТНОСТЬ
    if day_to_show == 1 and (current_weekday == 7 or current_weekday == 6):
        week_type = 2 if week_type == 1 else 1
    
    # Получаем расписание с информацией о домашних заданиях на target_date
    text = await get_rasp_formatted(day_to_show, week_type, chat_id, target_date)
    
    week_name = "нечетная" if week_type == 1 else "четная"
    
    # Формируем сообщение
    message = f"📅 Расписание на {display_text} | Неделя: {week_name}\n\n{text}"
    
    # Добавляем анекдот
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                message += f"\n\n😂 Анекдот:\n{row[0]}"
    
    # ДОБАВЛЯЕМ ПРОВЕРКУ ДНЕЙ РОЖДЕНИЯ
    birthday_footer = await format_birthday_footer(pool)
    if birthday_footer:
        message += birthday_footer
    
    # Отправляем сообщение с кнопкой "Назад"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await callback.message.edit_text(message, reply_markup=kb)
    await callback.answer()

async def send_today_rasp():
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            now = datetime.datetime.now(TZ)
            today = now.date()
            current_weekday = today.isoweekday()
            hour = now.hour
            
            # Определяем день для публикации
            if hour >= 18:
                target_date = today + datetime.timedelta(days=1)
                day_to_post = target_date.isoweekday()
                
                if day_to_post == 7:  # Воскресенье
                    target_date += datetime.timedelta(days=1)
                    day_to_post = 1
                    day_name = "послезавтра (Понедельник)"
                else:
                    day_name = "завтра"
            else:
                target_date = today
                day_to_post = current_weekday
                
                if day_to_post == 7:  # Воскресенье
                    target_date += datetime.timedelta(days=1)
                    day_to_post = 1
                    day_name = "завтра (Понедельник)"
                else:
                    day_name = "сегодня"
            
            # ПОЛУЧАЕМ АКТУАЛЬНУЮ ЧЕТНОСТЬ
            week_type = await get_current_week_type(pool)
            
            # ВАЖНО: ЕСЛИ ПОКАЗЫВАЕМ ПОНЕДЕЛЬНИК И СЕЙЧАС ВОСКРЕСЕНЬЕ ИЛИ СУББОТА ПОСЛЕ 18:00 - МЕНЯЕМ ЧЕТНОСТЬ
            if day_to_post == 1:
                # Если сегодня воскресенье ИЛИ сегодня суббота после 18:00
                if current_weekday == 7 or (current_weekday == 6 and hour >= 18):
                    week_type = 2 if week_type == 1 else 1
                    print(f"🔁 Смена четности для понедельника: {'нечетная' if week_type == 1 else 'четная'}")
            
            # Получаем расписание
            text = await get_rasp_formatted(day_to_post, week_type, chat_id, target_date)
            
            # Формируем сообщение
            day_names = {
                1: "Понедельник", 2: "Вторник", 3: "Среда",
                4: "Четверг", 5: "Пятница", 6: "Суббота"
            }
            
            week_name = "нечетная" if week_type == 1 else "четная"
            
            if "(" in day_name and ")" in day_name:
                msg = f"📅 Расписание на {day_name} | Неделя: {week_name}\n\n{text}"
            else:
                msg = f"📅 Расписание на {day_name} ({day_names[day_to_post]}) | Неделя: {week_name}\n\n{text}"
            
            try:
                # Добавляем анекдот
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
                        row = await cur.fetchone()
                        if row:
                            msg += f"\n\n😂 Анекдот:\n{row[0]}"

                # Добавляем поздравления с ДР (если есть)
                birthday_footer = await format_birthday_footer(pool)
                if birthday_footer:
                    msg += birthday_footer

                await bot.send_message(chat_id, msg)

            except Exception as e:
                print(f"Ошибка отправки расписания в чат {chat_id}: {e}")

        except Exception as e:
            print(f"❌ Ошибка в send_today_rasp для чата {chat_id}: {e}")




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

    # Проверяем менеджера фонда
    is_fund_manager = (message.from_user.id == FUND_MANAGER_USER_ID) and is_private

    await greet_and_send(
        message.from_user, 
        "Выберите действие:", 
        message=message, 
        markup=main_menu(
            is_admin=is_admin, 
            is_special_user=is_special_user, 
            is_group_chat=not is_private,
            is_fund_manager=is_fund_manager
        )
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


@dp.callback_query(F.data.startswith("rasp_day_"))
async def on_rasp_day(callback: types.CallbackQuery):
    if check_flood(callback.from_user.id):
        try:
            await callback.answer("⏳ Подождите немного...", show_alert=False)
        except:
            pass
        return

    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        try:
            await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        except:
            pass
        return

    parts = callback.data.split("_")
    try:
        day = int(parts[-1])
    except Exception:
        try:
            await callback.answer("Ошибка выбора дня", show_alert=True)
        except:
            pass
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data=f"rasp_show_{day}_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data=f"rasp_show_{day}_2")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_rasp")]
    ])
    
    # Используем безопасную функцию
    await safe_edit_message(
        callback, 
        f"📅 {DAYS[day-1]} — выберите неделю:", 
        markup=kb
    )
    
    try:
        await callback.answer()
    except:
        pass

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
    
    # Определяем дату для проверки домашних заданий
    # Для обычного расписания показываем домашние задания на ближайшую дату с этим днем недели
    today = datetime.datetime.now(TZ).date()
    days_ahead = day - today.isoweekday()
    if days_ahead <= 0:
        days_ahead += 7
    target_date = today + datetime.timedelta(days=days_ahead)
    
    # Получаем расписание с информацией о домашних заданиях
    chat_id = callback.message.chat.id
    text = await get_rasp_formatted(day, week_type, chat_id, target_date)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data=f"rasp_day_{day}")]
    ])
    
    day_names = {
        1: "Понедельник",
        2: "Вторник", 
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота"
    }
    
    week_name = "нечетная" if week_type == 1 else "четная"
    
    message = f"📅 {day_names[day]} | Неделя: {week_name}\n\n{text}"
    
    # ДОБАВЛЯЕМ ПРОВЕРКУ ДНЕЙ РОЖДЕНИЯ
    birthday_footer = await format_birthday_footer(pool)
    if birthday_footer:
        message += birthday_footer
    
    await callback.message.edit_text(message, reply_markup=kb)
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
    
    # Показываем общую четность
    current = await get_current_week_type(pool)
    current_str = "нечетная (1)" if current == 1 else "четная (2)"
    
    status_text = f"📊 Текущая четность недели (общая для всех чатов):\n\n{current_str}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_admin")]
    ])
    
    await callback.message.edit_text(status_text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "admin_sync_week")
async def admin_sync_week_handler(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    
    try:
        # Берем четность из первого группового чата как основную
        main_chat_id = ALLOWED_CHAT_IDS[0]
        main_week_type = await get_current_week_type(pool, main_chat_id)
        
        # Устанавливаем такую же четность для всех групповых чатов
        synced_chats = []
        for chat_id in ALLOWED_CHAT_IDS:
            await set_current_week_type(pool, chat_id, main_week_type)
            synced_chats.append(chat_id)
        
        # Также устанавливаем для ЛС чата админа
        admin_ls_chat_id = callback.message.chat.id
        await set_current_week_type(pool, admin_ls_chat_id, main_week_type)
        synced_chats.append(f"ЛС ({admin_ls_chat_id})")
        
        week_name = "нечетная" if main_week_type == 1 else "четная"
        
        await callback.message.edit_text(
            f"✅ Четность синхронизирована!\n\n"
            f"Все чаты установлены на: {week_name} неделя\n"
            f"Синхронизировано чатов: {len(synced_chats)}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка синхронизации: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
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
    
    try:
        # Получаем текущую неделю перед изменением
        current_week = await get_current_week_type(pool)
        
        # Устанавливаем новую четность
        await set_current_week_type(pool, week_type=week_type)
        
        # Если неделя изменилась, сбрасываем модификации для предыдущей недели
        if current_week != week_type:
            await reset_rasp_for_new_week()
        
        week_name = "нечетная" if week_type == 1 else "четная"
        
        await callback.message.edit_text(
            f"✅ Четность установлена: {week_name} неделя для всех чатов\n"
            f"🔄 Модификации расписания для предыдущей недели сброшены\n\n"
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

@dp.callback_query(F.data == "admin_save_static_rasp")
async def admin_save_static_rasp_start(callback: types.CallbackQuery, state: FSMContext):
    """Сохранение текущего расписания как статичного"""
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная неделя", callback_data="save_static_1")],
        [InlineKeyboardButton(text="2️⃣ Четная неделя", callback_data="save_static_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])
    
    await callback.message.edit_text(
        "💾 Сохранение статичного расписания\n\n"
        "Выберите для какой недели сохранить текущее расписание:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("save_static_"))
async def process_save_static_rasp(callback: types.CallbackQuery):
    week_type = int(callback.data.split("_")[2])
    
    try:
        # Используем новую функцию инициализации
        success = await initialize_static_rasp_from_current(pool, week_type)
        
        if success:
            week_name = "нечетную" if week_type == 1 else "четную"
            await callback.message.edit_text(
                f"✅ Текущее расписание сохранено как статичное для {week_name} недели!\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        else:
            await callback.message.edit_text(
                f"❌ Ошибка при сохранении статичного расписания\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при сохранении статичного расписания: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
    await callback.answer()

async def send_today_rasp():
    for chat_id in ALLOWED_CHAT_IDS:
        try:
            now = datetime.datetime.now(TZ)
            today = now.date()
            hour = now.hour
            
            # Определяем день для публикации
            if hour >= 18:
                target_date = today + datetime.timedelta(days=1)
                day_to_post = target_date.isoweekday()
                
                if day_to_post == 7:  # Воскресенье
                    target_date += datetime.timedelta(days=1)
                    day_to_post = 1
                    day_name = "послезавтра (Понедельник)"
                else:
                    day_name = "завтра"
            else:
                target_date = today
                day_to_post = today.isoweekday()
                
                if day_to_post == 7:  # Воскресенье
                    target_date += datetime.timedelta(days=1)
                    day_to_post = 1
                    day_name = "завтра (Понедельник)"
                else:
                    day_name = "сегодня"
            
            # Получаем базовую четность
            base_week_type = await get_current_week_type(pool)
            
            # ЕСЛИ ПОКАЗЫВАЕМ ПОНЕДЕЛЬНИК И СЕЙЧАС ВОСКРЕСЕНЬЕ - МЕНЯЕМ ЧЕТНОСТЬ
            if day_to_post == 1 and (today.isoweekday() == 7 or (hour >= 18 and (today + datetime.timedelta(days=1)).isoweekday() == 7)):
                week_type = 2 if base_week_type == 1 else 1
                week_name = "нечетная" if week_type == 1 else "четная"
                day_note = ""
            else:
                week_type = base_week_type
                week_name = "нечетная" if week_type == 1 else "четная"
                day_note = ""
            
            # Получаем расписание для конкретного чата
            text = await get_rasp_formatted(day_to_post, week_type, chat_id, target_date)
            
            # Формируем сообщение
            day_names = {
                1: "Понедельник", 2: "Вторник", 3: "Среда",
                4: "Четверг", 5: "Пятница", 6: "Суббота"
            }
            
            if "(" in day_name and ")" in day_name:
                msg = f"📅 Расписание на {day_name} | Неделя: {week_name}{day_note}\n\n{text}"
            else:
                msg = f"📅 Расписание на {day_name} ({day_names[day_to_post]}) | Неделя: {week_name}{day_note}\n\n{text}"
            
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


@dp.message(Command("listdr"))
async def cmd_list_birthdays(message: types.Message):
    """Показывает список всех дней рождения - только админы в ЛС"""
    if message.chat.type != "private" or message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ Эта команда доступна только администраторам в личных сообщениях")
        return

    birthdays = await get_all_birthdays(pool)
    
    if not birthdays:
        await message.answer("📅 В базе нет добавленных дней рождения.")
        return
    
    today = datetime.datetime.now(TZ).date()
    birthday_list = "📅 Все дни рождения в базе:\n\n"
    
    for bday in birthdays:
        bday_id, name, birth_date, added_by, created_at = bday
        
        birth_date_obj = birth_date if isinstance(birth_date, datetime.date) else datetime.datetime.strptime(str(birth_date), '%Y-%m-%d').date()
        
        # Вычисляем возраст
        age = today.year - birth_date_obj.year
        if today.month < birth_date_obj.month or (today.month == birth_date_obj.month and today.day < birth_date_obj.day):
            age -= 1
        
        # Форматируем дату
        birth_date_str = birth_date_obj.strftime("%d.%m.%Y")
        
        # Отмечаем, если день рождения сегодня
        today_str = today.strftime("%m-%d")
        bday_str = birth_date_obj.strftime("%m-%d")
        today_flag = " 🎉 СЕГОДНЯ!" if today_str == bday_str else ""
        
        birthday_list += f"🆔 ID: {bday_id}\n"
        birthday_list += f"👤 {name}{today_flag}\n"
        birthday_list += f"📅 {birth_date_str} (возраст: {age} лет)\n"
        birthday_list += "─" * 30 + "\n"
    
    birthday_list += f"\n💡 Для теста используйте: /testdr <ID>"
    
    await message.answer(birthday_list)

async def get_birthday_by_id(pool, birthday_id: int):
    """Получает день рождения по ID"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, user_name, birth_date, added_by_user_id, created_at
                FROM birthdays 
                WHERE id = %s
            """, (birthday_id,))
            return await cur.fetchone()





@dp.message(Command("deldr"))
async def cmd_delete_birthday(message: types.Message):
    """Удаление дня рождения - только админы в ЛС"""
    if message.chat.type != "private" or message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ Эта команда доступна только администраторам в личных сообщениях")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠ Использование: /deldr <id>\n\nИдентификатор можно посмотреть в /listdr")
        return
    
    try:
        birthday_id = int(parts[1])
        await delete_birthday(pool, birthday_id)
        await message.answer(f"✅ День рождения с ID {birthday_id} удален")
    except ValueError:
        await message.answer("❌ Неверный формат ID. Используйте цифры.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при удалении: {e}")



@dp.message(Command("jobs"))
async def cmd_show_jobs(message: types.Message):
    """Показывает активные задания планировщика"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    jobs = scheduler.get_jobs()
    if not jobs:
        await message.answer("📋 Нет активных заданий в планировщике")
        return
    
    text = "📋 Активные задания в планировщике:\n\n"
    for job in jobs:
        next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M:%S") if job.next_run_time else "Не запланировано"
        text += f"• **{job.id}**\n"
        text += f"  Следующий запуск: {next_run}\n"
        text += f"  Триггер: {job.trigger}\n\n"
    
    await message.answer(text)

async def main():
    global pool
    pool = await get_pool()
    await init_db(pool)
    await ensure_columns(pool)
    await ensure_birthday_columns(pool)
    
    # Загружаем спец-пользователей из базы данных
    await load_special_users(pool)
    
    # Инициализируем статичное расписание если его нет
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM static_rasp")
                count = (await cur.fetchone())[0]
                if count == 0:
                    print("🔄 Первоначальная инициализация статичного расписания...")
                    await initialize_static_rasp_from_current(pool, 1)
                    await initialize_static_rasp_from_current(pool, 2)
    except Exception as e:
        print(f"❌ Ошибка инициализации статичного расписания: {e}")
    # Пересоздаем задания публикации при старте
    await reschedule_publish_jobs(pool)
    
    # УДАЛЯЕМ все существующие задания check_birthdays чтобы избежать дублирования
    for job in scheduler.get_jobs():
        if job.id == 'check_birthdays' or 'birthday' in job.id:
            scheduler.remove_job(job.id)
    
    # ДОБАВЛЯЕМ проверку дней рождения в 9:00 с уникальным ID
    scheduler.add_job(
        check_birthdays, 
        CronTrigger(hour=7, minute=0, timezone=TZ), 
        id='daily_birthday_check'
    )
    
    scheduler.start()
    print("✅ Планировщик запущен")
    
    # Выводим информацию о заданиях для отладки
    jobs = scheduler.get_jobs()
    print(f"🎯 Активные задания в планировщике: {len(jobs)}")
    for job in jobs:
        print(f"  - {job.id}: следующее выполнение в {job.next_run_time}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())