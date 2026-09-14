from orca.knowledge.models import AgentResult, AgentTask
from orca.knowledge.retrieval import boundary_checks, boundary_proximity, nearest_pfz, route_points
from orca.orchestration.state import OrcaState

name = "geospatial_reasoning"


def run(state: OrcaState, task: AgentTask) -> AgentResult:
    lat, lon = state["last_location"]
    mode = task.params.get("mode")
    if mode == "boundary_check":
        evidence = boundary_checks(lat, lon)
    elif mode == "route":
        evidence = [boundary_proximity(point_lat, point_lon) for point_lat, point_lon in route_points((lat, lon), (lat + 0.25, lon + 0.35))]
    else:
        evidence = nearest_pfz(lat, lon)
    return AgentResult(task_id=task.task_id, agent=name, evidence=evidence, summary=evidence[0].content if evidence else "No current geospatial advisory is available for this location.", confidence=0.9 if evidence else 0.0)
