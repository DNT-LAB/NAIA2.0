// 메인 프롬프트 태그 카드의 **유형별 추천 줄**(2026-09-26). 순수 함수만 둔다 - tagAssist 가 그리고
// 누르기를 처리하며, node 시험이 직접 부른다.
//
// 데이터는 백엔드가 관계 팩(tools/build_tag_relation_pack.py)에서 꺼내 `tag_lookup_result.recommend`
// 로 싣는다. 메인 입력칸이 보낸 조회에만 온다 - 다른 칸(Search 창 등)의 카드는 그대로다.
// 줄은 Codex 제품 계약의 display_type, 누르면 할 일은 칩마다의 edit_policy 다(2026-09-27):
// ⇄ 칩 = 커서 태그를 바꾼다(검토된 같은 축 대안 · 부재 · 뜻을 품는 구체화), 나머지는 뒤에 더한다.
// 대표 리그와 더보기 리그(2026-09-27, 사용자 지정): 줄마다 칩 6개씩 전부 펼치니 카드가 너무 넓었다. 앞의 대표 줄
// 3개 · 칩 4개만 보이고, 나머지 칩은 [더보기] 아래 따로 모아 한 번에 편다(편 채로 둘지는 tagAssist 가 브라우저에
// 기억한다). 대표 줄은 펴도 그대로다 - 단추가 제자리라 두 번 눌러도 칩을 누르지 않는다.

// 줄 순서가 곧 대표 줄을 고르는 차례다 - 앞에서부터 칩이 있는 줄 3개. 지금 태그를 다듬는 Siblings · Variations ·
// State 가 먼저다.
export const RECOMMEND_TYPES = [
  {key: 'siblings', label: 'Siblings', hint: '같은 축의 대안 - 누르면 지금 태그를 바꿉니다'},
  {key: 'variations', label: 'Variations', hint: '더 구체적인 종류 - ⇄ 는 바꾸고 나머지는 더합니다'},
  {key: 'state', label: 'State', hint: '상태 - ⇄ 는 바꾸고 나머지는 더합니다'},
  {key: 'companions', label: 'Companions', hint: '같이 쓰는 것 - 누르면 더합니다'},
  {key: 'attributes', label: 'Attributes', hint: '모양·색·무늬·특징 - ⇄ 는 바꾸고 나머지는 더합니다'},
  {key: 'action', label: 'Action', hint: '동작 - 누르면 더합니다'},
  {key: 'parts', label: 'Parts', hint: '부위 - 누르면 더합니다'},
  {key: 'context', label: 'Context', hint: '맥락 - ⇄ 는 바꾸고 나머지는 더합니다'},
];

// 대표 줄 수와 그 줄에 처음 보이는 칩 수. 나머지 줄·칩은 [더보기] 뒤에 둔다(카드가 화면을 덮지 않게).
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

/** 프롬프트에 이미 있는 태그들 - 추천에서 뺀다(같은 칩을 또 권하지 않는다). */
export function promptTagSet(text) {
  const out = new Set();
  for (const part of String(text ?? '').split(/[,\n]/)) {
    const tag = normalizePromptTag(part);
    if (tag) out.add(tag);
  }
  return out;
}

/**
 * 유형별 줄의 HTML. groups = 백엔드의 [{type, items: [{tag, op}]}].
 * renderChip(tag, extraClass, extraAttrs) 는 호출자의 칩 그리개(설명 호버·data-insert 를 붙인다).
 * 앞의 leadRows 줄이 대표 줄(칩 leadChips 개까지). 그 줄의 남은 칩과 나머지 줄은 [더보기](data-reco-toggle) 뒤의
 * `.tag-reco-more` 에 같은 유형 이름으로 다시 줄을 세운다 - 단추가 감싼 `.tag-reco` 에 is-expanded 를 붙여 편다.
 * expanded = 처음부터 편 채로. 숨길 것이 없으면 [더보기] 도, 더보기 칸도 없다.
 * 그릴 칩이 하나도 없으면 '' - 호출자는 옛 related 줄로 돌아간다.
 */
export function recommendRowsHtml(groups, {
  present = new Set(), current = '', renderChip,
  leadRows = RECOMMEND_LEAD_ROWS, leadChips = RECOMMEND_LEAD_CHIPS, expanded = false,
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
  if (!rows.length) return '';
  const rowHtml = (type, items) => `<div class="tag-tooltip-extra tag-reco-row" data-reco-type="${type.key}">`
    + `<span class="tag-tooltip-extra-label" data-naia-title="${type.hint}">${type.label}</span>`
    + items.map(item => {
      const replace = item.op === 'replace';
      return renderChip(String(item.tag), replace ? 'is-replace' : 'is-add', `data-op="${replace ? 'replace' : 'add'}"`);
    }).join('') + '</div>';
  let lead = '';
  let more = '';
  let hidden = 0;
  const hiddenLabels = [];
  rows.forEach(({type, items}, r) => {
    const shown = r < leadRows ? items.slice(0, leadChips) : [];
    const rest = items.slice(shown.length);
    if (shown.length) lead += rowHtml(type, shown);
    if (rest.length) {
      more += rowHtml(type, rest);
      hidden += rest.length;
      hiddenLabels.push(type.label);
    }
  });
  if (!hidden) return `<div class="tag-reco">${lead}</div>`;
  // 단추는 칩이 아니다(data-insert 없음) - 누르면 펴고 접을 뿐이다. 마우스를 올리면 숨은 줄 이름이 뜬다.
  const toggle = `<button type="button" class="tag-reco-toggle" data-reco-toggle="1" data-naia-title="${hiddenLabels.join(' · ')}">`
    + `<span class="reco-toggle-more">더보기 +${hidden}</span><span class="reco-toggle-less">접기</span></button>`;
  return `<div class="tag-reco${expanded ? ' is-expanded' : ''}">${lead}${toggle}<div class="tag-reco-more">${more}</div></div>`;
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
