from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.models import Item
from app.services.items import build_item_query

ui_router = APIRouter(include_in_schema=False)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heif", ".heic", ".avif", ".tiff"}


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


def render_asset_card(asset_path: str, kind: str) -> str:
    suffix = Path(asset_path).suffix.lower()
    public_path = "/archive/" + "/".join(escape(part) for part in Path(asset_path).parts)
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
    list_markup = []
    selected_id = selected_item.id if selected_item else None

    for item in items:
        active_class = " active" if item.id == selected_id else ""
        href = build_filter_link(item.id, q, country, category)
        sub_bits = [item.category]
        if item.tracking_number:
            sub_bits.append(item.tracking_number)
        if item.origin:
            sub_bits.append(item.origin)
        list_markup.append(
            f'<a class="item-link{active_class}" href="{href}">'
            f'<div class="item-country">{escape(item.country)}</div>'
            f'<div class="item-title">{escape(item.title)}</div>'
            f'<div class="item-sub">{escape(" · ".join(sub_bits))}</div>'
            f"</a>"
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
            ("Origin", selected_item.origin or "Unknown"),
            ("Destination", selected_item.destination or "Unknown"),
            ("Archive ID", selected_item.archive_id),
            ("Source", selected_item.source_relpath or "Unknown"),
            ("Status", selected_item.status or "Unknown"),
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

        notes_markup = escape(selected_item.notes or "No notes yet.").replace("\n", "<br />")

        detail_markup = f"""
        <section class="panel detail">
          <div class="detail-head">
            <div>
              <div class="eyebrow">{escape(selected_item.country)} Collection</div>
              <h2 class="detail-title">{escape(selected_item.title)}</h2>
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
        <div class="item-list">{''.join(list_markup) or '<div class="empty">No items yet.</div>'}</div>
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
