// 메인 프롬프트 태그 카드의 **유형별 추천 줄**(2026-09-26). 순수 함수만 둔다 - tagAssist 가 그리고
// 누르기를 처리하며, node 시험이 직접 부른다.
//
// 데이터는 백엔드가 관계 팩(tools/build_tag_relation_pack.py)에서 꺼내 `tag_lookup_result.recommend`
// 로 싣는다. 메인 입력칸이 보낸 조회에만 온다 - 다른 칸(Search 창 등)의 카드는 그대로다.
// 한 줄은 한 가지 일만 한다: Siblings·Variations 는 바꾸기(⇄), 나머지는 더하기(+).
// 예외는 씨앗의 부정(no shirt · unworn hat)으로, 더하기 줄 안에서도 바꾸기다 - 칩마다 op 를 따른다.

export const RECOMMEND_TYPES = [
  {key: 'siblings', label: 'Siblings', hint: '같은 층의 대안 - 누르면 바꿉니다'},
  {key: 'variations', label: 'Variations', hint: '더 구체적인 것 - 누르면 바꿉니다'},
  {key: 'attributes', label: 'Attributes', hint: '모양·색·무늬·특징 - 누르면 더합니다'},
  {key: 'state', label: 'State', hint: '상태 - 누르면 더합니다'},
  {key: 'action', label: 'Action', hint: '동작 - 누르면 더합니다'},
  {key: 'parts', label: 'Parts', hint: '부위 - 누르면 더합니다'},
  {key: 'context', label: 'Context', hint: '맥락 - 누르면 더합니다'},
];

// 줄마다 처음 보이는 칩 수. 나머지는 [+N] 을 누르면 펼친다(카드가 화면을 덮지 않게).
export const RECOMMEND_VISIBLE = 6;

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
 * 그릴 칩이 하나도 없으면 '' - 호출자는 옛 related 줄로 돌아간다.
 */
export function recommendRowsHtml(groups, {present = new Set(), current = '', renderChip, visible = RECOMMEND_VISIBLE} = {}) {
  if (!Array.isArray(groups) || typeof renderChip !== 'function') return '';
  const byType = new Map();
  for (const group of groups) {
    if (group && typeof group.type === 'string' && Array.isArray(group.items)) byType.set(group.type, group.items);
  }
  const self = normalizePromptTag(current);
  let html = '';
  for (const type of RECOMMEND_TYPES) {
    const items = (byType.get(type.key) || []).filter(item => {
      const key = normalizePromptTag(item?.tag);
      return key && key !== self && !present.has(key);
    });
    if (!items.length) continue;
    const chips = items.map((item, i) => {
      const replace = item.op === 'replace';
      const classes = [replace ? 'is-replace' : 'is-add', i >= visible ? 'reco-hidden' : ''].filter(Boolean).join(' ');
      return renderChip(String(item.tag), classes, `data-op="${replace ? 'replace' : 'add'}"`);
    });
    const more = items.length > visible
      ? `<span class="tag-tooltip-extra-tag reco-more" data-reco-more="1">+${items.length - visible}</span>`
      : '';
    html += `<div class="tag-tooltip-extra tag-reco-row" data-reco-type="${type.key}">`
      + `<span class="tag-tooltip-extra-label" data-naia-title="${type.hint}">${type.label}</span>`
      + chips.join('') + more + '</div>';
  }
  return html;
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
