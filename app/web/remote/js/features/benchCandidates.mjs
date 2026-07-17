// 벤치 후보 상관관계 - 바리에이션 벤치와 캐릭터 생성 벤치가 공유하는 순수 함수.
//
// 두 벤치는 상태 머신(레이어/이벤트 위임/DOM 유지/포커스 보류)을 공유하지 않는다.
// 여기 있는 것만 공유한다: 서버 candidate 번호는 요청마다 0부터 다시 시작하므로,
// 후보를 누적하려면 화면용 stable index와 (requestId, requestCandidate) 매칭을
// 분리해야 한다. 위치 접근(candidates[meta.candidate])은 2번째 배치의 candidate 0이
// 1번째 배치 후보를 덮어쓴다.

/** 새 배치를 기존 후보 뒤에 붙인다(완료 후보는 이 벤치의 작업 이력이라 보존). */
export function appendBenchCandidateBatch(candidates, count, requestId, mode) {
  const current = Array.isArray(candidates) ? candidates : [];
  const nextIndex = current.reduce(
    (highest, candidate) => Math.max(highest, Number(candidate?.index) || 0),
    -1,
  ) + 1;
  const batch = Array.from({length: count}, (_, requestCandidate) => ({
    index: nextIndex + requestCandidate,
    requestCandidate,
    requestId,
    status: 'pending',
    historyId: '',
    message: '',
    saved: false,
    mode,
  }));
  return [...current, ...batch];
}

/** 서버가 돌려준 (requestId, candidate)로 후보를 찾는다. */
export function findBenchRequestCandidate(candidates, requestId, requestCandidate) {
  return (Array.isArray(candidates) ? candidates : []).find(candidate => (
    candidate.requestId === requestId
    && candidate.requestCandidate === Number(requestCandidate)
  )) || null;
}

/**
 * 후보/바리에이션의 생성 방식 배지.
 * 생성 벤치는 2축(base x reference)이라 hasReference가 붙으면 "+CR"이 따라온다.
 */
export function benchModeBadge(mode, hasReference = false) {
  const base = mode === 'char_reference' ? 'CR'
    : mode === 'enhance' ? 'ENH'
    : mode === 'inpaint' ? 'INP'
    : mode === 'scaffold' ? 'STD'
    : '';
  if (!base) return '';
  // 바리에이션 벤치의 char_reference는 그 자체가 레퍼런스 모드라 중복 표기하지 않는다.
  if (hasReference && mode !== 'char_reference') return `${base}+CR`;
  return base;
}

/**
 * 랜덤 슬롯이 소유한 태그를 교체해 Character Prompt를 다시 만든다.
 *
 * 계약(사용자 지시):
 * - 결과는 항상 {성별} + {외형} + {의상} + (사용자가 직접 쓴 나머지) 순서다.
 * - 굴리지 않은 카테고리(체크 해제)는 **이전에 넣어준 태그를 그대로 유지**한다.
 *   예: 외형을 끄고 랜덤생성 -> 의상 태그만 제거 후 새로 추가.
 * - 슬롯이 넣었던 태그만 회수한다. 사용자가 직접 쓴 태그는 순서를 지켜 뒤에 남는다.
 *
 * @param {string} prompt 현재 Character Prompt 원문
 * @param {{gender:string, appearance:string[], outfit:string[]}} owned 슬롯이 직전에 넣은 태그
 * @param {{gender:string, appearance:string[]|null, outfit:string[]|null}} next
 *        null = 이번에 굴리지 않음(owned 유지)
 * @returns {{prompt:string, owned:{gender:string, appearance:string[], outfit:string[]}}}
 */
export function applyRandomCharacterSlot(prompt, owned, next) {
  const previous = {
    gender: String(owned?.gender || ''),
    appearance: Array.isArray(owned?.appearance) ? owned.appearance : [],
    outfit: Array.isArray(owned?.outfit) ? owned.outfit : [],
  };
  const tokens = String(prompt || '').split(',').map(tag => tag.trim()).filter(Boolean);
  const tokenSet = new Set(tokens);
  // (a) reconcile — 사용자가 프롬프트에서 지운 소유 태그는 소유권에서 뗀다.
  //     안 그러면 그 카테고리를 끄고 굴렸을 때 지운 태그가 되살아난다(Codex).
  const live = {
    gender: tokenSet.has(previous.gender) ? previous.gender : '',
    appearance: previous.appearance.filter(tag => tokenSet.has(tag)),
    outfit: previous.outfit.filter(tag => tokenSet.has(tag)),
  };
  const ownedSet = new Set([live.gender, ...live.appearance, ...live.outfit].filter(Boolean));
  // 슬롯 소유 태그를 걷어낸 나머지 = 사용자가 직접 쓴 것(순서 보존)
  const remainder = tokens.filter(tag => !ownedSet.has(tag));
  const remainderSet = new Set(remainder);

  // (b) 슬롯은 "자기가 새로 넣은 태그"만 소유한다. 사용자가 이미 갖고 있던 태그와
  //     굴림 결과가 겹치면 그건 사용자 것으로 남겨야 다음 굴림에서 삭제되지 않는다(Codex).
  const claim = (rolled, kept) => (
    Array.isArray(rolled) ? rolled.filter(tag => !remainderSet.has(tag)) : kept
  );
  const nextOwned = {
    gender: String(next?.gender || live.gender || ''),
    appearance: claim(next?.appearance, live.appearance),
    outfit: claim(next?.outfit, live.outfit),
  };
  const block = [nextOwned.gender, ...nextOwned.appearance, ...nextOwned.outfit].filter(Boolean);
  const blockSet = new Set(block);
  // 성별은 슬롯 전용 축 - 반대 성별 태그가 사용자 꼬리에 남으면 1girl/1boy 판정이
  // 흔들리므로 함께 걷어낸다.
  const genderTags = new Set(['girl', 'boy']);
  const tail = remainder.filter(tag => (
    !blockSet.has(tag) && !(genderTags.has(tag) && nextOwned.gender)
  ));
  return {prompt: [...block, ...tail].join(', '), owned: nextOwned};
}

/**
 * 후보를 만료 표시한다.
 *
 * 주의: viewer_history_removed(히스토리 퇴출)로 호출하면 안 된다. 백엔드가 캐릭터
 * 에셋 후보를 bounded FIFO 리스로 붙잡고 있어 퇴출 후에도 저장이 가능하기 때문이다
 * (그렇게 하면 과금된 결과를 UI가 스스로 막는다 - Codex). 리스에서까지 밀려난
 * 경우에만, 즉 **저장/이미지 요청이 실제로 404를 돌려줄 때만** 만료로 확정한다.
 * @returns {boolean} 변경 여부(재렌더 필요)
 */
export function markBenchCandidateExpired(candidates, historyId) {
  const target = String(historyId || '');
  if (!target) return false;
  let changed = false;
  for (const candidate of (Array.isArray(candidates) ? candidates : [])) {
    if (candidate.historyId !== target || candidate.status === 'expired') continue;
    candidate.status = 'expired';
    candidate.message = '히스토리에서 만료됨 - 저장할 수 없습니다';
    changed = true;
  }
  return changed;
}
