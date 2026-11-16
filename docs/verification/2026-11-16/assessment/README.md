# App assessment and readable deadlines — 16 November 2026

The [assessment report](../../../APPLICATION_ASSESSMENT_2026-11-16.md) records
findings, successful checks, failing-runner diagnosis and practical limits.

Retained evidence:

- `full-pytest.xml`: completed **823-case** suite before the deadline edit.
- `date-pytest.xml`: final **13-case** deadline run after the edit.
- `date-live.json`: read-only feed/detail check at 13:26 UTC; the example displays
  `Nov 30, 2026` and all 16 visible deadlines use the requested format.
- `status.json`: read-only 12:57 UTC database/configuration/source snapshot.
  Its outer route list excludes included routers and is not an endpoint count.
- `probes.json`: synthetic MFA, unapproved publication and duplicate reminder
  results; in-memory storage, outgoing mail disabled.
- `quality-audits.json`, `offline-audits.json`: selected accessibility/reflow
  states from the isolated browser journeys. Manual axe checks remain necessary.
- `public-states.json`, `public-report.json`: 27 anonymous local browser states.
  The four contrast findings are retained, not counted as passing states.
- `browser-journeys.json`: completion/provenance summary and the discovery
  whitespace diagnosis, including the repository runner's failure.
- `static-checks.json`: final lint, Jinja and JavaScript parsing results.
- Selected screenshots: mobile Jobs, installation, directory, notifications,
  messages, Reels and registration with enlarged text.

Private databases, mailboxes, account documents and browser profiles were not
copied into this directory. Original temporary journey folders remain:

| Journey | Local artifacts |
| --- | --- |
| Quality | `/tmp/nurse-quality-browser-256mkl9n/` |
| Notifications/messages | `/tmp/nurse-notifications-browser-ei8n1eem/` |
| Offline | `/tmp/nurse-offline-browser-v1bz76n6/` |
| Reels | `/tmp/nurse-reels-browser-g26fdt6j/` |
| Discovery repository failure | `/tmp/nurse-discovery-browser-o40q50nc/` |
| Discovery temporary diagnosis | `/tmp/nurse-discovery-browser-87tj_atd/` |
| Public pages | `/tmp/nurse-app-public-inspection-5raq4_g0/` |

Reproduction commands, from the repository root:

```sh
venv/bin/python -m pytest --tb=short -o faulthandler_timeout=45
venv/bin/python -m pytest tests/test_date_display.py --tb=short
venv/bin/ruff check . --output-format concise
venv/bin/python -m pip check
venv/bin/python tests/browser/quality.py
venv/bin/python tests/browser/notifications.py
venv/bin/python tests/browser/offline.py
venv/bin/python tests/browser/reels.py
venv/bin/python tests/browser/member_discovery.py
deploy/clamav-local scan --version
```

The test fixture environment isolates the default database and disables account
mail. Browser fixtures use their own migrated databases and file mail. The
discovery repository runner currently fails its raw heading-text assertion;
only a temporary copy changing it to `.textContent.trim()` completed. The
diagnosis did not modify the repository runner.

Additional temporary assessment sources were
`/tmp/nurse-ng-assessment-probes.py`, `/tmp/nurse-ng-assessment-status.py`,
`/tmp/nurse-ng-public-inspection.py` and
`/tmp/nurse-ng-discovery-assessment.py`. Temporary sources/artifacts may be
removed by system cleanup. The final 13-date-test result supersedes the initial
fixture failure and interrupted targeted runs. No fresh full-suite result after
the deadline edit is claimed.
