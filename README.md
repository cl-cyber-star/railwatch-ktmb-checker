# Railwatch KTMB checker

This public repository contains only the checker code. KTMB session data and
Railwatch access credentials must be stored as encrypted GitHub Actions
secrets and must never be committed.

## Schedule

The workflow runs every 15 minutes (`*/15 * * * *`) and can also be started
manually from the Actions page. GitHub may start scheduled jobs a few minutes
late during periods of high platform load.

## Seat rules

An alert is eligible only when the authenticated KTMB seat map contains a
selectable Standard seat. The checker excludes Business/VIP seat types,
`OKU` accessible-reserved seats, and every seat marked reserved, blocked or
sold.

## Required GitHub Actions secrets

- `RAILWATCH_API_URL`
- `RAILWATCH_CHECKER_SECRET`
- `OAI_SITES_AUTHORIZATION`
- `KTMB_STORAGE_STATE_B64`

Open **Settings → Secrets and variables → Actions → New repository secret**.
Never place these values in repository files, issues, pull requests or logs.

## Capture the KTMB session on Windows

1. Install Node.js 22 LTS if it is not already installed.
2. Download this repository as a ZIP and extract it.
3. Open PowerShell in the extracted `runner` folder.
4. Run `npm ci`.
5. Run `npm run capture-session`.
6. Sign in only in the official KTMB browser window that opens.
7. Return to PowerShell and press Enter after the account page is visible.
8. Create the GitHub secret `KTMB_STORAGE_STATE_B64` and paste from the
   clipboard.

The script uses the installed Microsoft Edge or Google Chrome. It does not ask
for or store the KTMB password. If clipboard access is unavailable, it writes a
local `.railwatch-session-secret.txt` fallback; delete that file permanently
immediately after creating the GitHub secret.

## Run a test

After all four secrets exist, open **Actions → Railwatch KTMB checker → Run
workflow**. A successful run fetches active Railwatch monitors, opens the
authenticated KTMB timetable and seat map, counts only qualifying ordinary
seats, and posts the result back to Railwatch.
