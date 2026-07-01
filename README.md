# Philatelic Catalog

`philatelic-catalog` is a small FastAPI + SQLite project for managing philatelic collection metadata, with collection files copied into a managed local archive.

## Goals

- Keep managed archive files in the filesystem.
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

## Design Notes

- The database stores paths, not binary files.
- The intended ingest flow is copy-based on local macOS APFS storage.
- `items` is the core entity.
- `assets` stores related files such as `front`, `back`, `manifest`, and `invoice`.
- `tracking_events` is separate from freeform notes so postal history stays queryable.

## Next Good Steps

1. Add an importer that scans the existing `Letters` tree.
2. Add pagination and full-text search.
3. Add Alembic migrations once the schema settles.
