"""Evidence retrieval backed by PostGIS, with an explicit demo repository."""

from datetime import date, datetime, timedelta, timezone
from math import cos, radians, sqrt
from typing import Protocol

from orca.config import settings

from .database import PostGISDatabase, SQLiteDatabase
from .live_api import LiveApiRepository
from .models import EvidenceCard


class Repository(Protocol):
    def nearest_pfz(self, lat: float, lon: float, as_of: date) -> list[EvidenceCard]: ...
    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]: ...
    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]: ...
    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]: ...
    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard: ...


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x = radians(lon2 - lon1) * cos(radians((lat1 + lat2) / 2))
    y = radians(lat2 - lat1)
    return 6371.0 * sqrt(x * x + y * y)


class DemoRepository:
    def nearest_pfz(self, lat: float, lon: float, as_of: date) -> list[EvidenceCard]:
        distance = _distance_km(lat, lon, 15.10, 73.75)
        return [EvidenceCard(type="pfz_bulletin", content=f"Potential fishing zone: Konkan coast, approximately {distance:.1f} km from your location. Chlorophyll is elevated and sea-surface temperature is favourable.", source="INCOIS demo bulletin", lat=15.10, lon=73.75, valid_time=datetime.now(timezone.utc), raw_ref={"table": "pfz_bulletins", "id": 1, "issued_date": str(as_of)})]

    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]:
        return [EvidenceCard(type="weather_alert", content="No active cyclone, lightning, or high-wind alert is seeded for this demo area.", source="IMD demo feed", lat=lat, lon=lon, valid_time=end, raw_ref={"table": "weather_alerts", "status": "clear"})]

    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]:
        return [EvidenceCard(type="ocean_state", content="Forecast conditions: wave height 0.8 m, wind 18 km/h, and a moderate tide.", source="INCOIS OSF demo feed", lat=lat, lon=lon, valid_time=forecast_time, raw_ref={"table": "ocean_state_forecast", "id": 1})]

    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]:
        return [EvidenceCard(type="satellite_reading", content=f"{product.capitalize()} trend over the last {lookback_days} days is 12% below the preceding baseline in the demo region.", source="Oceansat-3 OCM demo feed", lat=lat, lon=lon, valid_time=datetime.now(timezone.utc), raw_ref={"table": "satellite_readings", "product": product, "lookback_days": lookback_days})]

    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard:
        boundary = ("Goa coastal protected zone", 15.24, 73.82, 12.0) if boundary_type == "MPA" else ("Indian Maritime Boundary", 15.05, 73.40, 38.0)
        distance = _distance_km(lat, lon, boundary[1], boundary[2])
        status = "inside or very close to" if distance <= boundary[3] else "outside"
        return EvidenceCard(type="boundary_check", content=f"Your position is {status} {boundary[0]} ({distance:.1f} km to its reference point).", source="ISRO marine boundary registry (demo)", lat=lat, lon=lon, valid_time=datetime.now(timezone.utc), raw_ref={"table": "boundary_geometries", "boundary_type": boundary_type, "name": boundary[0]})


class EmptyRepository:
    """No-data fallback for API-only deployments and unavailable providers."""

    def nearest_pfz(self, lat: float, lon: float, as_of: date) -> list[EvidenceCard]:
        return []

    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]:
        return []

    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]:
        return []

    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]:
        return []

    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard:
        return EvidenceCard(type="boundary_check", content=f"No {boundary_type} boundary data is available for this location.", source="Configured data sources", lat=lat, lon=lon, confidence=0.0, raw_ref={"boundary_type": boundary_type})


