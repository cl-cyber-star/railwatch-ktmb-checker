import pytest
from pydantic import ValidationError

from railwatch.config import Settings


def test_required_configuration_and_headers() -> None:
    settings = Settings.model_validate(
        {
            "RAILWATCH_API_URL": "https://railwatch.example/",
            "RAILWATCH_CHECKER_SECRET": "checker-secret",
            "OAI_SITES_AUTHORIZATION": "sites-secret",
        }
    )

    assert settings.api_base_url == "https://railwatch.example"
    assert settings.api_headers["authorization"] == "Bearer checker-secret"
    assert settings.session_api_path == "/api/checker/session"
    assert settings.ktmb_storage_state_b64 is None


def test_missing_required_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({})
