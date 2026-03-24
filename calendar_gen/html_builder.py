"""Build a mobile-friendly HTML page from a list of Event objects."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytz

from scrapers.base import Event

logger = logging.getLogger(__name__)


def build_html(events: list[Event], settings: dict, output_dir: str = "output") -> Path:
    """
    Build an HTML events page and write it to output_dir/events.html.
    Returns the path to the generated file.
    """
    loc_cfg = settings.get("location", {})
    prefs = settings.get("preferences", {})
    out_cfg = settings.get("output", {})

    tz_name = loc_cfg.get("timezone", "America/Chicago")
    try:
        tz = pytz.timezone(tz_name)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning("Unknown timezone %r, falling back to UTC", tz_name)
        tz = pytz.utc

    cal_name = out_cfg.get("calendar_name", "Family Events")
    days_ahead = prefs.get("days_ahead", 30)
    generated_at = datetime.now(tz).strftime("%B %d, %Y at %I:%M %p %Z")

    # Localize all event datetimes for display
    localized = []
    for e in events:
        try:
            if e.date_start.tzinfo is None:
                dt = tz.localize(e.date_start)
            else:
                dt = e.date_start.astimezone(tz)
            localized.append((e, dt))
        except Exception:
            localized.append((e, e.date_start))

    # Group by date
    by_date: dict[str, list[tuple[Event, datetime]]] = {}
    for e, dt in localized:
        date_key = dt.strftime("%Y-%m-%d")
        by_date.setdefault(date_key, []).append((e, dt))

    free_count = sum(1 for e in events if e.is_free)
    html = _render_html(by_date, cal_name, generated_at, len(events), free_count, days_ahead, tz)

    out_cfg = settings.get("output", {})
    html_filename = out_cfg.get("html_filename", "events.html")
    output_path = Path(output_dir) / html_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    logger.info("HTML page written: %s (%d events)", output_path, len(events))
    return output_path


def _render_html(
    by_date: dict[str, list[tuple[Event, datetime]]],
    cal_name: str,
    generated_at: str,
    total: int,
    free_count: int,
    days_ahead: int,
    tz: "pytz.BaseTzInfo",
) -> str:
    date_sections = []
    for date_key in sorted(by_date.keys()):
        items = by_date[date_key]
        dt_obj = datetime.strptime(date_key, "%Y-%m-%d")
        # %-d (strip leading zero) is Linux/Mac only — Windows needs a different approach
        try:
            day_label = dt_obj.strftime("%A, %B %-d")
        except ValueError:
            day_label = dt_obj.strftime("%A, %B %d").lstrip("0").replace(" 0", " ")

        cards = []
        for e, dt in items:
            cards.append(_render_card(e, dt))

        date_sections.append(f"""
    <section class="day-section">
      <h2 class="day-header">{_esc(day_label)}</h2>
      <div class="cards">{"".join(cards)}</div>
    </section>""")

    body = "\n".join(date_sections) if date_sections else '<p class="no-events">No events found.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#FF6B9D">
  <title>{_esc(cal_name)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f5f7;
      color: #1d1d1f;
      padding-bottom: 2rem;
    }}

    header {{
      background: linear-gradient(135deg, #FF6B9D 0%, #C44D8B 100%);
      color: white;
      padding: 1.5rem 1rem 1rem;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }}

    header h1 {{
      font-size: 1.4rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}

    header .subtitle {{
      font-size: 0.8rem;
      opacity: 0.88;
      margin-top: 0.25rem;
    }}

    header .stats {{
      display: flex;
      gap: 1rem;
      margin-top: 0.6rem;
      font-size: 0.78rem;
      opacity: 0.9;
    }}

    .stat-pill {{
      background: rgba(255,255,255,0.2);
      border-radius: 999px;
      padding: 0.2rem 0.6rem;
    }}

    .day-section {{
      max-width: 680px;
      margin: 1.2rem auto 0;
      padding: 0 0.75rem;
    }}

    .day-header {{
      font-size: 0.85rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #6e6e73;
      margin-bottom: 0.5rem;
      padding-left: 0.1rem;
    }}

    .cards {{
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }}

    .card {{
      background: white;
      border-radius: 14px;
      padding: 0.9rem 1rem;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.2rem 0.5rem;
      align-items: start;
      text-decoration: none;
      color: inherit;
      transition: box-shadow 0.15s;
    }}

    .card:hover {{ box-shadow: 0 3px 12px rgba(0,0,0,0.13); }}

    .card-title {{
      font-size: 0.95rem;
      font-weight: 600;
      line-height: 1.3;
      grid-column: 1;
    }}

    .badge-area {{
      grid-column: 2;
      grid-row: 1;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 0.25rem;
    }}

    .badge {{
      border-radius: 999px;
      padding: 0.15rem 0.55rem;
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      white-space: nowrap;
    }}

    .badge-free {{
      background: #d1fae5;
      color: #065f46;
    }}

    .badge-paid {{
      background: #fee2e2;
      color: #991b1b;
    }}

    .card-meta {{
      font-size: 0.78rem;
      color: #6e6e73;
      grid-column: 1 / -1;
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem 0.8rem;
      margin-top: 0.2rem;
    }}

    .meta-item {{
      display: flex;
      align-items: center;
      gap: 0.25rem;
    }}

    .meta-item svg {{
      flex-shrink: 0;
      opacity: 0.6;
    }}

    .card-desc {{
      font-size: 0.78rem;
      color: #8e8e93;
      grid-column: 1 / -1;
      margin-top: 0.3rem;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    .no-events {{
      text-align: center;
      color: #8e8e93;
      padding: 3rem 1rem;
    }}

    footer {{
      text-align: center;
      font-size: 0.72rem;
      color: #aeaeb2;
      margin-top: 2rem;
      padding: 0 1rem;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_esc(cal_name)}</h1>
    <div class="subtitle">Next {days_ahead} days · Chicago area</div>
    <div class="stats">
      <span class="stat-pill">{total} events</span>
      <span class="stat-pill">{free_count} free</span>
    </div>
  </header>

  {body}

  <footer>Generated {_esc(generated_at)}</footer>
</body>
</html>"""


