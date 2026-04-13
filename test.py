import threading
import time
import datetime
import os
import webbrowser
from difflib import SequenceMatcher
import pyautogui
import speech_recognition as sr
from playsound import playsound
import socket
import webview
from googlesearch import search
from functools import wraps
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import asyncio
import edge_tts
from dotenv import load_dotenv
from google import genai
from mysql.connector import pooling, Error
from werkzeug.security import generate_password_hash, check_password_hash
import queue
from groq import Groq
from collections import OrderedDict
from contextlib import contextmanager

# ─── Load API Key ───
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ─── Globals ───
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.secret_key = 'saarthi-secret-key-2026'

# FIX 1: LRU TTS cache with eviction (max 50 entries, prevents disk/memory leak)
MAX_TTS_CACHE = 50
tts_cache = OrderedDict()

# ─── DB Config ───
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'saarthi_db')
}

ADMIN_USERS = []
ADMIN_PASSWORDS = {}

i = 1
while True:
    username = os.getenv(f'ADMIN_{i}_USERNAME')
    password = os.getenv(f'ADMIN_{i}_PASSWORD')
    if not username or not password:
        break
    ADMIN_USERS.append(username)
    ADMIN_PASSWORDS[username] = password
    i += 1

print(f"✅ Loaded {len(ADMIN_USERS)} admin users from .env")

# ─── DB Connection Pool ───
try:
    connection_pool = pooling.MySQLConnectionPool(
        pool_name="saarthi_pool",
        pool_size=10,
        **DB_CONFIG
    )
    print("✅ MySQL Connection Pool Created Successfully")
except Error as err:
    print(f"❌ MySQL Connection Error: {err}")
    connection_pool = None

def get_db_connection():
    if connection_pool is None:
        raise Exception("Database connection pool not available")
    return connection_pool.get_connection()

# FIX 2: Context manager for DB — auto-closes connection always
@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass

def create_tables():
    """Create users and feedback tables"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role ENUM('user', 'admin') DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    email VARCHAR(150) NOT NULL,
                    message TEXT NOT NULL,
                    rating INT DEFAULT 3,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            cursor.close()
            print("✅ Database tables created successfully")
    except Error as err:
        print(f"❌ Table creation error: {err}")

def create_admin_users():
    """Create or update admin users from .env file"""
    if not ADMIN_USERS:
        return
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            for username in ADMIN_USERS:
                raw_password = ADMIN_PASSWORDS.get(username)
                if not raw_password:
                    continue
                hashed_password = generate_password_hash(raw_password)
                cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    cursor.execute("""
                        UPDATE users SET password = %s, role = 'admin'
                        WHERE username = %s
                    """, (hashed_password, username))
                    print(f"🔄 Updated admin user: {username}")
                else:
                    cursor.execute("""
                        INSERT INTO users (username, password, role)
                        VALUES (%s, %s, 'admin')
                    """, (username, hashed_password))
                    print(f"✅ Created new admin user: {username}")
            conn.commit()
            cursor.close()
    except Error as err:
        print(f"❌ Admin user creation error: {err}")


log_queue = queue.Queue(maxsize=200)

# FIX 3: chat_history capped at 100 to prevent memory leak
MAX_CHAT_HISTORY = 100
chat_history = []

# FIX 4: conversation capped globally
MAX_CONVERSATION = 10
conversation = []

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

# FIX 5: TTS queue so replies are never silently dropped
tts_queue = queue.Queue()

# FIX 6: Cache Gemini model at startup — avoid re-fetching on every call
GEMINI_MODEL = None

def init_gemini_model():
    global GEMINI_MODEL
    try:
        available_models = client.models.list()
        GEMINI_MODEL = next(
            (m.name for m in available_models if "generateContent" in m.supported_actions),
            None
        )
        if GEMINI_MODEL:
            print(f"✅ Gemini model cached: {GEMINI_MODEL}")
        else:
            print("⚠️ No valid Gemini model found")
    except Exception as e:
        print(f"❌ Gemini model init error: {e}")


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
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except:
        return False

def groq_response(prompt):
    global conversation
    try:
        conversation.append(f"User: {prompt}")
        # FIX 4: Trim conversation globally
        if len(conversation) > MAX_CONVERSATION:
            conversation = conversation[-MAX_CONVERSATION:]

        full_prompt = "\n".join(conversation[-6:])
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are Saarthi, a smart Indian AI assistant. Give short and accurate answers."},
                {"role": "user", "content": full_prompt}
            ]
        )
        reply = response.choices[0].message.content.strip()
        conversation.append(f"Assistant: {reply}")
        log_to_frontend("Groq: " + reply.replace("\n", " "))
        return reply
    except Exception as e:
        log_to_frontend("Groq Error: " + str(e))
        return None

# ─── Gemini AI ─────────────────────────
def gemini_response(prompt):
    global conversation
    try:
        # FIX 6: Use cached model — no API call every time
        if not GEMINI_MODEL:
            return "AI model not available."

        conversation.append(f"User: {prompt}")
        if len(conversation) > MAX_CONVERSATION:
            conversation = conversation[-MAX_CONVERSATION:]

        full_prompt = "\n".join(conversation[-8:])

        response = client.models.generate_content(
            model=GEMINI_MODEL,
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
        conversation.append(f"Assistant: {reply}")
        log_to_frontend("AI: " + reply.replace("\n", " "))
        return reply

    except Exception as e:
        log_to_frontend("Gemini Error: " + str(e))
        return "AI error"

# ─── Ollama AI (Offline) ─────────────────────────
def ollama_response(prompt):
    global conversation
    try:
        conversation.append(f"User: {prompt}")
        if len(conversation) > MAX_CONVERSATION:
            conversation = conversation[-MAX_CONVERSATION:]

        full_prompt = "\n".join(conversation[-6:])

        # FIX 7: Increased timeout — local models can be slow on first load
        timeout = int(os.getenv("OLLAMA_TIMEOUT", 60))
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": full_prompt,
                "stream": False
            },
            timeout=timeout
        )

        reply = response.json().get("response", "").strip()
        conversation.append(f"Assistant: {reply}")
        return reply if reply else "No response from offline AI."
    except Exception as e:
        print("Ollama error:", e)
        return "Offline AI not available."

# ─── Smart AI Switch ─────────────────────────
def ai_response(prompt):
    try:
        reply = groq_response(prompt)
        if reply:
            return reply
        reply = gemini_response(prompt)
        if reply:
            return reply
        return ollama_response(prompt)
    except Exception as e:
        log_to_frontend(f"AI Switch Error: {str(e)}")
        return "AI system error"

# ─── TTS Worker Thread ─────────────────────────
def tts_worker():
    """FIX 5: Dedicated TTS worker — processes speak queue one by one, never drops replies"""
    while True:
        text = tts_queue.get()
        if text is None:
            break
        try:
            if text in tts_cache:
                # Move to end (most recently used)
                tts_cache.move_to_end(text)
                playsound(tts_cache[text])
            else:
                filename = f"saarthi_{int(time.time()*1000)}.mp3"

                async def generate():
                    communicate = edge_tts.Communicate(text, VOICE)
                    await communicate.save(filename)

                asyncio.run(generate())

                # FIX 1: Evict oldest entry if cache is full
                if len(tts_cache) >= MAX_TTS_CACHE:
                    oldest_key, oldest_file = tts_cache.popitem(last=False)
                    try:
                        if os.path.exists(oldest_file):
                            os.remove(oldest_file)
                    except Exception:
                        pass

                tts_cache[text] = filename
                playsound(filename)

        except Exception as e:
            print("Speech error:", e)
        finally:
            tts_queue.task_done()

def speak(text):
    """FIX 5: Non-blocking, queue-based speak — replies are never dropped"""
    if not text:
        return
    try:
        tts_queue.put_nowait(text)
    except queue.Full:
        pass

# ─── Command Processor ─────────────────────────
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

    reply = ai_response(q)
    log_to_frontend(f"AI Generated: {reply}")
    return reply

def listen_command():
    try:
        with sr.Microphone(device_index=DEFAULT_MIC) as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, phrase_time_limit=8)
            query = recognizer.recognize_google(audio)
            print("You said:", query)

            log_to_frontend(f"User (voice): {query}")  # FIX 8: Log only once (removed duplicate)
            reply = process_query(query)

            global chat_history
            chat_history.append({
                "user": query,
                "assistant": reply,
                "time": datetime.datetime.now().strftime("%H:%M:%S")
            })
            # FIX 3: Cap chat_history
            if len(chat_history) > MAX_CHAT_HISTORY:
                chat_history = chat_history[-MAX_CHAT_HISTORY:]

            speak(reply)
    except:
        speak("Sorry, I didn't understand.")

def listen_for_wake_word():
    print("Listening for Saarthi...")
    log_to_frontend("Wake word listener started")
    while True:
        try:
            with sr.Microphone() as source:
                audio = recognizer.listen(source, phrase_time_limit=3)
            text = recognizer.recognize_google(audio).lower()
            if is_wake_word(text):
                command = text.replace("saarthi", "").strip()
                if command:
                    reply = process_query(command)
                    global chat_history
                    chat_history.append({
                        "user": command,
                        "assistant": reply,
                        "time": datetime.datetime.now().strftime("%H:%M:%S")
                    })
                    if len(chat_history) > MAX_CHAT_HISTORY:
                        chat_history = chat_history[-MAX_CHAT_HISTORY:]
                    speak(reply)
                else:
                    speak("Yes sir")
        except sr.UnknownValueError:
            pass
        except Exception as e:
            print("Wake word error:", e)
            time.sleep(0.2)

# ─── Flask Routes ───────────────────────────────

@app.route('/')
@app.route('/home')
def home():
    # FIX 9: Merged duplicate '/' routes into one
    return render_template('home.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        try:
            with get_db() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                cursor.close()

            if user and check_password_hash(user['password'], password):
                session['logged_in'] = True
                session['username'] = username
                session['role'] = user.get('role', 'user')
                log_to_frontend(f"User '{username}' logged in successfully")
                if username in ADMIN_USERS:
                    return redirect(url_for('admin'))
                return redirect(url_for('index'))
            else:
                return render_template('signin.html', error="Invalid username or password!")
        except Error as err:
            print(f"Database error: {err}")
            return render_template('signin.html', error="Server error. Try again.")

    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')

        if not username or not password or password != confirm:
            return render_template('signup.html', error="Please fill all fields correctly!")

        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    cursor.close()
                    return render_template('signup.html', error="Username already exists!")

                hashed = generate_password_hash(password)
                role = 'admin' if username in ADMIN_USERS else 'user'
                cursor.execute("""
                    INSERT INTO users (username, password, role)
                    VALUES (%s, %s, %s)
                """, (username, hashed, role))
                conn.commit()
                cursor.close()

            log_to_frontend(f"New user registered: {username}")
            return redirect(url_for('signin'))

        except Error as err:
            print(f"Signup error: {err}")
            return render_template('signup.html', error="Registration failed!")

    return render_template('signup.html')

@app.route('/index')
@login_required
def index():
    return render_template('index.html')

@app.route('/admin')
@login_required
def admin():
    username = session.get('username')
    if username not in ADMIN_USERS:
        return "Access Denied", 403
    return render_template('admin.html')

@app.route('/logout')
def logout():
    username = session.get('username', 'Unknown')
    log_to_frontend(f"User {username} logged out")
    session.clear()
    return redirect(url_for('signin'))

@app.route('/process', methods=['POST'])
@login_required
def process():
    data = request.get_json()
    query = data.get('query', '')

    log_to_frontend(f"User: {query}")
    reply = process_query(query)

    global chat_history
    chat_history.append({
        "user": query,
        "assistant": reply,
        "time": datetime.datetime.now().strftime("%H:%M:%S")
    })
    # FIX 3: Cap chat_history
    if len(chat_history) > MAX_CHAT_HISTORY:
        chat_history = chat_history[-MAX_CHAT_HISTORY:]

    log_to_frontend(f"AI: {reply}")
    speak(reply)
    return jsonify({
        'reply': reply,
        'chat': chat_history[-20:]
    })

@app.route('/get-chat')
@login_required
def get_chat():
    return jsonify({'chat': chat_history[-20:]})

@app.route('/get-logs')
@login_required
def get_logs():
    logs = []
    while not log_queue.empty():
        try:
            logs.append(log_queue.get_nowait())
        except:
            break
    return jsonify({'logs': logs[-60:]})

@app.route('/clear-logs')
@login_required
def clear_logs():
    # FIX 10: return was inside the while loop — fixed indentation
    while not log_queue.empty():
        try:
            log_queue.get_nowait()
        except:
            break
    log_to_frontend("Logs cleared by user")
    return jsonify({'status': 'cleared'})

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        message = data.get('message')
        rating = data.get('rating', 3)

        if not username or not email or not message:
            return jsonify({'status': 'error', 'message': 'Missing fields'}), 400

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO feedback (username, email, message, rating)
                VALUES (%s, %s, %s, %s)
            """, (username, email, message, rating))
            conn.commit()
            cursor.close()

        log_to_frontend(f"Feedback received from {username} (Rating: {rating})")
        return jsonify({'status': 'success'})
    except Exception as e:
        print("Feedback error:", e)
        return jsonify({'status': 'error', 'message': 'Failed to save feedback'}), 500

@app.route('/get_feedback')
@login_required
def get_feedback():
    try:
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, username, email, message, rating,
                       DATE_FORMAT(created_at, '%d %b %Y %H:%i') as time
                FROM feedback
                ORDER BY created_at DESC
            """)
            feedbacks = cursor.fetchall()
            cursor.close()
        return jsonify({'feedbacks': feedbacks})
    except Error as err:
        print(f"Feedback fetch error: {err}")
        return jsonify({'feedbacks': [], 'error': str(err)}), 500

@app.route('/clear_feedback', methods=['POST'])
@login_required
def clear_feedback():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("TRUNCATE TABLE feedback")
            conn.commit()
            cursor.close()
        log_to_frontend("Admin cleared all feedback")
        return jsonify({'status': 'success'})
    except Exception as e:
        print("Clear feedback error:", e)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/blog')
def blog():
    return render_template('blog.html')


def start_flask():
    app.run(port=5000, debug=False, use_reloader=False)


if __name__ == '__main__':
    create_tables()
    create_admin_users()

    # FIX 6: Cache Gemini model once at startup
    init_gemini_model()

    # FIX 5: Start TTS worker thread
    tts_worker_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_worker_thread.start()

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
