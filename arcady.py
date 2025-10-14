import subprocess
import shutil
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json
import tempfile
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

# Функции для бэкапа на Google Drive
async def create_database_backup():
    """Создает бэкап базы данных MySQL через Python"""
    try:
        print("🔄 Создаем бэкап БД через Python...")
        
        timestamp = datetime.datetime.now(TZ).strftime('%Y%m%d_%H%M%S')
        backup_filename = f"backup_{timestamp}.sql"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = os.path.join(temp_dir, backup_filename)
            
            # Получаем все таблицы
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SHOW TABLES")
                    tables = [row[0] for row in await cur.fetchall()]
            
            print(f"📋 Найдено таблиц: {tables}")
            
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write("-- Backup created by Arcady Bot\n")
                f.write(f"-- Date: {datetime.datetime.now(TZ)}\n")
                f.write(f"-- Database: {DB_NAME}\n")
                f.write(f"-- Tables: {len(tables)}\n\n")
                
                # Добавляем SET команды для совместимости
                f.write("SET FOREIGN_KEY_CHECKS=0;\n")
                f.write("SET SQL_MODE='NO_AUTO_VALUE_ON_ZERO';\n")
                f.write("SET AUTOCOMMIT=0;\n")
                f.write("START TRANSACTION;\n\n")
                
                for table in tables:
                    f.write(f"--\n-- Table structure for table `{table}`\n--\n\n")
                    
                    # Получаем структуру таблицы
                    async with pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(f"SHOW CREATE TABLE `{table}`")
                            create_table = await cur.fetchone()
                            if create_table:
                                f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                                f.write(f"{create_table[1]};\n\n")
                            
                            # Получаем данные
                            await cur.execute(f"SELECT * FROM `{table}`")
                            rows = await cur.fetchall()
                            
                            if rows:
                                f.write(f"--\n-- Dumping data for table `{table}`\n--\n\n")
                                
                                # Получаем названия колонок
                                await cur.execute(f"DESCRIBE `{table}`")
                                columns = [col[0] for col in await cur.fetchall()]
                                
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
                                            # Экранируем специальные символы
                                            escaped_value = str(value).replace("'", "''").replace("\\", "\\\\")
                                            values.append(f"'{escaped_value}'")
                                    
                                    f.write(f"INSERT INTO `{table}` ({', '.join([f'`{col}`' for col in columns])}) VALUES ({', '.join(values)});\n")
                            
                            f.write("\n")
                
                # Закрываем транзакцию
                f.write("COMMIT;\n")
                f.write("SET FOREIGN_KEY_CHECKS=1;\n")
            
            if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
                file_size = os.path.getsize(backup_path)
                print(f"✅ Бэкап создан: {backup_path} ({file_size} bytes)")
                
                # Проверяем содержимое
                with open(backup_path, 'r') as f:
                    first_lines = f.readlines()[:5]
                print(f"📝 Начало файла: {''.join(first_lines)}")
                
                return backup_path
            else:
                print("❌ Файл бэкапа пустой или не создан")
                return None
                
    except Exception as e:
        print(f"❌ Ошибка при создании бэкапа: {e}")
        import traceback
        print(f"🔍 Детали: {traceback.format_exc()}")
        return None

async def upload_to_google_drive(file_path):
    """Загружает файл на Google Drive с делегированием прав"""
    try:
        print("🔄 Начинаем загрузку на Google Drive...")
        
        # Проверяем что файл существует
        if not os.path.exists(file_path):
            print(f"❌ Файл для загрузки не существует: {file_path}")
            return False
        
        file_size = os.path.getsize(file_path)
        print(f"📁 Файл для загрузки: {file_path} ({file_size} bytes)")
        
        # Получаем credentials из переменных окружения
        credentials_json = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")
        
        if not credentials_json:
            print("❌ GOOGLE_DRIVE_CREDENTIALS_JSON не настроен")
            return False
        
        print("✅ Credentials из переменных окружения получены")
        
        try:
            creds_data = json.loads(credentials_json)
            email = creds_data.get('client_email')
            print(f"📧 Сервисный аккаунт: {email}")
        except Exception as e:
            print(f"❌ Ошибка парсинга credentials: {e}")
            return False
        
        # Используем делегирование прав на твой личный аккаунт
        user_email = "joespeen131@gmail.com"  # Твой email
        SCOPES = ['https://www.googleapis.com/auth/drive']
        
        try:
            creds = service_account.Credentials.from_service_account_info(
                creds_data, 
                scopes=SCOPES,
                subject=user_email  # Делегируем права твоего аккаунта
            )
            print(f"✅ Делегирование прав для: {user_email}")
        except Exception as e:
            print(f"❌ Ошибка делегирования: {e}")
            return False
        
        # Создаем сервис
        try:
            service = build('drive', 'v3', credentials=creds)
            print("✅ Сервис Google Drive создан")
        except Exception as e:
            print(f"❌ Ошибка создания сервиса: {e}")
            return False
        
        # Загружаем файл в корневую папку (без указания папки)
        file_name = os.path.basename(file_path)
        file_metadata = {
            'name': file_name,
            'mimeType': 'application/sql'
        }
        
        # Можно использовать папку если указана, но лучше без нее для простоты
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        if folder_id:
            print(f"📁 Загружаем в папку: {folder_id}")
            file_metadata['parents'] = [folder_id]
        else:
            print("📁 Загружаем в корневую папку")
        
        print(f"📤 Загружаем файл: {file_name}")
        try:
            media = MediaFileUpload(file_path, resumable=True)
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
            
            file_id = file.get('id')
            file_url = file.get('webViewLink', 'N/A')
            
            print(f"✅ Файл успешно загружен!")
            print(f"📎 ID: {file_id}")
            print(f"🔗 Ссылка: {file_url}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка загрузки файла: {e}")
            return False
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        return False

