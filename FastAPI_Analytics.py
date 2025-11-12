"""
Private FastAPI Analytics API:
Provides secure access to chatbot log data (chatbot_logs.db) using an API key.
"""
import sqlite3
import secrets
import os
import logging # Import logging
from dotenv import load_dotenv
from typing import Annotated, Optional
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
import json
import time
from demo_scheduler import schedule_demo_meeting # NEW IMPORT
from fastapi.middleware.cors import CORSMiddleware

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables (including ANALYTICS_API_KEY) from .env file
load_dotenv()
from Day_19_A import ANALYTICS_DB_PATH, ANALYTICS_API_KEY as ENV_API_KEY, LEADS_DB_PATH # Import config constants

# --- 1. API Key Setup ---
def generate_and_save_api_key():
    """Generates a secure API key if it does not exist in the .env file."""
    if not ENV_API_KEY:
        key = secrets.token_hex(32) # Increased key length for better security
        with open(".env", "a") as f:
            f.write(f"\nANALYTICS_API_KEY={key}\n")
        return key
    return ENV_API_KEY

API_KEY = generate_and_save_api_key()

# --- 2. FastAPI Initialization ---
app = FastAPI(title="LeanBot Analytics API", version="1.0.0")

# --- NEW: CORS Middleware (Allows frontend on any domain to access) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with your frontend domain(s), e.g., ["https://mycompany.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- END NEW: CORS Middleware ---

# --- 3. Dependency for API Key Authentication ---
def get_api_key(x_api_key: Annotated[str, Header()]) -> str:
    """Dependency function to validate the API key header."""
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key. Access denied."
        )
    return x_api_key

# --- 4. Pydantic Models for Response ---
class QueryLog(BaseModel):
    id: int
    query: str
    answer: str
    source: str
    language: str
    rating: Optional[int]
    timestamp: str

class AnalyticsResponse(BaseModel):
    total_queries: int = Field(..., description="Total number of interactions logged.")
    cache_vs_gemini: dict[str, int] = Field(..., description="Count of responses sourced from Cache vs. Gemini/RAG.")
    average_rating: float = Field(..., description="Average user rating (0=Dislike, 1=Like). Nulls excluded.")
    query_count_by_language: dict[str, int] = Field(..., description="Number of queries per language code.")
    last_10_queries: list[QueryLog] = Field(..., description="The most recent 10 logged interactions.")

class Lead(BaseModel):
    id: Optional[int] = None # Make ID optional for POST payload
    name: str
    contact_number: Optional[str] = None
    email: Optional[str] = None
    organization: Optional[str] = None
    # 🔹 NEW FIELD: demo_type
    demo_type: Optional[str] = None
    timestamp: Optional[str] = None # Make timestamp optional for POST payload

def fetch_leads_data():
    """Connects to the leads DB and fetches all lead records."""
    conn = None
    try:
        logging.info(f"Attempting connection to Leads DB: {LEADS_DB_PATH}")
        conn = sqlite3.connect(LEADS_DB_PATH)
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM leads ORDER BY timestamp DESC")
        raw_leads = cursor.fetchall()
        
        leads_data = [
            Lead(
                id=row['id'], 
                name=row['name'], 
                contact_number=row['contact_number'], 
                email=row['email'],
                organization=row['organization'],
                timestamp=row['timestamp']
            ) for row in raw_leads
        ]
        
        logging.info(f"Successfully retrieved {len(leads_data)} leads.")
        return leads_data
        
    except sqlite3.OperationalError as e:
        logging.error(f"SQLite Operational Error (Leads DB): {e}. Database locked or missing.")
        # Return an empty list or specific error if needed
        return [] 
    except Exception as e:
        logging.error(f"Unexpected error in fetch_leads_data: {e}")
        raise HTTPException(status_code=500, detail="Unexpected server error while fetching leads.")
    finally:
        if conn:
            conn.close()

