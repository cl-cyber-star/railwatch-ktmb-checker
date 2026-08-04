import json

import httpx
import pytest

from railwatch.api import RailwatchApi
from railwatch.config import Settings
from railwatch.models import CheckResult
from railwatch.session import encrypt_storage_state, storage_state_fingerprint


def make_settings() -> Settings:
    return Settings.model_validate(
        {
            "RAILWATCH_API_URL": "https://railwatch.example",
            "RAILWATCH_CHECKER_SECRET": "checker-secret",
            "OAI_SITES_AUTHORIZATION": "sites-secret",
        }
    )


@pytest.mark.asyncio
async def test_api_preserves_monitor_and_result_contract() -> None:
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
                            "ownerEmail": "owner@example.com",
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

    settings = make_settings()
    client = httpx.AsyncClient(
        base_url="https://railwatch.example",
        headers=settings.api_headers,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        api = RailwatchApi(settings, client=client)
        monitors = await api.get_monitors()
        await api.post_result(
            CheckResult(
                monitorId=monitors[0].id,
                availableSeats=0,
                matchingTrains=[],
            )
        )

    assert monitors[0].owner_email == "owner@example.com"
    assert seen_result == {
        "monitorId": 1,
        "availableSeats": 0,
        "matchingTrains": [],
    }


@pytest.mark.asyncio
async def test_per_user_session_load_and_save_contract() -> None:
    initial_state = {
        "cookies": [{"name": "session", "value": "old"}],
        "origins": [],
    }
    refreshed = {
        "cookies": [{"name": "session", "value": "new"}],
        "origins": [],
    }
    encrypted = encrypt_storage_state(initial_state, "checker-secret")
    fingerprint = storage_state_fingerprint(initial_state)
    seen_save: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/checker/session"
        if request.method == "GET":
            assert request.url.params["ownerEmail"] == "owner@example.com"
            return httpx.Response(
                200,
                json={
                    "session": {
                        "encryptedState": encrypted,
                        "bootstrapFingerprint": fingerprint,
                        "version": 7,
                        "status": "connected",
                    }
                },
            )
        seen_save.update(json.loads(request.content))
        return httpx.Response(200, json={"version": 8})

    settings = make_settings()
    client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers=settings.api_headers,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        api = RailwatchApi(settings, client=client)
        sessions = await api.get_sessions({"owner@example.com"})
        loaded = sessions["owner@example.com"]
        version = await api.save_session(
            loaded.owner_email,
            refreshed,
            expected_version=loaded.version,
        )

    assert loaded.storage_state == initial_state
    assert loaded.version == 7
    assert version == 8
    assert seen_save["ownerEmail"] == "owner@example.com"
    assert seen_save["expectedVersion"] == 7
    assert seen_save["bootstrapFingerprint"] == storage_state_fingerprint(refreshed)
    assert isinstance(seen_save["encryptedState"], str)


@pytest.mark.asyncio
async def test_session_conflict_does_not_overwrite_newer_user_state() -> None:
    settings = make_settings()
    client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers=settings.api_headers,
        transport=httpx.MockTransport(lambda _: httpx.Response(409)),
    )
    async with client:
        version = await RailwatchApi(settings, client=client).save_session(
            "owner@example.com",
            {"cookies": [], "origins": []},
            expected_version=4,
        )

    assert version is None


@pytest.mark.asyncio
async def test_corrupt_user_session_isolated_for_reconnect() -> None:
    fingerprint = "0" * 64

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "session": {
                    "encryptedState": "x" * 120,
                    "bootstrapFingerprint": fingerprint,
                    "version": 2,
                    "status": "connected",
                }
            },
        )

    settings = make_settings()
    client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers=settings.api_headers,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        sessions = await RailwatchApi(settings, client=client).get_sessions({"owner@example.com"})

    session = sessions["owner@example.com"]
    assert session.storage_state is None
    assert session.status == "reauth_required"
    assert session.error == "The stored KTMB session could not be decrypted."
