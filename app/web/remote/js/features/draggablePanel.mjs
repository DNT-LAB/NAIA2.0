/** draggablePanel — 화면 위에 떠 있는 창 하나를 만드는 공용 뼈대.
 *
 *  이 저장소의 팝업은 지금까지 전부 **고정 위치**이거나 **누른 단추에 붙는 앵커**였다.
 *  사용자가 원하는 자리에 놓고 그대로 두는 창은 없었다. Remote 컨트롤러가 그것을
 *  요구하므로 여기서 한 번만 만들어 두고 앞으로 다 여기에 얹는다.
 *
 *      ┌─ 머리줄(잡는 곳) ────────── [—] [×] ┐
 *      │                                     │
 *      │            본문(호출자가 채운다)      │
 *      │                                  ◢  │  ← 크기 조절(선택)
 *      └─────────────────────────────────────┘
 *
 *  왜 이렇게 만들었는지 — 전부 실제로 밟은 함정이다:
 *
 *  ⚠️ **`[hidden]` 은 `display:flex` 에 진다.** 이 저장소에서 세 번 밟았다
 *     (`.fs-*`, `.em-tab`, 모듈 팝업). 짝 규칙 `.dragpanel[hidden]{display:none!important}`
 *     이 style.css 에 **같은 커밋으로** 들어가 있어야 한다.
 *  ⚠️ **Pointer Events 한 길로만 간다.** mouse/touch 를 따로 달면 폰에서 두 번 발화하거나
 *     한쪽만 먹는다. `setPointerCapture` 를 쓰면 포인터가 창 밖으로 나가도 끊기지 않는다.
 *  ⚠️ **머리줄에 `touch-action:none`** 이 없으면 폰에서 창을 끄는 대신 페이지가 스크롤된다.
 *  ⚠️ **놓을 때가 아니라 옮기는 내내 clamp 한다.** 화면을 줄이면(창 크기 변경·폰 회전)
 *     밖으로 나간 창은 영영 못 잡는다 - `resize` 에서도 다시 clamp 한다. 조건은
 *     "창 전체가 보인다" 가 아니라 **"머리줄을 잡을 수 있다"** 다(실제 창 관리자와 같다).
 *  ⚠️ **문턱(3px) 없이 드래그를 시작하면** 머리줄의 단추가 눌리지 않는다 - 손가락은
 *     반드시 1~2px 움직인다.
 *  ⚠️ 위치는 **localStorage**(기기별)에 둔다. 서버에 두면 PC 에서 정한 자리가 폰에도
 *     가서 화면 밖에 놓인다. 메모와 달리 위치는 기기의 사정이다.
 */

// 떠 있는 창들의 앞뒤 순서. 마지막이 맨 앞.
const REGISTRY = [];
let zBase = 0;

function zIndexBase(doc) {
  if (zBase) return zBase;
  const raw = doc?.defaultView?.getComputedStyle?.(doc.documentElement)
    ?.getPropertyValue?.('--z-drag-panel');
  const parsed = Number.parseInt(String(raw || '').trim(), 10);
  zBase = Number.isFinite(parsed) && parsed > 0 ? parsed : 10150;
  return zBase;
}

function restack(doc) {
  const base = zIndexBase(doc);
  REGISTRY.forEach((panel, index) => {
    panel.el.style.zIndex = String(base + index);
  });
}

function clamp(value, low, high) {
  if (high < low) return low;
  return value < low ? low : (value > high ? high : value);
}

