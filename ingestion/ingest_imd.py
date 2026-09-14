"""
IMD weather alerts ingestion with fallback to public web scraping.

This module handles two paths:
1. IMD API (if whitelisting is approved) - returns GeoJSON MultiPolygon geometries
2. Fallback: Scrape public fishermen warning pages from mausam.imd.gov.in

The fallback is a real, load-bearing path for the demo dataset, not just a backup.
"""

import argparse
import re
from datetime import datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

from ingestion.common import load
from orca.config import settings


IMD_API_BASE = "https://api.imd.gov.in/api/v1"
IMD_MAUSAM_BASE = "https://mausam.imd.gov.in"

# Fishermen warning URLs by region (public pages, no API key needed)
FISHERMEN_WARNING_URLS = {
    "tamil_nadu": f"{IMD_MAUSAM_BASE}/imd_latest/contents/index_fisherman.php",
    "chennai_rsmc": f"{IMD_MAUSAM_BASE}/chennai/",
}

# Demo region bounding boxes (lat, lon)
DEMO_REGIONS = {
    "south_tamil_nadu": {"min_lat": 8.0, "max_lat": 9.5, "min_lon": 77.5, "max_lon": 79.5},
    "arabian_sea": {"min_lat": 8.0, "max_lat": 20.0, "min_lon": 65.0, "max_lon": 75.0},
}


