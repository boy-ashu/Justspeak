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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import pyotp
import qrcode
import base64
from io import BytesIO
import secrets

# ─── Load API Key ───
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ─── Globals ───
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.secret_key = os.getenv('SECRET_KEY', os.urandom(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=2)
)

# ─── Rate Limiter Setup ───
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# ─── Brute Force Tracking (keyed by "ip:username") ───
failed_attempts = {}          # "ip:username" -> {count, lockout_until}
LOCKOUT_THRESHOLD = 8
LOCKOUT_DURATION = datetime.timedelta(hours=1)


def _make_key(ip, username):
    """Create a composite key so each (IP, username) pair is tracked separately."""
    return f"{ip}:{username.lower().strip()}"

def generate_backup_codes():
    return [secrets.token_hex(4) for _ in range(5)]

def is_locked_out(ip, username=""):
    key = _make_key(ip, username)
    if key not in failed_attempts:
        return False
    data = failed_attempts[key]
    if data['lockout_until'] and datetime.datetime.now() < data['lockout_until']:
        return True
    # Lockout expired — clean up automatically
    if data['lockout_until'] and datetime.datetime.now() >= data['lockout_until']:
        del failed_attempts[key]
    return False


def get_remaining_lockout(ip, username=""):
    key = _make_key(ip, username)
    if key not in failed_attempts:
        return 0
    lockout_until = failed_attempts[key].get('lockout_until')
    if lockout_until and datetime.datetime.now() < lockout_until:
        delta = lockout_until - datetime.datetime.now()
        remaining = max(1, int(delta.seconds / 60))
        return remaining
    return 0


def record_failed_attempt(ip, username=""):
    key = _make_key(ip, username)
    if key not in failed_attempts:
        failed_attempts[key] = {'count': 0, 'lockout_until': None}
    failed_attempts[key]['count'] += 1
    count = failed_attempts[key]['count']
    if count >= LOCKOUT_THRESHOLD:
        failed_attempts[key]['lockout_until'] = (
            datetime.datetime.now() + LOCKOUT_DURATION
        )
        log_to_frontend(
            f"🔒 IP {ip} locked out for username '{username}' "
            f"after {count} failed attempts for 1 hour"
        )


def reset_failed_attempts(ip, username=""):
    key = _make_key(ip, username)
    if key in failed_attempts:
        del failed_attempts[key]


def get_attempt_count(ip, username=""):
    key = _make_key(ip, username)
    return failed_attempts.get(key, {}).get('count', 0)


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
                    twofa_secret VARCHAR(32),
                    twofa_enabled BOOLEAN DEFAULT FALSE,
                    backup_codes TEXT,
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS login_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    ip_address VARCHAR(45) NOT NULL,
                    user_agent TEXT,
                    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN DEFAULT TRUE,
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                )
            """)
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN twofa_secret VARCHAR(32)")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN twofa_enabled BOOLEAN DEFAULT FALSE")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN backup_codes TEXT;")
            except:
                pass
            conn.commit()
            cursor.close()
            print("✅ Database tables created successfully")
    except Error as err:
        print(f"❌ Table creation error: {err}")

def record_login_history(username, ip, user_agent, success=True):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO login_history (username, ip_address, user_agent, success)
                VALUES (%s, %s, %s, %s)
            """, (username, ip, user_agent[:255], success))  # limit user_agent length
            conn.commit()
            cursor.close()
    except Exception as e:
        print(f"❌ Failed to record login history: {e}")


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
_chat_histories = {}
_conversations = {}
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

def generate_2fa_setup(username):
    secret = pyotp.random_base32()

    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name="Saarthi AI"
    )
    qr = qrcode.make(uri)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(buffer.getvalue()).decode()
    return secret, qr_base64

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8
recognizer.phrase_threshold = 0.3

def find_default_mic():
    try:
        mic_names = sr.Microphone.list_microphone_names()
        print("🎤 Available microphones:")

        for i, name in enumerate(mic_names):
            print(f"[{i}] {name}")

        if not mic_names:
            print("❌ No microphones found!")
            return None

        print(f"✅ Using default mic [0]: {mic_names[0]}")
        return 0

    except Exception as e:
        print(f"❌ Mic detection error: {e}")
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


