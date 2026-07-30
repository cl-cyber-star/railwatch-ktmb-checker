import base64
import json

import pytest

from railwatch.errors import SessionError
from railwatch.session import decode_storage_state, encode_storage_state


def test_storage_state_round_trip() -> None:
    state = {
        "cookies": [{"name": "session", "value": "redacted"}],
        "origins": [],
    }

    encoded = encode_storage_state(state)

    assert decode_storage_state(encoded) == state
    assert "redacted" not in encoded


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
