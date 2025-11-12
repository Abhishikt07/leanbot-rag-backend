"""
Main Application Module: Streamlit UI entry point with Feedback, Regeneration, Lead Scoring, and Multilingual Support.
"""
import streamlit as st
import datetime
import logging
import json 
import time
import secrets # For generating unique user ID
import re # For validation

# --- 1. UI Setup (MUST be the first Streamlit command) ---
st.set_page_config(page_title="LEANEXT Conversational AI", layout="wide")
st.markdown("""<style>
.stChatMessage:nth-child(even) { background-color: #e6f2ff; }
.stChatMessage:nth-child(odd) { background-color: #f0f0f0; color: #333333; }
</style>""", unsafe_allow_html=True)


# Update all imports to Day_20_*
from Day_20_B import load_or_build_knowledge_base, build_and_index_faq_suggestions
from Day_20_C import (
    clean_query_with_gemini, answer_query_with_cache_first, retrieve_context, 
    get_similar_faq_suggestions, match_landing_page, regenerate_answer, calculate_conversion_score
)
# Note: Assuming Day_20_A.py is the config file
from Day_20_A import (
    BASE_URL, SUGGESTED_FAQS, UNCLEAR_QUERY_RESPONSE, FAQ_SEED_QUESTIONS, FINAL_FALLBACK_MESSAGE,
    DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, LANGUAGE_FAIL_MESSAGE, 
    HIGH_POTENTIAL_THRESHOLD, CONVERSION_SCORE_MAP
)
from Day_20_E import log_chatbot_interaction, get_all_indexed_urls, update_cached_answer, save_lead_contact, check_lead_saved
from language_middleware2 import LanguageTranslator # New Import

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 2. Initialization and Translator Setup ---
try:
    translator = LanguageTranslator()
    TRANSLATOR_READY = True
except Exception as e:
    logging.error(f"Multilingual feature initialization failed: {e}. Running in English-only mode.")
    st.warning(f"Translation API Failed. Only **English** is supported. Check `language_middleware.py` (Error: {e})", icon="⚠️")
    TRANSLATOR_READY = False
    translator = None 

# --- SESSION STATE INITIALIZATION ---
def init_session_state():
    if "messages" not in st.session_state: st.session_state.messages = []
    if 'user_input' not in st.session_state: st.session_state.user_input = ""
    if 'faq_submitted_query' not in st.session_state: st.session_state.faq_submitted_query = None
    if 'greeted' not in st.session_state: st.session_state.greeted = False 
    if 'debug_mode' not in st.session_state: st.session_state.debug_mode = False 
    if 'regenerate_index' not in st.session_state: st.session_state.regenerate_index = -1 
    if 'feedback' not in st.session_state: st.session_state.feedback = {} 
    if 'show_starter_faqs' not in st.session_state: st.session_state.show_starter_faqs = True
    
    # --- NEW: Lead Scoring and User ID ---
    # Generate unique user ID for the session if not present
    if 'user_id' not in st.session_state: st.session_state.user_id = secrets.token_hex(16)
    # Conversion score, defaults to 1
    if 'conversion_score' not in st.session_state: st.session_state.conversion_score = 1
    # Flag to control lead capture form visibility
    if 'show_lead_capture' not in st.session_state: st.session_state.show_lead_capture = False
    # Flag to prevent re-prompting if contact info is saved
    if 'lead_saved' not in st.session_state: st.session_state.lead_saved = check_lead_saved(st.session_state.user_id)
    # Store initial lead capture prompt status
    if 'lead_prompt_shown' not in st.session_state: st.session_state.lead_prompt_shown = False


def get_greeting():
    hour = datetime.datetime.now().hour
    return "🌞 Good morning!" if hour < 12 else "☀️ Good afternoon!" if hour < 18 else "🌙 Good evening!"


def clear_chat():
    st.session_state.messages = []
    st.session_state.user_input = ""
    st.session_state.faq_submitted_query = None
    st.session_state.greeted = False 
    st.session_state.show_starter_faqs = True 
    st.session_state.conversion_score = 1 # Reset score
    st.session_state.lead_prompt_shown = False # Reset prompt status
    st.session_state.lead_saved = check_lead_saved(st.session_state.user_id) # Check if persisted lead exists
    st.rerun()


