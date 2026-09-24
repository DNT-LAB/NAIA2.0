// Custom Parquet 라이브러리 카드 - "이 파일에 무엇이 들었나" 를 보여 준다.
//
// 백엔드(core/custom_parquet_library.py)가 저장 시 parquet 에 '명함'(만든 조건)을 새기고,
// search_state.parquet_library 로 카드 목록을 보낸다: {name, rows, size, mtime, source, recipe, has_meta}.
// 이 모듈은 **순수 함수**만 둔다(DOM 없음) - node 로 시험한다(tests/test_parquet_library_frontend.mjs).
//
// 레시피는 부모를 품는 사슬이다: export → parent(search | file | merge | refine) → ...
// 카드 한 줄 요약 = 사슬을 '←' 로 잇고, 펼치면 한 단계씩 줄로 보인다.

const ALL_RATINGS = ['e', 'g', 'q', 's'];
const MAX_DEPTH = 8;

function ratingText(ratings) {
  const list = Array.isArray(ratings) ? ratings.slice().sort() : [];
  if (!list.length || list.join('') === ALL_RATINGS.join('')) return '';
  return list.join('/');
}

function quoted(text) {
  const s = String(text || '').trim();
  return s ? `"${s}"` : '';
}

function tagList(tags) {
  return (Array.isArray(tags) ? tags : []).map(t => String(t)).filter(Boolean).join(', ');
}

function filterText(filters) {
  if (!filters || typeof filters !== 'object') return '';
  const out = [];
  for (const [key, spec] of Object.entries(filters)) {
    if (spec && typeof spec === 'object' && 'enabled' in spec) {
      if (spec.enabled) out.push(`${key} ${spec.value}`);
    } else if (spec === true) {
      out.push(key);
    }
  }
  return out.join(', ');
}

function join(parts) {
  return parts.filter(Boolean).join(' · ');
}

// 레시피 한 단계의 한 줄 설명.
export function recipeLine(recipe) {
  if (!recipe || typeof recipe !== 'object') return '';
  switch (recipe.source) {
    case 'search':
      return join([
        `검색 ${quoted(recipe.query) || '(전체)'}`,
        recipe.exclude ? `제외 ${quoted(recipe.exclude)}` : '',
        recipe.exclude_permanent ? `영구 제외 ${quoted(recipe.exclude_permanent)}` : '',
        ratingText(recipe.ratings),
        recipe.period || '',
      ]);
    case 'file':
      return `파일 ${recipe.name || '?'}${recipe.uploaded ? ' (PC에서)' : ''}`;
    case 'merge':
      return `합치기 ${(recipe.parts || []).length}개`;
    case 'refine': {
      const merged = (recipe.history || []).filter(h => h && h.step === 'merge_staging').length;
      return join([
        `심층검색 ${quoted(recipe.query) || '(전체)'}`,
        recipe.exclude ? `제외 ${quoted(recipe.exclude)}` : '',
        ratingText(recipe.ratings),
        filterText(recipe.filters),
        merged ? `스테이징 병합 ${merged}회` : '',
      ]);
    }
    case 'export': {
      const tf = recipe.tag_filter || {};
      return join([
        tf.include && tf.include.length ? `Tag Filter ${tagList(tf.include)}` : '',
        tf.exclude && tf.exclude.length ? `제외 ${tagList(tf.exclude)}` : '',
        ratingText(recipe.ratings),
      ]) || '조건 없이 저장';
    }
    case 'more':
      return `외 ${recipe.count || 0}개`;
    default:
      return recipe.source ? String(recipe.source) : '';
  }
}

// 사슬을 위(마지막 단계) → 아래(뿌리) 순서의 줄 목록으로. merge 는 조각을 들여써서 펼친다.
export function recipeLines(recipe) {
  const lines = [];
  let cur = recipe;
  for (let depth = 0; cur && typeof cur === 'object' && depth < MAX_DEPTH; depth += 1) {
    const text = recipeLine(cur);
    if (text) lines.push({ depth, text });
    if (cur.source === 'merge') {
      for (const part of cur.parts || []) {
        const partText = recipeLine(part);
        const inner = part && part.source === 'file' && part.recipe ? recipeLine(part.recipe) : '';
        if (partText) lines.push({ depth: depth + 1, part: true, text: inner ? `${partText} ← ${inner}` : partText });
      }
      break;
    }
    if (cur.truncated) {
      lines.push({ depth: depth + 1, text: '(이전 단계 생략)' });
      break;
    }
    cur = cur.parent || (cur.source === 'file' ? cur.recipe : null);
  }
  return lines;
}

