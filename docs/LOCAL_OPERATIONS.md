# Local operations without administrator access

The 14 November setup uses user systemd services and project-local ClamAV. It
requires no sudo and changes no system packages. MFA was deferred by the user.
This is a local pilot setup; the computer must be on and its user service manager
running. Persistent timers catch up after downtime.

## Document scanning

On Ubuntu 24.04, install the packages into the project and download official,
verified signatures:

```sh
deploy/install-local-clamav.sh
```

This uses `apt-get download` and `dpkg-deb -x`, not system installation. The
packages and signatures live in ignored `.local-tools/clamav/`. Rerun after
Ubuntu publishes ClamAV engine updates. The installer is specific to Ubuntu's
`libclamav12`/`libmspack0t64` package layout; other systems need their supported
ClamAV package or an administrator-managed scanner.

Configure the absolute command in `.env`:

```dotenv
NURSE_NG_EVIDENCE_SCAN_COMMAND="/home/recoding/nurse-ng/deploy/clamav-local scan"
```

The updater preserves certificate verification, uses official signature servers,
and checks every six hours. Uploads fail closed if scanning fails, signatures
are absent, or the last successful update check is more than 72 hours old. Files
are structurally validated and quarantined before release. The live check
accepted a valid PDF and rejected the harmless EICAR antivirus test file.
See [scanner evidence](verification/2026-11-14/scanner.json).

Evidence maintenance runs hourly: 90 days after a decision, or 180 days for an
unresolved case. Preview with `python -m app.cli maintain-evidence --dry-run`.
Missing historical files receive `scan_status=missing`; their audit records
remain and downloads/approval remain blocked. Maintenance found two such files
already absent on this computer. They cannot be reconstructed from a database.
Recover their originals from another copy or request replacement documents.

## Backups and restoration

`python -m app.cli backup` creates a private directory in
`.local-backups/automatic/`. It reserves SQLite's writer lock while taking a
consistent database snapshot and copying referenced avatars, community media
(including Reel variants), and private evidence. Keep this operation on a small
local pilot database: the writer reservation briefly delays writes and is not a
large-database backup strategy.

Each backup contains file sizes/SHA-256 hashes, migration revisions, table counts,
and a manifest. Creation fails on missing or changed referenced files. The sole
exception is evidence already marked `missing` by maintenance: its unavailable
state remains in the database, and the report explicitly counts it. No recovered
file or successful scan is invented. Expired documents must be maintained before
backup; expired backups are removed hourly. Backup retention defaults to seven
days and is shortened to the earliest evidence expiry in that snapshot. The
restorer refuses expired backups.

Directories are 0700; files are 0600. The tools reject symlinks, public upload
locations, malformed manifest paths, missing files and digest mismatches. Backup
creation and expiry cleanup share a lock. Only generated `backup-*` directories
in the configured automatic backup root are pruned; older manual migration
backups are not silently deleted.

Restore to a **new private directory**, never over the running database:

```sh
venv/bin/python -m app.cli restore-backup \
  .local-backups/automatic/backup-TIMESTAMP \
  .local-backups/restored-inspection
```

The restored layout is `database.sqlite3`, `avatars/`, `community/`, and
`evidence/`. The command verifies integrity, foreign keys, migration revision,
all table counts and referenced file digests before publishing the destination.
The [completed isolated restoration](verification/2026-11-14/restore-drill.json)
recovered the database and five existing media/photo files; the two previously
missing evidence files remained explicitly unavailable. The temporary drill
copy was removed afterward; the source backup remains private.

For actual recovery, stop web and worker writers, configure these restored paths,
restore secrets from their separate secure source, upgrade migrations if needed,
and validate before enabling mail delivery/workers. Unfinished resumable-upload
chunks and disposable processing files are not backed up; clients must restart
those unfinished uploads after disaster recovery. `.env`, mail spools, caches and
ClamAV packages are intentionally separate. Source code and migrations belong in
version control. A same-disk backup does **not** protect against device loss;
choose an approved encrypted off-device destination for that protection.

## Timers and checks

Install the reviewed unit pairs from `deploy/systemd/` into
`~/.config/systemd/user/` (adjust `%h/nurse-ng` for another checkout), then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now nurse-ng-evidence.timer nurse-ng-backup.timer \
  nurse-ng-backup-retention.timer nurse-ng-clamav-update.timer
systemctl --user list-timers 'nurse-ng-*'
systemctl --user --failed
venv/bin/python -m app.cli worker-status --json
```

Evidence maintenance and backup expiry run hourly; backups run daily; signatures
update every six hours. The [service record](verification/2026-11-14/operation-services.json)
shows the four timers enabled and the worker supervisor running. Check service
journals for failed runs. No administrator access or login lingering is assumed.

`.github/workflows/checks.yml` runs Ruff and the isolated pytest suite on pushes,
pull requests, and manual dispatch. Tests disable real outgoing mail. This
workflow is prepared locally and starts on GitHub after the change is pushed.
Browser runners remain separate manual checks. The staff evidence page now
identifies missing files and asks for replacement documents; page layouts are unchanged.

## Vacancy coverage

Measure actual public eligibility at any time:

```sh
venv/bin/python -m app.cli vacancy-coverage
```

It uses the same full predicate as the Jobs page and reports pending review
blockers. [The current measurement](verification/2026-11-14/vacancy-coverage-after.json)
is separate from the historical assessment.

The factual collector rotates within relevance groups, prioritizes nursing
adverts, reserves a request for discovering recruitment channels, and filters
unrelated structured adverts. It retains the existing four-detail-page limit,
approved source scopes, dates, current-application checks and staff decisions.
The worker logs the failure stage, exception category and stack locations without
SQL parameters or source-page prose.

The original MyJobMag processing failure preceded the employer database migration.
A fresh response applied successfully in an isolated database, and the live
worker then refreshed both MyJobMag ministry sources successfully. The old
exception cannot be reconstructed from its generic log, so the migration is a
plausible explanation, not a proven historical root cause.

The operator previewed and applied `reconcile-vacancies --exclude-unrelated`,
removing 78 unreviewed unrelated adverts from pending work. Audit records remain;
existing staff clarifications and rejection decisions are preserved. Use
`--dry-run` to preview future cleanup. Missing deadlines/employer facts still
need evidence; increased source counts alone do not establish more open jobs.

An approved staff-selected factual source can now target a current recruitment
channel inside its existing publisher scope. Preview the exact source/channel
pair, then repeat without `--dry-run` to apply it:

```sh
venv/bin/python -m app.cli set-collection-channel \
  --source-url https://www.myjobmag.com/jobs-at/federal-ministry-of-health \
  --channel-url https://www.myjobmag.com/jobs-by-industry/medical --dry-run
```

The source URL must identify exactly one registered source. The command records
an operator-configuration audit event, preserves existing approval evidence and
scope, rejects concurrent changes, and makes the source due for its normal worker
check. It does not grant approval. The selected channel uses one of the existing
four detail requests; up to three actual adverts follow it, rotating across
checks. Category pages no longer take the priority assigned to individual roles.

The live MyJobMag sources now target nursing/midwifery and broader healthcare
channels. Other existing sources continue collecting. Midwifery, community health,
internships, fellowships and graduate opportunities remain supported; collection
does not require applicants to be registered nurses. At 14:13 UTC on 14 November,
the public Jobs predicate returned **6 opportunities**, up from **3** before this
configuration. See the [channel collection report](verification/2026-11-14/COLLECTION_CHANNELS.md)
for the measurement and validation.
