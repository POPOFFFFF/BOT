from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram.exceptions import TelegramRetryAfter
from bot_init import dp, bot, pool  # Импортируем dp и bot

import asyncio
import datetime
import random
import re
import aiohttp
import io
from bs4 import BeautifulSoup
import time

from config import *
from database import *
from states import *
from keyboards import *

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=TZ)

# Глобальная переменная для пула БД (будет инициализирована в main)
pool = None

# ========== ОБЩИЕ ФУНКЦИИ ==========

async def safe_edit_message(callback: types.CallbackQuery, text: str, markup=None):
    """Безопасное редактирование сообщения с обработкой RetryAfter"""
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramRetryAfter as e:
        wait_time = e.retry_after
        print(f"⏳ Telegram просит подождать {wait_time} секунд")
        await asyncio.sleep(wait_time)
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception as retry_error:
            print(f"Ошибка при повторной попытке: {retry_error}")
    except Exception as e:
        print(f"Ошибка редактирования: {e}")
        try:
            await callback.message.answer(text, reply_markup=markup)
        except Exception as answer_error:
            print(f"Ошибка отправки нового сообщения: {answer_error}")

async def safe_send_message(chat_id: int, text: str, reply_markup=None, delay: float = 0.1):
    """Безопасная отправка сообщения с задержкой"""
    try:
        await asyncio.sleep(delay)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return True
    except Exception as e:
        return False

