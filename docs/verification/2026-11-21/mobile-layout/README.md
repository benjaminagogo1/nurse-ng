# Mobile layout verification

The initial browser sweep passed 56 page, viewport and display-preference combinations across settings, dashboard, suggestions, colleague directory, notifications, learning activities and weekly digest. It covered widths 320, 360, 390 and 1440, with default, larger text/higher contrast, and dark appearances. Results are in [browser-wide.json](browser-wide.json).

The final focused run passed all 30 layouts after the visual adjustments, with zero JavaScript exceptions. All functional checks passed. The related account, community, dashboard, notification and offline regression suites also passed all 240 distinct tests.

Rerun the focused checks with:

```bash
venv/bin/python tests/browser/mobile_layout.py --quick --record docs/verification/2026-11-21/mobile-layout
```

The final focused run passed 30 layouts: the seven pages at 320 with larger text/higher contrast, 360 with default and larger text/higher contrast, and 1440 with default appearance, plus settings without a photo and with an upload preview. There were no JavaScript exceptions. [browser.json](browser.json) records control spacing, text containment, document width and header height. The script additionally verified photo upload, colleague search, unread filtering, digest preference persistence, display settings, mobile navigation, and access to connection status from the account menu. Accounts, uploads and mail used an isolated temporary database and directories.

Representative screenshots:

- [Settings](settings-mobile.png) and [photo preview](photo-preview-mobile.png)
- [Dashboard statistics](dashboard-stats-mobile.png) and [desktop dashboard](dashboard-desktop.png)
- [Community navigation](activities-navigation-mobile.png) and [learning actions/search](activities-mobile.png)
- [Notification filters](notifications-mobile.png)
- [Digest highlights](digest-highlights-mobile.png)
- [Account menu and connection status](account-menu-mobile.png)

Install reminders were dismissed using the app's close control for the final captures. The dashboard and learning screenshots scroll to the affected components.
