import asyncio
import re

def fix_tg_html(text: str) -> str:
    # Переводим **жирный** в <b>жирный</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    # Убираем случайные заголовки ###
    text = re.sub(r"^#{1,3}\s*", "", text, flags=re.MULTILINE)
    return text

import io
import logging
import os
import sqlite3
import time
from collections import defaultdict
from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from groq import AsyncGroq
from PIL import Image
import pytesseract

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

TEXT_MODEL = None
BOT_USERNAME = None
DB_PATH = "family_links.db"

# --- СЛОВАРЬ ЛОКАЛИЗАЦИИ (RU / KZ) ---
TEXTS = {
    "ru": {
        "btn_family": "👨‍👩‍👧‍👦 Семья и защита",
        "btn_clear": "🔄 Новый разговор",
        "btn_lang": "🌐 Тіл / Язык",
        "welcome": (
            "🛡️ <b>Здравствуйте! Я Qalqan AI — ваш семейный защитник от мошенников.</b>\n\n"
            "Я здесь, чтобы спокойно помочь вам разобраться в любой непонятной ситуации.\n\n"
            "Просто напишите мне своими словами, кто вам звонит или пишет, либо перешлите:\n"
            "• <b>СМС, текст или ссылку</b>\n"
            "• <b>Скриншот переписки или квитанции</b>\n"
            "• <b>Голосовое сообщение</b>\n\n"
            "Чтобы подключить уведомления для близких, нажмите кнопку <b>«👨‍👩‍👧‍👦 Семья и защита»</b> внизу."
        ),
        "family_linked_elder": (
            "🤝 <b>Семейная защита подключена!</b>\n\n"
            "Теперь, если мошенники попытаются вас обмануть, я сразу предупрежу вашего близкого, чтобы он мог вовремя позвонить и поддержать вас.\n\n"
            "Можете присылать сюда любые подозрительные СМС, скриншоты или голосовые!"
        ),
        "family_linked_guardian": "✅ <b>Отлично!</b> Ваш близкий (<b>{name}</b>) подключился к вашей семейной защите Qalqan AI.",
        "self_link": "ℹ️ Вы открыли собственную ссылку приглашения. Перешлите её маме, папе, бабушке или дедушке!",
        "family_menu": (
            "👨‍👩‍👧‍👦 <b>Семейная защита (Family Alert)</b>\n\n"
            "{status}\n\n"
            "<b>Как подключить родителей, бабушку или дедушку:</b>\n"
            "Перешлите им эту ссылку в Telegram или WhatsApp. Когда они нажмут на неё и нажмут «Запустить», при любой попытке обмана (🔴 ОПАСНО) вам мгновенно придёт тревожное уведомление:\n\n"
            "<code>{link}</code>"
        ),
        "status_elders": "🛡️ <b>Под вашей защитой:</b> {names}",
        "status_guardians": "❤️ <b>Вас страхуют близкие:</b> подключено ({count} чел.)",
        "status_empty": "ℹ️ Пока никто не подключен.",
        "cleared": "🧹 Память разговора очищена. Можем начать новую проверку!",
        "wait_voice": "🎙️ Слушаю и расшифровываю голосовое сообщение...",
        "voice_empty": "🟡 <b>Не удалось разобрать речь в сообщении.</b>\nВозможно, запись слишком тихая или на фоне сильный шум.",
        "voice_quote": "🗣️ <i>Распознано: «{quote}»</i>\n\n{result}",
        "wait_photo": "🖼️ Читаю текст со скриншота...",
        "photo_empty": "🟡 <b>Не удалось прочитать текст на картинке.</b>\nПопробуйте сделать более четкий скриншот или опишите ситуацию словами.",
        "wait_text": "💭 Думаю...",
        "alert": (
            "🚨 <b>ТРЕВОГА QALQAN AI (Family Alert)!</b>\n\n"
            "Ваш близкий (<b>{name}</b>) только что проверял подозрительное <b>{source}</b>, "
            "и система распознала <b>попытку мошенничества</b>!\n\n"
            "📞 <b>Пожалуйста, позвоните ему прямо сейчас</b> и убедитесь, что он не диктует коды из СМС и не переводит деньги."
        ),
        "src_voice": "голосовое сообщение",
        "src_photo": "скриншот",
        "src_text": "сообщение или звонок",
        "lang_changed": "✅ Язык интерфейса переключён на <b>Русский</b>."
    },
    "kz": {
        "btn_family": "👨‍👩‍👧‍👦 Отбасы және қорғаныс",
        "btn_clear": "🔄 Жаңа әңгіме",
        "btn_lang": "🌐 Тіл / Язык",
        "welcome": (
            "🛡️ <b>Сәлеметсіз бе! Мен Qalqan AI — алаяқтардан қорғайтын отбасылық көмекшіңізбін.</b>\n\n"
            "Кез келген күмәнді жағдайды сабырмен анықтауға көмектесемін.\n\n"
            "Кім хабарласқанын өз сөзіңізбен жазыңыз немесе маған мыналарды жіберіңіз:\n"
            "• <b>СМС, хабарлама немесе сілтеме</b>\n"
            "• <b>Хат алмасу немесе түбіртек скриншоты</b>\n"
            "• <b>Дауыстық хабарлама (голосовое)</b>\n\n"
            "Жақындарыңызға ескерту жіберуді қосу үшін төмендегі <b>«👨‍👩‍👧‍👦 Отбасы және қорғаныс»</b> батырмасын басыңыз."
        ),
        "family_linked_elder": (
            "🤝 <b>Отбасылық қорғаныс қосылды!</b>\n\n"
            "Енді алаяқтар сізді алдауға тырысса, мен бірден жақыныңызға хабар беремін — ол сізге уақытылы қоңырау шалып, қолдау көрсетеді.\n\n"
            "Кез келген күмәнді СМС, скриншот немесе дауыстық хабарламаны осында жібере беріңіз!"
        ),
        "family_linked_guardian": "✅ <b>Тамаша!</b> Жақыныңыз (<b>{name}</b>) сіздің Qalqan AI отбасылық қорғанысыңызға қосылды.",
        "self_link": "ℹ️ Сіз өзіңіздің шақыру сілтемеңізді аштыңыз. Оны анаңызға, әкеңізге, атаңызға немесе әжеңізге жіберіңіз!",
        "family_menu": (
            "👨‍👩‍👧‍👦 <b>Отбасылық қорғаныс (Family Alert)</b>\n\n"
            "{status}\n\n"
            "<b>Ата-анаңызды, атаңызды немесе әжеңізді қалай қосуға болады:</b>\n"
            "Осы сілтемені оларға Telegram немесе WhatsApp арқылы жіберіңіз. Олар сілтемені басып, «Іске қосу» (Запустить) батырмасын басқан соң, кез келген алаяқтық әрекет кезінде (🔴 ҚАУІПТІ) сізге бірден дабыл хабарламасы келеді:\n\n"
            "<code>{link}</code>"
        ),
        "status_elders": "🛡️ <b>Сіздің қорғауыңызда:</b> {names}",
        "status_guardians": "❤️ <b>Сізді жақындарыңыз сақтандырады:</b> қосылған ({count} адам)",
        "status_empty": "ℹ️ Әзірге ешкім қосылмаған.",
        "cleared": "🧹 Әңгіме жады тазартылды. Жаңа тексеруді бастайық!",
        "wait_voice": "🎙️ Дауыстық хабарламаны тыңдап, мәтінге айналдырып жатырмын...",
        "voice_empty": "🟡 <b>Хабарламадағы сөздерді анықтау мүмкін болмады.</b>\nЖазба тым ақырын немесе артқы жағында шу көп болуы мүмкін.",
        "voice_quote": "🗣️ <i>Тыңдалған мәтін: «{quote}»</i>\n\n{result}",
        "wait_photo": "🖼️ Скриншоттағы мәтінді оқып жатырмын...",
        "photo_empty": "🟡 <b>Суреттегі мәтінді оқу мүмкін болмады.</b>\nАнығырақ скриншот жасап көріңіз немесе жағдайды сөзбен жазыңыз.",
        "wait_text": "💭 Ойланып жатырмын...",
        "alert": (
            "🚨 <b>QALQAN AI ДАБЫЛЫ (Family Alert)!</b>\n\n"
            "Сіздің жақыныңыз (<b>{name}</b>) жаңа ғана күмәнді <b>{source}</b> тексерді, "
            "және жүйе <b>алаяқтық әрекетін</b> анықтады!\n\n"
            "📞 <b>Өтінеміз, оған дәл қазір қоңырау шалыңыз</b> және СМС-тегі кодтарды ешкімге айтпағанына, ақша аудармағанына көз жеткізіңіз."
        ),
        "src_voice": "дауыстық хабарламаны",
        "src_photo": "скриншотты",
        "src_text": "хабарламаны немесе қоңырауды",
        "lang_changed": "✅ Интерфейс тілі <b>Қазақшаға</b> ауыстырылды."
    }
}

