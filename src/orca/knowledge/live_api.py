"""Read normalized provider feeds directly for freshness-sensitive queries."""

from datetime import date, datetime, timezone
from math import cos, radians, sqrt
from threading import Lock
from typing import Any, Callable

import requests

from ingestion.common import features, fetch_json, properties
from orca.config import settings

from .models import EvidenceCard


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x = radians(lon2 - lon1) * cos(radians((lat1 + lat2) / 2))
    y = radians(lat2 - lat1)
    return 6371.0 * sqrt(x * x + y * y)


def _coordinate_pairs(value: Any) -> list[tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        return [(float(value[0]), float(value[1]))]
    if isinstance(value, (list, tuple)):
        pairs = []
        for child in value:
            pairs.extend(_coordinate_pairs(child))
        return pairs
    return []


def _coordinates(feature: dict[str, Any], data: dict[str, Any]) -> tuple[float, float]:
    geometry = feature.get("geometry", {})
    coordinates = geometry.get("coordinates")
    pairs = _coordinate_pairs(coordinates)
    if pairs:
        lon = sum(pair[0] for pair in pairs) / len(pairs)
        lat = sum(pair[1] for pair in pairs) / len(pairs)
        return lat, lon
    return float(data.get("lat", 0.0)), float(data.get("lon", 0.0))


def _timestamp(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback or datetime.now(timezone.utc)


class LiveApiRepository:
    """Repository for normalized JSON/GeoJSON feeds configured in the environment."""

    def __init__(self, ttl_seconds: float | None = None) -> None:
        self.ttl_seconds = ttl_seconds or settings.feed_cache_ttl_seconds
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = Lock()

    def _records(self, key: str, url: str | None, token: str | None = None) -> list[dict[str, Any]]:
        if not url:
            return []
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.ttl_seconds:
                return cached[1]
        headers = {"Authorization": f"Bearer {token}"} if token else None
        records = list(features(fetch_json(url, headers=headers)))
        with self._lock:
            self._cache[key] = (now, records)
        return records

    def _safe(self, loader: Callable[[], list[EvidenceCard]]) -> list[EvidenceCard]:
        try:
            return loader()
        except (KeyError, TypeError, ValueError, OSError, requests.RequestException):
            return []

    def nearest_pfz(self, lat: float, lon: float, as_of: date, comparison: bool = False) -> list[EvidenceCard]:
        def load() -> list[EvidenceCard]:
            cards = []
            for feature in self._records("pfz", settings.pfz_feed_url):
                data = properties(feature)
                item_lat, item_lon = _coordinates(feature, data)
                issued = _timestamp(data.get("issued_date"))
                cards.append(EvidenceCard(type="pfz_bulletin", content=f"Potential fishing zone: {data['region_name']}, {_distance_km(lat, lon, item_lat, item_lon):.1f} km away. {data.get('advisory_text') or 'No additional advisory.'}", source=data.get("source", "INCOIS"), lat=item_lat, lon=item_lon, valid_time=issued, raw_ref={"source_url": settings.pfz_feed_url, "region_name": data["region_name"]}))
            return sorted(cards, key=lambda card: _distance_km(lat, lon, card.lat or 0.0, card.lon or 0.0))[:5]

        return self._safe(load)

    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]:
        def load() -> list[EvidenceCard]:
            cards = []
            for feature in self._records("weather", settings.imd_api_url, settings.imd_api_key):
                data = properties(feature)
                valid_from = _timestamp(data["valid_from"])
                valid_until = _timestamp(data.get("valid_until"), end) if data.get("valid_until") else end
                if valid_from <= end and valid_until >= start:
                    item_lat, item_lon = _coordinates(feature, data)
                    cards.append(EvidenceCard(type="weather_alert", content=f"{data['alert_type']} alert ({data.get('severity') or 'unknown'}): {data.get('description') or 'No description.'}", source=data.get("source", "IMD"), lat=item_lat or lat, lon=item_lon or lon, valid_time=valid_from, raw_ref={"source_url": settings.imd_api_url, "alert_type": data["alert_type"]}))
            return cards

        return self._safe(load)

    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]:
        def load() -> list[EvidenceCard]:
            cards = []
            for feature in self._records("osf", settings.osf_feed_url):
                data = properties(feature)
                item_lat, item_lon = _coordinates(feature, data)
                valid_time = _timestamp(data["forecast_time"])
                if valid_time >= forecast_time:
                    cards.append((abs(item_lat - lat) + abs(item_lon - lon), EvidenceCard(type="ocean_state", content=f"Forecast: waves {data.get('wave_height_m')} m, wind {data.get('wind_speed_kmh')} km/h, current {data.get('current_speed_ms')} m/s, tide {data.get('tide_level_m')} m.", source=data.get("source", "INCOIS OSF"), lat=item_lat, lon=item_lon, valid_time=valid_time, raw_ref={"source_url": settings.osf_feed_url, "forecast_time": data["forecast_time"]})))
            return [card for _, card in sorted(cards, key=lambda item: (item[1].valid_time, item[0]))[:1]]

        return self._safe(load)

    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]:
        def load() -> list[EvidenceCard]:
            readings = []
            for feature in self._records("satellite", settings.satellite_feed_url, settings.mosdac_token):
                data = properties(feature)
                if data.get("product") != product:
                    continue
                item_lat, item_lon = _coordinates(feature, data)
                readings.append((float(data["value"]), _timestamp(data["observed_at"]), item_lat, item_lon))
            if not readings:
                return []
            latest = max(readings, key=lambda item: item[1])
            unit = next((properties(feature).get("unit", "") for feature in self._records("satellite", settings.satellite_feed_url, settings.mosdac_token) if properties(feature).get("product") == product), "")
            return [EvidenceCard(type="satellite_reading", content=f"{product.capitalize()} feed has {len(readings)} observations; latest value is {latest[0]} {unit}.", source="Oceansat-3 OCM", lat=latest[2], lon=latest[3], valid_time=latest[1], raw_ref={"source_url": settings.satellite_feed_url, "product": product, "lookback_days": lookback_days})]

        return self._safe(load)

    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard:
        return EvidenceCard(type="boundary_check", content=f"Live {boundary_type} boundary geometry is configured for ingestion but direct boundary lookup is served from PostGIS.", source="PostGIS boundary registry", lat=lat, lon=lon, confidence=0.0, raw_ref={"table": "boundary_geometries", "boundary_type": boundary_type})