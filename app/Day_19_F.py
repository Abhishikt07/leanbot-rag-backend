"""
Day_19_F.py
FAQ Suggestion Helper Module
------------------------------------------
Reads FAQ entries from existing ChromaDB.
Does NOT re-embed or rebuild anything.

Functions:
- load_faq_suggestions()    → Prewarm + cache all FAQ docs
- get_similar_faqs()        → Return top-k similar FAQs
- get_faq_collection()      → Return the dedicated FAQ collection

Used by main.py for:
- startup warm
- top-3 related FAQ suggestions after chatbot answer
"""

from typing import Any, Dict, List, Optional
from chromadb.api.models.Collection import Collection

# Import the correct chroma client from Day_19_B
from app.Day_19_B import get_chroma_client


# internal module-level caches
_faq_collection: Optional[Collection] = None
_cached_faq_docs: Optional[List[Dict[str, Any]]] = None


# ------------------------------------------------------
# 1. Locate FAQ Collection
# ------------------------------------------------------

def _pick_faq_collection() -> Optional[Collection]:
    """
    Select the FAQ collection. 
    Heuristic:
       Prefer collection whose name contains 'faq' (case-insensitive).
    """
    client = get_chroma_client()
    collections = client.list_collections()

    for col in collections:
        if "faq" in col.name.lower():
            print(f"[Day_19_F] Using FAQ collection: {col.name}")
            return col

    print("[Day_19_F] No FAQ collection found.")
    return None


def get_faq_collection() -> Optional[Collection]:
    """
    Cached getter for the FAQ collection.
    """
    global _faq_collection
    if _faq_collection is None:
        _faq_collection = _pick_faq_collection()
    return _faq_collection


# ------------------------------------------------------
# 2. Load & Cache all FAQ documents
# ------------------------------------------------------

def load_faq_suggestions(max_items: int = 100) -> List[Dict[str, Any]]:
    """
    Load and cache FAQ entries from the collection.

    Output Format:
    [
       {
           "id": "123",
           "question": "What is Leanext?",
           "metadata": { ... }
       },
       ...
    ]
    """
    global _cached_faq_docs

    faq_col = get_faq_collection()
    if faq_col is None:
        _cached_faq_docs = []
        print("[Day_19_F] FAQ suggestions disabled (no FAQ collection).")
        return _cached_faq_docs

    # Safe initial bulk fetch from Chroma
    data = faq_col.get(include=["documents", "metadatas", "ids"])

    ids = data.get("ids", []) or []
    docs = data.get("documents", []) or []
    metas = data.get("metadatas", []) or []

    faq_items = []
    for _id, doc, meta in zip(ids, docs, metas):
        faq_items.append({
            "id": _id,
            "question": doc,
            "metadata": meta or {}
        })

    # Only keep top max_items entries
    _cached_faq_docs = faq_items[:max_items]

    print(f"[Day_19_F] Cached {len(_cached_faq_docs)} FAQ items.")
    return _cached_faq_docs


# ------------------------------------------------------
# 3. Query top-k similar FAQ questions
# ------------------------------------------------------

def get_similar_faqs(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Given a query, return top-k similar FAQ entries from the FAQ collection.

    Output Format:
    [
      {
         "id": "...",
         "question": "...",
         "score": <float>,
         "metadata": {...}
      }
    ]
    """
    faq_col = get_faq_collection()
    if faq_col is None:
        return []

    if not query or not query.strip():
        # fallback: return cached FAQs
        global _cached_faq_docs
        if _cached_faq_docs is None:
            load_faq_suggestions()
        return (_cached_faq_docs or [])[:top_k]

    res = faq_col.query(
        query_texts=[query],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    ids = res.get("ids", [[]])[0] or []
    docs = res.get("documents", [[]])[0] or []
    metas = res.get("metadatas", [[]])[0] or []
    dists = res.get("distances", [[]])[0] or []

    out = []
    for _id, doc, meta, dist in zip(ids, docs, metas, dists):
        out.append({
            "id": _id,
            "question": doc,
            "score": float(dist) if dist is not None else None,
            "metadata": meta or {}
        })

    return out
