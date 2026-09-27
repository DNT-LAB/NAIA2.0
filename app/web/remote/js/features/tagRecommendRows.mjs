// 메인 프롬프트 태그 카드의 **유형별 추천 줄**(2026-09-26). 순수 함수만 둔다 - tagAssist 가 그리고
// 누르기를 처리하며, node 시험이 직접 부른다.
//
// 데이터는 백엔드가 관계 팩(tools/build_tag_relation_pack.py)에서 꺼내 `tag_lookup_result.recommend`
// 로 싣는다. 메인 입력칸이 보낸 조회에만 온다 - 다른 칸(Search 창 등)의 카드는 그대로다.
// 줄은 Codex 제품 계약의 display_type, 누르면 할 일은 칩마다의 edit_policy 다(2026-09-27):
// ⇄ 칩 = 커서 태그를 바꾼다(검토된 같은 축 대안 · 부재 · 뜻을 품는 구체화), 나머지는 뒤에 더한다.
// 대표 줄과 유형 단추(2026-09-27, 사용자 지정): 앞의 대표 줄 3개 · 칩 4개만 보이고, 나머지는 아래 유형 단추
// [종류 5] [상태 12] … 로 **한 유형씩** 편다 - 한꺼번에 펴니 정보가 너무 많았다. 칩은 관련도 순 앞에서 고르고,
// 보일 때는 빌더가 정한 자리(key: ⇄ -> 색 -> 무늬·소재 -> 모양 -> ABC, 대안은 축 순서)로 선다.

// 줄 순서가 곧 대표 줄을 고르는 차례다 - 앞에서부터 칩이 있는 줄 3개. 지금 태그를 다듬는 대안 · 종류 · 상태가
// 먼저다. 이름은 사용자가 고른 한국어 짧은 이름(2026-09-27), 설명은 이름표·단추에 마우스를 올리면 뜬다.
const OP_HINT = ' - ⇄ 는 지금 태그를 바꾸고, 나머지는 뒤에 더합니다';
export const RECOMMEND_TYPES = [
  {key: 'siblings', label: '대안', hint: '같은 자리의 다른 선택 (short hair ↔ long hair)' + OP_HINT},
  {key: 'variations', label: '종류', hint: '더 구체적인 것 (chair → armchair)' + OP_HINT},
  {key: 'state', label: '상태', hint: '상태 (open shirt · wet shirt)' + OP_HINT},
  {key: 'companions', label: '함께', hint: '같이 잘 쓰는 것 (smile → blush)' + OP_HINT},
  {key: 'attributes', label: '스타일', hint: '색 · 무늬 · 모양 (white shirt · sleeveless)' + OP_HINT},
  {key: 'action', label: '동작', hint: '동작 (shirt tug · holding shirt)' + OP_HINT},
  {key: 'parts', label: '부분', hint: '부분 (pocket · hood · ahoge)' + OP_HINT},
  {key: 'context', label: '연출', hint: '연출 (naked shirt · on chair · hair over shoulder)' + OP_HINT},
];

// 추천 프롬프트 줄(사용자 지정 2026-09-27) - 서버가 고른 태그에서 함께 1 · 상태 1 을 골라 온다(recommend.fill).
const FILL_HINT = '이 태그에 어울리는 것 - 함께 1 · 상태 1 (색 · 스타일은 직접 고르세요). 누르면 뒤에 더합니다';

// 대표 줄 수와 그 줄에 보이는 칩 수. 나머지는 유형 단추 뒤에 둔다(카드가 화면을 덮지 않게).
export const RECOMMEND_LEAD_ROWS = 3;
export const RECOMMEND_LEAD_CHIPS = 4;

const WEIGHT_PREFIX = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*/;

