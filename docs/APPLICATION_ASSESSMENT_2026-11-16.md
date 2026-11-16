# Nurse.ng application assessment — 16 November 2026

Follow-up: the requested saved-reminder continuity, notification-worker and
LinkedIn contrast fixes are now implemented. The local supervisor runs all
three roles and readiness is healthy. See the
[implementation verification](verification/2026-11-16/assessment-fixes/README.md).
The findings below retain the original assessment snapshot.

Nurse.ng's main workflows are functioning in the tested local environment. The
full automated suite passed, and the browser journeys exercised registration,
profiles, jobs, community, events, messaging, notifications, Reels and offline
recovery. Remaining priorities include a reproduced saved-deadline defect after
vacancy consolidation, an inactive local notification worker, overstated source
verification wording, and a dark-theme contrast issue. Public release still
needs the previously deferred staff MFA and deployment/device assurance.

This assessment covers the working tree based on `fddad96`, including the earlier
duplicate-vacancy and installation repairs. It combines code inspection,
isolated tests and browser journeys, synthetic-account probes, and read-only
inspection of the running local app. Real accounts, source decisions and worker
configuration were not changed during this assessment. No real email was sent.
The requested job-deadline display change was implemented during the assessment;
the other findings below remain findings, not silently applied fixes.

## Verification

| Check | Result |
| --- | --- |
| Full Python regression, before the date change | **823 passed**, 1,621.06 seconds; one pypdf deprecation warning. Isolated database and disabled outgoing account mail. |
| Final deadline-specific tests | **13 passed**, 4.57 seconds, after the date change. Cover ISO dates/timestamps, timezone boundary days, date objects, missing/invalid input, feed/detail rendering, preserved storage and form recovery. |
| Quality browser journey | **25 audited states** passed, including job/application and employer flows, community, events, profile save recovery, staff navigation, keyboard dialogs and 320-pixel/200% text checks. Selected axe rules reported no violations in these isolated states; manual checks remain necessary. |
| Notifications and messaging | Passed inbox/preferences, incoming messages, 128-message history, retries and revoked access. The actual notification worker delivered to a private file mailbox. |
| Offline | Passed durable encrypted storage, browser restarts, reconnect, operation receipts, competing tabs and resumable video uploads. |
| Reels | Passed upload, actual worker processing, playback, likes, saves, comments and data saver at 320, 390 and 1280 pixels. |
| Discovery | The repository runner failed on an exact whitespace-sensitive heading assertion. A temporary copy changing only that assertion to `.textContent.trim()` completed registration, onboarding, privacy, suggestions, filtering, pagination, following and connection decisions. The repository runner itself is still failing. |
| Running anonymous public pages | **27 states** across 12 pages at 390/1280 pixels, plus registration, login and installation at 320 pixels/200% text. No JavaScript exceptions or horizontal document overflow. Four states reported the LinkedIn icon contrast issue below. |
| Installation | Earlier repair passed 60 related Python checks and isolated browser installation/device instruction checks. The local installation page has working actions. Physical Android/iPhone installation remains unverified. |
| Static checks | Ruff and dependency consistency passed; 81 Jinja templates parsed and 21 application JavaScript files passed syntax checks. Four native Node checks passed earlier in the assessment. |
| Local database | Read-only integrity check `ok`, zero foreign-key violations; current revision and migration head `e6480f6b2183`. |
| Local scanner | `ClamAV 1.5.4`, signatures `28185`, dated Nov 16, 2026. This was a version check, not a fresh upload or malware challenge. |

The full 823-case suite preceded the date change and was not repeated. An initial
targeted run contained a new test fixture error (direct template rendering lacked
a Request), then was interrupted by process termination. The fixture was replaced
with an HTTP form-recovery check. A subsequent foreground run of all 13 final
date tests passed; the interrupted run is not counted as a successful regression.

## Findings and priorities

1. **Medium — consolidation leaves saved opportunities and reminders on retired
   vacancies.** In an isolated reproduction, a member saved an alias with a
   confirmed deadline. Consolidation correctly redirected the old link and
   preserved the bookmark row, but the retained detail offered “Save opportunity”
   again. Generated deadline reminders changed from **one before consolidation
   to zero afterward**. The bookmark still references the withdrawn alias, while
   reminder generation filters its job through `open_job_condition()`. Resolve
   saved/reminder operations to the retained vacancy, preserve member reminder
   choices, and verify idempotence and already-sent reminder behavior before
   further consolidation. The live snapshot had **zero saved opportunities**;
   no real member reminder loss was observed. Evidence:
   [consolidation service](../app/services/vacancy_duplicates.py),
   [reminder generation](../app/services/opportunity_watch.py),
   [detail lookup](../app/web/jobs_routes.py), and
   [synthetic results](verification/2026-11-16/assessment/probes.json).

2. **Operational gap — the local notification worker is missing.** At 12:57 UTC,
   recruitment and Reels had healthy progress reports, but notifications had no
   heartbeat. The configured required workers are only `recruitment,reels`, so
   readiness can pass while notification generation/delivery is inactive. The
   notification role also runs opportunity matching and deadline generation.
   Include and supervise that role when these features are intended to operate,
   and inspect queue age/delivery status. The live notification table was empty;
   this does not establish lost or failed email. It was not activated during the
   assessment because actual SMTP is configured. The isolated file-mail worker
   journey passed. Evidence: [worker runtime](../app/services/worker_runtime.py)
   and [configuration snapshot](verification/2026-11-16/assessment/status.json).

