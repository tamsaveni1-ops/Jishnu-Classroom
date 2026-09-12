import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from gtts import gTTS
import base64
import os
import glob
import gdown
from streamlit_mic_recorder import speech_to_text

# --- 1. API செட்டப் ---
API_KEY = "AQ.Ab8RN6K3cb-7jBBUdAuJsAcfALtzSdUoWEVJdLAPDfqUmgK7GA"
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

# --- 3. கூகுள் டிரைவ் ஃபோல்டரிலிருந்து புத்தகங்களை ஆட்டோ-டவுன்லோட் செய்தல் ---
FOLDER_ID = "1e99M6r3j2_tRAsNksl52jb3E-fl09s6S"
BOOKS_DIR = "ncert_books"

@st.cache_resource
def download_drive_books():
    if not os.path.exists(BOOKS_DIR) or len(os.listdir(BOOKS_DIR)) == 0:
        os.makedirs(BOOKS_DIR, exist_ok=True)
        url = f'https://drive.google.com/drive/folders/{FOLDER_ID}'
        with st.spinner("📚 ஜிஷ்ணுவின் புத்தகங்கள் கூகுள் டிரைவில் இருந்து டவுன்லோட் ஆகின்றன... சிறிது நேரம் காத்திருக்கவும் ⏳"):
            try:
                gdown.download_folder(url, output=BOOKS_DIR, quiet=False, use_cookies=False)
                st.success("புத்தகங்கள் வெற்றிகரமாக டவுன்லோட் ஆகிவிட்டன!")
            except Exception as e:
                st.error(f"டவுன்லோட் செய்வதில் பிழை: {e}")

download_drive_books()

# --- 4. 8-ஆம் வகுப்பு CBSE பாடத்திட்ட அமைப்பு (6 Subjects) ---
cbse_syllabus = {
    "Mathematics (கணிதம்)": ["Part 1", "Part 2"],
    "Social Science (சமூக அறிவியல்)": ["Part 1", "Part 2"],
    "Science (அறிவியல்)": ["Full Book"],
    "English (ஆங்கிலம்)": ["Full Book"],
    "Hindi (இந்தி)": ["Full Book"],
    "Sanskrit (சமஸ்கிருதம்)": ["Full Book"]
}

# டிரைவில் டவுன்லோட் ஆன அனைத்து PDF ஃபைல்களையும் தேடும் வசதி
def find_matching_pdf(subject_name, part_name):
    all_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', '*.pdf'), recursive=True)
    if not all_pdfs:
        all_pdfs = glob.glob('*.pdf')
    
    # சப்ஜெக்ட் மற்றும் பார்ட் பெயருக்கு ஏற்ற ஃபைலைத் துல்லியமாகத் தேடுதல்
    for path in all_pdfs:
        fname = os.path.basename(path).lower()
        sub_key = subject_name.split()[0].lower() # எ.கா: maths, science
        if sub_key in fname:
            if "part" in part_name.lower():
                if part_name.lower().replace(" ", "") in fname.replace(" ", ""):
                    return path
            else:
                return path
                
    # ஒருவேளை பெயர்கள் மாறாக இருந்தால், முதல் கிடைக்கும் PDF-ஐத் தரும்
    return all_pdfs[0] if all_pdfs else ""

# --- 5. நினைவாற்றல் மற்றும் பாயிண்ட்ஸ் செட்டப் ---
subjects_flat_list = []
for subj, parts in cbse_syllabus.items():
    for p in parts:
        subjects_flat_list.append(f"{subj} - {p}")

if "memories" not in st.session_state:
    st.session_state.memories = {item: [] for item in subjects_flat_list}
if "chat_sessions" not in st.session_state:
    st.session_state.chat_sessions = {item: model.start_chat(history=[]) for item in subjects_flat_list}
if "score" not in st.session_state:
    st.session_state.score = 0

st.set_page_config(layout="wide", page_title="ஜிஷ்ணுவின் ஸ்மார்ட் கிளாஸ்ரூம்")

# --- 6. தலைப்பு மற்றும் ஸ்கோர் போர்டு ---
col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 ஜிஷ்ணுவின் சூப்பர் கிளாஸ்ரூம்")
with col_score:
    st.header(f"🏆 ஸ்கோர்: {st.session_state.score}")

# --- 7. பக்கவாட்டு மெனு (Subject & Book Selection) ---
with st.sidebar:
    st.header("📚 பாடத்தைத் தேர்ந்தெடு")
    
    selected_subject = st.selectbox("சப்ஜெக்ட்:", list(cbse_syllabus.keys()))
    selected_part = st.selectbox("புத்தகம் / பகுதி:", cbse_syllabus[selected_subject])
    
    page_number = st.number_input("பக்க எண்:", min_value=1, max_value=1000, value=1)
    
    current_selection_key = f"{selected_subject} - {selected_part}"
    pdf_path = find_matching_pdf(selected_subject, selected_part)

# --- 8. மெயின் திரை (PDF மற்றும் உரையாடல்) ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader(f"📖 {selected_subject} ({selected_part})")
    page_text = ""
    
    if pdf_path and os.path.exists(pdf_path):
        try:
            doc = fitz.open(pdf_path)
            if page_number <= len(doc):
                page = doc.load_page(page_number - 1)
                pix = page.get_pixmap()
                img_bytes = pix.tobytes("png")
                st.image(img_bytes, caption=f"பக்கம் {page_number} (மொத்த பக்கங்கள்: {len(doc)})", use_column_width=True)
                
                page_text = page.get_text("text")
                with st.expander("🔍 இந்த பக்கத்தில் உள்ள முக்கிய வரிகள்"):
                    st.write(page_text)
            else:
                st.error(f"இந்தப் புத்தகத்தில் மொத்தம் {len(doc)} பக்கங்கள் மட்டுமே உள்ளன.")
        except Exception as e:
            st.error(f"PDF வாசிப்பதில் பிழை: {e}")
    else:
        st.info("📁 புத்தகங்கள் கூகுள் டிரைவில் இருந்து லோட் ஆகிக்கொண்டிருக்கின்றன... சிறிது நேரம் காத்திருக்கவும்.")

with col2:
    st.subheader(f"👩‍🏫 {selected_subject} ஆசிரியர்")
    
    for msg in st.session_state.memories[current_selection_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.write("🎤 **மைக்கில் பேசு:**")
    voice_input = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key='mic')
    
    text_input = st.chat_input("அல்லது இங்கே டைப் செய்...")
    user_input = voice_input if voice_input else text_input

    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)
        st.session_state.memories[current_selection_key].append({"role": "user", "content": user_input})
        
        with st.chat_message("assistant"):
            with st.spinner("ஆசிரியர் அன்புடனும் பொறுமையாகவும் பதிலளிக்கிறார்..."):
                full_prompt = f"மாணவன் ஜிஷ்ணுவின் கேள்வி/பதில்: {user_input}\n\nதற்போது அவன் படிக்கும் புத்தகப் பக்கம்: {page_text}"
                response = st.session_state.chat_sessions[current_selection_key].send_message(full_prompt)
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

        st.session_state.memories[current_selection_key].append({"role": "assistant", "content": bot_reply})
        st.rerun()
