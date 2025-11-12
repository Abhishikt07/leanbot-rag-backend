"""
Cache Manager Module: Handles initialization, read, and write operations
for the SQLite Q&A cache database (chat_cache.db) and the user query log (chatbot_logs.db).
"""
import sqlite3
import logging
import datetime
from difflib import get_close_matches
# Note: Assuming Day_19_A.py exists and contains the constants
from Day_19_A import CACHE_DB_PATH, CACHE_MATCH_THRESHOLD, ANALYTICS_DB_PATH, LEADS_DB_PATH

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- INITIALIZATION FUNCTIONS ---

def init_cache_db():
    """Initializes the SQLite cache database and ensures the cache table exists."""
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
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
        conn.close()
        logging.info(f"Cache database initialized at {CACHE_DB_PATH}")
    except Exception as e:
        logging.error(f"Failed to initialize cache DB: {e}")

def init_analytics_db():
    """Initializes the SQLite analytics database and ensures the chatbot_logs table exists."""
    try:
        conn = sqlite3.connect(ANALYTICS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chatbot_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                answer TEXT,
                source TEXT,
                language TEXT,
                rating INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
        logging.info(f"Analytics database initialized at {ANALYTICS_DB_PATH}")
    except Exception as e:
        logging.error(f"Failed to initialize analytics DB: {e}")

# NEW FUNCTION: Initialize Leads Database
def init_leads_db():
    """Initializes the SQLite database for lead generation data."""
    try:
        conn = sqlite3.connect(LEADS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact_number TEXT,
            email TEXT,
            organization TEXT,
            demo_type TEXT, 
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
        logging.info(f"Leads database initialized at {LEADS_DB_PATH}")
    except Exception as e:
        logging.error(f"Failed to initialize leads DB: {e}")

# --- CACHE OPERATIONS (Read/Write) ---

def get_cached_answer(query):
    """
    Checks for exact or similar query matches in the cache.
    Returns (answer, source, original_query) tuple if found, else None.
    """
    conn = sqlite3.connect(CACHE_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT query, answer, source FROM cache")
    all_cache_entries = cursor.fetchall()
    conn.close()

    if not all_cache_entries: return None
    cached_queries = [entry[0] for entry in all_cache_entries]
    
    matches = get_close_matches(query, cached_queries, n=1, cutoff=CACHE_MATCH_THRESHOLD)
    
    if matches:
        matched_query = matches[0]
        conn = sqlite3.connect(CACHE_DB_PATH)
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
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO cache (query, answer, source)
            VALUES (?, ?, ?)
        """, (query, answer, source))
        conn.commit() # CRITICAL: Ensures persistence
        conn.close()
        logging.info(f"Answer saved to cache for query: '{query[:20]}...' (Source Tag: {source[:10]}...)")
    except Exception as e:
        logging.error(f"Failed to save to cache: {e}")


def update_cached_answer(query, new_answer, new_source):
    """
    Updates an existing Q&A pair in the cache database based on the original query.
    This is used after a successful regeneration (Thumbs Up).
    """
    try:
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        
        # Use the original query to find the entry and update it
        cursor.execute("""
            UPDATE cache
            SET answer = ?, source = ?, created_at = CURRENT_TIMESTAMP
            WHERE query = ?
        """, (new_answer, new_source, query))
        
        conn.commit() 
        conn.close()
        logging.info(f"Cache UPDATED for query: '{query[:20]}...'")
        return True
    except Exception as e:
        logging.error(f"Failed to update cache: {e}")
        return False

# --- LOGGING USER QUERIES (Updated Function Name) ---

def log_chatbot_interaction(query, translated_query, answer, source, language, rating=None):
    """
    Logs a complete user interaction (including language and rating) to the chatbot_logs database.
    This replaces the old log_user_query_db function.
    """
    try:
        conn = sqlite3.connect(ANALYTICS_DB_PATH)
        cursor = conn.cursor()
        
        # We store the original query (query) and the final answer (answer)
        cursor.execute(
            """
            INSERT INTO chatbot_logs (query, answer, source, language, rating) 
            VALUES (?, ?, ?, ?, ?)
            """, 
            (query, answer, source, language, rating)
        )
        conn.commit()
        conn.close()
        logging.info(f"Interaction logged (Lang: {language}, Source: {source[:10]}...)")
    except Exception as e:
        # Logging the error explicitly helps diagnose locking or table issues
        logging.error(f"Failed to log interaction to ANALYTICS DB: {e}")
        
# NEW FUNCTION: Log Validated Lead Data
def log_lead_data(name, contact_number=None, email=None, demo_type=None, organization=None): # 🔹 ADDED demo_type    
    """
    Saves validated lead data to the leads database.
    """
    conn = None # Initialize conn outside the try block
    try:
        # Establish connection
        conn = sqlite3.connect(LEADS_DB_PATH) 
        cursor = conn.cursor()
        
        cursor.execute(
            """
        INSERT INTO leads (name, contact_number, email, demo_type, organization) 
        VALUES (?, ?, ?, ?, ?) # 🔹 UPDATED SQL AND BINDINGS
        """, 
        (name, contact_number, email, demo_type, organization)
    )
        conn.commit()
        logging.info(f"New Lead logged: Name={name}, Email={email}, Phone={contact_number}")
        return True
    except sqlite3.OperationalError as e:
        # This catches specific errors like "database is locked"
        logging.error(f"SQLite Operational Error (Lead Log): {e}. Database might be locked.")
        return False
    except Exception as e:
        logging.error(f"Failed to log lead data to LEADS DB: {e}")
        return False
    finally:
        # Ensure connection is closed whether an error occurred or not
        if conn:
            conn.close()

# --- DEBUG FUNCTION ---
def get_all_indexed_urls(collection):
    """Retrieves all unique canonical URLs from the ChromaDB collection for debugging."""
    try:
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
