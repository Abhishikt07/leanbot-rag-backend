// embed.js
// Loader for Leanext Chat Widget: reads data-* attributes and initializes widget.js

(function () {
  function initFromScriptTag() {
    const script = document.currentScript;
    if (!script) return;

    const backendUrl  = script.getAttribute("data-backend-url") || null;
    const brandColor  = script.getAttribute("data-brand-color") || "#0f6ad8";
    const showOnLoad  =
      (script.getAttribute("data-show-on-load") || "false").toLowerCase() === "true";
    const debugMode   =
      (script.getAttribute("data-debug") || "false").toLowerCase() === "true";

    const widgetJsUrl = script.getAttribute("data-widget-js") || "widget.js";
    const cssUrl      = script.getAttribute("data-css-url") || "widget.css";

    const suggestedFaqsAttr = script.getAttribute("data-suggested-faqs") || "[]";
    const fullFaqsAttr      = script.getAttribute("data-full-faqs") || "[]";

    let suggestedFaqs = [];
    let fullFaqs = [];
    try {
      suggestedFaqs = JSON.parse(suggestedFaqsAttr);
      fullFaqs = JSON.parse(fullFaqsAttr);
    } catch (e) {
      console.warn("Failed to parse FAQ data attributes", e);
    }

    function loadWidgetAndInit() {
      if (window.LeanextChatWidget) {
        window.LeanextChatWidget.init({
          backendUrl,
          brandColor,
          showOnLoad,
          debugMode,
          cssUrl,
          suggestedFaqs,
          fullFaqs
        });
        return;
      }

      const scriptEl = document.createElement("script");
      scriptEl.src = widgetJsUrl;
      scriptEl.async = true;
      scriptEl.onload = function () {
        if (window.LeanextChatWidget) {
          window.LeanextChatWidget.init({
            backendUrl,
            brandColor,
            showOnLoad,
            debugMode,
            cssUrl,
            suggestedFaqs,
            fullFaqs
          });
        } else {
          console.error("LeanextChatWidget not found after loading widget.js");
        }
      };
      document.head.appendChild(scriptEl);
    }

    if (document.readyState === "complete" || document.readyState === "interactive") {
      loadWidgetAndInit();
    } else {
      document.addEventListener("DOMContentLoaded", loadWidgetAndInit);
    }
  }

  initFromScriptTag();
})();
