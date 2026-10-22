/**
 * 검은 배경 크게 보기 - 그림 목록 하나를 받아 한 장씩 본다(사용자 지시 2026-10-22: 세션 와일드카드 히스토리 창).
 *
 * 손버릇은 히스토리 브라우저 팝업(`resultHistory.mjs` 의 vp* · bindPopupViewer)과 **같다** - 그쪽을 고치면 여기도 맞춰라:
 *   휠 = 장 넘김 · Ctrl/Cmd/Alt + 휠 = 확대(커서 자리 기준) · 확대해서 넘칠 때만 끌어 옮김 · 더블클릭 = 맞춤 <-> 원본
 *   ← → Space = 한 장 · ↑ ↓ = 한 줄(부른 쪽 격자의 열 수) · Home/End · 0 = 맞춤 · 1 = 원본 · + - = 확대/축소 · F = 전체 화면 · Esc = 닫기
 * 히스토리 팝업은 서버 히스토리 쪽수 읽기에 묶여 있어 그대로 빌려 쓰지 못했다 - 목록을 받는 판으로 따로 뺐다.
 * ⚠️ 무대에 `vp-stage` 클래스를 같이 단다 - Electron preload 가 Ctrl+휠을 창 배율로 가져가는데 그 이름만 비켜 준다(preload.cjs).
 * ⚠️ 열린 동안 키는 **전부 여기서 끝난다**(window 캡처) - 뒤의 히스토리 Delete · Ctrl+Enter 생성 같은 단축키로 새지 않게(Codex 리뷰).
 */

const ZOOM_STEP = 1.15;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 8;
const WHEEL_THRESHOLD = 60;      // 히스토리 팝업과 같다 - 트랙패드 한 번에 여러 장 넘어가지 않게

