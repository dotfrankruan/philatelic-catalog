from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
import shutil
from pathlib import Path
from collections.abc import Iterable
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Asset, Item, Tag, TrackingEvent

HIDDEN_PREFIXES = (".", "._")
TRACKING_TOKEN_RE = re.compile(r"[A-Z0-9-]{6,}")
BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]")
EVENT_LINE_RE = re.compile(
    r"^(?P<timestamp>(?:[A-Za-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}) \d{2}:\d{2})(?:,\s+|\s+)(?P<rest>.+)$"
)
LOCATION_PREFIX_RE = re.compile(r"^(?P<location>[\u4e00-\u9fffA-Za-z0-9 .'\-()/]+?)(?:\s{2,}|\s+-\s+|\s+)(?P<message>.+)$")
TRACKING_METADATA_FILENAMES = {"manifest.txt"}
TRACKING_METADATA_SUFFIXES = {".yaml", ".yml"}

STATUS_KEYWORDS = {
    "delivered",
    "label created",
    "international arrival",
    "processed at outbound depot",
    "picked up/collected",
    "released for delivery",
    "with border agency",
    "in transit to local depot",
    "international departure",
    "processing at international depot",
}


@dataclass
class ParsedTrackingEvent:
    occurred_at: datetime
    location: str | None
    status: str
    details: str | None
    source: str | None = "manifest"


@dataclass
class ParsedItem:
    country: str
    category: str
    title: str
    tracking_number: str | None
    source_relpath: str
    archive_id: str
    origin: str | None
    destination: str | None
    sent_on: date | None
    received_on: date | None
    status: str | None
    notes: str | None
    is_returned: bool
    is_self_mail: bool
    tags: list[str]
    asset_files: list[tuple[str, Path]]
    tracking_events: list[ParsedTrackingEvent]


@dataclass
class ImportSummary:
    scanned: int = 0
    imported: int = 0
    updated: int = 0
    copied_assets: int = 0
    tracking_events: int = 0
    dry_run: bool = False


def is_visible_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(HIDDEN_PREFIXES)


def visible_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir() if is_visible_file(path))


def discover_item_directories(source_root: Path) -> list[Path]:
    directories: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_dir() or path.name.startswith(HIDDEN_PREFIXES):
            continue
        if visible_files(path):
            directories.append(path)
    return directories


def discover_item_directories_for_source(source_path: Path) -> list[Path]:
    if not source_path.exists():
        raise ValueError(f"Source path does not exist: {source_path}")
    if not source_path.is_dir():
        raise ValueError(f"Source path is not a directory: {source_path}")
    if visible_files(source_path):
        return [source_path]
    return discover_item_directories(source_path)


def discover_item_directories_for_sources(source_paths: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for source_path in source_paths:
        for item_dir in discover_item_directories_for_source(source_path):
            resolved = item_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            discovered.append(resolved)
    return sorted(discovered)


def normalize_name(raw_name: str) -> str:
    return re.sub(r"\s+", " ", raw_name).strip()


def extract_tags(raw_name: str) -> list[str]:
    tags = [tag.strip().lower().replace(" ", "-") for tag in BRACKET_TAG_RE.findall(raw_name)]
    normalized: list[str] = []
    for tag in tags:
        if tag in {"return", "returned", "retour"}:
            normalized.append("returned")
        else:
            normalized.append(tag)
    if "[RETURN]" in raw_name.upper() or "[RETOUR]" in raw_name.upper():
        normalized.append("returned")
    if "SELF-MAIL" in raw_name.upper():
        normalized.append("self-mail")
    return sorted(set(tag for tag in normalized if tag))


def extract_origin(raw_name: str) -> str | None:
    without_brackets = BRACKET_TAG_RE.sub("", raw_name).strip()
    match = re.search(r"\(([^()]*)\)\s*$", without_brackets)
    if not match:
        return None
    origin = normalize_name(match.group(1))
    return origin or None


def derive_tracking_number(raw_name: str) -> str | None:
    without_brackets = BRACKET_TAG_RE.sub("", raw_name)
    without_parens = re.sub(r"\([^()]*\)", "", without_brackets)
    candidates = TRACKING_TOKEN_RE.findall(without_parens.upper())
    if not candidates:
        return None
    return candidates[-1]


def classify_asset_kind(file_path: Path) -> str:
    stem = file_path.stem.lower()
    if stem in {"front", "back", "manifest", "invoice", "shipping-label"}:
        return stem.replace("-", "_")
    if file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".heif", ".heic", ".avif", ".tiff"}:
        return "image"
    if file_path.suffix.lower() == ".pdf":
        return "pdf"
    if file_path.suffix.lower() == ".txt":
        return "text"
    return "file"


