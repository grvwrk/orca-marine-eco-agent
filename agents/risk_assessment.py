from orca.knowledge.models import AgentResult, AgentTask
from orca.orchestration.state import OrcaState

name = "risk_assessment"


def run(state: OrcaState, task: AgentTask) -> AgentResult:
    evidence = [card for result in state["results"].values() for card in result.evidence]
    verdict = "CAUTION: confirm the latest local advisory before departure." if evidence else "UNSAFE: insufficient current evidence."
    return AgentResult(task_id=task.task_id, agent=name, evidence=evidence, summary=verdict, confidence=min((result.confidence for result in state["results"].values()), default=0.0))