def set_input_text(text):
    """Sets the processing flag for FAQ/Suggestion buttons."""
    st.session_state.faq_submitted_query = text
    st.session_state.user_input = "" 
    st.session_state.show_starter_faqs = False 


def get_history_queries(num_turns=3):
    """Extracts recent user queries for contextual search."""
    history_queries = []
    for message in st.session_state.messages[:-1]: 
        if message['role'] == 'user':
            translated_text = message.get('translated_query') or message['content']
            history_queries.append(translated_text)
    return " | ".join(history_queries[-num_turns:])


# --- Feedback Handlers ---
def handle_feedback(message_index, feedback_type):
    """Handles user feedback: triggers cache update on like, or regeneration on dislike."""
    st.session_state.feedback[message_index] = feedback_type
    
    assistant_message = st.session_state.messages[message_index]
    user_message = st.session_state.messages[message_index - 1]
    
    # Log the rating (1 for like, 0 for dislike)
    log_chatbot_interaction(
        user_id=st.session_state.user_id, # Log current user ID
        query=user_message['content'], # Original user query
        translated_query=user_message['translated_query'], 
        answer=assistant_message['content'],
        source=assistant_message['source_tag'],
        language=assistant_message['language'],
        rating=1 if feedback_type == 'like' else 0,
        conversion_score=st.session_state.conversion_score # Log current conversion score
    )

    if feedback_type == 'dislike':
        st.session_state.regenerate_index = message_index
        st.toast("Feedback recorded. Regenerating answer now... 🔄")
        
    elif feedback_type == 'like':
        query_to_cache = assistant_message.get('query_to_cache')
        
        if query_to_cache:
            original_query, new_answer_en, new_source = query_to_cache
            success = update_cached_answer(original_query, new_answer_en, new_source) 
            if success:
                st.toast("Feedback recorded and Cache updated with better answer! 👍 (Persistent)")
            else:
                st.toast("Feedback recorded, but failed to update persistent cache.")
        else:
            st.toast("Thank you for the positive feedback! 👍")

    st.rerun() 

# --- Lead Capture Handler ---
def handle_lead_capture(user_id, name, email, phone, score):
    """Handles submission of the lead capture form."""
    success, message = save_lead_contact(user_id, name, email, phone, score)
    
    if success:
        st.session_state.lead_saved = True
        st.session_state.show_lead_capture = False
        st.toast("✅ Thank you! We will reach out to you with details shortly.", icon="📧")
        st.success("Your contact details have been successfully saved.")
        st.markdown("*Your contact details will only be used by Leanext Consulting for follow-up and will not be shared externally.*")
    else:
        st.error(f"Failed to save contact: {message}")

# --- SCORE BADGE FUNCTION ---
def get_score_badge(score):
    """Returns Markdown for the visual score badge."""
    score_data = CONVERSION_SCORE_MAP.get(score, CONVERSION_SCORE_MAP[1])
    label, color = score_data
    
    # Generate stars (e.g., '★★★★☆')
    stars = '★' * score + '☆' * (5 - score)
    
    # Use HTML/CSS for a visually distinct badge
    badge_html = f"""
    <div style="
        border: 2px solid {color};
        border-radius: 8px;
        padding: 8px;
        margin-top: 10px;
        text-align: center;
        background-color: rgba(255, 255, 255, 0.05);
    ">
        <div style="font-weight: bold; color: {color}; font-size: 1.1em;">
            {label}
        </div>
        <div style="color: #FFD700; font-size: 1.2em; letter-spacing: 2px;">
            {stars}
        </div>
        <div style="font-size: 0.8em; color: gray; margin-top: 5px;">
            User ID: {st.session_state.user_id[:8]}...
        </div>
    </div>
    """
    st.markdown(badge_html, unsafe_allow_html=True)


# --- Main App Execution ---
init_session_state()

# Load the main KB and FAQ index
chroma_collection = load_or_build_knowledge_base() 
faq_suggestions_collection = build_and_index_faq_suggestions() 


