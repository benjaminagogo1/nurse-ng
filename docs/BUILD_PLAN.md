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

---

## Current product and engineering assessment — 2 November 2026

This section records the complete assessment at the user's request. The earlier plan is preserved as originally written; its proposed Django stack and invite-only approach are historical proposals, while the current application uses FastAPI and open registration. Recommendations below are proposed work, not completed implementation or newly approved technical decisions. Test and accessibility results refer to the prior verification recorded in [WORK_LOG.md](WORK_LOG.md#session-2026-11-02--dark-mode-and-accessibility); they were not rerun for this documentation update.

**I would assess Nurse.ng as a functional early-stage product with a sound foundation. It needs stronger trust controls, operational reliability, and evidence from real users before an unrestricted public launch.**

The progress is substantial: profiles, applications, messaging, community, document review, and accessibility controls work together. We have 115 passing tests and encouraging accessibility results. Those establish useful evidence about tested behavior; they do not yet establish production security, performance under load, or market demand.

Here is my assessment:

| Area | Current position | What would raise the standard |
|---|---|---|
| User experience | Coherent design, responsive pages, useful accessibility controls | Usability testing with nurses on real phones and unreliable connections |
| Architecture | FastAPI, clear domain models, services, routes, and migrations | More consistent business-rule enforcement and concurrency testing |
| Privacy | Private profiles, explicit sharing, application consent, restricted evidence access | Complete retention, deletion, recovery, and audit procedures |
| Trust | Document-review labels distinguish review from source confirmation | Employer checks, job legitimacy controls, appeals, and transparent review standards |
| Reliability | Automated tests and migration checks | Monitored deployments, tested restores, rollback procedures, and load testing |
| Product value | Several useful workflows exist | Evidence that nurses return and employers produce meaningful outcomes |

What would make it world-class, in my judgment, is the following work—in this order.

1. **Make trust the strongest part of the product.**

   An employer account currently gains posting access through its selected account type. That does not establish that the organization or vacancy is legitimate.

   I would introduce organization checks, accountable employer representatives, job reporting, listing expiry, and a clear response process for suspected scams. Nurses should understand who is requesting their information and why.

   Professional claims also need precise boundaries. “Document reviewed” must continue to mean exactly that. Any future claim of source confirmation needs a lawful, reliable source and a dated record of the check.

