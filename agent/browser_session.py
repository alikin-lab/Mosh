import time
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, Playwright


@dataclass
class NavEntry:
    timestamp: float
    action: str
    url: Optional[str] = None


class BrowserSession:
    def __init__(self, headless: bool = True, http_username: Optional[str] = None, http_password: Optional[str] = None):
        self.headless = headless
        self.http_username = http_username
        self.http_password = http_password
        self.page: Optional[Page] = None
        self.nav_log: list[NavEntry] = []

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self, url: str):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        ctx_kwargs = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "ru-RU",
        }
        if self.http_username and self.http_password:
            ctx_kwargs["http_credentials"] = {"username": self.http_username, "password": self.http_password}
        context = await self._browser.new_context(**ctx_kwargs)
        self.page = await context.new_page()
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._log("navigate", url)

    async def get_cq_user_id(self, timeout_sec: float = 15) -> Optional[str]:
        """Опрашивает window.carrotquest.data.user.id с ретраями, пока виджет инициализируется."""
        js = (
            "() => window.carrotquest && window.carrotquest.data && window.carrotquest.data.user "
            "? window.carrotquest.data.user.id : null"
        )
        for _ in range(int(timeout_sec)):
            try:
                user_id = await self.page.evaluate(js)
                if user_id:
                    return str(user_id)
            except Exception:
                pass
            await self.page.wait_for_timeout(1000)
        return None

    async def navigate_to(self, url: str):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._log("navigate", url)

    async def scroll_page(self):
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await self.page.wait_for_timeout(1_500)
        await self.page.evaluate("window.scrollTo(0, 0)")
        self._log("scroll")

    async def scroll_to(self, where: str = "bottom"):
        """where: 'bottom' | 'top' | число 0..1 (доля высоты страницы)."""
        if where == "bottom":
            js = "window.scrollTo(0, document.body.scrollHeight)"
        elif where == "top":
            js = "window.scrollTo(0, 0)"
        else:
            try:
                frac = max(0.0, min(1.0, float(where)))
            except (TypeError, ValueError):
                frac = 1.0
            js = f"window.scrollTo(0, document.body.scrollHeight * {frac})"
        await self.page.evaluate(js)
        self._log("scroll")

    async def exit_intent(self):
        """Имитирует уход мыши за верхнюю кромку окна — типичный триггер exit-intent попапов."""
        try:
            await self.page.mouse.move(640, 400)
            await self.page.mouse.move(10, 0)
            await self.page.evaluate(
                """() => {
                    const opts = {clientX: 10, clientY: -8, relatedTarget: null, bubbles: true};
                    document.dispatchEvent(new MouseEvent('mouseout', opts));
                    document.dispatchEvent(new MouseEvent('mouseleave', opts));
                    (document.documentElement || document.body).dispatchEvent(new MouseEvent('mouseleave', opts));
                }"""
            )
        except Exception:
            pass
        self._log("exit_intent")

    async def click(self, selector: str):
        try:
            await self.page.click(selector, timeout=5_000)
        except Exception:
            pass
        self._log(f"click: {selector}")

    async def open_chat(self):
        """Пытается открыть виджет чата CQ (триггер для нотификации бота)."""
        for sel in ("#carrot-messenger-collapsed-container", ".carrot-messenger-collapsed-frame", "[class*='messenger-collapsed']"):
            try:
                await self.page.click(sel, timeout=3_000)
                break
            except Exception:
                continue
        self._log("open_chat")

    async def wait(self, seconds: float):
        await self.page.wait_for_timeout(int(seconds * 1_000))

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _log(self, action: str, url: Optional[str] = None):
        self.nav_log.append(NavEntry(timestamp=time.time(), action=action, url=url))
