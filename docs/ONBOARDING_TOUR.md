# Interactive onboarding tour

The guided tour highlights real controls on Nurse.ng pages. It uses the existing
FastAPI, Jinja, SQLAlchemy and Alembic architecture, with plain JavaScript and a
native HTML dialog. No tour library or additional storage service is required.

## Using the tour

After successful registration or the first sign-in after installation, an account
receives one small invitation. The tour starts only when **Start tour** is selected.
Registration still opens the optional interests/location welcome flow.

- **Next / Previous:** save progress and open the relevant page.
- **Finish:** available at the last step; records completion.
- **Skip tour:** records dismissal, including when dismissing the invitation.
- **Pause / Escape:** close the tour and keep its current step.
- **Account settings → Your guided tour:** start, resume or restart at any time.
- **Arrow keys:** move between steps. Tab and Shift+Tab stay within the dialog.

An ignored invitation is not repeatedly offered on later sign-ins. Completed and
skipped tours also stay dismissed. A paused tour has a nonmodal Resume option on
signed-in pages; navigating elsewhere never forces a redirect back into the tour.
Only a matching active tour link automatically opens the next step.

The browser must support JavaScript and native dialogs. Without them, ordinary
navigation remains available and Settings explains how to explore the sections.
The tour respects light/dark themes, text size, contrast and reduced motion.

## Available steps

| Step | Page and highlighted control | Accounts |
| --- | --- | --- |
| Dashboard | /auth/dashboard — activity shortcuts | All |
| Professional profile | /profile/edit — display-name field | All |
| Job opportunities | /jobs — search and location controls | All |
| Networking | /nurses — published-profile search | All |
| Reels | /reels — heading and creation controls | All |
| Learning | /learning — first learning-resource card | All |
| Notifications | /notifications — heading and preferences | All |
| Messages | /messages — connections/conversation list | All |
| Employer tools | /employers — posting and candidate controls | Employer |
| User analytics | /staff/users — overview and refresh controls | Staff |

Nurse and partner accounts have eight steps. Employer accounts have nine.
Staff access is independent of account type: a staff nurse has nine, and a staff
employer has ten. The tour does not grant access to any feature.

New users can reach the profile editor without having created a profile. Touring
does not create or publish one, submit forms, send messages, change notification
preferences or complete the separate welcome questions. Copy distinguishes public
profile search, accepted connections, external learning links and job listings.

## Persistence and navigation

Migration **e6480ab31c95** adds the user_tours table, keyed by the existing users.id.
Each account stores its status, current step key, definition version, revision,
run ID and lifecycle timestamps. The foreign key deletes progress with its account.
The users.onboarding_completed_at field continues to describe the separate welcome flow.

Successful authentication offers the tour once using an atomic insert. Actual page
rendering consumes the invitation flag from the signed session; prefetches and
background requests do not. No historical completions or preferences are inferred.
Changing the definition version does not automatically re-offer a dismissed tour.

The offline service worker preserves top-level navigation intent with
`X-Nurse-Navigation: document`. Its timeout-enabled fetch otherwise changes the
browser's fetch metadata from `navigate/document` to `same-origin/empty`, which
previously hid the first invitation. The renderer accepts the hint only with the
matching same-origin metadata on successful GET pages, excluding prefetches. The
hint also preserves ordinary activity counting; it grants no account permissions.
The v9 worker update retains the existing timeout and neutral offline fallback.

**GET /tour** reads the current account's eligible steps and progress. **POST /tour**
accepts a fixed action, revision and run ID, protected by existing authentication
and CSRF checks. The server chooses the step, destination and completion status.
Both responses are private and use Cache-Control: no-store.

Every write compares the saved revision. Duplicate requests and stale tabs receive
409 with current progress; they cannot advance twice or overwrite a restarted run.
After an uncertain network result, the UI asks the user to check saved progress
before continuing. Pausing during a save prevents its response from reopening the
dialog or navigating. A later Resume reads the latest account state. Navigation
controls stay pending until the next document loads, preventing repeated input.

Progress is committed before page navigation. The local tour query parameter
identifies a run, not a user or an authentication credential. Old, completed or
mismatched links cannot restart it. Browser history restoration refreshes progress.

A bounded target lookup tolerates delayed rendering. Hidden or absent targets are
passed over in the chosen direction, with an explanation at the next available
step. If none remain, the tour closes as skipped rather than claiming completion.
Role eligibility is reevaluated on requests.

## Extending the tour

1. Add or update a TourStep in app/services/tours.py. Keep existing keys stable;
   set a local path, accurate copy, and the appropriate account/staff rule.
2. Add its data-tour hook to a real, consistently available control. Prefer a
   small content target that is visible with empty data and on mobile.
3. If a route has aliases, list them on the step. Avoid edit-page redirects, hidden
   desktop navigation, destructive controls or targets replaced by background polling.
4. Extend the role/page tests and run the browser journey. Shared behavior lives in
   app/static/js/tour.js; appearance lives in app/static/css/tour.css.

## Installation and verification

Back up the existing database, then run the additive migration before starting
application workers with the new code:

~~~sh
venv/bin/python -m alembic upgrade head
venv/bin/python -m alembic check
venv/bin/python -m pytest tests/test_tours.py tests/test_tour_migration.py
node --check app/static/js/tour.js
venv/bin/python tests/browser/tour.py
~~~

The browser script uses a temporary migrated SQLite database, test accounts,
an isolated Chrome profile and temporary localhost ports. It saves screenshots
under the printed artifact directory and stops only its own server/browser.
It covers lifecycle, actual mouse/keyboard interaction, responsive positioning,
role-specific steps, missing targets, lost responses and existing display controls.
It waits for the offline worker to control the registration page before submitting,
so the first invitation is exercised through the same path as returning browsers.
Use the same script with --loading-only for focused delayed-save, repeated-input
and pause/resume checks.

The migration creates an empty table and preserves existing accounts and data.
Downgrading refuses to discard saved preferences; export them before removal.
Browser validation uses Chromium emulation; physical-device and assistive-technology
testing, and production PostgreSQL validation, remain separate from these checks.
