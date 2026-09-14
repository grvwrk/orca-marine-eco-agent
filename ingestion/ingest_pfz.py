"""Fetch and load PFZ GeoJSON/JSON records into PostGIS."""

import argparse
from dataclasses import dataclass

from ingestion.common import features, fetch_json, geometry_json, load, properties


@dataclass(frozen=True)
class PfzBulletin:
    region_name: str
    issued_date: str
    geometry: str
    source_url: str


def parse_bulletin(feature: dict, source_url: str) -> PfzBulletin:
    data = properties(feature)
    return PfzBulletin(str(data["region_name"]), str(data["issued_date"]), geometry_json(feature), source_url)


def ingest(url: str, database_url: str) -> int:
    records = [parse_bulletin(feature, url) for feature in features(fetch_json(url))]
    for record in records:
        load(database_url, "INSERT INTO pfz_bulletins (region_name, issued_date, zone_geom, source) VALUES (%(region_name)s, %(issued_date)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326), %(source)s)", record.__dict__)
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(f"loaded {ingest(args.url, args.database_url)} PFZ bulletins")
