# Public browser assets

Every file served under this directory is public. Keep private uploads, account
tokens, databases and generated member snapshots in their configured private stores.

[FRONTEND_GUIDE.md](../../docs/FRONTEND_GUIDE.md) explains the stylesheet cascade,
script dependency order, DOM hooks, globals/events, browser storage and neutral
offline caching. [The asset reference](../../docs/reference/FRONTEND.md) indexes all
authored JavaScript and CSS and their literal template references.

`css/` holds shared and feature-scoped presentation; `js/` contains feature
enhancements rather than a separate SPA. `service-worker.js` caches an explicit
public-asset/neutral-shell list. `fonts/OFL.txt`, `img/CREDITS.txt` and
[vendor/README.md](vendor/README.md) retain licenses/provenance for bundled assets.
Vendor SDK sources keep upstream documentation; regenerate from their documented
distribution instead of treating them as application code.
