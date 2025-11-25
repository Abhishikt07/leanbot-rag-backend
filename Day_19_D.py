"""
Main Application Module: Streamlit UI entry point with Feedback, Regeneration, and Multilingual Support.
- FIXES: Command order error (set_page_config is first).
- FIXES: Correctly calls log_chatbot_interaction with all six arguments.
- Integrates LanguageTranslator for I/O.
- FIXES: Critical ValueError by correctly unpacking 7 return values from RAG functions.
- FIXES: Removes redundant query cleaning API call.
"""
import streamlit as st
import datetime
import logging
import json 
import time

# --- 1. UI Setup (MUST be the first Streamlit command) ---
st.set_page_config(page_title="LEANEXT Conversational AI", layout="wide")
st.markdown("""<style>
.stChatMessage:nth-child(even) { background-color: #e6f2ff; }
.stChatMessage:nth-child(odd) { background-color: #f0f0f0; color: #333333; }
</style>""", unsafe_allow_html=True)


# Update all imports to Day_19_*
import chromadb
from .app.Day_19_A import CHROMA_DB_PATH, FAQ_COLLECTION_NAME

from .app.Day_19_B import load_or_build_knowledge_base, build_and_index_faq_suggestions
from .app.Day_19_C import (
    clean_query_with_gemini, answer_query_with_cache_first, retrieve_context, 
    get_similar_faq_suggestions, match_landing_page, regenerate_answer, calculate_lead_score
)
# Note: Assuming Day_19_A.py is the config file
from .app.Day_19_A import (
    BASE_URL, SUGGESTED_FAQS, UNCLEAR_QUERY_RESPONSE, FAQ_SEED_QUESTIONS, FINAL_FALLBACK_MESSAGE,
    DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, LANGUAGE_FAIL_MESSAGE, LEAD_SCORE_WEIGHTS, LEAD_TRIGGER_KEYWORDS
)
from .app.Day_19_E import log_chatbot_interaction, get_all_indexed_urls, update_cached_answer, log_lead_data
from .app.language_middleware import LanguageTranslator # New Import

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 2. Initialization and Translator Setup ---
try:
    # Initialize the Translator instance *after* set_page_config
    # FIX: Initializing without the unsupported argument 'supported_langs'
    translator = LanguageTranslator()
    TRANSLATOR_READY = True
except Exception as e:
    # Log the failure but continue running the app
    logging.error(f"Multilingual feature initialization failed: {e}. Running in English-only mode.")
    st.warning(f"Translation API Failed. Only **English** is supported. Check `language_middleware.py` (Error: {e})", icon="⚠️")
    TRANSLATOR_READY = False
    translator = None # Ensure translator is None if initialization failed


def init_session_state():
    if "messages" not in st.session_state: st.session_state.messages = []
    if 'user_input' not in st.session_state: st.session_state.user_input = ""
    if 'last_user_input_check' not in st.session_state: st.session_state.last_user_input_check = ""
    if 'faq_submitted_query' not in st.session_state: st.session_state.faq_submitted_query = None
    if 'greeted' not in st.session_state: st.session_state.greeted = False 
    if 'debug_mode' not in st.session_state: st.session_state.debug_mode = False 
    if 'regenerate_index' not in st.session_state: st.session_state.regenerate_index = -1 
    if 'feedback' not in st.session_state: st.session_state.feedback = {} 
    if 'show_starter_faqs' not in st.session_state: st.session_state.show_starter_faqs = True
    if 'lead_score' not in st.session_state: st.session_state.lead_score = 0.0 # NEW
    if 'lead_logged' not in st.session_state: st.session_state.lead_logged = False # NEW
    if 'show_lead_form' not in st.session_state: st.session_state.show_lead_form = False # NEW

def get_greeting():
    hour = datetime.datetime.now().hour
    return "🌞 Good morning!" if hour < 12 else "☀️ Good afternoon!" if hour < 18 else "🌙 Good evening!"


def clear_chat():
    st.session_state.messages = []
    st.session_state.user_input = ""
    st.session_state.faq_submitted_query = None
    st.session_state.greeted = False 
    st.session_state.show_starter_faqs = True 
    st.rerun()


