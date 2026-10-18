# Nurse.ng — Build Plan

**Status:** For team review
**Prepared:** 17 October 2026
**Basis:** `Nurse_ng_Strategic_Product_Roadmap.md` (v1.0)
**Scope:** Review of the proposal, technical decisions, repository design, and a 22-week path to a trust-first MVP

---

## 1. Review

### Verdict

The strategy is unusually disciplined. The scope is right, the non-goals are explicit, and the verification taxonomy is the strongest part of the document. The build risk is not the architecture. It is concentrated in one unresolved question:

> Can a nurse's professional status be checked through a lawful, reliable source, and can that review be operated at a cost the business can carry?

Everything else — labels, pricing, employer demand, growth — depends on that answer. This plan makes it a Phase 0 kill gate before any verification code is written.

### What holds up

1. **Trust-first scope.** Profiles, verification, and controlled employer contact before jobs, CPD, and mobility. The sequencing follows operational maturity rather than feature ambition.
2. **Explicit non-goals.** Not a regulator, not a licence issuer, no patient records, no unmoderated messaging. These prevent the most common failure modes in this category.
3. **A real verification taxonomy.** Self-declared, document reviewed, source-confirmed, expired, disputed, and unable to verify is already better than most marketplaces.
4. **Exit gates and a risk register.** Rare in a product proposal. The structure is correct; the thresholds are missing.
5. **Privacy designed in.** Field-level visibility, data minimisation, appeal rights, and the separation of public profiles from private evidence are treated as product requirements.
6. **Users separated from payers.** The document correctly refuses to charge nurses for basic discoverability, which protects the supply side.

### What must change before build

1. **Make verification-source feasibility a kill gate.** Phase 0 must answer: does NMCN expose a lawful verification route? Can any authoritative source be queried reliably? If the answer is "documents only", the product can still launch, but every label, price, and claim changes. Write the decision memo before schema work.
2. **Model the review labour.** Manual review is the cost centre. Time ten real cases. Measure minutes per case, queue SLA, and appeal rate. Cost per verified profile = loaded reviewer cost / cases per reviewer per day. If that number does not fit under a plausible employer price, the model fails. The roadmap names the metric but sets no target.
3. **Name the legal regime.** Nigeria Data Protection Act 2023 (NDPC): controller registration where applicable, DPIA, lawful basis, data subject rights, cross-border transfers, and breach notification. Engage Nigerian counsel in Phase 0. The privacy notice and retention schedule are build inputs, not launch polish.
4. **Replace qualitative gates with numbers.** "Evidence of repeat use" is not a gate. Agree thresholds in Phase 0 and publish them internally.
5. **Narrow the MVP to invite-only.** Public employer search is the largest abuse surface and the hardest operation to staff. Start with a curated nurse cohort and 5–8 verified employers, controlled contact requests, and no public directory. Open discovery only after abuse controls are proven.
6. **Design the verification receipt.** A badge is not trust. Every public "verified" claim needs a page stating what was checked, against which source, by whom, when, and what it does not mean. This is a product requirement, not a footnote.
7. **Add a competitive baseline.** The document says to test against competitors but names none. Document the official register, general job boards, professional associations and WhatsApp groups, recruitment agencies, and international pathway firms — plus the one workflow Nurse.ng serves better.
8. **Resolve the timeline/team mismatch.** Eight weeks to MVP is achievable with three engineers and a narrowed scope. With two engineers it is not, unless verification and moderation run on spreadsheets. Decide the team before committing the date.
9. **Establish the trust surface.** Who operates Nurse.ng, the registered entity, a physical address, a grievance officer, response SLAs, and a status page. Nurses will share identity documents; anonymity is a conversion killer.
10. **Keep one source of truth.** Treat the Markdown as canonical and generate the PDF in CI so the two cannot drift.

### Sections to add to the roadmap

