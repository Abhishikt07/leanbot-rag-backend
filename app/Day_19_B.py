"""
Day_19_B — Backend-Optimized ChromaDB Loader (Render-Safe)
NO Streamlit, NO Playwright, NO heavy runtime indexing.
"""

import os
import json
import time
import logging
import chromadb
from bs4 import BeautifulSoup
import urllib.parse
import requests
import hashlib

# Basic config imports (safe)
from .Day_19_A import (
    BASE_URL,
    CHROMA_DB_PATH,
    COLLECTION_NAME,
    FAQ_COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
)

# Embedding function (light)
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

EMBED_FN = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)


#################################################################
# HELPERS — kept for compatibility but NOT used at startup
#################################################################

def normalize_url(url):
    """Basic URL cleanup."""
    url = urllib.parse.urldefrag(url)[0]
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed).rstrip("/")


#################################################################
# MAIN: Load Existing ChromaDB (NO indexing)
#################################################################

def load_or_build_knowledge_base():
    """
    Render-safe version.
    Loads an existing ChromaDB index.
    Does NOT rebuild or crawl the site.
    """

    logging.info("Attempting to load existing ChromaDB index...")

    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

        collection_names = [c.name for c in client.list_collections()]

        if COLLECTION_NAME not in collection_names:
            logging.error(
                f"❌ Collection '{COLLECTION_NAME}' not found. "
                f"You must run local indexing before deploying."
            )
            return None

        collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=EMBED_FN
        )

        logging.info(f"✅ Loaded ChromaDB collection with {collection.count()} chunks.")
        return collection

    except Exception as e:
        logging.error(f"❌ Failed to load ChromaDB: {e}")
        return None


#################################################################
# Load FAQ collection (also required for Startup)
#################################################################

def load_faq_collection():
    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection = client.get_collection(
            name=FAQ_COLLECTION_NAME,
            embedding_function=EMBED_FN
        )
        logging.info(f"✅ FAQ collection loaded ({collection.count()} FAQs)")
        return collection
    except Exception as e:
        logging.error(f"❌ Failed loading FAQ collection: {e}")
        return None
