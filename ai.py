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
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify
import asyncio
import edge_tts
from openai import OpenAI


# ─── Globals ─────────────────────────────────────────
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

recognizer = sr.Recognizer()
recognizer.energy_threshold = 150
recognizer.dynamic_energy_threshold = True

DEFAULT_MIC = None

VOICE = "en-IN-NeerjaNeural"
speaking = False
conversation = []


# ─── Wake word detection ─────────────────────────────
def is_wake_word(text):
    words = text.split()

    for word in words:
        similarity = SequenceMatcher(None, word, "saarthi").ratio()
        if similarity > 0.7:
            return True

    return False

def smart_search(query):

    answer = ""

    # 1️⃣ Wikipedia
    try:
        wiki = wikipedia.summary(query, sentences=2)
        answer += wiki
    except Exception as e:
        print("Wikipedia error:", e)
        pass

    # 2️⃣ Google search result snippet
    try:
        for url in search(query, num_results=2):
            response = requests.get(url, timeout=5)
            soup = BeautifulSoup(response.text, "html.parser")

            paragraphs = soup.find_all("p")

            for p in soup.find_all("p"):
                text = p.get_text().strip()

                if len(text) > 100:
                    answer += " " + text
                    break

            break
    except Exception as e:
        print("Search error:",e)

    if not answer:
        answer = "Sorry sir, I couldn't find information."

    return answer[:250]  # limit speech length
# ─── Internet Check ────────
def internet_available():
    try:
        socket.create_connection(("8.8.8.8",53), timeout=3)
        return True
    except:
        return False


# ─── Text To Speech ──
def speak(text):

    global speaking

    if not text or speaking:
        return

    print(f"Saarthi: {text}")
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
            print("Speech error:",e)

        finally:
                speaking = False
                if os.path.exists(filename):
                   os.remove(filename)

    threading.Thread(target=run, daemon=True).start()



# ─── Command Processor ───────────────────────────────
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
    

    # 🔎 Multi-source search
    return smart_search(q)


# ─── Command Listener ────────────────────────────────
def listen_command():

    if not internet_available():
        speak("Internet connection is required.")
        return

    try:

        with sr.Microphone(device_index=DEFAULT_MIC) as source:

            print("Listening for command...")

            recognizer.adjust_for_ambient_noise(source, duration=1)

            audio = recognizer.listen(source, phrase_time_limit=8)

            try:

                query = recognizer.recognize_google(audio)

                print("You said:", query)

                reply = process_query(query)

                speak(reply)

            except sr.UnknownValueError:

                speak("Sorry, I didn't understand.")

    except Exception as e:

        print("Command error:", e)


def listen_for_wake_word():

    print("Listening for Saarthi...")

    while True:

        if not internet_available():
            speak("Internet connection is required.")
            time.sleep(5)
            continue

        try:

            with sr.Microphone(device_index=DEFAULT_MIC) as source:

                recognizer.adjust_for_ambient_noise(source, duration=1)

                audio = recognizer.listen(source, phrase_time_limit=5)

                try:

                    text = recognizer.recognize_google(audio).lower()
                    print("Heard:", text)

                    if is_wake_word(text):
                        print("Wake word detected")

                        command = text.replace("saarthi","").replace("hey","").replace("play","").strip()

                        if command:
                            reply = process_query(command)
                            speak(reply)
                        else:
                            speak("Yes sir")
                            listen_command()

                except sr.UnknownValueError:
                    pass

        except Exception as e:
            print("Mic error:", e)

# ─── Flask ───────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/process', methods=['POST'])
def process():

    data = request.get_json()

    query = data.get('query','')

    reply = process_query(query)

    speak(reply)

    return jsonify({'reply': reply})


def start_flask():
    app.run(port=5000, debug=False, use_reloader=False)


# ─── Main ────────────────────────────────────────────
if __name__ == '__main__':

    print("=== Saarthi Voice Assistant Starting ===")

    # Start Flask server
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    time.sleep(2)

    # Start voice listener
    voice_thread = threading.Thread(target=listen_for_wake_word, daemon=True)
    voice_thread.start()

    # Startup voice
    speak("Hello sir. Saarthi voice assistant is now online.")

    # Start UI window
    webview.create_window(
        "Saarthi Voice Assistant",
        "http://127.0.0.1:5000/",
        width=1000,
        height=680,
        resizable=True
    )

    webview.start()