"""Build a standards-compliant .ics file from a list of Event objects."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from icalendar import Calendar, Event as ICalEvent, Alarm, vText, vCalAddress
import pytz

from scrapers.base import Event

logger = logging.getLogger(__name__)

# Max SUMMARY length for reliable display across calendar clients
MAX_SUMMARY_LEN = 75


def build_ics(events: list[Event], settings: dict, output_dir: str = "output") -> Path:
    """
    Build an .ics file from the given events and write it to output_dir.
    Returns the path to the generated file.
    """
    prefs = settings.get("preferences", {})
    out_cfg = settings.get("output", {})
    loc_cfg = settings.get("location", {})

    tz_name = loc_cfg.get("timezone", "America/Chicago")
    try:
        tz = pytz.timezone(tz_name)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning("Unknown timezone %r, falling back to UTC", tz_name)
        tz = pytz.utc

    cal_name = out_cfg.get("calendar_name", "Family Events")
    days_ahead = prefs.get("days_ahead", 30)

    # Build calendar object
    cal = Calendar()
    cal.add("PRODID", "-//FamilyEventsAgent//family-events-agent//EN")
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    cal.add("METHOD", "PUBLISH")
    cal.add("X-WR-CALNAME", cal_name)
    cal.add("X-WR-CALDESC", f"Family-friendly events for the next {days_ahead} days")
    cal.add("X-WR-TIMEZONE", tz_name)

    # Add VTIMEZONE component for proper iPhone compatibility
    _add_vtimezone(cal, tz)

    added = 0
    for event in events:
        vevent = _build_vevent(event, tz)
        if vevent:
            cal.add_component(vevent)
            added += 1

    # Determine output filename
    now = datetime.now()
    end_date = now + timedelta(days=days_ahead)
    filename_tpl = out_cfg.get("filename_template", "family_events_{start}_{end}.ics")
    filename = filename_tpl.format(
        start=now.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
    )

    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(cal.to_ical())

    logger.info("Calendar written: %s (%d events)", output_path, added)
    return output_path


def _build_vevent(event: Event, tz: "pytz.BaseTzInfo") -> ICalEvent | None:
    """Convert an Event dataclass to an icalendar VEVENT component."""
    vevent = ICalEvent()

    # SUMMARY — truncate if needed, prepend [FREE] indicator
    summary = event.display_title
    if len(summary) > MAX_SUMMARY_LEN:
        summary = summary[: MAX_SUMMARY_LEN - 1] + "…"
    vevent.add("SUMMARY", summary)

    # UID — deterministic hash so reimporting doesn't create duplicates
    vevent.add("UID", f"{event.uid}@family-events-agent")

    # DTSTART
    try:
        dt_start = _localize(event.date_start, tz)
        vevent.add("DTSTART", dt_start)
    except Exception as exc:
        logger.debug("Bad DTSTART for %r: %s", event.title, exc)
        return None

    # DTEND — default to 1 hour after start if not provided
    dt_end = event.date_end
    if dt_end is None:
        dt_end = event.date_start + timedelta(hours=1)
    try:
        vevent.add("DTEND", _localize(dt_end, tz))
    except Exception:
        vevent.add("DTEND", _localize(event.date_start + timedelta(hours=1), tz))

    # LOCATION
    location_parts = [p for p in [event.location_name, event.location_address] if p]
    if location_parts:
        vevent.add("LOCATION", ", ".join(location_parts))

    # DESCRIPTION — rich text with all available info
    desc_lines = []
    if event.org_name:
        desc_lines.append(f"Organizer: {event.org_name}")
    if event.cost:
        desc_lines.append(f"Cost: {event.cost}")
    elif event.is_free:
        desc_lines.append("Cost: Free")
    if event.age_range:
        desc_lines.append(f"Ages: {event.age_range}")
    if event.distance_miles is not None:
        desc_lines.append(f"Distance: {event.distance_miles} miles from home")
    if event.description:
        desc_lines.append("")
        desc_lines.append(event.description)
    if event.url:
        desc_lines.append("")
        desc_lines.append(f"More info: {event.url}")

    # icalendar spec requires \n (literal) as line separator in DESCRIPTION
    vevent.add("DESCRIPTION", "\\n".join(desc_lines))

    # URL
    if event.url:
        vevent.add("URL", event.url)

    # CATEGORIES
    if event.tags:
        vevent.add("CATEGORIES", event.tags)

    # SEQUENCE — use 0; increment if event is ever updated
    vevent.add("SEQUENCE", 0)

    # DTSTAMP — required by RFC 5545
    vevent.add("DTSTAMP", datetime.now(timezone.utc))

    # VALARM — 1 day before
    alarm_1day = Alarm()
    alarm_1day.add("ACTION", "DISPLAY")
    alarm_1day.add("DESCRIPTION", f"Tomorrow: {event.title[:60]}")
    alarm_1day.add("TRIGGER", timedelta(hours=-24))
    vevent.add_component(alarm_1day)

    # VALARM — 2 hours before
    alarm_2hr = Alarm()
    alarm_2hr.add("ACTION", "DISPLAY")
    alarm_2hr.add("DESCRIPTION", f"In 2 hours: {event.title[:60]}")
    alarm_2hr.add("TRIGGER", timedelta(hours=-2))
    vevent.add_component(alarm_2hr)

    return vevent


def _localize(dt: datetime, tz: "pytz.BaseTzInfo") -> datetime:
    """Attach timezone to a naive datetime, or convert if already aware."""
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def _add_vtimezone(cal: Calendar, tz: "pytz.BaseTzInfo") -> None:
    """
    Add a minimal VTIMEZONE component.
    Using icalendar's built-in approach: embed the timezone key so Apple Calendar
    can look it up from its own timezone database (X-LIC-LOCATION trick).
    """
    from icalendar import Timezone, TimezoneStandard, TimezoneDaylight
    import pytz

    tz_name = str(tz)

    vtimezone = Timezone()
    vtimezone.add("TZID", tz_name)
    vtimezone.add("X-LIC-LOCATION", tz_name)

    # Add standard time (winter) component
    standard = TimezoneStandard()
    standard.add("TZNAME", "ST")
    standard.add("DTSTART", datetime(1970, 1, 1, 2, 0, 0))
    standard.add("TZOFFSETFROM", timedelta(hours=-5))
    standard.add("TZOFFSETTO", timedelta(hours=-6))
    vtimezone.add_component(standard)

    # Add daylight saving time component
    daylight = TimezoneDaylight()
    daylight.add("TZNAME", "DT")
    daylight.add("DTSTART", datetime(1970, 3, 8, 2, 0, 0))
    daylight.add("TZOFFSETFROM", timedelta(hours=-6))
    daylight.add("TZOFFSETTO", timedelta(hours=-5))
    vtimezone.add_component(daylight)

    cal.add_component(vtimezone)
