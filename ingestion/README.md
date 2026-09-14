# Ingestion adapters

The demo runs with seeded retrieval data. Production ingestion jobs should normalize each source into the tables in `db/schema.sql`, preserving the upstream URL or bulletin identifier in the row metadata. These adapters are intentionally separate from orchestration so a failed feed can produce an explicit zero-confidence result instead of stopping the API.

## Overview

The ingestion pipeline populates the ORCA PostGIS database with real, verified ocean data from public sources:

| Source | Data Type | Module | Status |
|--------|-----------|--------|--------|
| INCOIS ERDDAP | Satellite (SST, chlorophyll, wind) | `ingest_erddap.py` | ✓ Implemented |
| INCOIS ERDDAP | ARGO float validation | `ingest_argo.py` | ✓ Implemented |
| IMD API / Scraper | Weather alerts & cyclone warnings | `ingest_imd.py` | ✓ Implemented (fallback ready) |
| Marine Regions | EEZ boundaries | `ingest_boundaries.py` | ✓ Implemented |
| Protected Planet | Marine Protected Areas | `ingest_boundaries.py` | ✓ Implemented |
| INCOIS | PFZ bulletins | `ingest_pfz.py` | ✓ Implemented (with manual curation fallback) |
| INCOIS | Ocean state forecast | `ingest_osf.py` | ✓ Implemented |

## Quick Start: Demo Dataset

To populate the database with a complete demo dataset:

```bash
# Install dependencies with live data support
pip install -e ".[live]"

# Run full population (tries live sources, falls back to mock data)
python ingestion/populate_demo_dataset.py \
    --database-url "postgresql://user:pass@localhost/orca" \
    --region south_tamil_nadu \
    --date 2026-09-10

# Run with mock data only (no network calls)
python ingestion/populate_demo_dataset.py \
    --database-url "postgresql://user:pass@localhost/orca" \
    --skip-live-sources
```

The `populate_demo_dataset.py` orchestrator handles:
- ERDDAP griddap satellite data with graceful fallback to realistic mock readings
- ARGO float ground truth with QC filtering
- IMD weather alerts (API or web scraper)
- Boundary geometries (EEZ, MPA)
- PFZ bulletins (mock curated data matching the spec)

## Module Details

### `ingest_erddap.py` — Satellite data from INCOIS ERDDAP

Fetches gridded data from INCOIS's public ERDDAP server using value-based constraints (avoiding index errors).

**Datasets:**
- `NOAA_AVHRR_AMSR_datasets` → SST (Sea Surface Temperature)
- `incois_oceansat2_datasets` → Chlorophyll and Kd490
- `ascat_daily_datasets` → Wind speed and stress

**Features:**
- Automatically converts ERDDAP grid responses to point readings
- Handles multi-dimensional arrays (time, latitude, longitude)
- Skips null/NaN values
- No authentication required

**Example usage:**
```bash
python ingestion/ingest_erddap.py \
    NOAA_AVHRR_AMSR_datasets sst "2026-09-10T00:00:00Z" \
    --min-lat 8.0 --max-lat 9.5 \
    --min-lon 77.5 --max-lon 79.5 \
    --database-url "postgresql://..."
```

### `ingest_argo.py` — Validated ARGO float ground truth

Fetches ARGO float measurements from INCOIS ERDDAP tabledap with quality control filtering.

**Key features:**
- Filters by QC flag (only QC=1 "good" readings are loaded)
- Provides validated temperature and salinity as ground truth
- Useful for model validation and anomaly detection
- No authentication required

**QC convention:** ARGO uses flag 1=good, 0=no QC, 2-8=suspect/bad. Only 1 is loaded.

**Example usage:**
```bash
python ingestion/ingest_argo.py \
    "2026-09-01T00:00:00Z" "2026-09-10T23:59:59Z" \
    --min-lat 8.0 --max-lat 9.5 \
    --min-lon 77.5 --max-lon 79.5 \
    --database-url "postgresql://..."
```

### `ingest_imd.py` — Weather alerts with fallback scraper

Fetches cyclone, gale, and fishermen warnings from IMD with intelligent fallback.

**Paths:**
1. **Preferred:** IMD public API (requires IP whitelisting approval)
   - Returns GeoJSON MultiPolygon geometries directly
   - Endpoints: `/fishmenwarning`, `/seaareaibulletin`, `/coastalbulletin`
2. **Fallback:** Public web scraper (always available)
   - Scrapes `mausam.imd.gov.in/imd_latest/contents/index_fisherman.php`
   - Extracts alert text and creates region-based geometries
   - No authentication required

The fallback scraper is a load-bearing path for hackathon/demo use, not a fallback of last resort.

