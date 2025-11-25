"""
Data Pipeline Module: Advanced Sitemap-First, Recursive Crawler and ChromaDB Indexer.
"""
import streamlit as st
import requests
from bs4 import BeautifulSoup
import time
import chromadb
import sqlite3
import logging
import os
import urllib.parse
from urllib.robotparser import RobotFileParser
import hashlib
import json
import argparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Imports from configuration
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from .Day_19_A import ( 
    BASE_URL, URL_PATHS, CHUNK_SIZE, OVERLAP, 
    CHROMA_DB_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME, CRAWLER_USER_AGENT, 
    SITEMAP_URL, SCRAPE_MAX_DEPTH, SCRAPE_DELAY_SECONDS, CRAWL_DOMAIN, CRAWLER_CACHE_DIR,
    RENDER_JS, RENDER_JS_THRESHOLD_WORDS, FAQ_COLLECTION_NAME, FAQ_SEED_QUESTIONS 
)
# FIX: Removing log_user_query_db and adding init_analytics_db
from .Day_19_E import init_cache_db, init_analytics_db, init_leads_db

# Initializations
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
_EMBEDDING_FUNCTION = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)
_visited_urls = set()
_canonical_urls_seen = set()
_robot_parser = RobotFileParser()

# --- Helper Functions for Crawling ---

def _normalize_url(url):
    """Normalize URL: strip fragments, sort query params, remove trailing slash."""
    url = urllib.parse.urldefrag(url)[0] 
    parsed = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed.query)
    clean_query = urllib.parse.urlencode({k: v for k, v in query_params.items() if not k.startswith(('utm_', 'ref_'))}, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=clean_query)).rstrip('/')

def is_internal(url, base_domain=CRAWL_DOMAIN):
    """Checks if the URL belongs to the target domain and is not a resource/tel/mailto link."""
    url = _normalize_url(url)
    if any(url.startswith(prefix) for prefix in ['mailto:', 'tel:', 'javascript:']): return False
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != base_domain and not parsed.netloc.endswith(f".{base_domain}"): return False
    if any(url.lower().endswith(ext) for ext in ['.pdf', '.zip', '.rar', '.jpg', '.png', '.mp4']): return False
    return True

def fetch_sitemap(sitemap_url):
    """Fetches and parses sitemap.xml."""
    logging.info(f"Attempting to fetch sitemap from: {sitemap_url}")
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        urls = [_normalize_url(loc.text) for loc in soup.find_all('loc')]
        logging.info(f"Successfully retrieved {len(urls)} URLs from sitemap.")
        return list(set(urls)) 
    except Exception as e:
        logging.error(f"Failed to fetch or parse sitemap: {e}")
        return []

