'use client';

import dynamic from 'next/dynamic';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';

const MarineMap = dynamic(() => import('./MarineMap'), { ssr: false });

const MODE_STYLES = {
  sqlite: { label: 'SQLite', color: 'var(--acid)' },
  demo: { label: 'Demo', color: 'var(--sky)' },
  live: { label: 'Live', color: 'var(--coral)' },
  fallback: { label: 'Fallback', color: 'var(--sun)' },
  default: { label: 'Mode', color: 'var(--paper)' },
};

const CONFIDENCE_STYLES = {
  high: { label: 'HIGH', color: '#1f7a4d', background: '#dff7e9' },
  medium: { label: 'MED', color: '#9a6a00', background: '#fff1bf' },
  low: { label: 'LOW', color: '#9a2a24', background: '#ffd6d6' },
};

type Evidence = {
  type: string;
  content: string;
  source: string;
  confidence?: number;
  valid_time?: string;
  lat?: number;
  lon?: number;
  distance_km?: number;
  data_status?: string;
  raw_ref?: Record<string, unknown>;
};

type AgentTraceItem = {
  agent: string;
  status: 'pending' | 'running' | 'done';
  summary: string;
  confidence?: number;
};

type ChatResponse = {
  response_text?: string;
  confidence?: number;
  lang?: string;
  evidence?: Evidence[];
  mode?: string;
  agent_trace?: AgentTraceItem[];
  mission_brief?: { assessment?: string; fishing_potential?: string; operational_safety?: string; recommendation?: string; confidence?: number; provenance?: string; provider_verification?: string; confidence_limitation?: string; technical_detail?: string; boundary_status?: string; decision_rationale?: string; positive_signals?: string[]; limitations?: string[]; primary_positive?: string; primary_limitation?: string; primary_risk_driver?: string; selected_candidate?: Candidate; candidate_summary?: Candidate[]; eligible_candidates?: Candidate[]; excluded_candidates?: Candidate[]; counterfactuals?: Scenario[]; scenario_groups?: { downgrade_if?: string[]; improve_if?: string[] }; decision_balance?: { fishing_potential?: string; weather_risk?: number; sea_state_risk?: number; boundary_confidence?: string; distance_km?: number }; resolved_location?: { place?: string; lat?: number; lon?: number } };
  evidence_coverage?: { available?: string[]; available_count?: number; total_domains?: number; missing_domains?: string[] };
  lineage?: string[];
  risk_decomposition?: { overall?: number; weather?: number; waves?: number; wind?: number; current?: number; tide?: number; boundary?: number; primary_driver?: string; semantics?: string; reasons?: Record<string, string> };
  agent_consensus?: Array<{ agent: string; confidence: number; summary: string }>;
  map_data?: { type: string; features?: Array<{ type: string; geometry?: { type: string; coordinates?: number[] | number[][] | number[][][] }; properties?: Record<string, unknown> }> };
  resolved_location?: { place?: string; lat?: number; lon?: number; source?: string };
};

type Candidate = { id?: number; name?: string; lat?: number; lon?: number; distance_km?: number; fishing_potential?: string; opportunity_score?: number; weather_risk?: number; sea_state_risk?: number; boundary_status?: string; eligibility_reason?: string; eligible?: boolean };
type Scenario = { current_assessment?: string; current_driver?: string; current_driver_value?: number; changed_condition?: string; resulting_assessment?: string };

const API_URL = process.env.NEXT_PUBLIC_ORCA_API_URL ?? 'http://127.0.0.1:8000';
const DEFAULT_LOCATION = { lat: 15.1, lon: 73.75 };
const missions = [
  ['NEAREST PFZ', 'Where is the nearest potential fishing zone today?', 'PFZ'],
  ['HAZARD WATCH', 'Are there any lightning or cyclone alerts in my area?', 'ALERT'],
  ['SEA STATE', 'What are the tide, weather, and sea conditions near my fishing location?', 'SEA'],
  ['BOUNDARY CHECK', 'Which zones should be avoided due to hazards or boundary restrictions?', 'ZONE'],
];

function percent(value = 0) {
  return `${Math.round(value * 100)}%`;
}

function confidenceBand(value = 0) {
  if (value >= 0.7) return 'high';
  if (value >= 0.4) return 'medium';
  return 'low';
}

