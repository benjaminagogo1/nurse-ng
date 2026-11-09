# Notifications and messaging

Implemented for roadmap priority 5 on 8 November 2026, using the user's requested
LinkedIn-style model while retaining Nurse.ng's design and connection permissions.

For opportunity matches and saved-job deadline reminders added in the next migration, see
[Nigerian opportunity operations](NIGERIAN_OPPORTUNITIES.md). The same notification worker
generates these events and delivers opted-in email; existing activity categories remain unchanged.

## Member experience

- `/notifications` is a private activity feed with All, Unread, Conversations,
  Connections, Messages and Applications filters. The header bell shows an unread
  badge on every signed-in page. The badge refreshes about every 25 seconds while
  the page is visible and online. New feed activity offers a refresh link without
  replacing the content someone is reading.
- Replies notify the post author, the author of the reply being answered and
  members following the discussion. Recipients are deduplicated, and members do
  not receive notifications for their own actions.
- Connection requests and acceptances, private messages, new job applications,
  employer status changes and applicant withdrawals create notifications in the
  same database transaction as their source event. No-op status changes do not
  create additional notifications.
- Opening the inbox does not clear unread items. Members can open an item, mark
  it read or mark all items through the page's displayed watermark as read.
  Later events remain unread. The inbox uses pages of 20 with older-page links.
- `/notifications/preferences`, also linked from Settings, controls in-app and
  email delivery separately for each category. In-app defaults on; email defaults
  off. Choices apply to new activity. Disabling email cancels queued or claimed
  delivery where it has not already been handed to the provider. Existing inbox
  history remains available. Account verification/recovery mail is separate.
- `/messages` keeps accepted connections as contacts. Open conversations update
  approximately every 4.5 seconds, pause polling while hidden/offline and back off
  after connection errors. Draft text and scroll position are preserved. Members
  reading earlier content receive a New messages button instead of a scroll jump.
- Conversation history loads in pages of 40, beyond the former 100-message cap.
  Server-rendered pagination and sending still work without JavaScript. JavaScript
  inserts older messages into the existing thread and deduplicates by message id.
- A send reference prevents duplicate submissions when a response is lost. A retry
  with the same sender/reference returns the original message; changed content
  cannot reuse a previously accepted reference. Sending, success, offline and error
  states appear next to the composer. Drafts stay in the current page's memory;
  reloading or navigating away is not a persistent draft-save feature.

## Access and privacy

Inbox reads, counts and destinations recheck current source visibility and
relationships. Removed replies/posts, revoked discussion subscriptions where the
member has no other reason to receive the event, disconnected conversations and
inactive actors are excluded. Application details are available only to their
applicant and owning employer, including through their direct notification link.
Existing application contact-sharing consent is preserved.

Every conversation read, poll, history request, send and read acknowledgement
requires an active accepted connection. On a live access failure the browser
clears the displayed conversation and disables its composer. Server-rendered
opening marks only the rendered batch read. Enhanced read receipts acknowledge
visible message ids, bounded to the same recipient and conversation. Unread
messages are replayed alongside cursor updates to recover incoming transactions
that commit behind a cursor. Sender/reference uniqueness also covers concurrent
send retries. Messages are escaped in templates and inserted with textContent.

All mutation endpoints require CSRF tokens. HTML and JSON responses containing
private information use `Cache-Control: no-store`. Notification emails use generic
text and authenticated links, without message bodies, applicant details or post
previews. No new public profile information or contact details are exposed.

## Migration and worker

Apply the migration before starting the updated web application:

```bash
venv/bin/alembic upgrade head
venv/bin/python -m app.cli notification-worker
```

Revision `9de420c3b287` follows `8cf309b2a176`. It adds notification/preferences
storage, the email outbox, and message send references/pagination indexes. Existing
messages are preserved; old activity is not backfilled into the notification feed.
Downgrading is refused while notification or preference records exist.

The worker uses the existing account email transport/configuration (including
Brevo SMTP locally). SMTP certificate validation remains enabled. Email must be
explicitly enabled by the recipient, whose address must currently be verified.
Run one continuous worker alongside the web application; multiple workers use
conditional database claims to avoid processing the same active lease.
For a scheduled/bounded invocation:

```bash
venv/bin/python -m app.cli notification-worker --once --max-tasks 20
```

The outbox persists before delivery. Workers claim records with a 120-second lease,
record attempts before sending, recover expired leases and retry transport failures
with exponential delay (2, 4, 8 and 16 minutes), up to five attempts. Before transport,
they recheck recipient activity, the verified address, current preferences, unread
state and source access. Delivery already accepted by SMTP cannot be recalled.
Terminal records clear their copied email address. Logging includes notification ids
and delivery states, without addresses, content, credentials or provider replies.

`queued`, `sending`, `sent`, `skipped` and `failed` are internal outbox states.
A `failed` record has exhausted its automatic retry budget; operators should inspect
transport health before changing retry policy. Its in-app notification remains
available when enabled. The worker does not promise exactly-once SMTP delivery:
a crash after provider acceptance can cause a repeated email. Retries use a stable
Message-ID, which does not guarantee deduplication by the mail provider.

Production still needs process supervision, alerting for stopped workers/failed
queues and deployment verification, as tracked under roadmap priority 1. This
implementation uses browser polling, not WebSockets or device push. No new paid
provider or infrastructure is required.

## Validation

Final local verification: **441 tests passed**. The final browser run passed at
320, 390 and 1280 pixels with clean JavaScript/server logs and successful actual
CLI-worker delivery into its isolated file mailbox. The local application database
is migrated and a notification worker is running alongside the development server.

Run isolated integration checks and the actual CLI/browser worker flow:

```bash
venv/bin/python -m pytest tests/test_notifications.py tests/test_workspace_flows.py tests/test_discussions.py
venv/bin/python tests/browser/notifications.py
```

The browser runner creates its own database, accounts, server, Chrome profile and
file mailbox. It exercises unread badges, opt-in controls, automatic incoming
messages, history beyond 100 messages, reading-position/draft preservation, offline
and lost-response retry, access revocation and actual worker delivery. It checks
320, 390 and 1280 pixel layouts and saves screenshots and server/worker logs in a
private temporary directory. It does not send real test emails. Deployment and
physical-device testing remain separate from these local checks.
