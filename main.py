#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KYPTEAM — Telegram ariza (recruitment) boti. Bitta fayl: main.py
(bot + foydalanuvchi oqimi + admin panel).

Talablar:  pip install "python-telegram-bot>=22.7"  (style maydoni 22.7+ da)
Sozlash:   BOT_TOKEN va ADMIN_IDS ni muhit o'zgaruvchisi yoki .env faylida bering.
Ishga tushirish:  python main.py
Render.com: Web Service sifatida ishlaydi — $PORT berilsa, health server
            (/, /health) avtomatik yoqiladi.

Tugmalar:
  * Asosiy tugmalar (menyu, ariza bosqichlari) — klaviatura o'rnida (ReplyKeyboard), rangli.
  * Chat ichida faqat yordamchi (inline) tugmalar: variant tanlash, test, tasdiqlash, admin amallari.
  * Ranglar Telegram Bot API 9.4 "style" maydoni orqali: success=yashil, danger=qizil, primary=ko'k.
"""

import asyncio
import csv
import html
import io
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# ----------------------------------------------------------------------------
# SOZLAMALAR
# ----------------------------------------------------------------------------


def _load_dotenv(path=".env"):
    """Oddiy .env o'qigich (qo'shimcha kutubxonasiz)."""
    full = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(full):
        return
    with open(full, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_IDS = {1833396464}
DB_PATH = os.environ.get("DB_PATH", "kypteam.db")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "180"))

# Qabul qilinganlarga yuboriladigan guruh havolasi.
GROUP_INVITE_LINK = os.environ.get("GROUP_INVITE_LINK", "https://t.me/+qqpyFJBhe6k3ZWJi").strip()
# Ixtiyoriy: bot guruhda admin bo'lsa, har bir a'zo uchun bir martalik havola yaratiladi.
_RAW_GROUP = os.environ.get("GROUP_CHAT_ID", "").strip()
GROUP_CHAT_ID = int(_RAW_GROUP) if re.fullmatch(r"-?\d+", _RAW_GROUP) else _RAW_GROUP
# Avtomatik tahlil o'tish foizi (0-100).
AUTO_ACCEPT_MIN = max(0, min(100, int(os.environ.get("AUTO_ACCEPT_MIN", "55"))))
# Har bir test savoliga beriladigan vaqt (soniya) — AI ga ko'chirib ulgurish qiyin bo'lsin.
QUIZ_TIME_SECONDS = max(20, int(os.environ.get("QUIZ_TIME_SECONDS", "60")))

CONSENT_VERSION = "v1"
QUIZ_VERSION = "v2"

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
# httpx URL ichida bot tokenini yozib yuboradi — o'chirib qo'yamiz.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("kypteam")

HTML = ParseMode.HTML
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
E = html.escape

# Tugma ranglari (Bot API 9.4)
GREEN, RED, BLUE = "success", "danger", "primary"


def kb(text, style=None, **kw):
    """Klaviatura (pastdagi) tugmasi, rangli."""
    return KeyboardButton(text, style=style, **kw)


def ib(text, data, style=None):
    """Chat ichidagi yordamchi (inline) tugma, rangli."""
    return InlineKeyboardButton(text, callback_data=data, style=style)


def rk(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def ik(rows):
    return InlineKeyboardMarkup(rows)


# ----------------------------------------------------------------------------
# MATNLAR (o'zbek, lotin)
# ----------------------------------------------------------------------------

B_APPLY = "📝 Ariza topshirish"
B_ABOUT = "👥 Jamoa haqida"
B_RULES = "📜 Qoidalar"
B_PRIVACY = "🔒 Maxfiylik"
B_HELP = "❓ Yordam"
B_STATUS = "📋 Ariza holati"
B_WITHDRAW = "↩️ Arizani qaytarib olish"
B_DELETE = "🗑 Ma‘lumotlarimni o‘chirish"
B_CORRECT = "✏️ Ma‘lumotni tuzatish"
B_NOTIFY = "🔔 Bildirishnomalar"
B_ADMIN = "🛠 Admin panel"
B_HOME = "🏠 Asosiy menyu"
B_JOIN = "🚀 Guruhga qo‘shilish"
B_CHAT = "💬 Foydalanuvchilar bilan bog‘lanish"
B_CHAT_END = "🛑 Chatni tugatish"

B_AGREE = "✅ Roziman va davom etaman"
B_DISAGREE = "❌ Rozimasman"
B_CANCEL = "🚫 Arizani bekor qilish"
B_BACK = "⬅️ Orqaga"
B_SKIP = "⏭ O‘tkazib yuborish"
B_RULES_OK = "✅ Qoidalarga roziman"
B_SHARE = "📱 Kontaktni ulashish"
B_QUIZ_GO = "🧠 Testni boshlash"
B_QUIZ_NO = "⏭ Testsiz davom etish"
B_QUIZ_STOP = "⏹ Testni to‘xtatish"
B_SUBMIT = "📤 Arizani yuborish"

B_A_NEW = "📥 Yangi arizalar"
B_A_STATS = "📊 Statistika"
B_A_SEARCH = "🔎 Ariza qidirish"
B_A_REQ = "🗂 Maxfiylik so‘rovlari"
B_A_APPS = "🔄 Qabulni ochish/yopish"
B_A_MAINT = "🛠 Texnik rejim"
B_A_EXPORT = "📤 CSV eksport"

WELCOME = (
    "🛡 <b>KYPTEAM</b> ga xush kelibsiz!\n\n"
    "KYPTEAM — kiberxavfsizlikni o‘rganuvchi jamoa. Biz <b>qonuniy va ruxsat "
    "berilgan muhitlarda</b> amaliyot qilamiz, jamoa bo‘lib o‘rganamiz va "
    "zaifliklar haqida mas‘uliyatli tarzda xabar beramiz.\n\n"
    "Ariza topshirish — a‘zolikka kafolat emas: arizalarni jamoa ko‘rib chiqadi.\n\n"
    "Pastdagi tugmalardan birini tanlang 👇"
)

ABOUT = (
    "👥 <b>Jamoa haqida</b>\n\n"
    "• Kiberxavfsizlik asoslarini birga o‘rganamiz\n"
    "• Faqat o‘quv laboratoriyalari, CTF va o‘z qurilmalarimizda amaliyot qilamiz\n"
    "• Tajriba almashamiz va bir-birimizga yordam beramiz\n"
    "• Zaiflik topsak, egasiga mas‘uliyatli tarzda xabar beramiz\n\n"
    "Boshlovchilar ham xush kelibsiz."
)

RULES_TEXT = (
    "📜 <b>Jamoa qoidalari</b>\n\n"
    "1. Faqat qonuniy va ruxsat berilgan muhitlarda (o‘quv laboratoriyalar, CTF, "
    "o‘z qurilmangiz) amaliyot qiling.\n"
    "2. Boshqalarning tizimi, akkaunti yoki ma‘lumotiga ruxsatsiz kirmang.\n"
    "3. Fishing, zararli dastur, parol o‘g‘irlash va yashirin kuzatuv vositalari "
    "yaratilmaydi va tarqatilmaydi.\n"
    "4. Zaiflik topsangiz — egasiga mas‘uliyatli tarzda xabar bering.\n"
    "5. Hurmat va jamoaviy ishlash: boshqalarning shaxsiy ma‘lumotini ulashmang.\n"
    "6. Parol, tasdiqlash kodi, token kabi sirlarni hech kim bilan (adminlar bilan ham) "
    "ulashmang.\n\n"
    "<i>Yosh siyosati: 16 yoshdan kichik arizalar qabul qilinmaydi.</i>"
)


def privacy_text():
    return (
        "🔒 <b>Maxfiylik va rozilik</b>\n\n"
        "<b>Qanday ma‘lumot so‘raladi va nega:</b> ism, tajriba, qiziqishlar va "
        "motivatsiya — arizangizni baholash uchun. Yosh oralig‘i, shahar/viloyat, "
        "ommaviy profil havolalari, aloqa usuli, maqsad va bo‘sh vaqt — "
        "<b>ixtiyoriy</b>, “O‘tkazib yuborish” mumkin.\n\n"
        "<b>Kim ko‘radi:</b> faqat vakolatli ko‘rib chiquvchilar. Ma‘lumotlar "
        "hech qachon ommaviy guruh yoki kanalga yuborilmaydi.\n\n"
        "<b>Chat:</b> jamoa siz bilan bog‘lansa, suhbat shu bot ichida ochiladi. "
        "Suhbat yozishmalari faqat siz va vakolatli adminlar uchun ko‘rinadi; "
        "ma‘lumotlaringizni o‘chirsangiz, chat tarixi ham o‘chiriladi.\n\n"
        f"<b>Saqlash muddati:</b> yakunlangan (rad etilgan, qaytarib olingan, arxivlangan) "
        f"arizalar {RETENTION_DAYS} kundan keyin, tugallanmagan qoralamalar esa 30 kundan "
        "keyin avtomatik o‘chiriladi.\n\n"
        "<b>Tuzatish / o‘chirish:</b> “" + B_CORRECT + "” va “" + B_DELETE + "” "
        "tugmalari orqali istalgan vaqtda so‘rash mumkin. O‘chirish darhol bajariladi.\n\n"
        "⚠️ <b>Hech qachon</b> parol, tasdiqlash (SMS/2FA) kodi, tiklash kodi, cookie, "
        "API kalit yoki tokenlarni yubormang — biz ularni so‘ramaymiz.\n"
        "Telefon raqami faqat Telegramning rasmiy “kontakt ulashish” tugmasi orqali va "
        "faqat xohlasangiz so‘raladi. Aniq manzil yoki joylashuv so‘ralmaydi."
    )


HELP_TEXT = (
    "❓ <b>Yordam</b>\n\n"
    "/start — bosh menyu\n"
    "/status — ariza holati\n"
    "/privacy — maxfiylik siyosati\n"
    "/cancel — joriy amalni bekor qilish\n"
    "/help — shu xabar\n\n"
    "Ariza bosqichlarida pastdagi “" + B_BACK + "”, “" + B_SKIP + "” va “" + B_CANCEL + "” "
    "tugmalaridan foydalaning. Bot to‘xtab qolsa, /start bosing — arizangiz saqlanib qoladi."
)

STATUS_UZ = {
    "draft": "Qoralama",
    "submitted": "Yuborildi",
    "review": "Ko‘rib chiqilmoqda",
    "need_info": "Qo‘shimcha ma‘lumot kerak",
    "accepted": "Qabul qilindi",
    "waitlisted": "Kutish ro‘yxatida",
    "rejected": "Qabul qilinmadi",
    "withdrawn": "Qaytarib olingan",
    "archived": "Arxivlangan",
}

STATUS_DESC = {
    "draft": "Ariza hali yuborilmagan. Davom ettirish uchun “" + B_APPLY + "” ni bosing.",
    "submitted": "Arizangiz qabul qilindi va jamoa ko‘rib chiqishini kutmoqda.",
    "review": "Arizangiz hozir ko‘rib chiqilmoqda.",
    "need_info": "Jamoa qo‘shimcha ma‘lumot so‘radi. Arizani yangilab qayta yuborishingiz mumkin.",
    "accepted": "Tabriklaymiz, arizangiz qabul qilindi!",
    "waitlisted": "Arizangiz kutish ro‘yxatida. Joy bo‘shasa, siz bilan bog‘lanamiz.",
    "rejected": "Bu safar arizangiz qabul qilinmadi. Keyinroq qayta urinib ko‘rishingiz mumkin.",
    "withdrawn": "Siz arizani qaytarib olgansiz.",
    "archived": "Ariza arxivlangan.",
}

NOTIFY_TEXT = {
    "review": "🔎 <b>{ref}</b> raqamli arizangiz ko‘rib chiqilmoqda.",
    "need_info": (
        "ℹ️ <b>{ref}</b> arizangiz bo‘yicha qo‘shimcha ma‘lumot kerak:\n\n{reason}\n\n"
        "“" + B_STATUS + "” bo‘limida arizani yangilab, qayta yuborishingiz mumkin."
    ),
    "accepted": (
        "🎉 <b>Tabriklaymiz!</b>\n\n"
        "<b>{ref}</b> arizangiz avtomatik tahlildan muvaffaqiyatli o‘tdi va <b>qabul qilindi</b>.\n\n"
        "Endi siz KYPTEAM guruhiga qo‘shilishingiz mumkin. Pastdagi "
        "“🚀 Guruhga qo‘shilish” tugmasini bosing — havola arizangiz tasdiqlangani uchun yuborildi.\n\n"
        "Guruhga kirgach, avval “" + B_RULES + "” bo‘limini o‘qib chiqing va o‘zingizni "
        "tanishtiring. Xush kelibsiz! 🛡"
    ),
    "waitlisted": (
        "🕓 <b>{ref}</b> arizangiz kutish ro‘yxatiga qo‘yildi. Qiziqishingiz uchun rahmat — "
        "imkoniyat bo‘lishi bilan sizga xabar beramiz."
    ),
    "rejected": (
        "Arizangiz uchun rahmat! 🙌\n\n"
        "Afsuski <b>{ref}</b> arizasi avtomatik tahlil natijasiga ko‘ra bu safar "
        "<b>qabul qilinmadi</b>, shu sababli guruhga qo‘shilish havolasi yuborilmaydi.\n\n"
        "Bu — siz haqingizdagi yakuniy xulosa emas. Quyidagilarni yaxshilab, qayta urinib ko‘ring:\n"
        "• motivatsiyani aniqroq va batafsil yozing;\n"
        "• qiziqishlaringizni ko‘proq belgilang;\n"
        "• testni oxirigacha yeching;\n"
        "• tajribangizni ochiq yozing.\n\n"
        "O‘rganishda davom eting — birozdan keyin yana ariza topshirishingiz mumkin! 💪"
    ),
}

# ---- bot ichidagi chat (admin ↔ foydalanuvchi) matnlari ----
CHAT_OPEN_FOR_USER = (
    "💬 <b>Chat ochildi!</b>\n\n"
    "KYPTEAM jamoasi siz bilan bog‘landi. Savolingiz bo‘lsa — shu yerga yozishingiz mumkin.\n\n"
    "✍️ Matn, 🖼 rasm, 🎬 video, 📎 fayl yoki 🎙 ovozli xabar yuborsangiz ham yetib boradi. "
    "Javobni ham shu chatda olasiz.\n\n"
    "<i>Suhbat tugasa, pastdagi “" + B_CHAT_END + "” tugmasini bosing.</i>"
)
CHAT_OPEN_FOR_ADMIN = (
    "💬 <b>Chat ochildi</b>\n\n"
    "👤 {who}\n🆔 <code>{tg_id}</code>\n📄 Ariza: {ref}\n\n"
    "Endi yozganlaringiz — matn, rasm, video, fayl yoki ovoz — to‘g‘ridan-to‘g‘ri "
    "foydalanuvchiga boradi. Tugatish uchun pastdagi “" + B_CHAT_END + "” tugmasini bosing."
)
CHAT_CLOSED_FOR_USER = (
    "✅ <b>Chat tugatildi</b>\n\n"
    "Suhbat uchun rahmat! Savollaringiz bo‘lsa, istalgan vaqtda yana yozishingiz mumkin — "
    "jamoa imkon boricha javob beradi.\n\n"
    "Ariza va guruhga qo‘shilish masalasida “" + B_STATUS + "” bo‘limi yordam beradi."
)
CHAT_CLOSED_FOR_ADMIN = "✅ <b>Chat tugatildi</b> · {who}"
CHAT_NO_OPEN = "💬 Hozir ochiq chat yo‘q."
CHAT_ALREADY = "💬 Bu foydalanuvchi bilan chat allaqachon ochiq — davom eting."
CHAT_NO_USERS = "👥 Hozircha botdan foydalangan foydalanuvchi yo‘q."
CHAT_RELAY_FAIL = "⚠️ Xabar yetib bormadi. Birozdan keyin qayta urinib ko‘ring."

# ---- ariza maydonlari ----
STEPS = [
    "name", "age", "city", "insta", "link", "contact",
    "exp", "interests", "motivation", "goal", "avail", "rules",
]
OPTIONAL = {"age", "city", "insta", "link", "contact", "goal", "avail"}

AGES = ["16 yoshdan kichik", "16–17", "18–24", "25–34", "35+"]
EXPERIENCE = [
    "Hali boshlamaganman",
    "Boshlang‘ich daraja",
    "Linux va terminal bilan tanishman",
    "Tarmoq asoslarini bilaman",
    "Dasturlashni bilaman",
    "CTF yoki laboratoriyalarda qatnashganman",
    "Boshqa",
]
INTERESTS = [
    "Linux va buyruq qatori asoslari",
    "Tarmoq asoslari",
    "Python / dasturlash",
    "Veb xavfsizlik asoslari",
    "Raqamli kriminalistika asoslari",
    "Xavfsiz kod yozish",
    "CTF va qonuniy amaliy laboratoriyalar",
    "Hujjatlashtirish va tadqiqot",
    "Dizayn / kontent / jamoa yordami",
    "Hali aniq emas, o‘rganyapman",
]
GOALS = [
    "Linux va tarmoq asoslarini o‘rganish",
    "Veb xavfsizlik asoslari",
    "CTF va laboratoriyalarda ishtirok etish",
    "Dasturlash va avtomatlashtirish",
    "Jamoada ishlash va tajriba almashish",
    "Boshqa",
]
AVAIL = ["Haftasiga 1–3 soat", "Haftasiga 4–7 soat", "Haftasiga 8+ soat", "Hozircha aniq emas"]

CHOICES = {  # prefiks: (bosqich, kalit, variantlar)
    "ag": ("age", "age", AGES),
    "ex": ("exp", "exp", EXPERIENCE),
    "go": ("goal", "goal", GOALS),
    "va": ("avail", "avail", AVAIL),  # "av" admin ko‘rish prefiksi bilan to‘qnashmasligi uchun
}

SECTION_LABELS = [  # xulosadagi "Tahrirlash" tugmalari
    ("name", "Ism"), ("age", "Yosh"), ("city", "Shahar"), ("insta", "Instagram"),
    ("link", "Havola"), ("contact", "Aloqa"), ("exp", "Tajriba"),
    ("interests", "Qiziqishlar"), ("motivation", "Motivatsiya"),
    ("goal", "Maqsad"), ("avail", "Vaqt"),
]

# ---- test savollari (versiya: QUIZ_VERSION) ----
# Bu testda "to'g'ri/noto'g'ri" javob yo'q: har bir variant moslik balliga (0-2) ega.
# Savollar shaxsiy tajriba va odatlarga asoslangan, har biriga vaqt chegarasi bor
# (QUIZ_TIME_SECONDS), savol xabari esa himoyalangan (protect_content) — nusxalab
# boshqa joyga (masalan, AI ga) tashlash qiyin bo'lsin.
QUIZ = [
    {
        "cat": "Vaziyat", "q": "Guruhda sizga notanish mavzu berildi, muddat esa qisqa. Birinchi qadamingiz qanday bo‘ladi?",
        "o": [
            "Mavzuni bo‘laklarga bo‘lib, eng muhim joyidan boshlayman; kerak bo‘lsa so‘rayman",
            "Kimdir tushuntirib berishini kutaman",
            "Muddatni uzaytirishni so‘rayman",
            "Mavzuni osonrog‘iga almashtiraman",
        ], "w": [2, 1, 1, 0],
        "e": "Notanish mavzuni bo‘laklash va savol berish — eng tez o‘rganish yo‘li.",
    },
    {
        "cat": "Halollik", "q": "Yangi mavzuni o‘rganishda sizda ko‘proq qaysi holat bo‘ladi?",
        "o": [
            "Ba’zan tez zerikaman, lekin mavzu qiziqarli bo‘lsa qaytaman",
            "Har doim rejam bo‘yicha oxirigacha boraman",
            "Odatda boshlashga qiynalaman, keyin ochilaman",
            "O‘rganishni boshqalarga qoldiraman",
        ], "w": [2, 1, 1, 0],
        "e": "O‘z odatini ochiq aytish — jamoada ishlash uchun muhim belgi.",
    },
    {
        "cat": "Jamoa", "q": "Hamkor sizga va’da bergan vazifani topshirmadi, muddat yaqin. Nima qilasiz?",
        "o": [
            "Holatni aniqlab, qolgan qismini o‘zim yetkazishga harakat qilaman va yetakchini xabardor qilaman",
            "O‘zim hammasini qilaman, hech kimga aytmayman",
            "Unga xafa bo‘lib, ishni to‘xtataman",
            "Muddat o‘tishini kutaman",
        ], "w": [2, 1, 0, 0],
        "e": "Muammoni yashirmaslik va jamoani xabardor qilish — ishonchni saqlaydi.",
    },
    {
        "cat": "Tanqid", "q": "Ishingizda xato topilganda odatda qanday munosabat bildirasiz?",
        "o": [
            "Tushuntirishni so‘rab, xatoni tuzataman",
            "Avval xafa bo‘laman, keyin o‘ylab ko‘raman",
            "Xatoni inkor qilaman",
            "Bahslashib, mavzuni o‘zgartiraman",
        ], "w": [2, 1, 0, 0],
        "e": "Xatoni tan olish va tuzatish — texnik jamoada eng qadrlanadigan sifat.",
    },
    {
        "cat": "Raqamli odob", "q": "Tanishingiz begona odamlarning ma’lumotlari bor faylni “ulashishni” taklif qildi.",
        "o": [
            "Rad etaman, faylni ochmayman va bu haqda jamoadagilarni ogohlantiraman",
            "Rad etaman, shunchaki e’tiborsiz qoldiraman",
            "Qiziqish uchun ko‘rib chiqaman",
            "Olib, boshqalarga ham yuboraman",
        ], "w": [2, 1, 0, 0],
        "e": "Begona ma’lumotni ko‘rmaslik va jamoada ogohlantirish — xavfsiz xatti-harakat.",
    },
    {
        "cat": "Qiyinchilik", "q": "Murakkab topshiriqda 3 soat urindingiz, natija yo‘q. Keyingi qadamingiz?",
        "o": [
            "To‘xtab, boshqa yondashuvni sinab ko‘raman yoki birovdan maslahat so‘rayman",
            "Yana bir necha soat shu yo‘l bilan davom etaman",
            "Tashlab, boshqa ishga o‘taman",
            "Tayyor javobni ko‘chirib qo‘yaman",
        ], "w": [2, 1, 0, 0],
        "e": "Yondashuvni almashtirish va yordam so‘rash — vaqtni tejaydigan odat.",
    },
    {
        "cat": "Motivatsiya", "q": "KYPTEAM sizga nima berishini eng aniq qaysi fikr ifodalaydi?",
        "o": [
            "Birgalikda o‘rganish muhiti, fikr almashish va o‘z ustimda ishlash",
            "Yangi tanishlar va guruh nomi",
            "Tezda “xaker” bo‘lib olish",
            "Faqat guruhdagi tayyor fayllar kerak",
        ], "w": [2, 1, 0, 0],
        "e": "Barqaror o‘rganish — qisqa muddatli qiziqishdan ko‘ra mustahkamroq.",
    },
    {
        "cat": "Mas’uliyat", "q": "Guruhda qoidani bilmasdan xato qildingiz. Nima qilasiz?",
        "o": [
            "O‘zim aytaman, kechirim so‘rayman va qoidani o‘rganaman",
            "Xato sezilmasa, jim turaman",
            "Boshqalarga ham shunday qilishni maslahat beraman",
            "Guruhdan chiqib ketaman",
        ], "w": [2, 0, 0, 1],
        "e": "Ochiq tan olish — jamoada ishonchni tez tiklaydi.",
    },
    {
        "cat": "Vaqt", "q": "Rejada bo‘lmagan ish chiqib qoldi va vaqtingiz yetmayapti. Qanday yo‘l tutasiz?",
        "o": [
            "Muhimligi bo‘yicha tartiblab, kerak bo‘lsa yordam so‘rayman",
            "Hammasini birdan qilishga urinaman",
            "Hech kimga aytmay kechiktiraman",
            "Ishni butunlay tashlab qo‘yaman",
        ], "w": [2, 1, 0, 0],
        "e": "Tartiblash va yordam so‘rash — muddatni saqlashning eng ishonchli yo‘li.",
    },
    {
        "cat": "Halollik", "q": "Testda bilmagan savolingizga javob berish kerak bo‘lsa?",
        "o": [
            "Bilmaganimni tan olaman va keyin o‘rganaman",
            "Taxmin qilib belgilayman, bu ham normal",
            "Boshqadan javobni so‘rayman",
            "Javobni internetdan izlayman",
        ], "w": [2, 1, 0, 0],
        "e": "Bilmaganini tan olish — o‘rganishning birinchi qadami.",
    },
]

# Har bir savolda to‘planadigan maksimal moslik balli.
QUIZ_MAX_PER_QUESTION = 2

LETTERS = "ABCD"

# ----------------------------------------------------------------------------
# MA'LUMOTLAR BAZASI (SQLite, parametrli so'rovlar)
# ----------------------------------------------------------------------------

conn = None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_init():
    global conn
    # DB_PATH diskdagi papkada bo‘lishi mumkin (masalan /var/data/kypteam.db) —
    # papka yo‘q bo‘lsa yaratamiz, aks holda SQLite ochilmaydi.
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            tg_id INTEGER PRIMARY KEY, username TEXT, name TEXT,
            notify INTEGER DEFAULT 1, state TEXT DEFAULT '',
            created_at TEXT, last_seen TEXT);
        CREATE TABLE IF NOT EXISTS apps(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, tg_id INTEGER NOT NULL,
            status TEXT NOT NULL, prev_status TEXT, step TEXT, editing INTEGER DEFAULT 0,
            consent_at TEXT, consent_ver TEXT, data TEXT DEFAULT '{}',
            quiz TEXT, quiz_version TEXT, score INTEGER, total INTEGER,
            created_at TEXT, submitted_at TEXT, updated_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_active_app ON apps(tg_id)
            WHERE status NOT IN ('withdrawn','archived','rejected');
        CREATE INDEX IF NOT EXISTS ix_apps_status ON apps(status);
        CREATE TABLE IF NOT EXISTS status_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, app_id INTEGER NOT NULL,
            status TEXT, actor TEXT, reason TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, app_id INTEGER NOT NULL,
            admin_id INTEGER, note TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS privacy_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, kind TEXT,
            text TEXT, status TEXT DEFAULT 'open', created_at TEXT, done_at TEXT);
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT,
            target TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS notif_log(
            log_id INTEGER PRIMARY KEY, app_id INTEGER, ok INTEGER, error TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', opened_by INTEGER,
            created_at TEXT, closed_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_open ON chats(tg_id) WHERE status='open';
        CREATE TABLE IF NOT EXISTS chat_msgs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            from_id INTEGER, text TEXT, at TEXT);
        CREATE INDEX IF NOT EXISTS ix_chat_msgs ON chat_msgs(chat_id);
        """
    )
    for k, v in (("apps_open", "1"), ("maintenance", "0")):
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    # Eski bazalarga yangi ustunlarni qo'shamiz (avtomatik tahlil natijasi).
    _add_column("apps", "auto_score", "INTEGER")
    _add_column("apps", "auto_note", "TEXT")


