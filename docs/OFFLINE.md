# Offline reading, drafts and synchronization

The **Offline & sync** destination in the member navigation and connection indicator
opens `/offline`. The implementation uses the existing FastAPI/Jinja application,
database, media validation and Reel worker. It adds no hosted service or runtime
JavaScript dependency. The [architecture record](OFFLINE_ARCHITECTURE.md) describes
the assessment and synchronization contract.

## Using it

1. Sign in while connected. Visit the profile, opportunities and notifications you
   want available, and open any message, application, post, reply or Reel form you
   will need. On Learning, explicitly download the original application checklist.
2. Use **Save draft locally** to retain a contribution without sending it. For a
   Reel, select the video before saving; this also saves its encrypted chunks.
3. While disconnected, reopen Nurse.ng in the same browser profile, including in a
   new tab or after restarting the browser. The fallback opens the offline
   workspace. Search saved information, edit a prepared draft, edit a saved profile,
   change a bookmark or queue a connection request to a saved public profile.
4. Use **Queue for synchronization** when ready to send. Applications and Reels
   require reviewed consent. Pending means the server has not confirmed the change.
5. Reopen and reconnect: pending sends resume automatically. Keep the tab open until
   they are confirmed, or press **Sync now**. Review any failed or
   conflicting change. Confirmed items link to the result; a received Reel still
   needs the ordinary processing worker before it is published.

The workspace overview links to **Local drafts**, **Sync activity** and the
**Saved library**, with counts from this browser's stored work. Search filters the
library; expand a saved item to read its full details. The sync button shows
**Reconnect to sync** while offline. Storage information and **Clear offline data**
are under **About offline storage**.

| Capability | Supported behavior |
| --- | --- |
| Opening the app | A neutral offline workspace after a successful service-worker installation. |
| Own professional profile | Selected fields can be read and edited; independent changes merge, overlapping changes require review. |
| Public profiles | Only currently public fields are downloaded. Connection requests recheck visibility when sent. |
| Opportunities | Downloaded details and bookmarks can be read and searched. Saving/removal rechecks current state. |
| Notifications | A bounded snapshot; refreshing removes records whose source is no longer visible. |
| Learning | Explicit download of Nurse.ng's original application checklist. External resources require internet. |
| Contributions | Prepared messages, internal application notes, text/link posts and text replies can be saved and queued. |
| Reels | Explicit video/caption draft saving, reviewed publication intent, resumable upload and the existing scanning/processing checks. |

Events, verification documents, account/security changes, staff decisions, community
attachments and external application destinations require a connection. Offline
support does not download Reel feeds or third-party learning material. Ordinary
connected forms continue to work, including without JavaScript.

## Storage and identity

Private records, explicit offline drafts, queued payloads and video chunks are
encrypted with AES-GCM in IndexedDB. A non-exportable `CryptoKey` is saved alongside
the encrypted workspace; raw key bytes are not written to localStorage. Normal tab
or browser closure preserves access. Same-account tabs share the saved workspace.
The ordinary automatic community text recovery is still tab-local; use **Save draft
locally** to keep an offline copy across browser restarts.

Signing out, changing accounts or using **Clear offline data** deletes the private
workspace and its key and locks other tabs. Session expiry or revocation also clears
access when learned on reconnect. An error page or a failed identity request does
not establish sign-out. This is browser storage, not a backup or cross-device draft
system; anyone who can use the signed-in browser can access its saved information.

Selected records expire after 24 hours and are limited to 200 per workspace. Drafts and
video chunks are kept for up to seven days after saving. Operation history expires
30 days after its last status update. Browser quotas and eviction can shorten these
periods. The app requests persistent browser storage where supported, but the browser
may decline. Private browsing may remove storage when its last window closes, and
clearing site data removes the workspace. A queued draft and its pending state are
written atomically, so a failed transaction cannot leave a hidden queued send.

Queue insertion, draft changes and sending are coordinated across tabs. An older
editor cannot overwrite a newer saved version; its typed text remains available
while the user opens the latest saved draft. Web Locks are backed by IndexedDB leases
with transaction checks that reject writes from an expired lease or cleared session.
Tabs share change IDs and session signals, not private payloads. Server receipts
still provide the final duplicate protection after interrupted requests.

Only the neutral shell and selected public static assets enter the service-worker
cache. Authenticated HTML, CSRF tokens, private media and arbitrary external
resources are excluded. Current session identity, CSRF, permissions and domain rules
are checked before every server write. A saved public record is a dated snapshot;
revocation cannot be learned until reconnection or expiry.

## Interrupted requests and uploads

