import logging
import os
import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import aiosqlite
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── Конфиг ────────────────────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN   = os.getenv("BOT_TOKEN")
TIMEZONE    = os.getenv("TIMEZONE", "Europe/Moscow")
NOTIFY_HOUR = int(os.getenv("NOTIFY_HOUR", "9"))
PORT        = int(os.getenv("PORT", 8000))       # Render передаёт порт сюда
if not BOT_TOKEN:
    raise RuntimeError("В .env не задан BOT_TOKEN")
TZ = ZoneInfo(TIMEZONE)

logging.basicConfig(level=logging.INFO)
bot   = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp    = Dispatcher(bot, storage=MemoryStorage())
sched = AsyncIOScheduler(timezone=TZ)

DB_DIR  = "data"
DB_PATH = os.path.join(DB_DIR, "products.db")

# ─── Локализация ────────────────────────────────────────────────────────────────
LOCALES = {
    "ru": {
        "welcome":    "👋 Привет! Выберите язык:",
        "main_menu":  ["➕ Добавить продукт", "📦 Список продуктов", "🌐 Сменить язык", "❓ Помощь"],
        "ask_name":   "Введите название продукта:",
        "ask_exp":    "Введите срок годности (DD.MM.YYYY):",
        "ask_notify": "Когда отправить уведомление?",
        "added":      "✅ Продукт добавлен и напоминания запланированы.",
        "ask_custom": "Введите дату и время уведомления (DD.MM.YYYY HH:MM):",
        "custom_ok":  "✅ Пользовательское напоминание запланировано.",
        "list_empty": "Список продуктов пуст.",
        "help": (
            "🆘 <b>Помощь</b>\n"
            "• /add — добавить продукт\n"
            "• /list — показать список\n"
            "• /language — сменить язык\n"
            "• /help — помощь\n\n"
            "Или воспользуйтесь кнопками ниже."
        ),
    },
    "en": {
        "welcome":    "👋 Hello! Please choose your language:",
        "main_menu":  ["➕ Add product", "📦 List products", "🌐 Change language", "❓ Help"],
        "ask_name":   "Enter product name:",
        "ask_exp":    "Enter expiration date (DD.MM.YYYY):",
        "ask_notify": "When to send the reminder?",
        "added":      "✅ Product added and reminders scheduled.",
        "ask_custom": "Enter custom reminder date & time (DD.MM.YYYY HH:MM):",
        "custom_ok":  "✅ Custom reminder scheduled.",
        "list_empty": "Your product list is empty.",
        "help": (
            "🆘 <b>Help</b>\n"
            "• /add — add product\n"
            "• /list — show products\n"
            "• /language — change language\n"
            "• /help — help\n\n"
            "Or use the buttons below."
        ),
    },
    "zh": {
        "welcome":    "👋 你好！请选择语言：",
        "main_menu":  ["➕ 添加产品", "📦 产品列表", "🌐 切换语言", "❓ 帮助"],
        "ask_name":   "请输入产品名称：",
        "ask_exp":    "请输入保质期 (DD.MM.YYYY)：",
        "ask_notify": "何时发送提醒？",
        "added":      "✅ 产品已添加，提醒已安排。",
        "ask_custom": "请输入自定义提醒日期和时间 (DD.MM.YYYY HH:MM)：",
        "custom_ok":  "✅ 自定义提醒已安排。",
        "list_empty": "您的产品列表为空。",
        "help": (
            "🆘 <b>帮助</b>\n"
            "• /add — 添加产品\n"
            "• /list — 显示列表\n"
            "• /language — 切换语言\n"
            "• /help — 帮助\n\n"
            "或使用下面的按钮。"
        ),
    },
    "hi": {
        "welcome":    "👋 नमस्ते! कृपया भाषा चुनें:",
        "main_menu":  ["➕ उत्पाद जोड़ें", "📦 उत्पाद सूची", "🌐 भाषा बदलें", "❓ सहायता"],
        "ask_name":   "उत्पाद का नाम दर्ज करें:",
        "ask_exp":    "समाप्ति तिथि दर्ज करें (DD.MM.YYYY):",
        "ask_notify": "रिमाइंडर कब भेजें?",
        "added":      "✅ उत्पाद जोड़ा गया और रिमाइंडर निर्धारित किया गया।",
        "ask_custom": "कस्टम रिमाइंडर दिनांक और समय दर्ज करें (DD.MM.YYYY HH:MM):",
        "custom_ok":  "✅ कस्टम रिमाइंडर शेड्यूल किया गया।",
        "list_empty": "आपकी उत्पाद सूची खाली है।",
        "help": (
            "🆘 <b>सहायता</b>\n"
            "• /add — उत्पाद जोड़ें\n"
            "• /list — सूची दिखाएँ\n"
            "• /language — भाषा बदलें\n"
            "• /help — सहायता\n\n"
            "या नीचे बटन का उपयोग करें।"
        ),
    },
}

def get_locale(user_id: int) -> str:
    return bot.lang_cache.get(user_id, "ru")

