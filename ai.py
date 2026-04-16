import threading
import time
import datetime
import os
import uuid
import webbrowser
import pyautogui
import speech_recognition as sr
from playsound import playsound
import socket
import webview
from functools import wraps
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import asyncio
import edge_tts
from dotenv import load_dotenv
from google import genai
from mysql.connector import pooling, Error
from werkzeug.security import generate_password_hash, check_password_hash
import queue
from groq import Groq
from contextlib import contextmanager
from app_automations.intent_parser import parse_intent
from app_automations import whatsapp, chrome, notepad

# ─── Load API Key ───
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ─── Globals ───
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.secret_key = 'saarthi-secret-key-2026'

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

# ─── Per-user chat history and conversation — keyed by username ───
MAX_CHAT_HISTORY = 100
MAX_CONVERSATION = 10
_chat_histories = {}   # username -> list of {user, assistant, time}
_conversations = {}    # username -> list of "User: ..." / "Assistant: ..." strings
_state_lock = threading.Lock()

def get_chat_history(username):
    with _state_lock:
        return list(_chat_histories.get(username, []))

def append_chat_history(username, entry):
    with _state_lock:
        hist = _chat_histories.setdefault(username, [])
        hist.append(entry)
        if len(hist) > MAX_CHAT_HISTORY:
            _chat_histories[username] = hist[-MAX_CHAT_HISTORY:]

def get_conversation(username):
    with _state_lock:
        return list(_conversations.get(username, []))

def append_conversation(username, line):
    with _state_lock:
        conv = _conversations.setdefault(username, [])
        conv.append(line)
        if len(conv) > MAX_CONVERSATION:
            _conversations[username] = conv[-MAX_CONVERSATION:]

def set_conversation(username, lines):
    with _state_lock:
        _conversations[username] = lines[-MAX_CONVERSATION:]


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
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8
recognizer.phrase_threshold = 0.3

def find_default_mic():
    mic_names = sr.Microphone.list_microphone_names()
    print("🎤 Available microphones:")
    for i, name in enumerate(mic_names):
        print(f"   [{i}] {name}")

    preferred = ['microphone', 'mic', 'realtek', 'headset', 'usb', 'input', 'array']
    for i, name in enumerate(mic_names):
        name_lower = name.lower()
        if any(p in name_lower for p in preferred):
            print(f"✅ Auto-selected mic [{i}]: {name}")
            return i

    if mic_names:
        print(f"⚠️ No preferred mic found, using [{0}]: {mic_names[0]}")
        return 0

    print("❌ No microphone found!")
    return None

DEFAULT_MIC = find_default_mic()
VOICE = "en-IN-NeerjaNeural"

tts_queue = queue.Queue(maxsize=10)

GEMINI_MODEL = None

def init_gemini_model():
    global GEMINI_MODEL
    try:
        print("⏳ Connecting to Gemini API...")
        result = [None]
        def fetch():
            try:
                available_models = client.models.list()
                result[0] = next(
                    (m.name for m in available_models if "generateContent" in m.supported_actions),
                    None
                )
            except Exception as e:
                print(f"❌ Gemini fetch error: {e}")

        t = threading.Thread(target=fetch, daemon=True)
        t.start()
        t.join(timeout=10)

        if t.is_alive():
            print("⚠️ Gemini API timed out — will use Groq/Ollama fallback")
            GEMINI_MODEL = None
            return

        GEMINI_MODEL = result[0]
        if GEMINI_MODEL:
            print(f"✅ Gemini model cached: {GEMINI_MODEL}")
        else:
            print("⚠️ No valid Gemini model found — will use Groq/Ollama fallback")
    except Exception as e:
        print(f"❌ Gemini model init error: {e}")
        GEMINI_MODEL = None


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

