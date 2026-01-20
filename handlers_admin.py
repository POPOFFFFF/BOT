from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
import datetime
import re
from typing import List, Tuple
from bot_init import dp, bot, pool  # Импортируем dp и bot

from config import *
from database import *
from states import *
from keyboards import *

# ========== АДМИН-ОБРАБОТЧИКИ ==========

@dp.callback_query(F.data == "admin_commands")
async def admin_commands_handler(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    commands_text = """
🤖 **КОМАНДЫ АДМИНИСТРАТОРА**

📊 **Управление расписанием:**
`/аркадий` - Главное меню
`/никнейм <имя>` - Установить никнейм
`/анекдот` - Случайный анекдот

👥 **Управление пользователями:**
`/акик` - Кикнуть пользователя (в ответ на сообщение)
`/амут <время> <единица>` - Мут пользователя
`/аразмут` - Снять мут
`/аспам` - Удалить спам и кикнуть

🎂 **Дни рождения:**
`/adddr Имя ДД.ММ.ГГГГ` - Добавить день рождения
`/listdr` - Список всех дней рождений
`/deldr <id>` - Удалить день рождения

💰 **Фонд группы:**
`/sql <запрос>` - Выполнить SQL запрос
`/экспорт` - Скачать бэкап базы данных

⚙ **Системные команды:**
`/jobs` - Показать активные задания планировщика
`/delptime <id>` - Удалить время публикации

📋 **Админ-панель (кнопки):**
• Установить четность недели
• Управление временем публикаций  
• Добавить/удалить пары
• Установить кабинеты
• Управление предметами
• Сохранить статичное расписание
• Управление домашними заданиями
• Управление спец-пользователями
• Удаление сообщений преподавателей

💡 **Примеры SQL запросов:**
`/sql SELECT * FROM group_fund_balance`
`/sql UPDATE group_fund_balance SET current_balance = 1000 WHERE id = 1`
`/sql INSERT INTO table VALUES (...)`

🛡️ **Модерация в беседах:**
• Кик, мут, бан через кнопки
• Очистка спама
• Просмотр сообщений преподавателей
"""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад в админку", callback_data="menu_admin")],
        [InlineKeyboardButton(text="🔄 Обновить список", callback_data="admin_commands")]
    ])

    await callback.message.edit_text(commands_text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

# ========== УПРАВЛЕНИЕ ЧЕТНОСТЬЮ ==========

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
        current_week = await get_current_week_type(pool)
        
        await set_current_week_type(pool, week_type=week_type)
        
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

@dp.callback_query(F.data == "admin_show_chet")
async def admin_show_chet(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Доступно только админам в ЛС", show_alert=True)
        return
    
    current = await get_current_week_type(pool)
    current_str = "нечетная (1)" if current == 1 else "четная (2)"
    
    status_text = f"📊 Текущая четность недели (общая для всех чатов):\n\n{current_str}"
    
    kb = back_to_admin_keyboard()
    
    await callback.message.edit_text(status_text, reply_markup=kb)
    await callback.answer()

# ========== ВРЕМЯ ПУБЛИКАЦИЙ ==========

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
    
    kb = back_to_admin_keyboard()
    
    await greet_and_send(callback.from_user, text, callback=callback, markup=kb)
    await callback.answer()

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
        await reschedule_publish_jobs()
        await message.answer(f"✅ Время публикации добавлено: {hh:02d}:{mm:02d} (Омск).")
    except Exception as e:
        await message.answer(f"❌ Ошибка при сохранении: {e}")
    finally:
        await state.clear()

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
    
    kb = back_to_admin_keyboard()
    
    await greet_and_send(callback.from_user, text, callback=callback, markup=kb)
    await callback.answer()

# ========== ДОБАВЛЕНИЕ ПАР ==========

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
        display_name = subject_name[:30] + "..." if len(subject_name) > 30 else subject_name
        
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
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name, rK FROM subjects WHERE id=%s", (subject_id,))
            result = await cur.fetchone()
            
            if not result:
                await callback.answer("❌ Предмет не найден в базе данных", show_alert=True)
                return
            
            subject_name, is_rk = result
    
    print(f"🔍 DEBUG choose_subject_by_id: предмет='{subject_name}', rK={is_rk}, ID={subject_id}")
    
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
    
    if is_rk:
        await callback.message.edit_text(
            f"📚 Выбран предмет: {subject_name}\n"
            f"🔢 Тип: с запросом кабинета (rK)\n\n"
            "Выберите четность недели:",
            reply_markup=kb
        )
    else:
        await callback.message.edit_text(
            f"📚 Выбран предмет: {subject_name}\n"
            f"🏫 Тип: с фиксированным кабинетом\n\n"
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
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text("Выберите номер пары:", reply_markup=kb)
    await state.set_state(AddLessonState.pair_number)

@dp.callback_query(F.data.startswith("pair_"))
async def choose_pair(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("pair_"):])
    await state.update_data(pair_number=pair_number)
    
    data = await state.get_data()
    subject_name = data["subject"]
    subject_id = data["subject_id"]
    is_rk = data["is_rk"]
    
    print(f"🔍 DEBUG choose_pair: день={data['day']}, неделя={data['week_type']}, пара={pair_number}, предмет={subject_name}, ID={subject_id}, rK={is_rk}")
    
    try:
        if is_rk:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
            ])
            
            await callback.message.edit_text(
                f"📚 Предмет: {subject_name}\n"
                f"📅 День: {DAYS[data['day']-1]}\n" 
                f"🔢 Пара: {pair_number}\n"
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
            
            print(f"🔍 DEBUG: Сохраняем обычный предмет - кабинет: {cabinet}")
            
            success_count = 0
            for chat_id in ALLOWED_CHAT_IDS:
                success = await save_rasp_modification(pool, chat_id, data["day"], data["week_type"], pair_number, subject_id, cabinet)
                if success:
                    success_count += 1
                print(f"🔍 DEBUG: Модификация для чата {chat_id} - {'успешно' if success else 'ошибка'}")
            
            await save_static_rasp(pool, data["day"], data["week_type"], pair_number, subject_id, cabinet)
            print(f"✅ Пара добавлена в статичное расписание: день={data['day']}, неделя={data['week_type']}, пара={pair_number}")
            
            display_name = clean_subject_name
            
            await callback.message.edit_text(
                f"✅ Урок '{display_name}' добавлен как изменение расписания!\n"
                f"📅 День: {DAYS[data['day']-1]}\n"
                f"🔢 Пара: {pair_number}\n"
                f"🏫 Кабинет: {cabinet}\n"
                f"💬 Обновлено чатов: {success_count}/{len(ALLOWED_CHAT_IDS)}\n"
                f"💾 Также сохранено в статичное расписание\n\n"
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
    
    print(f"🔍 DEBUG set_cabinet: получен кабинет '{cabinet}' для rK предмета")
    
    try:
        day = data.get("day")
        week_type = data.get("week_type") 
        pair_number = data.get("pair_number")
        subject_id = data.get("subject_id")
        subject_name = data.get("subject")
        
        if not all([day, week_type, pair_number, subject_id]):
            await message.answer("❌ Ошибка: не найдены данные о паре. Начните заново.")
            await state.clear()
            return
        
        print(f"🔍 DEBUG: Сохраняем rK предмет - день:{day}, неделя:{week_type}, пара:{pair_number}, предмет:{subject_name}, кабинет:{cabinet}")
        
        success_count = 0
        for chat_id in ALLOWED_CHAT_IDS:
            success = await save_rasp_modification(pool, chat_id, day, week_type, pair_number, subject_id, cabinet)
            if success:
                success_count += 1
            print(f"🔍 DEBUG: Модификация для чата {chat_id} - {'успешно' if success else 'ошибка'}")
        
        await save_static_rasp(pool, day, week_type, pair_number, subject_id, cabinet)
        print(f"✅ rK пара добавлена в статичное расписание: день={day}, неделя={week_type}, пара={pair_number}")
        
        await message.answer(
            f"✅ Урок '{subject_name}' добавлен как изменение расписания!\n"
            f"📅 День: {DAYS[day-1]}\n"
            f"🔢 Пара: {pair_number}\n"
            f"🏫 Кабинет: {cabinet} (вручную)\n"
            f"💬 Обновлено чатов: {success_count}/{len(ALLOWED_CHAT_IDS)}\n"
            f"💾 Также сохранено в статичное расписание\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        print(f"❌ Ошибка в set_cabinet: {e}")
        await message.answer(f"❌ Ошибка при добавлении урока: {e}")
    
    await state.clear()

# ========== ОЧИСТКА ПАР ==========

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
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]
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
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]
    )
    
    await greet_and_send(callback.from_user, "Выберите номер пары:", callback=callback, markup=kb)
    await state.set_state(ClearPairState.pair_number)
    await callback.answer()

