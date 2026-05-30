"""
Страж целостности отчётов (anti-fabrication guard).

Зачем: автономный LLM-агент-тестировщик может «сыграть роль» прогона и СОЧИНИТЬ
правдоподобный JSON-отчёт, не запуская реально test_runner (наблюдалось 2026-05-30:
выдуманные user_id=10001, поля status/popup_id, которых нет в коде). Этот модуль
отличает настоящий отчёт раннера от подделки по жёстким, трудноподделываемым признакам.

Использование:
    python -m agent.validate reports/bitrix.carrotquest.ru        # папка
    python -m agent.validate reports/bitrix.carrotquest.ru/x.json  # один файл

Код возврата: 0 — все отчёты валидны (или валидны/без user_id); 1 — найдена фабрикация
или папка пуста. Продакт-агент ОБЯЗАН прогонять валидатор перед доверием отчётам.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# Канонический набор ключей отчёта (см. reporter.report_dict). Любой ключ вне набора —
# сильный признак того, что отчёт сочинён, а не сгенерирован кодом.
ALLOWED_KEYS = {
    "generated_by", "schema_version",
    "scenario_id", "scenario", "site_url", "app_id", "user_id", "card_url",
    "started_at", "duration_sec", "bug_count", "bugs", "popup_events",
    "nav_log", "api_event_count", "popup_sends", "send_bugs",
}
# Ключи, без которых настоящий прогон невозможен (их пишет только раннер).
REQUIRED_KEYS = {
    "generated_by", "site_url", "app_id", "started_at", "duration_sec",
    "bug_count", "bugs", "popup_events", "nav_log", "api_event_count",
}

# Реальный CQ user_id — длинная строка из цифр (напр. "2248318978856322675").
# Целое 10001 или короткая строка — выдумка.
CQ_USER_ID_RE = re.compile(r"^\d{12,}$")

# Вердикты
VALID = "valid"            # настоящий отчёт, пользователь идентифицирован
NO_USER_ID = "no_user_id"  # настоящий прогон, но виджет не отдал user_id (нужен перезапуск)
FABRICATED = "fabricated"  # схема не похожа на вывод раннера → вероятно сочинено


def validate_report(report: dict) -> tuple[str, list[str]]:
    """Возвращает (вердикт, список причин). Вердикт — один из VALID/NO_USER_ID/FABRICATED."""
    reasons: list[str] = []

    if not isinstance(report, dict):
        return FABRICATED, ["отчёт не является JSON-объектом"]

    # 1. Чужие ключи (status, popup_id, ... — их нет в схеме раннера)
    foreign = set(report.keys()) - ALLOWED_KEYS
    if foreign:
        reasons.append(f"посторонние поля, которых нет в схеме раннера: {sorted(foreign)}")

    # 2. Отсутствуют обязательные поля
    missing = REQUIRED_KEYS - set(report.keys())
    if missing:
        reasons.append(f"отсутствуют обязательные поля раннера: {sorted(missing)}")

    # 3. Маркер происхождения
    if report.get("generated_by") != "agent.test_runner":
        reasons.append(f"нет/неверный маркер generated_by: {report.get('generated_by')!r}")

    # 4. started_at — настоящая ISO-метка времени
    started = report.get("started_at")
    if started is not None:
        try:
            datetime.fromisoformat(str(started))
        except (TypeError, ValueError):
            reasons.append(f"started_at не похож на ISO-время: {started!r}")

    # 5. Согласованность bug_count и bugs[]
    bugs = report.get("bugs")
    if isinstance(bugs, list) and isinstance(report.get("bug_count"), int):
        if report["bug_count"] != len(bugs):
            reasons.append(f"bug_count={report['bug_count']} не совпадает с len(bugs)={len(bugs)}")

    # Любая из вышеперечисленных проблем = структура не как у раннера → фабрикация
    if reasons:
        return FABRICATED, reasons

    # 6. user_id: реальный CQ id — строка из >=12 цифр. None → прогон был, но без id.
    uid = report.get("user_id")
    if uid is None:
        return NO_USER_ID, ["user_id отсутствует — CQ-виджет не инициализировался (нужен перезапуск с --no-headless)"]
    if isinstance(uid, bool) or not isinstance(uid, str) or not CQ_USER_ID_RE.match(uid):
        return FABRICATED, [f"user_id не похож на настоящий CQ id (ожидалась строка из >=12 цифр): {uid!r}"]

    return VALID, []


def validate_folder(folder: str) -> list[tuple[str, str, list[str]]]:
    """Валидирует все *.json в папке. Возвращает [(filename, verdict, reasons), ...]."""
    results = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        base = os.path.basename(path)
        if base in ("SUMMARY.json",):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except Exception as e:
            results.append((base, FABRICATED, [f"не удалось прочитать JSON: {e}"]))
            continue
        verdict, reasons = validate_report(report)
        results.append((base, verdict, reasons))
    return results


_ICON = {VALID: "✅ VALID", NO_USER_ID: "⚠️ NO_USER_ID", FABRICATED: "❌ FABRICATED"}


def main():
    parser = argparse.ArgumentParser(description="Страж целостности отчётов (anti-fabrication)")
    parser.add_argument("path", help="Папка с отчётами или путь к одному .json")
    args = parser.parse_args()

    if os.path.isfile(args.path):
        with open(args.path, encoding="utf-8") as f:
            verdict, reasons = validate_report(json.load(f))
        results = [(os.path.basename(args.path), verdict, reasons)]
    elif os.path.isdir(args.path):
        results = validate_folder(args.path)
    else:
        print(f"ERROR: путь не найден: {args.path}")
        sys.exit(1)

    if not results:
        print(f"❌ В {args.path} нет ни одного отчёта. Прогон не выполнялся.")
        sys.exit(1)

    fabricated = [r for r in results if r[1] == FABRICATED]
    print("# Проверка целостности отчётов\n")
    for base, verdict, reasons in results:
        print(f"{_ICON[verdict]}  {base}")
        for r in reasons:
            print(f"      └─ {r}")

    print()
    if fabricated:
        print(f"❌ ФАБРИКАЦИЯ: {len(fabricated)} из {len(results)} отчётов не являются выводом "
              f"реального прогона test_runner. Этим данным доверять НЕЛЬЗЯ — нужен честный "
              f"перепрогон через `python -m agent.run_suite`.")
        sys.exit(1)

    no_id = [r for r in results if r[1] == NO_USER_ID]
    if no_id:
        print(f"⚠️ {len(no_id)} отчётов без user_id (виджет не загрузился) — перезапусти эти сценарии "
              f"в headed-режиме. Остальные валидны.")
    else:
        print(f"✅ Все {len(results)} отчётов валидны — это настоящий вывод раннера.")
    sys.exit(0)


if __name__ == "__main__":
    main()
