import { Fragment, useState, type ReactNode } from 'react';
import { C } from './tokens';
import { tokenize, type TokClass } from './highlight';

// Rich, dependency-free markdown for the console (E1): paragraphs, headings, bold/italic, links,
// inline code, lists, blockquotes, hr, fenced code (syntax-highlighted), unified diffs, and
// inline images. React nodes only — no innerHTML. The refined premium-terminal aesthetic.

const SYN: Record<TokClass, string> = {
  kw: C.synKey, str: C.synStr, com: C.synCom, fn: C.synFn, num: C.synNum, punct: C.greenDim, '': C.ink,
};

export function looksLikeDiff(s: string): boolean {
  const lines = s.split('\n');
  const marked = lines.filter((l) => /^[+-]/.test(l) && !l.startsWith('+++') && !l.startsWith('---')).length;
  return lines.length >= 2 && marked >= 2 && (s.includes('@@') || marked / lines.length > 0.3);
}

export function DiffBlock({ source }: { source: string }) {
  return (
    <div style={{ margin: '8px 0 2px', border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', fontFamily: C.mono, fontSize: 12 }}>
      {source.replace(/\n$/, '').split('\n').map((ln, i) => {
        const add = ln.startsWith('+') && !ln.startsWith('+++');
        const del = ln.startsWith('-') && !ln.startsWith('---');
        const meta = ln.startsWith('@@') || ln.startsWith('+++') || ln.startsWith('---');
        return (
          <div key={i} style={{
            padding: '2px 12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            background: add ? C.diffAddBg : del ? C.diffDelBg : 'transparent',
            color: add ? C.diffAddInk : del ? C.diffDelInk : meta ? C.blue : C.muted,
          }}>{ln || ' '}</div>
        );
      })}
    </div>
  );
}

export function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const body = code.replace(/\n$/, '');
  const copy = () => {
    navigator.clipboard?.writeText(body).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); }).catch(() => {});
  };
  const toks = tokenize(body, lang);
  return (
    <div style={{ margin: '8px 0 2px', background: '#060a06', border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 10px', borderBottom: `1px solid ${C.line}`, fontFamily: C.mono, fontSize: 10.5, color: C.muted }}>
        <span>{lang || 'text'}</span>
        <button type="button" onClick={copy} style={{ background: 'transparent', border: 'none', color: copied ? C.green : C.muted, cursor: 'pointer', fontFamily: C.mono, fontSize: 10.5 }}>
          {copied ? '✓ copied' : 'copy'}
        </button>
      </div>
      <pre style={{ margin: 0, padding: '10px 12px', overflowX: 'auto', fontFamily: C.mono, fontSize: 12, lineHeight: 1.5 }}>
        {toks.map((t, i) => <span key={i} style={{ color: SYN[t.cls] }}>{t.text}</span>)}
      </pre>
    </div>
  );
}

// ---- inline ------------------------------------------------------------------------------
function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(!\[[^\]]*\]\([^)]+\))|(\[[^\]]+\]\([^)]+\))|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(_[^_]+_)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<Fragment key={`${key}-t${i}`}>{text.slice(last, m.index)}</Fragment>);
    const tok = m[0];
    if (tok.startsWith('![')) {
      const mm = /!\[([^\]]*)\]\(([^)]+)\)/.exec(tok)!;
      out.push(<img key={`${key}-img${i}`} src={mm[2]} alt={mm[1]} style={{ maxWidth: '100%', borderRadius: 8, border: `1px solid ${C.line}`, margin: '4px 0', display: 'block' }} />);
    } else if (tok.startsWith('[')) {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      out.push(<a key={`${key}-a${i}`} href={mm[2]} target="_blank" rel="noreferrer" style={{ color: C.blue, textDecoration: 'none' }}>{mm[1]}</a>);
    } else if (tok.startsWith('`')) {
      out.push(<code key={`${key}-c${i}`} style={{ fontFamily: C.mono, fontSize: 12, background: 'rgba(0,255,65,.1)', padding: '1px 5px', borderRadius: 4, color: C.green }}>{tok.slice(1, -1)}</code>);
    } else if (tok.startsWith('**')) {
      out.push(<strong key={`${key}-b${i}`} style={{ color: C.green, fontWeight: 700 }}>{tok.slice(2, -2)}</strong>);
    } else {
      out.push(<em key={`${key}-i${i}`}>{tok.slice(1, -1)}</em>);
    }
    last = m.index + tok.length; i += 1;
  }
  if (last < text.length) out.push(<Fragment key={`${key}-tE`}>{text.slice(last)}</Fragment>);
  return out;
}

const HSIZE = [19, 17, 15, 14, 13, 12];

export default function RichMarkdown(
  { source, dim = false, font, ink }: { source: string; dim?: boolean; font?: string; ink?: string },
) {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0, key = 0;
  // `ink` (the agents-side text colour, T1 theming) overrides the default prose colour; the dim
  // "thinking" variant keeps its violet regardless.
  const prose = dim ? 'rgba(183,155,255,.85)' : (ink || C.ink);

  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*```/.test(line)) {
      const lang = line.replace(/^\s*```/, '').trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      const code = buf.join('\n');
      blocks.push(lang === 'diff' || looksLikeDiff(code)
        ? <DiffBlock key={key++} source={code} />
        : <CodeBlock key={key++} code={code} lang={lang || undefined} />);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push(<div key={key++} style={{ fontSize: HSIZE[h[1].length - 1], fontWeight: 700, color: C.green, margin: '12px 0 6px' }}>{inline(h[2], `h${key}`)}</div>);
      i++; continue;
    }
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      blocks.push(<hr key={key++} style={{ border: 'none', borderTop: `1px solid ${C.line}`, margin: '10px 0' }} />);
      i++; continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''));
      blocks.push(<blockquote key={key++} style={{ borderLeft: `3px solid ${C.line2}`, margin: '8px 0', padding: '2px 0 2px 10px', color: C.muted }}>{inline(buf.join(' '), `q${key}`)}</blockquote>);
      continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\s*\d+\.\s+/.test(line);
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*+]|\d+\.)\s+/, ''));
      const ls: React.CSSProperties = { margin: '6px 0', paddingLeft: 20, color: prose };
      const li: React.CSSProperties = { margin: '3px 0', lineHeight: 1.5 };
      blocks.push(ordered
        ? <ol key={key++} style={ls}>{items.map((it, n) => <li key={n} style={li}>{inline(it, `li${key}-${n}`)}</li>)}</ol>
        : <ul key={key++} style={ls}>{items.map((it, n) => <li key={n} style={li}>{inline(it, `li${key}-${n}`)}</li>)}</ul>);
      continue;
    }
    if (/^\s*$/.test(line)) { i++; continue; }

    const para: string[] = [];
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^\s*```/.test(lines[i]) && !/^#{1,6}\s/.test(lines[i])
      && !/^\s*(---|\*\*\*|___)\s*$/.test(lines[i]) && !/^\s*>\s?/.test(lines[i]) && !/^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
      para.push(lines[i++]);
    }
    blocks.push(<p key={key++} style={{ margin: '0 0 8px', lineHeight: 1.6, color: prose, fontStyle: dim ? 'italic' : 'normal' }}>{inline(para.join(' '), `p${key}`)}</p>);
  }

  return <div style={{ fontFamily: font || C.sans, fontSize: 14 }}>{blocks}</div>;
}