@dp.callback_query(F.data.startswith("clr_pair_"))
async def clear_pair_number(callback: types.CallbackQuery, state: FSMContext):
    pair_number = int(callback.data[len("clr_pair_"):])
    data = await state.get_data()

    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for chat_id in ALLOWED_CHAT_IDS:
                    await cur.execute("""
                        DELETE FROM rasp_modifications 
                        WHERE chat_id=%s AND day=%s AND week_type=%s AND pair_number=%s
                    """, (chat_id, data["day"], data["week_type"], pair_number))
                    
                    await cur.execute("""
                        INSERT INTO rasp_modifications (chat_id, day, week_type, pair_number, subject_id, cabinet)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (chat_id, data["day"], data["week_type"], pair_number, None, "Очищено"))

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

# ========== СБРОС ВСЕЙ НЕДЕЛИ ==========

@dp.callback_query(F.data == "admin_reset_week")
async def admin_reset_week_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    kb = reset_week_keyboard()
    
    await callback.message.edit_text(
        "💥 Сброс ВСЕГО расписания на неделю\n\n"
        "⚠️ ВНИМАНИЕ! Это удалит:\n"
        "• Все модификации расписания\n"
        "• Все пары в статичном расписании\n"
        "• Все пары в детализированном расписании\n\n"
        "Выберите неделю для сброса:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("reset_week_"))
async def reset_week_confirm(callback: types.CallbackQuery):
    week_type = int(callback.data.split("_")[2])
    week_name = "нечетной" if week_type == 1 else "четной"
    
    kb = confirm_reset_keyboard(week_type)
    
    await callback.message.edit_text(
        f"⚠️ ОПАСНОЕ ДЕЙСТВИЕ!\n\n"
        f"Вы собираетесь сбросить ВСЁ расписание на {week_name} неделю:\n\n"
        f"• Все модификации расписания\n"
        f"• Все пары в статичном расписании\n"
        f"• Все пары в детализированном расписании\n\n"
        f"ЭТО НЕЛЬЗЯ ОТМЕНИТЬ!\n\n"
        f"Вы уверены?",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_reset_week_"))
async def confirm_reset_week(callback: types.CallbackQuery):
    week_type = int(callback.data.split("_")[3])
    week_name = "нечетную" if week_type == 1 else "четную"
    
    try:
        await callback.message.edit_text(f"🔄 Сбрасываю всё расписание на {week_name} неделю...")
        
        deleted_counts = await reset_week_schedule(pool, week_type)
        
        result_text = (
            f"✅ Сброс {week_name} недели завершен!\n\n"
            f"Удалено:\n"
            f"• Модификации: {deleted_counts['modifications']} шт.\n"
            f"• Статичные пары: {deleted_counts['static_rasp']} шт.\n"
            f"• Детализированные пары: {deleted_counts['rasp_detailed']} шт.\n\n"
            f"Расписание на {week_name} неделю теперь полностью пустое."
        )
        
        kb = back_to_admin_keyboard()
        
        await callback.message.edit_text(result_text, reply_markup=kb)
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при сбросе недели: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
    await callback.answer()

# ========== СБРОС МОДИФИКАЦИЙ ==========

@dp.callback_query(F.data == "admin_clear_modifications")
async def admin_clear_modifications_start(callback: types.CallbackQuery):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    kb = clear_modifications_week_keyboard()
    
    await callback.message.edit_text(
        "🗑️ Сброс модификаций расписания\n\n"
        "Выберите опцию:\n"
        "• Нечетная/четная неделя - сбросить ВСЕ модификации для выбранной недели\n"
        "• Выбрать день - сбросить модификации для конкретного дня",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("clear_mod_week_"))
async def clear_modifications_week_handler(callback: types.CallbackQuery):
    week_type = int(callback.data.split("_")[3])
    
    week_name = "нечетной" if week_type == 1 else "четной"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить всё", callback_data=f"confirm_clear_all_{week_type}")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_clear_modifications")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ Подтверждение сброса\n\n"
        f"Вы собираетесь сбросить ВСЕ модификации расписания для {week_name} недели.\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_clear_all_"))
async def confirm_clear_all_modifications(callback: types.CallbackQuery):
    try:
        week_type = int(callback.data.split("_")[3])
        
        cleared_count = await clear_rasp_modifications(pool, week_type)
        
        week_name = "нечетной" if week_type == 1 else "четной"
        
        await callback.message.edit_text(
            f"✅ Сброс завершен!\n\n"
            f"Удалены все модификации для {week_name} недели.\n"
            f"Очищено записей: {cleared_count}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при сбросе модификаций: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
    await callback.answer()

@dp.callback_query(F.data == "clear_mod_choose_day")
async def clear_modifications_choose_day_start(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная неделя", callback_data="clear_day_week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная неделя", callback_data="clear_day_week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_clear_modifications")]
    ])
    
    await callback.message.edit_text(
        "🗑️ Сброс модификаций для дня\n\n"
        "Сначала выберите четность недели:",
        reply_markup=kb
    )
    await state.set_state(ClearModificationsState.week_type)
    await callback.answer()

@dp.callback_query(F.data.startswith("clear_day_week_"))
async def clear_modifications_choose_week(callback: types.CallbackQuery, state: FSMContext):
    week_type = int(callback.data.split("_")[3])
    await state.update_data(week_type=week_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=day, callback_data=f"clear_mod_day_{i+1}")] 
        for i, day in enumerate(DAYS)
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_clear_modifications")]]
    )
    
    week_name = "нечетной" if week_type == 1 else "четной"
    
    await callback.message.edit_text(
        f"🗑️ Сброс модификаций для {week_name} недели\n\n"
        "Выберите день недели:",
        reply_markup=kb
    )
    await state.set_state(ClearModificationsState.day)
    await callback.answer()

@dp.callback_query(F.data.startswith("clear_mod_day_"))
async def clear_modifications_choose_specific_day(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data.split("_")[3])
    
    data = await state.get_data()
    week_type = data["week_type"]
    
    day_name = DAYS[day-1]
    week_name = "нечетной" if week_type == 1 else "четной"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить", callback_data=f"confirm_clear_day_{week_type}_{day}")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_clear_modifications")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ Подтверждение сброса\n\n"
        f"Вы собираетесь сбросить модификации расписания:\n"
        f"📅 День: {day_name}\n"
        f"🔢 Неделя: {week_name}\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_clear_day_"))
async def confirm_clear_day_modifications(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        week_type = int(parts[3])
        day = int(parts[4])
        
        cleared_count = await clear_day_modifications(pool, week_type, day)
        
        day_name = DAYS[day-1]
        week_name = "нечетной" if week_type == 1 else "четной"
        
        await callback.message.edit_text(
            f"✅ Сброс завершен!\n\n"
            f"Удалены модификации для:\n"
            f"📅 День: {day_name}\n"
            f"🔢 Неделя: {week_name}\n"
            f"Очищено записей: {cleared_count}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при сбросе модификаций: {e}\n\n"
            f"⚙ Админ-панель:",
            reply_markup=admin_menu()
        )
    
    await callback.answer()