async def set_locale(user_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users(user_id, lang) VALUES(?,?)",
            (user_id, lang)
        )
        await db.commit()
    bot.lang_cache[user_id] = lang

# ─── FSM ────────────────────────────────────────────────────────────────────────
class States(StatesGroup):
    choosing_lang = State()
    name          = State()
    expiration    = State()
    notify        = State()
    custom_time   = State()

# ─── Инициализация БД и миграция ────────────────────────────────────────────────
async def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                lang TEXT NOT NULL
            );
        """)
        # products
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                expiration_date TEXT NOT NULL,
                notify_day_before INTEGER NOT NULL,
                notify_week_before INTEGER NOT NULL,
                custom_time TEXT
            );
        """)
        await db.commit()

    # load language cache
    bot.lang_cache = {}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, lang FROM users;") as cur:
            async for uid, lang in cur:
                bot.lang_cache[uid] = lang

# ─── Планирование напоминаний ─────────────────────────────────────────────────
async def schedule_existing():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, name, expiration_date, notify_day_before, notify_week_before, custom_time FROM products;"
        ) as cur:
            async for pid, uid, name, exp_iso, nd, nw, cust in cur:
                exp_dt = datetime.fromisoformat(exp_iso)
                # за 7 дней
                if nw:
                    dt7 = datetime.combine((exp_dt - timedelta(days=7)).date(),
                                           time(NOTIFY_HOUR, 0), tzinfo=TZ)
                    sched.add_job(bot.send_message, "date", run_date=dt7,
                                  args=(uid, f"⏰ «{name}» истечёт через 7 дней. Совет: выкиньте или съешьте."),
                                  id=f"{pid}_7d", replace_existing=True)
                # за 1 день
                if nd:
                    dt1 = datetime.combine((exp_dt - timedelta(days=1)).date(),
                                           time(NOTIFY_HOUR, 0), tzinfo=TZ)
                    sched.add_job(bot.send_message, "date", run_date=dt1,
                                  args=(uid, f"⚠️ «{name}» истечёт завтра. Совет: выкиньте или съешьте."),
                                  id=f"{pid}_1d", replace_existing=True)
                # custom
                if cust:
                    dtc = datetime.fromisoformat(cust)
                    sched.add_job(bot.send_message, "date", run_date=dtc,
                                  args=(uid, f"🔔 «{name}» истечёт {dtc.strftime('%d.%m.%Y %H:%M')}.\nСовет: выкиньте или съешьте."),
                                  id=f"{pid}_cust", replace_existing=True)

# ─── UI ─────────────────────────────────────────────────────────────────────────
def main_kb(locale: str) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for txt in LOCALES[locale]["main_menu"]:
        kb.add(txt)
    return kb

# ─── HTTP-сервер для health check ───────────────────────────────────────────────
async def health(request):
    return web.Response(text="OK")

async def init_http():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"HTTP server running on port {PORT}")

# ─── Хендлеры ──────────────────────────────────────────────────────────────────
@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for code, label in [("ru","🇷🇺 Русский"),("en","🇬🇧 English"),
                        ("zh","🇨🇳 中文"),("hi","🇮🇳 हिन्दी")]:
        kb.insert(types.InlineKeyboardButton(label, callback_data=f"lang_{code}"))
    await m.answer("🌍 Выберите язык:", reply_markup=kb)
    await States.choosing_lang.set()

@dp.callback_query_handler(lambda c: c.data.startswith("lang_"), state=States.choosing_lang)
async def choose_lang(c: types.CallbackQuery, state: FSMContext):
    code = c.data.split("_",1)[1]
    await set_locale(c.from_user.id, code)
    try:
        await c.message.edit_reply_markup()
    except:
        pass
    loc = LOCALES[code]
    await c.message.answer(loc["welcome"], reply_markup=main_kb(code))
    await state.finish()

@dp.message_handler(lambda m: m.text == LOCALES[get_locale(m.from_user.id)]["main_menu"][2])
async def cmd_change_lang(m: types.Message):
    await cmd_start(m)

@dp.message_handler(lambda m: m.text == "/language")
async def cmd_language(m: types.Message):
    await cmd_start(m)

@dp.message_handler(lambda m: m.text == "/help" or
                    m.text == LOCALES[get_locale(m.from_user.id)]["main_menu"][3])
async def cmd_help(m: types.Message):
    loc = LOCALES[get_locale(m.from_user.id)]
    await m.answer(loc["help"], reply_markup=main_kb(get_locale(m.from_user.id)))

@dp.message_handler(lambda m: m.text == "/add" or
                    m.text == LOCALES[get_locale(m.from_user.id)]["main_menu"][0])
async def cmd_add(m: types.Message):
    loc = LOCALES[get_locale(m.from_user.id)]
    await States.name.set()
    await m.answer(loc["ask_name"], reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=States.name)
async def proc_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    loc = LOCALES[get_locale(m.from_user.id)]
    await States.expiration.set()
    await m.answer(loc["ask_exp"])

