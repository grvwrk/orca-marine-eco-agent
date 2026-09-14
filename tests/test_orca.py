import json
from datetime import date

from fastapi.testclient import TestClient

from ingestion.import_historic_sqlite import import_file
from orca.api.main import app
from orca.knowledge.database import SQLiteDatabase
from orca.knowledge.models import AgentResult, EvidenceCard
from orca.knowledge.retrieval import SQLiteRepository, boundary_proximity, nearest_pfz
from orca.orchestration.graph import plan, run_graph


def test_live_empty_retrievals_produce_a_low_confidence_result(monkeypatch) -> None:
    import agents.marine_data_discovery as marine_agent

    monkeypatch.setattr(marine_agent, "nearest_pfz", lambda lat, lon: [])
    state = run_graph("Where is the nearest potential fishing zone today?")
    result = state.results["marine_data_discovery"]
    assert result.evidence == []
    assert result.confidence == 0.0
    assert "No current PFZ advisory" in result.summary


def test_nearest_pfz_returns_traceable_evidence() -> None:
    card = nearest_pfz(15.1, 73.75)[0]
    assert card.type == "pfz_bulletin"
    assert card.raw_ref == {"table": "pfz_bulletins", "id": 1, "issued_date": card.raw_ref["issued_date"]}


def test_importer_replaces_seeded_demo_rows(tmp_path) -> None:
    db_path = tmp_path / "historical.sqlite3"
    db = SQLiteDatabase(str(db_path))
    db.execute("INSERT INTO pfz_bulletins (region_name, issued_date, zone_geom, lat, lon, advisory_text, source) VALUES (?, ?, ?, ?, ?, ?, ?)", ("Demo PFZ", "2026-09-14", '{"type":"Polygon"}', 15.1, 73.75, "seeded row", "INCOIS demo"))

    archive = tmp_path / "pfz_historical.json"
    archive.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[73.4, 15.0], [73.8, 15.0], [73.8, 15.5], [73.4, 15.5], [73.4, 15.0]]]},
            "properties": {
                "region_name": "Historical PFZ",
                "issued_date": "2025-09-02",
                "valid_until": "2025-09-05",
                "advisory_text": "real historical bulletin",
                "source": "INCOIS",
                "source_url": "https://example.org/historical"
            }
        }]
    }), encoding="utf-8")

    assert import_file(db, archive, date(2025, 1, 1), date(2025, 12, 31)) == 1
    rows = db.fetch_all("SELECT region_name, source FROM pfz_bulletins")
    assert rows == [{"region_name": "Historical PFZ", "source": "INCOIS"}]


def test_boundary_check_is_a_single_evidence_card() -> None:
    card = boundary_proximity(15.1, 73.75)
    assert card.type == "boundary_check"
    assert "Goa coastal protected zone" in card.content


