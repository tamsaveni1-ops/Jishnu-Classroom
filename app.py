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
from gtts import gTTS

try:
    from streamlit_mic_recorder import speech_to_text
    mic_available = True
except ImportError:
    mic_available = False

# ==========================================
# 1. API KEYS
# ==========================================
API_KEYS = [
    st.secrets["GEMINI_API_KEY_1"],
    st.secrets["GEMINI_API_KEY_2"]
]
cooldown_tracker = {}
key_models_cache = {}

# ==========================================
# 2. THE WORLD-CLASS SYSTEM INSTRUCTION
# ==========================================
SYSTEM_INSTRUCTION = """
You are a highly energetic, world-class Digital Smart Teacher sitting right next to a Grade 8 CBSE student named Jishnu. You act with the affection and enthusiasm of a favorite teacher.

CRITICAL TEACHING METHODOLOGY:
1. THE GRAND INTRO (CHAPTER SUMMARY): If it's a new chapter, DO NOT teach paragraphs yet. Tell him a fascinating, story-like summary of the ENTIRE chapter. Explain WHY this chapter is important for his real life and what he will learn.
2. PARAGRAPH-BY-PARAGRAPH: When explaining a page, break it down paragraph by paragraph. Say: "முதல் பத்தியில..." and "ரெண்டாவது பத்தியில...".
3. MULTILINGUAL & VOCABULARY (CRITICAL): In every page explanation, pick 2 or 3 important English words from the textbook. Teach him the meaning in Tamil, and tell him how to say it in Spoken English and Spoken Hindi. 
4. INTERACTIVE TESTING: Always end your page explanation by asking one simple, thought-provoking question to check if he understood. 
5. Q&A MODE: If asked for important questions, provide the top exam-focused questions and clear answers.
6. TONE & LANGUAGE: 
   - "display_text": Concise, highly structured bullet points mapping to the paragraphs and vocabulary.
   - "spoken_tamil": 100% COLLOQUIAL SPOKEN TAMIL (பேச்சுத் தமிழ்). Use an energetic, fast-paced tone. NEVER use formal written Tamil.

OUTPUT FORMAT (STRICT JSON):
{
  "display_text": "Structured bullet points, vocabulary words, and the ending question.",
  "spoken_tamil": "100% Conversational Spoken Tamil lecture."
}
"""

# ==========================================
# 3. AI ENGINE & RAG CACHE
# ==========================================
def get_available_models(client, key_label):
    try:
        available_models = []
        for m in client.models.list():
            name = m.name.replace('models/', '')
            if 'gemini' in name.lower() and 'embed' not in name.lower() and 'aqa' not in name.lower():
                if 'tts' not in name.lower() and 'image' not in name.lower() and 'audio' not in name.lower():
                    available_models.append(name)
        return {'flash': [m for m in available_models if 'flash' in m.lower()], 'pro': [m for m in available_models if 'pro' in m.lower()]}
    except Exception:
        return {'flash': ['gemini-1.5-flash'], 'pro': ['gemini-1.5-pro']}

def generate_ai_response(contents_payload, max_attempts=2):
    for attempt in range(max_attempts):
        for key_index, key in enumerate(API_KEYS, 1):
            key_label = f"Key-{key_index}"
            if key_label in cooldown_tracker and time.time() < cooldown_tracker[key_label]: continue
            client = genai.Client(api_key=key)
            if key not in key_models_cache: key_models_cache[key] = get_available_models(client, key_label)
            for model_name in list(key_models_cache[key]['flash']):
                tracker_key = f"{key_label}_{model_name}"
                if tracker_key in cooldown_tracker and time.time() < cooldown_tracker[tracker_key]: continue
                try:
                    config = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.7, response_mime_type="application/json")
                    response = client.models.generate_content(model=model_name, contents=contents_payload, config=config)
                    if response.text: return response.text, model_name, key_label
                except Exception as e:
                    if "429" in str(e) or "Quota" in str(e): cooldown_tracker[tracker_key] = time.time() + 60
        time.sleep(2)
    return '{"display_text": "AI Server is busy.", "spoken_tamil": "சர்வர் பிஸியா இருக்கு ஜிஸ்னு, கொஞ்ச நேரம் கழிச்சு கேளு."}', "Fallback", "None"

