/**
 * Chart Lab — the charting-ideas scout UI (Phase-3 slice 3).
 *
 * Lists idea cards the scout staged (mined from sources → AI expressed each as a
 * constrained indicator spec), lets you DEMO an idea's spec on a live chart, and
 * ACCEPT good ones into the arsenal (where they become reusable indicators on the
 * Charts tab / PortfolioScan). Specs are computed by the backend engine — nothing
 * the AI wrote runs in the browser.
 *
 * Keeps the centered <PageHeader> convention; the App shell reserves chrome
 * clearance so no per-page top/bottom padding is needed.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import KLineChartView from '../components/charts/KLineChartView';
import PageHeader from '../components/PageHeader';
import {
  acceptIdea,
  deleteIdea,
  listIdeas,
  listSources,
  runScout,
  type ScoutIdea,
  type ScoutSource,
} from '../lib/scoutApi';

const GREEN = '#00ff41';
const RED = '#ff3b3b';
const GREEN_DIM = 'rgba(0,255,65,0.3)';

const btn: React.CSSProperties = {
  background: '#000',
  color: GREEN,
  border: `1px solid ${GREEN_DIM}`,
  fontFamily: 'monospace',
  fontSize: 12,
  padding: '4px 10px',
  cursor: 'pointer',
  borderRadius: 4,
};

const inputStyle: React.CSSProperties = {
  background: '#000',
  color: GREEN,
  border: `1px solid ${GREEN_DIM}`,
  fontFamily: 'monospace',
  fontSize: 13,
  padding: '5px 10px',
  borderRadius: 4,
  width: 110,
  textTransform: 'uppercase',
};

const ChartingScout: React.FC = () => {
  const [ideas, setIdeas] = useState<ScoutIdea[]>([]);
  const [sources, setSources] = useState<ScoutSource[]>([]);
  const [symbol, setSymbol] = useState('SPY');
  const [draft, setDraft] = useState('SPY');
  const [demo, setDemo] = useState<{ spec: NonNullable<ScoutIdea['spec']>; label: string } | null>(null);
  const [demoKey, setDemoKey] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [note, setNote] = useState('');
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(() => {
    listIdeas().then(setIdeas).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    listSources().then(setSources).catch(() => undefined);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [refresh]);

  const onRun = () => {
    setScanning(true);
    setNote('Scout running in the background…');
    runScout()
      .then(() => {
        // Poll for staged ideas for ~60s (AI generation is async on the worker).
        let ticks = 0;
        if (pollRef.current) window.clearInterval(pollRef.current);
        pollRef.current = window.setInterval(() => {
          ticks += 1;
          refresh();
          if (ticks >= 12) {
            if (pollRef.current) window.clearInterval(pollRef.current);
            setScanning(false);
            setNote('');
          }
        }, 5000);
      })
      .catch((e) => {
        setScanning(false);
        setNote(e?.message || 'Scout failed to start');
      });
  };

  const onDemo = (idea: ScoutIdea) => {
    if (!idea.spec) return;
    setDemo({ spec: idea.spec, label: idea.title });
    setDemoKey((k) => k + 1); // remount the chart to seed the spec
  };

  const onAccept = (idea: ScoutIdea) => {
    acceptIdea(idea.id)
      .then(() => {
        setNote(`Accepted "${idea.title}" into the arsenal`);
        refresh();
      })
      .catch((e) => setNote(e?.response?.data?.detail || e?.message || 'Accept failed'));
  };

  const onDelete = (idea: ScoutIdea) => {
    deleteIdea(idea.id).then(() => refresh()).catch(() => undefined);
  };

  const submitSymbol = (e: React.FormEvent) => {
    e.preventDefault();
    const next = draft.trim().toUpperCase();
    if (next) setSymbol(next);
  };

  const implemented = sources.filter((s) => s.implemented).map((s) => s.name);

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-8">
      <PageHeader
        title="🔬 Chart Lab"
        subtitle={
          sources.length
            ? `scout sources: ${implemented.join(', ') || 'none live'}${
                sources.length > implemented.length ? ` (+${sources.length - implemented.length} stubbed)` : ''
              }`
            : 'charting-ideas scout'
        }
      >
        <button type="button" onClick={onRun} disabled={scanning} style={{ ...btn, opacity: scanning ? 0.5 : 1 }}>
          {scanning ? 'Scouting…' : '🔭 Run scout'}
        </button>
        <button type="button" onClick={refresh} style={btn}>
          ↻ Refresh
        </button>
        <form onSubmit={submitSymbol} style={{ display: 'flex', gap: 6 }}>
          <input
            aria-label="Demo symbol"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="SYMBOL"
            style={inputStyle}
          />
          <button type="submit" style={btn}>
            Demo on
          </button>
        </form>
      </PageHeader>

      {note && (
        <div style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 12, marginBottom: 12, textAlign: 'center' }}>
          {note}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Ideas list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {ideas.length === 0 && (
            <div
              style={{
                border: `1px dashed ${GREEN_DIM}`,
                borderRadius: 6,
                padding: 24,
                textAlign: 'center',
                color: GREEN_DIM,
                fontFamily: 'monospace',
                fontSize: 13,
              }}
            >
              No staged ideas yet. Hit “Run scout” to mine some.
            </div>
          )}
          {ideas.map((idea) => (
            <IdeaCard
              key={idea.id}
              idea={idea}
              onDemo={() => onDemo(idea)}
              onAccept={() => onAccept(idea)}
              onDelete={() => onDelete(idea)}
            />
          ))}
        </div>

        {/* Demo chart */}
        <div>
          {demo && (
            <div style={{ color: GREEN, fontFamily: 'monospace', fontSize: 12, marginBottom: 6 }}>
              Demoing: {demo.label} on {symbol}
            </div>
          )}
          <KLineChartView
            key={demoKey}
            symbol={symbol}
            initialResolution="D"
            height={560}
            initialCustomSpecs={demo ? [{ spec: demo.spec, label: demo.label }] : []}
          />
        </div>
      </div>
    </div>
  );
};