3. **High, previously deferred — staff MFA is still not enforced.** A synthetic
   staff account with `mfa_enabled=True` signed in using only its password and
   received HTTP 200 for `/review`, `/recruitment` and `/staff/users`.
   `require_staff` checks staff authorization without second-factor session
   verification. Enrollment, recovery and server enforcement remain release
   work previously deferred by the user. No MFA implementation was added here.
   Evidence: [staff dependency](../app/web/deps.py) and the synthetic results.

4. **Medium — external job wording overstates publisher verification.** The
   detail template still says “verified publisher” for every external listing.
   **31 of 34** publicly eligible jobs in the snapshot came from sources whose
   recorded identity basis was `staff_selection`, which does not establish
   independent verification. Derive wording from the evidence actually held,
   using an accurate staff-selection label where appropriate. Evidence:
   [job detail template](../app/templates/jobs/show.html) and the source basis
   counts in the configuration snapshot.

5. **Medium — the LinkedIn mark has insufficient contrast in dark theme.** The
   running public audit reported a serious axe `color-contrast` finding on `.in`
   on both login and registration at 390 and 1280 pixels. The mark keeps its
   fixed blue while the social button uses the dark theme surface. Provide a
   theme-appropriate mark color or accessible icon treatment and check both
   themes. The enlarged-text states did not report this violation, which does
   not clear the normal-size finding. Evidence:
   [mark color](../app/static/css/design.css),
   [theme surface](../app/static/css/appearance.css), and
   [public audit states](verification/2026-11-16/assessment/public-states.json).

6. **Product quality — vacancy metadata and availability need further review.**
   Of the 34 public jobs at 12:57 UTC, 12 lacked an employer and 16 lacked a
   deadline. The UI labelled 22 “Open” and 12 “Check availability.” Two Adamawa
   employer names included weather-widget strings such as
   `HumidityPressureWind...SunriseSunset`. An Enugu announcement URL contained
   `/2024/06/16/`, but no publication date was extracted. These observations do
   not prove the announcements are closed. Improve employer/date extraction and
   clearly distinguish confirmed openings from uncertain career announcements.
   Canonical public announcement URLs had **zero duplicates** at this snapshot.

7. **Release and recovery gaps remain.** Google and LinkedIn credentials and
   both native download URLs are unset locally. Provider code and clickable
   browser installation exist, but real provider sign-in and native distribution
   have not been validated. Local settings use development mode, debug and HTTP
   cookies; these need the intended production HTTPS/settings check. Two
   historical evidence records are marked `missing`; existing controls block
   access, and originals need recovery/replacement rather than relabelling them
   safe. Backup manifests exist, with the latest automatic backup at Nov 15,
   23:04 UTC. The documented Nov 14 isolated restoration and CI workflows now
   exist, so older assessments calling them absent are obsolete. No fresh
   restoration, production load or PostgreSQL acceptance test was performed.

The employer approval gap from earlier assessments is closed: the synthetic
unapproved employer could not publish, and reviewed organization/membership
checks now gate publishing and applicant access. Private evidence also has
structural validation, scanning/quarantine and retention controls added since
the older assessment. Passing tests supports those implemented controls; it
does not establish protection against every threat. Authoritative NMCN licence
verification remains previously deferred.

## Requested date display

Job cards and detail pages now display
`2026-11-30T23:59:59+00:00` as **Nov 30, 2026**. The shared `display_date` Jinja
filter uses English abbreviated months and an unpadded day. It retains the
timestamp's stated calendar date rather than converting it into the next day
in another timezone. Missing values retain the existing “Not stated” behavior;
invalid strings remain readable as supplied.

Stored deadlines and employer input values remain ISO values, so parsing,
deadline enforcement and form recovery retain their existing behavior. Event
times, message times and machine-readable timestamps were not reformatted by
this deadline change. At **13:26 UTC**, the running feed and the example detail
returned HTTP 200 and displayed **Nov 30, 2026**. All 16 visible feed deadlines
used the requested format. The running feed then had 32 eligible opportunities;
the earlier aggregate snapshot had 34 while collection continued.

## Inventory snapshot and practical limits

| Measure at 12:57 UTC | Value |
| --- | --- |
| Sources | 862: 165 approved, 697 pending |
| Authorized collectors | 165 |
| Approved sources marked healthy | 108 |
| Vacancy records | 55 published, 3 pending, 19 duplicate, 100 rejected |
| Publicly eligible jobs | 34 |
| Live saved opportunities / notifications | 0 / 0 |

Stored published records and publicly eligible jobs are different measures;
source authorization, freshness, status and employer gates affect eligibility.
Counts reflect their recorded times, not steady-state reliability or a current
vacancy guarantee.

The architecture has substantial working account/session, privacy, CSRF,
application-consent, moderation, durable draft/offline and background-processing
controls. The route review found 172 route decorators, including 80 changing
state. The apparent offline CSRF exceptions use `verified_session` to validate
`X-CSRF-Token` and `X-Offline-Scope`; they are not unprotected endpoints. The
small outer FastAPI route list in the raw snapshot does not enumerate included
routers and must not be interpreted as the total endpoint count.

Browser results used Chrome and synthetic accounts, isolated databases and
disabled or file-only mail. Anonymous local inspection submitted no forms.
Physical Android/iPhone devices, Safari installation, assistive technologies,
real social providers, production email, production load and a complete
penetration/dependency vulnerability audit were outside this assessment.
Screenshots and selected axe checks support the inspected states only.

Recommended next work is to repair saved-vacancy reminder continuity, configure
the intended notification role, correct source wording and dark-theme contrast,
and improve the affected vacancy metadata. Complete the deferred trust and
production/device checks before a public release. All current changes remain
local and uncommitted; no deployment was performed.

[Verification artifacts and reproduction notes](verification/2026-11-16/assessment/README.md)

