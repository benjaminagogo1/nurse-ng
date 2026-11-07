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

### 8. O1 verification-source memo (blocked, protocol drafted)

- **User direction:** work on the O1 decision memo (launch verification: document-based or source-confirmed), the Phase 0 kill gate.
- **Sources read:** `docs/PHASE0_PLAN.md` (workstream P1, kill criteria K1 and K3), `docs/BUILD_PLAN.md` review item 1, and the roadmap's verification taxonomy (§9).
- **Attempted research:** three `WebSearch` queries and one direct `WebFetch` of the NMCN (Nursing and Midwifery Council of Nigeria) site. Every call was refused with `deepseek-v4-flash is temporarily unavailable, so auto mode cannot determine the safety of WebSearch/WebFetch right now.` No page was retrieved and no access date exists.
- **Action taken:** wrote `docs/O1_VERIFICATION_SOURCE_MEMO.md` as an explicit **draft research protocol**, not a memo with findings. It defines the evidence standard, six candidate routes to test (R1–R6) phrased as hypotheses, the evidence required per route, an empty evaluation matrix, the cost model, the counsel checklist, the K1/K3 mapping, and the three decision options (source-confirmed, document-only downgraded, stop).
- **Deliberate omission:** no claim about NMCN services is stated as fact. The previous sessions recorded the same outage; inventing findings would manufacture the certainty the gate exists to test.
- **Gate status:** O1 remains **open**. `docs/DECISIONS.md` O1 and the README document list now point to the draft.
- **Next action:** rerun the searches when web tooling is restored, record primary sources with access dates in section 10 of the memo, and only then complete the matrix and choose a decision.

### 9. Document-review workflow (2026-10-21)

- **User direction:** "We review the licence/certificate plus identity, label every profile 'document reviewed'. Can you implement this?" Follow-up choices: certificate plus government-issued ID; a staff web review queue; keep all evidence with access auditing.
- **Scope chosen:** the downgraded label only. No NMCN (Nursing and Midwifery Council of Nigeria) register is consulted, no authenticity is asserted, and no competence is assessed. The O1 gate stays open; the memo records this as a provisional implementation, not a decision (O1 section 9).
- **Domain model (`app/models/verification.py`):** `VerificationCase` (one profile, registration number, status `pending`/`approved`/`rejected`, decider, decision time, note), `EvidenceDocument` (kind `licence` or `government_id`, opaque storage name, sniffed content type, size, SHA-256), and `EvidenceAccess` (one row per evidence open). `NurseProfile.document_reviewed_at` carries the public label date. Cascades delete evidence rows with a case; reviewer foreign keys use `SET NULL` so a deleted staff account does not erase the record of a decision.
- **Private storage (`app/core/storage.py`):** files live under `NURSE_NG_EVIDENCE_DIR` (default `evidence/`, now gitignored), outside the static tree, with UUID4 hexadecimal names. Validation is by magic bytes (JPEG, PNG, PDF), not declared type or filename. Each file is capped at 5 MB (`NURSE_NG_EVIDENCE_MAX_BYTES`), hashed, and written atomically; the directory is created with mode `0700` and each file set to `0600`, and a write failure removes the temporary file and returns a form error. Path resolution rejects anything that is not an opaque name under the root.
- **Service (`app/services/verification.py`):** one pending case per profile; both files must store or the first is deleted; a failed commit removes stored files; a decision requires a pending case; rejection requires a note; approval moves `document_reviewed_at` forward; a reviewer cannot decide their own case; decisions are final and a resubmission is a new case.
- **Routes:** `GET/POST /profile/verification` (submit with consent, history), `GET /review` (queue and recent decisions), `GET /review/{case_id}`, `GET /review/{case_id}/evidence/{evidence_id}` (private download plus audit row), and `POST /review/{case_id}/decide`. All review routes require `is_staff`; anonymous requests are redirected to sign-in and signed-in non-staff receive 403 (Forbidden).
- **Staff provisioning (`app/cli.py`):** `python -m app.cli set-staff <phone>` and `unset-staff`. No web route grants the flag.
- **Consent:** the submission form requires an explicit checkbox, checked again on the server. It states that documents are stored privately and inspected by a reviewer. The registration number is reviewer-only and never published.
- **Templates:** `profile/verification.html`, `review/queue.html`, `review/case.html`; updates to `profile/public.html` (badge plus receipt), `profile/show.html` (status and link), `profile/edit.html` (status remains self-declared; links to review), and `base.html` (Verification link; Review link for staff).
- **Copy boundary:** the public receipt says what was inspected, the review date, and that this is not source confirmation — no NMCN register check, no authenticity proof, no competence assessment. The footer distinguishes reviewed from unreviewed profiles. Production and counsel review of this wording is still required (L47, L52).
- **Migration:** `c4e7a1b9d2f3_add_document_review.py` adds `nurse_profiles.document_reviewed_at` through batch alter and creates `verification_cases`, `evidence_documents`, and `evidence_accesses` with their indexes and cascades.
- **Tests (`tests/test_verification.py`):** 15 cases covering sign-in, private storage and sniffed types, PDF acceptance, unsupported and oversized files, consent, CSRF, one pending case, staff-only queue, approval label and public receipt, self-review refusal, rejection note, evidence access audit, cross-account history isolation, and service-level ownership. Evidence is redirected to a `tmp_path` directory so the repository store is untouched.
- **Decisions recorded:** L47 (label and receipt), L48 (storage and validation), L49 (staff-only access and audit), L50 (consent and registration-number boundary), L51 (one pending case, no self-review, final decisions), L52 (badge accompanied by receipt). L13, L22, and L23 were amended where the new workflow changed their wording; O4 and O5 status notes were updated.
- **Verification (2026-10-21, user-pasted terminal output):** the first run found two unused imports in `app/models/verification.py` (`sqlalchemy.Uuid` and the type-only `User`); both were removed. The rerun was clean: `ruff check .` reported "All checks passed!"; `pytest -q` reported **89 passed** (74 existing plus 15 new); `alembic upgrade head` applied `8f2c1d4a9b6e -> c4e7a1b9d2f3`; and `alembic check` reported "No new upgrade operations detected."
- **Deliberate exclusions:** no malware scanning, encryption at rest, object storage, retention/deletion job, appeal route, consent withdrawal, or versioned consent record. These are recorded in L48, L50, L51, and the deferred verification list; the store is pilot-grade only.

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

### 5. Final verification: schema fix, both migration branches, and shared test baseline

The pre-hardening baseline of 103 tests and a clean alembic history failed to
close because the multiple-head revision `a1b2c3d4e5f6` (added in commit
`92745ab` "update plan.md & decision.md") tried to add `community_name_key`, which
`d7a9e3f5b1c2` had never added — so the first branch upgrade hit
`duplicate column name: community_name_key`. The `a1b2` migration was rewritten as
defensive against existing columns (both PRAGMA and information_schema fallbacks),
and then applied via `alembic upgrade a1b2c3d4e5f6`. The second branch
`e8f1a2b3c4d5` (commit `2784d9c`, UI/UX redesign) was applied next. After both
branches converged the database reached head `e8f1a2b3c4d5` and no drift remained.

| Command | Result |
|---|---|
| `./venv/bin/alembic upgrade a1b2c3d4e5f6` | Add missing columns defensively (skipped if present); ran on already-upgraded DB without error |
| `./venv/bin/alembic upgrade e8f1a2b3c4d5` | Applied harden community trust revision |
| `./venv/bin/alembic check` | **No new upgrade operations detected** (no schema drift) |
| `./venv/bin/ruff check .` | **All checks passed** |
| `./venv/bin/python -m pytest -o addopts='' -q` | **104 passed in 44.64 seconds** |

