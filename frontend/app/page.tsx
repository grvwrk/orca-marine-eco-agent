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
  mission_brief?: { assessment?: string; fishing_potential?: string; operational_safety?: string; recommendation?: string; confidence?: number; provenance?: string };
  evidence_coverage?: { available?: string[]; available_count?: number; total_domains?: number };
  lineage?: string[];
  risk_decomposition?: { overall?: number; weather?: number; ocean?: number; boundary?: number; primary_driver?: string };
  agent_consensus?: Array<{ agent: string; confidence: number; summary: string }>;
  map_data?: { type: string; features?: Array<{ type: string; geometry?: { type: string; coordinates?: number[] | number[][] | number[][][] }; properties?: Record<string, unknown> }> };
};

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
    <main className="shell">
      <div className="topline"><strong>ORCA // MARINE INTELLIGENCE</strong><span>SIH26176 / FIELD CONSOLE</span><span className="service"><span className="mode-badge" style={{ background: modeStyle.color }} data-mode={modeStyle.label}>{modeStyle.label}</span><i className={`status-dot ${status === 'online' ? 'ready' : ''}`} /> SERVICE {status.toUpperCase()} / DB {database.toUpperCase()}</span></div>

      <header className="hero">
        <div className="hero-copy"><h1>Read the<br /><em>water.</em></h1></div>
        <div className="hero-note"><span className="label">INDIAN OCEAN / WEST COAST WATCH</span><p>PFZ advisories, weather hazards, sea state and boundaries, assembled into one answer with its source trail attached.</p><div className="note-foot"><span>NOISE → SIGNAL</span><b>01—04</b></div></div>
      </header>

      <div className="chart-strip"><b>IN</b><b>09</b><b>24</b><b>W</b><span>COASTAL GRID / 15°06&apos;N 73°45&apos;E / BRG 270° / ALL SYSTEMS LOGGED</span></div>

      <nav className="mission-nav" aria-label="Quick missions"><span className="nav-label">QUICK MISSIONS</span>{missions.map(([label, query, code]) => <button key={label} className="mission-button" onClick={() => { setQuestion(query); void askOrca(undefined, query); }}><small>{code}</small>{label}<span>↗</span></button>)}</nav>

      <section className="console-grid">
        {missionBrief?.assessment && <article className={`panel mission-brief ${missionBrief.assessment === 'CAUTION' ? 'brief-caution' : ''}`}><div className="panel-head"><h2>Mission brief</h2><span>00 / SYNTHESIS</span></div><div className="brief-body"><div className="brief-assessment"><small>OVERALL ASSESSMENT</small><strong>{missionBrief.assessment}</strong><span>CONFIDENCE {percent(missionBrief.confidence ?? 0)}</span></div><div className="brief-metrics"><div><small>FISHING POTENTIAL</small><b>{missionBrief.fishing_potential}</b></div><div><small>OPERATIONAL SAFETY</small><b>{missionBrief.operational_safety}</b></div><div><small>EVIDENCE COVERAGE</small><b>{coverage?.available_count ?? 0} / {coverage?.total_domains ?? 5}</b></div><div><small>DATA STATUS</small><b>{missionBrief.provenance}</b></div></div><p className="brief-recommendation">{missionBrief.recommendation}</p><div className="brief-inspection"><div><strong>MARINE RISK {risk?.overall ?? 0} / 100</strong><span>PRIMARY DRIVER: {risk?.primary_driver ?? 'NONE IDENTIFIED'}</span><div className="risk-bars"><i style={{ width: `${risk?.weather ?? 0}%` }} /><i style={{ width: `${risk?.ocean ?? 0}%` }} /><i style={{ width: `${risk?.boundary ?? 0}%` }} /></div></div>{consensus.length > 0 && <details><summary>AGENT CONSENSUS</summary><ul>{consensus.map((item) => <li key={item.agent}><b>{item.agent.replaceAll('_', ' ')}</b><span>{percent(item.confidence)}</span></li>)}</ul></details>}</div>{lineage.length > 0 && <details className="lineage"><summary>WHERE DID THIS ANSWER COME FROM?</summary><ol>{lineage.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol></details>}</div></article>}
        <article className="panel mission-panel"><div className="panel-head"><h2>Mission query</h2><span>01 / ASK</span></div><div className="panel-body"><div className="question-meta"><span>CHANNEL / NATURAL LANGUAGE</span><span>CTRL + ENTER</span></div><form onSubmit={askOrca}><textarea value={question} onChange={event => setQuestion(event.target.value)} aria-label="Question" /><div className="location-row"><label>LAT<input value={latitude} onChange={event => setLatitude(event.target.value)} inputMode="decimal" /></label><label>LON<input value={longitude} onChange={event => setLongitude(event.target.value)} inputMode="decimal" /></label><button type="button" className="locate" onClick={useMyLocation} title="Use browser location">⌖ LOCATE</button><button className="ask" disabled={loading}>{loading ? 'SCANNING...' : 'ASK ORCA ↗'}</button></div></form><div className="answer-label"><span>Signal interpretation</span><div className={`confidence-pill ${confidence === null ? 'neutral' : confidenceBandKey}`}><span>{confidence === null ? 'WAITING' : CONFIDENCE_STYLES[confidenceBandKey].label}</span><strong>{confidence === null ? '--' : percent(confidence)}</strong></div></div><div className={`answer ${loading ? 'loading' : ''} ${confidence !== null && confidence < 0.4 ? 'low-confidence' : ''}`} aria-live="polite">{answer}</div>{error && <div className="error">// {error}</div>}</div></article>

        <aside className="right-stack">
          <article className="panel chart-panel"><div className="panel-head"><h2>Live map</h2><span>02 / POSITION</span></div><div className="panel-body">
            <div className="map-shell">
              <MarineMap center={mapCenter} points={mapFeatures} onEvidenceSelect={(index) => { setSelectedEvidenceIndex(index); evidenceRefs.current[index]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }} />
            </div>
            <div className="coords"><span>{formatCoord(lat, 'N', 'S')}</span><span>{formatCoord(lon, 'E', 'W')}</span></div>
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

      <footer><span>INCOIS / IMD / MOSDAC / POSTGIS</span><strong>EVIDENCE BEFORE CONFIDENCE.</strong><span>ORCA SYSTEMS / 2026</span></footer>
    </main>
  );
}