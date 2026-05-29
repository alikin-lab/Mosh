from datetime import datetime
from typing import Optional

from .popup_detector import Bug, PopupEvent
from .browser_session import NavEntry
from .config import POPUP_LABELS


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


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
        lines += ["---", "## ✅ Багов не обнаружено", ""]

    # Chronology
    lines += ["---", "## 📋 Хронология событий", ""]
    lines += ["| Время | Событие |", "|-------|---------|"]

    # Merge nav log + popup events sorted by timestamp
    all_rows: list[tuple[float, str]] = []
    for nav in nav_log:
        label = f"Переход: {nav.url}" if nav.url else "Скролл страницы"
        all_rows.append((nav.timestamp, label))
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
        lines += ["**Последние события из API:**", "", "| Время | Тип события |", "|-------|-------------|"]
        for ev in api_events[:20]:
            created = ev.get("created", "")
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%H:%M:%S")
            except Exception:
                pass
            lines.append(f"| {created} | `{ev.get('type', '—')}` |")
    else:
        lines.append("_События не получены (пользователь не идентифицирован или ошибка API)_")

    return "\n".join(lines)
