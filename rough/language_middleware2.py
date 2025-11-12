"""
Multilingual Middleware Module: Handles language detection and translation
for the RAG pipeline using googletrans.
"""
import logging
import unicodedata # NEW: For query normalization
from googletrans import Translator, LANGUAGES
from Day_21_A import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_FAIL_MESSAGE, LANGUAGE_MAP

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LanguageTranslator:
    """
    Handles translation between supported Indian languages and English for the RAG pipeline.
    Uses the free googletrans library.
    """
    def __init__(self):
        """Initializes the Translator instance."""
        self.translator = Translator()
        self.supported_codes = SUPPORTED_LANGUAGES
        self.default_code = DEFAULT_LANGUAGE

    def normalize_query(self, text: str) -> str:
        """NEW: Applies Unicode normalization to the query text for robust RAG."""
        if not text:
            return ""
        # Apply NFC (Normalization Form C) for composite characters
        return unicodedata.normalize('NFC', text).strip()


    def detect_language(self, text: str) -> str:
        """
        Detects the language of the input text.
        Returns the language code if supported, otherwise returns the default code ('en').
        """
        text = self.normalize_query(text)
        if not text:
            return self.default_code
            
        try:
            # First, check if the text is short or simple, which can confuse auto-detectors
            if len(text.strip()) < 5:
                # If it's a very short input, we assume it's English for RAG clarity
                return self.default_code
                
            detection = self.translator.detect(text)
            detected_code = detection.lang
            
            # Googletrans often returns a generic code (e.g., 'mr' for Marathi)
            # Check if the detected code is in our supported list
            if detected_code in self.supported_codes:
                return detected_code
            
            # Fallback to English if not a supported language
            logging.warning(f"Detected language '{detected_code}' not in supported list. Defaulting to 'en'.")
            return self.default_code

        except Exception as e:
            logging.error(f"Language detection failed: {e}. Defaulting to 'en'.")
            return self.default_code

    def translate(self, text: str, src: str, dest: str) -> str:
        """
        NEW: Generic translation wrapper.
        Translates text from src to dest. Returns the translated text.
        """
        text = self.normalize_query(text)
        if not text or src == dest:
            return text
            
        try:
            translation = self.translator.translate(text, src=src, dest=dest)
            logging.info(f"Translated from {src} to {dest}.")
            return translation.text
        except Exception as e:
            logging.error(f"Generic translation failed from {src} to {dest}: {e}")
            return text # Return original text on failure


    def to_english(self, text: str) -> tuple[str, str]:
        """
        Translates text to English for the RAG engine.
        Returns a tuple: (translated_text, detected_language_code).
        """
        detected_lang_code = self.detect_language(text)
        
        if detected_lang_code == self.default_code:
            # No translation needed if already English
            return text, self.default_code
        
        try:
            # FIX: Use the generic translate function
            translated_text = self.translate(text, src=detected_lang_code, dest=self.default_code)
            return translated_text, detected_lang_code
            
        except Exception as e:
            logging.error(f"Translation to English failed: {e}. Returning original text and error flag.")
            # If translation fails, return the original text and an error flag for handling
            return text, f"ERROR-{detected_lang_code}" 

    def from_english(self, text: str, dest_lang: str) -> str:
        """
        Translates an English answer back to the destination language.
        Returns the translated answer or an error message on failure.
        """
        if dest_lang == self.default_code or not dest_lang:
            return text
            
        try:
            # FIX: Use the generic translate function
            translated_text = self.translate(text, src='auto', dest=dest_lang)
            logging.info(f"Translated answer to {LANGUAGE_MAP.get(dest_lang, dest_lang)}.")
            return translated_text
            
        except Exception as e:
            logging.error(f"Translation from English failed for {dest_lang}: {e}")
            return LANGUAGE_FAIL_MESSAGE