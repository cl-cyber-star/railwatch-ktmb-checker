from datetime import date
from typing import Any

import pytest

from railwatch.config import Settings
from railwatch.dashboard import (
    filter_monitors,
    load_dashboard_snapshot,
    monitor_card_html,
    next_travel_date,
)
from railwatch.models import Monitor
from railwatch.session import SessionMaterial, encode_storage_state


@pytest.fixture
def monitors() -> tuple[Monitor, ...]:
    return (
        Monitor(
            id="northbound",
            originId="SEGAMAT",
            destinationId="KL SENTRAL",
            travelDate=date(2026, 8, 4),
            startTime="09:00",
            endTime="12:00",
        ),
        Monitor(
            id="southbound",
            originId="GEMAS",
            destinationId="JB SENTRAL",
            travelDate=date(2026, 8, 2),
            startTime="15:00",
            endTime="18:00",
        ),
    )


def test_filter_monitors_matches_route_date_time_and_id(
    monitors: tuple[Monitor, ...],
) -> None:
    assert filter_monitors(monitors, "kl sentral") == (monitors[0],)
    assert filter_monitors(monitors, "2026-08-02") == (monitors[1],)
    assert filter_monitors(monitors, "15:00") == (monitors[1],)
    assert filter_monitors(monitors, "northbound") == (monitors[0],)


def test_filter_monitors_returns_all_for_blank_query(
    monitors: tuple[Monitor, ...],
) -> None:
    assert filter_monitors(monitors, "  ") == monitors


def test_next_travel_date_ignores_past_dates(
    monitors: tuple[Monitor, ...],
) -> None:
    assert next_travel_date(monitors, today=date(2026, 8, 3)) == date(2026, 8, 4)
    assert next_travel_date(monitors, today=date(2026, 8, 5)) is None


def test_monitor_card_escapes_api_values() -> None:
    monitor = Monitor(
        id="<script>",
        originId="<b>SEGAMAT</b>",
        destinationId="KL & SENTRAL",
        travelDate=date(2026, 8, 4),
        startTime="09:00",
        endTime="12:00",
    )

    rendered = monitor_card_html(monitor)

    assert "<script>" not in rendered
    assert "<b>SEGAMAT</b>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&lt;b&gt;SEGAMAT&lt;/b&gt;" in rendered
    assert "KL &amp; SENTRAL" in rendered


@pytest.mark.asyncio
async def test_snapshot_sorts_monitors_and_exposes_only_session_metadata(
    monkeypatch: Any,
    monitors: tuple[Monitor, ...],
) -> None:
    seed = encode_storage_state({"cookies": [], "origins": []})
    settings = Settings.model_validate(
        {
            "RAILWATCH_API_URL": "https://railwatch.example",
            "RAILWATCH_CHECKER_SECRET": "checker-secret",
            "OAI_SITES_AUTHORIZATION": "sites-secret",
            "KTMB_STORAGE_STATE_B64": seed,
        }
    )

    class FakeApi:
        def __init__(self, _: Settings) -> None:
            pass

        async def __aenter__(self) -> "FakeApi":
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

        async def get_monitors(self) -> list[Monitor]:
            return list(monitors)

        async def load_session(self, _: str) -> SessionMaterial:
            return SessionMaterial(
                storage_state={"cookies": [], "origins": []},
                encoded=seed,
                version=8,
                source="server",
            )

    monkeypatch.setattr("railwatch.dashboard.RailwatchApi", FakeApi)

    snapshot = await load_dashboard_snapshot(settings)

    assert [monitor.id for monitor in snapshot.monitors] == ["southbound", "northbound"]
    assert snapshot.session_source == "server"
    assert snapshot.session_version == 8
