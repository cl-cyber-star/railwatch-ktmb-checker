from datetime import date
from typing import Any, cast

import pytest
from playwright.async_api import Browser, BrowserContext

from railwatch.errors import SessionRejectedError
from railwatch.models import Monitor
from railwatch.service import _open_authenticated_context, _process_monitors
from railwatch.session import SessionMaterial, encode_storage_state


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


@pytest.mark.asyncio
async def test_rejected_server_session_uses_new_secret_seed(monkeypatch: Any) -> None:
    server_state = {"cookies": [{"name": "session", "value": "old"}], "origins": []}
    fallback_state = {
        "cookies": [{"name": "session", "value": "new"}],
        "origins": [],
    }
    selected = SessionMaterial(
        storage_state=cast(Any, server_state),
        encoded=encode_storage_state(cast(Any, server_state)),
        version=4,
        source="server",
    )
    fallback_encoded = encode_storage_state(cast(Any, fallback_state))
    calls = 0

    async def fake_preflight(_: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SessionRejectedError("expired")

    monkeypatch.setattr("railwatch.service.preflight_session", fake_preflight)
    browser = FakeBrowser()

    context, recovered = await _open_authenticated_context(
        cast(Browser, browser),
        selected,
        fallback_encoded=fallback_encoded,
        fallback_state=cast(Any, fallback_state),
    )

    assert cast(FakeContext, context).state == fallback_state
    assert recovered.source == "secret"
    assert recovered.version == 4
    assert browser.contexts[0].closed is True
    assert calls == 2


@pytest.mark.asyncio
async def test_monitor_failure_is_posted_as_error_without_successful_zero(
    monkeypatch: Any,
) -> None:
    monitor = Monitor(
        id=1,
        originId="100",
        destinationId="200",
        travelDate=date(2026, 8, 1),
        startTime="08:00",
        endTime="12:00",
    )
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
        [monitor],
    )

    result = cast(Any, posted[0])
    assert failures == ["Monitor 1: KTMB page changed"]
    assert result.error == "KTMB page changed"
    assert result.available_seats == 0
