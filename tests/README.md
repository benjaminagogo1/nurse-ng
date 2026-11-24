# Understanding and running tests

The [test reference](../docs/reference/TESTS.md) lists every test module and top-level
case name. Use the [feature map](../docs/CODE_GUIDE.md) to choose focused checks.

## Pytest isolation

`conftest.py` sets development settings, an in-memory SQLite database, disabled
mail and empty provider credentials before importing the application. `engine`
enables foreign keys and creates/drops registered model metadata. `db_session`
provides the case's session; `client` overrides `get_db` for FastAPI requests.
Rate limiters reset between cases because TestClient clients share an address.

Tests inject provider responses instead of using real LiveKit/OIDC/mail accounts.
Filesystem tests use temporary roots/monkeypatches. Model metadata tests check
domain structure; migration tests independently check installed-schema transitions.
Never point test environment variables at the member database or private upload roots.

```sh
venv/bin/python -m pytest tests/test_participation.py tests/test_auth.py
venv/bin/python -m pytest tests/test_education.py tests/test_education_routes.py tests/test_education_live.py
venv/bin/python -m pytest tests/test_migrations.py
venv/bin/python -m pytest
venv/bin/ruff check app tests tools
```

`helpers.py` supplies shared registration payloads, CSRF extraction and HTML checks.
Keep assertions about real behavior: ownership, consent, visibility, state changes,
concurrency/retries and failure recovery. Avoid tests that merely reproduce an
implementation's assignments or check comments.

## Browser runners

`browser/*.py` are standalone journeys, not collected pytest tests. They normally
start an isolated local server/database and Chrome, then report a temporary
screenshots/logs directory. Read a runner's header/setup before invoking it; Chrome,
CDP/WebSocket tooling and sometimes axe-core/local media are required. Dependencies
and browser paths can differ by runner. Do not assume a system browser alone is
enough, or silently run a journey against the user's existing app process.

```sh
venv/bin/python tests/browser/community_drafts.py
venv/bin/python tests/browser/participation.py
venv/bin/python tests/browser/education_journeys.py
```

The draft runner exercises recovery and reply context; participation covers peer
support/welcomes/series/invitations/digest; education runners cover course and room
UI. Offline/mobile runners simulate connection loss, browser restarts and neutral
bundle recovery. See [quality verification](../docs/QUALITY_VERIFICATION.md) and
the owning feature guide for exact scope and prerequisites.

## PostgreSQL and hosted-process runners

`hosting/*.py` run separately with an explicitly isolated database. The PostgreSQL
journeys guard the database name `nurse_ng_hosting_test` and take
`NURSE_NG_TEST_POSTGRES_URL`. They may migrate/write that database; use a disposable
instance with fixture credentials. The CI workflow shows a concrete isolated
PostgreSQL/container setup without relying on a developer's installation.

Read [hosting](../docs/HOSTING.md) and the runner's setup before invoking it.
SQLite passing does not establish PostgreSQL locking/migration behavior, and local
ASGI tests do not establish a live provider's TLS/proxy configuration.

## Mobile tooling checks

```sh
npm test --prefix mobile
```

These Node tests validate origin/release configuration and offline-bundle generation.
They are distinct from an Android Gradle build, Xcode build, store review or actual
native WebView execution. [mobile/README.md](../mobile/README.md) records those limits.

## Evidence

Report actual commands/results and their environment. A generated case index is
not evidence that the cases passed. Historical screenshots/test counts belong to
their dated verification directory. Treat new authorization/retry/schema failures
as behavior to investigate, not as documentation to rewrite until it appears green.