def _add_column(table, name, ddl):
    cols = {r["name"] for r in qa(f"PRAGMA table_info({table})")}
    if name not in cols:
        ex(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def q1(sql, args=()):
    return conn.execute(sql, args).fetchone()


def qa(sql, args=()):
    return conn.execute(sql, args).fetchall()


def ex(sql, args=()):
    return conn.execute(sql, args)


def setting(key):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else ""


def set_setting(key, value):
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def audit(actor, action, target=""):
    ex("INSERT INTO audit(actor,action,target,at) VALUES(?,?,?,?)", (str(actor), action, str(target), now()))


def jload(s, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else {})
    except (ValueError, TypeError):
        return default if default is not None else {}


def upsert_user(update: Update):
    u = update.effective_user
    ts = now()
    name = (u.full_name or "")[:80]
    ex(
        """INSERT INTO users(tg_id,username,name,created_at,last_seen) VALUES(?,?,?,?,?)
           ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,
           name=excluded.name, last_seen=excluded.last_seen""",
        (u.id, u.username, name, ts, ts),
    )


def get_state(uid):
    r = q1("SELECT state FROM users WHERE tg_id=?", (uid,))
    return r["state"] if r and r["state"] else ""


def set_state(uid, state=""):
    ex("UPDATE users SET state=? WHERE tg_id=?", (state, uid))


def active_app(uid):
    return q1(
        "SELECT * FROM apps WHERE tg_id=? AND status NOT IN ('withdrawn','archived','rejected')",
        (uid,),
    )


def latest_app(uid):
    return q1("SELECT * FROM apps WHERE tg_id=? ORDER BY id DESC LIMIT 1", (uid,))


def app_by_id(app_id):
    return q1("SELECT * FROM apps WHERE id=?", (app_id,))


def draft_app(uid):
    return q1("SELECT * FROM apps WHERE tg_id=? AND status='draft'", (uid,))


def new_ref():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        ref = "KYP-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not q1("SELECT 1 FROM apps WHERE ref=?", (ref,)):
            return ref


def save_data(app_id, data):
    ex("UPDATE apps SET data=?, updated_at=? WHERE id=?", (json.dumps(data, ensure_ascii=False), now(), app_id))


def log_status(app_id, status, actor, reason=""):
    cur = ex(
        "INSERT INTO status_log(app_id,status,actor,reason,at) VALUES(?,?,?,?,?)",
        (app_id, status, str(actor), reason or "", now()),
    )
    return cur.lastrowid


def purge_app(app_id):
    logs = [r["id"] for r in qa("SELECT id FROM status_log WHERE app_id=?", (app_id,))]
    for lid in logs:
        ex("DELETE FROM notif_log WHERE log_id=?", (lid,))
    ex("DELETE FROM status_log WHERE app_id=?", (app_id,))
    ex("DELETE FROM notes WHERE app_id=?", (app_id,))
    ex("DELETE FROM apps WHERE id=?", (app_id,))


def purge_chats(uid):
    for r in qa("SELECT id FROM chats WHERE tg_id=?", (uid,)):
        ex("DELETE FROM chat_msgs WHERE chat_id=?", (r["id"],))
    ex("DELETE FROM chats WHERE tg_id=?", (uid,))


def purge_user(uid):
    for r in qa("SELECT id FROM apps WHERE tg_id=?", (uid,)):
        purge_app(r["id"])
    purge_chats(uid)
    ex("DELETE FROM privacy_requests WHERE tg_id=?", (uid,))
    ex("DELETE FROM users WHERE tg_id=?", (uid,))


# ----------------------------------------------------------------------------
# YORDAMCHI FUNKSIYALAR
# ----------------------------------------------------------------------------

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOKEN = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")
_PASS = re.compile(r"(parol|password|пароль)\s*[:=]", re.I)
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_URL = re.compile(r"^https?://[^\s<>\"']{3,200}$", re.I)
_IGUSER = re.compile(r"^@?([A-Za-z0-9._]{1,30})$")
_IGURL = re.compile(r"^(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?(?:\?.*)?$", re.I)


def clean(text, maxlen, multiline=False):
    text = _CTRL.sub("", text or "")
    text = re.sub(r"<[^>]*>", "", text).replace("<", "").replace(">", "")
    if multiline:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.strip()[:maxlen]


def looks_secret(text):
    return bool(_TOKEN.search(text or "") or _PASS.search(text or ""))


def is_admin(uid):
    return uid in ADMIN_IDS


_hits = defaultdict(lambda: deque(maxlen=120))
_warned = {}


def rate_limited(uid, limit=12, window=10):
    t = time.monotonic()
    d = _hits[uid]
    d.append(t)
    return len([x for x in d if t - x <= window]) > limit


def should_warn(uid, window=10):
    """Cheklov haqida ogohlantirishni foydalanuvchiga har 10 soniyada bir marta yuborish."""
    t = time.monotonic()
    if t - _warned.get(uid, 0.0) < window:
        return False
    _warned[uid] = t
    return True


async def safe_send(ctx, chat_id, text, markup=None, retries=2, protect=False):
    """(ok, error) qaytaradi. Bloklangan bot va Telegram xatolarini xotirjam ushlaydi.

    protect=True bo'lsa xabar himoyalanadi: uni boshqa chatga forward qilib yoki
    saqlab (nusxalab) bo'lmaydi. Skrinshotni Telegram bot API to'sa olmaydi,
    shuning uchun savollar yana vaqt chegarasi bilan ham qo'riqlanadi.
    """
    for attempt in range(retries + 1):
        try:
            await ctx.bot.send_message(
                chat_id, text, parse_mode=HTML, reply_markup=markup,
                link_preview_options=NO_PREVIEW, protect_content=protect,
            )
            return True, ""
        except RetryAfter as e:
            await asyncio.sleep(min(e.retry_after, 10) + 0.5)
        except Forbidden:
            return False, "blocked"
        except BadRequest as e:
            return False, "bad_request:" + str(e)[:60]
        except NetworkError:
            await asyncio.sleep(1 + attempt)
        except TelegramError as e:
            return False, type(e).__name__
    return False, "retry_exhausted"


async def send(ctx, chat_id, text, markup=None, protect=False):
    ok, _ = await safe_send(ctx, chat_id, text, markup, protect=protect)
    return ok


def menu_kb(uid):
    rows = []
    app = latest_app(uid)
    if app and app["status"] == "accepted":
        rows.append([kb(B_JOIN, GREEN)])
    rows += [
        [kb(B_APPLY, GREEN)],
        [kb(B_STATUS, BLUE), kb(B_ABOUT, BLUE)],
        [kb(B_RULES, BLUE), kb(B_PRIVACY, BLUE)],
        [kb(B_HELP, BLUE), kb(B_NOTIFY, BLUE)],
        [kb(B_CORRECT, BLUE), kb(B_WITHDRAW, RED)],
        [kb(B_DELETE, RED)],
    ]
    if is_admin(uid):
        rows.append([kb(B_ADMIN, RED)])
    return rk(rows)


def admin_kb():
    return rk([
        [kb(B_A_NEW, GREEN), kb(B_A_STATS, BLUE)],
        [kb(B_CHAT, GREEN)],
        [kb(B_A_SEARCH, BLUE), kb(B_A_REQ, BLUE)],
        [kb(B_A_APPS, RED), kb(B_A_MAINT, RED)],
        [kb(B_A_EXPORT, BLUE)],
        [kb(B_HOME, GREEN)],
    ])


def nav_kb(optional=False, first_row=None):
    rows = []
    if first_row:
        rows.append(first_row)
    r = [kb(B_BACK, BLUE)]
    if optional:
        r.append(kb(B_SKIP, GREEN))
    rows.append(r)
    rows.append([kb(B_CANCEL, RED)])
    return rk(rows)


def quiz_level(score, total):
    p = score / total if total else 0
    if p < 0.4:
        return "moslik past"
    if p < 0.75:
        return "moslik o‘rtacha"
    return "moslik yuqori"


def fmt_dt(s):
    return s[:16].replace("T", " ") if s else "—"


# ----------------------------------------------------------------------------
# ARIZA BOSQICHLARI
# ----------------------------------------------------------------------------

async def goto(ctx, chat_id, app_id, step):
    ex("UPDATE apps SET step=?, updated_at=? WHERE id=?", (step, now(), app_id))
    app = app_by_id(app_id)
    if step == "consent":
        await show_consent(ctx, chat_id)
    elif step in STEPS:
        await render_step(ctx, chat_id, app, step)
    elif step == "quiz_offer":
        await send(
            ctx, chat_id,
            "🧠 <b>Qisqa bilim testi</b> (ixtiyoriy)\n\n"
            f"{len(QUIZ)} ta oddiy savol. Bu test faqat joylashtirish va o‘rganish uchun — "
            "a‘zolikka kafolat emas. Bilmasangiz, “Bilmayman” ni tanlash mumkin, jarima yo‘q.",
            rk([[kb(B_QUIZ_GO, GREEN)], [kb(B_QUIZ_NO, BLUE)],
                [kb(B_BACK, BLUE)], [kb(B_CANCEL, RED)]]),
        )
    elif step == "quiz":
        await send_question(ctx, chat_id, app)
    elif step == "summary":
        await show_summary(ctx, chat_id, app)


async def advance(ctx, chat_id, app_id):
    app = app_by_id(app_id)
    if app["editing"]:
        ex("UPDATE apps SET editing=0 WHERE id=?", (app_id,))
        await goto(ctx, chat_id, app_id, "summary")
        return
    i = STEPS.index(app["step"])
    nxt = STEPS[i + 1] if i + 1 < len(STEPS) else "quiz_offer"
    await goto(ctx, chat_id, app_id, nxt)


def head(step):
    opt = "ixtiyoriy" if step in OPTIONAL else "majburiy"
    return f"<b>{STEPS.index(step) + 1}/{len(STEPS)}-bosqich</b> · <i>{opt}</i>\n\n"


def choice_markup(prefix, options):
    rows, row = [], []
    for i, label in enumerate(options):
        row.append(ib(label, f"{prefix}:{i}", BLUE))
        if len(row) == 2 or len(label) > 22:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return ik(rows)


def interests_markup(selected):
    rows = [
        [ib(("✅ " if lbl in selected else "▫️ ") + lbl, f"in:{i}", GREEN if lbl in selected else BLUE)]
        for i, lbl in enumerate(INTERESTS)
    ]
    rows.append([ib("✔️ Tayyor", "ind", GREEN)])
    return ik(rows)


async def render_step(ctx, chat_id, app, step):
    d = jload(app["data"])
    h = head(step)
    opt = step in OPTIONAL
    inline = None
    kbd = nav_kb(opt)
    if step == "name":
        text = h + "Ismingiz yoki taxallusingizni yozing.\nMasalan: <i>Azizbek</i>"
        inline = ik([[ib("Telegramdagi ismimdan foydalanish", "nm:tg", BLUE)]])
    elif step == "age":
        text = h + ("Yosh oralig‘ingizni tanlang. Tug‘ilgan sana yoki hujjat so‘ralmaydi.\n"
                    "<i>Yosh siyosati: 16 yoshdan kichik arizalar qabul qilinmaydi.</i>")
        inline = choice_markup("ag", AGES)
    elif step == "city":
        text = h + "Shahar yoki viloyatingizni yozing. <b>Aniq manzil yozmang.</b>"
    elif step == "insta":
        text = h + ("Ommaviy Instagram profilingiz havolasi yoki @username ni yozing.\n"
                    "⚠️ Parol yoki tasdiqlash kodini <b>yubormang</b>.")
    elif step == "link":
        text = h + ("Boshqa ommaviy profil yoki portfolio havolasini yuboring "
                    "(GitHub, LinkedIn, shaxsiy sayt va h.k.). Havola <code>https://</code> bilan boshlansin.")
    elif step == "contact":
        text = h + ("Aloqa usulini tanlang:\n"
                    "• “" + B_SHARE + "” — Telegramning rasmiy tugmasi orqali telefon raqamingiz "
                    "ulashiladi (faqat xohlasangiz)\n"
                    "• yoki elektron pochta manzilini yozing\n"
                    "• yoki Telegram orqali yozishni tanlang (pastdagi tugma)")
        kbd = nav_kb(True, [kb(B_SHARE, GREEN, request_contact=True)])
        inline = ik([[ib("Telegram orqali yozing", "ct:dm", BLUE)]])
    elif step == "exp":
        text = h + "Kiberxavfsizlik bo‘yicha tajribangizni tanlang:"
        inline = choice_markup("ex", EXPERIENCE)
    elif step == "interests":
        text = h + "Qiziqishlaringizni tanlang (bir nechta mumkin), so‘ng “Tayyor” ni bosing:"
        inline = interests_markup(d.get("interests", []))
    elif step == "motivation":
        text = h + ("Nega KYPTEAM ga qo‘shilmoqchisiz? Qisqa yozing (20–600 belgi).\n"
                    "Parol yoki shaxsiy sirlarni yozmang.")
    elif step == "goal":
        text = h + "O‘rganish maqsadingizni tanlang yoki qisqa matn bilan yozing (200 belgigacha):"
        inline = choice_markup("go", GOALS)
    elif step == "avail":
        text = h + "Haftasiga taxminan qancha vaqt ajrata olasiz?"
        inline = choice_markup("va", AVAIL)
    else:  # rules
        text = h + RULES_TEXT + "\n\nArizani yuborish uchun qoidalarga rozilik <b>majburiy</b>."
        kbd = nav_kb(False, [kb(B_RULES_OK, GREEN)])
    await send(ctx, chat_id, text, kbd)
    if inline:
        await send(ctx, chat_id, "👇 Yordamchi tugmalar:", inline)


async def show_consent(ctx, chat_id):
    await send(
        ctx, chat_id,
        privacy_text() + "\n\nDavom etish uchun <b>aniq rozilik</b> kerak.",
        rk([[kb(B_AGREE, GREEN)], [kb(B_DISAGREE, RED)], [kb(B_CANCEL, RED)]]),
    )


def summary_text(app):
    d = jload(app["data"])

    def v(k):
        x = d.get(k)
        return E(str(x)) if x else "—"

    interests = ", ".join(E(x) for x in d.get("interests", [])) or "—"
    if app["score"] is not None and app["total"]:
        quiz = f"{app['score']}/{app['total']} — {quiz_level(app['score'], app['total'])}"
    else:
        quiz = "topshirilmagan"
    return (
        "📋 <b>Arizangiz xulosasi</b>\n\n"
        f"👤 Ism: {v('name')}\n"
        f"🎂 Yosh: {v('age')}\n"
        f"📍 Shahar: {v('city')}\n"
        f"📷 Instagram: {v('insta')}\n"
        f"🔗 Havola: {v('link')}\n"
        f"☎️ Aloqa: {v('contact')}\n"
        f"🧭 Tajriba: {v('exp')}\n"
        f"🎯 Qiziqishlar: {interests}\n"
        f"💬 Motivatsiya: {v('motivation')}\n"
        f"🏁 Maqsad: {v('goal')}\n"
        f"⏱ Vaqt: {v('avail')}\n"
        f"📜 Qoidalar: {'qabul qilingan ✅' if d.get('rules') else '—'}\n"
        f"🧠 Test: {quiz}"
    )


async def show_summary(ctx, chat_id, app):
    rows, row = [], []
    for key, label in SECTION_LABELS:
        row.append(ib("✏️ " + label, f"ed:{key}", BLUE))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([ib("🧠 Testni qayta topshirish", "ed:quiz", BLUE)])
    await send(
        ctx, chat_id,
        summary_text(app) + "\n\nTekshiring. Kerak bo‘lsa, pastdagi tugmalar bilan tahrirlang.",
        rk([[kb(B_SUBMIT, GREEN)], [kb(B_BACK, BLUE)], [kb(B_CANCEL, RED)]]),
    )
    await send(ctx, chat_id, "👇 Tahrirlash:", ik(rows))


# ---- test ----

def qtext(item, idx, total, show_timer=True):
    qd = QUIZ[item["q"]]
    opts = "\n".join(f"<b>{LETTERS[k]})</b> {E(qd['o'][p])}" for k, p in enumerate(item["p"]))
    timer = ""
    if show_timer and item.get("d"):
        left = max(0, int(item["d"] - time.time()))
        timer = f" · ⏱ {left} soniya"
    return (
        f"🧠 <b>Savol {idx + 1}/{total}</b> · <i>{E(qd['cat'])}</i>{timer}\n\n"
        f"{E(qd['q'])}\n\n{opts}\n\n"
        "<i>Bu yerda “to‘g‘ri” yoki “noto‘g‘ri” javob yo‘q — sizga yaqin variantni tanlang.</i>"
    )


def qmarkup(idx):
    return ik([
        [ib(LETTERS[k], f"q:{idx}:{k}", BLUE) for k in range(4)],
        [ib("🤷 Bilmayman", f"q:{idx}:x")],
    ])


async def send_question(ctx, chat_id, app):
    quiz = jload(app["quiz"])
    i = quiz.get("i", 0)
    items = quiz.get("items", [])
    if i >= len(items):
        await finish_quiz(ctx, chat_id, app["id"])
        return
    # Har bir savolga alohida vaqt chegarasi (savol yuborilgan paytdan boshlab).
    if items[i].get("a") is None:
        items[i]["d"] = round(time.time() + QUIZ_TIME_SECONDS, 1)
        ex("UPDATE apps SET quiz=? WHERE id=?", (json.dumps(quiz), app["id"]))
    # protect_content: savolni forward qilib yoki nusxalab bo‘lmaydi.
    await send(ctx, chat_id, qtext(items[i], i, len(items)), qmarkup(i), protect=True)


async def start_quiz(ctx, chat_id, app_id):
    items = []
    for qi in random.sample(range(len(QUIZ)), len(QUIZ)):
        items.append({
            "q": qi,
            "p": random.sample(range(4), 4),
            "a": None,
        })
    quiz = {"v": QUIZ_VERSION, "i": 0, "items": items}
    ex("UPDATE apps SET quiz=?, quiz_version=?, score=NULL, total=NULL, step='quiz', updated_at=? WHERE id=?",
       (json.dumps(quiz), QUIZ_VERSION, now(), app_id))
    await send(ctx, chat_id,
               f"🧠 <b>Test boshlandi.</b> {len(items)} ta vaziyat savoli.\n\n"
               f"⏱ Har bir savolga <b>{QUIZ_TIME_SECONDS} soniya</b> vaqt bor. "
               "Bilmagan javobni “Bilmayman” deb belgilang — bu normal.",
               rk([[kb(B_QUIZ_STOP, BLUE)], [kb(B_CANCEL, RED)]]))
    await send_question(ctx, chat_id, app_by_id(app_id))


def quiz_max(items):
    return QUIZ_MAX_PER_QUESTION * len(items)


async def finish_quiz(ctx, chat_id, app_id):
    app = app_by_id(app_id)
    quiz = jload(app["quiz"])
    items = quiz.get("items", [])
    score = 0
    for it in items:
        if it["a"] is not None and it["a"] >= 0:
            score += QUIZ[it["q"]]["w"][it["p"][it["a"]]]
    total = quiz_max(items)
    ex("UPDATE apps SET score=?, total=?, updated_at=? WHERE id=?", (score, total, now(), app_id))
    await send(ctx, chat_id,
               f"✅ Test yakunlandi: <b>{score}/{total}</b> moslik balli\n"
               f"Profil: <b>{quiz_level(score, total)}</b>\n\n"
               "Bu natija arizani avtomatik baholashda hisobga olinadi. Rahmat!")
    ex("UPDATE apps SET editing=0 WHERE id=?", (app_id,))
    await goto(ctx, chat_id, app_id, "summary")


# ----------------------------------------------------------------------------
# ARIZANI AVTOMATIK TAHLIL QILISH
# ----------------------------------------------------------------------------

MOTIV_KEYS = (
    "o'rgan", "xavfsiz", "jamoa", "linux", "tarmoq", "ctf", "laborator",
    "python", "kod", "dastur", "kitob", "amaliyot",
)
AGE_VALUE = {"16–17": 0.7, "18–24": 1.0, "25–34": 1.0, "35+": 0.9}
AVAIL_VALUE = {
    "Haftasiga 1–3 soat": 0.6,
    "Haftasiga 4–7 soat": 1.0,
    "Haftasiga 8+ soat": 1.0,
    "Hozircha aniq emas": 0.5,
}


def _motivation_value(text):
    n = len(text or "")
    if n >= 240:
        v = 1.0
    elif n >= 140:
        v = 0.8
    elif n >= 70:
        v = 0.55
    elif n >= 20:
        v = 0.25
    else:
        v = 0.0
    low = (text or "").lower().replace("‘", "'").replace("’", "'")
    hits = sum(1 for w in MOTIV_KEYS if w in low)
    return min(1.0, v + 0.05 * hits)


def analyze_application(app):
    """Arizani avtomatik baholaydi.

    Qaytaradi: (foiz, tekshiruvlar, qat'iy rad sabablari).
    Qat'iy rad — majburiy maydon yo‘qligi yoki 16 yoshdan kichik bo‘lishi.
    """
    d = jload(app["data"])
    checks = []
    hard = []

    name = (d.get("name") or "").strip()
    checks.append(("Ism", 1.0 if len(name) >= 2 else 0.0, 1))
    if len(name) < 2:
        hard.append("ism")

    age = d.get("age")
    if age == AGES[0]:
        checks.append(("Yosh", 0.0, 2))
        hard.append("yosh")
    else:
        checks.append(("Yosh", AGE_VALUE.get(age, 0.6), 2))

    checks.append(("Motivatsiya", _motivation_value(d.get("motivation")), 3))
    if len((d.get("motivation") or "").strip()) < 20:
        hard.append("motivatsiya")

    exp = d.get("exp")
    exp_value = {
        EXPERIENCE[0]: 0.3, EXPERIENCE[1]: 0.6, EXPERIENCE[2]: 0.8,
        EXPERIENCE[3]: 0.85, EXPERIENCE[4]: 0.85, EXPERIENCE[5]: 1.0,
        EXPERIENCE[6]: 0.5,
    }.get(exp, 0.0)
    checks.append(("Tajriba", exp_value, 2))
    if not exp:
        hard.append("tajriba")

    n_int = len(d.get("interests") or [])
    interests_value = 1.0 if n_int >= 3 else 0.8 if n_int == 2 else 0.5 if n_int == 1 else 0.0
    checks.append(("Qiziqishlar", interests_value, 2))
    if not n_int:
        hard.append("qiziqishlar")

    checks.append(("Maqsad", 1.0 if d.get("goal") else 0.45, 1))
    checks.append(("Vaqt", AVAIL_VALUE.get(d.get("avail"), 0.5), 1))
    checks.append(("Aloqa",
                   1.0 if (d.get("contact") or d.get("link") or d.get("insta")) else 0.4, 1))
    checks.append(("Qoidalar", 1.0 if d.get("rules") else 0.0, 1))
    if not d.get("rules"):
        hard.append("qoidalar")

    if app["score"] is not None and app["total"]:
        checks.append(("Test", min(1.0, app["score"] / app["total"]), 3))
    else:
        # Test topshirilmagan: bu ustunlik bermaydi.
        checks.append(("Test", 0.3, 3))

    weight_sum = sum(w for _label, _v, w in checks)
    got = sum(v * w for _label, v, w in checks)
    percent = int(round(got / weight_sum * 100)) if weight_sum else 0
    return percent, checks, hard


def auto_note_json(percent, checks, hard):
    return json.dumps({
        "percent": percent,
        "hard": hard,
        "checks": [[label, round(value, 2), weight] for label, value, weight in checks],
        "at": now(),
    }, ensure_ascii=False)


async def group_invite_link(ctx, tg_id):
    """Qabul qilingan a’zo uchun guruh havolasi.

    GROUP_CHAT_ID berilgan va bot guruhda admin bo‘lsa — faqat bitta a’zo uchun
    ishlaydigan bir martalik havola yaratiladi (bot o‘zi tanlab qo‘shadi).
    Aks holda oddiy taklif havolasi qaytadi.
    """
    if GROUP_CHAT_ID:
        try:
            link = await ctx.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID, member_limit=1, name=f"KYP {tg_id}",
            )
            return link.invite_link
        except TelegramError as e:
            log.warning("Bir martalik havola yaratilmadi: %s", e)
    return GROUP_INVITE_LINK


