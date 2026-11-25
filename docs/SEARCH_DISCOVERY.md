# Search and recruitment discovery

Nurse.ng uses Python to schedule and execute searches, normalize and deduplicate results,
verify publishers, and monitor direct sources. General search is optional. The existing
ROR directory adapter and direct website checks work when every search provider is offline.

## What changed

Brave was previously the only general-search adapter, so general search required its API
key and a result-storage agreement reference. That requirement never applied to ROR or direct
monitoring. The same durable queue now also accepts `search` tasks. They query configured
SearXNG instances first, then optionally Brave. Existing explicitly configured `brave`
schedules retain their meaning.

No new Python dependency was added to Nurse.ng. The SearXNG service has its own dependencies
and lifecycle. Search suggestions remain unverified candidates; a search result is never
proof that a vacancy or organisation is genuine.

## Configure Nurse.ng

```dotenv
NURSE_NG_RECRUITMENT_SEARXNG_URLS=http://127.0.0.1:8888
NURSE_NG_RECRUITMENT_SEARCH_TIMEOUT_SECONDS=10
# Optional second/third instance: comma-separated base URLs, maximum three.
# NURSE_NG_RECRUITMENT_SEARXNG_URLS=https://search-a.internal,https://search-b.internal

# Optional paid API fallback; leave both empty to avoid it.
NURSE_NG_RECRUITMENT_SEARCH_KEY=
NURSE_NG_RECRUITMENT_SEARCH_PERMISSION_REFERENCE=
```

Run `venv/bin/alembic upgrade head`, then restart `venv/bin/python -m app.cli recruitment-worker`.
Startup creates the Nigerian general-search schedule and five themed searches if configured
and absent. They run every six hours, rotating national/state/category queries. Existing
schedule pauses and cursors are preserved.
Staff can add further schedules at `/recruitment`. A healthy empty result is not an error and
does not trigger a potentially paid fallback.

Instance order rotates with the query cursor. A timeout, bad response, denied JSON access,
rate limit or complete upstream-engine outage tries the next configured instance. If all
fail, the existing durable retry and lease system handles the task; attempts remain bounded.
HTTP 429 respects `Retry-After` and the existing shared cooldown. Search does not run from web
requests. Task logs report provider failures and partial upstream outages without secrets or
internal endpoint URLs. A successful source inspection is not cancelled by a search outage.

## Self-host SearXNG

