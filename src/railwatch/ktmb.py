"""KTMB browser automation and seat-selection business rules."""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from railwatch.errors import SessionRejectedError
from railwatch.models import CheckResult, MatchingTrain, Monitor, SeatDetail, in_time_window

LOGGER = logging.getLogger(__name__)
KTMB_HOME_URL = "https://online.ktmb.com.my/"
LOGIN_URL_PATTERN = re.compile(r"/Account/Login(?:$|[?#])", re.IGNORECASE)
TRIP_URL_PATTERN = re.compile(r"/Trip(?:$|\?)")
STANDARD_SEAT_PATTERN = re.compile(r"^(Stan|Std)", re.IGNORECASE)
SEAT_NUMBER_PATTERN = re.compile(r"^[A-Z]{0,2}\d{1,3}[A-Z]{0,2}$", re.IGNORECASE)
LABELED_SEAT_NUMBER_PATTERN = re.compile(
    r"\bseat(?:\s*(?:no|number|name|label|code))?\s*[:#-]?\s*"
    r"([A-Z]{0,2}\d{1,3}[A-Z]{0,2})\b",
    re.IGNORECASE,
)
SEAT_NUMBER_KEYS = {
    "seat",
    "seatcode",
    "seatlabel",
    "seatname",
    "seatno",
    "seatnumber",
}
COACH_KEYS = {
    "car",
    "carriage",
    "carriagecode",
    "carriagename",
    "carriageno",
    "carriagenumber",
    "coach",
    "coachcode",
    "coachid",
    "coachlabel",
    "coachname",
    "coachno",
    "coachnumber",
}
LABELED_COACH_PATTERN = re.compile(
    r"\b(?:coach|carriage|car)\s*(?:no|number|name|label|code)?\s*[:#-]?\s*"
    r"([A-Z0-9][A-Z0-9_-]{0,11})\b",
    re.IGNORECASE,
)
COACH_VALUE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,11}$", re.IGNORECASE)
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


def _normalized_metadata_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def _decoded_metadata(metadata: object) -> object:
    if not isinstance(metadata, str):
        return metadata
    value = html.unescape(metadata).strip()
    if value[:1] not in "[{":
        return metadata
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return metadata


def _metadata_values(metadata: object, keys: set[str]) -> list[object]:
    """Return values for matching keys, including values inside JSON strings."""
    metadata = _decoded_metadata(metadata)
    values: list[object] = []
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            normalized_key = _normalized_metadata_key(key)
            if normalized_key in keys or (
                normalized_key.startswith("data") and normalized_key[4:] in keys
            ):
                values.append(value)
            values.extend(_metadata_values(value, keys))
    elif isinstance(metadata, (list, tuple)):
        for value in metadata:
            values.extend(_metadata_values(value, keys))
    return values


def _metadata_texts(metadata: object) -> list[str]:
    metadata = _decoded_metadata(metadata)
    if isinstance(metadata, dict):
        return [text for value in metadata.values() for text in _metadata_texts(value)]
    if isinstance(metadata, (list, tuple)):
        return [text for value in metadata for text in _metadata_texts(value)]
    if isinstance(metadata, (str, int)):
        value = html.unescape(str(metadata)).strip()
        return [value] if value else []
    return []


def _seat_number_from_value(value: object) -> str | None:
    for text in _metadata_texts(value):
        compact = re.sub(r"\s+", "", text)
        if SEAT_NUMBER_PATTERN.fullmatch(compact):
            return compact.upper()
        labelled = LABELED_SEAT_NUMBER_PATTERN.search(text)
        if labelled:
            return labelled.group(1).upper()
    return None


def seat_number_from_metadata(metadata: object) -> str | None:
    """Extract a displayed seat number without mistaking a coach number for it."""
    for value in _metadata_values(metadata, SEAT_NUMBER_KEYS):
        seat_number = _seat_number_from_value(value)
        if seat_number:
            return seat_number

    for text in _metadata_texts(metadata):
        labelled = LABELED_SEAT_NUMBER_PATTERN.search(text)
        if labelled:
            return labelled.group(1).upper()
    return None


