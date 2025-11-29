from fastapi import FastAPI, Body, Response
from fastapi.middleware.cors import CORSMiddleware
import threading
import time
from app.Day_19_B import search_leanext_kb, search_leanext_kb_formatted
from app.Day_19_C import load_faq_suggestions, get_similar_faqs
from Day_19_D import llm_generate
from app.Day_19_E import get_index_stats, list_indexed_documents


app = FastAPI()

# ----------------------------------------------------
# CORS (Fixes Safari/Chrome OPTIONS preflight errors)
# ----------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Later restrict to your domain if needed
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
    """Load heavy models WITHOUT blocking FastAPI startup."""
    time.sleep(1)
    print("⏳ Background initialization started...")

    try:
        # Delay heavy imports until after server is already running
        from Day_19_C import load_faq_suggestions
        from Day_19_B import search_leanext_kb
        from Day_19_D import llm_generate

        print("Loading embedding model...")
        load_faq_suggestions()  # light + safe

        print("Embedding + FAQ index loaded.")

    except Exception as e:
        print("Background init error:", e)


# Run heavy startup in another thread (daemonized)
threading.Thread(target=background_startup, daemon=True).start()

# ----------------------------------------------------
# CHAT ENDPOINT (Core logic — UNCHANGED)
# ----------------------------------------------------
@app.post("/chat")
async def chat(payload: dict):
    query = payload.get("query", "")
    from Day_19_D import llm_generate
    return {"response": llm_generate(query)}

# ----------------------------------------------------
# OPTIONS /chat (Fixes preflight 405 errors)
# ----------------------------------------------------
@app.options("/chat")
async def chat_options():
    return Response(status_code=200)

# ----------------------------------------------------
# DEBUG ENDPOINT (Prevents /debug/indexed 404 errors)
# ----------------------------------------------------
@app.get("/debug/indexed")
async def debug_indexed():
    """
    Minimal stub so frontend debug panel works.
    You can integrate real Chroma stats later.
    """
    return {
        "indexed_urls": [],
        "last_index_run": None,
        "total_chunks": None
    }

# ----------------------------------------------------
# FEEDBACK ENDPOINT (Stops /feedback 404 errors)
# ----------------------------------------------------
@app.post("/feedback")
async def collect_feedback(payload: dict = Body(...)):
    """
    Widget sends ratings/feedback. 
    Logging not required yet.
    """
    return {"status": "ok"}

# ----------------------------------------------------
# REGENERATE ENDPOINT (Widget support)
# ----------------------------------------------------
@app.post("/regenerate")
async def regenerate_answer(payload: dict = Body(...)):
    """
    Stub for regenerate button.
    You can later connect it to your RAG pipeline.
    """
    return {
        "answer": "Regenerate endpoint working (stub).",
        "metadata": {"regenerated": True}
    }
