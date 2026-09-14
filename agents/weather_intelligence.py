from orca.knowledge.models import AgentResult, AgentTask
from orca.knowledge.retrieval import active_weather_alerts
from orca.orchestration.state import OrcaState

name = "weather_intelligence"


def run(state: OrcaState, task: AgentTask) -> AgentResult:
    evidence = active_weather_alerts(*state["last_location"])
    return AgentResult(task_id=task.task_id, agent=name, evidence=evidence, summary=evidence[0].content if evidence else "No current weather alerts are available for this location.", confidence=0.85 if evidence else 0.0)
