# Employer approval and private evidence operations

This change implements findings 1, 3, 4 and 5 in the 13 November repository
assessment. Staff MFA and the publisher-label finding are separate work.

## Upgrade

Install `requirements.lock`, back up the database and private evidence store, and
run `venv/bin/alembic upgrade head` before restarting web and worker processes.
The new revision is `e6480e5a1072`. It preserves accounts, listings, applications,
cases and evidence records; it grants no organization approval and marks existing
evidence as requiring checks. Downgrades refuse to discard recorded approvals or
evidence safety/retention state.

## Employer approval

Employers request membership at `/employers/organizations`, providing the
organization's registered name, official HTTPS website and their recruiting role.
Each account must verify its email through account settings. Requests alone
grant no publishing or application access.

Staff use `/staff/employers` (also linked in the sidebar) to record independent
organization and recruiting-authority checks. A reviewer cannot approve their
own membership. Check organization registration and confirm the person's role
using contact information obtained independently from the submitted request.
Both checks and a decision note are required for approval. The audit retains the
reviewer, organization, membership, action, note and timestamp.

Publication accepts only a server-selected approved organization. Its ID is
stored on the listing. Applicant access remains limited to the original listing
owner, with active approved membership, approved organization, active employer
account and verified email. Other members of the same organization do not gain
access to that owner's applications. Revocation, organization suspension, account
suspension or loss of email verification withdraws publication eligibility and
applicant access, including direct URLs and notifications. Nurses retain access
to their own submitted applications.

Existing employer listings are withheld until reviewed. Approving a membership
does not automatically trust matching old listings. Staff can explicitly select
the additional legacy-listing confirmation when they have checked those listings
and their applicant access. This binds only that account's unbound listings under
the exact approved organization name. External-source listings are unaffected.

## Private evidence

Uploads first enter a private temporary file, with directory permissions 0700
and file permissions 0600. A bounded subprocess parses complete JPEG/PNG images
or PDFs. It rejects encrypted PDFs, active scripts, embedded files, more than
25 pages, oversized decoded content and malformed structures. CPU, memory and
wall-clock limits constrain parsing. Original bytes and their SHA-256 are retained.

Install ClamAV and keep its signature database updated using the deployment's
package/update service. `NURSE_NG_EVIDENCE_SCAN_COMMAND` defaults to `clamscan`;
`clamdscan` can be configured where its daemon has access to private files. The
configured command receives `--no-summary` and the private filename; no shell is
used. Exit 0 means clean, exit 1 means infected, and all other results, missing
executables and timeouts reject the upload as temporarily unavailable. There is
no production or development bypass. Test suites use an explicit synthetic
scanner and exercise clean, infected, unavailable and timeout outcomes.

Only validated, successfully scanned files are released from quarantine. Reviewer
downloads and approval also check scan state, expiry, size and digest. Responses
are attachments with `no-store` and `nosniff`. Legacy files are inaccessible until
`maintain-evidence` validates and scans them; invalid files remain unavailable.

The store remains on the private filesystem. Provision encrypted storage,
restricted service permissions, private backups and matching backup retention
in the deployment; this change does not provision encryption or object storage.
Never expose the evidence directory through the web server or a public mount.

## Retention and maintenance

Defaults retain evidence for 90 days after a decision or 180 days for unresolved
cases. Configure the two `NURSE_NG_EVIDENCE_*_RETENTION_DAYS` values to the approved
operational policy before enabling the timer. Access expires even if cleanup is
delayed. On purge, evidence rows retain audit metadata and hashes, while original
filenames and case registration numbers are cleared. Pending cases become
expired so the nurse can submit a new request; prior approval labels remain.

Preview the next batch, then execute it:

```sh
venv/bin/python -m app.cli maintain-evidence --dry-run
venv/bin/python -m app.cli maintain-evidence
```

The dry run performs no scans, writes or deletions. Maintenance processes up to
100 expired cases and 100 pending documents per pass. It records durable file
deletions before touching disk and retries failed removals on subsequent passes.
Unreferenced upload/quarantine remnants receive a 24-hour grace period. A scanner
outage keeps legacy documents pending and returns a nonzero exit status.

The supplied user-systemd units follow the existing `%h/nurse-ng` deployment
layout and read its `.env`. Adjust the paths if necessary, install both files from
`deploy/systemd/nurse-ng-evidence.*` into the service user's systemd directory, then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now nurse-ng-evidence.timer
systemctl --user list-timers nurse-ng-evidence.timer
journalctl --user -u nurse-ng-evidence.service
```

The timer runs hourly and catches up after downtime. Monitor failures, scanner
signature updates, disk usage and the private backup retention process. A code
upgrade alone does not install the scanner or activate the timer.

## Regression checks

The [14 November verification record](verification/2026-11-14/README.md) preserves
the interrupted-session recovery and final test results.

`tests/test_employer_approval.py` covers pending requests, staff decisions,
self-approval, organization scoping, verified contact, legacy withholding and
revocation across publication, applicant URLs and notifications.
`tests/test_evidence_safety.py` exercises real document parsing, synthetic scanner
failure modes, private permissions, legacy checks, integrity, expiry, orphan grace
and retried deletions. Existing profile/reply tests now inspect HTML attributes
instead of indentation. The notification browser test checks the persisted sent
state and a correctly addressed private inbox email instead of CLI wording.
The accessibility runner checks the registration/login heading's text ranges for
clipping, as well as the existing axe audits at 320 pixels with enlarged text.

## Local setup completed on 14 November

The current computer uses project-local ClamAV without sudo, with a six-hour
signature updater and hourly evidence retention. See [local operations](LOCAL_OPERATIONS.md)
for installation, active timers, tested backups/restoration, and the two legacy
evidence files that were already missing from disk.
