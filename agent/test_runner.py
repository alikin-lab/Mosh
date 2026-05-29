"""
Main entry point for the CQ popup testing agent.

Usage:
    python -m agent.test_runner \
        --url https://bitrix.carrotquest.ru \
        --scenario "Ты потенциальный клиент. Посмотри продуктовые страницы." \
        --extra-urls https://bitrix.carrotquest.ru/products/ \
        --duration 120 \
        --no-headless
"""

import argparse
import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from .browser_session import BrowserSession
from .carrotquest_api import CarrotQuestAPI
from .config import RAPID_SUCCESSION_THRESHOLD_SEC
from .popup_detector import PopupDetector
from .reporter import generate_report

load_dotenv()


async def run_test(
    url: str,
    scenario: str,
    auth_token: str,
    app_id: str,
    extra_urls: list[str] | None = None,
    duration: int = 120,
    threshold: int = RAPID_SUCCESSION_THRESHOLD_SEC,
    headless: bool = True,
    http_username: str | None = None,
    http_password: str | None = None,
    debug: bool = False,
) -> str:
    session = BrowserSession(headless=headless, http_username=http_username, http_password=http_password)
    session_start = time.time()

    await session.start(url)

    detector = PopupDetector(page=session.page, threshold=threshold, debug=debug)
    monitor_task = asyncio.create_task(detector.start())

    # Give CQ widget time to load, then grab user ID
    await session.wait(3)
    user_id = await session.get_cq_user_id()

    # Navigate extra URLs if provided
    if extra_urls:
        for extra_url in extra_urls:
            await session.wait(10)
            await session.navigate_to(extra_url)
            await session.scroll_page()

    # Wait out the remaining session duration
    elapsed = time.time() - session_start
    remaining = max(0, duration - elapsed)
    if remaining > 0:
        await session.wait(remaining)

    session_end = time.time()
    detector.stop()
    monitor_task.cancel()

    # Fetch CQ API data
    api = CarrotQuestAPI(auth_token=auth_token, app_id=app_id)
    api_events: list[dict] = []
    card_url = None
    if user_id:
        card_url = api.user_card_url(user_id)
        try:
            api_events = api.get_user_events(user_id)
        except Exception as e:
            print(f"[warn] Could not fetch API events: {e}")

    await session.close()

    return generate_report(
        site_url=url,
        app_id=app_id,
        bugs=detector.bugs,
        popup_events=detector.events,
        nav_log=session.nav_log,
        api_events=api_events,
        session_start=session_start,
        session_end=session_end,
        user_id=user_id,
        card_url=card_url,
        scenario=scenario,
    )


def main():
    parser = argparse.ArgumentParser(description="CQ Popup QA Agent")
    parser.add_argument("--url", required=True, help="Стартовый URL сайта")
    parser.add_argument("--scenario", default="Обход сайта без конкретной легенды", help="Текстовое описание сценария")
    parser.add_argument("--extra-urls", nargs="*", default=[], help="Дополнительные URL для обхода")
    parser.add_argument("--duration", type=int, default=120, help="Длительность сессии в секундах")
    parser.add_argument("--threshold", type=int, default=RAPID_SUCCESSION_THRESHOLD_SEC, help="Порог быстрого появления (сек)")
    parser.add_argument("--no-headless", action="store_true", help="Показать окно браузера")
    parser.add_argument("--http-user", default=None, help="HTTP Basic Auth логин")
    parser.add_argument("--http-pass", default=None, help="HTTP Basic Auth пароль")
    parser.add_argument("--debug", action="store_true", help="Дебаг: дампить все popup-like элементы из всех фреймов")
    args = parser.parse_args()

    auth_token = os.getenv("CQ_AUTH_TOKEN")
    app_id = os.getenv("CQ_APP_ID")

    if not auth_token or not app_id:
        print("ERROR: Задайте CQ_AUTH_TOKEN и CQ_APP_ID в файле .env")
        return

    report = asyncio.run(run_test(
        url=args.url,
        scenario=args.scenario,
        auth_token=auth_token,
        app_id=app_id,
        extra_urls=args.extra_urls,
        duration=args.duration,
        threshold=args.threshold,
        headless=not args.no_headless,
        http_username=args.http_user,
        http_password=args.http_pass,
        debug=args.debug,
    ))

    print(report)


if __name__ == "__main__":
    main()
