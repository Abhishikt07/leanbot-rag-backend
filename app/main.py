# app/main.py
"""
Leanext RAG FastAPI Backend

- Uses Day_19_B + Day_19_C for core RAG logic.
- Uses Day_19_F only as a helper for FAQ suggestions / pre-warming Chroma.
- NO import of Day_19_D (Streamlit), so Render will not require `streamlit`.
- Exposes:
    - GET  /               -> health check
    - POST /chat           -> main chat endpoint
    - OPTIONS /chat        -> preflight support for widget
    - GET  /debug/indexed  -> debug info (safe, won't crash if stats fail)
    - POST /feedback       -> stub for like/dislike
    - POST /regenerate     -> stub for "regenerate" button
"""

from fastapi import FastAPI, Body, Response
from fastapi.middleware.cors import CORSMiddleware
import threading
import time
import logging

# ---- Core RAG entrypoints (these ultimately use Day_19_C under the hood) ----
from app.Day_19_B import (
    search_leanext_kb,          # high-level RAG answer (string)
    search_leanext_kb_formatted # optional richer format (if you want later)
)

# ---- FAQ helpers (our new helper module F) ----
from app.Day_19_F import load_faq_suggestions

# ---- Optional analytics / index helpers (wrapped in try/except later) ----
from app.Day_19_E import get_index_stats, list_indexed_documents

# Basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------------------------------
# FastAPI app + CORS (for your frontend widget)
# ----------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # you can later restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# HEALTH CHECK FOR RENDER
# -----------------------------
@app.get("/")
async def health():
    return {"status": "ok", "message": "Leanbot RAG backend running"}

# ----------------------------------------------------
# BACKGROUND INITIALIZATION (NON-BLOCKING)
# ----------------------------------------------------
def background_startup():
    """
    Load / pre-warm things AFTER the server has started,
    so Render sees an open port quickly.
    """
    time.sleep(1)
    logger.info("⏳ Background initialization started...")

    try:
    

        # 2) Pre-warm FAQ suggestions from helper module F
        try:
            num_faqs = len(load_faq_suggestions())
            logger.info(f"[Init] FAQ suggestions cached: {num_faqs} items.")
        except Exception as faq_err:
            logger.warning(f"[Init] FAQ suggestions failed: {faq_err}")

    except Exception as e:
        logger.error(f"[Init] Background init error: {e}")


# Run heavy-ish startup in another thread (daemonized)
threading.Thread(target=background_startup, daemon=True).start()

# ----------------------------------------------------
# CHAT ENDPOINT (Core RAG call)
# ----------------------------------------------------
@app.post("/chat")
async def chat(payload: dict = Body(...)):
    """
    Main chat endpoint used by your website widget.
    Uses search_leanext_kb() which internally calls
    the RAG logic defined in Day_19_C.
    """
    query = (payload.get("query") or "").strip()

    if not query:
        return {
            "response": "Please ask a question related to Leanext's services or solutions."
        }

    try:
        # This is your existing high-level helper from Day_19_B.
        # It ultimately uses Day_19_C's RAG engine, so your core logic stays intact.
        answer = search_leanext_kb(query)
        return {
            "response": answer
        }
    except Exception as e:
        logger.error(f"/chat error: {e}")
        # Safe fallback if something goes wrong in the pipeline
        return {
            "response": "Sorry, I'm having trouble answering that right now. Please try again in a moment."
        }

# ----------------------------------------------------
# OPTIONS /chat (Fixes preflight 405 errors on browsers)
# ----------------------------------------------------
@app.options("/chat")
async def chat_options():
    return Response(status_code=200)

# ----------------------------------------------------
# DEBUG ENDPOINT (for widget debug panel)
# ----------------------------------------------------
@app.get("/debug/indexed")
async def debug_indexed():
    """
    Returns basic information about the index.

    We *wrap* Day_19_E helpers in try/except so if they
    change signature or fail, this endpoint still returns
    a valid JSON object and doesn't crash the service.
    """
    data = {
        "indexed_urls": [],
        "last_index_run": None,
        "total_chunks": None,
    }

    # Try to enrich with real stats if Day_19_E is compatible
    try:
        stats = get_index_stats()  # expected to return a dict
        if isinstance(stats, dict):
            data.update(stats)
    except Exception as e:
        logger.warning(f"get_index_stats() failed: {e}")

    try:
        docs = list_indexed_documents(limit=50)  # expected: list of dicts with 'url'
        urls = []
        if isinstance(docs, list):
            for d in docs:
                url = d.get("url") or d.get("canonical") or d.get("path")
                if url:
                    urls.append(url)
        data["indexed_urls"] = urls
    except Exception as e:
        logger.warning(f"list_indexed_documents() failed: {e}")

    return data

# ----------------------------------------------------
# FEEDBACK ENDPOINT (Stops /feedback 404 errors)
# ----------------------------------------------------
@app.post("/feedback")
async def collect_feedback(payload: dict = Body(...)):
    """
    Widget sends ratings/feedback here.
    Right now we just acknowledge; later you can connect
    this to Day_19_E.log_chatbot_interaction if you want.
    """
    # You can inspect payload here for debugging if needed:
    # logger.info(f"Feedback payload: {payload}")
    return {"status": "ok"}

# ----------------------------------------------------
# REGENERATE ENDPOINT (Widget support)
# ----------------------------------------------------
@app.post("/regenerate")
async def regenerate_answer(payload: dict = Body(...)):
    """
    Stub for the 'regenerate answer' button.
    For now this just returns a simple message so that
    the frontend doesn't get a 404.
    Later you can wire this to Day_19_C.regenerate_answer.
    """
    query = (payload.get("query") or "").strip()
    return {
        "answer": f"Regenerate endpoint working (stub). Last query: '{query}'",
        "metadata": {"regenerated": True}
    }
