from orca.knowledge.models import AgentResult, AgentTask
from orca.knowledge.retrieval import ocean_state_at, satellite_trend
from orca.orchestration.state import OrcaState

name = "ocean_analytics"


def run(state: OrcaState, task: AgentTask) -> AgentResult:
    location = state["last_location"]
    evidence = satellite_trend(*location, "chlorophyll") if task.params.get("mode") == "trend" else ocean_state_at(*location)
    return AgentResult(task_id=task.task_id, agent=name, evidence=evidence, summary=evidence[0].content if evidence else "No current ocean-state data is available for this location.", confidence=0.85 if evidence else 0.0)
