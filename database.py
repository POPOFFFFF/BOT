import aiomysql
import datetime
import decimal
import re
import io
from typing import List, Tuple, Dict, Optional
from collections import defaultdict
import time
from config import *

# Глобальные переменные для управления флудом
user_last_action = defaultdict(float)
FLOOD_DELAY = 1.0

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

async def ensure_columns(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM week_setting LIKE 'set_at'")
            row = await cur.fetchone()
            if not row:
                await cur.execute("ALTER TABLE week_setting ADD COLUMN set_at DATE")

async def ensure_birthday_columns(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM birthdays LIKE 'added_by_user_id'")
            row = await cur.fetchone()
            if not row:
                await cur.execute("ALTER TABLE birthdays ADD COLUMN added_by_user_id BIGINT")
                print("✅ Добавлена колонка added_by_user_id в таблицу birthdays")

async def save_static_rasp(pool, day: int, week_type: int, pair_number: int, subject_id: int, cabinet: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                DELETE FROM static_rasp 
                WHERE day=%s AND week_type=%s AND pair_number=%s
            """, (day, week_type, pair_number))
            
            await cur.execute("""
                INSERT INTO static_rasp (day, week_type, pair_number, subject_id, cabinet)
                VALUES (%s, %s, %s, %s, %s)
            """, (day, week_type, pair_number, subject_id, cabinet))

async def get_static_rasp(pool, day: int, week_type: int):
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

async def save_rasp_modification(pool, chat_id: int, day: int, week_type: int, pair_number: int, subject_id: int, cabinet: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                print(f"🔍 DEBUG save_rasp_modification: чат={chat_id}, день={day}, неделя={week_type}, пара={pair_number}, subject_id={subject_id}, кабинет={cabinet}")
                
                await cur.execute("""
                    DELETE FROM rasp_modifications 
                    WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
                """, (chat_id, day, week_type, pair_number))
                
                print(f"🔍 DEBUG: Удалено старых модификаций: {cur.rowcount}")
                
                await cur.execute("""
                    INSERT INTO rasp_modifications (chat_id, day, week_type, pair_number, subject_id, cabinet)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (chat_id, day, week_type, pair_number, subject_id, cabinet))
                
                print(f"✅ Модификация сохранена: чат={chat_id}, день={day}, неделя={week_type}, пара={pair_number}")
                return True
                
    except Exception as e:
        print(f"❌ Ошибка сохранения модификации: {e}")
        return False

async def get_rasp_modifications(pool, chat_id: int, day: int, week_type: int):
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT pair_number, subject_id, cabinet
                    FROM rasp_modifications 
                    WHERE chat_id=%s AND day=%s AND week_type=%s
                    ORDER BY pair_number
                """, (chat_id, day, week_type))
                results = await cur.fetchall()
                print(f"🔍 DEBUG: Найдено модификаций для чата {chat_id}, день {day}, неделя {week_type}: {len(results)}")
                return results
    except Exception as e:
        print(f"❌ Ошибка получения модификаций: {e}")
        return []

async def clear_rasp_modifications(pool, week_type: int) -> int:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            total_cleared = 0
            for chat_id in ALLOWED_CHAT_IDS:
                await cur.execute("DELETE FROM rasp_modifications WHERE chat_id=%s AND week_type=%s", (chat_id, week_type))
                total_cleared += cur.rowcount
            
            print(f"🧹 Очищено модификаций для недели {week_type}: {total_cleared} записей")
            return total_cleared

async def clear_day_modifications(pool, week_type: int, day: int) -> int:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            total_cleared = 0
            for chat_id in ALLOWED_CHAT_IDS:
                await cur.execute("""
                    DELETE FROM rasp_modifications 
                    WHERE chat_id=%s AND week_type=%s AND day=%s
                """, (chat_id, week_type, day))
                total_cleared += cur.rowcount
            
            return total_cleared

async def sync_rasp_to_all_chats(pool, source_chat_id: int):
    try:
        synced_count = 0
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for chat_id in ALLOWED_CHAT_IDS:
                    if chat_id == source_chat_id:
                        continue
                    
                    await cur.execute("DELETE FROM rasp_detailed WHERE chat_id=%s", (chat_id,))
                    
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
                balance = row[0]
                if isinstance(balance, decimal.Decimal):
                    return float(balance)
                return float(balance)
            else:
                await cur.execute("INSERT INTO group_fund_balance (current_balance) VALUES (0)")
                return 0.0

async def update_fund_balance(pool, amount: float):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            current_balance = await get_fund_balance(pool)
            new_balance = current_balance + amount
            await cur.execute("INSERT INTO group_fund_balance (current_balance) VALUES (%s)", (new_balance,))

async def add_fund_member(pool, full_name: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO group_fund_members (full_name) VALUES (%s)", (full_name,))

async def get_all_fund_members(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, full_name, balance FROM group_fund_members ORDER BY full_name")
            rows = await cur.fetchall()
            result = []
            for row in rows:
                member_id, full_name, balance = row
                if isinstance(balance, decimal.Decimal):
                    balance = float(balance)
                elif hasattr(balance, '__float__'):
                    balance = float(balance)
                else:
                    balance = float(str(balance))
                result.append((member_id, full_name, balance))
            return result

async def delete_fund_member(pool, member_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_fund_members WHERE id = %s", (member_id,))

async def update_member_balance(pool, member_id: int, amount: float):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            amount_decimal = decimal.Decimal(str(amount))
            await cur.execute("UPDATE group_fund_members SET balance = balance + %s WHERE id = %s", (amount_decimal, member_id))

async def add_purchase(pool, item_name: str, item_url: str, price: float):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_fund_purchases (item_name, item_url, price) VALUES (%s, %s, %s)",
                (item_name, item_url, price)
            )
            await update_fund_balance(pool, -price)

async def get_all_purchases(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, item_name, item_url, price FROM group_fund_purchases WHERE is_active = TRUE ORDER BY created_at DESC")
            return await cur.fetchall()

async def delete_purchase(pool, purchase_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT price FROM group_fund_purchases WHERE id = %s", (purchase_id,))
            row = await cur.fetchone()
            if row:
                price = float(row[0])
                await update_fund_balance(pool, price)
                await cur.execute("UPDATE group_fund_purchases SET is_active = FALSE WHERE id = %s", (purchase_id,))

async def add_homework(pool, subject_id: int, due_date: str, task_text: str):
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
    current_hw = await get_homework_by_id(pool, homework_id)
    if not current_hw:
        raise ValueError("Задание не найдено")
    
    if subject_id is None:
        subject_id = current_hw[5]
    
    if due_date is None:
        due_date = current_hw[2]
        if isinstance(due_date, datetime.date):
            due_date = due_date.strftime('%Y-%m-%d')
    
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
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM homework WHERE id=%s", (homework_id,))

async def has_homework_for_date(pool, date: str) -> bool:
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
            return await cur.fetchall()

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
    global SPECIAL_USER_ID
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT user_id FROM special_users")
            rows = await cur.fetchall()
            SPECIAL_USER_ID = [row[0] for row in rows]
    print(f"Загружено {len(SPECIAL_USER_ID)} спец-пользователей: {SPECIAL_USER_ID}")

async def get_current_week_type(pool, chat_id: int = None) -> int:
    COMMON_CHAT_ID = 0
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT week_type, updated_at FROM current_week_type WHERE chat_id=%s", (COMMON_CHAT_ID,))
            row = await cur.fetchone()
            
            now = datetime.datetime.now(TZ)
            today = now.date()
            current_weekday = today.isoweekday()
            
            if row:
                week_type, last_updated = row
                
                if isinstance(last_updated, datetime.datetime):
                    last_updated_date = last_updated.date()
                else:
                    last_updated_date = last_updated
                
                if current_weekday == 1:
                    this_monday = today
                    
                    if last_updated_date < this_monday:
                        previous_week = week_type
                        week_type = 2 if week_type == 1 else 1
                        
                        await cur.execute("""
                            UPDATE current_week_type 
                            SET week_type=%s, updated_at=%s 
                            WHERE chat_id=%s
                        """, (week_type, today, COMMON_CHAT_ID))
                        
                        await clear_rasp_modifications(pool, previous_week)
                        print(f"✅ Автоматически переключена неделя на: {'нечетная' if week_type == 1 else 'четная'}")
                        print(f"✅ Сброшены модификации для предыдущей недели {previous_week}")
                
                return week_type
            else:
                week_type = 1
                await cur.execute("INSERT INTO current_week_type (chat_id, week_type, updated_at) VALUES (%s, %s, %s)", 
                                 (COMMON_CHAT_ID, week_type, today))
                return week_type

async def set_current_week_type(pool, chat_id: int = None, week_type: int = None):
    COMMON_CHAT_ID = 0
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO current_week_type (chat_id, week_type) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE week_type=%s, updated_at=CURRENT_TIMESTAMP
            """, (COMMON_CHAT_ID, week_type, week_type))

async def save_teacher_message(pool, message_id: int, from_user_id: int, 
                              signature: str, message_text: str, message_type: str):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO teacher_messages (message_id, from_user_id, signature, message_text, message_type)
                VALUES (%s, %s, %s, %s, %s)
            """, (message_id, from_user_id, signature, message_text, message_type))

async def get_teacher_messages(pool, offset: int = 0, limit: int = 10) -> List[Tuple]:
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
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM teacher_messages")
            result = await cur.fetchone()
            return result[0] if result else 0

async def add_birthday(pool, user_name: str, birth_date: str, added_by_user_id: int):
    try:
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
    today = datetime.datetime.now(TZ).date()
    today_str = today.strftime('%m-%d')
    
    print(f"🔍 Проверяем дни рождения на дату: {today_str}")
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
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
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, user_name, birth_date, added_by_user_id, created_at
                FROM birthdays 
                ORDER BY DATE_FORMAT(birth_date, '%m-%d')
            """)
            return await cur.fetchall()