async def backup_database_job():
    """Ежедневная задача бэкапа базы данных"""
    try:
        print("🔄 Запуск ежедневного бэкапа БД...")
        
        # Создаем бэкап
        backup_path = await create_database_backup()
        if not backup_path:
            print("❌ Не удалось создать бэкап БД")
            return
        
        # Загружаем на Google Drive
        success = await upload_to_google_drive(backup_path)
        if success:
            print("✅ Бэкап успешно создан и загружен на Google Drive")
            
            # Отправляем уведомление админам
            for admin_id in ALLOWED_USERS:
                try:
                    await bot.send_message(
                        admin_id, 
                        f"✅ Ежедневный бэкап БД выполнен успешно!\n"
                        f"📁 Файл: {os.path.basename(backup_path)}\n"
                        f"⏰ Время: {datetime.datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}"
                    )
                except Exception as e:
                    print(f"❌ Ошибка отправки уведомления админу {admin_id}: {e}")
        else:
            print("❌ Не удалось загрузить бэкап на Google Drive")
            
    except Exception as e:
        print(f"❌ Критическая ошибка в задаче бэкапа: {e}")

@dp.message(Command("backup"))
async def cmd_backup(message: types.Message):
    """Ручной запуск бэкапа базы данных"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🔄 Запуск ручного бэкапа базы данных...")
    
    # Создаем бэкап
    backup_path = await create_database_backup()
    if not backup_path:
        await message.answer("❌ Не удалось создать бэкап БД")
        return
    
    # Загружаем на Google Drive
    success = await upload_to_google_drive(backup_path)
    if success:
        await message.answer(
            f"✅ Бэкап успешно создан и загружен на Google Drive!\n"
            f"📁 Файл: {os.path.basename(backup_path)}"
        )
    else:
        await message.answer("❌ Не удалось загрузить бэкап на Google Drive")

@dp.message(Command("test_backup_simple"))
async def cmd_test_backup_simple(message: types.Message):
    """Простой тест бэкапа"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🧪 Тестируем упрощенный бэкап...")
    
    # Создаем бэкап
    backup_path = await create_database_backup()
    if not backup_path:
        await message.answer("❌ Не удалось создать бэкап БД")
        return
    
    await message.answer(f"✅ Бэкап создан: {os.path.basename(backup_path)}")
    
    # Пробуем загрузить
    success = await upload_to_google_drive(backup_path)
    if success:
        await message.answer("✅ Загрузка на Google Drive работает!")
    else:
        await message.answer("❌ Загрузка на Google Drive не работает")