# ─── Wake word detection ───
def is_wake_word(text):
    wake_words = ["saarthi", "sarathi", "sarthi", "hey saarthi"]
    for w in wake_words:
        if w in text:
            return True
    return False


# ─── Internet Check ───
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


# ─── TTS Worker Thread ───
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
    if not text:
        return
    try:
        tts_queue.put_nowait(text)
    except queue.Full:
        log_to_frontend("⚠️ TTS queue full — speech skipped")


# ─── Command Processor ───
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
    log_to_frontend("🎤 Say 'Hey Saarthi'")

    while _listener_running:
        try:
            if DEFAULT_MIC is None:
                log_to_frontend("❌ Mic missing, retrying...")
                time.sleep(2)
                DEFAULT_MIC = find_default_mic()
                continue

            with sr.Microphone(device_index=DEFAULT_MIC) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)

                log_to_frontend("👂 Listening...")
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)

            try:
                text = recognizer.recognize_google(audio).lower()
                print("🎤 Heard:", text)

            except sr.UnknownValueError:
                continue

            except sr.RequestError as e:
                log_to_frontend(f"❌ API error: {e}")
                time.sleep(2)
                continue

            if is_wake_word(text):
                command = text.replace("saarthi", "").strip()

                if not command:
                    speak("Yes sir?")
                    continue

                log_to_frontend(f"⚡ Command: {command}")

                reply = process_query(command, username)

                append_chat_history(username, {
                    "user": command,
                    "assistant": reply,
                    "time": datetime.datetime.now().strftime("%H:%M:%S")
                })

                speak(reply)

        except sr.WaitTimeoutError:
            continue

        except OSError as e:
            log_to_frontend(f"❌ Mic error: {e}")
            DEFAULT_MIC = find_default_mic()
            time.sleep(2)

        except Exception as e:
            print("❌ Listener error:", e)
            log_to_frontend(f"❌ Listener error: {e}")
            time.sleep(1)

    log_to_frontend("🔇 Listener exited")

def start_listener():
    global _listener_running

    with _listener_lock:
        if _listener_running:
            log_to_frontend("⚠️ Listener already running")
            return False

        if DEFAULT_MIC is None:
            log_to_frontend("❌ No microphone available")
            return False

        _listener_running = True

        def safe_listener():
            global _listener_running
            try:
                listener_loop()
            except Exception as e:
                print("💥 Listener crashed:", e)
                log_to_frontend(f"💥 Listener crashed: {e}")
            finally:
                _listener_running = False

        threading.Thread(target=safe_listener, daemon=True).start()
        log_to_frontend("🎤 Listener started")
        return True

def stop_listener():
    global _listener_running
    with _listener_lock:
        _listener_running = False

def is_listener_running():
    return _listener_running


# ─── Rate Limit Error Handler ───
@app.errorhandler(429)
def rate_limit_exceeded(e):
    log_to_frontend(f"🚫 Rate limit hit from {get_remote_address()}")
    return render_template('signin.html',
        error="Too many requests. Please slow down and try again."), 429

@app.route('/')
@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/verify-2fa', methods=['POST'])
@login_required
def verify_2fa():
    otp = request.form.get('otp')
    username = session['username']

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT twofa_secret FROM users WHERE username=%s",
            (username,)
        )
        user = cursor.fetchone()
        cursor.close()
    if not user or not user.get('twofa_secret'):
        return render_template('enable_2fa.html',
            error="Setup session expired. Please start again.",
            qr=None, secret=None)
    
    totp = pyotp.TOTP(user['twofa_secret'])
    if not totp.verify(otp, valid_window=1):
        # Re-show setup page with QR
        _, qr_b64 = generate_2fa_setup.__wrapped__(username) \
            if hasattr(generate_2fa_setup, '__wrapped__') \
            else (user['twofa_secret'], None)
        return render_template('enable_2fa.html',
            error="Invalid code — try again.",
            secret=user['twofa_secret'], qr=qr_b64)

    codes = generate_backup_codes()
    codes_json = ','.join(codes)  
 
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET twofa_enabled=TRUE, backup_codes=%s WHERE username=%s",
            (codes_json, username)
        )
        conn.commit()
        cursor.close()
 
    log_to_frontend(f"✅ 2FA enabled for '{username}'")
    return render_template('backup_codes.html', codes=codes)

