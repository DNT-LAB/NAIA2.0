// 프리셋 벤치 창(사용자 지시 2026-11-19 · 목업 3안 수정판)의 **화면 없는 부품** - 인원 · 칸 · 프롬프트 조립 · 비교 축.
//
// 창(presetBenchWindow.mjs)은 그리기와 서버 왕복만 하고, "무엇을 어디에 싣나" 는 전부 여기서 정한다.
// 사용자: "구현 뒤에도 계속 고친다" - 그래서 규칙을 이 파일 하나에 모았다. 여기 함수는 DOM 도 fetch 도 모른다.
//
//   인원(cast) -> 칸 목록(slots) -> 칸마다 고른 세트(태그 목록) -> assemble() -> {main, characters}
//
// 기반 프리셋의 prefix · postfix · negative 는 서버가 붙인다(POST /api/presets/bench/generate).
// 여기서 만드는 main 은 그 사이에 들어갈 **가운데 몫**이다.

// 인원. head = 메인 프롬프트 맨 앞 인원 태그. pool = 칸 갈래(의상 · 자세 · 표정 · 배경)가 읽을 풀(캐릭터마다).
// link = 연결 갈래 풀(2인만).
export const CASTS = {
  f1: {label: '1인 · 1girl', head: '1girl', pools: ['female']},
  m1: {label: '1인 · 1boy', head: '1boy', pools: ['male']},
  gb: {label: '2인 · 1girl, 1boy', head: '1girl, 1boy', pools: ['female', 'male'], link: 'girl_boy'},
  gg: {label: '2인 · 2girls', head: '2girls', pools: ['female', 'female'], link: 'girl_girl'},
  bb: {label: '2인 · 2boys', head: '2boys', pools: ['male', 'male'], link: 'boy_boy'},
};
export const DEFAULT_CAST = 'f1';

// 갈래(서버 kind) -> 칸 이름.
export const KIND_LABELS = {outfit: '의상', event: '자세', link: '연결', expression: '표정', scene: '배경'};

/** 인원의 칸 목록. 칸 = {id, kind, pool, owner}. owner = 캐릭터 번호(1 · 2) 또는 0(함께 · 장면).
 *  1인: 의상 · 자세 · 표정 · 배경. 2인: 캐릭터마다 의상 · 표정, 함께 = 연결 · 배경. */
export function slotsFor(castId) {
  const cast = CASTS[castId] || CASTS[DEFAULT_CAST];
  if (cast.pools.length === 1) {
    const pool = cast.pools[0];
    return [
      {id: 'o1', kind: 'outfit', pool, owner: 1},
      {id: 'pose', kind: 'event', pool, owner: 1},
      {id: 'e1', kind: 'expression', pool, owner: 1},
      {id: 'scene', kind: 'scene', pool, owner: 0},
    ];
  }
  return [
    {id: 'o1', kind: 'outfit', pool: cast.pools[0], owner: 1},
    {id: 'e1', kind: 'expression', pool: cast.pools[0], owner: 1},
    {id: 'o2', kind: 'outfit', pool: cast.pools[1], owner: 2},
    {id: 'e2', kind: 'expression', pool: cast.pools[1], owner: 2},
    {id: 'link', kind: 'link', pool: cast.link, owner: 0},
    // 배경 갈래는 여/남 풀이 따로 있다 - 2인이면 첫째 캐릭터의 풀을 쓴다(배경은 사람 없이 그린 세트라 차이가 작다).
    {id: 'scene', kind: 'scene', pool: cast.pools[0], owner: 0},
  ];
}

/** 캐릭터 프롬프트 칸에 싣는 칸인가(target = 'char' 일 때). 1인의 자세는 캐릭터 몫이지만 메인에 둔다 -
 *  NAI 는 동작을 메인에 둘 때 더 잘 따른다(목업 3안 미리보기와 같다). */
function goesToCharacter(slot) {
  return slot.owner > 0 && (slot.kind === 'outfit' || slot.kind === 'expression');
}

const joinTags = parts => parts.map(part => String(part || '').trim()).filter(Boolean).join(', ');

/**
 * 프롬프트 조립(순수 함수).
 *   castId    - CASTS 키
 *   target    - 'char'(캐릭터 프롬프트 칸) | 'main'(메인에 다 싣는다)
 *   names     - [캐릭터1 글, 캐릭터2 글] (이름이나 직접 쓴 캐릭터 프롬프트)
 *   picks     - {칸 id: 태그 배열}
 *   variant   - {slotId, tags} 이면 그 칸만 이 태그로 바꿔 조립한다(비교 축의 한 장)
 * 반환 {main, characters: [{prompt, uc}]}. target 'main' 이면 characters 는 빈 목록.
 */
export function assemble({castId, target = 'char', names = [], picks = {}, variant = null}) {
  const cast = CASTS[castId] || CASTS[DEFAULT_CAST];
  const slots = slotsFor(castId);
  const tagsOf = slot => {
    if (variant && variant.slotId === slot.id) return variant.tags || [];
    return picks[slot.id] || [];
  };
  const count = cast.pools.length;
  const nameOf = i => String(names[i] || '').trim();
  if (target === 'main') {
    const main = joinTags([
      cast.head,
      ...Array.from({length: count}, (_, i) => nameOf(i)),
      ...slots.map(slot => joinTags(tagsOf(slot))),
    ]);
    return {main, characters: []};
  }
  const main = joinTags([cast.head, ...slots.filter(slot => !goesToCharacter(slot)).map(slot => joinTags(tagsOf(slot)))]);
  const characters = [];
  for (let i = 0; i < count; i += 1) {
    const prompt = joinTags([nameOf(i), ...slots.filter(slot => goesToCharacter(slot) && slot.owner === i + 1)
      .map(slot => joinTags(tagsOf(slot)))]);
    characters.push({prompt, uc: ''});
  }
  // 캐릭터 칸이 전부 비면 싣지 않는다 - 빈 캐릭터 칸은 NAI 에 사람 하나를 더 그리라는 뜻이 될 수 있다.
  return {main, characters: characters.some(row => row.prompt) ? characters : []};
}

/** 미리보기 줄: 메인 · 캐릭터 N. 비교 축 칸은 `{의상 ×3}` 처럼 표시한다(axisCount > 1 이고 variant 가 없을 때). */
export function previewRows({castId, target, names, picks, variant = null, axis = null}) {
  let shownPicks = picks;
  if (!variant && axis && axis.count > 1) {
    shownPicks = {...picks, [axis.slotId]: [`{${axis.label} ×${axis.count}}`]};
  }
  const {main, characters} = assemble({castId, target, names, picks: shownPicks, variant});
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
export function buildItems({castId, target, names, picks, axis = null}) {
  if (axis && axis.sets && axis.sets.length > 1) {
    return axis.sets.map(set => {
      const {main, characters} = assemble({castId, target, names, picks, variant: {slotId: axis.slotId, tags: set.tags}});
      return {label: variantLabel(set.tags), main, characters, set};
    });
  }
  const {main, characters} = assemble({castId, target, names, picks});
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
