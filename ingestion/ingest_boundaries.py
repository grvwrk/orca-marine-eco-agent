"""Fetch and load EEZ, IMBL, and MPA GeoJSON boundaries."""

import argparse

from ingestion.common import features, fetch_json, geometry_json, load, properties


def normalize_boundary(feature: dict) -> dict:
    data = properties(feature)
    return {"boundary_type": data["boundary_type"], "name": data["name"], "geometry": geometry_json(feature), "metadata": data.get("metadata", {})}


def ingest(url: str, database_url: str) -> int:
    boundaries = [normalize_boundary(feature) for feature in features(fetch_json(url))]
    for boundary in boundaries:
        load(database_url, "INSERT INTO boundary_geometries (boundary_type, name, geom, metadata) VALUES (%(boundary_type)s, %(name)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326), %(metadata)s::jsonb)", boundary)
    return len(boundaries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(f"loaded {ingest(args.url, args.database_url)} boundaries")