from typing import TypedDict

from orca.knowledge.models import AgentResult, AgentTask


class OrcaState(TypedDict):
    session_id: str
    raw_query: str
    lang: str
    query_en: str
    tasks: list[AgentTask]
    results: dict[str, AgentResult]
    verdict: str | None
    map_data: dict | None
    response_text: str | None
    final_response: str | None
    last_location: tuple[float, float]
