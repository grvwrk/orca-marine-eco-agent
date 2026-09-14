"""Run one of the normalized ingestion adapters using the source catalog."""

import argparse

from ingestion.ingest_boundaries import ingest as ingest_boundaries
from ingestion.ingest_osf import ingest as ingest_osf
from ingestion.ingest_pfz import ingest as ingest_pfz
from ingestion.ingest_satellite import ingest as ingest_satellite
from ingestion.ingest_weather import ingest as ingest_weather
from ingestion.source_catalog import get_source
from orca.config import settings


ADAPTERS = {
    "boundaries": ingest_boundaries,
    "osf": ingest_osf,
    "pfz": ingest_pfz,
    "satellite": ingest_satellite,
    "weather": ingest_weather,
}

_SETTING_BY_ENV = {
    "ORCA_PFZ_FEED_URL": "pfz_feed_url",
    "ORCA_IMD_API_URL": "imd_api_url",
    "ORCA_OSF_FEED_URL": "osf_feed_url",
    "ORCA_SATELLITE_FEED_URL": "satellite_feed_url",
    "ORCA_BOUNDARIES_FEED_URL": "boundaries_feed_url",
}


def ingest_source(source_key: str, database_url: str, url: str | None = None) -> int:
    source = get_source(source_key)
    if source.adapter is None:
        raise ValueError(f"{source.key} is a reference page and has no ingestion adapter")
    feed_url = url or (getattr(settings, _SETTING_BY_ENV[source.feed_env_var]) if source.feed_env_var else None)
    if feed_url is None:
        raise ValueError(f"{source.key} requires --url or its configured feed environment variable")
    return ADAPTERS[source.adapter](feed_url, database_url)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="source key from ingestion.source_catalog")
    parser.add_argument("--url", help="machine-readable export/API URL; overrides the catalog page URL")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    count = ingest_source(args.source, args.database_url, args.url)
    print(f"loaded {count} records from {args.source}")


if __name__ == "__main__":
    main()