// 카드 한 줄 요약. 명함이 없으면 null(= "조건 기록 없음").
// 합치기 조각은 요약에 넣지 않는다(한 줄이 끝없이 길어진다) - 펼치면 보인다.
export function recipeSummary(recipe) {
  const lines = recipeLines(recipe).filter(l => !l.part);
  if (!lines.length) return null;
  return lines.map(l => l.text).join(' ← ');
}

export function formatRows(rows) {
  if (rows === null || rows === undefined) return '? 행';
  return `${Number(rows).toLocaleString('en-US')}행`;
}

export function formatSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

// 행 수(연노랑) · 용량 - 접힌 칸과 펼친 칸이 같은 모양으로 쓴다.
function sizeMeta(card, esc) {
  const size = formatSize(card.size);
  return `<span class="pql-rows">${esc(formatRows(card.rows))}</span>${size ? ` · ${esc(size)}` : ''}`;
}

export function librarySignature(cards) {
  return JSON.stringify((cards || []).map(c => [c.name, c.mtime, c.rows, c.has_meta]));
}

// 카드를 펼쳤을 때 보이는 '만든 조건' 을 칸별로 뽑는다(사용자 지정 2026-09-21):
//   등급(G/S/Q/E) · Search(검색어·제외어·기간) · Tag Filter(포함·제외) · 그 밖의 출처(파일·합치기·심층검색).
// 저장 = Search 결과 ∩ Tag Filter ∩ 등급(교집합). 사슬을 거슬러 올라가며 가장 가까운 것을 쓴다.
export function recipeFacts(recipe) {
  const facts = { ratings: null, search: null, tagFilter: null, origins: [] };
  let cur = recipe;
  for (let depth = 0; cur && typeof cur === 'object' && depth < MAX_DEPTH; depth += 1) {
    if (cur.source === 'export') {
      if (!facts.ratings && Array.isArray(cur.ratings)) facts.ratings = cur.ratings;
      if (!facts.tagFilter && cur.tag_filter) facts.tagFilter = cur.tag_filter;
    } else if (cur.source === 'search') {
      if (!facts.search) facts.search = cur;
      if (!facts.ratings && Array.isArray(cur.ratings)) facts.ratings = cur.ratings;
    } else if (cur.source === 'merge') {
      const names = (cur.parts || []).map(p => (p && p.name) || recipeLine(p)).filter(Boolean);
      facts.origins.push(`합치기: ${names.join(' + ')}`);
      break;   // 조각마다 조건이 다르다 - 하나로 뭉뚱그리지 않는다(단계 병합 레시피는 미정)
    } else if (cur.source === 'refine' || cur.source === 'file' || cur.source === 'more') {
      facts.origins.push(recipeLine(cur));
    }
    if (cur.truncated) { facts.origins.push('(이전 단계 생략)'); break; }
    cur = cur.parent || (cur.source === 'file' ? cur.recipe : null);
  }
  return facts;
}

function ratingPills(ratings, esc) {
  const on = new Set(Array.isArray(ratings) ? ratings : []);
  return ['g', 's', 'q', 'e'].map(r =>
    `<span class="pql-pill${on.has(r) ? ' is-on' : ''}" data-r="${r}">${esc(r.toUpperCase())}</span>`).join('');
}

function factRow(label, value, esc, cls = '') {
  if (!value) return '';
  return `<div class="pql-fact"><span class="pql-fact-k">${esc(label)}</span><span class="pql-fact-v ${cls}">${esc(value)}</span></div>`;
}

