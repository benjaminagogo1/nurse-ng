# Nurse.ng repository assessment — 13 November 2026

Nurse.ng is a substantial working pilot. Its feature breadth is ahead of its release assurance and operational maturity. The recent work improved the interface, profile privacy, review consistency, vacancy extraction and worker recovery. The highest-value next work is to close trust gaps, restore dependable checks, fix demonstrated accessibility defects, and improve useful vacancy coverage.

This assessment inspected commit `61d9f5082bc6a1a7d19b9e5407ae3a89bd25f8d8`, project documentation, application code, isolated tests and browser journeys, and read-only local database aggregates. No application code, real accounts, source approvals or vacancy decisions were changed. A separate two-line edit to `app/templates/home.html` appeared during the assessment and was preserved; the full suite should not be treated as validation of that subsequent edit.

| Verification | Current result |
| --- | --- |
| Full pytest suite | **703 passed, 7 failed**; 710 cases, 1,035.65 seconds. Isolated database default and disabled outgoing account mail. |
| Diagnosis of the seven failures | **7 passed** in temporary copies replacing only spacing-sensitive assertions with parsed HTML attribute checks. Repository tests remain unchanged and failing. |
| Ruff | Passed. |
| Installed dependencies | `pip check` passed; this is dependency consistency, not a vulnerability audit. |
| Syntax | 76 Jinja templates parsed; 19 JavaScript files passed `node --check`. |
| Notification browser runner | Completed inbox, preferences and message journeys through its final worker assertion; failed because the expected CLI log text is obsolete. A file-only test email was produced. This is not a full runner pass. |
| Quality/accessibility browser runner | Stopped on the first audited page, registration at 320 pixels with enlarged text, because of an indistinguishable inline link. Subsequent journeys were not exercised by this run. |
| Local database | Revision `e6480d3fb942`; SQLite quick check passed and no foreign-key violations were reported. |
| Isolated trust probes | Reproduced unapproved employer publication/applicant access, password-only staff access despite the MFA flag, and acceptance of malformed evidence. |

The initial sandboxed test-client run stalled before executing cases; the reported full run and browser runs used the permitted execution environment outside that restriction. Browser and trust probes used temporary databases and synthetic accounts. External messages were disabled or replaced with a local file mailbox.

**Findings and priorities**

1. **High — an employer role still grants publishing and applicant access without organization approval.** A public registration with an unverified email published an open listing under an arbitrary organization name. After a synthetic applicant explicitly consented, the employer could read that applicant's phone and email. Consent and ownership boundaries are implemented, but the organization receiving the information is not established. Add approved organizations and authorized employer memberships before enabling publication and access to applicants. Evidence: [publication gate](../app/services/jobs.py), lines 86–87; [registration](../app/services/auth.py); isolated probe results below.

2. **High — the staff MFA flag does not enforce a second factor.** With `mfa_enabled=True`, password sign-in alone returned HTTP 200 for `/review`, `/recruitment`, and `/staff/users`. The authorization dependency checks `is_staff` only. Implement enrollment, recovery, and a server-checked second-factor session state for sensitive staff routes. Evidence: [staff dependency](../app/web/deps.py), lines 46–57; [sign-in](../app/web/auth_routes.py).

3. **High readiness gap — private evidence storage remains a pilot implementation.** A 53-byte inert string beginning with `%PDF-` was accepted and saved as `application/pdf`. Header checks are not structural document validation. Private paths, reviewer authorization and access logging are useful safeguards, but document validation, quarantine/scanning and routine retention remain unfinished. This probe did not demonstrate malware execution. Evidence: [storage validation](../app/core/storage.py), lines 40–64.

4. **Medium — mobile registration clips enlarged text, and the shared footer has a link distinction defect.** At 320 pixels with a 32-pixel root font, the registration hero visibly loses text. Mobile CSS hides `<br>` elements in a heading whose adjacent text has no separating whitespace, joining words; ancestor `overflow: hidden` clips the result. The document-width check passes despite lost content. The same audited page reports the footer “Photo credits” link at 1.31:1 contrast against surrounding text, without an underline or another distinguishing style. Preserve word separation, allow text to reflow and inspect internal clipping. Give inline links a persistent visual distinction. Evidence: [heading](../app/templates/auth/register.html), line 19; [mobile CSS](../app/static/css/design.css), lines 3153–3160; [footer link](../app/templates/base.html), lines 414–417; screenshot below.

5. **Medium — the repository's verification baseline is not green.** Seven full-suite failures come from exact HTML string comparisons in profile defaults and reply-context checks. Temporary semantic assertions confirmed the expected attributes and allowed the rest of those seven cases to pass. Separately, the notification runner expects `state=sent`, but the new worker reports `notifications: completed task …; sent`; its local email artifact exists. Update assertions to inspect behavior, attributes and delivery outcomes. Keep the accessibility failure separate: it is a real UI finding. Evidence: [profile test](../tests/test_profile_pages.py), line 153; [reply-context tests](../tests/test_reply_context.py); [browser worker assertion](../tests/browser/notifications.py), line 390; [current log format](../app/services/worker_runtime.py), line 90.

6. **Medium — public source wording still overstates the stored evidence.** Every external job is labelled “From a verified publisher.” The staff factual-indexing path explicitly stores `identity_basis="staff_selection"` and says independent checks remain separate. Derive the label from the actual evidence, using “Staff-selected source” where appropriate. Evidence: [public job template](../app/templates/jobs/show.html), lines 35 and 118; [source approval](../app/services/recruitment.py), line 315.

