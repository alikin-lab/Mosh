CQ_API_BASE = "https://api.carrotquest.io"

POPUP_SELECTORS = {
    "cq_constructor": ".popup-block-container",   # inside carrot-popup-frame iframe
    "js_popup": "#popup-card",                    # JS popup, hidden via .hidden CSS class
    "bot_notification": ".cq-wrapper",             # inside carrot-messenger-tooltip iframe
}

POPUP_LABELS = {
    "cq_constructor": "CQ Попап (конструктор)",
    "js_popup": "JS Попап",
    "bot_notification": "Нотификация / правый виджет",
}

# Broad selectors used in --debug mode to discover real popup HTML structure
DEBUG_SELECTORS = [
    "[class*='popup']",
    "[class*='modal']",
    "[class*='dialog']",
    "[class*='overlay']",
    "[class*='notification']",
    "[class*='widget']",
    "[class*='banner']",
    "[class*='cq-']",
    "[class*='carrot']",
    "[data-resize-popup]",
    "[data-resize-notification]",
    "[id*='popup']",
    "[id*='modal']",
    "[id*='notification']",
]

RAPID_SUCCESSION_THRESHOLD_SEC = 60
POLL_INTERVAL_SEC = 0.5
CQ_INIT_WAIT_SEC = 3

# Окно для бага по таймингам отправки (CQ API):
# два РАЗНЫХ попапа, отправленных в пределах этого окна — "одновременная отправка".
SEND_CONCURRENT_WINDOW_SEC = 15