// 그리드 HTML. 기본은 **이름만**(사용자 지정). 누른 칸은 한 줄을 통째로 차지하며 펼쳐진다.
// openNames = 펼친 칸, renaming = 이름 바꾸는 중, confirmTrash = 휴지통 한 번 누른 칸.
export function libraryHtml(cards, { escHtml, openNames = new Set(), renaming = null, confirmTrash = null } = {}) {
  const esc = escHtml || (s => String(s));
  const list = cards || [];
  const items = list.map(card => {
    const name = String(card.name || '');
    const label = name.replace(/\.parquet$/i, '');
    const open = openNames.has(name);
    if (!open) {
      // 접힌 칸 = 한 줄을 가득 채운다(사용자 지정): 이름 ··· 행 수 · 용량. 조건은 펼쳐야 보인다.
      return `<button type="button" class="pql-tile" data-pql-name="${esc(name)}" data-pql="expand" title="${esc(label)}">
        <span class="pql-tile-name">${esc(label)}</span>
        <span class="pql-stamp">${sizeMeta(card, esc)}</span>
      </button>`;
    }
    const f = recipeFacts(card.recipe);
    const search = f.search;
    const tf = f.tagFilter || {};
    const body = card.has_meta === false || !card.recipe
      ? '<div class="pql-fact pql-dim">조건 기록 없음 (명함 이전에 저장한 파일)</div>'
      : `<div class="pql-fact"><span class="pql-fact-k">등급</span><span class="pql-fact-v">${f.ratings ? ratingPills(f.ratings, esc) : '<span class="pql-dim">기록 없음</span>'}</span></div>
        <div class="pql-group">Search</div>
        ${search ? factRow('검색', search.query || '(전체)', esc) + factRow('제외', search.exclude, esc, 'is-x')
                   + factRow('영구 제외', search.exclude_permanent, esc, 'is-x') + factRow('기간', search.period, esc)
                 : '<div class="pql-fact pql-dim">—</div>'}
        <div class="pql-group">Tag Filter</div>
        ${(tf.include && tf.include.length) || (tf.exclude && tf.exclude.length)
          ? factRow('포함', (tf.include || []).join(', '), esc) + factRow('제외', (tf.exclude || []).join(', '), esc, 'is-x')
          : '<div class="pql-fact pql-dim">—</div>'}
        ${f.origins.length ? `<div class="pql-group">출처</div>${f.origins.map(o => `<div class="pql-fact pql-origin">${esc(o)}</div>`).join('')}` : ''}`;
    const title = renaming === name
      ? `<input class="pql-rename" data-pql-rename="${esc(name)}" value="${esc(label)}" spellcheck="false">`
      : `<span class="pql-open-name" data-pql="expand" title="접기">${esc(label)}</span>`;
    const when = card.created_at ? String(card.created_at).replace('T', ' ').slice(0, 16) : '';
    return `<div class="pql-tile is-open" data-pql-name="${esc(name)}">
      <div class="pql-open-head">${title}<span class="pql-stamp">${sizeMeta(card, esc)}${when ? ` · ${esc(when)}` : ''}</span></div>
      <div class="pql-facts">${body}</div>
      <div class="pql-actions">
        <button type="button" class="pql-btn is-main" data-pql="load" title="현재 풀을 이 파일로 바꿉니다">불러오기</button>
        <button type="button" class="pql-btn" data-pql="merge" title="현재 풀에 이 파일을 더합니다">합치기</button>
        <span class="pql-spacer"></span>
        <button type="button" class="pql-btn" data-pql="rename">이름 바꾸기</button>
        <button type="button" class="pql-btn${confirmTrash === name ? ' pql-danger' : ''}" data-pql="trash">${confirmTrash === name ? '한 번 더 → 휴지통' : '휴지통'}</button>
      </div>
    </div>`;
  }).join('');
  const empty = list.length ? '' : '<div class="pql-empty">아직 저장한 parquet 이 없습니다. [Load / Save Parquets] ▸ 이 결과 저장…으로 만듭니다.</div>';
  return `<div class="pql-grid">${items}${empty}</div>`;
}

