"""
Smoke Check: Verifies core project imports and connectivity to the FastAPI health endpoint.
"""
import requests
import logging
import os
from Day_21_A import ANALYTICS_API_KEY # Load the key generated in .env
from Day_21_D import init_session_state, get_greeting # Test Streamlit UI imports
from Day_21_C import calculate_conversion_score # Test core logic imports

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def check_fastapi_health(port: int = 8001):
    """Checks the /api/health endpoint of the FastAPI application."""
    url = f"http://localhost:{port}/api/health"
    headers = {"X-API-Key": ANALYTICS_API_KEY} if ANALYTICS_API_KEY else {}
    
    logging.info(f"Checking FastAPI health at {url}...")
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        if data.get("status") == "ok":
            logging.info("✅ FastAPI Health Check: SUCCESS")
            logging.info(f"   Message: {data.get('message')}")
            return True
        else:
            logging.error(f"❌ FastAPI Health Check: FAILED (Status not 'ok'): {data}")
            return False
            
    except requests.exceptions.ConnectionError:
        logging.error(f"❌ FastAPI Health Check: FAILED (Connection Error). Is the API running on port {port}?")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ FastAPI Health Check: FAILED (Request Error): {e}")
        return False

def check_project_imports():
    """Checks for core project file imports."""
    logging.info("Checking core project imports...")
    try:
        # Imports already handled by the file structure, confirming a function from each
        _ = calculate_conversion_score("test query", 1)
        logging.info(f"   Conversion Score Test: OK (Result: {_})")
        _ = get_greeting()
        logging.info(f"   Streamlit UI Import Test: OK (Greeting: {_[:10]}...)")
        
        # Test an import that relies on the SQLite utility from Day_21_E
        from Day_21_E import check_lead_saved
        _ = check_lead_saved("dummy_user_id_check")
        logging.info("   SQLite/DB Utility Import Test: OK")

        logging.info("✅ All core imports successful.")
        return True
    except Exception as e:
        logging.error(f"❌ Core Imports FAILED: {e}")
        return False


if __name__ == "__main__":
    if check_project_imports():
        print("\n--- Running Smoke Check ---\n")
        # Note: FastAPI must be running on port 8001 for this check to pass
        check_fastapi_health(port=8001)
        print("\n--- Smoke Check Complete ---")
        print("To run the full project:\n1. python Day_21_B.py --build\n2. uvicorn Day_21_F_Analytics:app --port 8001 --reload\n3. streamlit run Day_21_D.py")