async def copy_sql_to_existing_txt():
    """Копирует содержимое SQL бэкапа в существующий TXT файл на Google Drive"""
    try:
        print("🔄 Копируем SQL бэкап в существующий TXT файл...")
        
        # Шаг 1: Создаем SQL бэкап
        print("1. Создаем SQL бэкап...")
        sql_backup_path = await create_database_backup()
        if not sql_backup_path:
            print("❌ Не удалось создать SQL бэкап")
            return False
        print(f"✅ SQL бэкап создан: {sql_backup_path}")
        
        # Шаг 2: Проверяем ID файла
        print("2. Проверяем ID файла...")
        existing_txt_file_id = "1VEt3C726q37cJqoRzjAVjymO32R6lUmr"
        
        if existing_txt_file_id == "1VEt3C726q37cJqoRzjAVjymO32R6lUmr":
            print("❌ Не указан ID TXT файла (используется заглушка)")
            return False
        print(f"✅ ID файла: {existing_txt_file_id}")
        
        # Шаг 3: Получаем credentials
        print("3. Получаем credentials...")
        credentials_json = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")
        if not credentials_json:
            print("❌ GOOGLE_DRIVE_CREDENTIALS_JSON не настроен")
            return False
        
        print("✅ Credentials получены из переменных окружения")
        
        # Шаг 4: Парсим credentials
        print("4. Парсим credentials...")
        try:
            creds_data = json.loads(credentials_json)
            email = creds_data.get('client_email')
            print(f"✅ Сервисный аккаунт: {email}")
        except Exception as e:
            print(f"❌ Ошибка парсинга credentials: {e}")
            return False
        
        # Шаг 5: Делегирование прав
        print("5. Настраиваем делегирование прав...")
        user_email = "joespeen131@gmail.com"
        SCOPES = ['https://www.googleapis.com/auth/drive']
        
        try:
            creds = service_account.Credentials.from_service_account_info(
                creds_data, 
                scopes=SCOPES,
                subject=user_email
            )
            print(f"✅ Делегирование прав для: {user_email}")
        except Exception as e:
            print(f"❌ Ошибка делегирования: {e}")
            return False
        
        # Шаг 6: Создаем сервис
        print("6. Создаем сервис Google Drive...")
        try:
            service = build('drive', 'v3', credentials=creds)
            print("✅ Сервис Google Drive создан")
        except Exception as e:
            print(f"❌ Ошибка создания сервиса: {e}")
            return False
        
        # Шаг 7: Проверяем доступ к файлу
        print("7. Проверяем доступ к файлу...")
        try:
            file_info = service.files().get(
                fileId=existing_txt_file_id,
                fields='id, name, mimeType, permissions'
            ).execute()
            print(f"✅ Файл найден: {file_info.get('name')}")
            print(f"📄 Тип файла: {file_info.get('mimeType')}")
            
            # Проверяем права доступа
            permissions = file_info.get('permissions', [])
            print(f"🔐 Права доступа: {len(permissions)} записей")
            for perm in permissions:
                print(f"   - {perm.get('role')}: {perm.get('type')} ({perm.get('emailAddress', 'N/A')})")
                
        except Exception as e:
            print(f"❌ Ошибка доступа к файлу: {e}")
            return False
        
        # Шаг 8: Читаем содержимое SQL файла
        print("8. Читаем содержимое SQL файла...")
        try:
            with open(sql_backup_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            
            print(f"✅ Содержимое прочитано: {len(sql_content)} символов")
            print(f"📝 Первые 100 символов: {sql_content[:100]}...")
        except Exception as e:
            print(f"❌ Ошибка чтения SQL файла: {e}")
            return False
        
        # Шаг 9: Создаем новое содержимое
        print("9. Создаем новое содержимое для TXT файла...")
        new_content = f"""=== АВТОМАТИЧЕСКИЙ БЭКАП БАЗЫ ДАННЫХ ===
Дата обновления: {datetime.datetime.now(TZ)}
Файл обновлен ботом Arcady

{sql_content}
"""
        print(f"✅ Новое содержимое создано: {len(new_content)} символов")
        
        # Шаг 10: Создаем временный файл
        print("10. Создаем временный файл...")
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(new_content)
                temp_txt_path = f.name
            print(f"✅ Временный файл создан: {temp_txt_path}")
            
            # Проверяем размер временного файла
            file_size = os.path.getsize(temp_txt_path)
            print(f"📁 Размер временного файла: {file_size} bytes")
        except Exception as e:
            print(f"❌ Ошибка создания временного файла: {e}")
            return False
        
        # Шаг 11: Обновляем файл на Google Drive
        print("11. Обновляем файл на Google Drive...")
        try:
            media = MediaFileUpload(temp_txt_path, mimetype='text/plain')
            print("✅ Media объект создан")
            
            updated_file = service.files().update(
                fileId=existing_txt_file_id,
                media_body=media,
                fields='id, name, modifiedTime, size'
            ).execute()
            
            print(f"✅ Файл обновлен!")
            print(f"📎 ID: {updated_file.get('id')}")
            print(f"📄 Имя: {updated_file.get('name')}")
            print(f"🕐 Время изменения: {updated_file.get('modifiedTime')}")
            print(f"📏 Размер: {updated_file.get('size', 'N/A')} bytes")
            
        except Exception as e:
            print(f"❌ Ошибка при обновлении файла: {e}")
            # Детальная информация об ошибке
            import traceback
            print(f"🔍 Детали ошибки: {traceback.format_exc()}")
            return False
        
        # Шаг 12: Удаляем временные файлы
        print("12. Удаляем временные файлы...")
        try:
            if os.path.exists(sql_backup_path):
                os.unlink(sql_backup_path)
                print(f"✅ Удален SQL файл: {sql_backup_path}")
            
            if os.path.exists(temp_txt_path):
                os.unlink(temp_txt_path)
                print(f"✅ Удален временный TXT файл: {temp_txt_path}")
        except Exception as e:
            print(f"⚠ Ошибка удаления временных файлов: {e}")
        
        print("🎉 Все шаги выполнены успешно!")
        return True
        
    except Exception as e:
        print(f"❌ Критическая ошибка в copy_sql_to_existing_txt: {e}")
        import traceback
        print(f"🔍 Детали: {traceback.format_exc()}")
        return False

@dp.message(Command("check_drive_info"))
async def cmd_check_drive_info(message: types.Message):
    """Проверяем информацию о сервисном аккаунте и доступных email"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🔍 Проверяем информацию о Google Drive...")
    
    try:
        credentials_json = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")
        if not credentials_json:
            await message.answer("❌ GOOGLE_DRIVE_CREDENTIALS_JSON не настроен")
            return
        
        creds_data = json.loads(credentials_json)
        
        # Показываем информацию о сервисном аккаунте
        client_email = creds_data.get('client_email', 'Не найден')
        project_id = creds_data.get('project_id', 'Не найден')
        
        info_text = (
            f"🔐 **Информация о сервисном аккаунте:**\n"
            f"📧 Client Email: `{client_email}`\n"
            f"🏢 Project ID: `{project_id}`\n\n"
            f"💡 **Для делегирования прав нужно использовать email:**\n"
            f"`{client_email}`\n\n"
            f"📋 **Действия:**\n"
            f"1. Откройте файл на Google Drive\n"
            f"2. Нажмите 'Настройки доступа'\n"
            f"3. Добавьте email выше с правами 'Редактор'"
        )
        
        await message.answer(info_text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("fix_drive_access"))
async def cmd_fix_drive_access(message: types.Message):
    """Исправляем доступ к Google Drive с правильным email"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🔧 Исправляем доступ к Google Drive...")
    
    try:
        credentials_json = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")
        if not credentials_json:
            await message.answer("❌ GOOGLE_DRIVE_CREDENTIALS_JSON не настроен")
            return
        
        creds_data = json.loads(credentials_json)
        client_email = creds_data.get('client_email')
        
        if not client_email:
            await message.answer("❌ Не удалось получить client_email из credentials")
            return
        
        # Используем правильный email (client_email самого сервисного аккаунта)
        SCOPES = ['https://www.googleapis.com/auth/drive']
        
        creds = service_account.Credentials.from_service_account_info(
            creds_data, 
            scopes=SCOPES
        )
        
        service = build('drive', 'v3', credentials=creds)
        
        # Создаем временный файл для теста
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("Test content from Arcady Bot")
            temp_file_path = f.name
        
        try:
            # Пробуем создать тестовый файл
            file_metadata = {
                'name': f'test_file_{datetime.datetime.now(TZ).strftime("%Y%m%d_%H%M%S")}.txt',
                'mimeType': 'text/plain'
            }
            
            media = MediaFileUpload(temp_file_path, mimetype='text/plain')
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
            
            await message.answer(
                f"✅ Доступ работает!\n"
                f"📄 Создан тестовый файл: {file.get('name')}\n"
                f"🔗 Ссылка: {file.get('webViewLink')}\n\n"
                f"💡 **Используемый email:** `{client_email}`\n"
                f"Добавьте этот email с правами редактора к вашему TXT файлу"
            )
            
        finally:
            # Удаляем временный файл
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        import traceback
        error_details = traceback.format_exc()
        print(f"Детали ошибки: {error_details}")

