"""
RAG Engine Module: Contains all core business logic for processing a user query,
including cleaning, retrieval from ChromaDB, and generation via the Gemini API.
"""
import requests
import streamlit as st
import json
import time
import logging
# FIX: Update imports to Day_18_A
from Day_19_A import (
    GEMINI_API_KEY, API_URL, TOP_K_CHUNKS, AUTOCOMPLETE_K, QUERY_PREDICTION_THRESHOLD, 
    CLEANING_SYSTEM_PROMPT, FINAL_FALLBACK_MESSAGE, GEMINI_RAG_SYSTEM_PROMPT, 
    SMALL_TALK_TRIGGERS, UNCLEAR_QUERY_THRESHOLD, RELATED_QS_LIMIT, BASE_URL, FAQ_COLLECTION_NAME,
    LANGUAGE_FAIL_MESSAGE, DEFAULT_LANGUAGE, UNCLEAR_QUERY_RESPONSE, LEAD_SCORE_WEIGHTS, LEAD_TRIGGER_KEYWORDS
)
# FIX: Update imports to Day_18_E
from Day_19_E import get_cached_answer, save_answer_to_cache
# NEW: Import the language middleware
from language_middleware import LanguageTranslator

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global translator instance
language_translator = LanguageTranslator()


def check_small_talk(query):
    """Checks if the *English* query is a basic small talk phrase."""
    normalized_query = query.lower()
    for key, response in SMALL_TALK_TRIGGERS.items():
        if key in normalized_query:
            return response
    return None

def clean_query_with_gemini(raw_query):
    """Stage 0: Uses Gemini to correct spelling and grammar (NLP Enhancement)."""
    # Note: This is called after translation to English, so it cleans the English query.
    if not GEMINI_API_KEY: return raw_query, "[ERROR: API Key Missing for Cleaning]"
    payload = {"contents": [{ "parts": [{ "text": raw_query }] }], "systemInstruction": { "parts": [{ "text": CLEANING_SYSTEM_PROMPT }] }}
    try:
        response = requests.post(API_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload), timeout=10)
        response.raise_for_status() 
        result = response.json()
        candidates = result.get('candidates')
        if not candidates: return raw_query, "[WARNING: Gemini returned no candidates]"
        cleaned_text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', raw_query).strip()
        return cleaned_text, None
    except Exception as e:
         logging.error(f"Query Cleaning Failed: {e}")
         return raw_query, f"[ERROR: Query Cleaning Failed: {e}]"


def retrieve_context(query, collection, is_autocomplete=False, history_queries=""):
    """
    Retrieves the top K most relevant text chunks from ChromaDB using the *English* query.
    Returns combined_context, best_distance, and a list of top K metadata objects.
    (Implementation remains the same as it handles English queries only)
    """
    n_results = AUTOCOMPLETE_K if is_autocomplete else TOP_K_CHUNKS
    effective_query = f"{query} | Previous Context: {history_queries}" if history_queries else query
    
    default_metadata_list = []
    
    try:
        results = collection.query(
            query_texts=[effective_query], n_results=n_results, include=['documents', 'metadatas', 'distances']
        )
    except Exception as e:
        logging.error(f"ChromaDB Retrieval Error: {e}")
        return None, 1.0, default_metadata_list 

    if not results or not results['documents'] or not results['documents'][0]:
        return None, 1.0, default_metadata_list
        
    top_k_results = []
    
    for doc, meta, dist in zip(results['documents'][0], results['metadatas'][0], results['distances'][0]):
        try:
            meta['headings'] = json.loads(meta.get('headings', '[]'))
        except json.JSONDecodeError:
            meta['headings'] = []
            
        top_k_results.append({'document': doc, 'metadata': meta, 'distance': dist})
        
    if is_autocomplete:
        unique_snippets = set()
        for res in top_k_results:
            if res['distance'] < QUERY_PREDICTION_THRESHOLD:
                snippet = res['document'].strip().split('.')[0].strip()
                if len(snippet.split()) > 3 and not snippet.lower().startswith("source page"): 
                    suggestion = f"Tell me about {snippet}..."
                    unique_snippets.add(suggestion)
        return list(unique_snippets)[:5], 0.0, default_metadata_list 

    else:
        context_list = []
        for res in top_k_results:
            source = res['metadata'].get('path', 'Unknown')
            context_list.append(f"Source Page ({source}): {res['document']}")
            
        combined_context = "\n\n---\n\n".join(context_list)
        best_distance = top_k_results[0]['distance']
        
        return combined_context, best_distance, [res['metadata'] for res in top_k_results]