This is the current verified baseline. Both the previously known 89-test case set
and the 14 community cases are covered, plus one login-probe test module added on
29 October 2026 while the harness was down.

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
| 2026-10-21 | Document-review tests (15 new, 89 total) | **89 passed** |
| 2026-10-21 | Ruff (Python linter) after document review | **All checks passed** |
| 2026-10-21 | Document-review migration `c4e7a1b9d2f3` | **Applied to development SQLite database** |
| 2026-10-21 | Alembic schema drift check after document review | **No drift detected** |
| 2026-10-28 | Pre-hardening baseline with separate community + hardening branches | **103 passed; ruff clean** |
| 2026-10-29 | Schema fix for the duplicate column head; both branches applied; probe test module added | **104 passed; ruff clean; no drift** |

---

## Session 2026-10-26

### 1. Initial repository inspection and scope correction

- **User request:** inspect the repository.
- **Reads:** repository structure, existing working-tree changes, project configuration, authentication, profile sharing, document review, tests, migrations, and selected planning documents. The working tree already contained modified and untracked files, and `main` was one commit ahead of and one behind `origin/main`; those changes were preserved.
- **Checks started:** `./venv/bin/ruff check .`, `./venv/bin/pip check`, and `./venv/bin/pytest -o addopts='' -q`.
- **Results:** Ruff reported "All checks passed!"; the dependency check reported "No broken requirements found", with a warning that the default pip cache directory was not writable. The test run produced no completed suite result and was interrupted with exit code 130 when the user raised a concern about work proceeding without consent. No new passing-test count was established.
- **Temporary migration check:** all three revisions upgraded successfully in an isolated database under `/tmp`; `alembic check` reported no new upgrade operations, and downgrading that temporary database to the base revision succeeded. The application database was not used for these checks.
- **Temporary service reproductions:** an approved profile retained its review date after a display-name change; two sessions that had loaded a pending case allowed a later rejection to overwrite an approval; and two simultaneous submissions created two pending cases. The latter two limitations are already recorded as accepted pilot trade-offs in L51. Development session defaults were also inspected. The reproductions used temporary database and evidence directories under `/tmp`; no application source fixes were made.
- **User concern and correction:** the user asked why implementation was occurring without consent. The assistant stopped the running checks, confirmed that the existing source-file changes and diff summary were unchanged, explained the temporary checks, and committed to reading rather than running further application checks or changing implementation without authorisation.

### 2. Full reading of the project record

- **User direction:** read the work log, decision record, project roadmap, and guidelines carefully before proceeding.
- **Documents read in full:** `docs/WORK_LOG.md`, `docs/DECISIONS.md`, `Nurse_ng_Strategic_Product_Roadmap.md`, `docs/BUILD_PLAN.md`, `docs/PHASE0_PLAN.md`, `docs/O1_VERIFICATION_SOURCE_MEMO.md`, and `README.md`.
- **Guidelines located:** the working agreement is recorded in the planning documents; no standalone repository `AGENTS.md` or `CLAUDE.md` was found. The work log records joint decision-making, immediate documentation of every step and choice, reasons and trade-offs, expanded abbreviations, and preservation of history.
- **Understanding confirmed:** FastAPI supersedes the earlier Django proposal; the current document-review workflow supports the downgraded label only; the latest historical verification remains 89 passing tests on 21 October 2026; and the source memo and Phase 0 gate remain open.
- **Scope during this reading:** file reading only, with no application tests, migrations, or implementation scripts run.

### 3. User-proposed adoption strategy

- **Proposal:** make enrolment more flexible and permissive, allow registration without professional verification, remove the invite-only launch model, offer public profiles, and introduce verification gradually while people experience interaction with like-minded members.
- **Clarification selected:** publication is a simple owner choice, rather than automatic publication. Profiles stay private until the member chooses "Make public".
- **Existing behaviour noted:** registration and profile sharing already work without document review in the current application. Open community discovery and interaction change the intended product direction and add features beyond that existing behaviour.
- **Working process reaffirmed by the user:** the assistant comes up with suggestions and options, explains a recommendation, and asks the user to choose. An initial ambiguous "yes" about community features was clarified before being recorded as a choice.

### 4. Community choices selected

| Question | User choice | Reason and trade-off record |
|---|---|---|
| Which community experiences? | All three: topic discussions, a public feed, and finding and connecting with other nurses | D12, L55 |
| How do members connect? | Both accepted connection requests and immediate following of public updates | L56 |
| Who reads and contributes? | Anyone can read the feed and topic discussions; registered members sign in to post and reply | D13, L57 |
| How do topics and the feed relate? | A topic post also appears in the public feed, with the same conversation and replies in both places | L58 |

### 5. Documentation of the approved direction

- **Decision record:** appended D11–D13 and L53–L58, including the user's option selections, their reasons and trade-offs, the reaffirmed working agreement, and the effect on earlier decisions.
- **Roadmap:** appended a dated direction revision describing open enrolment, optional public profiles, gradual optional verification, all three community experiences, both relationship types, public reading with member contribution, and shared topic/feed conversations.
- **History preserved:** earlier entries and the original roadmap sections remain intact. The build plan and Phase 0 plan remain historical documents; their older invite-only and deferred-community assumptions are superseded where the new decisions apply.
- **Implementation status:** this step records approved product choices. The new community features have not been implemented, and the existing application source was not changed by this documentation step.

### 6. Decisions still to make

- Content formats and starter topics.
- Moderation, reporting, and blocking behaviour.
- How discovery, a post author's visible identity, and private profiles work together; publication preview fields and search-engine indexing.
- Feed ordering and personalisation, relationship notifications, messaging, and any additional permissions for accepted connections.
- Delivery sequence and launch criteria for the revised public experience. Open decisions O1–O5 remain open; the adoption proposal does not close the Phase 0 gate.

The next design choice will be presented as options with a recommendation, following the user's stated process.

### 7. Documentation review

- **Read-only check:** `git diff --check -- docs/DECISIONS.md docs/WORK_LOG.md Nurse_ng_Strategic_Product_Roadmap.md` passed with no whitespace errors reported.
- **Review:** read the appended sections and checked that the selected choices, unresolved details, preserved history, and implementation status were represented accurately. This step updated planning documents only; no application test, migration, or implementation script was run.

### 8. Initial community content formats

- **Options proposed:** text posts and replies; text with images; or text, images, and video. The assistant recommended text for the first version to limit the initial build and mobile-data requirements.
- **User choice:** "All the three: 1, 2, & 3". The agreed initial community formats are therefore text, images, and video; the user chose the full media scope.
- **Reason and trade-off:** recorded in `docs/DECISIONS.md` L59. The choice supports written and visual contributions; media handling, moderation, and any hosting costs depend on how publishing is designed.
- **Documentation:** appended L59 to the decision record and a follow-up content-format choice to the roadmap. The earlier notes remain as history, with the previously pending content-format question now resolved.
- **Still to choose:** video uploads versus external links or both, detailed media limits and handling, and whether media attachments are available in replies. No media-sharing method, storage provider, cost commitment, or application implementation was selected by the format choice.
- **Documentation review:** read the new records and ran the read-only `git diff --check` for the three planning documents; it passed. This step updated documentation only and ran no application tests or migrations.
- **Next suggestion:** offer image/video uploads with external video links, image/video uploads alone, or image uploads with external links for video. Recommend uploads plus video links for flexible sharing, with the additional handling and hosting work stated as a trade-off. No media-sharing approach has been chosen yet.

### 9. Community media-sharing approach

