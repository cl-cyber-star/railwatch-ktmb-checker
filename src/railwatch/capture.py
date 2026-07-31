"""Interactive, password-free KTMB browser-session capture."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from playwright.async_api import Browser, BrowserType, Error, async_playwright

from railwatch.errors import SessionError
from railwatch.ktmb import KTMB_HOME_URL, assert_authenticated
from railwatch.session import encode_storage_state

LOGGER = logging.getLogger(__name__)
LOGIN_URL = "https://online.ktmb.com.my/Account/Login"
FALLBACK_FILE = Path(".railwatch-session-secret.txt")


async def capture_session() -> None:
    """Open an installed browser and capture storage state after manual login."""
    async with async_playwright() as playwright:
        browser = await _launch_installed_browser(playwright.chromium)
        context = await browser.new_context(locale="en-MY", timezone_id="Asia/Kuala_Lumpur")
        page = await context.new_page()
        try:
            LOGGER.info("Opening the official KTMB sign-in page...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.to_thread(
                input,
                "Sign in completely in the browser. When the account page is visible, "
                "return here and press Enter.",
            )
            await page.goto(KTMB_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            await assert_authenticated(page)
            encoded = encode_storage_state(await context.storage_state())
            if _copy_to_clipboard(encoded):
                LOGGER.info(
                    "Success. The KTMB session is on your clipboard. Paste it only into "
                    "the GitHub secret KTMB_STORAGE_STATE_B64."
                )
            else:
                await asyncio.to_thread(_write_fallback_file, encoded)
                LOGGER.warning(
                    "Clipboard access was unavailable. The session was saved to %s. "
                    "Delete it permanently after updating the GitHub secret.",
                    FALLBACK_FILE,
                )
        except SessionError:
            raise
        finally:
            await context.close()
            await browser.close()


async def _launch_installed_browser(browser_type: BrowserType) -> Browser:
    last_error: Error | None = None
    for channel in ("msedge", "chrome"):
        try:
            return await browser_type.launch(channel=channel, headless=False)
        except Error as exc:
            last_error = exc
    raise SessionError(
        "Microsoft Edge or Google Chrome could not be opened. Install one and retry."
    ) from last_error


def _copy_to_clipboard(value: str) -> bool:
    command: list[str] | None
    if sys.platform == "win32":
        command = ["clip.exe"]
    elif sys.platform == "darwin":
        command = ["pbcopy"]
    else:
        command = None
    if command is None:
        return False
    try:
        completed = subprocess.run(  # noqa: S603 - command is a fixed platform binary
            command,
            input=value,
            text=True,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _write_fallback_file(value: str) -> None:
    FALLBACK_FILE.write_text(value, encoding="utf-8")
    os.chmod(FALLBACK_FILE, 0o600)
