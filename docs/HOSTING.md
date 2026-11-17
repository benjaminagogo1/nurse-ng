# Hosting Nurse.ng

Nurse.ng supports a public HTTPS site with PostgreSQL or persistent SQLite,
separate web and worker processes, and shared private file storage. Use
[the production environment example](../deploy/production.env.example) for your
provider's settings. When the process sets `NURSE_NG_ENVIRONMENT=production`,
the app reads its process environment and ignores the local development `.env`.

## Domain, secrets and database

Set these in the hosting provider's environment and secret storage:

```dotenv
NURSE_NG_ENVIRONMENT=production
NURSE_NG_DEBUG=false
NURSE_NG_SESSION_HTTPS_ONLY=true
NURSE_NG_SESSION_SAME_SITE=lax
NURSE_NG_PUBLIC_BASE_URL=https://your-domain.example
NURSE_NG_ALLOWED_HOSTS=your-domain.example
NURSE_NG_REQUIRED_WORKERS=recruitment,reels,notifications
```

Supply a permanent, cryptographically random `NURSE_NG_SECRET_KEY` of at least
32 characters. Generate it with `python -c 'import secrets;
print(secrets.token_urlsafe(32))'`, then save it privately. Web, workers and
release commands must use the same key; rotating it invalidates sessions and
previous invitation signatures.

Supply `NURSE_NG_DATABASE_URL` explicitly. Managed PostgreSQL URLs beginning
`postgres://` or `postgresql://` automatically select the bundled psycopg driver.
Use the provider's TLS settings, for example `?sslmode=require`, or `verify-full`
with its required CA configuration. SQLite is supported for one web instance
only, with an absolute path on a persistent disk, such as
`sqlite:////var/lib/nurse-ng/nurse_ng.db`. An in-memory database is rejected in
production. A container filesystem or repository checkout is not durable storage.

The public URL must be an HTTPS origin without credentials, path, query or
fragment. Local/internal addresses are rejected in production, and the domain
must appear in the exact allowed-host list. Invitations, profile sharing,
email links and Google/LinkedIn callbacks use this configured origin. Page
assets and pagination use relative URLs, so internal HTTP proxy connections
cannot put HTTP asset addresses into public pages.

## Storage and runtime processes

Mount persistent storage and set these paths for both web and workers:

```dotenv
NURSE_NG_AVATAR_DIR=/var/lib/nurse-ng/avatars
NURSE_NG_COMMUNITY_MEDIA_DIR=/var/lib/nurse-ng/community
NURSE_NG_EVIDENCE_DIR=/var/lib/nurse-ng/evidence
NURSE_NG_BACKUP_DIR=/var/lib/nurse-ng/backups
NURSE_NG_COMMUNITY_MALWARE_SCAN_MODE=required
NURSE_NG_EVIDENCE_SCAN_COMMAND=clamscan
```

Web and workers need read/write access to the same files, including upload
chunks and processed videos. Keep these directories outside static hosting;
private evidence and photos are served through authorization checks. The
container runs as UID/GID `10001`, which must own its writable mount. Set private
storage directories to mode `0700`. Hosting
plans with separate process disks need shared storage before running this
architecture. An object-storage adapter is not included.

Install FFmpeg and ClamAV with current signatures. The image includes their
binaries; it does not download or refresh ClamAV signatures at application
startup. Run a host-managed ClamAV updater and share its readable signature
directory at `/var/lib/clamav`, or provide an equivalent scanner command with
ClamAV-compatible exit codes. Required scanning fails closed when unavailable.
Monitor disk space and back up referenced files alongside the database. For
PostgreSQL, use provider backups/PITR or `pg_dump` and test restoration; the
application's local backup command supports SQLite.

From a source checkout, install Python 3.12 and the pinned dependencies, then
validate settings without opening the database:

```sh
python3.12 -m venv venv
venv/bin/python -m pip install -r requirements.lock
venv/bin/python deploy/start.py web --check
venv/bin/python deploy/start.py workers --check
```

Run migrations once as a release step before starting web or workers:

```sh
venv/bin/alembic upgrade head
```

For an existing installation, stop writers and take a consistent backup first.
The current migration head is `e6480g7c3294`. Fresh PostgreSQL and SQLite use
the same migration chain. Existing SQLite databases are not automatically
converted to PostgreSQL; switching databases needs a separate data transfer.

Start these as two provider-managed services with automatic restart:

