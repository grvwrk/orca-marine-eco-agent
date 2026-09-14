"""PostGIS query adapter used when a database connection is configured."""

from datetime import date, datetime
from typing import Any


def nearest_pfz_sql(lat: float, lon: float, as_of: date) -> tuple[str, dict[str, Any]]:
    return (
        """SELECT id, region_name, issued_date, chlorophyll_level, sst_range, advisory_text,
                  ST_Y(ST_Centroid(zone_geom)) AS lat, ST_X(ST_Centroid(zone_geom)) AS lon,
                  ST_Distance(zone_geom::geography, ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography) AS distance_m
           FROM pfz_bulletins
          WHERE issued_date <= :as_of AND (valid_until IS NULL OR valid_until >= :as_of)
          ORDER BY zone_geom::geography <-> ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography
          LIMIT 5""",
        {"lat": lat, "lon": lon, "as_of": as_of},
    )


def active_alerts_sql(lat: float, lon: float, window_start: datetime, window_end: datetime) -> tuple[str, dict[str, Any]]:
    return (
        """SELECT id, alert_type, severity, description, source, valid_from, valid_until
             FROM weather_alerts
            WHERE valid_from <= :window_end AND (valid_until IS NULL OR valid_until >= :window_start)
              AND ST_Intersects(affected_area, ST_SetSRID(ST_Point(:lon, :lat), 4326))
            ORDER BY valid_from DESC""",
        {"lat": lat, "lon": lon, "window_start": window_start, "window_end": window_end},
    )