def get_similar_faq_suggestions(query, faq_collection, limit=3):
    """
    Finds the top 'limit' semantically similar questions from the dedicated 
    FAQ collection based on the user's *English* query.
    (Implementation remains the same as it handles English queries only)
    """
    if faq_collection is None:
         logging.warning("FAQ Collection not loaded. Cannot fetch suggestions.")
         return []
         
    try:
        # Perform similarity search against the FAQ index
        results = faq_collection.query(
            query_texts=[query], 
            n_results=limit, 
            include=['metadatas']
        )
        
        suggested_questions = []
        if results and results.get('metadatas') and results['metadatas'][0]:
            # Extract the 'question' field from the metadatas
            for meta in results['metadatas'][0]:
                if 'question' in meta:
                    suggested_questions.append(meta['question'])
            
        return suggested_questions
        
    except Exception as e:
        logging.error(f"Failed to generate FAQ suggestions from dedicated index: {e}")
        return []

def match_landing_page(query, context_metadatas):
    """Heuristically selects the best landing page URL from the context."""
    if not context_metadatas:
        return None
        
    best_match_meta = context_metadatas[0]
    url_to_use = best_match_meta.get('canonical') or best_match_meta.get('url')
    
    if url_to_use and BASE_URL in url_to_use:
        return {'url': url_to_use, 'title': best_match_meta.get('title', 'Related Page')}
        
    return None


# NEW FUNCTION: Calculate Lead Score
def calculate_lead_score(query: str, history_queries: str, distance: float) -> float:
    """Calculates a score based on query depth, RAG relevance, and keyword hits."""
    score = 0.0
    weights = LEAD_SCORE_WEIGHTS
    
    # 1. Relevance Score (based on best RAG distance)
    if distance is not None and distance < weights["distance_threshold"]:
        score += weights["low_distance_score"]
        
    # 2. History Depth Score (Max 3 turns)
    turn_count = len(history_queries.split('|')) if history_queries.strip() else 0
    score += min(turn_count, 3) * weights["history_turn_score"]
    
    # 3. Keyword Trigger Score (Highest weight)
    # Check current query for high-intent keywords
    lower_query = query.lower()
    for keyword in LEAD_TRIGGER_KEYWORDS:
        if keyword in lower_query:
            score += weights["keyword_score_trigger"]
            break # Triggered, no need to check others

    return score

def regenerate_answer(raw_query: str, chroma_collection, history_queries=""):
    """
    Bypasses the cache and Small Talk check to force a direct RAG generation.
    Returns: translated_answer, source, distance, top_k_metadata_list, is_unclear, query_to_cache (tuple), detected_lang_code
    """
    # 1. Translate Raw Query to English
    english_query, detected_lang_code = language_translator.to_english(raw_query)

    # Handle translation failure
    if detected_lang_code.startswith("ERROR"):
        return LANGUAGE_FAIL_MESSAGE, "Translation Error", 1.0, [], True, None, detected_lang_code.split('-')[1],0.0

    # 2. Clean English Query
    cleaned_english_question, _ = clean_query_with_gemini(english_query)
    
    # 3. Retrieve Context (using English query)
    context, distance, top_k_metadata_list = retrieve_context(cleaned_english_question, chroma_collection, history_queries=history_queries)

    # NEW: Calculate Lead Score for the regeneration turn
    lead_score = calculate_lead_score(cleaned_english_question, history_queries, distance)

    is_unclear = False
    if distance is None or distance > UNCLEAR_QUERY_THRESHOLD:
        is_unclear = True
        final_english_answer = FINAL_FALLBACK_MESSAGE
        source = "Regen Failed (Unclear)"
    else:
        # 4. Generate English Answer
        user_prompt = f"CONTEXT:\n---\n{context or 'Use company knowledge'}\n---\n\nUSER QUESTION: {cleaned_english_question}"
        payload = {
            "contents": [{ "parts": [{ "text": user_prompt }] }],
            "systemInstruction": { "parts": [{ "text": GEMINI_RAG_SYSTEM_PROMPT }] },
        }

        try:
            start = time.time()
            response = requests.post(API_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload), timeout=30)
            response.raise_for_status()
            result = response.json()
            
            final_english_answer = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', FINAL_FALLBACK_MESSAGE).strip()
            source = f"Gemini API (Regenerated: {time.time()-start:.1f}s)"
            
        except Exception:
            final_english_answer = FINAL_FALLBACK_MESSAGE
            source = "Gemini Error (Regen)"
            
    # 5. Translate English Answer back to User's Language
    translated_answer = language_translator.from_english(final_english_answer, detected_lang_code)

    # 6. Prepare Cache Data (using English Q/A)
    query_to_cache = None
    if not is_unclear and not source.startswith("Gemini Error"):
        # Store the cleaned English Q/A for the RAG cache
        cache_source_tag = top_k_metadata_list[0].get('canonical', 'RAG-Regen') if top_k_metadata_list else 'RAG-Regen'
        query_to_cache = (cleaned_english_question, final_english_answer, cache_source_tag) 

    # Returns the 7-tuple needed by Day_18_D.py's regeneration loop
    return translated_answer, source, distance, top_k_metadata_list, is_unclear, query_to_cache, detected_lang_code,lead_score

