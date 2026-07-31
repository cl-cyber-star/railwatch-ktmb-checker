"""Typed asynchronous client for the hosted Railwatch backend."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Self

import httpx
from playwright.async_api import StorageState
from pydantic import ValidationError

from railwatch.config import Settings
from railwatch.errors import ApiError
from railwatch.models import (
    CheckResult,
    Monitor,
    MonitorEnvelope,
    SessionEnvelope,
    SessionSaveRequest,
    SessionSaveResponse,
)
from railwatch.session import (
    SessionMaterial,
    decode_storage_state,
    decrypt_storage_state,
    encode_storage_state,
    encrypt_storage_state,
    storage_state_fingerprint,
)

LOGGER = logging.getLogger(__name__)


class RailwatchApi:
    """Backend access with shared authentication and response validation."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.api_base_url,
            headers=settings.api_headers,
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            follow_redirects=False,
        )
        self._session_store_available = settings.session_rotation_enabled

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_monitors(self) -> list[Monitor]:
        response = await self._request("GET", "/api/checker")
        try:
            return MonitorEnvelope.model_validate(response.json()).monitors
        except (ValueError, ValidationError) as exc:
            raise ApiError("Monitor API returned an invalid response.") from exc

    async def post_result(self, result: CheckResult) -> None:
        await self._request(
            "POST",
            "/api/checker",
            json=result.api_payload(),
        )

    async def load_session(self, fallback_encoded: str) -> SessionMaterial:
        """Load the latest server session, with the secret as a recovery seed."""
        fallback_state = decode_storage_state(fallback_encoded)
        fallback_fingerprint = storage_state_fingerprint(fallback_state)
        fallback = SessionMaterial(
            storage_state=fallback_state,
            encoded=fallback_encoded,
            version=None,
            source="secret",
            bootstrap_fingerprint=fallback_fingerprint,
        )

        if not self._session_store_available:
            return fallback

        response = await self._client.get(self._settings.session_api_path)
        if response.status_code in {204, 404}:
            self._session_store_available = False
            LOGGER.warning(
                "Rotating-session endpoint is unavailable; using the GitHub secret seed."
            )
            return fallback
        self._raise_for_status(response, "Session API")

        try:
            envelope = SessionEnvelope.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ApiError("Session API returned an invalid response.") from exc

        session = envelope.session
        if session is None:
            return fallback
        if session.bootstrap_fingerprint is None:
            raise ApiError(
                "Stored KTMB session metadata is incomplete. Recapture the session once."
            )
        if session.bootstrap_fingerprint != fallback_fingerprint:
            LOGGER.info("A newly captured KTMB session will replace the stored state.")
            return SessionMaterial(
                storage_state=fallback_state,
                encoded=fallback_encoded,
                version=session.version,
                source="secret",
                bootstrap_fingerprint=fallback_fingerprint,
            )

        checker_secret = self._settings.checker_secret.get_secret_value()
        state = decrypt_storage_state(session.encrypted_state, checker_secret)
        return SessionMaterial(
            storage_state=state,
            encoded=encode_storage_state(state),
            version=session.version,
            source="server",
            bootstrap_fingerprint=session.bootstrap_fingerprint,
        )

    async def save_session(
        self,
        storage_state: StorageState,
        *,
        expected_version: int | None,
        bootstrap_fingerprint: str,
    ) -> int | None:
        """Persist refreshed cookies using optimistic concurrency."""
        if not self._session_store_available:
            return None

        checker_secret = self._settings.checker_secret.get_secret_value()
        payload = SessionSaveRequest(
            encryptedState=encrypt_storage_state(storage_state, checker_secret),
            bootstrapFingerprint=bootstrap_fingerprint,
            expectedVersion=expected_version,
        ).model_dump(by_alias=True, exclude_none=True)
        response = await self._client.put(
            self._settings.session_api_path,
            json=payload,
        )
        if response.status_code == 409:
            LOGGER.warning("A newer KTMB session already exists; this run will not overwrite it.")
            return None
        if response.status_code == 404:
            self._session_store_available = False
            LOGGER.warning("Rotating-session endpoint disappeared; session was not persisted.")
            return None
        self._raise_for_status(response, "Session API")

        try:
            return SessionSaveResponse.model_validate(response.json()).version
        except (ValueError, ValidationError) as exc:
            raise ApiError("Session API returned an invalid save response.") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise ApiError(f"{path} could not be reached.") from exc
        self._raise_for_status(response, "Railwatch API")
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, label: str) -> None:
        if response.is_success:
            return
        raise ApiError(
            f"{label} returned HTTP {response.status_code}.",
            status_code=response.status_code,
        )