async def greet_and_send(user: types.User, text: str, message: types.Message = None, 
                        callback: types.CallbackQuery = None, markup=None, 
                        chat_id: int | None = None, include_joke: bool = False, 
                        include_week_info: bool = False):
    await asyncio.sleep(0.1)
    
    try:
        if include_joke:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
                    row = await cur.fetchone()
                    if row:
                        text += f"\n\n😂 Анекдот:\n{row[0]}"
        
        week_info = ""
        if include_week_info:
            try:
                current_week = await get_current_week_type(pool)
                week_name = "Нечетная" if current_week == 1 else "Четная"
                week_info = f"\n\n📅 Сейчас неделя: {week_name}"
            except Exception as e:
                week_info = f"\n\n📅 Информация о неделе временно недоступна"
        
        nickname = await get_nickname(pool, user.id)
        greet = f"👋 Салам, {nickname}!\n\n" if nickname else "👋 Салам!\n\n"
        full_text = greet + text + week_info
        
        if len(full_text) > 4000:
            full_text = full_text[:3990] + "\n\n... (сообщение обрезано)"
        
        if callback:
            try:
                await callback.message.edit_text(full_text, reply_markup=markup)
            except Exception as edit_error:
                try:
                    await asyncio.sleep(0.1)
                    await callback.message.answer(full_text, reply_markup=markup)
                except Exception as answer_error:
                    print(f"Ошибка отправки сообщения: {answer_error}")
        elif message:
            try:
                await message.answer(full_text, reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки сообщения: {e}")
        elif chat_id is not None:
            try:
                await bot.send_message(chat_id=chat_id, text=full_text, reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки сообщения: {e}")
        else:
            try:
                await bot.send_message(chat_id=user.id, text=full_text, reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки сообщения: {e}")
                
    except Exception as e:
        print(f"Общая ошибка в greet_and_send: {e}")

# ========== ОБРАБОТЧИКИ КОМАНД ==========

@dp.message(Command("аркадий", "акрадый", "акрадий", "аркаша", "котов", "arkadiy", "arkadiy@arcadiyis07_bot"))
async def trigger_handler(message: types.Message):
    is_private = message.chat.type == "private"
    is_allowed_chat = message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await message.answer("⛔ Бот не работает в этом чате")
        return
    
    is_admin = (message.from_user.id in ALLOWED_USERS) and is_private
    
    is_special_user = False
    if is_private:
        signature = await get_special_user_signature(pool, message.from_user.id)
        is_special_user = signature is not None

    is_fund_manager = (message.from_user.id == FUND_MANAGER_USER_ID) and is_private

    await greet_and_send(
        message.from_user, 
        "Выберите действие:", 
        message=message, 
        markup=await main_menu(
            is_admin=is_admin, 
            is_special_user=is_special_user, 
            is_group_chat=not is_private,
            is_fund_manager=is_fund_manager
        )
    )

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

@dp.message(Command("акик", "акick"))
async def cmd_admin_kick(message: types.Message):
    if not is_allowed_chat(message.chat.id):
        return

    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    try:
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await message.answer("❌ Бот должен быть администратором в чате")
            return
    except Exception:
        await message.answer("❌ Ошибка проверки прав бота")
        return
    
    if not message.reply_to_message:
        await message.answer("⚠ Использование: Ответьте на сообщение пользователя командой /акик")
        return
    
    try:
        user_id = message.reply_to_message.from_user.id
        user_to_kick = message.reply_to_message.from_user
        
        if user_id == message.from_user.id:
            await message.answer("❌ Нельзя кикнуть самого себя")
            return
        
        if user_id in ALLOWED_USERS:
            await message.answer("❌ Нельзя кикнуть другого администратора")
            return
        
        try:
            target_member = await bot.get_chat_member(message.chat.id, user_id)
            if target_member.status == "creator":
                await message.answer("❌ Не могу кикнуть создателя чата")
                return
        except Exception as e:
            print(f"Ошибка проверки прав цели: {e}")
        
        await bot.ban_chat_member(message.chat.id, user_id)
        await message.answer(f"🚫 Пользователь {user_to_kick.first_name} (@{user_to_kick.username or 'нет'}) был кикнут администратором")
        
        await asyncio.sleep(30)
        await bot.unban_chat_member(message.chat.id, user_id)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при кике: {e}")

@dp.message(Command("амут", "аmut"))
async def cmd_admin_mute(message: types.Message):
    if not is_allowed_chat(message.chat.id):
        return

    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    try:
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await message.answer("❌ Бот должен быть администратором в чате")
            return
    except Exception:
        await message.answer("❌ Ошибка проверки прав бота")
        return
    
    args = message.text.split()
    
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
    
    if not message.reply_to_message:
        await message.answer("⚠ Ответьте на сообщение пользователя, которого нужно замутить")
        return
    
    try:
        user_id = message.reply_to_message.from_user.id
        user_to_mute = message.reply_to_message.from_user
        
        if user_id == message.from_user.id:
            await message.answer("❌ Нельзя замутить самого себя")
            return
        
        if user_id in ALLOWED_USERS:
            await message.answer("❌ Нельзя замутить другого администратора")
            return
        
        try:
            target_member = await bot.get_chat_member(message.chat.id, user_id)
            if target_member.status == "creator":
                await message.answer("❌ Не могу замутить создателя чата")
                return
        except Exception as e:
            print(f"Ошибка проверки прав цели: {e}")
        
        number_str = args[1]
        unit = args[2].lower()
        
        try:
            number = int(number_str)
        except ValueError:
            await message.answer("❌ Неверное число. Пример: /амут 10 секунд")
            return
        
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
        
        if duration > 2592000:
            await message.answer("❌ Максимальное время мута - 30 дней")
            return
        
        if duration < 10:
            await message.answer("❌ Минимальное время мута - 10 секунд")
            return
        
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
        
        time_display = format_duration(duration)
        await message.answer(f"🔇 Пользователь {user_to_mute.first_name} (@{user_to_mute.username or 'нет'}) замьючен на {time_display} администратором")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при муте: {e}")

@dp.message(Command("аразмут", "аunmute"))
async def cmd_admin_unmute(message: types.Message):
    if not is_allowed_chat(message.chat.id):
        return
    
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    try:
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await message.answer("❌ Бот должен быть администратором в чате")
            return
    except Exception:
        await message.answer("❌ Ошибка проверки прав бота")
        return
    
    if not message.reply_to_message:
        await message.answer("⚠ Использование: Ответьте на сообщение пользователя командой /аразмут")
        return
    
    try:
        user_id = message.reply_to_message.from_user.id
        user_to_unmute = message.reply_to_message.from_user
        
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

    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return
    
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ Эта команда работает только в групповых чатах")
        return
    
    if not message.reply_to_message:
        await message.answer("⚠ Использование: Ответьте на спам-сообщение командой /аспам")
        return
    
    try:
        spam_user_id = message.reply_to_message.from_user.id
        spam_user = message.reply_to_message.from_user
        
        await message.delete()
        await message.reply_to_message.delete()
        
        await bot.ban_chat_member(message.chat.id, spam_user_id)
        
        await message.answer(f"🧹 Спам от {spam_user.first_name} (@{spam_user.username or 'нет'}) удален, пользователь кикнут")
        
        await asyncio.sleep(60)
        await bot.unban_chat_member(message.chat.id, spam_user_id)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при очистке спама: {e}")

@dp.message(Command("adddr"))
async def cmd_add_birthday(message: types.Message):
    if message.chat.type != "private" or message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ Эта команда доступна только администраторам в личных сообщениях")
        return

    parts = message.text.split()
    
    if len(parts) < 3:
        await message.answer(
            "⚠ Использование: /adddr Имя ДД.ММ.ГГГГ\n\n"
            "Пример:\n"
            "/adddr Егор 15.05.1990\n"
            "/adddr Иван_Иванов 20.12.1985"
        )
        return

    date_str = parts[-1]
    name_parts = parts[1:-1]
    name = ' '.join(name_parts)
    
    if not name:
        await message.answer("❌ Имя не может быть пустым.")
        return

    try:
        birth_date = datetime.datetime.strptime(date_str, '%d.%m.%Y').date()
        
        today = datetime.datetime.now(TZ).date()
        if birth_date > today:
            await message.answer("❌ Дата рождения не может быть в будущем.")
            return
        
        await add_birthday(pool, name, date_str, message.from_user.id)
        
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

@dp.message(Command("экспорт", "export", "бэкап", "backup"))
async def cmd_export_database(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return

    try:
        timestamp = datetime.datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.sql"
        
        tables = [
            'rasp', 'birthdays', 'nicknames', 'static_rasp', 'rasp_modifications',
            'publish_times', 'anekdoty', 'subjects', 'special_users', 'rasp_detailed',
            'current_week_type', 'teacher_messages', 'group_fund_balance',
            'group_fund_members', 'group_fund_purchases', 'homework'
        ]
        
        sql_content = f"-- Backup created at {datetime.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}\n"
        sql_content += f"-- Database: {DB_NAME}\n\n"
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for table in tables:
                    await cur.execute("SHOW TABLES LIKE %s", (table,))
                    if not await cur.fetchone():
                        sql_content += f"-- Table {table} does not exist\n\n"
                        continue
                    
                    sql_content += f"-- Table: {table}\n"
                    
                    await cur.execute(f"SHOW CREATE TABLE {table}")
                    create_table = await cur.fetchone()
                    if create_table:
                        sql_content += f"{create_table[1]};\n\n"
                    
                    await cur.execute(f"SELECT * FROM {table}")
                    rows = await cur.fetchall()
                    
                    if rows:
                        await cur.execute(f"DESCRIBE {table}")
                        columns = [col[0] for col in await cur.fetchall()]
                        
                        sql_content += f"-- Data for table {table} ({len(rows)} rows)\n"
                        
                        for row in rows:
                            values = []
                            for value in row:
                                if value is None:
                                    values.append("NULL")
                                elif isinstance(value, (int, float)):
                                    values.append(str(value))
                                elif isinstance(value, datetime.datetime):
                                    values.append(f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'")
                                elif isinstance(value, datetime.date):
                                    values.append(f"'{value.strftime('%Y-%m-%d')}'")
                                else:
                                    escaped_value = str(value).replace("'", "''").replace("\\", "\\\\")
                                    values.append(f"'{escaped_value}'")
                            
                            insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(values)});"
                            sql_content += insert_sql + "\n"
                        
                        sql_content += "\n"
                    else:
                        sql_content += f"-- No data in table {table}\n\n"
        
        sql_file = io.BytesIO(sql_content.encode('utf-8'))
        sql_file.name = filename
        
        await message.answer_document(
            document=types.BufferedInputFile(
                sql_file.getvalue(),
                filename=filename
            ),
            caption=f"📦 Бэкап базы данных\n🕐 {datetime.datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}\n📊 Таблиц: {len(tables)}"
        )
        
        sql_file.close()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании бэкапа: {e}")
        print(f"Backup error: {e}")

@dp.message(Command("sql", "запрос"))
async def cmd_execute_sql(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для использования этой команды")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⚠ Использование:\n"
            "/sql <SQL запрос>\n\n"
            "Примеры:\n"
            "/sql INSERT INTO group_fund_balance (id, current_balance, updated_at) VALUES (23, '567.53', '2025-11-26 17:09:39')\n"
            "/sql UPDATE group_fund_balance SET current_balance = 1000 WHERE id = 1\n"
            "/sql SELECT * FROM group_fund_balance\n\n"
            "⚠ Внимание: Будьте осторожны с DELETE и DROP операциями!"
        )
        return

    sql_query = parts[1].strip()
    
    dangerous_keywords = ['DROP TABLE', 'DELETE FROM', 'TRUNCATE', 'ALTER TABLE']
    if any(keyword in sql_query.upper() for keyword in dangerous_keywords):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выполнить anyway", callback_data=f"confirm_dangerous_{hash(sql_query)}")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_sql")]
        ])
        await message.answer(
            f"⚠ Внимание! Запрос содержит потенциально опасную операцию:\n\n"
            f"`{sql_query}`\n\n"
            f"Вы уверены, что хотите выполнить этот запрос?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    await execute_sql_query(message, sql_query)

async def execute_sql_query(message: types.Message, sql_query: str):
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql_query)
                
                query_type = sql_query.strip().upper().split()[0]
                
                if query_type in ('SELECT', 'SHOW', 'DESCRIBE'):
                    rows = await cur.fetchall()
                    
                    if not rows:
                        await message.answer("✅ Запрос выполнен. Результатов нет.")
                        return
                    
                    column_names = [desc[0] for desc in cur.description]
                    
                    result_text = f"📊 Результат запроса ({len(rows)} строк):\n\n"
                    
                    max_rows = 20
                    if len(rows) > max_rows:
                        result_text += f"⚠ Показано первых {max_rows} из {len(rows)} строк:\n\n"
                        rows = rows[:max_rows]
                    
                    result_text += " | ".join(column_names) + "\n"
                    result_text += "─" * (len(" | ".join(column_names)) + 10) + "\n"
                    
                    for row in rows:
                        row_str = " | ".join(str(value) if value is not None else "NULL" for value in row)
                        result_text += row_str + "\n"
                    
                    if len(result_text) > 4000:
                        file_content = f"SQL Query: {sql_query}\n\n{result_text}"
                        file_io = io.BytesIO(file_content.encode('utf-8'))
                        file_io.name = f"sql_result_{datetime.datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.txt"
                        
                        await message.answer_document(
                            document=types.BufferedInputFile(
                                file_io.getvalue(),
                                filename=file_io.name
                            ),
                            caption=f"📋 Результат SQL запроса\n🕐 {datetime.datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}"
                        )
                        file_io.close()
                    else:
                        await message.answer(f"```\n{result_text}\n```", parse_mode="Markdown")
                        
                else:
                    affected_rows = cur.rowcount
                    await message.answer(f"✅ Запрос выполнен успешно!\n\nЗатронуто строк: {affected_rows}")
                
                if query_type not in ('SELECT', 'SHOW', 'DESCRIBE'):
                    await conn.commit()
                
    except Exception as e:
        error_msg = f"❌ Ошибка выполнения SQL запроса:\n\n`{e}`"
        await message.answer(error_msg, parse_mode="Markdown")
        print(f"SQL Error: {e}")

