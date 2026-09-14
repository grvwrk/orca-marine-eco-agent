"""LangGraph execution path for the Orca agent workflow."""

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents import geospatial_reasoning, marine_data_discovery, ocean_analytics, reporting, risk_assessment, weather_intelligence
from orca.knowledge.models import AgentTask
from orca.orchestration.state import OrcaState
from orca.orchestration.graph import plan, resolve_location


def _agent_node(agent_name: str, runner: Any):
    def node(state: OrcaState) -> dict:
        tasks = [candidate for candidate in state["tasks"] if candidate.agent == agent_name]
        if not tasks:
            return {}
        results = [runner(state, task) for task in tasks]
        result = results[0]
        for additional in results[1:]:
            result = result.model_copy(update={"evidence": [*result.evidence, *additional.evidence], "summary": " ".join(dict.fromkeys((result.summary, additional.summary))), "confidence": max(result.confidence, additional.confidence)})
        update = {"results": {**state["results"], agent_name: result}}
        if agent_name == "risk_assessment":
            update["verdict"] = result.summary
        return update

    return node


def _planning_node(state: OrcaState) -> dict:
    return {"tasks": plan(state["raw_query"])}


def _reporting_node(state: OrcaState) -> dict:
    verdict = state.get("verdict")
    response = reporting.render(state["results"], verdict)
    lat, lon = state["last_location"]
    return {"response_text": response, "final_response": response, "map_data": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"label": "Query location"}}]}}


def build_graph():
    workflow = StateGraph(OrcaState)
    workflow.add_node("planning", _planning_node)
    workflow.add_node("marine_data_discovery", _agent_node("marine_data_discovery", marine_data_discovery.run))
    workflow.add_node("weather_intelligence", _agent_node("weather_intelligence", weather_intelligence.run))
    workflow.add_node("ocean_analytics", _agent_node("ocean_analytics", ocean_analytics.run))
    workflow.add_node("geospatial_reasoning", _agent_node("geospatial_reasoning", geospatial_reasoning.run))
    workflow.add_node("risk_assessment", _agent_node("risk_assessment", risk_assessment.run))
    workflow.add_node("reporting", _reporting_node)
    workflow.add_edge(START, "planning")
    workflow.add_edge("planning", "marine_data_discovery")
    workflow.add_edge("marine_data_discovery", "weather_intelligence")
    workflow.add_edge("weather_intelligence", "ocean_analytics")
    workflow.add_edge("ocean_analytics", "geospatial_reasoning")
    workflow.add_edge("geospatial_reasoning", "risk_assessment")
    workflow.add_edge("risk_assessment", "reporting")
    workflow.add_edge("reporting", END)
    return workflow.compile()


def run_langgraph(query: str, location: tuple[float, float] = (15.10, 73.75)) -> dict:
    resolved_location = resolve_location(query, fallback=location)
    initial: OrcaState = {"session_id": "local", "raw_query": query, "lang": "en", "query_en": query, "tasks": [], "results": {}, "verdict": None, "map_data": None, "response_text": None, "final_response": None, "last_location": resolved_location}
    return build_graph().invoke(initial)
