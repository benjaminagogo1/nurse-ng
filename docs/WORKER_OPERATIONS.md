# Background worker operations

Run one supervisor alongside the web server. It starts the configured workers,
retries transient errors with bounded delays, and replaces workers that exit or
stop making progress. Existing task leases still prevent simultaneous collection
and allow interrupted work to recover. The supervisor terminates worker child
processes as well, including network checks and video processing.

## Setup

For a hosted installation, use [hosting setup](HOSTING.md) and run
`venv/bin/python deploy/start.py workers` as a managed service alongside
`venv/bin/python deploy/start.py web`. Both need the same production environment,
database, signing key and persistent file mounts. The production entry validates
required worker roles; `workers --check` validates settings without a database
connection. Production process settings ignore the local development `.env`.

Back up the database before upgrading, then run from the repository root:

```sh
venv/bin/alembic upgrade head
```

Revision `e6480d3fb942` adds the worker progress table. Configure the roles needed
by this instance in its environment or local `.env`:

```dotenv
NURSE_NG_REQUIRED_WORKERS=recruitment,reels,notifications
```

Then run:

```sh
venv/bin/python -m app.cli workers
venv/bin/python -m app.cli worker-status --json
```

The supervisor defaults to recruitment, Reels and notifications when the setting is empty.
`--roles recruitment,reels` can select the processes explicitly, but readiness
always uses `NURSE_NG_REQUIRED_WORKERS`. Restart the web process after changing
that setting so its readiness check uses the same configuration.

The `notifications` role generates opportunity matches and saved-deadline alerts,
including in-app notifications when email transport is disabled. It delivers
email only for recipients with a verified address and the corresponding email
preference enabled. It is included in the default supervisor roles. For an
instance intentionally running fewer features, explicitly select its required
roles; both the supervisor and web readiness must use that selection.

The individual `recruitment-worker`, `reels-worker`, and `notification-worker`
commands remain available, including bounded `--once --max-tasks N` operation.
Stop the former manual workers before starting the supervisor.

## Persistent local service

The supplied user unit assumes the checkout is at `~/nurse-ng` and the virtual
environment is `venv/`. Adapt those paths for another installation. After testing
the commands above, install it for the account that owns the application:

```sh
install -Dm600 deploy/systemd/nurse-ng-workers.service ~/.config/systemd/user/nurse-ng-workers.service
systemctl --user daemon-reload
systemctl --user enable --now nurse-ng-workers.service
systemctl --user status nurse-ng-workers.service
journalctl --user -u nurse-ng-workers.service -n 50 --no-pager
```

The service restarts the supervisor if it exits. A user service normally runs
while the user's service manager is active. Check `loginctl show-user "$USER"
-p Linger`; running without a login or across reboot requires lingering or an
equivalent host-managed service. Installing this unit does not supervise the web
server or configure production hosting.

## Readiness and staff visibility

`/healthz` reports web-process liveness. `/readyz` returns HTTP 200 only if the
database is reachable and every configured required role has recent progress;
otherwise it returns HTTP 503. Responses contain no task contents, process IDs or
connection details. If no roles are configured, readiness checks the database
only. Use an allowed Host header when configuring a health probe.

Staff can open `/recruitment#worker-health` for worker health, recent task results,
queue counts and the oldest queued task. A healthy idle worker is waiting for
eligible work. Queued tasks can wait for rate limits or retry delays. Historical
failed-task totals are not the current failure rate.

Recruitment progress is expected within 75 seconds of a working report;
notification progress within 90 seconds. Reels allows three configured processing
timeouts plus 60 seconds. Idle reports expire after 30 seconds. A transient error
uses a delay of up to 60 seconds before retrying. Source-specific failures remain
in task/source history rather than making a functioning worker unhealthy.

## Existing vacancy review cleanup

Inspect the planned counts before applying cleanup:

```sh
venv/bin/python -m app.cli reconcile-vacancies --dry-run
venv/bin/python -m app.cli reconcile-vacancies
```

The command rejects clear admissions, service and category pages and holds
identical pending announcements as duplicates of one review record. It retains
source snapshots and audit events, preserves staff clarifications, and does not
publish incomplete records. Dry-run mode rolls back its changes. Stop collection
and avoid simultaneous staff review while running this maintenance command.

Open `/recruitment/vacancies?state=pending` for remaining reviews or use the
Duplicate filter to inspect retained duplicate evidence. Missing or conflicting
employers, dates and salary facts still require source evidence.
