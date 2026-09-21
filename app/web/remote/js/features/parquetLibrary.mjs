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

function ratingLetters(list) {
  const on = new Set(Array.isArray(list) ? list : []);
  return ['g', 's', 'q', 'e'].filter(r => on.has(r)).map(r => r.toUpperCase()).join('/');
}

// 한 줄: 앞말(흐리게) + 값 + '제외 …'(흐리게). 대문자 소제목·배지·키 열 없이 글줄로만 둔다
// (사용자: 너무 AI 티가 난다 - 옆 창들(아티스트 그룹·PE)과 같은 담백한 모양으로).
function line(lead, value, excluded, esc) {
  if (!value && !excluded) return '';
  return `<div class="pql-line"><span class="pql-lead">${esc(lead)}</span>${value ? `<span>${esc(value)}</span>` : ''}${
    excluded ? `<span class="pql-lead">제외</span><span>${esc(excluded)}</span>` : ''}</div>`;
}

// 그리드 HTML. 기본은 **이름만**(사용자 지정). 누른 칸은 한 줄을 통째로 차지하며 펼쳐진다.
// openNames = 펼친 칸, renaming = 이름 바꾸는 중, confirmTrash = 휴지통 한 번 누른 칸.
export function libraryHtml(cards, { escHtml, openNames = new Set(), renaming = null, confirmTrash = null } = {}) {
  const esc = escHtml || (s => String(s));
  const list = cards || [];
  const items = list.map(card => {
    const name = String(card.name || '');
    const label = name.replace(/\.parquet$/i, '');
    if (!openNames.has(name)) {
      return `<button type="button" class="pql-tile" data-pql-name="${esc(name)}" data-pql="expand" title="${esc(label)}">${esc(label)}</button>`;
    }
    const f = recipeFacts(card.recipe);
    const tf = f.tagFilter || {};
    const when = card.created_at ? String(card.created_at).replace('T', ' ').slice(5, 16) : '';
    const meta = [formatRows(card.rows), when].filter(Boolean).join(' · ');
    const body = card.has_meta === false || !card.recipe
      ? '<div class="pql-line pql-muted">조건 기록 없음</div>'
      : [
          f.search ? line('검색', f.search.query || '(전체)', f.search.exclude, esc) : '',
          line('Tag Filter', (tf.include || []).join(', '), (tf.exclude || []).join(', '), esc),
          `<div class="pql-line pql-muted">${esc([f.ratings ? ratingLetters(f.ratings) : '', f.search && f.search.period].filter(Boolean).join(' · '))}</div>`,
          ...f.origins.map(o => `<div class="pql-line pql-muted">${esc(o)}</div>`),
        ].join('');
    const title = renaming === name
      ? `<input class="pql-rename agw-name-input" data-pql-rename="${esc(name)}" value="${esc(label)}" spellcheck="false">`
      : `<span class="pql-open-name" data-pql="expand" title="접기">${esc(label)}</span>`;
    return `<div class="pql-tile is-open" data-pql-name="${esc(name)}">
      <div class="pql-open-head">${title}<span class="pql-meta">${esc(meta)}</span></div>
      ${body}
      <div class="pql-actions">
        <button type="button" class="agw-btn" data-pql="load" title="현재 풀을 이 파일로 바꿉니다">불러오기</button>
        <button type="button" class="agw-btn" data-pql="merge" title="현재 풀에 이 파일을 더합니다">합치기</button>
        <span class="pql-spacer"></span>
        <button type="button" class="agw-btn" data-pql="rename">이름 바꾸기</button>
        <button type="button" class="agw-btn danger${confirmTrash === name ? ' is-armed' : ''}" data-pql="trash">${confirmTrash === name ? '한 번 더' : '휴지통'}</button>
      </div>
    </div>`;
  }).join('');
  const empty = list.length ? '' : '<div class="pql-empty agw-empty">저장한 parquet 이 없습니다</div>';
  return `<div class="pql-grid">${items}${empty}</div>`;
}

export const PQL_CSS = `
.pql-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:5px;align-content:start}
.pql-tile{min-width:0;height:28px;padding:0 8px;border:1px solid var(--border-dim,#2c2c36);border-radius:7px;cursor:pointer;
  background:rgba(255,255,255,0.03);color:var(--text-secondary,#c8c8d0);font-size:11px;text-align:left;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pql-tile:hover{color:var(--text-primary,#e8e8ee);border-color:var(--accent,#8d7bd6)}
.pql-tile.is-open{grid-column:1/-1;height:auto;display:flex;flex-direction:column;gap:3px;padding:6px 8px;
  white-space:normal;cursor:default;border-color:var(--accent,#8d7bd6);background:rgba(255,255,255,0.04)}
.pql-open-head{display:flex;align-items:baseline;gap:8px;min-width:0;margin-bottom:1px}
.pql-open-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:11.5px;font-weight:600;color:var(--text-primary,#e8e8ee);cursor:pointer}
.pql-meta{font-size:10px;color:var(--text-muted,#9a9aa6);font-family:var(--font-mono,monospace);white-space:nowrap}
.pql-line{display:flex;flex-wrap:wrap;column-gap:5px;font-size:10.5px;line-height:1.5;color:var(--text-secondary,#c8c8d0);word-break:break-all}
.pql-lead{color:var(--text-muted,#9a9aa6)}
.pql-muted{color:var(--text-muted,#9a9aa6)}
.pql-actions{display:flex;gap:4px;align-items:center;margin-top:3px}
.pql-spacer{flex:1}
.pql-actions .agw-btn.is-armed{color:#ff9c9c;border-color:rgba(255,96,96,0.7)}
.pql-rename{flex:1}
.pql-empty{grid-column:1/-1}
.dragpanel.pqlw .dragpanel-body{padding:6px}
.search-save-form{display:flex;flex-direction:column;gap:4px;margin:4px 0;padding:6px 7px;border:1px solid var(--accent-green,#5a9e6f);border-radius:6px}
.search-save-form[hidden]{display:none!important}
.search-save-form .ssf-row{display:flex;gap:5px}
.search-save-form input{flex:1;min-width:0;font-size:11px;padding:2px 5px;background:var(--bg-surface,#15151b);color:var(--text,#e8e8ee);border:1px solid var(--border,#33333f);border-radius:4px}
.search-save-form .ssf-note{font-size:10px;color:var(--text-dim,#aaa);word-break:break-all}
`;
