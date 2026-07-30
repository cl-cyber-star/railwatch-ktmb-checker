"""KTMB Playwright storage-state encoding and validation."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Literal, cast

from playwright.async_api import StorageState

from railwatch.errors import SessionError


@dataclass(frozen=True, slots=True)
class SessionMaterial:
    """A decoded browser session and its server-side version."""

    storage_state: StorageState
    encoded: str
    version: int | None
    source: Literal["server", "secret"]


def decode_storage_state(encoded: str) -> StorageState:
    """Decode and validate a Base64-encoded Playwright storage state."""
    try:
        raw = base64.b64decode(encoded, validate=True)
        value = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionError("KTMB_STORAGE_STATE_B64 is not valid Base64 JSON.") from exc

    if not isinstance(value, dict):
        raise SessionError("The decoded KTMB storage state must be a JSON object.")
    if not isinstance(value.get("cookies", []), list):
        raise SessionError("The KTMB storage state's cookies field must be a list.")
    if not isinstance(value.get("origins", []), list):
        raise SessionError("The KTMB storage state's origins field must be a list.")

    return cast(StorageState, value)


def encode_storage_state(storage_state: StorageState) -> str:
    """Encode a Playwright storage state without logging its contents."""
    serialized = json.dumps(
        storage_state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.b64encode(serialized).decode("ascii")
