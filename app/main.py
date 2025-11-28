###############################################################
# FINAL main.py (Render-Optimized + Lazy Loading)
###############################################################

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb
import os

###############################################################
# Basic Config Imports Only (Safe)
###############################################################

from .Day_19_A import (
    CHROMA_DB_PATH,
    COLLECTION_NAME,
    FAQ_COLLECTION_NAME,
)

###############################################################
# DO NOT IMPORT Day_19_B / Day_19_C / Day_19_E HERE
# They load HUGE modules → block Uvicorn → Render fails
# We import them lazily inside startup_event
###############################################################

app = FastAPI()
@app.get("/")
def root():
    return {"status": "ok", "message": "Leanext RAG backend is running"}


# CORS for widget frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

###############################################################
# MODELS
###############################################################

class ChatRequest(BaseModel):
    query: str
    history: list = []


class ChatResponse(BaseModel):
    answer: str
    source: str
    distance: float
    language: str


###############################################################
# GLOBAL VARIABLES (Loaded at Startup)
###############################################################

chroma_collection = None
faq_suggestions_collection = None
rag_answer_fn = None
translator = None


###############################################################
# LAZY IMPORTER
###############################################################

def lazy_import_rag_modules():
    """
    Imports heavy modules ONLY after the server has bound to the port.
    This prevents Render from timing out.
    """
    from .Day_19_B import load_or_build_knowledge_base
    from .Day_19_C import answer_query_with_cache_first
    from .Day_19_E import log_chatbot_interaction
    from .language_middleware import LanguageTranslator

    return load_or_build_knowledge_base, answer_query_with_cache_first, log_chatbot_interaction, LanguageTranslator


###############################################################
# STARTUP EVENT — loads heavy RAG engine after Uvicorn binds port
###############################################################

@app.on_event("startup")
async def startup_event():
    global chroma_collection, faq_suggestions_collection, rag_answer_fn, translator

    print("🔄 Startup: Importing RAG modules...")
    (load_or_build_knowledge_base,
     answer_query_with_cache_first,
     log_chatbot_interaction,
     LanguageTranslator) = lazy_import_rag_modules()

    print("🔄 Startup: Loading Knowledge Base...")
    chroma_collection = load_or_build_knowledge_base()

    print("🔄 Startup: Loading FAQ Collection...")
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    faq_suggestions_collection = client.get_collection(name=FAQ_COLLECTION_NAME)

    rag_answer_fn = answer_query_with_cache_first
    translator = LanguageTranslator()

    print("✅ Backend Startup Complete — Ready to serve requests")


###############################################################
# HEALTH ROUTES
###############################################################

@app.get("/")
async def root():
    return {"status": "Leanext RAG Backend Running"}


###############################################################
# MAIN CHAT ENDPOINT
###############################################################

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    global rag_answer_fn, chroma_collection

    if rag_answer_fn is None:
        return ChatResponse(
            answer="Server warming up — please retry in a moment.",
            source="Backend Loading",
            distance=1.0,
            language="en"
        )

    # Convert last 3 messages into context string
    history_text = " | ".join(req.history[-3:])

    # Call RAG Engine
    answer, source, distance, _, _, _, detected_lang, _ = rag_answer_fn(
        req.query,
        chroma_collection,
        history_queries=history_text
    )

    return ChatResponse(
        answer=answer,
        source=source,
        distance=distance or 0.0,
        language=detected_lang
    )
