# Nurse.ng — Decision Record

**Status:** Agreed decisions from the 18 October 2026 working session
**Basis:** `Nurse_ng_Strategic_Product_Roadmap.md` (v1.0), `BUILD_PLAN.md`
**Scope:** Decisions that change the build plan's assumptions. This file is the running log; append new decisions, never rewrite history.
**Conventions:** Every abbreviation is expanded on first use in this file. Every design choice records its reason and its trade-off. The step-by-step record lives in `docs/WORK_LOG.md`.

---

## Agreed decisions


| # | Decision | Choice | Why | Revisit when |
|---|---|---|---|---|
| D1 | Build capacity | Solo builder, part-time (10–20 h/week), with AI (Artificial Intelligence) assistance | Current reality. The build plan's 112 engineer-day MVP (Minimum Viable Product) does not fit; at ~15 h/week the full S2–S7 build is roughly 60 weeks before review and defects | A second engineer joins, or the builder goes full-time |
| D2 | First nurse segment | New graduates | Sharpest need to establish status and find a first role; recent registration makes document review tractable | Pilot shows low willingness to engage, or employers prefer experienced hires |
| D3 | First employer segment | Public hospitals | Volume, legitimacy, and a strong trust signal for new graduates | Employer outreach produces no commitments within the Phase 0 window, or procurement proves unworkable |
| D4 | Discovery model | Invite-only pilot; no public directory | Build plan's explicit MVP recommendation; smallest abuse surface; staffable by one person. New graduates are a prime scam target | Abuse controls are proven and operations can be staffed |
| D5 | Employer access | None yet; willing to pursue | No existing relationships. Employer recruitment is therefore the critical path from day one | First public-hospital contact is established |
| D6 | Phase 0 budget | Defined budget available for counsel and manual verification support | Legal and verification assumptions can be tested rather than deferred | Budget is consumed or withdrawn |
| D7 | Backend start | A Django foundation was built and then deleted on 18 October 2026; a FastAPI foundation replaced it before the Phase 0 gate closes | Builder's direction. Recorded as an accepted risk, not a gate pass: if Phase 0 fails, this code is a liability rather than an asset | Phase 0 gate review |
| D8 | Development environment | uv (a Python package and project manager) for dependencies; SQLite (an embedded, file-based Structured Query Language (SQL) database) for development and tests; PostgreSQL (an open-source relational database) deferred | Fastest start while shell tooling was unavailable. PostgreSQL-specific behaviour is untested | Before any pilot data is stored |
| D9 | Backend framework | FastAPI (a Python web framework built on the ASGI (Asynchronous Server Gateway Interface) standard) with Jinja2 (a Python HTML templating engine) templates and HTMX (Hypermedia as the Extension of HTML, a JavaScript library for partial page updates); SQLAlchemy 2 (a Python SQL toolkit and Object-Relational Mapper (ORM)) + Alembic (a database migration tool for SQLAlchemy); pwdlib (a Python password-hashing library) with Argon2 (a memory-hard password-hashing algorithm) | Builder's choice, overriding the build plan's Django decision. Supersedes decision-ledger #2, #3, #5, and #8 in `BUILD_PLAN.md` | If assembled authentication, administration, or migration tooling costs more than the framework saves, or a Django-strength admin becomes necessary |
| D10 | Authentication | Server-side signed session cookie (Starlette (the ASGI web framework underlying FastAPI) `SessionMiddleware` (session middleware), signed with `itsdangerous` (a Python library for cryptographically signing data)); phone number + Argon2 password; per-session CSRF (Cross-Site Request Forgery) token; 14-day session lifetime | The MVP (Minimum Viable Product) is server-rendered, so sessions fit better than JWT (JSON Web Tokens) and need no client-side token storage. Same primitives the Django plan assumed, assembled explicitly | A mobile or partner API (Application Programming Interface) is committed (add token authentication then) or phone OTP (One-Time Password) / MFA (Multi-Factor Authentication) is introduced |

### Consequences

- **No custom reviewer console.** Django admin plus a documented procedure, if software is built at all.
- **No public search.** Invite-only discovery means search is not required to start; matching can be manual.
- **Concierge before software.** A manual pilot (spreadsheet, encrypted evidence store, email) tests verification cost, employer demand, and nurse supply before ~900 hours of build.
- **Early backend start.** At the builder's direction, a backend foundation was started on 18 October 2026 before the Phase 0 gate (D7). The Django version was deleted and replaced with FastAPI (D9). It implements no product workflow and does not count as a gate pass.
- **Employer recruitment starts immediately.** Public-hospital procurement is the longest-lead item and gates the pilot.
- **Status taxonomy must distinguish** student, graduate awaiting licensure, and registered nurse. A new graduate is not one undifferentiated category.
- **Authentication and profile foundation verified on 18 October 2026:** 46 tests passed, the initial Alembic (a database migration tool for SQLAlchemy) migration was applied, `alembic check` reported no schema drift, and Ruff (a Python linter) reported no findings. The verification record is in `docs/WORK_LOG.md`.

---

## Design log

Implementation choices made after the D-series decisions. Each entry states the choice, the reason, and the trade-off accepted. D10 sets the overall authentication direction; the entries below record the details.

### L1 — Phone number as the login identifier
- **Choice:** `users.phone` is the unique login identifier and is normalised to E.164 (the international telephone numbering standard) on write.
- **Reason:** nurses reliably hold a phone number, while email access varies; a single identifier also prevents duplicate accounts written as `0801...` and `+234801...`.
- **Trade-off:** no email-based recovery until an email flow is added. Numbers not written with a leading `+` are treated as Nigerian local numbers only when they are exactly 11 digits starting with `0`.

### L2 — Signed session cookie instead of JWT (JSON Web Token)
- **Choice:** `SessionMiddleware` stores `user_id` in a signed, client-side cookie.
- **Reason:** the MVP (Minimum Viable Product) is server-rendered; no token storage or refresh logic is needed; signing prevents tampering.
- **Trade-off:** signed cookies are stateless, so there is no per-device revocation list; logout clears only the browser's cookie. Server-side revocation relies on the per-request user status check in L9. A JWT (JSON Web Token) would have the same revocation problem with more moving parts.

### L3 — `itsdangerous` for cookie signing
- **Choice:** depend on `itsdangerous` (a Python library for cryptographically signing data) rather than hand-roll a signed-cookie format.
- **Reason:** maintained and widely used; avoids custom cryptography.
- **Trade-off:** one new runtime dependency, which must be installed in the existing virtual environment.

