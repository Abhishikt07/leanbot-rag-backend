"""
Day_19_E — Backend-Safe Database Layer (Render-compatible)
Handles:
- Query Cache (SQLite)
- Chat Analytics
- Lead Logging
- FAQ/KB Helpers
"""

import sqlite3
import os
import logging
from datetime import datetime

from .Day_19_A import CACHE_DB_PATH, ANALYTICS_DB_PATH, LEADS_DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


###############################################################
# 1. Ensure directories exist
###############################################################
def ensure_dir(path):
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)


###############################################################
# 2. Initialize DBs
###############################################################
def init_cache_db():
    ensure_dir(CACHE_DB_PATH)
    conn = sqlite3.connect(CACHE_DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            answer TEXT,
            source TEXT,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()
    return True


def init_analytics_db():
    ensure_dir(ANALYTICS_DB_PATH)
    conn = sqlite3.connect(ANALYTICS_DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            translated_query TEXT,
            answer TEXT,
            source TEXT,
            language TEXT,
            rating INTEGER,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()
    return True


def init_leads_db():
    ensure_dir(LEADS_DB_PATH)
    conn = sqlite3.connect(LEADS_DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            email TEXT,
            demo_type TEXT,
            organization TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()
    return True


###############################################################
# 3. Cache Functions
###############################################################
def get_cached_answer(cleaned_question):
    """Returns (answer, source, matched_query) or None"""
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
        cur = conn.cursor()

        cur.execute("SELECT answer, source, question FROM cache WHERE question = ?", (cleaned_question,))
        row = cur.fetchone()
        conn.close()

        if row:
            return row[0], row[1], row[2]
        return None

    except Exception as e:
        logging.error(f"Cache lookup failed: {e}")
        return None


def save_answer_to_cache(cleaned_question, answer, source):
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO cache (question, answer, source, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(question) DO UPDATE SET
                answer = excluded.answer,
                source = excluded.source,
                updated_at = excluded.updated_at
        """, (cleaned_question, answer, source, datetime.utcnow().isoformat()))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logging.error(f"Cache save failed: {e}")
        return False


def update_cached_answer(question, new_answer, new_source):
    """Used when the user presses 👍 on a regenerated answer."""
    return save_answer_to_cache(question, new_answer, new_source)


###############################################################
# 4. Analytics Logging
###############################################################
def log_chatbot_interaction(query, translated_query, answer, source, language, rating=None):
    try:
        conn = sqlite3.connect(ANALYTICS_DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO analytics (
                query, translated_query, answer, source, language, rating, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            query,
            translated_query,
            answer,
            source,
            language,
            rating,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logging.error(f"Analytics log failed: {e}")
        return False


###############################################################
# 5. Lead Logging
###############################################################
def log_lead_data(name, phone, email, demo_type, org):
    try:
        conn = sqlite3.connect(LEADS_DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO leads (name, phone, email, demo_type, organization, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            phone,
            email,
            demo_type,
            org,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logging.error(f"Lead log failed: {e}")
        return False


###############################################################
# 6. Fetching indexed URLs (Debug)
###############################################################
def get_all_indexed_urls(collection):
    """Returns list of canonical URLs from the ChromaDB collection."""
    try:
        all_meta = collection.get(include=["metadatas"])
        urls = [m.get("canonical") for m in all_meta["metadatas"] if m.get("canonical")]
        return list(set(urls))
    except:
        return []