The official [search API](https://docs.searxng.org/dev/search_api.html) supports GET/POST and JSON.
Enable `search.formats: [html, json]`; otherwise JSON requests return HTTP 403. Many public
instances intentionally disable this API. Use instances you operate or have permission to use;
do not rely on an anonymous public-instance list.

A private container example is in `deploy/searxng/compose.yaml` with its matching `settings.yml`.
Set `SEARXNG_SECRET` to a generated random value in the deployment environment, then run:

```sh
docker compose -f deploy/searxng/compose.yaml up -d
```

The example publishes only on loopback and disables SearXNG's public-instance limiter because
only the bounded background worker calls it. For network/public access, add authenticated
network controls, TLS and the SearXNG limiter/Valkey configuration described in its
[administration documentation](https://docs.searxng.org/admin/index.html). Never expose this
private example unchanged as a public search service. Operator-configured service addresses
can be private; discovered webpages cannot use this transport and still undergo public-IP
pinning, redirect scope, robots and verified TLS checks.

Pin `SEARXNG_IMAGE` to a tested image digest for a managed deployment, rather than following
`latest` indefinitely. Monitor engine failures/CAPTCHAs and update the image regularly. Two
instances on separate hosts improve resilience; two containers on one host do not protect
against a host/network outage. Engines share upstream availability and may both be throttled.

SearXNG is open source, not costless infrastructure: account for CPU/RAM, disk/cache, bandwidth,
hosting, security updates and operator time. It is a metasearch engine, not an independent
index; upstream engine terms, availability and anti-abuse rules still apply. Its AGPL licence
also applies to deployed modifications. The bundled configuration uses ordinary search engines;
it does not configure the Brave Search API or any API key.

## Direct information and content rights

Direct monitoring remains independent of search and records source URL, content changes,
check outcomes, linked documents and dates. HTML collectors do not parse PDF/image contents or
log in to application portals. Robots/access failures remain failures, not silent bypasses.

Automatic factual indexing supports government domains, independently verified organisations,
and recruitment portals linked by verified publishers. It retains only factual records,
hashes, original links and processing history. It does not claim permission to retain or
republish full descriptions. The existing licensed/full-content collectors remain available
when their documented reuse rights apply. Rejections, revocations and staff decisions remain
binding. Jobs disappear when their source/checks expire or availability can no longer be
confirmed.

A missing publication date is labelled "First listed". Across every collector, missing
deadlines, employers, locations, descriptions and eligibility details no longer prevent an
otherwise relevant announcement from appearing. The listing shows the facts available and
links to the original announcement. Missing deadlines display "Not stated" and "Check
availability", with no guessed deadline reminder. Explicit closure, expired deadlines,
contradictory or ambiguous dates, source authorization and freshness checks still apply.

## Continuing discovery across more websites

The recruitment worker now initializes these five searches automatically whenever a
provider is configured. These commands also support explicit preview/setup:

```sh
venv/bin/python -m app.cli expand-opportunity-discovery --dry-run
venv/bin/python -m app.cli expand-opportunity-discovery
```

This adds five six-hour searches covering federal/state government, hospitals and clinics,
NGOs, internships/fellowships/graduate programmes, and allied healthcare. Searches rotate
through Nigeria's regions, starting nationally. These additional searches exclude MyJobMag
and Jobberman; the existing sources continue their own collection. General search accepts
at most two candidates per hostname (treating `www` as the same hostname) per response.
Rerunning setup preserves existing schedules, including manual pauses and cursors.

Approved collectors also discover linked external careers portals. Up to three linked
portals become candidates for their own checks. A linked candidate cannot expand recursively,
and discovery does not overwrite staff rejection or grant approval automatically. All
collectors use the same missing-information rules. Search results and registered sources
are not counts of available vacancies; measure the public feed with `vacancy-coverage`.

## Persistent local search service

The previous temporary SearXNG process did not survive restart. The local setup now uses
the pinned upstream revision `3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf`, its pinned
dependencies and Granian WSGI server in an independent environment under `.local-tools/`.
The installer checks the source archive's SHA-256, generates a private secret on first
installation, and preserves existing search settings when repeated.

```sh
bash deploy/install-local-search.sh
install -m 644 deploy/systemd/nurse-ng-search.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nurse-ng-search.service
systemctl --user restart nurse-ng-workers.service
systemctl --user is-active nurse-ng-search.service nurse-ng-workers.service
```

The supplied service assumes this checkout is at `~/nurse-ng`; adjust its paths otherwise.
It binds only `127.0.0.1:8888`, restarts after failure, and starts with the user service
manager. Set `NURSE_NG_RECRUITMENT_SEARXNG_URLS=http://127.0.0.1:8888` in the app's `.env`.
The machine and user service manager must be running. Search engines may still return
rate limits, CAPTCHAs or incomplete results; direct source collection runs independently.
Inspect service failures with `journalctl --user -u nurse-ng-search.service`.

## Private search on Render

Set the service's Build Command to `bash deploy/render-build.sh` and its Start
Command to `python deploy/start.py all`. The build uses upstream revision
`3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf` and verifies the archive's SHA-256 before
extraction. SearXNG and Granian dependencies remain in `.local-tools/searxng/venv`,
separate from the application. Its generated settings are private and excluded
from Git. The [upstream source](https://github.com/searxng/searxng/tree/3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf)
and AGPL licence are retained in that source directory.

The launcher binds search to `127.0.0.1:8888`, waits for its local `/healthz`,
and supplies that address to web/workers before their configuration is loaded.
Application environment variables, including database and signing credentials,
are removed from the search process's environment. Its cache files live in a
private directory for this installation. Search has one worker and
four blocking threads. Search exit stops the hosted service so Render restarts
the entire group; all services receive shutdown together. The launcher embeds
the existing worker supervisor, avoiding an extra Python supervisor process on
the free plan while retaining worker restart and heartbeat deadlines.

The hosted configuration explicitly enables Yahoo, Google and DuckDuckGo. The current
Brave web adapter can emit malformed redirect URLs; these are rejected and count
as a provider extraction failure if none of its results are usable. A healthy
empty search still remains an empty result and does not trigger paid fallback.

`NURSE_NG_BUNDLED_SEARCH` accepts `auto` (default), `required`, or `off`.
Required mode reports a missing build installation before opening the database.
External SearXNG configuration or configured Brave credentials take precedence.
`NURSE_NG_BUNDLED_SEARCH_PORT` changes the private port if needed; it must differ
from the public web `PORT`. These are launcher variables, not member preferences.

Search and source discovery run in the background. Inspect search tasks and
source collection results at `/recruitment`, and measure eligible listings at
`/recruitment/coverage`. Engine throttling, source access failures and a lack of
current announcements can still yield zero jobs even while processes are healthy.

## Local verification — 9 November 2026

- Started upstream SearXNG revision `3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf` in a separate Python environment on `127.0.0.1:8888`. The local `.env` points to this instance; the Brave key is empty. The source archive's missing Git metadata is a non-fatal version-reporting warning.
- The JSON API returned 19 results for “Nigeria health internship”, despite one upstream CAPTCHA. A later call through Nurse.ng's isolated worker returned 20 candidate pages. A live run with an unreachable first instance and the local instance second also returned 20 candidates. No CAPTCHA bypass was attempted.
- Real-HTTP tests cover JSON parsing, response-close handling, instance failover, optional Brave fallback, rejected/duplicate/unsafe results, response limits, denied JSON access and HTTP 429. Worker integration verifies direct monitoring with search disabled. A live restart exposed a SQLite naive/aware timestamp comparison during stale-lease recovery; recovery now uses a database comparison and reloads the ORM record. A regression test verifies recovery and rejects the old lease token.
- The actual persistent worker activated NCDC monitoring and published an EHA Clinics vacancy. Source TLS verification, publisher evidence, factual-only storage and normal daily/cooldown limits remain enabled.
- Migration `b715a203ce46` was checked on a database clone and applied locally with all original rows preserved, no foreign-key violations and no metadata drift. Private backup: `/tmp/nurse-notifications-migration-cslmxexi/backup.sqlite`.
- The full pytest suite passed. Focused checks cover the final queue/change-tracking refinements. Isolated browser journeys passed at 320, 390 and 1280px, including saves, reminders, matching, worker-generated alerts and the coverage screen. Browser artifacts: `/tmp/nurse-opportunities-browser-_oelkysp/`.

At the 9 November verification, the local SearXNG process was a development service.
The Render build/launcher now supports a supervised private installation as described
above. The supplied standalone container configuration has not been launched here.
The Python integration also supports separately hosted instances.

Final live refresh: the persistent worker published the EHA Clinics vacancy at
`2026-11-09 00:19:50 UTC` and reconfirmed the same job at `00:27:10 UTC`, with no
duplicate job and no vacancy-review exception. Both tasks reported one publishable record;
three other detail pages were deferred by the bounded request budget. The final worker log is
`/tmp/nurse-opportunity-workers-le1xlvfo/recruitment-worker.log`. The worker and local SearXNG
service were left running.
