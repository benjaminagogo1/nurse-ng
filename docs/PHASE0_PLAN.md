# Nurse.ng — Phase 0 Plan (Revised for Solo, Part-Time Build)

**Status:** Working plan
**Prepared:** 18 October 2026
**Basis:** `BUILD_PLAN.md`, `DECISIONS.md` (D1–D6)
**Purpose:** Answer the build plan's kill-gate question before any application code is written.

---

## 1. The question Phase 0 must answer

> Can a nurse's professional status be checked through a lawful, reliable source — or a defensible manual procedure — at a cost the business can carry?

Everything else depends on the answer. Phase 0 exists to produce evidence, not software.

---

## 2. Constraints

- One person, 10–20 hours per week.
- Public hospitals are the target employer segment, but there is no existing access. Procurement is slow and the budget may not be discretionary.
- New graduates are the target nurse segment. They are the highest-risk group for recruitment scams and the lowest-ability-to-pay group.
- A defined Phase 0 budget exists for counsel and manual verification support.
- No application may be built until the gate closes.

**Capacity reality:** the build plan's S2–S7 is 112 engineer-days (~900 hours). At 15 hours per week that is roughly 60 weeks of building before review and defects. Software is therefore the _last_ thing Phase 0 produces, not the first.

---

## 3. Approach: concierge pilot before software

Run the pilot manually:

1. Recruit ~20 new-graduate nurses.
2. Verify their status by hand, using the most reliable lawful method available; time every case.
3. Approach public hospitals; secure at least 3 written pilot commitments.
4. Match candidates to employers manually with explicit consent, using a spreadsheet and email.
5. Measure time, cost, response rates, and abuse reports.
6. Build the Django application only for workflows that survive this contact with users.

If the pilot cannot find 3 employers or cannot verify a nurse at a bearable cost, software would not have saved it — it would only have hidden the problem longer.

---

## 4. Workstreams

| #   | Workstream                                      | Output                                                                                                                                                                                 | Gate                                                                                     |
| --- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| P1  | **Verification-source feasibility** (kill gate) | Decision memo: lawful route(s), terms of use, cost, turnaround, fallback, and kill criterion                                                                                           | A route is identified, or the document-only fallback is accepted with a downgraded label |
| P2  | **Legal and privacy**                           | Counsel brief and opinion on NDPA 2023 (lawful basis, controller registration, DPIA, retention, cross-border hosting, breach); data map; privacy notice outline; retention schedule v0 | Counsel confirms the manual pilot's evidence handling is lawful                          |
| P3  | **Employer access** (critical path)             | Map public-hospital decision-makers (federal and state); outreach log; ≥3 written pilot commitments                                                                                    | 3 signed commitments                                                                     |
| P4  | **Nurse discovery and cohort**                  | 15 nurse interviews synthesised; ~20 nurses recruited; willingness-to-submit tested                                                                                                    | ≥10 of 20 recruited nurses complete verification                                         |
| P5  | **Manual verification operations**              | Written review procedure v1; 10 cases timed end to end; cost per verified profile                                                                                                      | Median decision ≤ 3 business days at measured cost                                       |
| P6  | **Concierge pilot design**                      | Consent and matching protocol; contact rules; reporting and abuse procedure; record-keeping and evidence handling                                                                      | Protocol reviewed against P2 advice                                                      |
| P7  | **Minimal tooling only**                        | Encrypted evidence store with MFA and access log; intake form; tracking sheet; no application code                                                                                     | No public read path to evidence; access logged                                           |
| P8  | **Gates and metrics**                           | Numeric pilot gates agreed and written down                                                                                                                                            | Gate sheet signed off                                                                    |

**Single-owner reality:** all eight workstreams are one person's. P1, P2, P3, and P4 can be interleaved; P3 has the longest lead time and should start first.

---

## 5. Sequence and indicative timing

Part-time (≈15 h/week). Dates are planning estimates, not commitments.

| Weeks | Focus                                                                                                    |
| ----- | -------------------------------------------------------------------------------------------------------- |
| 1–4   | P1 research begins; P2 counsel engaged; P3 employer mapping and first outreach; P4 interview recruitment |
| 5–8   | P4 interviews (15 nurses, 5 employers); P1 memo drafted; P5 procedure drafted                            |
| 9–12  | P5 ten cases timed; P6 pilot protocol; P2 privacy notice outline and retention schedule                  |
| 13–16 | P3 commitments secured; P4 cohort confirmed; P8 gates agreed; go/no-go                                   |

**Estimate: 16 weeks (4 months) part-time, dominated by employer lead time.** If public-hospital procurement is slower, the gate moves; the plan does not compress to fit a calendar.

---

## 6. Kill criteria

| #   | Condition                                                                                                            | Response                                                                                             |
| --- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| K1  | No lawful, reliable verification route exists, and counsel advises document review cannot support a "verified" claim | Stop, or relaunch the product as "document reviewed" only with labels, pricing, and claims rewritten |
| K2  | Fewer than 3 public hospitals will commit to a written pilot after the outreach window                               | Do not build. Continue discovery, or reconsider the employer segment                                 |
| K3  | Measured cost per verified profile cannot be covered by a plausible employer price                                   | Stop or redesign the verification model                                                              |
| K4  | Counsel finds the evidence handling or cross-border hosting unlawful without changes the project cannot afford       | Stop, or adopt a reduced-data design                                                                 |
| K5  | Fewer than 10 of 20 recruited nurses complete verification                                                           | Demand or trust problem; do not build                                                                |
| K6  | Any reportable data incident during the pilot                                                                        | Pause, review, and correct before continuing                                                         |

---

## 7. Numeric gates to confirm during Phase 0

- 15 nurse interviews and 5 employer interviews completed.
- ≥3 written employer pilot commitments.
- ≥20 nurses recruited; ≥15 complete a profile; ≥10 verified.
- 10 verification cases timed; cost per verified profile calculated.
- Median verification decision ≤ 3 business days.
- Zero unresolved reportable data incidents.

These replace the build plan's qualitative gates, which it flags as insufficient.

---

## 8. What is deliberately not built

- Product workflows: profiles, verification cases, evidence handling, employer records, requests, moderation.
- Public search, directory, or ranking.
- Reviewer console.
- Payments, job listings, CPD, community, or mobility features.
- API and mobile client.

The repository holds documents plus a FastAPI foundation (`app/` package, SQLAlchemy models, Alembic configuration, templates, tests) started on 18 October 2026 before this gate, recorded as D7 and D9 in `DECISIONS.md`. It implements no product workflow and is not a gate pass. Product code begins only after the Phase 0 gate is passed.

---

## 9. Immediate next actions

1. Re-run verification-source research when web tooling is restored; record sources with access dates.
2. Engage Nigerian counsel with a scoped brief: NDPA 2023, evidence handling, retention, cross-border hosting, and the manual pilot's lawful basis.
3. Identify public hospitals and their hiring/HR decision-makers; start outreach.
4. Recruit 15 new-graduate nurses for interviews and ~20 for the pilot cohort.
5. Draft the manual verification procedure and the evidence-handling rules for P7.

---

_Legal and regulatory points require qualified Nigerian counsel. Timing, staffing, and cost figures are planning estimates._
