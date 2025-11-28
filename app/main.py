from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import threading
import time

app = FastAPI()

# -----------------------------
# QUICK ROOT ROUTE FOR RENDER
# -----------------------------
@app.get("/")
async def health():
    return {"status": "ok", "message": "Leanbot RAG backend running"}

# -----------------------------------------
# BACKGROUND INITIALIZATION (NON-BLOCKING)
# -----------------------------------------
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
        load_faq_suggestions()  # safe + fast

        print("Embedding + FAQ index loaded.")

    except Exception as e:
        print("Background init error:", e)


# Run heavy startup in another thread
threading.Thread(target=background_startup, daemon=True).start()

# -------------------------------------
# YOUR ORIGINAL ENDPOINTS BELOW
# -------------------------------------
@app.post("/chat")
async def chat(payload: dict):
    query = payload.get("query", "")
    from Day_19_D import llm_generate
    return {"response": llm_generate(query)}

