import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str | None = os.getenv("ORCA_DATABASE_URL")
    demo_mode: bool = os.getenv("ORCA_DEMO_MODE", "0") == "1"
    use_sqlite: bool = os.getenv("ORCA_USE_SQLITE", "1") == "1"
    sqlite_path: str = os.getenv("ORCA_SQLITE_PATH", "data/orca.sqlite3")
    request_timeout_seconds: float = float(os.getenv("ORCA_REQUEST_TIMEOUT", "15"))
    ca_bundle: str | bool = os.getenv("ORCA_CA_BUNDLE") or True
    feed_cache_ttl_seconds: float = float(os.getenv("ORCA_FEED_CACHE_TTL", "60"))
    max_useful_distance_km: float = float(os.getenv("ORCA_MAX_USEFUL_DISTANCE_KM", "200"))
    pfz_feed_url: str | None = os.getenv("ORCA_PFZ_FEED_URL") or None
    imd_api_url: str | None = os.getenv("ORCA_IMD_API_URL") or None
    osf_feed_url: str | None = os.getenv("ORCA_OSF_FEED_URL") or None
    satellite_feed_url: str | None = os.getenv("ORCA_SATELLITE_FEED_URL") or None
    boundaries_feed_url: str | None = os.getenv("ORCA_BOUNDARIES_FEED_URL") or None
    imd_api_key: str | None = os.getenv("ORCA_IMD_API_KEY") or None
    mosdac_token: str | None = os.getenv("ORCA_MOSDAC_TOKEN") or None
    wdpa_token: str | None = os.getenv("ORCA_WDPA_TOKEN") or None


settings = Settings()
