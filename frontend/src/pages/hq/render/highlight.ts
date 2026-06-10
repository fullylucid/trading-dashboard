// Compact, dependency-free syntax tokenizer for the console code blocks (E1). Covers the
// languages that actually show up in dev transcripts (ts/js/py/json/bash/css/html/diff) with a
// generic fallback. Returns {text, cls} tokens so the renderer emits React spans (no innerHTML,
// no XSS surface, no heavy highlighter dependency — matching HQ's lean MarkdownView taste).

export type TokClass = 'kw' | 'str' | 'com' | 'fn' | 'num' | 'punct' | '';
export type Token = { text: string; cls: TokClass };

type Lang = { kw: Set<string>; line?: string; block?: [string, string]; strs?: string };

const TS: Lang = {
  kw: new Set(
    ('const let var function return if else for while do switch case break continue class new ' +
     'import from export default await async type interface enum extends implements public private ' +
     'protected readonly static of in instanceof typeof void delete this super throw try catch finally ' +
     'yield as null undefined true false => get set').split(' '),
  ),
  line: '//', block: ['/*', '*/'], strs: "\"'`",
};
const PY: Lang = {
  kw: new Set(
    ('def return if elif else for while class import from as await async with try except finally raise ' +
     'lambda None True False and or not in is pass break continue global nonlocal yield assert del print ' +
     'self match case').split(' '),
  ),
  line: '#', strs: "\"'",
};
const BASH: Lang = {
  kw: new Set('if then fi else elif for in do done while until case esac function return export local readonly echo cd set'.split(' ')),
  line: '#', strs: "\"'",
};
const JSON_L: Lang = { kw: new Set(['true', 'false', 'null']), strs: '"' };
const CSS_L: Lang = { kw: new Set([]), block: ['/*', '*/'], strs: "\"'" };

const LANGS: Record<string, Lang> = {
  ts: TS, tsx: TS, js: TS, jsx: TS, javascript: TS, typescript: TS,
  py: PY, python: PY,
  sh: BASH, bash: BASH, shell: BASH, zsh: BASH,
  json: JSON_L,
  css: CSS_L, scss: CSS_L,
};

const ID = /[A-Za-z_$][\w$]*/y;
const NUM = /(?:0x[0-9a-fA-F]+|\d[\d_.]*(?:e[+-]?\d+)?)/y;

export function tokenize(code: string, lang?: string): Token[] {
  const L = LANGS[(lang || '').toLowerCase()];
  if (!L) return [{ text: code, cls: '' }];
  const out: Token[] = [];
  const push = (text: string, cls: TokClass) => text && out.push({ text, cls });
  const n = code.length;
  let i = 0;
  while (i < n) {
    const ch = code[i];

    // block comment
    if (L.block && code.startsWith(L.block[0], i)) {
      const end = code.indexOf(L.block[1], i + L.block[0].length);
      const stop = end === -1 ? n : end + L.block[1].length;
      push(code.slice(i, stop), 'com'); i = stop; continue;
    }
    // line comment
    if (L.line && code.startsWith(L.line, i)) {
      const end = code.indexOf('\n', i);
      const stop = end === -1 ? n : end;
      push(code.slice(i, stop), 'com'); i = stop; continue;
    }
    // string
    if (L.strs && L.strs.includes(ch)) {
      let j = i + 1;
      while (j < n && code[j] !== ch) { if (code[j] === '\\') j++; j++; }
      push(code.slice(i, Math.min(j + 1, n)), 'str'); i = j + 1; continue;
    }
    // number
    NUM.lastIndex = i;
    const numM = NUM.exec(code);
    if (numM && numM.index === i) { push(numM[0], 'num'); i += numM[0].length; continue; }
    // identifier / keyword / function
    ID.lastIndex = i;
    const idM = ID.exec(code);
    if (idM && idM.index === i) {
      const word = idM[0];
      let k = i + word.length;
      while (k < n && (code[k] === ' ' || code[k] === '\t')) k++;
      const cls: TokClass = L.kw.has(word) ? 'kw' : code[k] === '(' ? 'fn' : '';
      push(word, cls); i += word.length; continue;
    }
    // run of non-identifier punctuation/whitespace
    let j = i + 1;
    while (j < n && !/[A-Za-z0-9_$'"`]/.test(code[j]) && code[j] !== '\n') {
      if (L.line && code.startsWith(L.line, j)) break;
      if (L.block && code.startsWith(L.block[0], j)) break;
      j++;
    }
    const chunk = code.slice(i, j);
    push(chunk, /[{}()[\].,;:=<>+\-*/&|!?]/.test(chunk) ? 'punct' : '');
    i = j;
  }
  return out;
}
