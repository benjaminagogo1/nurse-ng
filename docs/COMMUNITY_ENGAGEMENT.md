# Community participation and invitations

The community engagement increment supports nurses at every career stage. Open
Community from the member navigation, or start at `/communities`.

## Delivered member journeys

- **Find a place to belong.** Search public communities by name or professional
  interest, create a community with a welcome message and guidelines, and join
  or leave it. The creator hosts the community and can edit its details; staff
  can also edit. Editing the name preserves existing links. `/feed/communities`
  brings together conversations from the communities the member joined.
  Onboarding suggests communities using the member's own interests.
  The directory and creation form show six editable examples: emergency/critical
  care, new-nurse support, a local network, exam preparation, school/alumni and
  research. An example fills the name, purpose, welcome and guidelines only;
  members can change every field or start with their own idea. Viewing an
  example does not create a community. The optional professional-interest
  category does not define or restrict the group's name or purpose.
  Creation links also appear in the conversation feed, composer and onboarding.
  Fresh generic posts require an explicit community choice; links from a
  community and restored drafts retain the member's chosen community.
- **Give and receive useful help.** The composer distinguishes questions,
  conversations and experiences. `/feed/unanswered` shows questions with no
  published reply from another member. Author follow-ups do not remove a
  question from the queue. Members can mark another person's response Helpful;
  the question's author can choose or replace an answer. Removed responses lose
  their public answer status. Reply notifications reuse the existing inbox,
  discussion follows and member-controlled email preferences.
- **Learn together.** `/activities` lists practice challenges, case discussions
  and peer Q&As. Activities have a title, written instructions and an optional
  start time. Times entered in the composer use Nigeria time and are stored in
  UTC. Members participate through the existing reply and follow controls.
  Activity metadata survives tab draft recovery and offline preparation.
- **Bring a colleague into the conversation.** Communities, questions and
  activities offer WhatsApp sharing, the device's native Share action when
  available, and a copyable invitation link with a manual copy fallback. A
  shared invitation opens its public destination. Sign-in and registration
  return the colleague there, including Google/LinkedIn flows when the operator
  has configured those providers. Invitations contain no inviter identity.

## Visibility and delivery boundaries

Community discussions remain public. Joining is a private personal-feed choice,
not a privacy boundary or a requirement for posting. Only aggregate membership
counts are public; no member roster or private professional profile is published.
Helpful recognition and selected answers are community feedback, not professional
credentials or verification of clinical advice. Existing reporting and staff
moderation apply to these contributions.

Invalid, tampered or removed-target invitations fail closed. Return destinations
are limited to current public community and conversation pages. Invites do not
automatically join a community or grant additional access. Sharing requires a
member action; development checks do not send invitations to real people.

Phone access and meaningful external invitation links require the existing
`NURSE_NG_PUBLIC_BASE_URL` to identify a reachable hosted HTTPS origin. The local
pilot uses `http://127.0.0.1:8000`. Native operating-system share sheets and live
provider callbacks need device/provider validation for a public release.

Learning activities are discussions, not a quiz engine, scoring system, meeting
host or recurring-event scheduler. Delegated community moderators, group push,
weekly digests and other wider community-expansion items remain in the
[separate backlog](COMMUNITY_EXPANSION.md).

## Operations and verification

The schema revision is `e6480g7c3294`, following `e6480f6b2183`. Before updating
another installation, stop its writers, take a private consistent database
backup, then run `venv/bin/alembic upgrade head`. The migration adds community
metadata, membership, helpful recognition, selected answers and authentication
continuation fields. It does not seed communities, members or activity.

The local rollout rehearses upgrade/downgrade/upgrade on a private SQLite copy,
compares every existing table's row content, and checks integrity and foreign
keys before upgrading the actual local database. Restart the web application
and worker supervisor afterward. Downgrading removes the new feature metadata;
retain the pre-upgrade backup for recovery.

Focused verification runners:

```sh
venv/bin/python -m pytest tests/test_community_growth.py tests/test_community_sharing.py tests/test_migrations.py
venv/bin/python tests/browser/community_growth.py
```

The Chrome runner uses an isolated database, disabled mail and temporary browser
storage. It checks hosted-community creation, signup continuation, joining,
questions/replies, Helpful/selected answers, learning drafts, sharing fallbacks,
offline activity editing/synchronization, and accessibility/reflow at 320, 390
and 1280 pixels. It expects Chrome at `/usr/bin/google-chrome` and axe-core at
`/tmp/nurse-community-browser-tools/node_modules/axe-core/axe.min.js`; set
`NURSE_NG_AXE_SCRIPT` to use another local copy.

Retained verification is in
[the delivery evidence](verification/2026-11-16/community-engagement/README.md).
The later member-created community examples and explicit composer selection
have [focused verification](verification/2026-11-16/community-examples/README.md).