def _render_card(e: Event, dt: datetime) -> str:
    # Time
    if dt.hour == 0 and dt.minute == 0:
        time_str = "All day"
    else:
        try:
            time_str = dt.strftime("%-I:%M %p")
        except ValueError:
            time_str = dt.strftime("%I:%M %p").lstrip("0") or dt.strftime("%I:%M %p")

    # Badge
    if e.is_free:
        badge = '<span class="badge badge-free">Free</span>'
    elif e.cost:
        badge = f'<span class="badge badge-paid">{_esc(e.cost[:20])}</span>'
    else:
        badge = ""

    # Location meta
    loc_parts = []
    if e.location_name:
        loc_parts.append(e.location_name)
    location_str = loc_parts[0] if loc_parts else ""

    dist_str = f"{e.distance_miles:.1f} mi" if e.distance_miles is not None else ""

    # Description snippet
    desc_html = ""
    if e.description:
        snippet = e.description[:200].strip()
        desc_html = f'<p class="card-desc">{_esc(snippet)}</p>'

    # Card wrapper — link if URL exists
    card_attrs = 'class="card"'
    if e.url:
        card_tag = f'<a {card_attrs} href="{_esc(e.url)}" target="_blank" rel="noopener">'
        card_close = "</a>"
    else:
        card_tag = f'<div {card_attrs}>'
        card_close = "</div>"

    clock_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
    pin_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>'
    walk_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="5" r="2"/><path d="M15 9l-3 3-3-3M9 21l3-9 3 9"/></svg>'

    meta_items = [f'<span class="meta-item">{clock_icon} {_esc(time_str)}</span>']
    if location_str:
        meta_items.append(f'<span class="meta-item">{pin_icon} {_esc(location_str)}</span>')
    if dist_str:
        meta_items.append(f'<span class="meta-item">{walk_icon} {_esc(dist_str)}</span>')
    if e.org_name and e.org_name != e.location_name:
        meta_items.append(f'<span class="meta-item">· {_esc(e.org_name)}</span>')

    return f"""{card_tag}
      <span class="card-title">{_esc(e.title)}</span>
      <span class="badge-area">{badge}</span>
      <div class="card-meta">{"".join(meta_items)}</div>
      {desc_html}
    {card_close}"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