class PostGISRepository:
    def __init__(self, database: PostGISDatabase | None = None) -> None:
        self.database = database or PostGISDatabase()

    def nearest_pfz(self, lat: float, lon: float, as_of: date) -> list[EvidenceCard]:
        rows = self.database.fetch_all("""SELECT id, region_name, issued_date, advisory_text, source, ST_Y(ST_Centroid(zone_geom)) AS lat, ST_X(ST_Centroid(zone_geom)) AS lon, ST_Distance(zone_geom::geography, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography) AS distance_m FROM pfz_bulletins WHERE issued_date <= %(as_of)s AND (valid_until IS NULL OR valid_until >= %(as_of)s) ORDER BY zone_geom::geography <-> ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography LIMIT 5""", {"lat": lat, "lon": lon, "as_of": as_of})
        return [EvidenceCard(type="pfz_bulletin", content=f"Potential fishing zone: {row['region_name']}, {row['distance_m'] / 1000:.1f} km away. {row.get('advisory_text') or 'No additional advisory.'}", source=row.get("source") or "INCOIS", lat=row["lat"], lon=row["lon"], valid_time=datetime.combine(row["issued_date"], datetime.min.time(), tzinfo=timezone.utc), raw_ref={"table": "pfz_bulletins", "id": row["id"]}) for row in rows]

    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]:
        rows = self.database.fetch_all("""SELECT id, alert_type, severity, description, source, valid_from FROM weather_alerts WHERE valid_from <= %(end)s AND (valid_until IS NULL OR valid_until >= %(start)s) AND ST_Intersects(affected_area, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)) ORDER BY valid_from DESC""", {"lat": lat, "lon": lon, "start": start, "end": end})
        return [EvidenceCard(type="weather_alert", content=f"{row['alert_type']} alert ({row.get('severity') or 'unknown'}): {row.get('description') or 'No description.'}", source=row.get("source") or "IMD", lat=lat, lon=lon, valid_time=row["valid_from"], raw_ref={"table": "weather_alerts", "id": row["id"]}) for row in rows]

    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]:
        rows = self.database.fetch_all("""SELECT id, forecast_time, wave_height_m, wind_speed_kmh, current_speed_ms, tide_level_m, source, ST_Y(location) AS lat, ST_X(location) AS lon FROM ocean_state_forecast WHERE forecast_time >= %(forecast_time)s ORDER BY location <-> ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326) LIMIT 1""", {"lat": lat, "lon": lon, "forecast_time": forecast_time})
        return [EvidenceCard(type="ocean_state", content=f"Forecast: waves {row['wave_height_m']} m, wind {row['wind_speed_kmh']} km/h, current {row['current_speed_ms']} m/s, tide {row['tide_level_m']} m.", source=row.get("source") or "INCOIS OSF", lat=row["lat"], lon=row["lon"], valid_time=row["forecast_time"], raw_ref={"table": "ocean_state_forecast", "id": row["id"]}) for row in rows]

    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        rows = self.database.fetch_all("""SELECT product, AVG(value) FILTER (WHERE observed_at >= %(start)s) AS recent_avg, AVG(value) FILTER (WHERE observed_at < %(start)s) AS baseline_avg, MAX(observed_at) AS observed_at, source FROM satellite_readings WHERE product = %(product)s AND ST_DWithin(location::geography, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography, 100000) GROUP BY product, source""", {"lat": lat, "lon": lon, "product": product, "start": start})
        cards = []
        for row in rows:
            change = ((float(row["recent_avg"]) - float(row["baseline_avg"])) / float(row["baseline_avg"]) * 100) if row["baseline_avg"] else None
            content = f"{product.capitalize()} changed {change:.1f}% over the last {lookback_days} days." if change is not None else f"Insufficient baseline for {product} trend."
            cards.append(EvidenceCard(type="satellite_reading", content=content, source=row.get("source") or "Oceansat-3 OCM", lat=lat, lon=lon, valid_time=row["observed_at"], raw_ref={"table": "satellite_readings", "product": product}))
        return cards

    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard:
        rows = self.database.fetch_all("""SELECT id, name, ST_Distance(geom::geography, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography) AS distance_m FROM boundary_geometries WHERE boundary_type = %(boundary_type)s ORDER BY geom::geography <-> ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography LIMIT 1""", {"lat": lat, "lon": lon, "boundary_type": boundary_type})
        if not rows:
            return EvidenceCard(type="boundary_check", content=f"No {boundary_type} boundary data is available for this location.", source="PostGIS boundary registry", lat=lat, lon=lon, confidence=0.0, raw_ref={"table": "boundary_geometries", "boundary_type": boundary_type})
        row = rows[0]
        return EvidenceCard(type="boundary_check", content=f"Nearest {boundary_type} boundary is {row['name']}, {row['distance_m'] / 1000:.1f} km away.", source="PostGIS boundary registry", lat=lat, lon=lon, valid_time=datetime.now(timezone.utc), raw_ref={"table": "boundary_geometries", "id": row["id"]})


