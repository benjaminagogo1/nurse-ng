# nurse-ng

Verified professional infrastructure for nurses in Nigeria and beyond.

## Documents

- [Strategic product roadmap](Nurse_ng_Strategic_Product_Roadmap.md) ([PDF](Nurse_ng_Strategic_Product_Roadmap.pdf))
- [Build plan](docs/BUILD_PLAN.md): review, decisions, repository structure, and phased delivery
- [Build plan, designed page](docs/build-plan.html): open directly in a browser
- [Decisions and design log](docs/DECISIONS.md): agreed decisions, reasons, and trade-offs
- [Work log](docs/WORK_LOG.md): every step, including blocked and unverified work

## Status

Backend foundation under construction. Authentication (registration, phone number + password, session login/logout) and nurse profiles (creation, activation, per-field sharing, public share links) are implemented and verified: 67 tests pass, the initial migration is applied, Alembic reports no schema drift, and the linter is clean. Profiles are private drafts by default, activation never lists a profile in a directory, and public share links show only fields the owner explicitly marks public. Every page and link is marked not-for-indexing. The build plan's Phase 0 verification-source gate remains open, and its research is deferred by the user's direction.
