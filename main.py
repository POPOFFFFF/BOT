import asyncio
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import *
from database import *
from bot_init import dp, bot, pool, scheduler  # Импортируем из bot_init
from scheduler_functions import send_today_rasp, check_birthdays  # Импортируем из нового файла

# Импортируем все обработчики (чтобы они зарегистрировались)
import handlers
import handlers_admin
import handlers_admin2
import handlers_homework
import handlers_fund

from database import get_current_week_type, clear_rasp_modifications

# ========== ФУНКЦИИ ПЛАНИРОВЩИКА ==========

async def reset_rasp_for_new_week():
    try:
        current_week = await get_current_week_type(pool)
        previous_week = 2 if current_week == 1 else 1
        
        await clear_rasp_modifications(pool, previous_week)
        print(f"✅ Сброшены модификации расписания для недели {previous_week}")
        
    except Exception as e:
        print(f"❌ Ошибка при сбросе расписания: {e}")

def _job_id_for_time(hour: int, minute: int) -> str:
    return f"publish_{hour:02d}_{minute:02d}"

async def reschedule_publish_jobs():
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

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

async def main():
    global pool
    
    print("🤖 Бот Аркадий запускается...")
    
    try:
        pool = await get_pool()
        print("✅ Подключение к базе данных установлено")
        
        await init_db(pool)
        print("✅ База данных инициализирована")
        
        await ensure_columns(pool)
        await ensure_birthday_columns(pool)
        print("✅ Проверка структуры базы данных завершена")
        
        await load_special_users(pool)
        
        await reschedule_publish_jobs()
        
        scheduler.add_job(check_birthdays, CronTrigger(hour=9, minute=0, timezone=TZ))
        scheduler.add_job(reset_rasp_for_new_week, CronTrigger(hour=0, minute=0, timezone=TZ))
        
        scheduler.start()
        print("✅ Планировщик задач запущен")
        
        print(f"✅ Бот запущен! Чат ID: {ALLOWED_CHAT_IDS}")
        
        await dp.start_polling(bot)
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if pool:
            pool.close()
            await pool.wait_closed()
            print("✅ Подключение к базе данных закрыто")

if __name__ == "__main__":
    asyncio.run(main())