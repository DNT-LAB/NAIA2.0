/** 모바일 전체화면 보기(사용자 지시 2026-10-30).
 *
 *      ┌──────────────────────────[X]┐
 *      │                              │
 *      │     지금 보고 있는 그림       │
 *      │     (#preview 를 비춘다)      │
 *      │                  ┌────────┐ │
 *      │                  │  ━━━   │ │  <- 손잡이를 끌어 옮긴다(자리는 기억)
 *      │                  │ [랜덤] │ │
 *      │                  │ [생성] │ │
 *      │                  │ [ ]자동│ │
 *      └──────────────────└────────┘─┘
 *
 *  진입 단추는 히스토리 머리줄(#viewerFsBtn)에 있고 좁은 화면(767px 이하)에서만 보인다.
 *
 *  ⚠️ 단추 셋은 **진짜 단추의 거울**이다(사용자 지정). 동작을 따로 짜지 않고 #btnRnd · #btnGen ·
 *     #optAutoGen 을 그대로 누른다 - ST Random · EV Random · SEQ Random · 랜덤 시 생성 · 생성 중 큐 · 인페인트
 *     세션 잠금이 전부 저쪽에 있고, 여기서 다시 짜면 한쪽만 고쳐지는 날이 온다. 글자 · 꺼짐 · 켜짐도 저쪽을
 *     지켜보다(MutationObserver) 그대로 옮겨 쓴다 - 생성 중 경과 초 · 대기 +N 도 같이 따라온다.
 *     꺼진(disabled) 진짜 단추는 .click() 이 아무 일도 안 하므로 거울도 똑같이 죽어 있다.
 *  ⚠️ 그림도 #preview 의 src 를 지켜본다 - 새 그림 · NAI 스트리밍 중간 그림 · 히스토리에서 고른 그림이 모두
 *     그 한 자리로 들어온다.
 */

const STYLE_ID = 'mobileFullscreenStyle';
const POS_KEY = 'naia.mobileFullscreen.fabPos';
const SCALE_KEY = 'naia.mobileFullscreen.fabScale';
const HIDE_AUTO_KEY = 'naia.mobileFullscreen.hideAuto';
const EDGE = 8;   // 단추판이 화면 끝에서 떨어지는 최소 거리
// 단추판 크기(사용자 지시 2026-10-30) - 오른쪽 아래 꺾쇠로 끈다. 이 값보다 작으면 글자가 R / G / A 로 줄고
// A 는 체크 상자 **안에** 겹친다(상자를 더 줄이려고 - 사용자 지정).
const SCALE_MIN = 0.45;
const SCALE_MAX = 1.25;
const COMPACT_BELOW = 0.75;
const BASE_WIDTH = 124;

