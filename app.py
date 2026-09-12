import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from gtts import gTTS
import base64
import os
import gdown
from streamlit_mic_recorder import speech_to_text

# --- 1. API செட்டப் ---
API_KEY = "YOUR_API_KEY_HERE"  # உங்கள் ஜெமினி API Key-ஐ இங்கே போடவும்
genai.configure(api_key=API_KEY)

# --- 2. தாயும் ஆசிரியருமான மேம்படுத்தப்பட்ட AI Persona ---
teacher_persona = """
நீ 14 வயது மாணவன் ஜிஷ்ணுவுக்கு 8-ஆம் வகுப்பு பாடங்களை நடத்தும் ஒரு உலகத்தரம் வாய்ந்த டிஜிட்டல் ஆசிரியர். 
அதே சமயம், ஒரு தாயின் அன்போடும், பரிவோடும் அவனுக்குப் பாடம் சொல்லிக் கொடுக்க வேண்டும்.
உன் முக்கிய நோக்கங்கள்:
1. ஆரம்பத்தில் அவனுக்குத் தாய்மொழியான தமிழில் மிக எளிமையாக, ஒரு அம்மா கதை சொல்வது போல விளக்க வேண்டும். 
2. போகப்போக ஆங்கிலம் மற்றும் ஹிந்தி வார்த்தைகளை உரையாடலில் கலந்து, அவனையும் அந்த மொழிகளில் பேசத் தூண்ட வேண்டும்.
3. அவன் நன்றாகப் பதில் சொன்னால், "மிகவும் சிறப்பு ஜிஷ்ணு கண்ணா! உனக்கு 10 பாயிண்டுகள்!" என்று சொல்லி அவனை உற்சாகப்படுத்த வேண்டும்.
4. அவன் கேட்கும் கேள்விகளுக்குக் கோபப்படாமல், மிகப்பொறுமையாகப் பதிலளிக்க வேண்டும்.
"""
model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=teacher_persona)

# --- 3. 6 பாடங்கள் மற்றும் புத்தக அமைப்பு ---
cbse_syllabus = {
    "Mathematics (கணிதம்)": ["Part 1", "Part 2"],
    "Social Science (சமூக அறிவியல்)": ["Part 1", "Part 2"],
    "Science (அறிவியல்)": ["Full Book"],
    "English (ஆங்கிலம்)": ["Full Book"],
    "Hindi (இந்தி)": ["Full Book"],
    "Sanskrit (சமஸ்கிரிதம்)": ["Full Book"]
}

# --- 4. கூகுள் டிரைவ் ஃபோல்டரிலிருந்து 400 MB புத்தகங்களை ஆட்டோ-டவுன்லோட் செய்தல் ---
FOLDER_ID = "1e99M6r3j2_tRAsNksl52jb3E-fl09s6S"
BOOKS_DIR = "ncert_books"

@st.cache_resource
def download_drive_books():
    if not os.path.exists(BOOKS_DIR) or len(os.listdir(BOOKS_DIR)) == 0:
        os.makedirs(BOOKS_DIR, exist_ok=True)
        url = f'https://drive.google.com/drive/folders/{FOLDER_ID}'
        with st.spinner("📚 ஜிஷ்ணுவின் புத்தகங்கள் கூகுள் டிரைவில் இருந்து டவுன்லோட் ஆகின்றன... (400 MB என்பதால் சிறிது நேரம் ஆகும்) ⏳"):
            try:
                gdown.download_folder(url, output=BOOKS_DIR, quiet=False, use_cookies=False)
                st.success("புத்தகங்கள் வெற்றிகரமாக டவுன்லோட் ஆகிவிட்டன!")
            except Exception as e:
                st.error(f"டவுன்லோட் செய்வதில் சிறு துகள்: {e}")

download_drive_books()

# --- 5. நினைவாற்றல் மற்றும் பாயிண்ட்ஸ் செட்டப் ---
subjects_list = list(cbse_syllabus.keys())

if "memories" not in st.session_state:
    st.session_state.memories = {subj: [] for subj in subjects_list}
if "chat_sessions" not in st.session_state:
    st.session_state.chat_sessions = {subj: model.start_chat(history=[]) for subj in subjects_list}
if "score" not in st.session_state:
    st.session_state.score = 0

st.set_page_config(layout="wide", page_title="ஜிஷ்ணுவின் ஸ்மார்ட் கிளாஸ்ரூம்")

# --- 6. தலைப்பு மற்றும் ஸ்கோர் போர்டு ---
col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 ஜிஷ்ணுவின் சூப்பர் கிளாஸ்ரூம்")
with col_score:
    st.header(f"🏆 ஸ்கோர்: {st.session_state.score}")

# --- 7. பக்கவாட்டு மெனு (Menu) ---
with st.sidebar:
    st.header("📚 பாடத்தைத் தேர்ந்தெடு")
    
    selected_subject = st.selectbox("சப்ஜெக்ட்:", subjects_list)
    selected_part = st.selectbox("புத்தகம் / பகுதி:", cbse_syllabus[selected_subject])
    page_number = st.number_input("பக்க எண்:", min_value=1, max_value=1000, value=1)
    
    pdf_path = f"{BOOKS_DIR}/{selected_subject}_{selected_part}.pdf"

# --- 8. மெயின் திரை (PDF மற்றும் உரையாடல்) ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📖 பாடப்புத்தகம் & ஃபோகஸ் மோடு")
    page_text = ""
    
    if os.path.exists(pdf_path):
        doc = fitz.open(pdf_path)
        if page_number <= len(doc):
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            st.image(img_bytes, caption=f"பக்கம் {page_number}", use_column_width=True)
            
            page_text = page.get_text("text")
            with st.expander("🔍 இந்த பக்கத்தில் உள்ள முக்கிய வரிகள்"):
                st.write(page_text)
        else:
            st.error("இந்தப் பக்க எண் புத்தகத்தில் இல்லை.")
    else:
        st.info(f"📁 புத்தக ஃபைல் தேடப்படுகிறது... (டிரைவில் இருந்து முழுப் புத்தகமும் லோட் ஆனவுடன் பக்கம் தெரியும்)")

with col2:
    st.subheader(f"👩‍🏫 {selected_subject} ஆசிரியர்")
    
    for msg in st.session_state.memories[selected_subject]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.write("🎤 **மைக்கில் பேசு:**")
    voice_input = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key='mic')
    
    text_input = st.chat_input("அல்லது இங்கே டைப் செய்...")
    user_input = voice_input if voice_input else text_input

    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)
        st.session_state.memories[selected_subject].append({"role": "user", "content": user_input})
        
        with st.chat_message("assistant"):
            with st.spinner("ஆசிரியர் பதிலளிக்கிறார்..."):
                full_prompt = f"மாணவன் ஜிஷ்ணுவின் கேள்வி/பதில்: {user_input}\n\nதற்போது அவன் படிக்கும் பாடத்தின் வரிகள்: {page_text}"
                response = st.session_state.chat_sessions[selected_subject].send_message(full_prompt)
                bot_reply = response.text
                st.markdown(bot_reply)
                
                if "10 பாயிண்டுகள்" in bot_reply:
                    st.session_state.score += 10
                
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

        st.session_state.memories[selected_subject].append({"role": "assistant", "content": bot_reply})
        st.rerun()