const IdeaCard: React.FC<{
  idea: ScoutIdea;
  onDemo: () => void;
  onAccept: () => void;
  onDelete: () => void;
}> = ({ idea, onDemo, onAccept, onDelete }) => {
  const conf = Math.round((idea.confidence ?? 0) * 100);
  return (
    <div
      style={{
        border: `1px solid ${idea.spec_valid ? GREEN_DIM : RED}`,
        borderRadius: 6,
        padding: 12,
        background: 'rgba(0,255,65,0.03)',
        fontFamily: 'monospace',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ color: GREEN, fontWeight: 700, fontSize: 14 }}>{idea.title}</span>
        <span style={{ color: GREEN_DIM, fontSize: 11 }}>[{idea.source_type}]</span>
        <span style={{ color: GREEN_DIM, fontSize: 11 }}>conf {conf}%</span>
        {idea.accepted && <span style={{ color: GREEN, fontSize: 11 }}>✓ in arsenal</span>}
      </div>
      {idea.technique && (
        <div style={{ color: GREEN_DIM, fontSize: 11, marginTop: 2 }}>{idea.technique}</div>
      )}
      <div style={{ color: '#bbb', fontSize: 12, marginTop: 6 }}>{idea.description}</div>
      {idea.why_useful && (
        <div style={{ color: GREEN_DIM, fontSize: 12, marginTop: 4 }}>edge: {idea.why_useful}</div>
      )}
      {idea.source_url && (
        <a
          href={idea.source_url}
          target="_blank"
          rel="noreferrer"
          style={{ color: GREEN, fontSize: 11, marginTop: 4, display: 'inline-block', opacity: 0.8 }}
        >
          source ↗
        </a>
      )}
      {!idea.spec_valid && (
        <div style={{ color: RED, fontSize: 11, marginTop: 6 }}>
          ⚠ spec invalid: {idea.spec_errors?.slice(0, 2).join('; ')}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
        <button type="button" onClick={onDemo} disabled={!idea.spec_valid} style={{ ...btn, opacity: idea.spec_valid ? 1 : 0.4 }}>
          Demo
        </button>
        <button
          type="button"
          onClick={onAccept}
          disabled={!idea.spec_valid || idea.accepted}
          style={{ ...btn, opacity: idea.spec_valid && !idea.accepted ? 1 : 0.4 }}
        >
          Accept → arsenal
        </button>
        <button type="button" onClick={onDelete} style={{ ...btn, borderColor: RED, color: RED }}>
          Delete
        </button>
      </div>
    </div>
  );
};

export default ChartingScout;