- **Options presented:** image/video uploads plus external video links (recommended); image/video uploads only; or image uploads with externally hosted video links.
- **User choice:** option 1, uploads plus video links. Members can upload images and videos from their devices or share existing videos through links.
- **Reason and trade-off:** recorded in `docs/DECISIONS.md` L60. The choice permits original media and existing resources; uploaded video needs storage and processing, while linked video depends on its external host.
- **Documentation:** appended L60 and a matching roadmap follow-up, preserving the earlier records. No application implementation, hosting provider, or cost commitment was selected by this choice.
- **Next suggestion:** propose initial community-upload counts and video durations as alternative limit sets. Detailed limits have not been agreed; external video links remain a separate sharing route.
- **Documentation review:** read the appended decision and roadmap records and ran the read-only `git diff --check` for the three planning documents; it passed. Application source, tests, and migrations were not changed or run by this step.
- **Limit sets proposed next:** per post, up to four images and one uploaded video of up to three minutes (recommended); two images and one video of up to one minute; or ten images and one video of up to ten minutes. The recommendation balances room for professional updates with upload and moderation work. These are proposed upload limits, not selected limits, and do not set the duration of externally linked videos.

### 10. Initial community-post upload limits

- **Options presented:** four images and one uploaded video of up to three minutes (recommended); two images and one video of up to one minute; or ten images and one video of up to ten minutes, per post.
- **User choice:** option 1. A community post can include up to four uploaded images and one uploaded video of up to three minutes. Longer videos can be shared through external links.
- **Reason and trade-off:** recorded in `docs/DECISIONS.md` L61. The chosen set provides room for photos and short explanations while bounding an individual post's media; larger albums and longer native video files exceed the selected allowance.
- **Documentation:** appended L61 and a matching roadmap follow-up, preserving the earlier proposal records. The limits are approved design choices, with application implementation still pending.
- **Still to choose:** file-size and type limits, processing and storage arrangements, any account-level upload limits, and media attachments in replies.
- **Documentation review:** read the new limit records and ran the read-only `git diff --check` for the three planning documents; it passed. This step changed planning documents only and ran no application tests or migrations.
- **Next suggestion:** choose whether posts and replies publish after automatic checks (recommended), require staff approval for every contribution, or require approval only for each member's first contribution. The proposed approaches all include member reporting and staff review/removal. Recommend publication after automatic checks for responsive conversations, with reports handled after publication; no moderation approach has been selected yet.

### 11. Publishing and moderation approach

- **Options presented:** publication after automatic checks (recommended); staff approval for every post and reply; or staff approval for each member's first contribution. All proposed approaches included member reporting and staff review/removal.
- **User choice:** option 1. Posts and replies become visible after automatic checks and any necessary media processing; members can report content and staff can review and remove it.
- **Reason and trade-off:** recorded in `docs/DECISIONS.md` L62. Conversations can proceed without routine staff pre-approval; reported issues may need handling after publication.
- **Documentation:** appended L62 and a matching roadmap follow-up, preserving the earlier proposal records. No application moderation implementation was made by this documentation step.
- **Still to choose:** community rules, detailed checks and reporting workflows, review response targets, staff moderation permissions, appeals, and the public identity shown on posts when an author's profile is private. Professional verification remains optional.

---

## Session 2026-10-28

### 1. Repository inspection and current implementation

- **User direction:** inspect the latest work, read the repository and roadmap, and explain the current state and remaining work.
- **Read:** every human-maintained source, configuration, template, test, migration, Markdown document, designed HTML page, and the roadmap PDF (Portable Document Format). Virtual environments, caches, Git internals, bytecode, and binary database contents were excluded from the file-by-file reading.
- **Finding:** the working tree contains the previously recorded document-review workflow plus a new public-community implementation: feed, topics, posts, replies, image/video uploads, external video links, nurse discovery, following, accepted connections, reports, and staff moderation. The community implementation had not been recorded in this log or the decision record.
- **Git state at inspection:** `main` was one commit ahead of and one behind `origin/main`; Git's patch comparison marked the two authentication-hardening commits as equivalent despite their different hashes. The working tree contained 24 modified files and 28 untracked files. Those changes were preserved.
- **Verification boundary:** the last documented complete result remained 89 passing tests from 21 October. Community tests existed, but no new result was treated as authoritative during the read-only inspection.

### 2. Login failure and authorised database migration

- **User report:** signing in returned an internal server error.
- **Diagnosis:** the running model selected `users.community_name`, but the development database was at revision `c4e7a1b9d2f3` and did not have that column. The pending community revision was `d7a9e3f5b1c2`.
- **User choice:** back up and migrate.
- **Backup:** copied the pre-migration SQLite database to `/tmp/opencode/nurse-ng-before-community-20261028.db`.
- **Migration:** `./venv/bin/alembic upgrade head` applied `c4e7a1b9d2f3 -> d7a9e3f5b1c2`. A read-only check confirmed the new revision and column. No application source was changed during the diagnosis.

### 3. Hardening scope authorised

- **User direction:** update the decision record, work log, README, roadmap, and PDF; remove stale invite-only registration copy; fix review/name and public-profile trust risks; add community rate limits, upload quotas, streaming, malware scanning, and cleanup; close relationship/report races; run the full verification set; split the work into logical commits; and reconcile the patch-equivalent branch histories.
- **Git clarification:** when asked how to reconcile and publish history, the user reserved that step for themselves. The assistant may create logical local commits but must not merge, rebase, push, or otherwise reconcile `main` with `origin/main`.

### 4. Approved choices and implementation plan

The user selected:

1. Keep a reviewed-name snapshot and distinguish it from any later profile name, rather than invalidating the review or blocking name changes (L63).
2. Reject hiding the display name while a profile is public; require unpublishing first (L64).
3. Make community names case-insensitively unique, reserve institutional/staff-like names, and lock a name after the first post or reply (L65).
4. Use the permissive limits: 10 posts/hour, 60 replies/hour, 20 reports/hour, 500 MB uploaded per 24-hour account window, and 5 GB stored per account (L66).
5. Stream files in bounded chunks, reserve quota transactionally, remove media after moderated post removal, and provide reconciliation tooling (L67).
6. Run ClamAV when available but allow an upload when the scanner is unavailable or fails operationally; a positive detection is always rejected (L68).
7. Add canonical database uniqueness keys and conditional state updates for connection and report races (L69).

Planned sequence:

1. Record the choices before implementation.
2. Establish the current test/lint baseline with the user's explicit approval.
3. Add the schema revision, service invariants, streaming/scanning/quota storage path, cleanup command, route controls, interface copy, and focused tests.
4. Verify tests, Ruff (Python linter), dependencies, schema drift, and migration upgrade/downgrade/upgrade in an isolated database.
5. Update completion records, README, roadmap, and generated PDF with actual—not planned—results.
6. Create logical local commits. Leave branch reconciliation and pushing to the user.

### 5. Pre-hardening baseline

The user explicitly approved execution of the full verification set. A first test invocation reached the final portion of the suite but exceeded the command's 120-second harness limit, so its partial output was not counted as a result. Re-running with a longer command limit established the baseline:

| Command | Result |
|---|---|
| `./venv/bin/python -m pytest -o addopts='' -q` | **103 passed in 65.21 seconds** |
| `./venv/bin/ruff check .` | **All checks passed** |
| `./venv/bin/pip check` | **No broken requirements found** |
| `git diff --check` | **Passed** (no whitespace errors) |

This is the pre-hardening result: the previously documented 89 cases plus 14 community cases. Migration drift and reversibility remain for the final isolated verification after the new hardening revision is written.

---

## Session 2026-11-02 — Resuming the interface refresh

### 1. Reconstructed unfinished work

