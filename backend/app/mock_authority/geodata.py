"""Synthetic campus geometry for the demo institutions (fictional coordinates and buildings).

`observed` footprints play the role of satellite-derived building outlines from an independent
geodata source; `declared` is what each institution submits in its campus-boundary GeoJSON.
Rectangles are (x, y, width, height) in metres from the campus's south-west corner.
"""

import math

CAMPUSES = {
    "1-2345678901": {  # Apex: boundary ≈ deed (12.5 acres); footprints ≈ plan ground coverage
        "origin": (77.4910, 28.4560), "size": (225, 225),
        "declared": [("Academic Block A", (20, 20, 60, 40)), ("Academic Block B", (110, 30, 50, 30)), ("Workshop", (40, 120, 30, 20))],
        "observed": [(20, 20, 59, 40), (110, 30, 50, 30), (40, 120, 30, 20)],
    },
    "1-5550001112": {  # Crescent: consistent
        "origin": (77.5230, 28.4710), "size": (203, 203),
        "declared": [("Main Block", (30, 30, 50, 35)), ("Lab Block", (100, 40, 45, 40))],
        "observed": [(30, 30, 50, 35), (100, 40, 45, 40)],
    },
    "1-9876543210": {  # Zenith: one declared building outside the boundary; most declared buildings not observed
        "origin": (77.3720, 28.6280), "size": (140, 140),
        "declared": [("Block 1", (20, 20, 40, 30)), ("Block 2", (60, 70, 40, 40)), ("Hostel Block", (160, 20, 30, 20))],
        "observed": [(20, 20, 40, 30)],
    },
}


def _ring(origin, x, y, w, h):
    lon0, lat0 = origin
    dlat = 1 / 111320.0
    dlon = 1 / (111320.0 * math.cos(math.radians(lat0)))
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    return [[round(lon0 + px * dlon, 7), round(lat0 + py * dlat, 7)] for px, py in pts]


def observed_footprints(permanent_id: str) -> list[list[list[float]]] | None:
    c = CAMPUSES.get(permanent_id)
    if not c:
        return None
    return [_ring(c["origin"], *r) for r in c["observed"]]


def campus_geojson(permanent_id: str) -> dict:
    c = CAMPUSES[permanent_id]
    w, h = c["size"]
    features = [{"type": "Feature", "properties": {"role": "campus", "name": "Campus boundary (survey)"},
                 "geometry": {"type": "Polygon", "coordinates": [_ring(c["origin"], 0, 0, w, h)]}}]
    for name, rect in c["declared"]:
        features.append({"type": "Feature", "properties": {"role": "building", "name": name},
                         "geometry": {"type": "Polygon", "coordinates": [_ring(c["origin"], *rect)]}})
    return {"type": "FeatureCollection", "name": "Synthetic campus boundary (demo)", "features": features}
