"""Read-only dashboard data access and presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape

from railwatch.api import RailwatchApi
from railwatch.config import Settings
from railwatch.models import Monitor


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """Validated data required by the Streamlit operator dashboard."""

    monitors: tuple[Monitor, ...]
    connected_accounts: int
    reconnect_accounts: int


async def load_dashboard_snapshot(settings: Settings) -> DashboardSnapshot:
    """Load current monitors and non-sensitive session metadata."""
    async with RailwatchApi(settings) as api:
        monitors = await api.get_monitors()
        sessions = await api.get_sessions({monitor.owner_email.casefold() for monitor in monitors})

    return DashboardSnapshot(
        monitors=tuple(
            sorted(
                monitors,
                key=lambda monitor: (
                    monitor.travel_date,
                    monitor.start_time,
                    str(monitor.id),
                ),
            )
        ),
        connected_accounts=sum(session.status == "connected" for session in sessions.values()),
        reconnect_accounts=sum(
            session.status == "reauth_required" for session in sessions.values()
        ),
    )


def filter_monitors(monitors: tuple[Monitor, ...], query: str) -> tuple[Monitor, ...]:
    """Filter monitors by route, date, time, or identifier."""
    normalized = query.casefold().strip()
    if not normalized:
        return monitors

    return tuple(
        monitor
        for monitor in monitors
        if normalized
        in " ".join(
            (
                str(monitor.id),
                monitor.origin_id,
                monitor.destination_id,
                monitor.travel_date.isoformat(),
                monitor.start_time,
                monitor.end_time,
            )
        ).casefold()
    )


def next_travel_date(monitors: tuple[Monitor, ...], *, today: date) -> date | None:
    """Return the nearest monitored travel date that has not passed."""
    return min(
        (monitor.travel_date for monitor in monitors if monitor.travel_date >= today),
        default=None,
    )


def monitor_card_html(monitor: Monitor) -> str:
    """Render one monitor card while escaping all API-supplied values."""
    monitor_id = escape(str(monitor.id))
    origin = escape(monitor.origin_id)
    destination = escape(monitor.destination_id)
    travel_date = escape(monitor.travel_date.strftime("%d %b %Y"))
    time_window = escape(f"{monitor.start_time}–{monitor.end_time}")

    return f"""
    <article class="monitor-card">
      <div class="monitor-card__topline">
        <span class="monitor-card__eyebrow">MONITOR {monitor_id}</span>
        <span class="monitor-card__status">ACTIVE</span>
      </div>
      <div class="monitor-card__route">
        <span>{origin}</span>
        <span class="monitor-card__arrow" aria-hidden="true">→</span>
        <span>{destination}</span>
      </div>
      <div class="monitor-card__details">
        <span>📅 {travel_date}</span>
        <span>🕒 {time_window}</span>
      </div>
    </article>
    """
