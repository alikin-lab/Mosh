import time
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, Playwright

from .config import CQ_INIT_WAIT_SEC


@dataclass
class NavEntry:
    timestamp: float
    action: str
    url: Optional[str] = None


class BrowserSession:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page: Optional[Page] = None
        self.nav_log: list[NavEntry] = []

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self, url: str):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        self.page = await context.new_page()
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._log("navigate", url)

    async def get_cq_user_id(self) -> Optional[str]:
        # Wait for CQ widget to initialize
        await self.page.wait_for_timeout(int(CQ_INIT_WAIT_SEC * 1000))
        try:
            user_id = await self.page.evaluate(
                "() => window.carrotquest && window.carrotquest.data && window.carrotquest.data.user ? window.carrotquest.data.user.id : null"
            )
            return str(user_id) if user_id else None
        except Exception:
            return None

    async def navigate_to(self, url: str):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._log("navigate", url)

    async def scroll_page(self):
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await self.page.wait_for_timeout(1_500)
        await self.page.evaluate("window.scrollTo(0, 0)")
        self._log("scroll")

    async def wait(self, seconds: float):
        await self.page.wait_for_timeout(int(seconds * 1_000))

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _log(self, action: str, url: Optional[str] = None):
        self.nav_log.append(NavEntry(timestamp=time.time(), action=action, url=url))
