// 프리셋 벤치 창(사용자 지시 2026-11-19 · 목업 3안 수정판)의 **화면 없는 부품** - 인원 · 칸 · 프롬프트 조립 · 비교 축.
//
// 창(presetBenchWindow.mjs)은 그리기와 서버 왕복만 하고, "무엇을 어디에 싣나" 는 전부 여기서 정한다.
// 사용자: "구현 뒤에도 계속 고친다" - 그래서 규칙을 이 파일 하나에 모았다. 여기 함수는 DOM 도 fetch 도 모른다.
//
//   인원(cast) -> 칸 목록(slots) -> 칸마다 고른 세트(태그 목록) -> assemble() -> {main, characters}
//
// 인원은 고르지 않는다(사용자 11-20: "1girl, 1boy 등을 선택해야 하는데 없는 게 더 편하다").
// cast = {count: 캐릭터 수(1 · 2), genders: ['girl' | 'boy' | 'other' | '', ...]} - 성별은 창이 캐릭터 이름으로
// 서버에 묻는다(GET /api/presets/bench/subject). 목록은 여성 · 남성 세트를 한데 보인다(칸 pool = '').
//
// 기반 프리셋의 prefix · postfix · negative 는 서버가 붙인다(POST /api/presets/bench/generate).
// 여기서 만드는 main 은 그 사이에 들어갈 **가운데 몫**이다.

export const MAX_CHARACTERS = 2;
const SUBJECT_ORDER = ['girl', 'boy', 'other'];

/** 저장된 값을 {count, genders} 로(캐릭터 1 ~ 2명 · 모르는 성별은 빈 값). */
export function normalizeCast(value) {
  const count = Math.min(MAX_CHARACTERS, Math.max(1, Number(value && value.count) || 1));
  const genders = Array.from({length: count}, (_, i) => {
    const g = String((value && value.genders && value.genders[i]) || '');
    return SUBJECT_ORDER.includes(g) ? g : '';
  });
  return {count, genders};
}

/** 메인 맨 앞 인원 태그. 모르는 성별은 girl(캐릭터 뷰어의 옛 기본값). girl+boy = '1girl, 1boy' · girl+girl = '2girls'.
 *  캐릭터 1명이 2인 자세 세트를 골랐으면(linkPool) 그 세트의 풀이 정한다 - 상대는 캐릭터 칸 없이 이 태그로만 들어간다. */
export function headFor(cast, linkPool = '') {
  const {count, genders} = normalizeCast(cast);
  if (count === 1 && LINK_POOLS[linkPool]) return LINK_POOLS[linkPool].head;
  return SUBJECT_ORDER
    .map(g => [g, genders.filter(x => (x || 'girl') === g).length])
    .filter(([, n]) => n > 0)
    .map(([g, n]) => `${n}${g}${n > 1 ? 's' : ''}`)
    .join(', ');
}

// 갈래(서버 kind) -> 칸 이름.
// 연결 갈래 = 두 사람이 함께 하는 자세(포옹 · 함께 자기 …). 화면 이름은 '자세 (2인 이상)'(사용자 11-20).
export const KIND_LABELS = {outfit: '의상', event: '자세', link: '자세 (2인 이상)', expression: '표정', scene: '배경'};
// 연결 세트 풀 -> 맨 앞 인원 태그 · 짧은 표지. 캐릭터가 1명인데 2인 자세를 고르면 상대는 이 태그로만 들어간다.
export const LINK_POOLS = {
  girl_boy: {head: '1girl, 1boy', badge: '남녀', genders: ['girl', 'boy']},
  girl_girl: {head: '2girls', badge: '여여', genders: ['girl']},
  boy_boy: {head: '2boys', badge: '남남', genders: ['boy']},
};

/** 캐릭터 1명 + 2인 자세에서 캐릭터 성별이 세트 풀과 어긋나나(boy 인데 여여 세트). 모르는 성별은 girl 로 본다. */
export function linkMismatch(gender, pool) {
  const info = LINK_POOLS[pool];
  const g = gender || 'girl';
  return Boolean(info) && g !== 'other' && !info.genders.includes(g);
}

