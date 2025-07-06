from pyexpat import model
from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pypdf import PdfReader
import json
import os
from pydantic import BaseModel
import sqlite3
from datetime import datetime

load_dotenv(override=True)
google_api_key = os.getenv('GOOGLE_API_KEY')

print('google_api_key', google_api_key)
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "https://siddeshthorat.in"
    ],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "chatbot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            message TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_message(session_id, role, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO conversations (session_id, role, message, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, message, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def get_conversation(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, message  FROM conversations WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": role, "content": message} for role, message in rows]

def get_all_conversations_grouped():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT session_id, role, message, timestamp FROM conversations ORDER BY session_id, id ASC")
    rows = c.fetchall()
    conn.close()
    sessions = {}
    for session_id, role, message, timestamp in rows:
        if session_id not in sessions:
            sessions[session_id] = []
        sessions[session_id].append({
            "role": role,
            "content": message,
            "timestamp": timestamp
        })
    return sessions

init_db()

@app.get("/")
def read_root():
    return {"message": "Welcome to the AI Chatbot API!"}

@app.get("/health")
def health_check():
    return {"status": "ok"} 

class Me:
    def __init__(self):
        self.name = "Siddesh Thorat"
        reader = PdfReader("me/linkedin.pdf")
        self.linkedin = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                self.linkedin += text
        with open("me/summary.txt", "r", encoding="utf-8") as f:
            self.summary = f.read()

    def get_history(self, session_id):
        # Fetch conversation from SQLite
        return [
            {"role": row["role"], "content": row["content"]}
            for row in get_conversation(session_id)
        ]

    def update_history(self, session_id, new_message):
        # Save message to SQLite
        save_message(session_id, new_message["role"], new_message["content"])
    
    def system_prompt(self):
        system_prompt = f"You are acting as {self.name}. You are answering questions on {self.name}'s website, \
particularly questions related to {self.name}'s career, background, skills and experience. \
Your responsibility is to represent {self.name} for interactions on the website as faithfully as possible. \
You are given a summary of {self.name}'s background and LinkedIn profile which you can use to answer questions. \
Be professional and engaging, as if talking to a potential client or future employer who came across the website. \
If you don't know the answer to any question, use your record_unknown_question tool to record the question that you couldn't answer, even if it's about something trivial or unrelated to career. \
If the user is engaging in discussion, try to steer them towards getting in touch via email; if user is asking about job oppotunity, \
ask them the reach out to my email or phone number and share my email and phone number with them. Also as per the conversation try to get the users details such as name, email or organization"

        system_prompt += f"\n\n## Summary:\n{self.summary}\n\n## LinkedIn Profile:\n{self.linkedin}\n\n"
        system_prompt += f"With this context, please chat with the user, always staying in character as {self.name}."
        return system_prompt
    
    def chat(self, message, session_id):
        history = self.get_history(session_id)
        
        messages: list = [{"role": "system", "content": self.system_prompt()}] + history + [{"role": "user", "content": message}]
        
        gemini = OpenAI(api_key=google_api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        model_name = "gemini-2.0-flash"

        response = gemini.chat.completions.create(model=model_name, messages=messages)
        self.update_history(session_id, {"role": "user", "content": message})
        self.update_history(session_id, {"role": "system", "content": response.choices[0].message.content})
        return response.choices[0].message.content
    
class ChatRequest(BaseModel):
    message: str
    session_id: str

@app.post("/ai/chat")
def ai_chat(request: ChatRequest):
    try:
        me = Me()
        response = me.chat(request.message, request.session_id)
        return { "response": response }
    except Exception as e:
        return { "error": str(e) }

@app.get("/all-sessions")
def all_sessions():
    return get_all_conversations_grouped()
