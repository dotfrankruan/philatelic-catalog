from __future__ import annotations

from html import escape
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.models import Asset, Item
from app.services.items import build_item_query

ui_router = APIRouter(include_in_schema=False)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heif", ".heic", ".avif", ".tiff"}
HEIF_SUFFIXES = {".heif", ".heic"}
DISPLAY_MARKER_RE = re.compile(r"^\s*(\[[^\]]+\]\s*)+")


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
      }}
    </style>
  </head>
  <body>{body}</body>
</html>"""


def build_filter_link(item_id: int, q: str, country: str, category: str) -> str:
    params = {"item": item_id}
    if q:
        params["q"] = q
    if country:
        params["country"] = country
    if category:
        params["category"] = category
    return f"/?{urlencode(params)}"


def display_title(raw_title: str) -> str:
    cleaned = DISPLAY_MARKER_RE.sub("", raw_title).strip()
    return cleaned or raw_title


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
    q: str,
    country: str,
    category: str,
) -> str:
    list_sections: list[str] = []
    selected_id = selected_item.id if selected_item else None
    grouped: dict[str, dict[str, list[Item]]] = {}
    for item in items:
        grouped.setdefault(item.country, {}).setdefault(item.category, []).append(item)

    for grouped_country, grouped_categories in grouped.items():
        category_sections: list[str] = []
        for grouped_category, grouped_items in grouped_categories.items():
            item_links = []
            for item in grouped_items:
                active_class = " active" if item.id == selected_id else ""
                href = build_filter_link(item.id, q, country, category)
                title_text = display_title(item.title)
                title_classes = "item-title"
                if item.is_returned:
                    title_classes += " returned"
                subtitle_text = grouped_category
                if item.tracking_number and title_text.strip().upper() != item.tracking_number.strip().upper():
                    subtitle_text = item.tracking_number
                item_links.append(
                    f'<a class="item-link{active_class}" href="{href}">'
                    f'<div class="{title_classes}">{escape(title_text)}</div>'
                    f'<div class="item-sub">{escape(subtitle_text)}</div>'
                    f"</a>"
                )
            category_sections.append(
                f'<section style="margin-top:12px;">'
                f'<div class="meta-label" style="margin-bottom:10px;">{escape(grouped_category)}</div>'
                f'<div class="item-list">{"".join(item_links)}</div>'
                f"</section>"
            )
        list_sections.append(
            f'<section class="panel filters" style="padding:16px 16px 10px; margin-bottom:14px;">'
            f'<div class="item-country" style="font-size:13px; margin-bottom:4px;">{escape(grouped_country)}</div>'
            f'{"".join(category_sections)}'
            f"</section>"
        )

    if selected_item is None:
        detail_markup = (
            '<section class="panel detail"><div class="empty">'
            "<h2>No item selected</h2><p>Import a few items or change the filters to start browsing.</p>"
            "</div></section>"
        )
    else:
        tag_pills = "".join(
            f'<span class="pill">{escape(tag.name)}</span>' for tag in selected_item.tags
        )
        if selected_item.is_returned:
            tag_pills += '<span class="pill">returned</span>'
        if selected_item.is_self_mail:
            tag_pills += '<span class="pill">self mail</span>'

        meta_cards = [
            ("Country", selected_item.country),
            ("Category", selected_item.category),
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
            <div class="pill-row">{tag_pills or '<span class="pill">untagged</span>'}</div>
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
              <input type="search" name="q" value="{escape(q)}" placeholder="tracking, title, place" />
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
        </section>

        <div class="list-meta">
          <span>{len(items)} item{"s" if len(items) != 1 else ""}</span>
          <span>{len(countries)} countries</span>
        </div>
        <div class="item-list">{''.join(list_sections) or '<div class="empty">No items yet.</div>'}</div>
      </aside>

      <main class="main">{detail_markup}</main>
    </div>
    """
    return render_page("Philatelic Catalog", body)


@ui_router.get("/", response_class=HTMLResponse)
def home(
    item: int | None = None,
    q: str = "",
    country: str = "",
    category: str = "",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    items = list(
        session.scalars(
            build_item_query(
                country=country or None,
                category=category or None,
                q=q or None,
            )
        ).all()
    )
    selected_item = None
    if item is not None:
        selected_item = next((candidate for candidate in items if candidate.id == item), None)
    if selected_item is None and items:
        selected_item = items[0]

    countries = list(
        session.scalars(select(distinct(Item.country)).order_by(Item.country.asc())).all()
    )
    categories = list(
        session.scalars(select(distinct(Item.category)).order_by(Item.category.asc())).all()
    )
    return HTMLResponse(render_home(items, selected_item, countries, categories, q, country, category))


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
