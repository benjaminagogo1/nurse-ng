# Vacancy duplicate repair — 16 November 2026

Recovered the interrupted comment-link repair and completed local application.
URLs containing comment-reply navigation or advertising tags now share one
vacancy identity. Job-specific query parameters remain distinct, original
evidence remains intact, and disagreeing facts still require review.

## Verification

- The previous session's regression report records **223 passed**, including 20
  new duplicate-repair cases. All implementation/test files were unchanged since
  that run. The report is retained as [pytest.xml](pytest.xml); it was not rerun
  during recovery. Current Ruff and whitespace checks passed.
- A fresh [private rehearsal](rehearsal.json) verified preview rollback, matching
  application results, preserved data, repeat idempotence and database integrity.
- [Local application](cleanup.json) ran with collection paused and a new private
  SQLite backup. The worker supervisor returned to its active state afterward.
- [Live verification](live-verification.json) checked the Jobs page, all three
  retained job details, all nine old job redirects, health and readiness.

| At local application, 12:13 UTC | Before | After |
| --- | ---: | ---: |
| Eligible public listings | 45 | 36 |
| Unique announcement identities | 36 | 36 |
| Duplicate public listings | 9 | 0 |
| Historical job rows | 56 | 56 |

Three groups were consolidated. Nine vacancy records were marked as duplicates;
13 new audit events retained their earlier identities. Job/record row counts,
raw facts, observation times, source snapshots, saved opportunities and all
unrelated tables were preserved. No conflicting group was automatically resolved.
SQLite integrity returned `ok` with zero foreign-key violations.

At **12:17 UTC**, `/jobs`, `/healthz`, `/readyz` and each retained detail returned
HTTP 200. Every old job URL returned HTTP 307 to its retained job; all nine
retired IDs were absent from the feed. Public eligibility remained 36, with zero
duplicate announcement identities. Counts are observations of the current
public predicate and can change as collection continues.

The backup is private at
`/tmp/nurse-vacancy-duplicates-ci48wop3/before.db`; it is not included in this
directory or Git. Application and receipts are local. No schema migration was
required, and source changes remain uncommitted.