**Example usage:**
```bash
# Automatic fallback if IP whitelisting not approved
python ingestion/ingest_imd.py \
    --region south_tamil_nadu \
    --database-url "postgresql://..."

# API-only (fails if not whitelisted)
python ingestion/ingest_imd.py \
    --region south_tamil_nadu \
    --api-only \
    --database-url "postgresql://..."
```

**Environment variables:**
- `ORCA_IMD_API_URL`: IMD API base URL (when whitelisted)
- `ORCA_IMD_API_KEY`: API key (if required)

### `ingest_boundaries.py` — EEZ and MPA geometries

Loads maritime boundaries from open datasets.

**Data sources:**
- **EEZ:** Marine Regions (`marineregions.org`) — India's Exclusive Economic Zone
- **MPA:** Protected Planet / WDPA — Marine Protected Areas (India)

**Supports:**
- GeoJSON and shapefile inputs
- `ogr2ogr` loading from downloadable sources
- Automatic metadata tagging (boundary_type, name)

**Example usage:**
```bash
# Download GeoJSON from Marine Regions, then:
python ingestion/ingest_boundaries.py \
    "https://example.com/eez_india.geojson" \
    --database-url "postgresql://..."
```

### `ingest_pfz.py` — Potential Fishing Zone bulletins

Loads PFZ data from normalized JSON/GeoJSON sources.

**Status:** No public machine-readable API found (per spec). The recommended path:

1. Check for undocumented endpoints by monitoring network requests in the INCOIS WebGIS (`incois.gov.in/geoportal/MFASPFZ/index.html`)
2. If no endpoint found, manually curate PFZ zones from published advisories
3. Use the mock curated dataset provided in `populate_demo_dataset.py`

**Example usage:**
```bash
python ingestion/ingest_pfz.py \
    "https://example.com/pfz_export.geojson" \
    --database-url "postgresql://..."
```

### `ingest_osf.py` — Ocean state forecast points

Loads INCOIS ocean state forecast (waves, wind, currents, tide).

**Expects:** GeoJSON/JSON FeatureCollection with Point geometries

**Example usage:**
```bash
python ingestion/ingest_osf.py \
    "https://incois.gov.in/api/osf_export" \
    --database-url "postgresql://..."
```

### `ingest_satellite.py` — Generic satellite point data

Base adapter for point-based satellite readings (legacy/fallback).

**Example usage:**
```bash
python ingestion/ingest_satellite.py \
    "https://example.com/satellite_points.geojson" \
    --database-url "postgresql://..."
```

### `ingest_weather.py` — Generic weather alert data

Base adapter for GeoJSON weather alert features.

**Expected format:**
```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [...]},
    "properties": {
      "alert_type": "Cyclone Warning",
      "severity": "high",
      "valid_from": "2026-09-10T00:00:00Z",
      "valid_until": "2026-09-11T00:00:00Z",
      "description": "..."
    }
  }]
}
```

**Example usage:**
```bash
python ingestion/ingest_weather.py \
    "https://example.com/weather_alerts.geojson" \
    --database-url "postgresql://..."
```

## Source Catalog

The `source_catalog.py` maintains metadata for all sources:
- Source URL (for reference/documentation)
- Ingestion adapter name
- Environment variable for feed URL
- Notes on usage (API requirements, limitations, etc.)

**To list all configured sources:**
```bash
python -c "from ingestion.source_catalog import SOURCES; [print(s.key) for s in SOURCES]"
```

## Verified Working Sources (as of 2026-09-10)

✓ **INCOIS ERDDAP griddap** — Confirmed datasets and variables
✓ **INCOIS ERDDAP tabledap** — ARGO floats with QC flags
✓ **IMD public pages** — Fishermen warnings accessible without registration
✗ **IMD API** — Pending IP whitelisting approval (fallback ready)
✗ **INCOIS PFZ machine-readable API** — No documented endpoint found; manual curation used

## Configuration

Set environment variables for live data access:

```bash
export ORCA_DATABASE_URL="postgresql://orca_user:password@localhost/orca"
export ORCA_IMD_API_URL="https://api.imd.gov.in/api/v1"  # When whitelisted
export ORCA_IMD_API_KEY="your-key-here"
export ORCA_REQUEST_TIMEOUT=30  # Seconds
```

Or in `.env` file (loaded by `orca.config`).

## Testing

```bash
# Test with mock data only
pytest tests/

# Test live sources (requires network + database)
pytest tests/ --live

# Generate demo dataset
python ingestion/populate_demo_dataset.py --skip-live-sources --database-url "..."
```

## Architecture Notes

- **Adapters are stateless:** Each call to an ingestion function is independent; failures don't affect other sources.
- **Graceful degradation:** Mock data is used if live sources unavailable (for demo purposes).
- **PostGIS normalization:** All adapters convert source data to (lon, lat) points and geometries using EPSG:4326.
- **QC filtering:** Validated data (ARGO, etc.) is explicitly filtered before storage.
- **Metadata preservation:** Source attribution is stored in every row for traceability.
