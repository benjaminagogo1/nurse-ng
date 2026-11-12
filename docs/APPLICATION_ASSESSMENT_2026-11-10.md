**Nurse.ng application assessment — 10 November 2026**

Implementation follow-up: the requested profile visibility, overlapping review,
collection quality and worker-operation changes are recorded in the
[work log](WORK_LOG.md#10-november-2026--vacancy-quality-salary-clarity-and-recovering-workers)
and [worker operations guide](WORKER_OPERATIONS.md). The findings and observations
below preserve the original assessment snapshot.

Nurse.ng is a working pilot with substantial functionality. The main workflows and responsive interface tested well. Public launch should wait for stronger employer and staff controls, consistent profile privacy, and demonstrated collection and hosting reliability. Passing the existing tests does not resolve the additional defects reproduced in this assessment.

This assessment covers the current working tree, including the recent source-approval changes. It combines code review, isolated synthetic-account probes, browser checks, and read-only inspection of the running local application. It does not establish the security or availability of a public deployment. Application code, real accounts, source approvals, and vacancy decisions were not changed during the assessment.

**Verification performed**

| Check                            | Result                                                                                                                                                                                   |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full automated suite             | **642 passed**, in 369.57 seconds. Default database redirected to isolated storage; outgoing account mail disabled.                                                                      |
| Ruff                             | Passed.                                                                                                                                                                                  |
| Installed dependency consistency | `pip check` reported no broken requirements. This was not a vulnerability database audit.                                                                                                |
| Isolated Chrome quality checks   | **23 screen states passed**, including job publication, validation, duplicate-submit prevention, community drafts/replies, events/RSVP, keyboard dialogs, and interrupted profile saves. |
| Accessibility and reflow         | No violations reported by the selected axe rules; reflow checks passed at 320 pixels with 200% text. Some checks require manual review.                                                  |
| Running public pages             | Home, Jobs, registration, and the current job detail inspected at 1440 and 390 pixels: **8 page states**, no JavaScript exceptions or horizontal document overflow observed.             |
| Local database                   | Schema `e6480c2ea831`; SQLite quick check passed; no foreign-key violations reported.                                                                                                    |

The browser assessment used temporary accounts, databases, and file-only email. The additional public-page browser used a fresh anonymous profile. Physical Android/iPhone devices, assistive technologies, production load, real social sign-in, production email delivery, PostgreSQL, and backup restoration were not validated in this assessment.

**Findings, ordered by importance**

1. **High — employer registration grants immediate publishing without establishing the organization.** A normal public registration with the employer role could publish a listing under an arbitrary organization name. The account had neither a verified phone nor a verified email. After a synthetic nurse explicitly consented and applied, that employer could read the candidate's name, phone, and email. Application consent and ownership restrictions work; the recipient's claimed organization has not been established. Add organization approval and an authorized employer membership before allowing publication and applicant access. An employer-role selection alone should not grant these capabilities. Evidence: [registration](/home/recoding/nurse-ng/app/services/auth.py:111), [job creation](/home/recoding/nurse-ng/app/services/jobs.py:86), and [application contact snapshot](/home/recoding/nurse-ng/app/services/jobs.py:389).

2. **High — staff access does not enforce multi-factor authentication.** A synthetic staff account with `mfa_enabled=True` signed in with only a password, then received HTTP 200 from the review queue, source administration, and a private evidence download. The flag currently provides no second-factor protection. Implement enrollment, recovery, and server-enforced MFA verification before granting a staff session access to sensitive administration. Evidence: [staff authorization](/home/recoding/nurse-ng/app/web/deps.py:46) and [password sign-in](/home/recoding/nurse-ng/app/web/auth_routes.py:234).

3. **High readiness gap — private document handling remains a pilot implementation.** Evidence access is authenticated and audited, and stored files receive private filesystem permissions. However, validation checks only the leading file bytes: a 55-byte inert string beginning with `%PDF-` was accepted as a PDF. The evidence path has no scanner/quarantine state or routine retention workflow. This probe did not demonstrate malware execution. Introduce structural file validation, scanning/quarantine, a retention schedule, and verified storage/backup protection before accepting identity documents at public scale. Account-deletion file cleanup already exists and should be retained. Evidence: [file validation and storage](/home/recoding/nurse-ng/app/core/storage.py:40), [reviewer download](/home/recoding/nurse-ng/app/web/review_routes.py:78), and [account deletion cleanup](/home/recoding/nurse-ng/app/services/accounts.py:314).

4. **Medium — account suspension does not close the public profile link.** Changing a synthetic account to `suspended` or `deactivated` removed it from directory results, but its existing `/p/{public_id}` URL still returned HTTP 200 and displayed its published name. The direct lookup checks profile status without checking account status. This exposes fields previously made public; it does not bypass private-field settings, and it is separate from account deletion. Apply the account-status restriction consistently to direct public lookup. Evidence: [public lookup](/home/recoding/nurse-ng/app/services/profiles.py:320), compared with [directory eligibility](/home/recoding/nurse-ng/app/services/profiles.py:380).

5. **Medium — overlapping document reviews can overwrite each other.** Two database sessions read the same pending case. The first approved it; the second, holding a stale pending object, rejected it successfully. The final case showed rejection and the second reviewer, while the public “Document reviewed” label remained. The status check is performed on the loaded object without an atomic database condition. Use a conditional update or version check and commit the decision and public label together. Reject stale decisions and retain a reliable decision history. Evidence: [decision handling](/home/recoding/nurse-ng/app/services/verification.py:223). This concerns document reviews; recruitment source review has a separate revision mechanism.

6. **Medium — the public job detail overstates publisher verification.** All external listings receive “From a verified publisher” and “Verified publisher” wording. The current staff factual-collection path records `identity_basis="staff_selection"` and explicitly separates that selection from independent identity/licensing checks. The assessment includes this mismatch in the recent changes. The existing published EHA listing uses this staff path. Describe the recorded basis accurately, for example “Staff-selected source,” and reserve stronger claims for the evidence actually held. Evidence: [public wording](/home/recoding/nurse-ng/app/templates/jobs/show.html:15), [source panel](/home/recoding/nurse-ng/app/templates/jobs/show.html:36), and [staff approval evidence](/home/recoding/nurse-ng/app/services/recruitment.py:313).

7. **High product priority — enabled collection has not yet produced reliable vacancy coverage.** The initial snapshot had 120 approved sources and authorized collectors, 33 sources marked healthy, and one current public job. The worker was progressing through its queue. The exception queue grew from six to ten records during the assessment. It includes repeated recruitment titles, category pages, a library-services page, and old admission notices. Publication checks are holding these records, which is useful protection, but the extraction is creating avoidable review work. Improve candidate selection and deduplication, verify that source URLs lead to appropriate recruitment pages, and measure fresh valid vacancies from a smaller set of dependable sources before expanding coverage. The observations do not establish a steady-state collection failure rate.

8. **High readiness gap — dependable production operation is unproven.** The observed app uses a local Uvicorn reload server and SQLite. Local settings enable development/debug mode and HTTP cookies; those settings are appropriate only for this local context. The recruitment worker was observed running. Notification and Reels workers were not observed, although both corresponding queues were empty, so this is not evidence of lost messages or uploads. `/healthz` checks process liveness only. No application CI/deployment configuration or completed restore drill was found in the reviewed repository. Before public launch, verify production HTTPS/settings, supervise the web process and required workers, monitor queue age and failures, and demonstrate restoration of the database and private files. If PostgreSQL is selected for deployment, exercise migrations, locking, and worker recovery on it. Evidence: [liveness endpoint](/home/recoding/nurse-ng/app/web/routes.py:14), [worker commands](/home/recoding/nurse-ng/app/cli.py:71), and [documented operating limits](/home/recoding/nurse-ng/docs/RECRUITMENT_SOURCE_OPERATIONS.md:137).

**Collection snapshot and review access**

The read-only aggregate snapshot was taken at **01:48 UTC on 10 November 2026**. Counts are observations at that time, not a permanent readiness guarantee.

| Measure                                   | Observed value                                                                       |
| ----------------------------------------- | ------------------------------------------------------------------------------------ |
| Approved sources                          | 120; 118 staff approvals and 2 automatic approvals                                   |
| Authorized collectors                     | 120                                                                                  |
| Sources marked healthy                    | 33                                                                                   |
| Sources still unchecked                   | 6                                                                                    |
| Sources with other recorded health states | 81; includes earlier processing, scope, connection, DNS, and other failures          |
| Current public vacancies                  | 1 — Medical Laboratory Scientist - Lagos                                             |
| Latest confirmation of that vacancy       | 00:58 UTC on 10 November                                                             |
| Pending vacancy records                   | 6 initially; **10 on the later follow-up**, including records collected at 02:13 UTC |
| Queued worker tasks                       | 98 at the initial snapshot                                                           |

Historical failed-task totals include previous attempts and cannot be used as the current failure rate. A momentary zero “running” count can occur between tasks or during cooldowns.

Open **Staff → Recruitment sources → Review vacancy exceptions**, directly below the source filters, or use [Vacancy review](http://127.0.0.1:8000/recruitment/vacancies?state=pending). Click a record title to inspect its original extracted data and the validation issues. This queue is separate from source approval.

The ten records inspected on the follow-up were held for these reasons:

| Candidate records                                      | Count | Recorded publication blockers / assessment observation                                       |
| ------------------------------------------------------ | ----- | -------------------------------------------------------------------------------------------- |
| Medical and pharmaceutical category/search pages       | 4     | Missing employer and closing date; these appear to be category pages.                        |
| CBN graduate trainees/specialists                      | 3     | Missing employer and closing date; repeated title requiring duplicate review.                |
| Medical Library Services                               | 1     | Missing closing date; appears to describe a service rather than a vacancy.                   |
| Nursing-school forms/admissions from 2024 or 2024/2025 | 2     | Missing closing date; one also lacks a country. These do not establish current job openings. |

All ten had missing or ambiguous deadlines; seven lacked an employer and one lacked an explicit country. These are candidate records requiring investigation. Do not infer employers or dates to clear validation. Check genuine vacancies against their original announcements, and reject duplicates or unrelated records after inspection.

**Usability and product direction**

The home and Jobs screens have a consistent visual design, clear search controls, readable cards, and useful behavior on a normal 390-pixel mobile viewport. Form feedback, retained drafts, explicit application consent, and account/session recovery are substantial strengths. Password reset and session revocation are implemented; older assessment text describing them as missing is obsolete.

Staff work needs clearer navigation. Staff links sit below a long workspace menu, while the recruitment page combines sources, approval, schedules, and task diagnostics. The user's difficulty locating reviews and understanding collection choices is consistent with that layout. Put “Review pending records,” “Add source URL,” and “View published vacancies” near the top of a staff landing page, with counts. Separate source approval, collection health, and published-vacancy counts in the interface. Explain queued/running/failed states and show whether the next action belongs to the worker or the operator.

Google and LinkedIn integrations exist in code, but neither provider is configured in the inspected local environment; the browser check confirmed the unavailable-provider feedback. Complete and verify those integrations before presenting them as available sign-in options. Learning currently provides curated external resources and an application-preparation guide.

The next implementation pass should address findings 1–6, improve extraction and deduplication using the actual exception records, and make staff review easier to find. Public launch then needs the operational evidence in finding 8 and a sustained run demonstrating fresh, relevant vacancies. No arbitrary numerical quality score is assigned.

**Reproduction and local evidence**

The full suite was run with:

```sh
NURSE_NG_DATABASE_URL=sqlite:// NURSE_NG_ACCOUNT_MAIL_BACKEND=disabled \
  venv/bin/python -m pytest --tb=short -o faulthandler_timeout=45
venv/bin/ruff check . --output-format concise
venv/bin/python -m pip check
venv/bin/python tests/browser/quality.py
```

Additional assessment scripts and artifacts are local temporary files and may be removed by system cleanup:

- [Isolated reproduction script](/tmp/nurse-ng-app-assessment-probes.py) and [results](/tmp/nurse-ng-assessment-probes-s6mk7y7m/results.json).
- [Aggregate database snapshot](/tmp/nurse-ng-app-assessment-status.json) and [pending-record follow-up](/tmp/nurse-ng-assessment-pending-vacancies.json).
- [Chrome quality audit results](/tmp/nurse-quality-browser-eolpx1jf/audits.json).
- [Public-page inspection results](/tmp/nurse-ng-public-assessment-7zj3htpr/results.json), [mobile home](/tmp/nurse-ng-public-assessment-7zj3htpr/390-home.png), and [mobile Jobs](/tmp/nurse-ng-public-assessment-7zj3htpr/390-jobs.png).
