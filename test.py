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
from googlesearch import search
from functools import wraps
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify,redirect, url_for, session
import asyncio
import edge_tts
from dotenv import load_dotenv
from google import genai
import json
from werkzeug.security import generate_password_hash, check_password_hash
import traceback
import queue
#Load API Key
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ─── Globals ─────────────────────────
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.secret_key = 'saarthi-secret-key-2026'

#user storage
USERS_FILE = 'users.json'

log_queue = queue.Queue(maxsize=200)

chat_history = []

ADMIN_USERS = ["ashutosh", "anshul", "vanshika", "abhi"]

def log_to_frontend(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")

    if not isinstance(message, str):
        message = str(message)
    
    if "sdk_http_response" in message:
        return
    
    clean = message.replace("\n", " ")
    log_entry = f"[{timestamp}] {clean}"
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

# ─── Wake word detection ─────────────────────────────
def is_wake_word(text):
    wake_words = ["saarthi", "sarathi", "sarthi", "hey saarthi"]

    for w in wake_words:
        if w in text:
            return True
    return False

# ─── Internet Check ─────────────────────
def internet_available():
    try:
        socket.create_connection(("8.8.8.8",53), timeout=3)
        return True
    except:
        return False

# ─── Gemini AI ─────────────────────────
def gemini_response(prompt):
    global conversation
    try:
        conversation.append(f"User: {prompt}")
        full_prompt = "\n".join(conversation[-8:])

        available_models = client.models.list()
        valid_model = next(
            (m.name for m in available_models if "generateContent" in m.supported_actions),
            None
        )

        if not valid_model:
            return "AI model not available."

        response = client.models.generate_content(
            model=valid_model,
            contents=f"You are Saarthi, a smart Indian assistant. Keep answers short.\n{full_prompt}"
        )

        reply = ""

        try:
            reply = response.candidates[0].content.parts[0].text
        except:
            try:
                reply = response.text
            except:
                reply = ""

        if not reply:
            return "No response from AI"

        reply = str(reply).strip()

        # ✅ ONLY CLEAN TEXT LOG
        log_to_frontend("AI: " + reply.replace("\n", " "))

        return reply

    except Exception as e:
        log_to_frontend("Gemini Error: " + str(e))
        return "AI error"
    
#Ollama AI (Offline)
def ollama_response(prompt):
    global conversation
    try:
        conversation.append(f"User: {prompt}")
        full_prompt = "\n".join(conversation[-6:])

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": full_prompt,
                "stream": False
            },
            timeout=10
        )

        reply = response.json().get("response", "").strip()
        conversation.append(f"Assistant: {reply}")

        return reply if reply else "No response from offline AI."
    except Exception as e:
        print("Ollama error:", e)
        return "Offline AI not available."

# Smart AI Switch 
def ai_response(prompt):
    try:
        if internet_available():
           reply = gemini_response(prompt)
           if reply:
              return reply
           
        return ollama_response(prompt)
    except Exception as e:
        log_to_frontend(f"Ai Switch Error: {str(e)}")
        return "AI system error"


#Fallback Search
def smart_search(query):
    try:
        return wikipedia.summary(query, sentences=2)
    except:
        return "Sorry sir, I couldn't find information."

#Text To Speech
def speak(text):
    global speaking
    if not text or speaking:
        return

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
            print("Speech error:", e)

        finally:
            speaking = False
            if 'filename' in locals() and os.path.exists(filename):
                os.remove(filename)

    threading.Thread(target=run, daemon=True).start()

#Command Processor 
def process_query(query):
    if not query:
        return "Sorry, I didn't catch that."

    q = query.lower().strip()

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

    # 🤖 AI RESPONSE
    reply = ai_response(q)

    log_to_frontend(f"AI Generated: {reply}")

    return reply


# Voice Listener
def listen_command():
    try:
        with sr.Microphone(device_index=DEFAULT_MIC) as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, phrase_time_limit=8)

            query = recognizer.recognize_google(audio)
            print("You said:", query)

            log_to_frontend(f"User (voice): {query}")

            reply = process_query(query)
            
            log_to_frontend(f"User (voice): {query}")
            chat_history.append({
                "user":query,
                "assistant": reply,
                "time": datetime.datetime.now().strftime("%H:%M:%S")
            })
            
            speak(reply)

    except:
        speak("Sorry, I didn't understand.")