def text_to_audio_bytes(spoken_text):
    try:
        clean_text = spoken_text.replace('*', '').replace('#', '')
        tts = gTTS(text=clean_text, lang='ta', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception: return None

def get_chapter_json_cache(subject_name, chapter_name, pdf_text):
    os.makedirs("cache", exist_ok=True)
    json_path = f"cache/{subject_name.split()[0].lower()}_{chapter_name.replace(' ', '_').lower()}.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    prompt = f"Analyze Grade 8 textbook text for Subject: {subject_name}, Chapter: {chapter_name}. Extract: 1. 'chapter_summary' 2. 'vocabulary' 3. 'key_questions' in JSON format."
    try:
        client = genai.Client(api_key=API_KEYS[0])
        response = client.models.generate_content(model='gemini-1.5-flash', contents=[prompt + "\n\n" + pdf_text[:12000]], config=types.GenerateContentConfig(response_mime_type="application/json"))
        data = json.loads(response.text)
        with open(json_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception: return {"chapter_summary": "Summary not available.", "vocabulary": [], "key_questions": []}

# ==========================================
# 4. APP SETUP & UI
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

if "memories" not in st.session_state: st.session_state.memories = {}
if "score" not in st.session_state: st.session_state.score = 0
if "last_chapter_read" not in st.session_state: st.session_state.last_chapter_read = ""
if "last_page_read" not in st.session_state: st.session_state.last_page_read = 0
if "current_audio" not in st.session_state: st.session_state.current_audio = None

with st.sidebar:
    st.header("📚 Curriculum Selection")
    selected_subject = st.selectbox("1. Select Subject:", list(cbse_syllabus.keys()))
    selected_chapter = st.selectbox("2. Select Chapter:", cbse_syllabus[selected_subject])
    st.divider()
    search_keyword = selected_subject.split()[0].lower()
    available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', f'*{search_keyword}*.pdf'), recursive=True)
    if not available_pdfs: available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', '*.pdf'), recursive=True)
    selected_pdf_path = st.selectbox("3. Choose PDF File:", available_pdfs, format_func=lambda x: os.path.basename(x)) if available_pdfs else None
    if not available_pdfs: st.error("⚠️ No PDFs found!")
    st.divider()
    page_number = st.number_input("4. Textbook Page Number:", min_value=1, max_value=500, value=1)
    
session_key = f"{selected_subject} - {selected_chapter}"
if session_key not in st.session_state.memories: st.session_state.memories[session_key] = []

col_title, col_score = st.columns([3, 1])
with col_title: st.title("🎓 Jishnu's Smart AI Classroom")
with col_score: st.header(f"🏆 Score: {st.session_state.score} PTS")

tab_classroom, tab_test, tab_english, tab_hindi = st.tabs([
    "📖 Classroom", 
    "📝 Exams", 
    "🗣️ Spoken English", 
    "🗣️ Spoken Hindi"
])

with tab_classroom:
    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader(f"📖 {selected_subject} Reader")
        page_text, cached_chapter_data = "", {}
        if selected_pdf_path:
            try:
                doc = fitz.open(selected_pdf_path)
                if page_number <= len(doc):
                    page = doc.load_page(page_number - 1)
                    st.image(page.get_pixmap().tobytes("png"), caption=f"Page {page_number}", width="stretch")
                    page_text = page.get_text("text")
                    full_pdf_text = "".join([doc.load_page(i).get_text("text") for i in range(min(15, len(doc)))])
                    cached_chapter_data = get_chapter_json_cache(selected_subject, selected_chapter, full_pdf_text)
                    with st.expander("🔍 View Extracted Text"): st.write(page_text)
                else: st.error("Page out of range.")
            except Exception as e: st.error("Error opening PDF.")

    with col2:
        st.subheader("👩‍🏫 AI Smart Teacher Interface")
        
        # ஆடியோ பிளேயர் எப்பொழுதும் மேலே (Top) இருக்கும். பழைய ஆடியோக்கள் மறைக்கப்படும்.
        if st.session_state.current_audio:
            st.audio(st.session_state.current_audio.getvalue(), format="audio/mp3", autoplay=True)
            st.caption("👆 பிளேயரை நிறுத்த அல்லது மீண்டும் கேட்க இங்கு அழுத்தவும்.")
        st.divider()

        # முக்கிய கேள்வி பதில்கள் Button
        col_btn1, col_btn2 = st.columns(2)
        qa_requested = False
        with col_btn1:
            if st.button("📝 முக்கிய கேள்வி-பதில்கள் (Q&A)"):
                qa_requested = True

        # Render Chat History (Without old audio players to keep it clean)
        for msg in st.session_state.memories[session_key]:
            with st.chat_message(msg["role"]):
                if "image" in msg: st.image(msg["image"], width="stretch")
                st.markdown(msg["content"])
        
        voice_text = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key=f'mic_{session_key}') if mic_available else ""
        text_input = st.chat_input("Ask your teacher a question...")
        
        chapter_changed = False
        if st.session_state.last_chapter_read != selected_chapter:
            chapter_changed = True
            st.session_state.last_chapter_read = selected_chapter

        page_turned = False
        if st.session_state.last_page_read != page_number:
            page_turned = True
            st.session_state.last_page_read = page_number
        
        user_input = voice_text if voice_text else text_input
        
        if qa_requested:
            user_input = "TEACHER_INSTRUCTION: ஜிஸ்னு இந்த பாடத்தின் முக்கிய கேள்வி பதில்களைக் கேட்கிறான். பாடத்தின் மிக முக்கியமான 3-5 கேள்விகளைக் கூறி, அதற்கான விடைகளை எளிமையாக விளக்கு."
        elif chapter_changed and not user_input:
            user_input = "TEACHER_INSTRUCTION: This is a new chapter. Give a grand, fascinating summary of the ENTIRE chapter to create interest. Explain why it is useful in real life. Do not teach paragraphs yet."
        elif page_turned and not user_input:
            user_input = "TEACHER_INSTRUCTION: Explain this page PARAGRAPH BY PARAGRAPH. Also teach 2-3 English/Hindi vocabulary words from this page. End by asking a question."

        if user_input:
            if not user_input.startswith("TEACHER_INSTRUCTION"):
                with st.chat_message("user"): st.markdown(user_input)
                st.session_state.memories[session_key].append({"role": "user", "content": user_input})

            with st.chat_message("assistant"):
                with st.spinner("Teacher is thinking..."):
                    prompt_context = f"""
                    Subject: {selected_subject} - {selected_chapter}
                    Current Page Number: {page_number}
                    Page Text: {page_text[:1500]}
                    Chapter Summary: {str(cached_chapter_data)[:1000]}
                    Request: {user_input}
                    """
                    bot_reply_json, used_model, used_key = generate_ai_response([prompt_context])
                    try:
                        parsed_response = json.loads(bot_reply_json)
                        display_text = parsed_response.get("display_text", "Error formatting text.")
                        spoken_tamil = parsed_response.get("spoken_tamil", bot_reply_json)
                    except:
                        display_text = bot_reply_json
                        spoken_tamil = bot_reply_json
                    
                    st.markdown(display_text)
                    
                    audio_fp = text_to_audio_bytes(spoken_tamil)
                    if audio_fp:
                        st.session_state.current_audio = audio_fp # சேமிக்கப்படும் புதிய ஆடியோ

            st.session_state.memories[session_key].append({"role": "assistant", "content": display_text})
            st.rerun()

with tab_test:
    with tab_english:
    st.header("🗣️ Spoken English Lab")
    st.write("ஜிஸ்னு, நீ இப்போது படித்துக் கொண்டிருக்கும் பக்கத்தில் உள்ள ஆங்கில வார்த்தைகளையும், வாக்கியம் அமைக்கும் முறையையும் இங்கே கற்றுக் கொள்வோம்!")
    
    if st.button("🚀 இந்தப் பக்கத்தின் English பாடத்தைத் தொடங்கு"):
        if page_text:
            with st.spinner("ஆங்கில ஆசிரியை தயார் ஆகிறார்..."):
                eng_prompt = f"""
                Act as Jishnu's Spoken English teacher. Based on this page text: {page_text[:1500]}
                1. Pick 3 hard English words from this page. Force him to say them aloud. Give Tamil meaning and pronunciation.
                2. Take 1 simple sentence from the text. Break it down and explain how to form a sentence (Subject, Verb).
                3. Ask him to form a new simple sentence based on what he learned.
                Respond strictly in JSON with "display_text" (Markdown) and "spoken_tamil" (Conversational Tamil teaching him English).
                """
                reply_json, _, _ = generate_ai_response([eng_prompt])
                try:
                    eng_data = json.loads(reply_json)
                    st.markdown(eng_data.get("display_text", ""))
                    audio_fp = text_to_audio_bytes(eng_data.get("spoken_tamil", ""))
                    if audio_fp:
                        st.audio(audio_fp.getvalue(), format="audio/mp3", autoplay=True)
                except:
                    st.markdown(reply_json)
        else:
            st.warning("முதலில் ஒரு PDF ஃபைலைத் தேர்ந்தெடு ஜிஸ்னு!")

with tab_hindi:
    st.header("🗣️ Spoken Hindi Lab")
    st.write("ஜிஸ்னு, இந்தப் பாடத்தின் கருத்துகளை வைத்து கொஞ்சம் ஹிந்தி பேசுவோமா?")
    
    if st.button("🚀 இந்தப் பக்கத்தின் Hindi பாடத்தைத் தொடங்கு"):
        if page_text:
            with st.spinner("ஹிந்தி ஆசிரியை தயார் ஆகிறார்..."):
                hin_prompt = f"""
                Act as Jishnu's Spoken Hindi teacher. Based on this page text: {page_text[:1500]}
                1. Teach 3 useful Hindi words related to the current topic (with Tamil translation & pronunciation).
                2. Teach one simple conversational sentence in Hindi related to this page.
                Respond strictly in JSON with "display_text" (Markdown) and "spoken_tamil" (Conversational Tamil teaching him Hindi).
                """
                reply_json, _, _ = generate_ai_response([hin_prompt])
                try:
                    hin_data = json.loads(reply_json)
                    st.markdown(hin_data.get("display_text", ""))
                    audio_fp = text_to_audio_bytes(hin_data.get("spoken_tamil", ""))
                    if audio_fp:
                        st.audio(audio_fp.getvalue(), format="audio/mp3", autoplay=True)
                except:
                    st.markdown(reply_json)
        else:
            st.warning("முதலில் ஒரு PDF ஃபைலைத் தேர்ந்தெடு ஜிஸ்னு!")
