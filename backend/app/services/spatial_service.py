"""Geospatial and blueprint verification of campus / building area claims (deterministic).

Inputs
  * Campus boundary submitted by the institution as GeoJSON (Polygon/MultiPolygon; features with
    properties.role = "campus" | "building"; anything else is treated as the campus).
  * Building footprints observed by a geodata provider for that area:
      simulated   synthetic satellite-derived footprints for the demo institutions (registry.json)
      osm         OpenStreetMap building outlines via the Overpass API (real campuses only)
  * The sanctioned building plan (ground coverage / built-up area / floors, room dimensions).

Outputs (facts for the rule engine and evidence for officers)
  spatial.boundary_area_acres        geodesic area of the campus polygon
  spatial.observed_footprint_sqm     total observed building footprint inside the boundary
  computed in rule facts:            footprint vs plan deviation (%)
Plus issues: declared buildings outside the boundary, invalid geometry, room area ≠ length × width.

No imagery is classified here: "observed" footprints come from the provider's vector data.
"""

import json
import logging
import math
from typing import Any

import httpx

from app.core.config import settings
from app.models.application import Application

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6371008.8
SQM_PER_ACRE = 4046.8564224


# ------------------------------------------------------------------ geometry

def ring_area_sqm(ring: list[list[float]]) -> float:
    """Geodesic area of a lon/lat ring on a sphere (spherical-excess formula)."""
    if len(ring) < 4:
        return 0.0
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total) * EARTH_RADIUS_M ** 2 / 2


def polygon_area_sqm(coords: list) -> float:
    outer, *holes = coords
    return max(ring_area_sqm(outer) - sum(ring_area_sqm(h) for h in holes), 0.0)


def geometry_area_sqm(geom: dict[str, Any]) -> float:
    if geom["type"] == "Polygon":
        return polygon_area_sqm(geom["coordinates"])
    if geom["type"] == "MultiPolygon":
        return sum(polygon_area_sqm(p) for p in geom["coordinates"])
    return 0.0


def centroid(ring: list[list[float]]) -> tuple[float, float]:
    xs, ys = [p[0] for p in ring[:-1]], [p[1] for p in ring[:-1]]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def point_in_ring(pt: tuple[float, float], ring: list[list[float]]) -> bool:
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1:
            inside = not inside
    return inside


def _outer_rings(geom: dict[str, Any]) -> list[list[list[float]]]:
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def _segments_intersect(a, b, c, d) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (orient(a, b, c) * orient(a, b, d) < 0) and (orient(c, d, a) * orient(c, d, b) < 0)


def self_intersects(ring: list[list[float]]) -> bool:
    segs = list(zip(ring, ring[1:]))
    for i in range(len(segs)):
        for j in range(i + 2, len(segs)):
            if i == 0 and j == len(segs) - 1:
                continue
            if _segments_intersect(*segs[i], *segs[j]):
                return True
    return False


# ------------------------------------------------------------- geodata providers

class SimulatedSatelliteProvider:
    """Synthetic satellite-derived footprints keyed by AICTE permanent ID (demo only)."""
    name = "Simulated satellite-derived footprints (demo data)"

    def footprints(self, app: Application, campus: dict[str, Any]) -> list[dict[str, Any]] | None:
        from app.mock_authority.geodata import observed_footprints
        rings = observed_footprints(app.permanent_id or "")
        if rings is None:
            return None
        return [{"type": "Polygon", "coordinates": [ring]} for ring in rings]


class OSMProvider:
    """OpenStreetMap building outlines inside the campus bounding box (Overpass API)."""
    name = "OpenStreetMap building outlines (Overpass API)"

    def footprints(self, app: Application, campus: dict[str, Any]) -> list[dict[str, Any]] | None:
        rings = _outer_rings(campus)
        lons = [p[0] for r in rings for p in r]
        lats = [p[1] for r in rings for p in r]
        q = f'[out:json][timeout:20];way["building"]({min(lats)},{min(lons)},{max(lats)},{max(lons)});out geom;'
        try:
            r = httpx.post(settings.OVERPASS_URL, data={"data": q}, timeout=25)
            r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Overpass unavailable: {e}")
            return None
        out = []
        for el in r.json().get("elements", []):
            ring = [[p["lon"], p["lat"]] for p in el.get("geometry", [])]
            if len(ring) >= 4:
                out.append({"type": "Polygon", "coordinates": [ring]})
        return out


