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

Backend foundation under construction. Authentication (registration, phone number + password, session login/logout), nurse profiles (creation, activation, per-field sharing, public share links), authentication hardening (per-IP login and registration throttles, account lockout, dummy-hash timing equalisation), and document review (private licence/identity evidence, a staff review queue, and a "Document reviewed" label) are implemented and verified: 104 tests pass, all six migrations are applied to the development database, Alembic reports no schema drift, and the linter is clean. Document review is not source confirmation: no NMCN (Nursing and Midwifery Council of Nigeria) register is checked, no authenticity is asserted, and no competence is assessed. Profiles are private drafts by default, activation never lists a profile in a directory, and public share links show only fields the owner explicitly marks public. Every page and link is marked not-for-indexing. The build plan's Phase 0 verification-source gate remains open, and its research is deferred by the user's direction.

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
