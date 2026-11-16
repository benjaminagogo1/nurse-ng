# Community engagement delivery — 16 November 2026

All four requested journeys are implemented locally: shared-interest communities,
useful questions/answers, learning activities and invitations with authentication
continuity. The [member/operations guide](../../../COMMUNITY_ENGAGEMENT.md) describes
the delivered behavior and remaining wider backlog.

## Passing verification

- [Related Python regression](regression.xml): **265 cases passed**, zero failures
  or errors, in 863.505 seconds. Covers community ownership/privacy, joining,
  unanswered questions, Helpful/selected answers, learning metadata, invitations,
  password/social authentication, notifications, offline operations, Reels,
  interests/onboarding and migration history.
- [Final invitation-authentication recheck](invitation-auth-final.xml): two
  cases passed after refining signup feedback. These are already included in
  the 265 distinct cases and are not counted twice.
- [Community Chrome results](community-browser/results.json): hosted-community
  creation, public invitation signup and exact conversation return, joining and
  personal feed, a colleague's reply, Helpful and selected-answer actions,
  activity draft recovery, WAT date/time, WhatsApp URL, clipboard/manual-copy
  fallback, native-share/cancellation stubs and offline activity editing with
  one confirmed synchronization all passed.
- [Accessibility audits](community-browser/audits.json): **27 page states passed**,
  nine each at 390px/light, 320px/dark with 32px root text, and 1280px/light. Zero
  selected WCAG axe violations, horizontal overflow or JavaScript exceptions.
  Manual/incomplete axe checks are retained separately; this is not a claim of
  complete assistive-technology or physical-device verification.
- The final existing `tests/browser/community_drafts.py` journey passed after
  the shared navigation fix: reply context, changed/removed targets, linked
  publication, failed/offline submissions, history, tab isolation, storage
  expiry/failure, cross-tab logout and account switch. Selected screenshots are
  retained under [draft-browser](draft-browser/).
- Final `npm test --prefix mobile`: **four Node cases passed**, including the
  bundled native offline workspace, in 15.291 seconds. This is a bundle/config
  check, not an Android/iOS signing or physical-device build result.
- Final Ruff, JavaScript syntax, 84 template parsing and whitespace checks passed.

The Python regression finished before the final browser-discovered JavaScript
navigation adjustment. Both complete browser runners and the native bundle
checks passed afterward. Initial failed/interrupted diagnostic runs are not
counted as passing: they exposed the draft guard treating intentionally disabled
activity fields as signed-out state, and fragment-only action redirects leaving
the old conversation visible. Both defects were fixed. Other initial runner
issues involved required-field selectors and waiting for complete page loads.

Inspected screenshots:

- [390px activity](community-browser/activity-390-light.png)
- [320px dark enlarged text](community-browser/activity-320-dark.png)
- [1280px activity](community-browser/activity-1280-light.png)
- [Existing targeted-reply journey](draft-browser/targeted-reply-mobile.png)

## Local rollout

[Private-copy rehearsal](migration-rehearsal.json) verified upgrade, downgrade
and upgrade again while preserving all original column values in **11,609 rows
across 50 existing tables**. Integrity, foreign keys and Alembic metadata checks
passed.

At 21:19 UTC, the [local migration](migration-apply.json) paused the existing
worker supervisor, took a fresh private SQLite backup, upgraded from
`e6480f6b2183` to `e6480g7c3294`, verified the same row-preservation checks and
restarted the supervisor. Backup:
`.local-backups/community-growth-apply-20261116T211916/before.db`.
The actual backup remains private and ignored by Git.

The [final local HTTP checks](local-pages.json) returned HTTP 200 for all eleven
checked pages, including `/communities`, `/feed/unanswered`, `/activities`,
`/healthz` and `/readyz`. Readiness reports `ready`; recruitment, Reels and
notification workers are healthy. The local pilot opens at
`http://127.0.0.1:8000/communities`.

Browser data, mail and transports were isolated; no real invitation or provider
callback was sent during verification. Communities remain public and membership
is a private feed preference. The migration seeds no member activity. Changes
remain local and uncommitted. Physical share sheets, live Google/LinkedIn
credentials, reachable HTTPS hosting and public deployment remain outside these
checks.
