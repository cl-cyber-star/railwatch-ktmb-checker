import json

import httpx
import pytest

from railwatch.api import RailwatchApi
from railwatch.config import Settings
from railwatch.models import CheckResult
from railwatch.session import encode_storage_state


def make_settings(seed: str) -> Settings:
    return Settings.model_validate(
        {
            "RAILWATCH_API_URL": "https://railwatch.example",
            "RAILWATCH_CHECKER_SECRET": "checker-secret",
            "OAI_SITES_AUTHORIZATION": "sites-secret",
            "KTMB_STORAGE_STATE_B64": seed,
        }
    )


@pytest.mark.asyncio
async def test_api_preserves_monitor_and_result_contract() -> None:
    seed = encode_storage_state({"cookies": [], "origins": []})
    seen_result: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer checker-secret"
        assert request.headers["oai-sites-authorization"] == "Bearer sites-secret"
        if request.method == "GET" and request.url.path == "/api/checker":
            return httpx.Response(
                200,
                json={
                    "monitors": [
                        {
                            "id": 1,
                            "originId": "100",
                            "destinationId": "200",
                            "travelDate": "2026-08-01",
                            "startTime": "08:00",
                            "endTime": "12:00",
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/api/checker":
            seen_result.update(json.loads(request.content))
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    client = httpx.AsyncClient(
        base_url="https://railwatch.example",
        headers=make_settings(seed).api_headers,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        api = RailwatchApi(make_settings(seed), client=client)
        monitors = await api.get_monitors()
        await api.post_result(
            CheckResult(
                monitorId=monitors[0].id,
                availableSeats=0,
                matchingTrains=[],
            )
        )

    assert monitors[0].origin_id == "100"
    assert seen_result == {
        "monitorId": 1,
        "availableSeats": 0,
        "matchingTrains": [],
    }


@pytest.mark.asyncio
async def test_session_rotation_uses_versioned_contract() -> None:
    seed = encode_storage_state({"cookies": [], "origins": []})
    refreshed = encode_storage_state(
        {"cookies": [{"name": "session", "value": "new"}], "origins": []}
    )
    seen_save: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"storageStateB64": seed, "version": 7},
            )
        seen_save.update(json.loads(request.content))
        return httpx.Response(200, json={"version": 8})

    settings = make_settings(seed)
    client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers=settings.api_headers,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        api = RailwatchApi(settings, client=client)
        loaded = await api.load_session(seed)
        version = await api.save_session(refreshed, expected_version=loaded.version)

    assert loaded.source == "server"
    assert loaded.version == 7
    assert version == 8
    assert seen_save == {
        "storageStateB64": refreshed,
        "expectedVersion": 7,
    }


@pytest.mark.asyncio
async def test_missing_session_endpoint_falls_back_to_secret() -> None:
    seed = encode_storage_state({"cookies": [], "origins": []})
    settings = make_settings(seed)
    client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers=settings.api_headers,
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
    )
    async with client:
        api = RailwatchApi(settings, client=client)
        loaded = await api.load_session(seed)
        saved = await api.save_session(seed, expected_version=None)

    assert loaded.source == "secret"
    assert saved is None