@app.route('/2fa-login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def twofa_login():
    if 'temp_user_2fa' not in session:
        return redirect(url_for('signin'))
 
    username = session['temp_user_2fa']
    error    = None
 
    if request.method == 'POST':
        otp = request.form.get('otp', '').strip().upper()
        use_backup = request.form.get('use_backup') == '1'
        ip = get_remote_address()
 
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT twofa_secret, backup_codes FROM users WHERE username=%s",
                (username,)
            )
            user = cursor.fetchone()
            cursor.close()
 
        verified = False
        if use_backup:
            stored_raw = (user or {}).get('backup_codes') or ''
            codes      = [c.strip() for c in stored_raw.split(',') if c.strip()]
            if otp in codes:
                codes.remove(otp)        # invalidate used code
                new_codes = ','.join(codes)
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET backup_codes=%s WHERE username=%s",
                        (new_codes, username)
                    )
                    conn.commit()
                    cursor.close()
                verified = True
                log_to_frontend(f"🔑 Backup code used by '{username}' ({len(codes)} remaining)")
            else:
                error = "Invalid backup code."
        else:
            secret = (user or {}).get('twofa_secret')
            if secret:
                totp = pyotp.TOTP(secret)
                if totp.verify(otp, valid_window=1):
                    verified = True
            if not verified and not error:
                error = "Invalid authentication code."
 
        if verified:
            record_failed_attempt_reset = True
            reset_failed_attempts(ip, username)
            user_agent = request.headers.get('User-Agent', 'Unknown')
            record_login_history(username, ip, user_agent, success=True)
            role = session.pop('temp_role', 'user')
            session.pop('temp_user_2fa', None)
            session['logged_in'] = True
            session['username']  = username
            session['role']      = role
            session.permanent    = True
            log_to_frontend(f"✅ 2FA verified for '{username}' from {ip}")
            return redirect(url_for('admin') if username in ADMIN_USERS else url_for('index'))
        else:
            record_failed_attempt(ip, username)
 
    return render_template('2fa_login.html', error=error)

@app.route('/enable-2fa')
@login_required
def enable_2fa():
    username = session['username']
    secret, qr = generate_2fa_setup(username)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET twofa_secret=%s WHERE username=%s",
            (secret, username)
        )
        conn.commit()
        cursor.close()
    return render_template('enable_2fa.html', qr=qr, secret=secret)

