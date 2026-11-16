# Saved reminders, notification worker and LinkedIn contrast

Implemented the three fixes requested from the assessment summary on
16 November 2026. Source wording and the deferred MFA work were not part of
this increment. Changes remain local and uncommitted; no deployment or schema
migration was required.

## Behavior

Saved opportunities now follow the retained vacancy during consolidation.
Multiple alias bookmarks become one canonical bookmark, preserving the oldest
saved time and any explicit reminder opt-out. Reminder progress for the current
deadline is retained. Existing matching/deadline notifications follow the same
vacancy; sent/read history suppresses repeated delivery or unread activity.
Redundant notification records remain retained but no longer display or deliver.
Old saved-page save, remove and reminder actions still work for their owner.
Corrupt alias markers cannot redirect bookmarks to another announcement.

The consolidation command also reconciles history left by earlier runs.
Its dry-run rolls everything back, repeat runs are idempotent, and aggregate
repair counts are audited without member identifiers. Pause collection and
notification delivery and avoid member save/reminder edits during maintenance,
as described in [local operations](../../../LOCAL_OPERATIONS.md).
Existing SMTP crash/retry behavior remains at-least-once.

The supervisor default now includes `notifications`, and both the example and
actual local configuration require `recruitment,reels,notifications`.
Explicit role selections remain supported. The existing user systemd service
was restarted and the local web application reloaded its readiness settings.
Notifications generate opportunity alerts even if email transport is disabled;
email continues to require a verified address and category opt-in.

The LinkedIn mark uses a lighter blue in dark theme. Its measured contrast is
**6.28:1 in dark theme** and **5.08:1 in light theme**. Shared stylesheet and
service-worker cache versions were advanced so cached installations receive
the updated CSS.

## Verification

| Check | Result |
| --- | --- |
| Reminder, notification and worker regression | **87 passed**, 158.31 seconds. Includes actual supervisor crash recovery for the notification role with outgoing mail disabled. |
| Final duplicate/deadline checks | **39 passed**, 13.07 seconds. Includes the additional queued-alias/file-delivery and invalid-alias checks, plus date-display regression. |
| Distinct automated cases across these two runs | **102 passed**; the overlapping duplicate cases were intentionally repeated after adding the final checks. |
| Queue continuity | A queued alias deadline notification retained its ID, followed the retained vacancy, and produced exactly one private test `.eml` file. Already-sent/read reminders did not repeat. |
| Browser contrast/reflow | **12 login/registration states** in light/dark themes, at 390/1280 pixels and 320 pixels with 200% text. No selected axe violations, JavaScript errors or horizontal overflow. |
| Final static checks | Ruff, whitespace, service-worker syntax and parsing of 81 Jinja templates passed. |
| Local runtime at 13:55 UTC | Supervisor active; recruitment, Reels and notifications all healthy; `/readyz` returned HTTP 200 with `status=ready`. |
| Database | Integrity `ok`, zero foreign-key violations, unchanged migration `e6480f6b2183`, zero saved opportunities stranded on retired aliases. |

The local consolidation preview found zero groups, conflicts or stranded member
history to repair; no live vacancy/bookmark cleanup was necessary. At worker
activation there were zero verified opted-in email preferences and no queued
notifications. The notification worker subsequently generated 20 matching
notification records with email state `skipped`. No real email was sent during
these checks; actual email delivery was tested only against a private file
mailbox in isolated fixtures.

Retained artifacts:

- `regression.xml`, `final-regression.xml`: both successful automated runs.
- `live.json`: actual local required roles, worker health, readiness, integrity
  and aggregate notification email states.
- `contrast-report.json`, `contrast-states.json`: the 12-state browser results
  and measured foreground/background contrast.
- `login-dark.png`, `login-light.png`, `register-dark.png`: inspected browser
  screenshots with the social buttons visible.

Original contrast browser artifacts are at
`/tmp/nurse-auth-contrast-fixes-okvoqghv/`; temporary source is
`/tmp/nurse-ng-auth-contrast-fixes.py`. Private databases, mail files, account
documents and browser profiles are not included in this evidence directory.
The full 823-case assessment suite was not repeated for these focused fixes.

Relevant commands:

```sh
venv/bin/python -m pytest tests/test_vacancy_duplicates.py tests/test_opportunity_watch.py tests/test_worker_operations.py tests/test_notifications.py
venv/bin/python -m pytest tests/test_vacancy_duplicates.py tests/test_date_display.py
venv/bin/python -m app.cli consolidate-duplicate-vacancies --dry-run
venv/bin/python -m app.cli worker-status --json
venv/bin/ruff check . --output-format concise
```