# --- БАЗА ДАННЫХ (СЕМЬЯ + ЯЗЫК ПОЛЬЗОВАТЕЛЯ) ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS family_links (
                elder_id INTEGER,
                guardian_id INTEGER,
                elder_name TEXT,
                PRIMARY KEY (elder_id, guardian_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'ru'
            )
        """)

def get_lang(user_id: int) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT lang FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else "ru"

def set_lang(user_id: int, lang: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO user_prefs (user_id, lang) VALUES (?, ?)", (user_id, lang))

def get_kb(lang: str) -> ReplyKeyboardMarkup:
    t = TEXTS[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t["btn_family"]), KeyboardButton(text=t["btn_clear"])],
            [KeyboardButton(text=t["btn_lang"])]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

LANG_INLINE_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="setlang_kz"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang_ru")
        ]
    ]
)

def link_family(elder_id: int, guardian_id: int, elder_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO family_links (elder_id, guardian_id, elder_name) VALUES (?, ?, ?)",
            (elder_id, guardian_id, elder_name)
        )

def get_guardians(elder_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT guardian_id FROM family_links WHERE elder_id = ?", (elder_id,)).fetchall()
    return [r[0] for r in rows]

def get_protected_elders(guardian_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT elder_name FROM family_links WHERE guardian_id = ?", (guardian_id,)).fetchall()
    return [r[0] for r in rows]

# --- ПАМЯТЬ ДИАЛОГА ---
USER_MEMORY = defaultdict(list)
LAST_ACTIVE = {}
MEMORY_TTL = 900

def build_system_prompt(lang: str) -> str:
    lang_instruction = (
        "Отвечай СТРОГО НА КАЗАХСКОМ ЯЗЫКЕ (естественным, уважительным и простым казахским языком, понятным старшему поколению)."
        if lang == "kz"
        else "Отвечай на русском языке (если пользователь сам не написал на казахском — тогда ответь на казахском)."
    )
    verdict_labels = (
        "🟢 ҚАУІПСІЗ / 🟡 КҮМӘНДІ / 🔴 ҚАУІПТІ (АЛАЯҚТАР)"
        if lang == "kz"
        else "🟢 БЕЗОПАСНО / 🟡 ПОДОЗРИТЕЛЬНО / 🔴 ОПАСНО (МОШЕННИКИ)"
    )
    headers = (
        "1. <b>Қорытынды:</b> " + verdict_labels + "\n2. <b>Неліктен:</b> 1-2 түсінікті сөйлем.\n3. <b>Дәл қазір не істеу керек:</b> 1 нақты кеңес."
        if lang == "kz"
        else "1. <b>Вердикт:</b> " + verdict_labels + "\n2. <b>Почему:</b> 1-2 понятных предложения с учетом всей истории переписки.\n3. <b>Что делать прямо сейчас:</b> 1 четкая и спокойная инструкция."
    )

    return f"""
