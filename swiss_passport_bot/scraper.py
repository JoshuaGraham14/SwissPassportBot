from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .calendar_urls import sanitize_url
from .config import Settings

if TYPE_CHECKING:
    from playwright.async_api import Page

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
except ModuleNotFoundError as exc:
    PlaywrightTimeoutError = TimeoutError
    async_playwright = None
    PLAYWRIGHT_IMPORT_ERROR = exc
else:
    PLAYWRIGHT_IMPORT_ERROR = None


RESCHEDULE_RE = re.compile(
    r"(reschedule|change appointment|modifier la r[ée]servation|modifier|"
    r"spostare|verschieben|umbuchen)",
    re.IGNORECASE,
)
NEXT_FREE_RE = re.compile(
    r"(next free appointments|show next free appointments|prochains rendez-vous libres|"
    r"nächste freie termine|prossimi appuntamenti liberi)",
    re.IGNORECASE,
)
SUGGESTIONS_PAGE_RE = re.compile(
    r"(please choose a date and a time in the suggestions below|show the calendar|start time)",
    re.IGNORECASE,
)
SUGGESTION_RE = re.compile(
    r"\b(?P<weekday>Mo|Tu|We|Th|Fr|Sa|Su|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Do|Di|Mi|Fr|Sa|So|Lu|Ma|Me|Je|Ve|Sa|Di)\.?\s+"
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<time>[0-2]\d:[0-5]\d)\b",
    re.IGNORECASE,
)
BLOCK_PAGE_RE = re.compile(
    r"(web page blocked|attack id|message id|the page cannot be displayed)",
    re.IGNORECASE,
)
INVALID_TOKEN_RE = re.compile(r"invalid access token", re.IGNORECASE)


@dataclass(frozen=True)
class AppointmentSlot:
    key: str
    date: str
    time: str
    label: str
    week_start: str
    url: str
    confidence: str


class SwissAppointmentScraper:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def find_slots(self) -> list[AppointmentSlot]:
        if async_playwright is None:
            raise RuntimeError(
                "Missing Python package 'playwright'. Run: python -m pip install -r requirements.txt"
            ) from PLAYWRIGHT_IMPORT_ERROR

        self.settings.require_site_config()
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        end_day = today + timedelta(days=self.settings.lookahead_days)

        async with async_playwright() as playwright:
            launch_kwargs = {"headless": self.settings.headless}
            if self.settings.browser_executable_path:
                launch_kwargs["executable_path"] = self.settings.browser_executable_path
            elif self.settings.browser_channel:
                launch_kwargs["channel"] = self.settings.browser_channel

            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                locale=self.settings.locale,
                timezone_id=self.settings.timezone,
                viewport={"width": 1600, "height": 1000},
            )
            page = await context.new_page()
            page.set_default_timeout(self.settings.page_timeout_ms)

            try:
                await self._open_calendar(page)
                suggestion_slots = await self._find_suggestion_slots(page, today, end_day)
                return _dedupe_slots(suggestion_slots)
            finally:
                await context.close()
                await browser.close()

    async def _open_calendar(self, page: Page) -> None:
        await page.goto(self.settings.session_url, wait_until="domcontentloaded")
        await self._wait_for_page_to_settle(page)
        await self._raise_if_blocked(page)

        if "/calendar" in page.url:
            return

        clicked = await self._click_reschedule(page)
        if not clicked:
            body_text = await self._body_text(page)
            raise RuntimeError(
                "Could not find the Reschedule button. "
                f"Current URL: {sanitize_url(page.url)}. "
                f"Visible text starts with: {body_text[:300]!r}"
            )

        await self._wait_for_page_to_settle(page)
        await self._raise_if_blocked(page)
        if "/calendar" not in page.url:
            body_text = await self._body_text(page)
            raise RuntimeError(
                "Clicked Reschedule, but the calendar did not open. "
                f"Current URL: {sanitize_url(page.url)}. "
                f"Visible text starts with: {body_text[:300]!r}"
            )

    async def _find_suggestion_slots(
        self,
        page: Page,
        today: date,
        end_day: date,
    ) -> list[AppointmentSlot]:
        body_text = await self._body_text(page)
        if not SUGGESTIONS_PAGE_RE.search(body_text):
            clicked = await self._click_next_free_appointments(page)
            if not clicked:
                body_text = await self._body_text(page)
                raise RuntimeError(
                    "Could not find the Next free appointments button. "
                    f"Current URL: {sanitize_url(page.url)}. "
                    f"Visible text starts with: {body_text[:300]!r}"
                )
            await self._wait_for_page_to_settle(page)
            await self._raise_if_blocked(page)

        body_text = await self._body_text(page)
        slots = _parse_suggestion_slots(body_text, today, end_day, sanitize_url(page.url))
        if slots:
            return slots

        raw_slots = await page.evaluate(JS_EXTRACT_SUGGESTIONS)
        return _parse_raw_suggestion_rows(raw_slots, today, end_day, sanitize_url(page.url))

    async def _raise_if_blocked(self, page: Page) -> None:
        body_text = await self._body_text(page)
        if INVALID_TOKEN_RE.search(body_text):
            raise RuntimeError(
                "The Swiss reservation site says the session link has an invalid access token. "
                "Paste a fresh appointment/session link into SESSION_URL in .env, then retry. "
                f"Current URL: {sanitize_url(page.url)}."
            )

        if not BLOCK_PAGE_RE.search(body_text):
            return

        raise RuntimeError(
            "The Swiss reservation site blocked this automated browser session. "
            "Try a visible real-Chrome check with HEADLESS=false and "
            'BROWSER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome". '
            "If the visible check is also blocked, the site is refusing automated access from this setup. "
            f"Current URL: {sanitize_url(page.url)}. "
            f"Visible text starts with: {body_text[:300]!r}"
        )

    async def _click_reschedule(self, page: Page) -> bool:
        buttons = page.get_by_role("button")
        count = await buttons.count()
        for index in range(count):
            button = buttons.nth(index)
            try:
                label = (await button.inner_text()).strip()
            except PlaywrightTimeoutError:
                continue
            if RESCHEDULE_RE.search(label):
                await button.click()
                return True

        # Some localized material buttons expose text outside the button node.
        locator = page.get_by_text(RESCHEDULE_RE).first
        try:
            await locator.click(timeout=3000)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _click_next_free_appointments(self, page: Page) -> bool:
        buttons = page.get_by_role("button")
        count = await buttons.count()
        for index in range(count):
            button = buttons.nth(index)
            try:
                label = (await button.inner_text()).strip()
            except PlaywrightTimeoutError:
                continue
            if NEXT_FREE_RE.search(label):
                await button.click()
                return True

        locator = page.get_by_text(NEXT_FREE_RE).first
        try:
            await locator.click(timeout=3000)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _wait_for_page_to_settle(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=self.settings.page_timeout_ms)
        except PlaywrightTimeoutError:
            pass
        await page.wait_for_timeout(1200)

    async def _body_text(self, page: Page) -> str:
        try:
            return re.sub(r"\s+", " ", await page.locator("body").inner_text(timeout=5000)).strip()
        except PlaywrightTimeoutError:
            return ""