async def format_birthday_footer(pool):
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
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM birthdays WHERE id=%s", (birthday_id,))

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
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM teacher_messages WHERE id = %s", (message_id,))
            await conn.commit()
            return cur.rowcount > 0

async def reset_week_schedule(pool, week_type: int) -> dict:
    deleted_counts = {
        'modifications': 0,
        'static_rasp': 0,
        'rasp_detailed': 0
    }
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for chat_id in ALLOWED_CHAT_IDS:
                    await cur.execute("DELETE FROM rasp_modifications WHERE chat_id=%s AND week_type=%s", 
                                    (chat_id, week_type))
                    deleted_counts['modifications'] += cur.rowcount
                
                await cur.execute("DELETE FROM static_rasp WHERE week_type=%s", (week_type,))
                deleted_counts['static_rasp'] = cur.rowcount
                
                for chat_id in ALLOWED_CHAT_IDS:
                    await cur.execute("DELETE FROM rasp_detailed WHERE chat_id=%s AND week_type=%s", 
                                    (chat_id, week_type))
                    deleted_counts['rasp_detailed'] += cur.rowcount
                
                await conn.commit()
        
        week_name = "нечетной" if week_type == 1 else "четной"
        print(f"✅ Сброшено всё расписание для {week_name} недели: "
              f"{deleted_counts['modifications']} модификаций, "
              f"{deleted_counts['static_rasp']} статичных пар, "
              f"{deleted_counts['rasp_detailed']} детализированных пар")
        
        return deleted_counts
        
    except Exception as e:
        print(f"❌ Ошибка при сбросе расписания на неделю {week_type}: {e}")
        return deleted_counts

