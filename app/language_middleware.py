"""
Multilingual Middleware Module: Handles language detection and translation
for the RAG pipeline using googletrans.
"""
import logging
from googletrans import Translator, LANGUAGES
from .Day_19_A import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_FAIL_MESSAGE, LANGUAGE_MAP

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

    def detect_language(self, text: str) -> str:
        """
        Detects the language of the input text.
        Returns the language code if supported, otherwise returns the default code ('en').
        """
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
            translation = self.translator.translate(text, src=detected_lang_code, dest=self.default_code)
            logging.info(f"Translated query from {detected_lang_code} to English.")
            return translation.text, detected_lang_code
        except Exception as e:
            logging.error(f"Translation to English failed: {e}. Returning original text and error message.")
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
            # Use 'auto' as source to let googletrans confirm the English source text
            translation = self.translator.translate(text, src='auto', dest=dest_lang)
            logging.info(f"Translated answer to {LANGUAGE_MAP.get(dest_lang, dest_lang)}.")
            return translation.text
        except Exception as e:
            logging.error(f"Translation from English failed for {dest_lang}: {e}")
            return LANGUAGE_FAIL_MESSAGE