# --- Sidebar Setup ---
with st.sidebar:
    st.title("💡 LeanBot")
    st.caption("Advanced RAG & Multilingual AI.")
    
    # NEW: Display Conversion Score Badge
    get_score_badge(st.session_state.conversion_score)
    
    st.button("🧹 Clear Chat History", on_click=clear_chat, use_container_width=True)
    
    st.markdown("---")
    st.subheader("Debug & Crawler")
    st.session_state.debug_mode = st.toggle("Show Crawler URLs Debug", value=st.session_state.debug_mode)
    if st.session_state.debug_mode:
        if chroma_collection:
            with st.expander("Indexed URLs"):
                indexed_urls = get_all_indexed_urls(chroma_collection)
                st.write(f"Total Indexed Pages: {len(indexed_urls)}")
                for i, url in enumerate(indexed_urls[:10]):
                    st.caption(f"{i+1}. {url}")
        else:
            st.caption("KB not loaded.")
            
        if faq_suggestions_collection:
            with st.expander("FAQ Index Status"):
                 st.write(f"Indexed Questions: {faq_suggestions_collection.count()}")
        else:
             st.caption("FAQ Index not loaded.")


st.title("🗣️ LEANEXT Conversational AI")
st.caption("Sitemap-driven, depth-limited crawler ensures comprehensive grounding in website data.")


if chroma_collection is None:
    st.error("Cannot run the chatbot. Knowledge Base failed to load.")
    st.stop()


# --- Display Chat History (With Feedback Buttons and Suggestions) ---
if not st.session_state.greeted:
    greeting = get_greeting()
    initial_message = f"{greeting} I'm LeanBot, your AI assistant from Leanext Consulting. How can I help you today?"
    with st.chat_message("assistant"):
        st.markdown(initial_message)
    st.session_state.greeted = True

for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        if message["role"] == "assistant":
            source_info = message.get("source_tag")
            language_info = f" | Lang: {message.get('language', DEFAULT_LANGUAGE).upper()}"
            distance_info = f" | Dist: {message.get('distance', 0.0):.4f}" if message.get('distance') else ""
            
            # Display language detection above the answer
            st.caption(f"Source: {source_info}{language_info}{distance_info}")
            
            # --- START: Feedback Button Rendering ---
            if not source_info.startswith("Small Talk") and i > 0:
                
                st.markdown("---", unsafe_allow_html=False)
                col_up, col_down, _ = st.columns([0.05, 0.05, 0.9])
                
                current_feedback = st.session_state.feedback.get(i)
                
                up_key = f"up_{i}"
                if col_up.button("👍", key=up_key, disabled=(current_feedback == 'like')):
                    handle_feedback(i, 'like')
                
                down_key = f"down_{i}"
                if col_down.button("👎", key=down_key, disabled=(current_feedback == 'dislike')):
                    handle_feedback(i, 'dislike')
            # --- END: Feedback Button Rendering ---
        
        st.caption(message["timestamp"])


# 2. Suggested Starter Questions 
if st.session_state.show_starter_faqs: 
    # Logic remains the same...
    st.markdown("### 💬 Popular Questions")
    cols = st.columns(3)
    for i, faq in enumerate(SUGGESTED_FAQS[:6]):
        col = cols[i % 3]
        col.button(faq, on_click=set_input_text, args=[faq], key=f"faq_starter_{i}", type="secondary", use_container_width=True)
    
    st.markdown("---")
    
    # 2. Expander for the Full 100-Question Library
    if FAQ_SEED_QUESTIONS:
         with st.expander(f"📚 Explore Our Full FAQ Library ({len(FAQ_SEED_QUESTIONS)} Questions)"):
            faq_cols = st.columns(3)
            for i, question in enumerate(FAQ_SEED_QUESTIONS):
                col = faq_cols[i % 3]
                col.button(question, on_click=set_input_text, args=[question], key=f"full_faq_{i}", type="secondary", use_container_width=True)
            
    st.markdown("---")


# --- NEW: CONDITIONAL LEAD CAPTURE PROMPT AND FORM ---
if st.session_state.conversion_score >= HIGH_POTENTIAL_THRESHOLD and not st.session_state.lead_saved and not st.session_state.lead_prompt_shown:
    st.session_state.show_lead_capture = True
    st.session_state.lead_prompt_shown = True # Only prompt once per high-score session

