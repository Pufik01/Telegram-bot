import asyncio
import logging
import httpx
import sqlite3
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from config import get_token, get_ai_api_key, CEREBRAS_API_URL, MODEL_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

bot_token = get_token()
api_key = get_ai_api_key()

bot = Bot(token=bot_token)
dp = Dispatcher()
http_client = httpx.AsyncClient(timeout=60.0)
scheduler = AsyncIOScheduler()

def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, habit_name TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS habit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, habit_name TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reminder_text TEXT, remind_time TIMESTAMP)")
    conn.commit()
    conn.close()

init_db()

class Form(StatesGroup):
    waiting_for_reminder = State()
    waiting_for_habit = State()
    waiting_for_dilemma = State()
    waiting_for_psychologist = State()
    waiting_for_ai = State()
    waiting_for_market_query = State()

def get_main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🤖 ИИ Ассистент")],
        [KeyboardButton(text="⏰ Напоминания")],
        [KeyboardButton(text="💚 Психологическая поддержка")],
        [KeyboardButton(text="📊 Трекер привычек")],
        [KeyboardButton(text="🎯 Бот-консилиум")],
        [KeyboardButton(text="💼 Мои услуги")],
    ], resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Главное меню")]], resize_keyboard=True)

async def ask_cerebras(user_message: str, system_prompt: str = "Ты полезный ассистент.") -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": MODEL_NAME, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}], "temperature": 0.7, "max_tokens": 1500}
    try:
        response = await http_client.post(CEREBRAS_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"AI Error: {e}")
        raise Exception(f"Ошибка ИИ: {str(e)}")

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Привет! Я многофункциональный AI-бот!\n\nВыберите функцию:\n\n🤖 ИИ Ассистент\n⏰ Напоминания\n💚 Психологическая поддержка\n📊 Трекер привычек\n🎯 Бот-консилиум\n💼 Мои услуги", reply_markup=get_main_keyboard())

