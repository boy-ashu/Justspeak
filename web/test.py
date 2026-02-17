import pyttsx3
import eel
import datetime
import speech_recognition as sr
import wikipedia
import webbrowser
import time
import threading
import os
import pyautogui
import pythoncom
from spellchecker import SpellChecker

eel.init("web")

is_speaking = False
r = sr.Recognizer()
r.energy_threshold = 400
r.dynamic_energy_threshold = False
spell = SpellChecker()

def display_message(text):
    eel.DisplayMessage(text)

def show_hood():
    eel.ShowHood()

def sender_text(text):
    eel.senderText(text)

def receiver_text(text):
    eel.receiverText(text)

def hide_loader():
    eel.hideLoader()

def hide_face_auth():
    eel.hideFaceAuth()

def hide_face_auth_success():
    eel.hideFaceAuthSuccess()

def hide_start():
    eel.hideStart()

def run_speech(text):
    global is_speaking
    is_speaking = True
    pythoncom.CoInitialize()

    engine = pyttsx3.init('sapi5')
    engine.setProperty('rate', 190)
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[1].id)

    engine.say(text)
    engine.runAndWait()

    pythoncom.CoUninitialize()
    is_speaking = False

def speak(text):
    receiver_text(text)
    print("Saarthi:", text)
    threading.Thread(target=run_speech, args=(text,)).start()

def startup_sequence():
    hide_loader()
    time.sleep(2)
    hide_face_auth()
    time.sleep(2)
    hide_face_auth_success()
    time.sleep(2)
    hide_start()

def wishme():
    hour = datetime.datetime.now().hour
    if hour < 12:
        speak("Good Morning! I am Saarthi. How can I help you?")
    elif hour < 18:
        speak("Good Afternoon! I am Saarthi. How can I help you?")
    else:
        speak("Good Evening! I am Saarthi. How can I help you?")

def takeCommand():
    global is_speaking
    while is_speaking:
        time.sleep(0.1)

    show_hood()

    with sr.Microphone() as source:
        print("Listening...")
        r.pause_threshold = 0.8
        audio = r.listen(source)

    try:
        query = r.recognize_google(audio, language="en-in")
        print("User:", query)
        sender_text(query)
        return query.lower()
    except:
        return ""

def assistant():
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=1)

    startup_sequence()
    wishme()

    while True:
        query = takeCommand()

        if not query:
            continue

        if 'exit' in query or 'stop' in query:
            speak("Goodbye Sir!")
            break

        elif 'time' in query:
            strTime = datetime.datetime.now().strftime("%I:%M %p")
            speak(f"It is {strTime}")

        elif 'date' in query:
            today = datetime.date.today().strftime("%B %d, %Y")
            speak(f"Today is {today}")

        elif 'open notepad' in query:
            speak("Opening Notepad")
            os.startfile("notepad.exe")

        elif 'open calculator' in query:
            speak("Opening Calculator")
            os.startfile("calc.exe")

        elif 'open google' in query:
            speak("Opening Google")
            webbrowser.open("https://google.com")

        elif 'open youtube' in query:
            speak("Opening YouTube")
            webbrowser.open("https://youtube.com")

        elif 'volume up' in query:
            pyautogui.press("volumeup")

        elif 'volume down' in query:
            pyautogui.press("volumedown")

        elif 'play music' in query:
            music_dir = r"C:\Users\ashutosh negi\Music"
            songs = os.listdir(music_dir)
            if songs:
                os.startfile(os.path.join(music_dir, songs[0]))
                speak("Playing music")

        else:
            try:
                speak("Searching Wikipedia")
                result = wikipedia.summary(query, sentences=1)
                speak(result)
            except:
                speak("I couldn't find that information.")

@eel.expose
def startAssistant():
    threading.Thread(target=assistant).start()

eel.start("index.html", mode="chrome", size=(1000, 650))
