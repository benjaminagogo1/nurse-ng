# Completed opportunity discovery after interruption

Recovered the 14 November session's instructions: publish useful announcements with
the information they provide, across all collectors, and discover sources beyond
MyJobMag and Jobberman, including government, hospitals, NGOs and programmes.

The implementation was already saved in `9a2bcf0`. Its three previously reported
test failures had been repaired before that commit, but the five new recurring
searches had not been activated. The configured search endpoint was unreachable;
the former SearXNG process and installation were temporary.

## Completed operation

- Took a private backup before changing discovery configuration:
  `.local-backups/automatic/backup-20261115T020848883066Z`. It preserved six
  existing files and explicitly recorded the two previously missing documents.
- Restored pinned SearXNG revision `3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf` and
  Granian 2.8.7 under `.local-tools/searxng/`, in a separate Python environment.
  The source archive SHA-256 is
  `1a10d9278f9b75aafab368f9f03ebc9bec653390b28091d60f961f325acb52ed`.
  A real application search returned 29 results and zero unavailable engines.
- Installed and enabled `nurse-ng-search.service`, bound to `127.0.0.1:8888`.
  Search and worker services were both enabled, active and running, with no
  restarts reported after startup. Systemd configuration verification passed.
- Activated all five six-hour schedules through `expand-opportunity-discovery`
  and restarted the existing worker supervisor to load the completed code.
  The [activation receipt](discovery-activation.json) records the actual write.
- Added a repeatable installer and service definition; verified installation
  can be repeated without replacing the existing private search settings.

The [before measurement](discovery-before.json) records 144 registered sources,
30 publicly eligible opportunities across nine publisher hostnames, and failed
general searches while the old search service was unavailable. The
[latest measurement](discovery-after.json) records the new searches and queue.
Candidate pages are not confirmed vacancies or automatically approved sources.
Their inspections and eligible collection continue under the ordinary worker
limits. The computer and user service manager must remain running.

All five initial searches completed by 02:21:40 UTC. They registered **85 new
source pages**, bringing the registry to 229 sources (130 approved, 99 pending)
at 02:22:39 UTC. The public feed still contained 30 eligible opportunities across
nine publisher hostnames at that measurement; this pass does not claim 85 new
jobs. [First-pass evidence](discovery-first-pass.json).

| Search | Newly registered pages |
| --- | ---: |
| Federal/state government health | 17 |
| Hospitals and clinics | 19 |
| NGOs | 20 |
| Internships and programmes | 19 |
| Allied healthcare | 10 |

The next scheduled round is 08:16:49 UTC, subject to the ordinary queue limits.
The internship and allied-health searches each reported one unavailable upstream
engine but still returned 19 and 12 candidates through the remaining engines.

At the final 02:35:34 UTC snapshot, 133 sources were approved and 96 pending.
Zamfara's government recruitment portal was among the new automatic approvals.
Public eligibility had dropped to **21** after the MyJobMag Lagos source exceeded
the existing 45-second check deadline twice. Its nine previously eligible jobs
are withheld until fresh confirmation; the task remains queued for its third
attempt at **02:45:12 UTC**. The normal retry, source-health and freshness rules
were preserved. This is a measured collection limitation, not 85 new vacancies.
The [timeout snapshot](discovery-during-source-timeout.json) and final
`job_source_checks` in [the latest measurement](discovery-after.json) preserve
the failure and retry details. Other collection and source inspections continue.

## Verification

- Full regression: **789 passed**, no failures, in **1541.28 seconds**.
  [JUnit results](pytest.xml). The single warning is the existing pypdf `add_js`
  deprecation in a synthetic PDF test. Local network/process tests ran outside
  the restricted sandbox; the initially stalled sandbox run was stopped.
- Focused regression: **103 passed**, including all three earlier failing cases,
  incomplete adverts, source diversity, linked portals, prior decisions,
  conflicts, deadlines and freshness.
- Chrome opportunity journey passed at **320, 390 and 1280 pixels**, covering
  saves/removal, interests, reminder controls, email opt-in, actual worker alerts
  to a local file mailbox, and the coverage dashboard. No JavaScript errors or
  server log errors were recorded. [Browser evidence](opportunities-browser/report.json).
- Fixed an outdated browser assertion that expected `state=sent` in worker logs.
  It now checks the two persisted notification delivery states and still checks
  the two mailbox files and visible inbox notices. Application behavior was
  already correct; the failure was in the assertion.
- Ruff, whitespace checks, shell syntax, all 80 template parses and both Python
  dependency checks passed.
- Live `/healthz`, `/readyz`, `/jobs` and an incomplete Nursing Officer listing
  returned HTTP 200. The listing displayed available facts, missing-data labels,
  "Check availability" and its original announcement link. [HTTP evidence](live-http.json).

No database migration was needed. Tests used isolated databases and local file
mailboxes. No real email was sent. Production hosting remains separate from this
local search-service recovery.
