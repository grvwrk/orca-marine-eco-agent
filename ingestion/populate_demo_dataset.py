"""
Orchestration script to populate ORCA PostGIS database with real ocean data.

This script demonstrates the full data ingestion pipeline using confirmed sources:
1. INCOIS ERDDAP (satellite data, ARGO ground truth)
2. IMD API (weather alerts, with public web scraper fallback)
3. Marine Regions + WDPA (boundary geometries)
4. Manually curated demo data (PFZ bulletins, as fallback)

Usage:
    python ingestion/populate_demo_dataset.py \\
        --database-url "postgresql://user:pass@localhost/orca" \\
        --region south_tamil_nadu \\
        --date 2026-09-10 \\
        --skip-live-sources  # Use only mock data if ERDDAP/IMD unavailable
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

# Ensure repo root is in path for imports
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from ingestion.ingest_argo import ingest as ingest_argo
from ingestion.ingest_erddap import ingest_satellite_product
from ingestion.ingest_imd import ingest as ingest_weather
from ingestion.common import load
from orca.config import settings


# Demo regions with documented bounding boxes
DEMO_REGIONS = {
    "south_tamil_nadu": {
        "name": "South Tamil Nadu Coast",
        "center": (8.8, 78.3),  # Near Tuticorin
        "min_lat": 8.0,
        "max_lat": 9.5,
        "min_lon": 77.5,
        "max_lon": 79.5,
        "erddap_zlev": 0,  # Surface level for satellite data
    },
    "arabian_sea": {
        "name": "Arabian Sea",
        "center": (15.0, 70.0),
        "min_lat": 8.0,
        "max_lat": 20.0,
        "min_lon": 65.0,
        "max_lon": 75.0,
        "erddap_zlev": 0,
    },
    "bay_of_bengal": {
        "name": "Bay of Bengal",
        "center": (15.0, 87.0),
        "min_lat": 8.0,
        "max_lat": 22.0,
        "min_lon": 85.0,
        "max_lon": 92.0,
        "erddap_zlev": 0,
    },
}

# ERDDAP dataset configurations
ERDDAP_PRODUCTS = {
    "sst": {
        "dataset_id": "NOAA_AVHRR_AMSR_datasets",
        "variable": "sst",
        "product": "sst",
        "unit": "°C",
    },
    "chlorophyll": {
        "dataset_id": "incois_oceansat2_datasets",
        "variable": "CHL",
        "product": "chlorophyll",
        "unit": "mg/m³",
    },
    "wind_speed": {
        "dataset_id": "ascat_daily_datasets",
        "variable": "wind_speed",
        "product": "wind_speed",
        "unit": "m/s",
    },
}


@dataclass
class MockSatelliteReading:
    """Mock satellite data for demo when ERDDAP is unavailable."""
    product: str
    value: float
    unit: str
    lon: float
    lat: float
    observed_at: str
    source: str


def generate_mock_satellite_readings(
    region: dict[str, Any],
    date_str: str,
    product_type: str = "sst",
) -> list[dict[str, Any]]:
    """
    Generate realistic mock satellite readings for demo purposes.

    These are synthetic but plausible values based on typical ocean conditions
    in the Indian Ocean. In production, these would come from ERDDAP.

    Args:
        region: Region dict with min/max lat/lon
        date_str: ISO date string (YYYY-MM-DD)
        product_type: 'sst', 'chlorophyll', or 'wind_speed'

    Returns:
        List of reading dicts ready for database insertion
    """
    readings = []
    min_lat = region["min_lat"]
    max_lat = region["max_lat"]
    min_lon = region["min_lon"]
    max_lon = region["max_lon"]

    # Create a grid of points across the region
    lat_step = (max_lat - min_lat) / 4
    lon_step = (max_lon - min_lon) / 4

    # Realistic value ranges for the Indian Ocean
    value_ranges = {
        "sst": (24, 32),  # 24-32°C typical
        "chlorophyll": (0.1, 5.0),  # 0.1-5 mg/m³
        "wind_speed": (3, 12),  # 3-12 m/s
    }

    units = {
        "sst": "°C",
        "chlorophyll": "mg/m³",
        "wind_speed": "m/s",
    }

    product_names = {
        "sst": "sst",
        "chlorophyll": "chlorophyll",
        "wind_speed": "wind_speed",
    }

    v_min, v_max = value_ranges.get(product_type, (0, 100))
    unit = units.get(product_type, "unknown")
    product = product_names.get(product_type, product_type)

    # Generate readings on a regular grid
    for i in range(5):
        for j in range(5):
            lat = min_lat + (i + 0.5) * lat_step
            lon = min_lon + (j + 0.5) * lon_step

            # Add some realistic variation
            import random
            value = v_min + random.random() * (v_max - v_min)

            readings.append(
                {
                    "product": product,
                    "value": round(value, 2),
                    "unit": unit,
                    "lon": round(lon, 4),
                    "lat": round(lat, 4),
                    "observed_at": f"{date_str}T00:00:00Z",
                    "source": f"Mock {product_type.upper()} (demo)",
                }
            )

    return readings


def populate_satellite_data(
    region: dict[str, Any],
    date_str: str,
    database_url: str,
    skip_live: bool = False,
) -> int:
    """
    Populate satellite_readings table from ERDDAP or mock data.

    Args:
        region: Region dict from DEMO_REGIONS
        date_str: ISO date string (YYYY-MM-DD)
        database_url: PostgreSQL connection string
        skip_live: If True, use mock data only

    Returns:
        Total number of readings loaded
    """
    total = 0
    iso_date = f"{date_str}T00:00:00Z"

    for product_key, config in ERDDAP_PRODUCTS.items():
        if skip_live:
            print(f"  Generating mock {product_key} readings...")
            readings = generate_mock_satellite_readings(region, date_str, product_key)
            for reading in readings:
                try:
                    load(
                        database_url,
                        """INSERT INTO satellite_readings 
                           (product, value, unit, location, observed_at, source)
                           VALUES (%(product)s, %(value)s, %(unit)s, 
                                   ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), 
                                   %(observed_at)s, %(source)s)""",
                        reading,
                    )
                    total += 1
                except Exception as e:
                    print(f"    Error inserting {product_key}: {e}")
        else:
            print(f"  Fetching {product_key} from ERDDAP...")
            try:
                count = ingest_satellite_product(
                    config["dataset_id"],
                    config["variable"],
                    config["product"],
                    config["unit"],
                    iso_date,
                    region["min_lat"],
                    region["max_lat"],
                    region["min_lon"],
                    region["max_lon"],
                    database_url,
                )
                print(f"    Loaded {count} {product_key} readings")
                total += count
            except Exception as e:
                print(f"    ERDDAP unavailable ({type(e).__name__})")
                print(f"    Falling back to mock data...")
                readings = generate_mock_satellite_readings(region, date_str, product_key)
                for reading in readings:
                    try:
                        load(
                            database_url,
                            """INSERT INTO satellite_readings 
                               (product, value, unit, location, observed_at, source)
                               VALUES (%(product)s, %(value)s, %(unit)s, 
                                       ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), 
                                       %(observed_at)s, %(source)s)""",
                            reading,
                        )
                        total += 1
                    except Exception as e2:
                        print(f"    Error inserting mock {product_key}: {e2}")

    return total


def populate_argo_data(
    region: dict[str, Any],
    date_str: str,
    database_url: str,
    skip_live: bool = False,
    days_lookback: int = 3,
) -> int:
    """
    Populate satellite_readings table with validated ARGO float data.

    Args:
        region: Region dict from DEMO_REGIONS
        date_str: ISO date string (YYYY-MM-DD)
        database_url: PostgreSQL connection string
        skip_live: If True, skip (no mock data for ARGO)
        days_lookback: Number of days to look back for ARGO data

    Returns:
        Number of readings loaded
    """
    if skip_live:
        print("  Skipping ARGO data (live only)")
        return 0

    print("  Fetching validated ARGO float data from ERDDAP...")
    try:
        start_dt = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days_lookback)
        end_dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)

        count = ingest_argo(
            start_dt.isoformat() + "Z",
            end_dt.isoformat() + "Z",
            region["min_lat"],
            region["max_lat"],
            region["min_lon"],
            region["max_lon"],
            database_url,
        )
        print(f"    Loaded {count} validated ARGO readings")
        return count
    except Exception as e:
        print(f"    ARGO ingestion failed: {e}")
        return 0


def populate_weather_alerts(
    region_key: str,
    database_url: str,
    skip_live: bool = False,
) -> int:
    """
    Populate weather_alerts table from IMD API or scraped data.

    Args:
        region_key: Key in DEMO_REGIONS
        database_url: PostgreSQL connection string
        skip_live: If True, skip (no mock data for weather alerts)

    Returns:
        Number of alerts loaded
    """
    if skip_live:
        print("  Skipping weather alerts (live only)")
        return 0

    print("  Fetching weather alerts from IMD...")
    try:
        count = ingest_weather(region_key, database_url)
        print(f"    Loaded {count} weather alerts")
        return count
    except Exception as e:
        print(f"    IMD ingestion failed: {e}")
        return 0


def populate_boundaries(
    region: dict[str, Any],
    database_url: str,
    skip_live: bool = False,
) -> int:
    """
    Populate boundary_geometries table with EEZ and MPA data.

    For now, this is a placeholder. In production, this would:
    1. Download EEZ data from Marine Regions
    2. Download MPA data from Protected Planet
    3. Load via ogr2ogr and normalize

    Args:
        region: Region dict (used for reference only, loads India-wide boundaries)
        database_url: PostgreSQL connection string
        skip_live: If True, use mock India EEZ only

    Returns:
        Number of boundaries loaded
    """
    print("  Setting up boundary geometries...")

    if skip_live:
        # Create minimal mock EEZ for demo
        print("  Generating mock India EEZ...")
        # India's approximate EEZ bounding box
        india_eez_coords = [
            [65.0, 8.0],
            [77.0, 8.0],
            [92.0, 8.0],
            [92.0, 22.0],
            [77.0, 22.0],
            [65.0, 22.0],
            [65.0, 8.0],
        ]
        try:
            load(
                database_url,
                """INSERT INTO boundary_geometries (boundary_type, name, geom, metadata)
                   VALUES (%(boundary_type)s, %(name)s, 
                           ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326),
                           %(metadata)s::jsonb)""",
                {
                    "boundary_type": "EEZ",
                    "name": "India EEZ (Mock)",
                    "geometry": json.dumps({"type": "Polygon", "coordinates": [india_eez_coords]}),
                    "metadata": json.dumps({"source": "demo", "note": "Approximate bounding box"}),
                },
            )
            return 1
        except Exception as e:
            print(f"  Error loading mock EEZ: {e}")
            return 0

    print("  TODO: Download and load real EEZ from Marine Regions")
    print("  TODO: Download and load MPA data from Protected Planet")
    return 0


def populate_pfz_data(
    region: dict[str, Any],
    date_str: str,
    database_url: str,
    skip_live: bool = False,
) -> int:
    """
    Populate pfz_bulletins table with Potential Fishing Zone data.

    According to the spec, PFZ data has no documented public machine-readable API.
    This function demonstrates the recommended fallback: manually curated demo data.

    Args:
        region: Region dict from DEMO_REGIONS
        date_str: ISO date string (YYYY-MM-DD)
        database_url: PostgreSQL connection string
        skip_live: If True, use mock curated data

    Returns:
        Number of bulletins loaded
    """
    print("  Setting up PFZ bulletins...")

    # Mock PFZ data for South Tamil Nadu (from the spec example)
    mock_pfz_zones = [
        {
            "region_name": "South Tamil Nadu",
            "issued_date": date_str,
            "zone_geom": {
                "type": "Polygon",
                "coordinates": [[[78.1, 8.7], [78.3, 8.7], [78.3, 8.9], [78.1, 8.9], [78.1, 8.7]]],
            },
            "chlorophyll_level": "moderate",
            "sst_range": "28-29°C",
            "advisory_text": "PFZ identified ~15km SE of Tuticorin landing centre",
            "source": "INCOIS (Mock)",
        },
        {
            "region_name": "South Tamil Nadu Offshore",
            "issued_date": date_str,
            "zone_geom": {
                "type": "Polygon",
                "coordinates": [[[78.5, 8.5], [79.0, 8.5], [79.0, 9.0], [78.5, 9.0], [78.5, 8.5]]],
            },
            "chlorophyll_level": "high",
            "sst_range": "29-30°C",
            "advisory_text": "Extended PFZ zone showing productive fishing conditions",
            "source": "INCOIS (Mock)",
        },
    ]

    count = 0
    for zone in mock_pfz_zones:
        try:
            load(
                database_url,
                """INSERT INTO pfz_bulletins 
                   (region_name, issued_date, zone_geom, chlorophyll_level, sst_range, advisory_text, source)
                   VALUES (%(region_name)s, %(issued_date)s,
                           ST_SetSRID(ST_GeomFromGeoJSON(%(zone_geom)s), 4326),
                           %(chlorophyll_level)s, %(sst_range)s, %(advisory_text)s, %(source)s)""",
                {
                    "region_name": zone["region_name"],
                    "issued_date": zone["issued_date"],
                    "zone_geom": json.dumps(zone["zone_geom"]),
                    "chlorophyll_level": zone["chlorophyll_level"],
                    "sst_range": zone["sst_range"],
                    "advisory_text": zone["advisory_text"],
                    "source": zone["source"],
                },
            )
            count += 1
        except Exception as e:
            print(f"  Error loading PFZ zone: {e}")

    print(f"  Loaded {count} PFZ zones")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        required=False,
        help="PostgreSQL connection string (default: ORCA_DATABASE_URL env)",
    )
    parser.add_argument(
        "--region",
        choices=list(DEMO_REGIONS.keys()),
        default="south_tamil_nadu",
        help="Demo region to populate",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date for data ingestion (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--skip-live-sources",
        action="store_true",
        help="Use mock data only (useful if ERDDAP/IMD APIs are unavailable)",
    )

    args = parser.parse_args()

    if not args.database_url:
        raise ValueError("No database URL provided. Set ORCA_DATABASE_URL or use --database-url")

    region = DEMO_REGIONS[args.region]
    print(f"\nPopulating ORCA database for {region['name']}")
    print(f"Date: {args.date}")
    print(f"Bounds: lat=[{region['min_lat']}, {region['max_lat']}], "
          f"lon=[{region['min_lon']}, {region['max_lon']}]")
    print()

    total = 0

    print("1. Satellite data (SST, chlorophyll, wind)...")
    total += populate_satellite_data(region, args.date, args.database_url, args.skip_live_sources)

    print("\n2. ARGO float ground truth...")
    total += populate_argo_data(region, args.date, args.database_url, args.skip_live_sources)

    print("\n3. Weather alerts...")
    total += populate_weather_alerts(args.region, args.database_url, args.skip_live_sources)

    print("\n4. Boundary geometries (EEZ, MPA)...")
    total += populate_boundaries(region, args.database_url, args.skip_live_sources)

    print("\n5. Potential Fishing Zone (PFZ) bulletins...")
    total += populate_pfz_data(region, args.date, args.database_url, args.skip_live_sources)

    print(f"\n✓ Successfully loaded {total} records into ORCA database")
    print(f"  Ready for demo queries from {', '.join(region['name'].split())}")


if __name__ == "__main__":
    main()
