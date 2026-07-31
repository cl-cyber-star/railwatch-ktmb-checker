# Railwatch KTMB checker and Streamlit dashboard

Railwatch's Python checker is a scheduled browser worker. It retrieves active
journey monitors from the hosted Railwatch application, checks authenticated
KTMB seat maps, counts qualifying Standard seats, and posts results back to the
existing Railwatch API.

The repository now also contains a Streamlit operator dashboard. It reads the
same active-monitor API, displays responsive journey cards and non-sensitive
session health, and can run a manually confirmed checker cycle.

The existing hosted Railwatch PWA, user accounts, push-notification service,
and database remain externally deployed. Streamlit does not replace the PWA's
service-worker Web Push or installable mobile experience.

## Python migration

The former Node.js scripts were replaced with Python 3.12 modules:

```text
src/railwatch/
├── api.py       # hosted Railwatch API client
├── capture.py   # manual KTMB session capture
├── cli.py       # check, capture-session, and doctor commands
├── config.py    # validated environment configuration
├── dashboard.py # Streamlit data access and safe card rendering
├── ktmb.py      # Playwright automation and seat rules
├── models.py    # typed API/domain models
├── service.py   # checker orchestration and session rotation
└── session.py   # storage-state validation and encoding
```

`streamlit_app.py` is the presentation entry point. FastAPI, Flask, and Django
are intentionally not added because the hosted application already provides
the API; introducing another backend would duplicate authentication and data
ownership.

## Preserved behavior

- GitHub Actions runs every five minutes and supports manual dispatch.
- The existing environment variable names and `/api/checker` GET/POST payloads
  are preserved.
- Only selectable Standard seats are counted.
- Business/VIP, OKU-reserved, sold, blocked, and non-selectable seats remain
  excluded.
- Monitor departure windows are inclusive and same-day.
- A failed check is reported to the backend without presenting zero seats as a
  successful check.
- KTMB credentials are never requested, logged, or stored by Railwatch.

## Rotating KTMB sessions

The worker first requests the latest storage state from
`/api/checker/session`. After an authenticated run it exports Playwright's
refreshed cookies and saves them back with optimistic version checking.

The existing `KTMB_STORAGE_STATE_B64` GitHub secret remains a recovery seed. If
the server-held session is rejected but the secret contains a newer recapture,
the worker retries the seed and replaces the expired server session. A
conflicting save returns HTTP `409` and is safely ignored so an older run cannot
overwrite a newer session.

Expected session API contract:

- `GET /api/checker/session` →
  `{"session":{"encryptedState":"...","bootstrapFingerprint":"...","version":1}}`
- `PUT /api/checker/session` with
  `{"encryptedState":"...","bootstrapFingerprint":"...","expectedVersion":1}` →
  `{"ok":true,"version":2}`
- Session state uses the deployed AES-256-GCM envelope and remains encrypted in
  the database.
- `204` or `404` from GET disables rotation for that run and uses the GitHub
  secret seed.

Rotating cookies can extend a sliding session, but KTMB can still require a new
login because of a fixed lifetime, CAPTCHA, account security policy, or
server-side invalidation.

## Requirements

- Python 3.12
- Microsoft Edge or Google Chrome for interactive capture
- Playwright Chromium for scheduled checking
- Git

## Local setup in Visual Studio / PowerShell

