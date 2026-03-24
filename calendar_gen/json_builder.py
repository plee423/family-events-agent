"""Serialize filtered events to JSON for consumption by the web UI."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from scrapers.base import Event

logger = logging.getLogger(__name__)


def build_json(events: list[Event], settings: dict, output_dir: str = "output") -> Path:
    """
    Write events to a JSON file for the web UI.
    Filename is taken from settings['output']['json_filename'],
    defaulting to events_{city}.json.
    """
    out_cfg = settings.get("output", {})
    loc_cfg = settings.get("location", {})

    city_raw = loc_cfg.get("city", "events")
    city_slug = city_raw.lower().replace(" ", "_").replace(",", "")
    filename = out_cfg.get("json_filename", f"events_{city_slug}.json")

    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "city": city_slug,
        "city_label": city_raw,
        "timezone": loc_cfg.get("timezone", "America/Chicago"),
        "total": len(events),
        "free_count": sum(1 for e in events if e.is_free),
        "events": [_serialize(e) for e in events],
    }

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("JSON written: %s (%d events)", output_path, len(events))
    return output_path


def _serialize(e: Event) -> dict:
    return {
        "uid": e.uid,
        "title": e.title,
        "display_title": e.display_title,
        "date_start": e.date_start.isoformat(),
        "date_end": e.date_end.isoformat() if e.date_end else None,
        "org_name": e.org_name,
        "location_name": e.location_name,
        "location_address": e.location_address,
        "location_lat": e.location_lat,
        "location_lng": e.location_lng,
        "description": e.description,
        "url": e.url,
        "cost": e.cost,
        "is_free": e.is_free,
        "age_range": e.age_range,
        "tags": e.tags,
        "distance_miles": e.distance_miles,
        "source_name": e.source_name,
    }
