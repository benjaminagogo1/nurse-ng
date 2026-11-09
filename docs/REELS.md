# Reels operations and first release

Reels live at `/reels`, with a creation form at `/reels/new` and a creator's private
upload/status list at `/reels/mine`. Existing community videos are not silently
converted into Reels. Uploading a Reel is an explicit public publishing action.

## Running locally

Install the updated dependencies, back up the database and media, and migrate:

```sh
venv/bin/python -m pip install -r requirements.lock
venv/bin/alembic upgrade head
```

Keep the video worker running in a separate terminal alongside Uvicorn:

```sh
venv/bin/python -m app.cli reels-worker
```

To process a bounded batch and exit:

```sh
venv/bin/python -m app.cli reels-worker --once --max-tasks 10
```

Both processes must use the same database and `NURSE_NG_COMMUNITY_MEDIA_DIR`.
The worker defaults to the FFmpeg binary shipped with pinned `imageio-ffmpeg`.
Set `NURSE_NG_REELS_FFMPEG` to an explicit executable to use an operator-maintained
build. `NURSE_NG_REELS_PROCESS_TIMEOUT_SECONDS` defaults to 300 per encoder step.
No broker or web-request background thread is required.

Without a running worker, accepted uploads remain in **Waiting to process**.
They are retained privately, and the creator can safely leave and return.

## Publishing and processing

- Existing upload limits apply: MP4, at most 100 MB and 180 seconds, per-user
  rate limits and storage/window quotas, format checks and configured malware scan.
- The creator name is automatic: keep the existing community name, or use the
  account name for a first contribution. Unnamed legacy accounts use a generic
  member label; contact information and private profile fields are never used.
  A short account suffix distinguishes namesakes under the existing unique-name
  rule. The form shows who is posting, without requesting another creator name.
- The creator supplies a caption, category, audience, community topic, cover
  frame and optional plain WebVTT captions (64 KB). The opportunity-link field
  has been removed. Existing stored links are preserved. Profile and photo
  visibility do not change.
- Each form has a unique upload key. A repeated submission returns the original
  upload rather than creating another post, including after a lost response.
- The post is `processing` and invisible to public post, media and Reels routes
  until the worker finishes. Source files never have public playback URLs.
- A worker atomically claims a database lease, releases database transactions
  during encoding, and checks ownership and the current lease before publishing.
  Expired leases recover after a crash. Three attempts is the maximum; a creator
  can retry failed processing or remove the upload.
- FFmpeg decodes local MP4 only, disables external data references, strips
  metadata, and produces H.264/AAC with fast-start MP4 layout: up to 720×1280,
  plus a smaller rendition up to 360×640. Landscape is preserved without cropping.
  A JPEG cover is extracted at the selected time. Encoded duration is checked too.
- Successful publication attaches all derived files in one database transaction,
  updates storage accounting, and queues deletion of the original. Failed or
  cancelled processing cannot publish partial results. Account deletion and
  moderation cover Reels media through the existing community records.
- `cleanup-account-files` retries queued original-file deletion after a storage
  failure. `cleanup-community-media` reconciles retained media and quotas; queued
  and failed Reel source files count as retained. As with existing community
  storage, run reconciliation during a maintenance window with uploads and the
  media worker stopped, so files in an uncommitted upload are not collected.

Logs contain `reel=<id> state=<ready|failed|cancelled>`, never uploaded metadata or
raw decoder errors. Inspect the creator's status page for a safe failure message.

## Viewing and community behavior

Discover orders Nigerian content ahead of worldwide content, then by publication
time, with Opportunities, Career, Learning and Our stories filters. Following uses
the existing people-follow graph; Saved is private to each account. This is an
explicit ordering policy, not a claim of personalised recommendations.

The player supports vertical scrolling, arrow-key navigation, play/pause, sound,
seek and creator-provided captions. Only the selected clip has an active source;
there is no speculative download of a queue of videos. Autoplay starts muted,
is disabled by data saver and reduced-motion preferences, and pauses on hidden
tabs and open dialogs. Data saver selects the smaller rendition. This release
uses two progressive MP4 files, **not adaptive HLS/DASH**.

Comments and reports reuse community replies, rate limits and moderation.
Following a public creator follows their community identity; it does not reveal
their private profile. Profile links and photos respect existing visibility
settings. Saves are idempotent, private bookmarks. Sharing uses the device share
sheet or copies the public permalink; no messages are sent automatically.

## Before public deployment

The first release runs on the existing local filesystem. **No object-storage
account, CDN, public deployment, or paid video provider has been provisioned.**
Do not put these files on an ephemeral hosting filesystem. A single-host pilot
needs a persistent media volume shared by web and worker, disk monitoring and
backups. Scaling to separate machines requires an object-storage adapter and CDN
integration; this is still deployment work, not an implemented provider feature.

Run the video worker as a supervised, unprivileged process separate from Uvicorn.
Apply memory, CPU and task limits (for example, systemd `MemoryMax`, `CPUQuota`,
`TasksMax` and `NoNewPrivileges`) and deny its outbound network access. The worker
needs write access only to the media volume, its temporary directory and the
database. Decoder subprocesses have bounded duration, thread counts and allocation
size, but these are not a substitute for operating-system resource isolation.
Keep FFmpeg patched. Begin with one worker; lease fencing permits another worker,
but concurrency should follow measured CPU and disk capacity.

Reels media responses currently use `Cache-Control: no-store` so a removed clip
is not served from a browser cache. A future CDN must preserve access/removal
checks and have a tested invalidation or short-lived signed-delivery design.
Never expose the media directory directly as a public static directory.

Automatic speech transcription, adaptive streaming, likes, view counts and
recommendation ranking are not part of this release. Captions are uploaded by
creators; the system does not label email verification as clinical verification.

## Verification

```sh
venv/bin/python -m pytest tests/test_reels.py tests/test_account_migration.py tests/test_community.py
venv/bin/python tests/browser/reels.py
```

The integration cases invoke the real encoder, validate both playback versions
by decoding them, and cover public/private boundaries, duplicate uploads, quotas,
lease recovery, cancellation, saves, follows, captions, comments, moderation and
account deletion. The browser runner uses an isolated migrated database, generated
test videos and temporary accounts. It uploads through the real web form, invokes
the **actual CLI worker**, observes status polling, exercises playback and actions,
and saves phone/desktop screenshots and worker logs under `/tmp/nurse-reels-browser-*`.
It never sends external email or adds test content to the real community.