### L4 — Session fixation
- **Choice:** `request.session.clear()` before writing `user_id` after registration or login.
- **Reason:** prevents an attacker-supplied session identifier from becoming authenticated.
- **Trade-off:** pre-login session data (currently only the CSRF (Cross-Site Request Forgery) token) is discarded; a new token is issued on the next rendered page.

### L5 — CSRF (Cross-Site Request Forgery) token on every POST (HTTP POST method)
- **Choice:** a random per-session token is rendered as a hidden form field; `verify_csrf` compares it with `hmac.compare_digest`.
- **Reason:** cookie-authenticated forms are otherwise forgeable from another site.
- **Trade-off:** every form must include the field; HTMX (Hypermedia as the Extension of HTML) requests will need the token supplied explicitly; no double-submit cookie or `Origin` / `Referer` check yet.

### L6 — Password length rules
- **Choice:** minimum 8, maximum 128 characters; no composition rules.
- **Reason:** length is the dominant factor in password strength; the maximum prevents an attacker from forcing expensive Argon2 (a memory-hard password-hashing algorithm) hashing on very large inputs.
- **Trade-off:** long but weak passwords (for example, a long common phrase) are accepted; a breached-password check is a later addition.

### L7 — Argon2 through `pwdlib`
- **Choice:** `PasswordHash.recommended()` from `pwdlib` (a Python password-hashing library), which selects Argon2.
- **Reason:** modern, salted, memory-hard; one call site for hashing and verification.
- **Trade-off:** Argon2 is deliberately expensive in CPU (Central Processing Unit) time and memory; the recommended parameters are untuned for the eventual host.

### L8 — Uniform sign-in failure
- **Choice:** an unknown phone number and a wrong password return the same 401 (Unauthorized) message.
- **Reason:** prevents account enumeration.
- **Trade-off:** slightly worse user experience. Timing still differs because no dummy hash is verified for unknown numbers; a dummy-hash check and rate limiting are required before public launch.

### L9 — Account status checked on every request
- **Choice:** `get_current_user` rejects users who are inactive or whose status is not `active`.
- **Reason:** suspension takes effect on the next request without a session revocation table.
- **Trade-off:** one database query per authenticated request; a cache may be needed at scale.

### L10 — Form responses and status codes
- **Choice:** validation errors re-render the form with 400 (Bad Request), a duplicate phone with 409 (Conflict), and a failed login with 401 (Unauthorized).
- **Reason:** gives tests and future HTMX (Hypermedia as the Extension of HTML) handlers precise semantics while keeping server-rendered forms.
- **Trade-off:** errors intentionally do not use Post/Redirect/Get (PRG), so the browser shows the returned page and a refresh may resubmit the form.

### L11 — Shared renderer and CSRF token
- **Choice:** `app/web/templating.py` `render()` injects the CSRF (Cross-Site Request Forgery) token into every template context.
- **Reason:** a template cannot forget the token when it is always present.
- **Trade-off:** any template rendered outside `render()` will not have it.

### L12 — FastAPI return annotations pinned to `Response`
- **Choice:** HTML and redirect endpoints are annotated `-> Response`.
- **Reason:** FastAPI (a Python web framework) infers a response model from endpoint return annotations; a union such as `RedirectResponse | object` is rejected at import or startup.
- **Trade-off:** the annotation is less precise than the concrete response class.

### L13 — Ruff (a Python linter) B008 exception
- **Choice:** add `fastapi.Depends`, `fastapi.Form`, and `fastapi.File` to `extend-immutable-calls`.
- **Reason:** B008 (a Bugbear lint rule) forbids function calls in argument defaults; FastAPI dependency and upload declarations are calls in defaults by design.
- **Trade-off:** the exception applies to all Bugbear checks in the project.

### L14 — Installable application package
- **Choice:** declare a Hatchling (a Python build backend) build system with `packages = ["app"]` in `pyproject.toml`.
- **Reason:** the repository has several top-level directories (`app`, `tests`, `migrations`, `docs`), so setuptools' automatic package discovery fails and `pip install -e .` cannot build. Explicit discovery makes the application installable and editable.
- **Trade-off:** one build-time dependency (Hatchling) and a build configuration to maintain. Tests, migrations, and documentation are deliberately not packaged.

### L15 — Editable installation of the application
- **Choice:** install the project with `pip install -e .` (editable mode) rather than installing dependency names individually.
- **Reason:** `pyproject.toml` stays the single source of dependency truth; no duplicated list can drift.
- **Trade-off:** editable installs add a path configuration file to the virtual environment; the package must remain importable with its declared backend.

### L16 — `httpx2` for the test client
- **Choice:** the development dependency is `httpx2` (an HTTP (Hypertext Transfer Protocol) client library) instead of `httpx`.
- **Reason:** the installed Starlette (the ASGI (Asynchronous Server Gateway Interface) web framework underlying FastAPI) version 1.8.0 raises `RuntimeError` when its `TestClient` is imported without `httpx2`. The installed FastAPI (a Python web framework) is 0.143.3.
- **Trade-off:** `httpx2` is a newer and less widespread library than `httpx`; tests depend on the Starlette version's requirement. If Starlette returns to `httpx`, this dependency must be revisited.

