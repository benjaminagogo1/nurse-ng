# Vacancy coverage and local operations — 14 November 2026

Completed the requested job-coverage and operational work. MFA remains deferred.
No system package installation or sudo access was needed.

## Vacancy coverage

The final measurement at **12:45:41 UTC** uses the full public Jobs eligibility
predicate. Publicly eligible jobs increased from **2 to 3**. The added listing is
Office Assistant / IT Trainee at Desol Medical Solutions Limited, an eligible
Nigerian early-career opportunity; this is not an increase in confirmed nursing
vacancies.

Both MyJobMag ministry sources completed live collection successfully. The old
Lagos-source `processing_error` did not recur in a fresh isolated replay or the
live worker. That failure predated the employer-table migration; its generic
message prevents a conclusive historical diagnosis. New diagnostics identify
saving/network-processing stages and exception categories without logging SQL
parameters or page contents.

Selection now prioritizes nursing links, reserves room for other relevant health
roles/programmes and channel discovery, rotates within relevance groups, and
filters unrelated structured adverts. Existing source permissions, request
bounds and publication checks remain enforced.

The operator previewed and excluded **78 unrelated unreviewed adverts**, retaining
their audit trail. The queue now contains **16 pending records**: all 16 lack a
usable deadline, 11 also lack employer evidence and 5 lack explicit country
information. Categories overlap. None has an empty issue list. The 144 registered
sources include 130 approved; 70 approved sources were healthy at the final
measurement. Network errors remain on other sources, so no broad-coverage claim
is made.

- [Final aggregate measurement](vacancy-coverage-after.json)
- [Successful collector refreshes](collector-recovery.json)
- Repeat with `venv/bin/python -m app.cli vacancy-coverage`.

## Scanning, retention and backups

ClamAV **1.5.4** and official verified signatures run from `.local-tools/clamav/`.
A real valid PDF passed upload parsing/quarantine/scanning; the harmless EICAR
antivirus test file was rejected. Update checks run every six hours. Scanning
fails closed after 72 hours without a successful update check.

Four user timers are enabled: hourly evidence maintenance, daily backups, hourly
backup expiry, and six-hour signature updates. All four services were run and
returned exit status 0; the worker supervisor is running and the homepage
returned HTTP 200. Evidence retention is 90 days after a decision or 180 days
unresolved. Backups expire after seven days, or earlier if included evidence
expires sooner.

Restoration to a new isolated directory passed database integrity and foreign-key
checks, every table's row counts, migration revision, and all included file
hashes. The database and five existing avatar/media objects were recovered.
The live database was not overwritten; the temporary restored copy was removed.

**Pre-existing loss:** two older evidence documents already had no files on disk.
Maintenance records them as `missing`; staff see that replacements are needed.
Their database/audit rows are retained, and the backup/restore reports explicitly
count them as unavailable. The tool does not claim to recover missing bytes.

These private local backups do not protect against loss of the office computer.
An approved encrypted off-device destination remains a separate deployment
choice. User timers operate while the user service manager is running and catch
up after downtime. No system-wide service or login lingering was enabled.

- [Scanner proof](scanner.json)
- [Enabled timers and successful service results](operation-services.json)
- [Latest isolated restore proof](restore-drill.json)
- [Installation and recovery instructions](../../LOCAL_OPERATIONS.md)

## Verification

- Full regression suite: **757 passed**, 831.58 seconds. One existing pypdf test
  helper emits a deprecation warning. [JUnit report](operations-full.xml).
- Final follow-up checks after small backup/selection changes: **7 passed**, then
  **2 passed** for rotation and review-preserving cleanup.
- Ruff, `git diff --check`, script/template parsing and `pip check` passed.
- Real application readiness returned `{"status":"ready"}`.
- `.github/workflows/checks.yml` runs Ruff and isolated pytest on pushes/PRs and
  manual dispatch. It is added locally; no remote workflow run is claimed.

Tests used isolated databases and disabled outgoing account mail. Earlier
sandboxed runs stalled and were stopped; the complete suite ran with permitted
local process/network access. No real external message was sent, and no admin
roles were changed during this work.