async def auto_review(ctx, app, admin_chat=None):
    """Arizani avtomatik tahlil qilib, holatni o‘zgartiradi va javob yuboradi."""
    percent, checks, hard = analyze_application(app)
    accepted = not hard and percent >= AUTO_ACCEPT_MIN
    ex("UPDATE apps SET auto_score=?, auto_note=? WHERE id=?",
       (percent, auto_note_json(percent, checks, hard), app["id"]))
    action = "acc" if accepted else "rej"
    reason = f"Avtomatik tahlil: {percent}%" + (" · qat‘iy shart bajarilmagan" if hard else "")
    ok, msg = await apply_status(ctx, "system", app["id"], action, reason)
    if not ok and admin_chat:
        await send(ctx, admin_chat, "⚠️ Avtomatik qaror qo‘llanmadi: " + msg)
    audit("system", "auto_review", f"{app['ref']}={percent}%")
    return accepted, percent, checks, hard


# ----------------------------------------------------------------------------
# FOYDALANUVCHI HANDLERLARI
# ----------------------------------------------------------------------------

async def guard(update: Update, ctx):
    """Texnik rejim va tezlik cheklovi. False => to'xtatish."""
    user = update.effective_user
    if not user:
        return False
    uid = user.id
    # Adminlar panelda tez ishlaydi — ular uchun cheklov kengroq.
    if rate_limited(uid, limit=60 if is_admin(uid) else 12):
        if update.callback_query:
            await update.callback_query.answer("Sekinroq, iltimos ⏳")
        elif update.effective_chat and should_warn(uid):
            await send(ctx, update.effective_chat.id,
                       "⏳ Juda ko‘p xabar yuborildi. Iltimos, 10 soniya kutib, qayta urinib ko‘ring.")
        return False
    if setting("maintenance") == "1" and not is_admin(uid):
        text = "🛠 Hozir texnik ishlar olib borilmoqda. Birozdan keyin qayta urinib ko‘ring."
        if update.callback_query:
            await update.callback_query.answer("Texnik ishlar", show_alert=True)
        else:
            await send(ctx, update.effective_chat.id, text)
        return False
    return True


