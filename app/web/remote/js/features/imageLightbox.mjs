/**
 * 검은 배경 크게 보기 - 그림 목록 하나를 받아 한 장씩 본다(사용자 지시 2026-10-22: 세션 와일드카드 히스토리 창).
 *
 * 손버릇은 옛 히스토리 브라우저 팝업(11-23 제거 · History 창으로 합침)에서 이어받았다:
 *   휠 = 장 넘김 · Ctrl/Cmd/Alt + 휠 = 확대(커서 자리 기준) · 확대해서 넘칠 때만 끌어 옮김 · 더블클릭 = 맞춤 <-> 원본
 *   ← → Space = 한 장 · ↑ ↓ = 한 줄(부른 쪽 격자의 열 수) · Home/End · 0 = 맞춤 · 1 = 원본 · + - = 확대/축소 · F = 전체 화면 · Esc = 닫기
 * 히스토리 팝업은 서버 히스토리 쪽수 읽기에 묶여 있어 그대로 빌려 쓰지 못했다 - 목록을 받는 판으로 따로 뺐다.
 * ⚠️ 무대에 `vp-stage` 클래스를 같이 단다 - Electron preload 가 Ctrl+휠을 창 배율로 가져가는데 그 이름만 비켜 준다(preload.cjs).
 * ⚠️ 열린 동안 키는 **전부 여기서 끝난다**(window 캡처) - 뒤의 히스토리 Delete · Ctrl+Enter 생성 같은 단축키로 새지 않게(Codex 리뷰).
 *    부른 쪽이 쓸 키(Del · Ctrl+S · 바인딩)는 options.onKey 로 **먼저** 묻는다 - true 를 돌려주면 그 키는 거기서 끝난다.
 * (11-22) 히스토리 브라우저 팝업을 없애며 그 뷰어의 나머지도 여기로 왔다: 아래 막대(위치 슬라이더 · n / 전체 · 확대 % · 맞춤) ·
 *   끝에서 한 번 멈춤(옛 뷰어의 _edge_pending - 관성으로 처음으로 튀어 자리를 잃지 않게) · 이어 받기(loadMore) ·
 *   프롬프트 판(P) · 이번에 펼쳐 본 장수. 옵션 없이 부르면(세션 와일드카드 히스토리 창) 예전 그대로다.
 */

const ZOOM_STEP = 1.15;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 8;
const WHEEL_THRESHOLD = 60;      // 히스토리 팝업과 같다 - 트랙패드 한 번에 여러 장 넘어가지 않게

// 단독 화면(output-search.html)은 style.css 를 싣지 않는다 - 바탕 규칙도 함께 넣는다(앱에서는 같은 값이 겹칠 뿐이다).
const STYLE_ID = 'ilb-style-20261122';
const STYLE = `
.ilb{position:fixed;inset:0;z-index:2147483000;background:rgba(0,0,0,.94);outline:none}
.ilb[hidden]{display:none}
.ilb-bar{position:absolute;left:0;right:0;top:0;z-index:2;display:flex;align-items:center;gap:10px;padding:10px 14px;
  font-size:11.5px;color:#ddd;background:linear-gradient(rgba(0,0,0,.55),transparent)}
.ilb-sp{flex:1}
.ilb-count{margin-left:10px;color:#999}
.ilb-hint{color:#888;font-size:10.5px}
.ilb-btn{padding:3px 10px;border-radius:5px;cursor:pointer;border:1px solid rgba(255,255,255,.25);background:transparent;color:#eee;font-size:11px}
.ilb-btn.on{background:rgba(124,106,239,.3);border-color:rgba(157,139,255,.7)}
.ilb-stage{position:absolute;inset:0;overflow:hidden;cursor:default}
.ilb-stage.is-panning{cursor:grabbing}
.ilb.has-foot .ilb-stage{bottom:44px}
.ilb-img{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);transform-origin:center;user-select:none}
.ilb-img:not([style]){opacity:0}
.ilb-nav{position:absolute;top:50%;z-index:2;transform:translateY(-50%);width:44px;height:64px;border:0;border-radius:8px;
  background:rgba(255,255,255,.06);color:#ccc;font-size:28px;cursor:pointer}
.ilb-nav:hover{background:rgba(255,255,255,.14)}
.ilb-nav.is-prev{left:12px}
.ilb-nav.is-next{right:12px}
.ilb-nav[hidden]{display:none}
.ilb-foot{position:absolute;left:0;right:0;bottom:0;height:44px;z-index:2;display:flex;align-items:center;gap:8px;padding:0 14px;
  font-size:11.5px;color:#ddd;background:rgba(0,0,0,.6);border-top:1px solid rgba(255,255,255,.08)}
.ilb-foot[hidden]{display:none}
.ilb-slider{flex:0 1 260px;min-width:80px}
.ilb-pos,.ilb-zoom{min-width:64px;text-align:center;color:#bbb;font-variant-numeric:tabular-nums}
.ilb-seen{color:#888}
.ilb-flash{position:absolute;left:50%;top:56px;z-index:3;transform:translateX(-50%);padding:6px 12px;border-radius:6px;
  background:rgba(20,20,30,.92);border:1px solid rgba(255,255,255,.18);color:#eee;font-size:12px;pointer-events:none}
.ilb-flash[hidden]{display:none}
.ilb-prompt{position:absolute;left:14px;right:14px;bottom:52px;z-index:2;max-height:32%;overflow:auto;padding:8px 10px;border-radius:6px;
  background:rgba(10,10,16,.88);border:1px solid rgba(255,255,255,.12);color:#ddd;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.ilb-prompt[hidden]{display:none}
`;

function injectStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const node = doc.createElement('style');
  node.id = STYLE_ID;
  node.textContent = STYLE;
  doc.head.appendChild(node);
}

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
  let opts = {};
  let edgePending = '';          // '' | 'first' | 'last' - 끝에서 한 번은 막고 알린다
  let loadingMore = false;
  let promptOn = false;
  let flashTimer = 0;
  const seen = new Set();        // 이번에 연 동안 펼쳐 본 그림(item.key) - 닫으면 다시 센다

  function ensure() {
    if (root) return root;
    injectStyle(doc);
    root = doc.createElement('div');
    root.className = 'ilb';
    root.hidden = true;
    root.tabIndex = -1;
    root.innerHTML = `<div class="ilb-bar"><span class="ilb-label" data-ilb-label></span><span class="ilb-sp"></span>`
      + `<span class="ilb-hint">휠 · ← → 넘김 · Ctrl+휠 확대 · 0 맞춤 · 1 원본 · F 전체 화면</span>`
      + `<button type="button" class="ilb-btn" data-ilb-close>닫기</button></div>`
      + `<div class="ilb-stage vp-stage" data-ilb-stage><img class="ilb-img" data-ilb-img alt="" draggable="false"></div>`
      + `<button type="button" class="ilb-nav is-prev" data-ilb-prev aria-label="이전">‹</button>`
      + `<button type="button" class="ilb-nav is-next" data-ilb-next aria-label="다음">›</button>`
      + `<div class="ilb-flash" data-ilb-flash hidden></div>`
      + `<div class="ilb-prompt" data-ilb-prompt hidden></div>`
      + `<div class="ilb-foot" data-ilb-foot hidden>`
      + `<input type="range" class="ilb-slider" data-ilb-slider min="1" max="1" value="1" step="1" aria-label="위치">`
      + `<span class="ilb-pos" data-ilb-pos></span><span class="ilb-seen" data-ilb-seen title="이번에 펼쳐 본 장수"></span>`
      + `<span class="ilb-sp"></span>`
      + `<button type="button" class="ilb-btn" data-ilb-ptoggle title="프롬프트 (P)">프롬프트</button>`
      + `<button type="button" class="ilb-btn" data-ilb-zout title="축소 (-)">−</button>`
      + `<span class="ilb-zoom" data-ilb-zoom></span>`
      + `<button type="button" class="ilb-btn" data-ilb-zin title="확대 (+)">+</button>`
      + `<button type="button" class="ilb-btn" data-ilb-fit title="맞춤 0 / 원본 1">맞춤</button></div>`;
    doc.body.appendChild(root);
    const stage = root.querySelector('[data-ilb-stage]');
    const img = root.querySelector('[data-ilb-img]');
    img.addEventListener('load', () => { natW = img.naturalWidth; natH = img.naturalHeight; fit(); });
    root.addEventListener('click', event => {
      if (event.target.closest('[data-ilb-close]')) { close(); return; }
      if (event.target.closest('[data-ilb-prev]')) { step(-1); return; }
      if (event.target.closest('[data-ilb-next]')) { step(1); return; }
      if (event.target.closest('[data-ilb-zin]')) { zoomStep(1); return; }
      if (event.target.closest('[data-ilb-zout]')) { zoomStep(-1); return; }
      if (event.target.closest('[data-ilb-fit]')) { if (fitMode) { tx = 0; ty = 0; setZoom(1); } else fit(); return; }
      if (event.target.closest('[data-ilb-ptoggle]')) { togglePrompt(); return; }
      if (event.target.closest('[data-ilb-foot]')) return;
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
    const slider = root.querySelector('[data-ilb-slider]');
    slider.addEventListener('input', () => { edgePending = ''; seek(Number(slider.value) - 1); });
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
    // 그림 끝을 무대 안으로 들이지 않는다(옛 히스토리 팝업에서 이어받음) - 끌어서 빈 화면을 만들 수 없게.
    const range = panRange();
    tx = Math.min(range.x, Math.max(-range.x, tx));
    ty = Math.min(range.y, Math.max(-range.y, ty));
    img.style.width = `${natW}px`;
    img.style.height = `${natH}px`;
    img.style.transform = `translate(-50%, -50%) translate(${tx}px, ${ty}px) scale(${zoom})`;
    const label = root.querySelector('[data-ilb-zoom]');
    if (label) label.textContent = `${Math.round(zoom * 100)}%`;
    const fitBtn = root.querySelector('[data-ilb-fit]');
    if (fitBtn) fitBtn.textContent = fitMode ? '맞춤' : '원본';
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
    // 결과 우클릭 메뉴가 이 그림을 히스토리 항목으로 알아보게 한다(경로를 준 호출자만).
    if (item.path) img.dataset.path = item.path; else delete img.dataset.path;
    const total = totalCount();
    root.querySelector('[data-ilb-label]').innerHTML = `${escHtml(item.label || '')}`
      + `<span class="ilb-count">${index + 1} / ${total}</span>`;
    root.querySelector('[data-ilb-prev]').hidden = total < 2;
    root.querySelector('[data-ilb-next]').hidden = total < 2;
    if (item.key != null) seen.add(item.key);
    const slider = root.querySelector('[data-ilb-slider]');
    slider.max = String(Math.max(1, total));
    slider.value = String(index + 1);
    root.querySelector('[data-ilb-pos]').textContent = `${index + 1} / ${total}`;
    root.querySelector('[data-ilb-seen]').textContent = seen.size > 1 ? `본 장 ${seen.size}` : '';
    drawPrompt();
    try { opts.onIndex?.(index, item); } catch (_) { /* 부른 쪽 실수로 보기가 멈추지 않게 */ }
  }
  function totalCount() {
    const total = Number(typeof opts.total === 'function' ? opts.total() : 0);
    return Math.max(items.length, Number.isFinite(total) ? total : 0);
  }
  function flash(message) {
    const node = root.querySelector('[data-ilb-flash]');
    node.textContent = message;
    node.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { node.hidden = true; }, 1600);
  }
  // 아직 안 받은 뒷장이 있으면 받아 온 뒤에 간다. 받는 동안 누른 키는 버린다(한 번에 여러 장 튀지 않게).
  async function ensureLoaded(target) {
    if (target < items.length || typeof opts.loadMore !== 'function' || loadingMore) return target < items.length;
    loadingMore = true;
    try {
      while (target >= items.length && items.length < totalCount()) {
        const before = items.length;
        await opts.loadMore();
        if (items.length <= before) break;
      }
    } catch (_) { /* 못 받으면 받은 데까지 */ }
    finally { loadingMore = false; }
    return target < items.length;
  }
  async function seek(next) {
    if (!items.length) return;
    const want = Math.max(0, Math.min(totalCount() - 1, next));
    if (!(await ensureLoaded(want))) { index = items.length - 1; show(); return; }
    index = want;
    show();
  }
  function step(delta) {
    if (!items.length) return;
    const total = totalCount();
    const next = index + delta;
    if (next >= 0 && next < total) { edgePending = ''; seek(next); return; }
    // 줄 단위(↑ ↓)는 끝에 붙인다 - 덜 찬 마지막 줄에서 손이 막히지 않게. 되감기는 좌우(±1) 전용.
    if (Math.abs(delta) > 1) { seek(delta > 0 ? total - 1 : 0); return; }
    // 진짜 끝 - 옛 뷰어처럼 **한 번은 막고 알린다.**
    const edge = delta > 0 ? 'last' : 'first';
    if (edgePending !== edge) {
      edgePending = edge;
      flash(edge === 'last' ? '마지막 그림입니다. 한 번 더 누르면 처음으로.' : '첫 그림입니다. 한 번 더 누르면 마지막으로.');
      return;
    }
    edgePending = '';
    seek(edge === 'last' ? 0 : total - 1);
  }
  function drawPrompt() {
    const node = root.querySelector('[data-ilb-prompt]');
    const text = items[index]?.prompt || '';
    node.hidden = !promptOn || !text;
    node.textContent = text;
    root.querySelector('[data-ilb-ptoggle]').classList.toggle('on', promptOn);
  }
  function togglePrompt() { promptOn = !promptOn; drawPrompt(); }
  function wheelStep(deltaY) {
    if (Math.sign(deltaY) !== Math.sign(wheelAccum)) wheelAccum = 0;
    wheelAccum += deltaY;
    if (Math.abs(wheelAccum) < WHEEL_THRESHOLD) return;
    const direction = wheelAccum < 0 ? -1 : 1;
    wheelAccum = 0;
    step(direction);
  }

  // 큰 보기 위에 뜬 확인 창(모달)이 있으면 키는 그 창의 것이다 - Esc · 방향키 · Enter 를 가로채지 않는다.
  function modalAbove() {
    for (const node of doc.querySelectorAll('[role="dialog"][aria-modal="true"]')) {
      if (!root.contains(node) && node.getClientRects().length) return true;
    }
    return false;
  }

  function onKey(event) {
    if (!root || root.hidden) return;
    if (modalAbove()) return;
    // 열린 동안 어떤 키도 뒤로 넘기지 않는다(조합 중 입력 · 브라우저 기본 동작은 그대로 - 막는 것은 앱의 단축키 전달).
    event.stopImmediatePropagation();
    if (event.key === 'Tab') { event.preventDefault(); return; }       // 초점이 뒤 화면으로 나가지 않게
    const key = String(event.key || '').toLowerCase();
    const handled = () => { event.preventDefault(); event.stopPropagation(); };
    if (typeof opts.onKey === 'function') {
      let taken = false;
      try { taken = opts.onKey(event, items[index], index) === true; } catch (_) { taken = false; }
      if (taken) { handled(); return; }
    }
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
    else if (key === 'p') { handled(); togglePrompt(); }
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
    const onClose = opts.onClose;
    opts = {};
    try { onClose?.(index); } catch (_) { /* 닫기는 늘 끝난다 */ }
  }

  return {
    /** items = [{full, thumb, label, key?, prompt?}] · options:
     *    rowStep = () => 격자 한 줄의 장 수(↑ ↓) · footer = 아래 막대 · zIndex = 겹침(확인 창 아래에 두려면)
     *    total = () => 전체 장수(아직 안 받은 것 포함) · loadMore = async () => 부른 쪽이 더 받고 setItems 로 넘긴다
     *    onKey = (event, item, index) => true 면 그 키는 부른 쪽 몫 · onIndex = (index, item) · onClose = (index)
     */
    open(nextItems, startIndex = 0, options = {}) {
      ensure();
      items = Array.isArray(nextItems) ? nextItems : [];
      rowStep = typeof options.rowStep === 'function' ? options.rowStep : () => 1;
      if (!items.length) return;
      opts = options || {};
      root.style.zIndex = opts.zIndex ? String(opts.zIndex) : '';
      root.classList.toggle('has-foot', Boolean(opts.footer));
      root.querySelector('[data-ilb-foot]').hidden = !opts.footer;
      seen.clear();
      edgePending = '';
      root.hidden = false;
      wheelAccum = 0;
      seek(startIndex);
      window.removeEventListener('keydown', onKey, true);
      window.addEventListener('keydown', onKey, true);
      root.focus();
    },
    close,
    isOpen: () => !!(root && !root.hidden),
    /** 부른 쪽 목록이 바뀌었다(더 받음 · 지움). keep = 지금 보던 그림의 key - 남아 있으면 그 자리, 없으면 같은 번호. */
    setItems(nextItems, keep = undefined) {
      if (!root || root.hidden) return;
      items = Array.isArray(nextItems) ? nextItems : [];
      if (!items.length) { close(); return; }
      const at = keep === undefined ? -1 : items.findIndex(item => item.key === keep);
      const was = index;
      index = at >= 0 ? at : Math.min(index, items.length - 1);
      if (at >= 0 && at === was && keep !== undefined) {
        // 같은 그림 - 그림을 다시 싣지 않고 숫자만 고친다(확대 상태를 지킨다).
        const total = totalCount();
        root.querySelector('[data-ilb-pos]').textContent = `${index + 1} / ${total}`;
        const slider = root.querySelector('[data-ilb-slider]');
        slider.max = String(Math.max(1, total));
        slider.value = String(index + 1);
        return;
      }
      show();
    },
    current: () => index,
    /** 지금 보고 있는 항목(부른 쪽 목록이 바뀌었을 때 번호가 아니라 이것으로 찾는다). */
    currentItem: () => (root && !root.hidden ? items[index] || null : null),
  };
}
