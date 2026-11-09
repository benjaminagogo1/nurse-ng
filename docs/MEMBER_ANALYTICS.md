# User analytics and daily activity

The staff dashboard is available at `/staff/users`, under **Staff → User analytics**.
Each user can also see and copy their own permanent account ID in
**Settings → Your account**. This is the existing `users.id` UUID, not a new identity
or a professional registration number. No existing ID is changed.

## Dashboard

- Nurse accounts are selected by default; employers, partners and all accounts are
  available. Staff are excluded by default and can be included explicitly.
- Summary cards show total accounts, enabled accounts, unique accounts active today,
  activity within five minutes, and distinct accounts over the last 7 and 30 days.
- An interactive chart offers 7-, 14- and 30-day views, keyboard-focusable points and
  an equivalent daily-count table. It shows only the available recorded period.
- The user directory supports exact UUID and name search, activity filters,
  25-account pages, copying IDs, account status, last recorded visit and days active
  during the last 30 calendar days. Private profiles need not be published to count.
- Account type and the staff choice control the whole report. Name/activity filters
  narrow the directory without changing the summary cards or chart.
- Visible dashboards refresh every 30 seconds through a staff-protected, uncached
  endpoint. Refresh pauses during selection, keyboard interaction with the results,
  or an open daily-count table. Explicit refresh is also available. Failed/offline
  refresh retains the previous data and labels it accordingly. Revoked staff access
  clears the displayed results. Neither refresh path creates a page visit.
  Without JavaScript, the dashboard accurately labels its data as updated on page
  load and provides a working Refresh view link.
- The interface supports the existing light/dark/high-contrast preferences, keyboard
  controls and enlarged text. On smaller screens user rows become labeled cards.

## What activity means

All calendar-day boundaries use `Africa/Lagos` (WAT, UTC+1), regardless of the
server's or browser's timezone. Timestamps are stored in UTC. Seven and thirty-day
figures include today and count a distinct account once over the entire period;
they are not sums of daily counts.

A successful signed-in HTML page navigation records a visit. Prefetches, fetch
fragments, JSON polling, assets, errors and anonymous requests do not. Without
JavaScript, page navigation still records visits. The browser can renew activity
at most once per minute after a trusted interaction on a visible page. Idle pages,
hidden tabs and automatic notification/messaging/dashboard requests cannot keep an
account active indefinitely. Long passive reading without interaction is therefore
not proof of continuing presence. “Recently active” means a recorded visit within
five minutes; it does not assert a live network connection or exact time spent.

The browser observes wheel, touch, key and pointer input rather than scroll events:
automatic chat scrolling can emit a browser-trusted scroll event without a person
interacting. That automatic movement does not renew activity.

The server derives identity from the authenticated session and uses server time.
The pulse endpoint requires the existing CSRF token and rechecks active account
status and session version. Caller-supplied IDs or timestamps are not used.
Writes are coalesced within a minute, except that a new local calendar day always
gets its own record. Concurrent visits/devices are deduplicated by the database.

Nurse totals describe the account type selected at registration. They do not count
verified professional identities: one person can own more than one account. Daily
history reflects existing accounts under their current type/staff settings. A
suspended account's earlier valid visit remains in period counts, while recent
presence excludes suspended/deactivated accounts. Account deletion cascades to
its activity records and removes that account from these reports.

No activity is inferred from account creation, login lockout counters or profile
updates. History begins with tracked visits after installation; the earliest day
may be partial. There is no backfill of historical usage or seeded user activity.

## Storage, access and deployment

Revision `d537f982ac14` adds `user_daily_activity`, with a composite primary key
`(user_id, activity_date)`, first/last timestamps and date/last-activity indexes.
No URLs, content, IP addresses, device identifiers, or user-agent strings are stored.
Activity is staff-only and is not added to the public directory or public profiles.
Users' own settings explain this visibility. Activity records share the existing
database backup policy and are removed from live storage on account deletion.

Run the usual migration before starting the updated application:

```sh
venv/bin/alembic upgrade head
```

No new dependency, third-party analytics provider or background worker is required.
Page tracking uses a separate short database transaction so it cannot commit a
route's pending business changes. Tracking errors leave the user's page working
and log a fixed, non-sensitive warning. Failed pulse writes return a retryable
failure. Monitor those warnings if counts stop advancing.

The migration creates an empty table and preserves all existing user IDs and data.
Downgrade refuses to silently discard activity history. SQLite is the locally
verified database; the service also uses PostgreSQL's native conflict update, but
production PostgreSQL concurrency and deployment remain separate validation work.

## Verification

`tests/test_activity.py` covers daily boundaries, distinct period counts, staff and
role scopes, repeated/concurrent visits, monotonic times, private access, session
revocation, CSRF, safe failures, account deletion, navigation versus polling,
pagination and migration preservation.

`tests/browser/activity.py` runs an isolated Chrome journey with synthetic accounts
and history. It exercises the dashboard, search, pagination, ID copying/fallback,
live refresh, chart keyboard access, idle/hidden activity, themes, responsive
layouts, enlarged text, offline recovery and staff-access revocation. It never
uses the real application database or sends email. See the work log for the final
local results and artifact locations.

All 538 collected automated tests passed in completed groups of 48, 193 and 297.
The test IDs in the three reports were compared with collection to confirm complete,
nonduplicated coverage. The local database was backed up and the migration tested
on a clone, preserving every original row/column in all 35 existing tables, before
the additive upgrade was applied. Foreign keys and Alembic metadata checks passed.