async def initialize_static_rasp_from_current(pool, week_type: int):
    print(f"🔧 Начинаю сохранение недели {week_type}")
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM static_rasp WHERE week_type=%s", (week_type,))
        
        if ALLOWED_CHAT_IDS:
            main_chat_id = ALLOWED_CHAT_IDS[0]
            
            for day in range(1, 7):
                print(f"🔍 Обработка дня {day} (неделя {week_type})...")
                
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            SELECT pair_number, subject_id, cabinet 
                            FROM rasp_detailed 
                            WHERE chat_id=%s AND day=%s AND week_type=%s
                            ORDER BY pair_number
                        """, (main_chat_id, day, week_type))
                        static_rasp = await cur.fetchall()
                
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            SELECT pair_number, subject_id, cabinet
                            FROM rasp_modifications 
                            WHERE chat_id=%s AND day=%s AND week_type=%s
                            ORDER BY pair_number
                        """, (main_chat_id, day, week_type))
                        modifications = await cur.fetchall()
                
                print(f"  Статических пар: {len(static_rasp)}")
                print(f"  Модификаций: {len(modifications)}")
                
                mod_dict = {pair_num: (subj_id, cabinet) for pair_num, subj_id, cabinet in modifications}
                
                for pair_num in range(1, 7):
                    if pair_num in mod_dict:
                        subject_id, cabinet = mod_dict[pair_num]
                        print(f"  Пара {pair_num}: используем модификацию (subject_id={subject_id})")
                    else:
                        found = False
                        for static_pair_num, static_subject_id, static_cabinet in static_rasp:
                            if static_pair_num == pair_num:
                                subject_id = static_subject_id
                                cabinet = static_cabinet
                                found = True
                                print(f"  Пара {pair_num}: используем статику (subject_id={subject_id})")
                                break
                        
                        if not found:
                            print(f"  Пара {pair_num}: не существует, пропускаем")
                            continue
                    
                    if subject_id:
                        await save_static_rasp(pool, day, week_type, pair_num, subject_id, cabinet or "Не указан")
                        print(f"  ✅ Сохранена пара {pair_num}: день={day}, subject_id={subject_id}")
                    else:
                        print(f"  Пара {pair_num}: очищена (subject_id=None), не сохраняем")
            
            print(f"✅ Статичное расписание для недели {week_type} инициализировано")
            return True
        else:
            print("❌ Нет разрешенных чатов для инициализации статичного расписания")
            return False
        
    except Exception as e:
        print(f"❌ Ошибка при инициализации статичного расписания: {e}")
        import traceback
        traceback.print_exc()
        return False