@dp.message_handler(state=States.expiration)
async def proc_exp(m: types.Message, state: FSMContext):
    loc = LOCALES[get_locale(m.from_user.id)]
    try:
        d = datetime.strptime(m.text.strip(), "%d.%m.%Y").date()
    except:
        return await m.answer("❌ " + loc["ask_exp"])
    dt = datetime.combine(d, time(NOTIFY_HOUR,0), tzinfo=TZ)
    await state.update_data(expiration=dt.isoformat())
    await States.notify.set()

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("1️⃣ День",  callback_data="notify_day"),
        types.InlineKeyboardButton("7️⃣ Дней", callback_data="notify_week"),
        types.InlineKeyboardButton("➕ Оба",   callback_data="notify_both")
    )
    kb.add(types.InlineKeyboardButton("⏰ Свой", callback_data="notify_custom"))
    await m.answer(loc["ask_notify"], reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("notify_"), state=States.notify)
async def proc_notify(c: types.CallbackQuery, state: FSMContext):
    choice = c.data.split("_",1)[1]
    data   = await state.get_data()
    name   = data["name"]
    exp_iso= data["expiration"]
    uid    = c.from_user.id
    loc    = LOCALES[get_locale(uid)]

    nd = choice in ("day","both")
    nw = choice in ("week","both")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO products(user_id,name,expiration_date,notify_day_before,notify_week_before,custom_time) "
            "VALUES(?,?,?,?,?,NULL)",
            (uid,name,exp_iso,int(nd),int(nw))
        )
        await db.commit()
        pid = cur.lastrowid

    exp_dt = datetime.fromisoformat(exp_iso)
    if nw:
        dt7 = datetime.combine((exp_dt - timedelta(days=7)).date(), time(NOTIFY_HOUR,0), tzinfo=TZ)
        sched.add_job(bot.send_message, "date", run_date=dt7,
                      args=(uid, f"⏰ «{name}» истечёт через 7 дней. Совет: выкиньте или съешьте."),
                      id=f"{pid}_7d", replace_existing=True)
    if nd:
        dt1 = datetime.combine((exp_dt - timedelta(days=1)).date(), time(NOTIFY_HOUR,0), tzinfo=TZ)
        sched.add_job(bot.send_message, "date", run_date=dt1,
                      args=(uid, f"⚠️ «{name}» истечёт завтра. Совет: выкиньте или съешьте."),
                      id=f"{pid}_1d", replace_existing=True)

    await c.answer()
    if choice == "custom":
        await States.custom_time.set()
        return await bot.send_message(uid, loc["ask_custom"], parse_mode="Markdown")

    await bot.send_message(uid, loc["added"], reply_markup=main_kb(get_locale(uid)))
    await state.finish()

@dp.message_handler(state=States.custom_time)
async def proc_custom(m: types.Message, state: FSMContext):
    loc = LOCALES[get_locale(m.from_user.id)]
    try:
        dt = datetime.strptime(m.text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
    except:
        return await m.answer("❌ " + loc["ask_custom"], parse_mode="Markdown")

    uid = m.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(id), name FROM products WHERE user_id = ?", (uid,)) as cur:
            pid, name = await cur.fetchone()
        await db.execute("UPDATE products SET custom_time=? WHERE id=?", (dt.isoformat(), pid))
        await db.commit()

    sched.add_job(bot.send_message, "date", run_date=dt,
                  args=(uid,
                      f"🔔 «{name}» истечёт {dt.strftime('%d.%m.%Y %H:%M')}.\nСовет: выкиньте или съешьте."
                  ),
                  id=f"{pid}_cust", replace_existing=True)

    await m.answer(loc["custom_ok"], reply_markup=main_kb(get_locale(uid)))
    await state.finish()

@dp.message_handler(lambda m: m.text == "/list" or
                    m.text == LOCALES[get_locale(m.from_user.id)]["main_menu"][1])
async def cmd_list(m: types.Message):
    uid = m.from_user.id
    loc = LOCALES[get_locale(uid)]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, expiration_date, notify_day_before, notify_week_before, custom_time "
            "FROM products WHERE user_id=? ORDER BY id",
            (uid,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await m.answer(loc["list_empty"], reply_markup=main_kb(get_locale(uid)))

    lines = []
    for name, exp_iso, nd, nw, cust in rows:
        exp_str = datetime.fromisoformat(exp_iso).strftime("%d.%m.%Y")
        parts = []
        if nd: parts.append("1д")
        if nw: parts.append("7д")
        if cust:
            parts.append(f"в {datetime.fromisoformat(cust).strftime('%d.%m %H:%M')}")
        opts = ", ".join(parts) if parts else "—"
        lines.append(f"• {name} — до {exp_str} (⏱ {opts})")

    await m.answer("\n".join(lines), reply_markup=main_kb(get_locale(uid)))

# ─── Запуск ─────────────────────────────────────────────────────────────────────
async def on_startup(dp):
    await init_db()
    await schedule_existing()
    await init_http()         # запускаем HTTP-сервер для health check
    sched.start()
    logging.info("Scheduler started")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
