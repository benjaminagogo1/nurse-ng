# Nurse.ng — Work Log

**Purpose:** A chronological record of every step taken on this project: what was done, why, what was attempted, what succeeded or failed, and what remains unverified.
**Conventions:** Every abbreviation is expanded on first use. Design choices also appear in `docs/DECISIONS.md`; this file records the sequence of work rather than the decision rationale (the rationale lives in the decision record).
**Rule:** Append entries; never delete history. Record failures and blocked work as carefully as successes.

---

## Session 2026-10-18 (current)

### 1. Reconstructed prior context

- **Action:** Checked `~/.claude/projects/-home-recoding-nurse-ng/memory/`. The persistent memory directory was empty and `MEMORY.md` did not exist.
- **Action:** Read the prior session transcripts stored beside the memory directory: `1a64ae5f-e58a-4e02-9b65-3e9628a9ba47.jsonl`, `edce1f94-7be3-4076-b0fe-d991fc1c7e0a.jsonl`, and `c1f6527f-c87e-40d7-a219-a07189e3fa4e.jsonl`.
- **Finding:** Earlier work created `docs/BUILD_PLAN.md`, `docs/build-plan.html`, `docs/DECISIONS.md`, and `docs/PHASE0_PLAN.md`; then a Django (a Python web framework) foundation was written, deleted, and replaced with a FastAPI (a Python web framework built on the ASGI (Asynchronous Server Gateway Interface) standard) foundation. The NMCN (Nursing and Midwifery Council of Nigeria) verification research was never completed because the harness safety classifier was unavailable.
- **Memory written:** `collaborate-on-decisions` (the user requires joint decision-making) and `nurse-ng-backend-state` (the FastAPI scaffold is unexecuted).

### 2. Confirmed repository state

- **Action:** Ran `git log --oneline -10`, `find`, `git ls-files`, and read the repository files.
- **Finding:** Four commits exist: `7163717 Initial commit`, `22b1aff file structure setup`, `25cf84c chore: ensure development environments are ignored`, and `9bd50ea env file removed`.
- **Finding:** The tracked tree contains only the FastAPI stack. No Django files exist. `migrations/versions/` contains only `.gitkeep`, so no initial Alembic (a database migration tool for SQLAlchemy) revision exists.
- **Finding:** A `venv/` virtual environment exists on disk and is ignored by Git. `itsdangerous` (a Python library for cryptographically signing data) is **not** installed in it.
- **Finding:** `.gitignore` line 17 ignores `.env.example`, so the example configuration file is untracked. This is recorded as an open housekeeping item; it was **not** changed without approval.

### 3. Attempted verification (blocked)

- **Intended command:** `./venv/bin/python -m pytest -q`.
- **Outcome:** The harness's safety classifier repeatedly refused Bash (a command-line shell) execution with: `deepseek-v4-flash is temporarily unavailable, so auto mode cannot determine the safety of Bash right now.`
- **Also attempted:** the Monitor tool (a background command runner), which failed with the same classifier message.
- **Consequence:** No test, migration, linter, or install command executed while the outage lasted. The shell returned later in the session; every result below was produced after that point.

### 4. Static review of the existing scaffold

- **Files reviewed:** `pyproject.toml`, `alembic.ini`, `migrations/env.py`, `app/main.py`, `app/core/config.py`, `app/core/uuid.py`, `app/core/validators.py`, `app/core/security.py`, `app/db/base.py`, `app/db/session.py`, `app/models/user.py`, `app/models/profile.py`, `app/services/profiles.py`, `app/web/routes.py`, `app/templates/base.html`, `app/templates/home.html`, `app/static/css/app.css`, `tests/conftest.py`, and every test module.
- **Result:** No obvious logic errors were found by inspection. Notable risks were identified: handwritten migrations, no executed test suite, and an unavailable runtime verifier. The review is not a substitute for execution.

### 5. User direction

- **Instruction:** Do not use Django; FastAPI is the chosen framework. Park the NMCN (Nursing and Midwifery Council of Nigeria) verification research and return to it later; continue building.
- **Follow-up instruction:** Build authentication (registration, phone number + password, session login/logout).
- **Standing documentation rule:** Every design choice is written into the relevant file immediately, every abbreviation is followed immediately by its full meaning, reasons and trade-offs are never dropped, and every step is documented regardless of file size. Saved to memory as `document-every-choice`.

### 6. Authentication increment