function formatCoord(value: number, positive: string, negative: string) {
  return `${Math.abs(value).toFixed(4)}° ${value >= 0 ? positive : negative}`;
}

function formatDistance(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return `${value.toFixed(0)} KM`;
}

export default function Home() {
  const [question, setQuestion] = useState(missions[0][1]);
  const [latitude, setLatitude] = useState(String(DEFAULT_LOCATION.lat));
  const [longitude, setLongitude] = useState(String(DEFAULT_LOCATION.lon));
  const [answer, setAnswer] = useState('Ask about PFZ, weather, sea state, hazards, routes, or boundaries.');
  const [confidence, setConfidence] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [trace, setTrace] = useState<AgentTraceItem[]>([]);
  const [missionBrief, setMissionBrief] = useState<ChatResponse['mission_brief']>({});
  const [coverage, setCoverage] = useState<ChatResponse['evidence_coverage']>({});
  const [lineage, setLineage] = useState<string[]>([]);
  const [risk, setRisk] = useState<ChatResponse['risk_decomposition']>({});
  const [consensus, setConsensus] = useState<NonNullable<ChatResponse['agent_consensus']>>([]);
  const [mode, setMode] = useState<string>('demo');
  const [status, setStatus] = useState('checking');
  const [database, setDatabase] = useState('waiting');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedEvidenceIndex, setSelectedEvidenceIndex] = useState<number | null>(null);
  const [mapCenter, setMapCenter] = useState(DEFAULT_LOCATION);
  const lat = Number(latitude) || DEFAULT_LOCATION.lat;
  const lon = Number(longitude) || DEFAULT_LOCATION.lon;
  const evidenceRefs = useRef<Array<HTMLElement | null>>([]);
  const mapFeatures = useMemo(() => {
    const features = [] as Array<{ lat: number; lon: number; label: string; index: number }>; 
    evidence.forEach((card, index) => {
      const evidenceLat = card.lat;
      const evidenceLon = card.lon;
      if (evidenceLat !== undefined && evidenceLon !== undefined && Number.isFinite(evidenceLat) && Number.isFinite(evidenceLon)) {
        features.push({ lat: evidenceLat, lon: evidenceLon, label: `${card.type} / ${card.source}`, index });
      }
    });
    if (features.length === 0) {
      features.push({ lat: lat, lon: lon, label: 'Query location', index: -1 });
    }
    return features;
  }, [evidence, lat, lon]);
  const modeStyle = MODE_STYLES[mode as keyof typeof MODE_STYLES] ?? MODE_STYLES.default;
  const confidenceBandKey = confidence === null ? 'low' : confidenceBand(confidence);

  const sessionId = useMemo(() => {
    if (typeof window === 'undefined') return 'server-preview';
    const key = 'orca-session-id';
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const created = window.crypto.randomUUID();
    window.localStorage.setItem(key, created);
    return created;
  }, []);

  useEffect(() => {
    if (evidence.length > 0) {
      const focus = evidence[0];
      const focusLat = focus.lat;
      const focusLon = focus.lon;
      if (focusLat !== undefined && focusLon !== undefined && Number.isFinite(focusLat) && Number.isFinite(focusLon)) {
        setMapCenter({ lat: focusLat, lon: focusLon });
      }
    } else {
      setMapCenter({ lat: lat, lon: lon });
    }
  }, [evidence, lat, lon]);

  useEffect(() => {
    if (!loading && trace.length === 0) return;
    const sequence = trace.map((entry, index) => ({ ...entry, status: index === 0 ? 'running' : 'pending' }));
    sequence.forEach((entry, index) => {
      setTimeout(() => {
        setTrace(prev => {
          const next = [...prev];
          if (index < next.length) {
            next[index] = { ...next[index], status: 'done' };
          }
          return next;
        });
      }, 180 + index * 240);
    });
  }, [loading, trace.length]);

  async function checkHealth() {
    try {
      const response = await fetch(`${API_URL}/health`);
      if (!response.ok) throw new Error('offline');
      const data = await response.json();
      setStatus(data.status ?? 'online');
      setDatabase(data.db ?? 'unknown');
    } catch {
      setStatus('offline');
      setDatabase('unreachable');
    }
  }

  useEffect(() => { void checkHealth(); }, []);

  async function askOrca(event?: FormEvent, missionQuestion = question) {
    event?.preventDefault();
    if (!missionQuestion.trim() || loading) return;
    setLoading(true);
    setError('');
    setAnswer('Consulting marine sources...');
    setConfidence(null);
    setEvidence([]);
    setTrace([]);
    setSelectedEvidenceIndex(null);
    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: missionQuestion.trim(), lat, lon }),
      });
      const data: ChatResponse & { detail?: string } = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'The marine service is unavailable.');
      setAnswer(data.response_text ?? 'No interpretation returned.');
      setConfidence(data.confidence ?? 0);
      setEvidence(data.evidence ?? []);
      setMode(data.mode ?? 'demo');
      setTrace((data.agent_trace ?? []).map((item, index) => ({ ...item, status: index === 0 ? 'running' : 'pending' })));
      setMissionBrief(data.mission_brief ?? {});
      setCoverage(data.evidence_coverage ?? {});
      setLineage(data.lineage ?? []);
      setRisk(data.risk_decomposition ?? {});
      setConsensus(data.agent_consensus ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to reach the marine service.');
      setAnswer('Signal lost. Check the API connection and try again.');
    } finally {
      setLoading(false);
      void checkHealth();
    }
  }

  function useMyLocation() {
    if (!navigator.geolocation) { setError('Geolocation is not available in this browser.'); return; }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const latitudeValue = position?.coords?.latitude;
        const longitudeValue = position?.coords?.longitude;

        if (typeof latitudeValue !== 'number' || !Number.isFinite(latitudeValue) || typeof longitudeValue !== 'number' || !Number.isFinite(longitudeValue)) {
          setError('Location coordinates were unavailable. Enter values manually.');
          return;
        }

        setLatitude(latitudeValue.toFixed(4));
        setLongitude(longitudeValue.toFixed(4));
        setError('');
      },
      () => setError('Location permission was not granted. Enter coordinates manually.'),
    );
  }

  return (
    <main className={`shell ${missionBrief?.selected_candidate ? '' : missionBrief?.assessment === 'NO ELIGIBLE OPTION' ? 'no-selection' : ''}`}>
      <div className="topline"><strong>ORCA // MARINE INTELLIGENCE</strong><span>SIH26176 / FIELD CONSOLE</span><span className="service"><span className="mode-badge" style={{ background: modeStyle.color }} data-mode={modeStyle.label}>{modeStyle.label}</span><i className={`status-dot ${status === 'online' ? 'ready' : ''}`} /> SERVICE {status.toUpperCase()} / DB {database.toUpperCase()}</span></div>

      <header className="hero">
        <div className="hero-copy"><h1>Read the<br /><em>water.</em></h1></div>
        <div className="hero-note"><span className="label">INDIAN OCEAN / WEST COAST WATCH</span><p>PFZ advisories, weather hazards, sea state and boundaries, assembled into one answer with its source trail attached.</p><div className="note-foot"><span>NOISE → SIGNAL</span><b>01—04</b></div></div>
      </header>

      <div className="chart-strip"><b>ORCA</b><b>DATA</b><b>DECISION</b><b>TRACE</b><span>EVIDENCE-GROUNDED MARINE INTELLIGENCE / DATA STATUS AVAILABLE IN ABOUT DATA</span></div>

      <nav className="mission-nav" aria-label="Quick missions"><span className="nav-label">QUICK MISSIONS</span>{missions.map(([label, query, code]) => <button key={label} className="mission-button" onClick={() => { setQuestion(query); void askOrca(undefined, query); }}><small>{code}</small>{label}<span>↗</span></button>)}</nav>

      <section className="console-grid">
        {missionBrief?.assessment && <article className={`panel mission-brief ${missionBrief.assessment === 'CAUTION' ? 'brief-caution' : ''}`}><div className="panel-head"><h2>Mission brief</h2><span>00 / SYNTHESIS</span></div><div className="brief-body"><div className="brief-assessment"><small>OVERALL ASSESSMENT</small><strong>{missionBrief.assessment}</strong><span>CONFIDENCE {percent(missionBrief.confidence ?? 0)}</span></div><div className="brief-metrics"><div><small>FISHING POTENTIAL</small><b>{missionBrief.fishing_potential}</b></div><div><small>OPERATIONAL SAFETY</small><b>{missionBrief.operational_safety}</b></div><div><small>EVIDENCE COVERAGE</small><b>{coverage?.available_count ?? 0} / {coverage?.total_domains ?? 5}</b></div><div><small>DATA STATUS</small><b>{missionBrief.provenance}</b></div></div><p className="brief-recommendation">{missionBrief.recommendation}</p><div className="brief-inspection"><div><strong>MARINE RISK {risk?.overall ?? 0} / 100</strong><span>PRIMARY DRIVER: {risk?.primary_driver ?? 'NONE IDENTIFIED'}</span><div className="risk-bars"><i style={{ width: `${risk?.weather ?? 0}%` }} /><i style={{ width: `${risk?.waves ?? 0}%` }} /><i style={{ width: `${risk?.boundary ?? 0}%` }} /></div></div>{consensus.length > 0 && <details><summary>AGENT CONSENSUS</summary><ul>{consensus.map((item) => <li key={item.agent}><b>{item.agent.replaceAll('_', ' ')}</b><span>{percent(item.confidence)}</span></li>)}</ul></details>}</div>{lineage.length > 0 && <details className="lineage"><summary>WHERE DID THIS ANSWER COME FROM?</summary><ol>{lineage.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol></details>}</div></article>}
        {missionBrief?.assessment && <article className={`panel mission-brief ${missionBrief.assessment === 'CAUTION' ? 'brief-caution' : ''}`}><div className="panel-head"><h2>Mission brief</h2><span>00 / SYNTHESIS</span></div><div className="brief-body"><div className="brief-assessment"><small>OVERALL ASSESSMENT</small><strong>{missionBrief.assessment}</strong><span>CONFIDENCE {percent(missionBrief.confidence ?? 0)}</span></div><div className="brief-metrics"><div><small>FISHING POTENTIAL</small><b>{missionBrief.fishing_potential}</b></div><div><small>OPERATIONAL SAFETY</small><b>{missionBrief.operational_safety}</b></div><div><small>EVIDENCE COVERAGE</small><b>{coverage?.available_count ?? 0} / {coverage?.total_domains ?? 5}</b></div><div><small>DATA STATUS</small><b>{missionBrief.provenance}</b><small>PROVIDER: {missionBrief.provider_verification}</small></div></div><p className="brief-recommendation">{missionBrief.recommendation}</p><div className="brief-inspection"><div><strong>MARINE RISK {risk?.overall ?? 0} / 100</strong><span>PRIMARY DRIVER: {risk?.primary_driver ?? 'NONE IDENTIFIED'}</span><div className="risk-bars"><i style={{ width: `${risk?.weather ?? 0}%` }} /><i style={{ width: `${risk?.waves ?? 0}%` }} /><i style={{ width: `${risk?.boundary ?? 0}%` }} /></div></div>{consensus.length > 0 && <details><summary>AGENT CONSENSUS</summary><ul>{consensus.map((item) => <li key={item.agent}><b>{item.agent.replaceAll('_', ' ')}</b><span>{percent(item.confidence)}</span></li>)}</ul></details>}</div>{lineage.length > 0 && <details className="lineage"><summary>WHERE DID THIS ANSWER COME FROM?</summary><ol>{lineage.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol></details>}</div></article>}
        <article className="panel mission-panel"><div className="panel-head"><h2>Mission query</h2><span>01 / ASK</span></div><div className="panel-body"><div className="question-meta"><span>CHANNEL / NATURAL LANGUAGE</span><span>CTRL + ENTER</span></div><form onSubmit={askOrca}><textarea value={question} onChange={event => setQuestion(event.target.value)} aria-label="Question" /><div className="location-row"><label>LAT<input value={latitude} onChange={event => setLatitude(event.target.value)} inputMode="decimal" /></label><label>LON<input value={longitude} onChange={event => setLongitude(event.target.value)} inputMode="decimal" /></label><button type="button" className="locate" onClick={useMyLocation} title="Use browser location">⌖ LOCATE</button><button className="ask" disabled={loading}>{loading ? 'SCANNING...' : 'ASK ORCA ↗'}</button></div></form><div className="answer-label"><span>Signal interpretation</span><div className={`confidence-pill ${confidence === null ? 'neutral' : confidenceBandKey}`}><span>{confidence === null ? 'WAITING' : CONFIDENCE_STYLES[confidenceBandKey].label}</span><strong>{confidence === null ? '--' : percent(confidence)}</strong></div></div><div className={`answer ${loading ? 'loading' : ''} ${confidence !== null && confidence < 0.4 ? 'low-confidence' : ''}`} aria-live="polite">{answer}</div>{error && <div className="error">// {error}</div>}</div></article>
        {missionBrief?.candidate_summary && <article className="panel structured-panel"><div className="panel-head"><h2>Decision structure</h2><span>01A / INSPECT</span></div><div className="panel-body"><div className="structured-meta"><b>RESOLVED: {missionBrief.resolved_location?.place ?? 'USER LOCATION'} / {missionBrief.resolved_location?.lat?.toFixed(2)}, {missionBrief.resolved_location?.lon?.toFixed(2)}</b><b>RECOMMENDS: {missionBrief.selected_candidate?.name ?? 'NONE'}</b></div><h3>TOP NEARBY OPTIONS</h3><div className="candidate-list">{missionBrief.candidate_summary.map((candidate) => <div className="candidate-row selected-candidate" key={candidate.id ?? candidate.name}><b>{candidate.name}</b><span>{candidate.distance_km?.toFixed(1)} KM / {candidate.fishing_potential}</span><span>WEATHER {candidate.weather_risk ?? 0} / SEA {candidate.sea_state_risk ?? 0}</span><span>MPA {candidate.boundary_status} / SELECTED</span></div>)}</div>{(missionBrief.excluded_candidates ?? []).length > 0 && <><h3>OUTSIDE USEFUL RANGE</h3><div className="candidate-list">{missionBrief.excluded_candidates?.map((candidate) => <div className="candidate-row excluded-candidate" key={candidate.id ?? candidate.name}><b>{candidate.name}</b><span>{candidate.distance_km?.toFixed(1)} KM</span><span>EXCLUDED / {candidate.eligibility_reason}</span></div>)}</div></>}<h3>RISK DECOMPOSITION</h3><p className="risk-scale">{risk?.semantics ?? '0 = minimal risk; 100 = extreme risk; lower is better.'}</p><div className="risk-breakdown">{(['weather', 'waves', 'wind', 'current', 'tide', 'boundary'] as const).map((key) => <span key={key} title={risk?.reasons?.[key]}>{key} {risk?.[key] ?? 0}</span>)}<strong>PRIMARY: {risk?.primary_driver ?? 'NONE'}</strong></div><h3>WHAT WOULD CHANGE THIS?</h3>{(missionBrief.counterfactuals ?? []).map((scenario, index) => <p className="scenario" key={`${scenario.changed_condition}-${index}`}><b>{scenario.current_assessment}</b> / {scenario.current_driver} {scenario.current_driver_value} → IF {scenario.changed_condition} → <strong>{scenario.resulting_assessment}</strong></p>)}<h3>EVIDENCE COVERAGE</h3><p>{coverage?.available?.join(' / ')}; missing: {coverage?.missing_domains?.join(', ') || 'NONE'}</p><p className="confidence-limitation">{missionBrief.confidence_limitation}</p><p className="provenance">{missionBrief.provenance} / {missionBrief.provider_verification}</p></div></article>}

        {missionBrief?.decision_rationale && <article className="panel rationale-panel"><div className="panel-head"><h2>Decision rationale</h2><span>01B / WHY</span></div><div className="panel-body"><div className="recommendation-hierarchy"><small>RECOMMENDATION</small><strong>{missionBrief.assessment}</strong><small>BEST NEARBY OPTION</small><b>{missionBrief.selected_candidate?.name}</b><small>PRIMARY POSITIVE SIGNAL</small><span>+ {missionBrief.primary_positive}</span><small>PRIMARY LIMITATION</small><span>- {missionBrief.primary_limitation}</span><small>PRIMARY RISK DRIVER</small><span>{missionBrief.primary_risk_driver}</span></div><p className="decision-rationale">{missionBrief.decision_rationale}</p>{missionBrief.assessment === 'CAUTION' && <details open className="why-not"><summary>WHY NOT FAVOURABLE?</summary><p className="signal-positive">+ {(missionBrief.positive_signals ?? []).join(' / ')}</p><p className="signal-negative">- {(missionBrief.limitations ?? []).join(' / ')}</p></details>}<div className="decision-balance"><h3>DECISION BALANCE</h3><span>Fishing potential <b>{missionBrief.decision_balance?.fishing_potential}</b></span><span>Weather risk <b>{missionBrief.decision_balance?.weather_risk} / 100</b></span><span>Sea-state risk <b>{missionBrief.decision_balance?.sea_state_risk} / 100</b></span><span>Boundary confidence <b>{missionBrief.decision_balance?.boundary_confidence}</b></span><span>Distance <b>{missionBrief.decision_balance?.distance_km} KM</b></span></div><div className="scenario-columns"><div><h3>DOWNGRADE IF</h3>{(missionBrief.scenario_groups?.downgrade_if ?? []).map((item) => <span key={item}>- {item}</span>)}</div><div><h3>IMPROVE IF</h3>{(missionBrief.scenario_groups?.improve_if ?? []).map((item) => <span key={item}>+ {item}</span>)}</div></div></div></article>}

        {missionBrief?.provenance && <details className="panel data-details"><summary>ABOUT DATA / PROVENANCE</summary><div><b>{missionBrief.provenance}</b><span>Provider verification: {missionBrief.provider_verification}</span><span>{missionBrief.confidence_limitation}</span><span>Evidence coverage: {coverage?.available_count ?? 0} / {coverage?.total_domains ?? 5} domains</span></div></details>}

        <aside className="right-stack">
          <article className="panel chart-panel"><div className="panel-head"><h2>Live map</h2><span>02 / POSITION</span></div><div className="panel-body">
            <div className="map-shell">
              <MarineMap center={mapCenter} points={mapFeatures} onEvidenceSelect={(index) => { setSelectedEvidenceIndex(index); evidenceRefs.current[index]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }} />
            </div>
            <div className="coords"><span>{formatCoord(missionBrief?.resolved_location?.lat ?? lat, 'N', 'S')}</span><span>{formatCoord(missionBrief?.resolved_location?.lon ?? lon, 'E', 'W')}</span></div>
          </div></article>

          <article className="panel trace-panel"><div className="panel-head"><h2>Reasoning trace</h2><span>03 / AGENTS</span></div><div className="panel-body trace-body">
            {trace.length === 0 ? <p className="empty">No agent trace yet. Run a mission to surface collaborative reasoning.</p> : trace.map((entry, index) => (
              <div key={`${entry.agent}-${index}`} className={`trace-row ${entry.status}`}>
                <span className="trace-bullet" />
                <div className="trace-copy">
                  <div className="trace-head"><strong>{entry.agent.replaceAll('_', ' ')}</strong><small>{entry.status.toUpperCase()}</small></div>
                  <p>{entry.summary || 'Awaiting result...'}</p>
                </div>
                <div className="trace-score">{entry.confidence !== undefined ? percent(entry.confidence) : '--'}</div>
              </div>
            ))}
          </div></article>
        </aside>
      </section>

      <section className="bottom-grid">
        <article className="panel evidence-panel">
          <div className="panel-head"><h2>Evidence trail</h2><span>04 / TRACE</span></div>
          <div className="panel-body">{evidence.length === 0 ? <p className="empty">Evidence cards will appear here after the first query.</p> : <div className="evidence-list">{evidence.map((card, index) => <article ref={(node) => { evidenceRefs.current[index] = node; }} className={`evidence-card ${selectedEvidenceIndex === index ? 'selected' : ''}`} key={`${card.source}-${index}`} onClick={() => { setSelectedEvidenceIndex(index); const evidenceLat = card.lat; const evidenceLon = card.lon; if (evidenceLat !== undefined && evidenceLon !== undefined && Number.isFinite(evidenceLat) && Number.isFinite(evidenceLon)) { setMapCenter({ lat: evidenceLat, lon: evidenceLon }); } }}><div className="evidence-top"><b>{card.type.replaceAll('_', ' ')}</b><span className={`confidence-pill mini ${confidenceBand(card.confidence ?? 0)}`}>{CONFIDENCE_STYLES[confidenceBand(card.confidence ?? 0)].label}</span></div><p>{card.content}</p><div className="evidence-foot"><span>{card.source}</span><span>{formatDistance(card.distance_km) ?? 'CURRENT'} {card.valid_time ? new Date(card.valid_time).toLocaleDateString() : ''}</span></div>{card.raw_ref && <details><summary>raw_ref</summary><pre>{JSON.stringify(card.raw_ref, null, 2)}</pre></details>}</article>)}</div>}</div></article>
      </section>

      <footer><span>MARINE INTELLIGENCE CONSOLE</span><strong>EVIDENCE BEFORE CONFIDENCE.</strong><span>ORCA SYSTEMS / 2026</span></footer>
    </main>
  );
}