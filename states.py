from aiogram.fsm.state import StatesGroup, State

class ClearModificationsState(StatesGroup):
    week_type = State()
    day = State()
    confirm_clear_all = State()

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

class GroupFundStates(StatesGroup):
    add_member_name = State()
    delete_member_confirm = State()
    select_member_for_balance = State()
    enter_balance_change = State()
    add_purchase_name = State()
    add_purchase_url = State()
    add_purchase_price = State()
    delete_purchase_confirm = State()