if st.session_state.show_lead_capture and not st.session_state.lead_saved:
    with st.expander("🚀 **Connect with a Consultant Now!**", expanded=True):
        st.markdown(f"""
        **Your engagement shows high intent!** Would you like Leanext Consulting to reach out 
        to you with more details about our services or training? Please share your contact information below.
        """)
        
        with st.form("lead_capture_form"):
            name = st.text_input("Name (Optional)", max_chars=100)
            email = st.text_input("Email (Required for Contact)", help="We will use this to follow up.")
            phone = st.text_input("Phone Number (Optional)", max_chars=20)
            
            submitted = st.form_submit_button("Submit Contact Info")
            
            if submitted:
                handle_lead_capture(
                    st.session_state.user_id, name, email, phone, st.session_state.conversion_score
                )
                st.rerun()
            
        st.caption("Your contact details will only be used by Leanext Consulting for follow-up and will not be shared externally.")


# --- Input Logic (Remains at the bottom of the main area) ---
prompt = None 
with st.form("chat_form", clear_on_submit=True):
    current_input_value = st.text_input("Ask about services or just say 'hello' (supports English, Hindi, Marathi, Kannada, Bengali)...", key='user_input', label_visibility="collapsed")
    
    submitted = st.form_submit_button("Send ⬆️", type="primary")

    if submitted and current_input_value.strip():
        prompt = current_input_value.strip()
        st.session_state.show_starter_faqs = False 

prompt_to_process = prompt 
if st.session_state.faq_submitted_query is not None:
    prompt_to_process = st.session_state.faq_submitted_query
    st.session_state.faq_submitted_query = None


# --- RAG Pipeline Execution (Initial Query) ---
if prompt_to_process:
    
    # --- STAGE 1: Language Detection and Translation (User Input) ---
    original_query = prompt_to_process
    detected_lang = DEFAULT_LANGUAGE
    translated_query = original_query
    
    if TRANSLATOR_READY:
        try:
            translated_query, detected_lang = translator.to_english(original_query)
        except Exception as e:
            logging.error(f"Translation (to English) failed: {e}")
            detected_lang = DEFAULT_LANGUAGE
            translated_query = original_query
    
    # Store the user message (including the translated version for RAG history)
    st.session_state.messages.append({
        "role": "user", "content": original_query, 
        "timestamp": datetime.datetime.now().strftime("%I:%M %p"),
        "translated_query": translated_query, # Store translated query for RAG/Gemini logic
        "detected_lang": detected_lang # Store detected language for use in the next assistant turn
    })
    st.rerun() 