- **User direction:** continue where the work stopped. Reviewed the existing uncommitted interface refresh, job applications, private messaging, account settings, profile additions, and document-upload wiring. These changes were already present when this session resumed.
- **Finding:** the local database still has the two community migration heads and lacks account names/types, additional profile fields, jobs, applications, and messages. Creating tables from model metadata in tests would hide this deployment gap.
- **Finding:** the pending compatibility-marker edit changed its historical parent, even though the development database still records both original heads. Preserve the original branch ancestry and add an explicit merge before the new schema revision (L70).
- **Initial verification:** Ruff (Python linter) found four long lines in the new resources route; wrapped them. The sandboxed test suite and a separate health-check test stalled in the asynchronous test client's thread bridge. Requested the same test suite outside the sandbox; its result is pending.
- **Next work:** finish migrations, verify fresh and existing database upgrades in temporary copies, exercise the new account/job/message flows, fix regressions, and record actual results. Existing source changes and historical records are preserved.

### 2. Baseline results and migration repair

- **Tests outside the sandbox:** 101 passed and 3 failed in 73.92 seconds. The failures were missing public/private profile labels and a review-submission label in redesigned templates. Restored explicit visibility labels and changed the review button to “Submit for review”.
- **Fresh migration failure:** `d7a9e3f5b1c2` also declared the community-name key/lock columns owned by hardening. This caused an Alembic (database migration tool) circular column dependency. Removed those duplicate declarations; the hardening revision remains their sole owner. The compatibility marker preserves its original parent; `f9a2b3c4d5e6` merges both heads.
- **Schema revision:** generated `b2c3d4e5f6a7` against an isolated database successfully migrated through the merge. It adds account names and roles, qualification/experience/skills, jobs, applications, and private messages, including foreign keys and the unique job/applicant constraint.
- **Interface connections:** added a message link for accepted active network connections; replaced an unsupported “caught up” notification claim with links to actual requests/messages; removed duplicate file-input JavaScript already handled by the shared script.

### 3. Regression coverage and local database upgrade

- **New tests:** `tests/test_workspace_flows.py` covers account details and role/staff boundaries, duplicate email rollback, employer-only posting and job filters, application consent/contact snapshots/employer isolation/withdrawal, accepted active connection permissions, message escaping and read tracking, protected pages, and explicit sharing of qualification, experience (including zero), and skills.
- **Migration test:** `tests/test_migrations.py` starts from the two historical heads, inserts an existing account, upgrades and checks metadata drift, verifies old data and new defaults, downgrades the new increment and re-upgrades, then exercises a full downgrade to base and a fresh upgrade. Added Alembic's explicit operating-system path separator to remove its configuration deprecation warning.
- **Results:** the first 10 new tests passed in 20.18 seconds. After adding the extended-profile privacy case, the complete suite passed: **115 tests in 87.79 seconds**, with no warnings. Ruff reported “All checks passed!”; the dependency check reported “No broken requirements found”; `git diff --check` passed.
- **Data preservation:** saved `/tmp/nurse-ng-before-refresh-20261102.db`, upgraded a separate copy, and compared every original column value across all 14 existing application tables. All values were preserved; Alembic detected no schema drift.
- **Local application database:** applied the same merge and schema revisions successfully to `b2c3d4e5f6a7`; the subsequent schema-drift check passed. No account or content fixtures were added to the application database.

### 4. Browser review

- **Environment:** a temporary application server, a separate browser database, and headless Chrome. Temporary accounts exist only in the browser database. The browser runner is `/tmp/nurse-ng-browser-check.py`; screenshots and logs are under `/tmp/nurse-ng-browser-review/`.
- **First attempts:** Chrome did not initialise within the first allowance; disabling its system keyring and allowing more startup time resolved that. The next runner stopped because it expected registration to redirect to `/auth/dashboard`; the application correctly redirects to `/`, which renders the member dashboard. Corrected the runner.
- **Completed journeys:** real browser registration and profile editing, password visibility, public and signed-in mobile menus, and navigation through profile, verification, jobs, applications, messages, network, topics, feed, learning, resources, and settings. No application script exceptions, failed page/asset responses, or broken images were reported in that pass.
- **Visual findings:** fixed the keyboard skip link peeking from the left edge, aligned public mobile navigation actions to the right, and corrected a full-width form plus margins overflowing the settings screen. Reduced the base input selector's specificity so the refreshed component styles can apply; reset the header-search input's minimum height to fit its container.
- **Final visual verification:** passed after enabling keyboard focus emulation in the headless browser. The skip link is fully hidden when unfocused and visible on focus. Desktop landing/dashboard layouts and all checked mobile pages fit their viewport, including settings at 390 pixels. Public and member menus, Escape dismissal, password visibility, registration, and profile editing passed. No application script exceptions, failed page/asset responses, or broken images were detected. Temporary servers and browsers were stopped after each attempt.
- **Completion documentation:** updated README status and the decision record with the inherited feature boundaries, migration repair, actual verification results, and remaining placeholder functionality. No Git history reconciliation, commits, or publication were performed.

---

## Session 2026-11-02 — Dark mode and accessibility

### 1. Direction and implementation

- **User direction:** implement dark mode and accessibility. The preceding discussion confirmed that the dashboard at `/` is expected for a valid existing session; no routing or authentication change was made during this increment.
- **Decision:** recorded L72 before implementation: System/Light/Dark themes plus independent larger-text, higher-contrast, and reduced-motion options. Preferences belong to the browser. Device motion preferences remain authoritative even when the additional reduction option is off.
- **Display controls:** added `_display.html`, `display.js`, and `appearance.css`. An early script applies the stored preference before styles load; guarded storage access falls back safely when storage is unavailable. Changes persist across navigation and reloads; system-theme changes and storage events update the current page. The dialog includes a reset action and explains when saving is unavailable.
- **Entry points:** added the display button to public/member headers, login and registration headers, and account settings. Native dialog behavior supplies focus isolation, Escape dismissal, and restoration to the opener.
- **Appearance:** added dark surface/text/status palettes, clearer input borders and focus rings, readable secondary labels, larger touch targets, text enlargement that uses relative sizing, high-contrast controls, forced-color handling, and reduced-motion styling. Photographs retain their original colors; higher contrast removes decorative photo backgrounds.
- **Navigation/accessibility:** moved mobile navigation into a native dialog so links are inaccessible while it is closed and page controls cannot take focus while it is open. Desktop navigation is restored at the breakpoint. Removed the old backdrop element and the single-character search shortcut, which could interfere with speech input. Added a stable accessible account-menu name, specific file-upload names/hints, a focusable main landmark, and focus on returned form errors.

### 2. Verification and corrections

