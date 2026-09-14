/** Remote 컨트롤러 — 탭의 조각을 잠시 빌려 오는 떠 있는 조작판.
 *
 *  Web-Remote(폰으로 여는 원격 화면)와는 **다른 것**이다. 같은 화면 안에서 손이 닿는
 *  자리에 두고 쓰는 리모컨에 가깝다(사용자 지정 2026-09-14).
 *
 *  왜 필요했나 — Artist Thumbnail 로 랜덤 그림을 계속 뽑아 보려면 **탭 하나를 포기**해야
 *  했다. 그림을 보려면 Result 탭, 다음 작가를 뽑고 제외·관심을 매기려면 Artists 탭.
 *  리모컨은 Artists 탭의 **그 조각만** 잠시 들어 올려 Result 를 보면서 돌릴 수 있게 한다.
 *
 *  ## 핵심 결정: 베끼지 않고 **진짜 노드를 옮긴다**
 *
 *  똑같이 생긴 단추를 리모컨에 새로 그리고 클릭만 원본으로 넘기는 길도 있었다. 그러면
 *  라벨·비활성·선택 상태를 **두 곳에서** 관리하게 된다 — 이 저장소가 이미 세 번
 *  되돌아온 함정이다([[feedback_two_entry_points]]). 대신 원본 요소를 그대로 들어다
 *  리모컨에 붙이고, 끌 때 있던 자리에 되돌려 놓는다. 배선·렌더링·상태가 전부 하나다.
 *
 *  ⚠️ 이게 되는 이유는 `artistThumbTab.mjs` 가 요소를 **id 로 한 번만 잡아 두고** 그
 *     참조로만 일하기 때문이다(부모에서 다시 찾지 않는다). 새 모듈을 온보딩할 때는
 *     **그것부터 확인**하라 - 매번 `panel.querySelector(...)` 로 찾는 모듈이라면 노드를
 *     옮기는 순간 조용히 못 찾게 된다.
 *  ⚠️ 되돌릴 때는 **거꾸로** 넣는다. 들어 올린 둘이 서로 형제였으면 A 의 `nextSibling`
 *     이 B 라서, B 가 먼저 돌아와 있어야 A 가 제자리에 앉는다.
 *
 *  ## 여는 규칙
 *
 *  리모컨은 **온보딩한 모듈이 하나라도 있으면** 뜨고, 마지막 하나가 빠지면 닫힌다
 *  (사용자 지정). 별도의 표시/숨김 설정은 두지 않는다 - 규칙이 둘이 되면 어긋난다.
 *  [×] 는 온보딩을 **전부 해제**한다(각 모듈의 토글도 그때 꺼진다).
 *
 *  관리 단위는 **탭**이다. 지금은 Artist Thumbnail 하나뿐이지만 여러 탭이 들어오면
 *  탭마다 한 구획이 쌓인다.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260914-rctl2';

export function createRemoteController({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  showToast = () => {},
  escHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
} = {}) {
  const panel = createDraggablePanel({
    document: doc,
    window: win,
    storage,
    id: 'remoteController',
    variant: 'rctl',
    title: 'Remote',
    storageKey: 'remote-controller',
    // 썸네일 격자가 들어오므로 좁으면 쓸모가 없다. 두 칸은 나와야 한다.
    width: 430,
    minWidth: 260,
    maxWidth: 900,
    // 썸네일 격자가 본론이라 두 줄은 보여야 한다. 화면이 낮으면 place() 가 줄인다.
    height: 560,
    minHeight: 200,
    resizable: true,
    collapsible: true,
    closable: true,
    initial: {right: 24, y: 96},
    escHtml,
    onClose: () => releaseAll(),
  });

  // 탭 열쇠 -> {title, rows, onRelease, moved:[{node, parent, next}], ghosts:[...]}
  const boarded = new Map();

  // ── 노드를 들어 올리고 되돌리기 ────────────────────────────────────────
  function lift(entry, node, {ghost = null} = {}) {
    if (!node || !node.parentNode) return null;
    const record = {node, parent: node.parentNode, next: node.nextSibling, ghost: null};
    if (ghost) {
      const mark = doc.createElement('div');
      mark.className = 'rctl-ghost';
      mark.innerHTML = `<span>${escHtml(ghost)}</span>`;
      record.parent.insertBefore(mark, node);
      record.ghost = mark;
    }
    entry.moved.push(record);
    return record;
  }

  function restore(entry) {
    // 거꾸로 - 서로 형제였던 노드들의 nextSibling 이 살아 있어야 제자리에 앉는다.
    for (let i = entry.moved.length - 1; i >= 0; i -= 1) {
      const {node, parent, next, ghost} = entry.moved[i];
      try {
        if (next && next.parentNode === parent) parent.insertBefore(node, next);
        else parent.appendChild(node);
      } catch { /* 부모가 사라졌다면 되돌릴 자리가 없다 - 조용히 넘긴다 */ }
      ghost?.remove?.();
    }
    entry.moved.length = 0;
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  function render() {
    panel.body.innerHTML = '';
    const keys = [...boarded.keys()];
    // 한 탭만 올라와 있으면 제목줄이 곧 그 탭 이름이다 - 구획 머리를 또 두면 줄만 먹는다.
    const single = keys.length === 1;
    panel.setTitle(single ? (boarded.get(keys[0]).title || 'Remote') : 'Remote');

    keys.forEach(key => {
      const entry = boarded.get(key);
      const sec = doc.createElement('div');
      sec.className = 'rctl-sec';
      sec.dataset.rctlKey = key;
      if (!single) {
        const head = doc.createElement('div');
        head.className = 'rctl-sec-head';
        head.textContent = entry.title || key;
        sec.appendChild(head);
      }
      entry.rows.forEach(row => {
        const nodes = (row.nodes || []).filter(Boolean);
        if (!nodes.length) return;
        const wrap = doc.createElement('div');
        wrap.className = ['rctl-row', row.fill ? 'rctl-fill' : '', row.className || '']
          .filter(Boolean).join(' ');
        nodes.forEach(node => wrap.appendChild(node));
        sec.appendChild(wrap);
      });
      panel.body.appendChild(sec);
    });
  }

  // ── 온보딩 ────────────────────────────────────────────────────────────
  /**
   * 탭의 조각을 리모컨으로 들어 올린다.
   *
   * @param {string} key    탭 열쇠(관리 단위). 같은 열쇠로 다시 부르면 갈아 끼운다.
   * @param {object} spec
   *   - title      리모컨 제목/구획 이름
   *   - rows       [{nodes:[HTMLElement], fill?:boolean, className?:string}]
   *                `fill` 인 줄이 남는 높이를 다 먹는다(썸네일 격자).
   *   - ghosts     Map(node -> '자리에 남길 안내 문구') - 큰 구멍에만 쓴다
   *   - onRelease  리모컨이 이 조각을 놓을 때(닫힘·해제) 불린다. 모듈의 토글을 끈다.
   */
  function onboard(key, {title = '', rows = [], ghosts = null, onRelease = null} = {}) {
    if (!key) return false;
    if (boarded.has(key)) offboard(key, {silent: true});
    const entry = {title, rows, onRelease, moved: []};
    rows.forEach(row => (row.nodes || []).forEach(node => {
      lift(entry, node, {ghost: ghosts?.get?.(node) || null});
    }));
    if (!entry.moved.length) return false;
    boarded.set(key, entry);
    render();
    panel.open();
    return true;
  }

  function offboard(key, {silent = false} = {}) {
    const entry = boarded.get(key);
    if (!entry) return false;
    boarded.delete(key);
    restore(entry);
    if (!silent) {
      render();
      // 마지막 하나가 빠지면 닫는다 - 빈 리모컨이 떠 있을 이유가 없다.
      if (!boarded.size) panel.close();
    }
    return true;
  }

  /** [x] 로 닫았을 때 - 올라와 있던 것을 전부 제자리로 돌리고 각 모듈에 알린다. */
  let releasing = false;
  function releaseAll() {
    if (releasing) return;
    releasing = true;
    try {
      [...boarded.keys()].forEach(key => {
        const entry = boarded.get(key);
        boarded.delete(key);
        restore(entry);
        try { entry.onRelease?.(key); } catch (error) { console.error('remote onRelease', error); }
      });
      panel.body.innerHTML = '';
    } finally {
      releasing = false;
    }
  }

  return {
    ...panel,
    onboard,
    offboard,
    releaseAll,
    isOnboarded: key => boarded.has(key),
    onboardedKeys: () => [...boarded.keys()],
    toggleOnboard(key, spec) {
      if (boarded.has(key)) { offboard(key); return false; }
      return onboard(key, spec);
    },
    /** 자리·크기를 처음으로 되돌린다(리모컨을 화면 밖에 두고 잃어버렸을 때). */
    resetGeometry() {
      panel.resetGeometry();
      showToast('Remote 컨트롤러 위치를 초기화했습니다.', 'info');
    },
  };
}
