/**
 * CopilotPanel — the AI charting copilot for the current symbol.
 *
 * "Read chart" gives a concise TA read; the question box answers free-text questions.
 * Both call the reusable /api/ai/explain endpoint with kind="chart" (free local Opus
 * via the agent-bridge); the backend enriches the prompt with real server-computed TA
 * (signals / support-resistance / Fibonacci) so the model reasons from actual numbers.
 * The indicators currently on the chart are passed as context.
 */

import { useState } from 'react';

import { explainDatapoint } from '../../lib/aiApi';

const GREEN = '#00ff41';
const RED = '#ff3b3b';
const GREEN_DIM = 'rgba(0,255,65,0.3)';

const ctl: React.CSSProperties = {
  background: '#000',
  color: GREEN,
  border: `1px solid ${GREEN_DIM}`,
  fontFamily: 'monospace',
  fontSize: 12,
  padding: '5px 9px',
  borderRadius: 4,
};

const CopilotPanel: React.FC<{ symbol: string; indicators: string[] }> = ({ symbol, indicators }) => {
  const [question, setQuestion] = useState('');
  const [text, setText] = useState('');
  const [status, setStatus] = useState<'idle' | 'thinking' | 'done' | 'err'>('idle');
  const [errMsg, setErrMsg] = useState('');

  const ask = (q: string) => {
    setStatus('thinking');
    setText('');
    setErrMsg('');
    explainDatapoint('chart', { question: q, indicators }, symbol.toUpperCase())
      .then((r) => {
        setText(r.text);
        setStatus('done');
      })
      .catch((e) => {
        setStatus('err');
        setErrMsg(e?.response?.data?.detail || e?.message || 'AI unavailable (worker busy?)');
      });
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim()) ask(question.trim());
  };

  return (
    <div
      style={{
        border: `1px solid ${GREEN_DIM}`,
        borderRadius: 4,
        padding: 8,
        background: 'rgba(0,255,65,0.03)',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>🤖 copilot · {symbol}</span>
        <button
          type="button"
          onClick={() => ask('')}
          disabled={status === 'thinking'}
          style={{ ...ctl, cursor: 'pointer' }}
        >
          📊 Read chart
        </button>
        {['What are the key levels?', 'Is it overbought or oversold?', "What's the trend?"].map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => ask(q)}
            disabled={status === 'thinking'}
            style={{ ...ctl, cursor: 'pointer', fontSize: 11, opacity: 0.85 }}
          >
            {q}
          </button>
        ))}
      </div>

      <form onSubmit={submit} style={{ display: 'flex', gap: 6 }}>
        <input
          aria-label="Ask the copilot"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={`Ask about ${symbol}…`}
          style={{ ...ctl, flex: 1 }}
        />
        <button type="submit" disabled={status === 'thinking' || !question.trim()} style={{ ...ctl, cursor: 'pointer' }}>
          Ask
        </button>
      </form>

      {status === 'thinking' && (
        <div style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 12 }}>thinking…</div>
      )}
      {status === 'err' && (
        <div style={{ color: RED, fontFamily: 'monospace', fontSize: 12 }}>⚠ {errMsg}</div>
      )}
      {status === 'done' && text && (
        <div
          style={{
            color: '#d7ffe4',
            fontFamily: 'monospace',
            fontSize: 13,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
          }}
        >
          {text}
        </div>
      )}
    </div>
  );
};

export default CopilotPanel;
