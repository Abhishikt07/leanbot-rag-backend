#!/usr/bin/env bash

# --- Configuration ---
# This path MUST match the directory where ChromaDB saves its files (CHROMA_DB_PATH from Day_19_A.py)
DB_PATH="chroma_db_leanext" 

# --- 1. Persistence Check and Build ---
echo "Checking for existing RAG vector database at $DB_PATH..."
if [ ! -d "$DB_PATH" ] || [ ! -f "$DB_PATH/chroma.sqlite3" ]
then
    echo "Vector database NOT FOUND or incomplete. Initiating slow build process..."
    # The Day_19_B.py main_cli with --build flag saves data to DB_PATH
    python3 Day_19_B.py --build
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Vector build failed. Exiting deployment."
        exit 1
    fi
    echo "Vector database build complete and saved to Persistent Disk."
else
    echo "Vector database found on Persistent Disk. Skipping rebuild."
fi

# --- 2. Start the FastAPI Analytics Service ---
# The service will run Day_19_D.py for the Chatbot and FastAPI_Analytics.py for the API
# We start the Analytics API here, assuming your main RAG API is in Day_19_D (or the main chatbot UI).
echo "Starting FastAPI Analytics application..."
# Run the API using Gunicorn. The -w 4 sets 4 worker processes.
gunicorn -w 4 -k uvicorn.workers.UvicornWorker FastAPI_Analytics:app --bind 0.0.0.0:$PORT