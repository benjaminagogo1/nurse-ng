# Understanding the Nurse.ng code

This guide is the starting point for a maintainer returning to the project. It
explains where behavior belongs, how a request reaches the database, and which
boundaries must remain intact when a feature changes. The [live learning guide](LIVE_LEARNING_ARCHITECTURE.md)
walks through the new educator, course and classroom domain in more detail.

## Read these files first

1. `app/main.py` assembles the FastAPI application, middleware, error handlers,
   static files and feature routers. It is the map of the running application.
2. `app/core/config.py` defines environment settings and validates the production
   origin, hosts, cookies, signing key and database connection. Production reads
   the process environment; the local `.env` is a development convenience.
3. `app/web/deps.py` resolves the current account, checks its persisted session
   version, and provides member/staff and CSRF dependencies.
4. `app/db/session.py` provides a database session for a request and enables
   SQLite foreign keys. `app/db/base.py` supplies common IDs and timestamps.
5. `app/web/templating.py` builds the common page context, supplies CSRF tokens,
   and integrates feedback, private drafts, notifications and activity recording.

Then follow one feature from its route into its service, model and tests. For
example, course enrollment begins in `app/web/education_routes.py`, calls
`app/services/education.py`, and writes `LearningEnrollment` from
`app/models/education.py`. Its HTTP behavior and domain invariants have separate
tests so a rendering change cannot silently replace the authorization check.

## How the application is organized

| Directory | Responsibility | What belongs elsewhere |
| --- | --- | --- |
| `app/core/` | Settings, security primitives, storage and shared validation | Feature-specific permission decisions |
| `app/models/` | Database records, relationships, constraints and identity | HTTP responses and external provider calls |
| `app/services/` | Domain rules, transactions, work queues and provider adapters | HTML rendering and browser state |
| `app/web/` | Route input/output, dependencies and presentation context | Reimplementation of domain rules |
| `app/templates/` | Accessible server-rendered pages and reusable components | Secret values and authoritative permission checks |
| `app/static/` | Scoped CSS, browser behavior and public assets | Private uploads, credentials and database files |
| `migrations/versions/` | Versioned changes from an existing database to the current schema | Runtime model imports that could change an old migration |
| `tests/` | Isolated domain, HTTP, migration, browser and hosting checks | Changes to real members or outbound development email |
| `deploy/` | Production process startup and host-specific setup | Member-facing product explanations |
| `mobile/` | Native app packaging around the hosted experience | The Python application's root/build directory |

The application is a domain-organized monolith. A single web application shares
one database with supervised recruitment, Reels and notification processes. The
live classroom's media transport runs in LiveKit; its teaching permissions,
registrations and learning records remain in Nurse.ng.

```mermaid
flowchart LR
    Browser[Browser or native shell] --> Web[FastAPI routes]
    Web --> Domain[Domain services]
    Domain --> DB[(SQLite or PostgreSQL)]
    Web --> Templates[Jinja pages]
    Workers[Supervised workers] --> Domain
    Domain --> Adapters[Mail and media adapters]
    Browser --> Media[LiveKit classroom media]
    Media --> Webhook[Signed webhook route]
    Webhook --> Domain
```

## Request lifecycle and permissions

A normal member action follows this sequence:

1. Middleware rejects an unlisted host and verifies the signed session cookie.
2. The current-user dependency loads the account and checks active status and
   `auth_version`. Resetting a password can revoke older sessions in the database.
3. A mutation validates the CSRF token. Classroom JSON uses `X-CSRF-Token`;
   ordinary forms use a hidden `csrf_token` field.
4. The route normalizes browser input and calls a domain service. User identity
   and content ownership come from the server, never a submitted `user_id`.
5. The service validates current access and performs its transaction. Unique
   constraints and conditional updates protect retries and concurrent writes.
6. The route renders or redirects with a server-confirmed result. Browser
   enhancement adds pending/error behavior to the ordinary HTML form.

Account type, public profile visibility, community participation, educator
approval and staff access are separate concepts. A teaching application does
not grant staff access. Enrollment does not grant course editing. A public
community does not imply private membership. Keep these distinctions in the
service that owns the action, even when the page also hides an unavailable button.

## Data ownership and privacy

