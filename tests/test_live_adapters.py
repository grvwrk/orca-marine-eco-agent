from datetime import date, datetime, timezone

from ingestion.ingest_pfz import parse_bulletin
from ingestion.ingest_source import ingest_source
from ingestion.ingest_weather import normalize_alert
from ingestion.source_catalog import SOURCES, get_source
from orca.knowledge.models import EvidenceCard
from orca.knowledge.retrieval import EmptyRepository, HybridRepository
from orca.knowledge.retrieval import PostGISRepository


class FakeDatabase:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.query = ""

    def fetch_all(self, query: str, params: dict) -> list[dict]:
        self.query = query
        return self.rows


def test_postgis_repository_converts_real_pfz_rows_to_evidence() -> None:
    database = FakeDatabase([{"id": 7, "region_name": "Konkan", "issued_date": date(2026, 9, 7), "advisory_text": "Use daylight hours.", "source": "INCOIS", "lat": 15.1, "lon": 73.7, "distance_m": 2400}])
    cards = PostGISRepository(database).nearest_pfz(15.1, 73.7, date(2026, 9, 7))
    assert cards[0].raw_ref == {"table": "pfz_bulletins", "id": 7}
    assert "2.4 km" in cards[0].content
    assert "ST_Distance" in database.query


def test_ingestion_normalizes_geojson_properties() -> None:
    feature = {"type": "Feature", "properties": {"region_name": "Konkan", "issued_date": "2026-09-07"}, "geometry": {"type": "Polygon", "coordinates": [[[73.7, 15.0], [73.8, 15.0], [73.8, 15.1], [73.7, 15.0]]]}}
    bulletin = parse_bulletin(feature, "https://example.test/pfz.geojson")
    assert bulletin.region_name == "Konkan"
    assert '"type": "Polygon"' in bulletin.geometry

    alert = normalize_alert({"properties": {"alert_type": "lightning", "valid_from": "2026-09-07T00:00:00Z"}, "geometry": feature["geometry"]})
    assert alert["alert_type"] == "lightning"
    assert alert["geometry"]


def test_source_catalog_contains_the_supplied_public_sources() -> None:
    assert {source.key for source in SOURCES} >= {"pfz_advisory", "oceansat_open_data", "imd_api", "incois_osf", "marine_regions_eez", "protected_planet", "gebco"}
    assert get_source("imd_api").adapter == "weather"


def test_reference_sources_fail_before_fetching() -> None:
    try:
        ingest_source("gebco", "postgresql://unused")
    except ValueError as error:
        assert "no ingestion adapter" in str(error)
    else:
        raise AssertionError("reference-only sources must not be sent to a vector adapter")


def test_live_sources_require_a_machine_readable_url() -> None:
    try:
        ingest_source("imd_api", "postgresql://unused")
    except ValueError as error:
        assert "requires --url" in str(error)
    else:
        raise AssertionError("portal URLs must not be treated as data feeds")


class FakeRepository:
    def nearest_pfz(self, lat, lon, as_of):
        return [EvidenceCard(type="pfz_bulletin", content="database PFZ", source="database")]

    def active_weather_alerts(self, lat, lon, start, end):
        return []

    def ocean_state_at(self, lat, lon, forecast_time):
        return [EvidenceCard(type="ocean_state", content="database OSF", source="database")]

    def satellite_trend(self, lat, lon, product, lookback_days):
        return []

    def boundary_proximity(self, lat, lon, boundary_type):
        return EvidenceCard(type="boundary_check", content="database boundary", source="database")


class FakeLiveRepository:
    def nearest_pfz(self, lat, lon, as_of):
        return [EvidenceCard(type="pfz_bulletin", content="fresh API PFZ", source="api")]

    def active_weather_alerts(self, lat, lon, start, end):
        return []

    def ocean_state_at(self, lat, lon, forecast_time):
        return []

    def satellite_trend(self, lat, lon, product, lookback_days):
        return [EvidenceCard(type="satellite_reading", content="fresh API satellite", source="api")]

    def boundary_proximity(self, lat, lon, boundary_type):
        return EvidenceCard(type="boundary_check", content="api boundary", source="api")


def test_hybrid_repository_prefers_fresh_api_evidence() -> None:
    repository = HybridRepository(FakeRepository(), FakeLiveRepository())
    assert repository.nearest_pfz(15.1, 73.7, date(2026, 9, 8))[0].source == "api"
    assert repository.satellite_trend(15.1, 73.7, "sst", 30)[0].source == "api"


def test_hybrid_repository_falls_back_when_api_has_no_data() -> None:
    repository = HybridRepository(FakeRepository(), FakeLiveRepository())
    assert repository.ocean_state_at(15.1, 73.7, datetime.now(timezone.utc))[0].source == "database"
    assert repository.active_weather_alerts(15.1, 73.7, datetime.now(timezone.utc), datetime.now(timezone.utc)) == []


def test_empty_repository_supports_api_only_mode_without_fabricating_data() -> None:
    repository = EmptyRepository()
    assert repository.nearest_pfz(15.1, 73.7, date(2026, 9, 8)) == []
    assert repository.boundary_proximity(15.1, 73.7, "EEZ").confidence == 0.0