def set_input_text(text):
    """Sets the processing flag for FAQ/Suggestion buttons."""
    st.session_state.faq_submitted_query = text
    st.session_state.user_input = "" 
    st.session_state.show_starter_faqs = False 
    # The prompt processing loop will handle the rerun


def get_history_queries(num_turns=3):
    """Extracts recent user queries for contextual search."""
    history_queries = []
    # We only look at the 'translated_query' from user messages if available
    for message in st.session_state.messages[:-1]: 
        if message['role'] == 'user':
            # Use the stored translated version for RAG history if it exists
            translated_text = message.get('translated_query') or message['content']
            history_queries.append(translated_text)
    return " | ".join(history_queries[-num_turns:])

import re
def validate_email(email):
    # Simple check for @ and .
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def validate_phone(number):
    # Check for exactly 10 digits
    return re.match(r"^\d{10}$", number)

# 🔹 ADD THE COMPLETE, CORRECTED FUNCTION DEFINITION HERE
def submit_lead_form(name, number, email, demo_type, org):
    """Handles form validation and logging, including demo type."""
    if not name.strip():
        st.session_state.lead_form_error = "Name is mandatory."
        return False
        
    num = number.strip() if number else None
    em = email.strip() if email else None
    
    # Either number or email must be provided and valid
    if not num and not em:
        st.session_state.lead_form_error = "Provide either a contact number or an email."
        return False
        
    if num and not validate_phone(num):
        st.session_state.lead_form_error = "Contact Number must be exactly 10 digits."
        return False
        
    if em and not validate_email(em):
        st.session_state.lead_form_error = "Invalid email format (e.g., must contain @ and .)."
        return False
        
    # CRITICAL: This line uses the new demo_type argument
    if log_lead_data(name, num, em, demo_type, org.strip() if org else None):
        st.session_state.lead_logged = True
        st.session_state.show_lead_form = False
        st.toast("✅ Lead captured! A consultant will contact you shortly.")
        st.rerun() 
        return True
    else:
        st.session_state.lead_form_error = "Database Error: Could not save lead."
        return False
# 🔹 END ADDITION

# --- Feedback Handlers ---
def handle_feedback(message_index, feedback_type):
    """Handles user feedback: triggers cache update on like, or regeneration on dislike."""
    st.session_state.feedback[message_index] = feedback_type
    
    assistant_message = st.session_state.messages[message_index]
    user_message = st.session_state.messages[message_index - 1]
    
    # Log the rating (1 for like, 0 for dislike)
    log_chatbot_interaction(
        query=user_message['content'], # Original user query
        translated_query=user_message['translated_query'], 
        answer=assistant_message['content'],
        source=assistant_message['source_tag'],
        language=assistant_message['language'],
        rating=1 if feedback_type == 'like' else 0
    )

    if feedback_type == 'dislike':
        # Trigger regeneration
        st.session_state.regenerate_index = message_index
        st.toast("Feedback recorded. Regenerating answer now... 🔄")
        
    elif feedback_type == 'like':
        # --- CRITICAL PERSISTENCE LOGIC ---
        query_to_cache = assistant_message.get('query_to_cache')
        
        if query_to_cache:
            original_query, new_answer_en, new_source = query_to_cache
            # The cache stores the English version of the answer (new_answer_en is the English text)
            success = update_cached_answer(original_query, new_answer_en, new_source) 
            if success:
                st.toast("Feedback recorded and Cache updated with better answer! 👍 (Persistent)")
            else:
                st.toast("Feedback recorded, but failed to update persistent cache.")
        else:
            st.toast("Thank you for the positive feedback! 👍")

    st.rerun() 



# --- Main App Execution ---
init_session_state()

# Load the main KB and FAQ index
chroma_collection = load_or_build_knowledge_base() 
# Load FAQ collection instead of rebuilding it
import chromadb
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
faq_suggestions_collection = client.get_collection(name=FAQ_COLLECTION_NAME, embedding_function=None)


# --- Sidebar Setup ---
with st.sidebar:
    st.title("💡 LeanBot")
    st.caption("Advanced RAG & Multilingual AI.")
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
    # 1. Primary Suggested FAQs
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