- Market and competitor baseline
- Verification-source feasibility decision memo
- Data retention schedule with defaults
- Incident response and breach communications plan
- Support model (WhatsApp is the default channel for many Nigerian users)
- Accessibility and performance budget
- Data-processing register and vendor DPAs

---

## 2. Decision ledger

| # | Decision | Choice | Why | Revisit when |
|---|---|---|---|---|
| 1 | Architecture | Modular monolith: one Django project, Celery worker, Celery Beat | Team size, transactional invariants, simple audit model | Beyond ~10 engineers or independent scaling needs |
| 2 | Backend | Python, Django 5.2 LTS | Server-rendered pages, mature auth and admin, strong security defaults, Python hiring pool | A committed need for async-first services or a different runtime |
| 3 | Frontend | Django templates, HTMX, vanilla JavaScript, Tailwind CSS | Low JS payload, progressive enhancement, one deployable, no SPA build | A reviewer console or employer experience genuinely demands a SPA |
| 4 | Database | Managed PostgreSQL | Relational invariants, full-text search, JSONB, proven operations | Search outgrows Postgres FTS |
| 5 | ORM / migrations | Django ORM and migrations | Built-in, reviewable migrations, admin integration | Complex SQL or performance forces raw SQL or another ORM |
| 6 | Evidence storage | Cloudflare R2 via django-storages and boto3; private bucket, signed URLs | Cheap egress, S3 API, no public object path | Residency or procurement requires another provider |
| 7 | Background jobs | Celery + Redis; Celery Beat for expiry and rechecks | Retries, scheduling, broad ecosystem | Operational overhead too high: use RQ or Django-Q2 |
| 8 | Authentication | Django auth, custom user model, django-otp, phone OTP | Control, auditability, MFA for privileged roles | Social login is needed (django-allauth) or a managed provider saves more than four weeks |
| 9 | Search | Django `contrib.postgres` SearchVector and TrigramSimilarity, permission-aware querysets | No separate search cluster; adequate at pilot scale | Over ~100k profiles or ranking requirements grow |
| 10 | API | Server-rendered first; DRF `/api/v1` deferred until a mobile or partner client is committed | Avoids duplicating every workflow; the service layer keeps the API possible | Release 2 or a signed mobile/partner commitment |
| 11 | Hosting | Fly.io (`jnb` / `cpt`) behind Cloudflare; Gunicorn or Uvicorn, WhiteNoise | Low latency to Nigeria, cheap, Docker-portable | Compliance or procurement requires a specific region |
| 12 | Payments | Paystack (Release 2 only) | Nigerian market fit | Expansion corridors require local processors |
| 13 | SMS | Termii primary, Twilio fallback | Nigerian deliverability and sender IDs | Delivery data favours another provider |

**Frontend boundary.** HTMX handles partial updates and form submissions. Vanilla JavaScript modules handle uploads, visibility controls, and small interactions. No React or Vue in the MVP. If a console later needs a SPA, the Django service layer and a versioned API are the boundary; do not start there.

---

## 3. Architecture

One Django web application, one Celery worker, one Celery Beat scheduler, one relational database, one private object store.

- **Web app:** Django views and templates for public and authenticated pages; HTMX for partial updates; small vanilla JavaScript modules for uploads and interactions.
- **Worker:** Celery consumes Redis jobs for evidence scanning, notifications, expiry checks, and abuse signals. Beat schedules expiry and recheck tasks.
- **Database:** profiles, claims, cases, decisions, employers, requests, reports, and the append-only audit log.
- **Object storage:** evidence only. Objects are written to a quarantine prefix, scanned, then moved to a clean prefix. No public bucket and no direct object URL.
- **External services:** email, SMS, and (later) payments. Registry checks start as a documented manual procedure unless a lawful source is confirmed.

### Evidence path

