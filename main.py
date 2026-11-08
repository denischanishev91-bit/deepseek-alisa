import os
import json
import uuid
import random
import asyncio
import httpx
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
# -----------------------------------

@app.post("/")
async def main(request: Request):
    body = await request.json()
    session_id = body["session"]["session_id"]
    user_id = body["session"]["user_id"]
    
    user_text = body.get("request", {}).get("original_utterance", "").strip()
    payload = body.get("request", {}).get("payload")

    # --- ОБРАБОТКА КОМАНД УПРАВЛЕНИЯ ЧАТАМИ ---
    
    # 1. Создание нового чата
    if user_text.lower() in ["новый чат", "новый диалог", "начнем сначала", "очисти память"]:
        create_new_chat(user_id)
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {"text": "Начинаем новый диалог. О чем поговорим?", "end_session": False}
        }

    # 2. Список чатов
    if user_text.lower() in ["мои чаты", "список чатов", "какие есть чаты"]:
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
            
        chat_list_text += " Скажите номер чата или нажмите кнопку."
        return {
            "version": body["version"],
            "session": body["session"],
            "response": {
                "text": chat_list_text,
                "buttons": buttons,
                "end_session": False
            }
        }

    # 3. Переключение по кнопке (Payload)
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

    # 4. Переключение голосом ("Чат 1", "Включи чат 2")
    if user_text.lower().startswith("чат ") or user_text.lower().startswith("переключись на чат "):
        try:
            num_str = user_text.lower().replace("переключись на чат ", "").replace("чат ", "").strip()
            chat_index = int(num_str) - 1
            
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
                    "response": {"text": f"Переключилась на диалог: {chat_info['title']}. Продолжаем?", "end_session": False}
                }
            else:
                return {
                    "version": body["version"],
                    "session": body["session"],
                    "response": {"text": "Чата с таким номером не существует. Скажите 'Мои чаты', чтобы узнать список.", "end_session": False}
                }
        except ValueError:
            pass # Если не смогли распарсить номер, идем дальше как в обычный чат

    # --- ОБЫЧНЫЙ ДИАЛОГ ---

    # СЦЕНАРИЙ 1: Пользователь жмет кнопку "Продолжить"
    if user_text.lower() in ["продолжить", "да", "слушаю", "давай"] or payload == "get_answer":
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
