# O1 — Verification-Source Feasibility: Decision Memo

**Status:** **DRAFT — research not run. This document does not close the Phase 0 kill gate.**
**Prepared:** 21 October 2026
**Owner:** Benjamin Agogo (solo, part-time builder)
**Basis:** `docs/PHASE0_PLAN.md` workstream P1; `docs/BUILD_PLAN.md` review item 1; `Nurse_ng_Strategic_Product_Roadmap.md` §9
**Gate to close:** a lawful, reliable route is identified, or the document-only fallback is accepted with a downgraded label (K1 in `PHASE0_PLAN.md`)

> **Why this is a draft.** The harness's safety classifier was unavailable on 21 October 2026, so `WebSearch` and `WebFetch` were refused. No source was retrieved, no access date exists, and **no finding is recorded here**. Everything below section 2 is either a question to answer or a template to fill. Guessing at NMCN (Nursing and Midwifery Council of Nigeria) services from memory would manufacture the exact certainty the gate exists to test.

---

## 1. The question

> Can a nurse's professional status be checked through a lawful, reliable source — or a defensible manual procedure — at a cost the business can carry?

The memo must answer five things for every candidate route: **lawfulness**, **terms of use**, **cost**, **turnaround**, and **fallback**. It must end in one of three decisions: source-confirmed, document-only with a downgraded label, or stop.

## 2. Terms used in this memo

- **Route:** a specific mechanism by which Nurse.ng could learn a nurse's registration status. A route is not an organisation; "ask NMCN" is not a route until the mechanism is named.
- **Source-confirmed:** the status was checked against an identified, lawfully accessible authoritative source (roadmap §9). It requires recording what was checked, against which source, by whom, and when.
- **Document reviewed:** a reviewer inspected a submitted document. This does **not** establish authenticity (roadmap §9) and cannot support a "verified" claim without a downgraded label.
- **Lawful:** permitted by the source's terms of use, the nurse's consent (where required), and the Nigeria Data Protection Act 2023 (NDPA 2023). This is a counsel question, not a builder assumption.
- **Reliable:** returns a current, unambiguous status for the population in scope, with an auditable result and a defined failure mode when the source is unavailable.
- **Primary source:** NMCN's own website, portal, published regulations, fee schedule, terms of use, or written correspondence. Secondary commentary can point to a primary source but cannot substitute for it.

## 3. Candidate routes to investigate

These are **hypotheses to test**, not claims about what NMCN offers. Each must be confirmed or struck with a primary source and access date.

| ID | Route to test | What it would mean | What must be verified |
|---|---|---|---|
| R1 | NMCN public online register or verification lookup | A source-confirmed check is possible by querying an official system | Whether it exists; what it returns; whether public or login-only; terms of use; rate limits; whether it covers students, graduates, and registered nurses alike |
| R2 | NMCN formal verification at the nurse's request (letter, email, or portal request) | The nurse requests an official statement; Nurse.ng receives or reviews it | Whether the service exists; who may request; whether third parties may receive the result; fee; turnaround; format (paper/PDF/QR); revocation signalling |
| R3 | Applicant-obtained official verification report | Same as R2, but the nurse obtains and shares the result | Whether a third party can rely on it; whether it can be forged; whether it can be checked back with NMCN |
| R4 | Document review of NMCN-issued licence, certificate, or printout | Fallback only; supports "document reviewed" | What security features exist; whether a QR code or lookup can authenticate it; reviewer training and dual review; the exact label and disclaimer |
| R5 | Direct employer or HR confirmation channel with NMCN | An employer-facing route, not a Nurse.ng route | Whether NMCN confirms status to employers; what authorization is needed; whether it scales beyond a phone call |
| R6 | Third-party verification or background-check vendor | A vendor absorbs the source relationship | Whether the vendor has a lawful source, not merely a document check; coverage of NMCN status; price; audit trail; data-protection terms |

**Do not assume that a channel used for foreign regulators (for example, verification requested by an overseas nursing board) is open to a private platform.** If such a channel exists, this memo must record whether its terms permit Nurse.ng's use, and whether an employer-facing product changes the answer.

## 4. Evidence required per route

For each route, capture:

1. **The primary source** (URL, document title) and the **access date**.
2. **Exact wording** of any eligibility, consent, or prohibition clause; quote, do not paraphrase.
3. **Fee schedule**, currency, who pays, and whether it is per check or per nurse.
4. **Turnaround**: published service standard and, separately, any observed time from the ten timed cases in P5.
5. **Output format** and whether it carries a verifiable identifier.
6. **Failure mode**: what the source returns for an unknown, expired, suspended, or revoked registration.
7. **Coverage**: students, new graduates awaiting licensure, registered nurses, midwives, and nurses registered abroad.
8. **Automation boundary**: whether requests may be made by software, and the rate or volume permitted.
9. **Contract or permission**: whether written authorization from NMCN is required before a private platform may use the route.

