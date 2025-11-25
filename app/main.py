from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import os

# Import your backend modules
from .Day_19_A import (
    BASE_URL, SUGGESTED_FAQS, UNCLEAR_QUERY_RESPONSE, FAQ_SEED_QUESTIONS,
    FINAL_FALLBACK_MESSAGE, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES,
    LANGUAGE_FAIL_MESSAGE, LEAD_SCORE_WEIGHTS, LEAD_TRIGGER_KEYWORDS
)

from .Day_19_B import load_or_build_knowledge_base, build_and_index_faq_suggestions
from .Day_19_C import (
    clean_query_with_gemini, answer_query_with_cache_first, retrieve_context,
    get_similar_faq_suggestions, match_landing_page, regenerate_answer,
    calculate_lead_score
)

from .Day_19_E import (
    log_chatbot_interaction, update_cached_answer, get_all_indexed_urls,
    log_lead_data
)

from .language_middleware import LanguageTranslator


# -----------------------------
# FASTAPI APP INITIALIZATION
# -----------------------------
app = FastAPI(title="Leanext RAG Chatbot Backend", version="1.0")

# CORS (allow all domains because widget can be placed anywhere)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # You may restrict later to company domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# STATIC FILES MOUNT (OPTION A)
# -----------------------------
# Serve your widget from /frontend/*
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


# -----------------------------
# LOAD RAG COMPONENTS
# -----------------------------
chroma_collection = load_or_build_knowledge_base()
faq_suggestions_collection = build_and_index_faq_suggestions()

translator = LanguageTranslator()


# -----------------------------
# REQUEST MODELS
# -----------------------------
class ChatRequest(BaseModel):
    query: str
    history: Optional[List[str]] = []


class FeedbackRequest(BaseModel):
    query: str
    translated_query: str
    answer: str
    source: str
    language: str
    rating: int


class LeadRequest(BaseModel):
    name: str
    number: Optional[str] = None
    email: Optional[str] = None
    demo_type: Optional[str] = "General Inquiry"
    org: Optional[str] = None


# -----------------------------
# CHAT ENDPOINT
# -----------------------------
@app.post("/chat")
async def chat_endpoint(payload: ChatRequest):
    original_query = payload.query
    history = payload.history or []

    # 1. Translation to English
    try:
        translated_query, detected_lang = translator.to_english(original_query)
    except:
        translated_query = original_query
        detected_lang = DEFAULT_LANGUAGE

    # 2. Run RAG
    response_en, source, distance, metadata_list, is_unclear, _, _, lead_score = answer_query_with_cache_first(
        translated_query,
        chroma_collection,
        history_queries=" | ".join(history[-3:])
    )

    if is_unclear:
        final_en = UNCLEAR_QUERY_RESPONSE
    else:
        final_en = response_en

    # 3. Translate back to user's language
    try:
        final_out = translator.from_english(final_en, detected_lang)
    except:
        final_out = final_en

    # 4. Matched landing page
    page = None
    if source.startswith("Gemini API"):
        page = match_landing_page(translated_query, metadata_list)

    # 5. Log interaction
    log_chatbot_interaction(
        query=original_query,
        translated_query=translated_query,
        answer=final_en,
        source=source,
        language=detected_lang,
        rating=None
    )

    return {
        "answer": final_out,
        "source": source,
        "distance": distance,
        "detected_lang": detected_lang,
        "lead_score": lead_score,
        "related_page": page
    }


# -----------------------------
# REGENERATE ENDPOINT
# -----------------------------
@app.post("/regenerate")
async def regenerate_endpoint(payload: ChatRequest):
    cleaned, _ = clean_query_with_gemini(payload.query)
    history = payload.history or []

    new_en, src, dist, metadata_list, _, cache_tuple, lead_raw, _ = regenerate_answer(
        cleaned,
        chroma_collection,
        history_queries=" | ".join(history[-3:])
    )

    try:
        final = translator.from_english(new_en, DEFAULT_LANGUAGE)
    except:
        final = new_en

    return {
        "answer": final,
        "source": src,
        "distance": dist,
        "detected_lang": DEFAULT_LANGUAGE,
        "lead_score": lead_raw,
        "related_page": None
    }


# -----------------------------
# FEEDBACK ENDPOINT
# -----------------------------
@app.post("/feedback")
async def feedback_endpoint(payload: FeedbackRequest):
    log_chatbot_interaction(
        payload.query,
        payload.translated_query,
        payload.answer,
        payload.source,
        payload.language,
        payload.rating,
    )
    return {"message": "Feedback logged"}


# -----------------------------
# LEAD CAPTURE
# -----------------------------
@app.post("/lead")
async def lead_endpoint(payload: LeadRequest):
    ok = log_lead_data(
        payload.name,
        payload.number,
        payload.email,
        payload.demo_type,
        payload.org,
    )
    return {"success": ok}


# -----------------------------
# DEBUG: INDEXED URLS
# -----------------------------
@app.get("/debug/indexed")
async def debug_indexed():
    urls = get_all_indexed_urls(chroma_collection)
    return {"urls": urls}


# -----------------------------
# ROOT (OPTIONAL)
# -----------------------------
@app.get("/")
async def root():
    return {"message": "Leanext Chatbot Backend Running"}


# -----------------------------
# LOCAL DEV
# -----------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
