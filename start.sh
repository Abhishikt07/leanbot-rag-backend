#!/bin/bash

echo "Starting Leanext RAG Chatbot Backend..."

# Render always provides $PORT - we MUST bind to it
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers 1 \
    --timeout-keep-alive 75