const CSS = `
.viewer-fs-btn { display: none; }
@media (max-width: 767px) {
  .viewer-fs-btn {
    display: flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; margin-left: auto; padding: 0;
    background: rgba(255,255,255,0.05); border: 1px solid var(--border-dim); border-radius: 5px;
    color: var(--text-dim); cursor: pointer;
  }
  .viewer-fs-btn:hover { background: rgba(255,255,255,0.1); color: var(--text-primary); }
  .viewer-panel.collapsed .viewer-fs-btn { display: none; }
}
.mfs-overlay {
  position: fixed; inset: 0; z-index: 9800;
  display: none; align-items: center; justify-content: center;
  background: #000; touch-action: none;
}
.mfs-overlay.open { display: flex; }
.mfs-image { max-width: 100%; max-height: 100%; width: 100%; height: 100%; object-fit: contain; user-select: none; -webkit-user-drag: none; }
.mfs-image:not([src]), .mfs-image[src=""] { visibility: hidden; }
.mfs-close {
  position: absolute; top: max(10px, env(safe-area-inset-top)); right: 10px;
  width: 40px; height: 40px; border-radius: 50%; padding: 0;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.55); border: 1px solid rgba(255,255,255,0.22);
  color: #fff; font-size: 22px; line-height: 1; cursor: pointer;
}
.mfs-fab {
  --s: 1;
  position: absolute; width: calc(${BASE_WIDTH}px * var(--s));
  /* 아래 16px 은 크기 꺾쇠 자리 - 단추와 겹치면 작은 판의 A 를 누르기 어려웠다(사용자 제보 2026-10-30). */
  padding: max(4px, calc(6px * var(--s))) max(5px, calc(8px * var(--s))) 16px;
  display: flex; flex-direction: column; gap: max(4px, calc(6px * var(--s)));
  background: rgba(20,20,30,0.86); border: 1px solid rgba(255,255,255,0.14); border-radius: 12px;
  user-select: none; touch-action: none;
}
/* 손잡이도 <button> - 아래 꺾쇠와 같은 이유(작은 판에서 바로 아래 R 이 터치를 가져간다). */
.mfs-grip {
  height: max(12px, calc(18px * var(--s))); width: 100%; padding: 0; margin: 0; background: none; border: none;
  display: flex; align-items: center; justify-content: center; cursor: grab; touch-action: none;
}
.mfs-grip::before { content: ''; width: min(30px, 60%); height: 4px; border-radius: 2px; background: rgba(255,255,255,0.32); }
.mfs-fab.dragging .mfs-grip { cursor: grabbing; }
.mfs-resize {
  /* ⚠️ <button> 이어야 한다 - 터치는 브라우저가 가까운 '누를 수 있는' 요소로 옮겨 준다(touch adjustment).
     <div> 였을 때 꺾쇠를 눌러도 바로 위 A 단추가 터치를 가져갔다(실측 2026-10-30). */
  position: absolute; right: -1px; bottom: -1px; width: 28px; height: 16px; padding: 0 3px 3px; margin: 0;
  display: flex; align-items: flex-end; justify-content: flex-end;
  background: none; border: none; cursor: nwse-resize; touch-action: none;
}
.mfs-resize::before {
  content: ''; width: 9px; height: 9px; border-bottom-right-radius: 3px;
  border-right: 2px solid rgba(255,255,255,0.5); border-bottom: 2px solid rgba(255,255,255,0.5);
}
.mfs-btn {
  height: max(30px, calc(40px * var(--s))); padding: 0 4px; border: none; border-radius: 8px;
  color: #fff; font-size: max(13px, calc(13px * var(--s))); font-weight: 600; cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.mfs-short, .mfs-auto-letter { display: none; }
.mfs-fab.compact .mfs-full, .mfs-fab.compact .mfs-auto-label { display: none; }
.mfs-fab.compact .mfs-short { display: inline; }
.mfs-btn.rnd { background: #a0659a; }
.mfs-btn.gen { background: #6a5ad8; }
.mfs-btn.gen.generating { background: #4a3fa0; }
.mfs-btn:disabled { opacity: 0.4; cursor: default; }
.mfs-auto {
  height: max(28px, calc(34px * var(--s))); padding: 0 8px; display: flex; align-items: center; gap: 8px;
  background: transparent; border: 1px solid rgba(255,255,255,0.16); border-radius: 8px;
  color: #ddd; font-size: 13px; cursor: pointer;
}
.mfs-auto-box {
  width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid #aaa; flex: none;
  display: flex; align-items: center; justify-content: center; font-size: 11px; color: #fff;
}
.mfs-auto.on .mfs-auto-box { background: #6a5ad8; border-color: #6a5ad8; }
.mfs-auto.on .mfs-auto-box::after { content: '\\2713'; }
.mfs-auto.pending { opacity: 0.6; }
/* 손가락으로 누른 뒤 남는 흰 초점 테두리는 지운다 - 키보드 초점(:focus-visible)은 그대로 보인다. */
.mfs-overlay button:focus:not(:focus-visible) { outline: none; }
/* 작은 판: 체크 상자 하나가 단추 전체다 - A 를 상자 안에 겹치고, 켜지면 상자가 채워진다(체크 표시 없음).
   상자는 R / G 와 같은 폭 · 높이로 줄을 다 채운다 - 작은 상자는 손가락으로 누르기 어려웠다. */
.mfs-fab.compact .mfs-auto { height: max(30px, calc(40px * var(--s))); justify-content: center; padding: 0; border: none; }
/* 작은 판의 A 는 **투명 단추**다(사용자 지정 2026-10-30) - 꺼지면 흐린 테두리 · 켜지면 연한 흰색으로 찬다.
   보라색으로 채우면 바로 위 G 와 같은 단추로 읽혔다. */
.mfs-fab.compact .mfs-auto-box {
  width: 100%; height: 100%; background: transparent;
  border-radius: 8px; border: 1.5px solid rgba(255,255,255,0.28);
  font-size: 13px; font-weight: 700; color: rgba(255,255,255,0.6);
}
.mfs-fab.compact .mfs-auto-letter { display: inline; }
.mfs-fab.compact .mfs-auto.on .mfs-auto-box {
  background: rgba(255,255,255,0.24); border-color: rgba(255,255,255,0.62); color: #fff;
}
.mfs-fab.compact .mfs-auto.on .mfs-auto-box::after { content: none; }
.mfs-fab.hide-auto .mfs-auto { display: none; }
/* 길게 누르기 - 휴대폰의 복사 · 선택 메뉴가 뜨지 않게 한다. */
.mfs-overlay, .mfs-overlay * { -webkit-touch-callout: none; -webkit-user-select: none; user-select: none; }
.mfs-settings {
  position: absolute; width: 240px; max-width: calc(100% - 16px); padding: 10px;
  display: none; flex-direction: column; gap: 2px;
  background: rgba(24,24,34,0.97); border: 1px solid rgba(255,255,255,0.18); border-radius: 12px;
  color: #ddd; font-size: 13px;
}
.mfs-settings.open { display: flex; }
.mfs-settings-head { display: flex; align-items: center; justify-content: space-between; margin: 0 2px 6px; color: #aaa; font-size: 12px; }
.mfs-settings-x { width: 28px; height: 28px; padding: 0; background: none; border: none; color: #ccc; font-size: 18px; cursor: pointer; }
.mfs-set-row {
  display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 0 8px;
  background: none; border: none; border-radius: 8px; color: #ddd; font-size: 13px; text-align: left; cursor: pointer;
}
.mfs-set-row:active { background: rgba(255,255,255,0.08); }
.mfs-set-row:disabled { opacity: 0.4; cursor: default; }
.mfs-set-row .mfs-auto-box { flex: none; }
.mfs-set-row.on .mfs-auto-box { background: #6a5ad8; border-color: #6a5ad8; }
.mfs-set-row.on .mfs-auto-box::after { content: '\\2713'; }
.mfs-settings-foot { margin: 4px 6px 0; color: #999; font-size: 11px; line-height: 1.5; }
`;

