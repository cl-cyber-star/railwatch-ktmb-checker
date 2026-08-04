"""Typed asynchronous client for the hosted Railwatch backend."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Self

import httpx
from playwright.async_api import StorageState
from pydantic import ValidationError

from railwatch.config import Settings
from railwatch.errors import ApiError, SessionError
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
    decrypt_storage_state,
    encrypt_storage_state,
    storage_state_fingerprint,
)

LOGGER = logging.getLogger(__name__)


class RailwatchApi:
    """Backend access with checker authentication and response validation."""

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
        await self._request("POST", "/api/checker", json=result.api_payload())

    async def get_sessions(self, owner_emails: set[str]) -> dict[str, SessionMaterial]:
        """Load each user-owned KTMB session from the existing per-owner endpoint."""
        materials: dict[str, SessionMaterial] = {}
        checker_secret = self._settings.checker_secret.get_secret_value()
        for requested_owner in sorted(owner_emails):
            owner_email = requested_owner.casefold()
            try:
                response = await self._client.get(
                    self._settings.session_api_path,
                    params={"ownerEmail": owner_email},
                )
            except httpx.HTTPError as exc:
                raise ApiError("User-session API could not be reached.") from exc
            self._raise_for_status(response, "User-session API")
            try:
                session = SessionEnvelope.model_validate(response.json()).session
            except (ValueError, ValidationError) as exc:
                raise ApiError("User-session API returned an invalid response.") from exc
            if session is None:
                continue

            fingerprint = session.bootstrap_fingerprint or ""
            if not fingerprint:
                materials[owner_email] = SessionMaterial(
                    owner_email=owner_email,
                    storage_state=None,
                    version=session.version,
                    status="reauth_required",
                    bootstrap_fingerprint="0" * 64,
                    error="The stored KTMB session metadata is incomplete.",
                )
                continue
            try:
                state = decrypt_storage_state(session.encrypted_state, checker_secret)
            except SessionError:
                LOGGER.warning("One user session could not be decrypted; reconnection is required.")
                materials[owner_email] = SessionMaterial(
                    owner_email=owner_email,
                    storage_state=None,
                    version=session.version,
                    status="reauth_required",
                    bootstrap_fingerprint=fingerprint,
                    error="The stored KTMB session could not be decrypted.",
                )
                continue

            materials[owner_email] = SessionMaterial(
                owner_email=owner_email,
                storage_state=state,
                version=session.version,
                status=session.status,
                bootstrap_fingerprint=fingerprint,
            )
        return materials

    async def save_session(
        self,
        owner_email: str,
        storage_state: StorageState,
        *,
        expected_version: int,
    ) -> int | None:
        """Persist one user's refreshed cookies using optimistic concurrency."""
        checker_secret = self._settings.checker_secret.get_secret_value()
        payload = SessionSaveRequest(
            ownerEmail=owner_email,
            encryptedState=encrypt_storage_state(storage_state, checker_secret),
            bootstrapFingerprint=storage_state_fingerprint(storage_state),
            expectedVersion=expected_version,
        ).model_dump(by_alias=True)
        try:
            response = await self._client.put(self._settings.session_api_path, json=payload)
        except httpx.HTTPError as exc:
            raise ApiError("User-session API could not be reached.") from exc
        if response.status_code == 409:
            LOGGER.warning("A newer KTMB session exists; this account run will not overwrite it.")
            return None
        self._raise_for_status(response, "User-session API")
        try:
            return SessionSaveResponse.model_validate(response.json()).version
        except (ValueError, ValidationError) as exc:
            raise ApiError("User-session API returned an invalid save response.") from exc

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
