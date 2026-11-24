# Deployment source and local service installers

[HOSTING.md](../docs/HOSTING.md) is the setup/acceptance guide. This directory holds
process startup, environment examples and optional workstation service setup;
[the infrastructure reference](../docs/reference/INFRASTRUCTURE.md) links each piece.

| File | Responsibility |
| --- | --- |
| `start.py` | Validate production settings and launch `web`, supervised `workers`, or both with `all`. |
| `production.env.example` | Explain production setting names; supply real secrets through the host's secret environment. |
| `install-local-clamav.sh` | Configure the workstation malware scanner; inspect platform/privilege requirements before execution. |
| `install-local-search.sh` | Configure local SearXNG tooling for optional recruitment search. |
| `searxng/compose.yaml`, `searxng/settings.yml` | Separate search-service container and engine settings. |
| Root `Dockerfile` | Python runtime, scanner/media dependencies, non-root file layout and entry point. |
| Root `render.yaml` | Single-service Render preview, operator-supplied database/origin/hosts and generated signing key. |
| `.github/workflows/checks.yml` | Source/reference/mobile checks and isolated PostgreSQL/container checks. |
| `.github/workflows/mobile.yml` | Manual preview/simulator artifacts; release/store signing remains separate. |

`start.py --check` validates the selected command without starting services or
running migrations. `web` launches one Uvicorn worker on provider `PORT`; proxy
headers are enabled only for the configured trusted IPs/CIDRs. `workers` launches
the domain supervisor. Both require the database to have been migrated already.

`all` first runs `alembic upgrade head`, then manages separate web and supervisor
process groups. If either service exits, the launcher stops the other and returns
a failure for host recovery; signals reach both groups during shutdown. It is a
single-service convenience, not independent scaling of the roles.

Private uploads and worker-generated files need persistent shared storage and
working scanners where required. The free preview definition does not manufacture
a persistent disk, configure a real email/media provider or publish a native app.
Follow the hosting guide for those deployment requirements and verify them on the
actual host. Source comments are not operational evidence.