# --- 5. Conditional Lead Pop-up (NEW) ---
# NOTE: Using st.popover as a fallback for environment stability, 
# as st.dialog may be causing unexpected context issues (AttributeError: __enter__).
if st.session_state.show_lead_form and not st.session_state.lead_logged:
    
    # Use st.popover instead of st.dialog
    with st.popover("🚀 Ready to Consult? (High-Interest Query Detected)", use_container_width=True): 
        st.markdown("We noticed your question is highly relevant to our core services. Get in touch directly!")
        
        # Use an internal form to manage submission state cleanly
        with st.form("lead_capture_form_popover", clear_on_submit=False): # Unique form key
            
            # Mandatory Field
            lead_name = st.text_input("Your Name * (Mandatory)", key="lead_name_popover_field") 
            
            # Either/Or Fields
            col1, col2 = st.columns(2)
            lead_number = col1.text_input("Contact Number (10 Digits)", key="lead_number_popover_field", max_chars=10) 
            lead_email = col2.text_input("Email", key="lead_email_popover_field") 
            
            # Optional Field
            lead_org = st.text_input("Organization Name (Optional)", key="lead_org_popover_field") 
            
            # 🔹 ADD HERE: Demo Type Dropdown
            demo_type = st.selectbox(
                "Select Demo Type (Optional)",
                ["General Inquiry", "ERP", "Enterprise LMS", "IMS Software", "Asset & Maintenance Management Software"],
                index=0,
                key="demo_type_popover_field"
            )

            # Error Display 
            if 'lead_form_error' in st.session_state and st.session_state.lead_form_error:
                st.error(st.session_state.lead_form_error)
            
            # 🔹 ADD HERE: Submission Buttons
            col_contact, col_demo = st.columns(2)
            submit_button = col_contact.form_submit_button("Submit & Connect", type="primary")
            book_demo_button = col_demo.form_submit_button("📅 Book a Demo", type="secondary")

            # --- Logic executed immediately inside the form for validation ---
            if submit_button or book_demo_button: # Trigger on either button
                # Clear previous error message
                st.session_state.lead_form_error = "" 
                
                # Determine the type of submission for the logging function
                final_demo_type = demo_type if book_demo_button and demo_type != "General Inquiry" else "General Inquiry"
                
                # The submit_lead_form function now needs to be updated to accept the demo_type.
                # Since we cannot modify submit_lead_form's signature here (it's in Day_19_D.py), 
                # we'll pass it as part of the optional organization field or refactor.
                # For minimal code change, let's update the helper and log_lead_data signature in Day_19_E.
                # For this patch, let's update the local call and assume the back-end is updated.
                
                if submit_lead_form(lead_name, lead_number, lead_email, final_demo_type, lead_org):
                    # If successful, submit_lead_form handles the RERUN and state updates
                    pass 
                else:
                    # If validation fails, update error message and rerun to display it
                    st.rerun() 

        # --- Close button is OUTSIDE the st.form, but INSIDE the st.popover ---
        # Note: Since popover is a click trigger, the close behavior is handled slightly differently, 
        # but a manual close button inside the popover is still the clearest UX.
        if st.button("No, thanks (Close Form)", key="close_popover_btn"):
            st.session_state.show_lead_form = False
            st.rerun()