def test_chat_contract() -> None:
    client = TestClient(app)
    response = client.post("/chat", json={"session_id": "demo", "message": "Where is the nearest potential fishing zone today?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["response_text"]
    assert payload["evidence"][0]["type"] == "pfz_bulletin"
    assert payload["map_data"]["type"] == "FeatureCollection"
    assert payload["mission_brief"]["assessment"]
    assert payload["evidence_coverage"]["total_domains"] == 5
    assert payload["lineage"]


def test_demo_queries_select_specialist_paths() -> None:
    queries = [
        "are there any lightning or cyclone alerts in my area?",
        "what are the tide, weather, and sea conditions near my fishing location?",
        "why has fish productivity declined in this region?",
        "which zones should be avoided due to hazards or boundary restrictions?",
        "what is the safest route for my vessel given current conditions?",
    ]
    for query in queries:
        state = run_graph(query)
        assert state.response_text
        assert state.results


def test_follow_up_reuses_session_location_and_detects_language() -> None:
    client = TestClient(app)
    first = client.post("/chat", json={"session_id": "follow-up", "message": "weather near my location", "lat": 14.5, "lon": 74.2})
    second = client.post("/chat", json={"session_id": "follow-up", "message": "what about tomorrow?"})
    assert first.status_code == second.status_code == 200
    assert second.json()["map_data"]["features"][0]["geometry"]["coordinates"] == [74.2, 14.5]
    tamil = client.post("/chat", json={"session_id": "tamil", "message": "கடல் நிலை என்ன?"})
    assert tamil.json()["lang"] == "ta"


def test_chat_deduplicates_shared_underlying_evidence(monkeypatch) -> None:
    import orca.api.main as api
    from orca.orchestration.graph import OrcaState
    from orca.knowledge.models import AgentTask

    card = EvidenceCard(type="pfz_bulletin", content="same row", source="INCOIS", raw_ref={"table": "pfz_bulletins", "id": 42})
    result = AgentResult(task_id="one", agent="marine_data_discovery", evidence=[card], summary="same row", confidence=0.9)
    state = OrcaState(query="pfz", tasks=[AgentTask(task_id="one", agent="marine_data_discovery")], results={"marine_data_discovery": result}, response_text="brief")
    monkeypatch.setattr(api, "run_graph", lambda query, location: state)
    response = TestClient(api.app).post("/chat", json={"session_id": "dedupe", "message": "pfz"})
    assert response.status_code == 200
    assert len(response.json()["evidence"]) == 1


def test_sqlite_retrieval_rejects_distant_records(tmp_path) -> None:
    repository = SQLiteRepository(SQLiteDatabase(str(tmp_path / "distance.sqlite3")))
    assert repository.nearest_pfz(0.0, 0.0, date.today()) == []


def test_same_agent_tasks_merge_evidence() -> None:
    state = run_graph("Can I fish here tomorrow morning?", location=(15.1, 73.75))
    geospatial = state.results["geospatial_reasoning"]
    assert len(geospatial.evidence) >= 2
    assert any(card.type == "pfz_bulletin" for card in geospatial.evidence)
    assert any(card.type == "boundary_check" for card in geospatial.evidence)


def test_explicit_place_name_resolution_for_key_regions() -> None:
    from orca.orchestration.graph import resolve_location

    expected = {
        "Gujarat": (22.7, 69.0),
        "Chennai": (13.08, 80.27),
        "Goa": (15.1, 73.75),
        "Kerala": (10.2, 76.1),
    }
    for name, target in expected.items():
        resolved = resolve_location(f"Near {name} I am considering fishing tomorrow morning.")
        assert abs(resolved[0] - target[0]) < 0.75
        assert abs(resolved[1] - target[1]) < 0.75


def test_signature_query_contract_and_counterfactuals() -> None:
    query = "Near Gujarat, I’m considering fishing tomorrow morning. Find the best nearby area by balancing fishing potential, weather risk, sea state, and protected-area restrictions. Compare the top candidates, explain your recommendation, show what evidence supports it, and tell me what would need to change for your recommendation to change."
    state = run_graph(query, location=(15.1, 73.75))
    payload = state.response_text.lower()

    assert "gujarat" in payload
    assert "candidate" in payload.lower() or "candidates" in payload.lower()
    assert "counterfactual" in payload.lower() or "what would need to change" in payload.lower() or "scenario simulation" in payload.lower()
    assert "risk" in payload.lower()
    assert "evidence" in payload.lower() or "pfz" in payload.lower() or "weather" in payload.lower()

    pfz = [card for card in state.results["marine_data_discovery"].evidence if card.type == "pfz_bulletin"]
    weather = [card for card in state.results["weather_intelligence"].evidence if card.type == "weather_alert"]
    ocean = [card for card in state.results["ocean_analytics"].evidence if card.type == "ocean_state"]
    boundary = [card for card in state.results["geospatial_reasoning"].evidence if card.type == "boundary_check"]
    assert pfz
    assert weather or ocean
    assert boundary

    for card in pfz + weather + ocean + boundary:
        if card.lat is not None and card.lon is not None:
            assert abs(card.lat - state.location[0]) < 2.0 or abs(card.lon - state.location[1]) < 2.0

    synthesis = state.results["risk_assessment"]
    assert synthesis.summary


def test_demo_fixture_status_and_coverage_labels() -> None:
    query = "Near Gujarat, I’m considering fishing tomorrow morning. Find the best nearby area by balancing fishing potential, weather risk, sea state, and protected-area restrictions. Compare the top candidates, explain your recommendation, show what evidence supports it, and tell me what would need to change for your recommendation to change."
    state = run_graph(query, location=(15.1, 73.75))
    assert state.response_text
    assert "demo fixture" in state.response_text.lower() or "not live verified" in state.response_text.lower()

    coverage = state.response_text.lower()
    assert "pfz" in coverage
    assert "weather" in coverage
    assert "ocean" in coverage
    assert "boundary" in coverage
