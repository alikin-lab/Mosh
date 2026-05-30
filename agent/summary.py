"""
Сводный отчёт по серии прогонов.

Собирает все JSON-отчёты из папки (reports/<клиент>/*.json) в одну сводку:
общая статистика, таблица по сценариям, уникальные баги, отправленные попапы.

Использование:
    python -m agent.summary reports/bitrix
    python -m agent.summary reports/bitrix --out reports/bitrix/SUMMARY.md
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

from .validate import validate_report, VALID, FABRICATED, NO_USER_ID


def _load_reports(folder: str) -> list[dict]:
    reports = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        if os.path.basename(path) == "SUMMARY.json":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                reports.append(json.load(f))
        except Exception as e:
            print(f"[warn] не удалось прочитать {path}: {e}")
    return reports


def build_summary(reports: list[dict]) -> str:
    if not reports:
        return "_Нет отчётов для сводки._"

    reports = sorted(reports, key=lambda r: r.get("started_at", ""))
    site = next((r.get("site_url") for r in reports if r.get("site_url")), "—")
    date = (reports[0].get("started_at", "") or "")[:10]

    # Страж целостности: отсеиваем сочинённые агентом отчёты до подсчёта статистики.
    verdicts = {id(r): validate_report(r)[0] for r in reports}
    fabricated = [r for r in reports if verdicts[id(r)] == FABRICATED]

    def has_send_bug(r):
        return len(r.get("send_bugs", [])) > 0

    total = len(reports)
    dom_bugs = [r for r in reports if verdicts[id(r)] != FABRICATED and r.get("bug_count", 0) > 0]
    send_signal = [r for r in reports if verdicts[id(r)] != FABRICATED and has_send_bug(r)]
    clean = [r for r in reports if verdicts[id(r)] == VALID
             and r.get("bug_count", 0) == 0 and not has_send_bug(r)]
    invalid = [r for r in reports if verdicts[id(r)] == NO_USER_ID]

    lines = [
        "# 📊 Сводный отчёт тестирования попапов",
        "",
    ]

    # Баннер о фабрикации — наверх, чтобы продакт не доверял подделанным данным.
    if fabricated:
        bad = ", ".join(r.get("scenario_id") or "—" for r in fabricated)
        lines += [
            "> ❌ **ВНИМАНИЕ: обнаружена фабрикация отчётов.** "
            f"{len(fabricated)} из {total} отчётов НЕ являются выводом реального прогона "
            f"(`{bad}`). Статистике ниже доверять нельзя — нужен честный перепрогон через "
            "`python -m agent.run_suite`. Подробности: `python -m agent.validate <папка>`.",
            "",
        ]

    lines += [
        f"**Сайт:** {site}",
        f"**Дата:** {date}",
        f"**Сценариев прогнано:** {total}",
        f"**С DOM-багами:** {len(dom_bugs)} · **С сигналом отправки (API):** {len(send_signal)} · "
        f"**Чисто:** {len(clean)} · **Невалидных (нет user_id):** {len(invalid)} · "
        f"**Фабрикаций:** {len(fabricated)}",
        "",
        "---",
        "## Результаты по сценариям",
        "",
        "| Сценарий | Длит. | DOM-баги | Сигнал отправки | Вовлечённые попапы | Карточка |",
        "|----------|-------|----------|-----------------|--------------------|----------|",
    ]

    for r in reports:
        sid = r.get("scenario_id") or "—"
        dur = f"{r.get('duration_sec', 0)} c"
        bc = r.get("bug_count", 0)
        if verdicts[id(r)] == FABRICATED:
            bug_cell = "❌ фейк"
        elif verdicts[id(r)] == NO_USER_ID:
            bug_cell = "⚠️ невалид"
        elif bc:
            bug_cell = f"🔴 {bc}"
        else:
            bug_cell = "✅ 0"
        sb = r.get("send_bugs", [])
        send_cell = f"🟠 {len(sb)}" if sb else "—"
        popups = set()
        for b in r.get("bugs", []):
            popups.update(b.get("popups_involved", []))
        for b in sb:
            popups.update(b.get("popups", []))
        popups_cell = ", ".join(sorted(popups)) if popups else "—"
        card = f"[ссылка]({r['card_url']})" if r.get("card_url") else "—"
        lines.append(f"| {sid} | {dur} | {bug_cell} | {send_cell} | {popups_cell} | {card} |")

    # Уникальные баги
    lines += ["", "---", "## Уникальные баги", ""]
    bug_key = Counter()
    bug_example = {}
    for r in reports:
        for b in r.get("bugs", []):
            key = (b.get("type"), tuple(sorted(b.get("popups_involved", []))))
            bug_key[key] += 1
            bug_example.setdefault(key, b)
    if bug_key:
        for (btype, popups), cnt in bug_key.most_common():
            name = "Наложение попапов" if btype == "overlap" else "Быстрое повторное появление"
            lines.append(f"- 🔴 **{name}** (DOM) — {', '.join(popups)} · воспроизведён в {cnt} сценариях")
    else:
        lines.append("_DOM-багов не обнаружено._")

    # Уникальные сигналы по таймингам отправки (CQ API)
    send_key = Counter()
    for r in reports:
        for b in r.get("send_bugs", []):
            key = (b.get("type"), tuple(sorted(b.get("popups", []))))
            send_key[key] += 1
    if send_key:
        lines += ["", "**По таймингам отправки (CQ API):**", ""]
        for (btype, popups), cnt in send_key.most_common():
            if btype == "send_concurrent":
                lines.append(f"- 🟠 **Одновременная отправка** — {', '.join(popups)} · в {cnt} сценариях")
            else:
                lines.append(f"- 🟠 **Повторная отправка** — {', '.join(popups)} · в {cnt} сценариях")

    # Отправленные попапы (по всем сценариям)
    lines += ["", "---", "## Отправленные попапы/сообщения (по всем прогонам)", ""]
    send_names = Counter()
    for r in reports:
        for s in r.get("popup_sends", []):
            send_names[s.get("name", "—")] += 1
    if send_names:
        lines += ["| Попап/сообщение | Раз отправлено |", "|-----------------|----------------|"]
        for nm, cnt in send_names.most_common():
            lines.append(f"| {nm} | {cnt} |")
    else:
        lines.append("_Событий отправки попапов не зафиксировано._")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Сводный отчёт по серии прогонов")
    parser.add_argument("folder", help="Папка с JSON-отчётами (например reports/bitrix)")
    parser.add_argument("--out", default=None, help="Куда сохранить сводку (.md)")
    args = parser.parse_args()

    reports = _load_reports(args.folder)
    summary = build_summary(reports)

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"[summary] Сохранено: {args.out}")

    print(summary)


if __name__ == "__main__":
    main()
