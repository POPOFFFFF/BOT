from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
import datetime
import re
from typing import List, Tuple

from config import *
from database import *
from states import *
from keyboards import *
from bot_init import dp, bot, pool  # Импортируем dp и bot
# ========== УСТАНОВКА КАБИНЕТОВ ==========

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
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]
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
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]]
    )
    
    await greet_and_send(callback.from_user, "Выберите номер пары:", callback=callback, markup=kb)
    await state.set_state(SetCabinetState.pair_number)
    await callback.answer()

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

@dp.message(SetCabinetState.cabinet)
async def set_cabinet_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cabinet = message.text.strip()
    
    if cabinet.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    day = data.get("day")
    week_type = data.get("week_type") 
    pair_number = data.get("pair_number")
    
    if not all([day, week_type, pair_number]):
        await message.answer("❌ Ошибка: не найдены данные о паре. Начните заново.")
        await state.clear()
        return
    
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
    
    await message.answer(
        f"✅ Кабинет установлен для всех чатов!\n"
        f"📅 День: {DAYS[day-1]}\n"
        f"🔢 Пара: {pair_number}\n"
        f"🏫 Кабинет: {cabinet}\n\n"
        f"⚙ Админ-панель:",
        reply_markup=admin_menu()
    )
    await state.clear()

# ========== УПРАВЛЕНИЕ ПРЕДМЕТАМИ ==========

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
    
    if subject_name.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
        
    if not subject_name:
        await message.answer("❌ Название предмета не может быть пустым. Введите название:")
        return
    
    await state.update_data(name=subject_name)
    
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

@dp.callback_query(F.data.startswith("subject_type_"))
async def process_subject_type_choice(callback: types.CallbackQuery, state: FSMContext):
    try:
        subject_type = callback.data[len("subject_type_"):]
        data = await state.get_data()
        subject_name = data["name"]
        
        if subject_type == "fixed":
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

@dp.message(AddSubjectState.cabinet)
async def process_subject_cabinet(message: types.Message, state: FSMContext):
    cabinet = message.text.strip()
    
    if cabinet.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
        
    data = await state.get_data()
    subject_name = data["name"]
    
    if not cabinet:
        await message.answer("❌ Номер кабинета не может быть пустым. Введите кабинет:")
        return
    
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
    
    await message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
    await state.clear()

@dp.callback_query(F.data == "admin_delete_subject")
async def admin_delete_subject_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name, rK FROM subjects ORDER BY name")
            subjects = await cur.fetchall()
    
    if not subjects:
        await callback.message.edit_text("❌ В базе нет предметов для удаления.")
        await callback.answer()
        return
    
    keyboard = []
    for subject_id, name, rk in subjects:
        type_icon = "🔢" if rk else "🏫"
        button_text = f"{type_icon} {name}"
        keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"delete_subject_{subject_id}")])
    
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
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name, rK FROM subjects WHERE id=%s", (subject_id,))
            subject = await cur.fetchone()
            
            if not subject:
                await callback.message.edit_text("❌ Предмет не найден.")
                await callback.answer()
                return
            
            name, rk = subject
            
            await cur.execute("SELECT COUNT(*) FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
            usage_count_rasp = (await cur.fetchone())[0]
            
            await cur.execute("SELECT COUNT(*) FROM homework WHERE subject_id=%s", (subject_id,))
            usage_count_homework = (await cur.fetchone())[0]
            
            total_usage = usage_count_rasp + usage_count_homework
            
            if total_usage > 0:
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
                await cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
                await callback.message.edit_text(f"✅ Предмет '{name}' удален.")
                
                await callback.message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
                await state.clear()
    
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_subject_"))
async def confirm_delete_subject(callback: types.CallbackQuery):
    subject_id = int(callback.data[len("confirm_delete_subject_"):])
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM subjects WHERE id=%s", (subject_id,))
            subject_name = (await cur.fetchone())[0]
            
            await cur.execute("DELETE FROM rasp_detailed WHERE subject_id=%s", (subject_id,))
            await cur.execute("DELETE FROM rasp_modifications WHERE subject_id=%s", (subject_id,))
            await cur.execute("DELETE FROM static_rasp WHERE subject_id=%s", (subject_id,))
            await cur.execute("DELETE FROM homework WHERE subject_id=%s", (subject_id,))
            await cur.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
    
    await callback.message.edit_text(
        f"✅ Предмет '{subject_name}' и все связанные данные удалены."
    )
    
    await callback.message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "cancel_delete_subject")