def try_imd_api(endpoint: str, alert_type: str, database_url: str) -> int:
    """
    Try to fetch from IMD API if whitelisting is approved.

    Expected endpoint format (from IMD reference):
    /api/v1/fishmenwarning
    /api/v1/seaareaibulletin
    /api/v1/coastalbulletin

    Response format (confirmed for Cyclone Wind Warning):
    {
        "status": true,
        "message": "alert type name",
        "data": {
            "27kt": {"type": "MultiPolygon", "coordinates": [...]},
            ...
        }
    }

    Args:
        endpoint: IMD API endpoint name (e.g., "fishmenwarning")
        alert_type: Alert type label for weather_alerts table
        database_url: PostgreSQL connection

    Returns:
        Number of alerts loaded, or 0 if API unavailable
    """
    if not settings.imd_api_url or not settings.imd_api_key:
        return 0

    try:
        url = f"{settings.imd_api_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {settings.imd_api_key}"}
        resp = requests.get(
            url,
            timeout=settings.request_timeout_seconds,
            headers=headers,
            verify=settings.ca_bundle,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("status"):
            return 0

        # Extract multipolygon geometries
        count = 0
        alert_data = data.get("data", {})
        for intensity, geom in alert_data.items():
            if geom.get("type") == "MultiPolygon":
                try:
                    load(
                        database_url,
                        """INSERT INTO weather_alerts 
                           (alert_type, severity, affected_area, valid_from, valid_until, description, source)
                           VALUES (%(alert_type)s, %(severity)s, 
                                   ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326),
                                   %(valid_from)s, %(valid_until)s, %(description)s, %(source)s)""",
                        {
                            "alert_type": alert_type,
                            "severity": intensity,
                            "geometry": __import__("json").dumps(geom),
                            "valid_from": datetime.utcnow().isoformat(),
                            "valid_until": (datetime.utcnow() + timedelta(days=1)).isoformat(),
                            "description": f"{alert_type}: {intensity}",
                            "source": "IMD API",
                        },
                    )
                    count += 1
                except Exception as e:
                    print(f"Failed to insert alert: {e}")

        return count

    except requests.RequestException as e:
        print(f"IMD API not available: {e}; falling back to scraper")
        return 0


def scrape_fishermen_warnings(url: str, region_bounds: dict[str, float], database_url: str) -> int:
    """
    Scrape IMD fishermen warning public web page.

    This is the fallback when API whitelisting isn't ready. Extracts alert text
    and creates approximate bounding box geometries based on region_bounds.

    Args:
        url: URL to fishermen warning page
        region_bounds: Dict with min_lat, max_lat, min_lon, max_lon for the region
        database_url: PostgreSQL connection

    Returns:
        Number of alerts loaded
    """
    try:
        resp = requests.get(
            url,
            timeout=settings.request_timeout_seconds,
            verify=settings.ca_bundle,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
    except requests.RequestException as e:
        print(f"Failed to fetch page {url}: {e}")
        return 0

    count = 0

    # Look for alert-related text blocks
    # Pattern: Fishermen warning sections typically contain region names and advisories
    text_content = soup.get_text()

    # Extract warning blocks by looking for common patterns
    # This is a heuristic approach since the HTML structure may vary
    warning_pattern = r"(?:fishermen warning|fishing advisory|cyclone|gale|depression)(.*?)(?=fishermen warning|fishing advisory|cyclone|gale|depression|$)"
    warnings = re.findall(warning_pattern, text_content, re.IGNORECASE | re.DOTALL)

    if not warnings:
        # If regex extraction fails, try to find any alert-like divs or sections
        alert_divs = soup.find_all(["div", "section", "p"], class_=re.compile(r"alert|warning|advisory", re.I))
        warnings = [div.get_text(strip=True) for div in alert_divs if div.get_text(strip=True)]

    # For each warning found, create an alert entry with the region's bounding box
    for warning_text in warnings:
        if not warning_text.strip():
            continue

        # Determine alert severity from keywords
        severity = "moderate"
        if any(word in warning_text.lower() for word in ["gale", "cyclone", "severe", "danger"]):
            severity = "high"
        elif any(word in warning_text.lower() for word in ["caution", "wind", "rough"]):
            severity = "moderate"

        # Create a bounding box polygon from region bounds
        min_lat = region_bounds["min_lat"]
        max_lat = region_bounds["max_lat"]
        min_lon = region_bounds["min_lon"]
        max_lon = region_bounds["max_lon"]

        polygon_coords = [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ]
        geometry = {"type": "Polygon", "coordinates": polygon_coords[0]}

        try:
            load(
                database_url,
                """INSERT INTO weather_alerts 
                   (alert_type, severity, affected_area, valid_from, valid_until, description, source)
                   VALUES (%(alert_type)s, %(severity)s, 
                           ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326),
                           %(valid_from)s, %(valid_until)s, %(description)s, %(source)s)""",
                {
                    "alert_type": "Fishermen Warning",
                    "severity": severity,
                    "geometry": __import__("json").dumps(geometry),
                    "valid_from": datetime.utcnow().isoformat(),
                    "valid_until": (datetime.utcnow() + timedelta(days=1)).isoformat(),
                    "description": warning_text[:500],  # Truncate to reasonable length
                    "source": "IMD Mausam (Scraped)",
                },
            )
            count += 1
        except Exception as e:
            print(f"Failed to insert scraped alert: {e}")

    return count


def ingest(region_key: str = "south_tamil_nadu", database_url: str = "") -> int:
    """
    Ingest weather alerts from IMD, preferring API but falling back to scraper.

    Args:
        region_key: Key to demo region in DEMO_REGIONS
        database_url: PostgreSQL connection string

    Returns:
        Number of alerts ingested
    """
    if not database_url:
        database_url = settings.database_url
    if not database_url:
        raise ValueError("No database_url provided or configured")

    region_bounds = DEMO_REGIONS.get(region_key)
    if not region_bounds:
        raise ValueError(f"Unknown region: {region_key}")

    total_count = 0

    # Try IMD API endpoints (will return 0 if not whitelisted)
    print("Attempting IMD API (if whitelisted)...")
    total_count += try_imd_api("fishmenwarning", "Fishermen Warning", database_url)
    total_count += try_imd_api("seaareaibulletin", "Sea Area Bulletin", database_url)
    total_count += try_imd_api("coastalbulletin", "Coastal Bulletin", database_url)

    # Fallback: Scrape public pages
    print("Scraping IMD public pages as fallback...")
    for url in FISHERMEN_WARNING_URLS.values():
        total_count += scrape_fishermen_warnings(url, region_bounds, database_url)

    return total_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        default="south_tamil_nadu",
        choices=list(DEMO_REGIONS.keys()),
        help="Demo region for alert geometry",
    )
    parser.add_argument("--database-url", required=True, help="PostgreSQL connection string")
    parser.add_argument("--api-only", action="store_true", help="Try API only, skip scraper fallback")

    args = parser.parse_args()

    if args.api_only:
        # Try only API path
        count = try_imd_api("fishmenwarning", "Fishermen Warning", args.database_url)
        print(f"Loaded {count} alerts from IMD API")
    else:
        # Full fallback path
        count = ingest(args.region, args.database_url)
        print(f"Loaded {count} weather alerts from IMD ({args.region})")
