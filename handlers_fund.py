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

# ========== УПРАВЛЕНИЕ ФОНДОМ ==========

@dp.callback_query(F.data == "fund_manage_members")
async def fund_manage_members_handler(callback: types.CallbackQuery):
    kb = fund_members_keyboard()
    
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
        
        try:
            await message.delete()
        except:
            pass
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        
        await message.answer(
            f"✅ Участник '{full_name}' добавлен!\n\n"
            f"💰 Управление Фондом Группы:",
            reply_markup=kb
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении участника: {e}")
    
    await state.clear()

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
        else:
            callback_data = f"select_member_balance_{member_id}"
        
        keyboard.append([InlineKeyboardButton(
            text=f"{full_name} ({balance:.2f} руб.)", 
            callback_data=callback_data
        )])
    
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

# ========== ИЗМЕНЕНИЕ БАЛАНСА ==========

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
        
        await update_member_balance(pool, member_id, amount)
        await update_fund_balance(pool, amount)
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT balance FROM group_fund_members WHERE id = %s", (member_id,))
                result = await cur.fetchone()
                new_balance = float(result[0]) if result else current_balance + amount
        
        print(f"🔍 DEBUG: Новый баланс участника: {new_balance}")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        
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

# ========== УПРАВЛЕНИЕ ПОКУПКАМИ ==========

@dp.callback_query(F.data == "fund_manage_purchases")
async def fund_manage_purchases_handler(callback: types.CallbackQuery):
    kb = fund_purchases_keyboard()
    
    await callback.message.edit_text(
        "🛍️ Управление покупками\n\n"
        "Выберите действие:",
        reply_markup=kb
    )
    await callback.answer()

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
        
        await add_purchase(pool, item_name, item_url, price)
        
        balance = await get_fund_balance(pool)
        
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
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
        ])
        await callback.message.answer("💰 Управление Фондом Группы:", reply_markup=kb)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при удалении покупки: {e}")
    
    await callback.answer()