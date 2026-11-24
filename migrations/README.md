# Database migrations

Alembic revisions in `versions/` evolve an existing installation. The current
source graph is listed in the [infrastructure reference](../docs/reference/INFRASTRUCTURE.md).
`env.py` loads configuration and the model registry, then applies revisions to the
configured database. These commands affect that installation; check the environment.

```sh
venv/bin/alembic heads
venv/bin/alembic current
venv/bin/alembic upgrade head
```

Use `heads` to identify the checked-in target and `current` to identify the installed
state. Do not copy a historical revision from an older feature guide. Existing
merge revisions are part of the graph; future divergent heads require an explicit
reviewed merge rather than deleting another feature's history.

When adding a persisted field, constraint or table:

1. Update the model and register new model classes in `app/models/__init__.py`.
2. Add a revision from the current graph; review generated SQL, defaults and data transforms.
3. Keep historical revisions self-contained. Do not import current runtime models into old revisions.
4. Check SQLite and PostgreSQL semantics, especially Boolean defaults, batch alterations and foreign keys.
5. Test upgrading an existing database with representative rows, not just creating fresh model metadata.
6. Document destructive downgrade/data-loss implications and rehearse on an isolated copy.
7. Regenerate the schema/revision reference with the model/migration change.

Fresh-schema tests using `Base.metadata.create_all` do not prove an installed
database can upgrade. Adding a Python column alone leaves deployed tables unchanged.
Do not rewrite an already applied revision merely to avoid creating the next one.

Take a consistent private backup, coordinate writers and follow
[hosting](../docs/HOSTING.md) before changing a real installation. The single-service
deployment `all` role upgrades before launching processes; separate `web`/`workers`
roles rely on the release's earlier migration step.
