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
    assert card.raw_ref == {"table": "pfz_bulletins", "id": 1, "region_name": "Goa Offshore PFZ", "issued_date": card.raw_ref["issued_date"]}


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


def test_signature_query_structured_contract() -> None:
    query = "Near Gujarat, I’m considering fishing tomorrow morning. Find the best nearby area by balancing fishing potential, weather risk, sea state, and protected-area restrictions. Compare the top candidates, explain your recommendation, show what evidence supports it, and tell me what would need to change for your recommendation to change."
    response = TestClient(app).post("/chat", json={"session_id": "strict-signature", "message": query, "lat": 15.1, "lon": 73.75})
    assert response.status_code == 200
    payload = response.json()
    brief = payload["mission_brief"]
    candidates = brief["candidate_summary"]
    assert candidates
    assert all(candidate["distance_km"] <= 200 for candidate in candidates)
    assert brief["eligible_candidates"] == candidates
    assert brief["excluded_candidates"]
    assert all(candidate["distance_km"] > 200 for candidate in brief["excluded_candidates"])
    assert not ({candidate["id"] for candidate in brief["excluded_candidates"]} & {candidate["id"] for candidate in candidates})
    assert len({candidate["name"] for candidate in candidates}) == len(candidates)
    assert len({candidate["id"] for candidate in candidates}) == len(candidates)
    assert all(candidate["distance_km"] is not None for candidate in candidates)
    assert all(candidate["fishing_potential"] for candidate in candidates)
    assert all(candidate["opportunity_score"] is not None for candidate in candidates)
    assert all(candidate["weather_risk"] is not None and candidate["sea_state_risk"] is not None for candidate in candidates)
    assert [candidate["score"] for candidate in candidates] == sorted((candidate["score"] for candidate in candidates), reverse=True)
    assert brief["selected_candidate"]["id"] in {candidate["id"] for candidate in candidates}

    resolved = payload["resolved_location"]
    assert resolved["place"] == "Gujarat"
    assert (resolved["lat"], resolved["lon"]) == (22.7, 69.0)
    assert brief["resolved_location"] == {"place": "Gujarat", "lat": 22.7, "lon": 69.0, "source": "explicit_query"}
    assert all(abs(candidate["lat"] - resolved["lat"]) < 10 or abs(candidate["lon"] - resolved["lon"]) < 10 for candidate in candidates)

    evidence = payload["evidence"]
    persisted_keys = [(card["raw_ref"].get("table"), card["raw_ref"].get("id")) for card in evidence if card.get("raw_ref", {}).get("table") is not None and card.get("raw_ref", {}).get("id") is not None]
    evidence_keys = [("record", *key) for key in persisted_keys] + [("generated", card["type"], card["source"], card["content"]) for card in evidence if card.get("raw_ref", {}).get("id") is None]
    assert len(persisted_keys) == len(set(persisted_keys))
    assert len(evidence) == len(evidence_keys) == len(set(evidence_keys))
    assert all(candidate["evidence_refs"] for candidate in candidates)
    assert all(any(ref.get("id") == candidate["id"] for ref in candidate["evidence_refs"]) for candidate in candidates)

    risk = payload["risk_decomposition"]
    assert all(key in risk for key in ("overall", "weather", "waves", "wind", "current", "tide", "boundary", "primary_driver"))
    assert risk[risk["primary_driver"]] > 0
    scenarios = brief["counterfactuals"]
    assert scenarios
    assert all(scenario["current_assessment"] and scenario["current_driver"] and scenario["changed_condition"] and scenario["resulting_assessment"] for scenario in scenarios)

    assert {brief["provenance"], brief["provider_verification"]} == {"DEMO FIXTURE", "NOT LIVE VERIFIED"}
    assert {"fishing_potential", "operational_safety", "recommendation", "boundary_status", "confidence_limitation"} <= set(brief)
    assert {"PFZ", "WEATHER", "OCEAN", "BOUNDARY"} <= set(payload["evidence_coverage"]["available"])
    assert "SATELLITE" in payload["evidence_coverage"]["missing_domains"]
    assert {"User query", "Specialist agents", "Candidate comparison", "Reporting-agent synthesis"} <= set(payload["lineage"])
    assert "boundary_reasoning" in {item["agent"] for item in payload["agent_trace"]}
    assert payload["risk_decomposition"]["boundary"] == 0
    trace_by_agent = {item["agent"]: item["summary"] for item in payload["agent_trace"]}
    assert "PFZ geospatial comparison completed" not in trace_by_agent.get("boundary_reasoning", "")
    assert "MPA status" in trace_by_agent["boundary_reasoning"]
    assert brief["decision_rationale"]
    assert "Gujarat Gulf of Kutch" in payload["response_text"]
    assert "CAUTION" in payload["response_text"]
    assert len(payload["response_text"].split()) < 100
    assert "pfz_bulletins" not in payload["response_text"]
    assert "raw_ref" not in payload["response_text"]
    assert "CANDIDATES" not in payload["response_text"]
    assert "SPECIALIST SUMMARY" not in payload["response_text"]
    assert "EVIDENCE COVERAGE" not in payload["response_text"]
    assert brief["selected_candidate"]["name"] in brief["decision_rationale"]
    assert "fishing potential" in brief["decision_rationale"].lower()
    assert "caution" in brief["decision_rationale"].lower()
    assert brief["primary_positive"] in brief["decision_rationale"]
    assert brief["primary_limitation"] in brief["decision_rationale"]
    assert brief["primary_risk_driver"] == payload["risk_decomposition"]["primary_driver"]
    assert brief["scenario_groups"]["downgrade_if"]
    assert brief["scenario_groups"]["improve_if"]
    assert brief["decision_balance"]["distance_km"] == brief["selected_candidate"]["distance_km"]

    chennai = TestClient(app).post("/chat", json={"session_id": "strict-chennai", "message": "Near Chennai, assess the marine risks and compare nearby fishing candidates.", "lat": 15.1, "lon": 73.75}).json()
    assert chennai["resolved_location"]["place"] == "Chennai"
    assert (chennai["resolved_location"]["lat"], chennai["resolved_location"]["lon"]) == (13.08, 80.27)


def test_calm_conditions_do_not_produce_saturated_risk() -> None:
    state = run_graph("What are the calm sea conditions near Kerala?", location=(10.2, 76.1))
    risk = __import__("agents.reporting", fromlist=["_extract_risk_profile"])._extract_risk_profile([card for result in state.results.values() for card in result.evidence])
    assert risk["overall"] < 100
    assert risk["overall"] < 70


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
