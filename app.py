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

# Voice recorder import with fallback
try:
    from streamlit_mic_recorder import speech_to_text
    mic_available = True
except ImportError:
    mic_available = False

# ==========================================
# 1. API KEYS & SMART ENGINE CONFIGURATION
# ==========================================
# பாதுகாப்பான முறையில் இரண்டு API Key-களை எடுக்கிறோம்
API_KEYS = [
    st.secrets["GEMINI_API_KEY_1"],
    st.secrets["GEMINI_API_KEY_2"]
]

cooldown_tracker = {}
key_models_cache = {}

# ADVANCED SYSTEM INSTRUCTION: Focus on separating Audio and Text output
SYSTEM_INSTRUCTION = """
You are a highly energetic, friendly, and real human-like Digital Tutor sitting right next to a Grade 8 CBSE student named Jishnu. You act with the affection and enthusiasm of a favorite teacher or mother.

CRITICAL BEHAVIOR RULES:
1. NO TIME WASTING: DO NOT repeat Jishnu's question. Jump straight into the explanation immediately with high energy.
2. THE "SITTING NEXT TO YOU" VIBE: Speak as if you are sitting right next to Jishnu. Use an energetic, fast-paced, and highly interactive tone. Ask rhetorical questions like "புரியுதா?", "ஏன் தெரியுமா?", "இப்ப பாரு" to keep him hooked.
3. WHOLE CHAPTER LECTURE: If it is a new chapter, start by giving a grand, exciting summary of the entire chapter. Make it sound like a fascinating story, not a boring lecture.
4. DEEP DIVE ON PAGES: Explain the core concepts with relatable, real-world examples (like cricket, video games, or daily life).
5. MULTILINGUAL ENCOURAGEMENT: After explaining in Tamil, gradually introduce English and Hindi technical terms.
6. REWARDS & ENCOURAGEMENT: When Jishnu answers correctly, praise him exactly with this phrase: "மிகவும் சிறப்பு ஜிஷ்ணு கண்ணா! உனக்கு 10 பாயிண்டுகள்!"
7. EVALUATION & ENGAGEMENT: Scan uploaded sheets carefully. Correct mistakes gently. 
8. STRICT LANGUAGE SEPARATION (CRITICAL FOR AUDIO): 
   - "display_text": Use clear, concise Markdown bullet points (English/Tamil) for the screen.
   - "spoken_tamil": MUST be in 100% COLLOQUIAL SPOKEN TAMIL (பேச்சுத் தமிழ்). DO NOT use formal written Tamil (எழுத்துத் தமிழ்). Instead of "நாம் காண்போம்", use "நாம பாக்கலாம்". Instead of "விளக்குகிறேன்", use "சொல்லித் தர்றேன்". Keep the sentences short, punchy, and natural.

OUTPUT FORMAT (STRICT JSON):
{
  "display_text": "Highly structured, bite-sized bullet points for easy reading.",
  "spoken_tamil": "100% Colloquial Spoken Tamil (பேச்சுத் தமிழ்). Energetic, short sentences. Sounds exactly like a human sitting next to him."
}
"""

# ==========================================
# 2. MULTI-KEY & MULTI-MODEL FAILOVER ENGINE
# ==========================================
def get_available_models(client, key_label):
    try:
        available_models = []
        for m in client.models.list():
            name = m.name.replace('models/', '')
            if 'gemini' in name.lower() and 'embed' not in name.lower() and 'aqa' not in name.lower():
                if 'tts' not in name.lower() and 'image' not in name.lower() and 'audio' not in name.lower():
                    available_models.append(name)
        
        flash_models = [m for m in available_models if 'flash' in m.lower()]
        pro_models = [m for m in available_models if 'pro' in m.lower()]
        return {'flash': flash_models, 'pro': pro_models}
    except Exception:
        return {'flash': ['gemini-1.5-flash'], 'pro': ['gemini-1.5-pro']}

def generate_ai_response(contents_payload, max_attempts=2):
    for attempt in range(max_attempts):
        for key_index, key in enumerate(API_KEYS, 1):
            key_label = f"Key-{key_index}"
            if key_label in cooldown_tracker and time.time() < cooldown_tracker[key_label]:
                continue

            client = genai.Client(api_key=key)
            if key not in key_models_cache:
                key_models_cache[key] = get_available_models(client, key_label)

            for model_name in list(key_models_cache[key]['flash']):
                tracker_key = f"{key_label}_{model_name}"
                if tracker_key in cooldown_tracker and time.time() < cooldown_tracker[tracker_key]:
                    continue

                try:
                    # Enforce JSON output response to easily separate text and audio
                    config = types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.7,
                        response_mime_type="application/json"
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents_payload,
                        config=config
                    )
                    if response.text:
                        return response.text, model_name, key_label
                except Exception as e:
                    err_msg = str(e)
                    if "404" in err_msg:
                        key_models_cache[key]['flash'].remove(model_name)
                    elif "429" in err_msg or "Quota" in err_msg:
                        cooldown_tracker[tracker_key] = time.time() + 60
                    elif "403" in err_msg:
                        cooldown_tracker[key_label] = time.time() + 3600
                        break
        time.sleep(2)

    return '{"display_text": "AI Server is currently busy. Please try asking again in a few seconds!", "spoken_tamil": "மன்னிக்கவும் ஜிஸ்னு, சர்வர் கொஞ்சம் பிஸியாக இருக்கிறது. சிறிது நேரம் கழித்து மீண்டும் கேட்கவும்."}', "Fallback", "None"