async def cmd_start(update: Update, ctx):
    if not update.effective_chat or update.effective_chat.type != "private":
        return
    upsert_user(update)
    if not await guard(update, ctx):
        return
    uid = update.effective_user.id
    set_state(uid, "")
    text = WELCOME
    if draft_app(uid):
        text += "\n\n📌 Sizda tugallanmagan ariza bor — “" + B_APPLY + "” orqali davom ettiring."
    await send(ctx, update.effective_chat.id, text, menu_kb(uid))


async def show_home(update, ctx, note="Asosiy menyu 👇"):
    uid = update.effective_user.id
    await send(ctx, update.effective_chat.id, note, menu_kb(uid))


async def h_help(update, ctx):
    await send(ctx, update.effective_chat.id, HELP_TEXT, menu_kb(update.effective_user.id))


async def h_about(update, ctx):
    await send(ctx, update.effective_chat.id, ABOUT, menu_kb(update.effective_user.id))


async def h_rules(update, ctx):
    await send(ctx, update.effective_chat.id, RULES_TEXT, menu_kb(update.effective_user.id))


async def h_privacy(update, ctx):
    await send(ctx, update.effective_chat.id, privacy_text(), menu_kb(update.effective_user.id))


async def h_notify(update, ctx):
    uid = update.effective_user.id
    r = q1("SELECT notify FROM users WHERE tg_id=?", (uid,))
    new = 0 if (r and r["notify"]) else 1
    ex("UPDATE users SET notify=? WHERE tg_id=?", (new, uid))
    msg = ("🔔 Bildirishnomalar <b>yoqildi</b>." if new else
           "🔕 Muhim bo‘lmagan bildirishnomalar <b>o‘chirildi</b>. Ma‘lumot so‘rovlari baribir yuboriladi.")
    await send(ctx, update.effective_chat.id, msg, menu_kb(uid))


async def h_apply(update, ctx):
    uid = update.effective_user.id
    chat = update.effective_chat.id
    app = active_app(uid)
    if app is None:
        if setting("apps_open") != "1":
            await send(ctx, chat, "🔒 Hozircha arizalar qabul qilinmayapti. Keyinroq qayta urinib ko‘ring.",
                       menu_kb(uid))
            return
        try:
            ex("""INSERT INTO apps(ref,tg_id,status,step,created_at,updated_at)
                  VALUES(?,?,?,?,?,?)""", (new_ref(), uid, "draft", "consent", now(), now()))
        except sqlite3.IntegrityError:
            app = active_app(uid)
            if app is None:
                await send(ctx, chat, "⚠️ Ariza yaratishda xatolik yuz berdi. Iltimos, qayta urinib ko‘ring.",
                           menu_kb(uid))
                return
        else:
            app = draft_app(uid)
            await send(ctx, chat, "Ariza jarayoni boshlandi. Istalgan vaqtda “" + B_CANCEL + "” ni bosishingiz mumkin.")
    if app["status"] == "draft":
        if app["step"] != "consent":
            await send(ctx, chat, "↪️ Arizangiz qoldirilgan joydan davom etadi.")
        await goto(ctx, chat, app["id"], app["step"])
        return
    await show_status(update, ctx)


async def show_status(update, ctx):
    uid = update.effective_user.id
    chat = update.effective_chat.id
    app = active_app(uid) or latest_app(uid)
    if not app:
        await send(ctx, chat, "Sizda hali ariza yo‘q. “" + B_APPLY + "” tugmasi orqali boshlang.", menu_kb(uid))
        return
    text = (
        f"📋 <b>Ariza holati</b>\n\nRaqam: <b>{app['ref']}</b>\n"
        f"Holat: <b>{STATUS_UZ[app['status']]}</b>\n"
        f"Yuborilgan: {fmt_dt(app['submitted_at'])}\n\n{STATUS_DESC[app['status']]}"
    )
    rows = []
    if app["status"] in ("submitted", "review", "need_info"):
        rows.append([ib("✏️ Arizani yangilash", "up:y", BLUE)])
    if app["status"] in ("submitted", "review", "need_info", "waitlisted", "accepted"):
        rows.append([ib("↩️ Arizani qaytarib olish", "wd:ask", RED)])
    await send(ctx, chat, text, menu_kb(uid))
    if rows:
        await send(ctx, chat, "👇 Yordamchi tugmalar:", ik(rows))


async def h_withdraw(update, ctx):
    uid = update.effective_user.id
    app = active_app(uid)
    if not app or app["status"] == "draft":
        await send(ctx, update.effective_chat.id, "Qaytarib olinadigan yuborilgan ariza yo‘q.", menu_kb(uid))
        return
    await send(ctx, update.effective_chat.id, f"<b>{app['ref']}</b> arizasini qaytarib olishni tasdiqlaysizmi?",
               ik([[ib("Ha, qaytarib olaman", "wd:y", RED), ib("Yo‘q", "wd:n", GREEN)]]))


async def h_delete(update, ctx):
    await send(ctx, update.effective_chat.id,
               "🗑 Barcha ma‘lumotlaringiz (ariza, test, holat tarixi) <b>butunlay o‘chiriladi</b>. "
               "Bu amalni qaytarib bo‘lmaydi. Tasdiqlaysizmi?",
               ik([[ib("Ha, o‘chirilsin", "del:y", RED), ib("Yo‘q", "del:n", GREEN)]]))


async def h_correct(update, ctx):
    uid = update.effective_user.id
    set_state(uid, "correction")
    await send(ctx, update.effective_chat.id,
               "✏️ Qaysi ma‘lumotni tuzatish kerakligini qisqa yozing (500 belgigacha). "
               "Bekor qilish uchun /cancel.\n\n<i>Eslatma: yuborilgan arizani “Ariza holati” → "
               "“Arizani yangilash” orqali o‘zingiz ham tuzatishingiz mumkin.</i>")


