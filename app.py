import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from gtts import gTTS
import base64
import os
import requests
from streamlit_mic_recorder import speech_to_text # மைக்ரோஃபோன் வசதிக்காக

# 1. API செட்டப்
API_KEY = "AQ.Ab8RN6K3cb-7jBBUdAuJsAcfALtzSdUoWEVJdLAPDfqUmgK7GA"
genai.configure(api_key=API_KEY)

# 2. ஜெமினிக்கான மேம்படுத்தப்பட்ட ஆசிரியர் Prompt (Language Progression & Points)
teacher_persona = """
நீ 14 வயது மாணவன் ஜிஷ்ணுவுக்கு 8-ஆம் வகுப்பு பாடங்களை நடத்தும் ஒரு உலகத்தரம் வாய்ந்த டிஜிட்டல் ஆசிரியர். 
உன் முக்கிய நோக்கங்கள்:
1. ஆரம்பத்தில் அவனுக்குத் தாய்மொழியான தமிழில் மிக எளிமையாக விளக்க வேண்டும். 
2. போகப்போக ஆங்கிலம் மற்றும் ஹிந்தி வார்த்தைகளை உரையாடலில் கலந்து, அவனையும் அந்த மொழிகளில் பேசத் தூண்ட வேண்டும்.
3. அவன் நன்றாகப் பதில் சொன்னால், "சிறப்பு ஜிஷ்ணு! உனக்கு 10 பாயிண்டுகள்!" என்று சொல்லி அவனை உற்சாகப்படுத்த வேண்டும்.
4. அவன் கேட்கும் கேள்விகளுக்குப் பொறுமையாக ஆடியோ மூலம் பேசுவது போலப் பதிலளிக்க வேண்டும்.
"""
model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=teacher_persona)

# 3. நினைவாற்றல் மற்றும் பாயிண்ட்ஸ் செட்டப்
if "memories" not in st.session_state:
    st.session_state.memories = {"Maths": [], "Science": [], "English": [], "Hindi": []}
if "chat_sessions" not in st.session_state:
    st.session_state.chat_sessions = {
        "Maths": model.start_chat(history=[]), "Science": model.start_chat(history=[]),
        "English": model.start_chat(history=[]), "Hindi": model.start_chat(history=[])
    }
if "score" not in st.session_state:
    st.session_state.score = 0

st.set_page_config(layout="wide", page_title="ஜிஷ்ணுவின் ஸ்மார்ட் கிளாஸ்ரூம்")

# தலைப்பு மற்றும் ஸ்கோர் போர்டு
col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 ஜிஷ்ணுவின் சூப்பர் கிளாஸ்ரூம்")
with col_score:
    st.header(f"🏆 ஸ்கோர்: {st.session_state.score}")

# 4. ஆட்டோ டவுன்லோட் வசதி (Auto-Download Function)
def download_pdf(subject, chapter_name):
    # இது ஒரு உதாரண URL. NCERT லிங்குகளை இங்கே கொடுக்கலாம்.
    url = f"https://ncert.nic.in/textbook/pdf/{chapter_name}.pdf" 
    folder = f"ncert_books/{subject}"
    os.makedirs(folder, exist_ok=True)
    filepath = f"{folder}/{chapter_name}.pdf"
    
    if not os.path.exists(filepath):
        st.info("புத்தகம் டவுன்லோட் ஆகிறது... காத்திருக்கவும் ⏳")
        response = requests.get(url)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(response.content)
            st.success("டவுன்லோட் முடிந்தது!")
    return filepath

# பக்கவாட்டு மெனு
with st.sidebar:
    st.header("📚 பாடத்தைத் தேர்ந்தெடு")
    subject = st.selectbox("சப்ஜெக்ட்:", ["Maths", "Science", "English", "Hindi"])
    chapter = st.text_input("பாடத்தின் பெயர் (எ.கா: jems101):", "jems101")
    page_number = st.number_input("பக்க எண்:", min_value=1, max_value=500, value=1)
    
    if st.button("பாடத்தைக் கொண்டுவா"):
        pdf_path = download_pdf(subject, chapter)
        st.session_state.current_pdf = pdf_path

# 5. மெயின் திரை (PDF மற்றும் உரையாடல்)
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📖 பாடப்புத்தகம் & ஃபோகஸ் மோடு")
    page_text = ""
    if "current_pdf" in st.session_state and os.path.exists(st.session_state.current_pdf):
        doc = fitz.open(st.session_state.current_pdf)
        if page_number <= len(doc):
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            st.image(img_bytes, caption=f"பக்கம் {page_number}", use_column_width=True)
            
            # Focus Mode: வரியைத் தனியாக எடுத்துக் காட்டுதல்
            page_text = page.get_text("text")
            with st.expander("🔍 இந்த பக்கத்தில் உள்ள முக்கிய வரிகள் (படிக்க வசதியாக)"):
                st.write(page_text)

with col2:
    st.subheader(f"👨‍🏫 {subject} ஆசிரியர்")
    
    # பழைய மெசேஜ்கள்
    for msg in st.session_state.memories[subject]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 6. மைக்ரோஃபோன் வசதி (Voice Input)
    st.write("🎤 **மைக்கில் பேசு:**")
    voice_input = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key='mic')
    
    # டெக்ஸ்ட் இன்புட் (விருப்பப்பட்டால் டைப் செய்ய)
    text_input = st.chat_input("அல்லது இங்கே டைப் செய்...")
    
    user_input = voice_input if voice_input else text_input

    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)
        st.session_state.memories[subject].append({"role": "user", "content": user_input})
        
        with st.chat_message("assistant"):
            with st.spinner("ஆசிரியர் பதிலளிக்கிறார்..."):
                full_prompt = f"மாணவனின் கேள்வி/பதில்: {user_input}\n\nபாடத்தின் பக்கம்: {page_text}"
                response = st.session_state.chat_sessions[subject].send_message(full_prompt)
                bot_reply = response.text
                st.markdown(bot_reply)
                
                # ஸ்கோர் அப்டேட் (ஜெமினி பாயிண்ட் கொடுத்தால் அதைக் கூட்டிக்கொள்ள)
                if "10 பாயிண்டுகள்" in bot_reply:
                    st.session_state.score += 10
                
                # ஆடியோ பதில்
                try:
                    tts = gTTS(text=bot_reply, lang='ta')
                    tts.save("reply.mp3")
                    audio_file = open("reply.mp3", "rb")
                    audio_bytes = audio_file.read()
                    audio_base64 = base64.b64encode(audio_bytes).decode()
                    audio_html = f'<audio autoplay controls><source src="data:audio/mp3;base64,{audio_base64}" type="audio/mp3"></audio>'
                    st.markdown(audio_html, unsafe_allow_html=True)
                except:
                    pass

        st.session_state.memories[subject].append({"role": "assistant", "content": bot_reply})
        st.rerun() # ஸ்கோர் அப்டேட் ஆக திரையை ரெஃப்ரெஷ் செய்ய