@dp.callback_query(F.data.startswith("confirm_dangerous_"))
async def confirm_dangerous_sql(callback: types.CallbackQuery):
    try:
        original_message = callback.message.text
        sql_query = original_message.split("`")[1]
        
        await callback.message.edit_text("🔄 Выполняю запрос...")
        await execute_sql_query(callback.message, sql_query)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {e}")
    
    await callback.answer()

@dp.callback_query(F.data == "cancel_sql")
async def cancel_sql(callback: types.CallbackQuery):
    await callback.message.edit_text("❌ Запрос отменен.")
    await callback.answer()

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
        await reschedule_publish_jobs()
        await message.answer(f"✅ Время публикации с id={pid} удалено и задачи пересозданы.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
# ========== ОБРАБОТЧИКИ КНОПОК ==========

@dp.callback_query(F.data == "menu_back")
async def menu_back_handler(callback: types.CallbackQuery, state: FSMContext):
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

    try:
        await state.clear()
    except Exception:
        pass
    
    is_admin = (callback.from_user.id in ALLOWED_USERS) and is_private
    
    is_special_user = False
    if is_private:
        signature = await get_special_user_signature(pool, callback.from_user.id)
        is_special_user = signature is not None

    is_fund_manager = (callback.from_user.id == FUND_MANAGER_USER_ID) and is_private

    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await safe_send_message(
        callback.message.chat.id,
        "Выберите действие:",
        reply_markup=await main_menu(
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

@dp.callback_query(F.data.startswith("menu_"))
async def menu_handler(callback: types.CallbackQuery, state: FSMContext):
    is_private = callback.message.chat.type == "private"
    is_allowed_chat = callback.message.chat.id in ALLOWED_CHAT_IDS
    
    if not (is_private or is_allowed_chat):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return
        
    action = callback.data
    
    if action == "menu_rasp":
        kb = rasp_days_keyboard()
        await greet_and_send(callback.from_user, "📅 Выберите день:", callback=callback, markup=kb)
        await callback.answer()
    
    elif action == "menu_zvonki":
        kb = zvonki_keyboard()
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
    
    elif action == "menu_homework":
        await menu_homework_handler(callback)
    
    elif action == "menu_birthdays":
        await menu_birthdays_handler(callback)
    
    elif action == "menu_group_fund":
        await menu_group_fund_handler(callback)

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
        
    kb = rasp_week_type_keyboard(day)
    await safe_edit_message(callback, f"📅 {DAYS[day-1]} — выберите неделю:", markup=kb)
    
    try:
        await callback.answer()
    except:
        pass

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
    
    today = datetime.datetime.now(TZ).date()
    days_ahead = day - today.isoweekday()
    if days_ahead <= 0:
        days_ahead += 7
    target_date = today + datetime.timedelta(days=days_ahead)
    
    chat_id = callback.message.chat.id
    text = await get_rasp_formatted(day, week_type, chat_id, target_date)
    
    kb = back_to_menu_keyboard()
    
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
    
    birthday_footer = await format_birthday_footer(pool)
    if birthday_footer:
        message += birthday_footer
    
    await callback.message.edit_text(message, reply_markup=kb)
    await callback.answer()

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
    
    if current_weekday == 7:
        target_date = today + datetime.timedelta(days=1)
        day_to_show = 1
        day_name = "понедельник"
        display_text = "понедельник"
    else:
        target_date = today
        day_to_show = current_weekday
        day_name = "сегодня"
        day_names = {
            1: "понедельник",
            2: "вторник", 
            3: "среду",
            4: "четверг",
            5: "пятницу",
            6: "субботу"
        }
        display_text = f"{day_name} ({day_names[current_weekday]})"
    
    week_type = await get_current_week_type(pool)
    
    if day_to_show == 1 and current_weekday == 7:
        week_type = 2 if week_type == 1 else 1
    
    text = await get_rasp_formatted(day_to_show, week_type, chat_id, target_date)
    
    week_name = "нечетная" if week_type == 1 else "четная"
    
    message = f"📅 Расписание на {display_text} | Неделя: {week_name}\n\n{text}"
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                message += f"\n\n😂 Анекдот:\n{row[0]}"
    
    birthday_footer = await format_birthday_footer(pool)
    if birthday_footer:
        message += birthday_footer
    
    kb = back_to_menu_keyboard()
    
    await callback.message.edit_text(message, reply_markup=kb)
    await callback.answer()

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
    
    target_date = today + datetime.timedelta(days=1)
    day_to_show = target_date.isoweekday()
    
    if day_to_show == 7:
        target_date += datetime.timedelta(days=1)
        day_to_show = 1
        display_text = "послезавтра (понедельник)"
    else:
        day_names = {
            1: "понедельник",
            2: "вторник", 
            3: "среду",
            4: "четверг",
            5: "пятницу",
            6: "субботу"
        }
        display_text = f"завтра ({day_names[day_to_show]})"
    
    week_type = await get_current_week_type(pool)
    
    if day_to_show == 1 and (current_weekday == 7 or current_weekday == 6):
        week_type = 2 if week_type == 1 else 1
    
    text = await get_rasp_formatted(day_to_show, week_type, chat_id, target_date)
    
    week_name = "нечетная" if week_type == 1 else "четная"
    
    message = f"📅 Расписание на {display_text} | Неделя: {week_name}\n\n{text}"
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT text FROM anekdoty ORDER BY RAND() LIMIT 1")
            row = await cur.fetchone()
            if row:
                message += f"\n\n😂 Анекдот:\n{row[0]}"
    
    birthday_footer = await format_birthday_footer(pool)
    if birthday_footer:
        message += birthday_footer
    
    kb = back_to_menu_keyboard()
    
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
    kb = back_to_menu_keyboard()

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

@dp.callback_query(F.data == "menu_homework")
async def menu_homework_handler(callback: types.CallbackQuery):
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    homework_list = await get_all_homework(pool)
    
    if not homework_list:
        kb = back_to_menu_keyboard()
        await callback.message.edit_text(
            "📚 Домашнее задание\n\n"
            "Пока нет заданных домашних заданий.",
            reply_markup=kb
        )
        return
    
    homework_text = "📚 Домашнее задание:\n\n"
    for hw_id, subject_name, due_date, task_text, created_at in homework_list:
        due_date_obj = due_date if isinstance(due_date, datetime.date) else datetime.datetime.strptime(str(due_date), '%Y-%m-%d').date()
        due_date_str = due_date_obj.strftime("%d.%m.%Y")
        
        homework_text += f"📅 {due_date_str} | {subject_name}\n"
        homework_text += f"📝 {task_text}\n"
        homework_text += "─" * 30 + "\n"
    
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
        
        kb = back_to_menu_keyboard()
        await callback.message.edit_text(parts[0], reply_markup=kb)
        
        for part in parts[1:]:
            await callback.message.answer(part)
    else:
        kb = back_to_menu_keyboard()
        await callback.message.edit_text(homework_text, reply_markup=kb)
    
    await callback.answer()

@dp.callback_query(F.data == "menu_birthdays")
async def menu_birthdays_handler(callback: types.CallbackQuery):
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    birthdays = await get_all_birthdays(pool)
    if not birthdays:
        kb = back_to_menu_keyboard()
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

    kb = back_to_menu_keyboard()
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "menu_group_fund")
async def menu_group_fund_handler(callback: types.CallbackQuery):
    if not is_allowed_chat(callback.message.chat.id):
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    balance = await get_fund_balance(pool)
    
    kb = group_fund_keyboard()
    
    await callback.message.edit_text(
        f"💰 Фонд Группы\n\n"
        f"💵 Текущий баланс: {balance:.2f} руб.\n\n"
        f"Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

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
    
    kb = back_to_menu_keyboard()
    
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
    
    kb = back_to_menu_keyboard()
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "menu_fund_management")
async def menu_fund_management_handler(callback: types.CallbackQuery):
    if callback.from_user.id != FUND_MANAGER_USER_ID:
        await callback.answer("⛔ У вас нет прав для управления фондом", show_alert=True)
        return

    kb = fund_management_keyboard()
    
    await callback.message.edit_text(
        "💰 Управление Фондом Группы\n\n"
        "Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

# ========== СООБЩЕНИЯ ПРЕПОДАВАТЕЛЕЙ ==========

@dp.callback_query(F.data == "view_teacher_messages")
async def view_teacher_messages_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.id not in ALLOWED_CHAT_IDS:
        await callback.answer("⛔ Бот не работает в этом чате", show_alert=True)
        return

    if callback.message.chat.type not in ["group", "supergroup"]:
        await callback.answer("⛔ Эта функция доступна только в беседе", show_alert=True)
        return

    await show_teacher_messages_page(callback, state, page=0)
    await callback.answer()

async def show_teacher_messages_page(callback: types.CallbackQuery, state: FSMContext, page: int = 0):
    limit = 10
    offset = page * limit
    
    messages = await get_teacher_messages(pool, offset, limit)
    total_count = await get_teacher_messages_count(pool)
    
    if not messages:
        kb = back_to_menu_keyboard()
        await callback.message.edit_text(
            "📝 Сообщения от преподавателей\n\n"
            "Пока нет сохраненных сообщений от преподавателей.",
            reply_markup=kb
        )
        return
    
    keyboard = []
    for i, (msg_id, message_id, signature, text, msg_type, created_at) in enumerate(messages):
        display_text = text[:50] + "..." if len(text) > 50 else text
        if not display_text:
            display_text = f"{msg_type} сообщение"
        
        emoji = "📝" if msg_type == "text" else "🖼️" if msg_type == "photo" else "📎" if msg_type == "document" else "🎵"
        button_text = f"{emoji} {signature}: {display_text}"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"view_message_{msg_id}"
        )])
    
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
        
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            date_str = str(created_at)
        
        message_link = f"https://t.me/c/{str(current_chat_id).replace('-100', '')}/{message_id}"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Перейти к сообщению", url=message_link)],
            [InlineKeyboardButton(text="⬅ Назад к списку", callback_data="back_to_messages_list")]
        ])
        
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