1. A Django view issues a short-lived presigned upload URL.
2. File lands in the quarantine prefix; the view records `sha256`, MIME, size, and uploader.
3. A Celery task scans the object, rejects malware, re-encodes images where applicable, and moves accepted files.
4. The reviewer console requests a five-minute download URL; the read is written to the audit log.
5. A decision row is created; the claim and public projection update in one transaction.

No path exists from the public profile to an evidence object.

---

## 4. Repository structure

A single Django project with apps by domain, one Celery worker, and one Beat scheduler. No separate service yet.

```
nurse-ng/
├── README.md
├── manage.py
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── BUILD_PLAN.md
│   ├── strategy/                 # roadmap + generated PDF (move here once agreed)
│   ├── adr/                      # one file per decision in section 2
│   ├── policies/                 # verification taxonomy, retention, acceptable use, incident response
│   ├── runbooks/                 # verification queue, abuse report, restore drill
│   └── diagrams/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── test.py
│   │   └── prod.py
│   ├── urls.py
│   ├── asgi.py
│   ├── wsgi.py
│   └── celery.py
├── apps/
│   ├── core/                     # base models, UUIDs, storage helpers, middleware
│   ├── identity/                 # custom user, auth, MFA, phone verification
│   ├── profiles/                 # nurse profile, visibility, credential claims
│   ├── verification/             # cases, evidence, decisions, reviewer console
│   ├── employers/                # organizations, memberships, verification
│   ├── requests/                 # contact requests, consent, blocks
│   ├── moderation/               # reports, appeals, case management
│   ├── search/                   # permission-aware queries, projections
│   ├── notifications/            # email/SMS templates and delivery log
│   ├── audit/                    # append-only events
│   └── api/                      # DRF v1 when committed
├── templates/
│   ├── base.html
│   ├── components/               # badges, cards, HTMX partials
│   ├── marketing/                # home, trust, privacy, terms
│   ├── auth/                     # sign-in, sign-up, verify-phone, recover
│   ├── nurse/                    # dashboard, profile, verification, account
│   ├── employer/                 # dashboard, candidates, requests, organization
│   ├── reviewer/                 # verification queue, evidence, decisions
│   ├── admin/                    # admin overrides
│   └── emails/
├── static/
│   ├── css/
│   │   ├── tokens.css
│   │   └── app.css
│   ├── js/
│   │   ├── app.js
│   │   ├── upload.js
│   │   └── vendor/htmx.min.js
│   └── img/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── authz/                    # role × resource matrix
│   ├── api/                      # contract tests
│   └── e2e/                      # Playwright
├── scripts/
│   ├── create_admin.py
│   ├── export_audit.py
│   └── check_env.py
├── .github/workflows/
│   ├── ci.yml
│   ├── security.yml
│   └── deploy.yml
├── docker-compose.yml            # Postgres, Redis, MinIO, Mailpit, ClamAV
├── Dockerfile
└── .env.example
```

### Boundary rules

1. **Views compose; services decide.** `views.py` handles HTTP and template context; `services.py` holds business rules; `selectors.py` holds query logic. No business rules in templates.
2. **Apps own their models and migrations.** Cross-app access goes through services or selectors, not another app's models directly.
3. **Authorize at the boundary.** Every view and HTMX action calls `authorize(actor, action, resource)`, never only in the template.
4. **Public reads use projections.** Public profile pages use a dedicated selector. They never load evidence or private fields.
5. **Evidence stays opaque.** Storage keys are never returned to clients; signed URLs are minted server-side only.
6. **Tasks stay framework-free.** Celery tasks import services, never views or templates.
7. **Forms are adapters.** Domain validation lives in services or shared validators. Do not duplicate rules between forms, API serializers, and tasks.
8. **Templates escape by default.** Any `mark_safe` or `|safe` requires review.
9. **Custom user model from day one.** Use `identity.User` from the first migration. Never use `auth.User` directly.
10. **Uploads are hostile.** Enforce MIME, size, extension, and scan status before any processing.

---

## 5. Data model and invariants