def answer_query_with_cache_first(raw_query: str, chroma_collection, history_queries=""):
    """
    Implements the Multilingual Cache-First strategy.
    Returns: translated_answer, source, distance, top_k_metadata_list, is_unclear, query_to_cache (always None here), detected_lang_code
    """
    
    # 1. Translate Raw Query to English
    english_query, detected_lang_code = language_translator.to_english(raw_query)
    
    # Handle translation failure
    if detected_lang_code.startswith("ERROR"):
        return LANGUAGE_FAIL_MESSAGE, "Translation Error", 1.0, [], True, None, detected_lang_code.split('-')[1], 0.0

    # 2. Check English Small Talk
    smalltalk_response = check_small_talk(english_query)
    if smalltalk_response:
        # Translate small talk response back to user's language
        translated_smalltalk = language_translator.from_english(smalltalk_response, detected_lang_code)
        return translated_smalltalk, "Small Talk Response", None, [], False, None, detected_lang_code, 0.0

    # 3. Check English Cache
    cached = get_cached_answer(english_query)
    if cached:
        english_answer, source_tag, matched_query = cached
        # Translate cached English answer back
        translated_answer = language_translator.from_english(english_answer, detected_lang_code)
        return translated_answer, f"Cache HIT (Matched: '{matched_query[:20]}...')", None, [], False, None, detected_lang_code, 0.0

    # 4. Clean English Query (Needed for RAG & Unclear check)
    cleaned_english_question, _ = clean_query_with_gemini(english_query)

    # 5. Retrieve Context (using cleaned English query)
    context, distance, top_k_metadata_list = retrieve_context(cleaned_english_question, chroma_collection, history_queries=history_queries)
    
    # NEW: Calculate Lead Score before proceeding with RAG/Unclear logic
    lead_score = calculate_lead_score(cleaned_english_question, history_queries, distance)

    is_unclear = False
    if distance is not None and distance > UNCLEAR_QUERY_THRESHOLD:
        is_unclear = True
        # If unclear, return None as English answer, let the app handle the "Did you mean..." suggestion
        final_english_answer = None 
        source = "Unclear Query"
        # FIX: Added lead_score variable
        return unclear_response_in_lang, source, distance, top_k_metadata_list, is_unclear, None, detected_lang_code, lead_score
    else:
        # 6. Generate English Answer
        # FIX: Remove the redundant line: if context is None: distance = 1.0
        
        user_prompt = f"CONTEXT:\n---\n{context or 'Use company knowledge'}\n---\n\nUSER QUESTION: {cleaned_english_question}"
        payload = {
            "contents": [{ "parts": [{ "text": user_prompt }] }],
            "systemInstruction": { "parts": [{ "text": GEMINI_RAG_SYSTEM_PROMPT }] },
        }

        try:
            start = time.time()
            response = requests.post(API_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload), timeout=30)
            response.raise_for_status()
            result = response.json()
            
            final_english_answer = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', FINAL_FALLBACK_MESSAGE).strip()
            source = f"Gemini API (Fetch: {time.time()-start:.1f}s)"
            
        except Exception:
            final_english_answer = FINAL_FALLBACK_MESSAGE
            source = "Gemini Error"
            
        # 7. Post-processing: Cache and Translate
        if not source.startswith("Gemini Error") and final_english_answer != FINAL_FALLBACK_MESSAGE:
            cache_source_tag = top_k_metadata_list[0].get('canonical', 'RAG') if top_k_metadata_list else 'RAG'
            # Saves the cleaned English Q/A to the cache immediately on a fresh RAG hit
            save_answer_to_cache(cleaned_english_question, final_english_answer, cache_source_tag) 
            
        # Translate to user's language only if an answer was generated
        if final_english_answer:
            translated_answer = language_translator.from_english(final_english_answer, detected_lang_code)
        else:
            translated_answer = FINAL_FALLBACK_MESSAGE # Should only happen if final_english_answer is None
    
    # Handle the 'Unclear' case: no answer is generated, only context/distance is returned
    if is_unclear:
        # For an unclear query, we return a generic response in the detected language
        unclear_response_in_lang = language_translator.from_english(UNCLEAR_QUERY_RESPONSE, detected_lang_code)
        return unclear_response_in_lang, source, distance, top_k_metadata_list, is_unclear, None, detected_lang_code,lead_score
        
    # Final successful RAG/Cache path
    return translated_answer, source, distance, top_k_metadata_list, is_unclear, None, detected_lang_code,lead_score