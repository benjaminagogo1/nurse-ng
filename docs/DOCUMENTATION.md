# Keeping documentation useful

Documentation lives next to the behavior it explains and is connected through
[docs/README.md](README.md). A maintainer should be able to identify a file's
responsibility before reading its implementation.

## What to document

| Location | Explain |
| --- | --- |
| Module docstring / script header | Responsibility, callers and important boundaries. |
| Model class docstring | What the record represents, who owns it and what its state does or does not prove. |
| Public service function | Action, authorization assumptions/checks, return meaning, transaction owner, external side effects, expected errors and retry behavior when non-obvious. |
| Inline comment | Why an unusual implementation is necessary: locking order, conditional updates, parsing limits, lease fencing, timezone rules or crash recovery. |
| Template comment | A non-obvious context contract, privacy condition or submit-button behavior. Use Jinja comments so explanations do not become page content. |
| Feature guide | End-to-end flow, lifecycle, privacy, failure behavior, setup and verification limits. |
| Generated reference | Current symbols, declared routes/dependencies, table declarations, assets and tests. |

Do not narrate every assignment or assertion. A short helper with a clear name
can remain self-explanatory; comments should explain the domain reason or contract.
Keep existing detailed docstrings. Avoid speculative guarantees: a browser success
message, SMTP acceptance, seat reservation and verified provider attendance are
different kinds of evidence.

## Updating a feature

1. Update the relevant module/function explanation when behavior changes.
2. Update the owning feature guide and the feature map in `CODE_GUIDE.md` if ownership changes.
3. For data changes, add an Alembic revision and update `DATA_GUIDE.md` if a privacy/lifecycle rule changes.
4. For browser changes, update hooks/events/load-order notes in `FRONTEND_GUIDE.md`.
5. Regenerate the source reference with `python3 tools/build_code_reference.py`.
6. Run `python3 tools/build_code_reference.py --check`, lint and the appropriate existing behavior checks.

The generator parses only explicit source directories. It does not import
`app.main`, load `.env`, run CLI commands, read uploads or query member data.
Generated pages should be committed with the code change. `--check` reports stale
pages without writing them. CI runs this check so source maps cannot silently lag.

## Accuracy and evidence

Declared dependency lists are a route-navigation aid. Additional checks can live
inside the handler, called services, router dependencies or middleware. Read the
owning service before changing access rules. Model declarations explain structure;
the actual installed schema depends on applied migrations.

Dated verification results remain dated. Record the command, environment and
limitations of new checks; avoid copying an old passing-test count into a current
setup instruction. Use `alembic heads` instead of hard-coding a moving head.

The repository contains generated/native/vendor code as well as authored code.
Explain custom native behavior and package regeneration in the mobile guide;
retain third-party notices rather than adding application comments to SDK sources.
