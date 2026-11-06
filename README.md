# nurse-ng

Verified professional infrastructure for nurses in Nigeria and beyond.

## Documents

- [Strategic product roadmap](Nurse_ng_Strategic_Product_Roadmap.md) ([PDF](Nurse_ng_Strategic_Product_Roadmap.pdf))
- [Build plan](docs/BUILD_PLAN.md): review, decisions, repository structure, and phased delivery
- [Assessment baseline and completion tracker](docs/BUILD_PLAN.md#assessment-baseline-and-completion-tracker--6-november-2026): findings, closure criteria, and evidence for measuring progress
- [Build plan, designed page](docs/build-plan.html): open directly in a browser
- [Decisions and design log](docs/DECISIONS.md): agreed decisions, reasons, and trade-offs
- [O1 verification-source memo](docs/O1_VERIFICATION_SOURCE_MEMO.md): draft research protocol for the Phase 0 kill gate; findings pending
- [Work log](docs/WORK_LOG.md): every step, including blocked and unverified work

## Status

The current application includes the refreshed public site and member workspace, phone/password authentication and account settings, professional profiles, document review, public community discussions and media, nurse discovery and connections, employer job posting, applications, and private messaging between accepted connections. Applications require consent to share a snapshot of the applicant's contact details; private profile fields remain private. Profiles start as private drafts. Choosing “Make public” lists a profile in nurse discovery and exposes only the fields its owner marks public.

Local verification on 2 November 2026: **115 tests pass**, Ruff (Python linter) and dependency checks pass, and Alembic (database migration tool) reports no schema drift. Fresh installation, upgrades from the previous two migration heads, and downgrade/upgrade cycles are covered. The development database is backed up and upgraded to `b2c3d4e5f6a7`.

A01 verification on 6 November 2026: **152 tests pass**, including 37 production-configuration and session-cookie checks; Ruff passes. Production now requires explicit safe configuration, and unlisted hosts are rejected. A01 remains in progress until the actual deployment configuration and HTTPS/proxy behavior are verified. See the setup instructions below before starting an existing local environment.

Document review is not source confirmation: no NMCN (Nursing and Midwifery Council of Nigeria) register is checked, no authenticity is asserted, and no competence is assessed. Public profile responses and `robots.txt` request exclusion from search indexing. The build plan's Phase 0 verification-source gate remains open, and its research is deferred by the user's direction. Learning pages link to external resources; events and social sign-in remain placeholders.

Use the half-circle **Display and accessibility** button in the header (also available on login and registration), or the matching button in account settings, to choose System, Light, or Dark appearance, larger text, higher contrast, and reduced motion. Preferences are saved in this browser. The site respects the device's reduced-motion setting and supports keyboard navigation and forced colors. Automated accessibility checks cover the main page/theme states; assistive-technology testing and author-provided descriptions/captions for community media remain further work.

## Development

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
