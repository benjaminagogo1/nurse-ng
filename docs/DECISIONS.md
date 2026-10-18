# Nurse.ng — Decision Record

**Status:** Agreed decisions from the 18 October 2026 working session
**Basis:** `Nurse_ng_Strategic_Product_Roadmap.md` (v1.0), `BUILD_PLAN.md`
**Scope:** Decisions that change the build plan's assumptions. This file is the running log; append new decisions, never rewrite history.

---

## Agreed decisions

| # | Decision | Choice | Why | Revisit when |
|---|---|---|---|---|
| D1 | Build capacity | Solo builder, part-time (10–20 h/week), with AI assistance | Current reality. The build plan's 112 engineer-day MVP does not fit; at ~15 h/week the full S2–S7 build is roughly 60 weeks before review and defects | A second engineer joins, or the builder goes full-time |
| D2 | First nurse segment | New graduates | Sharpest need to establish status and find a first role; recent registration makes document review tractable | Pilot shows low willingness to engage, or employers prefer experienced hires |
| D3 | First employer segment | Public hospitals | Volume, legitimacy, and a strong trust signal for new graduates | Employer outreach produces no commitments within the Phase 0 window, or procurement proves unworkable |
| D4 | Discovery model | Invite-only pilot; no public directory | Build plan's explicit MVP recommendation; smallest abuse surface; staffable by one person. New graduates are a prime scam target | Abuse controls are proven and operations can be staffed |
| D5 | Employer access | None yet; willing to pursue | No existing relationships. Employer recruitment is therefore the critical path from day one | First public-hospital contact is established |
| D6 | Phase 0 budget | Defined budget available for counsel and manual verification support | Legal and verification assumptions can be tested rather than deferred | Budget is consumed or withdrawn |
| D7 | Backend start | A Django foundation was built and then deleted on 18 October 2026; a FastAPI foundation replaced it before the Phase 0 gate closes | Builder's direction. Recorded as an accepted risk, not a gate pass: if Phase 0 fails, this code is a liability rather than an asset | Phase 0 gate review |
| D8 | Development environment | uv for dependencies; SQLite for development and tests; PostgreSQL deferred | Fastest start while shell tooling was unavailable. Postgres-specific behaviour is untested | Before any pilot data is stored |
| D9 | Backend framework | FastAPI with Jinja2 templates and HTMX; SQLAlchemy 2 + Alembic; pwdlib with Argon2 | Builder's choice, overriding the build plan's Django decision. Supersedes decision-ledger #2, #3, #5, and #8 in `BUILD_PLAN.md` | If assembled auth, admin, or migration tooling costs more than the framework saves, or a Django-strength admin becomes necessary |

### Consequences

- **No custom reviewer console.** Django admin plus a documented procedure, if software is built at all.
- **No public search.** Invite-only discovery means search is not required to start; matching can be manual.
- **Concierge before software.** A manual pilot (spreadsheet, encrypted evidence store, email) tests verification cost, employer demand, and nurse supply before ~900 hours of build.
- **Early backend start.** At the builder's direction, a backend foundation was started on 18 October 2026 before the Phase 0 gate (D7). The Django version was deleted and replaced with FastAPI (D9). It implements no product workflow and does not count as a gate pass.
- **Employer recruitment starts immediately.** Public-hospital procurement is the longest-lead item and gates the pilot.
- **Status taxonomy must distinguish** student, graduate awaiting licensure, and registered nurse. A new graduate is not one undifferentiated category.

---

## Open decisions

| # | Decision | Status | Blocker |
|---|---|---|---|
| O1 | Launch verification: document-based or source-confirmed | Open | Verification-source research is incomplete (tooling outage); memo required first |
| O2 | Legal entity that operates the platform | Open | Needs counsel input; affects NDPA controller registration and trust surface |
| O3 | Numeric pilot gates and cost-per-verified-profile target | Open | Requires ten timed manual cases before a target can be set |
| O4 | Evidence retention period and deletion schedule | Open | Needs counsel input for NDPA 2023 |
| O5 | Whether the concierge pilot stores identity documents at all | Open | Depends on O1 and counsel advice; minimum-data option is registration number plus certificate image |

---

## Notes on this session

- Verification-source feasibility remains **unresearched**. No web sources were available during the session; nothing here should be read as a finding about NMCN's services.
- The roadmap's Phase 4–6 (jobs, community, international mobility) remain out of scope and are not affected by these decisions.
- These decisions revise the build plan's assumptions; `BUILD_PLAN.md` itself has not been edited. A revision should be made once Phase 0 closes, not before.
