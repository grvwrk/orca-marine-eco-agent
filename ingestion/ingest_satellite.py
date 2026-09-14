"""Fetch and load point satellite readings."""

import argparse

from ingestion.common import features, fetch_json, load, properties


def normalize_reading(feature: dict) -> dict:
    data = properties(feature)
    coordinates = feature.get("geometry", {}).get("coordinates", [data["lon"], data["lat"]])
    return {"product": data["product"], "value": float(data["value"]), "unit": data.get("unit"), "lon": coordinates[0], "lat": coordinates[1], "observed_at": data["observed_at"], "source": data.get("source", "Oceansat-3 OCM")}


def ingest(url: str, database_url: str) -> int:
    readings = [normalize_reading(feature) for feature in features(fetch_json(url))]
    for reading in readings:
        load(database_url, "INSERT INTO satellite_readings (product, value, unit, location, observed_at, source) VALUES (%(product)s, %(value)s, %(unit)s, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), %(observed_at)s, %(source)s)", reading)
    return len(readings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(f"loaded {ingest(args.url, args.database_url)} satellite readings")
