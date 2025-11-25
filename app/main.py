from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb

# --- Internal Imports ---
from .Day_19_A import (
    CHROMA_DB_PATH,
    COLLECTION_NAME,
    FAQ_COLLECTION_NAME
)

from .Day_19_B import load_or_build_knowledge_base
from .Day_19_C import answer_query_with_cache_first
from .Day_19_E import log_chatbot_interaction

from .language_middleware import LanguageTranslator


# --------------------------
# FastAPI App
# --------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

translator = LanguageTranslator()

# --------------------------
# Load Knowledge Base on Startup
# --------------------------
print("🔄 Loading Knowledge Base...")
chroma_collection = load_or_build_knowledge_base()

print("🔄 Loading FAQ Suggestions Collection...")
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
faq_suggestions_collection = client.get_collection(name=FAQ_COLLECTION_NAME)


# --------------------------
# Request/Response Models
# --------------------------
class ChatRequest(BaseModel):
    query: str
    history: list = []
    user_lang: str | None = None


class ChatResponse(BaseModel):
    answer: str
    source: str
    distance: float
    language: str


# --------------------------
# Chat Endpoint
# --------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):

    # Convert history into a single string for RAG
    history_text = " | ".join(req.history[-3:])  

    # Run RAG pipeline (English inside)
    answer, source, distance, _, _, _, detected_lang, lead_score = answer_query_with_cache_first(
        req.query, chroma_collection, history_queries=history_text
    )

    # Format response
    return ChatResponse(
        answer=answer,
        source=source,
        distance=distance or 0.0,
        language=detected_lang
    )


@app.get("/")
async def root():
    return {"status": "Leanext RAG Chatbot Backend is Running"}
