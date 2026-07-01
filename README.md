# Philatelic Catalog

`philatelic-catalog` is a small FastAPI + SQLite project for managing philatelic collection metadata, with collection files copied into a managed local archive.

## Goals

- Keep managed archive files in the filesystem using UUID-based relative object paths.
- Store metadata, tags, and tracking history in SQLite.
- Expose a clean REST API for future batch importers and integrations.

## Project Layout

```text
app/
  api/        HTTP routes
  db/         database setup
  models/     SQLAlchemy models
  schemas/    Pydantic schemas
  services/   business logic
scripts/      helper scripts
tests/        API tests
```

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

The API will start at `http://127.0.0.1:8000`.

## First Endpoints

- `GET /health`
- `GET /items`
- `POST /items`
- `GET /items/{item_id}`
- `PATCH /items/{item_id}`
- `POST /items/{item_id}/tags`
- `POST /items/{item_id}/assets`
- `POST /items/{item_id}/tracking-events`
- `GET /tags`

## Importing The Existing Archive

Use the built-in importer to scan the old `Letters` tree, copy files into the managed archive, and write metadata into SQLite.

```bash
python scripts/import_letters.py '/Volumes/Frank Ruan Database/MediaLibrary/Letters' --dry-run --limit 10
python scripts/import_letters.py '/Volumes/Frank Ruan Database/MediaLibrary/Letters' --recreate-db
```

Notes:

- `--dry-run` parses items without copying files or writing the database.
- `--limit` is useful for small trial runs.
- `--recreate-db` is helpful while the schema is still evolving.

## Design Notes

- The database stores relative archive paths, not binary files.
- The intended ingest flow is copy-based on local macOS APFS storage.
- Imported files do not preserve the source directory layout.
- Archive files are bucketed under top-level `0-9` and `A-F` directories with UUID-based filenames.
- `items` is the core entity.
- `assets` stores related files and optional descriptive attributes such as `front`, `back`, `content`, `manifest`, or `invoice`.
- `tracking_events` is separate from freeform notes so postal history stays queryable.

## Next Good Steps

1. Add an importer that scans the existing `Letters` tree.
2. Add pagination and full-text search.
3. Add Alembic migrations once the schema settles.
