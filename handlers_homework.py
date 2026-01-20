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

# ========== ДОМАШНИЕ ЗАДАНИЯ (админ часть) ==========

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
    
    if due_date_str.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    try:
        due_date = datetime.datetime.strptime(due_date_str, '%d.%m.%Y').date()
        await state.update_data(due_date=due_date_str)
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, name FROM subjects ORDER BY name")
                subjects = await cur.fetchall()
        
        if not subjects:
            await message.answer("❌ В базе нет предметов. Сначала добавьте предметы.")
            await state.clear()
            return
        
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
    
    if task_text.lower() in ['отмена', 'cancel', '❌ отмена']:
        await message.answer("❌ Действие отменено.\n\n⚙ Админ-панель:", reply_markup=admin_menu())
        await state.clear()
        return
    
    if not task_text:
        await message.answer("❌ Текст задания не может быть пустым. Введите задание:")
        return
    
    data = await state.get_data()
    
    try:
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
        await state.update_data(new_due_date=None)
    else:
        due_date_str = message.text.strip()
        try:
            datetime.datetime.strptime(due_date_str, '%d.%m.%Y')
            await state.update_data(new_due_date=due_date_str)
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введите в формате ДД.ММ.ГГГГ или /skip:")
            return
    
    data = await state.get_data()
    
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
    
    subject_id = data.get('new_subject_id', data['current_subject_id'])
    due_date = data.get('new_due_date', data['current_due_date'])
    
    if isinstance(due_date, str) and '.' in due_date:
        try:
            due_date = datetime.datetime.strptime(due_date, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            await message.answer("❌ Ошибка в формате даты. Исправьте дату и попробуйте снова.")
            await state.clear()
            return
    
    try:
        await update_homework(pool, data['homework_id'], subject_id, due_date, new_task_text)
        
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