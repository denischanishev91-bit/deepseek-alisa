import os
import json
import uuid
import random
import asyncio
import httpx
import re
from fastapi import FastAPI, Request

app = FastAPI()

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

HISTORY_FILE = "history.json"
response_cache = {}
MAX_HISTORY_MESSAGES = 20  # Сообщений в контексте для DeepSeek

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

# Словарь для распознавания числительных прописью
WORD_TO_NUM = {
    "один": 1, "первый": 1, "одному": 1, "первого": 1,
    "два": 2, "второй": 2, "двум": 2, "второго": 2,
    "три": 3, "третий": 3, "трем": 3, "третьего": 3,
    "четыре": 4, "четвертый": 4, "четырем": 4, "четвертого": 4,
    "пять": 5, "пятый": 5, "пяти": 5, "пятого": 5,
    "шесть": 6, "шестой": 6, "шести": 6, "шестого": 6,
    "семь": 7, "седьмой": 7, "семи": 7, "седьмого": 7,
    "восемь": 8, "восьмой": 8, "восьми": 8, "восьмого": 8,
    "девять": 9, "девятый": 9, "девяти": 9, "девятого": 9,
    "десять": 10, "десятый": 10, "десяти": 10, "десятого": 10
}

# --- ФУНКЦИИ РАБОТЫ С ПАМЯТЬЮ ---
def load_data():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_data(data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка записи: {e}")

def get_user_data(data, user_id):
    """Возвращает данные пользователя, создавая базовую структуру при необходимости."""
    if user_id not in data:
        data[user_id] = {"active_chat": None, "chats": {}}
    return data[user_id]

def create_new_chat(user_id):
    """Создает новый чат и делает его активным."""
    data = load_data()
    user_data = get_user_data(data, user_id)
    
    chat_id = str(uuid.uuid4())[:6]  # Короткий ID для удобства
    user_data["chats"][chat_id] = {
        "title": "Новый диалог",
        "messages": []
    }
    user_data["active_chat"] = chat_id
    save_data(data)
    return chat_id

def add_message_to_active_chat(user_id, role, content):
    """Добавляет сообщение в активный чат пользователя."""
    data = load_data()
    user_data = get_user_data(data, user_id)
    
    active_chat = user_data.get("active_chat")
    if not active_chat or active_chat not in user_data["chats"]:
        # Если чата нет, создаем его
        chat_id = str(uuid.uuid4())[:6]
        user_data["chats"][chat_id] = {"title": "Новый диалог", "messages": []}
        user_data["active_chat"] = chat_id
        active_chat = chat_id
    
    chat = user_data["chats"][active_chat]
    chat["messages"].append({"role": role, "content": content})
    
    # Обрезаем историю
    if len(chat["messages"]) > MAX_HISTORY_MESSAGES:
        chat["messages"] = chat["messages"][-MAX_HISTORY_MESSAGES:]
        
    # Если это первое сообщение пользователя, делаем его названием чата
    if role == "user" and chat["title"] == "Новый диалог":
        chat["title"] = content[:30] + ("..." if len(content) > 30 else "")
        
    save_data(data)

def extract_number_from_text(text):
    """Пытается найти число в тексте (цифрой или прописью)."""
    text = text.lower()
    
    # Заменяем слова на цифры
    for word, num in WORD_TO_NUM.items():
        text = re.sub(r'\b' + word + r'\b', str(num), text)
        
    # Ищем первую попавшуюся цифру
    match = re.search(r'\b(\d+)\b', text)
    if match:
        return int(match.group(1))
    return None
# -----------------------------------

@app.post("/")
async def main(request: Request):
    body = await request.json()
    session_id = body["session"]["session_id"]
    user_id = body["session"]["user_id"]
    
    user_text = body.get("request", {}).get("original_utterance", "").strip()
    payload = body.get("request", {}).get("payload")

    # --- БЛОК УПРАВЛЕНИЯ ЧАТАМИ ---
    
    text_lower = user_text.lower()
    
    # 1. Создание нового чата
    if text_lower in ["новый чат", "новый диалог", "начнем сначала", "очисти память"]:
        create_new_chat(user_id)
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {"text": "Начинаем новый диалог. О чем поговорим?", "end_session": False}
        }

    # 2. Список чатов
    if text_lower in ["мои чаты", "список чатов", "какие есть чаты"]:
        data = load_data()
        user_data = get_user_data(data, user_id)
        chats = user_data["chats"]
        
        if not chats:
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {"text": "У нас пока нет сохраненных диалогов. Скажите 'Новый чат', чтобы начать.", "end_session": False}
            }
            
        chat_list_text = "Ваши сохраненные диалоги: "
        buttons = []
        for i, (chat_id, chat_info) in enumerate(chats.items(), 1):
            title = chat_info["title"]
            chat_list_text += f"{i}. {title}. "
            buttons.append({"title": f"Чат {i}", "payload": f"switch_chat_{chat_id}", "hide": False})
            
        chat_list_text += " Скажите номер чата, чтобы переключиться, или 'Удали чат и номер', чтобы удалить."
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {
                "text": chat_list_text,
                "buttons": buttons,
                "end_session": False
            }
        }

    # 3. Удаление чата ("Удали чат 2", "Удали второй диалог")
    if "удали" in text_lower and ("чат" in text_lower or "диалог" in text_lower):
        chat_num = extract_number_from_text(text_lower)
        
        if chat_num is not None:
            chat_index = chat_num - 1
            data = load_data()
            user_data = get_user_data(data, user_id)
            chats = list(user_data["chats"].items())
            
            if 0 <= chat_index < len(chats):
                chat_id, chat_info = chats[chat_index]
                title = chat_info["title"]
                
                # Удаляем чат
                del user_data["chats"][chat_id]
                
                # Если удалили активный чат, нужно сбросить или выбрать другой
                if user_data.get("active_chat") == chat_id:
                    if user_data["chats"]:
                        # Делаем активным первый попавшийся чат
                        user_data["active_chat"] = list(user_data["chats"].keys())[0]
                    else:
                        user_data["active_chat"] = None
                        
                save_data(data)
                return {
                    "version": body["version"],
                    "session": body["session"],
                    "response": {"text": f"Чат «{title}» успешно удален.", "end_session": False}
                }
            else:
                return {
                    "version": body["version"],
                    "session": body["session"],
                    "response": {"text": f"Чата с номером {chat_num} нет в списке.", "end_session": False}
                }

    # 4. Переключение по кнопке (Payload)
    if payload and payload.startswith("switch_chat_"):
        chat_id = payload.replace("switch_chat_", "")
        data = load_data()
        user_data = get_user_data(data, user_id)
        
        if chat_id in user_data["chats"]:
            user_data["active_chat"] = chat_id
            save_data(data)
            title = user_data["chats"][chat_id]["title"]
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {"text": f"Переключилась на диалог: {title}. Продолжаем?", "end_session": False}
            }

    # 5. Переключение голосом ("Включи второй чат")
    if "чат" in text_lower or "диалог" in text_lower:
        # Защита от ложного срабатывания, если человек просто болтает про чаты, 
        # но команда на переключение подразумевает наличие цифры.
        chat_num = extract_number_from_text(text_lower)
        
        if chat_num is not None:
            chat_index = chat_num - 1
            data = load_data()
            user_data = get_user_data(data, user_id)
            chats = list(user_data["chats"].items())
            
            if 0 <= chat_index < len(chats):
                chat_id, chat_info = chats[chat_index]
                user_data["active_chat"] = chat_id
                save_data(data)
                return {
                    "version": body["version"],
                    "session": body["session"],
                    "response": {"text": f"Переключилась на диалог номер {chat_num}: {chat_info['title']}. Продолжаем?", "end_session": False}
                }
            else:
                return {
                    "version": body["version"],
                    "session": body["session"],
                    "response": {"text": f"Диалога с номером {chat_num} не существует. Скажите 'Мои чаты', чтобы узнать список.", "end_session": False}
                }

    # --- ОБЫЧНЫЙ ДИАЛОГ ---

    # СЦЕНАРИЙ 1: Пользователь жмет кнопку "Продолжить"
    if text_lower in ["продолжить", "да", "слушаю", "давай"] or payload == "get_answer":
        if session_id in response_cache:
            final_answer = response_cache.pop(session_id)
            add_message_to_active_chat(user_id, "assistant", final_answer)
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {"text": final_answer, "end_session": False}
            }
        else:
            return {
                "version": body["version"],
                "session": body["session"],
                "response": {
                    "text": "Я все еще думаю, дай мне еще пару секунд.",
                    "buttons": [{"title": "Продолжить", "payload": "get_answer", "hide": False}],
                    "end_session": False
                }
            }

    if not user_text:
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {"text": "Я вас слушаю.", "end_session": False}
        }

    # СЦЕНАРИЙ 2: Новый запрос в текущий активный чат
    add_message_to_active_chat(user_id, "user", user_text)
    
    task = asyncio.create_task(fetch_deepseek_answer(session_id, user_id))

    try:
        await asyncio.wait_for(task, timeout=3.5)
        final_answer = response_cache.pop(session_id)
        add_message_to_active_chat(user_id, "assistant", final_answer)
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {"text": final_answer, "end_session": False}
        }
    except asyncio.TimeoutError:
        random_phrase = random.choice(WAIT_PHRASES)
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {
                "text": random_phrase,
                "buttons": [{"title": "Продолжить", "payload": "get_answer", "hide": False}],
                "end_session": False
            }
        }

async def fetch_deepseek_answer(session_id: str, user_id: str):
    """Запрос к DeepSeek с контекстом только активного чата."""
    data = load_data()
    user_data = get_user_data(data, user_id)
    
    active_chat_id = user_data.get("active_chat")
    if not active_chat_id or active_chat_id not in user_data["chats"]:
        history = []
    else:
        history = user_data["chats"][active_chat_id]["messages"]

    messages = [
        {"role": "system", "content": "Ты полезный голосовой ассистент. Отвечай четко, но развернуто (в пределах 3-5 предложений). Учитывай контекст текущего диалога."}
    ] + history

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-chat",
                    "messages": messages,
                    "max_tokens": 400
                },
                timeout=30.0
            )
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            if not answer.strip():
                answer = "Нейросеть задумалась и не смогла сформулировать ответ. Попробуйте переформулировать вопрос."
            response_cache[session_id] = answer
        except Exception as e:
            print(f"Ошибка DeepSeek: {e}")
            response_cache[session_id] = "Извините, произошла ошибка при обращении к нейросети."
