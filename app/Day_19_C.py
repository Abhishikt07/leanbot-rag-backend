"""
Day_19_C — Render-Safe RAG Engine
No Streamlit. No UI. Only backend logic.
"""

import json
import time
import logging
import requests

from .Day_19_A import (
    GEMINI_API_KEY,
    API_URL,
    TOP_K_CHUNKS,
    AUTOCOMPLETE_K,
    QUERY_PREDICTION_THRESHOLD,
    CLEANING_SYSTEM_PROMPT,
    FINAL_FALLBACK_MESSAGE,
    GEMINI_RAG_SYSTEM_PROMPT,
    SMALL_TALK_TRIGGERS,
    UNCLEAR_QUERY_THRESHOLD,
    RELATED_QS_LIMIT,
    BASE_URL,
    FAQ_COLLECTION_NAME,
    LANGUAGE_FAIL_MESSAGE,
    DEFAULT_LANGUAGE,
    UNCLEAR_QUERY_RESPONSE,
    LEAD_SCORE_WEIGHTS,
    LEAD_TRIGGER_KEYWORDS,
)

from .Day_19_E import get_cached_answer, save_answer_to_cache
from .language_middleware import LanguageTranslator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

translator = LanguageTranslator()


#################################################################
# Small Talk
#################################################################

def check_small_talk(query):
    query_l = query.lower()
    for trigger, reply in SMALL_TALK_TRIGGERS.items():
        if trigger in query_l:
            return reply
    return None


#################################################################
# Query Cleaning
#################################################################

def clean_query_with_gemini(raw_query):
    if not GEMINI_API_KEY:
        return raw_query, None

    payload = {
        "contents": [{"parts": [{"text": raw_query}]}],
        "systemInstruction": {"parts": [{"text": CLEANING_SYSTEM_PROMPT}]}
    }

    try:
        res = requests.post(API_URL, json=payload)
        res.raise_for_status()
        data = res.json()

        cleaned = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", raw_query)
        )
        return cleaned.strip(), None

    except Exception as e:
        logging.error(f"Cleaning failed: {e}")
        return raw_query, str(e)


#################################################################
# Retrieval
#################################################################

def retrieve_context(query, collection, history_queries=""):
    try:
        effective = f"{query} | {history_queries}" if history_queries else query

        res = collection.query(
            query_texts=[effective],
            n_results=TOP_K_CHUNKS,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        logging.error(f"RAG Retrieval failed: {e}")
        return None, 1.0, []

    if not res or not res["documents"] or not res["documents"][0]:
        return None, 1.0, []

    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    context_blocks = []
    top_meta = []

    for doc, meta, dist in zip(docs, metas, dists):
        try:
            meta["headings"] = json.loads(meta.get("headings", "[]"))
        except:
            meta["headings"] = []

        context_blocks.append(f"Source ({meta.get('path','unknown')}): {doc}")
        top_meta.append(meta)

    combined = "\n\n---\n\n".join(context_blocks)
    return combined, dists[0], top_meta


#################################################################
# Lead Scoring
#################################################################

def calculate_lead_score(query, history, distance):
    score = 0.0
    w = LEAD_SCORE_WEIGHTS

    if distance is not None and distance < w["distance_threshold"]:
        score += w["low_distance_score"]

    turns = len(history.split("|")) if history else 0
    score += min(turns, 3) * w["history_turn_score"]

    lower_q = query.lower()
    for kw in LEAD_TRIGGER_KEYWORDS:
        if kw in lower_q:
            score += w["keyword_score_trigger"]
            break

    return score


#################################################################
# Main RAG Function
#################################################################

def answer_query_with_cache_first(raw_query, collection, history_queries=""):
    english, detected_lang = translator.to_english(raw_query)

    if detected_lang.startswith("ERROR"):
        return LANGUAGE_FAIL_MESSAGE, "Translation Error", 1.0, [], True, None, detected_lang, 0.0

    # small talk
    st = check_small_talk(english)
    if st:
        return translator.from_english(st, detected_lang), "Small Talk", None, [], False, None, detected_lang, 0.0

    # cache
    cached = get_cached_answer(english)
    if cached:
        answer_en, source_tag, matched = cached
        return translator.from_english(answer_en, detected_lang), f"Cache HIT", None, [], False, None, detected_lang, 0.0

    # clean
    cleaned, _ = clean_query_with_gemini(english)

    # retrieve context
    context, distance, topk = retrieve_context(cleaned, collection, history_queries)

    score = calculate_lead_score(cleaned, history_queries, distance)

    # unclear
    if distance > UNCLEAR_QUERY_THRESHOLD:
        unclear = translator.from_english(UNCLEAR_QUERY_RESPONSE, detected_lang)
        return unclear, "Unclear Query", distance, topk, True, None, detected_lang, score

    # generate with Gemini
    prompt = f"CONTEXT:\n{context}\n\nUSER QUESTION: {cleaned}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": GEMINI_RAG_SYSTEM_PROMPT}]}
    }

    try:
        res = requests.post(API_URL, json=payload)
        res.raise_for_status()
        data = res.json()
        answer_en = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", FINAL_FALLBACK_MESSAGE)
        )
    except Exception:
        answer_en = FINAL_FALLBACK_MESSAGE

    # save to cache
    if answer_en != FINAL_FALLBACK_MESSAGE:
        src = topk[0].get("canonical", "RAG") if topk else "RAG"
        save_answer_to_cache(cleaned, answer_en, src)

    translated = translator.from_english(answer_en, detected_lang)

    return translated, "Gemini API", distance, topk, False, None, detected_lang, score
