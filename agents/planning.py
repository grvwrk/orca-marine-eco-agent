from orca.knowledge.models import AgentTask
from orca.orchestration.graph import plan


def run(query_en: str) -> list[AgentTask]:
    return plan(query_en)
