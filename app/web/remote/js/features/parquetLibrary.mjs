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

// 카드 목록 HTML. openNames = 펼친 카드 이름 Set, moreName = [⋯] 메뉴가 열린 카드, renaming = 이름 바꾸는 중인 카드.
export function libraryHtml(cards, { escHtml, openNames = new Set(), moreName = null, renaming = null, confirmTrash = null } = {}) {
  const esc = escHtml || (s => String(s));
  const list = cards || [];
  const items = list.map(card => {
    const name = String(card.name || '');
    const summary = recipeSummary(card.recipe);
    const open = openNames.has(name);
    const detail = open && summary
      ? `<div class="pql-detail">${recipeLines(card.recipe).map(l =>
          `<div class="pql-line" style="padding-left:${l.depth * 12}px">${l.depth ? '↳ ' : ''}${esc(l.text)}</div>`).join('')}
         ${card.created_at ? `<div class="pql-line pql-dim">저장 ${esc(String(card.created_at).replace('T', ' '))}</div>` : ''}</div>`
      : '';
    const nameCell = renaming === name
      ? `<input class="pql-rename" data-pql-rename="${esc(name)}" value="${esc(name.replace(/\.parquet$/i, ''))}" spellcheck="false">`
      : `<span class="pql-name" title="${esc(name)}">${esc(name.replace(/\.parquet$/i, ''))}</span>`;
    const more = moreName === name
      ? `<div class="pql-more">
          <button type="button" data-pql="rename">이름 바꾸기</button>
          <button type="button" data-pql="trash" class="${confirmTrash === name ? 'pql-danger' : ''}">${confirmTrash === name ? '한 번 더 누르면 휴지통' : '휴지통으로'}</button>
        </div>`
      : '';
    return `<div class="pql-card${open ? ' is-open' : ''}" data-pql-name="${esc(name)}">
      <div class="pql-row">
        ${nameCell}
        <span class="pql-rows">${esc(formatRows(card.rows))}</span>
        <button type="button" class="pql-btn" data-pql="load" title="현재 풀을 이 파일로 바꿉니다">불러오기</button>
        <button type="button" class="pql-btn" data-pql="merge" title="현재 풀에 이 파일을 더합니다">합치기</button>
        <button type="button" class="pql-btn pql-icon" data-pql="more" title="이름 바꾸기 · 휴지통">⋯</button>
      </div>
      <div class="pql-recipe${summary ? '' : ' pql-dim'}" data-pql="expand" title="${summary ? '눌러서 펼치기' : ''}">${esc(summary || '조건 기록 없음')}</div>
      ${detail}${more}
    </div>`;
  }).join('');
  const empty = list.length ? '' : '<div class="pql-empty">아직 저장한 parquet 이 없습니다. [Load / Save Parquets] ▸ 이 결과 저장…으로 만듭니다.</div>';
  return `<div class="pql-list">${items}${empty}</div>`;
}

export const PQL_CSS = `
.pql-list{display:flex;flex-direction:column;gap:4px;margin-top:4px}
.pql-card{border:1px solid var(--border,#2c2c36);border-radius:6px;padding:5px 7px;background:var(--bg-elevated,#1d1d24)}
.pql-card.is-open{border-color:var(--accent-blue,#8d7bd6)}
.pql-row{display:flex;align-items:center;gap:5px;min-width:0}
.pql-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;font-weight:600;color:var(--text,#e8e8ee)}
.pql-rename{flex:1;min-width:0;font-size:11px;padding:1px 4px;background:var(--bg-surface,#15151b);color:var(--text,#e8e8ee);border:1px solid var(--accent-blue,#8d7bd6);border-radius:4px}
.pql-rows{font-family:var(--font-mono,monospace);font-size:10px;color:var(--accent-green,#5a9e6f);white-space:nowrap}
.pql-btn{height:20px;padding:0 6px;font-size:10px;border-radius:4px;border:1px solid var(--border,#33333f);background:transparent;color:var(--text-dim,#aaa);cursor:pointer;white-space:nowrap}
.pql-btn:hover{color:var(--text,#e8e8ee);border-color:var(--accent-blue,#8d7bd6)}
.pql-icon{padding:0 5px}
.pql-recipe{margin-top:2px;font-size:10px;color:var(--text-dim,#aaa);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.pql-dim{color:var(--text-dimmer,#6c6c78);font-style:italic}
.pql-detail{margin-top:4px;padding-top:4px;border-top:1px dashed var(--border,#2c2c36)}
.pql-line{font-size:10px;line-height:1.5;color:var(--text,#d8d8e0);word-break:break-all}
.pql-more{display:flex;gap:5px;margin-top:4px}
.pql-more button{height:20px;padding:0 8px;font-size:10px;border-radius:4px;border:1px solid var(--border,#33333f);background:transparent;color:var(--text-dim,#aaa);cursor:pointer}
.pql-more button.pql-danger{border-color:#b85454;color:#f0a0a0}
.pql-empty{font-size:10px;color:var(--text-dimmer,#6c6c78);padding:4px 2px}
.search-save-form{display:flex;flex-direction:column;gap:4px;margin:4px 0;padding:6px 7px;border:1px solid var(--accent-green,#5a9e6f);border-radius:6px}
.search-save-form[hidden]{display:none!important}
.search-save-form .ssf-row{display:flex;gap:5px}
.search-save-form input{flex:1;min-width:0;font-size:11px;padding:2px 5px;background:var(--bg-surface,#15151b);color:var(--text,#e8e8ee);border:1px solid var(--border,#33333f);border-radius:4px}
.search-save-form .ssf-note{font-size:10px;color:var(--text-dim,#aaa);word-break:break-all}
`;
