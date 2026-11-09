# Operating recruitment-source discovery

The system discovers institutions, automatically activates sources that pass reproducible checks, and sends uncertain cases to staff review. Configured approved sources can supply structured vacancies to the shared jobs interface. It does not claim regulatory or individual-vacancy verification and does not run AI models. Direct employer submissions retain their existing consented application flow.

## Local setup

Run from the repository root with the existing development `.env`:

```bash
./venv/bin/alembic upgrade head
./venv/bin/python -m app.cli recruitment-init
./venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, run the worker:

```bash
./venv/bin/python -m app.cli recruitment-worker
```

Keep both processes running. The worker polls the durable queue every five seconds when idle. It runs separately from Uvicorn, so reloads do not start duplicate discovery loops. Ctrl+C stops it; interrupted leases recover on the next worker run. Deployments should supervise this command with their existing process manager; no worker service is installed by these commands.

`recruitment-init` is repeatable: it creates a daily Nigerian ROR healthcare schedule and a weekly worldwide schedule. Rerunning setup upgrades the original built-in worldwide 24-hour interval to 168 hours, retaining its pause state and page cursor; custom schedules/intervals are retained. It seeds pending starting points for LSHSC (preserving the exact user URL), the Federal Ministry of Health, National Health Fellows, Nigeria Jubilee Fellows, and Iwosan Lagoon Hospitals careers. These are examples across government, youth programmes and private healthcare, not an exclusive source list. Setup makes no network requests and approves or publishes nothing. Directory jobs discover further institutions; later inspection jobs identify recruitment/programme links. Each directory run processes up to 20 records and advances its cursor.

Nigerian work has priority both when admitting due items to the bounded queue and when claiming ready tasks. Four of every five slots prefer Nigeria; the fifth prefers other countries. Either group uses a slot if the preferred group is empty. Schedules and source checks compete together; a worldwide schedule cannot automatically fill the last slot before a Nigerian source. Within each group the oldest eligible work goes first. Leases, retry times, daily limits, cooldowns and staff decisions still apply. The registry and public jobs feed also rank Nigeria first; the jobs page offers Nigeria-only and international views. Unknown countries are not labelled Nigerian or international.

The relevance rules include nursing and health roles, plus Nigerian youth fellowships, internships and graduate programmes across sectors. This includes opportunities like Jubilee Fellows without claiming every user qualifies. Programme types are taken from explicit titles; original employment terms and eligibility text are retained. International general trainee titles still require a health field in the title/description. Existing records receive updated normalization on their next successful authorized collection.

Search categories now include federal/state recruitment, private hospitals, youth fellowships, digital health, internships and graduate training. Configured Nigerian search schedules start with a national round, then cover all 36 states and FCT, visiting every category for an area before advancing. Use `{category} {region} {country}` as a broad query. Search still needs its separately configured key and storage permission; setup does not enable paid search. ROR alone does not cover all government or youth programmes. The current collector still requires structured `JobPosting` records and the existing source/reuse evidence: prose, PDFs, absent deadlines and unsupported sites require further adapter or review work. Priority and registration are not proof of a current opening.

Starter-site research on 2026-11-08: [the Ministry](https://health.gov.ng/) directly linked [National Health Fellows](https://healthfellows.ng/); [Iwosan Lagoon Hospitals](https://www.lagoonhospitals.com/) linked its careers page; [Nigeria Jubilee Fellows](https://njfp.ng/) returned a programme-titled JavaScript shell, not extractable vacancy data. These observations support discovery candidates only. No application deadline or active opening was inferred.

Sign in with an existing staff account and open **Staff → Recruitment sources**, or <http://127.0.0.1:8000/recruitment>. An operator can grant an existing account staff access with:

```bash
./venv/bin/python -m app.cli set-staff +234YOUR_NUMBER
```

For an existing scheduler, invoke `recruitment-worker --once --max-tasks 1` once a minute instead of starting a continuous process. `--once` exits when no task is currently eligible; it does not wait through cooldowns. Only one network task can hold the database lease, even if commands overlap.

## Automatic activation

The worker assesses new monitoring sources by default; no extra switch or per-source approval is needed. A passing check activates the source, configures its collector, retains the original page, and imports valid vacancies in the same fenced transaction. The registry and source pages show automatic decisions and the reason an uncertain source still needs review.

The first automatic policy requires all of the following:

- A fresh **active ROR healthcare record** matching the organisation name, country and recorded website. Search results, government-looking domains and manual entries alone are insufficient independent evidence for this adapter.
- The exact source page and official website use HTTPS on the same origin. The homepage identifies the organisation and directly links to the recruitment page. An external redirect or conflicting canonical address requires review.
- The recruitment page declares exactly one supported whole-page licence through `<link rel="license" href="…">` in its HTML head: **CC0 1.0** or **CC BY 4.0**, using its canonical HTTPS Creative Commons URL. A licence on an image or individual JSON-LD object does not establish rights to retain the entire HTML page. Other terms and legal bases continue through staff review; they are not automatically declared invalid.
- At least one relevant structured nursing, health or Nigerian early-career opportunity matches the organisation and country, with an announcement URL inside the page scope. Individual vacancy validation follows activation: reversed salaries, missing deadlines and other record problems go to vacancy review without disabling an otherwise verified source. This policy reads a single page and confines announcement URLs to that page's path scope. It does not infer rights across a whole website.
- Date-only deadlines use the supported country mapping (Nigeria, Ghana and Kenya). Other countries require explicit UTC offsets in every source date or staff timezone configuration. Mixed-country date-only records need review.

Automatic approval expires after **48 hours**. Each daily check repeats independent identity, recruitment and reuse checks before renewal and collection. Missing terms, conflicting evidence or access failures stop automatic activation and current job listings. Passing checks can restore automatic sources; they do not override staff decisions. Public vacancy details retain the captured licence link, source attribution and adaptation notice.

Staff approval, collector edits and **Reopen for staff review** put the source under staff control. Pause, reject and revoke remain effective. **Return to automatic checks** explicitly opts a source back in; rejected/revoked sources must first be reopened. All actions require staff, CSRF and a current revision. Changing organisation details also requires staff review or an explicit return to automatic checks. Evidence history distinguishes staff and automatic decisions.

This is verification of a publication channel, not regulatory accreditation or a guarantee about individual vacancies. A government source may use a documented legal basis without a separate licence through the staff path. Broader authoritative registries, legal-rule adapters, licence formats and timezone mappings can extend automatic coverage later.

## Reviewing sources

The registry can be filtered by name/URL, status and two-letter country code. Leave country blank for worldwide schedules or unknown candidate locations. Search targeting never establishes a candidate's country or organisation identity.

Open a source to see the exact original URL, observed redirect address, canonical hint, checks, and evidence history. Correct suggested organisation details where needed; this invalidates approvals on related sources. The current deduplication key is organisation identity plus normalized URL. Independent providers may produce separate organisation candidates; the system deliberately does not merge them solely because names resemble each other.

Staff approval requires a confirmed category and country, an expiry within one year, a permitted collection method, a decision note, and an authoritative URL plus written finding for each of:

- Organisation identity.
- Website association.
- Recruitment-channel authority.
- Applicable registration/licensing, including the reason if not applicable in that jurisdiction.
- Collection and republication permission and its limitations.

These are recorded staff findings, not automated regulatory verification. Passing automatic sources use the separate policy above. Use administrator-assisted collection where automated reuse is not permitted. After approval, staff can configure the structured vacancy collector. Ordinary valid records then publish automatically, while exceptions require review. Source approval is distinct from institution, agency, or individual-vacancy verification.

Pause checks when terms/access restrictions need investigation. Reject or revoke a source when the evidence warrants that decision, recording why. Reopen returns it to pending. Request page check schedules background work; web requests never fetch submitted URLs. Staff routes require authentication and CSRF tokens, and responses are not cached.

Failures preserve verification evidence and record separate health outcomes. A newly observed origin change returns an approved source to pending. The original address is never overwritten. A canonical hint is only evidence, not authority to change ownership. Configured collection records vacancy changes, missing records and deadlines in addition to page hashes.

## Providers, limits and costs

ROR discovery works without search credentials, using its public healthcare directory metadata. ROR is a research-organisation registry, not a hospital licensing authority or exhaustive directory of employers, agencies, ministries or commissions. Its live records can contain old domains. Nigerian and worldwide discovery are supported, but completeness is not claimed.

Optional Brave search requires both environment values:

```dotenv
NURSE_NG_RECRUITMENT_SEARCH_KEY=
NURSE_NG_RECRUITMENT_SEARCH_PERMISSION_REFERENCE=
```

The permission reference must identify the applicable agreement allowing persistent result storage for this use. Filling in the reference records the operator's decision; the software cannot establish contractual rights. The key is sent only to the configured Brave endpoint, never stored in registry/task records or displayed. Source websites still need their own collection/republication review. No paid search is activated by default.

Once configured, staff can add a Brave schedule. For Nigeria, a query such as `{region} {category} nursing recruitment {country}` rotates across 36 states plus the FCT and institution categories. For other countries, use a country code and a suitable query; category rotation works without an allowlist of countries. This first adapter is not a complete multilingual discovery strategy. Query/page observations remain pending evidence.

Defaults:

- Up to 100 attempted tasks per UTC day, configurable with `NURSE_NG_RECRUITMENT_DAILY_TASK_LIMIT` (1–1000). The conservative count includes all attempts on tasks attempted that day, including earlier retries.
- Up to 500 queued/running tasks, configurable with `NURSE_NG_RECRUITMENT_PENDING_TASK_LIMIT` (20–5000).
- One network task globally, a 60-second cooldown after each result, at most eight requests per task, and a 2 MiB response limit. Robots crawl delays that exceed the task budget defer the check. Persistent cooldowns also protect successive checks from different processes.
- A 45-second process deadline, a 90-second lease, and at most three attempts. Transient failures retry after five and ten minutes. HTTP 429 pauses all network work for at least 15 minutes or the supplied Retry-After interval, whichever is longer, up to one year.
- Daily page checks for monitoring sources; rejected/revoked or paused sources are excluded. A request/check that becomes stale during review is cancelled before saving observations.

Unapproved-source discovery stores metadata and provenance. Enabled approved-source collection also stores original page bytes, extracted JSON and normalized/decision history. Snapshot/audit/task retention is currently unbounded: define archival and deletion policy before large production runs. The dashboard exposes recent tasks, status counts, failures and paginated source evidence; external alerts/metrics are not installed.

No new runtime dependency, broker or microservice is introduced. Each task uses a disposable Python process for hard timeouts; at this volume the startup overhead is acceptable. Broader coverage will require measured queue budgets, official directory adapters, search rights and staff review capacity. Search fees and infrastructure consumption need observation rather than a guessed production cost.

## Access and deployment limits

The fetcher checks robots policy, pins connections to validated public DNS results, revalidates redirects, preserves HTTPS verification, and rejects private/special IPs, embedded credentials, sensitive query tokens, unusual ports, compressed/oversized responses and HTTPS downgrades. Provider credentials cannot cross origins. A robots allowance is not a republication licence. Public-page discovery only records a small set of source metadata; known contractual restrictions should be recorded and monitoring paused.

For LSHSC only, the fetcher supplies a verified missing Sectigo intermediate for `lshsc.ng` and `www.lshsc.ng`. Certificate/hostname/expiry verification still requires a complete chain to an existing system root; no system trust settings or runtime certificate downloads are used. See [bundle provenance and maintenance](../app/certificates/README.md). This compatibility measure does not bypass source approval or redirect-scope checks.

The first checker handles HTML, recruitment links and a bounded conventional sitemap. It does not render JavaScript, solve access challenges, scrape logged-in pages, inspect PDFs, or discover every language-specific careers route. Failure is recorded instead of fabricating content. ROR and Brave provider endpoints are specific reviewed adapters, not arbitrary authenticated fetch targets.

SQLite is exercised by the current tests. Validate PostgreSQL locking, worker recovery, database migrations, outbound network policy, backups, retention and process supervision before production operation. The current global task lease favours predictability over throughput; expand concurrency only after measuring source backlog and implementing durable per-origin budgets.

## Enabling structured vacancy collection

Run `./venv/bin/alembic upgrade head` before using this version (schema `6a21d8e40c93`). Keep the existing discovery worker running; it also collects vacancies for configured sources.

For a source that does not pass automatic checks:

1. Review and approve the source for **Permitted website collection**. Select a documented legal basis (including applicable government-publication rules), published reuse terms, or written authorization. A separate licence is not mandatory. The permission evidence must explain the reference, applicable scope and conditions; government ownership, public access and robots allowances alone do not establish unrestricted reuse. Explicitly confirm collection by the selected method, retention of complete original snapshots/records, and republication of normalized vacancy content. Enter the covered URL prefix.
2. Open **Configure vacancy collection** on the source page. Select **Structured JobPosting data**, enter a vacancy URL prefix within the approved reuse scope, an IANA timezone such as `Africa/Lagos`, and the permission reference/scope note. The prefix must include the source page; shared portals need a suitable tenant/path boundary. Another origin needs its own approved source. Reapproval clears previous collector settings so a new decision cannot silently reactivate an old configuration.
3. Request a check or wait for the daily worker check. The adapter reads at most 50 embedded schema.org JobPosting records from this one page. It does not traverse job-detail links, render JavaScript, or extract prose/PDF announcements. Larger feeds need paginated adapters.
4. Open `/jobs` for public opportunities or `/recruitment/vacancies` for exceptions. Country/type filters and search use the shared Job model. Existing employer jobs have no guessed country; new submissions can explicitly provide one.

The adapter uses the documented [schema.org JobPosting](https://schema.org/JobPosting) representation, inspected on 7 November 2026. This does not imply every Nigerian institution uses that format or permits reuse. Ordinary publication requires a nursing title, employer matching the approved organisation, description, explicit vacancy country, in-scope announcement URL, and unambiguous publication/closing dates. Third-party employer names, multiple locations, spelled-out countries or incomplete fields may need staff clarification. Original information remains available rather than being guessed.

Disclosed structured salaries retain currency and pay period. Missing/unsupported salary information is not converted to naira. Date-only closing values include that calendar day in the configured timezone; timestamps without an offset require review. Employment start dates are not application opening dates. Employer requirements do not establish professional licensing eligibility.

Raw snapshots and original JSON remain available to staff, including malformed structured pages. Downloads are text attachments with active HTML execution disabled. History links each change to its snapshot. Staff corrections need evidence and do not overwrite original data; they expire when the raw source record changes. Rejected records remain rejected. Stale forms cannot overwrite newer observations. A missing or stale record cannot be manually republished as currently confirmed.

Deduplication uses normalized announcement URLs rather than title similarity. Conflicting records make the public vacancy unconfirmed. Staff must reject incorrect evidence or reconcile it before publication. Different vacancies sharing one announcement URL need a more specific identity/adapter strategy. Fuzzy matching and cross-provider organisation merging remain future work.

Public listings require current approval/permission, an enabled collector, healthy checks, confirmation within 48 hours and an unexpired deadline. These gates apply on reads even when the worker is stopped. Missing records and failed collections stop claiming open. Known elapsed deadlines show **Closed**, uncertainty shows **Unconfirmed**, and documented future application openings can show **Upcoming**. Explicit withdrawal signals are not yet extracted.

Aggregated listings identify their source and use **Open original vacancy** for the institution's instructions. They do not collect applicant contacts or invent a dedicated application URL. Scope and obvious redirect-query checks reduce unsafe destinations; independent monitoring of every announcement/application link remains future work. Source approval does not guarantee every vacancy or the nurse's eligibility.

The initial implementation did not approve a live source. Automatic activation now applies on subsequent worker checks when its evidence criteria pass. The exact `https://lshsc.ng/recruitment` remains pending; its saved inspected page contains zero JobPosting records. A source-specific adapter and documented reuse rights are needed where recruitment is published in other formats.