def groq_response(prompt, username="system"):
    try:
        conv = get_conversation(username)
        conv.append(f"User: {prompt}")
        full_prompt = "\n".join(conv[-6:])

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are Saarthi, a smart Indian AI assistant. Give short and accurate answers."},
                {"role": "user", "content": full_prompt}
            ]
        )
        reply = response.choices[0].message.content.strip()

        append_conversation(username, f"User: {prompt}")
        append_conversation(username, f"Assistant: {reply}")

        log_to_frontend("Groq: " + reply.replace("\n", " "))
        return reply
    except Exception as e:
        log_to_frontend("Groq Error: " + str(e))
        return None

def gemini_response(prompt, username="system"):
    try:
        if not GEMINI_MODEL:
            return "AI model not available."

        conv = get_conversation(username)
        conv.append(f"User: {prompt}")
        full_prompt = "\n".join(conv[-8:])

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
            return None

        reply = str(reply).strip()

        append_conversation(username, f"User: {prompt}")
        append_conversation(username, f"Assistant: {reply}")

        log_to_frontend("AI: " + reply.replace("\n", " "))
        return reply

    except Exception as e:
        log_to_frontend("Gemini Error: " + str(e))
        return None

def ollama_response(prompt, username="system"):
    try:
        conv = get_conversation(username)
        conv.append(f"User: {prompt}")
        full_prompt = "\n".join(conv[-6:])

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
        if reply:
            append_conversation(username, f"User: {prompt}")
            append_conversation(username, f"Assistant: {reply}")
        return reply if reply else "No response from offline AI."
    except Exception as e:
        print("Ollama error:", e)
        return "Offline AI not available."

def ai_response(prompt, username="system"):
    try:
        reply = groq_response(prompt, username)
        if reply:
            return reply
        reply = gemini_response(prompt, username)
        if reply:
            return reply
        return ollama_response(prompt, username)
    except Exception as e:
        log_to_frontend(f"AI Switch Error: {str(e)}")
        return "AI system error"

# ─── TTS Worker Thread ─────────────────────────
def tts_worker():
    while True:
        text = tts_queue.get()
        if text is None:
            break

        filename = f"saarthi_{uuid.uuid4().hex}.mp3"
        try:
            async def generate():
                communicate = edge_tts.Communicate(text, VOICE)
                await communicate.save(filename)

            asyncio.run(generate())
            playsound(filename)

        except Exception as e:
            print("Speech error:", e)

        finally:
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                print("File delete error:", e)

            tts_queue.task_done()

def speak(text):
    """Non-blocking, queue-based TTS. Drops silently if queue is full."""
    if not text:
        return
    try:
        tts_queue.put_nowait(text)
    except queue.Full:
        log_to_frontend("⚠️ TTS queue full — speech skipped")

# ─── Command Processor ─────────────────────────
def process_query(query, username="system"):
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

    reply = ai_response(q, username)
    log_to_frontend(f"AI Generated: {reply}")
    return reply

_listener_running = False
_listener_lock = threading.Lock()