Use a custom user model (`identity.User`) from the first migration. Changing it after data exists is painful, and Django's built-in `auth.User` is not suitable for phone-first accounts or role assignment.

| Entity | Key fields | Invariant |
|---|---|---|
| `User` | id, contact, password_hash, mfa, status | Custom user model; one active contact per account; sessions are revocable |
| `NurseProfile` | user_id, public_id, status, discoverable | One profile per user; public reads use a projection |
| `CredentialClaim` | profile_id, type, value, status | A claim never becomes verified without a decision row |
| `VerificationCase` | claim_id, state, assignee, sla_due_at | At most one open case per claim |
| `EvidenceObject` | case_id, storage_key, sha256, mime, scan_status | Never public; keys are opaque; every read audited |
| `VerificationDecision` | case_id, reviewer_id, outcome, source, rationale, decided_at | Append-only; current status is a projection |
| `EmployerOrganization` | name, cac_number, status, verified_at | Only verified organisations can contact nurses |
| `EmployerMembership` | org_id, user_id, role, scopes | Permissions are scoped per organisation |
| `ContactRequest` | employer_user_id, nurse_id, purpose, status | Requires consent; nurse can block or report |
| `ReportCase` / `AppealCase` | subject, state, assignee, sla_due_at | SLA tracked; decisions recorded with reason codes |
| `AuditEvent` | actor, action, resource, before/after, ts | Append-only; no sensitive payloads |
| `NotificationDelivery` | channel, template, status | No sensitive content in messages |

### Core invariants

- IDs are UUIDv7. A licence or registration number is never a primary key or a public identifier.
- `VerificationDecision` and `AuditEvent` are append-only. Corrections are new rows.
- Field-level visibility defaults to private. Public fields are explicitly opted in.
- Search only returns profiles where `discoverable = true`; contact details are never in search results.
- Deleting an account follows a documented workflow: revoke sessions, remove public projection, retain audit records per policy, delete evidence on schedule.
- Every state transition on a case writes an audit event in the same transaction.

### Verification states

`Draft → Submitted → Queued → In review → Source-confirmed | Document reviewed | Unable to verify`

`Source-confirmed` and `Document reviewed` can move to `Expired`. Either can enter `Appeal` and return to `In review`. `Revoked` requires a reliable source and a documented process; it is never inferred from silence.

---

## 6. Build plan

### Assumptions

- Three engineers (or two engineers plus a narrowed scope), one product/domain lead, one verification operations lead, and part-time security, privacy, and legal support.
- The team is comfortable with Python, Django, HTMX, and Tailwind. One engineer owns the reviewer console and admin customization.
- 22 weeks to the end of the closed pilot. Dates are planning estimates, not commitments.
- Verification starts manual. Automation is added only where a lawful source exists and volume justifies it.

### Phases and sprints

| Sprint | Weeks | Focus | Key output | Gate |
|---|---|---|---|---|
| S0 | 1–2 | Discovery and spikes | Interview notes, verification-source memo, competitor baseline, four technical spikes | A lawful verification route is identified, or the fallback is accepted |
| S1 | 3–4 | Synthesis and design | Data map, threat model, schema draft, numeric gates, pilot commitments | Phase 0 go/no-go |
| S2 | 5–6 | Foundation | Django project, custom user, auth, RBAC, audit primitive, Tailwind/HTMX pipeline, storage | Authz matrix v0 green |
| S3 | 7–8 | Trust core | Profiles, field visibility, claims, evidence upload, reviewer queue | Phase 1 gate |
| S4 | 9–10 | Review operations | Reviewer console, decisions, notifications, SLAs, verification receipt | Ten cases end to end |
| S5 | 11–12 | Employer side | Organisation onboarding, verification, scoped seats, shortlists | Three employers onboarded |
| S6 | 13–14 | Discovery and contact | Permission-aware search, contact requests, consent, block and report | Abuse paths tested |
| S7 | 15–16 | Hardening | Appeals, admin case management, rate limits, pen test, load test, restore drill | Phase 2 gate |
| S8 | 17–18 | Pilot launch | Cohort onboarding, support tooling, dashboards | 20 nurses / 3 employers active |
| S9 | 19–20 | Pilot run | Weekly operations review, defect fixes, cost measurement | SLAs met |
| S10 | 21–22 | Evaluation | Pilot report, unit economics, Release 2 recommendation | Go/no-go for jobs marketplace |