@dp.message(F.text == "🔙 Главное меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_keyboard())

@dp.message(F.text == "🤖 ИИ Ассистент")
async def ai_assistant(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_ai)
    await message.answer("🤖 ИИ Ассистент активирован! Задайте вопрос.\nДля выхода: 🔙 Главное меню", reply_markup=get_back_keyboard())

@dp.message(Form.waiting_for_ai)
async def handle_ai_message(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        response = await ask_cerebras(message.text)
        await message.answer(response)
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")

@dp.message(F.text == "⏰ Напоминания")
async def reminders_menu(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_reminder)
    await message.answer("⏰ Напишите: напомни мне в 16:38 пойти в больницу\nДля выхода: 🔙 Главное меню", reply_markup=get_back_keyboard())

@dp.message(Form.waiting_for_reminder)
async def handle_reminder(message: Message):
    text = message.text.lower()
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        await message.answer("⚠️ Не нашёл время. Пример: напомни мне в 16:38")
        return
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        await message.answer("⚠️ Некорректное время")
        return
    now = datetime.now()
    remind_time = now.replace(hour=hour, minute=minute, second=0)
    if remind_time <= now:
        remind_time += timedelta(days=1)
    reminder_text = re.sub(r"напомни\s*(мне)?\s*в\s*\d{1,2}:\d{2}\s*", "", text, flags=re.IGNORECASE).strip() or "Ваше напоминание"
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (user_id, reminder_text, remind_time) VALUES (?, ?, ?)", (message.from_user.id, reminder_text, remind_time))
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    scheduler.add_job(send_reminder, trigger=DateTrigger(run_date=remind_time), args=[message.from_user.id, reminder_id, reminder_text], id=f"reminder_{reminder_id}")
    await message.answer(f"✅ Напоминание создано!\n📝 {reminder_text}\n⏰ {remind_time.strftime('%d.%m.%Y %H:%M')}")

async def send_reminder(user_id: int, reminder_id: int, text: str):
    try:
        await bot.send_message(chat_id=user_id, text=f"⏰ Напоминание!\n\n{text}")
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Reminder error: {e}")

@dp.message(F.text == "💚 Психологическая поддержка")
async def psychologist_menu(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_psychologist)
    await message.answer("💚 Психологическая поддержка (первая линия)\n\n⚠️ Важно: Я не заменяю терапию.\n\n🆘 Экстренные контакты (Россия):\n- Телефон доверия: 8-800-2000-122\n- МЧС: 112\n- Скорая: 103\n\nВыберите: 🌬️ Дыхание | 🔄 Рефрейминг | 💬 Поговорить", reply_markup=get_back_keyboard())

@dp.message(Form.waiting_for_psychologist)
async def handle_psychologist(message: Message):
    if message.text == "🌬️":
        await message.answer("🌬️ Дыхательная техника 4-7-8:\n1. Вдох на 4 счёта\n2. Задержка на 7 счетов\n3. Выдох на 8 счетов\nПовторите 4-5 циклов.")
        return
    if message.text == "🔄":
        await message.answer("🔄 Рефрейминг: Опишите ситуацию, и я помогу найти альтернативный взгляд.")
        return
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        response = await ask_cerebras(message.text, "Ты эмпатичный психолог первой линии. Поддержи, предложи техники самопомощи, напоминай что ты не заменяешь терапию.")
        await message.answer(response)
    except Exception as e:
        await message.answer("💚 Я здесь. Попробуйте технику 🌬️")

@dp.message(F.text == "📊 Трекер привычек")
async def habits_menu(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_habit)
    await message.answer("📊 Трекер привычек\n\n➕ добавь привычку пить воду\n✅ выпил воду - отметить\n📈 статистика\n🗑️ удали привычку\n\nДля выхода: 🔙 Главное меню", reply_markup=get_back_keyboard())

@dp.message(Form.waiting_for_habit)
async def handle_habit(message: Message):
    text = message.text.lower()
    user_id = message.from_user.id
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    if text.startswith("добавь привычку") or text.startswith("добавить привычку"):
        habit_name = text.replace("добавь привычку", "").replace("добавить привычку", "").strip()
        if habit_name:
            cursor.execute("INSERT INTO habits (user_id, habit_name) VALUES (?, ?)", (user_id, habit_name))
            conn.commit()
            await message.answer(f"✅ Привычка '{habit_name}' добавлена!")
    elif text.startswith("удали привычку") or text.startswith("удалить привычку"):
        habit_name = text.replace("удали привычку", "").replace("удалить привычку", "").strip()
        if habit_name:
            cursor.execute("DELETE FROM habits WHERE user_id = ? AND habit_name = ?", (user_id, habit_name))
            conn.commit()
            await message.answer("🗑️ Привычка удалена!")
    elif text == "статистика":
        cursor.execute("SELECT habit_name, COUNT(*) FROM habit_logs WHERE user_id = ? GROUP BY habit_name", (user_id,))
        stats = cursor.fetchall()
        if stats:
            await message.answer("📈 Статистика:\n" + "\n".join([f"{h}: {c} раз" for h, c in stats]))
        else:
            await message.answer("📊 Пока нет статистики")
    elif text.startswith("список") or text == "привычки":
        cursor.execute("SELECT habit_name FROM habits WHERE user_id = ?", (user_id,))
        habits = cursor.fetchall()
        if habits:
            await message.answer("📝 Привычки:\n" + "\n".join([f"• {h[0]}" for h in habits]))
        else:
            await message.answer("📝 Нет привычек")
    else:
        cursor.execute("SELECT habit_name FROM habits WHERE user_id = ?", (user_id,))
        habits = [h[0] for h in cursor.fetchall()]
        found = False
        for habit in habits:
            if habit.lower() in text:
                cursor.execute("INSERT INTO habit_logs (user_id, habit_name) VALUES (?, ?)", (user_id, habit))
                conn.commit()
                cursor.execute("SELECT COUNT(*) FROM habit_logs WHERE user_id = ? AND habit_name = ?", (user_id, habit))
                count = cursor.fetchone()[0]
                await message.answer(f"✅ '{habit}' выполнено {count} раз! 💪")
                found = True
                break
        if not found:
            await message.answer("⚠️ Не понял. Пример: выпил воду")
    conn.close()

@dp.message(F.text == "🎯 Бот-консилиум")
async def consilium_menu(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_dilemma)
    await message.answer("🎯 Бот-консилиум\nОпишите дилемму, и я дам 5 взглядов:\n🧠 Прагматик | 💚 Эмпат | 💰 Инвестор | 🛡️ Консерватор | 🚀 Новатор\n\nДля выхода: 🔙 Главное меню", reply_markup=get_back_keyboard())

@dp.message(Form.waiting_for_dilemma)
async def handle_dilemma(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        response = await ask_cerebras(message.text, "Ты бот-консилиум. Для ситуации давай 5 перспектив: 1) 🧠 ПРАГМАТИК - факты 2) 💚 ЭМПАТ - чувства 3) 💰 ИНВЕСТОР - выгода/риски 4) 🛡️ КОНСЕРВАТОР - безопасность 5) 🚀 НОВАТОР - возможности. Краткий анализ и рекомендация для каждой.")
        await message.answer(response)
    except Exception as e:
        await message.answer("⚠️ Ошибка. Попробуйте ещё раз.")

@dp.message(F.text == "💼 Мои услуги")
async def market_menu(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_market_query)
    await message.answer("""
💼 МОИ УСЛУГИ

🤖 ИИ-ассистент - Бесплатно
⏰ Напоминания - 99₽/мес
💚 Психологическая поддержка - 499₽/сессия
📊 Трекер привычек PRO - 199₽/мес
🎯 Бот-консилиум - 299₽/запрос
📦 ВСЁ ВКЛЮЧЕНО - 799₽/мес

💳 Оплата: Карта РФ, СБП, Крипта
📩 Заказ: @support_manager

*Цены ориентировочные*""", reply_markup=get_back_keyboard())

@dp.message(Form.waiting_for_market_query)
async def handle_market_query(message: Message):
    await message.answer("💼 Для заказа: @support_manager", reply_markup=get_back_keyboard())

@dp.message()
async def handle_default(message: Message):
    await message.answer("Выберите функцию из меню. Нажмите /start", reply_markup=get_main_keyboard())

async def main():
    logging.info("Запуск бота...")
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        await http_client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
