# app/Day_19_B.py
"""
Core utilities for talking to the *existing* ChromaDB index.

Key ideas:
- Never rebuild embeddings here.
- Always reuse the persisted DB at app/chroma_db_leanext.
- Provide a simple search_leanext_kb(query, n_results=5) helper
  that other modules (Day_19_D, FastAPI, etc.) can call.
"""

import os
from typing import Any, Dict, List, Optional

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection


# -------------------------------------------------------------------
# 1. Resolve the *persisted* Chroma path inside the app package
# -------------------------------------------------------------------

# /opt/render/project/src/app/Day_19_B.py -> /opt/render/project/src/app/chroma_db_leanext
CHROMA_PERSIST_DIRECTORY = os.path.join(
    os.path.dirname(__file__),  # app/
    "chroma_db_leanext"
)


_client: Optional[PersistentClient] = None
_kb_collection: Optional[Collection] = None


# -------------------------------------------------------------------
# 2. Client + Collection helpers
# -------------------------------------------------------------------

def get_chroma_client() -> PersistentClient:
    """Return a singleton PersistentClient pointing to app/chroma_db_leanext."""
    global _client

    if _client is None:
        if not os.path.isdir(CHROMA_PERSIST_DIRECTORY):
            raise RuntimeError(
                f"Chroma directory not found at {CHROMA_PERSIST_DIRECTORY}. "
                "Make sure you committed app/chroma_db_leanext to Git."
            )

        _client = PersistentClient(path=CHROMA_PERSIST_DIRECTORY)
        print(f"[Day_19_B] Connected to Chroma at: {CHROMA_PERSIST_DIRECTORY}")

    return _client


def _pick_kb_collection(client: PersistentClient) -> Collection:
    """
    Heuristic: pick a 'main KB' collection from whatever exists in Chroma.
    Preference order:
      - Name exactly: leanext_kb / leanext_main / leanext_docs
      - Otherwise: first collection in the list.
    """
    collections = client.list_collections()
    if not collections:
        raise RuntimeError(
            "No Chroma collections found in the persisted DB. "
            "Did you run the crawler / indexer locally and commit the DB?"
        )

    preferred_names = ["leanext_kb", "leanext_main", "leanext_docs"]

    # Exact name match if possible
    for name in preferred_names:
        for col in collections:
            if col.name == name:
                print(f"[Day_19_B] Using preferred KB collection: {col.name}")
                return col

    # Fallback: first collection
    col = collections[0]
    print(f"[Day_19_B] Using fallback KB collection: {col.name}")
    return col


def get_kb_collection() -> Collection:
    """Return a singleton handle to the 'main' KB collection."""
    global _kb_collection

    if _kb_collection is None:
        client = get_chroma_client()
        _kb_collection = _pick_kb_collection(client)

    return _kb_collection


# -------------------------------------------------------------------
# 3. Public search helpers
# -------------------------------------------------------------------

def search_leanext_kb(
    query: str,
    n_results: int = 5,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Low-level wrapper around Chroma's .query().

    Returns the *raw* Chroma response:
      {
        "ids": [[...]],
        "distances": [[...]] or "embeddings": [...],
        "documents": [[...]],
        "metadatas": [[...]],
      }
    """
    if not query or not query.strip():
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    collection = get_kb_collection()

    result = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where or {},
        include=["documents", "metadatas", "distances"],
    )

    return result


def search_leanext_kb_formatted(
    query: str,
    n_results: int = 5,
    where: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Convenience wrapper that returns a cleaner list of dicts:

    [
      {
        "id": "...",
        "score": <float>,
        "document": "...",
        "metadata": {...},
      },
      ...
    ]
    """
    raw = search_leanext_kb(query=query, n_results=n_results, where=where)

    ids = raw.get("ids", [[]])[0] or []
    docs = raw.get("documents", [[]])[0] or []
    metas = raw.get("metadatas", [[]])[0] or []
    dists = raw.get("distances", [[]])[0] or []

    formatted = []
    for _id, doc, meta, dist in zip(ids, docs, metas, dists):
        formatted.append(
            {
                "id": _id,
                "score": float(dist) if dist is not None else None,
                "document": doc,
                "metadata": meta or {},
            }
        )

    return formatted
