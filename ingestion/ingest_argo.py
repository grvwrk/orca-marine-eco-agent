"""
Fetch and load ARGO ground truth data from INCOIS ERDDAP tabledap.

This module handles Indian_ARGO_Floats dataset:
- Query by time and space bounds
- Filter by QC flags (quality control)
- Load validated temperature and salinity readings as satellite_readings proxy

ARGO QC Convention: 1=good, 0=no QC, 2-8 indicate varying suspect/bad quality.
Only rows with QC=1 are treated as validated ground truth.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

from ingestion.common import load
from orca.config import settings


ERDDAP_BASE = "https://erddap.incois.gov.in/erddap"
ARGO_DATASET = "Indian_ARGO_Floats"


@dataclass(frozen=True)
class ArgoReading:
    """Validated ARGO float measurement."""
    product: str  # 'argo_temperature' or 'argo_salinity'
    value: float
    unit: str
    lon: float
    lat: float
    observed_at: str
    source: str
    qc_flag: int


def fetch_argo_tabledap(
    start_time: str,
    end_time: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> dict[str, Any]:
    """
    Fetch ARGO float data from ERDDAP tabledap endpoint.

    Args:
        start_time, end_time: ISO 8601 datetimes (e.g., '2026-09-01T00:00:00Z')
        min_lat, max_lat: Latitude bounds
        min_lon, max_lon: Longitude bounds

    Returns:
        Parsed JSON response from ERDDAP tabledap
    """
    url = (
        f"{ERDDAP_BASE}/tabledap/{ARGO_DATASET}.json"
        "?latitude,longitude,time,TEMP,TEMP_QC,PSAL,PSAL_QC,PRES"
        f"&time>={start_time}&time<={end_time}"
        f"&latitude>={min_lat}&latitude<={max_lat}"
        f"&longitude>={min_lon}&longitude<={max_lon}"
    )
    resp = requests.get(
        url,
        timeout=settings.request_timeout_seconds,
        verify=settings.ca_bundle,
    )
    resp.raise_for_status()
    return resp.json()


def parse_argo_response(
    response: dict[str, Any],
    source: str = "INCOIS ARGO Floats",
) -> list[ArgoReading]:
    """
    Parse ERDDAP tabledap JSON response into validated readings.

    ERDDAP tabledap returns:
    {
        "table": {
            "columnNames": ["latitude", "longitude", "time", "TEMP", "TEMP_QC", "PSAL", "PSAL_QC", "PRES"],
            "columnTypes": [...],
            "rows": [[lat, lon, time, temp, temp_qc, psal, psal_qc, pres], ...]
        }
    }

    Only rows with QC=1 (good quality) are included.

    Args:
        response: JSON response from tabledap
        source: Data source attribution

    Returns:
        List of ArgoReading objects with valid QC flags
    """
    readings = []
    table = response.get("table", {})
    column_names = table.get("columnNames", [])
    rows = table.get("rows", [])

    if not column_names or not rows:
        return readings

    # Build column index mapping
    col_index = {name: idx for idx, name in enumerate(column_names)}

    # Required columns
    required = ["latitude", "longitude", "time", "TEMP", "TEMP_QC", "PSAL", "PSAL_QC"]
    if not all(col in col_index for col in required):
        return readings

    lat_idx = col_index["latitude"]
    lon_idx = col_index["longitude"]
    time_idx = col_index["time"]
    temp_idx = col_index["TEMP"]
    temp_qc_idx = col_index["TEMP_QC"]
    psal_idx = col_index["PSAL"]
    psal_qc_idx = col_index["PSAL_QC"]

    for row in rows:
        try:
            if len(row) <= max(lat_idx, lon_idx, time_idx, temp_idx, temp_qc_idx, psal_idx, psal_qc_idx):
                continue

            lat = float(row[lat_idx])
            lon = float(row[lon_idx])
            time_str = str(row[time_idx])
            temp = row[temp_idx]
            temp_qc = int(row[temp_qc_idx]) if row[temp_qc_idx] is not None else 0
            psal = row[psal_idx]
            psal_qc = int(row[psal_qc_idx]) if row[psal_qc_idx] is not None else 0

            # Only process good-quality (QC=1) readings
            if temp is not None and temp_qc == 1:
                try:
                    temp_val = float(temp)
                    if temp_val == temp_val:  # NaN check
                        readings.append(
                            ArgoReading(
                                product="argo_temperature",
                                value=temp_val,
                                unit="°C",
                                lon=lon,
                                lat=lat,
                                observed_at=time_str,
                                source=source,
                                qc_flag=temp_qc,
                            )
                        )
                except (ValueError, TypeError):
                    pass

            # Only process good-quality salinity readings
            if psal is not None and psal_qc == 1:
                try:
                    psal_val = float(psal)
                    if psal_val == psal_val:  # NaN check
                        readings.append(
                            ArgoReading(
                                product="argo_salinity",
                                value=psal_val,
                                unit="PSU",
                                lon=lon,
                                lat=lat,
                                observed_at=time_str,
                                source=source,
                                qc_flag=psal_qc,
                            )
                        )
                except (ValueError, TypeError):
                    pass

        except (ValueError, IndexError, TypeError):
            # Skip malformed rows
            continue

    return readings


def ingest(
    start_time: str,
    end_time: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    database_url: str,
) -> int:
    """
    Fetch and ingest ARGO float ground truth data.

    Args:
        start_time, end_time: ISO 8601 datetimes
        min_lat, max_lat, min_lon, max_lon: Query bounding box
        database_url: PostgreSQL connection string

    Returns:
        Number of readings ingested
    """
    try:
        response = fetch_argo_tabledap(start_time, end_time, min_lat, max_lat, min_lon, max_lon)
    except requests.RequestException as e:
        print(f"Failed to fetch ARGO data: {e}")
        return 0

    readings = parse_argo_response(response)
    count = 0

    for reading in readings:
        try:
            load(
                database_url,
                """INSERT INTO satellite_readings 
                   (product, value, unit, location, observed_at, source)
                   VALUES (%(product)s, %(value)s, %(unit)s, 
                           ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), 
                           %(observed_at)s, %(source)s)""",
                {
                    "product": reading.product,
                    "value": reading.value,
                    "unit": reading.unit,
                    "lon": reading.lon,
                    "lat": reading.lat,
                    "observed_at": reading.observed_at,
                    "source": reading.source,
                },
            )
            count += 1
        except Exception as e:
            print(f"Failed to insert ARGO reading: {e}")
            continue

    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_time", help="Start time in ISO 8601 format (e.g., 2026-09-01T00:00:00Z)")
    parser.add_argument("end_time", help="End time in ISO 8601 format (e.g., 2026-09-10T23:59:59Z)")
    parser.add_argument("--min-lat", type=float, required=True, help="Min latitude of query box")
    parser.add_argument("--max-lat", type=float, required=True, help="Max latitude of query box")
    parser.add_argument("--min-lon", type=float, required=True, help="Min longitude of query box")
    parser.add_argument("--max-lon", type=float, required=True, help="Max longitude of query box")
    parser.add_argument("--database-url", required=True, help="PostgreSQL connection string")

    args = parser.parse_args()
    count = ingest(
        args.start_time,
        args.end_time,
        args.min_lat,
        args.max_lat,
        args.min_lon,
        args.max_lon,
        args.database_url,
    )
    print(f"Loaded {count} validated ARGO readings from {args.start_time} to {args.end_time}")
