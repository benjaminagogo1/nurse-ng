# Server-rendered templates

Read [the frontend guide](../../docs/FRONTEND_GUIDE.md) for context, load order,
DOM hooks and browser contracts. The [template reference](../../docs/reference/FRONTEND.md)
lists every page/partial and its literal inheritance/includes.

`base.html` is the shared shell. Feature directories group related pages; `_*.html`
files are reusable macros/partials. Education and Reels have feature layouts that
extend the shared base. HTTP context comes from the owning route/context helper and
`app/web/templating.py`, including CSRF, feedback, draft scope and tour state.

Preserve input names, submit-button values, accessible labels and `data-*` hooks
when editing forms. Check route parsers and enhancement scripts together. Keep
permission decisions in services even when a template hides unavailable actions.
Use Jinja comments for maintainer explanations so notes do not become public HTML.
