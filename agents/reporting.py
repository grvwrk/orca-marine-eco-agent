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
USEFUL_DISTANCE_KM = 200.0
RISK_WEIGHTS = {"weather": 0.35, "waves": 0.22, "wind": 0.18, "current": 0.13, "tide": 0.07, "boundary": 0.05}


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
            if (card.raw_ref or {}).get("boundary_type") == "EEZ" or "nearest eez" in text or "no mpa boundary data" in text:
                continue
            if any(word in text for word in ("inside", "very close", "protected", "restricted", "avoid")):
                boundary_risk = max(boundary_risk, 50.0)
            elif "no mpa boundary data" not in text and "unknown" not in text:
                boundary_risk = max(boundary_risk, 12.0)

    overall = min(100.0, sum({"weather": weather_risk, "waves": wave_risk, "wind": wind_risk, "current": current_risk, "tide": tide_risk, "boundary": boundary_risk}[name] * weight for name, weight in RISK_WEIGHTS.items()))
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
        "risk_semantics": "0 = minimal risk; 100 = extreme risk; lower is better",
        "risk_reasons": {
            "weather": next((card.content for card in evidence if card.type == "weather_alert"), "No weather evidence retrieved."),
            "waves": next((card.content for card in evidence if card.type == "ocean_state"), "No ocean evidence retrieved."),
            "wind": next((card.content for card in evidence if card.type == "ocean_state"), "No ocean evidence retrieved."),
            "current": next((card.content for card in evidence if card.type == "ocean_state"), "No ocean evidence retrieved."),
            "tide": next((card.content for card in evidence if card.type == "ocean_state"), "No ocean evidence retrieved."),
            "boundary": next((card.content for card in evidence if card.type == "boundary_check"), "Boundary status unknown: no usable MPA evidence retrieved."),
        },
    }


