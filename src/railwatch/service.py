"""Railwatch checker orchestration."""

from __future__ import annotations

import logging

from playwright.async_api import Browser, BrowserContext, StorageState, async_playwright

from railwatch.api import RailwatchApi
from railwatch.config import Settings
from railwatch.errors import CheckerFailure, SessionRejectedError
from railwatch.ktmb import check_monitor, preflight_session
from railwatch.models import CheckResult, Monitor
from railwatch.session import (
    SessionMaterial,
    decode_storage_state,
    storage_state_fingerprint,
)

LOGGER = logging.getLogger(__name__)


async def run_checker(settings: Settings) -> None:
    """Fetch monitors, check KTMB, post results, and rotate session state."""
    fallback_encoded = settings.ktmb_storage_state_b64.get_secret_value()
    fallback_state = decode_storage_state(fallback_encoded)

    async with RailwatchApi(settings) as api:
        monitors = await api.get_monitors()
        if not monitors:
            raise CheckerFailure("Railwatch API returned no active monitors.")

        selected = await api.load_session(fallback_encoded)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context, selected = await _open_authenticated_context(
                    browser,
                    selected,
                    fallback_encoded=fallback_encoded,
                    fallback_state=fallback_state,
                )
                try:
                    failures = await _process_monitors(api, context, monitors)
                    refreshed = await context.storage_state()
                    version = await api.save_session(
                        refreshed,
                        expected_version=selected.version,
                        bootstrap_fingerprint=selected.bootstrap_fingerprint,
                    )
                    if version is not None:
                        LOGGER.info("KTMB session refreshed and saved as version %s.", version)
                finally:
                    await context.close()
            finally:
                await browser.close()

        if failures:
            raise CheckerFailure(f"Railwatch check failed: {' | '.join(failures)}")


async def _open_authenticated_context(
    browser: Browser,
    selected: SessionMaterial,
    *,
    fallback_encoded: str,
    fallback_state: StorageState,
) -> tuple[BrowserContext, SessionMaterial]:
    context = await _new_context(browser, selected.storage_state)
    try:
        await preflight_session(context)
        return context, selected
    except SessionRejectedError:
        await context.close()

    if selected.source != "server" or selected.encoded == fallback_encoded:
        raise SessionRejectedError("KTMB rejected both the stored session and recovery seed.")

    LOGGER.warning("Server session was rejected; trying the GitHub secret recovery seed.")
    fallback = SessionMaterial(
        storage_state=fallback_state,
        encoded=fallback_encoded,
        version=selected.version,
        source="secret",
        bootstrap_fingerprint=storage_state_fingerprint(fallback_state),
    )
    context = await _new_context(browser, fallback.storage_state)
    try:
        await preflight_session(context)
    except SessionRejectedError:
        await context.close()
        raise SessionRejectedError(
            "KTMB rejected both the stored session and recovery seed."
        ) from None
    return context, fallback


async def _new_context(
    browser: Browser,
    storage_state: StorageState,
) -> BrowserContext:
    return await browser.new_context(
        storage_state=storage_state,
        locale="en-MY",
        timezone_id="Asia/Kuala_Lumpur",
    )


async def _process_monitors(
    api: RailwatchApi,
    context: BrowserContext,
    monitors: list[Monitor],
) -> list[str]:
    failures: list[str] = []
    for monitor in monitors:
        try:
            result = await check_monitor(context, monitor)
            LOGGER.info(
                "Monitor %s: %s ordinary seat(s) across %s matching train(s).",
                monitor.id,
                result.available_seats,
                len(result.matching_trains),
            )
        except Exception as exc:
            message = _safe_error_message(exc)
            result = CheckResult(
                monitorId=monitor.id,
                availableSeats=0,
                matchingTrains=[],
                error=message,
            )
            failures.append(f"Monitor {monitor.id}: {message}")
            LOGGER.error("Monitor %s: %s", monitor.id, message)

        await api.post_result(result)
        LOGGER.info("Monitor %s: result accepted by Railwatch backend.", monitor.id)
    return failures


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return message[:500]