/** 프롬프트 토큰 하나를 비교용 태그 이름으로(가중치·괄호·이스케이프·밑줄을 걷는다). */
export function normalizePromptTag(token) {
  let t = String(token ?? '').trim();
  if (!t || t.startsWith('#')) return '';
  if (t.startsWith('-(')) t = t.substring(1);
  while (WEIGHT_PREFIX.test(t)) t = t.replace(WEIGHT_PREFIX, '');
  t = t.replace(/\s*::\s*$/, '');
  let changed = true;
  while (changed && t.length >= 2) {
    changed = false;
    const first = t[0];
    const last = t[t.length - 1];
    if ((first === '(' && last === ')') || (first === '[' && last === ']') || (first === '{' && last === '}')) {
      t = t.substring(1, t.length - 1).trim();
      changed = true;
    }
  }
  t = t.replace(/:\d+(?:\.\d+)?$/, '');
  t = t.replace(/\\([()[\]])/g, '$1');
  return t.replace(/_/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
}

// 추천 프롬프트의 맥락 = 메인 칸의 **명확한 단부루 태그**(사용자 지정 2026-09-27). 쉼표·줄바꿈·가중치로 나뉜 토큰만
// 보고, 자연어 문장(낱말 6개 · 64자 넘게) · 와일드카드 · 변수 · 대안 문법 · 음의 가중치(빼 달라는 태그)는 뺀다.
// 서버가 이것을 다시 사전과 맞춰 본다. Prefix/Postfix 는 다른 칸이라 애초에 안 읽는다.
export const PROMPT_TAG_LIMIT = 150;
const NEGATIVE_WEIGHT = /^\s*-\s*(?:\d+(?:\.\d*)?|\.\d+)\s*::/;

export function promptTagList(text, limit = PROMPT_TAG_LIMIT) {
  const out = [];
  const seen = new Set();
  for (const part of String(text ?? '').split(/[,\n]/)) {
    if (NEGATIVE_WEIGHT.test(part) || part.includes('__')) continue;      // 와일드카드는 밑줄을 걷기 **전에** 본다
    const tag = normalizePromptTag(part);
    if (!tag || tag.length > 64 || tag.split(' ').length > 6 || /__|[$|{}]/.test(tag) || seen.has(tag)) continue;
    seen.add(tag);
    out.push(tag);
    if (out.length >= limit) break;
  }
  return out;
}

const escapeAttr = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** 프롬프트에 이미 있는 태그들 - 추천에서 뺀다(같은 칩을 또 권하지 않는다). */
export function promptTagSet(text) {
  const out = new Set();
  for (const part of String(text ?? '').split(/[,\n]/)) {
    const tag = normalizePromptTag(part);
    if (tag) out.add(tag);
  }
  return out;
}

/** 보일 차례로 세운다 - key(빌더가 정한 자리)가 있으면 그 순서, 없으면(옛 팩) 받은 순서 그대로. */
export function displayOrder(items) {
  return items.map((item, i) => [item, Number.isInteger(item?.key) ? item.key : i, i])
    .sort((a, b) => a[1] - b[1] || a[2] - b[2])
    .map(([item]) => item);
}

/**
 * 유형별 줄의 HTML. groups = 백엔드의 [{type, items: [{tag, op, key}]}] - items 는 관련도 순이다.
 * renderChip(tag, extraClass, extraAttrs) 는 호출자의 칩 그리개(설명 호버·data-insert 를 붙인다).
 * 앞의 leadRows 줄이 대표 줄(관련도 앞의 칩 leadChips 개). 그 줄의 남은 칩과 나머지 줄은 유형 단추
 * (data-reco-tab)와 그 아래 칸(data-reco-panel)으로 그려 두고, tagAssist 가 누른 유형의 칸만 연다.
 * 칩은 어디서나 key 순으로 선다. 숨길 것이 없으면 단추도 칸도 없다.
 * fill = 서버의 추천 프롬프트(함께 1 · 상태 1) - 맨 위 '추천' 줄. 둘 이상이면 [모두 넣기](한 칩처럼 한 번에 더한다).
 * 그릴 칩이 하나도 없으면 '' - 호출자는 옛 related 줄로 돌아간다.
 */
export function recommendRowsHtml(groups, {
  present = new Set(), current = '', renderChip, fill = [],
  leadRows = RECOMMEND_LEAD_ROWS, leadChips = RECOMMEND_LEAD_CHIPS,
} = {}) {
  if (!Array.isArray(groups) || typeof renderChip !== 'function') return '';
  const byType = new Map();
  for (const group of groups) {
    if (group && typeof group.type === 'string' && Array.isArray(group.items)) byType.set(group.type, group.items);
  }
  const self = normalizePromptTag(current);
  // 모르는 유형(팩이 새 줄을 더했다)도 버리지 않는다 - 아는 줄 뒤에 이름 그대로 그린다.
  const known = new Set(RECOMMEND_TYPES.map(t => t.key));
  const extra = [...byType.keys()].filter(key => !known.has(key) && /^[a-z_]+$/.test(key))
    .map(key => ({key, label: key.charAt(0).toUpperCase() + key.slice(1), hint: ''}));
  const rows = [];
  for (const type of [...RECOMMEND_TYPES, ...extra]) {
    const items = (byType.get(type.key) || []).filter(item => {
      const key = normalizePromptTag(item?.tag);
      return key && key !== self && !present.has(key);
    });
    if (items.length) rows.push({type, items});
  }
  // 서버가 준 뒤에 프롬프트가 바뀌었을 수 있다 - 지금 칸에 있는 것은 여기서도 뺀다.
  const fillItems = (Array.isArray(fill) ? fill : []).filter(item => {
    const key = normalizePromptTag(item?.tag);
    return key && key !== self && !present.has(key);
  });
  if (!rows.length && !fillItems.length) return '';
  const fillAll = fillItems.length > 1
    ? `<span class="tag-tooltip-extra-tag reco-fill-all" data-insert="${escapeAttr(fillItems.map(item => item.tag).join(', '))}" data-op="add">모두 넣기</span>`
    : '';
  const head = fillItems.length
    ? `<div class="tag-tooltip-extra tag-reco-row tag-reco-fill" data-reco-type="fill">`
      + `<span class="tag-tooltip-extra-label" data-naia-title="${FILL_HINT}">추천</span>`
      + fillItems.map(item => renderChip(String(item.tag), 'is-add', 'data-op="add"')).join('') + fillAll + '</div>'
    : '';
  const chipsHtml = items => displayOrder(items).map(item => {
    const replace = item.op === 'replace';
    return renderChip(String(item.tag), replace ? 'is-replace' : 'is-add', `data-op="${replace ? 'replace' : 'add'}"`);
  }).join('');
  let lead = '';
  let tabs = '';
  let panels = '';
  rows.forEach(({type, items}, r) => {
    const shown = r < leadRows ? items.slice(0, leadChips) : [];
    const rest = items.slice(shown.length);
    if (shown.length) {
      lead += `<div class="tag-tooltip-extra tag-reco-row" data-reco-type="${type.key}">`
        + `<span class="tag-tooltip-extra-label" data-naia-title="${type.hint}">${type.label}</span>`
        + chipsHtml(shown) + '</div>';
    }
    if (rest.length) {
      // 단추는 칩이 아니다(data-insert 없음) - 누르면 그 유형의 칸을 펴고 접을 뿐이다.
      tabs += `<button type="button" class="tag-reco-tab" data-reco-tab="${type.key}" data-naia-title="${type.hint}">`
        + `${type.label}<b>${rest.length}</b></button>`;
      panels += `<div class="tag-tooltip-extra tag-reco-panel" data-reco-panel="${type.key}">${chipsHtml(rest)}</div>`;
    }
  });
  // 칸은 단추 줄 **아래** - 펴도 단추가 제자리라 같은 자리를 다시 누르면 다시 그 단추다(칩이 아니다).
  const more = tabs ? `<div class="tag-reco-tabs">${tabs}</div>${panels}` : '';
  return `<div class="tag-reco">${head}${lead}${more}</div>`;
}

/**
 * 추천 칩을 눌렀을 때의 새 글과 캐럿. token = tagAssist 의 getActiveTokenInfo 결과({raw, stripped, start, end}).
 * add     = 지금 태그 뒤에 `, 새 태그`(기존 칩과 같은 동작).
 * replace = 토큰 안의 태그 이름만 갈아 끼운다 - 가중치·괄호(`1.2::shirt ::`, `(shirt:1.2)`)는 남긴다.
 *           이름을 토큰에서 못 찾으면(이스케이프 표기 등) 토큰 전체를 새 태그로 바꾼다.
 */
export function applyRecommendation(text, token, tag, op) {
  const value = String(text ?? '');
  const name = String(tag ?? '');
  if (op !== 'replace') {
    return {text: value.substring(0, token.end) + ', ' + name + value.substring(token.end), caret: token.end + 2 + name.length};
  }
  const raw = String(token.raw ?? value.substring(token.start, token.end));
  const at = raw.toLowerCase().indexOf(String(token.stripped ?? '').toLowerCase());
  const found = token.stripped && at >= 0;
  const nextRaw = found ? raw.substring(0, at) + name + raw.substring(at + token.stripped.length) : name;
  return {
    text: value.substring(0, token.start) + nextRaw + value.substring(token.end),
    caret: token.start + (found ? at : 0) + name.length,
  };
}
