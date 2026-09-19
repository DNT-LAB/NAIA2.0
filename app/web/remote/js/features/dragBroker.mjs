/** 끌기 중개자 — 창을 **건너는** 끌기의 유일한 길.
 *
 *  원본(격자 카드 · 그룹 창 항목 · 믹스 큐 블럭)은 `arm()` 만 부르고, 받는 쪽(믹스 큐 ·
 *  그룹 창 · 임시 창)은 `registerZone()` 만 한다. 끌기 자체는 여기서 한 번만 구현한다 -
 *  진입점마다 따로 만들면 하나만 고쳐지는 일이 반복된다.
 *
 *  ⚠️ HTML5 drag-and-drop 을 쓰지 않는다(유령만 움직여 "부자연스럽다" 는 제보로 걷어냄).
 *     포인터 이벤트 + 고정 위치 유령. 유령은 `pointer-events:none` 이라야
 *     `elementFromPoint` 가 **유령 밑**의 받는 쪽을 돌려준다.
 *  ⚠️ 끌 거리(payload)는 `arm()` 순간 **값으로 복사**한다. 끄는 도중 원본 창이 서버 응답에
 *     다시 그려져 원본 노드가 사라져도 끌기는 산다.
 *  ⚠️ `pointerdown` 에서 기본 동작을 막지 않는다 - 막으면 카드 클릭(선택)이 죽는다.
 *     문턱을 넘은 뒤의 `pointermove` 에서만 막는다. 대신 이미지 네이티브 끌기는
 *     `dragstart` 에서 막는다(안 막으면 브라우저가 pointercancel 을 쏘고 끌기를 가져간다).
 *  ⚠️ 끌고 난 뒤 따라오는 click 한 번은 **문서 캡처 단계에서 한 번만** 삼킨다.
 */

const SLOP = 4;
const brokers = new WeakMap();

/** 문서마다 하나. 리모컨·격자·그룹 창이 같은 중개자를 본다. */
export function dragBrokerFor(doc = document, win = (typeof window !== 'undefined' ? window : null)) {
  let broker = brokers.get(doc);
  if (!broker) {
    broker = createDragBroker(doc, win);
    brokers.set(doc, broker);
  }
  return broker;
}

function copyPayload(payload) {
  try { return JSON.parse(JSON.stringify(payload ?? null)); } catch { return {...payload}; }
}

