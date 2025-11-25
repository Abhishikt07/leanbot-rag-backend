#!/bin/bash

echo "Starting Leanext RAG Chatbot Backend..."

# Playwright installation (only needs to run during build)
# Remove this line from start.sh if you don't need Playwright at runtime
# playwright install --with-deps

# Start FastAPI server with Gunicorn
exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:$PORT \
    --timeout 300 \
    --workers 1
