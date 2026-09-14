"""Fetch and load IMD-style weather alert GeoJSON records."""

import argparse

from ingestion.common import features, fetch_json, geometry_json, load, properties


def normalize_alert(feature: dict) -> dict:
    data = properties(feature)
    return {"alert_type": data["alert_type"], "severity": data.get("severity"), "description": data.get("description", ""), "valid_from": data["valid_from"], "valid_until": data.get("valid_until"), "geometry": geometry_json(feature), "source": data.get("source", "IMD")}


def ingest(url: str, database_url: str) -> int:
    alerts = [normalize_alert(feature) for feature in features(fetch_json(url))]
    for alert in alerts:
        load(database_url, "INSERT INTO weather_alerts (alert_type, severity, affected_area, valid_from, valid_until, description, source) VALUES (%(alert_type)s, %(severity)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326), %(valid_from)s, %(valid_until)s, %(description)s, %(source)s)", alert)
    return len(alerts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(f"loaded {ingest(args.url, args.database_url)} weather alerts")
