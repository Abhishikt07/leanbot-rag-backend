#!/bin/bash
echo "Starting Leanext RAG FastAPI Backend..."

# Ensure Python uses correct PATH
export PYTHONUNBUFFERED=1

# Render exposes your assigned port in $PORT
if [ -z "$PORT" ]; then
  export PORT=8000
fi

echo "➡ Listening on PORT: $PORT"

# Start FastAPI app
uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