## 5. Evaluation matrix

Fill one row per tested route. Leave blank until sourced.

| Route | Lawful? | Terms permit Nurse.ng? | Cost per check | Turnaround | Coverage | Auditability | Failure mode | Verdict |
|---|---|---|---|---|---|---|---|---|
| R1 | | | | | | | | |
| R2 | | | | | | | | |
| R3 | | | | | | | | |
| R4 | | | | | | | | |
| R5 | | | | | | | | |
| R6 | | | | | | | | |

**Verdict values:** source-confirmed · document-only (downgraded label) · rejected (state why) · unresolved (state what is missing).

## 6. Cost model

The build plan names manual review labour as the cost centre. Complete after the ten timed cases in P5.

```
cost per verified profile =
    (reviewer loaded hourly cost × median minutes per case / 60)
  + (NMCN or vendor fee per check, if any)
  + (re-check cost amortised over the re-check interval)
  + (evidence storage and support cost per case)
```

Record the median, not the mean, and record the queue time separately from the review time. A route that is lawful but cannot fit under a plausible employer price fails K3 even if it works.

## 7. Legal and privacy checklist (for Nigerian counsel)

This memo does not answer these; it hands them to counsel (P2).

- Lawful basis under the NDPA 2023 for checking status and for retaining the result.
- Whether the nurse's consent must be specific, written, and separately recorded, and whether it can be withdrawn.
- Controller registration, data protection impact assessment (DPIA), and cross-border transfer if hosting or a vendor is outside Nigeria.
- Data minimisation: store the status and its evidence, not the nurse's full credential file, unless a document is genuinely required.
- Retention period and deletion schedule (open decision O4).
- Whether NMCN's terms prohibit third-party storage or reuse of verification results.
- Breach notification duties and the response procedure.

## 8. Kill-criterion mapping

| Condition | What this memo would show | Response |
|---|---|---|
| K1: no lawful, reliable route, and document review cannot support a defensible claim | Every route rejected or unresolved | Stop, or relaunch as "document reviewed" with labels, pricing, and claims rewritten |
| K1 partial: a route exists but its terms prohibit Nurse.ng | R1/R2 exist but are closed to private platforms | Seek written authorization; if refused, treat as K1 |
| K3: cost cannot be covered | Cost model above | Stop or redesign the verification model |

## 9. Decision options

- **A — Source-confirmed.** A route passes lawfulness, terms, cost, and reliability. Commit to its exact label and evidence trail.
- **B — Document-only, downgraded.** No source route passes, but document review plus identity checks can support the label "document reviewed". Rewrite pricing and claims; never use "verified".

**Provisional implementation (21 October 2026):** at the user's direction, the software now implements a document-review workflow with the downgraded label only (DECISIONS L47–L52). This is **not** a selection of option B for O1 and does not close the gate: route research, the source log, the cost model, and counsel input are still missing. It does mean the label can already be shown once a reviewer approves a case, so the receipt wording in L47/L52 must stay accurate until the gate closes.

- **C — Stop.** Neither A nor B is defensible. The product does not launch on the current premise.

**Decision:** unresolved. No option can be selected without sources. The provisional implementation is reversible and claims no source confirmation.

## 10. Source log

| Date accessed | Source (title and URL) | What it establishes | Reliability notes |
|---|---|---|---|
| — | — | — | No source retrieved: web tooling blocked on 21 October 2026 |

## 11. Outreach and open questions

- Written question to NMCN: which verification service exists, who may request it, what it returns, what it costs, and whether a private platform may rely on it.
- Ask whether an employer or platform can obtain status with the nurse's written consent.
- Ask how revocation, suspension, and expiry are communicated to a party that checked previously.
- Ask whether students and new graduates awaiting licensure can be checked, or only registered practitioners.
- Counsel: is a consent-based check by a private platform a lawful processing operation under the NDPA 2023?

## 12. Next actions

1. When web tooling is restored, retrieve the NMCN primary sources and record every access date in section 10. Do not use secondary summaries as confirmation.
2. Send the written questions in section 11; keep copies of the responses.
3. Complete the evaluation matrix and cost model after P5's ten timed cases.
4. Record the decision (A, B, or C) in `docs/DECISIONS.md` O1 and update the verification taxonomy before any label is shown to a nurse or employer.

---

*Legal and regulatory points require qualified Nigerian counsel. This draft records a research protocol, not findings.*