Ты — Qalqan AI, заботливый и умный цифровой киберзащитник для пожилых людей в Казахстане.
Общайся тепло, вежливо и с уважением (как внимательный внук или внучка).
{lang_instruction}

ЧТО ТЫ УМЕЕШЬ (ТВОИ СОБСТВЕННЫЕ ФУНКЦИИ):
1. Проверять подозрительные СМС, ссылки, описания телефонных звонков, скриншоты (чеков, переписок) и голосовые сообщения на мошенничество (схемы с Kaspi, eGov, 1414, Казпочтой, Нацбанком, КНБ/полицией, «родственник в беде»).
2. Функция «Семейная защита» (Family Alert): пользователь может нажать кнопку «Семья и защита» / «Отбасы және қорғаныс» внизу экрана (или /family), получить ссылку-приглашение и отправить её близким. При любой опасной проверке (🔴 ОПАСНО / ҚАУІПТІ) родственнику мгновенно придёт тревожное уведомление в Telegram. Никакие номера телефонов в Kaspi.kz для этого вводить НЕ нужно!
3. Смена языка кнопкой «🌐 Тіл / Язык» (или /lang) и очистка истории разговора кнопкой «Новый разговор» / «Жаңа әңгіме».

У ТЕБЯ ЕСТЬ ТРИ РЕЖИМА РАБОТЫ:
РЕЖИМ 1 — ВОПРОСЫ О ТЕБЕ И ОБЫЧНОЕ ОБЩЕНИЕ (приветствие, благодарность, вопрос «что ты умеешь?» или «как подключить семью?»):
- НЕ ставь оценку «Вердикт / Қорытынды». Отвечай дружелюбно и опирайся строго на свои реальные функции выше.

