"""Streamlit operator frontend for Railwatch."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Mapping
from datetime import date
from typing import Any

import streamlit as st
from pydantic import ValidationError
from streamlit.errors import StreamlitSecretNotFoundError

from railwatch.config import Settings
from railwatch.dashboard import (
    DashboardSnapshot,
    filter_monitors,
    load_dashboard_snapshot,
    monitor_card_html,
    next_travel_date,
)
from railwatch.errors import RailwatchError
from railwatch.service import run_checker

SECRET_NAMES = (
    "RAILWATCH_API_URL",
    "RAILWATCH_CHECKER_SECRET",
    "OAI_SITES_AUTHORIZATION",
    "KTMB_STORAGE_STATE_B64",
    "RAILWATCH_SESSION_API_PATH",
    "KTMB_SESSION_ROTATION_ENABLED",
    "RAILWATCH_HTTP_TIMEOUT_SECONDS",
)


def _streamlit_secret_overrides(secrets: Mapping[str, Any]) -> dict[str, Any]:
    """Return only supported settings, leaving environment values as fallback."""
    return {name: secrets[name] for name in SECRET_NAMES if name in secrets}


def _load_settings() -> Settings:
    try:
        secret_values = st.secrets.to_dict()
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        secret_values = {}

    overrides = _streamlit_secret_overrides(secret_values)
    environment = {name: value for name in SECRET_NAMES if (value := os.getenv(name))}
    return Settings.model_validate(environment | overrides)


def _missing_settings(error: ValidationError) -> list[str]:
    return sorted(
        {
            str(item["loc"][0])
            for item in error.errors()
            if item.get("type") == "missing" and item.get("loc")
        }
    )


def _run_async[T](awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


def _load_snapshot(settings: Settings) -> DashboardSnapshot:
    return _run_async(load_dashboard_snapshot(settings))


def _render_styles() -> None:
    st.markdown(
        """
        <style>
          .stApp {
            background:
              radial-gradient(circle at 90% 0%, rgba(48, 90, 79, 0.10), transparent 28rem),
              #f6f3ec;
          }
          [data-testid="stHeader"] { background: transparent; }
          .block-container { max-width: 1120px; padding-top: 2.5rem; }
          .railwatch-kicker {
            color: #9b5c35;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            margin-bottom: 0.35rem;
          }
          .railwatch-subtitle {
            color: #58635f;
            font-size: 1.02rem;
            margin: 0.15rem 0 1.6rem;
          }
          .monitor-card {
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(43, 65, 59, 0.16);
            border-radius: 1.25rem;
            box-shadow: 0 0.75rem 2rem rgba(41, 55, 51, 0.07);
            box-sizing: border-box;
            height: auto;
            margin: 0.8rem 0;
            overflow: hidden;
            padding: 1.2rem 1.25rem 1.1rem;
            width: 100%;
          }
          .monitor-card__topline {
            align-items: center;
            display: flex;
            gap: 0.75rem;
            justify-content: space-between;
          }
          .monitor-card__eyebrow {
            color: #77817e;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            min-width: 0;
            overflow-wrap: break-word;
          }
          .monitor-card__status {
            background: #dcebe3;
            border-radius: 999px;
            color: #2e6e58;
            flex: 0 0 auto;
            font-size: 0.68rem;
            font-weight: 800;
            padding: 0.35rem 0.62rem;
          }
          .monitor-card__route {
            align-items: center;
            color: #1f302b;
            display: grid;
            font-family: Georgia, "Times New Roman", serif;
            font-size: clamp(1.28rem, 4vw, 1.85rem);
            font-weight: 700;
            gap: 0.7rem;
            grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
            line-height: 1.16;
            margin: 1rem 0;
          }
          .monitor-card__route > span {
            min-width: 0;
            overflow-wrap: break-word;
            white-space: normal;
            word-break: normal;
          }
          .monitor-card__route > span:last-child { text-align: right; }
          .monitor-card__arrow {
            color: #b46c40;
            font-family: system-ui, sans-serif;
            font-weight: 500;
          }
          .monitor-card__details {
            color: #64706c;
            display: flex;
            flex-wrap: wrap;
            font-size: 0.88rem;
            gap: 0.55rem 1.25rem;
          }
          @media (max-width: 520px) {
            .block-container { padding: 1.4rem 1rem 3rem; }
            .monitor-card { padding: 1rem; }
            .monitor-card__route {
              align-items: start;
              grid-template-columns: minmax(0, 1fr);
              gap: 0.3rem;
            }
            .monitor-card__route > span:last-child { text-align: left; }
            .monitor-card__arrow { transform: rotate(90deg); width: fit-content; }
            .monitor-card__details { align-items: flex-start; flex-direction: column; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown('<div class="railwatch-kicker">KTMB SEAT MONITOR</div>', unsafe_allow_html=True)
    st.title("Railwatch")
    st.markdown(
        '<p class="railwatch-subtitle">'
        "A Python and Streamlit operations dashboard for active journey monitors."
        "</p>",
        unsafe_allow_html=True,
    )


def _render_metrics(snapshot: DashboardSnapshot) -> None:
    nearest = next_travel_date(snapshot.monitors, today=date.today())
    session_label = (
        f"{snapshot.session_source.title()} · v{snapshot.session_version}"
        if snapshot.session_version is not None
        else snapshot.session_source.title()
    )
    first, second, third = st.columns(3)
    first.metric("Active monitors", len(snapshot.monitors))
    second.metric("Next journey", nearest.strftime("%d %b") if nearest else "None")
    third.metric("KTMB session", session_label)


def _render_sidebar(settings: Settings) -> None:
    st.sidebar.header("Checker controls")
    st.sidebar.caption("The scheduled GitHub worker continues to run every five minutes.")

    st.sidebar.checkbox(
        "I understand this checks every active monitor",
        key="confirm_check",
    )
    if st.sidebar.button(
        "Run checker now",
        type="primary",
        use_container_width=True,
        disabled=not st.session_state.get("confirm_check", False),
    ):
        with st.sidebar.status("Checking KTMB…", expanded=True) as status:
            try:
                _run_async(run_checker(settings))
            except RailwatchError as error:
                status.update(label="Checker failed", state="error")
                st.sidebar.error(str(error))
            except Exception:
                status.update(label="Checker failed", state="error")
                st.sidebar.error("An unexpected checker error occurred. Review the server logs.")
            else:
                status.update(label="Checker completed", state="complete")
                st.rerun()

    st.sidebar.divider()
    st.sidebar.caption(
        "This dashboard never displays the KTMB session, checker secret, or site authorization."
    )


def main() -> None:
    st.set_page_config(
        page_title="Railwatch",
        page_icon="🚆",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _render_styles()
    _render_header()

    try:
        settings = _load_settings()
    except ValidationError as error:
        missing = _missing_settings(error)
        st.warning("Railwatch is ready, but its server configuration is incomplete.")
        if missing:
            st.code("\n".join(missing), language=None)
        st.info(
            "Add the missing values to environment variables or "
            "`.streamlit/secrets.toml`, then restart Streamlit."
        )
        st.stop()

    _render_sidebar(settings)
    refresh_column, search_column = st.columns([1, 4], vertical_alignment="bottom")
    with refresh_column:
        if st.button("Refresh", use_container_width=True):
            st.rerun()
    with search_column:
        query = st.text_input(
            "Filter monitors",
            placeholder="Route, date, time, or monitor ID",
        )

    try:
        with st.spinner("Loading active monitors…"):
            snapshot = _load_snapshot(settings)
    except RailwatchError as error:
        st.error(str(error))
        st.caption("The scheduled checker is independent and may still be running.")
        st.stop()
    except Exception:
        st.error("Railwatch could not load the monitor dashboard.")
        st.caption("Review the Streamlit server logs for the underlying error.")
        st.stop()

    _render_metrics(snapshot)
    st.subheader("Active journey monitors")
    visible_monitors = filter_monitors(snapshot.monitors, query)
    if not visible_monitors:
        st.info("No active monitors match this filter.")
        return

    for monitor in visible_monitors:
        st.markdown(monitor_card_html(monitor), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
