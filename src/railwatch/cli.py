"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence

from pydantic import ValidationError

from railwatch.capture import capture_session
from railwatch.config import Settings
from railwatch.errors import RailwatchError
from railwatch.service import run_checker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="railwatch",
        description="Railwatch KTMB checker worker",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Run all active Railwatch monitors once")
    subparsers.add_parser(
        "capture-session",
        help="Capture a KTMB session after manual login",
    )
    subparsers.add_parser(
        "doctor",
        help="Validate configuration and session data without network access",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.command == "capture-session":
            asyncio.run(capture_session())
            return

        settings = Settings()  # type: ignore[call-arg]  # values come from the environment
        if args.command == "doctor":
            logging.getLogger(__name__).info(
                "Configuration is valid; KTMB sessions are supplied per Railwatch user."
            )
            return

        asyncio.run(run_checker(settings))
    except ValidationError as exc:
        missing = sorted(
            str(error["loc"][0]) for error in exc.errors() if error.get("type") == "missing"
        )
        detail = f" Missing: {', '.join(missing)}." if missing else ""
        parser.exit(2, f"Configuration error.{detail}\n")
    except (RailwatchError, KeyboardInterrupt) as exc:
        parser.exit(1, f"Railwatch failed: {exc}\n")