def should_import_as_asset(file_path: Path) -> bool:
    if file_path.name.lower() in TRACKING_METADATA_FILENAMES:
        return False
    if file_path.suffix.lower() in TRACKING_METADATA_SUFFIXES:
        return False
    return True


def archive_bucket_for_id(object_id: str) -> str:
    return object_id[0].upper()


def build_archive_asset_relpath(archive_id: str, source_path: Path) -> str:
    bucket = archive_bucket_for_id(archive_id)
    extension = source_path.suffix.lower()
    asset_id = uuid.uuid4().hex.upper()
    return f"{bucket}/{archive_id}-{asset_id}{extension}"


def parse_manifest_text(manifest_text: str) -> tuple[str | None, str | None, str | None, list[ParsedTrackingEvent]]:
    tracking_number = None
    package_status = None
    route = None
    events: list[ParsedTrackingEvent] = []

    for raw_line in manifest_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("===") or line.startswith("Powered by"):
            continue
        if line.startswith("Number:"):
            tracking_number = line.partition(":")[2].strip() or None
            continue
        if line.startswith("Package status:"):
            package_status = line.partition(":")[2].strip() or None
            continue
        if line.startswith("Country:"):
            route = line.partition(":")[2].strip() or None
            continue
        parsed_event = parse_tracking_event_line(line)
        if parsed_event:
            events.append(parsed_event)
    return tracking_number, package_status, route, events


def parse_yaml_tracking_text(yaml_text: str) -> list[ParsedTrackingEvent]:
    try:
        import yaml  # type: ignore
    except Exception:
        return []

    try:
        payload = yaml.safe_load(yaml_text)
    except Exception:
        return []
    return extract_tracking_events_from_yaml(payload)


def extract_tracking_events_from_yaml(payload: Any) -> list[ParsedTrackingEvent]:
    if isinstance(payload, list):
        events: list[ParsedTrackingEvent] = []
        for entry in payload:
            event = yaml_entry_to_tracking_event(entry)
            if event:
                events.append(event)
        return events

    if isinstance(payload, dict):
        for key in ("tracking_events", "events", "history", "timeline", "tracking"):
            candidate = payload.get(key)
            events = extract_tracking_events_from_yaml(candidate)
            if events:
                return events
    return []


def yaml_entry_to_tracking_event(entry: Any) -> ParsedTrackingEvent | None:
    if not isinstance(entry, dict):
        return None

    timestamp_value = None
    for key in ("occurred_at", "timestamp", "datetime", "date", "time"):
        if entry.get(key):
            timestamp_value = str(entry[key]).strip()
            break
    if not timestamp_value:
        return None

    occurred_at = parse_tracking_timestamp(timestamp_value)
    if occurred_at is None:
        return None

    status = None
    for key in ("status", "event", "message", "title"):
        if entry.get(key):
            status = str(entry[key]).strip()
            break
    if not status:
        return None

    location = None
    for key in ("location", "place", "facility", "city"):
        if entry.get(key):
            location = str(entry[key]).strip()
            break

    details = None
    for key in ("details", "description", "note", "content"):
        if entry.get(key):
            details = str(entry[key]).strip()
            break

    source = str(entry.get("source", "yaml")).strip() or "yaml"
    return ParsedTrackingEvent(
        occurred_at=occurred_at,
        location=location,
        status=status,
        details=details,
        source=source,
    )