- **Regression suite:** **115 passed in 91.44 seconds**. Ruff (Python linter), JavaScript syntax checks, and `git diff --check` passed. There is no schema change or new dependency for this feature.
- **Browser environment:** used an isolated local server/database and Chrome, with axe-core 4.10.3 as a temporary auditing tool. The audit runner and cases are `/tmp/nurse-ng-accessibility-check.py` and `/tmp/nurse-ng-accessibility-cases.py`. Results and screenshots are under `/tmp/nurse-ng-accessibility-review/`.
- **Harness corrections:** native dialogs permit focus to reach browser controls; the test now distinguishes that from background page focus. Native Escape/Tab handling also required virtual key codes in browser automation. These were test-runner fixes, not replacements for native keyboard behavior.
- **Findings fixed:** the first content audit found insufficient dark-mode contrast in dashboard labels, quick links, and a remaining white card footer. Corrected those colors and the statistic numbers/progress track. Enlarged text initially overflowed a 320-pixel header; simplified redundant header controls on very narrow screens while keeping their destinations in navigation.
- **Automated accessibility result:** **38 page/theme states, zero reported violations** under the selected WCAG (Web Content Accessibility Guidelines) A/AA rules through version 2.2. Coverage includes public landing/login/registration, the preferences dialog, mobile navigation, dashboard, profile/edit/verification, jobs, applications, messages/conversation, network, topics/feed, learning/resources, settings, and a higher-contrast enlarged-text state. Some image/background contrast and ARIA (Accessible Rich Internet Applications) relationships remain marked for manual review by the auditing tool; this is not a certification claim.
- **Behavior checks:** verified saved theme across navigation/reload, live system-theme changes, explicit overrides, device reduced motion, reset, blocked-storage fallback, keyboard navigation, Escape and focus restoration, and no focus on hidden navigation. Main mobile pages fit a 320-pixel viewport with enlarged text. No application script exceptions, failed page/asset responses, or broken images were reported.
- **Final polish and verification:** increased quick-action/tag legibility and aligned tag colors with the chosen theme. The focused final check passed: dark dashboard contrast, enlarged-text reflow at 320 pixels, named buttons/radios/checkboxes in the browser accessibility tree, rejection of background focus while the dialog is open, and visible borders/focus styling in forced colors. Runner: `/tmp/nurse-ng-display-final-check.py`; screenshots: `/tmp/nurse-ng-display-final-review/`. Temporary browsers and servers were stopped. Final syntax, lint, and whitespace checks passed.

---

## Session 2026-11-02 — Product and engineering assessment recorded