### Epic estimates

| Epic | Sprints | Engineer-days |
|---|---|---|
| Foundation: Django project, custom user, auth, audit, storage, observability, Tailwind/HTMX | S2 | 30 |
| Profiles and field-level visibility | S3 | 16 |
| Verification queue, reviewer console, and decisions | S4 | 18 |
| Employer onboarding and organisation verification | S5 | 8 |
| Search and contact requests | S6 | 14 |
| Moderation, appeals, admin case management | S7 | 10 |
| Data export, deletion, retention jobs | S7 | 6 |
| Hardening, performance, security fixes | S7 | 10 |
| Pilot tooling and instrumentation | S8–S10 | 25 |

**Capacity check:** the six build sprints (S2–S7) total 112 engineer-days; pilot tooling adds 25 more during weeks 17–22. Three engineers × 12 build weeks = 180 person-days, leaving roughly 38% for review, defects, and coordination. Two engineers would have 120 days, or roughly 7% buffer, which is effectively none. Staff three engineers or cut scope to a single employer segment and a manual verification spreadsheet.

### Phase 0 technical spikes

1. **Verification source:** what NMCN exposes publicly, what lawful access exists, what documents nurses can provide, and what a reviewer can reasonably check.
2. **SMS and identity:** Termii and Twilio deliverability, sender ID approval, and phone verification fallback.
3. **Low-bandwidth baseline:** measure a profile page on a mid-range Android over simulated 3G; set the budget before UI work.
4. **Reviewer console shape:** timebox a comparison of customized Django admin against a dedicated reviewer view for evidence preview, decisions, and audit. Pick one before S4.

---

## 7. Release gates, SLAs, and budgets

### Exit gates (proposed thresholds, to be agreed in Phase 0)

**Phase 0**
- Verification route documented, with a named fallback and legal sign-off.
- 15 nurse and 5 employer interviews completed.
- Pilot commitments from at least 3 employers.
- Numeric pilot gates agreed.

**Phase 1**
- Authorization matrix 100% green.
- Threat model signed off.
- Storage test proves no public read path.
- Schema reviewed; migrations reversible.
- CI green; restore drill passed.

**Phase 2**
- Zero unresolved critical or high security findings.
- p95 candidate search under 800 ms at pilot scale.
- Public profile LCP under 3 seconds on simulated 3G; initial JS under 100 KB gzipped.
- Every high-impact action produces an audit event.
- Pen-test findings closed or formally accepted.
- Runbooks exercised by someone other than their author.

**Phase 3**
- 40+ nurses onboarded, 5+ employers active.
- Median verification decision within 3 business days.
- 20+ consent-based contacts; 25%+ nurse response rate.
- 3+ employers willing to pay or sign a paid pilot.
- Cost per verified profile measured and inside the target derived from pricing.
- Zero reportable data incidents.

### Service levels (pilot stage)

| Workflow | Target |
|---|---|
| Verification first response | 1 business day |
| Verification decision | 3 business days median |
| Serious abuse report acknowledged | 4 hours |
| Abuse action taken | 24 hours |
| Appeal decision | 5 business days |
| Data rights request | 30 days (confirm statutory period with counsel) |
| Incident acknowledged internally | 1 hour |

### Performance budget

