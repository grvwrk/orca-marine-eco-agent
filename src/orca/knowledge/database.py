from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from pathlib import Path
import sqlite3

from orca.config import settings


class DatabaseUnavailable(RuntimeError):
    pass


class PostGISDatabase:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.database_url
        if not self.url:
            raise DatabaseUnavailable("ORCA_DATABASE_URL is not configured")

    @contextmanager
    def connection(self) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as error:
            raise DatabaseUnavailable("Install the live dependency group: pip install -e .[live]") from error
        connection = psycopg.connect(self.url)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fetch_all(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                columns = [column.name for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute(self, query: str, params: dict[str, Any]) -> None:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)


class SQLiteDatabase:
    """Local database for development and portable historical imports."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or settings.sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS pfz_bulletins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_name TEXT NOT NULL,
                    issued_date TEXT NOT NULL,
                    valid_until TEXT,
                    zone_geom TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    chlorophyll_level TEXT,
                    sst_range TEXT,
                    advisory_text TEXT,
                    source TEXT DEFAULT 'INCOIS',
                    source_url TEXT,
                    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sqlite_pfz_date ON pfz_bulletins (issued_date);
                CREATE TABLE IF NOT EXISTS weather_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT NOT NULL,
                    severity TEXT,
                    affected_area TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    description TEXT,
                    source TEXT DEFAULT 'IMD',
                    source_url TEXT,
                    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sqlite_weather_dates ON weather_alerts (valid_from, valid_until);
                CREATE TABLE IF NOT EXISTS ocean_state_forecast (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    forecast_time TEXT NOT NULL,
                    wave_height_m REAL,
                    wind_speed_kmh REAL,
                    current_speed_ms REAL,
                    tide_level_m REAL,
                    source TEXT DEFAULT 'INCOIS OSF',
                    source_url TEXT,
                    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sqlite_ocean_time ON ocean_state_forecast (forecast_time);
                CREATE TABLE IF NOT EXISTS satellite_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    source TEXT DEFAULT 'Oceansat-3 OCM',
                    source_url TEXT,
                    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sqlite_satellite_product_time ON satellite_readings (product, observed_at);
                CREATE TABLE IF NOT EXISTS boundary_geometries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    boundary_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    geom TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    metadata TEXT,
                    source_url TEXT,
                    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        self.seed_demo_data()

    def seed_demo_data(self) -> None:
        if self.fetch_all("SELECT 1 FROM pfz_bulletins LIMIT 1"):
            return
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        base_records = [
            ("pfz_bulletins", ("Konkan PFZ", "2026-09-14", None, '{\"type\":\"Polygon\"}', 15.10, 73.75, "high", "28-30C", "Potential fishing zone with elevated chlorophyll and productive shelf waters.", "INCOIS demo", "https://demo.local/pfz")),
            ("weather_alerts", ("lightning", "moderate", '{\"type\":\"Polygon\"}', 15.10, 73.75, today, None, "No severe cyclone alert in the seeded demo zone.", "IMD demo", "https://demo.local/weather")),
            ("ocean_state_forecast", (15.10, 73.75, today, 0.8, 18.0, 0.7, 1.2, "INCOIS OSF demo", "https://demo.local/osf")),
            ("satellite_readings", ("chlorophyll", 1.24, "mg/m3", 15.10, 73.75, today, "Oceansat-3 OCM demo", "https://demo.local/satellite")),
            ("satellite_readings", ("sst", 29.8, "C", 15.10, 73.75, today, "Oceansat-3 OCM demo", "https://demo.local/satellite")),
            ("boundary_geometries", ("MPA", "Goa coastal protected zone", '{\"type\":\"Polygon\"}', 15.14, 73.78, '{\"kind\":\"demo\"}', "https://demo.local/boundaries")),
            ("boundary_geometries", ("EEZ", "Indian maritime boundary", '{\"type\":\"Polygon\"}', 15.05, 73.40, '{\"kind\":\"demo\"}', "https://demo.local/boundaries")),
        ]
        for table, values in base_records:
            if table == "pfz_bulletins":
                self.execute("INSERT INTO pfz_bulletins (region_name, issued_date, valid_until, zone_geom, lat, lon, chlorophyll_level, sst_range, advisory_text, source, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            elif table == "weather_alerts":
                self.execute("INSERT INTO weather_alerts (alert_type, severity, affected_area, lat, lon, valid_from, valid_until, description, source, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            elif table == "ocean_state_forecast":
                self.execute("INSERT INTO ocean_state_forecast (lat, lon, forecast_time, wave_height_m, wind_speed_kmh, current_speed_ms, tide_level_m, source, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            elif table == "satellite_readings":
                self.execute("INSERT INTO satellite_readings (product, value, unit, lat, lon, observed_at, source, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
            elif table == "boundary_geometries":
                self.execute("INSERT INTO boundary_geometries (boundary_type, name, geom, lat, lon, metadata, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)", values)

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.connection() as connection:
            connection.execute(query, params)
