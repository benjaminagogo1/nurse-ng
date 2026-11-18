# Community engagement across every stage of nursing

Nurse.ng's immediate goal is increased adoption and sustained participation,
from a student's first day in nursing school through clinical practice,
leadership, research, nursing education and professorship. This delivery adds
five ways to begin a useful exchange, return and bring colleagues into it.

## Member journeys

### Find or offer peer support

Open **Peer support** at `/mentorship`. Signed-in members can find voluntary
offers by topic or search the public support introductions. Topics cover nursing
school, examinations, clinical transition, career development, leadership,
research and teaching. Members at any stage can offer support in an area they
know; no public professional profile or document review is required.

At `/mentorship/offer`, choose topics, write an introduction and availability,
set capacity from one to eight people, and explicitly enable the listing.
Turning off the listing pauses new requests. Only the display name and selected
offer fields appear in the directory. Private account names, contact details
and hidden profile fields are not used to present offers.

Requests contain a private topic and goal. **My support requests** shows sent
and received requests. The recipient can accept or decline; the requester can
withdraw a pending request. Acceptance creates or reuses a mutual connection
for the existing Messages experience. Either person can complete or end accepted
support. Ending support does not remove an existing messaging connection; that
remains controllable in Network.

Duplicate requests for an open pair reuse the saved request. Acceptance checks
current capacity inside the transaction, including competing acceptances on
PostgreSQL. State changes create private inbox notifications with the existing
separate in-app and optional-email preferences. Notification content points
to the private request and does not contain the goal.

Participants can report concerns. `/staff/mentorship-reports` is staff-only,
shows the reported request's goal and public display names, records reviews,
and can pause a support offer. Unreported requests are not exposed through a
staff browsing directory. Support and recognition are community participation,
not professional credentials or clinical supervision.

### Make learning a regular habit

Open `/activities/series/new` to host a weekly, fortnightly or four-weekly
practice challenge, case discussion or peer Q&A. Choose the public community,
title, instructions, local first-session time and timezone. The first discussion
is published on saving; each later session gets its own public discussion one
day before the scheduled time. A supplied meeting link is ordinary discussion
content; Nurse.ng does not host a video meeting.

`/activities/series` shows schedules the member hosts or manages as a community
host. Open a series to see its published sessions. Hosts can pause or resume
future sessions. Times preserve local wall-clock schedules through seasonal
timezone changes. Old missed sessions are not backfilled after an outage.
Inactive hosts or communities pause automatic publication.

**Join activity** stores a private participation choice and follows that
discussion's replies. Only the aggregate count appears publicly; no attendance
roster is published. Leaving the activity removes the participation record,
while discussion following retains its own control. Participants in a previous
session receive a notification for the next one, subject to their Community
learning preferences. Joining a session is not evidence of course completion.

### Help newcomers take a useful first step

**My next step** at `/community/start` offers optional goals for students,
practising nurses, career development, research, teaching and peer connections.
Goals stay private and do not change account roles or profile visibility.
The page shows actual joined-community, published-contribution and Helpful
counts, with links to communities, unanswered questions, peer support and learning.
Members can hide the dashboard reminder and revisit the page anytime.

An optional introduction asks for a community, a public display name when
needed, written text and explicit public-publication consent. Publication also
joins the chosen community. The saved introduction is reused on repeated
submission, and the host receives an inbox notification. Introductions are
ordinary public discussions and use the existing replies and moderation.

Hosts open **Welcome new colleagues** from their community page. An introduction
stays in the welcome queue until the host writes a real published reply and
marks the welcome complete. The queue is available only to the community host
and staff. No automatic greeting or fabricated community activity is added.

Helpful recognition is private by default. Members may choose to show their
Helpful reply count beside public contributions. Counts exclude removed content
and recognition from inactive accounts; they do not imply competence or verification.

### Bring colleagues into a conversation

At `/invitations`, choose an existing public community or conversation, optionally
add a private label, and create a personal link. Use WhatsApp, native sharing
where supported or Copy invite link. Personal links expire after 90 days and
can be revoked by their owner. Ordinary destination invitations remain available
and retain their original behavior without personal attribution.