- Initial JS on public profile pages: ≤ 100 KB gzip, including HTMX and app modules.
- No SPA framework in the MVP. Server-rendered pages with HTMX partials first.
- LCP: ≤ 3 s on a mid-range Android over Slow 4G.
- TTFB from Lagos: ≤ 800 ms.
- No web font blocks first render; system fallback first.
- Public profile and sign-in degrade gracefully without JavaScript.

### Cost model to instrument from day one

- Minutes per verification case.
- Cases per reviewer per day.
- Cost per verified profile.
- Support and moderation minutes per active user.
- Employer acquisition cost and revenue per paying employer.
- Fraud and refund cost per listing.
- Gross margin after verification and moderation.

---

## 8. First 10 working days

1. Name accountable owners for product, verification operations, security, and legal.
2. Write the verification-source feasibility memo and its kill criterion.
3. Brief Nigerian counsel on NDPA 2023, evidence handling, and cross-border hosting.
4. Interview 15 nurses and 5 employers; time ten manual verification cases.
5. Draft the data map, retention defaults, and privacy notice outline.
6. Stand up the repo, CI, local Docker stack, and secret management.
7. Draft schema v1 and the authorization matrix.
8. Define the verification receipt fields and wording.
9. Agree numeric pilot gates and the pilot cohort.
10. Book the day-30 go/no-go review.

### Open decisions for the team

- Which nurse segment first: new graduates, experienced clinicians, or international aspirants?
- Which employer segment first: hospitals, home care, or recruiters?
- Is launch verification document-based or source-confirmed?
- Which legal entity operates the platform?
- Are three engineers available?
- Is public search in the MVP, or invite-only discovery?
- What monthly budget is available for verification operations and counsel?

---

## Appendix: tools

| Area | Choice | Note |
|---|---|---|
| Language | Python (current stable), Django 5.2 LTS | Server-rendered, batteries included |
| Templates | Django templates | HTML-first; no separate frontend build |
| Interactivity | HTMX, vanilla JavaScript modules | Partial updates and small interactions |
| CSS | Tailwind CSS (standalone CLI), design tokens | Utility CSS without a Node dependency |
| Database | Managed PostgreSQL 16+ | Neon, Supabase, or RDS |
| ORM | Django ORM and migrations | Built-in |
| Auth | Django auth, custom user model, django-otp | Phone OTP via Termii/Twilio |
| Validation | Django forms, DRF serializers, shared validators | Adapters over domain rules |
| API | Django REST Framework + drf-spectacular (deferred) | When a mobile or partner client is committed |
| Evidence storage | Cloudflare R2 via django-storages and boto3 | Private bucket, presigned URLs |
| Malware scanning | ClamAV via a Celery task | Quarantine then clean |
| Jobs | Celery + Redis; Celery Beat | Scan, notify, expire, detect |
| Email | django-anymail with Resend or Postmark | Django templates for email |
| SMS | Termii primary, Twilio fallback | |
| Search | Django `contrib.postgres` SearchVector, TrigramSimilarity | Permission-aware querysets |
| Errors | Sentry SDK with PII scrubbing | |
| Logs / metrics | structlog, OpenTelemetry, Grafana Cloud or Better Stack | Structured and redacted |
| Product analytics | PostHog, EU or self-hosted | No sensitive fields |
| Tests | pytest, pytest-django, factory_boy, Playwright, axe-core, Locust | |
| CI security | Ruff, mypy with django-stubs, Bandit, pip-audit, Gitleaks, CodeQL | |
| Dependencies | uv with `pyproject.toml` | |
| Hosting | Fly.io + Cloudflare; Gunicorn or Uvicorn, WhiteNoise | `jnb` / `cpt` regions |
| Local dev | Docker Compose: Postgres, Redis, MinIO, Mailpit, ClamAV | |
| Payments | Paystack (Release 2) | |
| Docs | Markdown + ADRs, PDF generated in CI | |

---

*Legal and regulatory points are for qualified Nigerian counsel to confirm. Timeline, staffing, and cost figures are planning estimates, not commitments.*
