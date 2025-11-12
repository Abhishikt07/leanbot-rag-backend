"""
Configuration file: Centralizes all constants, file paths, model names, and API setup.
This file should contain no operational logic.
"""
from dotenv import load_dotenv
import os

# Load environment variables (like GEMINI_API_KEY, ANALYTICS_API_KEY) from .env file
load_dotenv()

# --- Website and Data Paths ---
BASE_URL = "https://leanextconsulting.com/"
URL_PATHS = [
    "", "capabilities", "about", "softwares", 
    "privacypolicy", "termsandcondition", "consulting", 
    "career", "contact",
    "trainings", "sixsigma", "leanmaster"
]
CHROMA_DB_PATH = "chroma_db_leanext" 
COLLECTION_NAME = "leanext_website_data"

# --- CRAWLING / SCRAPING CONFIGURATION ---
SITEMAP_URL = "https://leanextconsulting.com/sitemap.xml"
SCRAPE_MAX_DEPTH = 3           
SCRAPE_DELAY_SECONDS = 0.5     
RENDER_JS = False              
RENDER_JS_THRESHOLD_WORDS = 80 
CRAWLER_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" 
CRAWL_DOMAIN = "leanextconsulting.com"
CRAWLER_CACHE_DIR = "crawler_cache"
if not os.path.exists(CRAWLER_CACHE_DIR):
    os.makedirs(CRAWLER_CACHE_DIR)

# --- CACHE and LOGGING Configuration ---
CACHE_DB_PATH = "chat_cache.db"
CACHE_MATCH_THRESHOLD = 0.85
ANALYTICS_DB_PATH = "chatbot_logs.db" 
LEADS_DB_PATH = "leads.db" # Database for lead capture
RELATED_QS_LIMIT = 5

# --- CONVERSION AND LEAD SCORING ---
HIGH_INTENT_KEYWORDS = [
    "demo", "pricing", "cost", "consulting", "training", "schedule", 
    "quote", "trial", "implementation", "contact sales", "enquire"
]
MAX_CONVERSION_SCORE = 5
HIGH_POTENTIAL_THRESHOLD = 4
CONVERSION_SCORE_MAP = {
    5: ("🔥 Hot Lead", "red"),
    4: ("⭐ High Potential", "orange"),
    3: ("💡 Exploring", "yellow"),
    2: ("❓ Curious", "blue"),
    1: ("👋 Visitor", "gray"),
}


# --- RAG and Embedding Parameters ---
CHUNK_SIZE = 300               
OVERLAP = 80                   
TOP_K_CHUNKS = 5        
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2' 
AUTOCOMPLETE_K = 10
QUERY_PREDICTION_THRESHOLD = 0.35 
UNCLEAR_QUERY_THRESHOLD = 0.65  
FAQ_COLLECTION_NAME = "leanext_faq_suggestions" # New collection for FAQ index

# --- LLM Models and API Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
MODEL_CLOUD = "gemini-2.5-flash-preview-05-20"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_CLOUD}:generateContent?key={GEMINI_API_KEY}"

# --- FEATURE 1: MULTILINGUAL CONFIGURATION ---
# Supported languages for auto-detection and translation
SUPPORTED_LANGUAGES = ["en", "hi", "mr", "kn", "bn", "gu"] 
DEFAULT_LANGUAGE = "en"
LANGUAGE_MAP = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", 
    "kn": "Kannada", "bn": "Bengali", "gu": "Gujarati", "default": "English"
}
LANGUAGE_FAIL_MESSAGE = "Sorry, I encountered an issue with language translation. Please try again in English or another supported language."

# --- FEATURE 2: ANALYTICS API CONFIGURATION ---
ANALYTICS_API_KEY = os.getenv("ANALYTICS_API_KEY")

# --- Prompts and Fallbacks ---
GEMINI_RAG_SYSTEM_PROMPT = (
    "You are a helpful, professional chatbot for Leanext Consulting. "
    "Answer clearly and conversationally, based ONLY on the provided CONTEXT. "
    "If a related landing page exists, provide its link. Be concise and professional. "
    "Crucially: Your response MUST be in English. It will be translated by a service later."
)
CLEANING_SYSTEM_PROMPT = (
    "You are a spelling and grammar correction expert. "
    "Take the user's text, correct all typos, spelling errors, and awkward phrasing. "
    "Your response MUST contain ONLY the corrected, cleaned, and syntactically perfect query, "
    "with no explanation or introductory text."
)
FINAL_FALLBACK_MESSAGE = "I've checked our internal knowledge base, but I couldn't find a definitive answer to your question right now. Please try rephrasing."
UNCLEAR_QUERY_RESPONSE = "I'm not entirely sure what you meant. Did you mean one of these?"


# --- Small Talk Triggers ---
SMALL_TALK_TRIGGERS = {
    "how are you": "I’m doing great, thanks for asking! I'm here to help you navigate Leanext's services.",
    "who are you": "I’m LeanBot, your AI assistant from Leanext Consulting—here to answer questions and guide you through our programs.",
    "what can you do": "I can answer your questions about Leanext’s services, provide information about our training programs, and find relevant links for you!",
    "your name": "You can call me LeanBot 😊",
    "tell me a joke": "Sure! Why did the data scientist go broke? Because he lost all his cache!",
    "hello": "Hello! It's wonderful to meet you. How can I assist you with Leanext Consulting today?"
}


