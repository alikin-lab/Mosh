CQ_API_BASE = "https://api.carrotquest.io"

POPUP_SELECTORS = {
    "cq_constructor": "[data-resize-popup]",
    "js_popup": ".cq-popup__body",
    "bot_notification": "[data-resize-notification]",
}

POPUP_LABELS = {
    "cq_constructor": "CQ Попап (конструктор)",
    "js_popup": "JS Попап",
    "bot_notification": "Нотификация бота",
}

RAPID_SUCCESSION_THRESHOLD_SEC = 60
POLL_INTERVAL_SEC = 0.5
CQ_INIT_WAIT_SEC = 3