/** 캐릭터 수의 칸 목록. 칸 = {id, kind, pool, owner}. owner = 캐릭터 번호(1 · 2) 또는 0(캐릭터 밖 - 따로 카드).
 *  pool '' = 모든 풀(서버가 여성 · 남성 세트를 겹침 없이 한 목록으로 준다).
 *  1인: 의상 · 자세 · 표정 + 자세 (2인 이상) · 배경. 2인: 캐릭터마다 의상 · 표정 + 자세 (2인 이상) · 배경.
 *  2인 이상 자세는 1명이어도 쓴다(상대는 이름 없이 - 사용자 11-20). 칸 id 'link' 는 두 경우 같다(바꿔도 남는다).
 *  2인 이상 자세는 늘 캐릭터 밖(owner 0) - 배경 위 붉은 카드(사용자 11-20: 주로 NSFW 갈래라 눈에 띄게). */
export function slotsFor(count) {
  const pool = '';
  if ((Number(count) || 1) < 2) {
    return [
      {id: 'o1', kind: 'outfit', pool, owner: 1},
      {id: 'pose', kind: 'event', pool, owner: 1},
      {id: 'link', kind: 'link', pool, owner: 0},
      {id: 'e1', kind: 'expression', pool, owner: 1},
      {id: 'scene', kind: 'scene', pool, owner: 0},
    ];
  }
  return [
    {id: 'o1', kind: 'outfit', pool, owner: 1},
    {id: 'e1', kind: 'expression', pool, owner: 1},
    {id: 'o2', kind: 'outfit', pool, owner: 2},
    {id: 'e2', kind: 'expression', pool, owner: 2},
    {id: 'link', kind: 'link', pool, owner: 0},
    {id: 'scene', kind: 'scene', pool, owner: 0},
  ];
}

// 1인 자세 + 2인 자세를 함께 고르면 2인 자세가 주인공이다 - 1인 자세는 이 가중치로 눌러 싣는다(사용자 11-20).
// NAI 수치 가중치 꼴 `0.7::태그, 태그::`(벤치 생성은 NAI 만 받는다).
export const POSE_WEIGHT_WITH_LINK = 0.7;

/** 캐릭터 프롬프트 칸에 싣는 칸인가(target = 'char' 일 때). 1인의 자세는 캐릭터 몫이지만 메인에 둔다 -
 *  NAI 는 동작을 메인에 둘 때 더 잘 따른다(목업 3안 미리보기와 같다). */
function goesToCharacter(slot) {
  return slot.owner > 0 && (slot.kind === 'outfit' || slot.kind === 'expression');
}

const joinTags = parts => parts.map(part => String(part || '').trim()).filter(Boolean).join(', ');
// 메인 한 줄 안에서 같은 태그를 한 번만(이름 칸에 1boy 를 직접 써도 맨 앞 인원 태그와 겹치지 않게).
const uniqueTags = text => [...new Set(String(text || '').split(',').map(tag => tag.trim()).filter(Boolean))].join(', ');

/**
 * 프롬프트 조립(순수 함수).
 *   cast      - {count, genders}
 *   target    - 'char'(캐릭터 프롬프트 칸) | 'main'(메인에 다 싣는다)
 *   names     - [캐릭터1 글, 캐릭터2 글] (이름이나 직접 쓴 캐릭터 프롬프트)
 *   picks     - {칸 id: 태그 배열}
 *   variant   - {slotId, tags, pool} 이면 그 칸만 이 태그로 바꿔 조립한다(비교 축의 한 장)
 *   cast.linkPool - 2인 자세 칸에 든 세트의 풀(1명일 때 인원 태그를 정한다)
 *   ucs       - [캐릭터1 UC, 캐릭터2 UC] (에셋에서 불러온 캐릭터 UC - 캐릭터 칸에만 실린다)
 *   extras    - [캐릭터1 추가 프롬프트, …] - 그 캐릭터 몫 끝(캐릭터 칸 · target 'main' 이면 메인)
 *   extraMain - 추가 프롬프트 - 메인 끝(기반 postfix 앞)
 * 반환 {main, characters: [{prompt, uc}]}. target 'main' 이면 characters 는 빈 목록.
 */