def coach_from_metadata(metadata: object) -> str | None:
    """Extract the coach/carriage label associated with one selectable seat."""
    for value in _metadata_values(metadata, COACH_KEYS):
        for text in _metadata_texts(value):
            labelled = LABELED_COACH_PATTERN.search(text)
            if labelled:
                return labelled.group(1).upper()
            compact = re.sub(r"\s+", "", text)
            if COACH_VALUE_PATTERN.fullmatch(compact):
                return compact.upper()

    for text in _metadata_texts(metadata):
        labelled = LABELED_COACH_PATTERN.search(text)
        if labelled:
            return labelled.group(1).upper()
    return None


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
        try:
            await page.wait_for_url(TRIP_URL_PATTERN, timeout=45_000)
        except PlaywrightTimeoutError:
            await assert_authenticated(page)
            raise
        await page.wait_for_selector("tr", timeout=30_000)

        rows = page.locator("tbody tr:visible").filter(has_text="Pick Seats")
        matching_trains: list[MatchingTrain] = []
        for index in range(await rows.count()):
            row = rows.nth(index)
            cells = await row.locator("td").all_text_contents()
            service = cells[0].strip() if cells else ""
            departure = cells[1].strip() if len(cells) > 1 else ""
            if not in_time_window(departure, monitor.start_time, monitor.end_time):
                continue

            await _open_seat_modal(page, row)
            ordinary_seats, seat_numbers, seat_details = await _ordinary_seat_availability(page)

            if ordinary_seats:
                matching_trains.append(
                    MatchingTrain(
                        service=service,
                        departure=departure,
                        ordinarySeats=ordinary_seats,
                        seatNumbers=seat_numbers,
                        seatDetails=seat_details,
                    )
                )

            await _close_seat_modal(page)

        return CheckResult(
            monitorId=monitor.id,
            availableSeats=sum(train.ordinary_seats for train in matching_trains),
            matchingTrains=matching_trains,
        )
    finally:
        await page.close()


async def _ordinary_seat_availability(
    page: Page,
) -> tuple[int, list[str], list[SeatDetail]]:
    seats = page.locator("#seatSelect img.selectable-icon[data-seat-data]")
    count = 0
    seat_numbers: list[str] = []
    seat_details: list[SeatDetail] = []
    seen_details: set[tuple[str | None, str | None]] = set()
    for index in range(await seats.count()):
        seat = seats.nth(index)
        if seat_is_ordinary(await seat.get_attribute("src"), base_url=page.url):
            count += 1
            metadata = await seat.evaluate(
                r"""
                (element) => {
                  const attributes = (node) => Object.fromEntries(
                    Array.from(node?.attributes ?? []).map((item) => [item.name, item.value])
                  );
                  const coachContext = [];
                  for (
                    let node = element.parentElement;
                    node && node.id !== "seatSelect";
                    node = node.parentElement
                  ) {
                    const identity = `${node.id} ${node.className}`;
                    const data = { ...node.dataset };
                    const attrs = attributes(node);
                    const hasCoachMarker = /coach|carriage|(^|[-_\s])car($|[-_\s])/i.test(identity)
                      || Object.keys({ ...data, ...attrs }).some(
                        (key) => /coach|carriage|(^|[-_])car($|[-_])/i.test(key)
                      );
                    if (hasCoachMarker) {
                      coachContext.push({
                        id: node.id,
                        className: node.className,
                        dataset: data,
                        attributes: attrs,
                        text: node.textContent?.trim() ?? "",
                      });
                    }
                  }
                  return {
                    seat: {
                      dataset: { ...element.dataset },
                      attributes: attributes(element),
                      ariaLabel: element.getAttribute("aria-label"),
                      alt: element.getAttribute("alt"),
                      title: element.getAttribute("title"),
                      parentText: element.parentElement?.textContent?.trim() ?? "",
                    },
                    coachContext,
                  };
                }
                """
            )
            seat_metadata = metadata.get("seat", {}) if isinstance(metadata, dict) else metadata
            seat_number = seat_number_from_metadata(seat_metadata)
            coach = coach_from_metadata(metadata)
            if seat_number:
                seat_numbers.append(seat_number)
            detail_key = (coach, seat_number)
            if detail_key != (None, None) and detail_key not in seen_details:
                seen_details.add(detail_key)
                seat_details.append(SeatDetail(coach=coach, seatNumber=seat_number))
    return count, seat_numbers, seat_details


async def _open_seat_modal(page: Page, row: Locator) -> None:
    """Open one visible seat map with a DOM-click fallback for KTMB overlays."""
    buttons = row.locator(
        "a.btn-seat-layout:visible, button.btn-seat-layout:visible, a:visible, button:visible"
    ).filter(has_text=re.compile(r"^\s*Pick Seats\s*$", re.IGNORECASE))
    button = buttons.first
    if await buttons.count() == 0:
        raise PlaywrightTimeoutError("No visible Pick Seats control was found.")

    await button.scroll_into_view_if_needed(timeout=10_000)
    try:
        await button.click(timeout=10_000)
    except PlaywrightTimeoutError:
        LOGGER.warning("Normal Pick Seats click timed out; using a DOM click fallback.")
        await button.evaluate("(element) => element.click()")

    await page.locator("#seatSelect").wait_for(state="visible", timeout=15_000)
    await page.wait_for_selector("#seatSelect.show img", timeout=15_000)


async def _close_seat_modal(page: Page) -> None:
    close_button = page.locator(
        "#seatSelect button.close:visible, #seatSelect [data-dismiss='modal']:visible"
    ).first
    await close_button.click(timeout=10_000)
    await page.locator("#seatSelect").wait_for(state="hidden", timeout=10_000)