```sh
venv/bin/python deploy/start.py web
venv/bin/python deploy/start.py workers
```

The web entry binds `0.0.0.0` and the provider's `PORT` (default `8000`). It
uses one Uvicorn worker because IP rate limits currently live in process memory.
Keep one web replica; multiple replicas need shared rate limiting and coordinated
file storage before scaling. The worker supervisor runs the required recruitment,
Reels and notification roles. See [worker operations](WORKER_OPERATIONS.md).
Schedule `python -m app.cli maintain-evidence` separately for retention and cleanup.

## Container option

Build the repository's `Dockerfile`. For Docker on a server, save the completed
production values in a private, Git-ignored `.env.production` file. The commands
below assume writable storage belongs to UID `10001` and ClamAV signatures are
being maintained at `/srv/nurse-ng/clamav`:

```sh
docker build -t nurse-ng:release .
docker run --rm --env-file .env.production nurse-ng:release web --check
docker run --rm --env-file .env.production \
  --mount type=bind,src=/srv/nurse-ng/data,dst=/var/lib/nurse-ng \
  --entrypoint python nurse-ng:release -m alembic upgrade head
docker run -d --name nurse-ng-web --restart unless-stopped \
  --env-file .env.production -p 127.0.0.1:8000:8000 \
  --mount type=bind,src=/srv/nurse-ng/data,dst=/var/lib/nurse-ng \
  --mount type=bind,src=/srv/nurse-ng/clamav,dst=/var/lib/clamav,readonly \
  nurse-ng:release web
docker run -d --name nurse-ng-workers --restart unless-stopped \
  --env-file .env.production \
  --mount type=bind,src=/srv/nurse-ng/data,dst=/var/lib/nurse-ng \
  --mount type=bind,src=/srv/nurse-ng/clamav,dst=/var/lib/clamav,readonly \
  nurse-ng:release workers
```

Configure your HTTPS proxy to reach the web service. Adapt port mapping and
mounts to your provider. CI includes image build/preflight checks. Local Docker
verification was blocked by daemon permissions; that build has not been verified
on this workstation.

## HTTPS proxy, email and mobile release

Terminate TLS at the hosting proxy and preserve an allowed Host header. Set
`NURSE_NG_TRUSTED_PROXY_IPS` to the actual proxy IPs or bounded CIDRs reaching
Uvicorn, such as `127.0.0.1` for a proxy on the same host. Otherwise forwarded
headers are disabled. Wildcards and all-address networks are rejected. Restrict
access to the backend port and have the trusted proxy replace incoming forwarded
headers; correct client IP forwarding is needed for per-IP abuse limits.

SMTP is optional for the inbox, but required for real email verification,
password recovery and opted-in email alerts. Set the SMTP values in the example
with a sender verified by your provider, and keep the notification worker running.
SMTP links require the public HTTPS origin. File mail remains a development tool.

Register these exact optional web sign-in callbacks with the providers:

```text
https://your-domain.example/auth/social/google/callback
https://your-domain.example/auth/social/linkedin/callback
```

For native releases, set `NURSE_NG_MOBILE_URL` to the same public origin when
building, supply signing credentials, and publish real download/store URLs.
See [mobile release instructions](../mobile/README.md). Browser installation
also requires a reachable HTTPS site. Native device/provider approval still
needs validation on the actual release.

## Verify the hosted site

Set provider probes to `/healthz` for liveness and `/readyz` for readiness, with
an allowed Host header. Readiness checks the database and configured workers;
allow startup time for their first progress reports. A successful `--check`
validates configuration only; it does not establish storage, SMTP, migrations,
database connectivity or live HTTPS health.

After hosting, check from a separate device:

1. Open the public HTTPS site and confirm `/healthz` and `/readyz` return 200.
2. Register/sign in, create your own community and post a question. Confirm
   session cookies have Secure, HttpOnly and SameSite flags.
3. Use **Invite colleagues** to copy a link with your public domain. Open it in
   a separate signed-out browser and register; it must return to that community
   or question. Confirm WhatsApp/copy sharing works on a phone.
4. Verify email, password recovery and any configured provider login using your
   own test account. Check uploads and Reels processing, restart both services,
   and confirm the database and files persist.
5. Check browser installation and prepared offline work on the hosted origin.

Isolated verification is retained in
[the hosting readiness evidence](verification/2026-11-17/hosting-readiness/README.md).
No public deployment, real invitations or email were sent during those checks.
