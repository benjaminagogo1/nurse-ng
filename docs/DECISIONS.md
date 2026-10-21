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
- **Choice:** add `fastapi.Depends` and `fastapi.Form` to `extend-immutable-calls`.
- **Reason:** B008 (a Bugbear lint rule) forbids function calls in argument defaults; FastAPI dependency declarations are calls in defaults by design.
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
- **Trade-off:** there is no administrator or reviewer route to open another nurse's profile; such access needs a separate, authorised path with audit logging.

### L23 — Professional status is labelled self-declared
- **Choice:** the profile page shows the status with the words "(self-declared)" and the edit form says verification is not available yet.
- **Reason:** the verification domain does not exist; the product must not imply that an unverified value has been checked.
- **Trade-off:** the page is less persuasive than a badge would be, and this wording must be replaced with a verification receipt once decisions and evidence exist.

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
| O1 | Launch verification: document-based or source-confirmed | Open | Deferred by the user on 18 October 2026; the research has not started and the memo is required before the Phase 0 gate can close |
| O2 | Legal entity that operates the platform | Open | Needs counsel input; affects NDPA 2023 (Nigeria Data Protection Act 2023) controller registration and trust surface |
| O3 | Numeric pilot gates and cost-per-verified-profile target | Open | Requires ten timed manual cases before a target can be set |
| O4 | Evidence retention period and deletion schedule | Open | Needs counsel input for NDPA 2023 (Nigeria Data Protection Act 2023) |
| O5 | Whether the concierge pilot stores identity documents at all | Open | Depends on O1 and counsel advice; minimum-data option is registration number plus certificate image |

---

## Notes on this session

- Verification-source feasibility remains **unresearched**. The user deferred the research on 18 October 2026 in order to continue building; nothing here should be read as a finding about the NMCN (Nursing and Midwifery Council of Nigeria) or its services.
- The roadmap's Phase 4–6 (jobs, community, international mobility) remain out of scope and are not affected by these decisions.
- These decisions revise the build plan's assumptions; `BUILD_PLAN.md` itself has not been edited. A revision should be made once Phase 0 closes, not before.
