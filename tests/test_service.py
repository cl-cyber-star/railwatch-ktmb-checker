from datetime import date
from typing import Any, cast

import pytest
from playwright.async_api import Browser, BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from railwatch.errors import SessionRejectedError
from railwatch.models import CheckResult, Monitor
from railwatch.service import _process_account, _process_monitors
from railwatch.session import SessionMaterial


class FakeContext:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []

    async def new_context(self, **kwargs: object) -> FakeContext:
        context = FakeContext(cast(dict[str, object], kwargs["storage_state"]))
        self.contexts.append(context)
        return context


def monitor() -> Monitor:
    return Monitor(
        id=1,
        ownerEmail="owner@example.com",
        originId="100",
        destinationId="200",
        travelDate=date(2026, 8, 1),
        startTime="08:00",
        endTime="12:00",
    )


@pytest.mark.asyncio
async def test_rejected_user_session_is_paused_without_blocking_other_accounts(
    monkeypatch: Any,
) -> None:
    posted: list[CheckResult] = []

    class FakeApi:
        async def post_result(self, result: CheckResult) -> None:
            posted.append(result)

    async def reject(_: object) -> None:
        raise SessionRejectedError("KTMB redirected to login")

    monkeypatch.setattr("railwatch.service.preflight_session", reject)
    browser = FakeBrowser()
    session = SessionMaterial(
        owner_email="owner@example.com",
        storage_state=cast(Any, {"cookies": [], "origins": []}),
        version=4,
        status="connected",
        bootstrap_fingerprint="0" * 64,
    )

    failures = await _process_account(
        cast(Any, FakeApi()),
        cast(Browser, browser),
        session,
        [monitor()],
    )

    assert failures == []
    assert posted[0].error_code == "reauth_required"
    assert posted[0].error == "KTMB redirected to login"
    assert browser.contexts[0].closed is True


@pytest.mark.asyncio
async def test_monitor_failure_is_posted_as_error_without_successful_zero(
    monkeypatch: Any,
) -> None:
    posted: list[object] = []

    class FakeApi:
        async def post_result(self, result: object) -> None:
            posted.append(result)

    async def failing_check(_: object, __: Monitor) -> None:
        raise RuntimeError("KTMB page changed")

    monkeypatch.setattr("railwatch.service.check_monitor", failing_check)

    failures = await _process_monitors(
        cast(Any, FakeApi()),
        cast(BrowserContext, object()),
        [monitor()],
    )

    result = cast(Any, posted[0])
    assert failures == ["Monitor 1: KTMB page changed"]
    assert result.error == "KTMB page changed"
    assert result.available_seats == 0


@pytest.mark.asyncio
async def test_temporary_playwright_failure_retries_once(monkeypatch: Any) -> None:
    calls = 0
    posted: list[CheckResult] = []

    class FakeApi:
        async def post_result(self, result: CheckResult) -> None:
            posted.append(result)

    async def flaky_check(_: object, item: Monitor) -> CheckResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PlaywrightTimeoutError("temporary overlay")
        return CheckResult(monitorId=item.id, availableSeats=0, matchingTrains=[])

    monkeypatch.setattr("railwatch.service.check_monitor", flaky_check)

    failures = await _process_monitors(
        cast(Any, FakeApi()),
        cast(BrowserContext, object()),
        [monitor()],
    )

    assert failures == []
    assert calls == 2
    assert len(posted) == 1
