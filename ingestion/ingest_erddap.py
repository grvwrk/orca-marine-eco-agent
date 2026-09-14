"""
Fetch and load satellite data from INCOIS ERDDAP server (griddap).

This module handles:
- SST from NOAA_AVHRR_AMSR_datasets
- Chlorophyll from incois_oceansat2_datasets
- Wind data from ascat_daily_datasets

Converts gridded ERDDAP responses to point readings in satellite_readings table.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ingestion.common import load
from orca.config import settings


ERDDAP_BASE = "https://erddap.incois.gov.in/erddap"

# Dataset mappings: (dataset_id, variable_name, product_name, unit)
SATELLITE_DATASETS = {
    "sst": ("NOAA_AVHRR_AMSR_datasets", "sst", "sst", "°C"),
    "chlorophyll": ("incois_oceansat2_datasets", "CHL", "chlorophyll", "mg/m³"),
    "wind_speed": ("ascat_daily_datasets", "wind_speed", "wind_speed", "m/s"),
}

# ERDDAP dimensions between products are not interchangeable. The SST and wind
# variables include a singleton vertical dimension between time and latitude.
GRID_FIXED_DIMENSIONS = {
    "NOAA_AVHRR_AMSR_datasets": ("zlev", 0.0),
    "ascat_daily_datasets": ("depth", 10.0),
}


@dataclass(frozen=True)
class SatelliteReading:
    """Normalized satellite reading ready for PostGIS insertion."""
    product: str
    value: float
    unit: str
    lon: float
    lat: float
    observed_at: str
    source: str


def fetch_griddap(
    dataset_id: str,
    variable: str,
    date: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> dict[str, Any]:
    """
    Fetch gridded data from ERDDAP griddap endpoint using value-based constraints.

    Args:
        dataset_id: ERDDAP dataset identifier
        variable: Variable name within the dataset
        date: ISO 8601 datetime (e.g., '2026-09-10T00:00:00Z')
        min_lat, max_lat: Latitude bounds
        min_lon, max_lon: Longitude bounds

    Returns:
        Parsed JSON response from ERDDAP griddap
    """
    # Value-based constraints avoid off-by-one index bugs
    constraints = [f"[({date})]"]
    fixed_dimension = GRID_FIXED_DIMENSIONS.get(dataset_id)
    if fixed_dimension:
        constraints.append(f"[({fixed_dimension[1]})]")
    constraints.extend((f"[({min_lat}):({max_lat})]", f"[({min_lon}):({max_lon})]"))
    url = f"{ERDDAP_BASE}/griddap/{dataset_id}.json?{variable}{''.join(constraints)}"
    resp = requests.get(
        url,
        timeout=settings.request_timeout_seconds,
        verify=settings.ca_bundle,
    )
    try:
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Re-raise with clearer message for SSL/network issues
        error_type = "SSL Certificate" if "certificate" in str(e).lower() else "Network"
        raise RuntimeError(f"{error_type} error connecting to ERDDAP") from e
    return resp.json()


def parse_griddap_response(
    response: dict[str, Any],
    product: str,
    unit: str,
    date_str: str,
    source: str,
) -> list[SatelliteReading]:
    """
    Parse ERDDAP griddap JSON response into point readings.

    ERDDAP griddap returns:
    {
        "table": {
            "columnNames": ["time", "latitude", "longitude", "variable"],
            "columnTypes": [...],
            "rows": [[timestamp, lat, lon, value], ...]
        }
    }

    Args:
        response: JSON response from griddap
        product: Product name for satellite_readings table
        unit: Unit of measurement
        date_str: ISO datetime string for observed_at
        source: Data source attribution

    Returns:
        List of SatelliteReading objects
    """
    readings = []
    table = response.get("table", {})
    column_names = table.get("columnNames", [])
    rows = table.get("rows", [])

    if not column_names or not rows:
        return readings

    # Build column index mapping
    col_index = {name: idx for idx, name in enumerate(column_names)}

    for row in rows:
        try:
            # Indices should be: time, latitude, longitude, variable_value
            # The exact order depends on ERDDAP response, but typically this pattern
            lat_idx = col_index.get("latitude", 1)
            lon_idx = col_index.get("longitude", 2)
            val_idx = col_index.get(column_names[-1], 3)  # Last column is usually the data variable

            if len(row) > max(lat_idx, lon_idx, val_idx):
                lat = float(row[lat_idx])
                lon = float(row[lon_idx])
                value = float(row[val_idx])

                # Skip null/invalid values
                if value is None or value != value:  # NaN check
                    continue

                reading = SatelliteReading(
                    product=product,
                    value=value,
                    unit=unit,
                    lon=lon,
                    lat=lat,
                    observed_at=date_str,
                    source=source,
                )
                readings.append(reading)
        except (ValueError, IndexError, TypeError):
            # Skip malformed rows
            continue

    return readings


def ingest_satellite_product(
    dataset_id: str,
    variable: str,
    product: str,
    unit: str,
    date: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    database_url: str,
) -> int:
    """
    Fetch and ingest a single satellite product from ERDDAP.

    Args:
        All parameters as documented in fetch_griddap
        database_url: PostgreSQL connection string
        product, unit: For satellite_readings table

    Returns:
        Number of readings ingested
    """
    try:
        response = fetch_griddap(dataset_id, variable, date, min_lat, max_lat, min_lon, max_lon)
    except requests.RequestException as e:
        print(f"Failed to fetch {dataset_id}/{variable}: {e}")
        return 0

    readings = parse_griddap_response(response, product, unit, date, dataset_id)

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
        except Exception as e:
            print(f"Failed to insert reading: {e}")
            continue

    return len(readings)


def ingest(
    dataset_id: str,
    variable: str,
    date: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    database_url: str,
) -> int:
    """
    Generic ERDDAP griddap ingestion adapter matching ingest_source.py interface.

    Expected to be called via ingest_source.py with parameters:
    --url "erddap://DATASET_ID:VARIABLE:DATE:MIN_LAT:MAX_LAT:MIN_LON:MAX_LON"

    For now, call ingest_satellite_product directly from scripts.
    """
    product_name, unit = SATELLITE_DATASETS.get(variable, (variable, "unknown"))[:2]
    return ingest_satellite_product(
        dataset_id, variable, product_name, unit, date, min_lat, max_lat, min_lon, max_lon, database_url
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id", help="ERDDAP dataset ID (e.g., NOAA_AVHRR_AMSR_datasets)")
    parser.add_argument("variable", help="Variable name within dataset (e.g., sst, CHL)")
    parser.add_argument("date", help="ISO 8601 date/time (e.g., 2026-09-10T00:00:00Z)")
    parser.add_argument("--min-lat", type=float, required=True, help="Min latitude of query box")
    parser.add_argument("--max-lat", type=float, required=True, help="Max latitude of query box")
    parser.add_argument("--min-lon", type=float, required=True, help="Min longitude of query box")
    parser.add_argument("--max-lon", type=float, required=True, help="Max longitude of query box")
    parser.add_argument("--database-url", required=True, help="PostgreSQL connection string")

    args = parser.parse_args()
    count = ingest_satellite_product(
        args.dataset_id,
        args.variable,
        args.variable,
        "unknown",
        args.date,
        args.min_lat,
        args.max_lat,
        args.min_lon,
        args.max_lon,
        args.database_url,
    )
    print(f"Loaded {count} satellite readings from {args.dataset_id}/{args.variable}")
