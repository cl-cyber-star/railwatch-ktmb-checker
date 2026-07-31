"""KTMB Playwright storage-state encoding and validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Literal, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from playwright.async_api import StorageState

from railwatch.errors import SessionError

AUTH_TAG_BYTES = 16
SESSION_KEY_PREFIX = "railwatch-ktmb-session-v1:"


@dataclass(frozen=True, slots=True)
class SessionMaterial:
    """A decoded browser session and its server-side version."""

    storage_state: StorageState
    encoded: str
    version: int | None
    source: Literal["server", "secret"]
    bootstrap_fingerprint: str


def _validate_storage_state(value: object) -> StorageState:
    if not isinstance(value, dict):
        raise SessionError("The decoded KTMB storage state must be a JSON object.")
    if not isinstance(value.get("cookies", []), list):
        raise SessionError("The KTMB storage state's cookies field must be a list.")
    if not isinstance(value.get("origins", []), list):
        raise SessionError("The KTMB storage state's origins field must be a list.")
    return cast(StorageState, value)


def _serialize_storage_state(storage_state: StorageState) -> bytes:
    return json.dumps(
        storage_state,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _session_key(checker_secret: str) -> bytes:
    return hashlib.sha256(f"{SESSION_KEY_PREFIX}{checker_secret}".encode()).digest()


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def decode_storage_state(encoded: str) -> StorageState:
    """Decode and validate a Base64-encoded Playwright storage state."""
    try:
        raw = base64.b64decode(encoded, validate=True)
        value = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionError("KTMB_STORAGE_STATE_B64 is not valid Base64 JSON.") from exc

    return _validate_storage_state(value)


def encode_storage_state(storage_state: StorageState) -> str:
    """Encode a Playwright storage state without logging its contents."""
    serialized = json.dumps(
        storage_state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.b64encode(serialized).decode("ascii")


def storage_state_fingerprint(storage_state: StorageState) -> str:
    """Match the SHA-256 bootstrap fingerprint produced by the Node checker."""
    return hashlib.sha256(_serialize_storage_state(storage_state)).hexdigest()


def encrypt_storage_state(storage_state: StorageState, checker_secret: str) -> str:
    """Encrypt storage state using the deployed AES-256-GCM envelope."""
    iv = os.urandom(12)
    ciphertext_and_tag = AESGCM(_session_key(checker_secret)).encrypt(
        iv,
        _serialize_storage_state(storage_state),
        None,
    )
    ciphertext = ciphertext_and_tag[:-AUTH_TAG_BYTES]
    tag = ciphertext_and_tag[-AUTH_TAG_BYTES:]
    envelope = {
        "v": 1,
        "iv": base64.urlsafe_b64encode(iv).decode().rstrip("="),
        "tag": base64.urlsafe_b64encode(tag).decode().rstrip("="),
        "data": base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
    }
    return json.dumps(envelope, separators=(",", ":"))


def decrypt_storage_state(encrypted_state: str, checker_secret: str) -> StorageState:
    """Decrypt the AES-256-GCM envelope written by either checker implementation."""
    try:
        envelope = json.loads(encrypted_state)
        if not isinstance(envelope, dict) or envelope.get("v") != 1:
            raise ValueError("unsupported session version")
        iv = _base64url_decode(str(envelope["iv"]))
        tag = _base64url_decode(str(envelope["tag"]))
        ciphertext = _base64url_decode(str(envelope["data"]))
        if len(iv) != 12 or len(tag) != AUTH_TAG_BYTES:
            raise ValueError("invalid session envelope")
        plaintext = AESGCM(_session_key(checker_secret)).decrypt(
            iv,
            ciphertext + tag,
            None,
        )
        return _validate_storage_state(json.loads(plaintext.decode("utf-8")))
    except (
        binascii.Error,
        InvalidTag,
        KeyError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise SessionError(
            "The stored KTMB session could not be decrypted. Reconnect it once."
        ) from exc
