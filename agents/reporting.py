import json

from llm.client import complete
from orca.knowledge.models import AgentResult, EvidenceCard


def _signal_inputs(evidence: list[EvidenceCard]) -> dict[str, object]:
    domains = {"pfz_bulletin": "PFZ", "weather_alert": "Weather", "ocean_state": "Ocean", "satellite_reading": "Satellite", "boundary_check": "Boundary"}
    available = sorted({domains[card.type] for card in evidence if card.type in domains})
    weather = [card.content for card in evidence if card.type == "weather_alert" and "weather_observation" not in card.content.lower()]
    ocean = [card.content for card in evidence if card.type == "ocean_state"]
    pfz = [card.content for card in evidence if card.type == "pfz_bulletin"]
    boundary = [card.content for card in evidence if card.type == "boundary_check"]
    risk_score = min(100, len(weather) * 35 + len(ocean) * 10 + sum(20 for item in weather if "no severe" not in item.lower() and any(word in item.lower() for word in ("severe", "cyclone", "high", "warning"))))
    opportunity_score = min(100, len(pfz) * 30 + sum(20 for item in evidence if item.type == "satellite_reading" and any(word in item.content.lower() for word in ("high", "productive", "elevated"))))
    return {"available_domains": available, "domain_count": len(available), "total_domains": 5, "pfz_signals": pfz, "weather_signals": weather, "ocean_signals": ocean, "boundary_signals": boundary, "risk_score": risk_score, "opportunity_score": opportunity_score, "evidence_count": len(evidence)}


def synthesize(results: dict[str, AgentResult], query: str, location: tuple[float, float]) -> dict[str, object]:
    evidence = [card for result in results.values() for card in result.evidence]
    inputs = _signal_inputs(evidence)
    prompt = "You are Orca's reporting agent. Synthesize a marine mission brief from these structured specialist inputs. Separate fishing opportunity from operational safety, preserve uncertainty, name the primary risk driver, and do not invent missing evidence. Return concise plain text.\n" + json.dumps({"query": query, "location": location, "inputs": inputs, "agent_summaries": [result.summary for result in results.values()]}, default=str)
    response_text = complete(prompt, lambda: render(results, results.get("risk_assessment").summary if results.get("risk_assessment") else None))
    risk_score = int(inputs["risk_score"])
    opportunity_score = int(inputs["opportunity_score"])
    available = inputs["available_domains"]
    assessment = "INSUFFICIENT EVIDENCE" if not evidence else "CAUTION" if risk_score >= 35 else "FAVOURABLE" if opportunity_score >= 30 else "MONITOR"
    safety = "ELEVATED" if risk_score >= 35 else "GOOD" if "Weather" in available or "Ocean" in available else "UNKNOWN"
    potential = "HIGH" if opportunity_score >= 60 else "MODERATE" if opportunity_score >= 30 else "UNKNOWN"
    recommendation = "Review the latest warning and sea-state evidence before departure." if assessment == "CAUTION" else "Use the evidence trail and verify current conditions before acting."
    confidence = min((result.confidence for result in results.values()), default=0.0)
    return {"response_text": response_text, "mission_brief": {"assessment": assessment, "fishing_potential": potential, "operational_safety": safety, "recommendation": recommendation, "confidence": confidence, "provenance": "DEMO_FIXTURE" if any("ORCA Demo Fixture" in card.source for card in evidence) else "HISTORICAL_OR_LIVE"}, "evidence_coverage": {"available": available, "available_count": inputs["domain_count"], "total_domains": inputs["total_domains"]}, "risk_decomposition": {"overall": risk_score, "weather": min(100, len(inputs["weather_signals"]) * 45), "ocean": min(100, len(inputs["ocean_signals"]) * 30), "boundary": min(100, len(inputs["boundary_signals"]) * 20), "primary_driver": inputs["weather_signals"][0] if inputs["weather_signals"] else "No dominant risk signal"}, "agent_consensus": [{"agent": result.agent, "confidence": result.confidence, "summary": result.summary} for result in results.values()], "lineage": ["User query", "Location and mission routing", "Specialist agents", f"{len(evidence)} structured evidence candidates", "Reporting-agent synthesis", "Mission brief"]}


def render(results: dict[str, AgentResult], verdict: str | None = None) -> str:
    summaries = [result.summary for result in results.values() if result.agent != "risk_assessment"]
    if verdict:
        summaries.append(verdict)
    return " ".join(dict.fromkeys(summaries))