Use public identities only where the person deliberately chose to share them.
The account's `full_name`, contact fields and private professional profile do
not become public merely because the account participates in a classroom.
The classroom uses an educator's explicit display name or a member's community
name, with a generic learner fallback.

Private evidence, messages and recordings are authorized when accessed. A link,
reservation, old notification or browser cache is not a substitute for the
current permission check. Notifications retain record references, and their
visibility is recalculated before listing or delivery. Quiz answer keys stay
in the service/model layer and are not sent with an unanswered learner form.

Do not put private uploads under `app/static/`. Do not log provider responses,
bearer tokens, database URLs or account email tokens. `.env` and `.env.*` are
Git-ignored; examples contain setting names and instructions, not real secrets.

## Transactions and external services

Services normally commit the domain operation they own. The `notifications.emit`
helper is an exception by design: it appends notices inside its caller's
transaction and leaves committing and delivery to that caller/outbox.

Educator application/review and classroom state changes also accept
`commit=False` for a specific transaction boundary: the educator routes close
active provider rooms, update the sessions, and change approval in one database
unit. Those callers explicitly commit or roll back. Classroom mutations acquire
account, educator-profile and session locks in that order. Keep this order when
extending moderation, so a fresh start/token cannot race an approval change.

A database transaction cannot atomically commit an external video or SMTP call.
The classroom uses namespaced, stable room IDs, bounded provider calls and
serialized lifecycle decisions. The email outbox uses expiring claims and
bounded retries. Their documentation states the remaining retry semantics;
do not describe either boundary as exactly-once delivery.
If a later remote room deletion fails, earlier rooms may already be disconnected
even though the database changes roll back. A retry safely repeats those
deletions; this external boundary is described in the live learning guide.

For schema changes, add an Alembic revision and test an existing database upgrade.
Adding a SQLAlchemy column is insufficient for an installation already running.
Historical migration definitions must remain stable. Use SQL Boolean defaults
that work on PostgreSQL and SQLite, and explicitly enable SQLite foreign keys.

## Browser code and styling

The server-rendered page remains the foundation. Browser scripts enhance a
specific feature using documented `data-*` hooks. A script should initialize
only when its root element exists, explain failures, and release timers/media
when the page closes. Browser callbacks do not establish server authorization.

`app/static/css/appearance.css` defines shared light/dark/accessibility tokens.
Feature styles build on those tokens and are scoped to their feature root.
Learning styles load through `app/templates/education/base.html`, and the large
LiveKit SDK loads only on classroom pages. Keep reduced-motion, keyboard focus,
enlarged text and narrow-screen behavior as part of the component contract.

## Making a change safely

1. Find the responsible route, service, model and focused tests with `rg`.
2. Identify the invariant being changed: ownership, lifecycle, data visibility,
   retries, ordering or external-service behavior.
3. Keep the change in its owning layer. Add a migration if persisted data changes.
4. Verify the actual behavior and the important failure/revocation path. Use
   isolated accounts, temporary databases and disabled/test mail transports.
5. Update the guide or module contract when an invariant or environment setting changes.

Useful checks from the repository root:

```sh
venv/bin/ruff check app tests
venv/bin/python -m pytest tests/test_education.py tests/test_education_routes.py tests/test_education_live.py
venv/bin/python -m pytest tests/test_education_notifications.py
venv/bin/python -m pytest tests/test_migrations.py
venv/bin/python -m pytest
```

Browser and PostgreSQL runners have their own setup and isolation safeguards.
See [quality verification](QUALITY_VERIFICATION.md), [hosting](HOSTING.md), and
the feature-specific guide before running them. A passing local test is evidence
for the tested behavior; live provider, device and production acceptance need
their own recorded results.

## Documentation conventions

Each new module explains its responsibility and important boundaries. Public
functions explain the action, authorization and side effects. Inline comments
explain non-obvious reasons, such as atomic capacity allocation, raw webhook
verification, or invalidating quiz progress after a revised assessment. Prefer
clear names and short functions over comments that repeat each line of code.

When returning years later, start with this guide and `app/main.py`, then the
feature guide and its tests. Dated verification artifacts explain what was
demonstrated at a particular revision; they are not a replacement for current code.
