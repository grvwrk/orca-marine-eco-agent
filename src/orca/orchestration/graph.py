from dataclasses import dataclass, field
import os
import re
from typing import Any

from agents import geospatial_reasoning, marine_data_discovery, ocean_analytics, reporting, risk_assessment, weather_intelligence
from orca.knowledge.models import AgentResult, AgentTask

PLACE_COORDS: dict[str, tuple[float, float]] = {
    "gujarat": (22.7, 69.0),
    "goa": (15.1, 73.75),
    "chennai": (13.08, 80.27),
    "kerala": (10.2, 76.1),
}


def resolve_location(query: str, fallback: tuple[float, float] = (15.10, 73.75)) -> tuple[float, float]:
    normalized = " ".join(re.sub(r"[’']", " ", query.lower()).split())
    for place_name, coords in sorted(PLACE_COORDS.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(place_name)}\b", normalized):
            return coords
    return fallback


@dataclass
class OrcaState:
    query: str
    location: tuple[float, float] = (15.10, 73.75)
    tasks: list[AgentTask] = field(default_factory=list)
    results: dict[str, AgentResult] = field(default_factory=dict)
    verdict: str | None = None
    map_data: dict[str, Any] | None = None
    response_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def plan(query: str) -> list[AgentTask]:
    text = query.lower()
    tasks: list[AgentTask] = []
    if any(term in text for term in ("fishing zone", "fishing", "fish", "pfz")):
        tasks.append(AgentTask(task_id="marine-1", agent="marine_data_discovery", params={"need": "pfz"}))
        tasks.append(AgentTask(task_id="geo-1", agent="geospatial_reasoning", params={"mode": "nearest_pfz"}))
    if any(word in text for word in ("weather", "alert", "lightning", "cyclone", "safe", "hazard", "fishing", "fish")):
        tasks.append(AgentTask(task_id="weather-1", agent="weather_intelligence"))
    if any(word in text for word in ("tide", "sea condition", "wave", "current", "safe", "fishing", "fish")):
        tasks.append(AgentTask(task_id="ocean-1", agent="ocean_analytics"))
    if "productivity" in text or "chlorophyll" in text or "declined" in text:
        tasks.append(AgentTask(task_id="ocean-trend-1", agent="ocean_analytics", params={"mode": "trend"}))
    if any(word in text for word in ("boundary", "geofence", "restricted", "avoid", "fishing", "fish")):
        tasks.append(AgentTask(task_id="geo-2", agent="geospatial_reasoning", params={"mode": "boundary_check"}))
    if "route" in text:
        tasks.append(AgentTask(task_id="geo-route-1", agent="geospatial_reasoning", params={"mode": "route"}))
    if any(word in text for word in ("safe", "hazard", "route", "avoid", "fishing", "fish", "weather risk", "sea state", "candidate", "compare")):
        tasks.append(AgentTask(task_id="risk-1", agent="risk_assessment"))
    if not tasks:
        tasks.append(AgentTask(task_id="weather-1", agent="weather_intelligence"))
    return tasks


def run_graph(query: str, location: tuple[float, float] = (15.10, 73.75)) -> OrcaState:
    resolved_location = resolve_location(query, fallback=location)
    if os.getenv("ORCA_USE_LANGGRAPH", "1") == "1":
        try:
            from orca.orchestration.langgraph_runtime import run_langgraph

            result = run_langgraph(query, resolved_location)
            return OrcaState(query=query, location=resolved_location, tasks=result["tasks"], results=result["results"], verdict=result["verdict"], map_data=result["map_data"], response_text=result["response_text"] or "")
        except ImportError:
            pass

    location_name = next((name for name in PLACE_COORDS if re.search(rf"\b{re.escape(name)}\b", " ".join(re.sub(r"[’']", " ", query.lower()).split()))), "user")
    state = OrcaState(query=query, location=resolved_location, metadata={"resolved_location": resolved_location, "location_name": location_name, "explicit_place": location_name != "user"})
    state.tasks = plan(query)
    registry = {
        "marine_data_discovery": marine_data_discovery.run,
        "weather_intelligence": weather_intelligence.run,
        "ocean_analytics": ocean_analytics.run,
        "geospatial_reasoning": geospatial_reasoning.run,
        "risk_assessment": risk_assessment.run,
    }
    for task in state.tasks:
        runner = registry.get(task.agent)
        if runner is None:
            continue
        effective_task = task.model_copy(update={"params": {**task.params, "resolved_location": resolved_location, "location_name": location_name}})
        result = runner({"last_location": resolved_location, "results": state.results, "resolved_location": resolved_location, "location_name": location_name}, effective_task)
        existing = state.results.get(task.agent)
        if existing is not None:
            result = result.model_copy(update={"evidence": [*existing.evidence, *result.evidence], "summary": " ".join(dict.fromkeys((existing.summary, result.summary))), "confidence": max(existing.confidence, result.confidence)})
        state.results[task.agent] = result
        if task.agent == "risk_assessment":
            state.verdict = result.summary
    state.map_data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [resolved_location[1], resolved_location[0]]}, "properties": {"label": "Query location"}}]}
    state.response_text = reporting.render(state.results, state.verdict, query=query, location=resolved_location)
    return state
