from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
import shutil
from pathlib import Path
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Asset, Item, Tag, TrackingEvent

HIDDEN_PREFIXES = (".", "._")
TRACKING_TOKEN_RE = re.compile(r"[A-Z0-9-]{6,}")
BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]")
EVENT_LINE_RE = re.compile(r"^(?P<timestamp>[A-Za-z]+ \d{1,2}, \d{4} \d{2}:\d{2}), (?P<rest>.+)$")

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


def normalize_name(raw_name: str) -> str:
    return re.sub(r"\s+", " ", raw_name).strip()


def extract_tags(raw_name: str) -> list[str]:
    tags = [tag.strip().lower().replace(" ", "-") for tag in BRACKET_TAG_RE.findall(raw_name)]
    if "[RETURN]" in raw_name.upper():
        tags.append("return")
    if "SELF-MAIL" in raw_name.upper():
        tags.append("self-mail")
    return sorted(set(tag for tag in tags if tag))


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


def parse_tracking_event_line(line: str) -> ParsedTrackingEvent | None:
    match = EVENT_LINE_RE.match(line)
    if not match:
        return None
    occurred_at = datetime.strptime(match.group("timestamp"), "%B %d, %Y %H:%M")
    rest_parts = [part.strip() for part in match.group("rest").split(", ", 2)]

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


def build_parsed_item(item_dir: Path, source_root: Path, archive_root: Path) -> ParsedItem:
    relative = item_dir.relative_to(source_root)
    if len(relative.parts) < 3:
        raise ValueError(f"Unsupported item directory layout: {item_dir}")

    country = relative.parts[0]
    category = relative.parts[1]
    title = normalize_name(relative.name)
    source_relpath = relative.as_posix()
    origin = extract_origin(title)
    tags = extract_tags(title)
    tracking_number = derive_tracking_number(title)
    archive_id = str(uuid.uuid4()).upper()

    manifest_path = next((path for path in visible_files(item_dir) if path.name.lower() == "manifest.txt"), None)
    manifest_text = manifest_path.read_text(encoding="utf-8", errors="replace") if manifest_path else ""
    manifest_tracking, package_status, route, tracking_events = parse_manifest_text(manifest_text)

    if manifest_tracking:
        tracking_number = manifest_tracking

    destination = None
    if route and "->" in route:
        _, _, destination = route.partition("->")
        destination = normalize_name(destination) or None
        if destination == "Unknown":
            destination = None

    ordered_events = sorted(tracking_events, key=lambda event: event.occurred_at)
    sent_on = ordered_events[0].occurred_at.date() if ordered_events else None
    received_on = None
    for event in reversed(ordered_events):
        lowered = event.status.lower()
        if "deliver" in lowered or "签收" in event.status:
            received_on = event.occurred_at.date()
            break

    notes_parts = [f"Imported from {source_relpath}"]
    if route:
        notes_parts.append(f"Route: {route}")

    asset_files = [(classify_asset_kind(path), path) for path in visible_files(item_dir)]

    return ParsedItem(
        country=country,
        category=category,
        title=title,
        tracking_number=tracking_number,
        source_relpath=source_relpath,
        archive_id=archive_id,
        origin=origin,
        destination=destination,
        sent_on=sent_on,
        received_on=received_on,
        status=package_status,
        notes="\n".join(notes_parts),
        is_returned="[RETURN]" in title.upper() or "(RETURNED)" in title.upper(),
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
    summary = ImportSummary(dry_run=dry_run)
    item_directories = discover_item_directories(source_root)
    if limit is not None:
        item_directories = item_directories[:limit]

    for item_dir in item_directories:
        parsed = build_parsed_item(item_dir, source_root, archive_root)
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