Each queued change keeps a stable UUID and payload across retries. Its receipt and
database change commit together. Timeouts, transient server failures and rate
limits use bounded backoff; rejected changes require review. Profile and bookmark
conflicts have no force-overwrite action. Confirmed message/Reel forms prepare a
new submission reference without erasing newer text. Publishing through an ordinary
connected form also removes its matching offline draft after confirmation.

Reel staging uses 1 MiB chunks. On retry the server reports the received position,
so acknowledged chunks are not uploaded again. Duplicate chunks must match their
stored bytes. Publication uses the existing file, duration, caption, quota and
malware validation; receipt confirmation means received for processing.

The offline video limit is the smaller of 100 MiB and
`NURSE_NG_COMMUNITY_VIDEO_MAX_BYTES`. Server reservations allow two unfinished uploads
per account and 2 GiB in total. Reservations expire after seven days and are removed
by media cleanup. Completed upload metadata and operation receipts remain until
account deletion; do not delete them while clients may retry.

Foreground synchronization is primary. Background Sync, where supported, wakes
open tabs; it does not promise delivery after the browser closes. Keep a stable
signing key across server processes and restarts. Rotating it invalidates sessions
and changes request fingerprints.

## Running this version

Back up the database, then apply the additive migrations before serving this code:

```sh
venv/bin/alembic upgrade head
venv/bin/alembic check
```

Revision `e6480b1d9a72` adds operation receipts and `e6480c2ea831` adds upload staging.
Both follow the events/social-sign-in revision `e6480ac93d25`. Downgrades refuse to
drop nonempty receipt/staging tables.

Durable browser storage needs no additional server migration. The v10 service-worker
cache and versioned offline scripts replace the previous cached code without forcing
open forms to reload. Existing open tabs migrate their old session key when reloaded;
the raw key is removed only after a durable key commit. Other legacy tabs recover
same-named drafts as separate copies, preserving operation UUIDs and server payloads.
If merging runs out of storage, its saved key and source data remain for a later
retry. Data whose old tab key was already lost cannot be recovered retrospectively.

Use HTTPS in deployment; localhost HTTP is supported for development. HTTP on a
phone's LAN address is not a secure context and cannot establish these offline
capabilities. Browsers without the required storage/crypto APIs keep the connected
application and explain why local saving is unavailable.

Staging resides in `.offline/` beneath `NURSE_NG_COMMUNITY_MEDIA_DIR`. It must remain
private and writable. File locks require the current Unix deployment and a shared
local media volume for all web processes handling uploads. Multiple app hosts with
independent disks are not supported by this staging implementation.

Keep the existing Reel worker supervised and schedule ordinary media cleanup:

```sh
venv/bin/python -m app.cli reels-worker
venv/bin/python -m app.cli cleanup-community-media
```

Cleanup removes expired, orphaned and completed staging files. Its existing
`--dry-run` option does not modify staging. Configure sufficient disk space for
staging, temporary assembly and processed media. Production worker supervision,
CDN/object storage and public hosting remain separate deployment work.

## Verification

```sh
venv/bin/python -m pytest tests/test_offline.py tests/test_offline_content.py \
  tests/test_offline_uploads.py tests/test_offline_migration.py
venv/bin/ruff check app tests
npm install --prefix /tmp/nurse-quality-tools axe-core@4.10.3 --no-audit --no-fund
venv/bin/python -u tests/browser/offline.py
```

The browser runner requires local Chrome at `/usr/bin/google-chrome` and local
socket access. Set `NURSE_NG_AXE_SCRIPT` to use another local axe-core copy. All
accounts, messages, applications and videos stay in a temporary migrated database;
the runner stops its server/browser and reports its logs, screenshots and audit
directory. It does not send external email.

The checks cover stopped-server navigation, encrypted/expired storage, non-exportable
keys, fresh tabs and full Chrome restarts, automatic resumption, profile conflicts,
lost committed responses across restarts, transaction failures, repeated submissions,
preserved newer text, resumed video chunks after restart, actual Reel processing,
ordinary-form draft clearing, competing tabs with and without Web Locks, stale
editors and leases, clear/sign-out/account isolation, and legacy migration failures.
Reflow checks use the viewport's client width so mobile viewport expansion cannot
conceal overflowing controls.

Initial local verification on 9 November 2026: **619 Python tests passed**, plus
the expanded offline browser journey, existing community-draft browser regression
and 23 page states in the quality browser runner. The durable-storage continuation
has its own focused backend and expanded browser checks. The work log records the
completed checks, artifacts and migration evidence.

Live HTTPS, production PostgreSQL concurrency, physical Android/iPhone storage and
eviction, assistive technologies and closed-browser scheduling need deployment or
device validation. Local Chromium/SQLite results do not establish those outcomes.
