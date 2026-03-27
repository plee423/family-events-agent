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
        tz_name = "UTC"

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
    html = _render_html(by_date, cal_name, generated_at, len(events), free_count, days_ahead, tz, tz_name)

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
    tz_name: str = "America/Chicago",
) -> str:
    # Collect all unique neighborhoods for filter bar
    all_neighborhoods: set[str] = set()
    for items in by_date.values():
        for e, _ in items:
            if e.neighborhood:
                all_neighborhoods.add(e.neighborhood)
    neighborhoods_sorted = sorted(all_neighborhoods)

    filter_pills_html = '\n      '.join(
        f'<button class="filter-pill" data-neighborhood="{_esc(nb)}">{_esc(nb)}</button>'
        for nb in neighborhoods_sorted
    )

    date_sections = []
    for date_key in sorted(by_date.keys()):
        items = by_date[date_key]
        dt_obj = datetime.strptime(date_key, "%Y-%m-%d")
        try:
            day_label = dt_obj.strftime("%A, %B %-d")
        except ValueError:
            day_label = dt_obj.strftime("%A, %B %d").lstrip("0").replace(" 0", " ")

        # Fix 3: sort free events to top, preserving time order within each group
        sorted_items = sorted(items, key=lambda x: (0 if x[0].is_free else 1, x[1]))

        cards = []
        for e, dt in sorted_items:
            # Compute dtstart / dtend strings in local timezone for .ics
            dtstart_fmt = dt.strftime("%Y%m%dT%H%M%S")
            if e.date_end:
                try:
                    dtend_dt = (
                        tz.localize(e.date_end)
                        if e.date_end.tzinfo is None
                        else e.date_end.astimezone(tz)
                    )
                except Exception:
                    dtend_dt = dt + timedelta(hours=1)
            else:
                dtend_dt = dt + timedelta(hours=1)
            dtend_fmt = dtend_dt.strftime("%Y%m%dT%H%M%S")
            cards.append(_render_card(e, dt, dtstart_fmt, dtend_fmt, tz_name))

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
      padding: 1.5rem 1rem 0.75rem;
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

    /* Filter bar */
    .filter-bar {{
      display: flex;
      gap: 0.4rem;
      flex-wrap: nowrap;
      overflow-x: auto;
      padding: 0.6rem 0 0.75rem;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }}
    .filter-bar::-webkit-scrollbar {{ display: none; }}

    .filter-pill {{
      flex-shrink: 0;
      background: rgba(255,255,255,0.18);
      border: 1.5px solid rgba(255,255,255,0.35);
      color: white;
      border-radius: 999px;
      padding: 0.22rem 0.75rem;
      font-size: 0.72rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s;
      white-space: nowrap;
    }}
    .filter-pill:hover {{
      background: rgba(255,255,255,0.28);
    }}
    .filter-pill.active {{
      background: white;
      color: #C44D8B;
      border-color: white;
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
      padding: 0.9rem 1rem 0.7rem;
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

    .badge-neighborhood {{
      background: #ede9fe;
      color: #5b21b6;
      font-size: 0.68rem;
      font-weight: 600;
      border-radius: 999px;
      padding: 0.15rem 0.55rem;
    }}

    .badge-virtual {{
      background: #e0f2fe;
      color: #0369a1;
      font-size: 0.68rem;
      font-weight: 600;
      border-radius: 999px;
      padding: 0.15rem 0.55rem;
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

    /* Add to Calendar button */
    .card-actions {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: flex-end;
      margin-top: 0.4rem;
    }}

    .add-cal-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      background: none;
      border: 1.5px solid #e0e0e5;
      border-radius: 999px;
      padding: 0.22rem 0.7rem;
      font-size: 0.7rem;
      font-weight: 600;
      color: #6e6e73;
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }}
    .add-cal-btn:hover {{
      border-color: #C44D8B;
      color: #C44D8B;
      background: #fff0f6;
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
    <div class="filter-bar" id="filterBar">
      <button class="filter-pill active" data-neighborhood="">All</button>
      {filter_pills_html}
    </div>
  </header>

  {body}

  <footer>Generated {_esc(generated_at)}</footer>

  <script>
    // ── Neighborhood filter (multi-select) ──────────────────────────────────
    const filterBar = document.getElementById('filterBar');
    const selected = new Set();

    filterBar.addEventListener('click', function(e) {{
      const pill = e.target.closest('.filter-pill');
      if (!pill) return;
      const nb = pill.dataset.neighborhood;

      if (nb === '') {{
        // "All" clicked — clear all selections
        selected.clear();
        filterBar.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
      }} else {{
        // Deactivate "All"
        filterBar.querySelector('[data-neighborhood=""]').classList.remove('active');

        if (selected.has(nb)) {{
          selected.delete(nb);
          pill.classList.remove('active');
        }} else {{
          selected.add(nb);
          pill.classList.add('active');
        }}

        // If nothing left selected, fall back to "All"
        if (selected.size === 0) {{
          filterBar.querySelector('[data-neighborhood=""]').classList.add('active');
        }}
      }}

      applyFilter();
    }});

    function applyFilter() {{
      document.querySelectorAll('.card').forEach(function(card) {{
        if (selected.size === 0) {{
          card.style.display = '';
        }} else {{
          const nb = card.dataset.neighborhood || '';
          card.style.display = selected.has(nb) ? '' : 'none';
        }}
      }});

      // Collapse day sections whose cards are all hidden
      document.querySelectorAll('.day-section').forEach(function(section) {{
        const anyVisible = section.querySelector('.card:not([style*="display: none"])');
        section.style.display = anyVisible ? '' : 'none';
      }});
    }}

    // ── Add to Calendar (.ics download) ────────────────────────────────────
    function addToCalendar(btn) {{
      const card = btn.closest('.card');
      const title    = card.dataset.title || '';
      const dtstart  = card.dataset.dtstart || '';
      const dtend    = card.dataset.dtend   || '';
      const tzid     = card.dataset.tzid    || 'America/Chicago';
      const location = card.dataset.location    || '';
      const desc     = card.dataset.description || '';
      const url      = card.dataset.url         || '';

      const uid = dtstart + '-' + title.replace(/\\W/g, '').slice(0, 24) + '@family-events';
      const now = new Date().toISOString().replace(/[-:.]/g, '').slice(0, 15) + 'Z';

      const lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//FamilyEventsAgent//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        'UID:' + uid,
        'DTSTAMP:' + now,
        'DTSTART;TZID=' + tzid + ':' + dtstart,
        'DTEND;TZID='   + tzid + ':' + dtend,
        'SUMMARY:'  + escIcs(title),
      ];
      if (location)  lines.push('LOCATION:'    + escIcs(location));
      if (desc)      lines.push('DESCRIPTION:' + escIcs(desc));
      if (url)       lines.push('URL:'          + url);
      lines.push('BEGIN:VALARM', 'TRIGGER:-PT2H', 'ACTION:DISPLAY',
                 'DESCRIPTION:Reminder', 'END:VALARM');
      lines.push('END:VEVENT', 'END:VCALENDAR');

      const ics = lines.join('\\r\\n');
      const blob = new Blob([ics], {{ type: 'text/calendar;charset=utf-8' }});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = title.replace(/[^a-z0-9]/gi, '_').slice(0, 60) + '.ics';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function() {{ URL.revokeObjectURL(a.href); }}, 1000);
    }}

    function escIcs(s) {{
      return String(s)
        .replace(/\\\\/g, '\\\\\\\\')
        .replace(/;/g,   '\\\\;')
        .replace(/,/g,   '\\\\,')
        .replace(/\\n/g,  '\\\\n');
    }}
  </script>
</body>
</html>"""


def _render_card(
    e: Event,
    dt: datetime,
    dtstart_fmt: str,
    dtend_fmt: str,
    tz_name: str,
) -> str:
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
    location_str = e.location_name if e.location_name else ""

    # Description snippet
    desc_html = ""
    if e.description:
        snippet = e.description[:200].strip()
        desc_html = f'<p class="card-desc">{_esc(snippet)}</p>'

    # Data attributes for JS (filter + ics generation)
    data_attrs = (
        f' data-neighborhood="{_esc(e.neighborhood)}"'
        f' data-free="{1 if e.is_free else 0}"'
        f' data-title="{_esc(e.title)}"'
        f' data-dtstart="{dtstart_fmt}"'
        f' data-dtend="{dtend_fmt}"'
        f' data-tzid="{_esc(tz_name)}"'
        f' data-location="{_esc(location_str)}"'
        f' data-description="{_esc(e.description[:300])}"'
        f' data-url="{_esc(e.url)}"'
    )

    # Card wrapper — link if URL exists
    card_attrs = f'class="card"{data_attrs}'
    if e.url:
        card_tag = f'<a {card_attrs} href="{_esc(e.url)}" target="_blank" rel="noopener">'
        card_close = "</a>"
    else:
        card_tag = f'<div {card_attrs}>'
        card_close = "</div>"

    clock_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
    pin_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>'
    walk_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="5" r="2"/><path d="M15 9l-3 3-3-3M9 21l3-9 3 9"/></svg>'
    cal_icon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>'

    meta_items = [f'<span class="meta-item">{clock_icon} {_esc(time_str)}</span>']
    if location_str:
        meta_items.append(f'<span class="meta-item">{pin_icon} {_esc(location_str)}</span>')
    if e.neighborhood == "Virtual":
        meta_items.append('<span class="meta-item badge badge-virtual">Virtual</span>')
    elif e.neighborhood:
        meta_items.append(f'<span class="meta-item badge badge-neighborhood">{_esc(e.neighborhood)}</span>')
    if e.org_name and e.org_name != e.location_name:
        meta_items.append(f'<span class="meta-item">· {_esc(e.org_name)}</span>')

    add_cal_btn = (
        f'<div class="card-actions">'
        f'<button class="add-cal-btn" type="button" '
        f'onclick="event.stopPropagation();addToCalendar(this)" '
        f'title="Add to Calendar">{cal_icon} Add to Calendar</button>'
        f'</div>'
    )

    return f"""{card_tag}
      <span class="card-title">{_esc(e.title)}</span>
      <span class="badge-area">{badge}</span>
      <div class="card-meta">{"".join(meta_items)}</div>
      {desc_html}
      {add_cal_btn}
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
