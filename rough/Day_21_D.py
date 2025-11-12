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
from typing import Optional, Any, Dict, List, Tuple

# --- 1. UI Setup (MUST be the first Streamlit command) ---
st.set_page_config(page_title="LEANEXT Conversational AI", layout="wide")
st.markdown("""<style>
.stChatMessage:nth-child(even) { background-color: #e6f2ff; }
.stChatMessage:nth-child(odd) { background-color: #f0f0f0; color: #333333; }
</style>""", unsafe_allow_html=True)


# Update all imports to Day_21_*
from Day_21_B import load_or_build_knowledge_base, build_and_index_faq_suggestions
from Day_21_C import (
    clean_query_with_gemini, answer_query_with_cache_first, retrieve_context, 
    get_similar_faq_suggestions, match_landing_page, regenerate_answer, calculate_conversion_score
)
# Note: Assuming Day_21_A.py is the config file
from Day_21_A import (
    BASE_URL, SUGGESTED_FAQS, UNCLEAR_QUERY_RESPONSE, FAQ_SEED_QUESTIONS, FINAL_FALLBACK_MESSAGE,
    DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, LANGUAGE_FAIL_MESSAGE, 
    HIGH_POTENTIAL_THRESHOLD, CONVERSION_SCORE_MAP
)
from Day_21_E import log_chatbot_interaction, get_all_indexed_urls, update_cached_answer, save_lead_contact, check_lead_saved
from language_middleware2 import LanguageTranslator # New Import

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the expected RAG response shape from Day_21_C
RAG_RESPONSE_SHAPE = Tuple[str, str, Optional[float], List[Dict[str, Any]], bool, Optional[str], str, int]


# --- 2. Initialization and Translator Setup ---
try:
    translator = LanguageTranslator()
    TRANSLATOR_READY = True
except Exception as e:
    # FIX: Added specific logging for initialization failure
    logging.error(f"Multilingual feature initialization failed (language_middleware2.py): {e}. Running in English-only mode.")
    st.warning(f"Translation API Failed. Only **English** is supported. Check `language_middleware2.py` (Error: {e})", icon="⚠️")
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
    
    # --- Lead Scoring and User ID ---
    if 'user_id' not in st.session_state: st.session_state.user_id = secrets.token_hex(16)
    if 'conversion_score' not in st.session_state: st.session_state.conversion_score = 1
    # show_lead_capture now controls the inline expander visibility (no longer a modal)
    if 'show_lead_capture' not in st.session_state: st.session_state.show_lead_capture = False
    if 'lead_saved' not in st.session_state: st.session_state.lead_saved = check_lead_saved(st.session_state.user_id)
    if 'lead_prompt_shown' not in st.session_state: st.session_state.lead_prompt_shown = False
    # State for form submission message
    if 'lead_submit_message' not in st.session_state: st.session_state.lead_submit_message = (None, None) # (Type, Message)


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
    st.session_state.show_lead_capture = False # Hide section
    # FIX: Ensure lead_saved re-check is called after clear, in case a lead was saved but not yet persisted across sessions.
    st.session_state.lead_saved = check_lead_saved(st.session_state.user_id) # Check if persisted lead exists
    st.session_state.lead_submit_message = (None, None) # Clear message
    st.rerun()


def set_input_text(text):
    """Sets the processing flag for FAQ/Suggestion buttons."""
    # The text passed here is the original English FAQ seed question
    st.session_state.faq_submitted_query = text
    st.session_state.user_input = "" 
    st.session_state.show_starter_faqs = False 


def get_history_queries(num_turns=3):
    """Extracts recent user queries for contextual search."""
    history_queries = []
    # FIX: Iterate through all messages EXCEPT the last one (which is the current user query being processed)
    # The current message is processed *after* this history is gathered.
    for message in st.session_state.messages: 
        if message['role'] == 'user':
            # Use the translated query stored at user submission time
            translated_text = message.get('translated_query') or message['content']
            history_queries.append(translated_text)
    
    # Only return the last 'num_turns' translated queries
    return " | ".join(history_queries[-num_turns:])