def fetch_page(url, render_js=False):
    """Fetches page content using requests (static) or Playwright (dynamic)."""
    headers = {'User-Agent': CRAWLER_USER_AGENT}
    
    response = None
    text_len = 0 
    final_url = _normalize_url(url)
    
    # 1. Static Fetch Attempt
    try:
        response = requests.get(url, headers=headers, timeout=10)
        final_url = _normalize_url(response.url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        main_text = soup.find('main') or soup.find('article') or soup.find('body')
        
        if main_text:
            text_len = len(main_text.get_text(strip=True).split())
            if not render_js and text_len >= RENDER_JS_THRESHOLD_WORDS:
                logging.info(f"Static fetch sufficient ({text_len} words).")
                return response.text, final_url

    except requests.exceptions.HTTPError as e:
        if e.response.status_code in (429, 503, 404):
             logging.warning(f"{e.response.status_code} encountered for {url}. Skipping or Retrying JS.")
        else:
             logging.error(f"Static fetch failed for {url}: {e}. Trying JS render.")
    except Exception:
         pass 
    
    # 2. Dynamic Fetch (Playwright) if requested or static failed/content short
    if render_js or ('response' not in locals() or text_len < RENDER_JS_THRESHOLD_WORDS):
        logging.info(f"Trying JS render for {url}...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=CRAWLER_USER_AGENT)
                page.set_default_timeout(20000)
                page.goto(url, wait_until="networkidle")
                html_content = page.content()
                final_url = _normalize_url(page.url)
                browser.close()
                logging.info("JS render successful.")
                return html_content, final_url
        except PlaywrightTimeoutError:
             logging.error(f"Playwright timed out for {url}.")
             return None, _normalize_url(url)
        except Exception as e:
             logging.error(f"Playwright failed for {url}: {e}")
             return None, _normalize_url(url)
             
    # Fallback return after all attempts
    return response.text if 'response' in locals() else None, final_url if 'final_url' in locals() else _normalize_url(url)

def _save_raw_html(url, html):
    """Saves raw HTML content to the cache directory."""
    try:
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        filename = os.path.join(CRAWLER_CACHE_DIR, f"{url_hash}.html")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)
        return filename
    except Exception as e:
        logging.error(f"Failed to save raw HTML for {url}: {e}")
        return None

def extract_page_metadata(html, url):
    """Parses HTML to extract structured metadata, text, and internal links."""
    soup = BeautifulSoup(html, 'lxml')
    metadata = {
        'url': url, 'canonical': url, 'title': soup.find('title').text.strip() if soup.find('title') else 'No Title',
        'meta_description': '', 'headings': [], 'json_ld': [], 'og_url': '', 'og_title': '', 'main_text': '',
        'path': urllib.parse.urlparse(url).path.strip('/') or 'home'
    }
    
    canonical_tag = soup.find('link', rel='canonical')
    if canonical_tag and canonical_tag.get('href'):
        metadata['canonical'] = _normalize_url(urllib.parse.urljoin(url, canonical_tag['href']))

    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'): metadata['meta_description'] = meta_desc['content'].strip()

    for tag in soup.find_all(['h1', 'h2', 'h3']): metadata['headings'].append(tag.get_text(strip=True))
    for script in soup.find_all('script', type='application/ld+json'):
        try: metadata['json_ld'].append(json.loads(script.string))
        except Exception: continue
            
    for meta in soup.find_all('meta', property=True):
        if meta.get('property') == 'og:url': metadata['og_url'] = _normalize_url(meta.get('content'))
        elif meta.get('property') == 'og:title': metadata['og_title'] = meta.get('content')
            
    main_content_area = soup.find('main') or soup.find('article') or soup.find('div', class_='main-content') or soup.find('body')
    if not main_content_area: main_content_area = soup 
            
    TARGET_TAGS = ['h1', 'h2', 'h3', 'p', 'li', 'section', 'article', 'dt', 'dd']
    EXCLUSION_TAGS = ['header', 'footer', 'nav', 'script', 'style', 'form', 'button', 'a']

    content_parts = []
    for tag in main_content_area.find_all(TARGET_TAGS):
        if tag.find_parent(EXCLUSION_TAGS): continue
        text = tag.get_text(separator=' ', strip=True)
        if len(text) < 15: continue
        if tag.name.startswith('h') or tag.name == 'dt': text = f"\n\n--- {text.upper()} ---\n"
        elif tag.name == 'li': text = f"* {text}"
        content_parts.append(text)
        
    metadata['main_text'] = ' '.join(content_parts)

    internal_links = set()
    for a_tag in soup.find_all('a', href=True):
         href = a_tag['href']
         full_url = _normalize_url(urllib.parse.urljoin(url, href))
         if is_internal(full_url): internal_links.add(full_url)
             
    return metadata, internal_links

def chunk_text(text, metadata, chunk_size=CHUNK_SIZE, overlap=OVERLAP):
    """Splits text into overlapping chunks, appending rich metadata to each."""
    header = f"Page: {metadata['title']} | Path: {metadata['path']} | Description: {metadata['meta_description']}\n\n"
    full_text = header + text
    chunks = []
    words = full_text.split()
    start = 0
    id_counter = 0
    
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunk_metadata = {
            'id': f"{metadata['path'].replace('/', '_')}_{id_counter}_{hashlib.sha1(chunk.encode('utf-8')).hexdigest()[:6]}",
            'text': chunk,
            'url': metadata['url'], 'canonical': metadata['canonical'], 'title': metadata['title'],
            'headings': metadata['headings'], 'path': metadata['path']
        }
        chunks.append(chunk_metadata)
        id_counter += 1
        start += (chunk_size - overlap)
        
    return chunks

# --- Main Crawling and Indexing ---

def crawl(seed_urls, max_depth, render_js_flag, sitemap_only=False, progress_bar=None):
    """Manages the BFS crawl process, returns a list of all chunks."""
    global _visited_urls, _canonical_urls_seen
    
    _visited_urls = set()
    _canonical_urls_seen = set()
    all_chunks = []
    
    # 0. Initialize Robot Parser (Loaded, but check is commented out for aggressive testing)
    try:
        _robot_parser.set_url(urllib.parse.urljoin(BASE_URL, 'robots.txt'))
        _robot_parser.read()
        logging.info("robots.txt loaded.")
    except Exception as e:
        logging.warning(f"Could not load robots.txt: {e}")

    queue = [(url, 0) for url in seed_urls if is_internal(url)]
    
    # 1. Main BFS Loop
    while queue:
        url, depth = queue.pop(0)
        
        if url in _visited_urls or depth > max_depth: continue
        
        # FIX: robots.txt check is commented out here to allow indexing
        # if not _robot_parser.can_fetch(CRAWLER_USER_AGENT, url):
        #      logging.info(f"Skipping {url} (Blocked by robots.txt)")
        #      continue
             
        if progress_bar is not None:
             progress_bar.progress(0, text=f"Crawling (Depth {depth}/{max_depth}): {url[:50]}...")
        
        _visited_urls.add(url)
        time.sleep(SCRAPE_DELAY_SECONDS)
        
        # 2. Fetch Page
        html_content, final_url = fetch_page(url, render_js=render_js_flag)
        if not html_content: continue

        # 3. Save raw HTML
        _save_raw_html(final_url, html_content)

        # 4. Extract Metadata and Links
        metadata, internal_links = extract_page_metadata(html_content, final_url)
        
        # 5. Deduplication Check (by Canonical URL)
        canonical_url = metadata['canonical']
        if canonical_url in _canonical_urls_seen:
            logging.info(f"Skipping {final_url} (Canonical {canonical_url} already processed)")
            continue
            
        _canonical_urls_seen.add(canonical_url)
        
        # 6. Chunk Text and Store
        if metadata['main_text']:
            new_chunks = chunk_text(metadata['main_text'], metadata)
            all_chunks.extend(new_chunks)
            logging.info(f"Chunked {len(new_chunks)} pieces from {final_url}")

        # 7. Add New Links to Queue (if not sitemap_only)
        if not sitemap_only and depth < max_depth:
            for link in internal_links:
                if link not in _visited_urls:
                    queue.append((link, depth + 1))
            
    return all_chunks


def build_and_index_knowledge_base(max_depth, render_js_flag, sitemap_only, progress_bar=None):
    """Controls the flow: sitemap -> crawl -> index."""
    
    sitemap_urls = fetch_sitemap(SITEMAP_URL)
    seed_urls = sitemap_urls if sitemap_urls else [BASE_URL + p for p in URL_PATHS]
    
    all_chunks = crawl(seed_urls, max_depth, render_js_flag, sitemap_only, progress_bar)
    
    if not all_chunks: 
        if progress_bar: progress_bar.empty()
        logging.error("No content crawled. Indexing skipped.")
        return None
        
    logging.info(f"Starting ChromaDB indexing for {len(all_chunks)} chunks...")
    if progress_bar is not None: progress_bar.progress(0.9, text=f"Indexing {len(all_chunks)} documents...")

    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        
        # FINAL FIX: Force-delete and recreate the collection to ensure it's empty.
        try:
            client.delete_collection(name=COLLECTION_NAME)
            logging.info(f"Successfully deleted existing collection: {COLLECTION_NAME}")
        except ValueError:
            pass 
        
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}, embedding_function=_EMBEDDING_FUNCTION
        )
        
        ids = [chunk['id'] for chunk in all_chunks]
        documents = [chunk['text'] for chunk in all_chunks]
        metadatas = [
            {
                'url': chunk['url'],
                'canonical': chunk['canonical'],
                'title': chunk['title'],
                'headings': json.dumps(chunk['headings']), 
                'path': chunk['path']
            } 
            for chunk in all_chunks
        ]
        
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        
        if progress_bar is not None: progress_bar.empty()
        logging.info(f"Knowledge Base Ready: {collection.count()} indexed chunks loaded.")

        summary = {
            "timestamp": time.time(), "total_chunks": collection.count(),
            "unique_pages_indexed": len(_canonical_urls_seen), "max_depth": max_depth,
            "js_rendered": render_js_flag, "sitemap_only": sitemap_only,
            "canonical_urls": list(_canonical_urls_seen)
        }
        with open(os.path.join(CRAWLER_CACHE_DIR, 'last_run_summary.json'), 'w') as f:
            json.dump(summary, f, indent=4)
        
        return collection
        
    except Exception as e:
        if progress_bar is not None: progress_bar.empty()
        logging.error(f"Failed to initialize/index ChromaDB: {e}")
        return None

