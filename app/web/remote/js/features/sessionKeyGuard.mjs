// 랜덤 슬롯(세션 와일드카드 - Find [현재 결과 → 랜덤 와일드카드])의 `__키__` 를 지킨다(사용자 지시 2026-10-19).
//
// 규칙(서버 `core/headless_character_service.py` 의 `keep_session_prefix` 와 같다): 새 글에 키가 **그대로** 있으면 받고
// (앞 · 뒤에 쓰기 · Connect 로 감싸기 · 통째로 붙여 넣기), 없으면(지움 · 글자 바꿈) 그 편집 한 번을 되돌린다.
// 키를 '고쳐 주는' 규칙은 Connect 구간 · 글자 바꿔치기에서 번번이 엉뚱한 글을 만들었다(Codex 리뷰 8 · 9차) - 거절만 한다.
//
// 화면이 둘이다(캐릭터 퀵 패널 · Manage 의 캐릭터 모듈 창) - 둘 다 이 모듈로 지킨다. 하나만 지키면 다른 쪽에서 고친 글을
// 서버가 통째로 거절하는데 화면은 고친 글을 계속 보여 준다(포커스 중에는 서버 값으로 다시 그리지 않는다 - Codex 리뷰 12차).

export const SESSION_TOKEN = /__\d{8}_\d{6}_cw__/;

export function keepSessionPrefix(before, after) {
  const match = SESSION_TOKEN.exec(String(before || ''));
  if (!match) return after;
  return String(after || '').includes(match[0]) ? after : before;
}

/**
 * root 안의 칸들을 지킨다.
 *   tokenOf(element)    = 그 칸이 지킬 키(`__…_cw__`). 랜덤 슬롯 칸이 아니면 ''.
 *   serverText(element) = 서버가 아는 그 칸의 글 - 되돌릴 기준 글이 없을 때(초점이 이미 있던 칸 등) 쓴다.
 *   onRevert(element)   = 되돌린 뒤 서버에 되돌린 글을 보낼 때(한글 조합이 끝나 되돌린 경우 - 조합 중 보낸 글은 서버가 거절했다).
 * 돌려주는 check(element) 를 칸의 input 처리 맨 앞에서 부른다 - 되돌렸으면 true(그 입력은 보내지 않는다).
 */
export function attachSessionKeyGuard(root, {tokenOf, serverText = () => '', onRevert = () => {}, toast = () => {}}) {
  const target = event => {
    const element = event.target && event.target.closest ? event.target.closest('textarea') : null;
    return element && tokenOf(element) ? element : null;
  };
  const remember = element => {
    element._skPrev = element.value;
    element._skSel = [element.selectionStart, element.selectionEnd];
  };

  function check(element) {
    const token = element ? tokenOf(element) : '';
    if (!token || element._skComposing) return false;
    if (element.value.includes(token)) {
      remember(element);
      return false;
    }
    // 키가 사라졌다 - 키가 든 기준 글로 되돌린다. 쥐어 둔 글이 없거나 그것마저 키가 없으면 서버의 글로.
    const held = typeof element._skPrev === 'string' && element._skPrev.includes(token);
    const base = held ? element._skPrev : String(serverText(element) || '');
    if (!base.includes(token)) return false;
    const [from, to] = held && element._skSel ? element._skSel : [base.length, base.length];
    element.value = base;
    element.setSelectionRange(from, to);
    remember(element);
    toast('랜덤 슬롯의 와일드카드 이름은 고칠 수 없습니다. 그 앞 · 뒤에 쓰세요.');
    return true;
  }

  // 초점이 들어올 때 · 매 입력 직전에 기준 글을 쥔다(키가 든 글만). ⚠️ 한글 조합 중에는 쥐지 않는다 - 조합 중간 글을 기준으로
  // 삼으면 그 뒤로 검사가 풀린다. 조합 **시작** 순간의 글을 쥐고, 조합이 끝나면 한 번 검사한다(Codex 리뷰 10 · 11차).
  const rememberIfIntact = element => {
    if (element.value.includes(tokenOf(element))) remember(element);
  };
  root.addEventListener('focusin', event => {
    const element = target(event);
    if (element && !element._skComposing) rememberIfIntact(element);
  });
  root.addEventListener('beforeinput', event => {
    const element = target(event);
    if (element && !event.isComposing && !element._skComposing) rememberIfIntact(element);
  });
  root.addEventListener('compositionstart', event => {
    const element = target(event);
    if (!element) return;
    if (!element._skComposing) rememberIfIntact(element);
    element._skComposing = true;
  });
  root.addEventListener('compositionend', event => {
    const element = target(event);
    if (!element) return;
    element._skComposing = false;
    if (check(element)) onRevert(element);
  });
  return {check};
}