# --- Feedback Handlers ---
def handle_feedback(message_index, feedback_type):
    """Handles user feedback: triggers cache update on like, or regeneration on dislike."""
    st.session_state.feedback[message_index] = feedback_type
    
    assistant_message = st.session_state.messages[message_index]
    # FIX: The user message is always at index - 1
    user_message = st.session_state.messages[message_index - 1]
    
    # Log the rating (1 for like, 0 for dislike)
    log_chatbot_interaction(
        user_id=st.session_state.user_id, # Log current user ID
        query=user_message['content'], # Original user query
        translated_query=user_message.get('translated_query', user_message['content']), 
        # FIX: The assistant message content is the translated one. We log the English raw LLM output for cache standardization.
        # Check for 'llm_raw' which holds the English answer from the RAG pipeline.
        answer=assistant_message.get('llm_raw') or assistant_message['content'], # Use English raw for logs/cache
        source=assistant_message['source_tag'],
        language=assistant_message['language'],
        rating=1 if feedback_type == 'like' else 0,
        conversion_score=st.session_state.conversion_score # Log current conversion score
    )

    if feedback_type == 'dislike':
        st.session_state.regenerate_index = message_index
        st.toast("Feedback recorded. Regenerating answer now... 🔄")
        
    elif feedback_type == 'like':
        # 'query_to_cache' is a tuple: (cleaned_english_question, new_answer_en, new_source)
        query_to_cache_data = assistant_message.get('query_to_cache')
        
        if query_to_cache_data:
            # FIX: The original logic here was wrong, as query_to_cache was only set during regeneration.
            # When LIKING a regenerated answer, use the stored tuple.
            original_query_en, new_answer_en, new_source = query_to_cache_data
            success = update_cached_answer(original_query_en, new_answer_en, new_source) 
            if success:
                st.toast("Feedback recorded and Cache updated with better answer! 👍 (Persistent)")
            else:
                st.toast("Feedback recorded, but failed to update persistent cache.")
        else:
            # When LIKING a regular answer, we assume it's already cached or not cacheable (small talk/unclear)
            st.toast("Thank you for the positive feedback! 👍")

    st.rerun() 

# --- Lead Capture Handler ---
def handle_lead_capture_submission(name, email, phone, organization):
    """Handles submission of the lead capture form within the inline expander."""
    
    # Validation checks 
    name = name.strip()
    email = email.strip()
    phone = phone.strip()
    organization = organization.strip()
    
    if not name:
        st.session_state.lead_submit_message = ('error', "Name is mandatory. Please provide your name.")
        return 

    # FIX: Added a more robust email/phone check
    is_valid_email = re.match(r"[^@]+@[^@]+\.[^@]+", email)
    is_valid_phone = re.match(r"^[\s\d\+\-\(\)]+$", phone) # Simple check for digits/spaces/symbols

    if not (is_valid_email or is_valid_phone):
        st.session_state.lead_submit_message = ('error', "Please provide a valid Email address OR a Phone number.")
        return 
        
    # If validation passes, attempt database save
    success, message = save_lead_contact(
        st.session_state.user_id, name, email, phone, organization, st.session_state.conversion_score
    )
    
    if success:
        st.session_state.lead_saved = True
        st.session_state.show_lead_capture = False # Hide section after success
        st.session_state.lead_submit_message = (
            'success', "✅ Thank you! We will reach out to you with details shortly. (Details saved.)"
        )
        st.toast(st.session_state.lead_submit_message[1], icon="📧")
    else:
        # FIX: Log the database error
        logging.error(f"Failed to save lead contact (DB Error): {message}")
        st.session_state.lead_submit_message = ('error', f"Failed to save contact. Please try again. ({message})")
    
    # Rerun is required to update the UI
    st.rerun()


# --- SCORE BADGE FUNCTION ---
def get_score_badge(score):
    """Returns Markdown for the visual score badge."""
    score = min(max(1, score), 5) # Ensure score is within 1-5 range
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

# --- LEAD CAPTURE INLINE SECTION FUNCTION ---
def render_lead_capture_section():
    """Renders the inline lead capture form section at the bottom of the main chat area."""
    if st.session_state.show_lead_capture and not st.session_state.lead_saved:
        
        st.markdown("---")
        
        # We use st.container to make the section visually distinct
        with st.container(border=True):
            st.markdown("## 🚀 Connect with a Consultant Now!")
            st.markdown(f"""
            **Your engagement shows high intent!** Would you like Leanext Consulting to reach out 
            to you with more details about our services or training? Please share your contact information below.
            """)
            
            # Display any previous submission error/success message
            msg_type, msg_text = st.session_state.lead_submit_message
            if msg_text:
                if msg_type == 'error':
                    st.error(msg_text)
                elif msg_type == 'success':
                    st.success(msg_text)
            
            # Reset message after display
            st.session_state.lead_submit_message = (None, None)
                
            with st.form("inline_lead_capture_form", clear_on_submit=False):
                col_n, col_o = st.columns(2)
                # Mandatory field: Name
                name = col_n.text_input("Name", help="Mandatory field.", key="lead_name")
                # Optional field: Organization
                organization = col_o.text_input("Organization (Optional)", key="lead_org")
                
                col_e, col_p = st.columns(2)
                # Conditional Mandatory fields (Email OR Phone)
                email = col_e.text_input("Email", help="Required: Provide EITHER Email OR Phone.", key="lead_email")
                phone = col_p.text_input("Phone Number", max_chars=20, help="Required: Provide EITHER Email OR Phone.", key="lead_phone")
                
                # Use a single column for the primary submit button inside the form
                submitted = st.form_submit_button("Submit Contact Info", type="primary")
                
                if submitted:
                    # Note: Submission handler triggers st.rerun if successful
                    handle_lead_capture_submission(name, email, phone, organization)
            
            # Place the "No Thanks" button OUTSIDE the form to avoid callback conflicts
            st.button("No Thanks (Dismiss for this session)", on_click=lambda: st.session_state.update(show_lead_capture=False, lead_prompt_shown=True))

            st.caption("Your contact details will only be used by Leanext Consulting for follow-up and will not be shared externally.")


