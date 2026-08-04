from datetime import date

import pytest
from pydantic import ValidationError

from railwatch.models import CheckResult, MatchingTrain, Monitor, in_time_window


def test_monitor_accepts_existing_camel_case_payload() -> None:
    monitor = Monitor.model_validate(
        {
            "id": 42,
            "ownerEmail": "owner@example.com",
            "originId": "100",
            "destinationId": "200",
            "travelDate": "2026-08-01",
            "startTime": "08:00",
            "endTime": "12:30",
        }
    )

    assert monitor.travel_date == date(2026, 8, 1)
    assert monitor.origin_id == "100"


@pytest.mark.parametrize("value", ["8:00", "24:00", "10:60", "invalid"])
def test_monitor_rejects_invalid_times(value: str) -> None:
    with pytest.raises(ValidationError):
        Monitor.model_validate(
            {
                "id": "monitor",
                "ownerEmail": "owner@example.com",
                "originId": "100",
                "destinationId": "200",
                "travelDate": "2026-08-01",
                "startTime": value,
                "endTime": "23:00",
            }
        )


def test_monitor_rejects_overnight_window() -> None:
    with pytest.raises(ValidationError, match="overnight"):
        Monitor.model_validate(
            {
                "id": "monitor",
                "ownerEmail": "owner@example.com",
                "originId": "100",
                "destinationId": "200",
                "travelDate": "2026-08-01",
                "startTime": "22:00",
                "endTime": "02:00",
            }
        )


def test_time_window_is_inclusive() -> None:
    assert in_time_window("08:00", "08:00", "12:00")
    assert in_time_window("12:00", "08:00", "12:00")
    assert not in_time_window("12:01", "08:00", "12:00")
    assert not in_time_window("invalid", "08:00", "12:00")


def test_result_preserves_existing_api_shape() -> None:
    result = CheckResult(
        monitorId=42,
        availableSeats=3,
        matchingTrains=[MatchingTrain(service="9321", departure="09:30", ordinarySeats=3)],
    )

    assert result.api_payload() == {
        "monitorId": 42,
        "availableSeats": 3,
        "matchingTrains": [{"service": "9321", "departure": "09:30", "ordinarySeats": 3}],
    }
