"""
Единая точка входа для прогона ВСЕЙ серии сценариев одной командой.

Зачем: даёт агенту-тестировщику РОВНО одну команду, чей stdout является
доказательством реального прогона. Она сама: прогоняет каждый сценарий через
реальный Playwright, пишет отчёты, валидирует их (страж anti-fabrication),
собирает SUMMARY.md и печатает итоговый вердикт с run-токеном.

Использование:
    python -m agent.run_suite \
        --scenario-file scenarios/bitrix.carrotquest.ru.json \
        --out-dir reports/bitrix.carrotquest.ru \
        --http-user carrotadmin --http-pass "<пароль>" \
        --no-headless

Если --out-dir не задан, выводится из хоста site_url: reports/<host>.
Агент НЕ должен писать файлы отчётов руками — только эта команда.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from .reporter import REPORT_SCHEMA_VERSION
from .scenario import load_scenarios
from .summary import build_summary
from .test_runner import run_test
from .validate import validate_report, VALID, NO_USER_ID, FABRICATED

load_dotenv()


def _out_dir_for(site_url: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    host = (urlparse(site_url).hostname if site_url else None) or "client"
    return os.path.join("reports", host)


async def _run_one(scenario_obj, *, start_url, scenario_text, auth_token, app_id,
                   threshold, headless, http_user, http_pass, debug, retries=1):
    """Прогон одного сценария с однократным ретраем при ошибке/пустом user_id."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            result = await run_test(
                url=start_url,
                scenario=scenario_text,
                auth_token=auth_token,
                app_id=app_id,
                threshold=threshold,
                headless=headless,
                http_username=http_user,
                http_password=http_pass,
                debug=debug,
                scenario_obj=scenario_obj,
            )
            if result["json"].get("user_id") or attempt == retries:
                return result["json"], None
            print(f"   ↻ user_id пуст — ретрай {scenario_obj.id} ({attempt + 1}/{retries})")
        except Exception as e:  # noqa: BLE001 — ретраим любой сбой прогона
            last_exc = e
            print(f"   ⚠ ошибка прогона {scenario_obj.id}: {e}")
            if attempt < retries:
                print(f"   ↻ ретрай {scenario_obj.id} ({attempt + 1}/{retries})")
    return None, last_exc


def main():
    parser = argparse.ArgumentParser(description="Прогон всей серии сценариев одной командой")
    parser.add_argument("--scenario-file", required=True, help="JSON-файл со сценариями")
    parser.add_argument("--out-dir", default=None, help="Папка для отчётов (по умолчанию reports/<host>)")
    parser.add_argument("--threshold", type=int, default=None, help="Порог быстрого появления (сек)")
    parser.add_argument("--no-headless", action="store_true", help="Показать окно браузера (рекомендуется)")
    parser.add_argument("--http-user", default=None, help="HTTP Basic Auth логин")
    parser.add_argument("--http-pass", default=None, help="HTTP Basic Auth пароль")
    parser.add_argument("--debug", action="store_true", help="Дебаг: дамп popup-like элементов")
    args = parser.parse_args()

    auth_token = os.getenv("CQ_AUTH_TOKEN")
    app_id = os.getenv("CQ_APP_ID")
    if not auth_token or not app_id:
        print("ERROR: Задайте CQ_AUTH_TOKEN и CQ_APP_ID в файле .env")
        sys.exit(1)

    site_url, scenarios = load_scenarios(args.scenario_file)
    if not scenarios:
        print(f"ERROR: в {args.scenario_file} нет сценариев")
        sys.exit(1)

    out_dir = _out_dir_for(site_url, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    from .config import RAPID_SUCCESSION_THRESHOLD_SEC
    threshold = args.threshold if args.threshold is not None else RAPID_SUCCESSION_THRESHOLD_SEC
    headless = not args.no_headless

    suite_start = time.time()
    print(f"▶ Прогон {len(scenarios)} сценариев · сайт {site_url} · headless={headless}")
    if not args.http_user and not args.http_pass:
        print("  ⚠ Basic Auth не задан (--http-user/--http-pass). Если сайт под паролем — "
              "прогон упадёт с ERR_INVALID_AUTH_CREDENTIALS.")

    reports: list[dict] = []
    for i, sc in enumerate(scenarios, 1):
        # стартовый URL: site_url, иначе первый navigate сценария
        start_url = site_url
        if not start_url:
            for step in sc.steps:
                if step.action == "navigate":
                    start_url = step.params.get("url")
                    break
        scenario_text = f"{sc.title} — {sc.description}".strip(" —")
        print(f"\n[{i}/{len(scenarios)}] ▶ {sc.id}")

        report_json, exc = asyncio.run(_run_one(
            sc, start_url=start_url, scenario_text=scenario_text,
            auth_token=auth_token, app_id=app_id, threshold=threshold,
            headless=headless, http_user=args.http_user, http_pass=args.http_pass,
            debug=args.debug,
        ))

        if report_json is None:
            print(f"   ✖ {sc.id}: FAILED ({exc})")
            continue

        out_path = os.path.join(out_dir, f"{sc.id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report_json, f, ensure_ascii=False, indent=2)
        verdict, reasons = validate_report(report_json)
        bc = report_json.get("bug_count", 0)
        sb = len(report_json.get("send_bugs", []))
        mark = {VALID: "✅", NO_USER_ID: "⚠️", FABRICATED: "❌"}[verdict]
        print(f"   {mark} {verdict} · DOM-баги={bc} · сигнал-отправки={sb} · → {out_path}")
        reports.append(report_json)

    # Сводка — два формата: markdown для чата + HTML-дашборд для браузера.
    summary_path = os.path.join(out_dir, "SUMMARY.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(build_summary(reports))
    html_path = os.path.join(out_dir, "report.html")
    if reports:
        from .report_html import build_html
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(build_html(reports))

    # Итоговый вердикт с run-токеном (доказательство реального прогона)
    elapsed = int(time.time() - suite_start)
    run_token = f"run-{int(suite_start)}-{len(reports)}of{len(scenarios)}-{elapsed}s"
    verdicts = [validate_report(r)[0] for r in reports]
    n_valid = verdicts.count(VALID)
    n_noid = verdicts.count(NO_USER_ID)
    n_fab = verdicts.count(FABRICATED)
    total_bugs = sum(r.get("bug_count", 0) for r in reports)
    total_send = sum(len(r.get("send_bugs", [])) for r in reports)

    print("\n" + "=" * 60)
    print(f"ИТОГ · run_token={run_token} · schema_v{REPORT_SCHEMA_VERSION}")
    print(f"  Сценариев успешно: {len(reports)}/{len(scenarios)}")
    print(f"  Валидных: {n_valid} · без user_id: {n_noid} · фабрикаций: {n_fab}")
    print(f"  Всего DOM-багов: {total_bugs} · сигналов отправки (API): {total_send}")
    print(f"  Сводка (markdown, для чата): {summary_path}")
    if reports:
        print(f"  Дашборд (HTML, для браузера): {html_path}")
    print("=" * 60)

    # Ненулевой код, если есть фабрикации или вообще нет валидных прогонов
    if n_fab or (len(reports) == 0):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