# Исправленная основная функция для бэкапа
async def copy_sql_to_existing_txt_fixed():
    """Исправленная версия - копирует SQL бэкап в существующий TXT файл"""
    try:
        print("🔄 Копируем SQL бэкап в существующий TXT файл (исправленная версия)...")
        
        # 1. Создаем SQL бэкап
        print("1. Создаем SQL бэкап...")
        sql_backup_path = await create_database_backup()
        if not sql_backup_path:
            print("❌ Не удалось создать SQL бэкап")
            return False
        print(f"✅ SQL бэкап создан: {sql_backup_path}")
        
        # 2. ID файла (ЗАМЕНИТЕ НА РЕАЛЬНЫЙ ID ВАШЕГО ФАЙЛА!)
        existing_txt_file_id = "1VEt3C726q37cJqoRzjAVjymO32R6lUmr"  # ЗАМЕНИТЕ ЭТОТ ID!
        
        if existing_txt_file_id == "1VEt3C726q37cJqoRzjAVjymO32R6lUmr":
            print("❌ Не указан реальный ID TXT файла")
            return False
        
        # 3. Настраиваем доступ
        print("2. Настраиваем доступ к Google Drive...")
        credentials_json = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")
        if not credentials_json:
            print("❌ GOOGLE_DRIVE_CREDENTIALS_JSON не настроен")
            return False
        
        creds_data = json.loads(credentials_json)
        client_email = creds_data.get('client_email')
        SCOPES = ['https://www.googleapis.com/auth/drive']
        
        # Используем сервисный аккаунт напрямую (без делегирования)
        creds = service_account.Credentials.from_service_account_info(
            creds_data, 
            scopes=SCOPES
        )
        
        service = build('drive', 'v3', credentials=creds)
        print(f"✅ Сервис создан для: {client_email}")
        
        # 4. Проверяем доступ к файлу
        print("3. Проверяем доступ к файлу...")
        try:
            file_info = service.files().get(
                fileId=existing_txt_file_id,
                fields='id, name, mimeType, permissions'
            ).execute()
            print(f"✅ Файл найден: {file_info.get('name')}")
            
            # Проверяем права
            permissions = file_info.get('permissions', [])
            has_access = any(perm.get('emailAddress') == client_email for perm in permissions)
            if not has_access:
                print(f"⚠ Внимание: сервисный аккаунт {client_email} не имеет явного доступа к файлу")
            else:
                print(f"✅ Сервисный аккаунт имеет доступ к файлу")
                
        except Exception as e:
            print(f"❌ Ошибка доступа к файлу: {e}")
            return False
        
        # 5. Читаем SQL и создаем временный файл
        print("4. Читаем SQL и создаем временный файл...")
        try:
            with open(sql_backup_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            print(f"✅ SQL прочитан: {len(sql_content)} символов")
        except Exception as e:
            print(f"❌ Ошибка чтения SQL: {e}")
            return False
        
        new_content = f"""=== АВТОМАТИЧЕСКИЙ БЭКАП БАЗЫ ДАННЫХ ===
Дата обновления: {datetime.datetime.now(TZ)}
Файл обновлен ботом Arcady

{sql_content}
"""
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(new_content)
                temp_txt_path = f.name
            print(f"✅ Временный файл создан: {temp_txt_path}")
        except Exception as e:
            print(f"❌ Ошибка создания временного файла: {e}")
            return False
        
        # 6. Обновляем файл
        print("5. Обновляем файл на Google Drive...")
        try:
            media = MediaFileUpload(temp_txt_path, mimetype='text/plain', resumable=True)
            print("✅ Media объект создан")
            
            updated_file = service.files().update(
                fileId=existing_txt_file_id,
                media_body=media,
                fields='id, name, modifiedTime, size'
            ).execute()
            
            print(f"✅ Файл успешно обновлен!")
            print(f"📄 Имя: {updated_file.get('name')}")
            print(f"🕐 Время изменения: {updated_file.get('modifiedTime')}")
            print(f"📏 Размер: {updated_file.get('size', 'N/A')} bytes")
            
        except Exception as e:
            print(f"❌ Ошибка обновления файла: {e}")
            return False
        
        # 7. Чистим временные файлы
        print("6. Очищаем временные файлы...")
        try:
            if os.path.exists(sql_backup_path):
                os.unlink(sql_backup_path)
                print(f"✅ Удален SQL файл: {sql_backup_path}")
            
            if os.path.exists(temp_txt_path):
                os.unlink(temp_txt_path)
                print(f"✅ Удален временный TXT: {temp_txt_path}")
        except Exception as e:
            print(f"⚠ Ошибка очистки: {e}")
        
        print("🎉 Бэкап успешно завершен!")
        return True
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        print(f"🔍 Детали: {traceback.format_exc()}")
        return False

# Команда для получения ID файла (практичная)
@dp.message(Command("get_my_file_id"))
async def cmd_get_my_file_id(message: types.Message):
    """Помогает получить ID вашего файла и настроить доступ"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    # Получаем email сервисного аккаунта
    credentials_json = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")
    if credentials_json:
        try:
            creds_data = json.loads(credentials_json)
            client_email = creds_data.get('client_email', 'неизвестен')
        except:
            client_email = 'неизвестен'
    else:
        client_email = 'неизвестен (настройте GOOGLE_DRIVE_CREDENTIALS_JSON)'
    
    instructions = f""

@dp.message(Command("update_backup_fixed"))
async def cmd_update_backup_fixed(message: types.Message):
    """Обновляет TXT файл исправленной версией"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🔄 Обновляю TXT файл (исправленная версия)...")
    
    success = await copy_sql_to_existing_txt_fixed()
    
    if success:
        await message.answer("✅ TXT файл успешно обновлен!")
    else:
        await message.answer("❌ Не удалось обновить TXT файл")
