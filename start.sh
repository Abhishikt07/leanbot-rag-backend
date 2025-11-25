#!/usr/bin/env bash

# ---- Leanext Chatbot Production Start Script ----

echo "Starting Leanext RAG Chatbot Backend..."

# Start FastAPI using Gunicorn + Uvicorn workers
exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --bind 0.0.0.0:$PORT
