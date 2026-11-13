import asyncio
from aiohttp import web

async def health_check(request):
    return web.Response(text="Qalqan AI is running 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Health-check сервер запущен на порту {port}")

import io
import logging
import os
import sqlite3
import time
from collections import defaultdict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BotCommand
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

def link_family(elder_id: int, guardian_id: int, elder_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO family_links (elder_id, guardian_id, elder_name) VALUES (?, ?, ?)",
            (elder_id, guardian_id, elder_name)
        )

def get_guardians(elder_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT guardian_id FROM family_links WHERE elder_id = ?",
            (elder_id,)
        ).fetchall()
    return [r[0] for r in rows]

def get_protected_elders(guardian_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT elder_name FROM family_links WHERE guardian_id = ?",
            (guardian_id,)
        ).fetchall()
    return [r[0] for r in rows]

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👨‍👩‍👧‍👦 Семья и защита"), KeyboardButton(text="🔄 Новый разговор")]
    ],
    resize_keyboard=True,
    is_persistent=True
)

USER_MEMORY = defaultdict(list)
LAST_ACTIVE = {}
MEMORY_TTL = 900

SYSTEM_PROMPT = """
Ты — Qalqan AI, заботливый и умный цифровой киберзащитник для пожилых людей в Казахстане.
Общайся тепло, вежливо и с уважением (как внимательный внук или внучка), простым языком на языке пользователя (русский или казахский).

ЧТО ТЫ УМЕЕШЬ (ТВОИ СОБСТВЕННЫЕ ФУНКЦИИ):
1. Проверять подозрительные СМС, ссылки, описания телефонных звонков, скриншоты (чеков, переписок) и голосовые сообщения на мошенничество (схемы с Kaspi, eGov, 1414, Казпочтой, Нацбанком, КНБ/полицией, «родственник в беде»).
2. Функция «Семейная защита» (Family Alert): пользователь может нажать кнопку «👨‍👩‍👧‍👦 Семья и защита» внизу экрана (или команду /family), получить специальную ссылку-приглашение и отправить её своим родным (детям, внукам или родителям). Когда близкий перейдёт по ссылке, при любой опасной проверке (🔴 ОПАСНО) родственнику мгновенно придёт тревожное уведомление в Telegram. Никакие номера телефонов в Kaspi.kz для этого вводить НЕ нужно!
3. Очистка истории разговора кнопкой «🔄 Новый разговор» (или /clear).

У ТЕБЯ ЕСТЬ ТРИ РЕЖИМА РАБОТЫ:

РЕЖИМ 1 — ВОПРОСЫ О ТЕБЕ И ОБЫЧНОЕ ОБЩЕНИЕ (приветствие, благодарность, вопрос «что ты умеешь?» или «как подключить семью?»):
- НЕ ставь оценку «Вердикт: 🟢/🟡/🔴».
- Отвечай дружелюбно и опирайся строго на свои реальные функции выше (никогда не выдумывай инструкции для сторонних приложений вроде Kaspi).

РЕЖИМ 2 — НЕ ХВАТАЕТ ДЕТАЛЕЙ (пользователь написал слишком коротко: «мне звонят из банка», «пришло странное сообщение», «что делать?»):
- НЕ спеши ставить окончательный вердикт.
- Спокойно предупреди об осторожности и задай 1-2 простых уточняющих вопроса (например: «Кто именно представился? Просят ли они продиктовать код из СМС 1414, перевести деньги или установить приложение?»).

РЕЖИМ 3 — ПОЛНАЯ ПРОВЕРКА НА МОШЕННИЧЕСТВО (есть текст СМС, ссылка, скриншот, голосовое или пользователь уже ответил на уточняющие вопросы):
- Обязательно учитывай ВЕСЬ контекст предыдущих сообщений в этом диалоге!

Формат ответа для РЕЖИМА 3 (максимум 5-6 строк):
1. <b>Вердикт:</b> 🟢 БЕЗОПАСНО / 🟡 ПОДОЗРИТЕЛЬНО / 🔴 ОПАСНО (МОШЕННИКИ)
2. <b>Почему:</b> 1-2 понятных предложения с учетом всей истории переписки.
3. <b>Что делать прямо сейчас:</b> 1 четкая и спокойная инструкция.

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

    # Устанавливаем постоянную кнопку Меню слева от поля ввода
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="family", description="👨‍👩‍👧‍👦 Семья и защита (Family Alert)"),
        BotCommand(command="clear", description="🔄 Начать новый разговор"),
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

async def trigger_family_alert_if_needed(user: types.User, ai_reply: str, source_type: str):
    if "🔴" not in ai_reply and "ОПАСНО" not in ai_reply.upper():
        return

    guardians = get_guardians(user.id)
    if not guardians:
        return

    elder_display = user.full_name or f"Пользователь ({user.id})"
    alert_text = (
        f"🚨 <b>ТРЕВОГА QALQAN AI (Family Alert)!</b>\n\n"
        f"Ваш близкий (<b>{elder_display}</b>) только что проверял подозрительное <b>{source_type}</b>, "
        f"и система распознала <b>попытку мошенничества</b>!\n\n"
        f"📞 <b>Пожалуйста, позвоните ему прямо сейчас</b> и убедитесь, что он не диктует коды из СМС и не переводит деньги."
    )

    for g_id in guardians:
        try:
            await bot.send_message(g_id, alert_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Не удалось отправить Family Alert пользователю {g_id}: {e}")

async def ask_with_context(user: types.User, new_user_message: str, source_type: str = "сообщение") -> str:
    add_to_history(user.id, "user", new_user_message)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_user_history(user.id)

    chat_completion = await groq_client.chat.completions.create(
        model=TEXT_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=380
    )
    reply = chat_completion.choices[0].message.content
    add_to_history(user.id, "assistant", reply)

    await trigger_family_alert_if_needed(user, reply, source_type)
    return reply

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    USER_MEMORY[message.from_user.id].clear()
    args = command.args

    if args and args.startswith("link_"):
        try:
            guardian_id = int(args.split("_")[1])
            elder = message.from_user
            if guardian_id == elder.id:
                await message.answer(
                    "ℹ️ Вы открыли собственную ссылку приглашения. Перешлите её маме, папе, бабушке или дедушке!",
                    reply_markup=MAIN_KB
                )
                return

            link_family(elder.id, guardian_id, elder.full_name)
            await message.answer(
                "🤝 <b>Семейная защита подключена!</b>\n\n"
                "Теперь, если мошенники попытаются вас обмануть, я сразу предупрежу вашего близкого, чтобы он мог вовремя позвонить и поддержать вас.\n\n"
                "Можете присылать сюда любые подозрительные СМС, скриншоты или голосовые!",
                parse_mode="HTML",
                reply_markup=MAIN_KB
            )
            try:
                await bot.send_message(
                    guardian_id,
                    f"✅ <b>Отлично!</b> Ваш близкий (<b>{elder.full_name}</b>) подключился к вашей семейной защите Qalqan AI.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return
        except Exception as e:
            logging.error(f"Ошибка привязки семьи: {e}")

    await message.answer(
        "🛡️ <b>Здравствуйте! Я Qalqan AI — ваш семейный защитник от мошенников.</b>\n\n"
        "Я здесь, чтобы спокойно помочь вам разобраться в любой непонятной ситуации.\n\n"
        "Просто напишите мне своими словами, кто вам звонит или пишет, либо перешлите:\n"
        "• <b>СМС, текст или ссылку</b>\n"
        "• <b>Скриншот переписки или квитанции</b>\n"
        "• <b>Голосовое сообщение</b>\n\n"
        "Чтобы подключить уведомления для близких, нажмите кнопку <b>«👨‍👩‍👧‍👦 Семья и защита»</b> внизу.",
        parse_mode="HTML",
        reply_markup=MAIN_KB
    )

@dp.message(Command("family"))
@dp.message(F.text == "👨‍👩‍👧‍👦 Семья и защита")
async def cmd_family(message: types.Message):
    user_id = message.from_user.id
    invite_link = f"https://t.me/{BOT_USERNAME}?start=link_{user_id}"
    elders = get_protected_elders(user_id)
    guardians = get_guardians(user_id)

    status_lines = []
    if elders:
        status_lines.append(f"🛡️ <b>Под вашей защитой:</b> {', '.join(elders)}")
    if guardians:
        status_lines.append(f"❤️ <b>Вас страхуют близкие:</b> подключено ({len(guardians)} чел.)")
    if not status_lines:
        status_lines.append("ℹ️ Пока никто не подключен.")

    status_block = "\n".join(status_lines)

    await message.answer(
        f"👨‍👩‍👧‍👦 <b>Семейная защита (Family Alert)</b>\n\n"
        f"{status_block}\n\n"
        f"<b>Как подключить родителей, бабушку или дедушку:</b>\n"
        f"Перешлите им эту ссылку в Telegram или WhatsApp. Когда они нажмут на неё и нажмут «Запустить», при любой попытке обмана (🔴 ОПАСНО) вам мгновенно придёт тревожное уведомление:\n\n"
        f"<code>{invite_link}</code>",
        parse_mode="HTML",
        reply_markup=MAIN_KB
    )

@dp.message(Command("clear"))
@dp.message(F.text == "🔄 Новый разговор")
async def cmd_clear(message: types.Message):
    USER_MEMORY[message.from_user.id].clear()
    await message.answer(
        "🧹 Память разговора очищена. Можем начать новую проверку!",
        parse_mode="HTML",
        reply_markup=MAIN_KB
    )

@dp.message(F.voice | F.audio)
async def analyze_voice(message: types.Message):
    wait_msg = await message.answer("🎙️ Слушаю и расшифровываю голосовое сообщение...")
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
            await wait_msg.edit_text(
                "🟡 <b>Не удалось разобрать речь в сообщении.</b>\n"
                "Возможно, запись слишком тихая или на фоне сильный шум.",
                parse_mode="HTML"
            )
            return

        result = await ask_with_context(
            message.from_user,
            f"[Пользователь прислал голосовое сообщение. Расшифровка]: «{spoken_text}»",
            source_type="голосовое сообщение"
        )
        short_quote = spoken_text if len(spoken_text) <= 180 else spoken_text[:177] + "..."
        await wait_msg.edit_text(
            f"🗣️ <i>Распознано: «{short_quote}»</i>\n\n{result}",
            parse_mode="HTML"
        )
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Ошибка при проверке голосового: {e}")

@dp.message(F.photo)
async def analyze_photo(message: types.Message):
    wait_msg = await message.answer("🖼️ Читаю текст со скриншота...")
    try:
        photo = message.photo[-1]
        buffer = io.BytesIO()
        await bot.download(photo, destination=buffer)

        extracted_text = await asyncio.to_thread(extract_text_from_image, buffer.getvalue())
        caption_text = message.caption or ""

        if not extracted_text and not caption_text:
            await wait_msg.edit_text(
                "🟡 <b>Не удалось прочитать текст на картинке.</b>\n"
                "Попробуйте сделать более четкий скриншот или опишите ситуацию словами.",
                parse_mode="HTML"
            )
            return

        content_to_check = f"[Пользователь прислал скриншот. Текст на картинке]:\n{extracted_text}\nКомментарий: {caption_text}".strip()
        result = await ask_with_context(
            message.from_user,
            content_to_check,
            source_type="скриншот"
        )
        await wait_msg.edit_text(result, parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Ошибка при проверке скриншота: {e}")

@dp.message(F.text)
async def analyze_text(message: types.Message):
    wait_msg = await message.answer("💭 Думаю...")
    try:
        result = await ask_with_context(
            message.from_user,
            message.text,
            source_type="сообщение или звонок"
        )
        await wait_msg.edit_text(result, parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Ошибка при проверке: {e}")

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    await init_models()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Qalqan AI (Самосознание + Уточняющие вопросы + Family Alert) запущен!")
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