The landing page explains the aggregate measurement and offers public reading,
sign-in and registration that continue to the shared destination. A valid first
invitation in the browser's signup journey attributes a newly created account,
including new Google/LinkedIn enrollment. Existing sign-ins, self-referrals,
invalid signatures, expired/revoked links and removed destinations do not count
as new attributed members.

Owners see only aggregate counts for browser visits, new active members,
contributors and returning members. Contribution means a currently published
post or reply; return means recorded activity on a later Nigerian calendar day.
Staff and inactive referred accounts are excluded from member counts. No
individual referred identities, private activity history or referral rewards
are displayed. Browser counts use session randomness, without IP addresses or
fingerprints; they are approximate rather than unique-person measurements.

### Choose an optional weekly digest

Open `/digest`, also linked from notification preferences. Email is off until
the member explicitly enables it with a verified email address. Choose recent
unanswered questions in joined communities, upcoming activities in joined
communities and relevant opportunities, with Nigerian opportunities first.
Choose a weekday and timezone; delivery is scheduled for 9am local time.
The page previews currently eligible highlights.

The existing notification worker queues weekly receipts, claims delivery with
an expiring token, bounds retries and rechecks the active account, verification,
subscription, community membership and current published content before sending.
It skips an empty digest. Each account gets at most one receipt per local week;
changing a subscription cancels queued claims. Receipts retain no content snapshot
and terminal receipts older than eight weeks are removed during worker passes.

Every digest contains preference and unsubscribe links. Opening an unsubscribe
page asks for confirmation; an authenticated-purpose POST turns the digest off
without requiring sign-in, including provider one-click unsubscribe. Ordinary
notification emails remain separately controlled. As with the existing email
worker, SMTP acceptance followed by a crash can cause a retry; the stable
Message-ID helps clients identify it but is not an exactly-once guarantee.

## Operation and rollout

The database head is `e6480i9e5416`. The saved participation foundation
`e6480h8d4305` follows `e6480g7c3294`; the new head connects support requests to
notifications. Boolean defaults in the previously unfinished foundation now
work on both SQLite and PostgreSQL. Migrations preserve existing member content
and create no example communities, requests, attendance, invitations or subscriptions.

Stop writers, take a consistent private backup, rehearse the upgrade and
downgrade/upgrade on a copy, and then upgrade the intended installation:

```sh
venv/bin/alembic upgrade head
```

Restart the web process and existing worker supervisor. The **notifications**
role also publishes recurring sessions and queues/delivers digests. Keep it
running even when email delivery is disabled; session publication still works.
The existing per-member post limiter also covers introduction and series creation.
Text-only forms use CSRF checks, bounded input and the app's existing feedback.

Personal sharing needs a reachable public HTTPS origin in
`NURSE_NG_PUBLIC_BASE_URL`. Actual digest delivery needs configured mail transport
and a member's verified-email opt-in. See [hosting](HOSTING.md) and
[worker operation](WORKER_OPERATIONS.md). Hosted provider callbacks and physical
Android/iPhone share-sheet behavior still need release-device validation.
These new private management forms require online access; existing discussion
drafts and offline synchronization retain their own supported scope.

## Verification

```sh
venv/bin/python -m pytest tests/test_participation.py tests/test_migrations.py
venv/bin/python tests/browser/participation.py
NURSE_NG_TEST_POSTGRES_URL=postgresql://fixture@127.0.0.1:5432/nurse_ng_hosting_test \
  venv/bin/python tests/hosting/participation_journey.py
npm test --prefix mobile
```

The browser runner uses an isolated database, disabled mail, local Chrome and
axe-core. It completes newcomer registration from a personal invitation,
introduction, host welcome, a support offer/request/acceptance, recurring session
creation and attendance, and verified-email digest opt-in. It checks phone,
enlarged-text dark and desktop layouts. The PostgreSQL runner requires an
explicit test database, verifies the existing hosted journey, then exercises
competing mentorship acceptances, session generation and digest claims with an
isolated mail capture. CI runs that PostgreSQL journey.

See [delivery evidence](verification/2026-11-17/community-participation/README.md).