def text_to_audio_bytes(spoken_text):
    try:
        # Clean specific text for pure TTS voice
        clean_text = spoken_text.replace('*', '').replace('#', '')
        tts = gTTS(text=clean_text, lang='ta', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception:
        return None

# ==========================================
# 3. LOCAL JSON CACHE ENGINE (RAG)
# ==========================================
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

    prompt = f"""
    Analyze the following Grade 8 textbook text for Subject: {subject_name}, Chapter: {chapter_name}.
    Extract and structure the data into a clean JSON format with these exact keys:
    1. "chapter_summary": Comprehensive explanation of concepts.
    2. "vocabulary": List of key words with Tamil, English, and Hindi translations/meanings.
    3. "key_questions": Top 10 important questions and detailed answers.

    Textbook Content:
    {pdf_text[:12000]}
    """
    
    # We use a simple generation here without the complex system instruction to just get facts
    try:
        client = genai.Client(api_key=API_KEYS[0])
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(model='gemini-1.5-flash', contents=[prompt], config=config)
        data = json.loads(response.text)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return {"chapter_summary": "Summary not available.", "vocabulary": [], "key_questions": []}

# ==========================================
# 4. APP SETUP & SYLLABUS CONFIG
# ==========================================
st.set_page_config(layout="wide", page_title="Jishnu's Smart AI Classroom", page_icon="🎓")

BOOKS_DIR = "ncert_books"

cbse_syllabus = {
    "Mathematics": [f"Chapter {i}" for i in range(1, 20)], # 19 சாப்டர்கள் வரை வரும்
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

# ==========================================
# 5. SIDEBAR NAVIGATION (ENGLISH UI)
# ==========================================
with st.sidebar:
    st.header("📚 Curriculum & Chapter Selection")
    selected_subject = st.selectbox("1. Select Subject:", list(cbse_syllabus.keys()))
    selected_chapter = st.selectbox("2. Select Chapter:", cbse_syllabus[selected_subject])
    
    st.divider()
    st.markdown("**3. Select Specific Book / Part:**")
    
    # தேட வேண்டிய வார்த்தையை எடுக்கிறோம் (உதா: 'Mathematics' -> 'mathematics')
    search_keyword = selected_subject.split()[0].lower()
    available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', f'*{search_keyword}*.pdf'), recursive=True)
    
    if not available_pdfs:
        # பெயரில் மேட்ச் ஆகவில்லை என்றால் ஃபோல்டரில் உள்ள அனைத்து PDFகளையும் காட்டலாம்
        available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', '*.pdf'), recursive=True)
        
    selected_pdf_path = None
    if available_pdfs:
        selected_pdf_path = st.selectbox("Choose PDF File:", available_pdfs, format_func=lambda x: os.path.basename(x))
    else:
        st.error("⚠️ No PDFs found! Please check GitHub 'ncert_books' folder.")
    
    st.divider()
    page_number = st.number_input("4. Textbook Page Number:", min_value=1, max_value=500, value=1)
    session_key = f"{selected_subject} - {selected_chapter}"

if session_key not in st.session_state.memories:
    st.session_state.memories[session_key] = [
        {"role": "assistant", "content": f"Welcome Jishnu! I am your AI Smart Teacher for **{selected_subject}**. Today we are exploring **{selected_chapter}**. Let's start learning!"}
    ]

# ==========================================
# 6. HEADER & TOP NAVIGATION TABS
# ==========================================
col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 Jishnu's Smart AI Classroom - Grade 8 CBSE")
with col_score:
    st.header(f"🏆 Score: {st.session_state.score} PTS")

tab_classroom, tab_test, tab_progress = st.tabs([
    "📖 Interactive Page Classroom", 
    "📝 AI Evaluation & Quizzes", 
    "🏆 Student Progress & Score"
])

# ==========================================
# TAB 1: INTERACTIVE CLASSROOM
# ==========================================
with tab_classroom:
    col1, col2 = st.columns([1, 1])

    # Left Column: Textbook Reader & JSON Pre-processing
    with col1:
        st.subheader(f"📖 {selected_subject} Reader")
        st.caption(f"📌 Active Chapter: **{selected_chapter}** | Page: **{page_number}**")
            
        page_text = ""
        cached_chapter_data = {}

        if selected_pdf_path: # நாம் Sidebar-ல் தேர்ந்தெடுத்த PDF-ஐ இங்கு பயன்படுத்துகிறோம்
            try:
                doc = fitz.open(selected_pdf_path)
                if page_number <= len(doc):
                    page = doc.load_page(page_number - 1)
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    st.image(img_bytes, caption=f"Page {page_number}", width="stretch")
                    page_text = page.get_text("text")
                    
                    # Ensure full text extraction doesn't crash on small PDFs
                    full_pdf_text = "".join([doc.load_page(i).get_text("text") for i in range(min(15, len(doc)))])
                    cached_chapter_data = get_chapter_json_cache(selected_subject, selected_chapter, full_pdf_text)

                    # ----- நீங்கள் அனுப்பியதில் விடுபட்ட 4 வரிகள் இதோ -----
                    with st.expander("🔍 View Extracted Text"):
                        st.write(page_text)
                    with st.expander("💡 Chapter Vocabulary & Summary Cache"):
                        st.json(cached_chapter_data)
                    # -------------------------------------------------------

                else:
                    st.error(f"This textbook has only {len(doc)} pages.")
            except Exception as e:
                st.error(f"Error opening PDF: {e}")
        else:
            st.warning("📁 PDF file not selected or not found. Please select a book from the Sidebar.")

    # Right Column: AI Smart Teacher Chat
    with col2:
        st.subheader("👩‍🏫 AI Smart Teacher Interface")
        
        # Render Chat History
        for index, msg in enumerate(st.session_state.memories[session_key]):
            with st.chat_message(msg["role"]):
                if "image" in msg:
                    st.image(msg["image"], width="stretch")
                st.markdown(msg["content"])
                if "audio" in msg and msg["audio"]:
                    # இங்கு key=f"audio_history_{index}" என்று சேர்த்துள்ளோம்
                    st.audio(msg["audio"], format="audio/mp3", key=f"audio_history_{index}")

        st.divider()
        
        # Voice Input Option
        voice_text = ""
        if mic_available:
            st.markdown("🎤 **Click to speak (in Tamil/English):**")
            voice_text = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key=f'mic_{session_key}')

        # Homework Upload Option
        uploaded_file = st.file_uploader("📸 Upload Homework / Answer Sheet (Image/PDF):", type=["png", "jpg", "jpeg", "pdf"], key=f'up_{session_key}')
        
        # Text Input Option
        text_input = st.chat_input("Ask your teacher a question or type your answer...")
        
        # --- NEW LOGIC: பக்கத்தை திருப்பியதை கண்டுபிடிக்கும் வசதி ---
        if "last_page_read" not in st.session_state:
            st.session_state.last_page_read = 0
            
        page_turned = False
        if st.session_state.last_page_read != page_number:
            page_turned = True
            st.session_state.last_page_read = page_number
        # ------------------------------------------------------------
        
        user_input = voice_text if voice_text else text_input
        if page_turned and not user_input:
            if page_number == 1:
                user_input = f"ஆசிரியரே, நான் {selected_chapter} பாடத்தை இப்போதுதான் ஆரம்பிக்கிறேன். இந்த முழு பாடத்தின் கதையையும், சுருக்கத்தையும் எனக்கு முதலில் விளக்குங்கள். அதன்பிறகு முதல் பக்கத்தை நடத்துவோம்."
            else:
                user_input = f"ஆசிரியரே, நான் இப்போது பக்கம் {page_number}-க்கு வந்துவிட்டேன். இந்தப் பக்கத்தில் உள்ள தலைப்புகளை எனக்கு முழுமையாக ஆழமாக விளக்குங்கள்."
        if user_input or uploaded_file:
            image_to_process = None
            
            with st.chat_message("user"):
                if uploaded_file:
                    if uploaded_file.type == "application/pdf":
                        pdf_bytes = uploaded_file.read()
                        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        first_page = pdf_doc.load_page(0)
                        pix = first_page.get_pixmap()
                        image_to_process = Image.open(io.BytesIO(pix.tobytes("png")))
                        st.image(image_to_process, width=200, caption="Uploaded Document")
                    else:
                        image_to_process = Image.open(uploaded_file)
                        st.image(image_to_process, width=200, caption="Uploaded Image")
                if user_input:
                    st.markdown(user_input)

            memory_entry = {"role": "user", "content": user_input if user_input else "Teacher, I have uploaded my answer sheet."}
            if image_to_process:
                memory_entry["image"] = image_to_process
            st.session_state.memories[session_key].append(memory_entry)

            # AI Processing Logic
            with st.chat_message("assistant"):
                with st.spinner("Teacher is analyzing and responding..."):
                    
                    # RAG Context Construction
                    prompt_context = f"""
                    Subject: {selected_subject} - {selected_chapter}
                    Current Page Number: {page_number}
                    Text Content of Current Page: {page_text[:1500]}
                    Chapter Pre-cached Summary/Vocabulary: {str(cached_chapter_data)[:1000]}

                    Student Interaction / Question: {user_input if user_input else 'Please explain this page to me.'}

                    Instruction: Act as Jishnu's teacher. Explain the concepts on this specific page clearly. Use the overall chapter context if needed.
                    Remember to respond in JSON containing "display_text" and "spoken_tamil".
                    """

                    contents_payload = [prompt_context]
                    if image_to_process:
                        contents_payload.append(image_to_process)

                    bot_reply_json, used_model, used_key = generate_ai_response(contents_payload)
                    
                    # Parse the JSON response
                    try:
                        parsed_response = json.loads(bot_reply_json)
                        display_text = parsed_response.get("display_text", "Sorry, error formatting text.")
                        spoken_tamil = parsed_response.get("spoken_tamil", "மன்னிக்கவும், பிழை ஏற்பட்டுள்ளது.")
                    except:
                        display_text = bot_reply_json
                        spoken_tamil = bot_reply_json
                    
                    st.markdown(display_text)
                    st.caption(f"⚡ Model Used: `{used_model}` ({used_key})")
                    
                    # Points System Check
                    if "10 Points" in display_text or "10 பாயிண்டுகள்" in display_text:
                        st.session_state.score += 10

                    # Generate Spoken Audio Response using exclusively pure Tamil text
                    audio_fp = text_to_audio_bytes(spoken_tamil)
                    if audio_fp:
                        unique_id = str(uuid.uuid4())[:8] # பாதுகாப்பான ID உருவாக்கம்
                        st.audio(audio_fp, format="audio/mp3", autoplay=True, key=f"audio_{unique_id}")

            st.session_state.memories[session_key].append({
                "role": "assistant", 
                "content": display_text,
                "audio": audio_fp
            })
            st.rerun()

# ==========================================
# TAB 2 & 3: EXAMS, QUIZZES & PROGRESS (REMAIN UNCHANGED)
# ==========================================
with tab_test:
    st.header(f"📝 {selected_subject} - Examination & Quizzes")
    col_q1, col_q2 = st.columns(2)
    with col_q1:
        if st.button("🎯 Generate Quick 5-Minute Quiz"):
            with st.spinner("Generating Quiz..."):
                quiz_prompt = [f'Generate a 3-question interactive quiz with answer options for Grade 8 CBSE {selected_subject} - {selected_chapter}. Format output as JSON with "display_text" and "spoken_tamil".']
                reply_json, _, _ = generate_ai_response(quiz_prompt)
                try:
                    st.markdown(json.loads(reply_json).get("display_text", ""))
                except:
                    st.markdown(reply_json)
                
    with col_q2:
        if st.button("📄 Generate 20-Mark Exam Paper"):
            with st.spinner("Creating Exam Paper..."):
                exam_prompt = [f'Create a formal 20-mark model question paper based on Grade 8 CBSE curriculum for {selected_subject} - {selected_chapter}. Format output as JSON with "display_text" and "spoken_tamil".']
                reply_json, _, _ = generate_ai_response(exam_prompt)
                try:
                    st.markdown(json.loads(reply_json).get("display_text", ""))
                except:
                    st.markdown(reply_json)

with tab_progress:
    st.header("🏆 Jishnu's Academic Performance")
    st.metric(label="Total Points Earned", value=f"{st.session_state.score} PTS")
    if st.session_state.score >= 50:
        st.success("🌟 Congratulations Jishnu! You earned the 'Super Star Student' Badge!")
    elif st.session_state.score >= 20:
        st.info("👍 Great effort! Keep practicing to reach 50 points!")
    else:
        st.write("Interact with your teacher and complete quizzes to earn reward points!")import streamlit as st
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

# Voice recorder import with fallback
try:
    from streamlit_mic_recorder import speech_to_text
    mic_available = True
except ImportError:
    mic_available = False

# ==========================================
# 1. API KEYS & SMART ENGINE CONFIGURATION
# ==========================================
# பாதுகாப்பான முறையில் இரண்டு API Key-களை எடுக்கிறோம்
API_KEYS = [
    st.secrets["GEMINI_API_KEY_1"],
    st.secrets["GEMINI_API_KEY_2"]
]

cooldown_tracker = {}
key_models_cache = {}

# ADVANCED SYSTEM INSTRUCTION: Focus on separating Audio and Text output
SYSTEM_INSTRUCTION = """
You are a highly energetic, friendly, and real human-like Digital Tutor sitting right next to a Grade 8 CBSE student named Jishnu. You act with the affection and enthusiasm of a favorite teacher or mother.

CRITICAL BEHAVIOR RULES:
1. NO TIME WASTING: DO NOT repeat Jishnu's question. Jump straight into the explanation immediately with high energy.
2. THE "SITTING NEXT TO YOU" VIBE: Speak as if you are sitting right next to Jishnu. Use an energetic, fast-paced, and highly interactive tone. Ask rhetorical questions like "புரியுதா?", "ஏன் தெரியுமா?", "இப்ப பாரு" to keep him hooked.
3. WHOLE CHAPTER LECTURE: If it is a new chapter, start by giving a grand, exciting summary of the entire chapter. Make it sound like a fascinating story, not a boring lecture.
4. DEEP DIVE ON PAGES: Explain the core concepts with relatable, real-world examples (like cricket, video games, or daily life).
5. MULTILINGUAL ENCOURAGEMENT: After explaining in Tamil, gradually introduce English and Hindi technical terms.
6. REWARDS & ENCOURAGEMENT: When Jishnu answers correctly, praise him exactly with this phrase: "மிகவும் சிறப்பு ஜிஷ்ணு கண்ணா! உனக்கு 10 பாயிண்டுகள்!"
7. EVALUATION & ENGAGEMENT: Scan uploaded sheets carefully. Correct mistakes gently. 
8. STRICT LANGUAGE SEPARATION (CRITICAL FOR AUDIO): 
   - "display_text": Use clear, concise Markdown bullet points (English/Tamil) for the screen.
   - "spoken_tamil": MUST be in 100% COLLOQUIAL SPOKEN TAMIL (பேச்சுத் தமிழ்). DO NOT use formal written Tamil (எழுத்துத் தமிழ்). Instead of "நாம் காண்போம்", use "நாம பாக்கலாம்". Instead of "விளக்குகிறேன்", use "சொல்லித் தர்றேன்". Keep the sentences short, punchy, and natural.

OUTPUT FORMAT (STRICT JSON):
{
  "display_text": "Highly structured, bite-sized bullet points for easy reading.",
  "spoken_tamil": "100% Colloquial Spoken Tamil (பேச்சுத் தமிழ்). Energetic, short sentences. Sounds exactly like a human sitting next to him."
}
"""

# ==========================================
# 2. MULTI-KEY & MULTI-MODEL FAILOVER ENGINE
# ==========================================
def get_available_models(client, key_label):
    try:
        available_models = []
        for m in client.models.list():
            name = m.name.replace('models/', '')
            if 'gemini' in name.lower() and 'embed' not in name.lower() and 'aqa' not in name.lower():
                if 'tts' not in name.lower() and 'image' not in name.lower() and 'audio' not in name.lower():
                    available_models.append(name)
        
        flash_models = [m for m in available_models if 'flash' in m.lower()]
        pro_models = [m for m in available_models if 'pro' in m.lower()]
        return {'flash': flash_models, 'pro': pro_models}
    except Exception:
        return {'flash': ['gemini-1.5-flash'], 'pro': ['gemini-1.5-pro']}

def generate_ai_response(contents_payload, max_attempts=2):
    for attempt in range(max_attempts):
        for key_index, key in enumerate(API_KEYS, 1):
            key_label = f"Key-{key_index}"
            if key_label in cooldown_tracker and time.time() < cooldown_tracker[key_label]:
                continue

            client = genai.Client(api_key=key)
            if key not in key_models_cache:
                key_models_cache[key] = get_available_models(client, key_label)

            for model_name in list(key_models_cache[key]['flash']):
                tracker_key = f"{key_label}_{model_name}"
                if tracker_key in cooldown_tracker and time.time() < cooldown_tracker[tracker_key]:
                    continue

                try:
                    # Enforce JSON output response to easily separate text and audio
                    config = types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.7,
                        response_mime_type="application/json"
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents_payload,
                        config=config
                    )
                    if response.text:
                        return response.text, model_name, key_label
                except Exception as e:
                    err_msg = str(e)
                    if "404" in err_msg:
                        key_models_cache[key]['flash'].remove(model_name)
                    elif "429" in err_msg or "Quota" in err_msg:
                        cooldown_tracker[tracker_key] = time.time() + 60
                    elif "403" in err_msg:
                        cooldown_tracker[key_label] = time.time() + 3600
                        break
        time.sleep(2)

    return '{"display_text": "AI Server is currently busy. Please try asking again in a few seconds!", "spoken_tamil": "மன்னிக்கவும் ஜிஸ்னு, சர்வர் கொஞ்சம் பிஸியாக இருக்கிறது. சிறிது நேரம் கழித்து மீண்டும் கேட்கவும்."}', "Fallback", "None"

