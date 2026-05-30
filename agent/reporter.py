from datetime import datetime
from typing import Optional

from .popup_detector import Bug, PopupEvent
from .browser_session import NavEntry
from .config import POPUP_LABELS, RAPID_SUCCESSION_THRESHOLD_SEC, SEND_CONCURRENT_WINDOW_SEC


ACTION_LABELS = {
    "scroll": "Скролл страницы",
    "exit_intent": "Exit-intent (увод мыши)",
    "open_chat": "Открыт чат",
}


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _nav_label(nav: NavEntry) -> str:
    if nav.url:
        return f"Переход: {nav.url}"
    return ACTION_LABELS.get(nav.action, nav.action)


def _normalize_api_event(ev: dict) -> dict:
    """Приводит событие CQ API к виду {ts, time, name, is_popup_send, message_name}."""
    created = ev.get("created")
    try:
        ts = float(created)
        time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        ts, time_str = 0.0, str(created or "")

    t = ev.get("type")
    name = t.get("name") if isinstance(t, dict) else str(t)
    props = ev.get("props") or {}
    message_name = props.get("$message_name") or props.get("$message_part_name")

    # Событие "отправлен попап/сообщение": системное $chat_bot_sent или
    # пользовательское "Коммуникации: Отправлено сообщение - <название>"
    is_send = (name == "$chat_bot_sent") or ("Отправлено сообщение" in (name or ""))

    return {
        "ts": ts,
        "time": time_str,
        "name": name,
        "is_popup_send": is_send,
        "message_name": message_name,
    }


def _popup_send_label(norm: dict) -> str:
    """Чистое название отправленного попапа для отчёта."""
    if norm.get("message_name"):
        return norm["message_name"]
    name = norm.get("name") or ""
    if " - " in name:
        return name.split(" - ", 1)[1]
    if name == "$chat_bot_sent":
        return "Сообщение лид-бота"
    return name


def detect_send_bugs(
    api_events: list[dict],
    concurrent_window: float = SEND_CONCURRENT_WINDOW_SEC,
    resend_window: float = RAPID_SUCCESSION_THRESHOLD_SEC,
) -> list[dict]:
    """Баги по таймингам ОТПРАВКИ попапов (данные CQ API), независимо от DOM.

    - send_concurrent: два РАЗНЫХ попапа отправлены в пределах concurrent_window сек
      (риск наложения на стороне доставки).
    - send_rapid_resend: ОДИН и тот же попап отправлен повторно в пределах resend_window сек.
    """
    sends = sorted(
        (n for n in (_normalize_api_event(e) for e in api_events) if n["is_popup_send"]),
        key=lambda x: x["ts"],
    )
    bugs: list[dict] = []
    seen: set = set()

    for i in range(len(sends)):
        for j in range(i + 1, len(sends)):
            a, b = sends[i], sends[j]
            interval = b["ts"] - a["ts"]
            if interval > resend_window:
                break  # дальше только больше — выходим из внутреннего цикла
            na, nb = _popup_send_label(a), _popup_send_label(b)
            if na == nb:
                btype, key = "send_rapid_resend", ("resend", na)
                window = resend_window
            elif interval <= concurrent_window:
                btype, key = "send_concurrent", ("concurrent", frozenset((na, nb)))
                window = concurrent_window
            else:
                continue
            if key in seen:
                continue
            seen.add(key)
            bugs.append({
                "type": btype,
                "time": b["time"],
                "popups": [na] if na == nb else [na, nb],
                "interval_seconds": round(interval, 1),
                "threshold_seconds": window,
            })
    return bugs


def report_dict(
    site_url: str,
    app_id: str,
    bugs: list[Bug],
    popup_events: list[PopupEvent],
    nav_log: list[NavEntry],
    api_events: list[dict],
    session_start: float,
    session_end: float,
    user_id: Optional[str],
    card_url: Optional[str],
    scenario: str,
    scenario_id: Optional[str] = None,
) -> dict:
    """Структурированный отчёт — для парсинга агентами (продакт/тестировщик)."""
    return {
        "scenario_id": scenario_id,
        "scenario": scenario,
        "site_url": site_url,
        "app_id": app_id,
        "user_id": user_id,
        "card_url": card_url,
        "started_at": datetime.fromtimestamp(session_start).isoformat(),
        "duration_sec": int(session_end - session_start),
        "bug_count": len(bugs),
        "bugs": [
            {
                "type": b.bug_type,
                "timestamp": _fmt(b.timestamp),
                "description": b.description,
                "popups_involved": [POPUP_LABELS.get(p, p) for p in b.popups_involved],
                "interval_seconds": b.interval_seconds,
            }
            for b in bugs
        ],
        "popup_events": [
            {"timestamp": _fmt(e.timestamp), "event": e.event_type, "popup": e.label}
            for e in popup_events
        ],
        "nav_log": [
            {"timestamp": _fmt(n.timestamp), "action": n.action, "url": n.url}
            for n in nav_log
        ],
        "api_event_count": len(api_events),
        # Отправленные попапы/сообщения по данным CQ API: время + название
        "popup_sends": [
            {"time": n["time"], "name": _popup_send_label(n)}
            for n in sorted((_normalize_api_event(e) for e in api_events), key=lambda x: x["ts"])
            if n["is_popup_send"]
        ],
        # Баги по таймингам отправки (независимый от DOM сигнал)
        "send_bugs": detect_send_bugs(api_events),
    }


