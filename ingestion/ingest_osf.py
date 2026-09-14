"""Fetch and load INCOIS ocean-state forecast points."""

import argparse

from ingestion.common import features, fetch_json, load, properties


def normalize_forecast(feature: dict) -> dict:
    data = properties(feature)
    coordinates = feature.get("geometry", {}).get("coordinates", [data["lon"], data["lat"]])
    return {"lon": coordinates[0], "lat": coordinates[1], "forecast_time": data["forecast_time"], "wave_height_m": data.get("wave_height_m"), "wind_speed_kmh": data.get("wind_speed_kmh"), "current_speed_ms": data.get("current_speed_ms"), "tide_level_m": data.get("tide_level_m"), "source": data.get("source", "INCOIS OSF")}


def ingest(url: str, database_url: str) -> int:
    forecasts = [normalize_forecast(feature) for feature in features(fetch_json(url))]
    for forecast in forecasts:
        load(database_url, "INSERT INTO ocean_state_forecast (location, forecast_time, wave_height_m, wind_speed_kmh, current_speed_ms, tide_level_m, source) VALUES (ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), %(forecast_time)s, %(wave_height_m)s, %(wind_speed_kmh)s, %(current_speed_ms)s, %(tide_level_m)s, %(source)s)", forecast)
    return len(forecasts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(f"loaded {ingest(args.url, args.database_url)} forecast points")
