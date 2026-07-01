from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db.database import get_session
from app.models import Asset, Item, Tag, TrackingEvent
from app.services.importers import ImportSummary, import_letter_sources
from app.services.items import build_item_query

ui_router = APIRouter(include_in_schema=False)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heif", ".heic", ".avif", ".tiff"}
HEIF_SUFFIXES = {".heif", ".heic"}
DISPLAY_MARKER_RE = re.compile(r"\[[^\]]+\]")
PAGE_SIZE = 12


def render_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <style>
      :root {{
        --paper: #f6f1e7;
        --paper-strong: #ece4d4;
        --ink: #201b16;
        --muted: #736455;
        --line: #d5c8b4;
        --accent: #9c4f2d;
        --accent-soft: #e5b98e;
        --card: rgba(255,255,255,0.55);
        --shadow: 0 18px 45px rgba(55, 39, 24, 0.10);
      }}

      * {{ box-sizing: border-box; }}

      body {{
        margin: 0;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(156, 79, 45, 0.12), transparent 28%),
          radial-gradient(circle at bottom right, rgba(114, 96, 67, 0.12), transparent 32%),
          linear-gradient(180deg, #f8f5ee 0%, #efe7d9 100%);
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      }}

      a {{ color: inherit; text-decoration: none; }}

      .shell {{
        min-height: 100vh;
        display: grid;
        grid-template-columns: 360px 1fr;
      }}

      .sidebar {{
        border-right: 1px solid var(--line);
        background: rgba(250, 246, 239, 0.92);
        backdrop-filter: blur(12px);
        padding: 28px 24px;
        position: sticky;
        top: 0;
        height: 100vh;
        overflow: auto;
      }}

      .main {{
        padding: 28px;
      }}

      .eyebrow {{
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--accent);
        font-size: 12px;
        margin-bottom: 10px;
      }}

      h1 {{
        margin: 0 0 8px;
        font-size: 34px;
        line-height: 1;
      }}

      .subtitle {{
        margin: 0 0 24px;
        color: var(--muted);
        line-height: 1.5;
      }}

      .panel {{
        background: var(--card);
        border: 1px solid rgba(213, 200, 180, 0.9);
        border-radius: 22px;
        box-shadow: var(--shadow);
      }}

      .filters {{
        padding: 18px;
        margin-bottom: 18px;
      }}

      .filters form {{
        display: grid;
        gap: 12px;
      }}

      .filters label {{
        display: grid;
        gap: 6px;
        font-size: 13px;
        color: var(--muted);
      }}

      input, select {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: rgba(255,255,255,0.85);
        padding: 10px 12px;
        font: inherit;
        color: var(--ink);
      }}

      input[type="checkbox"] {{
        width: auto;
        margin-right: 8px;
      }}

      button {{
        border: 0;
        border-radius: 999px;
        padding: 11px 16px;
        background: var(--accent);
        color: white;
        font: inherit;
        cursor: pointer;
      }}

      .reset {{
        display: inline-block;
        margin-left: 10px;
        color: var(--muted);
        font-size: 14px;
      }}

      .list-meta {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin: 10px 2px 12px;
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
        padding: 14px 16px;
        border-radius: 18px;
        border: 1px solid rgba(213, 200, 180, 0.7);
        background: rgba(255,255,255,0.58);
      }}

      .nav-link.active,
      .browse-card.active {{
        border-color: var(--accent-soft);
        box-shadow: inset 0 0 0 1px rgba(156, 79, 45, 0.12);
        background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(239,231,217,0.95));
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
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 6px;
      }}

      .item-title {{
        font-size: 18px;
        margin-bottom: 6px;
      }}

      .item-sub {{
        color: var(--muted);
        font-size: 14px;
      }}

      .browse-grid {{
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      }}

      .count-pill {{
        display: inline-block;
        margin-top: 8px;
        padding: 5px 10px;
        border-radius: 999px;
        background: rgba(156, 79, 45, 0.08);
        color: var(--accent);
        font-size: 12px;
      }}

      .pager {{
        grid-auto-flow: column;
        justify-content: start;
        margin-top: 18px;
      }}

      .item-title.returned,
      .detail-title.returned {{
        color: #c27f78;
      }}

      .detail {{
        padding: 26px;
      }}

      .detail-head {{
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: start;
        margin-bottom: 22px;
      }}

      .detail-title {{
        font-size: 40px;
        line-height: 1.05;
        margin: 0 0 8px;
      }}

      .pill-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}

      .pill {{
        padding: 7px 11px;
        border-radius: 999px;
        background: rgba(156, 79, 45, 0.08);
        color: var(--accent);
        font-size: 13px;
      }}

      .inline-meta {{
        margin-top: 10px;
        padding: 10px 12px;
        border-radius: 14px;
        background: rgba(255,255,255,0.62);
        border: 1px solid rgba(213, 200, 180, 0.7);
      }}

      .inline-meta .meta-label {{
        margin-bottom: 4px;
      }}

      .button-link {{
        display: inline-block;
        border-radius: 999px;
        padding: 11px 16px;
        background: rgba(156, 79, 45, 0.10);
        color: var(--accent);
        font-size: 14px;
      }}

      .meta-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 24px;
      }}

      .meta-card {{
        padding: 16px;
        border-radius: 18px;
        background: rgba(255,255,255,0.6);
        border: 1px solid rgba(213, 200, 180, 0.7);
      }}

      .meta-label {{
        color: var(--muted);
        font-size: 12px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin-bottom: 8px;
      }}

      .meta-value {{
        font-size: 18px;
        line-height: 1.35;
        word-break: break-word;
      }}

      .section {{
        margin-top: 24px;
      }}

      .section h2 {{
        margin: 0 0 12px;
        font-size: 20px;
      }}

      .asset-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
      }}

      .asset-card {{
        padding: 14px;
        border-radius: 20px;
        background: rgba(255,255,255,0.62);
        border: 1px solid rgba(213, 200, 180, 0.7);
      }}

      .asset-card img {{
        width: 100%;
        height: 240px;
        object-fit: cover;
        border-radius: 14px;
        display: block;
        margin-bottom: 10px;
        background: var(--paper-strong);
      }}

      .asset-kind {{
        color: var(--accent);
        font-size: 12px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin-bottom: 5px;
      }}

      .asset-path {{
        color: var(--muted);
        font-size: 13px;
        word-break: break-all;
      }}

      .timeline {{
        display: grid;
        gap: 12px;
      }}

      .event {{
        padding: 14px 16px;
        border-left: 4px solid var(--accent-soft);
        border-radius: 0 18px 18px 0;
        background: rgba(255,255,255,0.6);
      }}

      .event-time {{
        color: var(--muted);
        font-size: 13px;
        margin-bottom: 5px;
      }}

      .empty {{
        padding: 34px;
        text-align: center;
        color: var(--muted);
      }}

      textarea {{
        width: 100%;
        min-height: 120px;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: rgba(255,255,255,0.85);
        padding: 10px 12px;
        font: inherit;
        color: var(--ink);
        resize: vertical;
      }}

      .admin-grid {{
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 20px;
      }}

      .admin-form {{
        padding: 18px;
      }}

      .admin-form form {{
        display: grid;
        gap: 12px;
      }}

      .flash {{
        margin-bottom: 16px;
        padding: 12px 14px;
        border-radius: 14px;
        background: rgba(97, 141, 92, 0.12);
        color: #4f6d48;
        border: 1px solid rgba(97, 141, 92, 0.25);
      }}

      .flash.error {{
        background: rgba(156, 79, 45, 0.10);
        color: #8f4325;
        border-color: rgba(156, 79, 45, 0.22);
      }}

      .check-row {{
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--muted);
      }}

      .summary-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 12px;
        margin-bottom: 18px;
      }}

      .hint-list {{
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
        line-height: 1.7;
      }}

      @media (max-width: 980px) {{
        .shell {{
          grid-template-columns: 1fr;
        }}

        .sidebar {{
          position: static;
          height: auto;
          border-right: 0;
          border-bottom: 1px solid var(--line);
        }}

        .meta-grid {{
          grid-template-columns: 1fr;
        }}

        .admin-grid {{
          grid-template-columns: 1fr;
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
            location_text = display_location(item.title, item.origin)
            title_classes = "item-title"
            if item.is_returned:
                title_classes += " returned"
            subtitle_text = item.tracking_number or item.category
            returned_badge = '<span class="count-pill">Returned</span>' if item.is_returned else ""
            item_cards.append(
                f'<a class="browse-card{" active" if item.id == selected_id else ""}" href="{build_home_link(q=q, country=country, category=category, item_id=item.id, page=page)}">'
                f'<div class="{title_classes}">{escape(title_text)}</div>'
                f'<div class="inline-meta"><div class="meta-label">Location</div><div class="item-sub">{escape(location_text)}</div></div>'
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
    <section class="panel detail" style="margin-bottom:24px;">
      {browse_header}
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
            ("Location", display_location(selected_item.title, selected_item.origin)),
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
              <div class="subtitle">A lightweight archive view over your imported philatelic metadata and files.</div>
            </div>
            <div>
              <div class="pill-row" style="justify-content:flex-end; margin-bottom:10px;">{tag_pills or '<span class="pill">untagged</span>'}</div>
              <a class="button-link" href="/admin/items/{selected_item.id}">Open Admin Console</a>
            </div>
          </div>

          <div class="meta-grid">{meta_markup}</div>

          <section class="section">
            <h2>Assets</h2>
            <div class="asset-grid">{assets_markup}</div>
          </section>

          <section class="section">
            <h2>Notes</h2>
            <div class="meta-card"><div class="meta-value">{notes_markup}</div></div>
          </section>

          <section class="section">
            <h2>Tracking Timeline</h2>
            <div class="timeline">{events_markup}</div>
          </section>
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
        <p class="subtitle">A calm, desk-side view of your collection with search, filtering, and image previews.</p>

        <section class="panel filters">
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

        <div class="list-meta">
          <span>{total_items} item{"s" if total_items != 1 else ""}</span>
          <span>{len(countries)} countries</span>
        </div>
        <section class="panel filters">
          <div class="meta-label" style="margin-bottom:10px;">Countries</div>
          <div class="country-list">{country_links}</div>
        </section>
        {f'<section class="panel filters"><div class="meta-label" style="margin-bottom:10px;">Mail Types</div><div class="category-list">{category_links}</div></section>' if country else ""}
      </aside>

      <main class="main">{browse_panel}{detail_markup}</main>
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
      <div class="eyebrow">Philatelic Catalog</div>
      <h1>Admin Console</h1>
      <p class="subtitle">Fine-tune metadata and add manual tracking events for <strong>{escape(display_title(item.title))}</strong>.</p>
      {flash}
      <div class="admin-grid">
        <section class="panel admin-form">
          <h2>Item Metadata</h2>
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
          <h2>Add Tracking Event</h2>
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
    error: str | None = None,
    executed_mode: str | None = None,
) -> str:
    message = ""
    if error:
        message = f'<div class="flash error">{escape(error)}</div>'
    elif summary is not None:
        headline = "Dry run complete." if summary.dry_run else "Import complete."
        message = f'<div class="flash">{headline}</div>'

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

    body = f"""
    <main class="main" style="max-width: 1200px; margin: 0 auto;">
      <div class="eyebrow">Philatelic Catalog</div>
      <h1>Batch Importer</h1>
      <p class="subtitle">Paste one or more folders, preview the scan, then import them into the managed archive.</p>
      {message}
      {summary_markup}
      <div class="admin-grid">
        <section class="panel admin-form">
          <h2>Import Queue</h2>
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
          <h2>How It Works</h2>
          <ul class="hint-list">
            <li>One folder per line. You can paste the whole `Letters` root, a country folder, a category folder, or a single item folder.</li>
            <li>`Preview Import` parses everything without changing SQLite or copying files.</li>
            <li>`Run Import` copies assets into `managed_archive` and merges metadata into the catalog.</li>
            <li>Duplicate folders in the queue are ignored automatically for the same run.</li>
          </ul>

          <section class="section">
            <h2>Suggested Starting Point</h2>
            <div class="meta-card">
              <div class="meta-label">Archive Root</div>
              <div class="meta-value">/Volumes/Frank Ruan Database/MediaLibrary/Letters</div>
            </div>
          </section>
        </section>
      </div>
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
def importer_page() -> HTMLResponse:
    return HTMLResponse(
        render_importer(
            source_paths="/Volumes/Frank Ruan Database/MediaLibrary/Letters",
            limit="",
            summary=None,
            error=None,
            executed_mode=None,
        )
    )


@ui_router.post("/import", response_class=HTMLResponse)
async def importer_run(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body, keep_blank_values=True)
    source_paths_raw = get_form_value(form_data, "source_paths")
    limit_raw = get_form_value(form_data, "limit")
    mode = get_form_value(form_data, "mode", "preview")

    try:
        source_paths = parse_source_paths_input(source_paths_raw)
        limit = parse_limit_input(limit_raw)
        summary = import_letter_sources(
            session,
            source_paths,
            settings.managed_archive_root,
            dry_run=(mode != "import"),
            limit=limit,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Importer could not run."
        return HTMLResponse(
            render_importer(
                source_paths=source_paths_raw,
                limit=limit_raw,
                summary=None,
                error=detail,
                executed_mode=mode,
            ),
            status_code=exc.status_code,
        )
    except Exception as exc:
        return HTMLResponse(
            render_importer(
                source_paths=source_paths_raw,
                limit=limit_raw,
                summary=None,
                error=str(exc),
                executed_mode=mode,
            ),
            status_code=500,
        )

    return HTMLResponse(
        render_importer(
            source_paths=source_paths_raw,
            limit=limit_raw,
            summary=summary,
            error=None,
            executed_mode=mode,
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
