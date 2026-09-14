CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS pfz_bulletins (
    id SERIAL PRIMARY KEY,
    region_name TEXT NOT NULL,
    issued_date DATE NOT NULL,
    valid_until DATE,
    zone_geom GEOMETRY(Polygon, 4326) NOT NULL,
    chlorophyll_level TEXT,
    sst_range TEXT,
    advisory_text TEXT,
    source TEXT DEFAULT 'INCOIS',
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pfz_geom ON pfz_bulletins USING GIST (zone_geom);

CREATE TABLE IF NOT EXISTS boundary_geometries (
    id SERIAL PRIMARY KEY,
    boundary_type TEXT NOT NULL,
    name TEXT NOT NULL,
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_boundary_geom ON boundary_geometries USING GIST (geom);

CREATE TABLE IF NOT EXISTS weather_alerts (
    id SERIAL PRIMARY KEY,
    alert_type TEXT NOT NULL,
    severity TEXT,
    affected_area GEOMETRY(Polygon, 4326) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    description TEXT,
    source TEXT DEFAULT 'IMD',
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alert_geom ON weather_alerts USING GIST (affected_area);

CREATE TABLE IF NOT EXISTS ocean_state_forecast (
    id SERIAL PRIMARY KEY,
    location GEOMETRY(Point, 4326) NOT NULL,
    forecast_time TIMESTAMPTZ NOT NULL,
    wave_height_m NUMERIC,
    wind_speed_kmh NUMERIC,
    current_speed_ms NUMERIC,
    tide_level_m NUMERIC,
    source TEXT DEFAULT 'INCOIS OSF',
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_osf_geom ON ocean_state_forecast USING GIST (location);

CREATE TABLE IF NOT EXISTS satellite_readings (
    id SERIAL PRIMARY KEY,
    product TEXT NOT NULL CHECK (product IN ('chlorophyll', 'sst')),
    value NUMERIC NOT NULL,
    unit TEXT,
    location GEOMETRY(Point, 4326) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source TEXT DEFAULT 'Oceansat-3 OCM',
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sat_geom ON satellite_readings USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_sat_time ON satellite_readings (observed_at);

CREATE TABLE IF NOT EXISTS evidence_cards (
    id SERIAL PRIMARY KEY,
    card_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    location GEOMETRY(Point, 4326),
    valid_time TIMESTAMPTZ,
    confidence NUMERIC DEFAULT 1.0,
    raw_ref JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
