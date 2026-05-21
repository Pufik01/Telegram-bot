mport asyncio
import logging
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

from config import get_token, get_ai_api_key, CEREBRAS_API_URL, MODEL_NAME

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Инициализация бота и диспетчера
bot_token = get_token()
api_key = get_ai_api_key()

bot = Bot(token=bot_token)
dp = Dispatcher()

# Клиент для HTTP запросов (переиспользуем соединение)
http_client = httpx.AsyncClient(timeout=30.0)

async def ask_cerebras(user_message: str) -> str:
    """Отправляет запрос к Cerebras API и возвращает ответ."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Ты полезный ассистент."},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 1024
    }

    try:
        response = await http_client.post(CEREBRAS_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Извлекаем текст ответа
        return data["choices"][0]["message"]["content"]
    
    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        raise Exception(f"Ошибка сервера ИИ ({e.response.status_code}). Попробуйте позже.")
    except httpx.RequestError as e:
        logging.error(f"Request Error: {e}")
        raise Exception("Не удалось соединиться с сервисом ИИ. Проверьте интернет.")
    except KeyError as e:
        logging.error(f"Unexpected API response format: {e}")
        raise Exception("Получен некорректный ответ от ИИ сервиса.")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я AI-бот на базе Cerebras.\n"
        "Напиши мне любой вопрос, и я постараюсь ответить."
    )

@dp.message()
async def handle_text(message: Message):
    if not message.text:
        return

    # Индикатор набора текста
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        # Получаем ответ от ИИ
        ai_response = await ask_cerebras(message.text)
        await message.answer(ai_response)
    
    except Exception as e:
        logging.exception("Error processing message")
        # Человеческое сообщение об ошибке пользователю
        await message.answer(
            f"⚠️ Произошла ошибка при обработке запроса: {str(e)}\n"
            "Пожалуйста, попробуйте еще раз через минуту."
        )

async def main():
    logging.info("Запуск бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await http_client.aclose()

if __name__ == "__main__":
    asyncio.run(main())