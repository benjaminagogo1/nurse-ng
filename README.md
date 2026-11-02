# nurse-ng

Verified professional infrastructure for nurses in Nigeria and beyond.

## Documents

- [Strategic product roadmap](Nurse_ng_Strategic_Product_Roadmap.md) ([PDF](Nurse_ng_Strategic_Product_Roadmap.pdf))
- [Build plan](docs/BUILD_PLAN.md): review, decisions, repository structure, and phased delivery
- [Build plan, designed page](docs/build-plan.html): open directly in a browser
- [Decisions and design log](docs/DECISIONS.md): agreed decisions, reasons, and trade-offs
- [O1 verification-source memo](docs/O1_VERIFICATION_SOURCE_MEMO.md): draft research protocol for the Phase 0 kill gate; findings pending
- [Work log](docs/WORK_LOG.md): every step, including blocked and unverified work

## Status

The current application includes the refreshed public site and member workspace, phone/password authentication and account settings, professional profiles, document review, public community discussions and media, nurse discovery and connections, employer job posting, applications, and private messaging between accepted connections. Applications require consent to share a snapshot of the applicant's contact details; private profile fields remain private. Profiles start as private drafts. Choosing “Make public” lists a profile in nurse discovery and exposes only the fields its owner marks public.

Local verification on 2 November 2026: **115 tests pass**, Ruff (Python linter) and dependency checks pass, and Alembic (database migration tool) reports no schema drift. Fresh installation, upgrades from the previous two migration heads, and downgrade/upgrade cycles are covered. The development database is backed up and upgraded to `b2c3d4e5f6a7`.

Document review is not source confirmation: no NMCN (Nursing and Midwifery Council of Nigeria) register is checked, no authenticity is asserted, and no competence is assessed. Public profile responses and `robots.txt` request exclusion from search indexing. The build plan's Phase 0 verification-source gate remains open, and its research is deferred by the user's direction. Learning pages link to external resources; events and social sign-in remain placeholders.

Use the half-circle **Display and accessibility** button in the header (also available on login and registration), or the matching button in account settings, to choose System, Light, or Dark appearance, larger text, higher contrast, and reduced motion. Preferences are saved in this browser. The site respects the device's reduced-motion setting and supports keyboard navigation and forced colors. Automated accessibility checks cover the main page/theme states; assistive-technology testing and author-provided descriptions/captions for community media remain further work.

## Development

Python 3.12 is required. The verified environment is `venv/`, which is not tracked.

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.lock
./venv/bin/pip install -e . --no-deps
./venv/bin/pytest
./venv/bin/ruff check .
./venv/bin/alembic upgrade head
```

`requirements.lock` is a pinned snapshot of the verified environment (see `docs/DECISIONS.md` L46); `pyproject.toml` remains the source of declared dependency ranges. Copy `.env.example` to `.env` for local overrides: `.env` is ignored by Git and the example is tracked.

Document-review evidence is stored under `evidence/` by default (ignored by Git); set `NURSE_NG_EVIDENCE_DIR` to move it. Grant staff access to the review queue from the terminal:

```bash
./venv/bin/python -m app.cli set-staff +2348012345678
```