export const PQL_CSS = `
/* 한 칸 = 한 줄(사용자 지정) - 여러 열로 두면 짧은 목록에서 칸이 줄을 못 채우고 빈 자리가 남았다. */
.pql-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:5px;align-content:start}
/* 칸 안쪽은 창 배경보다 어둡게 - 같은 색이면 칸과 창이 구분되지 않는다(사용자 지정). */
.pql-tile{display:flex;align-items:center;min-width:0;height:34px;padding:0 9px;border-radius:6px;cursor:pointer;text-align:left;
  border:1px solid var(--border,#2c2c36);background:rgba(0,0,0,0.24);color:var(--text,#e8e8ee)}
.pql-tile:hover{border-color:var(--accent-blue,#8d7bd6)}
.pql-tile-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;font-weight:600}
.pql-tile > .pql-stamp{margin-left:8px;flex:0 0 auto}
/* 선택 안 한 칸은 강조 없이 조금 덜 밝은 흰색(사용자 지정) - 연노랑 행 수는 펼친 칸에서만. */
.pql-tile:not(.is-open){color:rgba(255,255,255,0.80)}
.pql-tile:not(.is-open) > .pql-stamp{color:rgba(255,255,255,0.58)}
.pql-tile:not(.is-open) .pql-rows{color:inherit;font-weight:inherit}
.pql-tile.is-open{grid-column:1/-1;height:auto;display:flex;flex-direction:column;align-items:stretch;gap:6px;padding:7px 9px;
  cursor:default;border-color:var(--accent-blue,#8d7bd6);background:rgba(0,0,0,0.32)}
.pql-open-head{display:flex;align-items:baseline;gap:8px;min-width:0}
.pql-open-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:700;cursor:pointer}
.pql-stamp{font-family:var(--font-mono,monospace);font-size:10px;color:var(--text-muted,#9a9aa6);white-space:nowrap}
.pql-rows{color:#f5dc8a;font-weight:700}
.pql-rename{flex:1;min-width:0;font-size:11px;padding:1px 4px;background:var(--bg-surface,#15151b);color:var(--text,#e8e8ee);border:1px solid var(--accent-blue,#8d7bd6);border-radius:4px}
.pql-facts{display:flex;flex-direction:column;gap:2px}
.pql-group{margin-top:3px;font-size:9.5px;font-weight:700;letter-spacing:.04em;color:var(--text-muted,#9a9aa6);text-transform:uppercase}
.pql-fact{display:flex;gap:6px;font-size:10.5px;line-height:1.45;min-width:0}
.pql-fact-k{flex:0 0 30px;color:var(--text-dimmer,#6c6c78)}
.pql-fact-v{flex:1;min-width:0;word-break:break-all;color:var(--text,#d8d8e0);display:flex;flex-wrap:wrap;gap:3px}
.pql-fact-v.is-x{color:#e39a9a}
.pql-origin{color:var(--text-dim,#aaa)}
.pql-pill{display:inline-flex;align-items:center;justify-content:center;width:18px;height:16px;border-radius:3px;font-size:9.5px;font-weight:700;
  border:1px solid var(--border,#33333f);color:var(--text-dimmer,#6c6c78)}
/* 켜진 등급 = Quick Filter 의 .rating-btn.active 색 그대로(style.css). */
.pql-pill.is-on[data-r="g"]{background:#2e7d32;color:#fff;border-color:#4CAF50}
.pql-pill.is-on[data-r="s"]{background:#1565C0;color:#fff;border-color:#2196F3}
.pql-pill.is-on[data-r="q"]{background:#e65100;color:#fff;border-color:#FF9800}
.pql-pill.is-on[data-r="e"]{background:#c62828;color:#fff;border-color:#F44336}
.pql-dim{color:var(--text-dimmer,#6c6c78);font-style:italic}
.pql-actions{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.pql-spacer{flex:1}
.pql-btn{height:22px;padding:0 8px;font-size:10.5px;border-radius:4px;border:1px solid var(--border,#33333f);background:transparent;color:var(--text-dim,#aaa);cursor:pointer;white-space:nowrap}
.pql-btn:hover{color:var(--text,#e8e8ee);border-color:var(--accent-blue,#8d7bd6)}
.pql-btn.is-main{background:#2e7d32;border-color:#4CAF50;color:#fff;font-weight:600}
.pql-btn.is-main:hover{background:#388e3c;border-color:#66bb6a;color:#fff}
.pql-btn.pql-danger{border-color:#b85454;color:#f0a0a0}
.pql-empty{grid-column:1/-1;font-size:10.5px;color:var(--text-dimmer,#6c6c78);padding:6px 2px}
.dragpanel.pqlw{border-color:rgba(120,190,150,0.42)}
.dragpanel.pqlw .dragpanel-head{background:rgba(120,190,150,0.10)}
.dragpanel.pqlw .dragpanel-body{padding:7px}
.search-save-form{display:flex;flex-direction:column;gap:4px;margin:4px 0;padding:6px 7px;border:1px solid var(--accent-green,#5a9e6f);border-radius:6px}
.search-save-form[hidden]{display:none!important}
.search-save-form .ssf-row{display:flex;gap:5px}
.search-save-form input{flex:1;min-width:0;font-size:11px;padding:2px 5px;background:var(--bg-surface,#15151b);color:var(--text,#e8e8ee);border:1px solid var(--border,#33333f);border-radius:4px}
.search-save-form .ssf-note{font-size:10px;color:var(--text-dim,#aaa);word-break:break-all}
`;