async def cancel_flow(update, ctx):
    uid = update.effective_user.id
    chat = update.effective_chat.id
    if get_state(uid):
        set_state(uid, "")
        await send(ctx, chat, "Bekor qilindi.", menu_kb(uid))
        return
    app = draft_app(uid)
    if app:
        if app["prev_status"]:
            ex("UPDATE apps SET status=?, prev_status=NULL, step='done', editing=0, updated_at=? WHERE id=?",
               (app["prev_status"], now(), app["id"]))
            await send(ctx, chat, "Yangilash bekor qilindi, arizangiz avvalgi holatda qoldi.", menu_kb(uid))
        else:
            purge_app(app["id"])
            await send(ctx, chat, "🚫 Ariza bekor qilindi va qoralama o‘chirildi.", menu_kb(uid))
        return
    await send(ctx, chat, "Bekor qilinadigan jarayon yo‘q.", menu_kb(uid))


async def cmd_cancel(update, ctx):
    if update.effective_chat.type != "private":
        return
    upsert_user(update)
    if await guard(update, ctx):
        await cancel_flow(update, ctx)


async def cmd_status(update, ctx):
    if update.effective_chat.type != "private":
        return
    upsert_user(update)
    if await guard(update, ctx):
        await show_status(update, ctx)


async def cmd_privacy(update, ctx):
    if update.effective_chat.type != "private":
        return
    upsert_user(update)
    if await guard(update, ctx):
        await h_privacy(update, ctx)


async def cmd_help(update, ctx):
    if update.effective_chat.type != "private":
        return
    upsert_user(update)
    if await guard(update, ctx):
        await h_help(update, ctx)


# ---- wizard tugmalari ----

async def h_agree(update, ctx):
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = draft_app(uid)
    if not app or app["step"] != "consent":
        await show_home(update, ctx, "Avval “" + B_APPLY + "” ni bosing.")
        return
    ex("UPDATE apps SET consent_at=?, consent_ver=? WHERE id=?", (now(), CONSENT_VERSION, app["id"]))
    await goto(ctx, chat, app["id"], "name")


async def h_disagree(update, ctx):
    uid = update.effective_user.id
    app = draft_app(uid)
    if app and app["step"] == "consent":
        purge_app(app["id"])
    await send(ctx, update.effective_chat.id,
               "Tushunamiz, hech qanday ma‘lumot saqlanmadi. Fikringiz o‘zgarsa, istalgan payt qaytishingiz mumkin.",
               menu_kb(uid))


async def h_back(update, ctx):
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = draft_app(uid)
    if not app:
        await show_home(update, ctx)
        return
    step = app["step"]
    if app["editing"]:
        ex("UPDATE apps SET editing=0 WHERE id=?", (app["id"],))
        await goto(ctx, chat, app["id"], "summary")
    elif step == "consent":
        await cancel_flow(update, ctx)
    elif step == "name":
        await goto(ctx, chat, app["id"], "consent")
    elif step in STEPS:
        await goto(ctx, chat, app["id"], STEPS[STEPS.index(step) - 1])
    elif step == "quiz_offer":
        await goto(ctx, chat, app["id"], "rules")
    elif step == "quiz":
        ex("UPDATE apps SET quiz=NULL, score=NULL, total=NULL WHERE id=?", (app["id"],))
        await goto(ctx, chat, app["id"], "quiz_offer")
    elif step == "summary":
        await goto(ctx, chat, app["id"], "quiz_offer")


async def h_skip(update, ctx):
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = draft_app(uid)
    if not app:
        await show_home(update, ctx)
        return
    step = app["step"]
    if step not in OPTIONAL:
        await send(ctx, chat, "Bu savol majburiy — o‘tkazib yuborib bo‘lmaydi. Javob bering yoki “" + B_BACK + "” ni bosing.")
        return
    d = jload(app["data"])
    d.pop(step, None)
    save_data(app["id"], d)
    await advance(ctx, chat, app["id"])


async def h_rules_ok(update, ctx):
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = draft_app(uid)
    if not app or app["step"] != "rules":
        await show_home(update, ctx)
        return
    d = jload(app["data"])
    d["rules"] = True
    save_data(app["id"], d)
    await advance(ctx, chat, app["id"])


async def h_quiz_go(update, ctx):
    app = draft_app(update.effective_user.id)
    if app and app["step"] == "quiz_offer":
        await start_quiz(ctx, update.effective_chat.id, app["id"])


async def h_quiz_no(update, ctx):
    app = draft_app(update.effective_user.id)
    if app and app["step"] == "quiz_offer":
        await goto(ctx, update.effective_chat.id, app["id"], "summary")


async def h_quiz_stop(update, ctx):
    app = draft_app(update.effective_user.id)
    if app and app["step"] == "quiz":
        ex("UPDATE apps SET quiz=NULL, score=NULL, total=NULL WHERE id=?", (app["id"],))
        await send(ctx, update.effective_chat.id, "Test to‘xtatildi. Natija saqlanmadi.")
        await goto(ctx, update.effective_chat.id, app["id"], "summary")


async def h_submit(update, ctx):
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = draft_app(uid)
    if not app or app["step"] != "summary":
        await show_status(update, ctx)
        return
    d = jload(app["data"])
    missing = []
    if not d.get("name"):
        missing.append("Ism")
    if not d.get("exp"):
        missing.append("Tajriba")
    if not d.get("interests"):
        missing.append("Qiziqishlar")
    if not d.get("motivation"):
        missing.append("Motivatsiya")
    if not d.get("rules"):
        missing.append("Qoidalarga rozilik")
    if not app["consent_at"]:
        missing.append("Maxfiylik roziligi")
    if missing:
        await send(ctx, chat, "⚠️ Majburiy maydonlar to‘ldirilmagan: <b>" + ", ".join(missing) +
                   "</b>. Tahrirlash tugmalari orqali to‘ldiring.")
        return
    updated = app["prev_status"] is not None
    ts = now()
    cur = ex("""UPDATE apps SET status='submitted', prev_status=NULL, step='done', editing=0,
          submitted_at=?, updated_at=? WHERE id=? AND status='draft'""", (ts, ts, app["id"]))
    if cur.rowcount == 0:  # boshqa oqim allaqachon yuborgan
        await show_status(update, ctx)
        return
    log_status(app["id"], "submitted", uid, "Ariza yangilandi" if updated else "")
    await send(ctx, chat,
               f"📤 <b>Ariza {'yangilandi' if updated else 'yuborildi'}!</b>\n\n"
               f"Ariza raqami: <b>{app['ref']}</b>\n"
               "🤖 Hozir arizangiz avtomatik tahlil qilinadi — bir necha soniya...",
               menu_kb(uid))
    app = app_by_id(app["id"])
    accepted, percent, _checks, _hard = await auto_review(ctx, app, admin_chat=chat)
    for aid in ADMIN_IDS:
        await send(ctx, aid,
                   f"🆕 Yangi ariza: <b>{app['ref']}</b>" + (" (yangilangan)" if updated else "")
                   + f"\n🤖 Avtomatik tahlil: <b>{percent}%</b> — "
                   + ("qabul ✅" if accepted else "rad ❌"),
                   ik([[ib("👀 Ko‘rish", f"av:{app['id']}", GREEN)]]))
    await send(ctx, chat, "👇 Yordamchi tugmalar:",
               ik([[ib("📋 Ariza holatini tekshirish", "st:show", BLUE),
                    ib("↩️ Arizani qaytarib olish", "wd:ask", RED)]]))


# ---- matn kiritish ----

async def handle_step_text(update, ctx, app, text):
    uid, chat = update.effective_user.id, update.effective_chat.id
    step = app["step"]
    d = jload(app["data"])

    if looks_secret(text):
        await send(ctx, chat, "⛔ Xabaringizda parol yoki token o‘xshash narsa bor. Bunday ma‘lumotni "
                              "<b>hech qachon</b> yubormang. Iltimos, boshqa javob yozing.")
        return

    if step == "name":
        v = clean(text, 60)
        if len(v) < 2:
            await send(ctx, chat, "Ism kamida 2 belgidan iborat bo‘lsin.")
            return
        d["name"] = v
    elif step == "city":
        v = clean(text, 60)
        if len(v) < 2:
            await send(ctx, chat, "Shahar yoki viloyat nomini yozing (yoki “" + B_SKIP + "”).")
            return
        d["city"] = v
    elif step == "insta":
        t = text.strip()
        m = _IGURL.match(t) or _IGUSER.match(t)
        if not m:
            await send(ctx, chat, "Instagram havolasi yoki @username noto‘g‘ri. Masalan: <code>@kypteam</code>")
            return
        d["insta"] = "https://instagram.com/" + m.group(1)
    elif step == "link":
        t = text.strip()
        if not _URL.match(t):
            await send(ctx, chat, "Havola <code>https://</code> bilan boshlanishi va bo‘shliqsiz bo‘lishi kerak.")
            return
        d["link"] = clean(t, 200)
    elif step == "contact":
        t = text.strip()
        if not _EMAIL.match(t):
            await send(ctx, chat, "Elektron pochta noto‘g‘ri. Tugmalardan foydalaning yoki to‘g‘ri manzil yozing.")
            return
        d["contact"] = "Email: " + clean(t, 100)
    elif step == "motivation":
        v = clean(text, 600, multiline=True)
        if len(v) < 20:
            await send(ctx, chat, f"Biroz batafsilroq yozing (kamida 20 belgi, hozir {len(v)}).")
            return
        d["motivation"] = v
    elif step == "goal":
        v = clean(text, 200)
        if len(v) < 3:
            await send(ctx, chat, "Maqsadni tanlang yoki qisqa yozing.")
            return
        d["goal"] = v
    else:
        await send(ctx, chat, "Bu savolga pastdagi yordamchi tugmalar orqali javob bering 👇 "
                              "yoki “" + B_BACK + "” / “" + B_CANCEL + "” ni bosing.")
        return
    save_data(app["id"], d)
    await advance(ctx, chat, app["id"])


async def on_contact(update: Update, ctx):
    if update.effective_chat.type != "private":
        return
    upsert_user(update)
    if not await guard(update, ctx):
        return
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = draft_app(uid)
    c = update.message.contact
    if not app or app["step"] != "contact":
        row = open_chat_row(uid)
        if row:
            await user_chat_forward(update, ctx, row)
            return
        await send(ctx, chat, "Kontakt hozir kerak emas.", menu_kb(uid))
        return
    if c.user_id != uid:  # faqat o'zining kontakti
        await send(ctx, chat, "Iltimos, faqat o‘zingizning kontaktingizni ulashing (tugma orqali).")
        return
    d = jload(app["data"])
    phone = re.sub(r"[^\d+]", "", c.phone_number or "")[:20]
    d["contact"] = "Telefon: " + (phone if phone.startswith("+") else "+" + phone)
    save_data(app["id"], d)
    await advance(ctx, chat, app["id"])


async def on_other(update: Update, ctx):
    """Matn bo‘lmagan xabarlar: ochiq chatda rasm/video/fayl/ovoz bo‘lsa — uzatamiz."""
    if update.effective_chat.type != "private" or not update.message:
        return
    upsert_user(update)
    if not await guard(update, ctx):
        return
    uid = update.effective_user.id
    state = get_state(uid)
    if is_admin(uid) and state.startswith("chat:"):
        try:
            target = int(state.split(":", 1)[1])
        except ValueError:
            set_state(uid, "")
        else:
            await admin_chat_forward(update, ctx, target)
            return
    row = open_chat_row(uid)
    if row:
        await user_chat_forward(update, ctx, row)
        return
    await send(ctx, update.effective_chat.id,
               "Men faqat matn va tugmalar bilan ishlayman. Menyudan foydalaning 👇",
               menu_kb(uid))


# ----------------------------------------------------------------------------
# ADMIN QISMI (bot ichida)
# ----------------------------------------------------------------------------

async def h_admin(update, ctx):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    open_chats = q1("SELECT COUNT(*) c FROM chats WHERE status='open'")["c"]
    await send(ctx, update.effective_chat.id,
               "🛠 <b>Admin panel</b>\n\n"
               f"Qabul: <b>{'ochiq' if setting('apps_open') == '1' else 'yopiq'}</b> · "
               f"Texnik rejim: <b>{'yoqilgan' if setting('maintenance') == '1' else 'o‘chiq'}</b> · "
               f"Ochiq chatlar: <b>{open_chats}</b>",
               admin_kb())


async def cmd_admin(update, ctx):
    if update.effective_chat.type != "private":
        return
    upsert_user(update)
    await h_admin(update, ctx)


def app_row_btn(a):
    return [ib(f"{a['ref']} · {STATUS_UZ[a['status']]}", f"av:{a['id']}", BLUE)]


