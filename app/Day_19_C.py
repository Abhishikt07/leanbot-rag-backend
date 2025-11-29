# app/Day_19_C.py
"""
FAQ suggestion helpers.

We *only* read from the existing Chroma DB at app/chroma_db_leanext.
We do NOT rebuild or re-embed anything here.

Two main entry points:
- load_faq_suggestions()          -> prewarm + cache
- get_similar_faqs(query, top_k)  -> return suggested FAQ questions
"""

from typing import Any, Dict, List, Optional

from chromadb.api.models.Collection import Collection

from app.Day_19_B import get_chroma_client


_faq_collection: Optional[Collection] = None
_cached_faq_docs: Optional[List[Dict[str, Any]]] = None


# -------------------------------------------------------------------
# 1. Collection selection
# -------------------------------------------------------------------

def _pick_faq_collection() -> Optional[Collection]:
    """
    Try to find a dedicated FAQ collection.

    Heuristic:
      - Prefer collection with 'faq' in the name (case-insensitive).
      - Otherwise: return None (no FAQ collection).
    """
    client = get_chroma_client()
    collections = client.list_collections()

    for col in collections:
        if "faq" in col.name.lower():
            print(f"[Day_19_C] Using FAQ collection: {col.name}")
            return col

    print("[Day_19_C] No FAQ collection found (name containing 'faq').")
    return None


def get_faq_collection() -> Optional[Collection]:
    global _faq_collection
    if _faq_collection is None:
        _faq_collection = _pick_faq_collection()
    return _faq_collection


# -------------------------------------------------------------------
# 2. Prewarm / load
# -------------------------------------------------------------------

def load_faq_suggestions(max_items: int = 100) -> List[Dict[str, Any]]:
    """
    Load FAQ entries from the FAQ collection (if exists) and cache them.

    Returns a list like:
      [
        {
          "id": "...",
          "question": "...",
          "metadata": {...}
        },
        ...
      ]
    """
    global _cached_faq_docs

    faq_col = get_faq_collection()
    if faq_col is None:
        _cached_faq_docs = []
        print("[Day_19_C] FAQ suggestions disabled (no FAQ collection).")
        return _cached_faq_docs

    # Fetch all docs (or the first max_items) – safe since it's only called once at startup.
    all_data = faq_col.get(
        include=["documents", "metadatas"]
    )

    ids = all_data.get("ids", []) or []
    docs = all_data.get("documents", []) or []
    metas = all_data.get("metadatas", []) or []

    faq_items: List[Dict[str, Any]] = []
    for _id, doc, meta in zip(ids, docs, metas):
        faq_items.append(
            {
                "id": _id,
                "question": doc,
                "metadata": meta or {},
            }
        )

    # Truncate to max_items for safety
    _cached_faq_docs = faq_items[:max_items]

    print(f"[Day_19_C] Cached {len(_cached_faq_docs)} FAQ items.")
    return _cached_faq_docs


# -------------------------------------------------------------------
# 3. Similar FAQ suggestions for a user query
# -------------------------------------------------------------------

def get_similar_faqs(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Given a user query, return the top-K similar FAQ entries (if FAQ collection exists).

    Shape:
      [
        {
          "id": "...",
          "question": "...",
          "score": <float>,
          "metadata": {...},
        },
        ...
      ]
    """
    faq_col = get_faq_collection()
    if faq_col is None:
        return []

    if not query or not query.strip():
        # Fallback: just return the top cached ones (if any)
        global _cached_faq_docs
        if _cached_faq_docs is None:
            load_faq_suggestions()
        return (_cached_faq_docs or [])[:top_k]

    res = faq_col.query(
        query_texts=[query],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    ids = res.get("ids", [[]])[0] or []
    docs = res.get("documents", [[]])[0] or []
    metas = res.get("metadatas", [[]])[0] or []
    dists = res.get("distances", [[]])[0] or []

    out: List[Dict[str, Any]] = []
    for _id, doc, meta, dist in zip(ids, docs, metas, dists):
        out.append(
            {
                "id": _id,
                "question": doc,
                "score": float(dist) if dist is not None else None,
                "metadata": meta or {},
            }
        )

    return out