/** 진짜 단추의 보이는 글자 - 단축키 힌트 · Anlas 칩을 뺀 나머지. 칩 글자는 따로 돌려준다. */
function buttonLabel(btn) {
  const clone = btn.cloneNode(true);
  clone.querySelectorAll('.shortcut-hint').forEach(n => n.remove());
  const chip = clone.querySelector('.gen-cost-chip');
  const chipText = chip ? chip.textContent.trim() : '';
  if (chip) chip.remove();
  return {label: clone.textContent.trim(), chip: chipText};
}

export function createMobileFullscreen({document: doc = document, window: win = window} = {}) {
  const preview = doc.getElementById('preview');
  const realRnd = doc.getElementById('btnRnd');
  const realGen = doc.getElementById('btnGen');
  const realAuto = doc.getElementById('optAutoGen');
  const entry = doc.getElementById('viewerFsBtn');
  if (!preview || !realRnd || !realGen || !realAuto) return {open() {}, close() {}, isOpen: () => false};

  if (!doc.getElementById(STYLE_ID)) {
    const tag = doc.createElement('style');
    tag.id = STYLE_ID;
    tag.textContent = CSS;
    doc.head.appendChild(tag);
  }

  const overlay = doc.createElement('div');
  overlay.className = 'mfs-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-label', '전체화면 보기');
  overlay.innerHTML = `
    <img class="mfs-image" alt="">
    <button type="button" class="mfs-close" aria-label="전체화면 닫기">&times;</button>
    <div class="mfs-fab">
      <button type="button" class="mfs-grip" tabindex="-1" aria-label="단추판 옮기기"></button>
      <button type="button" class="mfs-btn rnd"><span class="mfs-full"></span><span class="mfs-short">R</span></button>
      <button type="button" class="mfs-btn gen"><span class="mfs-full"></span><span class="mfs-short">G</span></button>
      <button type="button" class="mfs-auto" aria-pressed="false" aria-label="자동">
        <span class="mfs-auto-box" aria-hidden="true"><span class="mfs-auto-letter">A</span></span><span class="mfs-auto-label">자동</span>
      </button>
      <button type="button" class="mfs-resize" tabindex="-1" aria-label="단추판 크기 조절"></button>
    </div>
    <div class="mfs-settings" role="dialog" aria-label="단추판 설정">
      <div class="mfs-settings-head"><span>단추판 설정</span>
        <button type="button" class="mfs-settings-x" aria-label="설정 닫기">&times;</button></div>
      <button type="button" class="mfs-set-row" data-set="generate_on_random" aria-pressed="false">
        <span class="mfs-auto-box" aria-hidden="true"></span>랜덤을 누를 때 생성</button>
      <button type="button" class="mfs-set-row" data-set="hide_auto" aria-pressed="false">
        <span class="mfs-auto-box" aria-hidden="true"></span>자동(A) 단추 숨기기</button>
      <div class="mfs-settings-foot">랜덤 시 생성은 확장 기능(⚙)의 같은 옵션입니다 · Auto Gen 이 꺼져 있을 때만 작동합니다</div>
    </div>`;
  doc.body.appendChild(overlay);

  const img = overlay.querySelector('.mfs-image');
  const fab = overlay.querySelector('.mfs-fab');
  const grip = overlay.querySelector('.mfs-grip');
  const rnd = overlay.querySelector('.mfs-btn.rnd');
  const gen = overlay.querySelector('.mfs-btn.gen');
  const auto = overlay.querySelector('.mfs-auto');

  // ---- 거울 ----
  function syncImage() {
    const src = preview.getAttribute('src') || '';
    if (img.getAttribute('src') !== src) img.setAttribute('src', src);
  }
  function syncButton(mirror, real) {
    const {label, chip} = buttonLabel(real);
    const text = chip ? `${label} · ${chip}` : label;
    const full = mirror.querySelector('.mfs-full');
    if (full.textContent !== text) full.textContent = text;
    // 작은 판은 R / G 만 보이므로 진짜 글자(EV Random · 경과 초 등)는 aria-label 과 툴팁으로 남긴다.
    mirror.setAttribute('aria-label', text);
    mirror.disabled = real.disabled;
    mirror.title = real.title || text;
    mirror.classList.toggle('generating', real.classList.contains('generating'));
  }
  function syncAuto() {
    const on = realAuto.dataset.checked === 'true';
    auto.classList.toggle('on', on);
    auto.classList.toggle('pending', realAuto.classList.contains('is-pending'));
    auto.setAttribute('aria-pressed', on ? 'true' : 'false');
  }
  function syncAll() {
    syncImage();
    syncButton(rnd, realRnd);
    syncButton(gen, realGen);
    syncAuto();
  }

  // 닫혀 있을 때는 지켜보기를 멈춘다 - 생성 중 경과 초가 매초 단추를 다시 쓰기 때문이다.
  const observers = [];
  function watch() {
    if (observers.length) return;
    const add = (target, fn, opts) => {
      const ob = new MutationObserver(fn);
      ob.observe(target, opts);
      observers.push(ob);
    };
    const btnOpts = {childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ['disabled', 'class', 'title']};
    add(preview, syncImage, {attributes: true, attributeFilter: ['src']});
    add(realRnd, () => syncButton(rnd, realRnd), btnOpts);
    add(realGen, () => syncButton(gen, realGen), btnOpts);
    add(realAuto, syncAuto, {attributes: true, attributeFilter: ['data-checked', 'class']});
  }
  function unwatch() {
    while (observers.length) observers.pop().disconnect();
  }

  rnd.addEventListener('click', () => realRnd.click());
  gen.addEventListener('click', () => realGen.click());
  auto.addEventListener('click', () => realAuto.click());

  // ---- 단추판 끌기 · 자리 기억 ----
  function loadPos() {
    try {
      const raw = JSON.parse(win.localStorage.getItem(POS_KEY) || 'null');
      if (raw && Number.isFinite(raw.x) && Number.isFinite(raw.y)) return raw;
    } catch (_) { /* 저장소가 없거나 깨졌으면 기본 자리 */ }
    return null;
  }
  function savePos(pos) {
    try { win.localStorage.setItem(POS_KEY, JSON.stringify(pos)); } catch (_) { /* 기억만 못 한다 */ }
  }
  // 자리는 화면 비율(0~1)로 기억한다 - 세로 · 가로를 돌려도 같은 구석에 남는다.
  function placeFab(pos) {
    const maxX = Math.max(EDGE, overlay.clientWidth - fab.offsetWidth - EDGE);
    const maxY = Math.max(EDGE, overlay.clientHeight - fab.offsetHeight - EDGE);
    const p = pos || {x: 1, y: 1};   // 기본 = 오른쪽 아래
    const x = Math.min(maxX, Math.max(EDGE, EDGE + p.x * (maxX - EDGE)));
    const y = Math.min(maxY, Math.max(EDGE, EDGE + p.y * (maxY - EDGE)));
    fab.style.left = `${Math.round(x)}px`;
    fab.style.top = `${Math.round(y)}px`;
  }
  function currentRatio() {
    const maxX = Math.max(EDGE, overlay.clientWidth - fab.offsetWidth - EDGE);
    const maxY = Math.max(EDGE, overlay.clientHeight - fab.offsetHeight - EDGE);
    const x = parseFloat(fab.style.left) || EDGE;
    const y = parseFloat(fab.style.top) || EDGE;
    return {
      x: maxX > EDGE ? (x - EDGE) / (maxX - EDGE) : 0,
      y: maxY > EDGE ? (y - EDGE) / (maxY - EDGE) : 0,
    };
  }

  let drag = null;
  grip.addEventListener('pointerdown', event => {
    if (event.button !== undefined && event.button !== 0) return;
    const rect = fab.getBoundingClientRect();
    drag = {id: event.pointerId, dx: event.clientX - rect.left, dy: event.clientY - rect.top};
    fab.classList.add('dragging');
    try { grip.setPointerCapture(event.pointerId); } catch (_) { /* 잡지 못해도 끌기는 된다 */ }
    event.preventDefault();
  });
  grip.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    const box = overlay.getBoundingClientRect();
    const maxX = overlay.clientWidth - fab.offsetWidth - EDGE;
    const maxY = overlay.clientHeight - fab.offsetHeight - EDGE;
    const x = Math.min(maxX, Math.max(EDGE, event.clientX - box.left - drag.dx));
    const y = Math.min(maxY, Math.max(EDGE, event.clientY - box.top - drag.dy));
    fab.style.left = `${Math.round(x)}px`;
    fab.style.top = `${Math.round(y)}px`;
  });
  const endDrag = event => {
    if (!drag || (event && event.pointerId !== drag.id)) return;
    drag = null;
    fab.classList.remove('dragging');
    savePos(currentRatio());
  };
  grip.addEventListener('pointerup', endDrag);
  grip.addEventListener('pointercancel', endDrag);
  grip.addEventListener('lostpointercapture', endDrag);

  // ---- 단추판 크기 ----
  const resize = overlay.querySelector('.mfs-resize');
  let scale = 1;
  function loadScale() {
    try {
      const v = Number(win.localStorage.getItem(SCALE_KEY));
      if (Number.isFinite(v) && v > 0) return Math.min(SCALE_MAX, Math.max(SCALE_MIN, v));
    } catch (_) { /* 기본 크기 */ }
    return 1;
  }
  function applyScale(value) {
    scale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, value));
    fab.style.setProperty('--s', String(scale));
    fab.classList.toggle('compact', scale < COMPACT_BELOW);
    resize.title = `크기 ${Math.round(scale * 100)}%`;
  }

  let sizing = null;
  resize.addEventListener('pointerdown', event => {
    if (event.button !== undefined && event.button !== 0) return;
    // 왼쪽 위 모서리는 그 자리에 두고 판만 커지고 줄게 - 끄는 동안 위치 비율을 다시 계산하지 않는다.
    sizing = {id: event.pointerId, x: event.clientX, scale};
    try { resize.setPointerCapture(event.pointerId); } catch (_) { /* 잡지 못해도 된다 */ }
    event.preventDefault();
    event.stopPropagation();
  });
  resize.addEventListener('pointermove', event => {
    if (!sizing || event.pointerId !== sizing.id) return;
    // 화면 밖으로 커지지 않게 - 지금 왼쪽 자리에서 오른쪽 끝까지가 한계다.
    const left = parseFloat(fab.style.left) || EDGE;
    const room = (overlay.clientWidth - left - EDGE) / BASE_WIDTH;
    const next = sizing.scale + (event.clientX - sizing.x) / BASE_WIDTH;
    applyScale(Math.min(next, Math.max(SCALE_MIN, room)));
  });
  const endSizing = event => {
    if (!sizing || (event && event.pointerId !== sizing.id)) return;
    sizing = null;
    try { win.localStorage.setItem(SCALE_KEY, String(Math.round(scale * 100) / 100)); } catch (_) { /* 기억만 못 한다 */ }
    // 커져서 아래로 넘쳤으면 안으로 밀어 넣고 그 자리를 기억한다.
    const maxY = overlay.clientHeight - fab.offsetHeight - EDGE;
    if ((parseFloat(fab.style.top) || 0) > maxY) fab.style.top = `${Math.round(Math.max(EDGE, maxY))}px`;
    savePos(currentRatio());
  };
  resize.addEventListener('pointerup', endSizing);
  resize.addEventListener('pointercancel', endSizing);
  resize.addEventListener('lostpointercapture', endSizing);

  const onResize = () => { if (isOpen()) { placeFab(loadPos()); closeSettings(); } };

  // ---- 길게 누르기 -> 단추판 설정(사용자 지시 2026-10-30) ----
  // 단추판 어디든(꺾쇠 빼고) LONG_PRESS_MS 동안 움직이지 않고 누르면 설정 창이 뜬다. 뜬 뒤 손을 떼도 그 단추는
  // 눌리지 않는다(suppressClick). 손잡이를 끌기 시작하면(MOVE_SLOP 넘게 움직이면) 길게 누르기는 취소된다.
  const settings = overlay.querySelector('.mfs-settings');
  const LONG_PRESS_MS = 500;
  const MOVE_SLOP = 8;
  let press = null;
  let suppressClick = false;

  function cancelPress() {
    if (press) win.clearTimeout(press.timer);
    press = null;
  }
  fab.addEventListener('pointerdown', event => {
    if (event.target.closest('.mfs-resize')) return;
    if (event.button !== undefined && event.button !== 0) return;
    cancelPress();
    const timer = win.setTimeout(() => {
      press = null;
      suppressClick = true;
      win.setTimeout(() => { suppressClick = false; }, 800);   // 클릭이 안 오는 경우(끌다 놓침)에도 풀린다
      if (drag) { drag = null; fab.classList.remove('dragging'); }   // 손잡이를 쥐고 있었다 - 옮기지 않고 끝낸다
      openSettings();
    }, LONG_PRESS_MS);
    press = {id: event.pointerId, x: event.clientX, y: event.clientY, timer};
  }, true);
  fab.addEventListener('pointermove', event => {
    if (!press || event.pointerId !== press.id) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > MOVE_SLOP) cancelPress();
  }, true);
  for (const type of ['pointerup', 'pointercancel']) {
    fab.addEventListener(type, event => { if (press && event.pointerId === press.id) cancelPress(); }, true);
  }
  // 길게 누른 뒤 떼면서 오는 클릭은 삼킨다 - 거울 단추가 진짜 단추를 누르지 않게.
  fab.addEventListener('click', event => {
    if (!suppressClick) return;
    suppressClick = false;
    event.stopPropagation();
    event.preventDefault();
  }, true);
  overlay.addEventListener('contextmenu', event => event.preventDefault());

  // '랜덤을 누를 때 생성' 은 확장 기능(⚙) 팝업의 줄을 그대로 누른다 - 옵션 통로가 그 줄에 있다(optionExtras.mjs).
  const realExtraRow = () => doc.querySelector('.opt-extras-popup [data-option="generate_on_random"]');
  const setRow = key => settings.querySelector(`[data-set="${key}"]`);
  let settingsObserver = null;

  function loadHideAuto() {
    try { return win.localStorage.getItem(HIDE_AUTO_KEY) === '1'; } catch (_) { return false; }
  }
  function applyHideAuto(hidden) {
    fab.classList.toggle('hide-auto', hidden);
    const row = setRow('hide_auto');
    row.classList.toggle('on', hidden);
    row.setAttribute('aria-pressed', hidden ? 'true' : 'false');
  }
  function syncSettings() {
    const real = realExtraRow();
    const row = setRow('generate_on_random');
    const on = real?.dataset.checked === 'true';
    row.disabled = !real;
    row.classList.toggle('on', on);
    row.setAttribute('aria-pressed', on ? 'true' : 'false');
    applyHideAuto(fab.classList.contains('hide-auto'));
  }
  function placeSettings() {
    const f = fab.getBoundingClientRect();
    const o = overlay.getBoundingClientRect();
    const w = settings.offsetWidth;
    const h = settings.offsetHeight;
    // 단추판 위에 연다 - 모자라면 아래, 그것도 모자라면 화면 안 아무 데나.
    let top = f.top - o.top - h - 8;
    if (top < EDGE) top = f.bottom - o.top + 8;
    if (top + h > o.height - EDGE) top = Math.max(EDGE, o.height - h - EDGE);
    const left = Math.min(o.width - w - EDGE, Math.max(EDGE, f.left - o.left + f.width / 2 - w / 2));
    settings.style.left = `${Math.round(left)}px`;
    settings.style.top = `${Math.round(top)}px`;
  }
  function isSettingsOpen() { return settings.classList.contains('open'); }
  function openSettings() {
    syncSettings();
    settings.classList.add('open');
    placeSettings();
    const real = realExtraRow();
    if (real && !settingsObserver) {
      settingsObserver = new MutationObserver(syncSettings);
      settingsObserver.observe(real, {attributes: true, attributeFilter: ['data-checked', 'class']});
    }
  }
  function closeSettings() {
    settings.classList.remove('open');
    settingsObserver?.disconnect();
    settingsObserver = null;
  }

  settings.addEventListener('click', event => {
    if (event.target.closest('.mfs-settings-x')) { closeSettings(); return; }
    const row = event.target.closest('[data-set]');
    if (!row || row.disabled) return;
    if (row.dataset.set === 'generate_on_random') {
      realExtraRow()?.click();   // 서버 echo 가 오면 observer 가 칠한다
    } else if (row.dataset.set === 'hide_auto') {
      const hidden = !fab.classList.contains('hide-auto');
      try { win.localStorage.setItem(HIDE_AUTO_KEY, hidden ? '1' : '0'); } catch (_) { /* 기억만 못 한다 */ }
      applyHideAuto(hidden);
      // 판 높이가 바뀌었다 - 아래로 넘치면 안으로 밀어 넣는다.
      const maxY = overlay.clientHeight - fab.offsetHeight - EDGE;
      if ((parseFloat(fab.style.top) || 0) > maxY) fab.style.top = `${Math.round(Math.max(EDGE, maxY))}px`;
    }
  });
  // 설정 창 바깥을 누르면 닫는다(누른 것은 그대로 동작한다).
  overlay.addEventListener('pointerdown', event => {
    if (isSettingsOpen() && !settings.contains(event.target)) closeSettings();
  }, true);

  // ---- 열기 · 닫기 ----
  function isOpen() { return overlay.classList.contains('open'); }
  function open() {
    if (isOpen()) return;
    syncAll();
    watch();
    applyScale(loadScale());
    applyHideAuto(loadHideAuto());
    overlay.classList.add('open');
    placeFab(loadPos());
    win.addEventListener('resize', onResize);
    overlay.querySelector('.mfs-close').focus({preventScroll: true});
  }
  function close() {
    if (!isOpen()) return;
    overlay.classList.remove('open');
    closeSettings();
    cancelPress();
    unwatch();
    win.removeEventListener('resize', onResize);
    entry?.focus?.({preventScroll: true});
  }

  overlay.querySelector('.mfs-close').addEventListener('click', close);
  overlay.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    if (isSettingsOpen()) closeSettings(); else close();
  });
  entry?.addEventListener('click', open);

  return {open, close, isOpen};
}
