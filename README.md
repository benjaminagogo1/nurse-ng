# nurse-ng

A professional platform for nurses and healthcare employers, beginning in Nigeria.

## Documents

- [Strategic product roadmap](Nurse_ng_Strategic_Product_Roadmap.md) ([PDF](Nurse_ng_Strategic_Product_Roadmap.pdf))
- [Build plan](docs/BUILD_PLAN.md): review, decisions, repository structure, and phased delivery
- [Assessment baseline and completion tracker](docs/BUILD_PLAN.md#assessment-baseline-and-completion-tracker--6-november-2026): findings, closure criteria, and evidence for measuring progress
- [Community delivery progress](docs/BUILD_PLAN.md#community-delivery-progress--6-november-2026): implemented conversations, search, and discussion follows, with verification evidence
- [Build plan, designed page](docs/build-plan.html): open directly in a browser
- [Decisions and design log](docs/DECISIONS.md): agreed decisions, reasons, and trade-offs
- [Automated recruitment-source discovery](docs/AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md): research, proposed architecture, source approval, AI boundaries, and first-release acceptance criteria
- [O1 verification-source memo](docs/O1_VERIFICATION_SOURCE_MEMO.md): draft research protocol for the Phase 0 kill gate; findings pending
- [Work log](docs/WORK_LOG.md): every step, including blocked and unverified work

## Status

The current application includes the refreshed public site and member workspace, phone/password authentication and account settings, professional profiles, document review, public community discussions and media, nurse discovery and connections, employer job posting, applications, and private messaging between accepted connections. Applications require consent to share a snapshot of the applicant's contact details; private profile fields remain private. Profiles start as private drafts. Choosing “Make public” lists a profile in nurse discovery and exposes only the fields its owner marks public.

Local verification on 2 November 2026: **115 tests pass**, Ruff (Python linter) and dependency checks pass, and Alembic (database migration tool) reports no schema drift. Fresh installation, upgrades from the previous two migration heads, and downgrade/upgrade cycles are covered. The development database is backed up and upgraded to `b2c3d4e5f6a7`.

A01 verification on 6 November 2026: **152 tests pass**, including 37 production-configuration and session-cookie checks; Ruff passes. Production now requires explicit safe configuration, and unlisted hosts are rejected. A01 remains in progress until the actual deployment configuration and HTTPS/proxy behavior are verified. See the setup instructions below before starting an existing local environment.

Community delivery on 6 November 2026: **165 tests pass**. Community opens at `/feed`, where members can ask or share, respond, and search both conversations and published replies. Listings are paginated. Members can follow individual discussions and return through `/feed/discussions`, which marks new replies from others until the conversation is read. Indicators update on page load; no email or push delivery is included. A first community name can be chosen while composing, independently of professional-profile visibility. Community remains one function of the wider platform; the user has deferred A02/A04 to prioritize this work.

Targeted mobile/desktop browser checks passed for posting, replying, following, unread/read behavior, search, pagination, and display controls. The local database was backed up and upgraded to `c3d4e5f6a7b8` with existing records preserved and no schema drift. Other databases must run `./venv/bin/alembic upgrade head` before using this version. A database with no topics receives one empty General nursing category; existing topics are preserved. No member activity is seeded. See the [community work log](docs/WORK_LOG.md#session-2026-11-06--community-conversations) for verification details.

Reply pagination follow-up on 6 November 2026: **177 tests pass**. Conversations now show 20 replies per page. Click a new-reply indicator in Following discussions, or **First unread reply** inside a conversation, to jump to the first unopened reply. Only replies on a successfully rendered page are marked read; skipped pages stay unread. Each reply has a permanent link that resolves its current page, and submitting a reply opens the page containing it. Browser checks passed on mobile and desktop. The local database is now backed up and upgraded to `d4e5f6a7b8c9`, with no schema drift. Other environments need `./venv/bin/alembic upgrade head`. See [delivery evidence](docs/BUILD_PLAN.md#reply-pagination-and-unread-navigation--6-november-2026).

Draft recovery on 7 November 2026: **182 tests pass**, plus the repeatable Chrome draft checks. Questions and replies save while typing and restore when returning to the same composer in the same tab, for up to 24 hours. Each discussion has a separate reply draft. Drafts clear on explicit discard or confirmed publication; failed/interrupted submissions retain the text. Signing out clears drafts across open tabs, and changing accounts cannot restore the previous session's drafts. Files must be selected again. Closing a tab can remove its drafts; this is not cross-device storage. No additional migration is needed. See [draft delivery evidence](docs/BUILD_PLAN.md#community-draft-recovery--7-november-2026).

Reply context on 7 November 2026: **192 tests pass**. Use **Reply** beneath a response to answer that specific response; the composer shows whom you are answering and keeps your typed text when you change the selection. Published responses show a short reference with a link back, while the discussion stays chronological. Drafts preserve the selected response across pages. Removed responses no longer expose their text through references, and unavailable or cross-discussion targets cannot be used for publication. The local database was backed up and upgraded to `e5f6a7b8c9d0`, with original data and foreign keys preserved and no schema drift. Other environments need `./venv/bin/alembic upgrade head`. See [reply-context evidence](docs/BUILD_PLAN.md#replying-to-a-specific-response--7-november-2026).

Document review is not source confirmation: no NMCN (Nursing and Midwifery Council of Nigeria) register is checked, no authenticity is asserted, and no competence is assessed. Public profile responses and `robots.txt` request exclusion from search indexing. The build plan's Phase 0 verification-source gate remains open, and its research is deferred by the user's direction. Learning pages link to external resources; events and social sign-in remain placeholders.

Use the half-circle **Display and accessibility** button in the header (also available on login and registration), or the matching button in account settings, to choose System, Light, or Dark appearance, larger text, higher contrast, and reduced motion. Preferences are saved in this browser. The site respects the device's reduced-motion setting and supports keyboard navigation and forced colors. Automated accessibility checks cover the main page/theme states; assistive-technology testing and author-provided descriptions/captions for community media remain further work.

## Development

Recruitment-source discovery and staff review are now implemented. Open `/recruitment` with a staff account to manage pending sources, evidence, approvals and discovery schedules. ROR finds Nigerian and international institutions without a supplied list of hospital URLs; optional search requires configured credentials and storage permissions. The exact LSHSC source is retained. Configured approved HTML sources can now supply structured JobPosting vacancies to `/jobs`; exceptions go to `/recruitment/vacancies`. Source approval and reuse rights are required before activation. AI remains pending. The full suite passes 280 tests. See the [capability tracker](docs/AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md#implementation-progress--7-november-2026) and [operating instructions](docs/RECRUITMENT_SOURCE_OPERATIONS.md).

Activation controls on 7 November 2026: **298 tests pass**, plus isolated Chrome checks of source review and vacancy publication. Reuse scope is enforced before collection; reapproval requires collector reconfiguration. LSHSC remains pending.

After migrating, run `./venv/bin/python -m app.cli recruitment-init` once, then keep `./venv/bin/python -m app.cli recruitment-worker` running in a separate terminal alongside Uvicorn. The initialisation command is repeatable and creates pending records only. Source review accepts a documented legal basis, published terms or written authorization; a separate licence is not compulsory. Live activation enforces the recorded reuse scope. See the [LSHSC activation review](docs/LSHSC_ACTIVATION_REVIEW.md). Local schema is now `49b37f820e16`; the database was backed up and existing data preserved.

Python 3.12 is required. The verified environment is `venv/`, which is not tracked.

Before starting the application or running migrations locally, copy `.env.example` to `.env` if you do not already have one. For an existing `.env`, set `NURSE_NG_ENVIRONMENT=development` and `NURSE_NG_SESSION_HTTPS_ONLY=0` for local HTTP, and remove the old `change-me-in-development` or `insecure-dev-key-change-me` signing key. Development generates a random key when none is supplied; those sessions end on process restart. A configured key must be a randomly generated value of at least 32 characters. Tests configure their own local environment and use an isolated database.

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.lock
./venv/bin/pip install -e . --no-deps
./venv/bin/pytest
./venv/bin/ruff check .
./venv/bin/python -m app.cli check-config
./venv/bin/alembic upgrade head
```

`requirements.lock` is a pinned snapshot of the verified environment (see `docs/DECISIONS.md` L46); `pyproject.toml` remains the source of declared dependency ranges. Local overrides belong in `.env`, which is ignored by Git; `.env.example` is tracked.

Start the development server from the repository root after configuring `.env`:

```bash
./venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>, or <http://127.0.0.1:8000/feed> for community. Keep the terminal open; press Ctrl+C to stop. If startup reports an invalid signing key, check the `.env` setup above; without that file or explicit environment variables, the application defaults to production configuration.

To repeat the draft-recovery and reply-context browser checks, run `./venv/bin/python tests/browser/community_drafts.py`. The runner requires Chrome at `/usr/bin/google-chrome`, uses an isolated temporary database/server, and reports its screenshots/log directory. It exercises recovery, failed/offline submission, confirmed publication, browser Back, tab/discussion separation, expiry, blocked storage, logout, and selecting/restoring/changing a response across pages. It does not use the application database.

## Production configuration

Startup defaults to production and refuses a missing, short, or known development signing key, an empty host list, debug mode, or cookies without the Secure flag. Set the following values in the deployment environment; the signing key belongs in the deployment's secret storage:

```dotenv
NURSE_NG_ENVIRONMENT=production
NURSE_NG_DEBUG=0
NURSE_NG_SESSION_HTTPS_ONLY=1
NURSE_NG_SESSION_SAME_SITE=lax
NURSE_NG_ALLOWED_HOSTS=nurse.ng,www.nurse.ng
```

Supply `NURSE_NG_SECRET_KEY` as a cryptographically random value of at least 32 characters, shared by every worker. For example, Python's `secrets.token_urlsafe(32)` generates a suitable value; a length check alone cannot establish randomness. Rotating the key invalidates existing sessions. There is no fallback to the previous development keys.

Allowed hosts are comma-separated exact DNS names or IP addresses; schemes, ports, paths, and wildcards are rejected. Write IPv6 addresses without brackets in the setting. Host checks apply to every route, including health and static files. Configure proxies and health probes to send an allowed Host header. Serve production traffic over HTTPS; trusting proxy addresses and configuring TLS remain deployment work.

Run `./venv/bin/python -m app.cli check-config` in the actual deployment environment before startup. It validates settings and reports the environment, allowed hosts, Secure-cookie flag, and debug flag without displaying the signing key or database URL, and without connecting to the database. Verify the public HTTPS response's cookie flags and host rejection there as well; local tests do not establish the live proxy configuration.

These safeguards cover assessment item A01. Session revocation, account recovery, staff MFA, and the other readiness items remain tracked separately.

Document-review evidence is stored under `evidence/` by default (ignored by Git); set `NURSE_NG_EVIDENCE_DIR` to move it. Grant staff access to the review queue from the terminal:

```bash
./venv/bin/python -m app.cli set-staff +2348012345678
```
