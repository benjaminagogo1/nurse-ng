# Private conversations and AM/PM timestamps — 17 November 2026

The private conversation page now has a compact header, clearer incoming and
outgoing bubbles, a scrollable history and a message box that stays visible on
phone and desktop. The installation reminder is omitted on Messages. Local
draft and queued-send controls remain available under **Save for later**.

Displayed timestamps throughout the app use `17 Nov 2026 08:33 AM` or
`17 Nov 2026 08:33 PM`, including live arrivals, community posts/replies,
notifications, event schedules, staff activity, recruitment history and saved
offline records. Stored timestamps, calendar dates, native date/time form values
and calendar export data retain their existing meanings. Existing Nigeria-time
conversions for activities and events remain in place.

## Verification

- [Python regression](regression.xml): **174 cases passed**, with no failures,
  errors or skips, covering messages/notifications, calendar display, community
  growth, staff activity, events, participation and recruitment.
- [Live-message journey](live-message-journey.json): automatic incoming messages,
  retained text, 128-message history, stable reading position, offline and
  lost-response retry, access revocation and isolated worker file delivery passed.
  The retained runner is [notifications.py](../../../../tests/browser/notifications.py).
- [Native bundle](mobile.json): four Node tests passed, including building the
  actual offline document and its shared assets.
- [Visual results](results.json) and [accessibility/reflow audits](audits.json):
  **eight selected axe/reflow states passed**, with no selected violations,
  horizontal overflow or recorded JavaScript errors. They cover collapsed and
  expanded draft controls at 390px/light, 1280px/light, 320px/dark with enlarged
  text and 390px/dark. The review also compared saved and arriving timestamps
  and verified normal phone/desktop composer visibility.
- Midnight, morning, noon and evening formatting was checked. Ruff, all 101
  templates, the five changed JavaScript files and whitespace checks passed.

Screenshots were visually inspected:

- [Phone](conversation-390-light.png).
- [Desktop](conversation-1280-light.png).
- [Enlarged text on a narrow dark screen](conversation-320-dark-large.png).
- [Dark phone](conversation-390-dark.png).

[Original phone](conversation-before-390.png) and
[original desktop](conversation-before-1280.png) captures show the installation
banner and expanded offline actions pushing the composer below the viewport.
The final audit was repeated after tightening the phone heading and enlarged-text
composer. Earlier passing audit results are superseded by the retained final ones.

[Local runtime receipt](local-runtime.json): the local web process was restarted,
readiness and six HTTP checks passed. No database migration was needed. The
public asset cache advanced to v37 to deliver the revised styles and scripts.
Open <http://127.0.0.1:8000/messages> to review the page.

Browser checks used isolated accounts, temporary databases and private file
mail capture. No real member messages or email, public deployment, commit or
push occurred. These selected checks do not establish behavior on every physical
phone or every assistive device.