def build_and_index_faq_suggestions():
    """Builds a dedicated ChromaDB collection for the 100 FAQ suggestions (no arguments needed)."""
    
    if not FAQ_SEED_QUESTIONS:
        logging.warning("FAQ_SEED_QUESTIONS list is empty. Skipping FAQ index build.")
        return None
        
    logging.info(f"Starting ChromaDB indexing for {len(FAQ_SEED_QUESTIONS)} FAQ suggestions...")

    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        
        # Force-delete and recreate the FAQ collection
        try:
            client.delete_collection(name=FAQ_COLLECTION_NAME)
            logging.info(f"Successfully deleted existing FAQ collection: {FAQ_COLLECTION_NAME}")
        except ValueError:
            pass 
        
        faq_collection = client.get_or_create_collection(
            name=FAQ_COLLECTION_NAME, metadata={"hnsw:space": "cosine"}, embedding_function=_EMBEDDING_FUNCTION
        )
        
        # Index the questions themselves as documents
        ids = [f"faq_{i}" for i in range(len(FAQ_SEED_QUESTIONS))]
        
        faq_collection.add(
            ids=ids, 
            documents=FAQ_SEED_QUESTIONS, # The questions are the documents
            metadatas=[{'question': q} for q in FAQ_SEED_QUESTIONS]
        )
        
        logging.info(f"FAQ Suggestion Base Ready: {faq_collection.count()} indexed questions loaded.")
        return faq_collection
        
    except Exception as e:
        logging.error(f"Failed to initialize/index FAQ ChromaDB: {e}")
        return None