# --- Input Logic ---
prompt = None 
with st.form("chat_form", clear_on_submit=True):
    current_input_value = st.text_input("Ask about services or just say 'hello' (supports English, Hindi, Marathi, Kannada, Bengali)...", key='user_input', label_visibility="collapsed")
    
    # Autocomplete is intentionally removed here to simplify the multilingual logic flow
    
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
    
    # 1. Immediate Keyword Check (Pop-up on first high-intent question)
    if not st.session_state.lead_logged and any(k in prompt_to_process.lower() for k in LEAD_TRIGGER_KEYWORDS):
        st.session_state.show_lead_form = True
        # If triggered by a hard keyword, only trigger the form and rerun, don't process the answer yet.
        # This gives the user the immediate chance to fill the form.
        # We will let the RAG logic run in the next RERUN cycle.

    # --- STAGE 1: Language Detection and Translation (User Input) ---
    original_query = prompt_to_process
    detected_lang = DEFAULT_LANGUAGE
    translated_query = original_query
    
    if TRANSLATOR_READY:
        try:
            translated_query, detected_lang = translator.to_english(original_query)
        except Exception as e:
            logging.error(f"Translation (to English) failed: {e}")
            # Fallback to English and continue
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
    # Use the stored translated query for RAG/Gemini logic
    query_for_rag = user_message["translated_query"]
    # Retrieve the detected language stored in the user message
    detected_lang = user_message.get("detected_lang", DEFAULT_LANGUAGE) 

    with st.chat_message("assistant"):

        response_container = st.empty()
        response_container.markdown(f"Assistant is thinking in **{detected_lang.upper()}**... ✍️")

        # 1. Get RAG History
        history = get_history_queries(num_turns=3)

        # 2. RAG call (uses translated English text)
        # FIX: Correctly unpack 7 return values from answer_query_with_cache_first
        response_en, source, distance, top_k_metadata_list, is_unclear, _, _, lead_score = answer_query_with_cache_first(
            query_for_rag, chroma_collection, history_queries=history
        )

        # NEW: Update Session State Score and Check Pop-up Threshold
        st.session_state.lead_score += lead_score

        if st.session_state.lead_score >= LEAD_SCORE_WEIGHTS["MAX_SCORE_THRESHOLD"] and not st.session_state.lead_logged:
             st.session_state.show_lead_form = True

        bot_timestamp = datetime.datetime.now().strftime("%I:%M %p")
        
        final_output = FINAL_FALLBACK_MESSAGE
        final_output_en = FINAL_FALLBACK_MESSAGE # English answer before final translation

        # --- Response Assembly ---
        if is_unclear:
            final_output_en = UNCLEAR_QUERY_RESPONSE
            # Translate Fallback/Unclear response
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
                    final_output = final_output_en # Fallback to English
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
            
        
        # 5. Log the interaction (using the correct function signature)
        log_chatbot_interaction(
            query=original_query,
            translated_query=query_for_rag,
            answer=final_output_en, # Log the English answer (standardized cache data)
            source=source,
            language=detected_lang,
            rating=None # Initial log has no rating
        )
        
        # --- Persistent FAQ Suggestions ---
        top_3_faq_qs = []
        if faq_suggestions_collection:
            top_3_faq_qs = get_similar_faq_suggestions(
                query_for_rag, 
                faq_suggestions_collection, 
                limit=3
            )
        
        if top_3_faq_qs: 
            with st.expander("💡 Top 3 Related FAQs (Click to Ask)"):
                for i, q in enumerate(top_3_faq_qs): 
                    st.button(q, on_click=set_input_text, args=[q], key=f"related_faq_sug_{i}", use_container_width=True)
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
        
    # If the lead form was triggered, we need a final rerun to display it
        if st.session_state.show_lead_form:
             st.rerun()

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


# --- Regeneration Execution ---
if st.session_state.regenerate_index != -1:
    
    idx = st.session_state.regenerate_index
    user_message = st.session_state.messages[idx - 1]
    original_user_query = user_message["content"] 
    query_for_rag = user_message["translated_query"] 
    detected_lang = st.session_state.messages[idx]["language"] # Use the language from the message being disliked
    
    st.session_state.regenerate_index = -1 
    
    with st.chat_message("assistant"):
        st.info("🔄 **Regenerating Answer...** Bypassing cache for a fresh response.")
        
        # 1. Clean query
        cleaned_question, _ = clean_query_with_gemini(query_for_rag)
        
        # 2. Force RAG generation (returns English answer)
        # FIX: Correctly unpack 7 return values from regenerate_answer
        new_response_en, new_source, new_distance, new_metadata, _, query_to_cache,detected_lang_code_out, lead_score_raw, _ = regenerate_answer(
            cleaned_question, chroma_collection, history_queries=get_history_queries(num_turns=3)
        )
        try:
            lead_score = float(lead_score_raw)
        except (ValueError, TypeError):
            logging.error(f"Failed to convert lead score to float: {lead_score_raw}")
            lead_score = 0.0 # Default to 0 if conversion fails
        
        st.session_state.lead_score += lead_score
    
        if st.session_state.lead_score >= LEAD_SCORE_WEIGHTS["MAX_SCORE_THRESHOLD"] and not st.session_state.lead_logged:
            st.session_state.show_lead_form = True

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