From the repository root:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m playwright install chromium
```

If `py -3.12` is unavailable, install Python 3.12 and restart Visual Studio:

```powershell
winget install Python.Python.3.12
```

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `RAILWATCH_API_URL` | Yes | Base URL of the hosted Railwatch backend |
| `RAILWATCH_CHECKER_SECRET` | Yes | Bearer secret for checker API access |
| `OAI_SITES_AUTHORIZATION` | Yes | Authorization for the hosted site |
| `KTMB_STORAGE_STATE_B64` | Yes | Base64 browser-state recovery seed |
| `RAILWATCH_SESSION_API_PATH` | No | Defaults to `/api/checker/session` |
| `KTMB_SESSION_ROTATION_ENABLED` | No | Defaults to `true` |
| `RAILWATCH_HTTP_TIMEOUT_SECONDS` | No | Defaults to `30` |

Copy `.env.example` to `.env` only for local development. `.env` and every
storage-state file are ignored by Git. Never paste secrets into source files,
issues, commits, screenshots, or workflow logs.

For Streamlit Community Cloud or another Streamlit host, configure the same
names in the deployment's secret manager. For local Streamlit development,
environment variables are preferred. `.streamlit/secrets.toml` is also
supported and ignored by Git:

```toml
RAILWATCH_API_URL = "https://your-railwatch-site.example"
RAILWATCH_CHECKER_SECRET = "replace-me"
OAI_SITES_AUTHORIZATION = "replace-me"
KTMB_STORAGE_STATE_B64 = "replace-me"
```

## Capture a KTMB session

Activate the virtual environment, then run:

```powershell
python -m railwatch capture-session
```

1. Sign in manually in the official KTMB browser window.
2. Return to PowerShell and press Enter after the account page is visible.
3. Paste the copied value into the GitHub Actions secret
   `KTMB_STORAGE_STATE_B64`.
4. If clipboard access fails, the command creates
   `.railwatch-session-secret.txt`. Delete it permanently immediately after
   updating the GitHub secret.

The script does not read or store the KTMB password.

## Run and test locally

Validate environment configuration without contacting either service:

```powershell
python -m railwatch doctor
```

Run formatting, static checks, and tests:

```powershell
python -m ruff check .
python -m mypy
python -m pytest -v
```

Run one real checker cycle only after the four required variables are set:

```powershell
python -m railwatch check
```

This performs real requests to Railwatch and KTMB and posts monitor results.

## Run the Streamlit frontend

Install the project and frontend dependencies:

```powershell
python -m pip install -r requirements-frontend.txt
python -m pip install --no-deps -e .
```

Start the dashboard:

```powershell
python -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. The dashboard:

- lists and filters active journey monitors;
- uses content-driven cards that wrap on narrow desktop and mobile screens;
- shows the nearest travel date and session source/version without displaying
  cookie or secret values;
- refreshes API data on demand; and
- provides a guarded operator action to run all active monitors immediately.

The Streamlit server must be treated as an authenticated operator surface
because it holds the checker credentials. Do not publish it as an unrestricted
public app. User sign-in, monitor deletion, and per-device Web Push remain in
the existing hosted PWA because the checker API does not expose those public
account operations.

## Database migration

None is required. The repository contains no database schema, and the Python
worker preserves the existing hosted API and database structure.

## GitHub deployment

The scheduled workflow installs Python 3.12, the pinned dependencies, and
Playwright Chromium before running:

```text
python -m railwatch doctor
python -m railwatch check
```

Keep all four required values under **Settings → Secrets and variables →
Actions**. No workflow secret names changed during the migration.

The scheduled worker intentionally installs `requirements.txt`, not
`requirements-frontend.txt`, so Streamlit is not added to each five-minute
checker run.

Push this migration on `feature/python-migration` and open a pull request into
`main`. The new Python CI workflow runs Ruff, mypy, and pytest on the branch and
pull request. Merge only after CI and a manually dispatched checker run pass.

## Troubleshooting

- **Stored session rejected:** recapture once and update
  `KTMB_STORAGE_STATE_B64`, then manually dispatch the workflow.
- **Session API 404/204:** the checker falls back to the GitHub secret, but
  refreshed cookies cannot be retained until the session endpoint is deployed.
- **No scheduled run:** GitHub schedules may be delayed during high load. Check
  that Actions are enabled and manually dispatch the workflow.
- **KTMB page changed:** inspect the Playwright failure before modifying
  selectors; failed checks remain visible in Railwatch activity.
