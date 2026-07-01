from __future__ import annotations

from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from html import escape
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import parse_qs, urlencode
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db.database import SessionLocal, get_session
from app.models import Asset, Item, Tag, TrackingEvent
from app.services.importers import (
    ImportPreviewRow,
    ImportSummary,
    describe_import_letter_sources,
    import_letter_sources,
)
from app.services.items import build_item_query

ui_router = APIRouter(include_in_schema=False)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heif", ".heic", ".avif", ".tiff"}
HEIF_SUFFIXES = {".heif", ".heic"}
DISPLAY_MARKER_RE = re.compile(r"\[[^\]]+\]")
PAGE_SIZE = 12
IMPORT_JOBS: dict[str, dict[str, object]] = {}
IMPORT_JOBS_LOCK = threading.Lock()


def render_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <style>
      :root {{
        --paper: #f4efe4;
        --paper-strong: #e8dcc7;
        --paper-deep: #ddc6a6;
        --ink: #1d1712;
        --muted: #6e6255;
        --line: rgba(122, 94, 62, 0.18);
        --accent: #a4532f;
        --accent-strong: #7f3e22;
        --accent-soft: #d7a97c;
        --accent-wash: rgba(164, 83, 47, 0.08);
        --sage: #71816a;
        --danger: #be7a72;
        --card: rgba(255,255,255,0.64);
        --card-solid: rgba(255, 250, 242, 0.96);
        --shadow: 0 24px 64px rgba(47, 33, 20, 0.11);
        --shadow-soft: 0 12px 30px rgba(47, 33, 20, 0.08);
      }}

      * {{ box-sizing: border-box; }}

      body {{
        margin: 0;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(164, 83, 47, 0.18), transparent 26%),
          radial-gradient(circle at top right, rgba(221, 198, 166, 0.3), transparent 24%),
          linear-gradient(180deg, #f7f3eb 0%, #efe6d8 52%, #eadfcf 100%);
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      }}

      a {{ color: inherit; text-decoration: none; }}

      .shell {{
        min-height: 100vh;
        display: grid;
        grid-template-columns: 340px minmax(0, 1fr);
        gap: 22px;
        padding: 22px;
      }}

      .sidebar {{
        border: 1px solid var(--line);
        border-radius: 28px;
        background:
          linear-gradient(180deg, rgba(255, 251, 245, 0.96), rgba(247, 239, 228, 0.94));
        backdrop-filter: blur(12px);
        box-shadow: var(--shadow);
        padding: 26px 22px;
        position: sticky;
        top: 22px;
        height: calc(100vh - 44px);
        overflow: auto;
      }}

      .main {{
        padding: 8px 4px 28px;
        min-width: 0;
      }}

      .eyebrow {{
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent);
        font-size: 11px;
        margin-bottom: 12px;
        font-weight: 700;
      }}

      h1 {{
        margin: 0 0 10px;
        font-size: clamp(2.4rem, 5vw, 4.3rem);
        line-height: 0.96;
        letter-spacing: -0.03em;
        max-width: 12ch;
      }}

      h2 {{
        margin: 0;
        font-size: clamp(1.45rem, 2.3vw, 2rem);
        line-height: 1.08;
        letter-spacing: -0.02em;
      }}

      .subtitle {{
        margin: 0;
        color: var(--muted);
        line-height: 1.65;
        font-size: 1.04rem;
      }}

      .panel {{
        background: var(--card);
        border: 1px solid rgba(213, 200, 180, 0.9);
        border-radius: 28px;
        box-shadow: var(--shadow);
      }}

      .masthead {{
        padding: 26px 28px 30px;
        background:
          linear-gradient(135deg, rgba(255, 251, 245, 0.94), rgba(246, 235, 219, 0.9)),
          radial-gradient(circle at top right, rgba(164, 83, 47, 0.08), transparent 32%);
        position: relative;
        overflow: hidden;
      }}

      .masthead::after {{
        content: "";
        position: absolute;
        inset: auto -40px -60px auto;
        width: 220px;
        height: 220px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(164, 83, 47, 0.12), transparent 65%);
        pointer-events: none;
      }}

      .masthead-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(260px, 0.95fr);
        gap: 18px;
        align-items: end;
      }}

      .hero-note {{
        position: relative;
        z-index: 1;
      }}

      .hero-stats {{
        display: grid;
        gap: 12px;
        position: relative;
        z-index: 1;
      }}

      .hero-stat {{
        padding: 16px 18px;
        border-radius: 20px;
        border: 1px solid rgba(164, 83, 47, 0.14);
        background: rgba(255,255,255,0.66);
        box-shadow: var(--shadow-soft);
      }}

      .hero-stat-value {{
        font-size: 1.75rem;
        line-height: 1;
        margin-bottom: 4px;
      }}

      .hero-stat-label {{
        color: var(--muted);
        font-size: 0.95rem;
      }}

      .sidebar-block {{
        margin-top: 18px;
      }}

      .filters {{
        padding: 18px;
      }}

      .filters form {{
        display: grid;
        gap: 14px;
      }}

      .filters label {{
        display: grid;
        gap: 6px;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
      }}

      input, select {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 15px;
        background: rgba(255,255,255,0.88);
        padding: 12px 14px;
        font: inherit;
        color: var(--ink);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.45);
      }}

      input[type="checkbox"] {{
        width: auto;
        margin-right: 8px;
      }}

      button {{
        border: 0;
        border-radius: 999px;
        padding: 12px 18px;
        background: linear-gradient(135deg, var(--accent), var(--accent-strong));
        color: white;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
        box-shadow: 0 10px 24px rgba(164, 83, 47, 0.24);
      }}

      .reset {{
        display: inline-block;
        margin-left: 12px;
        color: var(--muted);
        font-size: 14px;
      }}

      .list-meta {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin: 16px 4px 12px;
        color: var(--muted);
        font-size: 14px;
      }}

      .item-list {{
        display: grid;
        gap: 10px;
      }}

      .country-list,
      .category-list,
      .browse-grid,
      .pager {{
        display: grid;
        gap: 10px;
      }}

      .browse-card,
      .nav-link {{
        display: block;
        padding: 16px 17px;
        border-radius: 20px;
        border: 1px solid rgba(213, 200, 180, 0.6);
        background: rgba(255,255,255,0.62);
        transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
      }}

      .browse-card:hover,
      .nav-link:hover,
      .item-link:hover,
      .button-link:hover {{
        transform: translateY(-1px);
        box-shadow: var(--shadow-soft);
      }}

      .nav-link.active,
      .browse-card.active {{
        border-color: rgba(164, 83, 47, 0.28);
        box-shadow:
          inset 0 0 0 1px rgba(164, 83, 47, 0.14),
          0 12px 28px rgba(73, 47, 27, 0.08);
        background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(241,232,220,0.96));
      }}

      .item-link {{
        display: block;
        padding: 14px 16px;
        border-radius: 18px;
        border: 1px solid rgba(213, 200, 180, 0.7);
        background: rgba(255,255,255,0.58);
      }}

      .item-link.active {{
        border-color: var(--accent-soft);
        box-shadow: inset 0 0 0 1px rgba(156, 79, 45, 0.12);
        background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(239,231,217,0.95));
      }}

      .item-country {{
        color: var(--accent);
        font-size: 12px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        margin-bottom: 8px;
        font-weight: 700;
      }}

      .item-title {{
        font-size: 1.55rem;
        line-height: 1.22;
        margin-bottom: 8px;
      }}

      .item-sub {{
        color: var(--muted);
        font-size: 14px;
      }}

      .browse-grid {{
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      }}

      .count-pill {{
        display: inline-block;
        margin-top: 10px;
        padding: 6px 10px;
        border-radius: 999px;
        background: rgba(194, 127, 120, 0.12);
        color: #bf7c76;
        font-size: 12px;
      }}

      .pager {{
        grid-auto-flow: column;
        justify-content: start;
        margin-top: 20px;
        align-items: center;
      }}

      .item-title.returned,
      .detail-title.returned {{
        color: var(--danger);
      }}

      .detail {{
        padding: 28px;
      }}

      .detail-head {{
        display: flex;
        justify-content: space-between;
        gap: 20px;
        align-items: start;
        margin-bottom: 26px;
      }}

      .detail-title {{
        font-size: clamp(2.2rem, 3.5vw, 3.4rem);
        line-height: 1;
        margin: 0 0 8px;
        max-width: 12ch;
      }}

      .pill-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}

      .pill {{
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(164, 83, 47, 0.08);
        color: var(--accent);
        font-size: 13px;
      }}

      .inline-meta {{
        margin: 10px 0 10px;
        padding: 12px 13px;
        border-radius: 16px;
        background: rgba(255,255,255,0.76);
        border: 1px solid rgba(213, 200, 180, 0.7);
      }}

      .inline-meta .meta-label {{
        margin-bottom: 4px;
      }}

      .location-breakdown {{
        display: grid;
        gap: 10px;
      }}

      .button-link {{
        display: inline-block;
        border-radius: 999px;
        padding: 11px 16px;
        background: rgba(164, 83, 47, 0.10);
        color: var(--accent);
        font-size: 14px;
        border: 1px solid rgba(164, 83, 47, 0.1);
      }}

      .meta-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 26px;
      }}

      .meta-card {{
        padding: 16px;
        border-radius: 20px;
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(213, 200, 180, 0.7);
      }}

      .meta-label {{
        color: var(--muted);
        font-size: 12px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        margin-bottom: 8px;
      }}

      .meta-value {{
        font-size: 18px;
        line-height: 1.35;
        word-break: break-word;
      }}

      .section {{
        margin-top: 28px;
      }}

      .section h2 {{
        margin: 0 0 14px;
        font-size: 1.65rem;
      }}

      .asset-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 16px;
      }}

      .asset-card {{
        padding: 14px;
        border-radius: 22px;
        background: rgba(255,255,255,0.7);
        border: 1px solid rgba(213, 200, 180, 0.7);
      }}

      .asset-card img {{
        width: 100%;
        height: 260px;
        object-fit: cover;
        border-radius: 16px;
        display: block;
        margin-bottom: 12px;
        background: var(--paper-strong);
      }}

      .asset-kind {{
        color: var(--accent);
        font-size: 12px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        margin-bottom: 6px;
      }}

      .asset-path {{
        color: var(--muted);
        font-size: 13px;
        word-break: break-all;
      }}

      .timeline {{
        display: grid;
        gap: 14px;
      }}

      .event {{
        padding: 16px 18px;
        border-left: 4px solid var(--accent-soft);
        border-radius: 0 20px 20px 0;
        background: rgba(255,255,255,0.72);
        box-shadow: var(--shadow-soft);
      }}

      .event-time {{
        color: var(--muted);
        font-size: 13px;
        margin-bottom: 6px;
      }}

      .empty {{
        padding: 40px 32px;
        text-align: center;
        color: var(--muted);
      }}

      textarea {{
        width: 100%;
        min-height: 120px;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: rgba(255,255,255,0.88);
        padding: 12px 14px;
        font: inherit;
        color: var(--ink);
        resize: vertical;
      }}

      .admin-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
        gap: 22px;
      }}

      .admin-form {{
        padding: 22px;
      }}

      .admin-form form {{
        display: grid;
        gap: 14px;
      }}

      .flash {{
        margin-bottom: 18px;
        padding: 14px 16px;
        border-radius: 18px;
        background: rgba(113, 129, 106, 0.12);
        color: #50604a;
        border: 1px solid rgba(113, 129, 106, 0.25);
      }}

      .flash.error {{
        background: rgba(164, 83, 47, 0.10);
        color: var(--accent-strong);
        border-color: rgba(164, 83, 47, 0.22);
      }}

      .check-row {{
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--muted);
      }}

      .summary-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
        margin-bottom: 18px;
      }}

      .progress-shell {{
        margin-bottom: 18px;
      }}

      .progress-bar {{
        width: 100%;
        height: 14px;
        border-radius: 999px;
        background: rgba(213, 200, 180, 0.8);
        overflow: hidden;
        margin: 10px 0 8px;
      }}

      .progress-fill {{
        height: 100%;
        background: linear-gradient(90deg, var(--accent), #d58b5f);
        width: 0%;
        transition: width 0.25s ease;
      }}

      .preview-list {{
        display: grid;
        gap: 12px;
      }}

      .preview-card {{
        padding: 14px 16px;
        border-radius: 20px;
        border: 1px solid rgba(213, 200, 180, 0.7);
        background: rgba(255,255,255,0.68);
      }}

      .uploader-status {{
        margin-top: 14px;
      }}

      .toolbar {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
      }}

      .stack {{
        display: grid;
        gap: 18px;
      }}

      .section-frame {{
        padding: 24px 26px;
      }}

      .section-copy {{
        margin-bottom: 18px;
      }}

      .section-copy .subtitle {{
        margin-top: 6px;
        max-width: 72ch;
      }}

      .sidebar-heading {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
      }}

      .micro-stat-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 14px;
      }}

      .micro-stat {{
        padding: 12px 13px;
        border-radius: 18px;
        background: rgba(255,255,255,0.7);
        border: 1px solid rgba(213, 200, 180, 0.62);
      }}

      .micro-stat strong {{
        display: block;
        font-size: 1.2rem;
        margin-bottom: 3px;
      }}

      .sidebar-divider {{
        height: 1px;
        border: 0;
        background: linear-gradient(90deg, rgba(164, 83, 47, 0.2), transparent);
        margin: 18px 0;
      }}

      .detail-columns {{
        display: grid;
        grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.75fr);
        gap: 22px;
      }}

      .note-card {{
        white-space: normal;
      }}

      .hint-list {{
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
        line-height: 1.7;
      }}

      @media (max-width: 1180px) {{
        .masthead-grid,
        .detail-columns {{
          grid-template-columns: 1fr;
        }}

        .meta-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}

      @media (max-width: 980px) {{
        .shell {{
          grid-template-columns: 1fr;
          padding: 14px;
        }}

        .sidebar {{
          position: static;
          top: 0;
          height: auto;
        }}

        .meta-grid {{
          grid-template-columns: 1fr;
        }}

        .admin-grid {{
          grid-template-columns: 1fr;
        }}

        .detail-head {{
          flex-direction: column;
        }}

        .main {{
          padding: 0 0 24px;
        }}
      }}
    </style>
  </head>
  <body>{body}</body>
</html>"""


def build_home_link(
    *,
    q: str = "",
    country: str = "",
    category: str = "",
    item_id: int | None = None,
    page: int | None = None,
) -> str:
    params: dict[str, str | int] = {}
    if q:
        params["q"] = q
    if country:
        params["country"] = country
    if category:
        params["category"] = category
    if item_id is not None:
        params["item"] = item_id
    if page is not None and page > 1:
        params["page"] = page
    if not params:
        return "/"
    return f"/?{urlencode(params)}"


def display_title(raw_title: str) -> str:
    base_title, _ = split_title_and_location(raw_title)
    return base_title or raw_title


def split_title_and_location(raw_title: str) -> tuple[str, str | None]:
    cleaned = normalize_text_for_display(DISPLAY_MARKER_RE.sub(" ", raw_title))
    match = re.search(r"\(([^()]*)\)\s*$", cleaned)
    if not match:
        return cleaned, None
    location = normalize_text_for_display(match.group(1))
    base_title = normalize_text_for_display(cleaned[: match.start()])
    return base_title or cleaned, location or None


def display_location(raw_title: str, stored_location: str | None) -> str:
    if stored_location and normalize_text_for_display(stored_location):
        return normalize_text_for_display(stored_location)
    _, parsed_location = split_title_and_location(raw_title)
    return parsed_location or "N/A"


def parse_location_parts(raw_title: str, stored_location: str | None) -> dict[str, str]:
    location_text = display_location(raw_title, stored_location)
    if location_text == "N/A":
        return {"location": "N/A", "city": "N/A", "region": "N/A", "country": "N/A"}

    normalized = normalize_text_for_display(location_text)
    segments = [normalize_text_for_display(part) for part in re.split(r"\s*(?:,|/|->|\|)\s*", normalized) if normalize_text_for_display(part)]
    city = "N/A"
    region = "N/A"
    country = "N/A"

    if len(segments) >= 1:
        city = segments[0]
    if len(segments) >= 2:
        region = segments[1]
    if len(segments) >= 3:
        country = ", ".join(segments[2:])

    return {
        "location": normalized,
        "city": city,
        "region": region,
        "country": country,
    }


def normalize_text_for_display(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def display_relpath(raw_relpath: str) -> str:
    parts = Path(raw_relpath).parts
    if not parts:
        return raw_relpath
    cleaned_last = display_title(parts[-1])
    return "/".join([*parts[:-1], cleaned_last])


def resolve_archive_path(asset_path: str) -> Path:
    relative = Path(asset_path)
    resolved = (settings.managed_archive_root / relative).resolve()
    resolved.relative_to(settings.managed_archive_root.resolve())
    return resolved


def get_item_or_404(session: Session, item_id: int) -> Item:
    item = session.scalar(
        select(Item).where(Item.id == item_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def get_or_create_tag(session: Session, tag_name: str) -> Tag:
    tag = session.scalar(select(Tag).where(Tag.name == tag_name))
    if tag is None:
        tag = Tag(name=tag_name)
        session.add(tag)
        session.flush()
    return tag


def parse_tag_input(raw_tags: str) -> list[str]:
    parts = re.split(r"[,\\n]", raw_tags)
    tags: list[str] = []
    for part in parts:
        tag = part.strip().lower().replace(" ", "-")
        if not tag:
            continue
        if tag in {"return", "retour"}:
            tag = "returned"
        tags.append(tag)
    return sorted(set(tags))


def parse_datetime_input(raw_value: str) -> datetime:
    cleaned = raw_value.strip()
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(cleaned, pattern)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Invalid datetime format")


def get_form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key)
    if not values:
        return default
    return values[0]


def parse_source_paths_input(raw_paths: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw_line in raw_paths.splitlines():
        candidate = raw_line.strip()
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"Source path not found: {candidate}")
        if not path.is_dir():
            raise HTTPException(status_code=400, detail=f"Source path is not a directory: {candidate}")
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(resolved)
    if not paths:
        raise HTTPException(status_code=400, detail="Add at least one source folder.")
    return paths


def parse_limit_input(raw_limit: str) -> int | None:
    cleaned = raw_limit.strip()
    if not cleaned:
        return None
    try:
        value = int(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Limit must be a whole number.") from exc
    if value <= 0:
        raise HTTPException(status_code=400, detail="Limit must be greater than zero.")
    return value


def sanitize_uploaded_relpath(filename: str) -> Path:
    cleaned = filename.replace("\\", "/").strip("/")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Uploaded file is missing a path.")
    relative = Path(cleaned)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise HTTPException(status_code=400, detail=f"Unsafe upload path: {filename}")
    return relative


async def extract_uploaded_tree(request: Request) -> tuple[Path, int, str, str]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400, detail="Uploader expects multipart form data.")

    body = await request.body()
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )

    mode = "preview"
    limit_raw = ""
    upload_id = uuid.uuid4().hex
    staging_root = settings.upload_staging_root / upload_id
    staging_root.mkdir(parents=True, exist_ok=True)
    file_count = 0

    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if filename:
            relative = sanitize_uploaded_relpath(filename)
            destination = (staging_root / relative).resolve()
            destination.relative_to(staging_root.resolve())
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            file_count += 1
            continue

        value = payload.decode("utf-8", errors="replace")
        if field_name == "mode":
            mode = value.strip() or "preview"
        elif field_name == "limit":
            limit_raw = value.strip()

    if file_count == 0:
        raise HTTPException(status_code=400, detail="Choose a folder before uploading.")

    return staging_root, file_count, mode, limit_raw


def snapshot_job(job_id: str) -> dict[str, object] | None:
    with IMPORT_JOBS_LOCK:
        job = IMPORT_JOBS.get(job_id)
        if job is None:
            return None
        return dict(job)


def update_job(job_id: str, **changes: object) -> None:
    with IMPORT_JOBS_LOCK:
        if job_id not in IMPORT_JOBS:
            return
        IMPORT_JOBS[job_id].update(changes)


def start_import_job(source_paths: list[Path], limit: int | None) -> str:
    job_id = uuid.uuid4().hex
    with IMPORT_JOBS_LOCK:
        IMPORT_JOBS[job_id] = {
            "job_id": job_id,
            "state": "queued",
            "completed": 0,
            "total": 0,
            "current_item": "",
            "summary": None,
            "error": None,
        }

    def run() -> None:
        with SessionLocal() as session:
            try:
                update_job(job_id, state="running")

                def on_progress(index: int, total: int, parsed, summary: ImportSummary) -> None:
                    update_job(
                        job_id,
                        completed=index,
                        total=total,
                        current_item=display_title(parsed.title),
                        summary={
                            "scanned": summary.scanned,
                            "imported": summary.imported,
                            "updated": summary.updated,
                            "copied_assets": summary.copied_assets,
                            "tracking_events": summary.tracking_events,
                            "dry_run": summary.dry_run,
                        },
                    )

                summary = import_letter_sources(
                    session,
                    source_paths,
                    settings.managed_archive_root,
                    dry_run=False,
                    limit=limit,
                    progress_callback=on_progress,
                )
                update_job(
                    job_id,
                    state="completed",
                    completed=summary.scanned,
                    total=summary.scanned,
                    current_item="",
                    summary={
                        "scanned": summary.scanned,
                        "imported": summary.imported,
                        "updated": summary.updated,
                        "copied_assets": summary.copied_assets,
                        "tracking_events": summary.tracking_events,
                        "dry_run": summary.dry_run,
                    },
                )
            except Exception as exc:
                session.rollback()
                update_job(job_id, state="failed", error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return job_id


def build_asset_public_path(asset_path: str, suffix: str) -> str:
    if suffix in HEIF_SUFFIXES:
        return f"/asset-preview?{urlencode({'path': asset_path})}"
    return "/archive/" + "/".join(escape(part) for part in Path(asset_path).parts)


def render_asset_card(asset_path: str, kind: str) -> str:
    suffix = Path(asset_path).suffix.lower()
    public_path = build_asset_public_path(asset_path, suffix)
    label = escape(kind.replace("_", " ")) if kind else "asset"
    path_text = escape(asset_path)

    if suffix in IMAGE_SUFFIXES:
        preview = f'<img src="{public_path}" alt="{label}" loading="lazy" />'
    else:
        preview = (
            f'<div class="meta-card" style="min-height:240px; display:grid; place-items:center;">'
            f'<a href="{public_path}" target="_blank">Open file</a></div>'
        )

    return (
        f'<article class="asset-card">'
        f"{preview}"
        f'<div class="asset-kind">{label}</div>'
        f'<div class="asset-path">{path_text}</div>'
        f"</article>"
    )


def render_home(
    items: list[Item],
    selected_item: Item | None,
    countries: list[str],
    categories: list[str],
    country_counts: dict[str, int],
    category_counts: dict[str, int],
    q: str,
    country: str,
    category: str,
    page: int,
    total_items: int,
    total_pages: int,
) -> str:
    selected_id = selected_item.id if selected_item else None

    country_links = "".join(
        f'<a class="nav-link{" active" if value == country else ""}" href="{build_home_link(q=q, country=value)}">'
        f'<div class="item-country">{escape(value)}</div>'
        f'<div class="item-sub">{country_counts.get(value, 0)} item{"s" if country_counts.get(value, 0) != 1 else ""}</div>'
        f"</a>"
        for value in countries
    ) or '<div class="empty">No countries yet.</div>'

    category_links = ""
    if country:
        category_links = "".join(
            f'<a class="nav-link{" active" if value == category else ""}" href="{build_home_link(q=q, country=country, category=value)}">'
            f'<div class="meta-label">{escape(value)}</div>'
            f'<div class="item-sub">{category_counts.get(value, 0)} item{"s" if category_counts.get(value, 0) != 1 else ""}</div>'
            f"</a>"
            for value in categories
        ) or '<div class="empty">No categories for this country.</div>'

    browse_header = ""
    browse_markup = ""
    pager_markup = ""

    if not country:
        browse_header = '<div class="eyebrow">Browse Countries</div><h2>Select a country or region</h2>'
        browse_markup = "".join(
            f'<a class="browse-card" href="{build_home_link(q=q, country=value)}">'
            f'<div class="item-country">{escape(value)}</div>'
            f'<div class="meta-value">{country_counts.get(value, 0)} item{"s" if country_counts.get(value, 0) != 1 else ""}</div>'
            f"</a>"
            for value in countries
        ) or '<div class="empty">No countries yet.</div>'
    elif not category:
        browse_header = f'<div class="eyebrow">{escape(country)}</div><h2>Choose a mail type</h2>'
        browse_markup = "".join(
            f'<a class="browse-card" href="{build_home_link(q=q, country=country, category=value)}">'
            f'<div class="meta-label">{escape(value)}</div>'
            f'<div class="meta-value">{category_counts.get(value, 0)} item{"s" if category_counts.get(value, 0) != 1 else ""}</div>'
            f"</a>"
            for value in categories
        ) or '<div class="empty">No categories for this country.</div>'
    else:
        browse_header = (
            f'<div class="eyebrow">{escape(country)} / {escape(category)}</div>'
            f'<h2>Items on this page</h2>'
            f'<p class="subtitle" style="margin-bottom:16px;">{total_items} total item{"s" if total_items != 1 else ""} in this section.</p>'
        )
        item_cards = []
        for item in items:
            title_text = display_title(item.title)
            location_parts = parse_location_parts(item.title, item.origin)
            title_classes = "item-title"
            if item.is_returned:
                title_classes += " returned"
            subtitle_text = item.tracking_number or item.category
            returned_badge = '<span class="count-pill">Returned</span>' if item.is_returned else ""
            item_cards.append(
                f'<a class="browse-card{" active" if item.id == selected_id else ""}" href="{build_home_link(q=q, country=country, category=category, item_id=item.id, page=page)}">'
                f'<div class="{title_classes}">{escape(title_text)}</div>'
                f'<div class="inline-meta"><div class="meta-label">Location</div><div class="item-sub">{escape(location_parts["location"])}</div></div>'
                f'<div class="item-sub">{escape(subtitle_text)}</div>'
                f"{returned_badge}"
                f"</a>"
            )
        browse_markup = "".join(item_cards) or '<div class="empty">No items on this page.</div>'

        if total_pages > 1:
            pager_links = []
            if page > 1:
                pager_links.append(
                    f'<a class="button-link" href="{build_home_link(q=q, country=country, category=category, item_id=selected_id, page=page - 1)}">Previous</a>'
                )
            pager_links.append(f'<span class="pill">Page {page} of {total_pages}</span>')
            if page < total_pages:
                pager_links.append(
                    f'<a class="button-link" href="{build_home_link(q=q, country=country, category=category, item_id=selected_id, page=page + 1)}">Next</a>'
                )
            pager_markup = f'<div class="pager">{"".join(pager_links)}</div>'

    browse_panel = f"""
    <section class="panel detail section-frame" style="margin-bottom:24px;">
      <div class="section-copy">{browse_header}</div>
      <div class="browse-grid">{browse_markup}</div>
      {pager_markup}
    </section>
    """

    if selected_item is None:
        detail_markup = (
            '<section class="panel detail"><div class="empty">'
            "<h2>No item selected</h2><p>Choose a country, then a mail type, then pick an item to inspect.</p>"
            "</div></section>"
        )
    else:
        location_parts = parse_location_parts(selected_item.title, selected_item.origin)
        visible_tag_names = sorted({tag.name for tag in selected_item.tags if tag.name != "returned"})
        tag_pills = "".join(
            f'<span class="pill">{escape(tag_name)}</span>' for tag_name in visible_tag_names
        )
        if selected_item.is_returned:
            tag_pills += '<span class="pill">returned</span>'
        if selected_item.is_self_mail:
            tag_pills += '<span class="pill">self mail</span>'

        meta_cards = [
            ("Country", selected_item.country),
            ("Category", selected_item.category),
            ("Location", location_parts["location"]),
            ("City", location_parts["city"]),
            ("Region", location_parts["region"]),
            ("Location Country", location_parts["country"]),
            ("Tracking", selected_item.tracking_number or "None"),
            ("Archive ID", selected_item.archive_id),
            (
                "Source",
                display_relpath(selected_item.source_relpath) if selected_item.source_relpath else "Unknown",
            ),
        ]
        meta_markup = "".join(
            f'<article class="meta-card"><div class="meta-label">{escape(label)}</div>'
            f'<div class="meta-value">{escape(value)}</div></article>'
            for label, value in meta_cards
        )

        assets_markup = "".join(
            render_asset_card(asset.path, asset.kind) for asset in selected_item.assets
        ) or '<div class="empty">No assets yet.</div>'

        events_markup = "".join(
            f'<article class="event">'
            f'<div class="event-time">{escape(event.occurred_at.isoformat(sep=" ", timespec="minutes"))}</div>'
            f'<div><strong>{escape(event.status)}</strong></div>'
            f'<div>{escape(event.location or "Unknown location")}</div>'
            f'{f"<div>{escape(event.details)}</div>" if event.details else ""}'
            f"</article>"
            for event in selected_item.tracking_events
        ) or '<div class="empty">No tracking events yet.</div>'

        notes_text = selected_item.notes or "No notes yet."
        if selected_item.source_relpath:
            notes_text = notes_text.replace(
                selected_item.source_relpath, display_relpath(selected_item.source_relpath)
            )
        notes_markup = escape(notes_text).replace("\n", "<br />")

        detail_markup = f"""
        <section class="panel detail">
          <div class="detail-head">
            <div>
              <div class="eyebrow">{escape(selected_item.country)} Collection</div>
              <h2 class="detail-title{' returned' if selected_item.is_returned else ''}">{escape(display_title(selected_item.title))}</h2>
              <div class="subtitle">A curated reading view for scanned covers, postal markings, route fragments, and imported catalog notes.</div>
            </div>
            <div>
              <div class="pill-row" style="justify-content:flex-end; margin-bottom:10px;">{tag_pills or '<span class="pill">untagged</span>'}</div>
              <a class="button-link" href="/admin/items/{selected_item.id}">Open Admin Console</a>
            </div>
          </div>

          <div class="detail-columns">
            <div>
              <div class="meta-grid">{meta_markup}</div>

              <section class="section">
                <h2>Assets</h2>
                <div class="asset-grid">{assets_markup}</div>
              </section>
            </div>

            <div class="stack">
              <section class="section" style="margin-top:0;">
                <h2>Notes</h2>
                <div class="meta-card note-card"><div class="meta-value">{notes_markup}</div></div>
              </section>

              <section class="section" style="margin-top:0;">
                <h2>Tracking Timeline</h2>
                <div class="timeline">{events_markup}</div>
              </section>
            </div>
          </div>
        </section>
        """

    country_options = '<option value="">All countries</option>' + "".join(
        f'<option value="{escape(value)}"{" selected" if value == country else ""}>{escape(value)}</option>'
        for value in countries
    )
    category_options = '<option value="">All categories</option>' + "".join(
        f'<option value="{escape(value)}"{" selected" if value == category else ""}>{escape(value)}</option>'
        for value in categories
    )

    body = f"""
    <div class="shell">
      <aside class="sidebar">
        <div class="eyebrow">Philatelic Catalog</div>
        <h1>Archive Browser</h1>
        <p class="subtitle">A quieter way to browse your postal archive, with country-led navigation, scanning context, and catalog notes kept in one place.</p>

        <div class="micro-stat-grid">
          <div class="micro-stat">
            <strong>{total_items}</strong>
            <div class="item-sub">catalogued items</div>
          </div>
          <div class="micro-stat">
            <strong>{len(countries)}</strong>
            <div class="item-sub">countries / regions</div>
          </div>
        </div>

        <div class="sidebar-block">
        <section class="panel filters">
          <div class="sidebar-heading">
            <div class="meta-label">Find Something</div>
          </div>
          <form method="get" action="/">
            <label>
              Search
              <input type="search" name="q" value="{escape(q)}" placeholder="tracking, title, location" />
            </label>
            <label>
              Country
              <select name="country">{country_options}</select>
            </label>
            <label>
              Category
              <select name="category">{category_options}</select>
            </label>
            <div>
              <button type="submit">Apply Filters</button>
              <a class="reset" href="/">Reset</a>
            </div>
          </form>
          <div style="margin-top:12px;">
            <a class="button-link" href="/import">Open Importer</a>
          </div>
        </section>
        </div>

        <hr class="sidebar-divider" />
        <div class="list-meta">
          <span>Browse tree</span>
          <span>{country or "All regions"}</span>
        </div>
        <section class="panel filters sidebar-block">
          <div class="meta-label" style="margin-bottom:10px;">Countries</div>
          <div class="country-list">{country_links}</div>
        </section>
        {f'<section class="panel filters sidebar-block"><div class="meta-label" style="margin-bottom:10px;">Mail Types</div><div class="category-list">{category_links}</div></section>' if country else ""}
      </aside>

      <main class="main">
        <section class="panel masthead">
          <div class="masthead-grid">
            <div class="hero-note">
              <div class="eyebrow">Reading Room</div>
              <h2>Browse by geography first, then drill into format, route, and markings.</h2>
              <p class="subtitle">This view is designed to feel less like a raw database and more like a curator's desk: broad structure on the left, focused reading on the right.</p>
            </div>
            <div class="hero-stats">
              <div class="hero-stat">
                <div class="meta-label">Current Scope</div>
                <div class="hero-stat-value">{escape(country or "All regions")}</div>
                <div class="hero-stat-label">{escape(category or "Choose a mail type to narrow further.")}</div>
              </div>
              <div class="hero-stat">
                <div class="meta-label">Selection</div>
                <div class="hero-stat-value">{total_items}</div>
                <div class="hero-stat-label">items in the current filtered set</div>
              </div>
            </div>
          </div>
        </section>

        {browse_panel}
        {detail_markup}
      </main>
    </div>
    """
    return render_page("Philatelic Catalog", body)


def render_admin(item: Item, saved: bool = False) -> str:
    tag_value = ", ".join(sorted({tag.name for tag in item.tags}))
    flash = '<div class="flash">Saved.</div>' if saved else ""
    recent_events = sorted(item.tracking_events, key=lambda event: event.occurred_at, reverse=True)[:12]
    event_cards = "".join(
        f'<article class="event"><div class="event-time">{escape(event.occurred_at.isoformat(sep=" ", timespec="minutes"))}</div>'
        f'<div><strong>{escape(event.status)}</strong></div>'
        f'<div>{escape(event.location or "Unknown location")}</div>'
        f'{f"<div>{escape(event.details)}</div>" if event.details else ""}</article>'
        for event in recent_events
    ) or '<div class="empty">No tracking events yet.</div>'

    body = f"""
    <main class="main" style="max-width: 1360px; margin: 0 auto;">
      <section class="panel masthead" style="margin-bottom:24px;">
        <div class="masthead-grid">
          <div class="hero-note">
            <div class="eyebrow">Philatelic Catalog</div>
            <h1>Admin Console</h1>
            <p class="subtitle">Fine-tune metadata, normalize parsed fields, and add manual tracking events for <strong>{escape(display_title(item.title))}</strong>.</p>
          </div>
          <div class="hero-stats">
            <div class="hero-stat">
              <div class="meta-label">Tracking Number</div>
              <div class="hero-stat-value">{escape(item.tracking_number or "N/A")}</div>
              <div class="hero-stat-label">{escape(item.country)} / {escape(item.category)}</div>
            </div>
            <div class="hero-stat">
              <div class="meta-label">Archive ID</div>
              <div class="hero-stat-value">{escape(item.archive_id)}</div>
              <div class="hero-stat-label">Manual edits are saved directly into the catalog database.</div>
            </div>
          </div>
        </div>
      </section>
      {flash}
      <div class="admin-grid">
        <section class="panel admin-form">
          <div class="section-copy">
            <div class="eyebrow">Metadata</div>
            <h2>Item Record</h2>
            <p class="subtitle">Use this side to clean display title, location, tags, and curator notes without touching the original source folder.</p>
          </div>
          <form method="post" action="/admin/items/{item.id}">
            <label>Title<input type="text" name="title" value="{escape(item.title)}" /></label>
            <label>Tracking Number<input type="text" name="tracking_number" value="{escape(item.tracking_number or '')}" /></label>
            <label>Location<input type="text" name="origin" value="{escape(item.origin or '')}" placeholder="N/A" /></label>
            <label>Country<input type="text" name="country" value="{escape(item.country)}" /></label>
            <label>Category<input type="text" name="category" value="{escape(item.category)}" /></label>
            <label>Tags
              <input type="text" name="tags" value="{escape(tag_value)}" placeholder="returned, self-mail, commemorative" />
            </label>
            <label>Notes<textarea name="notes">{escape(item.notes or '')}</textarea></label>
            <label class="check-row"><input type="checkbox" name="is_returned" {"checked" if item.is_returned else ""} /> Returned</label>
            <label class="check-row"><input type="checkbox" name="is_self_mail" {"checked" if item.is_self_mail else ""} /> Self mail</label>
            <div>
              <button type="submit">Save Metadata</button>
              <a class="reset" href="/?item={item.id}">Back to Browser</a>
            </div>
          </form>
        </section>

        <section class="panel admin-form">
          <div class="section-copy">
            <div class="eyebrow">Timeline</div>
            <h2>Add Tracking Event</h2>
            <p class="subtitle">When importer output is incomplete, this panel lets you patch the route history by hand.</p>
          </div>
          <form method="post" action="/admin/items/{item.id}">
            <input type="hidden" name="form_kind" value="tracking_event" />
            <label>Occurred At<input type="text" name="event_occurred_at" placeholder="2025-04-11 09:31" /></label>
            <label>Location<input type="text" name="event_location" placeholder="Shanghai" /></label>
            <label>Status<input type="text" name="event_status" placeholder="Delivered" /></label>
            <label>Details<textarea name="event_details"></textarea></label>
            <div><button type="submit">Add Event</button></div>
          </form>

          <section class="section">
            <h2>Recent Timeline Entries</h2>
            <div class="timeline">{event_cards}</div>
          </section>
        </section>
      </div>
    </main>
    """
    return render_page("Philatelic Catalog Admin", body)


def render_importer(
    *,
    source_paths: str,
    limit: str,
    summary: ImportSummary | None = None,
    previews: list[ImportPreviewRow] | None = None,
    error: str | None = None,
    executed_mode: str | None = None,
    job_id: str | None = None,
    job: dict[str, object] | None = None,
) -> str:
    message = ""
    if error:
        message = f'<div class="flash error">{escape(error)}</div>'
    elif summary is not None:
        headline = "Dry run complete." if summary.dry_run else "Import complete."
        message = f'<div class="flash">{headline}</div>'
    elif job_id and job:
        state = str(job.get("state", "queued"))
        if state == "completed":
            state_label = "Import complete."
        elif state == "failed":
            state_label = "Import failed."
        elif state == "queued":
            state_label = "Import queued."
        else:
            state_label = "Import in progress."
        message = f'<div class="flash">{state_label}</div>'

    summary_markup = ""
    if summary is not None:
        summary_cards = [
            ("Scanned", str(summary.scanned)),
            ("Imported", str(summary.imported)),
            ("Updated", str(summary.updated)),
            ("Copied Assets", str(summary.copied_assets)),
            ("Tracking Events", str(summary.tracking_events)),
        ]
        summary_markup = (
            '<section class="section">'
            '<h2>Latest Run</h2>'
            '<div class="summary-grid">'
            + "".join(
                f'<article class="meta-card"><div class="meta-label">{escape(label)}</div>'
                f'<div class="meta-value">{escape(value)}</div></article>'
                for label, value in summary_cards
            )
            + "</div>"
            + f'<div class="meta-card"><div class="meta-value">Mode: {escape(executed_mode or ("preview" if summary.dry_run else "import"))}</div></div>'
            + "</section>"
        )
    elif job and isinstance(job.get("summary"), dict):
        snapshot = job["summary"]
        summary_cards = [
            ("Scanned", str(snapshot.get("scanned", 0))),
            ("Imported", str(snapshot.get("imported", 0))),
            ("Updated", str(snapshot.get("updated", 0))),
            ("Copied Assets", str(snapshot.get("copied_assets", 0))),
            ("Tracking Events", str(snapshot.get("tracking_events", 0))),
        ]
        summary_markup = (
            '<section class="section">'
            '<h2>Latest Run</h2>'
            '<div class="summary-grid">'
            + "".join(
                f'<article class="meta-card"><div class="meta-label">{escape(label)}</div>'
                f'<div class="meta-value">{escape(value)}</div></article>'
                for label, value in summary_cards
            )
            + "</div>"
            + '<div class="meta-card"><div class="meta-value">Mode: import</div></div>'
            + "</section>"
        )

    progress_markup = ""
    script_markup = ""
    if job_id and job:
        state = str(job.get("state", "queued"))
        completed = int(job.get("completed", 0) or 0)
        total = int(job.get("total", 0) or 0)
        current_item = str(job.get("current_item", "") or "")
        percent = 0 if total <= 0 else int((completed / total) * 100)
        progress_text = current_item or (
            "Import complete." if state == "completed" else "Import failed." if state == "failed" else "Waiting to start..."
        )
        progress_heading = "Live Progress" if state not in {"completed", "failed"} else "Run Status"
        progress_markup = f"""
        <section class="section progress-shell">
          <h2>{progress_heading}</h2>
          <div class="meta-card">
            <div class="meta-label">State</div>
            <div class="meta-value" id="import-state">{escape(state.title())}</div>
            <div class="progress-bar"><div class="progress-fill" id="import-progress" style="width:{percent}%;"></div></div>
            <div class="item-sub" id="import-progress-text">{completed} / {total or '?'}</div>
            <div class="item-sub" id="import-current-item">{escape(progress_text)}</div>
          </div>
        </section>
        """
        if state not in {"completed", "failed"}:
            script_markup = f"""
        <script>
        const importJobId = {job_id!r};
        async function pollImportJob() {{
          const response = await fetch(`/import/jobs/${{importJobId}}`);
          if (!response.ok) return;
          const payload = await response.json();
          const total = payload.total || 0;
          const completed = payload.completed || 0;
          const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
          document.getElementById("import-state").textContent = (payload.state || "queued").replace(/^./, c => c.toUpperCase());
          document.getElementById("import-progress").style.width = `${{percent}}%`;
          document.getElementById("import-progress-text").textContent = `${{completed}} / ${{total || "?"}}`;
          document.getElementById("import-current-item").textContent = payload.current_item || "Waiting to start...";
          if (payload.state === "completed" || payload.state === "failed") {{
            window.location.href = `/import?job_id=${{importJobId}}`;
            return;
          }}
          window.setTimeout(pollImportJob, 800);
        }}
        window.setTimeout(pollImportJob, 300);
        </script>
        """

    preview_markup = ""
    if previews:
        preview_markup = (
            '<section class="section"><h2>Dry Run Items</h2><div class="preview-list">'
            + "".join(
                f'<article class="preview-card">'
                f'<div class="item-country">{escape(row.country)} / {escape(row.category)}</div>'
                f'<div class="item-title">{escape(display_title(row.title))}</div>'
                f'<div class="item-sub">{escape(row.tracking_number or "No tracking number")}</div>'
                f'<div class="item-sub">Location: {escape(row.location or "N/A")}</div>'
                f'<div class="item-sub">Action: {escape(row.action)} | Assets: {row.asset_count} | Tracking events: {row.tracking_event_count}</div>'
                f'<div class="item-sub">{escape(display_relpath(row.source_relpath))}</div>'
                f'</article>'
                for row in previews
            )
            + "</div></section>"
        )

    body = f"""
    <main class="main" style="max-width: 1200px; margin: 0 auto;">
      <section class="panel masthead" style="margin-bottom:24px;">
        <div class="masthead-grid">
          <div class="hero-note">
            <div class="eyebrow">Philatelic Catalog</div>
            <h1>Batch Importer</h1>
            <p class="subtitle">Bring in folders carefully: preview the structure, inspect what will be added, then import into the managed archive with a progress view.</p>
          </div>
          <div class="hero-stats">
            <div class="hero-stat">
              <div class="meta-label">Suggested Source</div>
              <div class="hero-stat-value">Letters</div>
              <div class="hero-stat-label">The importer understands the country / category / item folder layout you already use.</div>
            </div>
            <div class="hero-stat">
              <div class="meta-label">Safety Model</div>
              <div class="hero-stat-value">Preview First</div>
              <div class="hero-stat-label">Dry runs inspect metadata without touching SQLite or the managed archive.</div>
            </div>
          </div>
        </div>
      </section>
      {message}
      {progress_markup}
      {summary_markup}
      {preview_markup}
      <div class="admin-grid">
        <section class="panel admin-form">
          <div class="section-copy">
            <div class="eyebrow">Filesystem Intake</div>
            <h2>Import Queue</h2>
            <p class="subtitle">Paste one or more folders from disk. This is best for the existing archive root or when you want deterministic source paths.</p>
          </div>
          <form method="post" action="/import">
            <label>Source Folders
              <textarea name="source_paths" placeholder="/Volumes/Frank Ruan Database/MediaLibrary/Letters">{escape(source_paths)}</textarea>
            </label>
            <label>Limit
              <input type="text" name="limit" value="{escape(limit)}" placeholder="Optional item cap for this run" />
            </label>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <button type="submit" name="mode" value="preview">Preview Import</button>
              <button type="submit" name="mode" value="import">Run Import</button>
              <a class="button-link" href="/">Back to Browser</a>
            </div>
          </form>
        </section>

        <section class="panel admin-form">
          <div class="section-copy">
            <div class="eyebrow">Browser Intake</div>
            <h2>Upload Folder</h2>
            <p class="subtitle">Send a local folder directly from the browser when the source is not already reachable on disk from this machine context.</p>
          </div>
          <form id="upload-form" method="post" action="/import/upload" enctype="multipart/form-data">
            <label>Choose Folder
              <input id="upload-files" type="file" name="files" webkitdirectory directory multiple />
            </label>
            <label>Limit
              <input id="upload-limit" type="text" name="limit" value="{escape(limit)}" placeholder="Optional item cap for this upload" />
            </label>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <button type="button" onclick="submitUploadForm('preview')">Preview Upload</button>
              <button type="button" onclick="submitUploadForm('import')">Upload and Import</button>
            </div>
          </form>
          <div class="uploader-status">
            <div class="meta-card">
              <div class="meta-label">Selected Folder</div>
              <div class="meta-value" id="upload-root">No folder selected</div>
              <div class="item-sub" id="upload-count">0 files selected</div>
            </div>
          </div>

          <section class="section" id="upload-progress-shell" style="display:none;">
            <h2>Upload Progress</h2>
            <div class="meta-card">
              <div class="meta-label">Transfer</div>
              <div class="progress-bar"><div class="progress-fill" id="upload-progress" style="width:0%;"></div></div>
              <div class="item-sub" id="upload-progress-text">0%</div>
              <div class="item-sub" id="upload-progress-detail">Waiting to upload...</div>
            </div>
          </section>

          <section class="section">
          <h2>How It Works</h2>
          <ul class="hint-list">
            <li>One folder per line. You can paste the whole `Letters` root, a country folder, a category folder, or a single item folder.</li>
            <li>`Preview Import` parses everything without changing SQLite or copying files.</li>
            <li>`Run Import` copies assets into `managed_archive` and merges metadata into the catalog.</li>
            <li>Duplicate folders in the queue are ignored automatically for the same run.</li>
            <li>`Upload Folder` lets you send a local folder straight from the browser and reuses the same preview/import pipeline.</li>
          </ul>

          <section class="section">
            <h2>Suggested Starting Point</h2>
            <div class="meta-card">
              <div class="meta-label">Archive Root</div>
              <div class="meta-value">/Volumes/Frank Ruan Database/MediaLibrary/Letters</div>
            </div>
          </section>
          </section>
        </section>
      </div>
      {script_markup}
      <script>
      function updateUploadSelectionSummary() {{
        const input = document.getElementById("upload-files");
        const root = document.getElementById("upload-root");
        const count = document.getElementById("upload-count");
        if (!input.files || input.files.length === 0) {{
          root.textContent = "No folder selected";
          count.textContent = "0 files selected";
          return;
        }}
        const firstPath = input.files[0].webkitRelativePath || input.files[0].name;
        const rootName = firstPath.split("/")[0] || "Uploaded folder";
        root.textContent = rootName;
        count.textContent = input.files.length + " file" + (input.files.length === 1 ? "" : "s") + " selected";
      }}

      function setUploadProgress(percent, detail) {{
        document.getElementById("upload-progress-shell").style.display = "block";
        document.getElementById("upload-progress").style.width = percent + "%";
        document.getElementById("upload-progress-text").textContent = percent + "%";
        document.getElementById("upload-progress-detail").textContent = detail;
      }}

      async function submitUploadForm(mode) {{
        const input = document.getElementById("upload-files");
        const limit = document.getElementById("upload-limit").value;
        if (!input.files || input.files.length === 0) {{
          window.alert("Choose a folder before uploading.");
          return;
        }}
        const formData = new FormData();
        formData.append("mode", mode);
        formData.append("limit", limit);
        for (const file of input.files) {{
          formData.append("files", file, file.webkitRelativePath || file.name);
        }}
        setUploadProgress(0, "Preparing upload...");
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/import/upload");
        xhr.upload.onprogress = (event) => {{
          if (!event.lengthComputable) {{
            setUploadProgress(0, "Uploading files...");
            return;
          }}
          const percent = Math.max(1, Math.min(100, Math.round((event.loaded / event.total) * 100)));
          setUploadProgress(percent, "Uploaded " + event.loaded.toLocaleString() + " / " + event.total.toLocaleString() + " bytes");
        }};
        xhr.onload = () => {{
          setUploadProgress(100, "Upload complete. Loading importer results...");
          document.open();
          document.write(xhr.responseText);
          document.close();
        }};
        xhr.onerror = () => {{
          setUploadProgress(0, "Upload failed.");
          window.alert("Upload failed. Please try again.");
        }};
        xhr.send(formData);
      }}
      document.getElementById("upload-files")?.addEventListener("change", updateUploadSelectionSummary);
      </script>
    </main>
    """
    return render_page("Philatelic Catalog Importer", body)


@ui_router.get("/", response_class=HTMLResponse)
def home(
    item: int | None = None,
    q: str = "",
    country: str = "",
    category: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    q_only_items = list(
        session.scalars(
            build_item_query(
                q=q or None,
            )
        ).all()
    )
    country_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for candidate in q_only_items:
        country_counts[candidate.country] = country_counts.get(candidate.country, 0) + 1
        if not country or candidate.country == country:
            category_counts[candidate.category] = category_counts.get(candidate.category, 0) + 1

    all_items = list(
        session.scalars(
            build_item_query(
                country=country or None,
                category=category or None,
                q=q or None,
            )
        ).all()
    )

    total_items = len(all_items)
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    page_start = (page - 1) * PAGE_SIZE
    items = all_items[page_start: page_start + PAGE_SIZE]

    selected_item = None
    if category:
        if item is not None:
            selected_item = next((candidate for candidate in all_items if candidate.id == item), None)
        if selected_item is None and items:
            selected_item = items[0]

    countries = sorted(country_counts)
    categories = sorted(category_counts)
    return HTMLResponse(
        render_home(
            items,
            selected_item,
            countries,
            categories,
            country_counts,
            category_counts,
            q,
            country,
            category,
            page,
            total_items,
            total_pages,
        )
    )


@ui_router.get("/admin/items/{item_id}", response_class=HTMLResponse)
def admin_item(item_id: int, saved: int = 0, session: Session = Depends(get_session)) -> HTMLResponse:
    item = session.scalar(
        select(Item)
        .where(Item.id == item_id)
        .options(selectinload(Item.tags), selectinload(Item.tracking_events))
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return HTMLResponse(render_admin(item, saved=bool(saved)))


@ui_router.get("/import", response_class=HTMLResponse)
def importer_page(job_id: str | None = None) -> HTMLResponse:
    job = snapshot_job(job_id) if job_id else None
    summary = None
    if job and isinstance(job.get("summary"), dict):
        payload = job["summary"]
        summary = ImportSummary(
            scanned=int(payload.get("scanned", 0)),
            imported=int(payload.get("imported", 0)),
            updated=int(payload.get("updated", 0)),
            copied_assets=int(payload.get("copied_assets", 0)),
            tracking_events=int(payload.get("tracking_events", 0)),
            dry_run=bool(payload.get("dry_run", False)),
        )
    return HTMLResponse(
        render_importer(
            source_paths="/Volumes/Frank Ruan Database/MediaLibrary/Letters",
            limit="",
            summary=summary,
            previews=None,
            error=str(job.get("error")) if job and job.get("error") else None,
            executed_mode=None,
            job_id=job_id,
            job=job,
        )
    )


@ui_router.get("/import/jobs/{job_id}", response_class=JSONResponse)
def importer_job_status(job_id: str) -> JSONResponse:
    job = snapshot_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return JSONResponse(job)


@ui_router.post("/import/upload", response_class=HTMLResponse)
async def importer_upload(request: Request, session: Session = Depends(get_session)) -> Response:
    try:
        upload_root, file_count, mode, limit_raw = await extract_uploaded_tree(request)
        limit = parse_limit_input(limit_raw)
        source_label = f"[Uploaded {file_count} files]"
        if mode == "import":
            job_id = start_import_job([upload_root], limit)
            return RedirectResponse(url=f"/import?job_id={job_id}", status_code=303)

        summary, previews = describe_import_letter_sources(
            session,
            [upload_root],
            settings.managed_archive_root,
            limit=limit,
        )
        return HTMLResponse(
            render_importer(
                source_paths=source_label,
                limit=limit_raw,
                summary=summary,
                previews=previews,
                error=None,
                executed_mode="upload-preview",
                job_id=None,
                job=None,
            )
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Upload could not run."
        return HTMLResponse(
            render_importer(
                source_paths="",
                limit="",
                summary=None,
                previews=None,
                error=detail,
                executed_mode="upload",
                job_id=None,
                job=None,
            ),
            status_code=exc.status_code,
        )
    except Exception as exc:
        return HTMLResponse(
            render_importer(
                source_paths="",
                limit="",
                summary=None,
                previews=None,
                error=str(exc),
                executed_mode="upload",
                job_id=None,
                job=None,
            ),
            status_code=500,
        )


@ui_router.post("/import", response_class=HTMLResponse)
async def importer_run(
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body, keep_blank_values=True)
    source_paths_raw = get_form_value(form_data, "source_paths")
    limit_raw = get_form_value(form_data, "limit")
    mode = get_form_value(form_data, "mode", "preview")

    try:
        source_paths = parse_source_paths_input(source_paths_raw)
        limit = parse_limit_input(limit_raw)
        if mode == "import":
            job_id = start_import_job(source_paths, limit)
            return RedirectResponse(url=f"/import?job_id={job_id}", status_code=303)

        summary, previews = describe_import_letter_sources(
            session,
            source_paths,
            settings.managed_archive_root,
            limit=limit,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Importer could not run."
        return HTMLResponse(
            render_importer(
                source_paths=source_paths_raw,
                limit=limit_raw,
                summary=None,
                previews=None,
                error=detail,
                executed_mode=mode,
                job_id=None,
                job=None,
            ),
            status_code=exc.status_code,
        )
    except Exception as exc:
        return HTMLResponse(
            render_importer(
                source_paths=source_paths_raw,
                limit=limit_raw,
                summary=None,
                previews=None,
                error=str(exc),
                executed_mode=mode,
                job_id=None,
                job=None,
            ),
            status_code=500,
        )

    return HTMLResponse(
        render_importer(
            source_paths=source_paths_raw,
            limit=limit_raw,
            summary=summary,
            previews=previews,
            error=None,
            executed_mode=mode,
            job_id=None,
            job=None,
        )
    )


@ui_router.post("/admin/items/{item_id}")
async def admin_item_save(
    item_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    item = get_item_or_404(session, item_id)
    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body, keep_blank_values=True)
    form_kind = get_form_value(form_data, "form_kind", "metadata")

    if form_kind == "tracking_event":
        event_occurred_at = get_form_value(form_data, "event_occurred_at")
        event_location = get_form_value(form_data, "event_location")
        event_status = get_form_value(form_data, "event_status")
        event_details = get_form_value(form_data, "event_details")
        if event_occurred_at.strip() and event_status.strip():
            occurred_at = parse_datetime_input(event_occurred_at)
            session.add(
                TrackingEvent(
                    item_id=item.id,
                    occurred_at=occurred_at,
                    location=event_location.strip() or None,
                    status=event_status.strip(),
                    details=event_details.strip() or None,
                    source="manual",
                )
            )
    else:
        title = get_form_value(form_data, "title")
        tracking_number = get_form_value(form_data, "tracking_number")
        origin = get_form_value(form_data, "origin")
        country = get_form_value(form_data, "country")
        category = get_form_value(form_data, "category")
        tags = get_form_value(form_data, "tags")
        notes = get_form_value(form_data, "notes")
        item.title = title.strip() or item.title
        item.tracking_number = tracking_number.strip() or None
        item.origin = origin.strip() or None
        item.country = country.strip() or item.country
        item.category = category.strip() or item.category
        item.notes = notes
        item.is_returned = "is_returned" in form_data
        item.is_self_mail = "is_self_mail" in form_data
        item.tags.clear()
        for tag_name in parse_tag_input(tags):
            item.tags.append(get_or_create_tag(session, tag_name))

    session.add(item)
    session.commit()
    return RedirectResponse(url=f"/admin/items/{item.id}?saved=1", status_code=303)


@ui_router.get("/asset-preview", response_class=FileResponse)
def asset_preview(path: str = Query(...), session: Session = Depends(get_session)) -> FileResponse:
    asset = session.scalar(select(Asset).where(Asset.path == path))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    source_path = resolve_archive_path(asset.path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Archive file not found")

    suffix = source_path.suffix.lower()
    if suffix not in HEIF_SUFFIXES:
        return FileResponse(source_path)

    settings.preview_cache_root.mkdir(parents=True, exist_ok=True)
    preview_path = settings.preview_cache_root / f"{source_path.stem}.jpg"
    if not preview_path.exists() or preview_path.stat().st_mtime < source_path.stat().st_mtime:
        result = subprocess.run(
            ["sips", "-s", "format", "jpeg", str(source_path), "--out", str(preview_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not preview_path.exists():
            raise HTTPException(status_code=500, detail="Preview generation failed")

    return FileResponse(preview_path, media_type="image/jpeg")