async def get_rasp_formatted(day, week_type, chat_id: int = None, target_date: datetime.date = None):
    if chat_id is None:
        chat_id = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else DEFAULT_CHAT_ID
    
    msg_lines = []
    
    static_rasp = await get_static_rasp(pool, day, week_type)
    static_pairs = {row[0]: (row[1], row[2], row[3]) for row in static_rasp}
    
    modifications = await get_rasp_modifications(pool, chat_id, day, week_type)
    modified_pairs = {row[0]: (row[1], row[2]) for row in modifications}

    max_pair = 0
    all_pairs = set(static_pairs.keys()) | set(modified_pairs.keys())
    if all_pairs:
        max_pair = max(all_pairs)
    
    if max_pair == 0:
        result = "Расписание пустое."
    else:
        has_modifications = False
        
        for i in range(1, max_pair + 1):
            line = ""
            
            if i in modified_pairs:
                subject_id, cabinet = modified_pairs[i]
                
                if subject_id is None or subject_id == 0:
                    line = f"{i}. Свободно 🔄"
                    has_modifications = True
                else:
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
        
        if target_date is None:
            target_date = datetime.datetime.now(TZ).date()
        
        target_date_str = target_date.strftime("%Y-%m-%d")
        has_hw = await has_homework_for_date(pool, target_date_str)
        
        if has_hw:
            result += "\n\n📚 Есть заданное домашнее задание"
        
        if has_modifications:
            result += "\n\n🔄 Отмечены измененные пары"
    
    return result

def check_flood(user_id: int) -> bool:
    """Проверяет флуд, возвращает True если нужно блокировать"""
    current_time = time.time()
    if current_time - user_last_action[user_id] < FLOOD_DELAY:
        return True
    user_last_action[user_id] = current_time
    return False

def is_allowed_chat(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS

def get_zvonki(is_saturday: bool):
    return "\n".join(ZVONKI_SATURDAY if is_saturday else ZVONKI_DEFAULT)

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

def format_rasp_message(day_num, week_type, text):
    day_name = DAYS[day_num - 1]
    week_name = "нечетная" if week_type == 1 else "четная"
    return f"📅 {day_name} | Неделя: {week_name}\n\n{text}"