async def h_a_new(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    rows = qa("""SELECT * FROM apps WHERE status NOT IN ('draft','withdrawn')
                 ORDER BY COALESCE(submitted_at, updated_at) DESC LIMIT 15""")
    if not rows:
        await send(ctx, update.effective_chat.id, "📭 Hozircha yuborilgan ariza yo‘q.", admin_kb())
        return
    await send(ctx, update.effective_chat.id,
               f"📥 Oxirgi {len(rows)} ta ariza (avtomatik qaror bilan):", admin_kb())
    await send(ctx, update.effective_chat.id, "👇 Tanlang:", ik([app_row_btn(a) for a in rows]))


async def h_a_stats(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    total = q1("SELECT COUNT(*) c FROM apps WHERE status!='draft'")["c"]
    if not total:
        await send(ctx, update.effective_chat.id, "📊 Hali yuborilgan ariza yo‘q — ko‘rsatiladigan statistika yo‘q.", admin_kb())
        return
    by = {r["status"]: r["c"] for r in qa("SELECT status, COUNT(*) c FROM apps GROUP BY status")}
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    reviewed = q1("""SELECT COUNT(DISTINCT app_id) c FROM status_log
                     WHERE at>=? AND status IN ('review','accepted','waitlisted','rejected','need_info')
                     AND actor!='system'""", (week,))["c"]
    quiz_done = q1("SELECT COUNT(*) c FROM apps WHERE score IS NOT NULL")["c"]
    avg = q1("SELECT AVG(CAST(score AS REAL)/total) a FROM apps WHERE score IS NOT NULL AND total>0")["a"]
    lines = [
        "📊 <b>Statistika</b>\n",
        f"Jami yuborilgan: <b>{total}</b>",
        f"Ko‘rib chiqilishini kutmoqda: <b>{by.get('submitted', 0) + by.get('need_info', 0)}</b>",
        f"Ko‘rib chiqilmoqda: <b>{by.get('review', 0)}</b>",
        f"Shu hafta ko‘rib chiqilgan: <b>{reviewed}</b>",
        f"Qabul qilingan: <b>{by.get('accepted', 0)}</b>",
        f"Kutish ro‘yxatida: <b>{by.get('waitlisted', 0)}</b>",
        f"Rad etilgan: <b>{by.get('rejected', 0)}</b>",
        f"Test topshirganlar: <b>{quiz_done}</b>" + (f" (o‘rtacha {round(avg * 100)}%)" if avg is not None else ""),
    ]
    recent = qa("""SELECT a.ref, s.status, s.at FROM status_log s JOIN apps a ON a.id=s.app_id
                   ORDER BY s.id DESC LIMIT 5""")
    if recent:
        lines.append("\n<b>So‘nggi o‘zgarishlar:</b>")
        for r in recent:
            lines.append(f"• {r['ref']} → {STATUS_UZ.get(r['status'], r['status'])} ({fmt_dt(r['at'])})")
    await send(ctx, update.effective_chat.id, "\n".join(lines), admin_kb())


async def h_a_search(update, ctx):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    set_state(uid, "adm_search")
    await send(ctx, update.effective_chat.id,
               "🔎 Ariza raqami (KYP-...), ism, @username yoki holat nomini yozing. Bekor qilish: /cancel")


async def h_a_apps(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    new = "0" if setting("apps_open") == "1" else "1"
    set_setting("apps_open", new)
    audit(update.effective_user.id, "apps_open=" + new)
    await send(ctx, update.effective_chat.id,
               "🔓 Arizalar qabuli <b>ochildi</b>." if new == "1" else "🔒 Arizalar qabuli <b>yopildi</b>.", admin_kb())


async def h_a_maint(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    new = "0" if setting("maintenance") == "1" else "1"
    set_setting("maintenance", new)
    audit(update.effective_user.id, "maintenance=" + new)
    await send(ctx, update.effective_chat.id,
               "🛠 Texnik rejim <b>yoqildi</b> (adminlardan boshqalar uchun bot to‘xtatilgan)." if new == "1"
               else "✅ Texnik rejim <b>o‘chirildi</b>.", admin_kb())


async def h_a_export(update, ctx):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    rows = qa("SELECT ref,status,data,score,total,submitted_at FROM apps WHERE status!='draft' ORDER BY id")
    if not rows:
        await send(ctx, update.effective_chat.id, "Eksport qilinadigan ariza yo‘q.", admin_kb())
        return
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ariza", "holat", "tajriba", "test_ball", "test_jami", "yuborilgan"])
    for r in rows:
        d = jload(r["data"])
        w.writerow([r["ref"], r["status"], d.get("exp", ""), r["score"] if r["score"] is not None else "",
                    r["total"] or "", r["submitted_at"] or ""])
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    data.name = "kypteam_arizalar.csv"
    audit(uid, "csv_export", f"{len(rows)} qator")
    await send(ctx, update.effective_chat.id,
               "⚠️ Bu fayl shaxsiy ma‘lumotga bog‘liq ariza ma‘lumotlarini o‘z ichiga oladi. "
               "Uni ehtiyotkorlik bilan saqlang va ulashmang. Eksport audit jurnaliga yozildi.")
    await ctx.bot.send_document(update.effective_chat.id, data, caption="Minimal CSV hisobot")


async def h_a_req(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    rows = qa("SELECT * FROM privacy_requests WHERE status='open' ORDER BY id LIMIT 10")
    if not rows:
        await send(ctx, update.effective_chat.id, "🗂 Ochiq maxfiylik so‘rovlari yo‘q.", admin_kb())
        return
    await send(ctx, update.effective_chat.id, f"🗂 Ochiq maxfiylik so‘rovlari: {len(rows)} ta", admin_kb())
    kinds = {"correction": "Tuzatish", "deletion": "O‘chirish"}
    for r in rows:
        a = latest_app(r["tg_id"]) if r["tg_id"] else None
        kind = kinds.get(r["kind"], r["kind"] or "—")
        await send(ctx, update.effective_chat.id,
                   f"<b>#{r['id']}</b> · {kind} · ariza: {a['ref'] if a else '—'}\n{E(r['text'] or '')}",
                   ik([[ib("✅ Bajarildi", f"pr:{r['id']}", GREEN)]]))


def app_admin_text(app):
    d = jload(app["data"])

    def v(k):
        x = d.get(k)
        return E(str(x)) if x else "—"

    u = q1("SELECT username FROM users WHERE tg_id=?", (app["tg_id"],))
    uname = f"@{E(u['username'])}" if u and u["username"] else "yo‘q"
    notes = q1("SELECT COUNT(*) c FROM notes WHERE app_id=?", (app["id"],))["c"]
    quiz = (f"{app['score']}/{app['total']} — {quiz_level(app['score'], app['total'])}"
            if app["score"] is not None and app["total"] else "topshirilmagan")
    auto = "o‘tkazilmagan"
    if app["auto_score"] is not None:
        auto = f"<b>{app['auto_score']}%</b>"
        note = jload(app["auto_note"], {})
        weak = [str(c[0]) for c in note.get("checks", [])
                if isinstance(c, list) and len(c) == 3 and c[1] < 0.6]
        if note.get("hard"):
            auto += " · qat‘iy shart bajarilmagan"
        if weak:
            auto += " · past: " + ", ".join(E(w) for w in weak[:4])
    return (
        f"📄 <b>{app['ref']}</b> · {STATUS_UZ[app['status']]}\n"
        f"Yuborilgan: {fmt_dt(app['submitted_at'])}\n"
        f"🤖 Avto tahlil: {auto}\n\n"
        f"👤 {v('name')} ({uname})\n"
        f"🎂 {v('age')} · 📍 {v('city')}\n"
        f"📷 {v('insta')}\n🔗 {v('link')}\n☎️ {v('contact')}\n"
        f"🧭 Tajriba: {v('exp')}\n"
        f"🎯 Qiziqishlar: {', '.join(E(x) for x in d.get('interests', [])) or '—'}\n"
        f"🏁 Maqsad: {v('goal')}\n⏱ Vaqt: {v('avail')}\n\n"
        f"💬 <b>Motivatsiya:</b>\n{v('motivation')}\n\n"
        f"🧠 Test: {quiz}\n📝 Izohlar: {notes}"
    )


def app_admin_markup(app):
    i = app["id"]
    rows = [
        [ib("👀 Ko‘rib chiqish", f"ad:rev:{i}", BLUE), ib("✅ Qabul", f"ad:acc:{i}", GREEN)],
        [ib("🕓 Kutish ro‘yxati", f"ad:wl:{i}", BLUE), ib("❌ Rad etish", f"ad:rej:{i}", RED)],
        [ib("ℹ️ Ma‘lumot so‘rash", f"ad:need:{i}", BLUE), ib("📝 Izoh qo‘shish", f"ad:note:{i}", BLUE)],
        [ib("📒 Izohlar", f"adn:{i}", BLUE), ib("🧠 Test javoblari", f"adq:{i}", BLUE)],
    ]
    if app["status"] == "archived":
        rows.append([ib("♻️ Tiklash", f"ad:rest:{i}", GREEN)])
    else:
        rows.append([ib("🗄 Arxivlash", f"ad:arch:{i}", RED)])
    return ik(rows)


async def admin_search(update, ctx, text):
    uid, chat = update.effective_user.id, update.effective_chat.id
    set_state(uid, "")
    t = clean(text, 60).lstrip("@")
    low = t.lower()
    status_keys = [k for k, v in STATUS_UZ.items() if low and (low == k or low == v.lower())]
    rows = qa(
        """SELECT a.* FROM apps a LEFT JOIN users u ON u.tg_id=a.tg_id
           WHERE a.status!='draft' AND (a.ref=? OR lower(u.username)=? OR a.status IN (%s)
              OR lower(json_extract(a.data,'$.name')) LIKE ?)
           ORDER BY a.id DESC LIMIT 15""" % (",".join("?" * len(status_keys)) or "''"),
        (t.upper(), low, *status_keys, f"%{low}%"),
    )
    if not rows:
        await send(ctx, chat, "Hech narsa topilmadi.", admin_kb())
        return
    await send(ctx, chat, f"🔎 Topildi: {len(rows)} ta", admin_kb())
    await send(ctx, chat, "👇 Tanlang:", ik([app_row_btn(a) for a in rows]))


async def notify_applicant(ctx, app, new_status, reason, log_id, actor_id):
    """Holat o'zgarishini bildirish — log_id bo'yicha bir marta (idempotent)."""
    text = NOTIFY_TEXT.get(new_status)
    if not text:
        return
    cur = ex("INSERT OR IGNORE INTO notif_log(log_id,app_id,ok,error,at) VALUES(?,?,0,'pending',?)",
             (log_id, app["id"], now()))
    if cur.rowcount == 0:
        return
    u = q1("SELECT notify FROM users WHERE tg_id=?", (app["tg_id"],))
    if new_status in ("review", "waitlisted") and u and not u["notify"]:
        ex("UPDATE notif_log SET error='opted_out' WHERE log_id=?", (log_id,))
        return
    markup = menu_kb(app["tg_id"])
    body = text.format(ref=app["ref"], reason=E(reason or ""))
    if new_status == "accepted":
        link = await group_invite_link(ctx, app["tg_id"])
        if link:
            body += f"\n\n🔗 <a href=\"{E(link)}\">Guruh havolasi</a>\n<code>{E(link)}</code>"
            markup = ik([[InlineKeyboardButton("🚀 Guruhga qo‘shilish", url=link)]])
    ok, err = await safe_send(ctx, app["tg_id"], body, markup)
    ex("UPDATE notif_log SET ok=?, error=? WHERE log_id=?", (1 if ok else 0, err, log_id))
    if not ok and is_admin(actor_id):
        await send(ctx, actor_id, f"⚠️ {app['ref']}: arizachiga xabar yetkazilmadi ({err}). "
                                  "Holat baribir o‘zgartirildi.")


TRANSITIONS = {"rev": "review", "acc": "accepted", "wl": "waitlisted",
               "rej": "rejected", "need": "need_info", "arch": "archived", "rest": "submitted"}


async def apply_status(ctx, admin_id, app_id, action, reason=""):
    app = app_by_id(app_id)
    new = TRANSITIONS[action]
    if not app or app["status"] in ("draft", "withdrawn"):
        return False, "Bu arizaning holatini o‘zgartirib bo‘lmaydi."
    if app["status"] == new:
        return False, "Ariza allaqachon shu holatda."
    if action == "rest" and app["status"] != "archived":
        return False, "Faqat arxivlangan arizani tiklash mumkin."
    ex("UPDATE apps SET status=?, updated_at=? WHERE id=?", (new, now(), app_id))
    lid = log_status(app_id, new, admin_id, reason)
    audit(admin_id, "status:" + new, app["ref"])
    await notify_applicant(ctx, app_by_id(app_id), new, reason, lid, admin_id)
    return True, f"{app['ref']} → <b>{STATUS_UZ[new]}</b>"


async def admin_text_input(update, ctx, state, text):
    uid, chat = update.effective_user.id, update.effective_chat.id
    set_state(uid, "")
    _, action, sid = state.split(":")
    app_id = int(sid)
    app = app_by_id(app_id)
    if not app:
        await send(ctx, chat, "Ariza topilmadi.", admin_kb())
        return
    if action == "note":
        note = clean(text, 1000, multiline=True)
        if note:
            ex("INSERT INTO notes(app_id,admin_id,note,at) VALUES(?,?,?,?)", (app_id, uid, note, now()))
            audit(uid, "note_added", app["ref"])
            await send(ctx, chat, "📝 Izoh saqlandi (ariza egasiga ko‘rinmaydi).", admin_kb())
        return
    reason = "" if text.strip() == "-" else clean(text, 500, multiline=True)
    if action == "need" and not reason:
        await send(ctx, chat, "Ma‘lumot so‘rovi matni bo‘sh bo‘lmasligi kerak.", admin_kb())
        return
    ok, msg = await apply_status(ctx, uid, app_id, action, reason)
    await send(ctx, chat, ("✅ " if ok else "⚠️ ") + msg, admin_kb())


def _cb_int(parts, idx):
    try:
        return int(parts[idx])
    except (IndexError, ValueError):
        return None


async def on_admin_callback(update, ctx, q, data):
    uid, chat = q.from_user.id, q.message.chat_id
    if not is_admin(uid):
        await q.answer("Ruxsat yo‘q", show_alert=True)
        return
    parts = data.split(":")
    kind = parts[0]
    if kind == "av":
        app_id = _cb_int(parts, 1)
        app = app_by_id(app_id) if app_id is not None else None
        if not app:
            await q.answer("Ariza topilmadi", show_alert=True)
            return
        await q.answer()
        await send(ctx, chat, app_admin_text(app), app_admin_markup(app))
    elif kind == "ad":
        action = parts[1] if len(parts) > 1 else ""
        app_id = _cb_int(parts, 2)
        app = app_by_id(app_id) if app_id is not None else None
        # “note” holat o‘zgartirmaydi, shuning uchun TRANSITIONS da yo‘q.
        if not app or (action not in TRANSITIONS and action != "note"):
            await q.answer("Noto‘g‘ri amal", show_alert=True)
            return
        if action in ("rej", "need", "note"):
            await q.answer()
            set_state(uid, f"adm:{action}:{app_id}")
            prompts = {
                "rej": "❌ Rad etish sababini yozing (ichki, ariza egasiga ko‘rinmaydi). O‘tkazish uchun “-”.",
                "need": "ℹ️ Ariza egasiga yuboriladigan savol/so‘rovni yozing (u buni ko‘radi):",
                "note": "📝 Ichki izohni yozing (ariza egasiga ko‘rinmaydi):",
            }
            await send(ctx, chat, prompts[action] + "\nBekor qilish: /cancel")
            return
        ok, msg = await apply_status(ctx, uid, app_id, action)
        await q.answer("Bajarildi" if ok else "Bajarilmadi")
        await send(ctx, chat, ("✅ " if ok else "⚠️ ") + msg)
    elif kind == "adn":
        app_id = _cb_int(parts, 1)
        if app_id is None:
            await q.answer("Noto‘g‘ri amal", show_alert=True)
            return
        await q.answer()
        notes = qa("SELECT * FROM notes WHERE app_id=? ORDER BY id DESC LIMIT 10", (app_id,))
        hist = qa("SELECT * FROM status_log WHERE app_id=? ORDER BY id DESC LIMIT 8", (app_id,))
        txt = "📒 <b>Izohlar</b>\n" + ("\n".join(f"• {E(n['note'])} <i>({fmt_dt(n['at'])})</i>" for n in notes) or "—")
        txt += "\n\n🕘 <b>Holat tarixi</b>\n" + "\n".join(
            f"• {STATUS_UZ.get(h['status'], h['status'])} · {fmt_dt(h['at'])}"
            + (f" · {E(h['reason'])}" if h["reason"] else "") for h in hist)
        await send(ctx, chat, txt)
    elif kind == "adq":
        await q.answer()
        app_id = _cb_int(parts, 1)
        app = app_by_id(app_id) if app_id is not None else None
        quiz = jload(app["quiz"]) if app else {}
        if not quiz.get("items"):
            await send(ctx, chat, "🧠 Bu ariza uchun test topshirilmagan.")
            return
        lines = [f"🧠 <b>Test javoblari</b> (versiya {quiz.get('v', '?')})\n"]
        for n, it in enumerate(quiz["items"], 1):
            qd = QUIZ[it["q"]]
            if it["a"] == -2:
                mark = "⌛ vaqt tugadi"
            elif it["a"] is None or it["a"] < 0:
                mark = "🤷 belgilanmagan"
            else:
                w = qd["w"][it["p"][it["a"]]]
                mark = f"{E(qd['o'][it['p'][it['a']]])} · moslik {w}/{QUIZ_MAX_PER_QUESTION}"
            lines.append(f"{n}. <i>{E(qd['cat'])}</i> — {mark}")
        await send(ctx, chat, "\n".join(lines))
    elif kind == "cb":
        target = _cb_int(parts, 1)
        if target is None or not q1("SELECT 1 FROM users WHERE tg_id=?", (target,)):
            await q.answer("Foydalanuvchi topilmadi", show_alert=True)
            return
        await q.answer("Chat ochilmoqda...")
        await chat_open(ctx, uid, target)
    elif kind == "cbl":
        await q.answer()
        await h_a_chat(update, ctx, offset=_cb_int(parts, 1) or 0)
    elif kind == "pr":
        req_id = _cb_int(parts, 1)
        r = q1("SELECT * FROM privacy_requests WHERE id=? AND status='open'", (req_id,)) if req_id else None
        if not r:
            await q.answer("Allaqachon bajarilgan", show_alert=True)
            return
        await q.answer("Bajarildi")
        if r["tg_id"]:
            await safe_send(ctx, r["tg_id"], "✅ Tuzatish so‘rovingiz ko‘rib chiqildi. Ma‘lumotlaringizni "
                                             "“Ariza holati” → “Arizani yangilash” orqali ham o‘zgartirishingiz mumkin.")
        ex("UPDATE privacy_requests SET status='done', done_at=?, text='', tg_id=NULL WHERE id=?",
           (now(), r["id"]))
        audit(uid, "privacy_request_done", f"#{r['id']}")
        await send(ctx, chat, f"✅ So‘rov #{r['id']} yopildi (matn va identifikator o‘chirildi).")


# ----------------------------------------------------------------------------
# BOT ICHIDAGI CHAT (admin ↔ foydalanuvchi)
# ----------------------------------------------------------------------------

def open_chat_row(tg_id):
    return q1("SELECT * FROM chats WHERE tg_id=? AND status='open'", (tg_id,))


def start_chat(admin_id, target):
    """Ochiq chatni qaytaradi; yo‘q bo‘lsa yangisini yaratadi. (chat_id, created)."""
    row = open_chat_row(target)
    if row:
        return row["id"], False
    try:
        cur = ex("INSERT INTO chats(tg_id,status,opened_by,created_at) VALUES(?,?,?,?)",
                 (target, "open", admin_id, now()))
        return cur.lastrowid, True
    except sqlite3.IntegrityError:
        row = open_chat_row(target)
        return (row["id"] if row else None), False


def log_chat(chat_id, from_id, text):
    ex("INSERT INTO chat_msgs(chat_id,from_id,text,at) VALUES(?,?,?,?)",
       (chat_id, from_id, clean(text, 500), now()))


def user_label(tg_id):
    u = q1("SELECT name,username FROM users WHERE tg_id=?", (tg_id,))
    name = ((u["name"] if u else "") or "").strip() or str(tg_id)
    if u and u["username"]:
        return f"{name} (@{u['username']})"
    return name


async def relay_message(ctx, msg, to_chat_id):
    """Xabarni (matn, rasm, video, fayl, ovoz) boshqa chatga nusxalaydi."""
    try:
        await ctx.bot.copy_message(chat_id=to_chat_id, from_chat_id=msg.chat_id,
                                   message_id=msg.message_id)
        return True
    except TelegramError as e:
        log.warning("Chat relay xatosi: %s", e)
        return False


async def chat_open(ctx, admin_id, target):
    """Admin va foydalanuvchi o‘rtasida bot ichida chat ochadi."""
    chat_id, created = start_chat(admin_id, target)
    app = latest_app(target)
    ref = app["ref"] if app else "—"
    set_state(admin_id, f"chat:{target}")
    await send(ctx, target, CHAT_OPEN_FOR_USER,
               ik([[ib(B_CHAT_END, f"cc:end:{target}", RED)]]))
    admin_text = (CHAT_OPEN_FOR_ADMIN if created else CHAT_ALREADY)
    await send(ctx, admin_id,
               admin_text.format(who=E(user_label(target)), tg_id=target, ref=ref),
               rk([[kb(B_CHAT_END, RED)], [kb(B_HOME, GREEN)]]))
    audit(admin_id, "chat_open" if created else "chat_resume", str(target))
    return chat_id


async def chat_close(ctx, target, actor_id):
    """Chatni tugatadi va ikkala tomonga chiroyli xabar yuboradi."""
    row = open_chat_row(target)
    if not row:
        if get_state(actor_id).startswith("chat:"):
            set_state(actor_id, "")
        await send(ctx, actor_id, CHAT_NO_OPEN,
                   admin_kb() if is_admin(actor_id) else menu_kb(actor_id))
        return False
    ex("UPDATE chats SET status='closed', closed_at=? WHERE id=?", (now(), row["id"]))
    audit(actor_id, "chat_close", str(target))
    for aid in ADMIN_IDS:
        if get_state(aid) == f"chat:{target}":
            set_state(aid, "")
    if get_state(target) == f"chat:{target}":
        set_state(target, "")
    who = E(user_label(target))
    await send(ctx, target, CHAT_CLOSED_FOR_USER, menu_kb(target))
    if is_admin(actor_id):
        await send(ctx, actor_id, CHAT_CLOSED_FOR_ADMIN.format(who=who), admin_kb())
    opener = row["opened_by"]
    if opener and opener != actor_id and is_admin(opener):
        await send(ctx, opener, CHAT_CLOSED_FOR_ADMIN.format(who=who), admin_kb())
    # Chat ariza jarayonini to‘xtatib qo‘ygan bo‘lsa — qoldirilgan joyidan davom etamiz.
    app = draft_app(target)
    if app:
        if app["step"] in STEPS:
            await send(ctx, target, "📝 Arizangizni qoldirilgan joyidan davom ettiramiz:")
            await render_step(ctx, target, app, app["step"])
        elif app["step"] == "quiz":
            await send_question(ctx, target, app)
        elif app["step"] == "summary":
            await show_summary(ctx, target, app)
    return True


async def admin_chat_forward(update, ctx, target):
    """Admin yozgan xabar (yoki media) foydalanuvchiga boradi."""
    msg = update.message
    uid = update.effective_user.id
    row = open_chat_row(target)
    if not row:
        set_state(uid, "")
        await send(ctx, uid, CHAT_NO_OPEN, admin_kb())
        return
    ok = await relay_message(ctx, msg, target)
    if not ok and msg.text:
        ok = await send(ctx, target, E(msg.text))
    log_chat(row["id"], uid, msg.text or msg.caption or "[media]")
    if not ok:
        await send(ctx, uid, CHAT_RELAY_FAIL)


async def user_chat_forward(update, ctx, row):
    """Foydalanuvchi yozgan xabar (yoki media) adminlarga boradi."""
    msg = update.message
    targets = [row["opened_by"]] if row["opened_by"] in ADMIN_IDS else list(ADMIN_IDS)
    delivered = False
    for aid in targets:
        if await relay_message(ctx, msg, aid):
            delivered = True
    if not delivered:
        label = E(user_label(msg.chat_id))
        body = E(msg.text or msg.caption or "[media]")
        for aid in targets:
            if await send(ctx, aid, f"💬 <b>{label}</b>:\n{body}"):
                delivered = True
    log_chat(row["id"], msg.chat_id, msg.text or msg.caption or "[media]")
    if not delivered:
        await send(ctx, msg.chat_id, CHAT_RELAY_FAIL)


CHAT_PAGE = 20


async def h_a_chat(update, ctx, offset=0):
    """Admin panel → foydalanuvchilar ro‘yxati (chat ochish uchun)."""
    uid, chat = update.effective_user.id, update.effective_chat.id
    if not is_admin(uid):
        return
    offset = max(0, int(offset))
    rows = qa(
        """SELECT u.tg_id, u.name, u.username,
                  (SELECT c.id FROM chats c WHERE c.tg_id=u.tg_id
                    AND c.status='open' LIMIT 1) AS oc
           FROM users u ORDER BY u.last_seen DESC LIMIT ? OFFSET ?""",
        (CHAT_PAGE, offset),
    )
    if not rows:
        await send(ctx, chat, CHAT_NO_USERS, admin_kb())
        return
    btns = []
    for r in rows:
        label = (r["name"] or str(r["tg_id"]))[:24]
        if r["username"]:
            label += " @" + r["username"][:14]
        icon = "🟢" if r["oc"] else "⚪"
        btns.append([ib(f"{icon} {label}", f"cb:{r['tg_id']}",
                        BLUE if r["oc"] else GREEN)])
    nav = []
    if offset > 0:
        nav.append(ib("⬅️ Oldingi", f"cbl:{max(0, offset - CHAT_PAGE)}", BLUE))
    if len(rows) == CHAT_PAGE:
        nav.append(ib("➡️ Keyingi", f"cbl:{offset + CHAT_PAGE}", BLUE))
    if nav:
        btns.append(nav)
    await send(
        ctx, chat,
        "💬 <b>Foydalanuvchilar bilan bog‘lanish</b>\n\n"
        "Chat ochmoqchi bo‘lgan foydalanuvchini tanlang.\n"
        "⚪ — yangi chat · 🟢 — chat allaqachon ochiq.\n\n"
        "<i>Chat ochilgach yozganlaringiz foydalanuvchiga boradi; u yuborgan matn, rasm, "
        "video, fayl va ovozli xabarlar ham sizga keladi.</i>",
        admin_kb(),
    )
    await send(ctx, chat, "👇 Tanlang:", ik(btns))


async def h_chat_end(update, ctx):
    uid, chat = update.effective_user.id, update.effective_chat.id
    state = get_state(uid)
    if is_admin(uid) and state.startswith("chat:"):
        try:
            target = int(state.split(":", 1)[1])
        except ValueError:
            target = None
        if target:
            await chat_close(ctx, target, uid)
            return
    row = open_chat_row(uid)
    if row:
        await chat_close(ctx, uid, uid)
        return
    await send(ctx, chat, CHAT_NO_OPEN, admin_kb() if is_admin(uid) else menu_kb(uid))


async def h_join(update, ctx):
    """Arizasi qabul qilingan a’zo uchun guruh havolasi."""
    uid, chat = update.effective_user.id, update.effective_chat.id
    app = latest_app(uid)
    if not app or app["status"] != "accepted":
        await send(
            ctx, chat,
            "🚀 Guruh havolasi faqat arizasi <b>qabul qilingan</b> a’zolar uchun.\n\n"
            "Arizangiz holatini “" + B_STATUS + "” bo‘limidan tekshiring.",
            menu_kb(uid),
        )
        return
    link = await group_invite_link(ctx, uid)
    if not link:
        await send(ctx, chat, "⚠️ Havola vaqtincha mavjud emas. Birozdan keyin qayta urinib ko‘ring.",
                   menu_kb(uid))
        return
    await send(
        ctx, chat,
        "🚀 <b>KYPTEAM guruhi</b>\n\n"
        f"<b>{app['ref']}</b> arizangiz qabul qilingan. Pastdagi tugma orqali guruhga qo‘shiling.\n\n"
        f"🔗 <a href=\"{E(link)}\">Guruh havolasi</a>\n<code>{E(link)}</code>\n\n"
        "Guruhga kirgach: qoidalarni o‘qing, o‘zingizni tanishtiring va o‘rganishni boshlang. 🛡",
        ik([[InlineKeyboardButton("🚀 Guruhga qo‘shilish", url=link)]]),
    )


# ----------------------------------------------------------------------------
# CALLBACK (yordamchi tugmalar) VA MATN YO'NALTIRGICH
# ----------------------------------------------------------------------------

async def on_callback(update: Update, ctx):
    q = update.callback_query
    if not q:
        return
    if not q.message or q.message.chat.type != "private":
        try:
            await q.answer()
        except TelegramError:
            pass
        return
    upsert_user(update)
    if not await guard(update, ctx):
        return
    data = (q.data or "")[:64]
    uid, chat = q.from_user.id, q.message.chat_id
    prefix = data.split(":")[0]

    if prefix in ("av", "ad", "adn", "adq", "pr", "cb", "cbl"):
        await on_admin_callback(update, ctx, q, data)
        return

    if prefix == "cc":
        # Chatni tugatish: admin ham, chat egasi bo‘lgan foydalanuvchi ham bosishi mumkin.
        parts_cc = data.split(":")
        target = _cb_int(parts_cc, 2)
        if target is None or not (is_admin(uid) or uid == target):
            await q.answer("Ruxsat yo‘q", show_alert=True)
            return
        await q.answer()
        await chat_close(ctx, target, uid)
        return

    async def stale():
        await q.answer("Bu tugma eskirgan", show_alert=True)

    async def mark(text):
        try:
            await q.edit_message_text(text, parse_mode=HTML)
        except BadRequest:
            pass

    app = draft_app(uid)

    if prefix in CHOICES:
        step, key, options = CHOICES[prefix]
        try:
            i = int(data.split(":")[1])
            label = options[i]
        except (ValueError, IndexError):
            await stale()
            return
        if not app or app["step"] != step:
            await stale()
            return
        await q.answer()
        d = jload(app["data"])
        d[key] = label
        save_data(app["id"], d)
        await mark(f"✔️ Tanlandi: <b>{E(label)}</b>")
        if step == "age" and i == 0:
            purge_app(app["id"])
            await send(ctx, chat, "Kechirasiz, hozircha 16 yoshdan kichik arizalar qabul qilinmaydi. "
                                  "Ma‘lumotlar saqlanmadi. O‘rganishda davom eting — kattaroq bo‘lganingizda kutamiz! 🙌",
                       menu_kb(uid))
            return
        await advance(ctx, chat, app["id"])
    elif prefix == "nm":
        if not app or app["step"] != "name":
            await stale()
            return
        await q.answer()
        d = jload(app["data"])
        d["name"] = clean(q.from_user.full_name or "", 60) or "Foydalanuvchi"
        save_data(app["id"], d)
        await mark(f"✔️ Ism: <b>{E(d['name'])}</b>")
        await advance(ctx, chat, app["id"])
    elif prefix == "ct":
        if not app or app["step"] != "contact":
            await stale()
            return
        await q.answer()
        d = jload(app["data"])
        d["contact"] = "Telegram orqali yozing"
        save_data(app["id"], d)
        await mark("✔️ Aloqa: <b>Telegram orqali</b>")
        await advance(ctx, chat, app["id"])
    elif prefix == "in":
        if not app or app["step"] != "interests":
            await stale()
            return
        try:
            lbl = INTERESTS[int(data.split(":")[1])]
        except (ValueError, IndexError):
            await stale()
            return
        d = jload(app["data"])
        sel = d.get("interests", [])
        if lbl in sel:
            sel.remove(lbl)
        else:
            sel.append(lbl)
        d["interests"] = [x for x in INTERESTS if x in sel]
        save_data(app["id"], d)
        await q.answer()
        try:
            await q.edit_message_reply_markup(reply_markup=interests_markup(d["interests"]))
        except BadRequest:
            pass
    elif prefix == "ind":
        if not app or app["step"] != "interests":
            await stale()
            return
        d = jload(app["data"])
        if not d.get("interests"):
            await q.answer("Kamida bittasini tanlang", show_alert=True)
            return
        await q.answer()
        await mark("✔️ Qiziqishlar: <b>" + ", ".join(E(x) for x in d["interests"]) + "</b>")
        await advance(ctx, chat, app["id"])
    elif prefix == "ed":
        key = data.split(":")[1]
        if not app or app["step"] != "summary":
            await stale()
            return
        await q.answer()
        if key == "quiz":
            ex("UPDATE apps SET editing=1 WHERE id=?", (app["id"],))
            await start_quiz(ctx, chat, app["id"])
        elif key in STEPS:
            ex("UPDATE apps SET editing=1 WHERE id=?", (app["id"],))
            await goto(ctx, chat, app["id"], key)
        else:
            await stale()
    elif prefix == "q":
        try:
            _, si, sk = data.split(":")
            idx = int(si)
        except ValueError:
            await stale()
            return
        if not app or app["step"] != "quiz":
            await stale()
            return
        quiz = jload(app["quiz"])
        items = quiz.get("items", [])
        if idx != quiz.get("i") or idx >= len(items) or items[idx]["a"] is not None:
            await q.answer("Bu savolga allaqachon javob berilgan", show_alert=True)
            return
        item = items[idx]
        if time.time() > item.get("d", float("inf")):
            # Vaqt tugagan: javob qabul qilinmaydi, savol o‘tkazib yuboriladi.
            item["a"] = -2
        elif sk == "x":
            item["a"] = -1
        elif sk in ("0", "1", "2", "3"):
            item["a"] = int(sk)
        else:
            await stale()
            return
        qd = QUIZ[item["q"]]
        if item["a"] == -2:
            verdict = (f"⌛ <b>Vaqt tugadi.</b> Javob qabul qilinmadi — savol o‘tkazib yuborildi. "
                       f"Keyingi savolda {QUIZ_TIME_SECONDS} soniya ichida javob bering.")
        elif item["a"] == -1:
            verdict = "🤷 Belgilanmadi — bilmaslik normal, muhimi o‘rganishda davom etish."
        elif qd["w"][item["p"][item["a"]]] == 2:
            verdict = "✅ Belgilandi — bu variant sizga yaxshi mos."
        else:
            verdict = "👍 Belgilandi."
        quiz["i"] = idx + 1
        ex("UPDATE apps SET quiz=?, updated_at=? WHERE id=?", (json.dumps(quiz), now(), app["id"]))
        await q.answer()
        await mark(qtext(item, idx, len(items), show_timer=False)
                   + f"\n\n{verdict}\n💡 {E(qd['e'])}")
        await send_question(ctx, chat, app_by_id(app["id"]))
    elif prefix == "st":
        await q.answer()
        await show_status(update, ctx)
    elif prefix == "up":
        a = active_app(uid)
        if not a or a["status"] not in ("submitted", "review", "need_info"):
            await stale()
            return
        await q.answer()
        ex("UPDATE apps SET prev_status=?, status='draft', step='summary', editing=0, updated_at=? WHERE id=?",
           (a["status"], now(), a["id"]))
        await send(ctx, chat, "✏️ Arizani tahrirlang va qayta yuboring. Bekor qilsangiz, avvalgi holat saqlanadi.")
        await show_summary(ctx, chat, app_by_id(a["id"]))
    elif prefix == "wd":
        act = data.split(":")[1]
        a = active_app(uid)
        if act == "ask":
            await q.answer()
            if a and a["status"] != "draft":
                await send(ctx, chat, f"<b>{a['ref']}</b> arizasini qaytarib olishni tasdiqlaysizmi?",
                           ik([[ib("Ha, qaytarib olaman", "wd:y", RED), ib("Yo‘q", "wd:n", GREEN)]]))
        elif act == "y":
            if not a or a["status"] == "draft":
                await stale()
                return
            await q.answer()
            ex("UPDATE apps SET status='withdrawn', updated_at=? WHERE id=?", (now(), a["id"]))
            log_status(a["id"], "withdrawn", uid, "Ariza egasi tomonidan")
            await mark("↩️ Ariza qaytarib olindi.")
            await send(ctx, chat, "Arizangiz qaytarib olindi. Xohlasangiz, keyinroq qayta topshirishingiz mumkin.",
                       menu_kb(uid))
        else:
            await q.answer()
            await mark("Bekor qilindi — ariza o‘z holida qoldi.")
    elif prefix == "del":
        if data.endswith(":y"):
            await q.answer()
            purge_user(uid)
            ex("INSERT INTO privacy_requests(tg_id,kind,text,status,created_at,done_at) VALUES(NULL,'deletion','','done',?,?)",
               (now(), now()))
            audit("user", "privacy_delete", "anonim")
            await mark("🗑 Ma‘lumotlaringiz o‘chirildi.")
            await send(ctx, chat, "Barcha ma‘lumotlaringiz o‘chirildi. Xohlasangiz, /start orqali qaytishingiz mumkin.",
                       rk([[kb("/start", GREEN)]]))
        else:
            await q.answer()
            await mark("Bekor qilindi — ma‘lumotlar o‘z joyida.")
    else:
        await stale()


BUTTONS = {
    B_APPLY: h_apply, B_ABOUT: h_about, B_RULES: h_rules, B_PRIVACY: h_privacy,
    B_HELP: h_help, B_STATUS: cmd_status, B_WITHDRAW: h_withdraw, B_DELETE: h_delete,
    B_CORRECT: h_correct, B_NOTIFY: h_notify, B_ADMIN: h_admin,
    B_HOME: lambda u, c: show_home(u, c),
    B_AGREE: h_agree, B_DISAGREE: h_disagree, B_CANCEL: cancel_flow,
    B_BACK: h_back, B_SKIP: h_skip, B_RULES_OK: h_rules_ok,
    B_QUIZ_GO: h_quiz_go, B_QUIZ_NO: h_quiz_no, B_QUIZ_STOP: h_quiz_stop,
    B_SUBMIT: h_submit,
    B_A_NEW: h_a_new, B_A_STATS: h_a_stats, B_A_SEARCH: h_a_search, B_A_REQ: h_a_req,
    B_A_APPS: h_a_apps, B_A_MAINT: h_a_maint, B_A_EXPORT: h_a_export,
    B_JOIN: h_join, B_CHAT: h_a_chat, B_CHAT_END: h_chat_end,
}


async def on_text(update: Update, ctx):
    msg = update.message
    if not msg or not msg.text or update.effective_chat.type != "private":
        return
    upsert_user(update)
    if not await guard(update, ctx):
        return
    uid, chat = update.effective_user.id, update.effective_chat.id
    text = msg.text.strip()

    if text in BUTTONS:
        if text not in (B_CANCEL, B_CHAT_END):
            set_state(uid, "")
        if text == B_STATUS:
            await show_status(update, ctx)
        else:
            await BUTTONS[text](update, ctx)
        return

    state = get_state(uid)
    if state == "correction":
        set_state(uid, "")
        body = clean(text, 500, multiline=True)
        if looks_secret(body) or len(body) < 3:
            await send(ctx, chat, "Iltimos, parol/token yozmang va so‘rovni aniqroq yozing. /cancel — bekor qilish.")
            set_state(uid, "correction")
            return
        cur = ex("INSERT INTO privacy_requests(tg_id,kind,text,status,created_at) VALUES(?,?,?,?,?)",
                 (uid, "correction", body, "open", now()))
        await send(ctx, chat, "✅ So‘rovingiz qabul qilindi. Jamoa ko‘rib chiqadi.", menu_kb(uid))
        for aid in ADMIN_IDS:
            await send(ctx, aid, f"🗂 Yangi maxfiylik so‘rovi #{cur.lastrowid}. “{B_A_REQ}” bo‘limida ko‘ring.")
        return
    if is_admin(uid) and state == "adm_search":
        await admin_search(update, ctx, text)
        return
    if is_admin(uid) and state.startswith("adm:"):
        await admin_text_input(update, ctx, state, text)
        return
    if is_admin(uid) and state.startswith("chat:"):
        try:
            target = int(state.split(":", 1)[1])
        except ValueError:
            set_state(uid, "")
        else:
            await admin_chat_forward(update, ctx, target)
            return

    # Ochiq chat bo‘lsa, foydalanuvchi matni to‘g‘ridan-to‘g‘ri adminga boradi.
    if not is_admin(uid):
        row = open_chat_row(uid)
        if row:
            await user_chat_forward(update, ctx, row)
            return

    app = draft_app(uid)
    if app and app["step"] in STEPS:
        await handle_step_text(update, ctx, app, text)
        return
    if app and app["step"] == "consent":
        await send(ctx, update.effective_chat.id, "Davom etish uchun pastdagi tugmalardan birini tanlang 👇")
        return
    if app and app["step"] in ("quiz", "quiz_offer", "summary"):
        await send(ctx, chat, "Iltimos, pastdagi yoki xabar ostidagi tugmalardan foydalaning 👇")
        return
    await send(ctx, chat, "Tushunmadim. Menyudagi tugmalardan foydalaning 👇", menu_kb(uid))


async def on_error(update, ctx):
    log.error("Handler xatosi: %s", ctx.error, exc_info=ctx.error)
    try:
        if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
            await ctx.bot.send_message(update.effective_chat.id,
                                       "⚠️ Kutilmagan xatolik yuz berdi. /start ni bosib qayta urinib ko‘ring.")
    except TelegramError:
        pass


# ----------------------------------------------------------------------------
# SAQLASH MUDDATI (retention) VA ISHGA TUSHIRISH
# ----------------------------------------------------------------------------

def run_retention():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    old = qa("""SELECT id FROM apps WHERE updated_at<? AND status IN ('rejected','withdrawn','archived')""", (cutoff,))
    drafts = qa("""SELECT id FROM apps WHERE status='draft' AND updated_at<?""",
                ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds"),))
    for r in list(old) + list(drafts):
        purge_app(r["id"])
    old_chats = qa("SELECT id FROM chats WHERE status='closed' AND closed_at<?", (cutoff,))
    for r in old_chats:
        ex("DELETE FROM chat_msgs WHERE chat_id=?", (r["id"],))
        ex("DELETE FROM chats WHERE id=?", (r["id"],))
    stale_users = qa(
        "SELECT tg_id FROM users WHERE last_seen<? AND tg_id NOT IN (SELECT tg_id FROM apps)",
        (cutoff,),
    )
    for r in stale_users:
        # Foydalanuvchi o‘chirilganda uning shaxsiy so‘rovlari ham qolmasligi kerak.
        ex("DELETE FROM privacy_requests WHERE tg_id=?", (r["tg_id"],))
        ex("DELETE FROM users WHERE tg_id=?", (r["tg_id"],))
    if old or drafts or stale_users or old_chats:
        audit("system", "retention_job",
              f"{len(old)} yakunlangan, {len(drafts)} qoralama, {len(old_chats)} chat, "
              f"{len(stale_users)} foydalanuvchi o‘chirildi")


async def retention_loop():
    while True:
        try:
            run_retention()
        except Exception:  # noqa: BLE001
            log.exception("Retention xatosi")
        await asyncio.sleep(24 * 3600)


async def post_init(app: Application):
    db_init()
    app.bot_data["retention_task"] = asyncio.create_task(retention_loop())
    await app.bot.set_my_commands([
        BotCommand("start", "Bosh menyu"),
        BotCommand("status", "Ariza holati"),
        BotCommand("privacy", "Maxfiylik"),
        BotCommand("cancel", "Bekor qilish"),
        BotCommand("help", "Yordam"),
    ])
    me = await app.bot.get_me()
    log.info("Bot ishga tushdi: @%s | adminlar: %d ta", me.username, len(ADMIN_IDS))


async def post_shutdown(app: Application):
    task = app.bot_data.get("retention_task")
    if task:
        task.cancel()


def start_health_server():
    """Render (va boshqa hostinglar) uchun oddiy HTTP health server.

    Render bepul “Web Service” faqat $PORT portini tinglaydigan dasturni tirik deb
    hisoblaydi; faqat polling qiladigan bot esa “no open ports detected” xatosi
    bilan yopiladi. Shu sababli bot bilan birga kichik HTTP server ishga tushadi
    (/ va /health — 200 va qisqa JSON). PORT berilmasa hech narsa ochilmaydi.
    """
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        log.info("PORT berilmagan — health server o‘chirilgan (lokal ish rejimi).")
        return None
    try:
        port = int(raw)
    except ValueError:
        log.warning("PORT noto‘g‘ri (%r) — health server ishga tushmadi", raw)
        return None

    class HealthHandler(BaseHTTPRequestHandler):
        server_version = "kypteam-health"

        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
            if self.path.split("?")[0] not in ("/", "/health", "/healthz"):
                self.send_error(404)
                return
            body = json.dumps(
                {"ok": True, "service": "kypteam-bot", "at": now()}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # noqa: A003
            log.debug("health: " + fmt, *args)

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    except OSError as e:
        log.warning("Health server %s portini egallay olmadi: %s", port, e)
        return None
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="health-server", daemon=True).start()
    log.info("Health server ishga tushdi: 0.0.0.0:%s (/health)", port)
    return srv


def main():
    if not BOT_TOKEN:
        sys.exit("XATO: BOT_TOKEN topilmadi. .env faylga yoki muhit o‘zgaruvchisiga qo‘ying (BotFather'dan oling).")
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS bo‘sh — admin panel hech kimga ochilmaydi.")
    start_health_server()  # Render: $PORT ni tinglash shart
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    priv = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", cmd_start, filters=priv))
    app.add_handler(CommandHandler("help", cmd_help, filters=priv))
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=priv))
    app.add_handler(CommandHandler("status", cmd_status, filters=priv))
    app.add_handler(CommandHandler("privacy", cmd_privacy, filters=priv))
    app.add_handler(CommandHandler("admin", cmd_admin, filters=priv))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(priv & filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(priv & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(priv & ~filters.COMMAND & ~filters.TEXT & ~filters.CONTACT, on_other))
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
