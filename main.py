import os
import uuid
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Временное хранилище для ответов от DeepSeek
# Ключ: ID сессии, Значение: готовый текст
response_cache = {}

@app.post("/")
async def main(request: Request):
    body = await request.json()
    session_id = body["session"]["session_id"]
    
    # Получаем текст от пользователя
    # Проверяем, есть ли запрос (чтобы не упасть на пустом запросе при старте)
    if "request" in body and "original_utterance" in body["request"]:
        user_text = body["request"]["original_utterance"]
    else:
        user_text = ""

    # СЦЕНАРИЙ 1: Пользователь нажал кнопку "Продолжить" или сказал "Да"
    if user_text.lower() in ["продолжить", "да", "слушаю"] or body["request"].get("payload") == "get_answer":
        if session_id in response_cache:
            # Достаем готовый ответ и очищаем кеш
            final_answer = response_cache.pop(session_id)
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {
                    "text": final_answer,
                    "end_session": False
                }
            }
        else:
            # Если ответа нет (например, DeepSeek не успел), просим подождать еще
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {
                    "text": "Я все еще думаю, подождите немного.",
                    "end_session": False
                }
            }

    # СЦЕНАРИЙ 2: Новый запрос от пользователя
    if not user_text:
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {"text": "Я вас слушаю.", "end_session": False}
        }

    # Асинхронно отправляем запрос в DeepSeek в фоне, чтобы успеть ответить Алисе за 4.5 сек
    # Мы не используем await здесь, чтобы сервер не "зависал" в ожидании
    import asyncio
    asyncio.create_task(fetch_deepseek_answer(session_id, user_text))

    # Мгновенный ответ Алисе (укладываемся в 1 секунду)
    return {
        "version": body["version"],
        "session": body["session"],
        "response": {
            "text": "Секунду, запрашиваю информацию у нейросети. Скажите 'Продолжить' или нажмите кнопку.",
            "buttons": [
                {"title": "Продолжить", "payload": "get_answer", "hide": False}
            ],
            "end_session": False
        }
    }

async def fetch_deepseek_answer(session_id: str, user_text: str):
    """Фоновая функция для запроса к DeepSeek"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": user_text}],
                    "max_tokens": 80  # Ограничиваем ответ 80 токенами
                },
                timeout=30.0 # Ждем от DeepSeek до 30 секунд в фоне
            )
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            
            # Сохраняем ответ в кеш по ID сессии
            response_cache[session_id] = answer
            
        except Exception as e:
            print(f"Ошибка DeepSeek: {e}")
            response_cache[session_id] = "Извините, произошла ошибка при обращении к нейросети."
        "response": {
            "end_session": False,
            "text": answer
        }
    }