# 2. Process the most recent user message
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user" and st.session_state.regenerate_index == -1:
    
    user_message = st.session_state.messages[-1]
    original_query = user_message["content"]
    query_for_rag = user_message["translated_query"]
    detected_lang = user_message.get("detected_lang", DEFAULT_LANGUAGE) 

    with st.chat_message("assistant"):

        response_container = st.empty()
        response_container.markdown(f"Assistant is thinking in **{detected_lang.upper()}**... ✍️")

        # 1. Get RAG History
        history = get_history_queries(num_turns=3)

        # 2. RAG call (uses translated English text)
        # FIX: Correctly unpack 8 return values from answer_query_with_cache_first (added new_conversion_score)
        (
            response_en, source, distance, top_k_metadata_list, is_unclear, _, 
            _, new_conversion_score
        ) = answer_query_with_cache_first(
            original_query, chroma_collection, st.session_state.conversion_score, history_queries=history
        )
        
        # Update session score immediately
        st.session_state.conversion_score = new_conversion_score
        
        bot_timestamp = datetime.datetime.now().strftime("%I:%M %p")
        
        final_output = FINAL_FALLBACK_MESSAGE
        final_output_en = FINAL_FALLBACK_MESSAGE

        # --- Response Assembly ---
        if is_unclear:
            final_output_en = UNCLEAR_QUERY_RESPONSE
            final_output = translator.from_english(final_output_en, detected_lang) if TRANSLATOR_READY else final_output_en
            response_container.warning(f"⚠️ **{final_output}**")
            
        else:
            final_output_en = response_en
            
            # 3. Translate Answer back to detected language
            if detected_lang != DEFAULT_LANGUAGE and TRANSLATOR_READY:
                try:
                    final_output = translator.from_english(final_output_en, detected_lang)
                except Exception as e:
                    logging.error(f"Translation (from English to {detected_lang}) failed: {e}")
                    final_output = final_output_en
            else:
                final_output = final_output_en
            
            # 4. Append landing page link (always using English metadata)
            recommended_page = None
            if source.startswith("Gemini API"): 
                recommended_page = match_landing_page(query_for_rag, top_k_metadata_list)
            
            if recommended_page:
                title = recommended_page['title']
                url = recommended_page['url']
                final_output += f"\n\n---\n\n🔗 **Related Page:** [{title}]({url})"
            
            response_container.markdown(final_output)
            
        
        # 5. Log the interaction (with score)
        log_chatbot_interaction(
            user_id=st.session_state.user_id,
            query=original_query,
            translated_query=query_for_rag,
            answer=final_output_en, # Log the English answer (standardized cache data)
            source=source,
            language=detected_lang,
            rating=None, # Initial log has no rating
            conversion_score=st.session_state.conversion_score # Log the NEW score
        )
        
        # --- RE-INSERTED LOGIC: Persistent FAQ Suggestions ---
        top_3_faq_qs = []
        if faq_suggestions_collection:
            top_3_faq_qs = get_similar_faq_suggestions(
                query_for_rag, 
                faq_suggestions_collection, 
                limit=3
            )
        
        if top_3_faq_qs: 
            with st.expander("💡 Top 3 Related FAQs (Click to Ask)"):
                for i, q_text in enumerate(top_3_faq_qs): # q_text is the string question
                    # Translate the FAQ question back to the user's language for the button label
                    q_in_user_lang = translator.from_english(q_text, detected_lang) if TRANSLATOR_READY else q_text
                    # The text passed to set_input_text must be the original English question for RAG processing
                    st.button(q_in_user_lang, on_click=set_input_text, args=[q_text], key=f"related_faq_sug_{i}", type="secondary", use_container_width=True)
        # --- End Persistent FAQ Suggestions ---


        # Append message
        st.session_state.messages.append({
            "role": "assistant", "content": final_output, 
            "timestamp": bot_timestamp,
            "source_tag": source, "distance": distance or 0.0, 
            "top_k_metadata": top_k_metadata_list,
            "query_to_cache": None, # Only regenerated answers get this
            "language": detected_lang # Store detected language for display/feedback
        })
        
        # Debug View
        if st.session_state.debug_mode and top_k_metadata_list:
             with st.expander("🔎 RAG Debug (Top K Metadata)"):
                 for i, meta in enumerate(top_k_metadata_list):
                     try:
                         headings_list = json.loads(meta.get('headings', '[]'))
                     except:
                         headings_list = ["Error parsing headings"]
                         
                     st.json({
                         "Rank": i + 1, "Distance": meta.get('distance'),
                         "Canonical URL": meta.get('canonical'), "Title": meta.get('title'),
                         "Path": meta.get('path'), "Headings": headings_list
                     })
    
    # Rerun to update sidebar score badge and possibly show the lead form
    st.rerun()


# --- Regeneration Execution ---
if st.session_state.regenerate_index != -1:
    
    idx = st.session_state.regenerate_index
    user_message = st.session_state.messages[idx - 1]
    query_for_rag = user_message["translated_query"] 
    detected_lang = st.session_state.messages[idx]["language"]
    
    st.session_state.regenerate_index = -1 
    
    with st.chat_message("assistant"):
        st.info("🔄 **Regenerating Answer...** Bypassing cache for a fresh response.")
        
        # 1. Clean query
        cleaned_question, _ = clean_query_with_gemini(query_for_rag)
        
        # 2. Force RAG generation (returns English answer)
        # FIX: Correctly unpack 7 return values from regenerate_answer
        new_response_en, new_source, new_distance, new_metadata, _, query_to_cache, _ = regenerate_answer(
            cleaned_question, chroma_collection, history_queries=get_history_queries(num_turns=3)
        )
        
        # 3. Translate new answer back
        if detected_lang != DEFAULT_LANGUAGE and TRANSLATOR_READY:
            try:
                new_response = translator.from_english(new_response_en, detected_lang)
            except Exception as e:
                logging.error(f"Regen translation failed: {e}")
                new_response = new_response_en
        else:
            new_response = new_response_en
            
        # 4. Overwrite the disliked message entry (the new one carries the cache update info)
        st.session_state.messages[idx] = {
            "role": "assistant", "content": new_response, 
            "timestamp": datetime.datetime.now().strftime("%I:%M %p"),
            "source_tag": new_source, "distance": new_distance or 0.0, 
            "top_k_metadata": new_metadata,
            "query_to_cache": query_to_cache, # Stores (query, answer_en, source) for next 'like' click
            "language": detected_lang # Maintain language tag
        }
    
    st.rerun()