export function createImageLightbox({document: doc = document, escHtml = v => String(v ?? '')} = {}) {
  let root = null;
  let items = [];
  let index = 0;
  let rowStep = () => 1;
  let zoom = 1;
  let fitZoom = 1;
  let fitMode = true;
  let tx = 0;
  let ty = 0;
  let pan = null;
  let natW = 0;
  let natH = 0;
  let wheelAccum = 0;
  let dragged = false;           // 방금 끌었다 - 그 뒤 따라오는 click 은 '바탕 누름(닫기)' 이 아니다

  function ensure() {
    if (root) return root;
    root = doc.createElement('div');
    root.className = 'ilb';
    root.hidden = true;
    root.tabIndex = -1;
    root.innerHTML = `<div class="ilb-bar"><span class="ilb-label" data-ilb-label></span><span class="ilb-sp"></span>`
      + `<span class="ilb-hint">휠 · ← → 넘김 · Ctrl+휠 확대 · 0 맞춤 · 1 원본 · F 전체 화면</span>`
      + `<button type="button" class="ilb-btn" data-ilb-close>닫기</button></div>`
      + `<div class="ilb-stage vp-stage" data-ilb-stage><img class="ilb-img" data-ilb-img alt="" draggable="false"></div>`
      + `<button type="button" class="ilb-nav is-prev" data-ilb-prev aria-label="이전">‹</button>`
      + `<button type="button" class="ilb-nav is-next" data-ilb-next aria-label="다음">›</button>`;
    doc.body.appendChild(root);
    const stage = root.querySelector('[data-ilb-stage]');
    const img = root.querySelector('[data-ilb-img]');
    img.addEventListener('load', () => { natW = img.naturalWidth; natH = img.naturalHeight; fit(); });
    root.addEventListener('click', event => {
      if (event.target.closest('[data-ilb-close]')) { close(); return; }
      if (event.target.closest('[data-ilb-prev]')) { step(-1); return; }
      if (event.target.closest('[data-ilb-next]')) { step(1); return; }
      // 그림 밖(검은 바탕)을 누르면 닫는다 - 히스토리 라이트박스와 같다.
      // ⚠️ 확대해서 끈 뒤의 click 은 포인터 캡처 때문에 무대로 온다 - 그건 닫기가 아니다(Codex 리뷰).
      if (dragged) { dragged = false; return; }
      if (event.target === stage) close();
    });
    stage.addEventListener('wheel', event => {
      if (!event.deltaY) return;
      event.preventDefault();
      if (event.ctrlKey || event.metaKey || event.altKey || pan) zoomStep(event.deltaY < 0 ? 1 : -1, event);
      else wheelStep(event.deltaY);
    }, {passive: false});
    stage.addEventListener('dblclick', () => (fitMode ? setZoom(1) : fit()));
    stage.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !canPan()) return;
      pan = {x: event.clientX, y: event.clientY, tx, ty};
      dragged = false;
      stage.setPointerCapture?.(event.pointerId);
      stage.classList.add('is-panning');
    });
    stage.addEventListener('pointermove', event => {
      if (!pan) return;
      if (Math.abs(event.clientX - pan.x) + Math.abs(event.clientY - pan.y) > 3) dragged = true;
      tx = pan.tx + (event.clientX - pan.x);
      ty = pan.ty + (event.clientY - pan.y);
      apply();
    });
    const endPan = () => { pan = null; stage.classList.remove('is-panning'); };
    stage.addEventListener('pointerup', endPan);
    stage.addEventListener('pointercancel', endPan);
    return root;
  }

  function stageRect() { return root.querySelector('[data-ilb-stage]').getBoundingClientRect(); }
  function panRange() {
    const rect = stageRect();
    return {x: Math.max(0, (natW * zoom - rect.width) / 2), y: Math.max(0, (natH * zoom - rect.height) / 2)};
  }
  function canPan() { const r = panRange(); return r.x > 0.5 || r.y > 0.5; }
  function apply() {
    const img = root.querySelector('[data-ilb-img]');
    // 그림 끝을 무대 안으로 들이지 않는다(히스토리 팝업 vpApplyTransform 과 같다) - 끌어서 빈 화면을 만들 수 없게.
    const range = panRange();
    tx = Math.min(range.x, Math.max(-range.x, tx));
    ty = Math.min(range.y, Math.max(-range.y, ty));
    img.style.width = `${natW}px`;
    img.style.height = `${natH}px`;
    img.style.transform = `translate(-50%, -50%) translate(${tx}px, ${ty}px) scale(${zoom})`;
  }
  function fit() {
    if (!natW || !natH) return;
    const rect = stageRect();
    fitZoom = Math.min(rect.width / natW, rect.height / natH, 1);
    zoom = fitZoom;
    fitMode = true;
    tx = 0;
    ty = 0;
    apply();
  }
  function setZoom(next, anchor = null) {
    const clamped = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, next));
    if (anchor) {
      // 커서 자리를 고정점으로 - 그 자리의 그림 점이 커서 밑에 남는다.
      const rect = stageRect();
      const ax = anchor.clientX - (rect.left + rect.width / 2) - tx;
      const ay = anchor.clientY - (rect.top + rect.height / 2) - ty;
      tx -= ax * (clamped / zoom - 1);
      ty -= ay * (clamped / zoom - 1);
    }
    zoom = clamped;
    fitMode = Math.abs(zoom - fitZoom) < 1e-6;
    if (!canPan()) { tx = 0; ty = 0; }
    apply();
  }
  function zoomStep(dir, anchor = null) { setZoom(zoom * (dir > 0 ? ZOOM_STEP : 1 / ZOOM_STEP), anchor); }

  function show() {
    const item = items[index];
    if (!item) return;
    const img = root.querySelector('[data-ilb-img]');
    natW = 0;
    natH = 0;
    img.removeAttribute('style');
    img.src = item.full || item.thumb || '';
    root.querySelector('[data-ilb-label]').innerHTML = `${escHtml(item.label || '')}`
      + `<span class="ilb-count">${index + 1} / ${items.length}</span>`;
    root.querySelector('[data-ilb-prev]').hidden = items.length < 2;
    root.querySelector('[data-ilb-next]').hidden = items.length < 2;
  }
  function seek(next) {
    if (!items.length) return;
    index = Math.max(0, Math.min(items.length - 1, next));
    show();
  }
  function step(delta) { seek(index + delta); }
  function wheelStep(deltaY) {
    if (Math.sign(deltaY) !== Math.sign(wheelAccum)) wheelAccum = 0;
    wheelAccum += deltaY;
    if (Math.abs(wheelAccum) < WHEEL_THRESHOLD) return;
    const direction = wheelAccum < 0 ? -1 : 1;
    wheelAccum = 0;
    step(direction);
  }

  function onKey(event) {
    if (!root || root.hidden) return;
    // 열린 동안 어떤 키도 뒤로 넘기지 않는다(조합 중 입력 · 브라우저 기본 동작은 그대로 - 막는 것은 앱의 단축키 전달).
    event.stopImmediatePropagation();
    if (event.key === 'Tab') { event.preventDefault(); return; }       // 초점이 뒤 화면으로 나가지 않게
    const key = String(event.key || '').toLowerCase();
    const handled = () => { event.preventDefault(); event.stopPropagation(); };
    if (event.key === 'ArrowLeft') { handled(); step(-1); }
    else if (event.key === 'ArrowRight' || event.key === ' ' || event.key === 'Spacebar') { handled(); step(1); }
    else if (event.key === 'ArrowUp') { handled(); step(-Math.max(1, rowStep())); }
    else if (event.key === 'ArrowDown') { handled(); step(Math.max(1, rowStep())); }
    else if (event.key === 'Home') { handled(); seek(0); }
    else if (event.key === 'End') { handled(); seek(items.length - 1); }
    else if (key === '0') { handled(); fit(); }
    else if (key === '1') { handled(); tx = 0; ty = 0; setZoom(1); }
    else if (key === '+' || key === '=') { handled(); zoomStep(1); }
    else if (key === '-' || key === '_') { handled(); zoomStep(-1); }
    else if (key === 'f' || event.key === 'F11') {
      handled();
      if (doc.fullscreenElement) doc.exitFullscreen?.(); else root.requestFullscreen?.().catch(() => {});
    } else if (event.key === 'Escape') {
      handled();
      if (doc.fullscreenElement) doc.exitFullscreen?.(); else close();
    }
  }

  function close() {
    if (!root || root.hidden) return;
    if (doc.fullscreenElement === root) doc.exitFullscreen?.();
    root.hidden = true;
    root.querySelector('[data-ilb-img]').removeAttribute('src');
    window.removeEventListener('keydown', onKey, true);
  }

  return {
    /** items = [{full, thumb, label}] · options.rowStep = () => 격자 한 줄의 장 수(↑ ↓). */
    open(nextItems, startIndex = 0, options = {}) {
      ensure();
      items = Array.isArray(nextItems) ? nextItems : [];
      rowStep = typeof options.rowStep === 'function' ? options.rowStep : () => 1;
      if (!items.length) return;
      root.hidden = false;
      wheelAccum = 0;
      seek(startIndex);
      window.removeEventListener('keydown', onKey, true);
      window.addEventListener('keydown', onKey, true);
      root.focus();
    },
    close,
    isOpen: () => !!(root && !root.hidden),
  };
}