function createDragBroker(doc, win) {
  const zones = new WeakMap();
  const listeners = new Set();
  let pending = null;   // {payload, x, y, pointerId, opts}
  let active = null;    // {payload, ghost, zoneEl, opts}
  let swallowClick = false;

  function escHtml(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function emit(state) {
    for (const fn of [...listeners]) {
      try { fn(state, active?.payload || null); } catch (error) { console.error('drag broker listener failed', error); }
    }
  }

  /** 받는 쪽 등록. `accept(payload, point)` 가 참을 돌려주면 받은 것이다. */
  function registerZone(el, spec) {
    if (!el) return () => {};
    el.setAttribute('data-drop-zone', spec?.kind || 'artist');
    zones.set(el, spec || {});
    return () => {
      zones.delete(el);
      el.removeAttribute('data-drop-zone');
      el.classList.remove('is-drop-hover');
    };
  }

  function zoneAt(x, y) {
    const hit = doc.elementFromPoint(x, y);
    let el = hit?.closest?.('[data-drop-zone]') || null;
    // 겹친 받는 쪽 가운데 **등록된 것**을 찾을 때까지 올라간다.
    while (el && !zones.has(el)) el = el.parentElement?.closest?.('[data-drop-zone]') || null;
    if (!el) return null;
    const spec = zones.get(el);
    if (spec.canAccept && !spec.canAccept(active?.payload)) return null;
    return {el, spec};
  }

  function makeGhost(payload) {
    const ghost = doc.createElement('div');
    ghost.className = 'drag-ghost';
    const img = payload?.image
      ? `<img src="${escHtml(payload.image)}" alt="" draggable="false">`
      : '<span class="drag-ghost-noimg"></span>';
    ghost.innerHTML = `${img}<span class="drag-ghost-name">${escHtml(payload?.label || payload?.artist || '')}</span>`;
    doc.body.appendChild(ghost);
    return ghost;
  }

  function moveGhost(x, y) {
    if (active?.ghost) active.ghost.style.transform = `translate(${Math.round(x + 12)}px, ${Math.round(y + 10)}px)`;
  }

  function setHover(zoneEl) {
    if (active.zoneEl === zoneEl) return;
    active.zoneEl?.classList.remove('is-drop-hover');
    zoneEl?.classList.add('is-drop-hover');
    active.zoneEl = zoneEl;
  }

  function start(x, y) {
    active = {payload: pending.payload, opts: pending.opts, ghost: makeGhost(pending.payload), zoneEl: null};
    pending = null;
    doc.documentElement.classList.add('is-drag-brokering');
    moveGhost(x, y);
    try { active.opts.onStart?.(); } catch (error) { console.error(error); }
    emit('start');
  }

  /** 끝. `dropped` = 받는 쪽이 받았다. `cancelled` = 사용자가 **물렸다**(Esc·취소).
   *
   *  ⚠️ 둘을 하나로 두면 안 된다. '아무 데도 안 놓았다' 를 제거로 읽는 받는 쪽이
   *     있는데(가로 띠), 거기서는 Esc 가 곧 삭제가 된다 - 되돌릴 수 없는 조작이다.
   */
  function finish(dropped, {cancelled = false} = {}) {
    if (!active) return;
    active.zoneEl?.classList.remove('is-drop-hover');
    active.ghost?.remove();
    doc.documentElement.classList.remove('is-drag-brokering');
    const opts = active.opts;
    active = null;
    try { opts.onEnd?.(dropped, {cancelled}); } catch (error) { console.error(error); }
    emit('end');
  }

  /** 원본의 pointerdown 에서 부른다. 문턱을 넘기 전까지는 아무 일도 안 한다. */
  function arm(event, payload, opts = {}) {
    if (active || event.button !== 0) return;
    pending = {
      payload: copyPayload(payload),
      x: event.clientX, y: event.clientY,
      pointerId: event.pointerId,
      opts,
    };
  }

  /** 이미 끌고 있던 것을 넘겨받는다(믹스 큐 블럭이 목록 밖으로 나갈 때). */
  function takeOver(event, payload, opts = {}) {
    if (active) return false;
    pending = {payload: copyPayload(payload), x: event.clientX, y: event.clientY,
               pointerId: event.pointerId, opts};
    start(event.clientX, event.clientY);
    const zone = zoneAt(event.clientX, event.clientY);
    setHover(zone?.el || null);
    return true;
  }

  doc.addEventListener('pointermove', event => {
    if (pending && !active) {
      if (event.pointerId !== pending.pointerId) return;
      if (Math.hypot(event.clientX - pending.x, event.clientY - pending.y) < SLOP) return;
      start(event.clientX, event.clientY);
    }
    if (!active) return;
    event.preventDefault();
    moveGhost(event.clientX, event.clientY);
    const zone = zoneAt(event.clientX, event.clientY);
    setHover(zone?.el || null);
    try { zone?.spec.hover?.(active.payload, {x: event.clientX, y: event.clientY}); } catch { /* 강조만 */ }
  }, true);

  doc.addEventListener('pointerup', event => {
    if (pending && !active) { pending = null; return; }
    if (!active) return;
    const zone = zoneAt(event.clientX, event.clientY);
    let dropped = false;
    if (zone) {
      try {
        dropped = zone.spec.accept?.(active.payload, {x: event.clientX, y: event.clientY}) !== false;
      } catch (error) {
        console.error('drop zone accept failed', error);
      }
    }
    // 뒤따라오는 click 한 번을 삼킨다. click 이 안 올 수도 있어서(다른 요소 위에서 놓음)
    // 빗장은 **다음 pointerdown** 에서도 푼다 - 타이머에 기대면 순서가 브라우저 마음이다.
    swallowClick = true;
    finish(dropped);
  }, true);

  doc.addEventListener('pointerdown', () => { swallowClick = false; }, true);

  // 브라우저가 끌기를 가져갔다(네이티브 끌기·손가락 이탈 등). 사용자의 뜻이 아니다.
  doc.addEventListener('pointercancel', () => {
    pending = null;
    finish(false, {cancelled: true});
  }, true);

  doc.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (pending) pending = null;
    if (active) { event.preventDefault(); finish(false, {cancelled: true}); }
  }, true);

  doc.addEventListener('click', event => {
    if (!swallowClick) return;
    swallowClick = false;
    event.preventDefault();
    event.stopPropagation();
  }, true);

  // 이미지·링크 네이티브 끌기는 막는다 - 브라우저가 가져가면 pointercancel 이 와서 끝난다.
  doc.addEventListener('dragstart', event => {
    if (pending || active) event.preventDefault();
  }, true);

  return {
    arm,
    takeOver,
    registerZone,
    isDragging: () => Boolean(active),
    payload: () => active?.payload || null,
    cancel: () => { pending = null; finish(false, {cancelled: true}); },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
