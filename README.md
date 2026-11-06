# KYPTEAM — Telegram ariza boti

Bitta faylli (`main.py`) Telegram bot: kiberxavfsizlik jamoasiga ariza qabul qilish,
arizani avtomatik tahlil qilish, vaziyat testi, admin panel, bot ichidagi chat,
maxfiylik (rozilik, tuzatish, o‘chirish) va avtomatik saqlash muddati (retention).

## 1. O‘rnatish

```bash
python -m venv .venv
# Windows (Git Bash):
.venv/Scripts/python.exe -m pip install -r requirements.txt
# Linux/macOS:
.venv/bin/python -m pip install -r requirements.txt
```

Talab: Python 3.10+ va `python-telegram-bot>=22.7` (tugma ranglari uchun).

## 2. Sozlash

`.env.example` dan nusxa olib `.env` yarating:

```dotenv
BOT_TOKEN=BotFather bergan token
ADMIN_IDS=1833396464,8609034602          # vergul bilan bir nechta ID
DB_PATH=kypteam.db
RETENTION_DAYS=180

# Qabul qilinganlarga yuboriladigan guruh havolasi
GROUP_INVITE_LINK=https://t.me/+qqpyFJBhe6k3ZWJi
# Ixtiyoriy: bot guruhda admin bo'lsa, har bir a'zo uchun bir martalik havola yaratiladi
GROUP_CHAT_ID=-1001234567890
# Avtomatik tahlil o'tish foizi (0-100)
AUTO_ACCEPT_MIN=55
# Har bir test savoliga beriladigan vaqt (soniya)
QUIZ_TIME_SECONDS=60
```

`GROUP_CHAT_ID` bo‘sh qoldirilsa, barcha qabul qilinganlarga `GROUP_INVITE_LINK` yuboriladi.
Bir martalik havola uchun bot guruhda **admin** bo‘lishi va “foydalanuvchilarni taklif qilish”
huquqiga ega bo‘lishi kerak.
Agar bot guruhda admin bo‘lsa va `GROUP_CHAT_ID` berilgan bo‘lsa, har bir a’zo uchun
**bitta odam uchun** ishlaydigan havola yaratiladi — shunda bot a’zolarni o‘zi tanlab qabul qiladi.

`.env` **hech qachon** git ga yoki boshqalarga berilmaydi (`.gitignore` da).

## 3. Ishga tushirish

```bash
.venv/Scripts/python.exe main.py     # Windows
# .venv/bin/python main.py           # Linux/macOS
```

Bot ishga tushganda `kypteam.db` (SQLite) avtomatik yaratiladi.
`PORT` muhit o‘zgaruvchisi berilsa, bot bilan birga kichik health server ham
yo‘lga tushadi (`http://127.0.0.1:$PORT/health`) — Render kabi hostinglar uchun.

## 4. Foydalanuvchi oqimi

`/start` → 📝 Ariza topshirish → maxfiylik roziligi → 12 bosqich (ism, yosh, shahar,
Instagram, havola, aloqa, tajriba, qiziqishlar, motivatsiya, maqsad, vaqt, qoidalar)
→ ixtiyoriy 10 savollik vaziyat testi → xulosa → yuborish.

### Avtomatik tahlil

Ariza yuborilgach bot uni darhol o‘zi baholaydi (yosh, motivatsiya, tajriba, qiziqishlar,
maqsad, vaqt, aloqa, qoidalar va test natijasi). Natija `AUTO_ACCEPT_MIN` foizdan yuqori
bo‘lsa — ariza **qabul qilinadi** va guruhga qo‘shilish havolasi yuboriladi; aks holda
**rad etiladi** va sabab/aniq tavsiyalar bilan chiroyli xabar yuboriladi (havola berilmaydi).
Admin panelda har bir ariza uchun avtomatik ball va qaysi mezonlar past bo‘lgani ko‘rinadi;
admin qarorni qo‘lda ham o‘zgartira oladi.

### Test savollari

Test — bilim emas, **vaziyat va odatlar** haqidagi savollar: “to‘g‘ri” javob yo‘q, har bir
variant moslik balliga (0–2) ega. Savollar aralashtiriladi, har biriga `QUIZ_TIME_SECONDS`
vaqt beriladi va savol xabari `protect_content` bilan himoyalanadi (forward/nusxa olinmaydi).
Shu tufayli savolni AI ga tashlab yuborish amalda foyda bermaydi. Telegram bot API
skrinshotni texnik jihatdan to‘sa olmaydi — buni faqat vaqt chegarasi va savol mazmuni
bilan qiyinlashtiramiz.

