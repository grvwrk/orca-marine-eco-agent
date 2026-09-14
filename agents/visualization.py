from typing import Any


def build_map_data(lat: float, lon: float) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"label": "Query location"}}]}
