"""
Cache Manager Module: Handles initialization, read, and write operations
for the SQLite Q&A cache database (chat_cache.db) and the user query log (chatbot_logs.db).
"""
import sqlite3
import logging
import datetime
from difflib import get_close_matches
from typing import Optional, Any, Dict, List, Tuple

# Note: Assuming Day_21_A.py exists and contains the constants
from Day_21_A import CACHE_DB_PATH, CACHE_MATCH_THRESHOLD, ANALYTICS_DB_PATH, LEADS_DB_PATH

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- INITIALIZATION FUNCTIONS ---

def get_db_connection(db_path: str, row_factory=None) -> sqlite3.Connection:
    """Utility function to get a connection with safety settings."""
    # FIX: Use check_same_thread=False for Streamlit/FastAPI compatibility, and enable WAL mode
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = row_factory
    # Enable WAL mode for better concurrency
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_cache_db():
    """Initializes the SQLite cache database and ensures the cache table exists."""
    conn = None
    try:
        conn = get_db_connection(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT UNIQUE,
                answer TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        logging.info(f"Cache database initialized at {CACHE_DB_PATH}")
    except sqlite3.Error as e:
        logging.error(f"Failed to initialize cache DB: {e}")
    finally:
        if conn:
            conn.close()

def init_analytics_db():
    """Initializes the SQLite analytics database and ensures the chatbot_logs table exists."""
    conn = None
    try:
        conn = get_db_connection(ANALYTICS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chatbot_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, -- NEW: User session identifier
                query TEXT,
                answer TEXT,
                source TEXT,
                language TEXT,
                rating INTEGER,
                conversion_score INTEGER, -- NEW: Score 1-5
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # NEW TABLE: related_question_logs (inherited from Day_19_E)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS related_question_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                main_query TEXT,
                related_question TEXT,
                clicked BOOLEAN,
                language TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        logging.info(f"Analytics database initialized at {ANALYTICS_DB_PATH}")
    except sqlite3.Error as e:
        logging.error(f"Failed to initialize analytics DB: {e}")
    finally:
        if conn:
            conn.close()

def init_leads_db():
    """UPDATED: Initializes the SQLite database for capturing leads, including organization."""
    conn = None
    try:
        conn = get_db_connection(LEADS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                user_id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                organization TEXT, -- NEW FIELD
                conversion_score INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        logging.info(f"Leads database initialized at {LEADS_DB_PATH}")
    except sqlite3.Error as e:
        logging.error(f"Failed to initialize leads DB: {e}")
    finally:
        if conn:
            conn.close()


# --- CACHE OPERATIONS (Read/Write) ---

def get_cached_answer(query) -> Optional[Tuple[str, str, str]]:
    """
    Checks for exact or similar query matches in the cache.
    Returns (answer, source, original_query) tuple if found, else None.
    """
    conn = get_db_connection(CACHE_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT query, answer, source FROM cache")
    all_cache_entries = cursor.fetchall()
    conn.close()

    if not all_cache_entries: return None
    cached_queries = [entry[0] for entry in all_cache_entries]
    
    # FIX: Use a lower cutoff for more fuzzy matching on the cache read
    matches = get_close_matches(query, cached_queries, n=1, cutoff=CACHE_MATCH_THRESHOLD)
    
    if matches:
        matched_query = matches[0]
        conn = get_db_connection(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT answer, source FROM cache WHERE query = ?", (matched_query,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logging.info(f"Cache HIT for query '{query[:20]}...' (matched: '{matched_query[:20]}...')")
            return result[0], result[1], matched_query
            
    logging.info(f"Cache MISS for query '{query[:20]}...'")
    return None

def save_answer_to_cache(query, answer, source):
    """
    Inserts a new Q&A pair into the cache, ignoring exact duplicates.
    """
    conn = None
    try:
        conn = get_db_connection(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO cache (query, answer, source)
            VALUES (?, ?, ?)
        """, (query, answer, source))
        conn.commit()
        logging.info(f"Answer saved to cache for query: '{query[:20]}...' (Source Tag: {source[:10]}...)")
    except sqlite3.IntegrityError:
        logging.info(f"Query already exists in cache (exact match): '{query[:20]}...'")
    except sqlite3.Error as e:
        logging.error(f"Failed to save to cache: {e}")
    finally:
        if conn:
            conn.close()


def update_cached_answer(query, new_answer, new_source):
    """
    Updates an existing Q&A pair in the cache database based on the original query.
    This is used after a successful regeneration (Thumbs Up).
    """
    conn = None
    try:
        conn = get_db_connection(CACHE_DB_PATH)
        cursor = conn.cursor()
        
        # Use the original query to find the entry and update it
        cursor.execute("""
            UPDATE cache
            SET answer = ?, source = ?, created_at = CURRENT_TIMESTAMP
            WHERE query = ?
        """, (new_answer, new_source, query))
        
        rows_affected = cursor.rowcount
        conn.commit() 
        
        if rows_affected > 0:
            logging.info(f"Cache UPDATED for query: '{query[:20]}...' (Rows affected: {rows_affected})")
            return True
        else:
             logging.warning(f"Cache update attempted but no matching row found for query: '{query[:20]}...'")
             return False
             
    except sqlite3.Error as e:
        logging.error(f"Failed to update cache: {e}")
        return False
    finally:
        if conn:
            conn.close()

# --- LOGGING USER INTERACTIONS (Analytics) ---

def log_chatbot_interaction(user_id, query, translated_query, answer, source, language, rating=None, conversion_score=1):
    """
    Logs a complete user interaction (including score) to the chatbot_logs database.
    """
    conn = None
    try:
        conn = get_db_connection(ANALYTICS_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO chatbot_logs (user_id, query, answer, source, language, rating, conversion_score) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, 
            (user_id, query, answer, source, language, rating, conversion_score)
        )
        conn.commit()
        logging.info(f"Interaction logged (User: {user_id[:8]}..., Lang: {language}, Score: {conversion_score})")
    except sqlite3.Error as e:
        # Logging the error explicitly helps diagnose locking or table issues
        logging.error(f"Failed to log interaction to ANALYTICS DB: {e}")
    finally:
        if conn:
            conn.close()
        
# --- LEAD CAPTURE OPERATIONS ---

def save_lead_contact(user_id, name, email, phone, organization, conversion_score):
    """
    Saves or updates a lead's contact information in the leads database.
    Includes organization field. Validation handled in Day_21_D.py for better UI feedback.
    """
    conn = None
    try:
        conn = get_db_connection(LEADS_DB_PATH)
        cursor = conn.cursor()
        
        # Validation passed in the UI, save the clean data
        cursor.execute("""
            INSERT OR REPLACE INTO leads 
                (user_id, name, email, phone, organization, conversion_score, created_at)
            VALUES 
                (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, name, email, phone, organization, conversion_score))
        
        conn.commit()
        logging.info(f"Lead contact saved/updated for User: {user_id[:8]}... (Score: {conversion_score})")
        return True, "Success"
    except sqlite3.Error as e:
        logging.error(f"Failed to save lead contact (DB Error): {e}")
        return False, f"Database error: {e}"
    finally:
        if conn:
            conn.close()

def check_lead_saved(user_id):
    """Checks if contact info has already been saved for this user_id."""
    conn = None
    try:
        conn = get_db_connection(LEADS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM leads WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except sqlite3.Error as e:
        logging.error(f"Failed to check lead status: {e}")
        return False
    finally:
        if conn:
            conn.close()

# --- DEBUG FUNCTION (renamed to avoid conflict) ---
def get_all_indexed_urls(collection):
    """Retrieves all unique canonical URLs from the ChromaDB collection for debugging."""
    try:
        # Fetching all documents can be slow, but useful for a debug function
        results = collection.get(
            include=['metadatas']
        )
        if not results or not results.get('metadatas'):
            return []
            
        canonical_urls = set()
        for meta in results['metadatas']:
            if 'canonical' in meta:
                canonical_urls.add(meta['canonical'])
        return sorted(list(canonical_urls))
    except Exception as e:
        logging.error(f"Failed to retrieve indexed URLs from ChromaDB: {e}")
        return []