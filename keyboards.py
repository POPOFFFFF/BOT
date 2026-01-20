from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import DAYS, ALLOWED_USERS, FUND_MANAGER_USER_ID
from database import get_nickname, get_special_user_signature, get_pool

async def main_menu(is_admin=False, is_special_user=False, is_group_chat=False, is_fund_manager=False):
    buttons = []
    
    if is_group_chat:
        buttons.append([InlineKeyboardButton(text="👨‍🏫 Посмотреть сообщения преподов", callback_data="view_teacher_messages")])
        buttons.append([InlineKeyboardButton(text="📚 Домашнее задание", callback_data="menu_homework")])
        buttons.append([InlineKeyboardButton(text="📅 Расписание", callback_data="menu_rasp")])
        buttons.append([InlineKeyboardButton(text="📅 Расписание на сегодня", callback_data="today_rasp")])
        buttons.append([InlineKeyboardButton(text="📅 Расписание на завтра", callback_data="tomorrow_rasp")])
        buttons.append([InlineKeyboardButton(text="⏰ Звонки", callback_data="menu_zvonki")])
        buttons.append([InlineKeyboardButton(text="🎂 Дни рожденья", callback_data="menu_birthdays")])
        buttons.append([InlineKeyboardButton(text="💰 Фонд Группы", callback_data="menu_group_fund")])

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
        
        [InlineKeyboardButton(text="💥 Сбросить всё на неделю", callback_data="admin_reset_week")],
        
        [InlineKeyboardButton(text="🗑️ Сбросить модификации", callback_data="admin_clear_modifications")],
        
        [InlineKeyboardButton(text="🏫 Установить кабинет", callback_data="admin_set_cabinet")],
        
        [InlineKeyboardButton(text="📚 Добавить предмет", callback_data="admin_add_subject")],
        [InlineKeyboardButton(text="🗑️ Удалить предмет", callback_data="admin_delete_subject")],
        
        [InlineKeyboardButton(text="💾 Сохранить статичное расписание", callback_data="admin_save_static_rasp")],
        
        [InlineKeyboardButton(text="📝 Добавить домашнее задание", callback_data="admin_add_homework")],
        [InlineKeyboardButton(text="✏️ Редактировать домашнее задание", callback_data="admin_edit_homework")],
        [InlineKeyboardButton(text="🗑️ Удалить домашнее задание", callback_data="admin_delete_homework")],
        
        [InlineKeyboardButton(text="👤 Добавить спец-пользователя", callback_data="admin_add_special_user")],
        [InlineKeyboardButton(text="🗑️ Удалить сообщение преподавателя", callback_data="admin_delete_teacher_message")],
        
        [InlineKeyboardButton(text="📋 Все команды", callback_data="admin_commands")],
        
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])
    return kb

def rasp_days_keyboard():
    keyboard = []
    for i, day in enumerate(DAYS):
        keyboard.append([InlineKeyboardButton(text=day, callback_data=f"rasp_day_{i+1}")])
    keyboard.append([InlineKeyboardButton(text="⬅ Назад", callback_data="menu_rasp")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def rasp_week_type_keyboard(day: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная", callback_data=f"rasp_show_{day}_1")],
        [InlineKeyboardButton(text="2️⃣ Четная", callback_data=f"rasp_show_{day}_2")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_rasp")]
    ])

def zvonki_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Будние дни", callback_data="zvonki_weekday")],
        [InlineKeyboardButton(text="📅 Суббота", callback_data="zvonki_saturday")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_zvonki")]
    ])

def back_to_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])

def back_to_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_admin")]
    ])

def clear_modifications_week_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная неделя", callback_data="clear_mod_week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная неделя", callback_data="clear_mod_week_2")],
        [InlineKeyboardButton(text="📅 Выбрать день", callback_data="clear_mod_choose_day")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])

def reset_week_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Нечетная неделя", callback_data="reset_week_1")],
        [InlineKeyboardButton(text="2️⃣ Четная неделя", callback_data="reset_week_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_admin")]
    ])

def confirm_reset_keyboard(week_type: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 Да, сбросить ВСЁ", callback_data=f"confirm_reset_week_{week_type}")],
        [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="menu_admin")]
    ])

def fund_management_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Добавить/убрать человека", callback_data="fund_manage_members")],
        [InlineKeyboardButton(text="💰 Изменить баланс человека", callback_data="fund_manage_balance")],
        [InlineKeyboardButton(text="🛍️ Добавить/удалить покупку", callback_data="fund_manage_purchases")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])

def fund_members_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить человека", callback_data="fund_add_member")],
        [InlineKeyboardButton(text="➖ Удалить человека", callback_data="fund_delete_member")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
    ])

def fund_purchases_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить покупку", callback_data="fund_add_purchase")],
        [InlineKeyboardButton(text="➖ Удалить покупку", callback_data="fund_delete_purchase")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_fund_management")]
    ])

def group_fund_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Покупки", callback_data="fund_purchases")],
        [InlineKeyboardButton(text="👥 Список Пожертвований", callback_data="fund_donations")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])