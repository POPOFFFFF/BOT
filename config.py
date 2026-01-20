import os
import ssl
from zoneinfo import ZoneInfo

TOKEN = os.getenv("BOT_TOKEN")
CHAT_IDS_STR = os.getenv("CHAT_ID", "")
ALLOWED_CHAT_IDS = [int(x.strip()) for x in CHAT_IDS_STR.split(",") if x.strip()]
DEFAULT_CHAT_ID = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else 0
ALLOWED_USERS = [5228681344, 7620086223, 1422286970]
FUND_MANAGER_USER_ID = 5228681344
SPECIAL_USER_ID = []

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

TZ = ZoneInfo("Asia/Omsk")

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
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