### L17 — Environment management during verification
- **Choice:** verify using the existing `venv/` virtual environment and `pip` (Python's package installer), installing the project in editable mode.
- **Reason:** the virtual environment already existed and contained `alembic` and `pytest`; using it avoided creating a second environment while still resolving dependencies from `pyproject.toml`.
- **Trade-off:** this departs from D8's stated use of `uv` (a Python package and project manager), and `pip` produced no committed lockfile. Dependency resolution therefore uses the `>=` ranges in `pyproject.toml` and is not byte-for-byte reproducible. A lockfile (`uv.lock` or a pinned requirements file) should be added and committed; this is recorded as an open item, not silently fixed.

### L18 — Profiles are created explicitly, not at registration
- **Choice:** no nurse profile is created when an account registers. `GET /profile` redirects to `GET /profile/edit`, and the first successful save creates the profile.
- **Reason:** accounts may later belong to employers, reviewers, or partners, not only nurses; creating a nurse profile for every account would produce empty, misleading rows and assume a role the system does not yet model.
- **Trade-off:** one extra navigation step before a nurse can save a profile, and every profile page must handle the "no profile yet" state. There is no audit event distinguishing the first creation from later edits.

### L19 — New profiles are drafts and private
- **Choice:** a created profile has status `draft` and `discoverable = false`; there is no interface for field visibility or discoverability in this increment.
- **Reason:** private-by-default is a stated product requirement; nothing should become visible because a form omitted a control.
- **Trade-off:** a profile cannot be shared with an employer yet, and the existing `FieldVisibility` model remains unused. Activation and sharing need their own increment.

### L20 — A single upsert form for create and edit
- **Choice:** one `POST /profile/edit` route creates the profile when absent and updates it when present.
- **Reason:** avoids a duplicate route and duplicated validation; editing is naturally idempotent.
- **Trade-off:** HTTP (Hypertext Transfer Protocol) semantics do not distinguish creation from update, so an audit log cannot tell them apart without comparing state.

### L21 — Profile validation mirrors the database columns
- **Choice:** display name is required; maximum lengths are 120 for display name, 160 for headline, 120 for location, and 5000 for bio; professional status must be one of `student`, `graduate`, `registered`, or `specialist`.
- **Reason:** the user gets a form error instead of a database error, and arbitrary status values cannot enter the column.
- **Trade-off:** the limits are duplicated between the model and the service; a schema change must update both, and the bio cap is an arbitrary abuse control rather than a database limit.

### L22 — Profile ownership comes from the session, not the URL (Uniform Resource Locator)
- **Choice:** every profile read and write filters by the signed-in user's `user_id`; no profile identifier appears in a route.
- **Reason:** prevents IDOR (Insecure Direct Object Reference), where changing an identifier in a URL exposes another person's profile.
- **Trade-off:** there is no administrator or reviewer route to open another nurse's profile from the profile domain; the only cross-profile path is the staff document-review queue, which is scoped to submitted cases and audited (L49).

### L23 — Professional status is labelled self-declared
- **Choice:** the profile page shows the status with the words "(self-declared)", and the edit form links to document review while saying the status itself is self-declared.
- **Reason:** document review checks the licence/certificate and identity, not the status value; the product must not imply that an unverified value has been checked.
- **Trade-off:** the page is less persuasive than a badge would be. The label sits beside a review badge, so the interface must keep the two claims visibly distinct (L47, L52).

### L24 — Post/Redirect/Get after a successful save
- **Choice:** a successful save returns 303 (See Other) to `GET /profile`; validation errors re-render the form with 400 (Bad Request).
- **Reason:** prevents duplicate submissions when the user refreshes the result page, while preserving entered values on error.
- **Trade-off:** there is no inline success message, and refreshing an error page resubmits the form.

### L25 — Lint policy for generated migrations
- **Choice:** ignore E501 (line too long) and I001 (unsorted imports) for `migrations/versions/*.py`.
- **Reason:** Alembic (a database migration tool) autogenerates long lines and its own import order; hand-formatting generated code creates churn and risks editing it incorrectly.
- **Trade-off:** hand-written migrations in that directory also skip those two checks; every other Ruff (Python linter) rule still applies.

### L26 — Tests are a package with shared helpers
- **Choice:** add `tests/__init__.py` and `tests/helpers.py` for CSRF (Cross-Site Request Forgery) extraction and sign-in setup.
- **Reason:** avoids duplicating the same form-extraction and registration code across test modules.
- **Trade-off:** test modules are imported as `tests.*`, and helper changes affect every web test module at once.

### L27 — Activation is a separate action from saving
- **Choice:** saving a profile keeps it in `draft`; a separate `POST /profile/activate` (with a CSRF token) moves it to `active`. Activation requires a non-empty display name.
- **Reason:** sharing must be a deliberate act, not a side effect of editing. A form save can never expose a profile by accident.
- **Trade-off:** one extra step before a link exists, and a profile can be complete but inactive. There is no audit event for activation or deactivation.

### L28 — The share link uses an opaque public identifier
- **Choice:** the public page is `GET /p/{public_id}`, where `public_id` is a UUID version 7 (a time-ordered universally unique identifier) generated when the profile is created. It is never the licence number, registration number, phone number, or internal database key.
- **Reason:** the identifier is unguessable and non-enumerable, and the URL carries no personal data. Possession of the link is the access control.
- **Trade-off:** the link is not human-readable. Anyone who receives it can reopen it, so revocation requires deactivation. UUID version 7 embeds a creation timestamp; that reveals only roughly when the profile was created.

### L29 — The public page shows only explicitly public fields
- **Choice:** `public_profile_fields` returns a field only when it has a `FieldVisibility` row set to `public` **and** a non-empty value. If the display name is private or empty, the page falls back to the heading "Nurse profile".
- **Reason:** private-by-default is the product requirement; a missing or malformed row must never cause a field to leak. The fallback keeps a shareable page sensible without revealing the name.
- **Trade-off:** an active profile can show almost nothing. The owner page warns when the name is private and reports the public field count.

### L30 — Activation never opts a profile into discovery
- **Choice:** `activate_profile` always sets `discoverable = false`, even if the stored column was changed elsewhere.
- **Reason:** the invite-only pilot has no directory (D4). A share link and being listed are different consents, and only the first is implemented.
- **Trade-off:** the `discoverable` column exists but no workflow sets it; a future directory needs its own explicit control, not a reuse of activation.

### L31 — An absent visibility row means private; choosing private deletes the row
- **Choice:** the database stores a row only for fields set to `public`. Setting a field back to private deletes its row.
- **Reason:** absence-as-private keeps the default safe and prevents stale rows from silently becoming meaningful later.
- **Trade-off:** no history of past sharing choices is kept, and re-sharing a field creates a new row with a new identifier.

### L32 — "Employers" visibility is rejected until employer accounts exist
- **Choice:** the stored `Visibility` enumeration includes `employers`, but `ALLOWED_VISIBILITIES` accepts only `private` and `public`; posting `employers` returns 400 (Bad Request).
- **Reason:** no employer account or employer view exists. Offering an option that does nothing would mislead nurses about who can see their details.
- **Trade-off:** the sharing form and service validation must change when employer access is built; the deferred level is documented in the interface copy.

### L33 — Public pages are excluded from search indexing
- **Choice:** every `GET /p/{public_id}` response carries `X-Robots-Tag: noindex, nofollow`, and `GET /robots.txt` returns `User-agent: *` / `Disallow: /`.
- **Reason:** an invite-only pilot must not leak into search indexes, and the robots rule also covers future pages by default.
- **Trade-off:** `robots.txt` is advisory and does not prevent a crawler that ignores it; the response header is the stronger control. The blanket `Disallow` must be narrowed deliberately when public marketing pages are added.

### L34 — Deactivation returns the profile to draft without deleting it
- **Choice:** `POST /profile/deactivate` sets the status back to `draft`; the public URL then returns 404 (Not Found). No data is deleted.
- **Reason:** gives immediate revocation while preserving the nurse's work.
- **Trade-off:** re-activation restores the same `public_id`, so any previously shared link starts working again. There is no way to issue a new link without changing the profile's public identifier (not exposed in this increment).

### L35 — Authentication is checked before CSRF validation
- **Choice:** on state-changing profile routes, `require_user` is declared before `verify_csrf` in the dependency list (FastAPI (a Python web framework) resolves dependencies in parameter order).
- **Reason:** an anonymous POST then redirects to sign-in with 303 (See Other), consistent with every GET route and with the tests, instead of returning 400 (Bad Request). CSRF validation still runs for any authenticated request.
- **Trade-off:** an unauthenticated request is short-circuited before its CSRF token is examined. That is acceptable because the token protects a session, and there is no session to protect.

### L36 — The session SameSite setting is a typed literal
- **Choice:** `session_same_site` is declared as `Literal["lax", "strict", "none"]` rather than a plain string.
- **Reason:** Starlette's (the ASGI (Asynchronous Server Gateway Interface) web framework underlying FastAPI) `SessionMiddleware` accepts only those three values. The type makes the constraint explicit to editors and static checkers, and Pydantic (the validation library behind the settings) rejects a mistyped environment value at startup instead of failing later inside the middleware.
- **Trade-off:** accepting a new SameSite value requires changing the type as well as the configuration; environment values remain case-sensitive.

### L37 — Per-IP throttling state is in process memory
- **Choice:** a fixed-window `FixedWindowLimiter` in `app/core/ratelimit.py` counts events per key in a plain dictionary guarded by a `threading.Lock`. Login failures are counted per client address; registration attempts are counted per client address.
- **Reason:** no new dependency, no write per request, and enough to blunt scripted guessing while the pilot runs one server process.
- **Trade-off:** counters reset when the process restarts and are not shared between workers. If the deployment moves to multiple workers or instances, this must become Redis or a database-backed counter before the limits are meaningful.

### L38 — Account lockout is persisted on the user row
- **Choice:** `users.failed_login_attempts` (integer, default 0) and `users.locked_until` (nullable timestamp) hold the lockout state. A failed password check increments the counter; reaching the threshold sets `locked_until`.
- **Reason:** a persisted lock survives a restart and is visible to every process, unlike the in-memory IP counter. It also keeps the decision on the account, which is the thing being protected.
- **Trade-off:** an attacker who knows a phone number can deliberately lock that account for the lock window (targeted denial of service). The window is short and IP throttling limits how fast an attacker can cycle accounts; a lock that never expires was rejected for this reason.

### L39 — Unknown numbers still perform a password hash
- **Choice:** the module holds one Argon2 hash generated at import; an unknown phone, or a user with no stored password, runs `verify_password` against it before returning `None`.
- **Reason:** removes the most obvious timing difference between "no such account" and "wrong password", complementing the existing uniform message (L8).
- **Trade-off:** one Argon2 verification is spent on every unknown-number attempt, which an attacker can use to consume CPU. The per-IP throttle bounds that cost per address. Generating the dummy hash at import adds a small fixed startup cost.

### L40 — An expired lock starts a fresh count
- **Choice:** when a login arrives after `locked_until` has passed, the lock and the failure counter are cleared before the password is checked.
- **Reason:** otherwise the first mistake after a completed lock immediately re-locks the account, and a user could never recover without operator help.
- **Trade-off:** the account gets a full new allowance of failures after each lock window. This is intentional; the IP throttle still limits the total rate.

### L41 — The client address is the ASGI peer address
- **Choice:** `request.client.host` is the throttle key. `X-Forwarded-For` is not read.
- **Reason:** nothing in the trust chain can yet distinguish a real forwarded header from one an attacker sets. Trusting the header without a configured proxy would let an attacker rotate the key and bypass the limit.
- **Trade-off:** behind a reverse proxy every request appears to come from the proxy, so one shared counter covers all users. Trusted-proxy parsing must be added with the production deployment configuration before the limits are exercised in production.

### L42 — The lockout migration uses batch alter
- **Choice:** revision `8f2c1d4a9b6e` adds and drops the columns through `op.batch_alter_table`.
- **Reason:** SQLite (an embedded, file-based Structured Query Language database) has narrower `ALTER TABLE` support than PostgreSQL (an open-source relational database); batch mode recreates the table and keeps `downgrade()` valid on both.
- **Trade-off:** the generated SQL is more verbose than a direct `ADD COLUMN`, and the batch copy rewrites the table. At current table sizes this is negligible.

### L43 — Tests reset every limiter between cases
- **Choice:** an autouse fixture in `tests/conftest.py` calls `reset_all_limiters()` before and after each test.
- **Reason:** Starlette's `TestClient` reports the same synthetic peer address for every request, so an allowance spent in one case would silently block the next. The reset keeps each case independent without exposing limiter internals through the application.
- **Trade-off:** the fixture clears global state, so a test that deliberately wants cross-case persistence would need to opt out. None does.

### L44 — Limits are configuration, not constants
- **Choice:** the six limits live on `Settings` with defaults: login 10 failures per 300 seconds per IP, registration 5 attempts per 3600 seconds per IP, lockout at 5 consecutive failures for 900 seconds. They are overridable through `NURSE_NG_*` environment variables.
- **Reason:** operational tuning should not require a code change, and tests read the same values rather than duplicating magic numbers.
- **Trade-off:** a misconfigured environment can weaken the protection; values are not validated against a safe minimum beyond being usable by the limiter.

### L45 — Lockout responses are explicit and carry `Retry-After`
- **Choice:** a tripped IP limit and a locked account both return 429 (Too Many Requests) with a generic "try again in N minute(s)" message and a `Retry-After` header. A wrong password that has not tripped anything still returns 401 (Unauthorized) with the existing generic message.
- **Reason:** the user chose clarity for a pilot audience over resisting account enumeration. `Retry-After` lets a client or proxy back off correctly.
- **Trade-off:** the 429 confirms that a phone number has an account. Mitigations are the uniform 401 before the threshold and the short lock window. A future decision could return 401 during lockout to remove the signal, at the cost of confusing locked-out users.

### L46 — The lockfile is a pip snapshot of the verified environment
- **Choice:** `requirements.lock` is generated with `pip freeze --exclude-editable` from the `venv/` environment in which the test suite was verified. The project's own editable install is excluded so the file contains only third-party pins.
- **Reason:** uv (a Python package and project manager) is not installed on the development machine, despite D8 naming it, and installing a new package manager merely to produce a lock would add an unverified tool to the session. The venv snapshot records exactly the versions that passed, including transitive dependencies, with no resolution step or network call.
- **Trade-off:** the file captures development and runtime dependencies together and is tied to whatever happened to be installed; regenerating it requires the venv. When uv is adopted, `uv.lock` can be generated from the same `pyproject.toml` and this file retired.

### L47 — The supported label is "document reviewed", not "source confirmed"
- **Choice:** document review means a Nurse.ng reviewer inspected an uploaded NMCN (Nursing and Midwifery Council of Nigeria) licence or certificate and a government-issued photo ID and matched the names to the profile. Approval sets `nurse_profiles.document_reviewed_at`. The public page shows the label with a receipt stating what was checked, the review date, and explicitly that Nurse.ng does not check NMCN's register, does not prove authenticity, and does not assess competence.
- **Reason:** the user chose this workflow while O1 (source-confirmed verification) remains open and web research is blocked. The label must describe only what a reviewer actually did. A truthful downgrade lets the pilot test demand without manufacturing the certainty the Phase 0 gate exists to test.
- **Trade-off:** assurance is weaker than a register check. A convincing forgery can pass a visual review, and the platform cannot promise that a registration is currently valid. A future source-confirmed route needs its own label and must not silently upgrade historic cases.

### L48 — Evidence is private local storage with opaque names and magic-byte checks
- **Choice:** uploaded files are written under `settings.evidence_dir` (default `evidence/`, gitignored), outside the static tree, with a UUID version 4 hexadecimal name. Content is accepted only when its leading bytes are JPEG, PNG, or PDF; the declared MIME type and filename are ignored. Each file is capped at 5 MB (`NURSE_NG_EVIDENCE_MAX_BYTES`), hashed with SHA-256, and recorded with its original filename for the reviewer's context. Writes are atomic within the directory, the directory is created with mode `0700`, and each file is set to `0600`.
- **Reason:** no object-storage dependency for the pilot; opaque names prevent guessing or path traversal; magic bytes stop a client from uploading one type while claiming another; the digest supports integrity checks; restrictive permissions keep the files private to the service account.
- **Trade-off:** local disk is unencrypted, unreplicated, and unscanned. `mkdir` does not tighten an existing directory, and file modes do not protect against a privileged operator or backups. Database cascades remove evidence rows but do not delete the files on disk, so any future deletion path must reconcile both. There is no malware scan, encryption at rest, or retention job. Before production this store must move to private object storage with encryption, malware scanning, and scheduled deletion (O4), and this decision must record that migration.

### L49 — The review area is staff-only, and every evidence open is audited
- **Choice:** all `/review` routes require `is_staff`, set only through `python -m app.cli set-staff <phone>` (no web route grants it). Evidence is served only by `GET /review/{case_id}/evidence/{evidence_id}`, which checks that the evidence belongs to the case and writes an `evidence_accesses` row (reviewer, timestamp) before returning the file. Evidence responses carry `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow`.
- **Reason:** evidence is the most sensitive data the platform holds. A read audit supports NDPA (Nigeria Data Protection Act) accountability and lets the operator answer "who saw this document, and when". Scoping by both identifiers prevents cross-case evidence discovery.
- **Trade-off:** the access table grows without bound until a retention job exists. Opening the case page or queue is not audited, only opening a file, so logins and browse activity still rely on server logs. Anyone with direct database access can bypass the application log.

### L50 — Submission requires explicit consent; the registration number stays private
- **Choice:** the submission form has a required consent checkbox ("I consent to Nurse.ng storing these documents privately and to a reviewer inspecting them"), validated on the server as well as in HTML. The NMCN registration number is required, validated, stored on the case, shown to reviewers, and never published on the profile.
- **Reason:** document review processes sensitive personal data; storing it requires a legible consent step. The registration number is a professional identifier and adds nothing to the public page that the review label does not already convey.
- **Trade-off:** consent is one broad checkbox, not granular per purpose, and it is not versioned. There is no self-service withdrawal or deletion flow; deletion depends on the retention decision (O4). Counsel should review the wording.

### L51 — One pending case, no self-review, and decisions are final
- **Choice:** a profile may have at most one pending case. A reviewer cannot decide their own case. Approval moves `document_reviewed_at` forward; rejection requires a note and leaves an earlier approval in place. Once decided, a case cannot be changed; a nurse submits a new case instead.
- **Reason:** duplicate pending cases would split evidence across decisions. The label's meaning depends on a second person inspecting the documents. Rejection needs a reason the nurse can act on. Keeping the earlier approval avoids erasing a review that did happen.
- **Trade-off:** there is no appeal or reopen route, and a later rejection does not revoke an earlier label. If the product later treats new adverse evidence as revoking, that needs an explicit decision and a new field rather than reusing this date. The one-pending rule is a check before insert, not a database constraint, so two simultaneous submissions could both pass; a partial unique index on `(profile_id)` where `status = 'pending'` is needed before the queue handles concurrent traffic. Two reviewers deciding the same case concurrently would be last-write-wins; the pilot assumes one reviewer at a time, and a conditional status update is needed before more than one reviewer works the queue.

### L52 — The public label is accompanied by a receipt
- **Choice:** the public page renders the "Document reviewed" badge with a short receipt and a footer that distinguishes a reviewed profile from an unreviewed one. The owner page shows the same status plus review history. The edit form points to the review page instead of claiming verification does not exist.
- **Reason:** a bare badge overstates what happened. The receipt states the scope and limits in the same place a viewer sees the claim, and the footer prevents an old sentence ("not verified") from contradicting a reviewed profile.
- **Trade-off:** the public page is longer, and the wording is a product/legal statement that must be reviewed by counsel and kept in step with L47 and the O1 outcome.

### Deferred verification work
- **Not built yet:** source confirmation against NMCN's register (O1), a distinct source-confirmed label, evidence encryption and malware scanning, object storage, retention and deletion schedules (O4), appeals or reopen, reviewer workload tooling, a consent version record, withdrawal of consent, and employer-facing display of review status.
- **Reason:** the pilot tests document review first. Each item adds operational, legal, or verification-cost surface that the open decisions have not settled.
- **Trade-off:** the current store is suitable for a controlled pilot only. It must not be described as production-grade evidence handling until the storage and retention items exist.

### Deferred authentication work
- **Built on 21 October 2026:** login rate limiting (per-IP), account lockout, and dummy-hash timing equalisation.
- **Not built yet:** email recovery, phone OTP (One-Time Password), MFA (Multi-Factor Authentication), breached-password checks, remember-me, per-device session management, trusted-proxy address handling (L41), distributed rate-limit state (L37), and startup enforcement of a high-entropy production secret key.
- **Reason:** none are required to prove the session flow; each adds operational or legal surface.
- **Trade-off:** the system is not safe for a public launch until at least the production secret key and trusted-proxy handling exist. Per-IP limits are only meaningful in production once the proxy question is settled.

### Production configuration required before launch
- `NURSE_NG_SECRET_KEY` must be set to a high-entropy value; the default `insecure-dev-key-change-me` signs development cookies only.
- `NURSE_NG_SESSION_HTTPS_ONLY` must be `1` behind HTTPS (Hypertext Transfer Protocol Secure).
- The session cookie is `SameSite=Lax` and not `Secure` by default in development.

---

## Open decisions

| # | Decision | Status | Blocker |
|---|---|---|---|
| O1 | Launch verification: document-based or source-confirmed | Open | Research protocol drafted on 21 October 2026 in `docs/O1_VERIFICATION_SOURCE_MEMO.md`; web tooling was blocked, so no source was retrieved and no finding exists. The memo must be completed before the Phase 0 gate can close |
| O2 | Legal entity that operates the platform | Open | Needs counsel input; affects NDPA 2023 (Nigeria Data Protection Act 2023) controller registration and trust surface |
| O3 | Numeric pilot gates and cost-per-verified-profile target | Open | Requires ten timed manual cases before a target can be set |
| O4 | Evidence retention period and deletion schedule | Open | Needs counsel input for NDPA 2023 (Nigeria Data Protection Act 2023). Interim behaviour is to keep every case and evidence file and audit each access (L49); no deletion job exists |
| O5 | Whether the concierge pilot stores identity documents at all | Open | Depends on O1 and counsel advice; minimum-data option is registration number plus certificate image. The software workflow now stores both documents with consent (L50); this does not decide the manual pilot's practice |

---

## Notes on this session

- Document review was implemented provisionally on 21 October 2026 at the user's direction (L47–L52). It supports the label "document reviewed" only, shows no source confirmation, and does not close O1.
- Verification-source feasibility remains **unresearched**. The user deferred the research on 18 October 2026 in order to continue building; nothing here should be read as a finding about the NMCN (Nursing and Midwifery Council of Nigeria) or its services.
- The roadmap's Phase 4–6 (jobs, community, international mobility) remain out of scope and are not affected by these decisions.
- These decisions revise the build plan's assumptions; `BUILD_PLAN.md` itself has not been edited. A revision should be made once Phase 0 closes, not before.

---

## Agreed revision — 26 October 2026

The builder proposed easier enrolment as an adoption strategy: open registration, optional professional verification, voluntary public profiles, and a community experience people can use before requesting verification. The choices below were discussed and selected by the user. They record product direction; the new community features still require implementation. Earlier entries remain as history, and this dated revision governs the choices it supersedes.

### Working agreement reaffirmed

- The assistant proposes options, explains a recommendation and the reasons and trade-offs, and asks the user to choose.
- The user's selected option or combination is the agreed design choice. An ambiguous answer is clarified rather than treated as approval of an arbitrary option.
- Approved choices are documented immediately. Further design and implementation work stays within the agreed scope.

### Additional agreed decisions

| # | Decision | Choice | Why | Revisit when |
|---|---|---|---|---|
| D11 | Enrolment and verification timing | Open enrolment replaces the invite-only launch policy in D4. Professional verification is optional for joining and participating and can be introduced gradually | Reduce enrolment friction and let people experience the platform's value before submitting documents | Participation, trust, or operating evidence calls for a different enrolment model |
| D12 | Initial community scope | Topic discussions, a public feed, and finding and connecting with other nurses are all included in the agreed community direction | The user chose all three so members can interact and develop professional relationships | Usage and the solo builder's operating capacity justify changing scope |
| D13 | Publication and audience | Profiles remain private until the owner chooses to publish. Anyone can read the public feed and topic discussions; registered members can post and reply | Combine a simple publication choice with an experience visitors can try before enrolling | User feedback or privacy and moderation requirements justify revising the audience rules |

### L53 — Open enrolment with optional professional verification

- **Choice:** people can register and participate without professional document review. Licence/certificate and identity evidence are requested when a member seeks review, rather than as a requirement for joining. Verification can be introduced gradually.
- **Reason:** the user wants early adoption to come from experiencing the community, with a more flexible and accommodating enrolment process.
- **Trade-off:** membership alone cannot support a professional verification claim. Self-declared information remains self-declared; the existing "Document reviewed" label still requires an actual approval and receipt under L47 and L52. Basic account authentication remains distinct from professional verification.

### L54 — A simple public-profile choice

- **Choice:** a profile stays private until its owner explicitly chooses "Make public" instead of "Keep private". The proposed enrolment flow shows a preview of the details that will become public. Contact details, registration numbers, and identity evidence retain their existing private boundaries.
- **Reason:** the user explicitly chose a simple public choice, rather than automatic publication. A clear decision makes publication easy while preserving control over personal information.
- **Trade-off:** the publication preview, its initial field selection, and the relationship between publication and member discovery still need detailed design. Search-engine indexing has not been selected by this choice. Public profile permission must not silently expose other private fields.

### L55 — All three community experiences

- **Choice:** include topic discussions, a public feed, and finding and connecting with other nurses. The user clarified that they wanted all three, rather than a single feature from the proposed options.
- **Reason:** these experiences provide opportunities to ask questions, share experiences, discover peers, and establish relationships, which can give members a reason to return.
- **Trade-off:** community introduces content and moderation work alongside profile and verification work. Early adoption and retention remain hypotheses to measure, rather than proof of employer demand or sustainable operating costs. Formal learning services, a jobs marketplace, and international mobility are separate later feature families.

### L56 — Following and accepted connection requests

- **Choice:** support both immediate following of another nurse's public updates and connection requests accepted by the other nurse. The user selected options 1 and 2 together. Neither relationship requires professional document review.
- **Reason:** following supports interest in public updates, while accepted requests establish a mutual professional relationship and give both members control over that relationship.
- **Trade-off:** the interface must explain the two relationships clearly. Notification behaviour, messaging, and any additional information available to connections have not been agreed; accepting a request must not silently settle those separate permissions.

### L57 — Public reading with account-based contribution

- **Choice:** anyone can read the public feed and topic discussions. Posting and replying require a registered member to sign in. The user selected option 1, rather than requiring registration to read or using different audiences for the feed and discussions.
- **Reason:** visitors can experience the platform's value before enrolling, supporting the user's adoption strategy.
- **Trade-off:** discussion content is visible beyond the registered community, so the posting experience must state its audience clearly. Moderation, reporting, and how a post author's visible identity relates to a private profile still require agreed rules.

### L58 — One conversation shared between its topic and the feed

- **Choice:** a member posts under a topic, and that post also appears in the public feed. Its replies belong to the same conversation in both places. The user selected the shared-post option.
- **Reason:** one posting flow supports both experiences, lets discussions reach more people, and avoids splitting a conversation across two sets of replies.
- **Trade-off:** topic posts enter the public feed as part of the agreed model. Topic categories, permitted content formats, feed ordering, and personalisation remain to be chosen.

### Effect on earlier plans and open decisions

- D11 supersedes the invite-only enrolment policy in D4. D13 preserves the private-by-default principle while changing the proposed publication experience.
- D12 brings community interaction forward from the roadmap's later community phase. D1 (solo, part-time capacity), D2 (new graduates), D3 (public hospitals), and D9 (FastAPI) have not been replaced by these choices.
- Open decisions O1–O5 remain open. The revised public release needs its launch criteria reviewed against its actual claims and evidence handling; these product choices do not close the original Phase 0 gate or establish a lawful authoritative verification source.
- Content formats, starter topics, moderation and reporting rules, discovery and indexing details, notifications, messaging, connection permissions, and a delivery sequence have not yet been selected.
- The existing build plan and Phase 0 plan remain historical planning documents. This revision records the new direction without presenting their older invite-only and deferred-community assumptions as the latest choices.

### L59 — Text, images, and video in the initial community version

- **Choice:** support text, images, and video from the first community version. The user selected all three proposed format sets, which includes the complete set of formats. These formats belong to the shared topic/feed experience under L58 and its public audience under L57.
- **Reason:** the user chose the full range of expression for the more accommodating community experience, rather than beginning with text alone. Members can share written contributions and visual content as part of the adoption strategy.
- **Trade-off:** media adds handling and moderation work, and storage and bandwidth costs depend on the publishing approach. Direct uploads, external video links, or a combination have not yet been selected. Permitted file types, sizes, video duration, processing and storage arrangements, and media attachments in replies still need detailed decisions.
- **Effect on earlier notes:** this choice resolves the content-format question listed as pending in the initial 26 October revision. The other open design details and implementation status remain as recorded above.

### L60 — Media uploads and external video links

- **Choice:** members can upload images and videos from their devices and share existing videos through external links. The user selected the "Uploads plus video links" option for the initial community experience.
- **Reason:** this supports sharing original media and existing video resources through the same community, matching the user's preference for flexible participation.
- **Trade-off:** the application must support uploaded media and linked-video presentation. Uploaded video requires storage and processing arrangements; linked videos depend on their external hosts. Upload counts, file sizes, video duration, permitted types, storage and processing providers, and detailed presentation behaviour remain to be selected.
- **Effect on earlier notes:** the media-sharing method listed as pending in L59 is now agreed. This choice does not select a hosting provider, commit to costs, decide media attachments in replies, or establish that media support has been implemented.

### L61 — Initial community-post upload limits

- **Choice:** a community post can include up to four uploaded images and one uploaded video of up to three minutes. The user selected the recommended initial limit set. These limits apply to uploads; longer videos can be shared through external links under L60.
- **Reason:** this gives members room for photos and short explanations while bounding the media attached to an individual post and the associated hosting and moderation work.
- **Trade-off:** larger albums and longer video files exceed this initial native-upload allowance. The external-video route remains available for longer resources. File-size limits, permitted types, processing and storage arrangements, any account-level upload limits, and media attachments in replies remain to be selected.
- **Effect on earlier notes:** the image count, uploaded-video count, and uploaded-video duration listed as pending in L60 are now agreed for posts. This remains a planned limit set, rather than an implemented or performance-verified behaviour.

### L62 — Publication after automatic checks with staff moderation

- **Choice:** posts and replies become visible after automatic checks and any necessary media processing. Routine staff approval is not required before publication. Members can report content, and staff can review and remove it. The user selected option 1 from the proposed publishing approaches.
- **Reason:** this supports responsive conversations and lets members participate without waiting for an initial or ongoing staff-approval queue.
- **Trade-off:** reported issues may need to be handled after content is already public. Community rules, the exact automatic checks, reporting and review workflows, response targets, moderation permissions, and appeals still need detailed decisions. Automatic checks and content publication do not confer professional verification or a "Document reviewed" label.
- **Effect on earlier notes:** the initial publication approach is now agreed. The staff-approval alternatives were not selected, and the new moderation workflow remains planned rather than implemented.

---

## Approved implementation decisions — 28 October 2026

The choices below were made after reviewing the first community implementation. They define the trust and abuse-control hardening requested before that increment is treated as complete.

### L63 — A document review keeps the name that was actually reviewed

- **Choice:** an approval stores the profile display name that the reviewer saw. If the member later changes the current display name, the review remains in history and the public receipt names the reviewed identity explicitly; it must not imply that the new name was matched to the documents.
- **Reason:** the user selected a reviewed-name snapshot instead of invalidating the approval or blocking later name corrections. The receipt can continue to state what truly happened without attaching that statement silently to a different name.
- **Trade-off:** a public profile may show a current self-declared name alongside a different reviewed name. The interface must make the distinction prominent, and an old review does not establish that both names belong to the same person.

### L64 — A discoverable profile must keep its display name public

- **Choice:** sharing controls reject an attempt to make the display name private while the profile is published and discoverable. The member must make the whole profile private first.
- **Reason:** nurse discovery needs a stable visible identity, and publication already requires the display name to be public. Enforcing the same rule after publication closes the path that could leave a nameless discoverable profile.
- **Trade-off:** changing this one field takes an extra unpublish step. The service layer, not only the form, must enforce the rule.

### L65 — Community names are unique, reserved where necessary, and locked after contribution

- **Choice:** public community names have a normalised, case-insensitive unique key. Names representing Nurse.ng, NMCN (Nursing and Midwifery Council of Nigeria), staff, moderation, administration, or support are reserved. A member can choose or correct the name before contributing; the name locks when their first post or reply is published.
- **Reason:** the user selected unique and locked names. This prevents two active members from presenting the same community identity, prevents ordinary accounts from presenting themselves as the platform or regulator, and stops a later rename from retroactively changing the apparent author of existing conversations.
- **Trade-off:** uniqueness is not identity verification and cannot stop every real-person impersonation. A legitimate correction after the first contribution requires a future staff procedure; deleting content does not unlock the name.

### L66 — Initial permissive community limits

- **Choice:** each account may attempt up to 10 posts per hour, 60 replies per hour, and 20 reports per hour. Community uploads are limited to 500 MB in a 24-hour account window and 5 GB stored per account, in addition to the existing per-file and per-post limits.
- **Reason:** the user selected the permissive limit set. It leaves room for active participation while bounding straightforward spam, report flooding, and unbounded local-disk consumption.
- **Trade-off:** action counters remain process-local for the pilot, so multiple workers weaken them until distributed state is introduced. Database-backed byte accounting is stronger, but the limits are operational defaults rather than evidence that those volumes are affordable.

### L67 — Stream uploads, reserve quota, and reconcile media storage

- **Choice:** community uploads are copied to a private temporary file in bounded chunks rather than loaded into application memory. Account quota is reserved in the same database transaction as publication. Removing a reported post removes its media records, attempts to delete its files, and releases stored quota; an operator cleanup command reconciles orphan files and byte counters.
- **Reason:** a permitted 100 MB video must not allocate one equally large Python bytes object, and database or filesystem failures must not silently consume quota forever.
- **Trade-off:** local files and database rows still cannot form one atomic transaction. A crash between them can leave an orphan, so the reconciliation command remains necessary. Production object storage needs its own lifecycle and accounting controls.

### L68 — Optional ClamAV scanning for community media

- **Choice:** when the configured ClamAV (an antivirus scanner) command is available, every completed temporary community-media file is scanned before publication and a positive detection is rejected. If the scanner is absent, times out, or fails operationally, the optional pilot mode logs the condition and allows the upload.
- **Reason:** the user selected optional scanning so development and the pilot are not blocked on a system daemon while still using the scanner when installed.
- **Trade-off:** this is fail-open and is not sufficient for an unrestricted public launch. A production deployment must change to required, fail-closed scanning or use a storage processing pipeline that provides equivalent protection.

### L69 — Database identities close connection and report races

- **Choice:** every connection stores a canonical unordered pair key with a unique constraint, so reciprocal requests cannot coexist. Every open report stores a unique reporter/target key, cleared when the report is resolved or dismissed. Connection responses and moderation claims use conditional state updates so only the first concurrent action succeeds.
- **Reason:** application-level pre-insert checks do not protect against two requests that race. Stable database keys let the database remain the authority on uniqueness while preserving requester/recipient direction and the ability to report again after a dismissal.
- **Trade-off:** the extra projection keys must be backfilled and maintained by services. SQLite (an embedded Structured Query Language database) cannot reproduce every PostgreSQL locking behaviour, so PostgreSQL concurrency verification remains required before production.

---

## Implementation continuation — 2 November 2026

### L70 — Merge existing migration heads before adding the interface schema

- **Choice:** keep the community compatibility revision at its historical parent, make it a no-op because the hardening revision owns the overlapping columns, and explicitly merge the two heads. Add the account, professional-profile, job, application, and direct-message schema in a following revision.
- **Reason:** the existing database records both community heads. Reparenting an applied revision obscures that history and can strand upgrades. Both fresh databases and databases at the two recorded heads need an executable path to the current models.
- **Trade-off:** this repairs a historical duplicate-column branch with a compatibility marker. Downgrading that marker alone does not remove hardening-owned columns. Full migration and data-preservation checks use temporary databases before any local application upgrade.
- **Scope:** continuation of existing unfinished implementation, not a new product choice. Existing application consent, connection permissions, and private profile defaults remain the basis for regression checks.

### L71 — Preserve the boundaries of the inherited workspace features

- **Implementation observed and completed:** account names/contact details are separate from public community identities; nurse/employer/partner account selection does not grant staff access. Job applications require explicit contact-sharing consent and store a snapshot for the posting employer. Message reads and writes require an accepted connection and an active recipient. New professional fields remain subject to the existing private-by-default sharing controls.
- **Reason:** the unfinished interface already exposed these flows. Its completion needs functional routes, schema support, and tests that preserve who can see or change data.
- **Trade-offs:** messaging shows the latest 100 messages and requires a page reload for new replies; its sending throttle remains process-local. Job applications are a basic submission/status workflow. Learning uses external resource links, while events and social sign-in remain placeholders. These implementation records do not establish authoritative professional verification or production launch readiness.
- **Interface fixes:** restore explicit profile visibility and review-submission labels, link accepted connections to their conversations, and use neutral notification copy rather than an unimplemented unread-status claim. Mobile forms account for their margins; the keyboard skip link remains hidden until focused.

### L72 — Browser display preferences and accessible navigation

- **User direction:** implement dark mode and accessibility. Keep the existing signed-in routing behavior accepted in the preceding discussion.
- **Choice:** offer System (default), Light, and Dark appearance; larger text, higher contrast, and reduced motion are independent options. Respect operating-system motion preferences even when the additional reduction is off. Save only these presentation preferences in browser storage and apply them before rendering the page.
- **Reason:** visitors and members should be able to read and navigate the same pages comfortably, including login and registration. An early theme script avoids flashing a light page on a dark preference.
- **Trade-off:** preferences belong to this browser, not the account, and may be unavailable when browser storage is blocked. System preferences remain the fallback. These improvements are not a claim of full accessibility certification; uploaded community media still needs author-provided descriptions/captions in a future content workflow.
- **Implementation scope:** a native display-preferences dialog, stronger focus and contrast, accessible names for icon/upload controls, larger touch targets, keyboard-safe mobile navigation, reduced-motion/forced-color support, and browser checks for theme persistence and keyboard behavior.

---

## Implementation — 6 November 2026

### L73 — Enforce safe configuration before application startup (A01)

- **User direction:** start the recommended A01 implementation: safe production configuration, session-cookie protection, and host enforcement with regression checks.
- **Choice:** introduce an explicit `NURSE_NG_ENVIRONMENT` (`production` by default; `development` for local work). Production requires an operator-supplied signing key of at least 32 characters, explicit allowed hosts, disabled debug mode, and Secure cookies. Reject the known development keys. Development without a key uses a fresh cryptographically random key per process. Host restrictions apply in both modes; wildcard hosts are not accepted. SameSite=None requires Secure cookies in either mode.
- **Reason:** a missing setting must not silently enable a publicly known session-signing key. Configuration validation and the host middleware make the security boundary executable instead of relying on deployment comments.
- **Trade-offs:** existing local environments must explicitly select development and remove old placeholder keys. A generated development key invalidates sessions after restart and is unsuitable for multiple workers. Production workers must share a securely provisioned random key; length checks cannot establish its randomness. The repository cannot verify the configuration of an unprovided live deployment.
- **Scope:** this implements configuration safeguards. Session revocation (A06), trusted-proxy address configuration, staff MFA, and the remaining assessment items retain their separate scope. Implementation and verification progress are recorded in the work log and A01 tracker entry.
