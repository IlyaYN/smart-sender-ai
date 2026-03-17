# --- ЖЕСТКО ЗАСТАВЛЯЕМ СИСТЕМУ ПОНИМАТЬ РУССКИЙ ЯЗЫК ---
import os
import sys

if os.environ.get("UTF8_REBOOT") != "1":
    os.environ["UTF8_REBOOT"] = "1"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.execv(sys.executable, [sys.executable] + sys.argv)
# -------------------------------------------------------

import smtplib, json, random, uvicorn, time, uuid
from datetime import datetime  
from fastapi import FastAPI
from pydantic import BaseModel
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr   
from email.header import Header      
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from google import genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class SenderSchema(BaseModel): email: str; password: str; provider: str = "gmail"
class DeleteSenderSchema(BaseModel): email: str
class KeySchema(BaseModel): name: str; api_key: str
class SingleEmailSchema(BaseModel): to_email: str; name: str; company: str; subject: str; body_template: str; ai_role: str; sender_name: str; sender_position: str; api_key: str 

def get_db():
    try:
        if not os.path.exists("senders.json"): return []
        with open("senders.json", "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def get_keys_db():
    try:
        if not os.path.exists("keys.json"): return []
        with open("keys.json", "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def get_history_db():
    try:
        if not os.path.exists("history.json"): return []
        with open("history.json", "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_to_history(email, status, body, subject=""):
    db = get_history_db()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.append({"date": current_time, "email": email, "status": status, "subject": subject, "body": body})
    db = db[-1000:] 
    with open("history.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)

@app.get("/")
def read_root(): return FileResponse("index.html")
@app.get("/get-senders")
def get_senders(): return get_db()
@app.get("/get-keys")
def get_keys(): return get_keys_db()
@app.get("/get-history")
def get_history(): return list(reversed(get_history_db()))

@app.post("/add-sender")
def add_sender(sender: SenderSchema):
    db = get_db()
    if any(s["email"].lower() == sender.email.lower() for s in db): return {"status": "error", "message": "Этот ящик уже есть!"}
    db.append({"email": sender.email, "password": sender.password, "provider": sender.provider, "active": True})
    with open("senders.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    return {"status": "success"}

@app.post("/toggle-sender")
def toggle_sender(data: dict):
    db = get_db()
    for s in db:
        if s["email"] == data["email"]: s["active"] = not s.get("active", True)
    with open("senders.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    return {"status": "success"}

@app.post("/delete-sender")
def delete_sender(data: DeleteSenderSchema):
    db = get_db()
    db = [s for s in db if s["email"] != data.email]
    with open("senders.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    return {"status": "success"}

@app.post("/add-key")
def add_key(data: KeySchema):
    db = get_keys_db()
    db.append({"name": data.name, "api_key": data.api_key, "active": True})
    with open("keys.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    return {"status": "success"}

@app.post("/toggle-key")
def toggle_key(data: dict):
    db = get_keys_db()
    for k in db:
        if k["name"] == data["name"]: k["active"] = not k.get("active", True)
    with open("keys.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    return {"status": "success"}

@app.post("/delete-key")
def delete_key(data: dict):
    db = get_keys_db()
    db = [k for k in db if k["name"] != data["name"]]
    with open("keys.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    return {"status": "success"}

@app.post("/send-single")
async def send_single(data: SingleEmailSchema):
    try:
        active_senders = [s for s in get_db() if s.get("active")]
        if not active_senders: return {"status": "error", "message": "Нет включенных ящиков!"}
        if not data.api_key: return {"status": "error", "message": "Нет API ключа!"}
            
        sender = random.choice(active_senders)
        name = data.name.strip() if data.name and str(data.name).lower() not in ['nan', 'undefined', ''] else "Уважаемый руководитель"
        comp = data.company.strip() if data.company and str(data.company).lower() not in ['nan', 'undefined', ''] else "вашей компании"
        user_prompt = data.body_template.replace("{name}", name).replace("{company}", comp)
        request_salt = str(uuid.uuid4())
        
        strict_prompt = f"""Ты — {data.ai_role}. Твоя задача — написать красивое, структурированное коммерческое письмо.

СТРОГИЕ ПРАВИЛА:
1. НИКАКИХ ЗВЕЗДОЧЕК: Используй обычное тире (-) для списков.
2. ФАКТЫ И КОНТАКТЫ — НЕПРИКОСНОВЕННЫ: Строго сохрани все контактные данные из задания. Не выдумывай цифры!
3. УНИКАЛЬНОСТЬ: ПЕРЕМЕШИВАЙ порядок услуг, используй разные эмодзи, перефразируй вступления.
4. СТРУКТУРА: Разделяй абзацы ПУСТОЙ СТРОКОЙ.
5. ФИНАЛ: "С уважением, {data.sender_name}, {data.sender_position}"
6. Не пиши слово "Тема:" в тексте.

ЗАДАНИЕ:
{user_prompt}

[SYSTEM_IGNORE: Trace_ID={request_salt} / Time={time.time()}]""" 
        
        final_body = ""
        success = False
        last_err = ""
        attempts = [('gemini-2.5-flash', 0), ('gemini-2.5-flash', random.randint(20, 35)), ('gemini-2.5-pro', random.randint(5, 15))]
        
        for model_name, delay in attempts:
            if delay > 0: time.sleep(delay)
            try:
                client = genai.Client(api_key=data.api_key)
                ai_response = client.models.generate_content(model=model_name, contents=strict_prompt)
                final_body = ai_response.text
                success = True
                break 
            except Exception as ai_err:
                err_str = str(ai_err).lower()
                last_err = str(ai_err)
                
                # Если блокировка за цензуру/опасный контент - сдаемся сразу
                if "safety" in err_str or "blocked" in err_str:
                    err_msg = f"Блокировка безопасности Google (Safety): {str(ai_err)}"
                    save_to_history(data.to_email, "Ошибка ИИ (Safety)", err_msg, data.subject)
                    return {"status": "error", "message": err_msg}
                
                # В остальных случаях (даже если Гугл чихнул или отвалился инет) - пробуем дальше!
                continue 
                    
        # Если провалились ВСЕ 3 попытки (значит ключ умер или сеть легла)
        if not success:
            return {"status": "error", "message": f"🛑 ЛИМИТ ИСЧЕРПАН ИЛИ СБОЙ! Переключаем ключ... ({last_err})"}

        subj = data.subject.replace("{name}", name).replace("{company}", comp)
        final_body = final_body.replace('**', '').replace('*', '-')
        html_body = final_body.replace('\n', '<br>')

        msg = MIMEMultipart()
        msg['From'] = formataddr((str(Header(data.sender_position, 'utf-8')), sender['email']))
        msg['To'] = data.to_email
        msg['Subject'] = subj
        msg.attach(MIMEText(html_body, 'html')) 

        srv = "smtp.gmail.com" 
        prov = sender.get("provider", "") 
        if prov == "yandex" or "yandex" in sender["email"]: srv = "smtp.yandex.ru"
        elif prov == "mailru" or "mail.ru" in sender["email"]: srv = "smtp.mail.ru"

        with smtplib.SMTP(srv, 587) as server:
            server.starttls()
            server.login(sender["email"], sender["password"])
            server.send_message(msg)
            
        save_to_history(data.to_email, "✅ Успешно", html_body, subj)
        return {"status": "success", "sender": sender["email"]}
        
    except smtplib.SMTPAuthenticationError:
        db = get_db()
        for s in db:
            if s["email"] == sender["email"]: s["active"] = False
        with open("senders.json", "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
        save_to_history(data.to_email, "❌ Ошибка авторизации SMTP", "Ящик заблокировал вход.", data.subject)
        return {"status": "error", "message": f"Ящик {sender['email']} не пускает. ОТКЛЮЧЕН."}
        
    except Exception as e:
        save_to_history(data.to_email, "❌ Ошибка SMTP", str(e), data.subject)
        return {"status": "error", "message": f"Ошибка SMTP: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)