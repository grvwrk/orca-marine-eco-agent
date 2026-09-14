from orca.knowledge.models import AgentResult, AgentTask
from orca.knowledge.retrieval import nearest_pfz
from orca.orchestration.state import OrcaState

name = "marine_data_discovery"


def run(state: OrcaState, task: AgentTask) -> AgentResult:
    if task.params.get("comparison"):
        evidence = nearest_pfz(*state["last_location"], comparison=True)
    else:
        evidence = nearest_pfz(*state["last_location"])
    summary = f"High-potential PFZ identified {evidence[0].distance_km:.1f} km away." if evidence and evidence[0].distance_km is not None else "No current PFZ advisory is available for this location."
    return AgentResult(task_id=task.task_id, agent=name, evidence=evidence, summary=summary, confidence=0.9 if evidence else 0.0)
