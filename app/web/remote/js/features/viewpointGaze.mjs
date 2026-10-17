// 구도 / 시점 제어 창의 [시선] 탭 - 인물이 어디를 보는가(사용자 지시 2026-10-17).
// 구도(viewpointWeights.mjs)와는 **별개**다(사용자 지시 2026-10-17 "둘은 별개로 취급") - 글 칸 · 복사도 따로다.
//
// 출처: 옛 Interactive 세션의 시선 콤보 셋(C:/VNR/NAIA2.0/ui/interactive/character_prompt_block.py - 방향 · 대상 · 신체).
// 이름은 Danbooru 와 겹치면 Danbooru 것으로 바꿨다(옛 목록은 e621 이름이 섞여 있었다):
//   looking aside -> looking to the side · looking forward -> looking ahead · looking at butt -> looking at ass ·
//   looking at genitalia -> looking at penis / looking at pussy · looking back at viewer -> 뒤돌아봄 + 관객 두 칩.
// 두 곳 다 거의 없는 이름(looking at partner · feet · chest)은 뺐고, 건수가 많은 eye contact · sideways glance 등을 더했다.
// 시선 태그는 가중치 없이 넣는다. 줄마다 하나만 고른다(옛 콤보와 같다).

export const GAZE_GROUPS = Object.freeze([
  {key: 'dir', label: '방향', items: [
    ['looking ahead', '앞'], ['looking up', '위'], ['looking down', '아래'], ['looking to the side', '옆'],
    ['looking away', '외면'], ['looking back', '뒤돌아봄'], ['looking afar', '먼 곳'], ['sideways glance', '곁눈질'],
  ]},
  {key: 'tgt', label: '대상', items: [
    ['looking at viewer', '관객(카메라)'], ['eye contact', '눈 맞춤'], ['looking at another', '다른 사람'],
    ['looking at self', '자기 자신'], ['looking at mirror', '거울'], ['looking at object', '물건'], ['looking at phone', '휴대폰'],
  ]},
  {key: 'body', label: '신체', adult: true, items: [
    ['looking at breasts', '가슴'], ['looking at ass', '엉덩이'], ['looking at belly', '배'], ['looking at penis', '성기(남)'],
    ['looking at pussy', '성기(여)'], ['looking at bulge', '불룩한 곳'], ['looking at anus', '항문'],
  ]},
]);

export const GAZE_TAGS = Object.freeze([...new Set(GAZE_GROUPS.flatMap(g => g.items.map(([tag]) => tag)))]);

export function normalizeGaze(input = {}) {
  const out = {};
  for (const group of GAZE_GROUPS) {
    const value = String(input?.[group.key] || '');
    out[group.key] = group.items.some(([tag]) => tag === value) ? value : '';
  }
  return out;
}

/** 고른 시선 -> 태그 목록(방향 · 대상 · 신체 차례). */
export function gazeTags(gaze) {
  const g = normalizeGaze(gaze);
  return [g.dir, g.tgt, g.body].filter(Boolean);
}

export function gazeLabel(groupKey, tag) {
  const group = GAZE_GROUPS.find(g => g.key === groupKey);
  return group?.items.find(([t]) => t === tag)?.[1] || '';
}