2. **Complete account security and recovery before collecting more sensitive information.**

   The source configuration still permits development defaults, including a development signing key and cookies without the secure-only setting. These are appropriate for local development, but production should refuse to start with unsafe settings. See [config.py](../app/core/config.py#L14).

   There is also an important distinction from our earlier session discussion: remaining signed in is normal, but **revoking access is a separate requirement**. The current [logout implementation](../app/web/auth_routes.py#L224) clears the browser session; it does not individually revoke an already-copied valid session cookie.

   I would prioritize revocable sessions, password recovery, verified recovery channels, and multi-factor authentication for staff. Someone reviewing identity documents should have stronger protection than an ordinary browsing session.

3. **Make failures recoverable and visible.**

   A dependable product needs answers to practical questions: If a deployment fails, can we roll back? If files disappear, can we restore them? If applications stop submitting, will we know before users complain?

   I would add automated deployment checks, a staging environment, error monitoring, actionable alerts, and backups with demonstrated restoration.

   Private evidence currently uses local storage, and community malware scanning can allow uploads when scanning is unavailable. Both are documented pilot choices. Before public operation, I would implement protected storage, explicit retention rules, and a scanning process that prevents unchecked files from being published.

4. **Finish the journeys that produce value.**


   My recommended first journey is:

   **Create a useful profile → find a legitimate opportunity → apply confidently → receive an employer response.**

   Measure where people abandon that journey. Improve those steps before expanding the feature catalogue.

   Community should have an equally concrete purpose: getting a useful answer, finding a mentor, or making a professional connection. A populated feed alone does not demonstrate that value.

   I would also address pagination, message-history access, useful notifications with preference controls, and concurrent updates. For example, two reviewers deciding a case simultaneously must not silently overwrite each other’s decisions.

5. **Design around the conditions your users actually face.**

   For Nigerian nurses, I would test inexpensive Android phones, limited data, interrupted uploads, shared devices, and slow connections.

   Priorities would include compressed media, preserved form drafts, recoverable submissions, clear error messages, and fast access to essential information. Accessibility work should continue with actual keyboard and screen-reader users, including better descriptions and captions for community media.

   The existing FastAPI application can support this direction. I would retain the architecture and improve it incrementally; I see no demonstrated need for a framework rewrite or microservices.

6. **Build a disciplined learning and operating process.**

   Start with a manageable cohort of nurses and a small number of accountable employers. Observe them completing tasks and provide responsive support.

   Track meaningful outcomes: completed profiles, useful conversations, employer response times, interviews arranged, returning users, and time to resolve reports. Understand the cost of document reviews, moderation, storage, and support alongside those outcomes.

   Those findings should guide both product development and the business model.

**My recommendation for the next development cycle is production readiness and one complete, measurable user journey.** I would begin with account recovery and session control, employer legitimacy, and deployment/backup safeguards, then run an observed pilot. That would give us much stronger evidence for deciding what Nurse.ng should become next.

---

## Assessment baseline and completion tracker — 6 November 2026

**Purpose:** preserve the assessment requested on 6 November 2026 and measure later work against it. This section supplements the earlier assessments; it does not rewrite their history. Saving these recommendations does not mark them implemented or authorize their implementation.

**Assessment scope:** local source code, automated checks, and isolated probes using an in-memory database. No live deployment was assessed, and no fresh browser visual or accessibility audit was performed. The observations below are the fixed baseline; update the tracker and evidence log as work progresses.

### Recorded assessment

**Nurse.ng is a substantial, functional MVP, but its security and trust gaps should be addressed before a public launch.** The architecture is suitable for continued development.

Checks performed during the assessment:

| Check | Result on 6 November 2026 |
|---|---|
| `venv/bin/python -m pytest` | **115 passed in 183.99 seconds** |
| `venv/bin/ruff check .` | Passed |
| `venv/bin/python -m pip check` | No broken requirements found |
| `node --check app/static/js/app.js` and `node --check app/static/js/display.js` | Passed |
| `venv/bin/alembic heads` | One head: `b2c3d4e5f6a7` |
| `venv/bin/alembic check` | No schema drift detected in the local SQLite database |
| Isolated assessment probes | Confirmed the unsafe-default session, unenforced host restriction, stale review decision, and suspended-profile findings below |

Passing the existing suite did not establish the absence of these defects. The probe runner was temporary (`/tmp/nurse-ng-assessment-probes.py`), not a committed regression test; the reproduction descriptions below are retained so future verification does not depend on that file. The sandbox blocked the probe test client's thread communication; the successful run used the approved execution outside the sandbox and only fixture data in memory.

The highest priorities are:

1. **Critical if deployed with defaults: forgeable login sessions.** The application accepts a publicly known signing key. Using that key and a fixture account ID, the assessment successfully accessed the staff review queue without signing in (HTTP 200). Secure cookies also default to off, and an unlisted Host header was accepted despite the `allowed_hosts` setting. Production startup should reject unsafe configuration. Sources: [configuration](../app/core/config.py), [application middleware](../app/main.py).

2. **High: simultaneous reviews can corrupt the decision record.** Two independent database sessions loaded the same pending case. One reviewer approved it, then the other session overwrote that approval with a rejection. The profile retained its approval badge. Decisions need an atomic state transition and preserved history. Source: [document-review service](../app/services/verification.py).

3. **High: employer legitimacy is unchecked.** Anyone can register as an employer and immediately publish jobs using an arbitrary organization name. Application consent protects against unexpected disclosure, but applicants can still share contact details with an impersonator. Organization approval should precede publishing jobs or receiving applications. Sources: [registration](../app/services/auth.py), [job service](../app/services/jobs.py).

4. **Medium: suspension leaves profiles publicly discoverable.** Suspending a fixture account did not remove its profile from the discovery query or prevent its public profile from resolving. Public queries check profile status without checking account status. Source: [profile service](../app/services/profiles.py).

There are meaningful strengths: private-by-default profiles, field-level sharing controls, explicit application consent, staff-only evidence access with access logging, Argon2 password hashing, and messaging restricted to accepted connections. The interface code also includes useful accessibility and display preferences. The earlier browser accessibility results remain historical evidence, not a fresh audit for this assessment.

The remaining readiness work goes beyond those bugs. Account recovery, password changes, session revocation, phone verification, and staff multi-factor authentication (MFA) are missing. Sensitive evidence uses local storage without an implemented retention or malware-scanning workflow. No checked-in continuous integration (CI) or deployment automation was found; PostgreSQL behavior and backup restoration still need demonstrated verification. Sources: [account routes](../app/web/pages_routes.py), [session authentication](../app/web/deps.py), [evidence storage](../app/core/storage.py), [test setup](../tests/conftest.py).

**The biggest product uncertainty is whether the trust service delivers measurable value.** The [verification-source memo](O1_VERIFICATION_SOURCE_MEMO.md) remains unresolved. The application correctly says “document reviewed,” but authoritative verification, review costs, and employer demand remain unproven. Research remains deferred as recorded in the existing project direction; this assessment does not restart it.

The recommended next development cycle addresses the issues above and one complete journey: **create a profile → find a legitimate job → apply → receive an employer response.** Measure completion, employer response times, interviews, and support effort before expanding features.

### Completion tracker

The criteria below make the recommendations reviewable; they describe proposed outcomes, not completed work or newly selected providers. Preserve IDs when linking fixes, pull requests, tests, or operational evidence.

- Status values: **Open**, **In progress**, **Deferred**, **Verified complete**.
- Mark an item **Verified complete** only when all its closure criteria are met and the evidence log contains a date, implementation reference, and actual verification result. A code change or passing unrelated tests alone does not close an item.
- Record a deferral or change of scope explicitly with its reason and decision reference. Deferred items remain unresolved and do not count as completed.
- Track the first four findings separately from the wider readiness work. A count is progress against this assessment, not a percentage of the whole product or proof of launch readiness.

**Baseline on 6 November 2026:** 0 of 4 priority findings verified complete; 0 of 13 total tracker items verified complete. Twelve items were open; A12 was deferred.

**Current progress:** 0 of 4 priority findings and 0 of 13 total items verified complete. Nine items are open, A01 is in progress, and A02, A04, and A12 are deferred. A01's implementation is locally verified; the actual deployment configuration and HTTPS/proxy checks remain outstanding. The user has prioritized community delivery and deferred A02/A04 under [L74](DECISIONS.md#l74--community-is-the-immediate-delivery-priority-within-the-wider-platform). **Last tracker update: 6 November 2026.** Update current counts together with the rows; preserve the baseline.

| ID | Area / priority | Status | Evidence required to close |
|---|---|---|---|
| A01 | Unsafe production configuration — critical if defaults are deployed | In progress | Production startup rejects missing or known development signing keys and unsafe cookie settings. Host restrictions are enforced. Automated checks reject a cookie signed with the old development key, reject unlisted hosts, and verify Secure cookies in production configuration. Record the deployed configuration check without recording secrets. |
| A02 | Review decision consistency — high | Deferred | Independent concurrent reviewers cannot overwrite a decided case. Exactly one transition succeeds; the losing attempt receives a clear conflict. Decision history is preserved and the public badge agrees with the recorded decision. Commit regression coverage using separate database sessions and verify on the intended production database. |
| A03 | Employer legitimacy — high | Open | A self-selected employer role cannot publish a job or receive applicant details before organization approval. Record the approval/revocation procedure and accountable representative. Test unapproved, approved, revoked, and unrelated employers, while retaining application consent and employer isolation. |
| A04 | Suspended profiles — medium | Deferred | Suspended and deactivated accounts are excluded from public discovery and public profile access. Regression checks cover direct profile URLs and listings, while active accounts retain their intended visibility. |
| A05 | Recovery, password changes, and verified phone ownership — readiness | Open | Users can verify phone ownership, change passwords with appropriate authentication, and recover access through a verified channel. Test successful flows, wrong/expired/reused recovery credentials, abuse limits, and prevention of cross-account changes. Record a support procedure for failed recovery. |
| A06 | Session revocation — readiness | Open | Users can invalidate an individual session and all sessions. Previously copied cookies cease granting access after revocation; password recovery and account suspension follow a documented invalidation policy. Regression checks demonstrate server-side rejection of revoked cookies. |
| A07 | Staff MFA — readiness | Open | Staff must complete a second factor before accessing review or moderation functions. Enrollment, recovery, and removal have documented controls. Tests demonstrate that a password-only session cannot bypass the requirement. |
| A08 | Sensitive evidence storage and lifecycle — readiness | Open | Document and verify production storage access protection, encryption, scanning/quarantine, retention periods, and deletion behavior. Unchecked or rejected evidence cannot be opened by reviewers. Exercise scanner failure, unauthorized reads, and scheduled deletion with fixture files; preserve the intended access audit. |
| A09 | CI and deployment automation — readiness | Open | Commit a reproducible pipeline that runs required checks and controls migrations and deployment. Record a successful staging deployment, a failed-check gate, and a demonstrated recovery or rollback procedure. |
| A10 | PostgreSQL verification — readiness | Open | Run migrations and relevant authentication, privacy, application, messaging, and review-concurrency checks against the intended PostgreSQL version. Record fresh-install and existing-data upgrade results and confirm no schema drift. SQLite results alone do not close this item. |
| A11 | Backup restoration — readiness | Open | Restore both database and private evidence from backups into an isolated environment. Verify account access, application records, evidence links, and permissions after restoration. Record backup age, restore duration, retention, and the repeatable restore procedure against agreed recovery targets. |
| A12 | Verification source and review economics — product decision | Deferred | Resolve O1 with sourced evidence and an explicit decision: source-confirmed, defensible document-only operation, or stop. Record permitted claims, applicable legal input, and observed review costs. Match public labels to the chosen model. Research remains deferred until resumed by the user; a document-reviewed implementation alone does not close O1. |
| A13 | Nurse-to-employer value — product validation | Open | Observe the full profile → legitimate job → application → employer response journey with real participants. Set pilot targets and a measurement window before evaluating results. Record completion/drop-off, response times, interviews, support effort, and whether those targets were met; document the resulting product decision. |

### Completion evidence log

Append a row for each status change or verification. Keep earlier results, including failures and deferrals. Link durable repository or operational records; do not rely solely on files under `/tmp`.

| Date | Item | Status change / result | Implementation or decision reference | Verification evidence / remaining work |
|---|---|---|---|---|
| 2026-11-06 | A01–A13 | Baseline recorded; no items closed | This assessment; [work log](WORK_LOG.md#session-2026-11-06--assessment-and-completion-baseline) | 115 existing tests passed; isolated probes confirmed A01, A02, and A04. A03 was established by registration/posting code and existing workflow coverage. A12 remains deferred under the recorded project direction. No fixes were made during the assessment. |
| 2026-11-06 | A01 | Open → In progress; implementation locally verified | [L73](DECISIONS.md#l73--enforce-safe-configuration-before-application-startup-a01), [configuration](../app/core/config.py), [middleware](../app/main.py), [operator check](../app/cli.py), [regression tests](../tests/test_configuration.py) | 37 focused checks passed, including fresh-process production startup, rejection of both old signing keys, host restrictions, IPv6 development access, HTTPS login/logout cookies, and a configuration check that neither displays secrets nor connects to the database. Full-suite results are recorded in the work log. Closure still requires running `python -m app.cli check-config` and verifying HTTPS cookies/host rejection in the actual deployment environment; no deployment was performed. |
| 2026-11-06 | A02, A04 | Open → Deferred | [L74](DECISIONS.md#l74--community-is-the-immediate-delivery-priority-within-the-wider-platform) | The user explicitly postponed these fixes and prioritized the described community experience. Their closure criteria remain unchanged; neither item is implemented or counted as complete by this increment. |

### Community delivery progress — 6 November 2026

The immediate journey is **ask or share → receive replies → follow the discussion → return to new replies or find earlier information**. This implements [L74/L75](DECISIONS.md#l74--community-is-the-immediate-delivery-priority-within-the-wider-platform) within the broader professional platform. The delivery checks below are separate from the fixed assessment baseline above; they measure this increment's behavior, not the completeness of Nurse.ng or outcomes with real nurses.

| ID | Delivered behavior | Verification |
|---|---|---|
| C01 | Text-first asking/sharing, optional media, and choosing a first community name in the composer without publishing a private professional profile | Automated identity/privacy cases and actual browser submission passed. |
| C02 | A working reply composer, preserved text on validation/throttling errors, reply counts, and a link to the submitted reply | Automated permission, escaping, validation, and throttle checks; browser reply submission passed. |
| C03 | Search public conversations, topics, and published reply text; page through results while retaining the query and topic | Automated search, hidden-content exclusion, wildcard, and pagination cases; browser reply-only search and pagination passed. |
| C04 | Explicitly follow/unfollow discussions and return through `/feed/discussions`; new replies from others are marked until read | Automated CSRF, privacy, uniqueness, unread/read, removal, and read-marker checks; browser follow → new reply → read flow passed. Indicators refresh on page load. |
| C05 | Upgrade safely with a follow table and activity index; initialize one empty General nursing category only when no topics exist | Migration upgrade/downgrade and existing-inactive-topic checks passed. Local upgrade preserved existing records across 17 tables; one schema head, `c3d4e5f6a7b8`, with no drift. |
| C06 | Usable conversation screens on mobile and desktop, using existing display preferences | Targeted Chrome checks at 320, 390, and 1440 pixels passed with no application script exceptions or failed HTTP responses. This was not a fresh full accessibility audit. |

**Evidence:** [discussion regression tests](../tests/test_discussions.py), [migration tests](../tests/test_migrations.py), and the [community work log](WORK_LOG.md#session-2026-11-06--community-conversations). Full regression suite: **165 passed in 77.57 seconds**. The local database was backed up and upgraded; other environments require `alembic upgrade head` before running this code.

**Still to validate:** whether real nurses can get useful answers and return to relevant conversations, especially on inexpensive phones and unreliable connections. Live updates, email/push notifications, and nested replies are not part of this increment. No artificial member activity was added.

### Reply pagination and unread navigation — 6 November 2026

Implemented under [L76](DECISIONS.md#l76--page-through-replies-without-clearing-unopened-information), following the user's instruction to start this increment. C01–C06 above retain the evidence from the initial delivery; this follow-up refines reading and returning to conversations.

| ID | Delivered behavior | Verification |
|---|---|---|
| C07 | At most 20 published replies per page, stable timestamp/ID ordering, earlier/later controls, and a composer that retains the current page on validation or throttle errors | Database-query bounds, tied timestamps, removed replies, invalid/stale/empty pages, and successful/error submissions covered in regression tests. Mobile/desktop browser reflow passed. |
| C08 | New-reply indicators open the first unread reply; the target is highlighted. Reading pages out of order clears only the replies on those pages | Tests and browser checks opened the final page first, returned to the earliest unread reply, and confirmed intermediate replies stayed new. Repeated reads, private member isolation, replies arriving after page load, failed rendering, and deletion of read records on unfollow are covered. |
| C09 | Permanent reply links resolve their current page, including after earlier replies are removed. Existing follow history survives the schema upgrade | Regression cases cover changed page positions, wrong-discussion/removed targets, existing follow cutoffs, fresh installation, and downgrade/upgrade. A trial and actual local upgrade preserved all existing records across 18 tables. |

**Latest evidence:** **177 tests passed in 109.05 seconds**, Ruff and whitespace checks passed, and targeted Chrome journeys passed at 320/390/1440 pixels. Sources: [discussion tests](../tests/test_discussions.py), [migration tests](../tests/test_migrations.py), [read-record migration](../migrations/versions/d4e5f6a7b8c9_add_discussion_reply_reads.py), and [work log](WORK_LOG.md#session-2026-11-06--reply-pagination-and-unread-navigation). Local schema head: `d4e5f6a7b8c9`; no drift.

Read state is private and means included in a rendered page, not proof of attention. PostgreSQL runtime/concurrency verification and the existing assessment items retain their separate status. Draft recovery was left for the following increment, recorded below.

### Community draft recovery — 7 November 2026

Implemented under [L77](DECISIONS.md#l77--recover-community-drafts-within-the-signed-in-browser-tab) after the user's instruction to start draft recovery. The earlier delivery records and assessment baseline remain intact.

| ID | Delivered behavior | Verification |
|---|---|---|
| C10 | Save question/reply text, selected topic, optional video link, and first community name; restore in the same tab and composer. Separate reply drafts by discussion; provide explicit discard and a 24-hour lifetime | Chrome checks passed for return/refresh, separate tabs and discussions, topic/link/name restoration, discard, expired/malformed storage, and file reselection. Draft content stays in session storage rather than the database or signed session cookie. |
| C11 | Clear only the version acknowledged after successful publication; retain text on failure or unknown network outcome; prevent Back from restoring published/discarded text | Server regression cases cover successful/failed post and reply publication, malformed version IDs, CSRF rejection, and one-time confirmation. Browser checks cover validation, offline submission, successful post/reply publication, a different draft in another tab, and history restoration. |
| C12 | Separate drafts by sign-in session, clear on logout/account change, and stop stale tabs re-saving signed-out drafts. Keep ordinary forms usable when storage is blocked | Automated session-boundary cases and real-browser logout across two tabs passed. Browser checks confirm old text is cleared, stale-tab input cannot save, another account starts empty, display preferences remain, and blocked storage still permits normal posting. |

**Evidence:** **182 automated tests passed in 128.92 seconds**; Ruff, JavaScript syntax, and whitespace checks passed. The checked-in [browser runner](../tests/browser/community_drafts.py) passed at 320/390/1440 pixels, including simulated network failure. See [server regression tests](../tests/test_draft_recovery.py) and the [work log](WORK_LOG.md#session-2026-11-07--community-draft-recovery). No new schema or runtime dependency was introduced.

**Scope:** drafts belong to the current browser tab and sign-in session, expire after 24 hours without an edit, and may disappear when the tab is closed. Cleanup of expired records runs on the next page visit. This is local recovery, not encrypted storage or cross-device synchronization. Browser/JavaScript restrictions can disable recovery; the composer reports that condition. Unknown submission outcomes are retained with a reminder to check the conversation before retrying; there is no automatic resubmission or duplicate-submission guarantee.

### Replying to a specific response — 7 November 2026

Implemented under [L78](DECISIONS.md#l78--link-a-response-to-the-reply-it-answers) after the user authorized the next community increment.

| ID | Delivered behavior | Verification |
|---|---|---|
| C13 | Reply to an individual response, show a short author/excerpt reference with a link back, and retain the chronological/paginated layout | Server cases cover selection links, native navigation without JavaScript, publication across pages, reference lookup, and ensuring an off-page excerpt does not mark the original reply read. |
| C14 | Preserve the selected response alongside draft text; explicit new selections take precedence; changing/removing the target keeps typed text | The browser runner covers selecting a response, changing pages, restoring the draft, choosing another response, clearing context, discarding, publishing, and following the reference back. |
| C15 | Reject unavailable or cross-discussion targets; removal hides quoted text; upgrade without losing replies, reports, or read records | Tests cover malformed/missing/removed/foreign targets, service validation, authentication/CSRF, escaping, restricted public metadata, soft removal, and hard deletion. Migration cases preserve historical replies/reports/read records through upgrade and downgrade/upgrade. A backup, trial, and actual local upgrade preserved original values across 19 tables and passed foreign-key checks. |

**Evidence:** **192 automated tests passed in 138.46 seconds**. Ruff, both community-script syntax checks, and whitespace checks passed. Sources: [reply-context cases](../tests/test_reply_context.py), [migration tests](../tests/test_migrations.py), [browser runner](../tests/browser/community_drafts.py), and [migration](../migrations/versions/e5f6a7b8c9d0_add_reply_context.py). Current local schema: `e5f6a7b8c9d0`; no drift.

The final browser pass verified response selection, changes/removal, draft restoration, cross-page publication and reference navigation, plus the existing draft/offline/logout journey. Focused mobile composer/reference screenshots were visually reviewed. See the [work log](WORK_LOG.md#session-2026-11-07--replying-to-individual-responses) for the actual results and browser-runner corrections; this is not a full accessibility audit.

Only immediate public references are loaded. Drafts store a response ID, not a copy of its author or excerpt. When the selected response disappears, the user must choose another or explicitly reply to the conversation instead; the text is retained. This increment adds no nested layout, private messaging permission, notification delivery, or runtime dependency. Earlier assessment deferrals remain unchanged.

### Recruitment-source discovery and review — 7 November 2026

Implemented under [L79](DECISIONS.md#l79--independent-recruitment-source-discovery-with-evidence-based-staff-approval) after the user authorised starting the saved recruitment design.

| ID | Delivered capability | Evidence and limits |
| --- | --- | --- |
| R01 | Central organisation/source registry and manual registration, exact original URL, separate observed/canonical fields | Migration `a3310f4d2d7b`; idempotency, exact LSHSC URL and redirect tests |
| R02 | Independent directory discovery for Nigeria and worldwide; recruitment-page links and bounded sitemap inspection; pending candidates | Live implemented ROR adapter: 18 usable Nigerian institution candidates from 20 records. Unseen NG/NZ fixture institutions proceed to recruitment-page candidates without a supplied hospital list. ROR coverage is incomplete. |
| R03 | Optional search adapter with configurable queries and Nigerian state/category rotation | Credential and storage-rights gates tested. Provider account/rights activation and live paid search validation remain open. |
| R04 | Staff evidence review, approval expiry, pause/revoke/reopen, health and event history | Service and HTTP tests cover separate evidence requirements, staff/CSRF, stale decisions, redirects and interrupted work. Browser forms verified. |
| R05 | Scheduled persistent queue, single network lease, hard deadline, retries, bounded requests and daily/queue budgets | Duplicate queue, lease fencing/recovery, cancellation, malformed results, rate-limit cooldown and SSRF/robots/redirect/size tests. Production PostgreSQL/deployment validation remains open. |

The full suite passed at **246 tests** before two additional special-address cases; the final recruitment suites passed **56 tests**, covering all changed recruitment logic. Current collection totals **248 tests**. Ruff and whitespace checks passed. Browser checks exercised staff login, source listing/detail on mobile and desktop, evidence submission and exact URL retention in an isolated database. A live read-only ROR request verified the adapter contract; no sources were automatically approved.

The local database was backed up, trial-migrated, and upgraded to `a3310f4d2d7b`, preserving original data across 19 tables, with 24 tables afterwards, valid foreign keys and no schema drift. Other environments must run `./venv/bin/alembic upgrade head`.

**Remaining:** AI assistance, the first permitted vacancy adapter, original/normalized vacancy storage, validation/deduplication, automatic publication, exceptions and lifecycle, unified search and notifications. Existing A03 employer legitimacy and A10 PostgreSQL readiness are not marked complete by this increment. See [the design's capability tracker](AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md#implementation-progress--7-november-2026) and [worker/admin instructions](RECRUITMENT_SOURCE_OPERATIONS.md).

### Structured vacancy ingestion and publication — 7 November 2026

Implemented under [L80](DECISIONS.md#l80--shared-vacancies-with-original-source-evidence-and-guarded-publication).

| ID | Delivered increment | Evidence and limits |
| --- | --- | --- |
| R06 | Approved-source JobPosting collection, original page snapshots and extracted/normalized records | Malformed structured pages retained without publication. One HTML page, up to 50 records; other formats require adapters. |
| R07 | Automatic ordinary publication, URL deduplication, staff exceptions and history | Missing dates/locations, unsafe URLs, employer mismatches, conflicts, stale forms, correction expiry and rejected-record persistence tested. No live source approval granted. |
| R08 | Shared `/jobs`, country/type filters, disclosed currencies/pay periods and external applications | Existing employer flows retained; imported jobs never collect contacts through the platform apply endpoint. Browser checks use isolated NG/NZ examples. |
| R09 | Deadline/freshness gates, approval expiry/revocation, missing-record and failure handling | Read gates work without a worker, using a 48-hour confirmation window. Explicit withdrawal signals and independent application-link monitoring remain open. |

**Verification:** **280 tests passed in 175.04 seconds**; Ruff and whitespace checks passed. Migration checks preserve historical employer jobs/applications through upgrade and an empty-vacancy downgrade/upgrade. The browser journey passed collector setup, automatic publication, international salary display, external application presentation, exception approval and mobile/desktop reflow. Visual review improved mobile search and job-card attribution placement, followed by another successful browser pass.

The local database was backed up, trial-upgraded and upgraded to `3838cd201521`, preserving every original value across 24 tables. There are now 27 tables, valid foreign keys and no drift. Populated vacancy history prevents a lossy downgrade. These checks do not close A10 PostgreSQL readiness.

The inspected saved exact LSHSC page contains zero JobPosting records. Actual source activation still requires source verification, reuse rights and a compatible adapter. AI, more adapters, A03 direct-employer safeguards, saved opportunities and notification delivery remain open. See the [capability tracker](AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md) and [operating instructions](RECRUITMENT_SOURCE_OPERATIONS.md).

### Source activation scope — 7 November 2026

Implemented under L81. A separate licence is not mandatory: staff can record the applicable legal basis for reuse, published terms or written authorization.

| ID | Delivered increment | Evidence and limits |
| --- | --- | --- |
| R10 | Explicit reuse basis, collection/retention/republication findings and URL scope | Staff evidence remains required; government ownership is not automatically converted into unrestricted rights. Existing records are preserved without inferred grants. |
| R11 | Scope enforcement in collector configuration and redirects; reapproval clears old configuration | Checked alongside stale-result cancellation, expiry, public-read restrictions and migration preservation. Live TLS checks remain separate. |
| R12 | Staff activation status and exact LSHSC review | Browser checks passed. [LSHSC remains pending](LSHSC_ACTIVATION_REVIEW.md); no structured vacancy was found and worker certificate validation fails. |

The local database is upgraded to `49b37f820e16`, with all original values across 27 tables preserved and no schema drift. Backup: `/tmp/nurse-vacancy-migration-6vpftetr/before.db`. This does not close production/PostgreSQL readiness or establish any source's legal rights.

Verification for R10–R12: **298 tests passed in 362.47 seconds**, with Ruff and whitespace checks passing. Isolated Chrome checks passed the legal-basis review form, approval without a separate licence, remaining collector blockers, exact URL preservation and mobile/desktop reflow; the vacancy publication/application/exception journey also passed.