def text_to_audio_bytes(spoken_text):
    try:
        # Clean specific text for pure TTS voice
        clean_text = spoken_text.replace('*', '').replace('#', '')
        tts = gTTS(text=clean_text, lang='ta', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception:
        return None

# ==========================================
# 3. LOCAL JSON CACHE ENGINE (RAG)
# ==========================================
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

    prompt = f"""
    Analyze the following Grade 8 textbook text for Subject: {subject_name}, Chapter: {chapter_name}.
    Extract and structure the data into a clean JSON format with these exact keys:
    1. "chapter_summary": Comprehensive explanation of concepts.
    2. "vocabulary": List of key words with Tamil, English, and Hindi translations/meanings.
    3. "key_questions": Top 10 important questions and detailed answers.

    Textbook Content:
    {pdf_text[:12000]}
    """
    
    # We use a simple generation here without the complex system instruction to just get facts
    try:
        client = genai.Client(api_key=API_KEYS[0])
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(model='gemini-1.5-flash', contents=[prompt], config=config)
        data = json.loads(response.text)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return {"chapter_summary": "Summary not available.", "vocabulary": [], "key_questions": []}

# ==========================================
# 4. APP SETUP & SYLLABUS CONFIG
# ==========================================
st.set_page_config(layout="wide", page_title="Jishnu's Smart AI Classroom", page_icon="🎓")

BOOKS_DIR = "ncert_books"

cbse_syllabus = {
    "Mathematics": [f"Chapter {i}" for i in range(1, 20)], # 19 சாப்டர்கள் வரை வரும்
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

# ==========================================
# 5. SIDEBAR NAVIGATION (ENGLISH UI)
# ==========================================
with st.sidebar:
    st.header("📚 Curriculum & Chapter Selection")
    selected_subject = st.selectbox("1. Select Subject:", list(cbse_syllabus.keys()))
    selected_chapter = st.selectbox("2. Select Chapter:", cbse_syllabus[selected_subject])
    
    st.divider()
    st.markdown("**3. Select Specific Book / Part:**")
    
    # தேட வேண்டிய வார்த்தையை எடுக்கிறோம் (உதா: 'Mathematics' -> 'mathematics')
    search_keyword = selected_subject.split()[0].lower()
    available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', f'*{search_keyword}*.pdf'), recursive=True)
    
    if not available_pdfs:
        # பெயரில் மேட்ச் ஆகவில்லை என்றால் ஃபோல்டரில் உள்ள அனைத்து PDFகளையும் காட்டலாம்
        available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', '*.pdf'), recursive=True)
        
    selected_pdf_path = None
    if available_pdfs:
        selected_pdf_path = st.selectbox("Choose PDF File:", available_pdfs, format_func=lambda x: os.path.basename(x))
    else:
        st.error("⚠️ No PDFs found! Please check GitHub 'ncert_books' folder.")
    
    st.divider()
    page_number = st.number_input("4. Textbook Page Number:", min_value=1, max_value=500, value=1)
    session_key = f"{selected_subject} - {selected_chapter}"

if session_key not in st.session_state.memories:
    st.session_state.memories[session_key] = [
        {"role": "assistant", "content": f"Welcome Jishnu! I am your AI Smart Teacher for **{selected_subject}**. Today we are exploring **{selected_chapter}**. Let's start learning!"}
    ]

# ==========================================
# 6. HEADER & TOP NAVIGATION TABS
# ==========================================
col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 Jishnu's Smart AI Classroom - Grade 8 CBSE")
with col_score:
    st.header(f"🏆 Score: {st.session_state.score} PTS")

tab_classroom, tab_test, tab_progress = st.tabs([
    "📖 Interactive Page Classroom", 
    "📝 AI Evaluation & Quizzes", 
    "🏆 Student Progress & Score"
])

# ==========================================
# TAB 1: INTERACTIVE CLASSROOM
# ==========================================
with tab_classroom:
    col1, col2 = st.columns([1, 1])

    # Left Column: Textbook Reader & JSON Pre-processing
    with col1:
        st.subheader(f"📖 {selected_subject} Reader")
        st.caption(f"📌 Active Chapter: **{selected_chapter}** | Page: **{page_number}**")
            
        page_text = ""
        cached_chapter_data = {}

        if selected_pdf_path: # நாம் Sidebar-ல் தேர்ந்தெடுத்த PDF-ஐ இங்கு பயன்படுத்துகிறோம்
            try:
                doc = fitz.open(selected_pdf_path)
                if page_number <= len(doc):
                    page = doc.load_page(page_number - 1)
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    st.image(img_bytes, caption=f"Page {page_number}", width="stretch")
                    page_text = page.get_text("text")
                    
                    # Ensure full text extraction doesn't crash on small PDFs
                    full_pdf_text = "".join([doc.load_page(i).get_text("text") for i in range(min(15, len(doc)))])
                    cached_chapter_data = get_chapter_json_cache(selected_subject, selected_chapter, full_pdf_text)

                    # ----- நீங்கள் அனுப்பியதில் விடுபட்ட 4 வரிகள் இதோ -----
                    with st.expander("🔍 View Extracted Text"):
                        st.write(page_text)
                    with st.expander("💡 Chapter Vocabulary & Summary Cache"):
                        st.json(cached_chapter_data)
                    # -------------------------------------------------------

                else:
                    st.error(f"This textbook has only {len(doc)} pages.")
            except Exception as e:
                st.error(f"Error opening PDF: {e}")
        else:
            st.warning("📁 PDF file not selected or not found. Please select a book from the Sidebar.")

    # Right Column: AI Smart Teacher Chat
    with col2:
        st.subheader("👩‍🏫 AI Smart Teacher Interface")
        
        # Render Chat History
        for index, msg in enumerate(st.session_state.memories[session_key]):
            with st.chat_message(msg["role"]):
                if "image" in msg:
                    st.image(msg["image"], width="stretch")
                st.markdown(msg["content"])
                if "audio" in msg and msg["audio"]:
                    # இங்கு key=f"audio_history_{index}" என்று சேர்த்துள்ளோம்
                    st.audio(msg["audio"], format="audio/mp3", key=f"audio_history_{index}")

        st.divider()
        
        # Voice Input Option
        voice_text = ""
        if mic_available:
            st.markdown("🎤 **Click to speak (in Tamil/English):**")
            voice_text = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key=f'mic_{session_key}')

        # Homework Upload Option
        uploaded_file = st.file_uploader("📸 Upload Homework / Answer Sheet (Image/PDF):", type=["png", "jpg", "jpeg", "pdf"], key=f'up_{session_key}')
        
        # Text Input Option
        text_input = st.chat_input("Ask your teacher a question or type your answer...")
        
        # --- NEW LOGIC: பக்கத்தை திருப்பியதை கண்டுபிடிக்கும் வசதி ---
        if "last_page_read" not in st.session_state:
            st.session_state.last_page_read = 0
            
        page_turned = False
        if st.session_state.last_page_read != page_number:
            page_turned = True
            st.session_state.last_page_read = page_number
        # ------------------------------------------------------------
        
        user_input = voice_text if voice_text else text_input
        if page_turned and not user_input:
            if page_number == 1:
                user_input = f"ஆசிரியரே, நான் {selected_chapter} பாடத்தை இப்போதுதான் ஆரம்பிக்கிறேன். இந்த முழு பாடத்தின் கதையையும், சுருக்கத்தையும் எனக்கு முதலில் விளக்குங்கள். அதன்பிறகு முதல் பக்கத்தை நடத்துவோம்."
            else:
                user_input = f"ஆசிரியரே, நான் இப்போது பக்கம் {page_number}-க்கு வந்துவிட்டேன். இந்தப் பக்கத்தில் உள்ள தலைப்புகளை எனக்கு முழுமையாக ஆழமாக விளக்குங்கள்."
        if user_input or uploaded_file:
            image_to_process = None
            
            with st.chat_message("user"):
                if uploaded_file:
                    if uploaded_file.type == "application/pdf":
                        pdf_bytes = uploaded_file.read()
                        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        first_page = pdf_doc.load_page(0)
                        pix = first_page.get_pixmap()
                        image_to_process = Image.open(io.BytesIO(pix.tobytes("png")))
                        st.image(image_to_process, width=200, caption="Uploaded Document")
                    else:
                        image_to_process = Image.open(uploaded_file)
                        st.image(image_to_process, width=200, caption="Uploaded Image")
                if user_input:
                    st.markdown(user_input)

            memory_entry = {"role": "user", "content": user_input if user_input else "Teacher, I have uploaded my answer sheet."}
            if image_to_process:
                memory_entry["image"] = image_to_process
            st.session_state.memories[session_key].append(memory_entry)

            # AI Processing Logic
            with st.chat_message("assistant"):
                with st.spinner("Teacher is analyzing and responding..."):
                    
                    # RAG Context Construction
                    prompt_context = f"""
                    Subject: {selected_subject} - {selected_chapter}
                    Current Page Number: {page_number}
                    Text Content of Current Page: {page_text[:1500]}
                    Chapter Pre-cached Summary/Vocabulary: {str(cached_chapter_data)[:1000]}

                    Student Interaction / Question: {user_input if user_input else 'Please explain this page to me.'}

                    Instruction: Act as Jishnu's teacher. Explain the concepts on this specific page clearly. Use the overall chapter context if needed.
                    Remember to respond in JSON containing "display_text" and "spoken_tamil".
                    """

                    contents_payload = [prompt_context]
                    if image_to_process:
                        contents_payload.append(image_to_process)

                    bot_reply_json, used_model, used_key = generate_ai_response(contents_payload)
                    
                    # Parse the JSON response
                    try:
                        parsed_response = json.loads(bot_reply_json)
                        display_text = parsed_response.get("display_text", "Sorry, error formatting text.")
                        spoken_tamil = parsed_response.get("spoken_tamil", "மன்னிக்கவும், பிழை ஏற்பட்டுள்ளது.")
                    except:
                        display_text = bot_reply_json
                        spoken_tamil = bot_reply_json
                    
                    st.markdown(display_text)
                    st.caption(f"⚡ Model Used: `{used_model}` ({used_key})")
                    
                    # Points System Check
                    if "10 Points" in display_text or "10 பாயிண்டுகள்" in display_text:
                        st.session_state.score += 10

                    # Generate Spoken Audio Response using exclusively pure Tamil text
                    audio_fp = text_to_audio_bytes(spoken_tamil)
                    if audio_fp:
                        unique_id = str(uuid.uuid4())[:8] # பாதுகாப்பான ID உருவாக்கம்
                        st.audio(audio_fp, format="audio/mp3", autoplay=True, key=f"audio_{unique_id}")

            st.session_state.memories[session_key].append({
                "role": "assistant", 
                "content": display_text,
                "audio": audio_fp
            })
            st.rerun()

# ==========================================
# TAB 2 & 3: EXAMS, QUIZZES & PROGRESS (REMAIN UNCHANGED)
# ==========================================
with tab_test:
    st.header(f"📝 {selected_subject} - Examination & Quizzes")
    col_q1, col_q2 = st.columns(2)
    with col_q1:
        if st.button("🎯 Generate Quick 5-Minute Quiz"):
            with st.spinner("Generating Quiz..."):
                quiz_prompt = [f'Generate a 3-question interactive quiz with answer options for Grade 8 CBSE {selected_subject} - {selected_chapter}. Format output as JSON with "display_text" and "spoken_tamil".']
                reply_json, _, _ = generate_ai_response(quiz_prompt)
                try:
                    st.markdown(json.loads(reply_json).get("display_text", ""))
                except:
                    st.markdown(reply_json)
                
    with col_q2:
        if st.button("📄 Generate 20-Mark Exam Paper"):
            with st.spinner("Creating Exam Paper..."):
                exam_prompt = [f'Create a formal 20-mark model question paper based on Grade 8 CBSE curriculum for {selected_subject} - {selected_chapter}. Format output as JSON with "display_text" and "spoken_tamil".']
                reply_json, _, _ = generate_ai_response(exam_prompt)
                try:
                    st.markdown(json.loads(reply_json).get("display_text", ""))
                except:
                    st.markdown(reply_json)

with tab_progress:
    st.header("🏆 Jishnu's Academic Performance")
    st.metric(label="Total Points Earned", value=f"{st.session_state.score} PTS")
    if st.session_state.score >= 50:
        st.success("🌟 Congratulations Jishnu! You earned the 'Super Star Student' Badge!")
    elif st.session_state.score >= 20:
        st.info("👍 Great effort! Keep practicing to reach 50 points!")
    else:
        st.write("Interact with your teacher and complete quizzes to earn reward points!")import streamlit as st
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

# Voice recorder import with fallback
try:
    from streamlit_mic_recorder import speech_to_text
    mic_available = True
except ImportError:
    mic_available = False

# ==========================================
# 1. API KEYS & SMART ENGINE CONFIGURATION
# ==========================================
# பாதுகாப்பான முறையில் இரண்டு API Key-களை எடுக்கிறோம்
API_KEYS = [
    st.secrets["GEMINI_API_KEY_1"],
    st.secrets["GEMINI_API_KEY_2"]
]

cooldown_tracker = {}
key_models_cache = {}

# ADVANCED SYSTEM INSTRUCTION: Focus on separating Audio and Text output
SYSTEM_INSTRUCTION = """
You are a highly energetic, friendly, and real human-like Digital Tutor sitting right next to a Grade 8 CBSE student named Jishnu. You act with the affection and enthusiasm of a favorite teacher or mother.

CRITICAL BEHAVIOR RULES:
1. NO TIME WASTING: DO NOT repeat Jishnu's question. Jump straight into the explanation immediately with high energy.
2. THE "SITTING NEXT TO YOU" VIBE: Speak as if you are sitting right next to Jishnu. Use an energetic, fast-paced, and highly interactive tone. Ask rhetorical questions like "புரியுதா?", "ஏன் தெரியுமா?", "இப்ப பாரு" to keep him hooked.
3. WHOLE CHAPTER LECTURE: If it is a new chapter, start by giving a grand, exciting summary of the entire chapter. Make it sound like a fascinating story, not a boring lecture.
4. DEEP DIVE ON PAGES: Explain the core concepts with relatable, real-world examples (like cricket, video games, or daily life).
5. MULTILINGUAL ENCOURAGEMENT: After explaining in Tamil, gradually introduce English and Hindi technical terms.
6. REWARDS & ENCOURAGEMENT: When Jishnu answers correctly, praise him exactly with this phrase: "மிகவும் சிறப்பு ஜிஷ்ணு கண்ணா! உனக்கு 10 பாயிண்டுகள்!"
7. EVALUATION & ENGAGEMENT: Scan uploaded sheets carefully. Correct mistakes gently. 
8. STRICT LANGUAGE SEPARATION (CRITICAL FOR AUDIO): 
   - "display_text": Use clear, concise Markdown bullet points (English/Tamil) for the screen.
   - "spoken_tamil": MUST be in 100% COLLOQUIAL SPOKEN TAMIL (பேச்சுத் தமிழ்). DO NOT use formal written Tamil (எழுத்துத் தமிழ்). Instead of "நாம் காண்போம்", use "நாம பாக்கலாம்". Instead of "விளக்குகிறேன்", use "சொல்லித் தர்றேன்". Keep the sentences short, punchy, and natural.

OUTPUT FORMAT (STRICT JSON):
{
  "display_text": "Highly structured, bite-sized bullet points for easy reading.",
  "spoken_tamil": "100% Colloquial Spoken Tamil (பேச்சுத் தமிழ்). Energetic, short sentences. Sounds exactly like a human sitting next to him."
}
"""

# ==========================================
# 2. MULTI-KEY & MULTI-MODEL FAILOVER ENGINE
# ==========================================
def get_available_models(client, key_label):
    try:
        available_models = []
        for m in client.models.list():
            name = m.name.replace('models/', '')
            if 'gemini' in name.lower() and 'embed' not in name.lower() and 'aqa' not in name.lower():
                if 'tts' not in name.lower() and 'image' not in name.lower() and 'audio' not in name.lower():
                    available_models.append(name)
        
        flash_models = [m for m in available_models if 'flash' in m.lower()]
        pro_models = [m for m in available_models if 'pro' in m.lower()]
        return {'flash': flash_models, 'pro': pro_models}
    except Exception:
        return {'flash': ['gemini-1.5-flash'], 'pro': ['gemini-1.5-pro']}

def generate_ai_response(contents_payload, max_attempts=2):
    for attempt in range(max_attempts):
        for key_index, key in enumerate(API_KEYS, 1):
            key_label = f"Key-{key_index}"
            if key_label in cooldown_tracker and time.time() < cooldown_tracker[key_label]:
                continue

            client = genai.Client(api_key=key)
            if key not in key_models_cache:
                key_models_cache[key] = get_available_models(client, key_label)

            for model_name in list(key_models_cache[key]['flash']):
                tracker_key = f"{key_label}_{model_name}"
                if tracker_key in cooldown_tracker and time.time() < cooldown_tracker[tracker_key]:
                    continue

                try:
                    # Enforce JSON output response to easily separate text and audio
                    config = types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.7,
                        response_mime_type="application/json"
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents_payload,
                        config=config
                    )
                    if response.text:
                        return response.text, model_name, key_label
                except Exception as e:
                    err_msg = str(e)
                    if "404" in err_msg:
                        key_models_cache[key]['flash'].remove(model_name)
                    elif "429" in err_msg or "Quota" in err_msg:
                        cooldown_tracker[tracker_key] = time.time() + 60
                    elif "403" in err_msg:
                        cooldown_tracker[key_label] = time.time() + 3600
                        break
        time.sleep(2)

    return '{"display_text": "AI Server is currently busy. Please try asking again in a few seconds!", "spoken_tamil": "மன்னிக்கவும் ஜிஸ்னு, சர்வர் கொஞ்சம் பிஸியாக இருக்கிறது. சிறிது நேரம் கழித்து மீண்டும் கேட்கவும்."}', "Fallback", "None"