class SQLiteRepository:
    """Portable local repository using numeric coordinate columns and haversine ranking."""

    def __init__(self, database: SQLiteDatabase | None = None) -> None:
        self.database = database or SQLiteDatabase()

    @staticmethod
    def _time(value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def nearest_pfz(self, lat: float, lon: float, as_of: date) -> list[EvidenceCard]:
        rows = self.database.fetch_all(
            "SELECT * FROM pfz_bulletins WHERE issued_date <= ? AND (valid_until IS NULL OR valid_until >= ?) ORDER BY issued_date DESC",
            (as_of.isoformat(), as_of.isoformat()),
        )
        rows = [(row, _distance_km(lat, lon, row["lat"], row["lon"])) for row in rows]
        rows = [(row, distance) for row, distance in rows if distance <= settings.max_useful_distance_km]
        rows.sort(key=lambda item: item[1])
        return [EvidenceCard(type="pfz_bulletin", content=f"Potential fishing zone: {row['region_name']}, {distance:.1f} km away. {row.get('advisory_text') or 'No additional advisory.'}", source=row.get("source") or "INCOIS", lat=row["lat"], lon=row["lon"], valid_time=self._time(row.get("issued_date")), distance_km=distance, raw_ref={"table": "pfz_bulletins", "id": row["id"], "issued_date": row.get("issued_date")}) for row, distance in rows[:5]]

    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]:
        rows = self.database.fetch_all("SELECT * FROM weather_alerts WHERE valid_from <= ? AND (valid_until IS NULL OR valid_until >= ?) ORDER BY valid_from DESC", (end.isoformat(), start.isoformat()))
        cards = []
        for row in rows:
            distance = _distance_km(lat, lon, row["lat"], row["lon"])
            if distance <= settings.max_useful_distance_km:
                cards.append(EvidenceCard(type="weather_alert", content=f"{row['alert_type']} alert ({row.get('severity') or 'unknown'}): {row.get('description') or 'No description.'}", source=row.get("source") or "IMD", lat=row["lat"], lon=row["lon"], valid_time=self._time(row.get("valid_from")), distance_km=distance, raw_ref={"table": "weather_alerts", "id": row["id"], "source_url": row.get("source_url")}))
        return cards

    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]:
        rows = self.database.fetch_all("SELECT * FROM ocean_state_forecast WHERE forecast_time >= ? ORDER BY forecast_time ASC", (forecast_time.isoformat(),))
        rows = [(row, _distance_km(lat, lon, row["lat"], row["lon"])) for row in rows]
        rows = [(row, distance) for row, distance in rows if distance <= settings.max_useful_distance_km]
        rows.sort(key=lambda item: (item[1], item[0]["forecast_time"]))
        return [EvidenceCard(type="ocean_state", content=f"Forecast: waves {row['wave_height_m']} m, wind {row['wind_speed_kmh']} km/h, current {row['current_speed_ms']} m/s, tide {row['tide_level_m']} m.", source=row.get("source") or "INCOIS OSF", lat=row["lat"], lon=row["lon"], valid_time=self._time(row.get("forecast_time")), distance_km=distance, raw_ref={"table": "ocean_state_forecast", "id": row["id"], "source_url": row.get("source_url")}) for row, distance in rows[:1]]

    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]:
        rows = self.database.fetch_all("SELECT * FROM satellite_readings WHERE product = ? ORDER BY observed_at DESC", (product,))
        nearby = [row for row in rows if _distance_km(lat, lon, row["lat"], row["lon"]) <= settings.max_useful_distance_km]
        if not nearby:
            return []
        latest = nearby[0]
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        recent = [row["value"] for row in nearby if (self._time(row["observed_at"]) or cutoff) >= cutoff]
        content = f"{product.capitalize()} archive contains {len(nearby)} observations; latest value is {latest['value']} {latest.get('unit') or ''}."
        if recent:
            content += f" {len(recent)} observations fall within the last {lookback_days} days."
        return [EvidenceCard(type="satellite_reading", content=content, source=latest.get("source") or "Satellite archive", lat=latest["lat"], lon=latest["lon"], valid_time=self._time(latest.get("observed_at")), distance_km=_distance_km(lat, lon, latest["lat"], latest["lon"]), raw_ref={"table": "satellite_readings", "id": latest["id"], "product": product})]

    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard:
        rows = self.database.fetch_all("SELECT * FROM boundary_geometries WHERE boundary_type = ?", (boundary_type,))
        rows = [(row, _distance_km(lat, lon, row["lat"], row["lon"])) for row in rows]
        rows = [(row, distance) for row, distance in rows if distance <= settings.max_useful_distance_km]
        rows.sort(key=lambda item: item[1])
        if not rows:
            return EvidenceCard(type="boundary_check", content=f"No {boundary_type} boundary data is available for this location.", source="SQLite boundary registry", lat=lat, lon=lon, confidence=0.0, raw_ref={"table": "boundary_geometries", "boundary_type": boundary_type})
        row, distance = rows[0]
        return EvidenceCard(type="boundary_check", content=f"Nearest {boundary_type} boundary is {row['name']}, {distance:.1f} km away.", source="SQLite boundary registry", lat=row["lat"], lon=row["lon"], valid_time=datetime.now(timezone.utc), distance_km=distance, raw_ref={"table": "boundary_geometries", "id": row["id"], "source_url": row.get("source_url")})


