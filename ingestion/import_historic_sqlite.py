"""Import normalized historical GeoJSON/JSON archives into local SQLite.

Input files are grouped by filename: pfz*.json, weather*.json, ocean*.json,
satellite*.json, and boundary*.json. Files may contain a FeatureCollection,
Feature, or a list of normalized records.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from ingestion.common import features, properties
from orca.knowledge.database import SQLiteDatabase


def _pairs(value: Any) -> list[tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        return [(float(value[0]), float(value[1]))]
    if isinstance(value, (list, tuple)):
        result: list[tuple[float, float]] = []
        for child in value:
            result.extend(_pairs(child))
        return result
    return []


def _coordinates(feature: dict[str, Any], data: dict[str, Any]) -> tuple[float, float]:
    pairs = _pairs(feature.get("geometry", {}).get("coordinates"))
    if pairs:
        return (sum(pair[1] for pair in pairs) / len(pairs), sum(pair[0] for pair in pairs) / len(pairs))
    return float(data["lat"]), float(data["lon"])


def _in_range(value: str | None, start: date, end: date) -> bool:
    if not value:
        return True
    return start.isoformat() <= value[:10] <= end.isoformat()


def _read(path: Path) -> Iterable[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return features(payload)


def _insert(database: SQLiteDatabase, table: str, record: dict[str, Any]) -> None:
    columns = ", ".join(record)
    placeholders = ", ".join("?" for _ in record)
    database.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(record.values()))


def _clear_demo_rows(database: SQLiteDatabase, table: str) -> None:
    if table == "boundary_geometries":
        database.execute("DELETE FROM boundary_geometries WHERE source_url LIKE 'https://demo.local/%'")
        return
    database.execute(
        f"DELETE FROM {table} WHERE source IN ('INCOIS demo', 'IMD demo', 'INCOIS OSF demo', 'Oceansat-3 OCM demo') OR source_url LIKE 'https://demo.local/%'"
    )


def import_file(database: SQLiteDatabase, path: Path, start: date, end: date) -> int:
    name = path.name.lower()
    if name.startswith("pfz"):
        table = "pfz_bulletins"
        kind = "pfz"
    elif name.startswith("weather") or name.startswith("imd"):
        table = "weather_alerts"
        kind = "weather"
    elif name.startswith("ocean") or name.startswith("osf"):
        table = "ocean_state_forecast"
        kind = "ocean"
    elif name.startswith("satellite") or name.startswith("sst") or name.startswith("chlorophyll"):
        table = "satellite_readings"
        kind = "satellite"
    elif name.startswith("boundary") or name.startswith("eez") or name.startswith("mpa"):
        table = "boundary_geometries"
        kind = "boundary"
    else:
        return 0

    _clear_demo_rows(database, table)
    loaded = 0
    for feature in _read(path):
        data = properties(feature)
        lat, lon = _coordinates(feature, data)
        geometry = json.dumps(feature.get("geometry", {}), separators=(",", ":"))
        source_url = str(data.get("source_url") or path)
        if kind == "pfz":
            issued = str(data["issued_date"])
            if not _in_range(issued, start, end):
                continue
            _insert(database, table, {"region_name": str(data["region_name"]), "issued_date": issued, "valid_until": data.get("valid_until"), "zone_geom": geometry, "lat": lat, "lon": lon, "chlorophyll_level": data.get("chlorophyll_level"), "sst_range": data.get("sst_range"), "advisory_text": data.get("advisory_text"), "source": data.get("source", "INCOIS"), "source_url": source_url})
        elif kind == "weather":
            valid_from = str(data["valid_from"])
            if not _in_range(valid_from, start, end):
                continue
            _insert(database, table, {"alert_type": str(data["alert_type"]), "severity": data.get("severity"), "affected_area": geometry, "lat": lat, "lon": lon, "valid_from": valid_from, "valid_until": data.get("valid_until"), "description": data.get("description", ""), "source": data.get("source", "IMD"), "source_url": source_url})
        elif kind == "ocean":
            forecast_time = str(data["forecast_time"])
            if not _in_range(forecast_time, start, end):
                continue
            _insert(database, table, {"lat": lat, "lon": lon, "forecast_time": forecast_time, "wave_height_m": data.get("wave_height_m"), "wind_speed_kmh": data.get("wind_speed_kmh"), "current_speed_ms": data.get("current_speed_ms"), "tide_level_m": data.get("tide_level_m"), "source": data.get("source", "INCOIS OSF"), "source_url": source_url})
        elif kind == "satellite":
            observed_at = str(data["observed_at"])
            if not _in_range(observed_at, start, end):
                continue
            _insert(database, table, {"product": str(data["product"]), "value": float(data["value"]), "unit": data.get("unit"), "lat": lat, "lon": lon, "observed_at": observed_at, "source": data.get("source", "Satellite archive"), "source_url": source_url})
        else:
            _insert(database, table, {"boundary_type": str(data["boundary_type"]), "name": str(data["name"]), "geom": geometry, "lat": lat, "lon": lon, "metadata": json.dumps(data.get("metadata", {})), "source_url": source_url})
        loaded += 1
    return loaded


def _replace_table(database: SQLiteDatabase, table: str) -> None:
    database.execute(f"DELETE FROM {table}")
    database.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing normalized JSON/GeoJSON archives")
    parser.add_argument("--db-path", type=Path, default=Path("data/orca.sqlite3"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2005, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--replace-seeded-data", action="store_true", help="Clear the seeded demo rows before importing historical data.")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start must be before --end")
    database = SQLiteDatabase(str(args.db_path))
    if args.replace_seeded_data:
        for table in ["pfz_bulletins", "weather_alerts", "ocean_state_forecast", "satellite_readings", "boundary_geometries"]:
            _replace_table(database, table)
    total = sum(import_file(database, path, args.start, args.end) for path in sorted(args.input_dir.glob("*.json")))
    print(f"Loaded {total} records into {args.db_path} for {args.start} through {args.end}.")


if __name__ == "__main__":
    main()