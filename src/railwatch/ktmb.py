"""KTMB browser automation and seat-selection business rules."""

from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from playwright.async_api import BrowserContext, Page

from railwatch.errors import SessionRejectedError
from railwatch.models import CheckResult, MatchingTrain, Monitor, in_time_window

LOGGER = logging.getLogger(__name__)
KTMB_HOME_URL = "https://online.ktmb.com.my/"
LOGIN_URL_PATTERN = re.compile(r"/Account/Login(?:$|[?#])", re.IGNORECASE)
TRIP_URL_PATTERN = re.compile(r"/Trip(?:$|\?)")
STANDARD_SEAT_PATTERN = re.compile(r"^(Stan|Std)", re.IGNORECASE)
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_ktmb_date(value: date) -> str:
    """Format a date as the KTMB form expects: DD Mon YYYY."""
    return f"{value.day:02d} {MONTHS[value.month - 1]} {value.year:04d}"


def seat_is_ordinary(src: str | None, *, base_url: str = KTMB_HOME_URL) -> bool:
    """Accept selectable Standard seats and reject OKU/reserved seat families."""
    if not src:
        return False
    parsed = urlparse(src if "://" in src else f"{base_url.rstrip('/')}/{src.lstrip('/')}")
    seat_id = parse_qs(parsed.query).get("id", [""])[0]
    return bool(STANDARD_SEAT_PATTERN.search(seat_id)) and "OKU" not in seat_id.upper()


async def assert_authenticated(page: Page) -> None:
    """Raise if the official site shows an unauthenticated session."""
    if LOGIN_URL_PATTERN.search(page.url):
        raise SessionRejectedError("KTMB redirected to login; the stored session was rejected.")
    visible_login_links = await page.locator('a[href*="/Account/Login"]:visible').count()
    if visible_login_links:
        raise SessionRejectedError("KTMB redirected to login; the stored session was rejected.")


async def preflight_session(context: BrowserContext) -> None:
    """Verify the stored browser state before processing monitors."""
    page = await context.new_page()
    try:
        await page.goto(KTMB_HOME_URL, wait_until="domcontentloaded", timeout=45_000)
        await assert_authenticated(page)
    finally:
        await page.close()


async def check_monitor(context: BrowserContext, monitor: Monitor) -> CheckResult:
    """Check one journey and return the existing Railwatch API payload."""
    page = await context.new_page()
    try:
        await page.goto(KTMB_HOME_URL, wait_until="domcontentloaded", timeout=45_000)
        await assert_authenticated(page)
        LOGGER.info("Monitor %s: KTMB session check passed.", monitor.id)

        await page.select_option("#FromStationId", monitor.origin_id)
        await page.wait_for_function(
            """
            (value) => {
              const select = document.querySelector("#ToStationId");
              return select && Array.from(select.options).some(
                (option) => option.value === value
              );
            }
            """,
            arg=monitor.destination_id,
            timeout=15_000,
        )
        await page.select_option("#ToStationId", monitor.destination_id)

        await page.locator("#OnwardDate").evaluate(
            """
            (input, value) => {
              if (!(input instanceof HTMLInputElement)) {
                throw new Error("KTMB departure field was not found.");
              }
              input.value = value;
              input.dispatchEvent(new Event("input", { bubbles: true }));
              input.dispatchEvent(new Event("change", { bubbles: true }));
            }
            """,
            format_ktmb_date(monitor.travel_date),
        )

        await page.locator("#btnSubmit").click()
        await page.wait_for_url(TRIP_URL_PATTERN, timeout=45_000)
        await page.wait_for_selector("tr", timeout=30_000)

        rows = page.locator("tbody tr").filter(has_text="Pick Seats")
        matching_trains: list[MatchingTrain] = []
        for index in range(await rows.count()):
            row = rows.nth(index)
            cells = await row.locator("td").all_text_contents()
            service = cells[0].strip() if cells else ""
            departure = cells[1].strip() if len(cells) > 1 else ""
            if not in_time_window(departure, monitor.start_time, monitor.end_time):
                continue

            await row.get_by_text("Pick Seats", exact=True).click()
            await page.wait_for_selector("#seatSelect.show img", timeout=30_000)
            ordinary_seats = await _count_ordinary_seats(page)

            if ordinary_seats:
                matching_trains.append(
                    MatchingTrain(
                        service=service,
                        departure=departure,
                        ordinarySeats=ordinary_seats,
                    )
                )

            await page.locator("#seatSelect button.close").click()
            await page.wait_for_selector("#seatSelect", state="hidden")

        return CheckResult(
            monitorId=monitor.id,
            availableSeats=sum(train.ordinary_seats for train in matching_trains),
            matchingTrains=matching_trains,
        )
    finally:
        await page.close()


async def _count_ordinary_seats(page: Page) -> int:
    seats = page.locator("#seatSelect img.selectable-icon[data-seat-data]")
    count = 0
    for index in range(await seats.count()):
        if seat_is_ordinary(await seats.nth(index).get_attribute("src"), base_url=page.url):
            count += 1
    return count
