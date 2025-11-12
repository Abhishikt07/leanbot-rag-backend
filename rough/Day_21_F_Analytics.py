"""
Private FastAPI Analytics API:
Provides secure access to chatbot log data (chatbot_logs.db) and leads data (leads.db)
using an API key.
"""
import sqlite3
import secrets
import os
import logging
from dotenv import load_dotenv
# FIX: Import Optional for Python < 3.10 compatibility, and List
from typing import Annotated, List, Optional, Any, Dict
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware # NEW: Import CORS middleware
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables (including ANALYTICS_API_KEY) from .env file
load_dotenv()
# FIX: Import from Day_21_A
from Day_21_A import ANALYTICS_DB_PATH, LEADS_DB_PATH, ANALYTICS_API_KEY as ENV_API_KEY, CONVERSION_SCORE_MAP, HIGH_POTENTIAL_THRESHOLD # Import config constants

# Import SQLite connection utility from Day_21_E for consistency and safety
from Day_21_E import get_db_connection

# --- 1. API Key Setup ---
def generate_and_save_api_key():
    """Generates a secure API key if it does not exist in the .env file."""
    if not ENV_API_KEY:
        key = secrets.token_hex(32) 
        # FIX: Check if .env exists before appending, or ensure it's created
        try:
            with open(".env", "a") as f:
                f.write(f"\nANALYTICS_API_KEY={key}\n")
        except Exception as e:
            logging.error(f"Could not write ANALYTICS_API_KEY to .env: {e}")
        return key
    return ENV_API_KEY

API_KEY = generate_and_save_api_key()

# --- 2. FastAPI Initialization ---
app = FastAPI(title="LeanBot Analytics API", version="2.0.0")

