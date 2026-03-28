"""Classify a (lat, lng) coordinate into a Chicago-area neighborhood name.

Uses axis-aligned bounding boxes ordered from most-specific (smallest) to
least-specific.  The first box that contains the point wins.  Falls back to
"Chicago" for any point inside the city limits that doesn't match a named box,
or to the empty string for points outside the greater-Chicago bounding box.
"""
from __future__ import annotations

# Each entry: (name, lat_min, lat_max, lng_min, lng_max)
# Ordered roughly small→large so more-specific boxes win over broad ones.
_NEIGHBORHOODS: list[tuple[str, float, float, float, float]] = [
    # ── Downtown / Near North ───────────────────────────────────────────────
    ("The Loop",            41.873, 41.888, -87.638, -87.624),
    ("South Loop",          41.854, 41.873, -87.638, -87.600),  # extended east to cover Museum Campus / lakefront
    ("West Loop",           41.877, 41.894, -87.654, -87.638),
    ("River North",         41.888, 41.904, -87.638, -87.620),
    ("Streeterville",       41.888, 41.900, -87.624, -87.600),  # extended east to cover Navy Pier / CCM
    ("Gold Coast",          41.895, 41.910, -87.632, -87.621),
    # ── North Side ──────────────────────────────────────────────────────────
    ("Old Town",            41.904, 41.918, -87.641, -87.627),
    ("Lincoln Park",        41.918, 41.943, -87.650, -87.621),
    ("Lakeview",            41.938, 41.960, -87.657, -87.629),
    ("Wrigleyville",        41.945, 41.960, -87.658, -87.646),
    ("Uptown",              41.960, 41.978, -87.656, -87.636),
    ("Andersonville",       41.974, 41.994, -87.676, -87.655),
    ("Ravenswood",          41.960, 41.982, -87.680, -87.658),
    ("Lincoln Square",      41.962, 41.978, -87.690, -87.670),
    ("Rogers Park",         41.994, 42.020, -87.680, -87.648),
    # ── Northwest Side ──────────────────────────────────────────────────────
    ("Wicker Park",         41.904, 41.916, -87.682, -87.667),
    ("Bucktown",            41.916, 41.928, -87.690, -87.670),
    ("Logan Square",        41.921, 41.940, -87.715, -87.682),
    ("Ukrainian Village",   41.892, 41.908, -87.680, -87.658),
    ("Humboldt Park",       41.893, 41.915, -87.725, -87.703),
    # ── West Side ───────────────────────────────────────────────────────────
    ("Near West Side",      41.868, 41.889, -87.670, -87.648),
    ("Pilsen",              41.846, 41.862, -87.667, -87.640),
    ("Little Village",      41.843, 41.858, -87.720, -87.680),
    # ── South Side ──────────────────────────────────────────────────────────
    ("Bridgeport",          41.828, 41.852, -87.650, -87.628),
    ("Hyde Park",           41.780, 41.810, -87.607, -87.578),
    ("Bronzeville",         41.820, 41.845, -87.625, -87.602),
    ("Kenwood",             41.810, 41.828, -87.607, -87.580),
    # ── Near suburbs (within 10-mile radius) ────────────────────────────────
    ("Evanston",            42.020, 42.078, -87.720, -87.673),
    ("Oak Park",            41.869, 41.902, -87.810, -87.768),
    ("Cicero",              41.838, 41.865, -87.770, -87.740),
    # ── Broad city fallback (must come last) ────────────────────────────────
    ("Chicago",             41.644, 42.023, -87.940, -87.524),

    # ── Orange County / Irvine area (ordered specific → broad) ──────────────
    # Specific cities before Irvine so they win when coords overlap.
    ("Rancho Santa Margarita", 33.608, 33.672, -117.632, -117.563),
    ("Aliso Viejo",            33.545, 33.610, -117.768, -117.692),
    ("Laguna Hills",           33.570, 33.636, -117.752, -117.680),
    ("Lake Forest",            33.597, 33.688, -117.742, -117.638),
    ("Tustin",                 33.718, 33.786, -117.862, -117.788),
    ("Santa Ana",              33.718, 33.786, -117.942, -117.862),
    ("Costa Mesa",             33.623, 33.700, -117.972, -117.884),
    ("Huntington Beach",       33.647, 33.745, -118.042, -117.934),
    ("Fullerton",              33.840, 33.912, -117.978, -117.882),
    ("Irvine",                 33.592, 33.755, -117.925, -117.680),
    # Broad OC fallback — catches anything within the county not matched above
    ("Orange County",          33.380, 34.010, -118.150, -117.380),
]


def classify(lat: float, lng: float) -> str:
    """Return the neighborhood name for the given coordinates.

    Returns an empty string when the point falls outside all known bounding boxes.
    """
    for name, lat_min, lat_max, lng_min, lng_max in _NEIGHBORHOODS:
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return name
    return ""
