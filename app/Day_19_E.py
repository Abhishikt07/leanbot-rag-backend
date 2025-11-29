# app/Day_19_E.py
"""
Debug + introspection helpers for the Leanext Chroma index.

These helpers are meant to be called from FastAPI routes like `/debug/indexed`
or internal tools, but they do NOT modify the index.
"""

from typing import Any, Dict, List

from chromadb.api.models.Collection import Collection

from app.Day_19_B import get_chroma_client


# -------------------------------------------------------------------
# 1. Index-level stats
# -------------------------------------------------------------------

def get_index_stats() -> Dict[str, Any]:
    """
    Return a lightweight summary of the Chroma index:
      - number of collections
      - per-collection document counts
    """
    client = get_chroma_client()
    cols = client.list_collections()

    coll_summaries: List[Dict[str, Any]] = []
    for col in cols:
        try:
            count = col.count()
        except Exception:
            count = None

        coll_summaries.append(
            {
                "name": col.name,
                "id": getattr(col, "id", None),
                "document_count": count,
            }
        )

    return {
        "total_collections": len(cols),
        "collections": coll_summaries,
    }


# -------------------------------------------------------------------
# 2. List indexed documents / URLs (for debug UI)
# -------------------------------------------------------------------

def list_indexed_documents(
    collection_name: str | None = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Return up to `limit` documents from either:
      - a specific collection (if name given), or
      - all collections concatenated.

    Each item:
      {
        "collection": "...",
        "id": "...",
        "document": "...",
        "metadata": {...}
      }
    """
    client = get_chroma_client()
    cols: List[Collection]

    if collection_name:
        # Try to get the named collection, or fall back if it doesn't exist
        try:
            col = client.get_collection(name=collection_name)
            cols = [col]
        except Exception:
            # Fallback: nothing
            return []
    else:
        cols = client.list_collections()

    results: List[Dict[str, Any]] = []

    for col in cols:
        try:
            data = col.get(include=["documents", "metadatas"])
        except Exception:
            continue

        ids = data.get("ids", []) or []
        docs = data.get("documents", []) or []
        metas = data.get("metadatas", []) or []

        for _id, doc, meta in zip(ids, docs, metas):
            results.append(
                {
                    "collection": col.name,
                    "id": _id,
                    "document": doc,
                    "metadata": meta or {},
                }
            )

            if len(results) >= limit:
                return results

    return results