@dp.callback_query(F.data.startswith("messages_page_"))
async def messages_page_handler(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    await show_teacher_messages_page(callback, state, page)
    await callback.answer()

# ========== СПЕЦ-ПОЛЬЗОВАТЕЛИ ==========

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

    signature = await get_special_user_signature(pool, callback.from_user.id)
    if not signature:
        signature = "ПРОВЕРКА"

    await state.update_data(
        signature=signature,
        start_time=datetime.datetime.now(TZ)
    )
    
    await state.set_state(SendMessageState.active)
    
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
    
    asyncio.create_task(disable_forward_mode_after_timeout(callback.from_user.id, state))
    
    await callback.answer()

async def disable_forward_mode_after_timeout(user_id: int, state: FSMContext):
    await asyncio.sleep(180)
    current_state = await state.get_state()
    if current_state == SendMessageState.active.state:
        await state.clear()
        try:
            await bot.send_message(user_id, "⏰ Режим пересылки автоматически отключен (прошло 180 секунд).")
        except:
            pass

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
    if message.text and message.text.startswith('/'):
        await message.answer("❌ Сообщения, начинающиеся с /, не отправляются.")
        return
    
    data = await state.get_data()
    signature = data.get("signature", "ПРОВЕРКА")
    
    prefix = f"Сообщение от {signature}: "

    try:
        message_text = ""
        message_type = "text"
        sent_message_ids = []
        
        if message.text:
            message_text = message.text
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
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_audio(chat_id, message.audio.file_id, caption=prefix + (message.caption or ""))
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки аудио в чат {chat_id}: {e}")
                    
        elif message.voice:
            message_text = "голосовое сообщение"
            message_type = "voice"
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_voice(chat_id, message.voice.file_id, caption=prefix)
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки голосового сообщения в чат {chat_id}: {e}")
                    
        elif message.sticker:
            message_text = "стикер"
            message_type = "sticker"
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    sent_message = await bot.send_sticker(chat_id, message.sticker.file_id)
                    sent_message_ids.append(sent_message.message_id)
                except Exception as e:
                    print(f"Ошибка отправки стикера в чат {chat_id}: {e}")
                    
        else:
            await message.answer("⚠ Не удалось распознать тип сообщения.")
            return

        if sent_message_ids:
            await save_teacher_message(
                pool, 
                sent_message_ids[0],
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