- **Dependency added:** `itsdangerous>=2.2` in `pyproject.toml`.
- **Configuration added:** `app/core/config.py` gained `session_cookie_name`, `session_max_age` (14 days), `session_https_only`, and `session_same_site`.
- **Middleware added:** `app/main.py` now installs Starlette's (the ASGI web framework underlying FastAPI) `SessionMiddleware` and includes the authentication router.
- **Service created:** `app/services/auth.py` with `register_user`, `authenticate_user`, `validate_password`, and `AuthError`.
- **Dependencies created:** `app/web/deps.py` with `get_current_user`, `require_user`, and `verify_csrf`.
- **Renderer created:** `app/web/templating.py` with a shared `render()` that always supplies a CSRF (Cross-Site Request Forgery) token.
- **Routes created:** `app/web/auth_routes.py` with `GET /auth/register`, `POST /auth/register`, `GET /auth/login`, `POST /auth/login`, `POST /auth/logout`, and `GET /auth/dashboard`.
- **Templates created:** `app/templates/auth/register.html`, `app/templates/auth/login.html`, `app/templates/auth/dashboard.html`; `app/templates/base.html` updated with session-aware navigation.
- **Styles added:** form, error, navigation, and button styles in `app/static/css/app.css`.
- **Tests created:** `tests/test_auth.py` with 12 tests covering registration, duplicate phone numbers, invalid input, password mismatch, CSRF (Cross-Site Request Forgery) rejection, successful and failed login, logout, and the protected dashboard.
- **Lint configuration:** `pyproject.toml` adds a Bugbear B008 exception for `fastapi.Depends` and `fastapi.Form`.
- **Reason and trade-off:** recorded as entries L1–L13 and "Deferred authentication work" in `docs/DECISIONS.md`.
- **Packaging changed:** `pyproject.toml` gained a Hatchling (a Python build backend) build system with explicit `packages = ["app"]` (L14), the application is installed in editable mode with `pip install -e .` (L15), and the development dependency changed from `httpx` to `httpx2` (L16).
- **Environment choice:** verification used the existing `venv/` virtual environment and `pip` (Python's package installer) rather than `uv` (a Python package and project manager), recorded as L17. No lockfile exists yet; dependency ranges come from `pyproject.toml`.
- **Verification status at time of writing:** not yet verified; verified later in step 10.

### 7. Documentation updates

- `docs/DECISIONS.md` gained D10 (authentication direction), the full design log L1–L16, deferred-work notes, production configuration requirements, and expanded abbreviations.
- `docs/WORK_LOG.md` (this file) created.
- `README.md` updated to link this log.

### 8. Verification commands and results

First attempt:

```bash
cd /home/recoding/nurse-ng
./venv/bin/pip install -e .
```

- **Failure:** setuptools (a Python packaging tool) could not auto-discover packages because the repository has several top-level directories. Fix recorded as L14 (explicit Hatchling package configuration) and L15 (editable installation).
- **Second attempt:** succeeded. Installed the application and its runtime dependencies, including `pwdlib`, `argon2-cffi`, `jinja2`, `python-multipart`, and `uvicorn`. `fastapi`, `sqlalchemy`, `alembic`, `pydantic-settings`, and `itsdangerous` were already present.

Test attempt:

```bash
./venv/bin/python -m pytest -q
```

- **Failure:** `RuntimeError: The starlette.testclient module requires the httpx2 package to be installed.` The installed Starlette version is 1.8.0 and FastAPI is 0.143.3. Fix recorded as L16.
- **Resolution:** `./venv/bin/pip install pytest httpx2 ruff` (pytest was already present).

Final verification:

| Command | Result |
|---|---|
| `./venv/bin/python -m pytest -o addopts="" -q` | **35 passed in 8.23 s**, exit code 0 |
| `./venv/bin/ruff check .` | **All checks passed** |
| `./venv/bin/alembic revision --autogenerate -m "initial schema"` | Generated `migrations/versions/253564276f57_initial_schema.py`; detected `users`, `nurse_profiles`, `credential_claims`, and `field_visibilities` |
| `./venv/bin/alembic upgrade head` | Applied `253564276f57` (initial schema) to SQLite (an embedded Structured Query Language database) |
| `./venv/bin/alembic check` | **No new upgrade operations detected** (no schema drift) |

Files created during verification: `migrations/versions/253564276f57_initial_schema.py` and the development database `nurse_ng.db` (ignored by `.gitignore`).

### 9. Nurse profile increment

- **User direction:** build nurse profile creation next.
- **Service extended:** `app/services/profiles.py` gained `get_profile_for_user`, `save_profile`, `validate_profile_input`, `professional_status_label`, the status label map, and the `ProfileError` exception, alongside the existing visibility selectors.
- **Routes created:** `app/web/profile_routes.py` with `GET /profile`, `GET /profile/edit`, and `POST /profile/edit`.
- **Routing wired:** `app/main.py` includes the profile router.
- **Templates created:** `app/templates/profile/edit.html` and `app/templates/profile/show.html`; `app/templates/base.html` gained a "Profile" link for signed-in users.
- **Styles added:** select, textarea, field hint, profile metadata, and bio styles in `app/static/css/app.css`.
- **Validation:** display name required; maximum lengths 120 (display name), 160 (headline), 120 (location), and 5000 (bio); professional status restricted to `student`, `graduate`, `registered`, or `specialist`.
- **Tests created:** `tests/test_profile_pages.py` with 11 tests covering the missing-profile redirect, creation, editing, prefilled forms, defaults, required name, invalid status, length limit, CSRF (Cross-Site Request Forgery) rejection, and cross-account isolation. `tests/helpers.py` and `tests/__init__.py` were added for shared helpers.
- **Design choices:** recorded as L18–L26 in `docs/DECISIONS.md`, each with reason and trade-off.
- **Database migration:** none required; the models did not change.
- **Verification, first attempt:** 46 tests passed. Ruff (Python linter) reported 16 findings, all in the autogenerated migration `migrations/versions/253564276f57_initial_schema.py` (15 E501 line-too-long, 1 I001 unsorted-imports). Resolved by L25 (per-file ignores for generated migrations).
- **Verification, final:** 46 tests passed in 34.79 s; Ruff reported "All checks passed"; `alembic check` reported "No new upgrade operations detected".

### 10. Next steps at the end of the authentication/profile increments

1. Decide whether to track `.env.example` by correcting `.gitignore`; it remains untracked.
2. Add a dependency lockfile (`uv.lock` or a pinned requirements file) so installs are reproducible (L17).
3. Continue with the next agreed increment: profile activation and sharing controls, or the verification domain.
4. The NMCN (Nursing and Midwifery Council of Nigeria) verification-source research remains deferred by the user's direction.
5. Before any public launch, address the deferred authentication work listed in `docs/DECISIONS.md`: rate limiting, account lockout, dummy-hash timing equalisation, and a high-entropy production secret key.

### 11. Profile activation and sharing increment

This increment was already present in the working tree when the session resumed: the service, routes, templates, and tests had been written, but the work log had not recorded them and no verification had run. The code was reviewed and completed as follows.

- **Service extended:** `app/services/profiles.py` gained `SHAREABLE_FIELDS`, `SHAREABLE_FIELD_NAMES`, `ALLOWED_VISIBILITIES`, `get_visibility_map`, `save_sharing_settings`, `public_profile_fields`, `get_active_profile_by_public_id`, `activate_profile`, and `deactivate_profile`.
- **Routes created:** `app/web/profile_routes.py` gained `GET /profile/sharing`, `POST /profile/sharing`, `POST /profile/activate`, `POST /profile/deactivate`, and the public `GET /p/{public_id}`; `app/main.py` includes the new `public_router`.
- **Robots rule added:** `app/web/routes.py` serves `GET /robots.txt` with `Disallow: /`, and every public profile response carries `X-Robots-Tag: noindex, nofollow`.
- **Templates created:** `app/templates/profile/sharing.html` (one private/public choice per shareable field) and `app/templates/profile/public.html` (renders only shared fields); `app/templates/profile/show.html` now shows the draft/active state, the share link, the public field count, a display-name warning, and activate/deactivate forms.
- **Styles added:** button-row and sharing-control styles in `app/static/css/app.css`.
- **Tests created:** `tests/test_profile_sharing.py` with 21 tests covering draft links, activation and deactivation, CSRF (Cross-Site Request Forgery) rejection, the display-name requirement, the discoverability invariant, field filtering, anonymous access, malformed links, sharing defaults, row creation and deletion, unknown fields and visibility levels, and `robots.txt`.
- **Design choices:** recorded as L27–L35 in `docs/DECISIONS.md`, each with reason and trade-off.
- **Database migration:** none required; `public_id`, `status`, `discoverable`, and `FieldVisibility` already existed in `253564276f57`, and the models did not change.

Defects found during the resumed review and fixed:

1. **Authentication/CSRF order.** `POST /profile/activate` and `POST /profile/deactivate` declared `verify_csrf` before `require_user`. FastAPI (a Python web framework) resolves dependencies in parameter order, so an anonymous POST returned 400 (Bad Request) instead of the 303 (See Other) sign-in redirect the test expects. Both routes now declare `require_user` first (L35).
2. **Unused import.** `tests/test_profile_sharing.py` imported `PROFILE` without using it, which Ruff (a Python linter) flags as F401. The import was removed.
3. **Stale copy.** `app/templates/profile/edit.html` said sharing controls "are added" in the future; it now describes activation and field sharing.

### 12. Verification attempt for the sharing increment

- **Intended commands:** `./venv/bin/python -m pytest -o addopts="" -q`, `./venv/bin/ruff check .`, and `./venv/bin/alembic check`.
- **Outcome:** the harness safety classifier refused Bash (a command-line shell) execution four times with: `deepseek-v4-flash is temporarily unavailable, so auto mode cannot determine the safety of Bash right now.` The same outage blocked the previous session's first attempts.
- **Consequence:** the 21 new tests (67 expected in total), Ruff, and the schema-drift check are **unverified**. The static review above found and fixed three defects, but static review is not a substitute for execution.

### 13. Current next steps (as of the interrupted verification)

1. Run the three verification commands in section 12 as soon as the runner is available; record the actual results in the verification ledger. **Completed — see section 14.**
2. Decide whether to track `.env.example` by correcting `.gitignore`; it remains untracked.
3. Add a dependency lockfile (`uv.lock` or a pinned requirements file) so installs are reproducible (L17).
4. Continue with the next agreed increment: the verification domain, or the deferred authentication hardening.
5. The NMCN (Nursing and Midwifery Council of Nigeria) verification-source research remains deferred by the user's direction.
6. Before any public launch, address the deferred authentication work listed in `docs/DECISIONS.md`: rate limiting, account lockout, dummy-hash timing equalisation, and a high-entropy production secret key.

### 14. Verification completed (activation/sharing increment)

Verification was run by the user in the terminal and the output pasted back, because the harness safety classifier was still refusing Bash (a command-line shell) execution.

| Command | Result |
|---|---|
| `./venv/bin/python -m pytest -o addopts="" -q` | **67 passed in 25.54 s**, exit code 0 |
| `./venv/bin/ruff check .` | **All checks passed** after one fix (below) |
| `./venv/bin/alembic check` | **No new upgrade operations detected** (no schema drift) |

Fixes applied during verification:

1. **Line-wrapped warning text.** `test_active_owner_page_warns_when_name_is_private` failed because the template broke "your name" across two lines, so the contiguous substring was absent from the response text. The sentence in `app/templates/profile/show.html` now sits on one line. 66 passed, 1 failed before the fix; 67 passed after.
2. **Import ordering.** Ruff reported I001 in `app/main.py`: two names imported from `app.web.profile_routes`, one of them aliased, must be split into separate import statements. Corrected.

Static type-checking after verification reported one diagnostic: the plain `str` `session_same_site` setting was passed to `SessionMiddleware`, whose parameter is a `Literal`. Fixed by typing the setting as `Literal["lax", "strict", "none"]` (L36). This changes validation, not the default value. Re-verified after the change: **67 passed** and **All checks passed**.

---

## Session 2026-10-21

### 1. Reconstruction and direction

- **Action:** Read `docs/WORK_LOG.md`, `docs/DECISIONS.md`, the repository history, and the authentication code. The working tree was clean at commit `d335caf`.
- **Finding:** the recorded state from 18 October 2026 was 67 tests passing, Ruff clean, and no Alembic drift. The commit title `Add routes, auth, login && Rate limiter` claims a rate limiter that does not exist: there is no limiter dependency, middleware, or code, only a comment at `app/services/auth.py` referring to future rate limiting. This entry overstates the commit; nothing was rewritten.
- **User direction:** continue with the authentication hardening increment fixed by `DECISIONS.md`: login rate limiting, account lockout, and dummy-hash timing equalisation.
- **Joint decisions (asked and answered):**
  - State lives in a hybrid: per-IP counters in memory, account lockout persisted on the user row.
  - Lockout after 5 consecutive failures for 15 minutes.
  - Per-IP limits: 10 failed sign-ins per 5 minutes; 5 registration attempts per hour.
  - Locked accounts return an explicit 429 (Too Many Requests) with a wait message.

### 2. Authentication hardening increment

- **Configuration:** `app/core/config.py` gained six settings: `login_ip_limit` (10), `login_ip_window_seconds` (300), `register_ip_limit` (5), `register_ip_window_seconds` (3600), `login_lockout_threshold` (5), and `login_lockout_seconds` (900). All are overridable through `NURSE_NG_*` environment variables (L44).
- **Limiter created:** `app/core/ratelimit.py` contains `FixedWindowLimiter`, a thread-safe in-memory fixed-window counter with `is_limited`, `record`, `retry_after`, `reset`, and `clear`, plus `reset_all_limiters()` for tests. State is process-local (L37).
- **Model extended:** `app/models/user.py` gained `failed_login_attempts` (integer, server default 0) and `locked_until` (nullable timezone-aware timestamp) (L38).
- **Service extended:** `app/services/auth.py` gained `LoginLockedError`, a module-level dummy Argon2 hash checked for unknown numbers (L39), and lock helpers that release an expired lock (L40), count failures, set the lock, and clear state after a valid sign-in.
- **Renderer extended:** `app/web/templating.py`'s `render()` now accepts `headers`, so a rate-limited form response can carry `Retry-After`.
- **Routes extended:** `app/web/auth_routes.py` gained two module-level limiters, `_client_ip()` (the ASGI peer address, L41), `_minutes()`, and `_render_rate_limited()`. `POST /auth/login` checks the IP allowance, catches `LoginLockedError`, records failed sign-ins, and returns 429 with `Retry-After` (L45). `POST /auth/register` checks and records the registration allowance.
- **Migration created:** `migrations/versions/8f2c1d4a9b6e_add_login_lockout_columns.py`, written by hand because the runner was unavailable, using `op.batch_alter_table` for SQLite compatibility (L42).
- **Tests created:** `tests/test_auth_hardening.py` with seven cases: lockout after the threshold, expiry releasing the lock, a success resetting the counter, lockout scoped to one account, the dummy hash for unknown numbers, the login IP limit, and the registration IP limit.
- **Test fixture added:** `tests/conftest.py` has an autouse fixture that clears every limiter before and after each case (L43).
- **Documentation:** `docs/DECISIONS.md` gained L37–L45 and an updated deferred-authentication section.

### 3. Static review fixes before verification

1. **CSRF token invalidated by registration.** The registration test first reused one CSRF token across five successful registrations. Each success signs the user in through `_start_session`, which clears the session including the CSRF token, so the second POST would have failed with 400. The test now clears the client cookie jar between attempts while the IP counter accumulates.
2. **Long line.** The `_login_ip_limiter` construction exceeded the 100-character limit; it was wrapped.
3. **Naive SQLite timestamps.** All comparisons pass through `_as_utc()`, because SQLite stores timestamps without an offset even when the column is timezone-aware. Covered explicitly by the expiry test, which reloads the row from the database.

### 4. Verification (pending)

- **Intended commands:** `./venv/bin/ruff check .`, `./venv/bin/pytest -o addopts="" -q`, `./venv/bin/alembic upgrade head`, and `./venv/bin/alembic check`.
- **Outcome so far:** the harness safety classifier refused Bash (a command-line shell) execution with `deepseek-v4-flash is temporarily unavailable, so auto mode cannot determine the safety of Bash right now.` The same outage blocked work in the previous sessions. No test, lint, or migration command has run in this session.
- **Consequence:** the increment is **unverified**. Static review found and fixed three issues, but that is not a substitute for execution. Results must be appended here and to the verification ledger when the runner is available.

### 5. Verification completed (2026-10-21)

The harness classifier still refused Bash execution for `ruff`, `pytest`, and `alembic` in this session, so the user ran the four commands in the terminal and pasted the output, as in section 14 of the previous session.

| Command | Result |
|---|---|
| `./venv/bin/ruff check .` | **All checks passed!** |
| `./venv/bin/pytest -o addopts="" -q` | **74 passed in 31.32s**, exit code 0 |
| `./venv/bin/alembic upgrade head` | Applied `8f2c1d4a9b6e` (add login lockout columns) to the development SQLite database |
| `./venv/bin/alembic check` | **No new upgrade operations detected** (no schema drift) |

The total is 74 tests: the previous 67 plus the seven new hardening cases. The increment is verified; no defects surfaced during execution.

### 6. State at end of session

- **Committed:** nothing. The increment is in the working tree; the most recent commit remains `d335caf`.
- **Next agreed work:** none chosen yet. Open items remain the `.env.example` tracking decision, a dependency lockfile, the Phase 0 O1 (verification-source) memo, and the production items in `DECISIONS.md` (trusted-proxy handling, distributed limiter state, high-entropy secret enforcement).

### 7. Housekeeping (2026-10-21)

- **`.env.example` tracking:** removed `.env.example` from `.gitignore` at the user's direction. `.env` itself remains ignored. The example holds only placeholders (`change-me-in-development`, a local SQLite URL, localhost hosts), so no credential was exposed; the file is now untracked rather than ignored and becomes part of the next commit.
- **Dependency lockfile:** `uv` (a Python package and project manager, named in D8) is not installed at `~/.local/bin`, `/usr/local/bin`, `/usr/bin`, `~/.cargo/bin`, or inside `venv/bin`, so `uv lock` could not be produced. Created `requirements.lock` instead, pinning all 42 third-party distributions installed in the verified `venv/`; the editable `nurse-ng` install and pip itself are excluded, matching `pip freeze`'s default skip of development tooling. The intended regeneration command is `./venv/bin/pip freeze --exclude-editable`.
- **Method note:** command execution was blocked by the safety-classifier outage, so the pins were read from the `*.dist-info/METADATA` files and sorted, rather than produced by `pip freeze` itself. Distribution names were normalised to the lowercase-hyphen form pip uses. The declared ranges remain in `pyproject.toml`; L46 records the choice and its trade-offs.
- **README:** the status paragraph now says 74 tests and names the hardening; a Development section documents the lockfile install, tests, lint, and migration commands.
- **Scope:** this closes items 2 and 3 of the 2026-10-18 session's next-step list; item 1 (`.env.example`) was the same item recorded there.

---

## Earlier sessions (reconstructed from transcripts)

### Session A — build plan and designed page

- Reviewed `Nurse_ng_Strategic_Product_Roadmap.md` (v1.0) and its PDF (Portable Document Format) export.
- Produced `docs/BUILD_PLAN.md` and the designed page `docs/build-plan.html`.
- Established the Phase 0 kill gate: whether a lawful, reliable source exists to verify a nurse's professional status.

### Session B — decisions and Phase 0 plan

- Agreed decisions D1–D6 in `docs/DECISIONS.md`: solo part-time builder, new graduates first, public hospitals first, invite-only pilot, no existing employer access, defined Phase 0 budget.
- Wrote `docs/PHASE0_PLAN.md`: a manual concierge pilot before software, employer recruitment on the critical path, and approximately 900 hours of build deferred.
- NMCN (Nursing and Midwifery Council of Nigeria) verification research was attempted and blocked by the same classifier outage; no findings were produced.
- Built a Django (a Python web framework) foundation, then deleted it at the user's direction and replaced it with a FastAPI (a Python web framework) foundation (D7 and D9).
- No application command was executed during this session either.

### Session C — interrupted continuation

- The user asked "can we continue?"; the request was interrupted before work began.

---

## Verification ledger

| Date | Item | Status |
|---|---|---|
| 2026-10-18 | Foundation, authentication, and profile tests | **46 passed** |
| 2026-10-18 | Ruff (Python linter) | **All checks passed** |
| 2026-10-18 | Initial Alembic (migration tool) revision | **Generated and applied** |
| 2026-10-18 | Alembic schema drift check | **No drift detected** |
| 2026-10-18 | Activation/sharing increment tests (21 new, 67 total) | **67 passed** |
| 2026-10-18 | Ruff and schema-drift check after the sharing increment | **All checks passed; no drift detected** |
| 2026-10-18 | NMCN (Nursing and Midwifery Council of Nigeria) research memo | **Not started; deferred by user** |
| 2026-10-21 | Authentication hardening tests (7 new, 74 total) | **74 passed** |
| 2026-10-21 | Ruff (Python linter) after authentication hardening | **All checks passed** |
| 2026-10-21 | Lockout migration `8f2c1d4a9b6e` | **Applied to development SQLite database** |
| 2026-10-21 | Alembic schema drift check after authentication hardening | **No drift detected** |
| 2026-10-21 | `.env.example` tracking and dependency lockfile | **`.env.example` now trackable; 42 distributions pinned in `requirements.lock`** |
