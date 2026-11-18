# Files in private conversations

Connected members can attach files to a private conversation, send files on
their own or add a caption. Use the paperclip beside the message box, review
the selected files and press **Send**. Images have previews, audio and video
have playback controls, and every file has a **Download** link. Media that a
device cannot play can still be downloaded.

Supported types are JPEG, PNG, WebP and GIF images; MP3, WAV, M4A, AAC, OGG,
Opus and FLAC audio; MP4, M4V, MOV and WebM video; PDF, DOCX, XLSX, PPTX,
ODT, ODS, ODP, RTF, TXT and CSV documents. Password-protected documents,
embedded programs and macros are rejected. Legacy DOC, XLS and PPT files
must be converted to a supported format first.

## Sending and retries

The default limits are four files per message, 50 MB per file and 100 MB total.
Each member also has a 500 MB upload allowance per 24-hour window, 1 GB of
file storage and at most 20 unfinished uploads. Limits use 1024-byte units.
Operators can adjust the `NURSE_NG_MESSAGE_*` settings in [.env.example](../.env.example).

Upload progress changes to **Checking file** while validation and malware
scanning run. On this local computer, loading the scanner signatures can take
about 30 seconds for each file. Keep the page open until sending is confirmed.
Interrupted uploads and sends retain their references so pressing Send retries
the original operation. A newer caption typed during an ambiguous send remains
in the box after the original message is confirmed.

Selected files stay in the current page while offline. File messages require
an online connection; **Save for later** continues to support text drafts and
queued text messages. It blocks saving a file message as text alone. Selected
file bytes are not saved to the offline workspace and need to be selected
again after leaving or closing the page.

## Access, storage and cleanup

Unsent files are visible only to the sender. Once sent, both active members of
the accepted connection can access them. Other members and staff cannot fetch
conversation files. Ending the connection or disabling either account removes
access. Access is checked again after long-running file preparation.

Files are structurally validated in a bounded subprocess and quarantined until
the configured `NURSE_NG_EVIDENCE_SCAN_COMMAND` succeeds. Scanner failures
block release. The local scanner uses verified ClamAV signatures and refuses
signatures that have not been checked in 72 hours; see [local operations](LOCAL_OPERATIONS.md).

Set `NURSE_NG_MESSAGE_MEDIA_DIR` to a private persistent directory shared by
web and notification workers. It must be separate from public/static files,
community media, evidence and avatars. Stored files use opaque names and
private permissions. Authorized responses use `private, no-store`, safe
download filenames and byte-range support for media playback.

The notification worker checks cleanup every five minutes. Unsent uploads
expire after 24 hours; abandoned quarantine files and old unreferenced files
are removed. Sent files remain with the conversation. Deleting either
participant's account queues their conversation files for durable deletion.
Operators can preview or run cleanup manually:

```sh
venv/bin/python -m app.cli maintain-message-files --dry-run
venv/bin/python -m app.cli maintain-message-files
```

## Migration and backups

Apply migration `e6480j0f6527` before starting this version of web or workers.
It adds attachment and upload-usage tables and preserves existing messages.
Downgrade is refused while attachment records exist.

The SQLite backup and restore commands include sent and staged file objects
with their sizes and SHA-256 hashes. Restored message files are under
`messages/`; configure that path when switching to a restored installation.
For PostgreSQL, coordinate provider backups or `pg_dump` with the private file
store and rehearse restoration. See [hosting](HOSTING.md) and
[worker operations](WORKER_OPERATIONS.md).
