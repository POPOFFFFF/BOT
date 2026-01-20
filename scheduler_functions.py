import datetime
import asyncio
from config import *
from database import *
from bot_init import bot, pool

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

async def check_birthdays():
    print(f"🎂 [{datetime.datetime.now(TZ)}] Запуск проверки дней рождения...")
    
    birthdays = await get_today_birthdays(pool)
    
    print(f"🎂 Найдено дней рождений: {len(birthdays)}")
    
    if not birthdays:
        print("🎂 Сегодня нет дней рождения")
        return True
        
    for birthday in birthdays:
        birthday_id, user_name, birth_date = birthday
        
        if isinstance(birth_date, datetime.datetime):
            birth_date_obj = birth_date.date()
        elif isinstance(birth_date, datetime.date):
            birth_date_obj = birth_date
        elif isinstance(birth_date, str):
            birth_date_obj = datetime.datetime.strptime(birth_date, '%Y-%m-%d').date()
        else:
            print(f"❌ Неизвестный формат даты: {type(birth_date)}")
            continue
        
        today = datetime.datetime.now(TZ).date()
        age = today.year - birth_date_obj.year
        if today.month < birth_date_obj.month or (today.month == birth_date_obj.month and today.day < birth_date_obj.day):
            age -= 1
        
        print(f"🎂 Поздравляем {user_name}, возраст: {age}")
        
        message_text = f"🎉 С ДНЕМ РОЖДЕНИЯ, {user_name.upper()}! 🎉\n\nВ этом году тебе исполнилось {age} лет!\n\nПоздравляю! 🎂"
        
        for chat_id in ALLOWED_CHAT_IDS:
            try:
                await bot.send_message(chat_id, message_text)
                print(f"✅ Отправлено поздравление для {user_name} в чат {chat_id}")
            except Exception as e:
                print(f"❌ Ошибка отправки поздравления для {user_name} в чат {chat_id}: {e}")
    
    print("✅ Проверка дней рождения завершена")
    return True