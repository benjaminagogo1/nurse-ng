# Vacancy coverage — 14 November 2026

Measured at **05:35:44 UTC** from the configured local `nurse_ng.db`, using a
read-only SQLite connection and transaction. The recruitment worker had a fresh,
healthy heartbeat. No collection, review, publication or database migration was
triggered by this check. The [aggregate snapshot](vacancy-coverage.json) preserves
the counts and stored review issues.

| Measure | 13 November assessment | 14 November snapshot |
| --- | ---: | ---: |
| Recruitment sources | 140 | 144 |
| Approved sources | 126 | 130 |
| Approved sources marked healthy | 70 | 73 |
| Jobs eligible for public listing | 2 | 2 |
| Pending vacancy records | 84 | 90 |
| Duplicate vacancy records | 15 | 15 |
| Rejected vacancy records | 22 | 22 |

Discovery has added sources and pending records without increasing the number
of publicly eligible jobs in these two snapshots. This is a comparison of
snapshots, not a measurement of every change between them.

## What can appear publicly

The two eligible jobs are both at eHealth Africa, in Nigeria:

- Medical Laboratory Scientist - Lagos.
- People and Culture Intern.

Neither title is a nursing position. Four vacancy records have a `published`
state, but the corresponding jobs comprise two `open` and two `unconfirmed`
listings. A published record alone does not establish present eligibility.

The withheld jobs are **Senior Nursing Officer** and **Procurement Intern
(NYSC)**. Both depend on the MyJobMag Lagos State Ministry of Health source,
which is marked `processing_error`. The Senior Nursing Officer confirmation
is also older than the 48-hour freshness limit.

A follow-up read found that source's latest failed check at **05:19 UTC**:
“Invalid adapter output. No partial discovery was committed.” This is a generic
failure message from result processing; it does not identify the underlying
exception or establish that the external website is unavailable.

## Why records remain pending

| Stored review issue | Pending records affected |
| --- | ---: |
| Health or Nigerian early-career relevance requires review | 77 |
| Missing or ambiguous deadline | 13 |
| Missing explicit country | 11 |
| Missing employer name | 8 |

Issue counts overlap. None of the 90 pending records has an empty issue list.
These are stored issues, not a fresh verification of the original announcements.

**82 of 90 pending records** come from the source groups named “Federal Ministry
of Health Jobs in Nigeria | MyJobMag” (45) and “Lagos State Ministry of Health
Jobs in Nigeria | MyJobMag” (37). Examples awaiting relevance review include
Head of Secondary School, Sales Partner, Head of Aquaculture and Agric Officer.
The concentration and mixed titles suggest that these sources need more precise
vacancy selection and detail extraction.

Potentially useful records include **Nursing Officer (Cardiothoracic)** and
**Nursing Officer (Psychiatry)** at Lagos State Ministry of Health. Both lack a
stored employer name and deadline and were last seen on 10 November. Their
titles alone do not establish that applications remain open.

## Collection status and next work

All 130 approved sources satisfy collector authorization, but only 73 are
currently marked healthy. The other 57 have stored connection, redirect, DNS,
timeout, HTTP/TLS, scope, policy, access, rate-limit or processing problems.
In the preceding 24 hours, 248 collection tasks finished with
`vacancies_collected`; this counts tasks, not distinct sources or new jobs.

The evidence points to three immediate priorities:

1. Diagnose the MyJobMag processing failure and improve selection of relevant
   announcements from the two groups generating most pending records.
2. Check the original announcements for promising nursing roles and obtain
   explicit employer, location and application-status/deadline evidence.
3. Address failures on useful recruitment sources and measure new eligible
   nursing vacancies, rather than treating source count as coverage.

## Measurement boundary

The database is still at revision `e6480d3fb942`; the employer/evidence migration
`e6480e5a1072` from the preceding implementation has not been applied. All four
stored jobs are external, so this check used the unchanged external-source
branch of `open_job_condition()` and selected only existing columns. This avoids
referencing the new employer tables and column. It measures data eligibility,
not a successful browser/API response from the current application. The pending
migration must be addressed before running the updated application against this
database. The generic source-processing error alone does not prove its cause.

**Follow-up at 06:09 UTC:** the pending migration was subsequently applied after
a backup and trial migration. Both the home and jobs pages returned HTTP 200;
see the [live migration record](live-migration.json). The coverage figures above
remain the original 05:35 UTC snapshot.
