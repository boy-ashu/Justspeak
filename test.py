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
from dotenv import load_dotenv
import google.generativeai as genai

# ─── Load API Key ─────────────────────────
load_dotenv(".env")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# ─── Globals ─────────────────────────
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
    for word in text.split():
        if SequenceMatcher(None, word, "saarthi").ratio() > 0.7:
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
        full_prompt = "\n".join(conversation[-6:])

        response = gemini_model.generate_content(
            f"You are Saarthi, a smart Indian assistant. Keep answers short.\n{full_prompt}"
        )

        reply = response.text.strip()
        conversation.append(f"Assistant: {reply}")

        return reply
    except Exception as e:
        print("Gemini error:", e)
        return None

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
    if internet_available():
        reply = gemini_response(prompt)
        if reply:
            return reply
    return ollama_response(prompt)

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
            print("Speech error:", e)

        finally:
            speaking = False
            if os.path.exists(filename):
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
    return ai_response(q)

# Voice Listener
def listen_command():
    try:
        with sr.Microphone(device_index=DEFAULT_MIC) as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, phrase_time_limit=8)

            query = recognizer.recognize_google(audio)
            print("You said:", query)

            reply = process_query(query)
            speak(reply)

    except:
        speak("Sorry, I didn't understand.")

def listen_for_wake_word():
    print("Listening for Saarthi...")

    while True:
        try:
            with sr.Microphone(device_index=DEFAULT_MIC) as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
                audio = recognizer.listen(source, phrase_time_limit=5)
                try:
                    text = recognizer.recognize_google(audio).lower()
                    print("Heard:", text)

                    if is_wake_word(text):
                       command = text.replace("saarthi","").strip()

                       if command:
                           speak(process_query(command))
                       else:
                            speak("Yes sir")
                            listen_command()
                except sr.UnknownValueError:
                    pass

        except:
            pass

#  Flask
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

#  Main 
if __name__ == '__main__':
    print("=== Saarthi Voice Assistant Starting ===")

    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(2)

    threading.Thread(target=listen_for_wake_word, daemon=True).start()
    speak("Hello sir. Saarthi is now online.")

    webview.create_window(
        "Saarthi Voice Assistant",
        "http://127.0.0.1:5000/",
        width=1000,
        height=680
    )

    webview.start()