# App quality: implementation and verification

## Implemented in this increment

- One feedback area is available on every full page. Profile edits, sharing,
  visibility, document submissions, job publication, applications and status changes,
  community posts/replies/reports/follows/connections, notification read actions,
  onboarding, staff review/collection controls and Reels retry/removal now display
  server-confirmed outcomes. Existing account, message and Reels feedback remains.
- Ordinary POST forms gain pending labels, an announced busy state, duplicate
  submission prevention, visible offline errors and retained entries/files on
  unsuccessful responses. The clicked button's name/value is preserved, including
  forms with separate Accept and Decline actions. Specialized message/Reels upload
  flows keep their own progress and retry behavior.
- Validation errors and permission, missing-item and expired-session responses are
  readable in the interface. Interrupted/timeout responses explicitly say the result
  is unconfirmed and ask members to check before retrying; no automatic retry occurs.
- Community drafts keep their version acknowledgements. Confirmed publication
  clears a draft; enhanced sign-out clears drafts after the server confirms sign-out.
  Error pages leave drafts and pending publication acknowledgements intact, even
  when authentication or the database is unavailable. Validation rejections clear
  the pending submission state; interrupted requests keep it until confirmed.
- Existing Google and LinkedIn controls have [provider integrations](SOCIAL_SIGN_IN.md),
  and the Upcoming events area has [working event publishing and RSVPs](EVENTS.md).
- [Offline & sync](OFFLINE.md) provides selected encrypted records, explicit drafts,
  queued actions and resumable Reel uploads. Pending, failed, conflicting and
  confirmed states remain distinct; ordinary unsuccessful POST forms are not
  automatically converted into queued sends.

Ordinary HTML forms remain available without JavaScript. Without JavaScript there
is no dynamic progress, offline retention or client-side duplicate-submit guard.
Feedback cannot guarantee that retrying a non-idempotent operation is safe after
a lost response; the interface deliberately directs the member to inspect the result.

## Repeatable local checks

```sh
venv/bin/python -m pytest
venv/bin/ruff check app tests
venv/bin/python tests/browser/account_feedback.py
venv/bin/python tests/browser/community_drafts.py
npm install --prefix /tmp/nurse-quality-tools axe-core@4.10.3 --no-audit --no-fund
venv/bin/python tests/browser/quality.py
```

The quality runner uses local Chrome, a migrated temporary database, temporary
accounts and a local server. It checks real submissions, offline/slow/interrupted
requests, duplicate prevention, draft clearing, keyboard dialog behavior, events,
and selected WCAG A/AA rules with axe-core. It also checks page reflow at a
320-pixel viewport with 200% text. Set `NURSE_NG_AXE_SCRIPT` to use another local
copy of the auditing script. Screenshots, results and logs are kept in the
reported `/tmp/nurse-quality-browser-*` directory. It never adds events or test
members to the actual app database and does not send external messages.
The draft runner also checks preservation across error pages and browser tabs,
validation rejections, interrupted submissions and clearing after real sign-out.

Automated accessibility findings that require manual review are retained in the
audit artifact. Zero reported violations is not an accessibility certification.

## Physical-device acceptance record — not yet executed

These checks require actual devices and assistive technologies. Record tester,
date, app version/commit, device model, OS/browser version, assistive technology,
connection conditions, result, artifact and follow-up issue for every row.

| Journey | Android Chrome + TalkBack | iPhone Safari + VoiceOver | Keyboard + 200% text |
| --- | --- | --- | --- |
| Register, phone sign-in, Google/LinkedIn sign-in, sign-out | Pending | Pending | Local checks only |
| Recover password, verify email, upload photo, change settings | Pending | Pending | Local checks only |
| Complete onboarding, find a member, edit/share profile | Pending | Pending | Local checks only |
| Find/save opportunity, apply, employer updates status | Pending | Pending | Local checks only |
| Publish/reply/report, follow/connect, send/retry message | Pending | Pending | Local checks only |
| Upload/process/play Reel, captions, data saver, report | Pending | Pending | Earlier local checks only |
| Find event, RSVP/cancel, download/open calendar | Pending | Pending | Local checks only |
| Staff document review, moderation, source administration | Pending | Pending | Local checks only |

For each journey:

1. Complete it on ordinary Wi-Fi, a throttled/mobile connection and a connection
   interrupted during submission. Check truthful pending/success/failure feedback,
   preservation of entries and the absence of accidental duplicate actions.
2. Repeat with TalkBack or VoiceOver. Check control names, form instructions,
   invalid fields, logical reading order, status announcements, focus after errors,
   dialogs, navigation and return to the originating control.
3. Use only a keyboard, including Tab/Shift+Tab, Enter/Space and Escape. Check
   visible focus, hidden controls, modals and the full completion path.
4. Enlarge text and zoom; check portrait/landscape, the on-screen keyboard, narrow
   screens, long names, light/dark/high contrast and reduced motion.
5. Exercise unavailable/deleted records, expired sessions, denied permissions,
   stale form submissions and Back/Forward navigation. Every visible action must
   reach its advertised result or show an accurate, useful explanation.

## Remaining external and later work

Physical-device and assistive-technology testing remain pending. Provider app
credentials, callback configuration and real Google/LinkedIn accounts are required
to validate social sign-in end to end. No public deployment was performed.

Adaptive HLS/DASH streaming and automatic speech captions remain later Reels
improvements, as specified in priority 6. Existing two-rendition MP4 playback and
creator-provided WebVTT captions remain the current implementation. These later
features should be selected against measured playback needs and transcription
cost/accuracy, then validated with the same device matrix.