- **User direction:** transfer the entire assessment into `BUILD_PLAN.md`.
- **Documentation:** appended the full assessment to [BUILD_PLAN.md](BUILD_PLAN.md#current-product-and-engineering-assessment--2-november-2026), including its opening qualifications, six-area comparison, all six priorities and their explanations, source references, and the next-cycle recommendation. Preserved the original plan and identified its historical stack and registration proposals separately from the current application.
- **Scope:** recommendations remain proposed work. This documentation update changes no application behavior; the cited test and accessibility results are from the preceding implementation work.

---

## Session 2026-11-06 — Assessment and completion baseline

- **User direction:** assess the project, then save the assessment in the project documents so future completeness can be measured against it.
- **Assessment results:** 115 tests passed in 183.99 seconds. Ruff, dependency consistency, and both JavaScript syntax checks passed. Alembic reported one head (`b2c3d4e5f6a7`) and no local SQLite schema drift. No live deployment or fresh browser accessibility audit was performed.
- **Additional findings:** isolated fixture checks confirmed that the development signing key permits a forged staff session, unlisted hosts are accepted, stale reviewer sessions can overwrite a decision while leaving the approval badge, and suspended profiles remain publicly discoverable. The probe runner stalled in the sandbox's asynchronous thread bridge; its approved run outside the sandbox completed successfully using an in-memory database. Temporary stalled runners were stopped. Employer self-registration and immediate posting privileges were also reviewed.
- **Documentation:** preserved the assessment and added a 13-item completion tracker, stable IDs, closure criteria, baseline counts, and an evidence log in [BUILD_PLAN.md](BUILD_PLAN.md#assessment-baseline-and-completion-tracker--6-november-2026). Linked it from the README. Kept the earlier assessments and the existing user edit intact.
- **Scope:** this records findings and proposed closure criteria, not implemented fixes or authorization to begin implementation. Verification-source research remains deferred. The checks above belong to the assessment; this follow-up changes documentation only.

---

## Session 2026-11-06 — A01 production configuration and session safeguards

- **User direction:** start the recommended first implementation item, A01. Recorded the implementation choice as L73 before editing application code.
- **Implementation:** production is the default environment and requires an explicit signing key and host list. Unsafe debug/cookie settings, short or known development keys, wildcard hosts, and malformed host entries fail configuration validation. Development must be selected explicitly and generates a random per-process signing key when none is supplied. TrustedHostMiddleware rejects unlisted hosts before session handling and routes. Validation messages and settings representations do not display the signing key.
- **Operator support:** added `python -m app.cli check-config`, which reports the validated mode, hosts, and cookie/debug flags without showing secrets or connecting to the database. Updated `.env.example` and README instructions, including migration from old local placeholder keys and the production verification procedure.
- **Focused checks:** the first run found 35 passing cases and one IPv6 localhost failure. Starlette preserves brackets around IPv6 Host literals; adjusted the configured middleware hosts accordingly. After that correction and the operator-command check, **37 tests passed in 5.81 seconds**. Ruff and whitespace checks passed. Tests run outside the sandbox because the test client's thread communication was previously blocked there.
- **Full regression check:** **152 tests passed in 65.04 seconds**, including all 115 existing cases and the 37 new configuration cases. The suite covers migration history as well as authentication, profiles, community, review, recruitment, and messaging. Final Ruff and whitespace checks passed; no dependency or schema changes were introduced.
- **Tracker:** A01 is in progress with its local implementation verified. Its original closure criteria also require checking the actual deployment configuration and public HTTPS/proxy behavior, which remain unverified. No deployment, data migration, or other assessment-item implementation was performed. The pre-existing documentation changes were preserved.

---

## Session 2026-11-06 — Community conversations

- **User direction:** leave A02/A04 for later and prioritize the community experience previously described: Nigerian nurses asking about internships, hospitals, recruitment, applications, and everyday professional experiences; sharing information; replying; following discussions; and finding earlier answers. Recorded L74/L75 and marked A02/A04 deferred without changing the assessment baseline or closure criteria. Nurse.ng remains a wider professional platform.
- **Findings:** the reply endpoint existed, but the conversation page had no reply composer. The local database had no topics, preventing normal posting. Existing follow functionality followed people rather than individual discussions. These gaps prevented the intended ask → reply → return journey.
- **Implementation:** restored the reply form, preserved reply text on validation and throttling errors, and redirect successful replies to their anchor. Asking/sharing is text-first with optional media and inline first-time community-name selection. Existing identity uniqueness, locking, professional-profile privacy, authentication, moderation, and participation permissions remain enforced.
- **Finding information:** added search across public post text, topic names, and published replies, with 20-item pagination for the main feed, topic pages, people-following feed, and followed discussions. Queries survive pagination; removed content is excluded. Listing summaries batch reply counts/activity instead of loading all replies for every card.
- **Returning to conversations:** added explicit discussion subscriptions, separate from following people or accepted connections, and `/feed/discussions`. New replies from others are marked until read; own and removed replies do not create unread indicators. Read markers advance monotonically only through rendered replies. Personalized list/detail responses use `Cache-Control: no-store`. Updates appear on page load.
- **Schema:** migration `c3d4e5f6a7b8` follows `b2c3d4e5f6a7`, adding the unique user/discussion follow table and reply activity index. It creates one empty General nursing topic only when no topics exist, preserving existing and intentionally inactive categories. Downgrade removes the follow schema and index but preserves the category because real posts may reference it.
- **Automated verification:** existing community/migration checks: **15 passed in 11.80 seconds**. Focused discussion/migration checks: **14 passed in 10.18 seconds**. Final full suite: **165 passed in 77.57 seconds**. The 11 discussion cases cover inline identity/privacy, actual reply forms, validation/throttling preservation, HTML escaping, search and hidden-content exclusion, pagination, follow permissions/CSRF/idempotence, unread/read/removal behavior, read-marker ordering, and subscription uniqueness. Two additional migration cases cover empty and existing-inactive topics through upgrade/downgrade with no drift. Ruff and whitespace checks passed.
- **Local data preservation:** `/tmp/nurse-ng-upgrade-community.py` backed up the local database to `/tmp/nurse-ng-community-upgrade-bxdevflr/before.db`, upgraded a trial copy, and compared existing records across 17 tables before applying the upgrade to `nurse_ng.db`. Existing data was preserved; the local schema is at `c3d4e5f6a7b8` with no drift. Only the empty General nursing category was initialized; no test accounts, posts, or replies were added to the real database. The temporary backup is local recovery evidence, not a production backup procedure or closure of A11.
- **Browser verification:** `/tmp/nurse-ng-community-browser.py` used headless Chrome and an isolated migrated fixture database/server. The first run stopped on quoting in the runner's JavaScript selector; corrected the runner. The next run passed login, inline-name posting, follow/new-reply/read behavior, reply submission and anchor, search matching only reply text, query-preserving pagination, display controls, and reflow at 320/390/1440 pixels. No application JavaScript exceptions or failed HTTP responses were detected. Screenshots/logs are under `/tmp/nurse-ng-community-browser-1uz5xz7o/`; mobile conversation, narrow dark view, and desktop feed screenshots were visually reviewed. Temporary browsers and servers were stopped. This is targeted browser verification, not a fresh full accessibility audit.
- **Documentation and scope:** updated README, the assessment status/evidence log, and a separate C01–C06 community delivery checklist; marked the older audit summary historical. No A02/A04 implementation, external deployment, email/push delivery, fabricated activity, or new runtime dependency was introduced. Real-nurse usability and useful-answer outcomes remain to be observed.

### Local startup follow-up

- **Reported issue:** Uvicorn's worker failed configuration validation when started directly. Inspection found no local `.env` and no development overrides in the agent's process, so configuration defaulted to production without the required signing key.
- **Fix:** created the Git-ignored `.env` from `.env.example` with development mode, local HTTP cookies, localhost hosts, and a securely generated persistent local signing key. The file has owner-only read/write permissions; the key was not printed or added to documentation. Added the direct Uvicorn command and local URLs to README.
- **Verification:** `python -m app.cli check-config` passed. Uvicorn's `Config.load()` successfully imported and initialized `app.main:app`, reproducing the previously failing startup stage. This check did not bind a port or replace the user's running reloader; restart it to use the saved settings.

---

## Session 2026-11-06 — Reply pagination and unread navigation

- **User direction:** start the proposed reply-pagination and first-unread increment. Recorded L76; draft recovery and previously deferred assessment items remain outside this increment.
- **Implementation:** conversation pages fetch at most 20 published replies, ordered by creation timestamp and ID, with earlier/later controls above and below the replies. Stale page numbers fall back to the last available page. The composer preserves its page and text on validation/throttling errors; successful submission links to the page and anchor containing the new reply. Detail and action queries no longer eagerly load the entire reply collection.
- **Returning:** new-reply badges link to the first unread reply; the conversation also offers a first-unread link and highlights newly opened replies. Each reply has a permanent URL that resolves its current page. Removed replies, removed posts, and reply IDs belonging to another conversation return 404 at that resolver. First-unread redirects themselves do not mark replies read.
- **Private read state:** added `discussion_reply_reads`, keyed by subscription and reply. Only replies on a successfully rendered page are recorded; reading the last page cannot consume earlier unread replies. Atomic conflict-tolerant inserts make repeated/overlapping writes additive. Historical `last_read_at` values remain unchanged as cutoffs for previously read content. Own replies do not create unread indicators. Unfollowing cascades deletion of the private read records. SQLite behavior is verified; PostgreSQL runtime/concurrency verification remains A10 work.
- **Migration:** `d4e5f6a7b8c9` follows `c3d4e5f6a7b8`. Upgrade adds only the new read table and reply index. Downgrade removes those records but preserves discussions and subscriptions with their historical cutoff; replies read through the new table may appear new again after rollback. No backfilled activity or new dependency was introduced.
- **Automated verification:** the existing discussion/migration checks first passed **14 tests in 12.09 seconds**. Expanded focused checks passed **25 tests in 13.89 seconds**. After adding the historical-cutoff migration case, the full suite passed **177 tests in 109.05 seconds**. Coverage includes bounded database loads, same-timestamp replies, pages read out of order, first-unread targets, current-page reply links after removal, form errors/throttling, private isolation, idempotent reads, unfollow cleanup, invalid/empty/stale pages, failed rendering, and preserving migration history. Ruff and whitespace checks passed; one import-order lint finding was corrected before the final checks.
- **Local database:** `/tmp/nurse-ng-upgrade-reply-pages.py` saved `/tmp/nurse-ng-reply-pages-upgrade-hx96mhjp/before.db`, upgraded a trial copy, and compared existing records across 18 tables before applying the upgrade to `nurse_ng.db`. Existing records were preserved; Alembic reports `d4e5f6a7b8c9` and no drift. The backup is local recovery evidence, not closure of production backup requirements.
- **Browser verification:** extended the isolated `/tmp/nurse-ng-community-browser.py` runner with a 47-reply conversation. Opening the final page left 38 new replies; first-unread navigation opened the earlier page and left 20; opening the remaining page cleared those updates. Replying from the middle page landed on the final page, and permanent reply links worked. The first attempt checked the target position before the existing smooth-scroll animation completed; waiting for the actual target position fixed the runner. The rerun passed the long-discussion journey plus existing posting, replying, following, search, display controls, and reflow at 320/390/1440 pixels, with no application script exceptions or failed HTTP responses. Mobile pagination and highlighted-target screenshots were visually reviewed. Artifacts: `/tmp/nurse-ng-community-browser-6yyortkt/`. Temporary servers/browsers were stopped; this was not a full accessibility audit.
- **Completion record:** added C07–C09 to the community delivery tracker and updated README with the current schema, test result, and navigation instructions. No external deployment or user-server restart was performed.

---

## Session 2026-11-07 — Community draft recovery

- **User direction:** start automatic recovery for questions and replies, explicit discard, cleanup after confirmed publication, and account-specific cleanup on logout. Recorded L77 before implementation.
- **Implementation:** added `community-drafts.js` and shared composer controls. Text, topic selection, video-link text, and a first community name save in session storage while typing. Each tab keeps an independent question draft and reply draft per discussion. Recovery restores on return/refresh, expires after 24 hours without editing, and removes malformed records. File contents are not stored; the interface explains reselection and tab lifetime. Storage failures show an honest unavailable message while normal forms remain usable.
- **Confirmation:** publishing routes accept an optional opaque draft-version ID. Only successful publication stores a small key/version acknowledgement in the signed session; the next successful template render emits and consumes it. The browser clears only a matching stored version, preserving a different or newer draft. Failed requests retain text. An unknown network outcome restores the draft with a reminder to check the conversation before sending again. No automatic retries or duplicate-submission guarantee were introduced.
- **Privacy:** draft keys use an opaque scope derived from the authenticated member and session CSRF token. Draft text is not placed in cookies, shared local storage, a new API, or the database. Shared browser storage and BroadcastChannel carry session-change/confirmation signals only. Logout clears the tab and notifies other tabs; revoked-session markers stop old tabs restoring or re-saving text. Switching accounts clears the old scope. Rendered HTML now defaults to `Cache-Control: no-store` so session-specific scope/confirmation data is not reused from an HTTP cache. Display preferences remain untouched.
- **Browser finding fixed:** the first browser pass showed that native history restoration could put published text back into the composer after draft deletion. Added cleared-version markers and reconciliation after the browser restores form values. The rerun passed, including Back navigation and independent drafts in a second tab.
- **Automated checks:** initial focused run: one failure, 38 passes. The synthetic signed-in cookie lacked a host domain and survived logout alongside the real cookie; corrected the shared test helper to use the same domain/path as the test browser. Focused rerun: **39 passed in 8.35 seconds**. Full regression suite: **182 passed in 128.92 seconds**. New server cases cover session scope, post/reply confirmations, validation failure, invalid version IDs, and CSRF rejection. Ruff, JavaScript syntax, and whitespace checks passed.
- **Repeatable browser verification:** committed `tests/browser/community_drafts.py`, using installed Chrome, an isolated migrated database, fixture accounts, and a temporary server. Checks passed for text/topic/link/name recovery, attachment reselection, separate tabs/discussions, validation errors, a deliberately offline submission, confirmed posting/replying, history restoration, discard, expiry, malformed/blocked storage, logout across tabs, prevention of stale-tab saves, account switching, preserved display settings, and reflow at 320/390/1440 pixels. The expected validation response was HTTP 400; the offline request intentionally failed. No unexpected application script exceptions or HTTP failures were reported. Final artifacts: `/tmp/nurse-ng-draft-browser-qobd59it/`; earlier successful screenshots under `/tmp/nurse-ng-draft-browser-u1l45ywc/` were visually reviewed. Temporary browsers/servers were stopped. This is targeted browser verification, not a full accessibility audit.
- **Completion:** recorded C10–C12 and the current checks in BUILD_PLAN/README. Existing application data and schema remain unchanged by this increment (`d4e5f6a7b8c9`); no migration, new runtime dependency, external deployment, or user-server restart was needed. Previously deferred assessment work remains deferred.

---

## Session 2026-11-07 — Replying to individual responses

- **User direction:** start the proposed Reply action on each response, a short reference and link back, and preservation of the selected response in drafts and across pages. Recorded L78 before implementation.
- **Implementation:** added optional `CommunityReply.in_reply_to_id`, validated against an existing published reply in the same discussion. Responses remain in chronological order with the existing pagination. Each targeted response displays a current public author/excerpt reference and uses the permanent reply URL to resolve the original's current page. Immediate references are loaded in a bounded batch; no recursive thread is fetched.
- **Composer:** the Reply link works as normal navigation without JavaScript. With JavaScript, it selects the response, keeps the typed text, identifies the response in the composer, and focuses the reply field. “Reply to conversation instead” explicitly clears only the target. URL/pagination state and the composer remain consistent when a target is changed or cleared.
- **Draft integration:** added only the selected response ID to the existing draft fields. Restoration fetches current public context through a small uncached endpoint. Explicit new selections override an older saved target while keeping its text; later history restoration uses the saved current draft. Discard, successful publication, and logout clear the target as well as text. Unavailable context does not silently convert a draft into an untargeted reply.
- **Moderation and privacy:** the context endpoint exposes only reply ID, public community name, a 180-character excerpt, and the public reply link. Templates escape the text and browser rendering uses `textContent`. Missing, removed, malformed, and cross-discussion targets are rejected at publication. Soft removal hides the excerpt in existing references; physical deletion clears the foreign key while preserving the answering response. Loading an off-page excerpt does not mark that original response read.
- **Migration:** `e5f6a7b8c9d0` follows `d4e5f6a7b8c9`, adding the nullable self-reference, index, and a check against referencing the same row. Downgrade drops the reference metadata while retaining response bodies. Historical-schema test fixtures now insert their original columns explicitly; their old shape predates this new field.
- **Automated verification:** the first focused run had 30 passes and one historical-fixture failure because the raw fixture omitted `removal_reason`. The expanded run had 40 passes and one fixture failure because its author lacked a normalized community-name key. Corrected both fixtures without weakening application validation. The final reply-context/migration run passed **14 tests in 16.20 seconds**. The full regression suite passed **192 tests in 138.46 seconds**. New checks cover published metadata, escaping, cross-page targeting/read state, failed submission preservation, unavailable and foreign targets, moderation/deletion, native links, auth/CSRF, and migration preservation of replies/reports/read records. Ruff, JavaScript syntax, and whitespace checks passed.
- **Local data:** `/tmp/nurse-ng-upgrade-reply-context.py` saved `/tmp/nurse-ng-reply-context-upgrade-2g0ng2mp/before.db`, upgraded a trial copy, and then upgraded `nurse_ng.db`. Comparisons preserved every original column value across 19 tables. Foreign-key checks passed on the backup, trial, and actual database; Alembic reports `e5f6a7b8c9d0` with no drift. No account, post, or reply fixtures were added to the application database.
- **Browser verification:** extended the checked-in draft browser runner to choose a response, preserve text and context across pages, restore an off-page target, override the draft target explicitly, clear/discard context, handle a removed target with retained text and a rejected submission, publish to an available target, and follow its reference back to an earlier page. The first behavior run passed. Subsequent screenshot checks exposed that the runner left the conversation in a background tab after its two-tab draft check; Chrome did not animate that tab's scroll. The runner now activates the tab before interacting and waits for scrolling to settle. Avoided redundant history updates in the context script as well. The final run passed the context journey and existing draft/offline/logout checks, with mobile/desktop reflow at 320/390/1440 pixels. Expected invalid-submission HTTP 400s and removed-context HTTP 404s were accounted for; no unexpected script exceptions or HTTP failures were reported.
- **Visual evidence and completion:** visually reviewed the focused mobile composer and the published response/reference. Final artifacts: `/tmp/nurse-ng-draft-browser-ih5cotrz/`; the repeatable runner is `tests/browser/community_drafts.py`. Temporary servers and browsers were stopped. Added C13–C15 and updated README. No new runtime dependency, external deployment, or unrelated assessment fix was introduced.

## Session 2026-11-07 — Recruitment-source discovery and review

- **Authority and scope:** user asked to start the saved source-discovery design. Inspected the existing implementation and preserved concurrent/uncommitted community work. Delivered the independently useful source-discovery/review increment; the full vacancy aggregation and AI stages remain open. Recorded L79 and updated the saved design's completion tracker.
- **Registry and staff screens:** five new tables for organisations, exact source URLs, discovery schedules, leased tasks and source events. Added `/recruitment` with filters, manual registration, source detail, evidence review, organisation corrections, history, check requests and schedule controls. Approval requires country/category, five distinct evidence findings with references, expiry and method. All changes require staff and CSRF; outputs escape external content. Source health is independent of verification.
- **Independent discovery:** ROR healthcare queries for Nigeria and worldwide; optional gated Brave adapter; bounded HTML recruitment-link and sitemap inspection. Directory/search records and newly found recruitment pages enter pending status. Source identity/URL deduplication does not silently merge unrelated organisations. The LSHSC original address remains exactly `https://lshsc.ng/recruitment`.
- **Worker and safety:** separate `recruitment-worker` command, persistent queue, single network lease, duplicate prevention, fencing/recovery, 45-second isolated-process deadline, retries and shared cooldowns. Daily attempt/queue caps are configurable. Network requests use verified TLS, public DNS-pinned sockets, robots checks, bounded redirects and responses, no cookies/proxies, and no cross-origin provider credentials. Reject special/private addresses and sensitive URL query tokens. No AI, paid search calls, vacancy publication or synthetic member activity.
- **Automated verification:** initial focused run found one assertion expecting 403 where the existing CSRF dependency correctly returns 400; fixed the assertion. Full suite passed with 246 collected cases. Added two multicast/tunnel-address rejection cases and ran the final recruitment suites: **56 passed in 29.20 seconds**; current collection is 248. Full Ruff and whitespace checks passed. Existing migration tests exercise fresh/history upgrades, data preservation, downgrade/upgrade and schema drift against the new head.
- **Live adapter evidence:** the first sandbox call could not resolve ROR; a permitted read-only network retry succeeded. The implemented Nigerian healthcare query returned 18 usable institution candidates from 20 records, including Bowen, Jos, Ilorin and Abuja teaching hospitals and Federal Medical Centres. Some returned addresses look historical. The result validates discovery, not current ownership, licensing or vacancy availability. No paid search or live source approval occurred.
- **Browser evidence:** `/tmp/nurse-recruitment-browser.py` uses an isolated temporary SQLite database/server and Chrome. Staff login, mobile/desktop registry/detail reflow, evidence approval and exact URL preservation passed; no JavaScript errors or unexpected HTTP failures. Synthetic approval evidence exists only in the disposable browser database. Visual inspection found unstyled buttons and overly bright borders; corrected to existing button/theme tokens and repeated the checks. Browser artifacts are under `/tmp/nurse-ng-source-browser-*`.
- **Database:** SQLite backup `/tmp/nurse-source-migration-980r_vla/before.db`; trial and real upgrade to `a3310f4d2d7b` preserved every original value across 19 tables. There are now 24 tables, foreign-key checks pass and Alembic reports no drift. Initialisation creates Nigerian/worldwide schedules and the one pending LSHSC source without network requests; the worker is an explicit separate process.
- **Operational limits:** ROR is incomplete; broader government/facility/agency discovery needs additional directory adapters or appropriately licensed search. JavaScript/PDF extraction, jurisdiction policies, PostgreSQL concurrency, deployment supervision, audit retention/metrics and cross-provider entity merging remain further work. Existing jobs and A03 employer safeguards are not changed. Instructions and budgets are in `docs/RECRUITMENT_SOURCE_OPERATIONS.md`.

## Session 2026-11-07 — Structured vacancy ingestion and publication

- **Authority:** user said “continue” after source discovery/review. Inspected existing code and saved decisions; preserved community work. Continued original-record retention, normalization, publication and basic lifecycle without approving live sources or enabling paid providers.
- **Primary documentation:** inspected `https://schema.org/JobPosting`, saved at `/tmp/nurse-schema-jobposting.html`. `url` identifies the announcement; `directApply` is not a separate endpoint. `jobStartDate` is employment start, not application opening. No licensing requirement is invented from an unrelated credential property.
- **Delivery:** shared Job model with an ownership constraint; original snapshots and JSON, normalized records and history; per-source collector configuration; approved-only worker ingestion; automatic ordinary publication and staff exception review; country filters, international salaries and external application instructions. No runtime dependency, model call or microservice added.
- **Trust/lifecycle:** validation covers nursing relevance, employer, country, text, URL scope and dates. Current permission/version/lease gates protect ingestion. Staff corrections keep original evidence and expire on source changes; rejections persist. Conflicts and missing/failed observations stop claiming open. Public reads check deadlines and 48-hour confirmation. Malformed structured pages are retained for investigation.
- **Verification:** early test fixtures used unescaped closing script tags inside JSON-LD, correctly causing rejection; fixed encoding. Historical migration fixtures needed string UUIDs and old-schema defaults. Focused ingestion passed 27 cases, source/workspace regression passed 40, and migration checks passed 7. Restricted runs intermittently stalled during TestClient/AnyIO event-loop startup. A permitted run outside the sandbox passed the final full suite: **280 tests in 175.04 seconds**. Stopped the three owned stalled runs afterwards. Ruff and whitespace checks passed.
- **Browser:** `/tmp/nurse-vacancy-browser.py` uses a disposable SQLite database/server and Chrome with synthetic permissions. Corrected its wait for text inside a collapsed panel after verifying the backend saved configuration. Collector setup, automatic publication, NG/NZ opportunities, NZD annual salary, external application presentation and exception review passed. Visual review found cramped mobile attribution/search controls; moved attribution into card bodies and gave search its own mobile row. Repeated successfully; final artifacts `/tmp/nurse-ng-vacancy-browser-k91ke1mh`.
- **Exact source:** saved browser capture `/tmp/nurse-research-ng-lshsc-browser.html` produced zero structured JobPosting records. `https://lshsc.ng/recruitment` remains exact and pending. No live source approval or vacancy was fabricated.
- **Database:** backup `/tmp/nurse-vacancy-migration-lg26zacf/before.db`; trial and real upgrade to `3838cd201521` preserved every original value across 24 tables. There are now 27 tables; foreign keys and Alembic drift checks passed. Downgrade refuses populated vacancy data that the old schema cannot represent.
- **Remaining:** verified live source activation, more Nigerian/international adapters, independent application-link checks, explicit withdrawal signals, broader extraction/identity merging, AI evaluation, saved jobs/notifications, A03 employer safeguards, A10 PostgreSQL readiness and retention/supervision. Updated the saved capability tracker and operating instructions without marking the whole recruitment system complete.


## Session 2026-11-07 — Source activation and reuse scope

- **User direction:** implement the remaining live-activation requirement. The user clarified that a separate licence should not be mandatory for a government source. Recorded L81: the application accepts a documented legal basis, including applicable government-publication rules, published reuse terms or written authorization. It records staff findings rather than independently determining legal rights.
- **Gap addressed:** existing approval collected written evidence, but the collector's URL scope was configured separately and could exceed it. Added explicit collection, complete original-snapshot retention and normalized republication findings, a reuse basis and covered URL prefix. The permission reference/finding remains in the audited review event. Collector configuration cannot exceed the grant. Reapproval clears the old configuration rather than silently restoring it.
- **Runtime controls:** shared gates cover workers, ingestion, public lists and vacancy detail access. Redirect paths are checked before requesting destinations outside the grant. Expiry, missing rights and revoked approval stop collection/current listings. Stale worker results cannot save snapshots after reapproval. Discovery metadata remains distinct from approved collection. No new runtime dependency was added.
- **Staff experience:** the source page explains missing approval, rights and configuration separately from access health. The evidence form supports a legal basis without a separate licence and identifies organisation registration/licensing separately from content reuse. An enabled collector does not claim a worker is running or that an open vacancy exists.
- **Exact LSHSC research:** the local source remains `https://lshsc.ng/recruitment`, pending, unknown permissions, no collector, and `tls_error` from existing checks. Fresh curl checks inside/outside the sandbox failed certificate-chain validation. Chrome with normal certificate verification loaded general recruitment guidance with zero JobPosting records. No applicable rule, independent domain association or specific authorization was verified. Saved findings and remaining work in `docs/LSHSC_ACTIVATION_REVIEW.md`; capture `/tmp/nurse-lshsc-activation-browser.html`. No external contact, live approval or fabricated vacancy was created.
- **Migration:** `49b37f820e16` preserves all prior source values and evidence while initializing granular rights as unrecorded. Historical approvals require a renewed scope review before collection. Downgrade refuses to discard recorded reuse decisions. Trial and actual local upgrades preserved all original data across 27 tables, valid foreign keys and no schema drift. Backup: `/tmp/nurse-vacancy-migration-6vpftetr/before.db`.
- **Automated verification:** the focused recruitment/ingestion checks passed. The complete suite, including 18 additional activation and migration cases, passed **298 tests in 362.47 seconds**. Ruff and `git diff --check` passed. Tests cover legal-basis approval, absent rights, invalid scope, scope widening, expiry, reapproval, stale results, same-origin redirects, public-read gates and migration preservation.
- **Browser verification:** the first browser run could not create localhost sockets inside the sandbox; the permitted rerun passed. The full vacancy journey passed collector configuration, automatic publication, external applications, international salary display, exception review and reflow (`/tmp/nurse-ng-vacancy-browser-241up3cv`). A separate isolated source-review run passed the new legal-basis form, remaining activation blockers, exact URL preservation and mobile/desktop reflow (`/tmp/nurse-ng-activation-browser-8wm9they`). All approvals and example vacancies in these checks belong only to temporary databases. Temporary servers/browsers were stopped. This is targeted verification, not a complete accessibility audit.
