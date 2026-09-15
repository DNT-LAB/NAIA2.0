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
import {createDraggablePanel} from './draggablePanel.mjs?v=20260914-rctl10';

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
    // 썸네일 격자가 들어오므로 좁으면 쓸모가 없다. 세 칸 + 여유 한 뼘.
    // 500 -> 490 (사용자 지정 2026-09-14: "너비를 10만큼만 줄입니다").
    width: 490,
    // ⚠️ **설계값 아래로는 못 줄인다**(사용자 지정) - 격자가 3칸 고정이라 더 좁히면
    //    카드가 설계보다 작아진다. 화면이 이보다 좁으면 그때는 화면에 맞춘다.
    // 3칸 고정이라 이 아래로는 카드가 너무 좁아진다. 처음엔 초기 설계값(490)을
    // 하한으로 뒀다가 "최소 너비가 너무 크다"는 제보로 낮췄다(사용자 지정).
    minWidth: 400,
    maxWidth: 900,
    // 썸네일 격자가 본론이지만 창이 화면을 다 덮으면 리모컨이 아니다.
    // ⚠️ **740 은 사용자가 실물을 보고 정한 값이다**(2026-09-14). 그 전까지 내가 올리던
    //    560->640->740->866 은 **한 번도 사용자 화면에 닿지 않았다** - 저장본이 첫 값
    //    (560)에서 굳어 기본값을 덮고 있었다(`sized` 로 고침). 그러니 이 숫자를 다시
    //    올릴 때는 **저장본을 심어 놓고** 실물로 확인할 것.
    // 카드 150px 기준 세 줄 남짓 보인다. 화면이 낮으면 place()/refit 이 줄인다.
    height: 740,
    minHeight: 200,
    resizable: true,
    collapsible: true,
    closable: true,
    initial: {right: 24, y: 96},
    escHtml,
    onClose: () => releaseAll(),
    // 창이 움직이거나 접히면 확대창의 자리가 의미를 잃는다. 끄는 중에는 pointerdown 이
    // 이미 걷지만, **키보드 화살표 이동**과 **접기**는 그 길로 안 온다(실측).
    onMove: () => { hideZoom(); placeSide(); },
    onCollapse: () => { hideZoom(); placeSide(); },
  });

  // 탭 열쇠 -> {title, rows, onRelease, moved:[{node, parent, next}], ghosts:[...]}
  const boarded = new Map();

  // ── 노드를 들어 올리고 되돌리기 ────────────────────────────────────────
  function lift(entry, node, {ghost = null, tag = ''} = {}) {
    if (!node || !node.parentNode) return null;
    const record = {node, parent: node.parentNode, next: node.nextSibling, ghost: null, tag: ''};
    // 줄 안에서 어느 칸인지 CSS 에 알려 준다. `:nth-child` 로 자리를 세면 조각 하나만
    // 늘어도 조용히 어긋나므로 이름을 붙인다. 되돌릴 때 다시 뗀다(원본을 안 남긴다).
    if (tag) {
      record.tag = `rctl-${tag}`;
      node.classList.add(record.tag);
    }
    // 자리 표식. 큰 구멍(격자)에는 안내를 띄우고, 격자 칸 안에서 빠져나간 조각에는
    // **얇은 표식**을 남긴다 - 안 남기면 남은 형제들이 칸을 밀고 들어와 탭이 뒤틀린다
    // (`.artist-thumb-toolbar-controls` 는 3열 grid 다).
    if (ghost) {
      const spec = (typeof ghost === 'string') ? {text: ghost} : (ghost || {});
      const mark = doc.createElement('div');
      mark.className = spec.slim ? 'rctl-ghost is-slim' : 'rctl-ghost';
      mark.innerHTML = `<span>${escHtml(spec.text || '')}</span>`;
      record.parent.insertBefore(mark, node);
      record.ghost = mark;
    }
    entry.moved.push(record);
    return record;
  }

  function restore(entry) {
    // 거꾸로 - 서로 형제였던 노드들의 nextSibling 이 살아 있어야 제자리에 앉는다.
    for (let i = entry.moved.length - 1; i >= 0; i -= 1) {
      const {node, parent, next, ghost, tag} = entry.moved[i];
      if (tag) node.classList.remove(tag);
      try {
        if (next && next.parentNode === parent) parent.insertBefore(node, next);
        else parent.appendChild(node);
      } catch { /* 부모가 사라졌다면 되돌릴 자리가 없다 - 조용히 넘긴다 */ }
      ghost?.remove?.();
    }
    entry.moved.length = 0;
  }

  /** 줄의 항목은 요소 그대로거나 `{node, tag}` 다(tag = 줄 안에서의 칸 이름). */
  const asNode = item => (item && item.nodeType === 1 ? item : (item?.node || null));

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
        const nodes = (row.nodes || []).map(asNode).filter(Boolean);
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
   *   - ghosts     Map(node -> '안내 문구' | {text, slim}) - 조각이 빠진 자리에 남길 표식.
   *                `slim` 은 칸만 지키는 얇은 것(격자 칸이 무너지지 않게).
   *   - onRelease  리모컨이 이 조각을 놓을 때(닫힘·해제) 불린다. 모듈의 토글을 끈다.
   *   - hoverPreview {selector, resolve(el) -> {src, title, note} | null}
   *                마우스를 올리면 창 **옆**에 크게 띄운다(리모컨에서는 썸네일이 작다).
   */
  function onboard(key, {title = '', rows = [], ghosts = null, onRelease = null,
                         hoverPreview = null} = {}) {
    if (!key) return false;
    if (boarded.has(key)) offboard(key, {silent: true});
    const entry = {title, rows, onRelease, hoverPreview, moved: []};
    rows.forEach(row => (row.nodes || []).forEach(item => {
      const node = asNode(item);
      lift(entry, node, {ghost: ghosts?.get?.(node) || null, tag: item?.tag || ''});
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
      hideZoom();
    } finally {
      releasing = false;
    }
  }

  // ── 마우스를 올리면 옆에 크게 ──────────────────────────────────────────
  //  리모컨 안에서는 썸네일이 112px 까지 줄어든다 - 그림을 보려고 켠 창인데 정작 그림이
  //  안 보인다. 창 **바깥** 좌우 중 넓은 쪽에 띄운다(창 안에 띄우면 격자를 가린다).
  const HOVER_DELAY_MS = 140;
  const HOVER_WIDTH = 320;
  let hoverEl = null;
  let hoverTimer = null;
  let hoverTarget = null;

  function hoverBox() {
    if (hoverEl) return hoverEl;
    hoverEl = doc.createElement('div');
    hoverEl.className = 'rctl-zoom';
    hoverEl.hidden = true;
    doc.body.appendChild(hoverEl);
    return hoverEl;
  }

  function hideZoom() {
    hoverTarget = null;
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
    if (hoverEl) hoverEl.hidden = true;
  }

  /** 창(또는 다른 기준 상자) **바깥** 좌우 중 넓은 쪽에 붙인다.
   *  ⚠️ 확대 보기와 보조 판이 같은 규칙을 써야 서로 겹쳐도 말이 된다. */
  function placeBeside(box, anchorRect, top) {
    const boxRect = box.getBoundingClientRect();
    const vw = win?.innerWidth || doc.documentElement.clientWidth;
    const vh = win?.innerHeight || doc.documentElement.clientHeight;
    const roomLeft = anchorRect.left;
    const roomRight = vw - anchorRect.right;
    const left = (roomLeft >= boxRect.width + 16 || roomLeft > roomRight)
      ? anchorRect.left - boxRect.width - 10
      : anchorRect.right + 10;
    box.style.left = `${Math.round(Math.max(6, Math.min(left, vw - boxRect.width - 6)))}px`;
    box.style.top = `${Math.round(Math.max(6, Math.min(top, vh - boxRect.height - 6)))}px`;
  }

  function showZoom(target, info, anchorRect = null) {
    const box = hoverBox();
    box.innerHTML = `<img src="${escHtml(info.src)}" alt="">`
      + `<div class="rctl-zoom-cap"><b>${escHtml(info.title || '')}</b>`
      + (info.note ? `<span>${escHtml(info.note)}</span>` : '') + '</div>';
    box.hidden = false;
    const cardRect = target.getBoundingClientRect();
    const boxRect = box.getBoundingClientRect();
    // 세로는 올린 칸에 맞춘다. 가로 기준은 호출자가 정한다 - 격자 칸은 **창** 기준
    // (믹스 판 위에 그대로 덮는다), 믹스 블럭은 **믹스 판** 기준(그 옆으로 비킨다).
    placeBeside(box, anchorRect || panel.el.getBoundingClientRect(),
                cardRect.top + cardRect.height / 2 - boxRect.height / 2);
  }

  // ── 창 옆 보조 판(믹스 큐) ────────────────────────────────────────────
  //  확대 보기가 뜨던 그 자리를 쓴다(사용자 지정). 확대 보기보다 **아래** 층이라
  //  격자 칸에 마우스를 올리면 그 위로 덮인다.
  let sideEl = null;
  let sideSummaryEl = null;
  let idleTimer = null;
  let folded = false;
  let pinned = false;

  function sideHost() {
    if (sideEl) return sideEl;
    sideEl = doc.createElement('div');
    sideEl.className = 'rctl-side';
    sideEl.hidden = true;
    sideSummaryEl = doc.createElement('div');
    sideSummaryEl.className = 'rctl-side-summary';
    doc.body.appendChild(sideEl);
    // 관심을 주면 다시 펴진다. 보조 판과 창 **둘 다** 본다 - 사용자가 격자를 훑는
    // 동안 옆의 큐가 접히면 안 된다.
    for (const target of [sideEl, panel.el]) {
      for (const type of ['pointermove', 'pointerdown', 'pointerup', 'wheel', 'keydown', 'focusin']) {
        target.addEventListener(type, poke, {passive: true});
      }
    }
    return sideEl;
  }

  // ── 가만히 두면 접힌다 ────────────────────────────────────────────────
  //  이 판은 그림 위에 뜬다(사용자 지정). 5초간 아무 관심이 없으면 제목줄 + 아주
  //  작은 글씨의 아티스트 목록만 남기고 말아 올린다.
  const IDLE_FOLD_MS = 5000;

  /** 지금 손이 이 안에 있는가. 있으면 **절대** 접지 않는다 -
   *  prefix/postfix 를 치다가 잠깐 생각하는 사이에 칸이 말려 올라가면 최악이다. */
  function attentionHeld() {
    const active = doc.activeElement;
    if (!active || active === doc.body) return false;
    return sideEl?.contains(active) || panel.el.contains(active);
  }

  function setFolded(next) {
    // 고정해 두면 접지 않는다 - 큐를 한참 붙들고 일할 때를 위한 빗장(사용자 지정).
    const want = Boolean(next) && !pinned && !attentionHeld();
    if (want === folded) return;
    folded = want;
    sideEl?.classList.toggle('is-folded', folded);
    placeSide();
  }

  function poke() {
    setFolded(false);
    if (idleTimer) clearTimeout(idleTimer);
    // 고정 중에는 시계를 아예 돌리지 않는다.
    if (pinned || !sideEl || sideEl.hidden) { idleTimer = null; return; }
    idleTimer = setTimeout(() => {
      idleTimer = null;
      if (attentionHeld()) { poke(); return; }   // 치는 중이면 그냥 다시 센다
      setFolded(true);
    }, IDLE_FOLD_MS);
  }

  /** 고정 = 자동 접힘 끄기. 켜는 순간 이미 접혀 있었다면 펴 준다. */
  function setSidePinned(next) {
    pinned = Boolean(next);
    sideHost().classList.toggle('is-pinned', pinned);
    poke();          // 켜면 펴고 시계를 멈추고, 끄면 다시 5초를 센다
    return pinned;
  }

  /** 접혔을 때 보여 줄 줄들. 그림 위에 얹는 글이라 상자도 배경도 없다. */
  function setSideSummary(lines) {
    sideHost();
    const rows = (Array.isArray(lines) ? lines : []).map(v => String(v || '').trim()).filter(Boolean);
    sideSummaryEl.innerHTML = rows.map(v => `<span>${escHtml(v)}</span>`).join('');
    sideSummaryEl.classList.toggle('is-empty', rows.length === 0);
  }

  function placeSide() {
    if (!sideEl || sideEl.hidden) return;
    const panelRect = panel.el.getBoundingClientRect();
    const vh = win?.innerHeight || doc.documentElement.clientHeight;
    // 창과 위를 맞추고, 창보다 길어지지 않게 자른다(안에서 스크롤한다).
    sideEl.style.maxHeight = `${Math.round(Math.min(panelRect.height, vh - 16))}px`;
    placeBeside(sideEl, panelRect, panelRect.top);
  }

  /** 시험·바깥에서 상태를 물을 때. */
  function sideFolded() {
    return folded;
  }

  /** 보조 판에 조각을 **쌓는다**(믹스 큐 + 그 아래 PE 빠른 수정). 부를 때마다 비운다. */
  function mountSide(...nodes) {
    const host = sideHost();
    host.innerHTML = '';
    nodes.flat().forEach(node => { if (node) host.appendChild(node); });
    host.appendChild(sideSummaryEl);   // 접혔을 때만 보이는 요약 - 늘 마지막에 둔다
    return host;
  }

  function showSide(open) {
    const host = sideHost();
    host.hidden = !open;
    if (open) { placeSide(); poke(); }
    else if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
    return !host.hidden;
  }

  function sideRect() {
    return sideEl && !sideEl.hidden ? sideEl.getBoundingClientRect() : null;
  }

  function hoverSpecFor(node) {
    for (const entry of boarded.values()) {
      const spec = entry.hoverPreview;
      if (!spec?.selector) continue;
      const target = node?.closest?.(spec.selector);
      if (target && panel.body.contains(target)) return {spec, target};
    }
    return null;
  }

  panel.body.addEventListener('pointerover', event => {
    // 손가락은 hover 가 없다 - 터치로는 띄우지 않는다(눌러야 할 칸을 가린다).
    if (event.pointerType === 'touch') return;
    const found = hoverSpecFor(event.target);
    if (!found) { hideZoom(); return; }
    if (found.target === hoverTarget) return;
    hoverTarget = found.target;
    if (hoverTimer) clearTimeout(hoverTimer);
    // 격자를 훑고 지나갈 때마다 번쩍이지 않게 조금 기다린다.
    hoverTimer = setTimeout(() => {
      hoverTimer = null;
      if (hoverTarget !== found.target) return;
      const info = found.spec.resolve?.(found.target);
      if (info?.src) showZoom(found.target, info);
      else if (hoverEl) hoverEl.hidden = true;
    }, HOVER_DELAY_MS);
  });
  panel.body.addEventListener('pointerout', event => {
    if (!event.relatedTarget || !panel.body.contains(event.relatedTarget)) hideZoom();
    else if (!hoverSpecFor(event.relatedTarget)) hideZoom();
  });
  // ⚠️ **대상이 사라지면 걷는다.** `Get Random Artist`/페이지 넘김은 격자를 통째로 다시
  //    그리는데, 커서가 그대로면 `pointerout` 이 안 온다 - 없는 카드를 계속 크게 보여
  //    주고 있었다(실측). 확대창은 '살아 있는 대상' 에 묶여 있어야 한다.
  if (typeof MutationObserver === 'function') {
    const gone = new MutationObserver(() => {
      if (hoverTarget && !panel.body.contains(hoverTarget)) hideZoom();
    });
    gone.observe(panel.body, {childList: true, subtree: true});
  }

  // 스크롤·드래그·창 닫힘에는 바로 걷는다(자리가 어긋난 채 떠 있으면 방해만 된다).
  panel.body.addEventListener('scroll', hideZoom, true);
  // ⚠️ 카드를 **누를 때는 걷지 않는다**(사용자 지정 2026-09-14) - 크게 보면서 고르는
  //    것이 이 기능의 쓸모인데 누르는 순간 닫히면 확인이 안 된다. 창이 움직이는
  //    경우(머리줄·크기 손잡이)에만 걷는다 - 그때는 자리가 어긋나기 때문이다.
  panel.el.addEventListener('pointerdown', event => {
    if (event.target.closest('.dragpanel-head, .dragpanel-grip')) hideZoom();
  }, true);
  win?.addEventListener?.('resize', () => { hideZoom(); placeSide(); });
  // 창 크기를 손잡이로 바꿀 때도 따라와야 한다(resize 이벤트가 안 온다).
  if (typeof ResizeObserver === 'function') {
    try { new ResizeObserver(() => placeSide()).observe(panel.el); } catch { /* noop */ }
  }

  return {
    ...panel,
    onboard,
    offboard,
    releaseAll,
    // 창 옆 보조 판(믹스 큐) - 확대 보기와 같은 자리를 쓴다.
    mountSide,
    showSide,
    placeSide,
    sideRect,
    // 가만히 두면 접히고, 접힌 동안 이 줄들을 아주 작게 보여 준다.
    setSideSummary,
    setSidePinned,
    sidePinned: () => pinned,
    sideFolded,
    foldSideNow: () => setFolded(true),
    /** 믹스 블럭처럼 **창이 아닌 것** 옆에 확대 보기를 띄울 때. */
    showZoomBeside: (target, info, anchorRect) => showZoom(target, info, anchorRect),
    hideZoom: () => hideZoom(),
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
