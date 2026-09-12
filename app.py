import streamlit as st
from google import genai
from google.genai import types
import fitz  # PyMuPDF
from PIL import Image
import io
import os
import glob
import json
import time
import uuid
from gtts import gTTS

try:
    from streamlit_mic_recorder import speech_to_text
    mic_available = True
except ImportError:
    mic_available = False

# ==========================================
# 1. API KEYS & SMART ENGINE CONFIGURATION
# ==========================================
API_KEYS = [st.secrets["GEMINI_API_KEY_1"]] if "GEMINI_API_KEY_1" in st.secrets else ["இங்கு_உங்கள்_API_KEY_போடவும்"]

cooldown_tracker = {}
key_models_cache = {}

# THE WORLD-CLASS TEACHER PERSONA
SYSTEM_INSTRUCTION = """
You are a highly energetic, world-class Digital Smart Teacher sitting right next to a Grade 8 CBSE student named Jishnu. 

CRITICAL TEACHING METHODOLOGY:
1. NO CHATBOT VIBES: Act exactly like a real human teacher. Sit beside him, make him look at his book.
2. PARAGRAPH-BY-PARAGRAPH TEACHING (CRITICAL): When explaining a specific page, you MUST break it down paragraph by paragraph. 
   - Say: "இந்த முதல் பத்தியில (In this first paragraph)..." and explain it.
   - Say: "அடுத்து ரெண்டாவது பத்தியில பாரு..." and explain it. 
   - Make sure he can follow along with his textbook.
3. STORY-LIKE INTRO: If he starts a new chapter, do not teach paragraphs yet. Tell him a grand, fascinating story summarizing the ENTIRE chapter.
4. TONE & LANGUAGE: 
   - "display_text": Concise bullet points mapping to each paragraph.
   - "spoken_tamil": MUST be 100% COLLOQUIAL SPOKEN TAMIL (பேச்சுத் தமிழ்). Use short sentences. Use interactive hooks like "புரியுதா?", "ஏன் தெரியுமா?". NO formal written Tamil.

OUTPUT FORMAT (STRICT JSON):
{
  "display_text": "Structured bullet points matching the paragraphs.",
  "spoken_tamil": "100% Conversational Spoken Tamil lecture teaching paragraph by paragraph."
}
"""

def generate_ai_response(contents_payload, max_attempts=2):
    for attempt in range(max_attempts):
        for key in API_KEYS:
            try:
                client = genai.Client(api_key=key)
                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.7,
                    response_mime_type="application/json"
                )
                response = client.models.generate_content(
                    model='gemini-1.5-flash',
                    contents=contents_payload,
                    config=config
                )
                if response.text:
                    return response.text, 'gemini-1.5-flash'
            except Exception as e:
                time.sleep(2)
                continue
    return '{"display_text": "சர்வர் பிஸியாக உள்ளது ஜிஸ்னு. மீண்டும் கேட்கவும்.", "spoken_tamil": "சர்வர் பிஸியா இருக்கு ஜிஸ்னு. ஒரு நிமிஷம் கழிச்சு கேளு."}', "Fallback"

