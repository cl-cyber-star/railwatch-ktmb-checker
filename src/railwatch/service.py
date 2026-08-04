"""Railwatch checker orchestration."""

from __future__ import annotations

import logging
from collections import defaultdict
from hashlib import sha256

from playwright.async_api import (
    Browser,
    BrowserContext,
    StorageState,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from railwatch.api import RailwatchApi
from railwatch.config import Settings
from railwatch.errors import CheckerFailure, SessionRejectedError
from railwatch.ktmb import check_monitor, preflight_session
from railwatch.models import CheckResult, Monitor
from railwatch.session import SessionMaterial

LOGGER = logging.getLogger(__name__)


async def run_checker(settings: Settings) -> None:
    """Check every connected user in a separate browser context."""
    async with RailwatchApi(settings) as api:
        monitors = await api.get_monitors()
        if not monitors:
            LOGGER.info("Railwatch has no active journey monitors.")
            return

        monitors_by_owner: dict[str, list[Monitor]] = defaultdict(list)
        for monitor in monitors:
            monitors_by_owner[monitor.owner_email.casefold()].append(monitor)
        sessions = await api.get_sessions(set(monitors_by_owner))

        failures: list[str] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                for owner_key, owner_monitors in monitors_by_owner.items():
                    account_label = _account_label(owner_key)
                    session = sessions.get(owner_key)
                    if session is None:
                        LOGGER.warning(
                            "%s: no KTMB account is connected; %s monitor(s) skipped.",
                            account_label,
                            len(owner_monitors),
                        )
                        continue
                    if session.status != "connected":
                        if session.error:
                            await _report_reauth(api, owner_monitors[0], session.error)
                        LOGGER.warning(
                            "%s: KTMB reconnection is required; %s monitor(s) skipped.",
                            account_label,
                            len(owner_monitors),
                        )
                        continue

                    try:
                        account_failures = await _process_account(
                            api,
                            browser,
                            session,
                            owner_monitors,
                        )
                        failures.extend(account_failures)
                    except Exception as exc:
                        message = _safe_error_message(exc)
                        failures.append(f"{account_label}: {message}")
                        LOGGER.error("%s: account check failed: %s", account_label, message)
            finally:
                await browser.close()

        if failures:
            raise CheckerFailure(f"Railwatch check failed: {' | '.join(failures)}")


async def _process_account(
    api: RailwatchApi,
    browser: Browser,
    session: SessionMaterial,
    monitors: list[Monitor],
) -> list[str]:
    if session.storage_state is None:
        await _report_reauth(
            api,
            monitors[0],
            session.error or "The stored KTMB session is unavailable.",
        )
        return []
    context = await _new_context(browser, session.storage_state)
    account_label = _account_label(session.owner_email)
    try:
        try:
            await preflight_session(context)
        except SessionRejectedError as exc:
            await _report_reauth(api, monitors[0], str(exc))
            LOGGER.warning(
                "%s: KTMB rejected the session (%s); the user was asked to reconnect.",
                account_label,
                _safe_error_message(exc),
            )
            return []

        try:
            failures = await _process_monitors(api, context, monitors)
        except SessionRejectedError as exc:
            await _report_reauth(api, monitors[0], str(exc))
            LOGGER.warning(
                "%s: KTMB ended the session during a check (%s); remaining monitors were skipped.",
                account_label,
                _safe_error_message(exc),
            )
            return []

        refreshed = await context.storage_state()
        version = await api.save_session(
            session.owner_email,
            refreshed,
            expected_version=session.version,
        )
        if version is not None:
            LOGGER.info(
                "%s: KTMB session refreshed and saved as version %s.",
                account_label,
                version,
            )
        return failures
    finally:
        await context.close()


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
            result = await _check_with_retry(context, monitor)
            LOGGER.info(
                "Monitor %s: %s ordinary seat(s) across %s matching train(s).",
                monitor.id,
                result.available_seats,
                len(result.matching_trains),
            )
        except SessionRejectedError:
            raise
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


async def _check_with_retry(
    context: BrowserContext,
    monitor: Monitor,
) -> CheckResult:
    for attempt in range(2):
        try:
            return await check_monitor(context, monitor)
        except SessionRejectedError:
            raise
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            if attempt == 1:
                raise
            LOGGER.warning(
                "Monitor %s: temporary KTMB interaction failed (%s); retrying once.",
                monitor.id,
                _safe_error_message(exc),
            )
    raise RuntimeError("Unreachable retry state")


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return message[:500]


def _account_label(owner_email: str) -> str:
    """Return a stable non-reversible account label safe for CI logs."""
    digest = sha256(owner_email.casefold().encode()).hexdigest()[:10]
    return f"account-{digest}"


async def _report_reauth(
    api: RailwatchApi,
    monitor: Monitor,
    error: str,
) -> None:
    await api.post_result(
        CheckResult(
            monitorId=monitor.id,
            availableSeats=0,
            matchingTrains=[],
            error=error[:400],
            errorCode="reauth_required",
        )
    )