export function assemble({cast, target = 'char', names = [], picks = {}, variant = null, ucs = [], extras = [], extraMain = ''}) {
  const {count} = normalizeCast(cast);
  const slots = slotsFor(count);
  const tagsOf = slot => {
    if (variant && variant.slotId === slot.id) return variant.tags || [];
    return picks[slot.id] || [];
  };
  const linkTags = tagsOf({id: 'link'});
  const linkPool = !linkTags.length ? '' : (variant && variant.slotId === 'link' ? variant.pool : cast && cast.linkPool);
  const head = headFor(cast, linkPool || '');
  const nameOf = i => String(names[i] || '').trim();
  const extraOf = i => String(extras[i] || '').trim();
  // 칸 한 개의 글 - 2인 자세가 있으면 1인 자세(event)는 POSE_WEIGHT_WITH_LINK 로 감싼다. 2인 자세는 늘 메인(goesToCharacter 밖).
  const slotText = slot => {
    const text = joinTags(tagsOf(slot));
    return text && slot.kind === 'event' && linkTags.length ? `${POSE_WEIGHT_WITH_LINK}::${text}::` : text;
  };
  if (target === 'main') {
    const main = uniqueTags(joinTags([
      head,
      ...Array.from({length: count}, (_, i) => nameOf(i)),
      ...slots.map(slotText),
      ...Array.from({length: count}, (_, i) => extraOf(i)),
      extraMain,
    ]));
    return {main, characters: []};
  }
  const main = uniqueTags(joinTags([head, ...slots.filter(slot => !goesToCharacter(slot)).map(slotText), extraMain]));
  const characters = [];
  for (let i = 0; i < count; i += 1) {
    const prompt = joinTags([nameOf(i), ...slots.filter(slot => goesToCharacter(slot) && slot.owner === i + 1).map(slotText), extraOf(i)]);
    characters.push({prompt, uc: String(ucs[i] || '').trim()});
  }
  // 캐릭터 칸이 전부 비면 싣지 않는다 - 빈 캐릭터 칸은 NAI 에 사람 하나를 더 그리라는 뜻이 될 수 있다.
  return {main, characters: characters.some(row => row.prompt) ? characters : []};
}

/** 미리보기 줄: 메인 · 캐릭터 N. 비교 축 칸은 `{의상 ×3}` 처럼 표시한다(axisCount > 1 이고 variant 가 없을 때). */
export function previewRows({cast, target, names, picks, variant = null, axis = null, ucs = [], extras = [], extraMain = ''}) {
  let shownPicks = picks;
  if (!variant && axis && axis.count > 1) {
    shownPicks = {...picks, [axis.slotId]: [`{${axis.label} ×${axis.count}}`]};
  }
  const {main, characters} = assemble({cast, target, names, picks: shownPicks, variant, ucs, extras, extraMain});
  const rows = [{key: 'main', label: '메인', text: main}];
  characters.forEach((row, i) => rows.push({key: `c${i + 1}`, label: `캐릭터 ${i + 1}`, text: row.prompt}));
  return rows;
}

/** 결과 이름표 - 비교 축으로 바뀐 몫만 짧게(앞 두 태그). */
export function variantLabel(tags) {
  const list = (tags || []).filter(Boolean);
  if (!list.length) return '비어 있음';
  return list.slice(0, 2).join(', ') + (list.length > 2 ? ' …' : '');
}

/** 생성 요청의 items. 비교 축이 있으면 축 칸의 세트마다 한 장, 없으면 한 장. */
export function buildItems({cast, target, names, picks, axis = null, ucs = [], extras = [], extraMain = ''}) {
  if (axis && axis.sets && axis.sets.length > 1) {
    return axis.sets.map(set => {
      const {main, characters} = assemble({cast, target, names, picks, ucs, extras, extraMain,
        variant: {slotId: axis.slotId, tags: set.tags, pool: set.pool}});
      return {label: variantLabel(set.tags), main, characters, set};
    });
  }
  const {main, characters} = assemble({cast, target, names, picks, ucs, extras, extraMain});
  return [{label: '한 장', main, characters, set: null}];
}

/** Danbooru 게시물 수를 짧게 - 1.0M · 128k · 9.5k · 450. */
export function formatPosts(n) {
  const v = Number(n) || 0;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e4) return `${Math.round(v / 1e3)}k`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
  return String(v);
}