# --- UI and FAQ Configuration ---
SUGGESTED_FAQS = [
    "What services does Leanext offer?", "How can I apply for a career at Leanext?", 
    "What is Leanext’s Lean Master training?", "Tell me about the software solutions.", 
    "Where is Leanext Consulting located?", "What are the terms and conditions?"
]

# --- Full List of 100 Questions for the Suggestion Index ---
FAQ_SEED_QUESTIONS = [
    "What is Leanext Consulting?",
    "Where is Leanext Consulting based?",
    "What industries does Leanext serve?",
    "What services does Leanext Consulting provide?",
    "What makes Leanext different from other consulting firms?",
    "How long has Leanext been in operation?",
    "What is Leanext’s mission and vision?",
    "Who are Leanext’s major clients?",
    "How can I contact Leanext Consulting?",
    "Does Leanext Consulting operate internationally?",
    "What types of consulting services does Leanext offer?",
    "What is operational excellence consulting?",
    "What is business transformation consulting?",
    "How does Leanext improve manufacturing efficiency?",
    "What is Lean transformation?",
    "What are Leanext’s key consulting methodologies?",
    "Does Leanext provide digital transformation services?",
    "Can Leanext help reduce waste in production?",
    "What kind of cost reduction projects has Leanext done?",
    "How does Leanext measure consulting success?",
    "What is Lean Six Sigma?",
    "Does Leanext offer Lean Six Sigma certification programs?",
    "What are the levels of Six Sigma certification?",
    "What is DMAIC methodology?",
    "How do I enroll in Leanext’s Six Sigma courses?",
    "What is the duration of the Six Sigma Green Belt course?",
    "What is the difference between Green Belt and Black Belt?",
    "Are the Six Sigma certifications globally recognized?",
    "Does Leanext offer corporate Six Sigma training?",
    "Can I take the Six Sigma course online?",
    "What kind of professional training does Leanext provide?",
    "Does Leanext conduct in-person or online workshops?",
    "What are Leanext’s most popular training programs?",
    "How do I register for Leanext’s training sessions?",
    "Are Leanext’s trainers industry experts?",
    "Does Leanext provide customized corporate training?",
    "Is there any demo class before joining a training?",
    "Can Leanext provide on-site company training?",
    "How do I request a training brochure?",
    "What is the cost of Leanext’s training programs?",
    "Are there job openings at Leanext Consulting?",
    "How can I apply for an internship?",
    "What qualifications do I need to work with Leanext?",
    "Does Leanext provide certification for interns?",
    "What kind of projects do interns work on?",
    "Is Leanext hiring remote employees?",
    "What is the selection process for careers at Leanext?",
    "Are there opportunities for recent graduates?",
    "How do I know if my application is shortlisted?",
    "Who can I contact for HR-related queries?",
    "Where can I find Leanext’s privacy policy?",
    "How does Leanext protect my personal data?",
    "What are the website’s terms and conditions?",
    "How do I get in touch with customer support?",
    "What should I do if a link on the website doesn’t work?",
    "Does Leanext use cookies on the website?",
    "Can I unsubscribe from Leanext newsletters?",
    "Where can I find Leanext’s refund or cancellation policy?",
    "Does Leanext store my payment details?",
    "How do I report an issue with the website?",
    "How do I schedule a consulting appointment?",
    "Can I book a free demo session?",
    "What happens during a demo call?",
    "Can Leanext customize the consulting approach for my company?",
    "How long does a consultation typically last?",
    "What details do I need to provide when booking a demo?",
    "Who will conduct my consulting session?",
    "Can I reschedule my demo after booking?",
    "Are consulting appointments paid or free?",
    "Will I receive a confirmation email after booking?",
    "Hi there, how are you today?",
    "Can you tell me more about Leanext’s expertise?",
    "What services are best for startups?",
    "Can you recommend a Leanext course for beginners?",
    "What industries does Leanext specialize in?",
    "How can Leanext help my business improve productivity?",
    "Does Leanext provide training for individuals as well as corporates?",
    "What are some success stories from Leanext’s clients?",
    "Can you help me choose the right course?",
    "How do I contact the support team directly?",
    "What is Lean Manufacturing?",
    "How do Lean and Six Sigma differ?",
    "What is Kaizen in Lean methodology?",
    "What is the meaning of continuous improvement?",
    "What is value stream mapping?",
    "What is Lean 5S methodology?",
    "What are some Lean tools and techniques?",
    "What is the role of data analytics in Lean Six Sigma?",
    "What software tools does Leanext use for consulting?",
    "What industries benefit most from Lean Six Sigma?",
    "Can Leanext integrate IoT or AI solutions in manufacturing?",
    "Does Leanext help implement ERP systems?",
    "How does Leanext track project KPIs?",
    "What are Leanext’s digital transformation capabilities?",
    "What are Leanext’s proprietary frameworks?",
    "Can Leanext optimize supply chain processes?",
    "How does Leanext handle client data security?",
    "What is Leanext’s success rate in process improvement projects?",
    "Does Leanext offer post-consulting support?",
    "Can I partner with Leanext for a joint venture?"
]

URL_EXCLUSIONS = ["privacypolicy", "termsandcondition"]