# --- Main App Execution ---
init_session_state()

# Load the main KB and FAQ index
# FIX: Unpack both returns from load_or_build_knowledge_base
chroma_collection, faq_suggestions_collection = load_or_build_knowledge_base() 
# FIX: The FAQ build function is no longer called here, it's inside the load_or_build_knowledge_base
# faq_suggestions_collection = build_and_index_faq_suggestions() 


# --- Sidebar Setup ---
with st.sidebar:
    st.title("💡 LeanBot")
    st.caption("Advanced RAG & Multilingual AI.")
    
    # Display Conversion Score Badge
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
                # FIX: Check the length before iterating
                if indexed_urls:
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
        # FIX: Also need to log the initial greeting as an assistant message
        st.session_state.messages.append({
            "role": "assistant", "content": initial_message, 
            "timestamp": datetime.datetime.now().strftime("%I:%M %p"),
            "source_tag": "Initial Greeting", "distance": 0.0, 
            "top_k_metadata": [],
            "query_to_cache": None,
            "language": DEFAULT_LANGUAGE,
            "llm_raw": initial_message # Store raw message for consistency
        })
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
            # FIX: Only show feedback for messages that aren't the initial greeting or small talk
            if not source_info.startswith("Small Talk") and not source_info.startswith("Initial Greeting") and i > 0:
                
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
                # FIX: Ensure all FAQ buttons hide the starter questions
                col.button(question, on_click=set_input_text, args=[question], key=f"full_faq_{i}", type="secondary", use_container_width=True)
            
    st.markdown("---")


# --- CONDITIONAL LEAD CAPTURE TRIGGER ---
# Set the flag to show the inline section if conversion score is high and lead is not saved
if st.session_state.conversion_score >= HIGH_POTENTIAL_THRESHOLD and not st.session_state.lead_saved and not st.session_state.lead_prompt_shown:
    st.session_state.show_lead_capture = True
    st.session_state.lead_prompt_shown = True # Only prompt once per high-score session


# --- Render the Inline Lead Capture Section ---
# This is placed here to be below the chat history but above the user input form
render_lead_capture_section()


# --- Input Logic (Remains at the bottom of the main area) ---
prompt = None 
with st.form("chat_form", clear_on_submit=True):
    # Retrieve the input value, keeping the key 'user_input'
    current_input_value = st.text_input("Ask about services or just say 'hello' (supports English, Hindi, Marathi, Kannada, Bengali, Gujarati)...", key='user_input', label_visibility="collapsed")
    
    # FIX: Stabilize button disability check by directly accessing the session state key.
    # We use st.session_state.user_input for the check.
    input_is_empty = not st.session_state.user_input.strip() if 'user_input' in st.session_state else True
    
    submitted = st.form_submit_button(
        "Send ⬆️", 
        type="primary", 
        # Use the derived state from session_state for reliability
        disabled=input_is_empty
    )

    if submitted and st.session_state.user_input.strip(): # Use session state for the logic trigger as well
        prompt = st.session_state.user_input.strip()
        st.session_state.show_starter_faqs = False 