def _parse_suggestion_slots(
    body_text: str,
    today: date,
    end_day: date,
    url: str,
) -> list[AppointmentSlot]:
    slots: list[AppointmentSlot] = []
    for match in SUGGESTION_RE.finditer(body_text):
        slot_date = _parse_site_date(match.group("date"))
        if slot_date is None or slot_date < today or slot_date > end_day:
            continue
        slot_time = match.group("time")
        slots.append(_suggestion_slot(slot_date, slot_time, url))
    return slots


def _parse_raw_suggestion_rows(
    rows: list[dict],
    today: date,
    end_day: date,
    url: str,
) -> list[AppointmentSlot]:
    slots: list[AppointmentSlot] = []
    for row in rows:
        row_text = re.sub(r"\s+", " ", row.get("text", "")).strip()
        match = SUGGESTION_RE.search(row_text)
        if not match:
            continue
        slot_date = _parse_site_date(match.group("date"))
        if slot_date is None or slot_date < today or slot_date > end_day:
            continue
        slots.append(_suggestion_slot(slot_date, match.group("time"), url))
    return slots


def _parse_site_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _suggestion_slot(slot_date: date, slot_time: str, url: str) -> AppointmentSlot:
    return AppointmentSlot(
        key=f"{slot_date.isoformat()}T{slot_time}",
        date=slot_date.isoformat(),
        time=slot_time,
        label=f"Suggested free appointment on {slot_date.isoformat()} at {slot_time}",
        week_start=monday_for_date(slot_date).isoformat(),
        url=url,
        confidence="high",
    )


def monday_for_date(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _dedupe_slots(slots: list[AppointmentSlot]) -> list[AppointmentSlot]:
    seen: set[tuple[str, str, str]] = set()
    results: list[AppointmentSlot] = []
    for slot in sorted(slots, key=lambda item: (item.date, item.time, item.key)):
        coarse_key = (slot.date, slot.time, slot.label)
        if coarse_key in seen:
            continue
        seen.add(coarse_key)
        results.append(slot)
    return results


JS_EXTRACT_SUGGESTIONS = r"""
() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 3 &&
      rect.height > 3 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none' &&
      Number(style.opacity || '1') > 0;
  };

  const selectors = [
    'tr',
    '[role="row"]',
    '.mat-row',
    '.mat-mdc-row',
    '.cdk-row'
  ];
  const seen = new Set();
  const rows = [];

  for (const selector of selectors) {
    for (const el of Array.from(document.querySelectorAll(selector))) {
      if (!visible(el)) continue;
      const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text || seen.has(text)) continue;
      seen.add(text);
      rows.push({ text });
    }
  }

  return rows;
}
"""


def find_slots_sync(settings: Settings) -> list[AppointmentSlot]:
    return asyncio.run(SwissAppointmentScraper(settings).find_slots())
