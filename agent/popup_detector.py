import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page

from .config import POPUP_SELECTORS, POPUP_LABELS, POLL_INTERVAL_SEC, DEBUG_SELECTORS


@dataclass
class PopupEvent:
    timestamp: float
    event_type: str  # "appeared" | "closed"
    popup_type: str
    frame_url: str = ""

    @property
    def label(self) -> str:
        return POPUP_LABELS.get(self.popup_type, self.popup_type)


@dataclass
class Bug:
    timestamp: float
    bug_type: str  # "overlap" | "rapid_succession"
    description: str
    popups_involved: list
    screenshot: Optional[bytes] = None
    interval_seconds: Optional[float] = None


class PopupDetector:
    def __init__(self, page: Page, threshold: int, debug: bool = False):
        self.page = page
        self.threshold = threshold
        self.debug = debug
        self.events: list[PopupEvent] = []
        self.bugs: list[Bug] = []

        self._previous_popups: set = set()
        self._last_any_close_time: Optional[float] = None
        self._last_overlap_bug_time: Optional[float] = None
        self._running = False

    async def _get_visible_popups(self) -> set:
        """Search for known popup selectors across ALL frames (main + iframes)."""
        visible = set()
        frames = self.page.frames

        for frame in frames:
            try:
                for popup_type, selector in POPUP_SELECTORS.items():
                    try:
                        elements = await frame.query_selector_all(selector)
                        for el in elements:
                            if await el.is_visible():
                                visible.add(popup_type)
                                if self.debug:
                                    print(f"[Detector] Found {popup_type!r} via '{selector}' in frame {frame.url!r}")
                                break
                    except Exception:
                        pass
            except Exception:
                pass

        return visible

    async def _debug_scan(self):
        """Dump all popup-like elements found across all frames (for selector discovery)."""
        frames = self.page.frames
        found_any = False
        for frame in frames:
            try:
                for selector in DEBUG_SELECTORS:
                    try:
                        elements = await frame.query_selector_all(selector)
                        for el in elements:
                            try:
                                tag = await el.evaluate("el => el.tagName")
                                cls = await el.evaluate("el => el.className")
                                attrs = await el.evaluate(
                                    "el => Array.from(el.attributes).map(a => a.name + '=' + a.value).join(' ')"
                                )
                                visible = await el.is_visible()
                                print(
                                    f"[Debug] frame={frame.url!r} selector={selector!r} "
                                    f"tag={tag} class={cls!r} attrs={attrs!r} visible={visible}"
                                )
                                found_any = True
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass
        if not found_any:
            print("[Debug] No popup-like elements found in any frame this tick")

    async def _check(self):
        now = time.time()

        if self.debug:
            await self._debug_scan()

        current = await self._get_visible_popups()

        appeared = current - self._previous_popups
        closed = self._previous_popups - current

        for popup_type in closed:
            self.events.append(PopupEvent(now, "closed", popup_type))
            self._last_any_close_time = now

        for popup_type in appeared:
            self.events.append(PopupEvent(now, "appeared", popup_type))

            if self._last_any_close_time is not None:
                interval = now - self._last_any_close_time
                if interval < self.threshold:
                    screenshot = await self.page.screenshot()
                    self.bugs.append(Bug(
                        timestamp=now,
                        bug_type="rapid_succession",
                        description=(
                            f"Попап появился через {interval:.1f} сек после закрытия предыдущего "
                            f"(порог: {self.threshold} сек)"
                        ),
                        popups_involved=[popup_type],
                        screenshot=screenshot,
                        interval_seconds=interval,
                    ))

            if self._previous_popups:
                if self._last_overlap_bug_time is None or (now - self._last_overlap_bug_time) > 5:
                    screenshot = await self.page.screenshot()
                    all_popups = list(self._previous_popups) + [popup_type]
                    self.bugs.append(Bug(
                        timestamp=now,
                        bug_type="overlap",
                        description=f"Одновременно видны {len(all_popups)} попапа",
                        popups_involved=all_popups,
                        screenshot=screenshot,
                    ))
                    self._last_overlap_bug_time = now

        self._previous_popups = current

    async def start(self):
        self._running = True
        while self._running:
            try:
                await self._check()
            except Exception:
                pass
            await asyncio.sleep(POLL_INTERVAL_SEC)

    def stop(self):
        self._running = False