The **Live vacancy collection** panel explains missing review, reuse scope and collector settings separately from page health. An enabled collector still needs a running worker and a successful collection; it is not proof of an open vacancy. Fetch redirects are checked against the approved reuse path before requesting the destination. Revocation, missing rights, expiry and new approvals prevent collection/public listing even while workers are stopped. Pending metadata discovery continues independently.

The reuse-scope migration preserves existing source fields and audit records but initializes explicit rights as unrecorded. Earlier approvals need a new scope review and collector configuration before automatic collection resumes. It refuses downgrade when recorded reuse decisions would be lost. See the [LSHSC activation review](LSHSC_ACTIVATION_REVIEW.md) for the exact source's current blockers.

Downgrade refuses populated vacancy jobs/snapshots that the previous schema cannot represent. Archive/export that data and choose an explicit migration path first. Existing employer jobs and applications passed upgrade and empty-vacancy downgrade/upgrade tests. Snapshot retention is not yet automated; unchanged pages deduplicate by hash, but changed pages and history grow until an archival policy is implemented.

The automatic-activation migration adds decision mode and assessment evidence without changing original records or historical staff decisions. Existing pending candidates become eligible for checks; staff-reviewed sources remain under staff control. Downgrade refuses to remove automatic controls while automatically activated sources exist.

## Current search and activation policy — 9 November 2026

See [Search and recruitment discovery](SEARCH_DISCOVERY.md) for current setup. The policy now supports factual listings from verified government domains, independently identified institutions and their linked recruitment portals. A CC licence or ROR healthcare classification is not required for factual indexing. Full page storage/republication remain separate permissions. Existing staff decisions are preserved. General search uses configured SearXNG instances with optional Brave fallback; no Brave API key is required for core discovery or direct monitoring. Fresh collections are scheduled every six hours; queue priority favours active collectors and first checks over repeated failed directory checks, while retaining Nigerian preference, global leases, cooldowns and daily limits.
