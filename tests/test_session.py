import base64
import json

import pytest

from railwatch.errors import SessionError
from railwatch.session import (
    decode_storage_state,
    decrypt_storage_state,
    encode_storage_state,
    encrypt_storage_state,
    storage_state_fingerprint,
)


def test_storage_state_round_trip() -> None:
    state = {
        "cookies": [{"name": "session", "value": "redacted"}],
        "origins": [],
    }

    encoded = encode_storage_state(state)

    assert decode_storage_state(encoded) == state
    assert "redacted" not in encoded


def test_node_session_envelope_compatibility() -> None:
    state = {
        "cookies": [{"name": "session", "value": "redacted"}],
        "origins": [],
    }
    node_envelope = (
        '{"v":1,"iv":"AAECAwQFBgcICQoL","tag":"ALjLNu396SNsD1rPCefGtw",'
        '"data":"a06BLGGxr0aaqnVtySo3XK3A887CuLlUtRyXh7JyvTPv8wEixgyP7tnjWveAYbGt'
        'cz6E3tFPG3cRcSTJWrRZ5Q"}'
    )

    assert decrypt_storage_state(node_envelope, "checker-secret") == state
    assert storage_state_fingerprint(state) == (
        "34b65f8e3790cea22d67ec06fed69d3904eee0014cc3b45aa6ca14ab47ce460f"
    )


def test_encrypted_storage_state_round_trip() -> None:
    state = {
        "cookies": [{"name": "session", "value": "redacted"}],
        "origins": [],
    }

    encrypted = encrypt_storage_state(state, "checker-secret")

    assert decrypt_storage_state(encrypted, "checker-secret") == state
    assert "redacted" not in encrypted


@pytest.mark.parametrize(
    "encoded",
    [
        "not-base64",
        base64.b64encode(b"not-json").decode(),
        base64.b64encode(json.dumps([]).encode()).decode(),
        base64.b64encode(json.dumps({"cookies": "wrong"}).encode()).decode(),
    ],
)
def test_storage_state_rejects_invalid_input(encoded: str) -> None:
    with pytest.raises(SessionError):
        decode_storage_state(encoded)