# NEW: CORS Middleware Setup
origins = [
    "http://localhost",
    "http://localhost:8501",  # Streamlit default port
    # Add other origins as needed
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allowing all origins for ease of development, but should be restricted in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    user_id: str
    query: str
    answer: str
    source: str
    language: str
    # FIX: Changed 'int | None' to 'Optional[int]'
    rating: Optional[int]
    conversion_score: int
    timestamp: str

class LeadContact(BaseModel):
    user_id: str
    # FIX: Changed 'str | None' to 'Optional[str]'
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    organization: Optional[str] # NEW FIELD
    conversion_score: int
    created_at: str
    
# FIX: Define a Pydantic model for the incoming lead payload from the UI (optional fields)
class IncomingLeadPayload(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    organization: Optional[str] = None
    conversion_score: Optional[int] = Field(default=1)


class AnalyticsResponse(BaseModel):
    total_queries: int = Field(..., description="Total number of interactions logged.")
    cache_vs_gemini: Dict[str, int] = Field(..., description="Count of responses sourced from Cache vs. Gemini/RAG.")
    average_rating: float = Field(..., description="Average user rating (0=Dislike, 1=Like). Nulls excluded.")
    query_count_by_language: Dict[str, int] = Field(..., description="Number of queries per language code.")
    conversion_summary: Dict[str, int] = Field(..., description="Total number of unique users by their highest conversion score (1-5).")
    last_10_queries: List[QueryLog] = Field(..., description="The most recent 10 logged interactions.")


# --- 5. Core Database Functionality ---
# FIX: Removed the original get_db_connection to use the safe one from Day_21_E
# Using the imported get_db_connection(db_path, row_factory=sqlite3.Row)

def fetch_analytics_data() -> AnalyticsResponse:
    """Connects to the DB and fetches all required data for the analytics endpoint."""
    conn_logs = None
    try:
        logging.info(f"Attempting connection to DB: {ANALYTICS_DB_PATH}")
        # FIX: Use get_db_connection from Day_21_E with row factory
        conn_logs = get_db_connection(ANALYTICS_DB_PATH, row_factory=sqlite3.Row)
        cursor = conn_logs.cursor()

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
            # FIX: Ensure all cache/small talk/regen tags are accounted for
            if source.startswith("Cache HIT") or source.startswith("Small Talk"):
                cache_vs_gemini["Cache"] += count
            elif source.startswith("Gemini API") or source.startswith("RAG-Regen") or source.startswith("Unclear Query"):
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
        # FIX: Handle potential None/empty string language codes gracefully
        query_count_by_language = {row['language'] or 'unknown': row['COUNT(id)'] for row in language_data}
        
        # 5. Conversion Summary (Highest score per unique user)
        cursor.execute("""
            SELECT user_id, MAX(conversion_score) as max_score
            FROM chatbot_logs
            GROUP BY user_id
        """)
        conversion_data = cursor.fetchall()
        # FIX: Dynamically build the summary structure based on the map keys
        conversion_summary = {CONVERSION_SCORE_MAP[i][0]: 0 for i in range(1, 6)}
        
        for row in conversion_data:
            score = row['max_score']
            # Safely get the label using CONVERSION_SCORE_MAP
            label = CONVERSION_SCORE_MAP.get(score, CONVERSION_SCORE_MAP[1])[0] 
            conversion_summary[label] += 1
        
        # 6. Last 10 Queries
        cursor.execute("SELECT * FROM chatbot_logs ORDER BY timestamp DESC LIMIT 10")
        last_10_raw = cursor.fetchall()
        
        last_10_queries = [
            QueryLog(
                id=row['id'], 
                user_id=row['user_id'],
                query=row['query'], 
                answer=row['answer'], 
                source=row['source'], 
                language=row['language'],
                rating=row['rating'],
                conversion_score=row['conversion_score'],
                timestamp=row['timestamp']
            ) for row in last_10_raw
        ]
        
        logging.info("Successfully retrieved analytics data.")
        return AnalyticsResponse(
            total_queries=total_queries,
            cache_vs_gemini=cache_vs_gemini,
            average_rating=average_rating,
            query_count_by_language=query_count_by_language,
            conversion_summary=conversion_summary,
            last_10_queries=last_10_queries
        )
        
    except sqlite3.OperationalError as e:
        logging.error(f"SQLite Operational Error (Analytics DB): {e}.")
        raise HTTPException(status_code=503, detail=f"Database operational error: {e}. Is the database locked by another process?")
    except Exception as e:
        logging.error(f"Unexpected error in fetch_analytics_data: {e}")
        raise HTTPException(status_code=500, detail="Unexpected server error.")
    finally:
        if conn_logs:
            conn_logs.close()

def fetch_high_potential_leads(threshold: int = 4) -> List[LeadContact]:
    """Fetches leads with a conversion score >= threshold from the leads database."""
    conn_leads = None
    try:
        logging.info(f"Attempting connection to Leads DB: {LEADS_DB_PATH}")
        # FIX: Use get_db_connection from Day_21_E with row factory
        conn_leads = get_db_connection(LEADS_DB_PATH, row_factory=sqlite3.Row)
        cursor = conn_leads.cursor()

        cursor.execute("""
            SELECT user_id, name, email, phone, organization, conversion_score, created_at
            FROM leads
            WHERE conversion_score >= ?
            ORDER BY created_at DESC
        """, (threshold,))
        
        leads_raw = cursor.fetchall()
        
        leads_list = [
            LeadContact(
                user_id=row['user_id'],
                name=row['name'],
                email=row['email'],
                phone=row['phone'],
                organization=row['organization'],
                conversion_score=row['conversion_score'],
                created_at=row['created_at']
            ) for row in leads_raw
        ]
        
        logging.info(f"Successfully retrieved {len(leads_list)} high-potential leads.")
        return leads_list

    except sqlite3.OperationalError as e:
        logging.error(f"SQLite Operational Error (Leads DB): {e}.")
        raise HTTPException(status_code=503, detail=f"Leads database operational error: {e}.")
    except Exception as e:
        logging.error(f"Unexpected error in fetch_high_potential_leads: {e}")
        raise HTTPException(status_code=500, detail="Unexpected server error while fetching leads.")
    finally:
        if conn_leads:
            conn_leads.close()


# --- 6. API Endpoints ---
@app.get("/api/health", tags=["Status"])
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "message": "Analytics API is operational."}

@app.get("/api/analytics", response_model=AnalyticsResponse, tags=["Analytics"])
async def get_analytics(authenticated: Annotated[str, Depends(get_api_key)]):
    """
    Returns core analytics data and conversion summaries from the chatbot logs.
    Requires 'x-api-key' header for authentication.
    """
    return fetch_analytics_data()

@app.get("/api/leads/high-potential", response_model=List[LeadContact], tags=["Leads"])
async def get_high_potential_leads(authenticated: Annotated[str, Depends(get_api_key)]):
    """
    Returns a list of leads who submitted contact information and have a score >= 4.
    Requires 'x-api-key' header for authentication.
    """
    return fetch_high_potential_leads(HIGH_POTENTIAL_THRESHOLD)


if __name__ == "__main__":
    import uvicorn
    # FIX: Use port 8001 as specified in the requirements for non-Streamlit
    FASTAPI_PORT = 8001 
    print("\n--- FastAPI Analytics API ---")
    print(f"🔑 Your required API Key (ANALYTICS_API_KEY): {API_KEY}")
    print(f"🚀 Running API at http://127.0.0.1:{FASTAPI_PORT}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host="0.0.0.0", port=FASTAPI_PORT, log_level="info")