@dp.message(Command("update_backup"))
async def cmd_update_backup(message: types.Message):
    """Обновляет существующий TXT файл новым бэкапом"""
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    await message.answer("🔄 Обновляю TXT файл новым бэкапом...")
    
    success = await copy_sql_to_existing_txt()
    
    if success:
        await message.answer("✅ TXT файл успешно обновлен новым бэкапом!")
    else:
        await message.answer("❌ Не удалось обновить TXT файл")

@dp.message(Command("get_file_id"))
async def cmd_get_file_id(message: types.Message):
    """Помогает получить ID файла"""
    response = """🔍 Как получить ID файла на Google Drive:

1. Открой файл в браузере
2. Посмотри на URL:
   https://drive.google.com/file/d/✅ЭТО_ID_ФАЙЛА✅/view
3. Скопируй часть между /d/ и /view

Пример:
URL: https://drive.google.com/file/d/1ABC123def456/view
ID: 1ABC123def456

После получения ID замени его в коде в переменной:
existing_txt_file_id = "ТВОЙ_ID_ЗДЕСЬ"
"""
    await message.answer(response)



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

# Остальной код продолжается...

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
            await cur.execute("""
                SELECT id, user_name, birth_date
                FROM birthdays 
                WHERE DATE_FORMAT(birth_date, '%m-%d') = %s
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
        print("🎂 Запуск проверки дней рождения...")
        birthdays = await get_today_birthdays(pool)
        
        if not birthdays:
            print("🎂 Сегодня нет дней рождения")
            return
        
        print(f"🎂 Найдено {len(birthdays)} дней рождений для поздравления")
        
        for birthday in birthdays:
            birthday_id, user_name, birth_date = birthday
            
            # Детальное логирование
            print(f"🎂 Обрабатываем: {user_name}, дата: {birth_date}")
            
            # Вычисляем возраст
            today = datetime.datetime.now(TZ).date()
            birth_date_obj = birth_date if isinstance(birth_date, datetime.date) else datetime.datetime.strptime(str(birth_date), '%Y-%m-%d').date()
            age = today.year - birth_date_obj.year
            
            # Если день рождения еще не наступил в этом году, корректируем возраст
            if today.month < birth_date_obj.month or (today.month == birth_date_obj.month and today.day < birth_date_obj.day):
                age -= 1
            
            print(f"🎂 {user_name} исполняется {age} лет")
            
            # Создаем текст поздравления
            message_text = (
                f"🎉 С ДНЕМ РОЖДЕНИЯ, {user_name.upper()}! 🎉\n\n"
                f"В этом году тебе исполнилось целых {age} лет!\n\n"
                f"От сердца и почек дарю тебе цветочек 💐"
            )
            
            # Отправляем поздравление во ВСЕ беседы из конфига
            success_count = 0
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    await bot.send_message(chat_id, message_text)
                    success_count += 1
                    print(f"✅ Отправлено поздравление для {user_name} в чат {chat_id}")
                except Exception as e:
                    print(f"❌ Ошибка отправки поздравления для {user_name} в чат {chat_id}: {e}")
            
            print(f"✅ Успешно отправлено {success_count} поздравлений для {user_name}")
                
    except Exception as e:
        print(f"❌ Критическая ошибка проверки дней рождения: {e}")


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
        buttons.append([InlineKeyboardButton(text="📚 Домашнее задание", callback_data="menu_homework")]),  # Новая кнопка
        buttons.append([InlineKeyboardButton(text="📅 Расписание", callback_data="menu_rasp")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание на сегодня", callback_data="today_rasp")]),
        buttons.append([InlineKeyboardButton(text="📅 Расписание на завтра", callback_data="tomorrow_rasp")]),
        buttons.append([InlineKeyboardButton(text="⏰ Звонки", callback_data="menu_zvonki")]),

    
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

        # Новые кнопки для домашних заданий
        [InlineKeyboardButton(text="📝 Добавить домашнее задание", callback_data="admin_add_homework")],
        [InlineKeyboardButton(text="✏️ Редактировать домашнее задание", callback_data="admin_edit_homework")],
        [InlineKeyboardButton(text="🗑️ Удалить домашнее задание", callback_data="admin_delete_homework")],

        [InlineKeyboardButton(text="👤 Добавить спец-пользователя", callback_data="admin_add_special_user")],
        [InlineKeyboardButton(text="🗑️ Удалить сообщение преподавателя", callback_data="admin_delete_teacher_message")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    return kb

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
    
    # Форматируем список домашних заданий
    homework_text = "📚 Домашнее задание:\n\n"
    for hw_id, subject_name, due_date, task_text, created_at in homework_list:
        # Форматируем дату
        due_date_obj = due_date if isinstance(due_date, datetime.date) else datetime.datetime.strptime(str(due_date), '%Y-%m-%d').date()
        due_date_str = due_date_obj.strftime("%d.%m.%Y")
        
        # Обрезаем длинный текст задания
        short_task = task_text[:100] + "..." if len(task_text) > 100 else task_text
        
        homework_text += f"📅 {due_date_str} | {subject_name}\n"
        homework_text += f"📝 {short_task}\n"
        homework_text += "─" * 30 + "\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    
    await callback.message.edit_text(homework_text, reply_markup=kb)
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
    
    try:
        # Проверяем, есть ли у предмета фиксированный кабинет (rK)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, rK FROM subjects WHERE name=%s", (subject_name,))
                result = await cur.fetchone()
                if not result:
                    await callback.message.edit_text("❌ Ошибка: предмет не найден в базе")
                    await state.clear()
                    return
                    
                subject_id, is_rk = result
        
        if is_rk:
            # Если предмет с rK - спрашиваем кабинет
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
            # Если предмет без rK - пытаемся извлечь кабинет из названия
            import re
            cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
            
            if cabinet_match:
                cabinet = cabinet_match.group(2)
                clean_subject_name = subject_name.replace(cabinet_match.group(0), '').strip()
            else:
                cabinet = "Не указан"
                clean_subject_name = subject_name
            
            await state.update_data(cabinet=cabinet)
            
            # Добавляем урок в расписание для ВСЕХ чатов
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Добавляем урок в расписание для ВСЕХ чатов
                    for chat_id in ALLOWED_CHAT_IDS:
                        await cur.execute("""
                            INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (chat_id, data["day"], data["week_type"], pair_number, subject_id, cabinet))
            
            display_name = clean_subject_name
            
            # Автоматическая синхронизация
            source_chat_id = ALLOWED_CHAT_IDS[0]
            await sync_rasp_to_all_chats(source_chat_id)
            
            await callback.message.edit_text(
                f"✅ Урок '{display_name}' добавлен во все чаты!\n"
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
    
    if cabinet.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    # Устанавливаем кабинет для ВСЕХ чатов
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for chat_id in ALLOWED_CHAT_IDS:
                await cur.execute("""
                    SELECT id FROM rasp_detailed
                    WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
                """, (chat_id, data["day"], data["week_type"], data["pair_number"]))
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
                    """, (chat_id, data["day"], data["week_type"], data["pair_number"], cabinet))
    
    # Автоматическая синхронизация
    source_chat_id = ALLOWED_CHAT_IDS[0]
    await sync_rasp_to_all_chats(source_chat_id)
    
    await message.answer(
        f"✅ Кабинет установлен для всех чатов!\n"
        f"📅 День: {DAYS[data['day']-1]}\n"
        f"🔢 Пара: {data['pair_number']}\n"
        f"🏫 Кабинет: {cabinet}\n\n"
        f"⚙ Админ-панель:",
        reply_markup=admin_menu()
    )
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

    # Очищаем пару для ВСЕХ чатов
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for chat_id in ALLOWED_CHAT_IDS:
                # проверяем, есть ли запись для этой пары
                await cur.execute("""
                    SELECT id FROM rasp_detailed
                    WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
                """, (chat_id, data["day"], data["week_type"], pair_number))
                row = await cur.fetchone()

                if row:
                    # обновляем предмет на NULL и кабинет на NULL
                    await cur.execute("""
                        UPDATE rasp_detailed
                        SET subject_id=NULL, cabinet=NULL
                        WHERE id=%s
                    """, (row[0],))
                else:
                    # создаём пустую запись
                    await cur.execute("""
                        INSERT INTO rasp_detailed (chat_id, day, week_type, pair_number, subject_id, cabinet)
                        VALUES (%s, %s, %s, %s, NULL, NULL)
                    """, (chat_id, data["day"], data["week_type"], pair_number))

    # Автоматическая синхронизация
    source_chat_id = ALLOWED_CHAT_IDS[0]
    await sync_rasp_to_all_chats(source_chat_id)

    await callback.message.edit_text(
        f"✅ Пара {pair_number} ({DAYS[data['day']-1]}, неделя {data['week_type']}) очищена во всех чатах.",
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
            # Используем общую четность для всех
            current_week = await get_current_week_type(pool)
            week_name = "Нечетная" if current_week == 1 else "Четная"
            week_info = f"\n\n📅 Сейчас неделя: {week_name}"
        except Exception as e:
            print(f"Ошибка получения четности: {e}")
            week_info = f"\n\n📅 Информация о неделе временно недоступна"
    
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



async def get_rasp_formatted(day, week_type, chat_id: int = None, target_date: datetime.date = None):
    """Получаем расписание для конкретного чата с информацией о домашних заданиях"""
    # Если chat_id не указан, используем первый из разрешенных
    if chat_id is None:
        chat_id = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else DEFAULT_CHAT_ID
    
    msg_lines = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.pair_number, COALESCE(r.cabinet, '') as cabinet, COALESCE(s.name, 'Свободно') as name
                   FROM rasp_detailed r
                   LEFT JOIN subjects s ON r.subject_id = s.id
                   WHERE r.chat_id=%s AND r.day=%s AND r.week_type=%s
                   ORDER BY r.pair_number""",
                (chat_id, day, week_type)
            )
            rows = await cur.fetchall()
    
    max_pair = 0
    pairs_dict = {}
    for row in rows:
        pair_num = row[0]
        pairs_dict[pair_num] = row
        if pair_num > max_pair:
            max_pair = pair_num
    
    if max_pair == 0:
        result = "Расписание пустое."
    else:
        for i in range(1, max_pair + 1):
            if i in pairs_dict:
                row = pairs_dict[i]
                cabinet = row[1]
                subject_name = row[2]
                
                if subject_name == "Свободно":
                    msg_lines.append(f"{i}. Свободно")
                else:
                    import re
                    clean_subject_name = re.sub(r'\s+(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', '', subject_name).strip()
                    
                    if cabinet and cabinet != "Не указан":
                        msg_lines.append(f"{i}. {cabinet} {clean_subject_name}")
                    else:
                        cabinet_match = re.search(r'(\s+)(\d+\.?\d*[а-я]?|\d+\.?\d*/\d+\.?\d*|сп/з|актовый зал|спортзал)$', subject_name)
                        if cabinet_match:
                            extracted_cabinet = cabinet_match.group(2)
                            msg_lines.append(f"{i}. {extracted_cabinet} {clean_subject_name}")
                        else:
                            msg_lines.append(f"{i}. {clean_subject_name}")
            else:
                msg_lines.append(f"{i}. Свободно")
        
        result = "\n".join(msg_lines)
    
    # Добавляем информацию о домашних заданиях на целевую дату
    if target_date is None:
        target_date = datetime.datetime.now(TZ).date()
    
    target_date_str = target_date.strftime("%Y-%m-%d")
    has_hw = await has_homework_for_date(pool, target_date_str)
    
    if has_hw:
        result += "\n\n📚 Есть заданное домашнее задание"
    
    return result

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

    # В ЛС используем ID ЛС чата для получения четности, в беседах - ID беседы
    current_chat_id = message.chat.id

    await greet_and_send(
        message.from_user,
        "Выберите действие:",
        message=message,
        markup=main_menu(is_admin=is_admin, is_special_user=is_special_user, is_group_chat=not is_private),
        include_week_info=True,
        chat_id=current_chat_id  # Передаем правильный chat_id для получения четности
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
        day_name = "послезавтра (Понедельник)"
    else:
        day_name = "завтра"
    
    # Получаем актуальную четность недели
    week_type = await get_current_week_type(pool, chat_id)
    
    # ВАЖНО: ЕСЛИ ПОКАЗЫВАЕМ ПОНЕДЕЛЬНИК И СЕЙЧАС ВОСКРЕСЕНЬЕ ИЛИ СУББОТА - МЕНЯЕМ ЧЕТНОСТЬ
    if day_to_show == 1:
        # Если сегодня воскресенье ИЛИ сегодня суббота
        if current_weekday == 7 or current_weekday == 6:
            week_type = 2 if week_type == 1 else 1
            print(f"🔁 Смена четности для понедельника в tomorrow_rasp: {'нечетная' if week_type == 1 else 'четная'}")
    
    # Получаем расписание с информацией о домашних заданиях на target_date
    text = await get_rasp_formatted(day_to_show, week_type, chat_id, target_date)
    
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
    
    await callback.message.edit_text(message, reply_markup=kb)
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
    
    await callback.message.edit_text(
        f"📅 {day_names[day]} | Неделя: {week_name}\n\n{text}", 
        reply_markup=kb
    )
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
        # Устанавливаем общую четность для всех
        await set_current_week_type(pool, week_type=week_type)
        
        week_name = "нечетная" if week_type == 1 else "четная"
        
        await callback.message.edit_text(
            f"✅ Четность установлена: {week_name} неделя для всех чатов\n\n"
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

@dp.message(Command("check_week"))
async def check_week_status(message: types.Message):
    """Проверка текущей четности во всех чатах"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    status_text = "📊 Статус четности по чатам:\n\n"
    
    for chat_id in ALLOWED_CHAT_IDS:
        week_type = await get_current_week_type(pool, chat_id)
        week_name = "нечетная" if week_type == 1 else "четная"
        status_text += f"Чат {chat_id}: {week_name} ({week_type})\n"
    
    await message.answer(status_text)

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
                day_note = " (неделя сменилась)"
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

@dp.message(Command("sync_week"))
async def sync_week_all_chats(message: types.Message):
    """Синхронизирует четность во всех чатах"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    try:
        # Берем четность из первого чата как основную
        main_chat_id = ALLOWED_CHAT_IDS[0]
        main_week_type = await get_current_week_type(pool, main_chat_id)
        
        # Устанавливаем такую же четность для всех чатов
        for chat_id in ALLOWED_CHAT_IDS:
            await set_current_week_type(pool, chat_id, main_week_type)
        
        week_name = "нечетная" if main_week_type == 1 else "четная"
        await message.answer(f"✅ Четность синхронизирована: {week_name} неделя для всех чатов")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка синхронизации: {e}")


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

'''
@dp.message(Command("testdr"))
async def cmd_test_birthday(message: types.Message):
    """Тестирование отправки поздравления по ID из базы - только админы в ЛС"""
    if message.chat.type != "private" or message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ Эта команда доступна только администраторам в личных сообщениях")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⚠ Использование: /testdr <ID_из_базы>\n\n"
            "Сначала посмотрите ID в /listdr\n\n"
            "Пример:\n"
            "/testdr 1\n"
            "/testdr 5"
        )
        return

    try:
        birthday_id = int(parts[1].strip())
        
        # Получаем данные о дне рождения из базы
        birthday_data = await get_birthday_by_id(pool, birthday_id)
        if not birthday_data:
            await message.answer(f"❌ День рождения с ID {birthday_id} не найден в базе.\nИспользуйте /listdr чтобы посмотреть все ID.")
            return

        bday_id, user_name, birth_date, added_by, created_at = birthday_data
        
        # Вычисляем возраст
        today = datetime.datetime.now(TZ).date()
        birth_date_obj = birth_date if isinstance(birth_date, datetime.date) else datetime.datetime.strptime(str(birth_date), '%Y-%m-%d').date()
        age = today.year - birth_date_obj.year
        if today.month < birth_date_obj.month or (today.month == birth_date_obj.month and today.day < birth_date_obj.day):
            age -= 1

        # Создаем текст поздравления (точно такой же как в автоматической отправке)
        message_text = (
            f"🎉 С ДНЕМ РОЖДЕНИЯ, {user_name.upper()}! 🎉\n\n"
            f"В этом году тебе исполнилось целых {age} лет!\n\n"
            f"От сердца и почек дарю тебе цветочек 💐"
        )

        # Отправляем поздравление во ВСЕ беседы из конфига
        success_count = 0
        failed_chats = []

        await message.answer(f"🔄 Отправляю тестовое поздравление для {user_name}...")

        for chat_id in ALLOWED_CHAT_IDS:
            try:
                await bot.send_message(chat_id, message_text)
                success_count += 1
                print(f"✅ Тестовое поздравление для {user_name} отправлено в чат {chat_id}")
            except Exception as e:
                failed_chats.append(f"{chat_id}: {e}")
                print(f"❌ Ошибка отправки тестового поздравления для {user_name} в чат {chat_id}: {e}")

        # Формируем отчет
        report = f"✅ Тестовое поздравление отправлено!\n\n"
        report += f"👤 Имя: {user_name}\n"
        report += f"📅 Дата рождения: {birth_date_obj.strftime('%d.%m.%Y')}\n"
        report += f"🎂 Возраст: {age} лет\n"
        report += f"🆔 ID в базе: {birthday_id}\n\n"
        report += f"📊 Статистика отправки:\n"
        report += f"✅ Успешно: {success_count} из {len(ALLOWED_CHAT_IDS)} чатов\n"

        if failed_chats:
            report += f"❌ Ошибки: {len(failed_chats)} чатов\n\n"
            report += "Чаты с ошибками:\n"
            for i, error in enumerate(failed_chats[:3], 1):
                report += f"{i}. {error}\n"
            if len(failed_chats) > 3:
                report += f"... и еще {len(failed_chats) - 3} ошибок"

        await message.answer(report)

    except ValueError:
        await message.answer("❌ Неверный формат ID. Используйте цифры.\n\nПример: /testdr 1")
    except Exception as e:
        await message.answer(f"❌ Ошибка при тестировании: {e}")

'''



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

@dp.message(Command("force_birthday_check"))
async def cmd_force_birthday_check(message: types.Message):
    """Принудительная проверка дней рождения - для тестирования"""
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    await message.answer("🔄 Принудительная проверка дней рождения...")
    await check_birthdays()
    await message.answer("✅ Проверка завершена")


async def main():
    global pool
    pool = await get_pool()
    await init_db(pool)
    await ensure_columns(pool)
    await ensure_birthday_columns(pool)
    
    # Загружаем спец-пользователей из базы данных
    await load_special_users(pool)
    
    # Пересоздаем задания публикации при старте
    await reschedule_publish_jobs(pool)
    
    # Проверка дней рождения каждый день в 7:00 утра
    scheduler.add_job(
        check_birthdays, 
        CronTrigger(hour=7, minute=0, timezone=TZ),
        id="birthday_check"
    )
    
    # ЕЖЕДНЕВНЫЙ БЭКАП БАЗЫ ДАННЫХ в 6:00 утра
    scheduler.add_job(
        backup_database_job,
        CronTrigger(hour=6, minute=0, timezone=TZ),  # 6:00 утра по Омску
        id="daily_backup"
    )
        
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