def listen_for_wake_word():
    print("Listening for Saarthi...")
    log_to_frontend("Wake word listener started - say 'Saarthi' to activate")

    while True:
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.8)
                audio = recognizer.listen(source, phrase_time_limit=4)
                try:
                    text = recognizer.recognize_google(audio).lower()
                    print(f"Heard:", {text})
                    log_to_frontend(f"Heard: {text}")

                    if is_wake_word(text):
                       command = text.replace("saarthi","").strip()

                       if command:
                           log_to_frontend(f"Command: {command}")

                           reply = process_query(command)
                          
                           log_to_frontend(f"Saarthi: {reply}")

                           chat_history.append({
                               "user": command,
                               "assistant": reply,
                               "time": datetime.datetime.now().strftime("%H:%M:%S")
                           })

                           speak(reply)
                       else:
                            speak("Yes sir")
                            listen_command()
                except sr.UnknownValueError:
                    pass
                except sr.RequestError:
                    print("Could not request result from Google speech Recognition")
                    time.sleep(0.8)
                except Exception as e:
                    print(f"Listener error :{e}")
                    time.sleep(0.3)

        except:
            pass


@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        users = load_users()

        if username in users and check_password_hash(users[username]['password'], password):
            session['logged_in'] = True
            session['username'] = username
            log_to_frontend(f"User '{username} logged in successfully")

            if username in ADMIN_USERS:
                session['role'] ='admin'
                return redirect(url_for('admin'))
            else:
                session['role'] = 'user'
                return redirect(url_for('index'))
        else:
            return render_template('signin.html', error="Invalid username or password!")

    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')

        if not username or not password:
            return render_template('signup.html', error="All fields are required!")
        if password != confirm:
            return render_template('signup.html',error="Passwords do not match!")
        
        users = load_users()
        if username in users:
            return render_template('signup.html', error="Username already exists!")
        
        users[username] = {'password': generate_password_hash(password)}
        save_users(users)
        log_to_frontend(f"New user registered: {username}")

        return redirect(url_for('signin'))
    
    return render_template('signup.html')

#  Flask
@app.route('/index')
@login_required
def index():
    return render_template('index.html')


@app.route('/')
def root():
    return render_template('home.html')

@app.route('/admin')
@login_required
def admin():
    username = session.get('username')
    if username not in ADMIN_USERS:
        return "Access Denied", 403
    return render_template('admin.html')

@app.route('/logout')
def logout():
    username = session.get('username', 'Unkown')
    log_to_frontend(f"User {username} logged out")
    session.clear()
    return redirect(url_for('signin'))

@app.route('/process', methods=['POST'])
@login_required
def process():
    data = request.get_json()
    query = data.get('query','')

    log_to_frontend(f"User: {query}")
    reply = f"You said: {query}"
    chat_history.append({
        "user": query,
        "assistant": reply,
        "time": datetime.datetime.now().strftime("%h:%M:%S")
    })
    log_to_frontend(f"AI: {reply}")
    speak(reply)
    return jsonify({
        'reply': reply,
        'chat': chat_history[-20:]})

@app.route('/get-chat')
@login_required
def get_chat():
    return jsonify({
        'chat': chat_history[-20:]
    })
@app.route('/get-logs')
@login_required
def get_logs():
    logs=[]
    while not log_queue.empty():
        try:
            logs.append(log_queue.get_nowait())
        except:
            break
    return jsonify({'logs': logs[-60:]})

@app.route('/home')
def homepage():
    return render_template('home.html')

@app.route('/clear-logs')
@login_required
def clear_logs():
    while not log_queue.empty():
        try:
            log_queue.get_nowait()
        except:
            pass
        log_to_frontend("Logs cleared by user")
        return jsonify({'status': 'cleared'})
@app.route('/blog')
def blog():
    return render_template('blog.html')

def start_flask():
    app.run(port=5000, debug=False, use_reloader=False)

#  Main 
if __name__ == '__main__':

    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1)

    threading.Thread(target=listen_for_wake_word, daemon=True).start()
    speak("Hello sir. Saarthi is now online.")
    
    webview.create_window(
        "Saarthi Voice Assistant",
        "http://127.0.0.1:5000/",
        width=1280,
        height=760
    )

    webview.start()