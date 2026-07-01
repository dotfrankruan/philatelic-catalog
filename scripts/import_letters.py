from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.database import Base, SessionLocal, engine
from app.services.importers import import_letters_archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import the Letters archive into the philatelic catalog.")
    parser.add_argument("source_root", type=Path, help="Path to the existing Letters archive.")
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=settings.managed_archive_root,
        help="Path to the managed archive root where files will be copied.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N items.")
    parser.add_argument("--dry-run", action="store_true", help="Parse without copying files or writing the database.")
    parser.add_argument(
        "--recreate-db",
        action="store_true",
        help="Recreate the SQLite database file before importing.",
    )
    return parser


def sqlite_database_path() -> Path | None:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    return Path(settings.database_url.removeprefix(prefix))


def ensure_database_compatibility(recreate_db: bool) -> None:
    db_path = sqlite_database_path()
    if recreate_db and db_path is not None:
        db_path.unlink(missing_ok=True)

    inspector = inspect(engine)
    if "items" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("items")}
    required_columns = {"source_path", "archive_path"}
    if required_columns.issubset(column_names):
        return

    raise SystemExit(
        "Existing database schema is outdated for the importer. Re-run with --recreate-db "
        "or delete philatelic_catalog.sqlite3 before importing."
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.dry_run:
        temp_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=temp_engine)
        session_factory = sessionmaker(bind=temp_engine, autoflush=False, autocommit=False)
    else:
        ensure_database_compatibility(args.recreate_db)
        Base.metadata.create_all(bind=engine)
        session_factory = SessionLocal

    with session_factory() as session:
        summary = import_letters_archive(
            session,
            source_root=args.source_root.resolve(),
            archive_root=args.archive_root.resolve(),
            dry_run=args.dry_run,
            limit=args.limit,
        )

    print(f"Dry run: {summary.dry_run}")
    print(f"Scanned items: {summary.scanned}")
    print(f"Imported items: {summary.imported}")
    print(f"Updated items: {summary.updated}")
    print(f"Copied assets: {summary.copied_assets}")
    print(f"Added tracking events: {summary.tracking_events}")


if __name__ == "__main__":
    main()
