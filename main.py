import os
import uuid
import random
import asyncio
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Хранилище ответов
response_cache = {}

# Список случайных фраз для разбавления ожидания
WAIT_PHRASES = [
    "Так, нейроны зашевелились, секунду...",
    "Уже гуглю в своих тайных знаниях...",
    "Мозг кипит, подожди чуть-чуть...",
    "Секунду, консультируюсь с цифровыми духами...",
    "Обрабатываю запрос. Не переключайтесь!",
    "Мои алгоритмы напряглись. Секунду...",
    "Загружаю ответ из глубин подсознания...",
    "Так, сейчас найду нужную информацию в своих терабайтах..."
]

@app.post("/")
async def main(request: Request):
    body = await request.json()
    session_id = body["session"]["session_id"]
    
    # Получаем текст от пользователя
    if "request" in body and "original_utterance" in body["request"]:
        user_text = body["request"]["original_utterance"]
    else:
        user_text = ""

    # СЦЕНАРИЙ 1: Пользователь жмет кнопку "Продолжить" или говорит "Да"
    if user_text.lower() in ["продолжить", "да", "слушаю", "давай"] or body["request"].get("payload") == "get_answer":
        if session_id in response_cache:
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
            # Если DeepSeek все еще думает
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {
                    "text": "Я все еще думаю, дай мне еще пару секунд.",
                    "buttons": [{"title": "Продолжить", "payload": "get_answer", "hide": False}],
                    "end_session": False
                }
            }

    # СЦЕНАРИЙ 2: Новый запрос
    if not user_text:
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {"text": "Я вас слушаю.", "end_session": False}
        }

    # Запускаем запрос к DeepSeek в фоне
    task = asyncio.create_task(fetch_deepseek_answer(session_id, user_text))

    # Ждем максимум 3.5 секунды. Если DeepSeek успел - отдаем сразу, если нет - шутим.
    try:
        # Ждем завершения задачи не более 3.5 секунд
        await asyncio.wait_for(task, timeout=3.5)
        
        # Если дошли сюда, значит DeepSeek ответил быстро
        final_answer = response_cache.pop(session_id)
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {
                "text": final_answer,
                "end_session": False
            }
        }
    except asyncio.TimeoutError:
        # Если не успел - выбираем случайную фразу
        random_phrase = random.choice(WAIT_PHRASES)
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {
                "text": f"{random_phrase}",
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
                    "messages": [
                        # Можно добавить системный промпт, чтобы ответы были лаконичными, но емкими
                        {"role": "system", "content": "Ты полезный голосовой ассистент. Отвечай четко, но развернуто (в пределах 3-5 предложений)."},
                        {"role": "user", "content": user_text}
                    ],
                    "max_tokens": 400  # Увеличили лимит до 400 токенов
                },
                timeout=30.0
            )
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            
            # Если по какой-то причине пришел пустой ответ
            if not answer.strip():
                answer = "Нейросеть задумалась и не смогла сформулировать ответ. Попробуйте переформулировать вопрос."
                
            response_cache[session_id] = answer
            
        except Exception as e:
            print(f"Ошибка DeepSeek: {e}")
            response_cache[session_id] = "Извините, произошла ошибка при обращении к нейросети."
