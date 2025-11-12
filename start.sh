#!/bin/bash

# --- 1. Database Initialization (Ephemeral Logs/Leads/Cache) ---
# NOTE: Data in these DBs is LOST on container restart/redeploy.
echo "Initializing ephemeral SQLite logs/leads/cache DBs..."
python3 -c "from Day_19_E import init_cache_db, init_analytics_db, init_leads_db; init_cache_db(); init_analytics_db(); init_leads_db()"

# --- 2. RAG Knowledge Base Check/Build (Uses Persistent Disk) ---
# KB_PATH MUST match the CHROMA_DB_PATH constant in Day_19_A.py
KB_PATH="chroma_db_leanext" 

# Check if the RAG KB folder exists on the mounted Render Persistent Disk
if [ ! -d "$KB_PATH" ]; then
    echo "⚠️ RAG Knowledge Base NOT found. Starting full build (SLOW!)."
    # Build ChromaDB and FAQ index (builds to the mounted disk path)
    python3 -c "from Day_19_B import build_and_index_knowledge_base, build_and_index_faq_suggestions; build_and_index_knowledge_base(max_depth=3, render_js_flag=False, sitemap_only=False); build_and_index_faq_suggestions()"
else
    echo "✅ RAG Knowledge Base found on persistent disk. Skipping build."
fi

# --- 3. Run FastAPI with Gunicorn/Uvicorn ---
# Runs the main FastAPI application (FastAPI_Analytics:app)
gunicorn -w 4 -k uvicorn.workers.UvicornWorker FastAPI_Analytics:app --bind 0.0.0.0:$PORT