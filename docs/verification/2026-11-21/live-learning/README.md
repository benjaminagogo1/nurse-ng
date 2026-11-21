# Courses and live classrooms

Nurse.ng now supports approved educators, structured courses, current-revision
knowledge checks, learner progress, scheduled lectures/discussions, classroom
moderation, private recording access and lecture reminders. The
[code guide](../../../CODE_GUIDE.md) explains the repository; the
[learning architecture guide](../../../LIVE_LEARNING_ARCHITECTURE.md) explains
permissions, transactions, media technology, configuration and maintenance.

The implementation rejects stale quiz forms and keeps old assessment results
out of current completion displays. Signed provider callbacks normalize the
supported protobuf representations and preserve confirmed recording metadata
when earlier events arrive late. Educator approval removal closes active rooms
before the approval transaction completes; failed external closures are
reported and can be retried without inventing success.
Reminder queries traverse every due lecture in bounded fetch batches, so a
large simultaneous schedule does not starve lectures after the first 200.

Camera controls request HD capture and show the achieved resolution. Optional
light correction processes the transmitted video track. Audio-only mode stops
camera capture, and cancelled capture/room entry cannot reactivate media after
Stop, page exit or a sign-in redirect.

## Recorded verification

- [Python regression report](pytest.xml): 1,163 passes and one notification-worker
  startup timeout across the full application suite. The
  [isolated startup rerun](worker-startup.xml) passed with the original timeout
  and restart assertions unchanged. Heavy host load/swap coincided with the
  full-run failure; investigation did not establish a runtime defect.
  The [final startup/restart check](worker-storage-isolation.xml) also passed
  after isolating every worker storage path, with its timeout unchanged.
- [Final reminders and worker report](reminders-and-workers.xml): 27 passing
  cases after the final batching fix, including 202 simultaneous lectures,
  duplicate suppression, current-access checks and worker recovery. This
  focused rerun verifies the helper change made after the full run began.
- [PostgreSQL report](postgres.json): fresh/historical migrations match model
  metadata, existing records survive, concurrent one-seat reservations do not
  overbook, and token/start requests wait behind educator revocation and are
  then denied. Separate transactions also produced exactly 202 committed
  reminders for 202 due lectures across repeated passes. This used
  PostgreSQL 18.7 and generated temporary schemas in a
  dedicated loopback test database; those schemas were cleaned up.
- [Media report](media.json): synthetic Chrome capture reached 1920 × 1080,
  the outgoing track used the real processor, 720p selection worked, audio-only
  mode stopped the camera, pending capture/join work was cancelled safely, and
  no JavaScript exceptions were recorded.
- [Browser journeys](browser.json): 30 page checks at 1280, 390 and 320 pixels
  found no horizontal overflow, missing control labels or duplicate IDs.
  Native forms completed enrollment, reading, scoring, course progress,
  reservations and educator draft creation without unexpected HTTP/JS errors.

[Desktop catalog](catalog-desktop.png) · [Mobile catalog](catalog-mobile.png) ·
[Desktop classroom](classroom-desktop.png) · [Mobile classroom](classroom-mobile.png) ·
[Educator studio](educator-studio.png)

The local development database was backed up consistently and the upgrade was
rehearsed on a copy before applying revision `e6480k1e9038`. Existing accounts,
community content and conversations were preserved; integrity and foreign-key
checks passed. The private snapshot is
`.local-backups/live-learning-20261121T012618Z/before.db`, outside version control.
The migration inserts no demo educator or course records into that database.

The supervisor test now places every configurable storage directory beneath
its temporary test directory. An empty test database therefore cannot make
operator-owned message files look like orphans during notification startup.

## Repeatable checks

```sh
venv/bin/python -m pytest --tb=short
venv/bin/ruff check app tests
node --check app/static/js/education.js
node --check app/static/js/education-room.js
venv/bin/python tests/browser/education_media.py
venv/bin/python tests/browser/education_journeys.py
```

For PostgreSQL, use the guarded setup in the architecture guide and run
`venv/bin/python tests/hosting/education_journey.py`. The browser runner's
`--keep-preview --port 14400` option retains an isolated demo application for
review. It does not create accounts in the actual development database.

## Acceptance boundaries

The media checks use a synthetic camera. Physical camera sharpness, lighting,
device permissions, Safari/mobile behavior and real provider media transport
need separate acceptance checks. Live calling requires LiveKit credentials;
recordings also require configured private storage. The current local/demo
configuration intentionally has no such credentials and reports unavailable
live service accurately.

Database concurrency checks mock media RPCs. Closing a provider room disconnects
participants but does not revoke bearer tokens already issued; those tokens
expire after 300 seconds by default. The architecture guide documents both this
boundary and partial provider/database failures.
