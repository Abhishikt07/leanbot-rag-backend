"""
RAG Engine Module: Contains all core business logic for processing a user query,
including cleaning, retrieval from ChromaDB, and generation via the Gemini API.
"""
import requests
import streamlit as st
import json
import time
import logging
from typing import Tuple, List, Dict, Any, Optional

# FIX: Update imports to Day_21_A
from Day_21_A import (
    GEMINI_API_KEY, API_URL, TOP_K_CHUNKS, AUTOCOMPLETE_K, QUERY_PREDICTION_THRESHOLD, 
    CLEANING_SYSTEM_PROMPT, FINAL_FALLBACK_MESSAGE, GEMINI_RAG_SYSTEM_PROMPT, 
    SMALL_TALK_TRIGGERS, UNCLEAR_QUERY_THRESHOLD, RELATED_QS_LIMIT, BASE_URL, FAQ_COLLECTION_NAME,
    LANGUAGE_FAIL_MESSAGE, DEFAULT_LANGUAGE, UNCLEAR_QUERY_RESPONSE, HIGH_INTENT_KEYWORDS, 
    MAX_CONVERSION_SCORE
)
# FIX: Update imports to Day_21_E
from Day_21_E import get_cached_answer, save_answer_to_cache
# NEW: Import the language middleware (using the new naming convention if available)
from language_middleware2 import LanguageTranslator

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global translator instance
language_translator = LanguageTranslator()

# Define the stable return shape for all core answer functions
RAG_RESPONSE_SHAPE = Tuple[
    str,                                 # answer_text (translated)
    str,                                 # source_docs (text tag)
    Optional[float],                     # distance_scores (best distance)
    List[Dict[str, Any]],                # top_k_metadata_list (list of metadata dicts)
    bool,                                # is_unclear (True/False)
    Optional[str],                       # llm_raw (Raw English LLM answer for caching/regen)
    str,                                 # detected_lang_code
    int                                  # conversion_score (new score)
]

def calculate_conversion_score(user_query: str, current_score: int) -> int:
    """
    Calculates the new conversion score based on the latest query.
    Score starts at 1, maxes out at MAX_CONVERSION_SCORE (5).
    """
    if not user_query:
        return current_score
        
    normalized_query = user_query.lower()
    
    # 1. Base score increase for any meaningful query
    # FIX: Only increase if the current score is lower than 2
    new_score = max(current_score, 2)
    
    # 2. Check for high-intent keywords (increases score by 2)
    for keyword in HIGH_INTENT_KEYWORDS:
        if keyword in normalized_query:
            new_score = min(new_score + 2, MAX_CONVERSION_SCORE)
            logging.info(f"High intent keyword '{keyword}' detected. New score: {new_score}")
            break # Stop after finding the first high-intent keyword

    # 3. Check for general intent keywords (increases score by 1)
    # If no high intent found, look for general intent (e.g., specific product names)
    if new_score < MAX_CONVERSION_SCORE:
        general_intent_words = ["leanmaster", "sixsigma", "software", "capabilities", "about"]
        if any(word in normalized_query for word in general_intent_words):
             new_score = min(new_score + 1, MAX_CONVERSION_SCORE)
    
    return min(new_score, MAX_CONVERSION_SCORE)

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
    if not GEMINI_API_KEY: 
        logging.warning("Gemini API Key missing for cleaning.")
        return raw_query, "[ERROR: API Key Missing for Cleaning]"
        
    payload = {"contents": [{ "parts": [{ "text": raw_query }] }], "systemInstruction": { "parts": [{ "text": CLEANING_SYSTEM_PROMPT }] }}
    
    try:
        response = requests.post(API_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload), timeout=10)
        response.raise_for_status() 
        result = response.json()
        candidates = result.get('candidates')
        if not candidates: 
            logging.warning(f"Gemini cleaning returned no candidates for query: {raw_query[:30]}...")
            return raw_query, "[WARNING: Gemini returned no candidates]"
            
        cleaned_text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', raw_query).strip()
        logging.info(f"Query cleaned. Before: '{raw_query[:20]}...', After: '{cleaned_text[:20]}...'")
        return cleaned_text, None
        
    except requests.exceptions.RequestException as e:
         logging.error(f"Query Cleaning Failed (Request Error): {e}")
         return raw_query, f"[ERROR: Query Cleaning Failed (Request): {e}]"
    except Exception as e:
         logging.error(f"Query Cleaning Failed (General Error): {e}")
         return raw_query, f"[ERROR: Query Cleaning Failed (General): {e}]"


