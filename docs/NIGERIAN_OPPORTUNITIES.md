# Nigerian opportunity coverage, saves and alerts

Implemented on 8 November 2026 for roadmap priority 3. Nigeria remains the default
priority; federal/state bodies, private employers, health programmes, fellowships,
internships and graduate opportunities remain in scope. Named programmes are examples,
not a fixed or exclusive list.

## Member features

- The Jobs page links to **For you**, **Saved opportunities**, and **Opportunity alerts**.
  Additional state/city and country filters are collapsed unless used. The previously
  removed Nigeria first, Full-time, Part-time and Contract filter buttons remain removed.
- Members save an opportunity on its detail page and can choose a deadline reminder.
  `/jobs/saved` is private, paginated in batches of 25, and supports removal and reminder
  controls. Closed bookmarks remain distinguishable from current openings. If source
  permission is revoked, a removable unavailable placeholder replaces its content.
- `/jobs/preferences` records explicit keyword/organisation, location, opportunity type
  and country interests. Nigeria is the default. **For you** shows up to 25 current
  matches. This is a text/category match, not a claim that the member is eligible.
  A location filter matches the source's stated location; leave it blank to include
  nationwide programmes whose text does not name a particular state.
- Matching alerts are off until the member enables them. They cover newly added matching
  jobs after interests were saved, rather than sending an initial backlog. The separate
  Opportunities category in notification preferences controls in-app/email channels.
  Email remains opt-in and requires a verified address. Changing matching criteria or
  disabling matching cancels queued match emails from the previous criteria.
- Saved-job reminders are generated once when a currently open, available opportunity
  with a stated deadline falls within 48 hours of closing. A changed deadline can produce
  a new reminder. Removing the bookmark or turning reminders off prevents its delivery.
  Expired, stale, unconfirmed and revoked-source jobs are excluded. No deadline is guessed.
- Employer submissions now accept optional deadlines. Nigerian date-only deadlines include
  the closing day in Africa/Lagos. International deadlines require an explicit offset.
  Expired employer jobs are excluded from current listings and cannot accept applications.

The new system notifications use the existing inbox and email outbox. They have no member
actor and never impersonate another user. A unique event key deduplicates reminder and
matching generation across retries. Suppressed matching events are recorded privately so
turning channels back on does not unexpectedly replay old matches. Read and email paths
recheck current job availability and reminder ownership.

## Collection beyond structured job data

The existing `jsonld` collector is retained. Source configuration now offers an
`announcements` collector for normal HTML recruitment and programme announcements.
It uses the same source approval, permission scope, retained snapshots, validation,
review queue, deduplication, expiry and freshness controls.

- Collect the configured index and at most four relevant linked pages per check. Only
  links within its approved URL scope are followed. The starting offset rotates across
  checks; there is no recursive crawl. Existing request/time budgets, public-IP checks,
  robots rules, TLS chain validation and hostname checks remain enabled.
- Prefer structured job data if present. Otherwise read a single H1 announcement, article
  text, explicitly labelled employer, location/country and deadline, and a publication
  date from a labelled field or article metadata. Scripts, navigation and footer content
  are excluded. ISO and named-month dates with explicit years are supported; ambiguous
  numeric dates are left empty for review.
- General informational pages without an application/recruitment signal do not become
  openings. Missing or conflicting required facts remain in the existing vacancy review
  queue. A programme homepage is not evidence that applications are open.
- Each fetched page retains its own snapshot/evidence. Missing-record reconciliation is
  limited to the page actually checked. Unvisited pages are not declared withdrawn just
  because a bounded batch did not reach them; the existing 48-hour freshness limit still
  excludes records that have not been reconfirmed.
- Failed child fetches fail the bounded collection instead of declaring partial results
  complete. PDF/image documents and application portals requiring browser interaction
  need another adapter; links to document/media files are not followed by this HTML adapter.

Read-only source discovery now records public redirects instead of stopping at the original
origin before observing the destination. Automatic activation still checks the exact
independently verified HTTPS identity and reuse evidence. Approved collection remains
strictly confined to its recorded scope; public redirects do not grant permission.

The starter set now also includes NPHCDA, NCDC and Lagos State Ministry of Health. They are
pending discovery candidates, not approved publishers. Existing source decisions and pause
settings are preserved. Nigerian-first scheduling and the existing category/state query
rotation remain in place. The optional search provider still needs its configured API key
and result-storage permission; this change does not provision or bill a provider.

## Coverage and the actual remaining work