def parse_tracking_timestamp(value: str) -> datetime | None:
    formats = (
        "%B %d, %Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_tracking_event_line(line: str) -> ParsedTrackingEvent | None:
    match = EVENT_LINE_RE.match(line)
    if not match:
        return None
    occurred_at = parse_tracking_timestamp(match.group("timestamp"))
    if occurred_at is None:
        return None
    rest = match.group("rest").strip()
    rest_parts = split_tracking_rest(rest)

    location: str | None = None
    status: str
    details: str | None = None

    if len(rest_parts) == 1:
        status = rest_parts[0]
    elif len(rest_parts) == 2:
        first, second = rest_parts
        if first.lower() in STATUS_KEYWORDS:
            status = first
            details = second
        elif re.search(r"[\u4e00-\u9fff]", first):
            location = first
            status = second
        else:
            location = first
            status = second
    else:
        location, status, details = rest_parts

    return ParsedTrackingEvent(
        occurred_at=occurred_at,
        location=location,
        status=status,
        details=details,
    )


def split_tracking_rest(rest: str) -> list[str]:
    comma_parts = [part.strip() for part in re.split(r"\s*,\s*", rest) if part.strip()]
    if len(comma_parts) >= 2:
        if len(comma_parts) == 2:
            return comma_parts
        return [comma_parts[0], comma_parts[1], ", ".join(comma_parts[2:])]

    prefix_match = LOCATION_PREFIX_RE.match(rest)
    if prefix_match:
        location = normalize_name(prefix_match.group("location"))
        message = normalize_name(prefix_match.group("message"))
        if location and message and is_probable_tracking_location(location):
            return [location, message]

    return [normalize_name(rest)]


def is_probable_tracking_location(value: str) -> bool:
    lowered = value.lower()
    if lowered in STATUS_KEYWORDS:
        return False
    if re.search(r"[\u4e00-\u9fff]", value):
        return True
    if any(token in lowered for token in ("province", "city", "district", "depot", "office", "airport")):
        return True
    if re.fullmatch(r"[A-Z][A-Za-z.'()/-]+(?:\s+[A-Z][A-Za-z.'()/-]+)+", value):
        return True
    return False


def derive_item_taxonomy(item_dir: Path) -> tuple[str, str, str, str]:
    if len(item_dir.parts) < 3:
        raise ValueError(f"Unsupported item directory layout: {item_dir}")
    country = item_dir.parents[1].name
    category = item_dir.parent.name
    title = normalize_name(item_dir.name)
    source_relpath = Path(country, category, item_dir.name).as_posix()
    return country, category, title, source_relpath


def build_parsed_item(
    item_dir: Path,
    source_root: Path | None = None,
    archive_root: Path | None = None,
) -> ParsedItem:
    country, category, title, source_relpath = derive_item_taxonomy(item_dir)
    origin = extract_origin(title)
    tags = extract_tags(title)
    tracking_number = derive_tracking_number(title)
    archive_id = str(uuid.uuid4()).upper()

    manifest_path = next((path for path in visible_files(item_dir) if path.name.lower() == "manifest.txt"), None)
    yaml_paths = [path for path in visible_files(item_dir) if path.suffix.lower() in {".yaml", ".yml"}]
    manifest_text = manifest_path.read_text(encoding="utf-8", errors="replace") if manifest_path else ""
    manifest_tracking, package_status, route, tracking_events = parse_manifest_text(manifest_text)
    for yaml_path in yaml_paths:
        yaml_text = yaml_path.read_text(encoding="utf-8", errors="replace")
        tracking_events.extend(parse_yaml_tracking_text(yaml_text))

    if manifest_tracking:
        tracking_number = manifest_tracking

    ordered_events = sorted(tracking_events, key=lambda event: event.occurred_at)

    notes_parts = [f"Imported from {source_relpath}"]
    if route:
        notes_parts.append(f"Route: {route}")

    asset_files = [
        (classify_asset_kind(path), path)
        for path in visible_files(item_dir)
        if should_import_as_asset(path)
    ]

    return ParsedItem(
        country=country,
        category=category,
        title=title,
        tracking_number=tracking_number,
        source_relpath=source_relpath,
        archive_id=archive_id,
        origin=origin,
        destination=None,
        sent_on=None,
        received_on=None,
        status=None,
        notes="\n".join(notes_parts),
        is_returned=("[RETURN]" in title.upper() or "[RETOUR]" in title.upper() or "(RETURNED)" in title.upper()),
        is_self_mail="SELF-MAIL" in title.upper(),
        tags=tags,
        asset_files=asset_files,
        tracking_events=ordered_events,
    )


def copy_assets(
    asset_files: list[tuple[str, Path]], archive_root: Path, archive_id: str, dry_run: bool
) -> list[tuple[str, Path]]:
    copied: list[tuple[str, Path]] = []
    for kind, source_path in asset_files:
        relative_path = Path(build_archive_asset_relpath(archive_id, source_path))
        destination_path = archive_root / relative_path
        if not dry_run:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
        copied.append((kind, relative_path))
    return copied


def get_or_create_tag(session: Session, tag_name: str) -> Tag:
    existing = session.scalar(select(Tag).where(Tag.name == tag_name))
    if existing is not None:
        return existing
    created = Tag(name=tag_name)
    session.add(created)
    session.flush()
    return created


def upsert_item_from_parsed(
    session: Session, parsed: ParsedItem, archive_root: Path, dry_run: bool
) -> tuple[Item | None, bool, int, int]:
    existing = session.scalar(
        select(Item)
        .options(
            selectinload(Item.assets),
            selectinload(Item.tags),
            selectinload(Item.tracking_events),
        )
        .where(Item.source_relpath == parsed.source_relpath)
    )

    created = existing is None
    item = existing or Item()
    item.country = parsed.country
    item.category = parsed.category
    item.title = parsed.title
    item.tracking_number = parsed.tracking_number
    item.source_relpath = parsed.source_relpath
    if created:
        item.archive_id = parsed.archive_id
    item.origin = parsed.origin
    item.destination = parsed.destination
    item.sent_on = parsed.sent_on
    item.received_on = parsed.received_on
    item.status = parsed.status
    item.notes = parsed.notes
    item.is_returned = parsed.is_returned
    item.is_self_mail = parsed.is_self_mail

    if dry_run:
        return item, created, len(parsed.asset_files), len(parsed.tracking_events)

    session.add(item)
    session.flush()

    for asset in list(item.assets):
        session.delete(asset)

    copied_assets = copy_assets(parsed.asset_files, archive_root, item.archive_id, dry_run=False)
    for kind, copied_path in copied_assets:
        session.add(Asset(item_id=item.id, kind=kind, path=copied_path.as_posix()))

    item.tags.clear()
    for tag_name in parsed.tags:
        item.tags.append(get_or_create_tag(session, tag_name))

    existing_events = {
        (event.occurred_at, event.status, event.location or "", event.details or "")
        for event in item.tracking_events
    }
    added_events = 0
    for event in parsed.tracking_events:
        key = (event.occurred_at, event.status, event.location or "", event.details or "")
        if key in existing_events:
            continue
        session.add(
            TrackingEvent(
                item_id=item.id,
                occurred_at=event.occurred_at,
                location=event.location,
                status=event.status,
                details=event.details,
                source=event.source,
            )
        )
        added_events += 1

    return item, created, len(copied_assets), added_events


def import_letters_archive(
    session: Session,
    source_root: Path,
    archive_root: Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> ImportSummary:
    return import_letter_sources(
        session,
        [source_root],
        archive_root,
        dry_run=dry_run,
        limit=limit,
    )


def import_letter_sources(
    session: Session,
    source_paths: Iterable[Path],
    archive_root: Path,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> ImportSummary:
    summary = ImportSummary(dry_run=dry_run)
    item_directories = discover_item_directories_for_sources(source_paths)
    if limit is not None:
        item_directories = item_directories[:limit]

    for item_dir in item_directories:
        parsed = build_parsed_item(item_dir)
        summary.scanned += 1
        _, created, copied_assets, added_events = upsert_item_from_parsed(
            session, parsed, archive_root=archive_root, dry_run=dry_run
        )
        if created:
            summary.imported += 1
        else:
            summary.updated += 1
        summary.copied_assets += copied_assets
        summary.tracking_events += added_events

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return summary
