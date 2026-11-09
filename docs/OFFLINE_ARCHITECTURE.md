# Progressive offline support

Implementation and operating instructions: [Offline reading, drafts and
synchronization](OFFLINE.md). The assessment below records the starting point.

## Assessment before implementation

Nurse.ng uses FastAPI, Jinja templates and plain JavaScript, SQLAlchemy and Alembic.
The configured default database is SQLite; services also contain PostgreSQL paths.
Signed HttpOnly cookies identify a session, CSRF protects writes, and account status
and auth_version are checked against the database. Pages are deliberately no-store.
There is no service worker, IndexedDB store or durable client operation queue.

Existing capabilities to retain:

- Community drafts in sessionStorage, version acknowledgements and cross-tab logout.
- Messages with sender/client-key uniqueness, pagination, retry and polling backoff.
- Unique Reel upload keys, bounded/scanned uploads, processing leases, two MP4
  renditions, captions, playback data-saving controls and upload progress.
- Unique applications and connection pairs, consent checks, notification access
  filtering, source permissions and opportunity freshness rules.
- Separate database-backed recruitment, notification and Reel CLI workers.
- Production configuration guards for HTTPS cookies, signing secrets and hosts.
  The repository has a SearXNG Compose deployment; app TLS/proxy configuration,
  production worker supervision and CDN/object storage remain operator concerns.

## Approach and boundaries

Keep the current stack. Use native service workers, IndexedDB and Web Crypto, with
no additional runtime provider or framework. Integrate an Offline & sync page into
the existing templates and navigation; a neutral rendering of that same page is
the navigation fallback. Cache only selected static resources and that neutral
shell. Never cache signed-in HTML, authentication endpoints, session/CSRF tokens,
verification evidence, administrative pages or arbitrary cross-origin resources.

Private structured records, explicit drafts, operation payloads and video chunks
are encrypted in IndexedDB. The original rollout kept a tab-only key in
sessionStorage. The durable-storage continuation saves a non-exportable AES-GCM
`CryptoKey` in IndexedDB, with one workspace namespace per sign-in scope. Normal
tab and browser closure preserve the workspace; fresh tabs read its saved identity
and key. The existing persistent authentication cookie establishes the same scope
after an ordinary browser restart. No new offline password system is introduced.

The existing v3 object store holds reserved identity, key and lease metadata rows,
so old open database connections cannot block a schema upgrade. Identity activation
and deletion are atomic. Data reads and mutations check the current workspace
generation in their transaction, and stale tabs only lock their own memory when
notified. They cannot delete a replacement workspace or restore cleared data.
A persistent revocation marker also prevents recovery if the page closes before
its deletion transaction finishes; the next opening completes deletion.
Web Locks and expiring IndexedDB leases coordinate writers; every protected mutation
checks the lease token and deadline. This also fences a suspended tab after takeover.
The server receipt remains authoritative when a request outlives a client lease.

Live legacy keys are committed before their sessionStorage copy is removed. The
first tab adopts its namespace; secondary tabs re-encrypt into the shared workspace,
using separate recovered draft IDs on collisions. Operation IDs and server payloads
stay unchanged. Imports delete source rows only in the same transaction that writes
their replacements; failed imports retain the durable source key for retry.

Browser storage can still be cleared or evicted, even after the app requests
persistent storage. A locked device remains the user's protection against somebody
using a signed-in browser. Logout and account changes revoke local access across
tabs and remove old records and keys. A generic error response is never interpreted
as proof of sign-out.

Before sending operations, fetch current identity and CSRF over the network and
match the original session scope. The service worker never holds credentials or
decrypts operations. Foreground/reconnect/manual sync is primary; background sync
may wake an open tab, but closed-browser delivery is not promised.

## Synchronization contract

Operations have a stable UUID, type, target, original values and requested values.
Statuses distinguish local drafts, pending, syncing, confirmed, conflict and failed.
A timeout retains the operation UUID and pending state. Bounded exponential backoff
with jitter applies to transport failures, 429 and transient server responses.
Validation, permission and conflict errors require user action. No blind retries
of existing ordinary POST forms.

The server checks authentication, CSRF, scope, current permissions and domain
validation on each operation. A receipt and the domain change commit in one
database transaction. The same UUID/payload returns its prior result; reusing an
UUID with different data fails. Receipts contain minimal result metadata, not the
private request body. Existing service commits are contained by savepoints inside
the receipt transaction. No external messages are sent by sync itself.

Profile edits compare original fields with current server values and merge only
non-conflicting changes. Bookmark changes compare the original saved/reminder
state. Conflicts expose current values for deliberate review; there is no force
overwrite shortcut. Applications recheck deadline, role and consent; messages
recheck the connection; replies recheck the target and moderation state. New
content retains existing rate limits and trust rules.

## Sequence and acceptance

1. Foundation: shell, encrypted storage, indicators, isolation and sync contract.
2. Essential data: selected profile/job/notification records, local search,
   profile edits, bookmarks and first-party learning material downloads.
3. Deferred content: messages, applications, text posts/replies, connections and
   explicit Reel draft saving/publication intent.
4. Poor networks: chunked upload recovery, timeouts/backoff, bounded fetching and
   media quality selection; retain current worker and media validation paths.

At every phase run focused backend/browser tests, preserve normal form fallbacks,
and report the exact supported behavior. Test offline reloads, slow and interrupted
requests, duplicate receipts, transaction rollback, concurrent updates, role and
session changes, quota failures and interrupted/resumed uploads. Live HTTPS,
physical-device storage eviction and background scheduling need deployment/device
validation; local emulation does not establish those outcomes.