def _candidate_cards(evidence: list[EvidenceCard], location: tuple[float, float]) -> list[dict[str, Any]]:
    pfz_cards = _dedupe_evidence([card for card in evidence if card.type == "pfz_bulletin"])
    if not pfz_cards:
        return []

    candidates: list[dict[str, Any]] = []
    for card in pfz_cards:
        region_name = (card.raw_ref or {}).get("region_name") or (card.content.split(":", 1)[1].split(",", 1)[0] if ":" in card.content else "Nearby sector")
        distance = _distance_km(location[0], location[1], float(card.lat or location[0]), float(card.lon or location[1])) if card.lat is not None and card.lon is not None else 0.0
        weather_risk = 0
        ocean_risk = 0
        boundary_risk = 0
        potential = "HIGH" if any(word in (card.content or "").lower() for word in ("high", "productive", "elevated", "favourable")) else "MODERATE" if any(word in (card.content or "").lower() for word in ("moderate", "good")) else "LOW"
        opportunity_score = {"HIGH": 85, "MODERATE": 60, "LOW": 30}[potential]
        score = opportunity_score - min(25.0, distance / USEFUL_DISTANCE_KM * 25.0)
        candidates.append({
            "id": (card.raw_ref or {}).get("id"),
            "name": str(region_name).replace(" PFZ", "").strip(),
            "lat": card.lat,
            "lon": card.lon,
            "distance_km": round(distance, 1),
            "fishing_potential": potential,
            "opportunity_score": opportunity_score,
            "weather_risk": round(min(100, weather_risk)),
            "sea_state_risk": round(min(100, ocean_risk)),
            "boundary_status": "UNKNOWN",
            "eligible": distance <= USEFUL_DISTANCE_KM,
            "eligibility_reason": "within useful range" if distance <= USEFUL_DISTANCE_KM else f"outside {USEFUL_DISTANCE_KM:.0f} km useful range",
            "evidence_coverage": ["PFZ", "WEATHER", "OCEAN", "BOUNDARY"],
            "evidence_refs": [card.raw_ref or {}],
            "confidence": float(card.confidence if card.confidence else 0.7),
            "score": round(max(0.0, min(100.0, score))),
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


def _scenario_records(risk_profile: dict[str, float], assessment: str) -> list[dict[str, Any]]:
    driver, driver_value = max(
        ((name, risk_profile.get(name, 0)) for name in ("weather", "waves", "wind", "current", "tide", "boundary")),
        key=lambda item: item[1],
    )
    return [
        {
            "current_assessment": assessment,
            "current_driver": driver,
            "current_driver_value": driver_value,
            "changed_condition": "weather severity increases or a new cyclone/watch alert is issued",
            "resulting_assessment": "RESTRICTED / DOWNGRADED",
        },
        {
            "current_assessment": assessment,
            "current_driver": "waves",
            "current_driver_value": risk_profile.get("waves", 0),
            "changed_condition": "wave height rises above the operating threshold",
            "resulting_assessment": "RESTRICTED / DOWNGRADED",
        },
    ]


def _decision_explanation(recommended: dict[str, Any], inputs: dict[str, Any], risk_profile: dict[str, float], assessment: str) -> dict[str, Any]:
    positives = [
        f"{recommended['distance_km']} km from the resolved location",
        f"{recommended['fishing_potential']} fishing potential",
    ]
    ocean_text = " ".join(inputs["ocean_signals"]).lower()
    if ocean_text and not any(value >= 50 for value in (risk_profile["waves"], risk_profile["wind"], risk_profile["current"], risk_profile["tide"])):
        positives.append("manageable current sea conditions")
    limitations: list[str] = []
    if risk_profile["weather"] > 0:
        limitations.append(f"weather risk is {risk_profile['weather']}/100")
    if risk_profile["waves"] > 0 or risk_profile["wind"] > 0:
        limitations.append("marine conditions are not risk-free")
    if "SATELLITE" in inputs["missing_domains"]:
        limitations.append("satellite evidence is unavailable")
    if any("no mpa boundary data" in signal.lower() for signal in inputs["boundary_signals"]):
        limitations.append("protected-area evidence is incomplete")
    rationale = f"{recommended['name']} is the strongest nearby option because it is {positives[0]} and combines {positives[1]} with {positives[-1]}. ORCA stops at {assessment} because " + "; ".join(limitations) + "."
    return {
        "text": rationale,
        "positive_signals": positives,
        "limitations": limitations,
        "primary_positive": positives[1],
        "primary_limitation": limitations[-1] if limitations else "No material limitation identified",
        "primary_risk_driver": max(("weather", "waves", "wind", "current", "tide", "boundary"), key=lambda name: risk_profile[name]),
    }


def _scenario_groups(risk_profile: dict[str, float], inputs: dict[str, Any]) -> dict[str, list[str]]:
    downgrade = [
        "A severe weather or cyclone warning is issued",
        "Wave height crosses the configured operating threshold",
        "Sustained wind exceeds the configured operating threshold",
        "A relevant protected-area restriction is confirmed",
    ]
    improve = [
        "Weather remains low-risk",
        "Sea state remains within the favourable operating range",
        "Protected-area clearance is confirmed",
    ]
    if "SATELLITE" in inputs["missing_domains"]:
        improve.append("Missing satellite evidence becomes available")
    return {"downgrade_if": downgrade, "improve_if": improve}


def _executive_fallback(recommended: dict[str, Any], explanation: dict[str, Any], assessment: str, scenario_groups: dict[str, list[str]]) -> str:
    change = "worsening weather or sea conditions, or confirmation of a protected-area restriction"
    return (
        f"Recommendation: {recommended['name']}.\n\n"
        f"It is the strongest nearby option at {recommended['distance_km']} km, with {recommended['fishing_potential']} fishing potential and manageable current sea conditions. "
        f"ORCA recommends {assessment} because {explanation['primary_risk_driver']} risk remains material and {explanation['primary_limitation']}.\n\n"
        f"The recommendation would change with {change}."
    )


def synthesize(results: dict[str, AgentResult], query: str, location: tuple[float, float]) -> dict[str, object]:
    evidence = _dedupe_evidence([card for result in results.values() for card in result.evidence])
    inputs = _signal_inputs(evidence)
    risk_profile = inputs["risk_profile"]
    all_candidates = _candidate_cards(evidence, location)
    eligible_candidates = [candidate for candidate in all_candidates if candidate["eligible"]]
    excluded_candidates = [candidate for candidate in all_candidates if not candidate["eligible"]]
    candidates = eligible_candidates
    recommended = max(candidates, key=lambda item: item["score"]) if candidates else {"name": "No eligible candidate", "distance_km": None, "fishing_potential": "UNKNOWN", "weather_risk": 0, "sea_state_risk": 0, "boundary_status": "UNKNOWN", "confidence": 0.0, "score": 0}
    recommendation_signal = "CAUTION" if inputs["risk_score"] >= 35 else "FAVOURABLE" if inputs["opportunity_score"] >= 40 else "MONITOR"
    safety = "ELEVATED" if inputs["risk_score"] >= 35 else "GOOD"
    potential = "HIGH" if inputs["opportunity_score"] >= 60 else "MODERATE" if inputs["opportunity_score"] >= 30 else "LOW"
    confidence = min((result.confidence for result in results.values()), default=0.0) * (len(inputs["available_domains"]) / inputs["total_domains"])
    primary_driver = "weather" if risk_profile["weather"] >= max(risk_profile["waves"], risk_profile["wind"], risk_profile["current"], risk_profile["tide"], risk_profile["boundary"]) else "sea_state" if risk_profile["waves"] >= max(risk_profile["wind"], risk_profile["current"], risk_profile["tide"], risk_profile["boundary"]) else "boundary" if risk_profile["boundary"] >= max(risk_profile["wind"], risk_profile["current"], risk_profile["tide"]) else "ocean_state"
    explanation = _decision_explanation(recommended, inputs, risk_profile, recommendation_signal)
    scenario_groups = _scenario_groups(risk_profile, inputs)

    response_context = {
        "query": query,
        "location": location,
        "inputs": inputs,
        "eligible_candidates": eligible_candidates,
        "excluded_candidates": excluded_candidates,
        "recommended": recommended,
        "risk_profile": risk_profile,
        "counterfactuals": _counterfactuals(risk_profile),
        "scenario_groups": scenario_groups,
        "decision_rationale": explanation,
        "agent_summaries": [result.summary for result in results.values()]
    }
    prompt = "You are Orca's reporting agent. Produce the executive answer for a marine mission from the structured evidence below. Return no headings, tables, lists, raw references, agent names, scores, or database terms. Use two short paragraphs: state the recommendation and best option, explain the positive tradeoff and the primary limitation, then state what would change the decision. Use only supplied evidence and be natural and concise.\n" + json.dumps(response_context, default=str)
    response_text = complete(prompt, lambda: _executive_fallback(recommended, explanation, recommendation_signal, scenario_groups))
    technical_response = render(results, results.get("risk_assessment").summary if results.get("risk_assessment") else None, query=query, location=location)

    provenance = "DEMO FIXTURE" if any("demo fixture" in (card.source or "").lower() or "demo" in (card.source or "").lower() for card in evidence) else "HISTORICAL"
    coverage = inputs["available_domains"]
    scenarios = _scenario_records(risk_profile, recommendation_signal)
    return {
        "response_text": response_text,
        "technical_response": technical_response,
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
            "eligible_candidates": eligible_candidates,
            "excluded_candidates": excluded_candidates,
            "selected_candidate": recommended,
            "resolved_location": {"lat": location[0], "lon": location[1]},
            "counterfactuals": scenarios,
            "boundary_status": "UNKNOWN" if any("no mpa boundary data" in card.content.lower() for card in evidence) else "ASSESSED",
            "confidence_limitation": f"Missing evidence: {', '.join(inputs['missing_domains'])}." if inputs["missing_domains"] else "All configured evidence domains returned.",
            "decision_rationale": explanation["text"],
            "positive_signals": explanation["positive_signals"],
            "limitations": explanation["limitations"],
            "primary_positive": explanation["primary_positive"],
            "primary_limitation": explanation["primary_limitation"],
            "primary_risk_driver": explanation["primary_risk_driver"],
            "scenario_groups": scenario_groups,
            "decision_balance": {
                "fishing_potential": recommended.get("fishing_potential", "UNKNOWN"),
                "weather_risk": risk_profile["weather"],
                "sea_state_risk": max(risk_profile["waves"], risk_profile["wind"], risk_profile["current"], risk_profile["tide"]),
                "boundary_confidence": "INCOMPLETE" if explanation["primary_limitation"] == "protected-area evidence is incomplete" else "ASSESSED",
                "distance_km": recommended.get("distance_km"),
            },
            "executive_answer": response_text,
            "technical_detail": technical_response,
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
            "semantics": inputs["risk_semantics"],
            "reasons": inputs["risk_reasons"],
        },
        "agent_consensus": [{"agent": result.agent, "confidence": result.confidence, "summary": result.summary} for result in results.values()],
        "lineage": ["User query", "Explicit location resolution", "Mission/intent detection", "Specialist agents", "Evidence retrieval", "Candidate comparison", "Risk decomposition", "Counterfactual scenario simulation", "Reporting-agent synthesis", "Mission brief"],
    }


def render(results: dict[str, AgentResult], verdict: str | None = None, query: str | None = None, location: tuple[float, float] | None = None) -> str:
    evidence = _dedupe_evidence([card for result in results.values() for card in result.evidence])
    inputs = _signal_inputs(evidence)
    all_candidates = _candidate_cards(evidence, location or (15.1, 73.75))
    candidates = [candidate for candidate in all_candidates if candidate["eligible"]]
    excluded_candidates = [candidate for candidate in all_candidates if not candidate["eligible"]]
    recommended = max(candidates, key=lambda item: item["score"]) if candidates else {"name": "No eligible candidate", "distance_km": None, "fishing_potential": "UNKNOWN"}
    assessment = "CAUTION" if inputs["risk_score"] >= 35 else "FAVOURABLE" if inputs["opportunity_score"] >= 40 else "MONITOR"
    explanation = _decision_explanation(recommended, inputs, inputs["risk_profile"], assessment)
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
        candidate_lines.append(f"{index}. {candidate['name']} — distance {candidate['distance_km']} km, fishing {candidate['fishing_potential']}, weather risk {candidate['weather_risk']}/100, sea-state risk {candidate['sea_state_risk']}/100, MPA {candidate['boundary_status']}, SELECTED/ELIGIBLE")
    if not candidate_lines:
        candidate_lines.append("No eligible candidate was found within the useful range.")
    excluded_lines = [f"{candidate['name']} — {candidate['distance_km']} km, EXCLUDED — {candidate['eligibility_reason']}" for candidate in _candidate_cards(evidence, location or (15.1, 73.75)) if not candidate["eligible"]]

    counterfactuals = _counterfactuals(inputs["risk_profile"])
    risk_summary = f"Risk decomposition: overall {inputs['risk_score']}/100; weather {inputs['risk_profile']['weather']}; waves {inputs['risk_profile']['waves']}; wind {inputs['risk_profile']['wind']}; current {inputs['risk_profile']['current']}; tide {inputs['risk_profile']['tide']}; boundary {inputs['risk_profile']['boundary']}."

    summary_lines = [
        f"{area or 'Regional'} candidate comparison.",
        "CANDIDATES",
        *candidate_lines,
        f"CURRENT RECOMMENDATION: {verdict or 'CAUTION'}.",
        "DECISION RATIONALE",
        explanation["text"],
        "WHY NOT FAVOURABLE?" if assessment == "CAUTION" else "WHY THIS IS FAVOURABLE",
        *[f"+ {item}" for item in explanation["positive_signals"]],
        *[f"- {item}" for item in explanation["limitations"]],
        "MARINE RISK SCALE: 0 = minimal risk; 100 = extreme risk; lower is better.",
        risk_summary,
        f"EVIDENCE COVERAGE: {coverage}",
        f"DATA STATUS: {provenance}",
        "WHAT WOULD CHANGE THIS?",
        *[f"- {item}" for item in counterfactuals[:3]],
        "OUTSIDE USEFUL RANGE",
        *(excluded_lines or [f"{candidate['name']} — {candidate['distance_km']} km, EXCLUDED — {candidate['eligibility_reason']}" for candidate in excluded_candidates] or ["None"]),
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
