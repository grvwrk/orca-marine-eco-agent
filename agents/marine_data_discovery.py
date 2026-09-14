from orca.knowledge.models import AgentResult, AgentTask
from orca.knowledge.retrieval import nearest_pfz
from orca.orchestration.state import OrcaState

name = "marine_data_discovery"


def run(state: OrcaState, task: AgentTask) -> AgentResult:
    evidence = nearest_pfz(*state["last_location"])
    return AgentResult(task_id=task.task_id, agent=name, evidence=evidence, summary=evidence[0].content if evidence else "No current PFZ advisory is available for this location.", confidence=0.9 if evidence else 0.0)
