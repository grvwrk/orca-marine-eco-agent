from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceCard(BaseModel):
    type: Literal[
        "pfz_bulletin", "satellite_reading", "weather_alert", "ocean_state", "boundary_check"
    ]
    content: str
    source: str
    lat: float | None = None
    lon: float | None = None
    valid_time: datetime | None = None
    distance_km: float | None = Field(default=None, ge=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    raw_ref: dict[str, Any] | None = None


class AgentTask(BaseModel):
    task_id: str
    agent: str
    params: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    task_id: str
    agent: str
    evidence: list[EvidenceCard] = Field(default_factory=list)
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=4000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class ChatResponse(BaseModel):
    session_id: str
    response_text: str
    lang: str
    map_data: dict[str, Any] | None = None
    evidence: list[EvidenceCard] = Field(default_factory=list)
    confidence: float
    mode: str = "demo"
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    mission_brief: dict[str, Any] = Field(default_factory=dict)
    evidence_coverage: dict[str, Any] = Field(default_factory=dict)
    lineage: list[str] = Field(default_factory=list)
    risk_decomposition: dict[str, Any] = Field(default_factory=dict)
    agent_consensus: list[dict[str, Any]] = Field(default_factory=list)


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    lang: str = "en"


class SessionState(BaseModel):
    session_id: str
    history: list[ConversationTurn] = Field(default_factory=list)
    last_location: tuple[float, float] | None = None