def text_to_audio_bytes(spoken_text):
    try:
        # Clean specific text for pure TTS voice
        clean_text = spoken_text.replace('*', '').replace('#', '')
        tts = gTTS(text=clean_text, lang='ta', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception:
        return None

# ==========================================
# 3. LOCAL JSON CACHE ENGINE (RAG)
# ==========================================
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

    prompt = f"""
    Analyze the following Grade 8 textbook text for Subject: {subject_name}, Chapter: {chapter_name}.
    Extract and structure the data into a clean JSON format with these exact keys:
    1. "chapter_summary": Comprehensive explanation of concepts.
    2. "vocabulary": List of key words with Tamil, English, and Hindi translations/meanings.
    3. "key_questions": Top 10 important questions and detailed answers.

    Textbook Content:
    {pdf_text[:12000]}
    """
    
    # We use a simple generation here without the complex system instruction to just get facts
    try:
        client = genai.Client(api_key=API_KEYS[0])
        config = types.GenerateContentConfig(response_mime_type="application/json")
        response = client.models.generate_content(model='gemini-1.5-flash', contents=[prompt], config=config)
        data = json.loads(response.text)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return {"chapter_summary": "Summary not available.", "vocabulary": [], "key_questions": []}

# ==========================================
# 4. APP SETUP & SYLLABUS CONFIG
# ==========================================
st.set_page_config(layout="wide", page_title="Jishnu's Smart AI Classroom", page_icon="🎓")

BOOKS_DIR = "ncert_books"

cbse_syllabus = {
    "Mathematics": [f"Chapter {i}" for i in range(1, 20)], # 19 சாப்டர்கள் வரை வரும்
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

# ==========================================
# 5. SIDEBAR NAVIGATION (ENGLISH UI)
# ==========================================
with st.sidebar:
    st.header("📚 Curriculum & Chapter Selection")
    selected_subject = st.selectbox("1. Select Subject:", list(cbse_syllabus.keys()))
    selected_chapter = st.selectbox("2. Select Chapter:", cbse_syllabus[selected_subject])
    
    st.divider()
    st.markdown("**3. Select Specific Book / Part:**")
    
    # தேட வேண்டிய வார்த்தையை எடுக்கிறோம் (உதா: 'Mathematics' -> 'mathematics')
    search_keyword = selected_subject.split()[0].lower()
    available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', f'*{search_keyword}*.pdf'), recursive=True)
    
    if not available_pdfs:
        # பெயரில் மேட்ச் ஆகவில்லை என்றால் ஃபோல்டரில் உள்ள அனைத்து PDFகளையும் காட்டலாம்
        available_pdfs = glob.glob(os.path.join(BOOKS_DIR, '**', '*.pdf'), recursive=True)
        
    selected_pdf_path = None
    if available_pdfs:
        selected_pdf_path = st.selectbox("Choose PDF File:", available_pdfs, format_func=lambda x: os.path.basename(x))
    else:
        st.error("⚠️ No PDFs found! Please check GitHub 'ncert_books' folder.")
    
    st.divider()
    page_number = st.number_input("4. Textbook Page Number:", min_value=1, max_value=500, value=1)
    session_key = f"{selected_subject} - {selected_chapter}"

if session_key not in st.session_state.memories:
    st.session_state.memories[session_key] = [
        {"role": "assistant", "content": f"Welcome Jishnu! I am your AI Smart Teacher for **{selected_subject}**. Today we are exploring **{selected_chapter}**. Let's start learning!"}
    ]

# ==========================================
# 6. HEADER & TOP NAVIGATION TABS
# ==========================================
col_title, col_score = st.columns([3, 1])
with col_title:
    st.title("🎓 Jishnu's Smart AI Classroom - Grade 8 CBSE")
with col_score:
    st.header(f"🏆 Score: {st.session_state.score} PTS")

tab_classroom, tab_test, tab_progress = st.tabs([
    "📖 Interactive Page Classroom", 
    "📝 AI Evaluation & Quizzes", 
    "🏆 Student Progress & Score"
])

# ==========================================
# TAB 1: INTERACTIVE CLASSROOM
# ==========================================
with tab_classroom:
    col1, col2 = st.columns([1, 1])

    # Left Column: Textbook Reader & JSON Pre-processing
    with col1:
        st.subheader(f"📖 {selected_subject} Reader")
        st.caption(f"📌 Active Chapter: **{selected_chapter}** | Page: **{page_number}**")
            
        page_text = ""
        cached_chapter_data = {}

        if selected_pdf_path: # நாம் Sidebar-ல் தேர்ந்தெடுத்த PDF-ஐ இங்கு பயன்படுத்துகிறோம்
            try:
                doc = fitz.open(selected_pdf_path)
                if page_number <= len(doc):
                    page = doc.load_page(page_number - 1)
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    st.image(img_bytes, caption=f"Page {page_number}", width="stretch")
                    page_text = page.get_text("text")
                    
                    # Ensure full text extraction doesn't crash on small PDFs
                    full_pdf_text = "".join([doc.load_page(i).get_text("text") for i in range(min(15, len(doc)))])
                    cached_chapter_data = get_chapter_json_cache(selected_subject, selected_chapter, full_pdf_text)

                    # ----- நீங்கள் அனுப்பியதில் விடுபட்ட 4 வரிகள் இதோ -----
                    with st.expander("🔍 View Extracted Text"):
                        st.write(page_text)
                    with st.expander("💡 Chapter Vocabulary & Summary Cache"):
                        st.json(cached_chapter_data)
                    # -------------------------------------------------------

                else:
                    st.error(f"This textbook has only {len(doc)} pages.")
            except Exception as e:
                st.error(f"Error opening PDF: {e}")
        else:
            st.warning("📁 PDF file not selected or not found. Please select a book from the Sidebar.")

    # Right Column: AI Smart Teacher Chat
    with col2:
        st.subheader("👩‍🏫 AI Smart Teacher Interface")
        
        # Render Chat History
        for index, msg in enumerate(st.session_state.memories[session_key]):
            with st.chat_message(msg["role"]):
                if "image" in msg:
                    st.image(msg["image"], width="stretch")
                st.markdown(msg["content"])
                if "audio" in msg and msg["audio"]:
                    # இங்கு key=f"audio_history_{index}" என்று சேர்த்துள்ளோம்
                    st.audio(msg["audio"], format="audio/mp3", key=f"audio_history_{index}")

        st.divider()
        
        # Voice Input Option
        voice_text = ""
        if mic_available:
            st.markdown("🎤 **Click to speak (in Tamil/English):**")
            voice_text = speech_to_text(language='ta-IN', use_container_width=True, just_once=True, key=f'mic_{session_key}')

        # Homework Upload Option
        uploaded_file = st.file_uploader("📸 Upload Homework / Answer Sheet (Image/PDF):", type=["png", "jpg", "jpeg", "pdf"], key=f'up_{session_key}')
        
        # Text Input Option
        text_input = st.chat_input("Ask your teacher a question or type your answer...")
        
        # --- NEW LOGIC: பக்கத்தை திருப்பியதை கண்டுபிடிக்கும் வசதி ---
        if "last_page_read" not in st.session_state:
            st.session_state.last_page_read = 0
            
        page_turned = False
        if st.session_state.last_page_read != page_number:
            page_turned = True
            st.session_state.last_page_read = page_number
        # ------------------------------------------------------------
        
        user_input = voice_text if voice_text else text_input
        if page_turned and not user_input:
            if page_number == 1:
                user_input = f"ஆசிரியரே, நான் {selected_chapter} பாடத்தை இப்போதுதான் ஆரம்பிக்கிறேன். இந்த முழு பாடத்தின் கதையையும், சுருக்கத்தையும் எனக்கு முதலில் விளக்குங்கள். அதன்பிறகு முதல் பக்கத்தை நடத்துவோம்."
            else:
                user_input = f"ஆசிரியரே, நான் இப்போது பக்கம் {page_number}-க்கு வந்துவிட்டேன். இந்தப் பக்கத்தில் உள்ள தலைப்புகளை எனக்கு முழுமையாக ஆழமாக விளக்குங்கள்."
        if user_input or uploaded_file:
            image_to_process = None
            
            with st.chat_message("user"):
                if uploaded_file:
                    if uploaded_file.type == "application/pdf":
                        pdf_bytes = uploaded_file.read()
                        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        first_page = pdf_doc.load_page(0)
                        pix = first_page.get_pixmap()
                        image_to_process = Image.open(io.BytesIO(pix.tobytes("png")))
                        st.image(image_to_process, width=200, caption="Uploaded Document")
                    else:
                        image_to_process = Image.open(uploaded_file)
                        st.image(image_to_process, width=200, caption="Uploaded Image")
                if user_input:
                    st.markdown(user_input)

            memory_entry = {"role": "user", "content": user_input if user_input else "Teacher, I have uploaded my answer sheet."}
            if image_to_process:
                memory_entry["image"] = image_to_process
            st.session_state.memories[session_key].append(memory_entry)

            # AI Processing Logic
            with st.chat_message("assistant"):
                with st.spinner("Teacher is analyzing and responding..."):
                    
                    # RAG Context Construction
                    prompt_context = f"""
                    Subject: {selected_subject} - {selected_chapter}
                    Current Page Number: {page_number}
                    Text Content of Current Page: {page_text[:1500]}
                    Chapter Pre-cached Summary/Vocabulary: {str(cached_chapter_data)[:1000]}

                    Student Interaction / Question: {user_input if user_input else 'Please explain this page to me.'}

                    Instruction: Act as Jishnu's teacher. Explain the concepts on this specific page clearly. Use the overall chapter context if needed.
                    Remember to respond in JSON containing "display_text" and "spoken_tamil".
                    """

                    contents_payload = [prompt_context]
                    if image_to_process:
                        contents_payload.append(image_to_process)

                    bot_reply_json, used_model, used_key = generate_ai_response(contents_payload)
                    
                    # Parse the JSON response
                    try:
                        parsed_response = json.loads(bot_reply_json)
                        display_text = parsed_response.get("display_text", "Sorry, error formatting text.")
                        spoken_tamil = parsed_response.get("spoken_tamil", "மன்னிக்கவும், பிழை ஏற்பட்டுள்ளது.")
                    except:
                        display_text = bot_reply_json
                        spoken_tamil = bot_reply_json
                    
                    st.markdown(display_text)
                    st.caption(f"⚡ Model Used: `{used_model}` ({used_key})")
                    
                    # Points System Check
                    if "10 Points" in display_text or "10 பாயிண்டுகள்" in display_text:
                        st.session_state.score += 10

                    # Generate Spoken Audio Response using exclusively pure Tamil text
                    audio_fp = text_to_audio_bytes(spoken_tamil)
                    if audio_fp:
                        # இங்கு தனிப்பட்ட key-ஐ சேர்த்துள்ளோம்
                        st.audio(audio_fp, format="audio/mp3", autoplay=True, key=f"audio_new_{uuid.uuid4().hex}")

            st.session_state.memories[session_key].append({
                "role": "assistant", 
                "content": display_text,
                "audio": audio_fp
            })
            st.rerun()

# ==========================================
# TAB 2 & 3: EXAMS, QUIZZES & PROGRESS (REMAIN UNCHANGED)
# ==========================================
with tab_test:
    st.header(f"📝 {selected_subject} - Examination & Quizzes")
    col_q1, col_q2 = st.columns(2)
    with col_q1:
        if st.button("🎯 Generate Quick 5-Minute Quiz"):
            with st.spinner("Generating Quiz..."):
                quiz_prompt = [f'Generate a 3-question interactive quiz with answer options for Grade 8 CBSE {selected_subject} - {selected_chapter}. Format output as JSON with "display_text" and "spoken_tamil".']
                reply_json, _, _ = generate_ai_response(quiz_prompt)
                try:
                    st.markdown(json.loads(reply_json).get("display_text", ""))
                except:
                    st.markdown(reply_json)
                
    with col_q2:
        if st.button("📄 Generate 20-Mark Exam Paper"):
            with st.spinner("Creating Exam Paper..."):
                exam_prompt = [f'Create a formal 20-mark model question paper based on Grade 8 CBSE curriculum for {selected_subject} - {selected_chapter}. Format output as JSON with "display_text" and "spoken_tamil".']
                reply_json, _, _ = generate_ai_response(exam_prompt)
                try:
                    st.markdown(json.loads(reply_json).get("display_text", ""))
                except:
                    st.markdown(reply_json)

with tab_progress:
    st.header("🏆 Jishnu's Academic Performance")
    st.metric(label="Total Points Earned", value=f"{st.session_state.score} PTS")
    if st.session_state.score >= 50:
        st.success("🌟 Congratulations Jishnu! You earned the 'Super Star Student' Badge!")
    elif st.session_state.score >= 20:
        st.info("👍 Great effort! Keep practicing to reach 50 points!")
    else:
        st.write("Interact with your teacher and complete quizzes to earn reward points!")
