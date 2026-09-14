import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orca.knowledge.models import ChatRequest, ChatResponse, EvidenceCard
from orca.knowledge.models import ConversationTurn
from orca.config import settings
from orca.knowledge.database import DatabaseUnavailable, PostGISDatabase, SQLiteDatabase
from orca.orchestration.graph import run_graph
from agents.reporting import synthesize
from orca.api.session_store import SessionStore

app = FastAPI(title="Orca Marine Intelligence", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
sessions = SessionStore()


@app.get("/health")
def health() -> dict[str, str]:
    database_status = "api-only" if any((settings.pfz_feed_url, settings.imd_api_url, settings.osf_feed_url, settings.satellite_feed_url)) else "demo"
    if settings.use_sqlite:
        try:
            SQLiteDatabase().fetch_all("SELECT 1")
            database_status = "sqlite"
        except (DatabaseUnavailable, OSError):
            database_status = "degraded"
    elif settings.database_url:
        try:
            PostGISDatabase().fetch_all("SELECT 1 AS ok", {})
            database_status = "ok"
        except (DatabaseUnavailable, OSError):
            database_status = "degraded"
    return {"status": "ok", "db": database_status, "llm_provider": "groq" if os.getenv("GROQ_API_KEY") else "fallback"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session = sessions.get(request.session_id)
    location = (request.lat, request.lon) if request.lat is not None and request.lon is not None else session.last_location or (15.10, 73.75)
    normalized = " ".join(request.message.lower().split())
    cache_key = (normalized, location)
    cached = sessions.cached(cache_key)
    if cached is not None:
        return ChatResponse.model_validate({**cached, "session_id": request.session_id})

    state = run_graph(request.message, location=location)
    evidence: list[EvidenceCard] = []
    seen_evidence: set[tuple[object, ...]] = set()
    for result in state.results.values():
        for card in result.evidence:
            raw_ref = card.raw_ref or {}
            table = raw_ref.get("table")
            record_id = raw_ref.get("id")
            key = (table, record_id) if table is not None and record_id is not None else (card.type, card.source, card.valid_time, card.lat, card.lon, card.content)
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            evidence.append(card)
    synthesis = synthesize(state.results, request.message, location)
    response = str(synthesis["response_text"])
    confidence = float(synthesis["mission_brief"]["confidence"])
    lang = _language_code(request.message)
    trace = []
    for task in state.tasks:
        result = state.results.get(task.agent)
        trace.append({
            "agent": task.agent,
            "status": "done" if result is not None else "pending",
            "summary": result.summary if result is not None else "Awaiting specialist result",
            "confidence": result.confidence if result is not None else 0.0,
        })
    data_mode = "sqlite" if settings.use_sqlite else "demo" if not settings.database_url else "live"
    output = ChatResponse(session_id=request.session_id, response_text=response, lang=lang, map_data=state.map_data, evidence=evidence, confidence=confidence, mode=data_mode, agent_trace=trace, mission_brief=synthesis["mission_brief"], evidence_coverage=synthesis["evidence_coverage"], lineage=synthesis["lineage"], risk_decomposition=synthesis["risk_decomposition"], agent_consensus=synthesis["agent_consensus"])
    session.last_location = location
    session.history.extend([ConversationTurn(role="user", content=request.message, lang=lang), ConversationTurn(role="assistant", content=response, lang=lang)])
    sessions.save(session)
    sessions.cache(cache_key, output.model_dump())
    return output


def _language_code(message: str) -> str:
    if any("\u0b80" <= character <= "\u0bff" for character in message):
        return "ta"
    if any("\u0900" <= character <= "\u097f" for character in message):
        return "hi"
    return "en"


def run() -> None:
    import uvicorn

    uvicorn.run("orca.api.main:app", host="127.0.0.1", port=8000, reload=False)
