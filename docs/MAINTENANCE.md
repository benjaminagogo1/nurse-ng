# Returning to Nurse.ng and making a change

Start with [CODE_GUIDE.md](CODE_GUIDE.md), then locate the feature in its ownership
table and follow the route, service, model and focused tests. The generated
[source reference](reference/BACKEND.md) makes an unfamiliar symbol searchable;
[docs/README.md](README.md) connects domain and operations guides.

## Establish the current state

From the repository root, inspect changes before editing:

```sh
git status --short
rg --files app tests docs deploy mobile tools migrations
```

Keep another developer's uncommitted changes intact. Inspect the actual installed
schema with `venv/bin/alembic current` and the checked-in graph with
`venv/bin/alembic heads`; these commands need the intended environment. Historical
guides can contain earlier heads or test counts. Do not substitute them for current
source/database state.

The root Python package is `app`, configured by `pyproject.toml`; pinned runtime
dependencies live in `requirements.lock`. The independent mobile Node project
lives under `mobile/`. Local `.env`, databases, private files, build tools and
signing material are ignored runtime resources, not application source.

## Local setup and checks

Follow the root [README](../README.md) for development `.env` setup and dependencies.
Production is the default when settings are imported without a development
environment. Use a generated signing key; do not copy a placeholder into a real
deployment. The [configuration reference](reference/CONFIGURATION.md) lists every
Settings field and source default without reading runtime secrets.

After configuring the intended local development environment:

```sh
venv/bin/alembic upgrade head
venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The web server handles requests; processing is separate. Run the configured worker
supervisor when testing background behavior, or use the owning worker's bounded
`--once` mode against an isolated installation. Read [worker operations](WORKER_OPERATIONS.md)
first: recruitment may perform outbound discovery, and mail depends on the backend.

Routine checks:

```sh
venv/bin/ruff check app tests tools
python3 tools/build_code_reference.py --check
venv/bin/python -m pytest
npm test --prefix mobile
```

Use focused existing tests for a small change before the broader suite. Browser
and hosting runners are separate from pytest; [tests/README.md](../tests/README.md)
documents their requirements. The normal pytest fixtures set an isolated SQLite
environment and disable mail before application import. Do not import the app
first and expect later environment changes to replace its cached settings.

## Where a change belongs

| Change | Update and inspect |
| --- | --- |
| Product rule or ownership | Owning service, route adaptation and focused behavior tests |
| Persisted field/state/index | Model, model registry, new Alembic revision and upgrade checks |
| Form field or button | Template, route parser, service validation and feedback/draft hooks |
| Public profile field | Shared visibility predicates and all directory/share contexts |
| Private file type/quota | Body limits, child parser, scanner, store, domain release and cleanup |
| Outbound provider call | Fixed origin/scope, bounded transport, sanitized errors and retry contract |
| Worker deadline/lease | Worker implementation, supervisor and readiness limits together |
| Browser cache/load order | Template assets, service-worker list/version and mobile bundle |
| Environment setting | Settings validation, examples, hosting/feature guide and regenerated reference |
| Native shell behavior | Custom Java/Swift and shared offline contract; verify on real devices |

For a non-obvious public service action, document authorization, transaction owner,
expected errors and external effects. Use conditional updates/unique constraints
for concurrent desired-state changes instead of browser-side read-then-toggle logic.
Do not move core rules into template visibility or JavaScript callbacks.

## Debug common symptoms

| Symptom | Inspect first | What the result means |
| --- | --- | --- |
| Next-step card remains/reappears | `MemberJourney.dismissed_at`, clicked save button | Explicit hide saves a timestamp; ordinary save clears it. |
| Login expires after account changes | `auth_version` and session dependency | Older signed cookies can be intentionally revoked. |
| Directory misses a member/field | Profile activation, discoverability and field visibility | Account existence alone does not imply public discovery. |
| Private conversation/file is unavailable | Current active accounts, accepted connection and attachment state | An old link/notice cannot bypass revoked access. |
| Reel remains processing/failed | Reel claim state, FFmpeg and shared media volume | Upload completion does not establish ready playback. |
| Notifications appear but email does not | Verified email, category opt-in, mail backend and worker | In-app notices operate independently of SMTP. |
| Recurring activity/reminder does not advance | Notifications worker progress and eligible schedule | This worker also owns non-email scheduling. |
| Recruitment page exists but no job appears | Source authority, collection scope, extraction/review blockers | Discovery is not evidence of a publishable current vacancy. |
| Lecture reserved but room cannot be joined | Current session/educator/account state, LiveKit setup | Seat allocation is distinct from live room access. |
| Readiness returns 503 | Database availability and required role progress | An idle worker can be healthy; a live but stuck PID can fail readiness. |
| Offline edit stays pending | Verified scope/session, conflict feedback and saved receipt | Local persistence is not confirmed delivery. |
| Theme/layout looks wrong | CSS cascade, root preferences and scoped selector | Later feature CSS must respect shared appearance tokens. |

Use sanitized exception classes and opaque operation IDs when logging. Keep
passwords, tokens, database URLs, provider credentials, patient/private member
content and file contents out of logs/screenshots/docs.

## Migrate, back up and deploy

Use [migration rules](../migrations/README.md), [hosting](HOSTING.md) and
[deployment source](../deploy/README.md). Rehearse changes on an isolated copy.
SQLite's consistent backup/restore CLI is not a PostgreSQL backup strategy; use
the PostgreSQL provider/native backup mechanism and separately preserve private
objects. Database and files must remain mutually consistent during recovery.

`deploy/start.py web` and `workers` expect a prior migration step. Its `all` mode
applies migrations before starting both services. `--check` validates production
configuration/commands without migration or service startup. The checked-in
Render preview uses `all`; its provider storage/scanner limitations remain documented
in the hosting guide. A source-code fix does not establish live TLS/proxy/storage,
SMTP, media-provider or native-device configuration.

Before rollout, run the relevant isolated checks, verify the migration head,
configure persistent paths/services, validate startup settings, and follow the
feature's real-provider/device acceptance steps. Retain a concrete rollback/recovery
procedure for data and external state changes.

## Leave a useful handover

Update current feature/architecture documentation and regenerate references:

```sh
python3 tools/build_code_reference.py
python3 tools/build_code_reference.py --check
```

Record what changed, why, how it was checked and any live-provider/device limits.
Link the owning source and current guide. Keep dated verification artifacts dated;
do not make a future maintainer guess whether a proposal, old screenshot or test
count describes the currently running application.
