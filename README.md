# NFPL Access Control Service

A full-stack demonstration of **explainable, scope-aware role-based access control (RBAC)** and maker/checker shipment workflows for a customs brokerage. Built with **FastAPI, SQLAlchemy 2.x, PostgreSQL, React, TypeScript and Vite**.

> **Security warning:** `X-Actor-Id` is a **demo-only identity selector**, **not authentication**. Any caller able to reach the API can impersonate a seeded user. Run this application only in a trusted local environment. Do not publish a write-enabled instance on the public internet without replacing this mechanism with verified authentication and authorization.

## Features

- Scoped grants across **client, branch, direction** (`import`/`export) and **mode** (`air`/`FCL`/`LCL`); null grant dimensions mean unrestricted.
- Separate `job.view`, `job.prepare`, `job.check`, `job.file`, reassignment, administration and parser permissions; unmatched requests are denied.
- Shipment workflow **Confirmed → Prepared → Checked → Filed**, with separation of duties between maker, checker and filer.
- Cancellation/reopening of protected shipments via **justified request + independent approval**, with job-version checks.
- Absent employee restrictions, client-only read access, constrained service/parser identity, admin self-grant/revoke protections.
- Explainable decisions (`allowed`, `reason_code`, `explanation`, and matched grant information for allowed requests).
- **My Work** queue using stage/scope SQL filtering followed by the same authorization decision logic used at execution.
- Audit events and per-job history. React pages include Dashboard, Jobs, My Work, Decision Explorer, Audit History and People.

## Repository structure

```text
backend/
  app/core.py             # SQLAlchemy models, role permissions, decision engine
  app/main.py             # FastAPI endpoints, workflow and admin operations
  app/seed.py             # Demo fixtures (20 users, 320 jobs)
  tests/                 # Backend unit/API tests
  nfpl_security_smoke.py # Optional additional smoke tests, if copied into backend
  requirements.txt
frontend/
  src/main.tsx            # React demo application
  src/style.css
  src/vite-env.d.ts       # Vite/TypeScript declarations
  package.json
docs/design.md             # Detailed architecture, decisions and limitations
```

The `nfpl_security_smoke.py` script is a separate supplied test utility and is present only if copied into `backend/`.

## Prerequisites

- Python 3.13, Node.js with npm, and Docker Desktop (running). PostgreSQL 17 can also be installed directly instead of using Docker.
- Windows PowerShell commands are shown below. On macOS/Linux, use the equivalent shell commands for virtual environments and environment variables.
- The application is **local-demo-only**, because `X-Actor-Id` is not real authentication. Do not expose the API to the public internet.

## Quick start for assessors (fresh Windows machine)

These instructions **do not require the original developer's database, Docker container or Windows DPAPI credential file**. Create your own local PostgreSQL database and credentials.

**1. Clone and enter the repository**

```powershell
git clone https://github.com/YOUR_USERNAME/nfpl-access-control-service.git
cd nfpl-access-control-service
```

Replace `YOUR_USERNAME` with the repository owner's GitHub username after publication.

**2. Create a local PostgreSQL 17 database**

Start Docker Desktop, then run:

```powershell
docker run --name nfpl-postgres -d `
  -p 127.0.0.1:5432:5432 `
  -e POSTGRES_DB=nfpl_dev `
  -e POSTGRES_USER=nfpl_user `
  -e POSTGRES_PASSWORD=ChangeThisLocalPassword `
  postgres:17
```

`ChangeThisLocalPassword` is a **public example password for a disposable localhost-only demo database**, not a credential for the author's machine. Change it to your own password. If a container named `nfpl-postgres` already exists, use that container's credentials or choose a different container name and available host port; do not overwrite or delete an existing database.

> On a shared or sensitive computer, avoid supplying real passwords directly in shell history. Use Docker's `--env-file` or another secret mechanism for non-demo credentials. The Docker command above is only for the assessor's isolated local demo.

**3. Set up and configure the backend**

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = 'postgresql+psycopg://nfpl_user:ChangeThisLocalPassword@127.0.0.1:5432/nfpl_dev'
python -m app.seed
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use **the password you chose in step 2** in `DATABASE_URL`. The example works as written only if you kept the example password. For passwords with special URL characters, percent-encode them or construct the SQLAlchemy connection string with `sqlalchemy.engine.URL.create()`; do not simply concatenate an arbitrary password into a URL.

Keep this PowerShell terminal running. Seeding initializes tables and inserts **5 branches, 10 clients, 20 users, 8 roles, 30 grants and 320 jobs** when the user table is empty. The seed script skips insertion if users already exist. Open <http://127.0.0.1:8000/docs> for the API.

**4. Start the frontend in a second PowerShell terminal**

From the repository root (or navigate there from `backend/`):

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The frontend uses `http://localhost:8000` by default and should display the seeded shipment data. If you have a custom backend URL, set `VITE_API_URL` for the frontend development process.

**5. Run tests (third terminal, backend directory)**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = 'postgresql+psycopg://nfpl_user:ChangeThisLocalPassword@127.0.0.1:5432/nfpl_dev'
python -m pytest -q
python .\nfpl_security_smoke.py
```

Use your actual local database password in `DATABASE_URL`. The smoke test is included only if `backend/nfpl_security_smoke.py` is committed to the repository. It runs security scenarios within rolled-back DB transactions.

### Existing developer-machine setup (optional)

The original Windows development machine uses an **existing** PostgreSQL 17 Docker container and stores the database password in a Windows DPAPI-encrypted credential file. This is not part of the assessor setup and the encrypted file must never be committed.

In each fresh backend PowerShell session on that machine:

```powershell
$dbCredential = Import-Clixml "$env:APPDATA\nfpl-db-credential.xml"
$env:NFPL_DB_PASSWORD = $dbCredential.GetNetworkCredential().Password
```

The tested `app.core.engine_for()` uses `DATABASE_URL` if present; otherwise it uses `NFPL_DB_PASSWORD` with SQLAlchemy `URL.create()`. If both are missing, it fails rather than silently switching to SQLite. **Ensure the modified `app/core.py` is committed.** If you are using the original developer container, simply use `docker start nfpl-postgres` if stopped; never recreate it just to follow the assessor example above.

### Troubleshooting

- **Connection refused:** Ensure Docker Desktop and `nfpl-postgres` are running (`docker ps`) and port 5432 is available.
- **Password authentication failed:** The value in `DATABASE_URL` must match the password used when the PostgreSQL volume was first created; changing a `docker run -e POSTGRES_PASSWORD=...` argument does **not** change an existing database password.
- **Missing `DATABASE_URL`:** It must be set in the **same terminal session** that starts Uvicorn or the seed command, unless using the original machine's `NFPL_DB_PASSWORD` mechanism.
- **Frontend blank/empty:** Verify <http://127.0.0.1:8000/health>, check browser Developer Tools for API/CORS errors, and make sure the backend is running.
- **PowerShell activation blocked:** Run `Set-ExecutionPolicy -Scope Process Bypass` in that terminal, then activate the virtual environment again; this affects only that process.

## Demo users and scenarios

The frontend's **Acting as** selector sets the demo `X-Actor-Id` header. The **Person** selector in Decision Explorer indicates whose permissions are evaluated. Evaluating **another** user requires `grant.manage`, so select **Asha Mehta (ID 1, Admin)** when demonstrating other users' permissions.

| Person | ID | Relevant permission / test |
|---|---:|---|
| Asha Mehta | 1 | Admin; can inspect another user's access, but cannot grant/revoke own access |
| Priya Shah | 2 | Global Maker; Checker for clients 1 and 2 |
| Rahul Desai | 3 | Checker for client 1, branch 1, imports only |
| Arjun Rao | 4 | Maker for client 1; cannot check a job he prepared |
| Vikram Joshi | 6 | Absent; cannot perform shipment work |
| Sana Khan | 7 | Filer |
| Dev Patel | 8 | Supervisor; can request exceptional changes |
| Client Contact | 19 | `ClientViewer` for client 1, read-only |
| Night Parser | 20 | Limited service identity; not a Checker/Filer |

**Suggested read-only Decision Explorer demonstrations (acting as Asha):**

- Client Contact / `job.view` / Job 11 → `MATCHED_GRANT` (client 1).
- Client Contact / `job.view` / Job 12 → `NO_MATCHING_GRANT` (client 2).
- Vikram Joshi / `job.prepare` / Job 21 → `USER_ABSENT`.
- Night Parser / `job.check` / Job 11 → `SERVICE_RESTRICTED`.

**Workflow demonstration:** With Arjun as acting user, prepare a Confirmed client-1 job from **My Work**. Switch to Asha and evaluate Arjun's `job.check` on that job → `SEPARATION_OF_DUTIES`. Evaluate Priya's `job.check` on that Prepared job → allowed if her scoped grant matches. Then use Priya as acting user to check it. **Job stages change after each demo; don't assume an example job is still in its seeded stage.**

## Tests and verified local results

From `backend/`:

```powershell
python -m pytest -q
python .\nfpl_security_smoke.py  # if copied into backend/
```

Verified on **12 November 2026**:

- Backend test suite: **10 passed**, 1 non-blocking Starlette deprecation warning.
- Additional security smoke suite: **17/17 passed**, with test DB writes rolled back.
- Frontend: `npm run build` completed successfully (Vite 8.3.8, TypeScript compilation).
- Browser: workflow changes persisted after refresh, and maker/checker denials and independent-checker allows were confirmed.

These are functional checks, **not** proof of production security or measured performance at scale.

## API overview

`GET /health`, `GET /api/meta`, `POST /api/authorize`, `GET/POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/transition`, `POST /api/jobs/{id}/reassign`, `POST /api/grants`, `DELETE /api/grants/{id}`, `POST /api/roles`, `GET /api/inbox`, `GET /api/jobs/{id}/history`, `GET /api/audit`, `POST /api/jobs/{id}/exception-request`, `POST /api/jobs/{id}/exception-approve`, `PATCH /api/jobs/{id}/parser`.

Protected requests require the **demo-only** `X-Actor-Id` header. `/api/authorize` returns a decision object for permitted evaluations; an unauthorized cross-user inspection itself receives HTTP 403.

## Five-minute evaluator walkthrough

1. **0:00–0:40 —** Dashboard, five branches, clients and seeded jobs.
2. **0:40–1:40 —** Decision Explorer with Asha: scoped client viewer vs cross-client denial and explanatory reason codes.
3. **1:40–2:50 —** Show maker/checker separation: Arjun cannot check his own prepared job; Priya can check if stage/scope match.
4. **2:50–3:50 —** My Work action, browser refresh, per-job history and admin audit timeline.
5. **3:50–5:00 —** Explain self-grant prevention, independent exception approval, 10 + 17 tests and known limitations.

## Limitations and production hardening

- **Not safe to expose publicly:** `X-Actor-Id` has no cryptographic verification or real login; use OIDC/JWT, verified service identities, HTTPS and rate limiting before production use.
- `Base.metadata.create_all()` is for the demo; production needs reviewed Alembic migrations and controlled data lifecycle.
- **Full historical “who could act at time T” reconstruction is not implemented.** Audit records events and some grant dates, but complete reconstruction needs historical identity/status, job and policy snapshots.
- Audit records are application-managed, not cryptographically tamper-evident. Not every internal decision is individually recorded.
- Job version checks exist for exception approval, but ordinary concurrent transitions need stronger row locking/optimistic-update enforcement.
- UI listing is capped to the first page of visible/actionable jobs; do not present counts as the global totals.
- Scale generator: `python -m app.seed --scale` seeds 500 users / 200,000 jobs **only on an empty database**. It has not been benchmarked here; use a separate test database.

See [`docs/design.md`](docs/design.md) for architectural decisions, security reasoning and trade-offs.