def text_to_audio_bytes(spoken_text):
    try:
        clean_text = spoken_text.replace('*', '').replace('#', '') 
        tts = gTTS(text=clean_text, lang='ta', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception:
        return None

def get_chapter_json_cache(subject_name, chapter_name, pdf_text):
    os.makedirs("cache", exist_ok=True)
    safe_subject = subject_name.split()[0].lower()
    safe_chapter = chapter_name.replace(" ", "_").lower()
    json_path = f"cache/{safe_subject}_{safe_chapter}.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    prompt = f"Analyze Grade 8 {subject_name}, {chapter_name}. Return JSON: {{'chapter_summary': '...', 'vocabulary': [], 'key_questions': []}}"
    try:
        client = genai.Client(api_key=API_KEYS[0])
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(model='gemini-1.5-flash', contents=[prompt + "\n" + pdf_text[:12000]], config=config)
        data = json.loads(response.text)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return {"chapter_summary": "Summary not available.", "vocabulary": [], "key_questions": []}

# ==========================================
# APP SETUP & UI
# ==========================================
st.set_page_config(layout="wide", page_title="Jishnu's Smart AI Classroom", page_icon="🎓")

BOOKS_DIR = "ncert_books"
cbse_syllabus = {
    "Mathematics": [f"Chapter {i}" for i in range(1, 20)],
    "Science": [f"Chapter {i}" for i in range(1, 20)],
    "Social Science": [f"Chapter {i}" for i in range(1, 35)],
    "English": [f"Chapter {i}" for i in range(1, 20)],
    "Hindi": [f"Chapter {i}" for i in range(1, 20)],
    "Sanskrit": [f"Chapter {i}" for i in range(1, 20)],
}

if "memories" not in st.session_state:
    st.session_state.memories = {}
if "score" not in st.session_state:
    st.session_state.score = 0
if "last_chapter_read" not in st.session_state:
    st.session_state.last_chapter_read = ""
if "last_page_read" not in st.session_state:
    st.session_state.last_page_read = 0

with st.sidebar:
    st.header("📚 Curriculum & Chapter Selection")
    selected_subject = st.selectbox("1. Select Subject:", list(cbse_syllabus.keys()))
    selected_chapter = st.selectbox("2. Select Chapter:", cbse_syllabus[selected_subject])
    st.divider()
    
    search_keyword = selected_subject.split()[0].lower()
    available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', f'*{search_keyword}*.pdf'), recursive=True)
    if not available_pdfs:
        available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', '*.pdf'), recursive=True)
        
    selected_pdf_path = st.selectbox("3. Choose PDF File:", available_pdfs, format_func=lambda x: os.path.basename(x)) if available_pdfs else None
    st.divider()
    page_number = st.number_input("4. Textbook Page Number:", min_value=1, max_value=500, value=1)

session_key = f"{selected_subject} - {selected_chapter}"
if session_key not in st.session_state.memories:
    st.session_state.memories[session_key] = []

col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 Jishnu's Smart AI Classroom")
with col_score:
    st.header(f"🏆 Score: {st.session_state.score} PTS")

tab_classroom, tab_test = st.tabs(["📖 AI Teacher Interface", "📝 Exams & Quizzes"])

with tab_classroom:
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("📖 Textbook Reader")
        page_text = ""
        cached_chapter_data = {}

        if selected_pdf_path:
            try:
                doc = fitz.open(selected_pdf_path)
                if page_number <= len(doc):
                    page = doc.load_page(page_number - 1)
                    pix = page.get_pixmap()
                    st.image(pix.tobytes("png"), caption=f"Page {page_number}", width="stretch")
                    page_text = page.get_text("text")
                    
                    full_pdf_text = "".join([doc.load_page(i).get_text("text") for i in range(min(15, len(doc)))])
                    cached_chapter_data = get_chapter_json_cache(selected_subject, selected_chapter, full_pdf_text)
            except Exception as e:
                st.error("Error opening PDF.")

    with col2:
        st.subheader("👩‍🏫 AI Tutor")
        
        # Audio Player Place (Always at top for easy stopping)
        audio_placeholder = st.empty()
        
        for msg in st.session_state.memories[session_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if "audio" in msg and msg["audio"]:
                    st.audio(msg["audio"].getvalue(), format="audio/mp3")

        # SMART TRIGGERS FOR TEACHING
        chapter_changed = (st.session_state.last_chapter_read != selected_chapter)
        page_changed = (st.session_state.last_page_read != page_number)
        
        user_input = st.chat_input("Ask your teacher...")
        voice_text = speech_to_text(language='ta-IN', just_once=True, key='mic') if mic_available else ""
        if voice_text: user_input = voice_text

        # 1. New Chapter Intro Trigger
        if chapter_changed and not user_input:
            user_input = "TEACHER_INSTRUCTION: This is a new chapter. Jishnu just opened it. Give a fascinating, story-like summary of the entire chapter to create interest. Do not teach paragraphs yet."
            st.session_state.last_chapter_read = selected_chapter
            st.session_state.last_page_read = page_number
            
        # 2. Page Paragraph-by-Paragraph Trigger
        elif page_changed and not user_input:
            user_input = "TEACHER_INSTRUCTION: Jishnu is looking at this exact page now. Look at the page text. Explain it PARAGRAPH BY PARAGRAPH. Say 'முதல் பத்தியில...' and explain clearly."
            st.session_state.last_page_read = page_number

        if user_input:
            if not user_input.startswith("TEACHER_INSTRUCTION"):
                with st.chat_message("user"): st.markdown(user_input)
                st.session_state.memories[session_key].append({"role": "user", "content": user_input})

            with st.chat_message("assistant"):
                with st.spinner("Teacher is reading the textbook..."):
                    
                    dynamic_prompt = f"""
                    Subject: {selected_subject} - {selected_chapter}
                    Current Page: {page_number}
                    Text on this page: {page_text}
                    
                    Student/System Request: {user_input}
                    
                    Remember: If teaching a page, explicitly break it down by paragraphs so he can follow along in the book!
                    """
                    
                    reply_json, used_model = generate_ai_response([dynamic_prompt])
                    
                    try:
                        parsed = json.loads(reply_json)
                        display_text = parsed.get("display_text", "Error parsing text.")
                        spoken_tamil = parsed.get("spoken_tamil", reply_json)
                    except:
                        display_text, spoken_tamil = reply_json, reply_json
                        
                    st.markdown(display_text)
                    
                    audio_fp = text_to_audio_bytes(spoken_tamil)
                    if audio_fp:
                        # Autoplay at the top placeholder so it's easy to stop
                        audio_placeholder.audio(audio_fp.getvalue(), format="audio/mp3", autoplay=True)

            st.session_state.memories[session_key].append({
                "role": "assistant", 
                "content": display_text,
                "audio": audio_fp
            })
            st.rerun()

with tab_test:
    st.write("Generate interactive quizzes and custom exam papers for Grade 8 CBSE.")