def retrieve_context(query, collection, is_autocomplete=False, history_queries=""):
    """
    Retrieves the top K most relevant text chunks from ChromaDB using the *English* query.
    Returns combined_context, best_distance, and a list of top K metadata objects.
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
            # FIX: Ensure headings are parsed back from JSON string to list
            meta['headings'] = json.loads(meta.get('headings', '[]'))
        except json.JSONDecodeError:
            meta['headings'] = []
            
        top_k_results.append({'document': doc, 'metadata': meta, 'distance': dist})
        
    if is_autocomplete:
        # Autocomplete logic remains the same
        unique_snippets = set()
        for res in top_k_results:
            if res['distance'] < QUERY_PREDICTION_THRESHOLD:
                snippet = res['document'].strip().split('.')[0].strip()
                if len(snippet.split()) > 3 and not snippet.lower().startswith("source page"): 
                    suggestion = f"Tell me about {snippet}..."
                    unique_snippets.add(suggestion)
        return list(unique_snippets)[:5], 0.0, default_metadata_list 

    else:
        # RAG context assembly
        context_list = []
        # FIX: Also ensure the metadata list being returned is the cleaned one
        top_k_metadata_list = [] 
        for res in top_k_results:
            source = res['metadata'].get('path', 'Unknown')
            context_list.append(f"Source Page ({source}): {res['document']}")
            top_k_metadata_list.append(res['metadata']) # Collect the cleaned metadata
            
        combined_context = "\n\n---\n\n".join(context_list)
        best_distance = top_k_results[0]['distance']
        
        return combined_context, best_distance, top_k_metadata_list # FIX: Return the cleaned top_k_metadata_list

def get_similar_faq_suggestions(query, faq_collection, limit=3):
    """
    Finds the top 'limit' semantically similar questions from the dedicated 
    FAQ collection based on the user's *English* query.
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

def regenerate_answer(raw_query: str, chroma_collection, history_queries="") -> RAG_RESPONSE_SHAPE:
    """
    Bypasses the cache and Small Talk check to force a direct RAG generation.
    Returns: answer_text, source, distance, top_k_metadata_list, is_unclear, llm_raw, detected_lang_code, conversion_score
    """
    # FIX: Get current score from session state or pass it in. Since this is a utility func, we'll assume a dummy score of 3 
    # to maintain the required return shape, and let the caller manage the score.
    dummy_conversion_score = 3

    # 1. Translate Raw Query to English
    english_query, detected_lang_code = language_translator.to_english(raw_query)

    # Handle translation failure
    if detected_lang_code.startswith("ERROR"):
        error_lang = detected_lang_code.split('-')[1]
        return LANGUAGE_FAIL_MESSAGE, "Translation Error", 1.0, [], True, None, error_lang, dummy_conversion_score

    # 2. Clean English Query
    cleaned_english_question, _ = clean_query_with_gemini(english_query)
    
    # 3. Retrieve Context (using English query)
    # FIX: Corrected variable name top_k_metadata_list
    context, distance, top_k_metadata_list = retrieve_context(cleaned_english_question, chroma_collection, history_queries=history_queries)
    
    is_unclear = False
    final_english_answer = None # Raw LLM output
    
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
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Gemini API Regen Failed (Request): {e}")
            final_english_answer = FINAL_FALLBACK_MESSAGE
            source = "Gemini Error (Regen)"
        except Exception as e:
            logging.error(f"Gemini API Regen Failed (General): {e}")
            final_english_answer = FINAL_FALLBACK_MESSAGE
            source = "Gemini Error (Regen)"
            
    # 5. Translate English Answer back to User's Language
    # FIX: Only translate if the detected language is NOT the default English
    translated_answer = language_translator.from_english(final_english_answer, detected_lang_code) if detected_lang_code != DEFAULT_LANGUAGE else final_english_answer
    
    # 6. Prepare Cache Data (using English Q/A)
    # The caller (Day_21_D) will use the 'like' button's logic to execute the persistent cache update.
    llm_raw = final_english_answer 

    # Returns the 8-tuple required
    return (
        translated_answer, source, distance, top_k_metadata_list, 
        is_unclear, llm_raw, detected_lang_code, dummy_conversion_score
    )


