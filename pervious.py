import threading
import time
import datetime
import os
import webbrowser
from difflib import SequenceMatcher
import pyautogui
import wikipedia
import speech_recognition as sr
from playsound import playsound
import socket
import webview
from functools import wraps
import requests
import asyncio
import edge_tts
from dotenv import load_dotenv
from google import genai
import json
from werkzeug.security import generate_password_hash, check_password_hash
import traceback
import queue
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

# Load API Key
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ─── Flask App ─────────────────────────
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.secret_key = 'saarthi-secret-key-2026'

USERS_FILE = 'users.json'

# ─── Live Logs for Frontend ─────────────────────────
log_queue = queue.Queue(maxsize=200)

def log_to_frontend(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    try:
        log_queue.put_nowait(log_entry)
    except queue.Full:
        pass

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('signin'))
        return f(*args, **kwargs)
    return decorated_function

recognizer = sr.Recognizer()
recognizer.energy_threshold = 150
recognizer.dynamic_energy_threshold = True

DEFAULT_MIC = None
VOICE = "en-IN-NeerjaNeural"
speaking = False
conversation = []

def is_wake_word(text):
    for word in text.split():
        if SequenceMatcher(None, word.lower(), "saarthi").ratio() > 0.75:
            return True
    return False

def internet_available():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except:
        return False

# Gemini AI - FIXED
def gemini_response(prompt):
    global conversation
    try:
        conversation.append(f"User: {prompt}")
        full_prompt = "\n".join(conversation[-8:])

        log_to_frontend("Calling Gemini AI...")

        available_models = client.models.list()
        valid_model = next(
            (m.name for m in available_models if "generateContent" in m.supported_actions), 
            None
        )

        if not valid_model:
            log_to_frontend("No valid Gemini model found!")
            return "AI model not available."

        response = client.models.generate_content(
            model=valid_model,
            contents=f"You are Saarthi, a smart Indian assistant. Keep answers short.\n{full_prompt}"
        )

        reply = getattr(response, "text", "No response from AI").strip()
        conversation.append(f"Assistant: {reply}")
        log_to_frontend(f"Gemini Response: {reply[:100]}...")

        return reply

    except Exception as e:
        log_to_frontend(f"Gemini Error: {str(e)}")
        traceback.print_exc()
        return "AI error occurred."

# Ollama AI
def ollama_response(prompt):
    global conversation
    try:
        conversation.append(f"User: {prompt}")
        full_prompt = "\n".join(conversation[-6:])

        log_to_frontend("Calling Offline Ollama...")

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3", "prompt": full_prompt, "stream": False},
            timeout=12
        )

        reply = response.json().get("response", "").strip()
        conversation.append(f"Assistant: {reply}")
        log_to_frontend(f"Ollama Response: {reply[:100]}...")

        return reply if reply else "No response from offline AI."

    except Exception as e:
        log_to_frontend(f"Ollama Error: {str(e)}")
        return "Offline AI not available."

def ai_response(prompt):
    if internet_available():
        log_to_frontend("Using Gemini (Online)")
        reply = gemini_response(prompt)
        if "error" not in reply.lower():
            return reply
    log_to_frontend("Using Ollama (Offline)")
    return ollama_response(prompt)

def speak(text):
    global speaking
    if not text or speaking:
        return
    log_to_frontend(f"Speaking: {text[:100]}...")
    speaking = True

    def run():
        global speaking
        try:
            filename = f"saarthi_{int(time.time()*1000)}.mp3"
            async def generate():
                communicate = edge_tts.Communicate(text, VOICE)
                await communicate.save(filename)
            asyncio.run(generate())
            playsound(filename)
        except Exception as e:
            log_to_frontend(f"Speech Error: {str(e)}")
        finally:
            speaking = False
            if 'filename' in locals() and os.path.exists(filename):
                os.remove(filename)

    threading.Thread(target=run, daemon=True).start()

def process_query(query):
    if not query:
        return "Sorry, I didn't catch that."

    q = query.lower().strip()
    log_to_frontend(f"Processing: {query}")

    if any(x in q for x in ['exit', 'quit', 'bye']):
        return "Goodbye Sir!"

    if 'time' in q:
        return f"It's {datetime.datetime.now().strftime('%I:%M %p')}."

    if 'date' in q:
        return f"Today is {datetime.date.today()}"

    if 'open youtube' in q:
        webbrowser.open("https://youtube.com")
        return "Opening YouTube."

    if 'open google' in q:
        webbrowser.open("https://google.com")
        return "Opening Google."

    if 'open notepad' in q:
        os.system("notepad.exe")
        return "Opening Notepad."

    if 'open calculator' in q:
        os.system("calc.exe")
        return "Opening Calculator."

    if 'volume up' in q:
        pyautogui.press('volumeup', presses=5)
        return "Volume increased."

    if 'volume down' in q:
        pyautogui.press('volumedown', presses=5)
        return "Volume decreased."

    return ai_response(q)

def listen_command():
    try:
        with sr.Microphone(device_index=DEFAULT_MIC) as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, phrase_time_limit=8)
            query = recognizer.recognize_google(audio)
            log_to_frontend(f"You said: {query}")
            reply = process_query(query)
            speak(reply)
    except Exception as e:
        log_to_frontend(f"Voice Error: {str(e)}")
        speak("Sorry, I didn't understand.")

def listen_for_wake_word():
    log_to_frontend("Wake word listener started → Say 'Saarthi'")
    while True:
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.8)
                audio = recognizer.listen(source, phrase_time_limit=5)
                text = recognizer.recognize_google(audio).lower()
                log_to_frontend(f"Heard: {text}")

                if is_wake_word(text):
                    command = text.replace("saarthi", "").strip()
                    if command:
                        speak(process_query(command))
                    else:
                        speak("Yes sir")
                        listen_command()
        except:
            pass
        time.sleep(0.1)

# Flask Routes
@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        users = load_users()
        if username in users and check_password_hash(users[username]['password'], password):
            session['logged_in'] = True
            session['username'] = username
            log_to_frontend(f"User '{username}' logged in successfully")