def generate_report(
    site_url: str,
    app_id: str,
    bugs: list[Bug],
    popup_events: list[PopupEvent],
    nav_log: list[NavEntry],
    api_events: list[dict],
    session_start: float,
    session_end: float,
    user_id: Optional[str],
    card_url: Optional[str],
    scenario: str,
) -> str:
    duration = int(session_end - session_start)
    lines = []

    # Header
    lines += [
        "## 🔍 Отчёт тестирования попапов",
        "",
        f"**Сайт:** {site_url}",
        f"**Сценарий:** {scenario}",
        f"**Дата:** {datetime.fromtimestamp(session_start).strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Длительность сессии:** {duration} сек",
        f"**ID пользователя CQ:** `{user_id}`" if user_id else "**ID пользователя CQ:** не определён",
        "",
    ]

    # Bugs
    if bugs:
        lines += [f"---", f"## 🐛 Найдено багов: {len(bugs)}", ""]
        for i, bug in enumerate(bugs, 1):
            is_rapid = bug.bug_type == "rapid_succession"
            name = "Быстрое повторное появление" if is_rapid else "Наложение попапов"
            emoji = "⚠️" if is_rapid else "🔴"
            involved = ", ".join(POPUP_LABELS.get(p, p) for p in bug.popups_involved)
            lines += [
                f"### {emoji} Баг {i}: {name}  [{_fmt(bug.timestamp)}]",
                f"- **{bug.description}**",
                f"- Попапы: {involved}",
            ]
            if bug.interval_seconds is not None:
                lines.append(f"- Интервал: {bug.interval_seconds:.1f} сек (порог: 60 сек)")
            lines.append("")
    else:
        lines += ["---", "## ✅ Багов по DOM не обнаружено", ""]

    # Баги по таймингам отправки (CQ API) — независимый сигнал
    send_bugs = detect_send_bugs(api_events)
    if send_bugs:
        lines += ["---", f"## 🟠 Сигналы по таймингам отправки (CQ API): {len(send_bugs)}", ""]
        for sb in send_bugs:
            if sb["type"] == "send_concurrent":
                lines.append(
                    f"- 🟠 **Одновременная отправка** [{sb['time']}]: «{sb['popups'][0]}» и "
                    f"«{sb['popups'][1]}» с разницей {sb['interval_seconds']} с "
                    f"(окно {sb['threshold_seconds']} с)"
                )
            else:
                lines.append(
                    f"- 🟠 **Повторная отправка** [{sb['time']}]: «{sb['popups'][0]}» "
                    f"повторно через {sb['interval_seconds']} с (порог {sb['threshold_seconds']} с)"
                )
        lines.append("")

    # Chronology
    lines += ["---", "## 📋 Хронология событий", ""]
    lines += ["| Время | Событие |", "|-------|---------|"]

    # Merge nav log + popup events sorted by timestamp
    all_rows: list[tuple[float, str]] = []
    for nav in nav_log:
        all_rows.append((nav.timestamp, _nav_label(nav)))
    for ev in popup_events:
        action = "Появился" if ev.event_type == "appeared" else "Закрыт"
        is_bug_moment = any(
            abs(b.timestamp - ev.timestamp) < 1.5 and ev.popup_type in b.popups_involved
            for b in bugs
        )
        suffix = " ⚠️ **БАГ**" if is_bug_moment else ""
        all_rows.append((ev.timestamp, f"{action}: {ev.label}{suffix}"))

    for ts, desc in sorted(all_rows, key=lambda x: x[0]):
        lines.append(f"| {_fmt(ts)} | {desc} |")

    lines.append("")

    # User card
    lines += ["---", "## 👤 Карточка пользователя", ""]
    if card_url:
        lines.append(f"🔗 [Открыть карточку в Carrot Quest]({card_url})")
        lines.append("")

    if api_events:
        norm = sorted((_normalize_api_event(e) for e in api_events), key=lambda x: x["ts"])
        sends = [n for n in norm if n["is_popup_send"]]

        # Отправленные попапы/сообщения — с таймингами и названиями
        lines += ["---", "## 📨 Отправленные попапы/сообщения (CQ API)", ""]
        if sends:
            lines += ["| Время | Название попапа/сообщения |", "|-------|---------------------------|"]
            for n in sends:
                lines.append(f"| {n['time']} | {_popup_send_label(n)} |")
        else:
            lines.append("_Событий отправки попапов в карточке не найдено._")
        lines.append("")

        # Полная лента событий из карточки
        lines += ["<details><summary>Все события из карточки</summary>", "",
                  "| Время | Событие |", "|-------|---------|"]
        for n in norm:
            mark = " 📨" if n["is_popup_send"] else ""
            lines.append(f"| {n['time']} | {n['name']}{mark} |")
        lines += ["", "</details>"]
    else:
        lines += ["---", "## 📨 События из карточки (CQ API)", "",
                  "_События не получены (пользователь не идентифицирован или ошибка API)_"]

    return "\n".join(lines)