### Chat

Admin panel → “💬 Foydalanuvchilar bilan bog‘lanish” → foydalanuvchini tanlash → chat ochiladi.
Foydalanuvchi “Chat ochildi! Savolingiz bo‘lsa yozishingiz mumkin” xabarini oladi, admin esa
to‘g‘ridan-to‘g‘ri shu bot ichida yozadi. Har ikki tomondan matn, rasm, video, fayl va ovozli
xabarlar uzatiladi. “🛑 Chatni tugatish” tugmasi suhbatni yopadi va ikkala tomonga chiroyli
xabar yuboradi (foydalanuvchi ariza jarayonida bo‘lsa, qoldirilgan bosqichdan davom etadi).

Buyruqlar: `/start`, `/status`, `/privacy`, `/cancel`, `/help`.

Foydalanuvchi istalgan vaqtda arizani tuzatishi, yangilashi, qaytarib olishi yoki
barcha ma’lumotlarini o‘chirishi mumkin.

## 5. Admin panel

`ADMIN_IDS` dagi foydalanuvchilarga “🛠 Admin panel” tugmasi ko‘rinadi:

- 📥 Yangi arizalar — ko‘rish, holat o‘zgartirish, izoh, test javoblari
- 💬 Foydalanuvchilar bilan bog‘lanish — ro‘yxatdan foydalanuvchini tanlab, **bot ichida chat**
  ochiladi. Admin yozgan matn, rasm, video, fayl yoki ovoz foydalanuvchiga boradi;
  foydalanuvchi yuborgan har qanday xabar ham adminga keladi. “🛑 Chatni tugatish”
  tugmasi chatni yopadi va ikkala tomonga chiroyli xabar yuboradi.
- 📊 Statistika
- 🔎 Ariza qidirish (KYP-..., ism, @username, holat)
- 🗂 Maxfiylik so‘rovlari
- 🔄 Qabulni ochish/yopish
- 🛠 Texnik rejim
- 📤 CSV eksport (minimal, audit jurnaliga yoziladi)

## 6. Maxfiylik va xavfsizlik

- Faqat parametrli SQL so‘rovlar, HTML escape, uzunlik cheklovlari.
- Parol/token o‘xshash matnlar qabul qilinmaydi.
- Yakunlangan arizalar `RETENTION_DAYS` kundan keyin, qoralamalar 30 kundan keyin
  avtomatik o‘chiriladi; foydalanuvchi ma’lumotlari bilan birga so‘rovlari va
yopilgan chat tarixi ham o‘chiriladi.
- Chat xabarlari faqat suhbat ishtirokchisi (foydalanuvchi) va vakolatli adminlarga
  uzatiladi; “Ma’lumotlarimni o‘chirish” chat tarixini ham butunlay o‘chiradi.
- Telefon faqat Telegramning rasmiy “kontakt ulashish” tugmasi orqali.

## 7. Testlar

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

## 8. Render.com ga deploy

1. Loyihani GitHub ga yuklang — `.env` `.gitignore` da, ya’ni token repoga tushmaydi.
2. Render → **New → Blueprint** → reponi tanlang; `render.yaml` avtomatik o‘qiladi
   (yoki **New → Web Service**: Build `pip install -r requirements.txt`,
   Start `python main.py`).
3. Dashboard → **Environment** bo‘limida `BOT_TOKEN` va `ADMIN_IDS` ni kiriting
   (qolgan o‘zgaruvchilar `render.yaml` da tayyor).
4. Deploy tugagach tekshiring: `https://<servis-nomi>.onrender.com/health` → `{"ok": true}`.

Muhim eslatmalar:

- Bot **polling** rejimida ishlaydi — bir vaqtda faqat bitta nusxa ishlashi kerak.
  Lokal kompyuterda ham `python main.py` ochiq bo‘lsa, Telegram
  `Conflict: terminated by other getUpdates request` xatosini beradi; lokalini to‘xtating.
- Render bepul “Web Service” ilovadan `$PORT` ni tinglashni talab qiladi — shu sababli
  `main.py` ichida health server bor. `PORT` berilmasa u ishga tushmaydi.
- Bepul planda fayl tizimi vaqtinchalik: har redeploy/restartdan keyin SQLite baza
  yangidan boshlanadi. Ma’lumotlar saqlanishi uchun **Starter plan + Disk** kerak:
  `render.yaml` dagi izohni oching (`mountPath: /var/data`) va `DB_PATH` ni
  `/var/data/kypteam.db` ga o‘zgartiring.