7. **High product priority — worker activity has not yet translated into broad usable vacancy coverage.** The 10:34 UTC snapshot showed 140 sources: 126 approved and 14 pending. Seventy approved sources were marked healthy. There were 3 stored open jobs, 84 pending vacancy records, 15 duplicates and 22 rejected records. A subsequent read using the application's public eligibility predicate returned **2 publicly eligible jobs**; stored “open” status alone does not establish eligibility. Of the 84 pending records, 73 had a relevance-review issue, 11 had missing/ambiguous deadlines, 10 lacked an explicit country and 6 had an employer issue; categories overlap. Prioritize dependable recruitment pages, relevance selection and review throughput. These observations do not establish a steady-state failure rate or prove every pending candidate is unsuitable.

8. **High release-readiness gap — production operation is still unproven.** Recruitment and Reels had fresh healthy progress reports at the snapshot, and readiness checks plus the systemd worker supervisor are meaningful improvements. The inspected configuration remains development; the supplied unit does not supervise the web server. No application CI workflow or completed restoration evidence was found in the reviewed repository. Google and LinkedIn client IDs are not configured locally. Before a public release, demonstrate the actual HTTPS/proxy configuration, supervised web and required worker processes, database/private-file restoration, monitoring and intended database behavior. Validate real devices and assistive technologies. These are evidence gaps, not claims that a deployed system has failed.

**Assessment of the work**

The FastAPI/Jinja/SQLAlchemy monolith is a reasonable architecture for the pilot. Routes, services, models and migrations are separated by domain. Account recovery, revocable sessions, CSRF protection, profile visibility, explicit application consent, durable drafts, offline operation receipts and background task handling show substantial implementation depth. The latest full suite exercises hundreds of cases; the privacy and overlapping-review regressions identified on 10 November now have fixes and passing tests. Worker supervision and bounded progress reporting improve operation materially.

The notification layout inspected at 390 pixels has clear filters, unread emphasis and readable actions. The browser runner reached its final worker check after exercising multiple viewport widths, incoming messages, history and revoked connections. This supports a positive assessment of those journeys, while the failing quality runner and clipped registration heading limit any app-wide accessibility claim.

Change organization needs improvement. The latest commit is titled “redesign notification page,” but changes 168 files with 25,425 insertions and 6,478 deletions, including backend behavior, a migration, tests and operations. Such a broad commit makes review, regression isolation and rollback harder. Prefer focused commits for behavior, presentation and mechanical formatting.

Documentation is extensive and often candid about limitations, but the README mixes many historical test counts and migration instructions. Keep one concise current setup/status section and move dated evidence to the work log. Link current test results to an automated check. The shared base also includes 12 stylesheet references, including authenticated-only assets, and loads several offline scripts across pages. This merits a measured mobile performance review; no transfer-time or load benchmark was performed here.

Recommended order: restore accurate tests and fix the demonstrated UI/source-label defects; close employer, staff and evidence-handling trust gaps before expanding access; improve fresh vacancy yield and reduce avoidable review work; then prove deployment, restoration and device acceptance. Another broad visual redesign is a lower priority than these concrete gaps.

**Reproduction and evidence**

Primary commands:

```sh
NURSE_NG_DATABASE_URL=sqlite:// NURSE_NG_ACCOUNT_MAIL_BACKEND=disabled \
  venv/bin/python -m pytest --tb=short -o faulthandler_timeout=45
venv/bin/ruff check . --output-format concise
venv/bin/python -m pip check
venv/bin/python tests/browser/notifications.py
venv/bin/python tests/browser/quality.py
```

The quality runner used `axe-core@4.10.3` installed under `/tmp/nurse-quality-tools`. Evidence below is local and can be removed by temporary-file cleanup:

- [Full test output](/tmp/nurse-ng-assessment-2026-11-13-pytest-unrestricted.log) and [seven-case semantic diagnosis](/tmp/nurse-ng-assessment-2026-11-13-semantic.log).
- [Trust probe source](/tmp/nurse-ng-review-probes-2026-11-13.py) and [results](/tmp/nurse-review-probes-d9yv6ceo/results.json).
- [Read-only aggregate snapshot](/tmp/nurse-ng-assessment-2026-11-13-snapshot.json).
- [Notification runner output](/tmp/nurse-ng-assessment-2026-11-13-notifications-unrestricted.log), [worker output](/tmp/nurse-notifications-browser-2p5zn0_k/worker.log), and [mobile notification screenshot](/tmp/nurse-notifications-browser-2p5zn0_k/notifications-390.png).
- [Accessibility result](/tmp/nurse-quality-browser-u8gzjigq/audits.json) and [registration screenshot showing clipping](/tmp/nurse-quality-browser-u8gzjigq/failure.png).

This was not a complete penetration test, dependency vulnerability audit, production load test, real-provider sign-in test, physical-device acceptance run or backup restoration drill. Authoritative NMCN licence verification remains outside the implemented document-review workflow, as the existing project documentation states.

## Follow-up: 14 November

This document preserves the original assessment. For the subsequent vacancy
selection, project-local ClamAV, scheduled retention, CI and completed isolated
backup restoration, see [local operations](LOCAL_OPERATIONS.md) and the
[fresh coverage measurement](verification/2026-11-14/vacancy-coverage-after.json).
MFA remains deferred at the user's request.

A further [collection-channel update](verification/2026-11-14/COLLECTION_CHANNELS.md)
raised publicly eligible opportunities from **3 to 6** at 14:13 UTC on 14 November.
The live Jobs page confirmed six results. This remains a small measured inventory;
the application serves a wider audience than registered nurses, and existing
healthcare and early-career relevance rules remain in place.
