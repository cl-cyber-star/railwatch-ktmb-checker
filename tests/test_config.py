import pytest
from pydantic import ValidationError

from railwatch.config import Settings
from railwatch.session import encode_storage_state


def test_required_configuration_and_headers() -> None:
    settings = Settings.model_validate(
        {
            "RAILWATCH_API_URL": "https://railwatch.example/",
            "RAILWATCH_CHECKER_SECRET": "checker-secret",
            "OAI_SITES_AUTHORIZATION": "sites-secret",
            "KTMB_STORAGE_STATE_B64": encode_storage_state({"cookies": [], "origins": []}),
        }
    )

    assert settings.api_base_url == "https://railwatch.example"
    assert settings.api_headers["authorization"] == "Bearer checker-secret"
    assert settings.session_rotation_enabled is True


def test_missing_required_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({})
