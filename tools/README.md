# Documentation tools

`build_code_reference.py` generates seven checked-in pages in `docs/reference/`:
backend modules/symbols, HTTP routes/dependencies, database declarations, frontend
assets/templates, environment fields, tests and infrastructure/migration revisions.

```sh
python3 tools/build_code_reference.py
python3 tools/build_code_reference.py --check
venv/bin/ruff check tools
```

The generator uses only Python's standard library and resolves the repository from
its own path, so it also works from another working directory. Output is deterministic
for the same source. `--check` does not write; it returns nonzero for stale/missing
pages. CI checks freshness alongside lint/tests.

It parses explicit checked-in source roots with `ast` and scans literal template/asset
references. It never imports the application, reads `.env`, opens a database or
inspects upload/native-build/vendor directories. Keep that isolation when extending
it: reference generation must be safe before configuration and dependencies exist.

The output describes declarations. A literal route dependency/call list cannot
infer every middleware/in-handler/service authorization check, and a model declaration
is not an inspection of an installed schema. Handwritten feature/data/frontend guides
explain those contracts. Add descriptive module/class/service docstrings there, then
regenerate rather than hand-editing a generated page.