@app.route('/login-history')
@login_required
def login_history():
    username = session.get('username')
    if username not in ADMIN_USERS:
        return "Access Denied - Admin Only", 403

    try:
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT username, ip_address, user_agent, 
                       DATE_FORMAT(login_time, '%d %b %Y %H:%i:%s') as login_time,
                       success
                FROM login_history 
                ORDER BY login_time DESC 
                LIMIT 100
            """)
            history = cursor.fetchall()
            cursor.close()

        return render_template('login_history.html', history=history)
    except Exception as e:
        print(f"Login history error: {e}")
        return "Error fetching login history", 500

@app.route('/disable-2fa', methods=['POST'])
@login_required
def disable_2fa():
    password = request.form.get('password', '')
    username = session['username']
 
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
 
    if not user or not check_password_hash(user['password'], password):
        return render_template('settings.html',
            error="Incorrect password. 2FA was NOT disabled.")
 
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET twofa_enabled=FALSE, twofa_secret=NULL, backup_codes=NULL "
            "WHERE username=%s", (username,)
        )
        conn.commit()
        cursor.close()
 
    log_to_frontend(f"⚠️  2FA disabled for '{username}'")
    return redirect(url_for('index'))

@app.route('/signin', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def signin():
    if request.method == 'POST':
        ip = get_remote_address()
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('signin.html', error="Please fill in all fields.")

        if is_locked_out(ip, username):
            minutes = get_remaining_lockout(ip, username)
            return render_template('signin.html',
                error=f"Too many failed attempts. Try again in {minutes} minute(s).")

        try:
            with get_db() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()

            password_correct = user and check_password_hash(user['password'], password)

            if password_correct:
                reset_failed_attempts(ip, username)
                user_agent = request.headers.get('User-Agent', 'Unknown')
                record_login_history(username, ip, user_agent, success=True)

                # === 2FA CHECK ===
                if user.get('twofa_enabled'):
                    session['temp_user_2fa'] = username
                    session['temp_role'] = user.get('role', 'user')
                    return redirect(url_for('twofa_login'))

                # Normal login (no 2FA)
                session['logged_in'] = True
                session['username'] = username
                session['role'] = user.get('role', 'user')
                session.permanent = True

                log_to_frontend(f"✅ {username} logged in from {ip}")
                return redirect(url_for('index'))

            else:
                record_failed_attempt(ip, username)
                count = get_attempt_count(ip, username)
                remaining = LOCKOUT_THRESHOLD - count

                if remaining <= 0:
                    return render_template('signin.html', error="Too many failed attempts. Account locked for 1 hour.")
                return render_template('signin.html',
                    error=f"Invalid credentials. {remaining} attempt(s) left.")

        except Exception as e:
            print("Signin error:", e)
            return render_template('signin.html', error="Server error. Please try again.")

    return render_template('signin.html')

@app.route('/verify-2fa-setup', methods=['POST'])
@login_required
def verify_2fa_setup():
    username = session['username']
    otp = request.form.get('otp', '').strip()

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT twofa_secret FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

    if not user or not user['twofa_secret']:
        return "2FA not initiated", 400

    totp = pyotp.TOTP(user['twofa_secret'])

    if totp.verify(otp, valid_window=1):
        backup_codes = generate_backup_codes()
        backup_str = ",".join(backup_codes)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET twofa_enabled = TRUE, 
                    backup_codes = %s 
                WHERE username = %s
            """, (backup_str, username))
            conn.commit()

        log_to_frontend(f"✅ 2FA enabled for {username}")
        return render_template('2fa_setup_success.html', 
                             backup_codes=backup_codes,
                             username=username)
    secret, qr = generate_2fa_setup(username)  
    return render_template('enable_2fa.html', 
                         qr=qr, 
                         secret=secret, 
                         error="Invalid code. Please try again.")

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        # Basic validation
        if not username or not password or not confirm:
            return render_template('signup.html', error="All fields are required!")

        if password != confirm:
            return render_template('signup.html', error="Passwords do not match!")

        if len(username) < 3 or len(username) > 50:
            return render_template('signup.html', error="Username must be between 3 and 50 characters.")

        if len(password) < 6:
            return render_template('signup.html', error="Password must be at least 6 characters long.")

        try:
            with get_db() as conn:
                cursor = conn.cursor(dictionary=True)

                # Check if username already exists
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    return render_template('signup.html', error="Username already exists! Please choose another one.")

                # Hash the password
                hashed_password = generate_password_hash(password)

                # Decide role
                role = 'admin' if username in [u.lower() for u in ADMIN_USERS] else 'user'

                # Insert new user with 2FA disabled by default
                cursor.execute("""
                    INSERT INTO users 
                    (username, password, role, twofa_enabled) 
                    VALUES (%s, %s, %s, FALSE)
                """, (username, hashed_password, role))

                conn.commit()
                cursor.close()

            log_to_frontend(f"✅ New user created successfully: {username} (Role: {role})")
            print(f"✅ New user created: {username}")   # Also print in terminal

            # Redirect to signin with success message (optional but helpful)
            return redirect(url_for('signin'))

        except Error as err:
            print(f"❌ Database Error during signup: {err}")
            return render_template('signup.html', error="Database error. Please try again later.")

        except Exception as e:
            print(f"❌ Unexpected Error during signup: {e}")
            return render_template('signup.html', error="Something went wrong. Please try again.")

    # GET request → show form
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

@app.route('/login-history-json')
@login_required
def login_history_json():
    username = session.get('username')
    if username not in ADMIN_USERS or session.get('role') != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT username, ip_address, user_agent,
                       DATE_FORMAT(login_time, '%d %b %Y %H:%i:%s') as login_time,
                       success
                FROM login_history
                ORDER BY login_time DESC
                LIMIT 100
            """)
            history = cursor.fetchall()
            cursor.close()
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/get-chat', methods=['GET'])
@login_required
def get_chat():
    username = session.get('username')
    history = get_chat_history(username)
    return jsonify({'chat': history[-20:]})

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
    time.sleep(2)

    start_listener()
    speak("Hello sir. Saarthi is now online.")
    webview.create_window(
        "Saarthi Voice Assistant",
        "http://127.0.0.1:5000/",
        width=1280,
        height=760
    )
    webview.start()