Staff can open `/recruitment/coverage` to distinguish registered Nigerian sources, healthy
collectors with a successful check within 48 hours, and actual current opportunities.
It breaks down source categories, opportunity types and recorded organisation locations
across the 36 states plus FCT. It also shows the daily discovery budget and explains
when queued checks are waiting for its midnight-UTC reset. Unmapped locations are stated explicitly. Organisation
location counts do not claim that vacancies exist or are open to residents in those states.

Live read-only checks on 8 November 2026 reached NCDC and NJFP homepages with HTTP 200,
but found no current structured vacancy or extractable announcement on those homepages.
Health ministry and NPHCDA checks hit redirect limits; Lagos health ministry timed out;
Health Fellows returned a connection failure. Those checks did not establish current
applications or publication permission, and did not publish any openings.

The existing local Nigerian registry was entirely pending when inspected. Three additional
candidates were registered without changing approval evidence. The final local registry
contained 42 Nigerian candidates, zero active approved collectors and zero current
Nigerian openings. The existing discovery worker had used its 100-check daily budget;
21 checks were queued for later execution. That limit and all prior decisions were preserved. Sustained live coverage
therefore still requires usable official announcement pages, resolution of source checks
and evidence-based source approval/configuration. No sample openings were inserted into
the real application database. These features improve collection and member retention;
they do not establish complete nationwide vacancy coverage.

## Migration and workers

Back up the database and apply revision `ae5314d8c902`, following `9de420c3b287`:

```bash
venv/bin/alembic upgrade head
venv/bin/python -m app.cli recruitment-init
venv/bin/python -m app.cli recruitment-worker
```

Run the notification worker separately:

```bash
venv/bin/python -m app.cli notification-worker
```

That worker now also scans saved deadlines and matching preferences. It examines up to 100
eligible saved deadlines and 50 due matching configurations per pass, with up to 20 new
matches per configuration; configurations are revisited after five minutes. Progress and
notices commit together, and event uniqueness protects retry duplication. The worker can
generate in-app opportunity alerts without SMTP; email delivery still needs the existing
account-mail configuration. `--once` provides a bounded run, suitable for testing or a
frequent external scheduler. A one-off run does not keep future reminders active.

Production worker supervision, restart policy, queue monitoring and deployed verification
remain roadmap priority 1. SMTP still has the delivery limitations documented in
[notification operations](NOTIFICATIONS.md).

## Verification

```bash
venv/bin/python -m pytest tests/test_opportunity_watch.py tests/test_local_opportunities.py tests/test_vacancy_ingestion.py
venv/bin/python tests/browser/opportunities.py
```

Tests cover private bookmark ownership, CSRF, pagination, criteria filtering, new-only
matches, suppressed-event deduplication, deadline changes/expiry, cancelled email, source
availability, HTML extraction/scope, rotating page batches, the discovery worker, migration
preservation and downgrade guards. Browser checks at 320, 390 and 1280 pixels exercise the
member journey and invoke the actual notification CLI worker to deliver matching/deadline
alerts into an isolated file mailbox. No real test emails are sent.

## Live implementation update — 9 November 2026

The earlier zero-collector state described above is historical. Automatic policy 3 separates factual indexing from full-content reuse, supports government domains and independent publisher/portal links, and connects ordinary HTML to automatic collection. NCDC was activated by the actual background worker without ROR or a CC licence. Its sampled pages did not contain current openings.

The worker also verified eHealth Africa's current independent directory record and its official careers-page link to EHA Clinics. It published **Medical Laboratory Scientist - Lagos** from `https://erp.eha.ng/jobs/medical-laboratory-scientist-lagos-576`, which was linked from the live job-offers index and included a job-bound application form. The source states Nigeria/Lagos; no publication or closing date was invented. Only factual records and generated summaries are retained under this mode.

General search now uses locally configured SearXNG. Live worker searches returned 20 candidates with the Brave API key empty, and unavailable-instance failover succeeded. The existing daily budget was preserved; no usage records were reset. New Nigerian checks and active collectors take priority over repeated failures from stale directory addresses. Full regression and 320/390/1280px browser journeys passed. See [deployment, verification and limits](SEARCH_DISCOVERY.md).

Coverage remains a measure of observed, fresh sources and vacancies. A reachable homepage is not an open application period. Some ministry/programme sites still time out, redirect repeatedly or require interactive portals; their failures remain visible. PDF/document links are tracked, but document contents and login-protected applications need additional adapters.