def provider():
    return OSMProvider() if settings.GEODATA_PROVIDER == "osm" else SimulatedSatelliteProvider()


# ------------------------------------------------------------------ service

class SpatialService:
    def analyze_boundary(self, db, app: Application, geojson_bytes: bytes) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        try:
            data = json.loads(geojson_bytes.decode("utf-8"))
        except Exception:
            return {"issues": [{"rag": "amber", "actionable_by": "institution", "message": "Campus boundary is not valid GeoJSON",
                                "fix_hint": "Upload the surveyed campus boundary as a GeoJSON Polygon."}]}
        features = data.get("features") if data.get("type") == "FeatureCollection" else [data if data.get("type") == "Feature" else {"geometry": data, "properties": {}}]
        campus, buildings = None, []
        for f in features or []:
            geom, role = f.get("geometry") or {}, (f.get("properties") or {}).get("role", "campus")
            if geom.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            if role == "building":
                buildings.append({"name": (f.get("properties") or {}).get("name", "Building"), "geometry": geom})
            elif campus is None:
                campus = geom
        if campus is None:
            return {"issues": [{"rag": "amber", "actionable_by": "institution", "message": "No campus polygon found in the boundary file",
                                "fix_hint": "The GeoJSON must contain the campus boundary as a Polygon."}]}

        rings = _outer_rings(campus)
        if any(self_intersects(r) for r in rings):
            issues.append({"rag": "amber", "actionable_by": "institution", "message": "Campus boundary polygon crosses itself",
                           "fix_hint": "Upload a valid, non-self-intersecting boundary from the land survey."})
        area_sqm = geometry_area_sqm(campus)

        declared = []
        for b in buildings:
            ring = _outer_rings(b["geometry"])[0]
            inside = any(point_in_ring(centroid(ring), r) for r in rings)
            declared.append({"name": b["name"], "area_sqm": round(geometry_area_sqm(b["geometry"]), 1), "inside_campus": inside})
            if not inside:
                issues.append({"rag": "red", "message": f"Declared building '{b['name']}' lies outside the campus boundary",
                               "evidence": "Building centroid falls outside every campus polygon ring."})

        prov = provider()
        observed = prov.footprints(app, campus)
        observed_inside = []
        if observed is not None:
            for fp in observed:
                ring = _outer_rings(fp)[0]
                if any(point_in_ring(centroid(ring), r) for r in rings):
                    observed_inside.append(round(geometry_area_sqm(fp), 1))
        result = {
            "boundary_area_sqm": round(area_sqm, 1),
            "boundary_area_acres": round(area_sqm / SQM_PER_ACRE, 3),
            "declared_buildings": declared,
            "declared_footprint_sqm": round(sum(d["area_sqm"] for d in declared), 1) if declared else None,
            "observed_source": prov.name if observed is not None else f"{prov.name} — no data for this area",
            "observed_footprints": len(observed_inside),
            "observed_footprint_sqm": round(sum(observed_inside), 1) if observed is not None else None,
            "geometry": {"campus": rings, "buildings": [_outer_rings(b["geometry"])[0] for b in buildings],
                         "observed": [_outer_rings(fp)[0] for fp in (observed or [])][:200]},
            "issues": issues,
        }
        if observed is None:
            issues.append({"rag": "amber", "actionable_by": "officer",
                           "message": "No independent footprint data for this campus; verify built-up area by inspection"})
        return result

    @staticmethod
    def blueprint_issues(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Room area stated on the plan must equal length × width (±2%)."""
        out = []
        for r in data.get("room_dimensions") or []:
            computed = r["length_m"] * r["width_m"]
            if abs(computed - r["stated_sqm"]) > 0.02 * r["stated_sqm"]:
                out.append({"rag": "red", "message": f"{r['room']}: stated {r['stated_sqm']:g} m² but {r['length_m']:g} m × {r['width_m']:g} m = {computed:g} m²",
                            "evidence": "Blueprint dimensions do not support the stated carpet area (tolerance 2%)."})
        return out


spatial_service = SpatialService()
