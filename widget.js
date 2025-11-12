/**
 * widget.js - Single-file, embeddable, vanilla JavaScript Chatbot Widget.
 * Connects to a FastAPI-based Multilingual RAG Backend.
 *
 * Configuration is read from the embedding script tag's data attributes:
 * - data-api (required): Base URL of the FastAPI endpoint (e.g., https://api.mycompany.com)
 * - data-title (optional): Widget title (default: "Ask Our AI Assistant 🤖")
 * - data-primary (optional): Primary color hex (default: #2563eb)
 * - data-welcome (optional): First bot message (default: "Hi! How can I help?")
 * - data-enable-leads (optional): 'true' to show the lead contact form (default: false)
 */

(function () {
    // --- 1. Configuration & Initialization ---

    const SCRIPT_ID = 'leanext-chatbot-widget-script';
    const WIDGET_ROOT_ID = 'mcw-chatbot-widget-root';
    const API_TIMEOUT_MS = 15000;

    // Attempt to find the script tag that loaded this file
    const scriptEl = document.getElementById(SCRIPT_ID) || document.currentScript;

    if (!scriptEl) {
        console.error('Chatbot Widget failed to find its script element.');
        return;
    }

    const API_BASE_URL = scriptEl.getAttribute('data-api');
    if (!API_BASE_URL) {
        console.error('Chatbot Widget requires the "data-api" attribute on the script tag.');
        return;
    }

    const CONFIG = {
        api: API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL,
        title: scriptEl.getAttribute('data-title') || 'Ask Our AI Assistant 🤖',
        primaryColor: scriptEl.getAttribute('data-primary') || '#2563eb',
        welcomeMessage: scriptEl.getAttribute('data-welcome') || "Hi! How can I help you navigate Leanext's services today?",
        enableLeads: scriptEl.getAttribute('data-enable-leads') === 'true',
    };

    let isWidgetOpen = false;
    let isAwaitingResponse = false;
    let isApiHealthy = true;

    // --- 2. Utility & Helper Functions ---

    /** Creates an HTML element with optional class name and attributes. */
    const createEl = (tag, className, attributes = {}) => {
        const el = document.createElement(tag);
        if (className) el.className = className;
        for (const key in attributes) {
            el.setAttribute(key, attributes[key]);
        }
        return el;
    };

    /** Basic HTML escaping to prevent XSS. */
    const escapeHTML = (str) => {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    /** Scrolls the message area to the bottom with animation. */
    const scrollToBottom = () => {
        const messagesEl = document.getElementById('mcw-messages');
        if (messagesEl) {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }
    };

    /** Debounces a function call. */
    const debounce = (func, delay) => {
        let timeoutId;
        return function (...args) {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => {
                func.apply(this, args);
            }, delay);
        };
    };

    /** Fetches with a timeout. */
    const fetchWithTimeout = (resource, options = {}) => {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);

        return fetch(resource, {
            ...options,
            signal: controller.signal
        }).then(response => {
            clearTimeout(timeoutId);
            return response;
        }).catch(error => {
            clearTimeout(timeoutId);
            throw error;
        });
    };

    // --- 3. UI Construction and Styling ---

    const injectStyles = () => {
        const style = createEl('style', null, { id: 'mcw-injected-styles' });
        style.textContent = `
            :root {
                --mcw-primary-color: ${CONFIG.primaryColor};
            }
            #${WIDGET_ROOT_ID} {
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 2147483647; /* Max z-index */
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            }

            /* --- WIDGET BUBBLE (CLOSED STATE) --- */
            .mcw-bubble {
                width: 50px;
                height: 50px;
                background-color: var(--mcw-primary-color);
                border-radius: 50%;
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
                transition: transform 0.3s ease-in-out;
            }
            .mcw-bubble:hover {
                transform: scale(1.05);
            }
            .mcw-bubble-icon {
                font-size: 24px;
                /* Unicode chat icon */
            }

            /* --- CHAT WINDOW (OPEN STATE) --- */
            .mcw-window {
                position: absolute;
                bottom: 0;
                right: 0;
                width: 380px;
                height: 520px;
                border-radius: 12px;
                box-shadow: 0 8px 30px rgba(0, 0, 0, 0.2);
                background-color: white;
                display: flex;
                flex-direction: column;
                overflow: hidden;
                transform: scale(0);
                transform-origin: bottom right;
                transition: transform 0.3s cubic-bezier(0.2, 0.6, 0.4, 1.1);
            }
            .mcw-window.mcw-open {
                transform: scale(1);
            }
            
            /* --- HEADER --- */
            .mcw-header {
                padding: 15px 20px;
                background-color: var(--mcw-primary-color);
                color: white;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-shrink: 0;
                cursor: default;
            }
            .mcw-header-title {
                font-size: 16px;
                font-weight: 600;
            }
            .mcw-header-close {
                background: none;
                border: none;
                color: white;
                font-size: 24px;
                line-height: 1;
                cursor: pointer;
                padding: 0;
            }

            /* --- MESSAGES AREA --- */
            .mcw-messages {
                flex-grow: 1;
                padding: 15px;
                overflow-y: auto;
                background-color: #f7f9fc;
            }
            .mcw-message {
                display: flex;
                margin-bottom: 15px;
            }
            .mcw-message.mcw-user {
                justify-content: flex-end;
            }
            .mcw-message.mcw-bot {
                justify-content: flex-start;
            }
            .mcw-bubble-content {
                max-width: 80%;
                padding: 10px 15px;
                border-radius: 18px;
                line-height: 1.4;
                font-size: 14px;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
            }
            .mcw-message.mcw-user .mcw-bubble-content {
                background-color: var(--mcw-primary-color);
                color: white;
                border-bottom-right-radius: 2px;
            }
            .mcw-message.mcw-bot .mcw-bubble-content {
                background-color: #e5e5e5;
                color: #333;
                border-bottom-left-radius: 2px;
            }
            
            /* Sources/Links */
            .mcw-sources {
                margin-top: 10px;
                padding-top: 5px;
                border-top: 1px solid rgba(0,0,0,0.1);
            }
            .mcw-sources p {
                font-size: 11px;
                font-weight: 600;
                margin: 0 0 5px 0;
                color: #555;
            }
            .mcw-sources a {
                display: block;
                font-size: 12px;
                color: var(--mcw-primary-color);
                text-decoration: none;
                margin-bottom: 3px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            /* --- FOOTER/INPUT AREA --- */
            .mcw-footer {
                padding: 10px 15px;
                border-top: 1px solid #e0e0e0;
                flex-shrink: 0;
            }
            .mcw-input-area {
                display: flex;
                align-items: flex-end;
                gap: 8px;
            }
            .mcw-input-area textarea {
                flex-grow: 1;
                border: 1px solid #ccc;
                border-radius: 8px;
                padding: 8px;
                resize: none;
                font-size: 14px;
                max-height: 100px;
                line-height: 1.4;
                box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.06);
            }
            .mcw-input-area button {
                background-color: var(--mcw-primary-color);
                border: none;
                border-radius: 8px;
                color: white;
                padding: 8px 10px;
                cursor: pointer;
                transition: background-color 0.2s;
                font-size: 18px;
                height: 38px;
                width: 38px;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }
            .mcw-input-area button:hover:not(:disabled) {
                background-color: var(--mcw-primary-color);
                filter: brightness(1.1);
            }
            .mcw-input-area button:disabled {
                background-color: #b0b0b0;
                cursor: not-allowed;
            }
            
            /* Loading Spinner (minimal CSS) */
            .mcw-spinner {
                border: 2px solid rgba(255, 255, 255, 0.3);
                border-top: 2px solid white;
                border-radius: 50%;
                width: 14px;
                height: 14px;
                animation: mcw-spin 1s linear infinite;
                display: none; /* Controlled by JS */
            }
            @keyframes mcw-spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            .mcw-loading-state .mcw-spinner { display: block; }
            .mcw-loading-state .mcw-send-icon { display: none; }

            /* --- API Status Banner --- */
            .mcw-api-error {
                background-color: #ffcccc;
                color: #cc0000;
                padding: 8px;
                text-align: center;
                font-size: 12px;
                border-top: 1px solid #ff9999;
                flex-shrink: 0;
            }
            
            /* --- Leads Form --- */
            .mcw-leads-toggle {
                text-align: right;
                margin-top: 5px;
            }
            .mcw-leads-toggle button {
                background: none;
                border: none;
                color: var(--mcw-primary-color);
                font-size: 12px;
                cursor: pointer;
                padding: 0;
            }
            .mcw-leads-form {
                margin: 10px 0 5px 0;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 8px;
                background-color: #fff;
            }
            .mcw-leads-form input {
                width: 100%;
                padding: 5px;
                margin-bottom: 5px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 13px;
                box-sizing: border-box;
            }
            .mcw-leads-form-button {
                width: 100%;
                background-color: var(--mcw-primary-color);
                color: white;
                border: none;
                padding: 8px;
                border-radius: 6px;
                cursor: pointer;
                margin-top: 5px;
            }
            .mcw-leads-form-button:disabled {
                 background-color: #b0b0b0;
            }
            .mcw-lead-error {
                color: #cc0000;
                font-size: 11px;
                margin-top: 5px;
            }

            /* --- MOBILE ADAPTATION --- */
            @media (max-width: 600px) {
                #${WIDGET_ROOT_ID} {
                    bottom: 0;
                    right: 0;
                    width: 100%;
                    height: 100%;
                }
                .mcw-window {
                    width: 100%;
                    height: 100vh;
                    border-radius: 0;
                }
            }
        `;
        document.head.appendChild(style);
    };

    const setupDOM = () => {
        // 1. Root Container
        const root = createEl('div', null, { id: WIDGET_ROOT_ID });
        document.body.appendChild(root);

        // 2. Chat Window
        const chatWindow = createEl('div', 'mcw-window', { id: 'mcw-window' });
        root.appendChild(chatWindow);

        // 3. Header
        const header = createEl('div', 'mcw-header');
        header.innerHTML = `
            <div class="mcw-header-title">${escapeHTML(CONFIG.title)}</div>
            <button class="mcw-header-close" id="mcw-close-btn" aria-label="Minimize Chat">–</button>
        `;
        chatWindow.appendChild(header);

        // 4. API Error Banner (hidden by default)
        const errorBanner = createEl('div', 'mcw-api-error', { id: 'mcw-api-error', style: 'display: none;' });
        errorBanner.textContent = 'Connection Error: API is currently unavailable.';
        chatWindow.appendChild(errorBanner);

        // 5. Messages Area
        const messages = createEl('div', 'mcw-messages', { id: 'mcw-messages' });
        chatWindow.appendChild(messages);

        // 6. Footer (Input/Send)
        const footer = createEl('div', 'mcw-footer');

        // Leads Form (Optional)
        if (CONFIG.enableLeads) {
            const leadsToggle = createEl('div', 'mcw-leads-toggle');
            leadsToggle.innerHTML = `<button id="mcw-leads-toggle-btn">Send Contact Details</button>`;
            footer.appendChild(leadsToggle);

            const leadsForm = createEl('div', 'mcw-leads-form', { id: 'mcw-leads-form', style: 'display: none;' });
            leadsForm.innerHTML = `
                <input type="text" id="mcw-lead-name" placeholder="Your Name *" required>
                <input type="email" id="mcw-lead-email" placeholder="Email">
                <input type="tel" id="mcw-lead-phone" placeholder="Phone (optional)">
                <p class="mcw-lead-error" id="mcw-lead-error"></p>
                <button id="mcw-leads-submit-btn" class="mcw-leads-form-button">Submit Lead</button>
            `;
            footer.appendChild(leadsForm);
        }

        const inputArea = createEl('div', 'mcw-input-area');
        inputArea.innerHTML = `
            <textarea id="mcw-input-textarea" rows="1" placeholder="Type your message..." aria-label="Chat Input"></textarea>
            <button id="mcw-send-btn">
                <span class="mcw-send-icon" title="Send">➤</span>
                <div class="mcw-spinner"></div>
            </button>
        `;
        footer.appendChild(inputArea);
        chatWindow.appendChild(footer);

        // 7. Floating Bubble
        const bubble = createEl('div', 'mcw-bubble', { id: 'mcw-bubble' });
        bubble.innerHTML = `<span class="mcw-bubble-icon" aria-label="Open Chat">💬</span>`;
        root.appendChild(bubble);

        return { root, chatWindow, bubble, messages, header, inputArea, footer, errorBanner };
    };

    // --- 4. Main Widget Logic ---

    const toggleOpen = () => {
        const bubble = document.getElementById('mcw-bubble');
        const windowEl = document.getElementById('mcw-window');

        if (!bubble || !windowEl) return;

        isWidgetOpen = !isWidgetOpen;

        // Toggle the window's visibility via the CSS transition class
        windowEl.classList.toggle('mcw-open', isWidgetOpen);

        // Accessibility and Bubble Icon Change (simple text icon change)
        bubble.innerHTML = isWidgetOpen ? '<span class="mcw-bubble-icon" aria-label="Close Chat">X</span>' : '<span class="mcw-bubble-icon" aria-label="Open Chat">💬</span>';

        if (isWidgetOpen) {
            scrollToBottom();
            document.getElementById('mcw-input-textarea').focus();
        }
    };

    const renderMessage = (sender, text, sources = []) => {
        const messagesEl = document.getElementById('mcw-messages');
        const messageEl = createEl('div', `mcw-message mcw-${sender}`);
        const contentEl = createEl('div', 'mcw-bubble-content');

        // Simple line break replacement for presentation
        let formattedText = escapeHTML(text).replace(/\n/g, '<br>');

        if (sender === 'bot' && sources.length > 0) {
            let sourcesHTML = '<div class="mcw-sources"><p>Related Sources:</p>';
            sources.slice(0, 3).forEach(source => { // Limit to top 3 sources
                sourcesHTML += `<a href="${escapeHTML(source.url)}" target="_blank" title="${escapeHTML(source.title)}">${escapeHTML(source.title)}</a>`;
            });
            sourcesHTML += '</div>';
            formattedText += sourcesHTML;
        }

        contentEl.innerHTML = formattedText;
        messageEl.appendChild(contentEl);
        messagesEl.appendChild(messageEl);

        scrollToBottom();
    };

    const toggleInputState = (loading) => {
        const windowEl = document.getElementById('mcw-window');
        const textarea = document.getElementById('mcw-input-textarea');
        const sendBtn = document.getElementById('mcw-send-btn');

        isAwaitingResponse = loading;
        textarea.disabled = loading;
        sendBtn.disabled = loading;

        windowEl.classList.toggle('mcw-loading-state', loading);
    };

    const showApiError = (show) => {
        const errorBanner = document.getElementById('mcw-api-error');
        if (errorBanner) {
            isApiHealthy = !show;
            errorBanner.style.display = show ? 'block' : 'none';
        }
    };

    const sendLead = (e) => {
        e.preventDefault();

        const nameInput = document.getElementById('mcw-lead-name');
        const emailInput = document.getElementById('mcw-lead-email');
        const phoneInput = document.getElementById('mcw-lead-phone');
        const submitBtn = document.getElementById('mcw-leads-submit-btn');
        const errorEl = document.getElementById('mcw-lead-error');

        const name = nameInput.value.trim();
        const email = emailInput.value.trim();
        const phone = phoneInput.value.trim();

        if (!name) {
            errorEl.textContent = 'Name is required.';
            return;
        }
        if (!email && !phone) {
            errorEl.textContent = 'Either email or phone is required.';
            return;
        }

        errorEl.textContent = 'Submitting...';
        submitBtn.disabled = true;

        const leadPayload = {
            name: name,
            email: email,
            phone: phone,
            source: 'web-widget',
            meta: {
                userAgent: navigator.userAgent,
                pageUrl: window.location.href
            }
        };

        fetchWithTimeout(`${CONFIG.api}/leads`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(leadPayload)
        })
            .then(response => response.json())
            .then(data => {
                if (data && data.ok) {
                    errorEl.textContent = 'Success! A consultant will contact you.';
                    // Hide the form on success
                    document.getElementById('mcw-leads-form').style.display = 'none';
                    document.getElementById('mcw-leads-toggle-btn').style.display = 'none';
                } else {
                    errorEl.textContent = 'Submission failed. Try again or call us.';
                }
            })
            .catch(() => {
                errorEl.textContent = 'Server error during submission. Try again later.';
            })
            .finally(() => {
                submitBtn.disabled = false;
                // Clear inputs after 5 seconds to allow user to see success
                setTimeout(() => {
                    if (errorEl.textContent.includes('Success')) {
                        nameInput.value = ''; emailInput.value = ''; phoneInput.value = '';
                    }
                    errorEl.textContent = '';
                }, 5000);
            });
    };

    const sendQuery = () => {
        const textarea = document.getElementById('mcw-input-textarea');
        const query = textarea.value.trim();

        if (!query || isAwaitingResponse) return;

        // 1. Render user message
        renderMessage('user', query);
        textarea.value = '';
        textarea.style.height = 'auto'; // Reset height
        toggleInputState(true);

        // 2. API Call
        fetchWithTimeout(`${CONFIG.api}/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        })
            .then(response => {
                showApiError(false); // Clear previous error
                if (!response.ok) {
                    return response.json().catch(() => ({})).then(err => { throw new Error(err.detail || `Server error: ${response.status}`); });
                }
                return response.json();
            })
            .then(data => {
                const botAnswer = data.answer || 'Sorry, I encountered an issue generating a response.';
                const sources = data.sources || [];
                renderMessage('bot', botAnswer, sources);
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    renderMessage('bot', 'The server took too long to respond. Please try again.');
                } else if (error.message.includes('Failed to fetch')) {
                    renderMessage('bot', 'Network or API server is unavailable. Please check the connection.');
                    showApiError(true);
                } else {
                    renderMessage('bot', `An unexpected error occurred: ${error.message}`);
                }
                console.error('API Query Error:', error);
            })
            .finally(() => {
                toggleInputState(false);
            });
    };


    // --- 5. Event Listeners and Initial Run ---

    const attachEventListeners = () => {
        const root = document.getElementById(WIDGET_ROOT_ID);
        const bubble = document.getElementById('mcw-bubble');
        const closeBtn = document.getElementById('mcw-close-btn');
        const sendBtn = document.getElementById('mcw-send-btn');
        const textarea = document.getElementById('mcw-input-textarea');

        if (!root || !bubble || !closeBtn || !sendBtn || !textarea) return;

        // Bubble Click
        bubble.addEventListener('click', toggleOpen);
        closeBtn.addEventListener('click', toggleOpen);

        // Outside Click (to close the window)
        document.addEventListener('click', (e) => {
            if (isWidgetOpen && !root.contains(e.target)) {
                // Check if the click is outside the root container
                toggleOpen();
            }
        });

        // Keyboard events on textarea
        textarea.addEventListener('keydown', (e) => {
            // Send on Enter, Newline on Shift+Enter
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendQuery();
            }
        });

        // Auto-resize textarea
        textarea.addEventListener('input', () => {
            textarea.style.height = 'auto';
            textarea.style.height = textarea.scrollHeight + 'px';
        });

        // Send Button Click
        sendBtn.addEventListener('click', sendQuery);

        // Leads Form Listeners
        if (CONFIG.enableLeads) {
            const leadsToggleBtn = document.getElementById('mcw-leads-toggle-btn');
            const leadsForm = document.getElementById('mcw-leads-form');
            const leadsSubmitBtn = document.getElementById('mcw-leads-submit-btn');

            leadsToggleBtn.addEventListener('click', () => {
                const isVisible = leadsForm.style.display === 'block';
                leadsForm.style.display = isVisible ? 'none' : 'block';
            });
            leadsSubmitBtn.addEventListener('click', sendLead);
        }
    };

    // Initial Health Check
    const checkHealth = () => {
        fetchWithTimeout(`${CONFIG.api}/health`, { method: 'GET' })
            .then(response => {
                if (!response.ok) throw new Error('Health check failed');
                return response.json();
            })
            .then(data => {
                if (data && data.status === 'ok') {
                    showApiError(false);
                } else {
                    throw new Error('Health check status not ok');
                }
            })
            .catch(() => {
                showApiError(true);
            });
    };


    // --- Bootstrap Function ---
    const initWidget = () => {
        if (document.getElementById(WIDGET_ROOT_ID)) {
            console.warn('Chatbot widget already initialized.');
            return;
        }

        injectStyles();
        setupDOM();
        attachEventListeners();

        // 1. Initial health check
        checkHealth();

        // 2. Add welcome message
        if (CONFIG.welcomeMessage) {
            renderMessage('bot', CONFIG.welcomeMessage);
        }

        // 3. Debounce API health check (e.g., every 60 seconds)
        setInterval(checkHealth, 60000);
    };

    // Wait for the DOM to be fully loaded before injecting the widget
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initWidget);
    } else {
        initWidget();
    }

})();

/*
<script 
    id="leanext-chatbot-widget-script"
    src="https://cdn.mycompany.com/widget.js" 
    data-api="https://api.mycompany.com" 
    data-title="Leanext AI Chatbot"
    data-primary="#1d4ed8"
    data-welcome="Hello! I'm LeanBot, ask me about our Lean Six Sigma training or consulting services."
    data-enable-leads="true">
</script>
*/