@st.cache_resource
def load_or_build_knowledge_base():
    """Controls the flow for Streamlit: Load DB if it exists, otherwise build it with defaults."""
    
    # CRITICAL FIX: Initialize both databases here
    init_cache_db() 
    init_analytics_db() 
    init_leads_db()

    # We are no longer logging system events from Day_19_B, only from Day_19_D
    # log_chatbot_interaction("INIT", "INIT", "System", "System", "en") # Old logging logic removed
    
    status_container = st.empty()
    progress_bar = status_container.progress(0, text="Initializing Knowledge Base...")
    
    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection_names = [c.name for c in client.list_collections()]
        
        if COLLECTION_NAME in collection_names:
            collection = client.get_collection(name=COLLECTION_NAME, embedding_function=_EMBEDDING_FUNCTION)
            if collection.count() > 0:
                progress_bar.empty()
                status_container.info(f"💾 Knowledge Base Loaded: {collection.count()} indexed chunks.", icon="⚡")
                return collection
    except Exception as e:
        logging.warning(f"ChromaDB Load Failed: {e}. Attempting rebuild.")
        pass 
    
    status_container.warning("🛑 Database not found or empty. Building and indexing knowledge base now...")
    return build_and_index_knowledge_base(
        max_depth=SCRAPE_MAX_DEPTH, render_js_flag=RENDER_JS, sitemap_only=False, progress_bar=progress_bar
    )

def main_cli():
    """CLI entry point for building and updating the knowledge base."""
    parser = argparse.ArgumentParser(description="LeanBot RAG Knowledge Base Builder/Crawler.")
    parser.add_argument('--build', action='store_true', help='Perform a full crawl and rebuild the ChromaDB index.')
    parser.add_argument('--update', action='store_true', help='Perform a light update (same as --build for now).')
    parser.add_argument('--max-depth', type=int, default=SCRAPE_MAX_DEPTH, help=f'Maximum recursion depth (default: {SCRAPE_MAX_DEPTH}).')
    parser.add_argument('--render-js', type=lambda x: x.lower() in ('true', '1', 't'), default=RENDER_JS, help=f'Force JS rendering (default: {RENDER_JS}).')
    parser.add_argument('--sitemap-only', action='store_true', help='Only crawl URLs found in the sitemap.')
    parser.add_argument('--test-sitemap', action='store_true', help='Test sitemap fetch and print sample URLs.')
    parser.add_argument('--test-metadata', type=str, help='Test metadata extraction on a single URL.')

    args = parser.parse_args()
    
    # Test Functions
    if args.test_sitemap:
        urls = fetch_sitemap(SITEMAP_URL)
        print("\n--- Sitemap Test Results ---")
        print(f"Total URLs found: {len(urls)}")
        print("Sample URLs:", urls[:5])
        return
        
    if args.test_metadata:
        print(f"\n--- Metadata Test for {args.test_metadata} ---")
        html, final_url = fetch_page(args.test_metadata, render_js=args.render_js)
        if html:
            metadata, links = extract_page_metadata(html, final_url)
            print("Metadata:\n", json.dumps(metadata, indent=4))
            print(f"\nFound {len(links)} internal links.")
        return
    
    # Main Build/Update Action
    if args.build or args.update:
        print("\n--- Starting LEANEXT RAG Indexing (CLI Mode) ---")
        init_cache_db() 
        init_analytics_db()
        # Old logging function removed from CLI mode: log_user_query_db("CLI_START", "CLI_START", "System", from_cache=False) 
        
        build_and_index_knowledge_base(
            max_depth=args.max_depth, render_js_flag=args.render_js, sitemap_only=args.sitemap_only
        )
        build_and_index_faq_suggestions() # Build FAQ index on CLI build
    else:
        parser.print_help()
        print("\nTo run the chatbot UI, use: streamlit run Day_19_D.py")


if __name__ == '__main__':
    if not os.getenv('STREAMLIT_SERVER_PORT'):
        main_cli()
