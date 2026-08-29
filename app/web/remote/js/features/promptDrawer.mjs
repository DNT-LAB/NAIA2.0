export function createPromptDrawer({
  document,
  getWs,
  WebSocket,
  mediaQuery,
}) {
  const drawer = document.getElementById('promptDrawer');
  const toggleBar = document.querySelector('.prompt-toggle-bar');
  const toggleArrow = document.getElementById('toggleArrow');
  const toggleArrow2 = document.getElementById('toggleArrow2');
  const promptNewDot = document.getElementById('promptNewDot');
  let open = false;

  function syncOpenClasses() {
    if (drawer) drawer.classList.toggle('open', open);
    if (toggleBar) toggleBar.classList.toggle('open', open);
    if (toggleArrow) {
      toggleArrow.classList.toggle('open', open);
      toggleArrow.innerHTML = open ? '&#9660;' : '&#9650;';
    }
    if (toggleArrow2) {
      toggleArrow2.classList.toggle('open', open);
      toggleArrow2.innerHTML = open ? '&#9660;' : '&#9650;';
    }
  }

  function toggle() {
    if (mediaQuery.matches) return;
    open = !open;
    syncOpenClasses();
    if (open) {
      if (promptNewDot) promptNewDot.classList.add('hidden');
      const ws = getWs();
      if (ws && ws.readyState === WebSocket.OPEN) ws.send('sync');
    }
  }

  /** 서랍을 접는다. **모바일 전용**이다(사용자 지정 2026-08-29).
   *
   *  Random / Generate 를 누르면 자동으로 내려온다 - 좁은 화면에서는 이 서랍이
   *  결과를 통째로 덮고 있어서, 누른 뒤에도 무엇이 나왔는지 볼 수가 없다.
   *
   *  ⚠️ 데스크톱에서는 아무것도 안 한다. 거기서는 이것이 '서랍' 이 아니라 늘 펼쳐진
   *     왼쪽 칸이라(`toggle()` 과 `closeForDesktop()` 이 같은 가드를 쓴다), 접으면
   *     프롬프트 칸이 통째로 사라진다.
   *  ⚠️ 이미 닫혀 있으면 손대지 않는다 - 클래스를 다시 써서 트랜지션이 깜빡이는 것을
   *     막는다.
   */
  function closeForMobile() {
    if (mediaQuery.matches) return;
    if (!open) return;
    open = false;
    syncOpenClasses();
  }

  function showNewContentDot() {
    if (!open && promptNewDot) promptNewDot.classList.remove('hidden');
  }

  function closeForDesktop() {
    if (!mediaQuery.matches) return;
    if (drawer) drawer.classList.remove('open');
    open = false;
  }

  function switchTab(name) {
    const page = document.getElementById('tab' + name.charAt(0).toUpperCase() + name.slice(1));
    if (!page) return;  // 탭바 버튼 없는 Fn 진입 페이지(sequence 등) 가드
    document.querySelectorAll('.tab-btn').forEach(button => {
      button.classList.toggle('active', button.dataset.tab === name);
    });
    document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
  }

  mediaQuery.addEventListener('change', closeForDesktop);

  return {
    toggle,
    closeForMobile,
    showNewContentDot,
    switchTab,
  };
}