export function createDraggablePanel({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  id = '',
  title = '',
  // 뿌리 요소에 함께 붙는 클래스. 기능별 옷은 여기로 입힌다(`.rctl` 처럼).
  variant = '',
  parent = null,
  // 위치를 기억할 열쇠. 비우면 기억하지 않는다.
  storageKey = '',
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  // ⚠️ **크기는 이번 실행에만** 산다(사용자 지정). 앱을 다시 켜면 새 창이라 이 저장소가
  //    비어 있고 크기가 기본값으로 돌아온다 - 새로고침(F5)에는 남는다.
  //    자리를 기억하는 것과 규칙이 다른 이유: 화면에 안 맞는 크기가 저장되면 손잡이가
  //    닿지 않는 자리로 가서, 고치려면 앱을 최대화해야 했다(사용자 제보).
  sizeStorage = (typeof sessionStorage !== 'undefined' ? sessionStorage : null),
  // 처음 열릴 때의 자리. right/bottom 은 화면 오른쪽/아래에서 잰 값.
  initial = {},
  width = 300,
  // ⚠️ `resizable` 창은 **처음부터 높이가 정해져 있어야 한다.** 안 그러면 내용만큼
  //    자란다 - 썸네일 격자를 넣었더니 창이 2,942px 이 됐다(실측). 화면을 넘는 창은
  //    머리줄만 잡힐 뿐 아래쪽을 영영 못 본다.
  height = 360,
  minWidth = 200,
  minHeight = 96,
  maxWidth = 720,
  resizable = false,
  collapsible = true,
  closable = true,
  // 가장자리에 이만큼 가까우면 딱 붙인다. 0 이면 끄기.
  edgeSnap = 12,
  // 창의 이 만큼은 언제나 화면 안에 남는다(가로).
  keepVisible = 72,
  onOpen = null,
  onClose = null,
  onCollapse = null,
  onMove = null,
  escHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
} = {}) {
  if (!doc) throw new Error('createDraggablePanel: document 가 필요합니다');
  const view = win || doc.defaultView;

  const el = doc.createElement('div');
  el.className = ['dragpanel', variant].filter(Boolean).join(' ');
  if (id) el.id = id;
  el.hidden = true;
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', title || 'panel');
  el.style.width = `${width}px`;

  el.innerHTML = `
    <div class="dragpanel-head" data-drag-handle tabindex="0"
         role="toolbar" aria-label="${escHtml(title)} 이동">
      <span class="dragpanel-grab" aria-hidden="true"></span>
      <span class="dragpanel-title">${escHtml(title)}</span>
      <span class="dragpanel-slot" data-nodrag></span>
      <span class="dragpanel-tools" data-nodrag>
        ${collapsible ? `<button type="button" class="dragpanel-btn dragpanel-collapse"
            aria-label="접기" title="접기">&#8211;</button>` : ''}
        ${closable ? `<button type="button" class="dragpanel-btn dragpanel-x"
            aria-label="닫기" title="닫기">&times;</button>` : ''}
      </span>
    </div>
    <div class="dragpanel-body"></div>
    ${resizable ? '<span class="dragpanel-grip" data-nodrag aria-hidden="true"></span>' : ''}
  `;

  const head = el.querySelector('.dragpanel-head');
  const body = el.querySelector('.dragpanel-body');
  const slot = el.querySelector('.dragpanel-slot');
  const titleEl = el.querySelector('.dragpanel-title');
  const grip = el.querySelector('.dragpanel-grip');
  const collapseBtn = el.querySelector('.dragpanel-collapse');
  const closeBtn = el.querySelector('.dragpanel-x');

  (parent || doc.body).appendChild(el);

  const api = {
    el, body, head, slot,
    open, close, toggle, isOpen, setTitle, moveTo, sizeTo, resetGeometry,
    collapse, expand, isCollapsed, raise, refit, destroy,
  };
  const entry = {el, api};

  let pos = {x: 0, y: 0};
  let collapsed = false;
  let placed = false;          // 한 번이라도 자리를 정했는가
  // ⚠️ `place()` 는 **자기 안에서 다시 불릴 수 있다**: 기억에서 `collapsed` 를
  //    되살리면 `setCollapsed -> refit -> place` 로 돌아온다. 그때 `placed` 는
  //    아직 false 라 `refit` 이 또 `place` 를 부른다 - 스택이 터진다(실측).
  let placing = false;
  let drag = null;
  let placeRetry = 0;
  let heldHeight = '';   // 접기 전의 세로 크기(펴면 되돌린다)
  // 사용자가 **직접** 크기를 잡았는가. 안 잡았으면 기본값을 따라간다 - 안 그러면
  // 기본값을 고쳐도 한 번이라도 창을 옮긴 사람에게는 영영 안 먹는다(사용자 제보).
  let userSized = false;
  let rafId = 0;
  let pending = null;

  // ── 기억 ────────────────────────────────────────────────────────────
  const memoryKey = storageKey ? `naia.dragpanel.${storageKey}` : '';
  const sizeKey = storageKey ? `naia.dragpanel.size.${storageKey}` : '';

  function readSlot(key, box) {
    if (!key || !box) return null;
    try {
      const parsed = JSON.parse(box.getItem(key) || 'null');
      return (parsed && typeof parsed === 'object') ? parsed : null;
    } catch { return null; }
  }

  /** 자리(오래 간다) + 크기(이번 실행만)를 하나로 합쳐 돌려준다. */
  function readMemory() {
    const where = readSlot(memoryKey, storage);
    const size = readSlot(sizeKey, sizeStorage);
    if (!where && !size) return null;
    return {...(where || {}), ...(size || {})};
  }

  function writeMemory() {
    if (memoryKey && storage) {
      try {
        storage.setItem(memoryKey, JSON.stringify({
          x: Math.round(pos.x), y: Math.round(pos.y),
          collapsed,
        }));
      } catch { /* 사파리 프라이빗 모드 등 - 위치를 못 외우는 것뿐이다 */ }
    }
    if (sizeKey && sizeStorage) {
      try {
        sizeStorage.setItem(sizeKey, JSON.stringify({
          w: Math.round(el.getBoundingClientRect().width) || width,
          h: resizable
            ? (collapsed ? Number.parseInt(heldHeight, 10) || 0
                         : Math.round(el.getBoundingClientRect().height))
            : 0,
          // 이 표가 없으면(옛 기록 포함) 크기는 안 되살린다.
          sized: userSized,
        }));
      } catch { /* noop */ }
    }
  }

  // ── 자리 ────────────────────────────────────────────────────────────
  function viewport() {
    return {
      w: view?.innerWidth || doc.documentElement.clientWidth || 0,
      h: view?.innerHeight || doc.documentElement.clientHeight || 0,
    };
  }

  /** 화면 밖으로 못 나가게 — 단, "전부 보이게" 가 아니라 **머리줄을 잡을 수 있게**.
   *  창을 반쯤 가장자리에 걸쳐 두는 것은 사용자의 자유다. */
  function clampPos(x, y) {
    const {w: vw, h: vh} = viewport();
    const rect = el.getBoundingClientRect();
    const w = rect.width || width;
    const headH = head.getBoundingClientRect().height || 34;
    const keep = Math.min(keepVisible, w);
    return {
      x: clamp(x, keep - w, Math.max(keep - w, vw - keep)),
      y: clamp(y, 0, Math.max(0, vh - headH)),
    };
  }

  /** 처음 놓을 때만 - 창이 통째로 들어갈 수 있으면 들어가게 위로 당긴다.
   *  ⚠️ 끄는 중의 clampPos 와 섞지 말 것. 그쪽은 '머리줄만 잡히면 된다' 가 규칙이고
   *     (가장자리에 걸쳐 두는 것은 사용자의 자유), 이쪽은 '처음에는 다 보여야 한다' 다.
   *     안 그러면 아래쪽 단추가 잘린 채 뜬다(실측: 866px 창 + 900px 화면). */
  function fitWholePanel(x, y) {
    const {w: vw, h: vh} = viewport();
    const rect = el.getBoundingClientRect();
    const h = rect.height || minHeight;
    const w = rect.width || width;
    let nx = x;
    let ny = y;
    if (h <= vh - 12 && y + h > vh - 8) ny = Math.max(8, vh - h - 8);
    // ⚠️ 가로도 같이 들여놓는다. 안 하면 `clampPos` 로 흘러가 72px 만 남기고 걸치는데,
    //    그 규칙은 **끄는 중**의 것이다. 좁아진 화면에서 다시 열면 오른쪽이 - 크기
    //    손잡이째 - 화면 밖에 놓인다(실측: 저장 x=1086, 화면 502, 490 창이 x=430).
    if (w <= vw - 12 && x + w > vw - 8) nx = Math.max(8, vw - w - 8);
    return {x: nx, y: ny};
  }

  /** 가로 하한. 보통은 `minWidth` 지만 화면이 그보다 좁으면 화면이 이긴다 -
   *  안 그러면 폰에서 창이 화면을 넘는다. */
  function widthFloor() {
    const {w: vw} = viewport();
    return vw > 0 ? Math.min(minWidth, Math.max(120, vw - 8)) : minWidth;
  }

  function applyPos() {
    el.style.left = `${Math.round(pos.x)}px`;
    el.style.top = `${Math.round(pos.y)}px`;
  }

  function schedule() {
    if (rafId) return;
    const raf = view?.requestAnimationFrame || (fn => setTimeout(fn, 16));
    rafId = raf.call(view || null, () => {
      rafId = 0;
      if (!pending) return;
      pos = clampPos(pending.x, pending.y);
      pending = null;
      applyPos();
    });
  }

  function moveTo(x, y, {persist = true} = {}) {
    pos = clampPos(x, y);
    placed = true;
    applyPos();
    if (persist) writeMemory();
    if (typeof onMove === 'function') onMove({x: pos.x, y: pos.y});
    return {...pos};
  }

  function sizeTo(w, h) {
    const {w: vw, h: vh} = viewport();
    userSized = true;
    if (Number.isFinite(w)) {
      el.style.width = `${Math.round(clamp(w, widthFloor(), Math.min(maxWidth, vw - 8)))}px`;
    }
    if (resizable && Number.isFinite(h) && h > 0) {
      el.style.height = `${Math.round(clamp(h, minHeight, vh - 8))}px`;
    }
    refit();
  }

  /** 첫 자리 — 기억 > initial > 오른쪽 아래에서 살짝 띄운 기본값. */
  function place() {
    // 재진입 빗장. 되돌아온 호출은 그냥 지나간다 - 바깥의 `place` 가 끝까지 가서
    // `moveTo` 로 자리를 정하면 `placed` 가 서고 다음부터는 정상 경로로 돈다.
    if (placing) return;
    placing = true;
    try {
      placeBody();
    } finally {
      placing = false;
    }
  }

  function placeBody() {
    const {w: vw, h: vh} = viewport();
    // ⚠️ 화면을 **못 재는 순간**(숨은 탭·최소화·접힌 pane — innerWidth 가 0)에 자리를
    //    정하면 창이 화면 밖에 놓인다. 그런데 refit 은 정해진 자리를 안으로 들일 뿐
    //    되돌리지 못해 영영 그 자리다 — 잴 수 있을 때까지 미룬다.
    if (vw <= 0 || vh <= 0) {
      placed = false;
      if (placeRetry < 120) {
        placeRetry += 1;
        const raf = view?.requestAnimationFrame || (fn => setTimeout(fn, 32));
        raf.call(view || null, () => { if (isOpen() && !placed) place(); });
      }
      return;
    }
    placeRetry = 0;
    if (resizable && !el.style.height) {
      el.style.height = `${Math.round(clamp(height, minHeight, vh - 16))}px`;
      heldHeight = el.style.height;
    }
    const saved = readMemory();
    if (saved) {
      // ⚠️ 크기는 **사용자가 직접 잡았을 때만** 되살린다. 자리만 옮긴 사람에게까지
      //    그때의 크기를 씌우면 기본값을 고쳐도 반영되지 않는다(사용자 제보).
      userSized = !!saved.sized;
      if (userSized && Number.isFinite(saved.w)) {
        el.style.width = `${clamp(saved.w, widthFloor(), Math.min(maxWidth, vw - 8))}px`;
      }
      if (userSized && resizable && Number.isFinite(saved.h) && saved.h > 0) {
        el.style.height = `${clamp(saved.h, minHeight, vh - 8)}px`;
        heldHeight = el.style.height;
      }
      if (saved.collapsed && collapsible) setCollapsed(true, {persist: false});
      if (Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
        // 더 큰 화면에서 정한 자리일 수 있다 - 들어갈 수 있으면 들여놓는다.
        const fit = fitWholePanel(saved.x, saved.y);
        moveTo(fit.x, fit.y, {persist: false});
        return;
      }
    }
    const rect = el.getBoundingClientRect();
    const w = rect.width || width;
    const h = rect.height || minHeight;
    const x = Number.isFinite(initial.x) ? initial.x
      : (Number.isFinite(initial.right) ? vw - w - initial.right : vw - w - 24);
    const y = Number.isFinite(initial.y) ? initial.y
      : (Number.isFinite(initial.bottom) ? vh - h - initial.bottom : Math.max(24, vh * 0.28));
    const fit = fitWholePanel(x, y);
    moveTo(fit.x, fit.y, {persist: false});
  }

  /** 화면이 바뀌었다(창 크기·폰 회전·주소창 접힘) → 다시 안으로 들인다. */
  function refit() {
    // 아직 자리를 못 정했으면(0x0 이었다) 이제 잴 수 있는지 다시 본다.
    if (!placed) { if (isOpen()) place(); return; }
    // 화면보다 큰 창은 줄인다 - 창을 줄이면 아래쪽이 영영 화면 밖에 남는다.
    const {w: vw, h: vh} = viewport();
    if (vw > 0 && vh > 0) {
      const rect = el.getBoundingClientRect();
      if (rect.width > vw - 8) el.style.width = `${Math.max(widthFloor(), vw - 8)}px`;
      if (resizable && rect.height > vh - 8) el.style.height = `${Math.max(minHeight, vh - 8)}px`;
    }
    const next = clampPos(pos.x, pos.y);
    if (next.x !== pos.x || next.y !== pos.y) {
      pos = next;
      applyPos();
    }
  }

  function resetGeometry() {
    if (memoryKey && storage) { try { storage.removeItem(memoryKey); } catch { /* noop */ } }
    if (sizeKey && sizeStorage) { try { sizeStorage.removeItem(sizeKey); } catch { /* noop */ } }
    el.style.width = `${width}px`;
    el.style.height = '';
    heldHeight = '';
    userSized = false;
    setCollapsed(false, {persist: false});
    placed = false;
    place();
    writeMemory();
  }

  // ── 앞뒤 ────────────────────────────────────────────────────────────
  function raise() {
    const at = REGISTRY.indexOf(entry);
    if (at >= 0) REGISTRY.splice(at, 1);
    REGISTRY.push(entry);
    restack(doc);
  }

  // ── 끌기 ────────────────────────────────────────────────────────────
  const DRAG_THRESHOLD = 3;

  function onHeadPointerDown(event) {
    if (event.button != null && event.button !== 0) return;
    if (event.target.closest('[data-nodrag]')) return;
    raise();
    drag = {
      id: event.pointerId,
      startX: event.clientX, startY: event.clientY,
      originX: pos.x, originY: pos.y,
      moved: false, mode: 'move',
    };
    try { head.setPointerCapture(event.pointerId); } catch { /* 캡처 못해도 문서 리스너가 받는다 */ }
  }

  function onGripPointerDown(event) {
    if (event.button != null && event.button !== 0) return;
    event.preventDefault();
    raise();
    const rect = el.getBoundingClientRect();
    drag = {
      id: event.pointerId,
      startX: event.clientX, startY: event.clientY,
      originW: rect.width, originH: rect.height,
      moved: false, mode: 'resize',
    };
    try { grip.setPointerCapture(event.pointerId); } catch { /* noop */ }
  }

  function onPointerMove(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.moved) {
      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
      drag.moved = true;
      el.classList.add('is-dragging');
      doc.body.classList.add('dragpanel-dragging');
    }
    event.preventDefault();
    if (drag.mode === 'resize') {
      const {w: vw, h: vh} = viewport();
      el.style.width = `${Math.round(clamp(drag.originW + dx, widthFloor(), Math.min(maxWidth, vw - 8)))}px`;
      el.style.height = `${Math.round(clamp(drag.originH + dy, minHeight, vh - 8))}px`;
      heldHeight = el.style.height;
      userSized = true;
      refit();
      return;
    }
    pending = {x: drag.originX + dx, y: drag.originY + dy};
    schedule();
  }

  function onPointerUp(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const wasMoved = drag.moved;
    const mode = drag.mode;
    drag = null;
    el.classList.remove('is-dragging');
    doc.body.classList.remove('dragpanel-dragging');
    if (!wasMoved) return;
    if (pending) { pos = clampPos(pending.x, pending.y); pending = null; applyPos(); }
    if (mode === 'move' && edgeSnap > 0) snapToEdges();
    placed = true;
    writeMemory();
    if (typeof onMove === 'function') onMove({x: pos.x, y: pos.y});
  }

  /** 가장자리 근처면 딱 붙인다 — 손으로 맞추면 1~2px 이 늘 어긋난다. */
  function snapToEdges() {
    const {w: vw, h: vh} = viewport();
    const rect = el.getBoundingClientRect();
    let {x, y} = pos;
    if (Math.abs(x) <= edgeSnap) x = 0;
    else if (Math.abs(vw - (x + rect.width)) <= edgeSnap) x = vw - rect.width;
    if (Math.abs(y) <= edgeSnap) y = 0;
    else if (Math.abs(vh - (y + rect.height)) <= edgeSnap) y = vh - rect.height;
    pos = clampPos(x, y);
    applyPos();
  }

  /** 머리줄에 초점이 있으면 화살표로 1px(Shift 10px) 씩 — 미세 조정과 키보드 접근성. */
  function onHeadKeyDown(event) {
    const step = event.shiftKey ? 10 : 1;
    let dx = 0;
    let dy = 0;
    if (event.key === 'ArrowLeft') dx = -step;
    else if (event.key === 'ArrowRight') dx = step;
    else if (event.key === 'ArrowUp') dy = -step;
    else if (event.key === 'ArrowDown') dy = step;
    else return;
    event.preventDefault();
    moveTo(pos.x + dx, pos.y + dy);
  }

  // ── 접기 ────────────────────────────────────────────────────────────
  function setCollapsed(next, {persist = true} = {}) {
    if (!collapsible) return;
    collapsed = !!next;
    // ⚠️ 접힌 상태에서 `height` 를 그대로 두면 머리줄 아래가 빈 채로 남는다. 그렇다고
    //    그냥 지우면 **펼 때 사용자가 잡아 둔 세로 크기를 잃는다** - 따로 들고 있다가
    //    되돌린다(잡아 둔 적이 없으면 내용에 맡긴다).
    if (collapsed) {
      if (!el.classList.contains('is-collapsed')) heldHeight = el.style.height || '';
      el.style.height = '';
    } else if (heldHeight) {
      el.style.height = heldHeight;
    }
    el.classList.toggle('is-collapsed', collapsed);
    if (collapseBtn) {
      collapseBtn.innerHTML = collapsed ? '&#9633;' : '&#8211;';
      collapseBtn.setAttribute('aria-label', collapsed ? '펴기' : '접기');
      collapseBtn.title = collapsed ? '펴기' : '접기';
    }
    refit();
    if (persist) writeMemory();
    if (typeof onCollapse === 'function') onCollapse(collapsed);
  }

  // ⚠️ 화살표 함수(const)로 두면 위의 `api` 리터럴이 TDZ 에 걸린다
  //    ("Cannot access 'collapse' before initialization"). 선언문으로 두어 끌어올린다.
  function collapse() { setCollapsed(true); }
  function expand() { setCollapsed(false); }
  function isCollapsed() { return collapsed; }

  // ── 열고 닫기 ────────────────────────────────────────────────────────
  function isOpen() { return !el.hidden; }

  function open() {
    if (isOpen()) { raise(); return; }
    el.hidden = false;
    if (!placed) place(); else refit();
    raise();
    if (typeof onOpen === 'function') onOpen();
  }

  function close() {
    if (!isOpen()) return;
    el.hidden = true;
    const at = REGISTRY.indexOf(entry);
    if (at >= 0) REGISTRY.splice(at, 1);
    if (typeof onClose === 'function') onClose();
  }

  function toggle() { if (isOpen()) close(); else open(); }

  function setTitle(text) {
    titleEl.textContent = String(text ?? '');
    el.setAttribute('aria-label', String(text ?? ''));
  }

  // ── 배선 ────────────────────────────────────────────────────────────
  head.addEventListener('pointerdown', onHeadPointerDown);
  head.addEventListener('keydown', onHeadKeyDown);
  head.addEventListener('dblclick', event => {
    if (event.target.closest('[data-nodrag]')) return;
    setCollapsed(!collapsed);
  });
  if (grip) grip.addEventListener('pointerdown', onGripPointerDown);
  // 캡처가 잡히면 이 둘은 head/grip 으로 오지만, 캡처가 실패한 브라우저를 위해 문서에도 건다.
  doc.addEventListener('pointermove', onPointerMove, {passive: false});
  doc.addEventListener('pointerup', onPointerUp);
  doc.addEventListener('pointercancel', onPointerUp);
  // 본문 어디를 눌러도 맨 앞으로.
  el.addEventListener('pointerdown', () => { if (isOpen()) raise(); }, true);
  if (collapseBtn) collapseBtn.addEventListener('click', () => setCollapsed(!collapsed));
  if (closeBtn) closeBtn.addEventListener('click', () => close());
  const onViewportChange = () => refit();
  view?.addEventListener?.('resize', onViewportChange);
  view?.addEventListener?.('orientationchange', onViewportChange);
  // ⚠️ `resize` 만으로는 놓치는 화면 변화가 있다 — 개발자도구 뷰포트 에뮬레이션(실측:
  //    한 번도 안 왔다), 폰 주소창 접힘, 창 분할. 뿌리 요소를 직접 지켜보는 쪽이 확실하다.
  //    관측은 refit 만 부른다(값을 안 읽고 다시 재기만 하므로 되먹임 고리가 없다).
  let rootObserver = null;
  if (typeof ResizeObserver === 'function') {
    rootObserver = new ResizeObserver(() => refit());
    try { rootObserver.observe(doc.documentElement); } catch { rootObserver = null; }
  }

  function destroy() {
    close();
    head.removeEventListener('pointerdown', onHeadPointerDown);
    head.removeEventListener('keydown', onHeadKeyDown);
    doc.removeEventListener('pointermove', onPointerMove);
    doc.removeEventListener('pointerup', onPointerUp);
    doc.removeEventListener('pointercancel', onPointerUp);
    view?.removeEventListener?.('resize', onViewportChange);
    view?.removeEventListener?.('orientationchange', onViewportChange);
    rootObserver?.disconnect?.();
    el.remove();
  }

  return api;
}