def listener_loop():
    global DEFAULT_MIC, _listener_running
    username = "voice_user"
    consecutive_errors = 0

    log_to_frontend("✅ Listener started — say 'Hey Saarthi <command>'")
    print("🎤 Listener loop started")

    while _listener_running:
        try:
            with sr.Microphone(device_index=DEFAULT_MIC) as source:
                # Recalibrate every 20 cycles to adapt to changing environment
                if consecutive_errors == 0 or consecutive_errors % 20 == 0:
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)

                audio = recognizer.listen(source, phrase_time_limit=6, timeout=8)

            text = recognizer.recognize_google(audio).lower()
            consecutive_errors = 0
            print(f"[MIC] Heard: {text}")

            if is_wake_word(text):
                # Strip wake word to isolate the actual command
                command = text
                for w in ["hey saarthi", "saarthi", "sarathi", "sarthi"]:
                    command = command.replace(w, "").strip()

                if command:
                    log_to_frontend(f"✅ Executing: \"{command}\"")
                    reply = process_query(command, username)
                    append_chat_history(username, {
                        "user": command,
                        "assistant": reply,
                        "time": datetime.datetime.now().strftime("%H:%M:%S")
                    })
                    speak(reply)

                else:
                    speak("Yes sir?")
                    log_to_frontend("👂 Wake word heard — waiting for follow-up command...")
                    try:
                        with sr.Microphone(device_index=DEFAULT_MIC) as source:
                            log_to_frontend("👂 Listening for your command...")
                            follow_audio = recognizer.listen(source, phrase_time_limit=6, timeout=5)

                        follow_text = recognizer.recognize_google(follow_audio).lower()
                        log_to_frontend(f"✅ Command: \"{follow_text}\"")
                        reply = process_query(follow_text, username)
                        append_chat_history(username, {
                            "user": follow_text,
                            "assistant": reply,
                            "time": datetime.datetime.now().strftime("%H:%M:%S")
                        })
                        speak(reply)

                    except sr.WaitTimeoutError:
                        speak("I didn't hear anything. Try again.")
                    except sr.UnknownValueError:
                        speak("Sorry, couldn't understand that.")

        except sr.WaitTimeoutError:
            pass  
        except sr.UnknownValueError:
            pass  
        except sr.RequestError as e:
            consecutive_errors += 1
            log_to_frontend(f"❌ Speech API error: {e}")
            time.sleep(3)

        except OSError as e:
            consecutive_errors += 1
            log_to_frontend(f"❌ Mic hardware error: {e} — retrying...")
            time.sleep(3)
            DEFAULT_MIC = find_default_mic()  # Re-detect mic on hardware failure

        except Exception as e:
            consecutive_errors += 1
            log_to_frontend(f"❌ Listener error [{type(e).__name__}]: {e}")
            time.sleep(1)

    log_to_frontend("🔇 Listener stopped")
    print("🔇 Listener loop exited")

def start_listener():
    """Start the listener if not already running. Returns True if started."""
    global _listener_running
    with _listener_lock:
        if _listener_running:
            log_to_frontend("⚠️ Listener already running")
            return False
        _listener_running = True
        threading.Thread(target=listener_loop, daemon=True).start()
        return True

def stop_listener():
    """Pause the listener. The loop exits cleanly on next iteration."""
    global _listener_running
    with _listener_lock:
        _listener_running = False

def is_listener_running():
    return _listener_running

@app.route('/')
@app.route('/home')
def home():
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
    username = session.get('username', 'unknown')

    log_to_frontend(f"User [{username}]: {query}")
    reply = process_query(query, username)

    append_chat_history(username, {
        "user": query,
        "assistant": reply,
        "time": datetime.datetime.now().strftime("%H:%M:%S")
    })

    log_to_frontend(f"AI [{username}]: {reply}")
    speak(reply)
    return jsonify({
        'reply': reply,
        'chat': get_chat_history(username)[-20:]
    })

@app.route('/toggle-mic', methods=['POST'])
@login_required
def toggle_mic():
    if is_listener_running():
        stop_listener()
        log_to_frontend("🔇 Mic paused by user")
        return jsonify({'status': 'off', 'message': 'Mic paused'})
    else:
        start_listener()
        log_to_frontend("🎤 Mic resumed by user — say Hey Saarthi")
        return jsonify({'status': 'on', 'message': 'Mic resumed — say Hey Saarthi'})

@app.route('/mic-status', methods=['GET'])
@login_required
def mic_status():
    """Frontend polls this to show the mic ON/OFF indicator."""
    return jsonify({'active': is_listener_running()})

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

    threading.Thread(target=init_gemini_model, daemon=True).start()

    tts_worker_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_worker_thread.start()

    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(2)  # Give Flask time to bind to port 5000

    start_listener()
    speak("Hello sir. Saarthi is now online.")
    webview.create_window(
        "Saarthi Voice Assistant",
        "http://127.0.0.1:5000/",
        width=1280,
        height=760
    )
    webview.start()