async def cancel_delete_subject(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Удаление отменено.")
    await menu_back_handler(callback, state)
    await callback.answer()

# ========== СТАТИЧНОЕ РАСПИСАНИЕ ==========

@dp.callback_query(F.data == "admin_save_static_rasp")
async def admin_save_static_rasp_start(callback: types.CallbackQuery, state: FSMContext):
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
        success = await initialize_static_rasp_from_current(pool, week_type)
        
        if success:
            week_name = "нечетную" if week_type == 1 else "четную"
            await callback.message.edit_text(
                f"✅ Текущее расписание сохранено как статичное для {week_name} недели!\n\n"
                f"⚠️ Внимание: Сохранены ВСЕ текущие пары (включая модификации) как статичное расписание.\n"
                f"Теперь при автоматической смене недели эти пары будут сохраняться.\n\n"
                f"⚙ Админ-панель:",
                reply_markup=admin_menu()
            )
        else:
            await callback.message.edit_text(
                "❌ Не удалось сохранить статичное расписание.\n"
                "Проверьте логи для подробностей.\n\n"
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

# ========== СПЕЦ-ПОЛЬЗОВАТЕЛИ (админ часть) ==========

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
        await set_special_user_signature(pool, user_id, signature)
        
        if user_id not in SPECIAL_USER_ID:
            SPECIAL_USER_ID.append(user_id)
        
        await message.answer(
            f"✅ Спец-пользователь добавлен!\n\n"
            f"👤 ID: {user_id}\n"
            f"📝 Подпись: {signature}\n\n"
            f"Пользователь теперь может отправлять сообщения в беседу через кнопку в меню."
        )
        
        await message.answer("⚙ Админ-панель:", reply_markup=admin_menu())
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении пользователя: {e}")
    
    await state.clear()

# ========== УДАЛЕНИЕ СООБЩЕНИЙ ПРЕПОДАВАТЕЛЕЙ ==========

@dp.callback_query(F.data == "admin_delete_teacher_message")
async def admin_delete_teacher_message_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.message.chat.type != "private" or callback.from_user.id not in ALLOWED_USERS:
        await callback.answer("⛔ Только в ЛС админам", show_alert=True)
        return

    messages = await get_teacher_messages(pool, limit=20)
    
    if not messages:
        await callback.message.edit_text(
            "🗑️ Удаление сообщения преподавателя\n\n"
            "❌ В базе нет сообщений для удаления."
        )
        await callback.answer()
        return
    
    keyboard = []
    for i, (msg_id, message_id, signature, text, msg_type, created_at) in enumerate(messages):
        display_text = text[:30] + "..." if len(text) > 30 else text
        if not display_text:
            display_text = f"{msg_type}"
        
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m %H:%M")
        else:
            date_str = str(created_at)
        
        button_text = f"{signature}: {display_text} ({date_str})"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text, 
            callback_data=f"delete_teacher_msg_{msg_id}"
        )])
    
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
    await state.clear()
    await callback.message.edit_text("⚙ Админ-панель:", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_teacher_msg_"))
async def process_delete_teacher_message(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "menu_admin":
        await callback.message.edit_text("⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        await callback.answer()
        return
    
    try:
        message_db_id = int(callback.data[len("delete_teacher_msg_"):])
        
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
        
        if isinstance(created_at, datetime.datetime):
            date_str = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            date_str = str(created_at)
        
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

@dp.callback_query(F.data.startswith("confirm_delete_msg_"))
async def confirm_delete_teacher_message(callback: types.CallbackQuery):
    try:
        message_db_id = int(callback.data[len("confirm_delete_msg_"):])
        
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

@dp.callback_query(F.data == "cancel_delete_msg")
async def cancel_delete_teacher_message(callback: types.CallbackQuery):
    await menu_back_handler(callback, None)
    await callback.answer()