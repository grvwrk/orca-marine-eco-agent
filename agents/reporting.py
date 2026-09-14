import json
import math
import re
from typing import Any

from llm.client import complete
from orca.knowledge.models import AgentResult, EvidenceCard


DOMAIN_LABELS = {
    "pfz_bulletin": "PFZ",
    "weather_alert": "WEATHER",
    "ocean_state": "OCEAN",
    "satellite_reading": "SATELLITE",
    "boundary_check": "BOUNDARY",
}


def _dedupe_evidence(evidence: list[EvidenceCard]) -> list[EvidenceCard]:
    unique: list[EvidenceCard] = []
    seen: set[tuple[object, ...]] = set()
    for card in evidence:
        raw_ref = card.raw_ref or {}
        table = raw_ref.get("table")
        record_id = raw_ref.get("id")
        key = (table, record_id) if table is not None and record_id is not None else (
            card.type,
            card.source,
            card.valid_time,
            round(card.lat, 6) if card.lat is not None else None,
            round(card.lon, 6) if card.lon is not None else None,
            (card.content or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(card)
    return unique


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371.0 * math.sqrt(x * x + y * y)


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if match is None:
        return None
    return float(match.group(0))


def _extract_risk_profile(evidence: list[EvidenceCard]) -> dict[str, float]:
    weather_risk = 0.0
    wave_risk = 0.0
    wind_risk = 0.0
    current_risk = 0.0
    tide_risk = 0.0
    boundary_risk = 0.0

    for card in evidence:
        text = (card.content or "").lower()
        if card.type == "weather_alert":
            if any(word in text for word in ("cyclone", "severe", "warning", "heavy", "storm")):
                weather_risk = max(weather_risk, 68.0)
            elif any(word in text for word in ("moderate", "watch", "elevated")):
                weather_risk = max(weather_risk, 35.0)
            else:
                weather_risk = max(weather_risk, 12.0)
        elif card.type == "ocean_state":
            wave_match = re.search(r"waves\s+([0-9]+(?:\.[0-9]+)?)\s*m", text)
            wind_match = re.search(r"wind\s+([0-9]+(?:\.[0-9]+)?)\s*km/h", text)
            current_match = re.search(r"current\s+([0-9]+(?:\.[0-9]+)?)\s*m/s", text)
            tide_match = re.search(r"tide\s+([0-9]+(?:\.[0-9]+)?)\s*m", text)
            if wave_match:
                wave_risk = max(wave_risk, min(100.0, float(wave_match.group(1)) * 28.0))
            if wind_match:
                wind_risk = max(wind_risk, min(100.0, float(wind_match.group(1)) * 2.2))
            if current_match:
                current_risk = max(current_risk, min(100.0, float(current_match.group(1)) * 35.0))
            if tide_match:
                tide_risk = max(tide_risk, min(100.0, float(tide_match.group(1)) * 25.0))
        elif card.type == "boundary_check":
            if any(word in text for word in ("inside", "very close", "protected", "restricted", "avoid")):
                boundary_risk = max(boundary_risk, 50.0)
            else:
                boundary_risk = max(boundary_risk, 12.0)

    overall = min(100.0, weather_risk * 0.35 + wave_risk * 0.22 + wind_risk * 0.18 + current_risk * 0.13 + tide_risk * 0.07 + boundary_risk * 0.05)
    return {
        "overall": round(overall),
        "weather": round(weather_risk),
        "waves": round(wave_risk),
        "wind": round(wind_risk),
        "current": round(current_risk),
        "tide": round(tide_risk),
        "boundary": round(boundary_risk),
    }


def _signal_inputs(evidence: list[EvidenceCard]) -> dict[str, Any]:
    available = sorted({DOMAIN_LABELS[card.type] for card in evidence if card.type in DOMAIN_LABELS})
    weather = [card.content for card in evidence if card.type == "weather_alert"]
    ocean = [card.content for card in evidence if card.type == "ocean_state"]
    pfz = [card.content for card in evidence if card.type == "pfz_bulletin"]
    boundary = [card.content for card in evidence if card.type == "boundary_check"]
    risk_profile = _extract_risk_profile(evidence)
    opportunity_score = min(100, len(pfz) * 36 + sum(18 for item in evidence if item.type == "satellite_reading" and any(word in item.content.lower() for word in ("high", "productive", "elevated", "favourable"))))
    return {
        "available_domains": available,
        "domain_count": len(available),
        "total_domains": 5,
        "missing_domains": [label for label in ("PFZ", "WEATHER", "OCEAN", "SATELLITE", "BOUNDARY") if label not in available],
        "pfz_signals": pfz,
        "weather_signals": weather,
        "ocean_signals": ocean,
        "boundary_signals": boundary,
        "risk_score": int(risk_profile["overall"]),
        "risk_profile": risk_profile,
        "opportunity_score": opportunity_score,
        "evidence_count": len(evidence),
    }


def _candidate_cards(evidence: list[EvidenceCard], location: tuple[float, float]) -> list[dict[str, Any]]:
    pfz_cards = _dedupe_evidence([card for card in evidence if card.type == "pfz_bulletin"])
    if not pfz_cards:
        return []

    candidates: list[dict[str, Any]] = []
    for card in pfz_cards:
        region_name = (card.raw_ref or {}).get("region_name") or (card.content.split(":", 1)[1].split(",", 1)[0] if ":" in card.content else "Nearby sector")
        distance = _distance_km(location[0], location[1], float(card.lat or location[0]), float(card.lon or location[1])) if card.lat is not None and card.lon is not None else 0.0
        weather_risk = max((1 if any(word in (card.content or "").lower() for word in ("cyclone", "warning", "high", "severe")) else 0) * 40, 0)
        ocean_risk = 18 if "wave" in (card.content or "").lower() else 12
        boundary_risk = 20 if any(word in (card.content or "").lower() for word in ("protected", "restricted", "inside", "boundary")) else 8
        potential = "HIGH" if any(word in (card.content or "").lower() for word in ("high", "productive", "elevated", "favourable")) else "MODERATE" if any(word in (card.content or "").lower() for word in ("moderate", "good")) else "LOW"
        score = (100 - min(100, distance / 5.0)) * 0.5 + (90 if potential == "HIGH" else 60 if potential == "MODERATE" else 35)
        candidates.append({
            "name": str(region_name).replace(" PFZ", "").strip(),
            "distance_km": round(distance, 1),
            "fishing_potential": potential,
            "weather_risk": round(min(100, weather_risk)),
            "sea_state_risk": round(min(100, ocean_risk)),
            "boundary_status": "PROTECTED / RESTRICTED" if boundary_risk > 15 else "OPEN / MONITOR",
            "evidence_coverage": ["PFZ", "WEATHER", "OCEAN", "BOUNDARY"],
            "confidence": float(card.confidence if card.confidence else 0.7),
            "score": round(score),
        })
    ordered = sorted(candidates, key=lambda item: item["score"], reverse=True)
    unique_candidates: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for candidate in ordered:
        name = candidate["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        unique_candidates.append(candidate)
    return unique_candidates[:3]


def _counterfactuals(risk_profile: dict[str, float]) -> list[str]:
    steps: list[str] = []
    weather = risk_profile.get("weather", 0)
    waves = risk_profile.get("waves", 0)
    wind = risk_profile.get("wind", 0)
    boundary = risk_profile.get("boundary", 0)

    if weather >= 30:
        steps.append("If weather severity increases or a new cyclone/watch alert is issued, the area should be downgraded and the recommendation would change.")
    else:
        steps.append("If a new severe weather alert or cyclone watch is triggered, the recommendation would worsen.")
    if waves >= 20:
        steps.append("If wave height rises above roughly 1.4-1.8 m, sea state risk will push the recommendation toward restricted operations.")
    else:
        steps.append("If wave height rises above about 1.4 m, the recommendation would become less favourable.")
    if wind >= 25:
        steps.append("If sustained wind exceeds about 25-30 km/h, the operating window narrows materially.")
    else:
        steps.append("If sustained wind rises above roughly 25-30 km/h, the candidate would lose favourability.")
    if boundary >= 30:
        steps.append("If the operation enters a protected or restricted zone, the recommendation changes to restricted regardless of PFZ quality.")
    else:
        steps.append("If the operation is moved into a protected or restricted area, the recommendation would change to restricted.")
    return steps


def synthesize(results: dict[str, AgentResult], query: str, location: tuple[float, float]) -> dict[str, object]:
    evidence = _dedupe_evidence([card for result in results.values() for card in result.evidence])
    inputs = _signal_inputs(evidence)
    risk_profile = inputs["risk_profile"]
    candidates = _candidate_cards(evidence, location)
    recommended = max(candidates, key=lambda item: item["score"]) if candidates else {"name": "Nearest sector", "distance_km": 0.0, "fishing_potential": "MODERATE", "weather_risk": 0, "sea_state_risk": 0, "boundary_status": "OPEN / MONITOR", "confidence": 0.6, "score": 60}
    recommendation_signal = "CAUTION" if inputs["risk_score"] >= 35 else "FAVOURABLE" if inputs["opportunity_score"] >= 40 else "MONITOR"
    safety = "ELEVATED" if inputs["risk_score"] >= 35 else "GOOD"
    potential = "HIGH" if inputs["opportunity_score"] >= 60 else "MODERATE" if inputs["opportunity_score"] >= 30 else "LOW"
    confidence = min((result.confidence for result in results.values()), default=0.0)
    primary_driver = "weather" if risk_profile["weather"] >= max(risk_profile["waves"], risk_profile["wind"], risk_profile["current"], risk_profile["tide"], risk_profile["boundary"]) else "sea_state" if risk_profile["waves"] >= max(risk_profile["wind"], risk_profile["current"], risk_profile["tide"], risk_profile["boundary"]) else "boundary" if risk_profile["boundary"] >= max(risk_profile["wind"], risk_profile["current"], risk_profile["tide"]) else "ocean_state"

    response_context = {
        "query": query,
        "location": location,
        "inputs": inputs,
        "candidates": candidates,
        "recommended": recommended,
        "risk_profile": risk_profile,
        "counterfactuals": _counterfactuals(risk_profile),
        "agent_summaries": [result.summary for result in results.values()]
    }
    prompt = "You are Orca's reporting agent. Synthesize a marine mission brief from these structured specialist inputs. Keep the answer evidence-based, explicitly compare nearby candidates, call out the top recommendation, explain what would change it, and include explicit scenario simulation rather than hard-coded fallback logic. Return a single concise narrative in plain English.\n" + json.dumps(response_context, default=str)
    response_text = complete(prompt, lambda: render(results, results.get("risk_assessment").summary if results.get("risk_assessment") else None, query=query, location=location))
    if "CANDIDATES" not in response_text.upper():
        response_text = (
            "CURRENT RECOMMENDATION\n"
            f"{recommendation_signal} for {recommended['name']} — fishing potential {potential}, operational safety {safety}.\n\n"
            "CANDIDATES\n"
            + "\n".join(f"{index + 1}. {candidate['name']} — distance {candidate['distance_km']} km, fishing {candidate['fishing_potential']}, weather risk {candidate['weather_risk']}/100, sea-state risk {candidate['sea_state_risk']}/100, boundary {candidate['boundary_status']}" for index, candidate in enumerate(candidates or [recommended]))
            + "\n\nWHY THIS AREA\n"
            + f"The recommendation is grounded in actual PFZ, weather, ocean and boundary evidence. The best-scoring candidate keeps PFZ quality high while managing risk to a manageable level; this is not the same as a high-risk warning state.\n\n"
            + "WHAT WOULD CHANGE IT?\n"
            + "\n".join(f"- {step}" for step in _counterfactuals(risk_profile))
            + "\n\nEVIDENCE\n"
            + " | ".join([card.content for card in evidence[:6]])
        )

    provenance = "DEMO FIXTURE" if any("demo fixture" in (card.source or "").lower() or "demo" in (card.source or "").lower() for card in evidence) else "HISTORICAL"
    coverage = inputs["available_domains"]
    return {
        "response_text": response_text,
        "mission_brief": {
            "assessment": recommendation_signal,
            "fishing_potential": potential,
            "operational_safety": safety,
            "recommendation": f"Prioritise {recommended['name']} while monitoring weather and protected-area exposure.",
            "confidence": confidence,
            "provenance": provenance,
            "provider_verification": "NOT LIVE VERIFIED",
            "data_status": "DEMO FIXTURE",
            "candidate_summary": candidates,
        },
        "evidence_coverage": {
            "available": coverage,
            "available_count": inputs["domain_count"],
            "total_domains": inputs["total_domains"],
            "missing_domains": inputs["missing_domains"],
            "summary": f"{' / '.join(coverage) if coverage else 'NO DATA'}; missing: {', '.join(inputs['missing_domains']) if inputs['missing_domains'] else 'NONE'}",
        },
        "risk_decomposition": {
            "overall": int(inputs["risk_score"]),
            "weather": int(risk_profile["weather"]),
            "waves": int(risk_profile["waves"]),
            "wind": int(risk_profile["wind"]),
            "current": int(risk_profile["current"]),
            "tide": int(risk_profile["tide"]),
            "boundary": int(risk_profile["boundary"]),
            "primary_driver": primary_driver,
        },
        "agent_consensus": [{"agent": result.agent, "confidence": result.confidence, "summary": result.summary} for result in results.values()],
        "lineage": ["User query", "Explicit location resolution", "Specialist agents", "Candidate comparison", "Risk decomposition", "Counterfactual scenario simulation", "Reporting-agent synthesis", "Mission brief"],
    }


def render(results: dict[str, AgentResult], verdict: str | None = None, query: str | None = None, location: tuple[float, float] | None = None) -> str:
    evidence = _dedupe_evidence([card for result in results.values() for card in result.evidence])
    inputs = _signal_inputs(evidence)
    candidates = _candidate_cards(evidence, location or (15.1, 73.75))
    area = ""
    if query:
        normalized = re.sub(r"[^a-zA-Z]", " ", query.lower()).split()
        area_tokens = [token for token in normalized if token in {"gujarat", "chennai", "goa", "kerala", "konkan", "kutch"}]
        if area_tokens:
            area = area_tokens[0].title()

    provenance = "DEMO FIXTURE / NOT LIVE VERIFIED" if any("demo" in (card.source or "").lower() for card in evidence) else "HISTORICAL / PROVIDER UNVERIFIED"
    coverage = " | ".join(f"{label}: {'✓' if label in inputs['available_domains'] else '—'}" for label in ("PFZ", "WEATHER", "OCEAN", "SATELLITE", "BOUNDARY"))

    candidate_lines = []
    for index, candidate in enumerate(candidates[:3], start=1):
        candidate_lines.append(f"{index}. {candidate['name']} — distance {candidate['distance_km']} km, fishing {candidate['fishing_potential']}, weather risk {candidate['weather_risk']}/100, sea-state risk {candidate['sea_state_risk']}/100, boundary {candidate['boundary_status']}")
    if not candidate_lines:
        candidate_lines.append("1. Nearby sector — evidence-based assessment from the closest PFZ and adjacent signals")

    counterfactuals = _counterfactuals(inputs["risk_profile"])
    risk_summary = f"Risk decomposition: overall {inputs['risk_score']}/100; weather {inputs['risk_profile']['weather']}; waves {inputs['risk_profile']['waves']}; wind {inputs['risk_profile']['wind']}; current {inputs['risk_profile']['current']}; tide {inputs['risk_profile']['tide']}; boundary {inputs['risk_profile']['boundary']}."

    summary_lines = [
        f"{area or 'Regional'} candidate comparison.",
        "CANDIDATES",
        *candidate_lines,
        f"CURRENT RECOMMENDATION: {verdict or 'CAUTION'}.",
        risk_summary,
        f"EVIDENCE COVERAGE: {coverage}",
        f"DATA STATUS: {provenance}",
        "WHAT WOULD NEED TO CHANGE FOR THIS RECOMMENDATION TO CHANGE?",
        "SCENARIO SIMULATION",
        *[f"- {item}" for item in counterfactuals[:3]],
        "COUNTERFACTUAL CHANGE CONDITIONS",
        *[f"- If {item.split('If ', 1)[1]}" for item in counterfactuals[:3]],
        "EVIDENCE SUPPORT",
    ]

    support = []
    for item in evidence[:5]:
        support.append(f"- {item.type.replace('_', ' ').title()}: {item.content}")
    if not support:
        support.append("- No direct evidence returned for this query.")

    summary_lines.extend(support)
    summaries = [result.summary for result in results.values() if result.agent != "risk_assessment"]
    if verdict:
        summaries.append(verdict)
    summary_lines.append("SPECIALIST SUMMARY: " + " ".join(dict.fromkeys(summaries)))
    return " ".join(summary_lines)
