#!/bin/bash

echo "Starting Leanext RAG FastAPI Backend..."

# Render sets PORT automatically
export PORT=${PORT:-8000}

echo "➡ Listening on PORT: $PORT"

# Run the FastAPI app inside app/main.py
gunicorn app.main:app \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:$PORT
