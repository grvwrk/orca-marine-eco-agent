from typing import Protocol

from orca.knowledge.models import AgentResult, AgentTask
from orca.orchestration.state import OrcaState


class Agent(Protocol):
    name: str

    def run(self, state: OrcaState, task: AgentTask) -> AgentResult:
        ...