class HybridRepository:
    """Use fresh configured feeds first, with PostGIS or demo data as fallback."""

    def __init__(self, fallback: Repository, live: LiveApiRepository | None = None) -> None:
        self.fallback = fallback
        self.live = live or LiveApiRepository()

    def nearest_pfz(self, lat: float, lon: float, as_of: date) -> list[EvidenceCard]:
        cards = self.live.nearest_pfz(lat, lon, as_of)
        return cards or self.fallback.nearest_pfz(lat, lon, as_of)

    def active_weather_alerts(self, lat: float, lon: float, start: datetime, end: datetime) -> list[EvidenceCard]:
        cards = self.live.active_weather_alerts(lat, lon, start, end)
        return cards or self.fallback.active_weather_alerts(lat, lon, start, end)

    def ocean_state_at(self, lat: float, lon: float, forecast_time: datetime) -> list[EvidenceCard]:
        cards = self.live.ocean_state_at(lat, lon, forecast_time)
        return cards or self.fallback.ocean_state_at(lat, lon, forecast_time)

    def satellite_trend(self, lat: float, lon: float, product: str, lookback_days: int) -> list[EvidenceCard]:
        cards = self.live.satellite_trend(lat, lon, product, lookback_days)
        return cards or self.fallback.satellite_trend(lat, lon, product, lookback_days)

    def boundary_proximity(self, lat: float, lon: float, boundary_type: str) -> EvidenceCard:
        return self.fallback.boundary_proximity(lat, lon, boundary_type)


def get_repository() -> Repository:
    if settings.use_sqlite:
        sqlite_repo = SQLiteRepository()
        try:
            if sqlite_repo.database.fetch_all("SELECT 1 FROM pfz_bulletins LIMIT 1"):
                fallback: Repository = sqlite_repo
            else:
                fallback = DemoRepository()
        except Exception:
            fallback = DemoRepository()
    elif settings.demo_mode:
        fallback = DemoRepository()
    elif any((settings.pfz_feed_url, settings.imd_api_url, settings.osf_feed_url, settings.satellite_feed_url)):
        fallback = EmptyRepository()
    else:
        raise RuntimeError("No repository configured. Set ORCA_DATABASE_URL or ORCA_DEMO_MODE=1.")
    return HybridRepository(fallback)


def nearest_pfz(lat: float, lon: float, as_of: date | None = None) -> list[EvidenceCard]:
    return get_repository().nearest_pfz(lat, lon, as_of or date.today())


def active_weather_alerts(lat: float, lon: float, window_start: datetime | None = None, window_end: datetime | None = None) -> list[EvidenceCard]:
    end = window_end or datetime.now(timezone.utc)
    return get_repository().active_weather_alerts(lat, lon, window_start or end, end)


def ocean_state_at(lat: float, lon: float, forecast_time: datetime | None = None) -> list[EvidenceCard]:
    return get_repository().ocean_state_at(lat, lon, forecast_time or datetime.now(timezone.utc))


def satellite_trend(lat: float, lon: float, product: str, lookback_days: int = 30) -> list[EvidenceCard]:
    return get_repository().satellite_trend(lat, lon, product, lookback_days)


def boundary_proximity(lat: float, lon: float, boundary_type: str = "MPA") -> EvidenceCard:
    return get_repository().boundary_proximity(lat, lon, boundary_type)


def boundary_checks(lat: float, lon: float) -> list[EvidenceCard]:
    return [boundary_proximity(lat, lon, boundary_type) for boundary_type in ("MPA", "EEZ")]


def route_points(start: tuple[float, float], end: tuple[float, float], samples: int = 5) -> list[tuple[float, float]]:
    return [(start[0] + (end[0] - start[0]) * index / (samples - 1), start[1] + (end[1] - start[1]) * index / (samples - 1)) for index in range(samples)]