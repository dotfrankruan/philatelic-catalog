# AGENTS

This repository is a personal philatelic catalog system.

The project is intentionally simple:

- Backend: FastAPI
- Database: SQLite
- ORM: SQLAlchemy
- API style: RESTful JSON
- Storage model: collection files are copied into this system's managed archive, metadata lives in SQLite

## Product Intent

This system is meant to manage a real philatelic collection, not just display images.

The core unit is an `item`, not an image. An item may have:

- front and back scans
- manifests or tracking logs
- invoices or related documents
- structured tags
- tracking events

The app should support:

- browsing and searching items
- editing metadata
- batch import from an existing filesystem archive
- future integration with other local tools or apps

## Source Of Truth

Follow these rules strictly:

- Managed copies inside this system are the source of truth for binaries.
- SQLite is the source of truth for structured metadata.
- The database should store file paths, not image or document blobs.
- Do not redesign the archive around Apple Photos or any opaque library model.
- The target platform is macOS on APFS, so copy-based ingest is the default strategy.

## Development Priorities

When extending this project, prefer this order:

1. Keep the data model stable and explicit.
2. Make importers safe and repeatable.
3. Expose clean API behavior.
4. Add UI only after the underlying model is solid.

Avoid jumping into frontend work before importer and metadata behavior are trustworthy.

## Architecture Rules

Keep responsibilities separated:

- `app/api`: request and response handling only
- `app/models`: SQLAlchemy persistence models
- `app/schemas`: Pydantic API contracts
- `app/services`: business logic, import orchestration, parsing, and mutations
- `app/db`: engine, session, and database bootstrapping
- `scripts`: operator utilities and one-off maintenance helpers

Business logic should not accumulate inside route handlers.

## Data Modeling Guidance

Current core entities:

- `items`
- `assets`
- `tags`
- `tracking_events`

Prefer adding new normalized fields over burying meaning in freeform notes.

Examples:

- Use boolean or enum-like fields for `returned`, `self_mail`, or similar states.
- Keep tracking history as rows in `tracking_events`.
- Use `assets.kind` for roles like `front`, `back`, `manifest`, `invoice`.

If a field is likely to be filtered, sorted, or counted later, it should probably be structured.

## Importer Rules

The importer will be a critical part of this repo. Build it conservatively.

- Import must be idempotent when practical.
- Initial ingest should copy files into the managed archive rather than referencing the original tree in place.
- Do not move or rewrite the original collection files during initial ingest.
- Prefer recording unresolved ambiguity over making destructive guesses.
- Preserve enough path information to trace every record back to the pre-import archive.
- If parsing fails for part of an item, ingest what is reliable and record the rest for review.

The first importer should assume local APFS storage and optimize for a straightforward copy workflow, not a cross-platform abstraction layer.

For the first importer, optimize for correctness and traceability over clever automation.

## API Guidance

The API should remain predictable and integration-friendly.

- Use JSON request and response bodies.
- Keep endpoint naming resource-oriented.
- Use `GET`, `POST`, `PATCH`, and `DELETE` conventionally.
- Return structured validation errors rather than silent coercion.
- Prefer additive evolution over breaking changes.

If pagination, filtering, or search is added, keep parameter names simple and stable.

## SQLite Guidance

SQLite is the correct default for now.

- Design schema so a later move to PostgreSQL is possible but not required now.
- Avoid SQLite-specific hacks unless there is a clear gain.
- Add migrations once the schema starts changing in earnest.

## Testing Expectations

At minimum, new work should include tests for:

- route behavior
- service behavior when business rules change
- importer parsing for representative archive examples

For importer work, small fixture directories are better than giant real-world samples.

## Change Strategy

When making substantial changes:

1. update or add schema
2. update service logic
3. update API contracts
4. add or adjust tests
5. only then adjust docs

Avoid mixing broad refactors with importer logic unless there is a clear reason.

## Practical Notes

- Prefer ASCII in new files unless existing data requires otherwise.
- Keep dependencies light.
- Do not add a heavy frontend framework unless the current product needs justify it.
- Favor boring, inspectable code over magic.

## Near-Term Roadmap

The next high-value milestones are:

1. build the filesystem importer for the existing `Letters` archive
2. add list filtering and pagination
3. add item detail enrichment and metadata editing
4. add migrations
5. add a lightweight web UI on top of the API