# --- 5. Core Database Functionality ---
def fetch_analytics_data():
    """Connects to the DB and fetches all required data for the analytics endpoint."""
    conn = None
    try:
        logging.info(f"Attempting connection to DB: {ANALYTICS_DB_PATH}")
        conn = sqlite3.connect(ANALYTICS_DB_PATH)
        conn.row_factory = sqlite3.Row # Allows accessing columns by name
        cursor = conn.cursor()

        # 1. Total Queries
        cursor.execute("SELECT COUNT(id) FROM chatbot_logs")
        total_queries = cursor.fetchone()[0]

        # 2. Source Counts (Cache vs Gemini/RAG)
        cursor.execute("SELECT source, COUNT(id) FROM chatbot_logs GROUP BY source")
        source_data = cursor.fetchall()
        
        cache_vs_gemini = {"Cache": 0, "Gemini_RAG": 0, "Other": 0}
        for row in source_data:
            source = row['source']
            count = row['COUNT(id)']
            if source.startswith("Cache HIT") or source.startswith("Small Talk"):
                cache_vs_gemini["Cache"] += count
            elif source.startswith("Gemini API") or source.startswith("RAG-Regen"):
                cache_vs_gemini["Gemini_RAG"] += count
            else:
                cache_vs_gemini["Other"] += count
                
        # 3. Average Rating
        cursor.execute("SELECT AVG(rating) FROM chatbot_logs WHERE rating IS NOT NULL")
        avg_rating = cursor.fetchone()[0]
        average_rating = round(avg_rating, 4) if avg_rating is not None else 0.0

        # 4. Query Count per Language
        cursor.execute("SELECT language, COUNT(id) FROM chatbot_logs GROUP BY language")
        language_data = cursor.fetchall()
        query_count_by_language = {row['language']: row['COUNT(id)'] for row in language_data}
        
        # 5. Last 10 Queries
        cursor.execute("SELECT * FROM chatbot_logs ORDER BY timestamp DESC LIMIT 10")
        last_10_raw = cursor.fetchall()
        
        last_10_queries = [
            QueryLog(
                id=row['id'], 
                query=row['query'], 
                answer=row['answer'], 
                source=row['source'], 
                language=row['language'],
                rating=row['rating'],
                timestamp=row['timestamp']
            ) for row in last_10_raw
        ]
        
        logging.info("Successfully retrieved analytics data.")
        return AnalyticsResponse(
            total_queries=total_queries,
            cache_vs_gemini=cache_vs_gemini,
            average_rating=average_rating,
            query_count_by_language=query_count_by_language,
            last_10_queries=last_10_queries
        )
        
    except sqlite3.OperationalError as e:
        # This specifically catches "database is locked" or "no such table" errors
        logging.error(f"SQLite Operational Error (Database Locked/Missing): {e}. Ensure Streamlit connections are closed.")
        raise HTTPException(status_code=503, detail=f"Database operational error: {e}. Is the database locked by another process?")
    except sqlite3.Error as e:
        logging.error(f"General Database error: {e}")
        raise HTTPException(status_code=500, detail="Database error during data retrieval.")
    except Exception as e:
        logging.error(f"Unexpected error in fetch_analytics_data: {e}")
        raise HTTPException(status_code=500, detail="Unexpected server error.")
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")


# --- 6. API Endpoints ---
@app.get("/api/health", tags=["Status"])
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "message": "Analytics API is operational."}

@app.get("/api/analytics", response_model=AnalyticsResponse, tags=["Analytics"])
async def get_analytics(authenticated: Annotated[str, Depends(get_api_key)]):
    """
    Returns core analytics data from the chatbot logs.
    Requires 'x-api-key' header for authentication.
    """
    return fetch_analytics_data()

@app.get("/api/leads", response_model=list[Lead], tags=["Leads"])
async def get_leads(authenticated: Annotated[str, Depends(get_api_key)]):
    """
    Returns all captured lead data from the dedicated leads.db database.
    Requires 'x-api-key' header for authentication.
    """
    leads = fetch_leads_data()
    if not leads:
        # Check if DB is totally empty or missing
        raise HTTPException(status_code=404, detail="No leads found, or database access failed.")
    return leads

# 🔹 ADD THIS NEW ENDPOINT
@app.post("/api/leads")
async def post_lead(lead: Lead):
    """
    Accepts new lead data and saves it to the leads database.
    Triggers demo scheduling if a demo type and email are provided.
    """
    conn = None
    try:
        # 1. Database Connection and WAL Mode for concurrency safety
        conn = sqlite3.connect(LEADS_DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        # 2. Ensure Table Exists (with new demo_type column)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact_number TEXT,
                email TEXT,
                organization TEXT,
                demo_type TEXT, -- 🔹 NEW COLUMN ADDED
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 3. Insert Data
        cursor.execute(
            """
            INSERT INTO leads (name, contact_number, email, organization, demo_type) 
            VALUES (?, ?, ?, ?, ?)
            """, 
            (lead.name, lead.contact_number, lead.email, lead.organization, lead.demo_type)
        )
        conn.commit()
        logging.info(f"New Lead saved: {lead.name}, Demo Type: {lead.demo_type}")

        # 4. Schedule Demo Meeting (New Logic Hook)
        if lead.demo_type and lead.demo_type != "General Inquiry" and lead.email:
            logging.info(f"Attempting to schedule demo for {lead.email} ({lead.demo_type}).")
            meet_link = schedule_demo_meeting(lead.name, lead.email, lead.demo_type)
            if meet_link:
                logging.info(f"Demo scheduled successfully. Meet Link: {meet_link}")
            else:
                logging.warning("Demo scheduling failed (check demo_scheduler.py logs). Lead still saved.")

        return {"status": "ok", "message": "Lead saved successfully."}

    except sqlite3.Error as e:
        logging.error(f"SQLite DB error during lead POST: {e}")
        raise HTTPException(status_code=500, detail="Database error during lead submission.")
    except Exception as e:
        logging.error(f"Unexpected error during lead POST: {e}")
        raise HTTPException(status_code=500, detail="Unexpected server error during lead submission.")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    import uvicorn
    print("\n--- FastAPI Analytics API ---")
    print(f"🔑 Your required API Key (ANALYTICS_API_KEY): {API_KEY}")
    print("🚀 Running API at http://127.0.0.1:8000")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