def answer_query_with_cache_first(raw_query: str, chroma_collection, current_score: int, history_queries="") -> RAG_RESPONSE_SHAPE:
    """
    Implements the Multilingual Cache-First strategy.
    
    Returns: 
        answer_text, source, distance, top_k_metadata_list, is_unclear, llm_raw, detected_lang_code, new_conversion_score
    """
    
    # 1. Calculate New Conversion Score first
    new_conversion_score = calculate_conversion_score(raw_query, current_score)
    
    # 2. Translate Raw Query to English
    english_query, detected_lang_code = language_translator.to_english(raw_query)
    
    # Initialize RAG result variables
    distance = None
    top_k_metadata_list = []
    is_unclear = False
    final_english_answer = None
    
    # Handle translation failure
    if detected_lang_code.startswith("ERROR"):
        error_lang = detected_lang_code.split('-')[1]
        return LANGUAGE_FAIL_MESSAGE, "Translation Error", 1.0, [], True, None, error_lang, new_conversion_score

    # 3. Check English Small Talk
    smalltalk_response = check_small_talk(english_query)
    if smalltalk_response:
        # FIX: Translate small talk response to user's language
        translated_smalltalk = language_translator.from_english(smalltalk_response, detected_lang_code) if detected_lang_code != DEFAULT_LANGUAGE else smalltalk_response
        return translated_smalltalk, "Small Talk Response", None, [], False, smalltalk_response, detected_lang_code, new_conversion_score

    # 4. Check English Cache
    cached = get_cached_answer(english_query)
    if cached:
        english_answer, source_tag, matched_query = cached
        # FIX: Translate cached answer to user's language
        translated_answer = language_translator.from_english(english_answer, detected_lang_code) if detected_lang_code != DEFAULT_LANGUAGE else english_answer
        return translated_answer, f"Cache HIT (Matched: '{matched_query[:20]}...')", None, [], False, english_answer, detected_lang_code, new_conversion_score

    # 5. Clean English Query (Needed for RAG & Unclear check)
    cleaned_english_question, _ = clean_query_with_gemini(english_query)

    # 6. Retrieve Context (using cleaned English query)
    context, distance, top_k_metadata_list = retrieve_context(cleaned_english_question, chroma_collection, history_queries=history_queries)
    
    
    if distance is not None and distance > UNCLEAR_QUERY_THRESHOLD:
        is_unclear = True
        source = "Unclear Query"
        final_english_answer = UNCLEAR_QUERY_RESPONSE # Use the English response for the error tag
    else:
        # 7. Generate English Answer
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
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Gemini API Fetch Failed (Request): {e}")
            final_english_answer = FINAL_FALLBACK_MESSAGE
            source = "Gemini Error"
        except Exception as e:
            logging.error(f"Gemini API Fetch Failed (General): {e}")
            final_english_answer = FINAL_FALLBACK_MESSAGE
            source = "Gemini Error"
            
        # 8. Post-processing: Cache and Translate
        if not source.startswith("Gemini Error") and final_english_answer != FINAL_FALLBACK_MESSAGE:
            cache_source_tag = top_k_metadata_list[0].get('canonical', 'RAG') if top_k_metadata_list else 'RAG'
            # Cache the English Q/A
            save_answer_to_cache(cleaned_english_question, final_english_answer, cache_source_tag) 
        
    
    # 9. Final Answer Translation
    if final_english_answer:
        # If it's the unclear response or a valid RAG answer, attempt translation
        if detected_lang_code != DEFAULT_LANGUAGE:
            translated_answer = language_translator.from_english(final_english_answer, detected_lang_code)
        else:
            translated_answer = final_english_answer # Use English answer directly
    else:
        # This case handles when final_english_answer is None (only if is_unclear is true)
        translated_answer = language_translator.from_english(UNCLEAR_QUERY_RESPONSE, detected_lang_code)


    return (
        translated_answer, source, distance, top_k_metadata_list, 
        is_unclear, final_english_answer, detected_lang_code, new_conversion_score
    )