# ... (rest of the file remains unchanged)

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
            # translator.to_english returns (translated_text, detected_language_code)
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
# FIX: Use index check for safety, and check if the turn is an assistant response
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user" and st.session_state.regenerate_index == -1:
    
    user_message = st.session_state.messages[-1]
    original_query = user_message["content"]
    query_for_rag = user_message["translated_query"]
    detected_lang = user_message.get("detected_lang", DEFAULT_LANGUAGE) 

    with st.chat_message("assistant"):

        response_container = st.empty()
        response_container.markdown(f"Assistant is thinking in **{detected_lang.upper()}**... ✍️")
        
        # 1. Get RAG History (uses translated English queries)
        history = get_history_queries(num_turns=3)

        # 2. RAG call (uses translated English text)
        # FIX: Unpack the new 8-element return shape (answer_text, source, distance, top_k_metadata_list, is_unclear, llm_raw, detected_lang_code, new_conversion_score)
        (
            response_in_lang, source, distance, top_k_metadata_list, is_unclear, 
            response_en, _, new_conversion_score
        ) = answer_query_with_cache_first(
            original_query, chroma_collection, st.session_state.conversion_score, history_queries=history
        )
        
        # Update session score immediately
        st.session_state.conversion_score = new_conversion_score
        
        bot_timestamp = datetime.datetime.now().strftime("%I:%M %p")
        
        final_output = response_in_lang
        final_output_en = response_en # The English raw LLM output, used for logging/caching

        # --- Response Assembly ---
        if is_unclear:
            # FIX: Use the response_in_lang directly, which contains the translated UNCLEAR_QUERY_RESPONSE
            response_container.warning(f"⚠️ **{final_output}**")
            
        else:
            # FIX: Ensure final_output_en is set correctly for non-unclear responses
            final_output_en = response_en if response_en else FINAL_FALLBACK_MESSAGE
            
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
            # FIX: Log the English raw LLM answer for standardization
            answer=final_output_en, 
            source=source,
            language=detected_lang,
            rating=None, # Initial log has no rating
            conversion_score=st.session_state.conversion_score # Log the NEW score
        )
        
        # --- RE-INSERTED LOGIC: Persistent FAQ Suggestions (Running unconditionally) ---
        top_3_faq_qs = []
        if faq_suggestions_collection:
            query_for_suggestions = query_for_rag if query_for_rag else original_query
            top_3_faq_qs = get_similar_faq_suggestions(
                query_for_suggestions, 
                faq_suggestions_collection, 
                limit=3
            )
        
        if top_3_faq_qs: 
            with st.expander("💡 Top 3 Related FAQs (Click to Ask)"):
                for i, q_text in enumerate(top_3_faq_qs): # q_text is the string question
                    # FIX: Only translate the button text if the translator is ready
                    q_in_user_lang = q_text
                    if TRANSLATOR_READY and detected_lang != DEFAULT_LANGUAGE:
                        try:
                            q_in_user_lang = translator.from_english(q_text, detected_lang)
                        except Exception as e:
                            logging.error(f"FAQ Suggestion translation failed: {e}")
                            q_in_user_lang = q_text
                    
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
            "language": detected_lang, # Store detected language for display/feedback
            "llm_raw": final_output_en # Store the English raw LLM output for consistent logging/caching on 'like'
        })
        
        # Debug View
        if st.session_state.debug_mode and top_k_metadata_list:
             with st.expander("🔎 RAG Debug (Top K Metadata)"):
                 for i, meta in enumerate(top_k_metadata_list):
                     # FIX: Headings is already a list in the metadata from Day_21_C
                     headings_list = meta.get('headings', [])
                         
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
    original_query = user_message["content"]
    detected_lang = st.session_state.messages[idx]["language"]
    
    st.session_state.regenerate_index = -1 
    
    with st.chat_message("assistant"):
        st.info("🔄 **Regenerating Answer...** Bypassing cache for a fresh response.")
        
        # 1. Force RAG generation (returns the 8-element tuple)
        # FIX: Unpack the 8-element return shape (answer_text, source, distance, top_k_metadata_list, is_unclear, llm_raw, detected_lang_code, conversion_score)
        (
            new_response, new_source, new_distance, new_metadata, _, 
            new_response_en, _, _
        ) = regenerate_answer(
            original_query, chroma_collection, history_queries=get_history_queries(num_turns=3)
        )
        
        # FIX: query_to_cache must be generated here using the English components for the next 'like' click
        # The regenerate_answer function now returns the English response as llm_raw.
        if new_response_en and new_response_en != FINAL_FALLBACK_MESSAGE:
            # We must clean the original English query for the cache key
            cleaned_question_for_cache, _ = clean_query_with_gemini(user_message["translated_query"])
            cache_source_tag = new_metadata[0].get('canonical', 'RAG-Regen') if new_metadata else 'RAG-Regen'
            query_to_cache_data = (cleaned_question_for_cache, new_response_en, cache_source_tag)
        else:
            query_to_cache_data = None
            
        # 4. Overwrite the disliked message entry (the new one carries the cache update info)
        st.session_state.messages[idx] = {
            "role": "assistant", "content": new_response, 
            "timestamp": datetime.datetime.now().strftime("%I:%M %p"),
            "source_tag": new_source, "distance": new_distance or 0.0, 
            "top_k_metadata": new_metadata,
            "query_to_cache": query_to_cache_data, # Stores (query, answer_en, source) for next 'like' click
            "language": detected_lang, # Maintain language tag
            "llm_raw": new_response_en # Store the English raw LLM output
        }
    
    st.rerun()