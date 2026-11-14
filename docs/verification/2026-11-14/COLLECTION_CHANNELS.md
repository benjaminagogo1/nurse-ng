# Current recruitment channels — 14 November 2026

Publicly eligible opportunities increased from **3 at 14:10 UTC to 6 at 14:13 UTC**.
Both measurements use the application's full public Jobs predicate. A guest HTTP
request to `/jobs` returned 200 and displayed all six opportunities.

The three added listings are Registered Nurse at St Dominic Catholic Hospital,
Oncology Nurse at Ascentech Services Limited, and Nurse at Baptist Mission Schools.
The existing Medical Laboratory Scientist, People and Culture Intern, and Office
Assistant / IT Trainee listings remain eligible. This is an increase in current
inventory, not evidence of increased adoption or comprehensive vacancy coverage.

## Collection change

An operator can select a current recruitment channel within an already approved
staff-selected factual source's scope. The two existing MyJobMag sources retain
their original registered URLs and approval evidence:

| Registered source | Selected collection channel |
| --- | --- |
| Lagos State Ministry of Health page | `https://www.myjobmag.com/jobs-by-title/nurse` |
| Federal Ministry of Health page | `https://www.myjobmag.com/jobs-by-industry/medical` |

The original registered page is still checked. The chosen channel consumes one
of the existing four detail requests, followed by up to three current adverts.
Rotation continues across checks. Category links cannot take individual-role
priority. Sources still retain factual fields and original links only; publisher
prose is not retained or republished by this factual-index mode.

Configuration supports dry runs, is idempotent, preserves scope/approval, and uses
revision checks to reject a concurrent source change. Audit events identify an
operator CLI configuration with no invented staff actor. No source approval was
added or extended. Normal queue limits, request limits and publication checks
remain in force. A private backup was completed before applying configuration.

Both normal worker checks completed successfully, and their next checks are
scheduled six hours later. The recruitment and Reels workers reported healthy
after restarting the existing user supervisor; no sudo was used.

## Audience and limits

The app remains free, and this pass adds no RN or member-verification requirement.
Existing collection rules support midwifery, community and public health,
internships, fellowships and graduate programmes, alongside nursing roles.
An integration test explicitly publishes Midwife, Community Health Extension
Worker and Medical Intern through the real collection/ingestion path. These test
fixtures are not claims that those three exact titles are currently live.

The user-rejected homepage/dashboard engagement drafts were discarded. This pass
does not add Community/Reels previews, joining prompts or sharing/invite controls.

Sixteen older records remain pending: all lack a usable deadline, eleven also
lack employer facts and five lack explicit country information. Categories
overlap. No dates were invented to publish these records. Other registered sources
still have network/access failures; six current opportunities is a limited result.

## Evidence

- [Before measurement](channel-coverage-before.json).
- [After measurement and both worker outcomes](channel-coverage-after.json).
- [Collection regression tests](collection-channels-tests.xml): **213 passed** in
  90.30 seconds, using isolated databases and disabled account email.
- Ruff on changed collector/CLI/test files and `git diff --check` passed.
- Live guest `/jobs`: HTTP 200, six results, all three new employers present.

Repeat the aggregate measurement with `venv/bin/python -m app.cli vacancy-coverage`.
See [operator instructions](../../LOCAL_OPERATIONS.md) for configuring a channel.

## Additional user-requested pass

At 14:24 UTC, the operator requested one additional check of each configured
source through the normal queue, with truthful operator audit events. There were
343 of 600 daily attempts used before queuing. No settings, collection limits or
application code changed for this repeat.

Both checks finished by 14:26:48 UTC. The healthcare source collected no eligible
records and reported one unavailable detail page. The nursing source refreshed
three existing listings. Final public eligibility remained **6**, with **no new
eligible listings** from this pass. The next normal checks are scheduled at
20:25 and 20:26 UTC, subject to the computer/workers running and queue limits.

- [Request and before measurement](repeat-collection-request.json).
- [Completed checks and after measurement](repeat-collection-after.json).
