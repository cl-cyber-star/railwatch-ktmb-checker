"""Validated domain and API models."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


def validate_clock_time(value: str) -> str:
    """Validate a 24-hour HH:MM value and return it unchanged."""
    if not TIME_PATTERN.fullmatch(value):
        raise ValueError("must use HH:MM format")
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("must be a valid 24-hour time")
    return value


def in_time_window(value: str, start: str, end: str) -> bool:
    """Return whether a departure is in the inclusive same-day window."""
    try:
        validate_clock_time(value)
        validate_clock_time(start)
        validate_clock_time(end)
    except ValueError:
        return False
    return start <= value <= end


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Monitor(ApiModel):
    id: int | str
    origin_id: str = Field(alias="originId", min_length=1, max_length=100)
    destination_id: str = Field(alias="destinationId", min_length=1, max_length=100)
    travel_date: date = Field(alias="travelDate")
    start_time: str = Field(alias="startTime")
    end_time: str = Field(alias="endTime")

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        return validate_clock_time(value)

    @field_validator("end_time")
    @classmethod
    def validate_window(cls, value: str, info: object) -> str:
        data = getattr(info, "data", {})
        start = data.get("start_time")
        if isinstance(start, str) and value < start:
            raise ValueError("overnight time windows are not supported")
        return value


class MonitorEnvelope(ApiModel):
    monitors: list[Monitor] = Field(default_factory=list)


class MatchingTrain(ApiModel):
    service: str
    departure: str
    ordinary_seats: int = Field(alias="ordinarySeats", ge=0)


class CheckResult(ApiModel):
    monitor_id: int | str = Field(alias="monitorId")
    available_seats: int = Field(alias="availableSeats", ge=0)
    matching_trains: list[MatchingTrain] = Field(alias="matchingTrains")
    error: str | None = None

    def api_payload(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class SessionRecord(ApiModel):
    encrypted_state: str = Field(alias="encryptedState", min_length=100)
    bootstrap_fingerprint: str | None = Field(
        alias="bootstrapFingerprint",
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    version: int = Field(ge=1)
    updated_at: str | None = Field(alias="updatedAt", default=None)


class SessionEnvelope(ApiModel):
    session: SessionRecord | None = None


class SessionSaveRequest(ApiModel):
    encrypted_state: str = Field(alias="encryptedState", min_length=100)
    bootstrap_fingerprint: str = Field(
        alias="bootstrapFingerprint",
        pattern=r"^[a-f0-9]{64}$",
    )
    expected_version: int | None = Field(alias="expectedVersion", default=None, ge=1)


class SessionSaveResponse(ApiModel):
    version: int = Field(ge=1)
