# nurse-ng

A professional platform for nurses and healthcare employers, beginning in Nigeria.

## Documents

- [Video likes, visibility and administrator management](docs/ENGAGEMENT_AND_ADMIN.md).
- [Employer approval and private evidence operations](docs/EMPLOYER_AND_EVIDENCE_OPERATIONS.md) — required migration, scanner, retention timer and legacy review.
- [Offline reading, drafts and sync](docs/OFFLINE.md) — supported actions, resumable Reel uploads, storage limits and setup.
- [App quality and device verification](docs/QUALITY_VERIFICATION.md).
- [Community events](docs/EVENTS.md) — publishing, RSVPs and calendar downloads.
- [Google and LinkedIn sign-in](docs/SOCIAL_SIGN_IN.md) — implementation and provider setup.

- [Interactive onboarding tour](docs/ONBOARDING_TOUR.md) — walkthrough, saved progress, role-specific steps and restart.

- [User analytics, unique IDs and daily activity](docs/MEMBER_ANALYTICS.md).

- [Nigerian opportunity coverage, saves and alerts](docs/NIGERIAN_OPPORTUNITIES.md).

- [Notifications and messaging](docs/NOTIFICATIONS.md) — inbox, preferences, live conversations and email-worker operations.

- [Strategic product roadmap](Nurse_ng_Strategic_Product_Roadmap.md) ([PDF](Nurse_ng_Strategic_Product_Roadmap.pdf))
- [Seven priorities for a world-standard app](docs/WORLD_STANDARD_ROADMAP.md): remaining work, current foundations, and recommended delivery order, recorded on 8 November 2026
- [Build plan](docs/BUILD_PLAN.md): review, decisions, repository structure, and phased delivery
- [Assessment baseline and completion tracker](docs/BUILD_PLAN.md#assessment-baseline-and-completion-tracker--6-november-2026): findings, closure criteria, and evidence for measuring progress
- [Community delivery progress](docs/BUILD_PLAN.md#community-delivery-progress--6-november-2026): implemented conversations, search, and discussion follows, with verification evidence
- [Build plan, designed page](docs/build-plan.html): open directly in a browser
- [Decisions and design log](docs/DECISIONS.md): agreed decisions, reasons, and trade-offs
- [Automated recruitment-source discovery](docs/AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md): research, proposed architecture, source approval, AI boundaries, and first-release acceptance criteria
- [O1 verification-source memo](docs/O1_VERIFICATION_SOURCE_MEMO.md): draft research protocol for the Phase 0 kill gate; findings pending
- [Work log](docs/WORK_LOG.md): every step, including blocked and unverified work

## Status

**Offline & sync** now supports selected saved information, explicit contribution
drafts and queued changes, with resumable Reel uploads. Upgrade through
`e6480c2ea831` before serving this version. Saved work survives tab and browser
closure in the same browser profile and sign-in session. Reopen and reconnect to
resume pending sends; signing out clears private offline data. See the
[offline guide](docs/OFFLINE.md) for supported behavior and verification.

Staff can monitor account IDs, daily active users, recent activity, 7/30-day
participation and daily history at `/staff/users` (**Staff → User analytics**).
Users can copy their own ID in Settings. Counts use Nigeria's calendar day and
exclude staff by default. History starts with recorded visits after installation;
upgrade to schema `d537f982ac14` before running this version. See
[user analytics](docs/MEMBER_ANALYTICS.md) for definitions and access controls.

The current application includes the refreshed public site and member workspace, phone/password authentication and account settings, professional profiles, document review, public community discussions and media, nurse discovery and connections, employer job posting, applications, and private messaging between accepted connections. Applications require consent to share a snapshot of the applicant's contact details; private profile fields remain private. Profiles start as private drafts. Choosing “Make public” lists a profile in nurse discovery and exposes only the fields its owner marks public.

Account settings now includes profile photo upload, email verification and permanent account deletion. **Forgot password** sends a reset link to a verified email address; real delivery requires SMTP configuration. Photos start private, and password resets revoke existing sessions. See [account features and email setup](docs/ACCOUNT_MANAGEMENT.md). Upgrade to schema `7bd28ea64c10` before running this version.

Account-feature verification on 8 November 2026: **390 tests passed**, plus isolated Chrome account flows at mobile and desktop widths. Account actions now show visible success/error cards, pending button labels and field errors, with results brought below the header. Settings retains verified-email and photo-privacy status. The local database is upgraded with existing records preserved. Brevo SMTP is enabled locally and verified TLS/authentication passed. After correcting the configured sender to the identity verified in Brevo, the user received the email and completed verification. A database check confirmed the account is verified and the single-use link was consumed. Deployed environments need their own email configuration and public URL.

Local verification on 2 November 2026: **115 tests pass**, Ruff (Python linter) and dependency checks pass, and Alembic (database migration tool) reports no schema drift. Fresh installation, upgrades from the previous two migration heads, and downgrade/upgrade cycles are covered. The development database is backed up and upgraded to `b2c3d4e5f6a7`.

A01 verification on 6 November 2026: **152 tests pass**, including 37 production-configuration and session-cookie checks; Ruff passes. Production now requires explicit safe configuration, and unlisted hosts are rejected. A01 remains in progress until the actual deployment configuration and HTTPS/proxy behavior are verified. See the setup instructions below before starting an existing local environment.

Community delivery on 6 November 2026: **165 tests pass**. Community opens at `/feed`, where members can ask or share, respond, and search both conversations and published replies. Listings are paginated. Members can follow individual discussions and return through `/feed/discussions`, which marks new replies from others until the conversation is read. Indicators update on page load; no email or push delivery is included. A first community name can be chosen while composing, independently of professional-profile visibility. Community remains one function of the wider platform; the user has deferred A02/A04 to prioritize this work.

Targeted mobile/desktop browser checks passed for posting, replying, following, unread/read behavior, search, pagination, and display controls. The local database was backed up and upgraded to `c3d4e5f6a7b8` with existing records preserved and no schema drift. Other databases must run `./venv/bin/alembic upgrade head` before using this version. A database with no topics receives one empty General nursing category; existing topics are preserved. No member activity is seeded. See the [community work log](docs/WORK_LOG.md#session-2026-11-06--community-conversations) for verification details.

Reply pagination follow-up on 6 November 2026: **177 tests pass**. Conversations now show 20 replies per page. Click a new-reply indicator in Following discussions, or **First unread reply** inside a conversation, to jump to the first unopened reply. Only replies on a successfully rendered page are marked read; skipped pages stay unread. Each reply has a permanent link that resolves its current page, and submitting a reply opens the page containing it. Browser checks passed on mobile and desktop. The local database is now backed up and upgraded to `d4e5f6a7b8c9`, with no schema drift. Other environments need `./venv/bin/alembic upgrade head`. See [delivery evidence](docs/BUILD_PLAN.md#reply-pagination-and-unread-navigation--6-november-2026).

Automatic community draft recovery on 7 November 2026: **182 tests pass**, plus the repeatable Chrome draft checks. Questions and replies save while typing and restore when returning to the same composer in the same tab, for up to 24 hours. Each discussion has a separate reply draft. Drafts clear on explicit discard or confirmed publication; failed/interrupted submissions retain the text. Signing out clears drafts across open tabs, and changing accounts cannot restore the previous session's drafts. Files must be selected again. Closing a tab can remove its drafts; this is not cross-device storage. No additional migration is needed. See [draft delivery evidence](docs/BUILD_PLAN.md#community-draft-recovery--7-november-2026).

Use **Save draft locally** for the [durable offline copy](docs/OFFLINE.md) added on
9 November, which survives normal tab and browser closure.

Reply context on 7 November 2026: **192 tests pass**. Use **Reply** beneath a response to answer that specific response; the composer shows whom you are answering and keeps your typed text when you change the selection. Published responses show a short reference with a link back, while the discussion stays chronological. Drafts preserve the selected response across pages. Removed responses no longer expose their text through references, and unavailable or cross-discussion targets cannot be used for publication. The local database was backed up and upgraded to `e5f6a7b8c9d0`, with original data and foreign keys preserved and no schema drift. Other environments need `./venv/bin/alembic upgrade head`. See [reply-context evidence](docs/BUILD_PLAN.md#replying-to-a-specific-response--7-november-2026).

Document review is not source confirmation: no NMCN (Nursing and Midwifery Council of Nigeria) register is checked, no authenticity is asserted, and no competence is assessed. Public profile responses and `robots.txt` request exclusion from search indexing. The build plan's Phase 0 verification-source gate remains open, and its research is deferred by the user's direction. Learning pages link to external resources. Community events now support staff publishing, RSVPs and calendar downloads. Google and LinkedIn sign-in integrations require provider credentials and callback configuration before live use.

Use the half-circle **Display and accessibility** button in the header (also available on login and registration), or the matching button in account settings, to choose System, Light, or Dark appearance, larger text, higher contrast, and reduced motion. Preferences are saved in this browser. The site respects the device's reduced-motion setting and supports keyboard navigation and forced colors. Automated accessibility checks cover the main page/theme states; assistive-technology testing and author-provided descriptions/captions for community media remain further work.

## Development

Recruitment-source discovery and staff review are now implemented. Open `/recruitment` with a staff account to manage pending sources, evidence, approvals and discovery schedules. ROR finds Nigerian and international institutions without a supplied list of hospital URLs; general search uses configured self-hosted SearXNG instances without API keys, with optional Brave API fallback. The exact LSHSC source is retained. Configured approved HTML sources can now supply structured JobPosting vacancies to `/jobs`; exceptions go to `/recruitment/vacancies`. Sources that pass automatic evidence checks activate and configure their collectors without staff approval; uncertain cases show reasons for review. Staff decisions remain authoritative. AI remains pending. See the [capability tracker](docs/AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md#implementation-progress--7-november-2026) and [operating instructions](docs/RECRUITMENT_SOURCE_OPERATIONS.md).

Staff can also use **Approve and start vacancy collection** on a source page to
enable factual listings and original announcement links in one step. The decision
records staff source selection; full-description reuse remains a separate approval.
Keep the recruitment worker running so collection, validation and publication can
complete. See [the combined approval workflow](docs/RECRUITMENT_SOURCE_OPERATIONS.md#approve-and-start-collection--10-november-2026).

Use the [worker supervisor and readiness checks](docs/WORKER_OPERATIONS.md) for
continuous collection and Reels processing. Run `venv/bin/alembic upgrade head`
before starting the supervisor; revision `e6480d3fb942` records worker progress.
The recruitment dashboard links directly to pending vacancy reviews and shows
worker health separately from historical task failures. Factual collection now
captures explicitly stated remuneration and holds repeated announcements as one
review; existing review queues can be reconciled with an audited cleanup command.

Nigerian opportunities take priority in the jobs feed, source registry and worker queue. Coverage includes government/private health roles and Nigerian youth fellowships, internships and graduate programmes across sectors; international opportunities remain accessible. Repeat `recruitment-init` to add pending local starter sites and update the original worldwide directory schedule from daily to weekly. Source registration does not establish a current opening; structured vacancy and source evidence checks still apply.

Previous verification on 7 November 2026: **298 tests pass**, plus isolated Chrome checks of source review and vacancy publication. Reuse scope is enforced before collection; reapproval requires collector reconfiguration. LSHSC remains pending.

After migrating, run `./venv/bin/python -m app.cli recruitment-init` once, then keep `./venv/bin/python -m app.cli recruitment-worker` running in a separate terminal alongside Uvicorn. The initialisation command is repeatable and creates pending records only. Source review accepts a documented legal basis, published terms or written authorization; a separate licence is not compulsory. Live activation enforces the recorded reuse scope. See the [LSHSC activation review](docs/LSHSC_ACTIVATION_REVIEW.md). Upgrade to schema `6a21d8e40c93` for automatic activation. Existing staff decisions are preserved; pending candidates are assessed by the worker.

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

Reels are available at <http://127.0.0.1:8000/reels>. Migrate to `8cf309b2a176`, install the updated dependencies, and keep `venv/bin/python -m app.cli reels-worker` running alongside the web server. Uploads remain private until this worker creates playback versions and a cover image. See [Reels operations](docs/REELS.md) for processing, captions, testing and the remaining storage/CDN deployment requirements.

Notifications are available at <http://127.0.0.1:8000/notifications>. Final notification/messaging verification: **441 tests passed**, plus isolated mobile/desktop browser and CLI-worker checks. Run `venv/bin/alembic upgrade head` (current revision `ae5314d8c902`) and keep `venv/bin/python -m app.cli notification-worker` running for opted-in email alerts. The inbox and automatic message updates work through the web application; email defaults off. See [notification operations](docs/NOTIFICATIONS.md).

To repeat the draft-recovery and reply-context browser checks, run `./venv/bin/python tests/browser/community_drafts.py`. The runner requires Chrome at `/usr/bin/google-chrome`, uses an isolated temporary database/server, and reports its screenshots/log directory. It exercises recovery, failed/offline submission, confirmed publication, browser Back, tab/discussion separation, expiry, blocked storage, logout, and selecting/restoring/changing a response across pages. It does not use the application database.

Automatic activation added on 8 November 2026: fresh matching ROR evidence, an official HTTPS recruitment link and supported page-level reuse terms can activate a source without staff approval. Staff decisions remain protected. Other evidence formats stay in review with reasons; see [automatic policy and limits](docs/RECRUITMENT_SOURCE_OPERATIONS.md#automatic-activation). Verification: 331-test full regression run, then 64 focused activation/ingestion checks after the final refinements; 333 cases are now collected. The local schema upgrade preserved all original data across 27 tables.

LSHSC TLS compatibility added on 8 November 2026: a verified intermediate certificate bundled only for its two hostnames fixes the missing server chain while preserving full certificate/hostname checks. The installed fetcher received HTTP 200; the page still contained no structured vacancies. See the [updated source review](docs/LSHSC_ACTIVATION_REVIEW.md#tls-compatibility-update--8-november-2026).

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

These safeguards cover assessment item A01. Password-reset session revocation and verified-email recovery are now implemented; production email setup, staff MFA and the other readiness items remain tracked separately.

Document-review evidence is stored under `evidence/` by default (ignored by Git); set `NURSE_NG_EVIDENCE_DIR` to move it. Grant staff access to the review queue from the terminal:

```bash
./venv/bin/python -m app.cli set-staff +2348012345678
```

Members can save opportunities, set matching interests and choose deadline reminders from the Jobs page. The notification worker generates these alerts; email remains optional. Source operators can select the ordinary-announcement collector and inspect `/recruitment/coverage`. See [Nigerian opportunity operations](docs/NIGERIAN_OPPORTUNITIES.md) for setup and live-coverage limits.

Search and automatic factual indexing updated on 9 November 2026: SearXNG works through the Python worker without a Brave key, with instance failover and independent direct monitoring. Verified government sources and authoritative publisher links can activate factual listings without full-content reuse permission. See [search deployment and operations](docs/SEARCH_DISCOVERY.md).