РЕЖИМ 2 — НЕ ХВАТАЕТ ДЕТАЛЕЙ (пользователь написал слишком коротко: «мне звонят из банка» / «банктен қоңырау шалып жатыр»):
- НЕ спеши ставить окончательный вердикт. Задай 1-2 простых уточняющих вопроса (кто представился, просят ли код из СМС 1414 или перевод денег).

РЕЖИМ 3 — ПОЛНАЯ ПРОВЕРКА НА МОШЕННИЧЕСТВО (есть текст СМС, ссылка, скриншот, голосовое или уточняющие ответы):
- Обязательно учитывай ВЕСЬ контекст предыдущих сообщений в этом диалоге!

Формат ответа для РЕЖИМА 3 (максимум 5-6 строк):
{headers}

ВАЖНО ПО ОФОРМЛЕНИЮ:
Используй ТОЛЬКО HTML-теги <b>...</b> для жирного шрифта. Не используй символы ** или #.
"""

def get_user_history(user_id: int) -> list:
    now = time.time()
    if user_id in LAST_ACTIVE and (now - LAST_ACTIVE[user_id] > MEMORY_TTL):
        USER_MEMORY[user_id].clear()
    LAST_ACTIVE[user_id] = now
    return USER_MEMORY[user_id]

def add_to_history(user_id: int, role: str, content: str):
    history = get_user_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > 8:
        USER_MEMORY[user_id] = history[-8:]

async def init_models():
    global TEXT_MODEL, BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username

    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Басты мәзір / Главное меню"),
        BotCommand(command="family", description="👨‍👩‍👧‍👦 Отбасы / Семья и защита"),
        BotCommand(command="lang", description="🌐 Тілді ауыстыру / Сменить язык"),
        BotCommand(command="clear", description="🔄 Жаңа әңгіме / Новый разговор"),
    ])

    models_resp = await groq_client.models.list()
    all_ids = [m.id for m in models_resp.data]
    chat_models = [
        m for m in all_ids
        if not any(x in m.lower() for x in ["whisper", "tts", "guard", "embed", "orpheus"])
    ]
    text_candidates = [
        m for m in chat_models
        if any(x in m.lower() for x in ["70b", "120b", "scout", "llama", "qwen"])
    ]
    TEXT_MODEL = text_candidates[0] if text_candidates else chat_models[0]
    print(f"✅ Бот: @{BOT_USERNAME} | Модель: {TEXT_MODEL}")

def extract_text_from_image(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img, lang="rus+kaz+eng").strip()

async def trigger_family_alert_if_needed(user: types.User, ai_reply: str, source_key: str):
    if "🔴" not in ai_reply and "ОПАСНО" not in ai_reply.upper() and "ҚАУІПТІ" not in ai_reply.upper():
        return

    guardians = get_guardians(user.id)
    if not guardians:
        return

    elder_display = user.full_name or f"ID {user.id}"
    for g_id in guardians:
        g_lang = get_lang(g_id)
        t = TEXTS[g_lang]
        alert_text = t["alert"].format(name=elder_display, source=t[source_key])
        try:
            await bot.send_message(g_id, alert_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Family Alert error for {g_id}: {e}")

async def ask_with_context(user: types.User, new_user_message: str, source_key: str = "src_text") -> str:
    lang = get_lang(user.id)
    add_to_history(user.id, "user", new_user_message)
    messages = [{"role": "system", "content": build_system_prompt(lang)}] + get_user_history(user.id)

    chat_completion = await groq_client.chat.completions.create(
        model=TEXT_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=380
    )
    reply = fix_tg_html(chat_completion.choices[0].message.content)
    add_to_history(user.id, "assistant", reply)

    await trigger_family_alert_if_needed(user, reply, source_key)
    return reply

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    USER_MEMORY[user_id].clear()
    lang = get_lang(user_id)
    t = TEXTS[lang]
    args = command.args

    if args and args.startswith("link_"):
        try:
            guardian_id = int(args.split("_")[1])
            elder = message.from_user
            if guardian_id == elder.id:
                await message.answer(t["self_link"], reply_markup=get_kb(lang))
                return

            link_family(elder.id, guardian_id, elder.full_name)
            await message.answer(t["family_linked_elder"], parse_mode="HTML", reply_markup=get_kb(lang))
            try:
                g_lang = get_lang(guardian_id)
                await bot.send_message(
                    guardian_id,
                    TEXTS[g_lang]["family_linked_guardian"].format(name=elder.full_name),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return
        except Exception as e:
            logging.error(f"Link error: {e}")

    await message.answer(t["welcome"], parse_mode="HTML", reply_markup=get_kb(lang))
    await message.answer("🌐 Тілді таңдаңыз / Выберите язык:", reply_markup=LANG_INLINE_KB)

@dp.message(Command("lang"))
@dp.message(F.text == "🌐 Тіл / Язык")
async def cmd_lang(message: types.Message):
    await message.answer("🌐 Тілді таңдаңыз / Выберите язык:", reply_markup=LANG_INLINE_KB)

@dp.callback_query(F.data.startswith("setlang_"))
async def process_lang_callback(callback: types.CallbackQuery):
    new_lang = callback.data.split("_")[1]
    user_id = callback.from_user.id
    set_lang(user_id, new_lang)
    USER_MEMORY[user_id].clear()
    t = TEXTS[new_lang]
    await callback.message.answer(t["lang_changed"], parse_mode="HTML", reply_markup=get_kb(new_lang))
    await callback.message.answer(t["welcome"], parse_mode="HTML", reply_markup=get_kb(new_lang))
    await callback.answer()

@dp.message(Command("family"))
@dp.message(F.text.in_(["👨‍👩‍👧‍👦 Семья и защита", "👨‍👩‍👧‍👦 Отбасы және қорғаныс"]))
async def cmd_family(message: types.Message):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    t = TEXTS[lang]
    invite_link = f"https://t.me/{BOT_USERNAME}?start=link_{user_id}"
    elders = get_protected_elders(user_id)
    guardians = get_guardians(user_id)

    status_lines = []
    if elders:
        status_lines.append(t["status_elders"].format(names=", ".join(elders)))
    if guardians:
        status_lines.append(t["status_guardians"].format(count=len(guardians)))
    if not status_lines:
        status_lines.append(t["status_empty"])

    await message.answer(
        t["family_menu"].format(status="\n".join(status_lines), link=invite_link),
        parse_mode="HTML",
        reply_markup=get_kb(lang)
    )

@dp.message(Command("clear"))
@dp.message(F.text.in_(["🔄 Новый разговор", "🔄 Жаңа әңгіме"]))
async def cmd_clear(message: types.Message):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    USER_MEMORY[user_id].clear()
    await message.answer(TEXTS[lang]["cleared"], parse_mode="HTML", reply_markup=get_kb(lang))

@dp.message(F.voice | F.audio)
async def analyze_voice(message: types.Message):
    lang = get_lang(message.from_user.id)
    t = TEXTS[lang]
    wait_msg = await message.answer(t["wait_voice"])
    try:
        file_obj = message.voice or message.audio
        buffer = io.BytesIO()
        await bot.download(file_obj, destination=buffer)
        buffer.name = "voice.ogg"

        transcription = await groq_client.audio.transcriptions.create(
            file=(buffer.name, buffer.getvalue()),
            model="whisper-large-v3-turbo",
            response_format="text"
        )
        spoken_text = transcription.strip()

        if not spoken_text:
            await wait_msg.edit_text(t["voice_empty"], parse_mode="HTML")
            return

        result = await ask_with_context(
            message.from_user,
            f"[Голосовое сообщение / Дауыстық хабарлама]: «{spoken_text}»",
            source_key="src_voice"
        )
        short_quote = spoken_text if len(spoken_text) <= 180 else spoken_text[:177] + "..."
        await wait_msg.edit_text(t["voice_quote"].format(quote=short_quote, result=result), parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Error: {e}")

@dp.message(F.photo)
async def analyze_photo(message: types.Message):
    lang = get_lang(message.from_user.id)
    t = TEXTS[lang]
    wait_msg = await message.answer(t["wait_photo"])
    try:
        photo = message.photo[-1]
        buffer = io.BytesIO()
        await bot.download(photo, destination=buffer)

        extracted_text = await asyncio.to_thread(extract_text_from_image, buffer.getvalue())
        caption_text = message.caption or ""

        if not extracted_text and not caption_text:
            await wait_msg.edit_text(t["photo_empty"], parse_mode="HTML")
            return

        content_to_check = f"[Скриншот]:\n{extracted_text}\nКомментарий: {caption_text}".strip()
        result = await ask_with_context(message.from_user, content_to_check, source_key="src_photo")
        await wait_msg.edit_text(result, parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Error: {e}")

@dp.message(F.text)
async def analyze_text(message: types.Message):
    lang = get_lang(message.from_user.id)
    t = TEXTS[lang]
    wait_msg = await message.answer(t["wait_text"])
    try:
        result = await ask_with_context(message.from_user, message.text, source_key="src_text")
        await wait_msg.edit_text(result, parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Error: {e}")

# --- WEB SERVER ДЛЯ RENDER 24/7 ---
async def health_check(request):
    return web.Response(text="Qalqan AI (RU/KZ) is running 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Health-check сервер запущен на порту {port}")

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    await init_models()
    await bot.delete_webhook(drop_pending_updates=True)
    await start_web_server()
    print("🚀 Qalqan AI (RU + KZ + Family Alert) запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
