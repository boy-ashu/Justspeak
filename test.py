import pyttsx3
import random
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

is_speaking = False
r = sr.Recognizer()
r.energy_threshold = 400 
r.dynamic_energy_threshold = False
spell = SpellChecker()

def run_speech(text):
    global is_speaking
    is_speaking = True 
    pythoncom.CoInitialize() 
    
    try:
        engine = pyttsx3.init('sapi5')
        engine.setProperty('rate', 190) 
        voices = engine.getProperty('voices')
        if len(voices) > 1:
            engine.setProperty('voice', voices[1].id)
        
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"Speech Error: {e}")
    finally:
        pythoncom.CoUninitialize()
        is_speaking = False

def speak(text):
    print(f"Saarthi: {text}")
    t = threading.Thread(target=run_speech, args=(text,))
    t.start()

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

    with sr.Microphone() as source:
        print("Listening...")
        r.pause_threshold = 0.8 
        audio = r.listen(source)

    try:
        query = r.recognize_google(audio, language="en-in")
        print(f"User: {query}")
        return query.lower()
    except:
        return ""
    
custom_words = [
    "google", "youtube", "notepad", "calculator", "music",
    "play", "open", "volume", "code", "time", "date",
    "whatsapp", "spotify"
]
spell.word_frequency.load_words(custom_words)

def auto_correct(text):
    words = text.split()
    corrected = []

    for w in words:
        cw = spell.correction(w)
        corrected.append(cw if cw else w)

    return " ".join(corrected)

def newCommand():
    query = takeCommand()
    if query:
        corrected_query = auto_correct(query)
        if corrected_query != query:
            print(f"AutoCorrected : {query} ->{corrected_query}")
        return corrected_query
    return query

if __name__ == "__main__":
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.5)
    
    wishme()

    while True: 
        query = takeCommand()
        if not query:
           continue

        if 'exit' in query or 'stop' in query or 'bye' in query:
            speak("Goodbye Sir! Have a productive day.")
            time.sleep(2)
            break
        
        elif 'how are you' in query:
            speak("I am doing great, Sir! How about you?")

        elif 'the time' in query:
            strTime = datetime.datetime.now().strftime("%I:%M %p") 
            speak(f"It is {strTime}")

        elif 'the date' in query:
            today = datetime.date.today().strftime("%B %d, %Y")
            speak(f"Sir Today is {today}")

        elif 'volume up' in query:
            pyautogui.press("volumeup")
            speak("Volume increased")

        elif 'volume down' in query:
            pyautogui.press("volumedown")
            speak("Volume decreased")

        elif 'open notepad' in query:
            speak("Opening Notepad")
            os.system("notepad.exe")

        elif 'open calculator' in query:
            speak("Opening Calculator")
            os.system()

        elif 'open google' in query:
            speak("Opening Google.")
            webbrowser.open("google.com")

        elif 'open youtube' in query:
            speak("Opening YouTube.")
            webbrowser.open("youtube.com")

        elif 'play music' in query:
            music_dir = r"C:\Users\ashutosh negi\Music" 
            
            try:
                songs = [f for f in os.listdir(music_dir) if f.endswith(('.mp3', '.wav', '.m4a'))]
                
                if len(songs) > 0:
                    speak(f"Playing {songs[0]}")
                    os.startfile(os.path.join(music_dir, songs[0]))
                else:
                    speak("Sir, I found the music folder, but there are no music files in it.")
            except FileNotFoundError:
                speak("I could not find your music directory. Please check the folder path in the code.")
            
            
        elif 'open vs code' in query or 'open code' in query:
            codepath = r"C:\Users\ashutosh negi\AppData\Local\Programs\Microsoft VS Code\Code.exe"
            
            if os.path.exists(codepath):
                speak("Opening Visual Studio Code")
                os.startfile(codepath)
            else:
                speak("Sir, I couldn't find the VS Code executable. Please check the installation path.")

        else:
            try:
                search_query = query.replace("what is", "").replace("who is", "").strip()
                if search_query:
                    speak(f"Looking up {search_query}...")
                    results = wikipedia.summary(search_query, sentences=1)
                    speak(results) 
            except:
                speak("I couldn't find that information.")