// V5 인페인트 가상 캔버스.
//
// V5 는 인페인트를 별도 팝업으로 빼지 않는다(사용자 지정 2026-08-26).
//
// ⚠️ **캔버스는 결과 이미지와 같은 자리(plane)에 산다.** 아래에 작은 복제본을 하나 더
//    띄우면 어느 쪽이 진짜인지 알 수 없다(사용자 지적). 가상 캔버스는 "원본과 실물을
//    분리해 두는 종이" 지, 별도의 미리보기가 아니다.
//
//    · 화면(스테이지) -> `#inpaintCanvasPlane` (결과 뷰어 위에 겹친다)
//    · 조작(도크)     -> `#inpaintCanvasPanel` (결과 뷰어 **안**에 떠 있고, 접힌다)
//
// 도크는 세션이 사는 동안 떠 있고, 거기서 셋 중 하나를 고른다:
//    편집(캔버스를 본다) / 결과 보기(생성 결과를 본다) / 세션 닫기(끝낸다).
//
// ⚠️ `가상 캔버스` 토글은 **없앴다**(사용자 지적: "역할이 모호합니다"). 실제로 켜나
//    끄나 결과가 같았다 - 캔버스=원본 크기 · 오프셋 0 · 배율 1 · 회전 0 이면
//    `build_payload` 가 원본을 그대로 돌려주고 빈 곳 마스크도 안 생긴다. 그 상태로
//    가는 길은 `초기화` 다.
//
// ⚠️ 계열 판정은 백엔드가 한다(`canvas_supported`). 여기서 모델 표를 한 벌 더 들면
//    커스텀 모델이 등록될 때마다 두 곳이 어긋난다.
//
// 스테이지·격자·드래그는 `posStage.mjs` 를 쓴다. 캐릭터 POS 화면과 같은 몸짓이어야
// 한다는 사용자 지정이고, 그 규칙들은 실측으로 얻은 것이라 두 번 짜면 한쪽이 틀린다.
//
// ⚠️ 좌표는 전부 **캔버스 픽셀**로 주고받는다. 화면이 줄어 있어도 그대로다 - 화면
//    비율로 보내면 캔버스 크기를 바꾼 순간 전부 어긋난다.
//
// ⚠️ 아래 import 의 캐시 키는 posStage 를 고칠 때도 **함께** 바꾼다. 이 파일 키만
//    올리면 브라우저가 옛 posStage 를 계속 쓴다 - import 는 URL 로 캐시된다.
import {contentToPercent, createPosStage, gridSvg} from './posStage.mjs?v=20260826-raf1';

const CANVAS_SIZES = ['832 x 1216', '1216 x 832', '1024 x 1024', '1152 x 896', '896 x 1152'];
const GRID_KEY = 'naia.inpaintcanvas.grid.v1';
const COLLAPSE_KEY = 'naia.inpaintcanvas.collapsed.v1';

// 백엔드 `clamp_scale` 과 같은 한계. 어긋나면 화면이 보내 놓고 다른 값을 되받는다.
const SCALE_MIN_PCT = 10;
const SCALE_MAX_PCT = 400;
// 변형은 서버가 이미지를 다시 합성한다(리사이즈 + PNG 인코딩 + base64). 슬라이더가
// 움직이는 동안 매번 보내면 그만큼 합성이 쌓인다 - 마지막 값만 보낸다.
const TRANSFORM_DEBOUNCE_MS = 200;

const ratio = (value) => (Number(value) || 0).toFixed(2);
const clampPct = (v) => Math.max(SCALE_MIN_PCT, Math.min(SCALE_MAX_PCT, Math.round(Number(v) || 100)));
const wrapDeg = (v) => ((Math.round(Number(v) || 0) % 360) + 360) % 360;

export function createInpaintCanvasPanel({
  panel, plane, viewer, escHtml, setModuleParam, showToast,
  openMaskEditor = () => {},
  onSlider = () => {},
  onRepeat = () => {},
  onGenerate = () => {},
  onClose = () => {},
  onVisibility = () => {},
}) {
  let state = null;
  let stageEl = null;
  let posStage = null;
  // 편집(캔버스) / 결과 보기. 화면에서만 쓰는 값이라 서버에 안 보낸다 - 다른 기기에서
  // 보던 화면을 여기서 바꿔 버리면 안 된다.
  let viewMode = 'edit';
  // 드래그 중 계산한 베이스 오프셋. DOM 에 붙여 두면 재렌더에 함께 날아간다.
  let pendingOffset = null;
  // 슬라이더를 끄는 동안에는 다시 그리지 않는다 - 끌던 input 이 교체되면 드래그가 끊긴다.
  let rangeDragging = false;
  const transformTimers = {};

  const read = (key, fallback) => {
    try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, value); } catch (_) {}
  };

  let showGrid = read(GRID_KEY, '1') !== '0';
  let collapsed = read(COLLAPSE_KEY, '0') === '1';

  const canvasSize = () => ({
    w: Number(state?.canvas_width) || 0,
    h: Number(state?.canvas_height) || 0,
  });

  function send(key, value) {
    try { setModuleParam('img2img', key, value); }
    catch (error) { showToast?.(`캔버스 설정 실패: ${error.message}`, 'error'); }
  }

  /** 변형은 마지막 값만 보낸다. 슬라이더 한 번에 수십 번 합성시키지 않는다. */
  function sendTransform(key, value) {
    if (transformTimers[key]) clearTimeout(transformTimers[key]);
    transformTimers[key] = setTimeout(() => {
      delete transformTimers[key];
      send(key, value);
    }, TRANSFORM_DEBOUNCE_MS);
  }

  // ── 렌더 ────────────────────────────────────────────────────────────────
  function render(next) {
    if (next) state = next;
    if (!panel) return;
    // ⚠️ 조작 중에는 절대 다시 그리지 않는다(posStage 규칙 1). 서버 echo 가 와도
    //    마찬가지다 - 끌고 있던 노드가 교체되면 그 조작이 통째로 무시된다.
    if (posStage?.isDragging() || rangeDragging || typingInPanel()) return;
    // 캔버스는 V5 인페인트 전용이다. 다른 계열에서 띄우면 팝업과 조작 수단이 둘로
    // 갈려 어느 쪽이 진짜인지 알 수 없게 된다.
    const show = !!(state?.active && state.canvas_supported);
    if (show !== !panel.hidden) onVisibility(show);
    if (!show) {
      panel.innerHTML = '';
      panel.hidden = true;
      viewMode = 'edit';        // 다음 세션은 편집부터 시작한다
      renderPlane();
      return;
    }
    panel.hidden = false;
    panel.className = `inpaint-canvas-panel${collapsed ? ' is-collapsed' : ''}`;
    panel.innerHTML = collapsed ? collapsedHtml() : dockHtml();
    renderPlane();
  }

  function collapsedHtml() {
    const editing = viewMode === 'edit';
    return `<button type="button" class="ic-pill" data-ic="collapse" title="인페인트 조작 펼치기">`
      + `<span class="ic-pill-dot${editing ? ' is-edit' : ''}"></span>`
      + `인페인트<span class="ic-caret">▴</span></button>`;
  }

  /** 캔버스 해상도 목록.
   *
   *  ⚠️ 지금 크기가 프리셋에 없으면 `<select>` 는 **첫 항목**을 보여 준다 - 화면이
   *     실제와 다른 해상도를 말하게 된다. 원본 크기는 프리셋과 무관하고(사용자가
   *     아무 이미지나 보낼 수 있다) `초기화` 는 그 원본 크기로 돌아가므로, 늘 있을
   *     수 있는 일이다. 없으면 맨 앞에 끼워 넣는다.
   */
  function sizeOptions(w, h) {
    const labels = CANVAS_SIZES.slice();
    const current = (w > 0 && h > 0) ? `${w} x ${h}` : '';
    const bare = (t) => String(t).replace(/\s+/g, '');
    if (current && !labels.some(label => bare(label) === bare(current))) labels.unshift(current);
    return labels.map(label => {
      const [sw, sh] = label.split('x').map(v => parseInt(v.trim(), 10));
      const sel = (sw === w && sh === h) ? ' selected' : '';
      return `<option value="${escHtml(label)}"${sel}>${escHtml(label)}</option>`;
    }).join('');
  }

  // 좌우 2단(사용자 지정 2026-08-26). 왼쪽은 **캔버스의 기하**, 오른쪽은 **인페인트의
  // 실행**이다. 한 단으로 늘어놓으면 세 줄이 넉 줄이 되고, 그만큼 캔버스가 눌린다.
  function dockHtml() {
    const {w, h} = canvasSize();
    const editing = viewMode === 'edit';
    const off = editing ? '' : 'disabled';
    const scalePct = clampPct((Number(state.base_scale) || 1) * 100);
    const rotation = wrapDeg(state.base_rotation);
    return `
      <div class="ic-bar ic-bar-head ic-nowrap">
        <span class="ic-title">인페인트</span>
        <div class="ic-modes" role="group" aria-label="보기 모드">
          <button type="button" class="ic-btn${editing ? ' is-on' : ''}" data-ic="mode-edit">편집</button>
          <button type="button" class="ic-btn${editing ? '' : ' is-on'}" data-ic="mode-result">결과 보기</button>
        </div>
        <span class="ic-spacer"></span>
        <span class="ic-hint">${editing
          ? '✥ 를 끌면 베이스가 움직이고, 비는 자리는 자동으로 열립니다.'
          : '생성 결과를 보는 중입니다.'}</span>
        <button type="button" class="ic-btn ic-btn-collapse" data-ic="collapse" title="접기" aria-label="접기">▾</button>
      </div>
      <div class="ic-cols">
        <section class="ic-col" aria-label="캔버스">
          <div class="ic-row">
            <span class="ic-label">캔버스</span>
            <select class="ic-select" data-ic="size" ${off} aria-label="캔버스 해상도">${sizeOptions(w, h)}</select>
            <button type="button" class="ic-btn" data-ic="reset" ${off}
              title="원본 그대로로 되돌립니다 — 크기·위치·확대·회전">초기화</button>
            <button type="button" class="ic-btn${showGrid ? ' is-on' : ''}" data-ic="grid" ${off} title="격자">격자</button>
          </div>
          <div class="ic-row">
            <span class="ic-label">확대</span>
            <button type="button" class="ic-btn ic-nudge" data-ic="zoom-out" ${off} title="1% 축소">−</button>
            <input type="range" class="ic-slider-wide" min="${SCALE_MIN_PCT}" max="${SCALE_MAX_PCT}" step="1"
                   value="${scalePct}" data-ic-tr="scale" ${off} aria-label="확대 비율">
            <strong class="ic-val" data-ic-val="scale">${scalePct}%</strong>
            <button type="button" class="ic-btn ic-nudge" data-ic="zoom-in" ${off} title="1% 확대">+</button>
          </div>
          <div class="ic-row">
            <span class="ic-label">회전</span>
            <button type="button" class="ic-btn ic-nudge" data-ic="rot-down" ${off} title="1° 반시계">−</button>
            <input type="range" class="ic-slider-wide" min="0" max="359" step="1" value="${rotation}"
                   data-ic-tr="rotation" ${off} aria-label="회전 각도">
            <strong class="ic-val" data-ic-val="rotation">${rotation}°</strong>
            <button type="button" class="ic-btn ic-nudge" data-ic="rot-up" ${off} title="1° 시계">+</button>
            <button type="button" class="ic-btn" data-ic="rot-quarter" ${off} title="90° 돌리기">⟳</button>
          </div>
        </section>
        ${runColHtml(editing)}
      </div>
    `;
  }

  // 팝업이 안 열리므로 인페인트 조작은 전부 여기 있어야 한다.
  function runColHtml(editing) {
    const strength = Number.isFinite(Number(state.strength)) ? Number(state.strength) : 99;
    const noise = Number.isFinite(Number(state.noise)) ? Number(state.noise) : 0;
    const repeat = Number.isFinite(Number(state.repeat)) ? Number(state.repeat) : 1;
    const masked = !!state.has_mask;
    const genTitle = state.requires_mask
      ? ' title="생성 전에 마스크를 칠하거나 베이스를 옮겨 빈 자리를 여세요"' : '';
    return `
      <section class="ic-col" aria-label="인페인트 실행">
        <div class="ic-row">
          <button type="button" class="ic-btn ic-btn-mask" data-ic="mask" ${editing ? '' : 'disabled'}>마스크 그리기</button>
          <span class="ic-mask-state${masked ? ' is-on' : ''}">${masked ? '마스크 있음' : '마스크 없음'}</span>
          <button type="button" class="ic-btn" data-ic="clear-mask"
            ${(masked && editing) ? '' : 'disabled'}>지우기</button>
        </div>
        <div class="ic-row">
          <span class="ic-label">강도</span>
          <input type="range" min="1" max="99" value="${strength}" data-ic-range="strength" aria-label="강도">
          <strong class="ic-val" data-ic-val="strength">${ratio(state.strength_value)}</strong>
          <span class="ic-label">노이즈</span>
          <input type="range" min="0" max="99" value="${noise}" data-ic-range="noise" aria-label="노이즈">
          <strong class="ic-val" data-ic-val="noise">${ratio(state.noise_value)}</strong>
        </div>
        <div class="ic-row">
          <span class="ic-label">반복</span>
          <input class="ic-num" type="number" min="1" max="99" value="${repeat}" data-ic-num="repeat" aria-label="반복">
          <span class="ic-spacer"></span>
          <button type="button" class="ic-btn ic-btn-go" data-ic="generate" ${state.can_generate ? '' : 'disabled'}${genTitle}>인페인트 생성</button>
          <button type="button" class="ic-btn ic-btn-end" data-ic="close">세션 닫기</button>
        </div>
      </section>
    `;
  }

  // 결과 이미지와 같은 자리. 편집 모드일 때만 겹친다.
  function renderPlane() {
    if (!plane) return;
    const editing = !!(state?.active && state.canvas_supported && viewMode === 'edit');
    // 뷰어에 표식을 남겨 결과 이미지를 숨긴다 - 캔버스가 반투명하게 겹치면 옮긴
    // 자리가 원본과 겹쳐 보여 무엇이 진짜인지 알 수 없다.
    viewer?.classList.toggle('ic-editing', editing);
    if (!editing) { plane.innerHTML = ''; plane.hidden = true; stageEl = null; return; }
    plane.hidden = false;

    const {w, h} = canvasSize();
    const preview = state.preview || '';
    const off = {x: Number(state.base_offset_x) || 0, y: Number(state.base_offset_y) || 0};
    const placedW = Number(state.placed_width) || Number(state.base_width) || 0;
    const placedH = Number(state.placed_height) || Number(state.base_height) || 0;
    // 베이스 손잡이는 **놓인 그림의 한가운데**에 둔다. 모서리에 두면 캔버스 밖으로
    // 나갔을 때 잡을 수가 없다.
    const handle = contentToPercent(off.x + placedW / 2, off.y + placedH / 2, w, h);
    const chars = (state.characters || [])
      .map((c, i) => ({...c, index: i}))
      .filter(c => c.prompt && c.position);
    plane.innerHTML = `
      <div class="ic-stage" data-ic-stage="1">
        ${preview ? `<img class="ic-canvas" src="${escHtml(preview)}" alt="canvas" draggable="false">` : ''}
        ${showGrid ? gridSvg(w, h, {className: 'ic-grid pos-grid'}) : ''}
        <div class="ic-ghost" data-ic-ghost="1" hidden></div>
        <button type="button" class="ic-handle" data-ic-handle="1"
          style="left:${handle.left};top:${handle.top}" title="끌어서 베이스 이미지를 옮깁니다">✥</button>
        ${chars.map(c => {
          const p = contentToPercent(c.position.x, c.position.y, w, h);
          return `<button type="button" class="ic-marker" data-ic-marker="${c.index}"
            style="left:${p.left};top:${p.top}" title="${escHtml(c.prompt)}">${c.index + 1}</button>`;
        }).join('')}
      </div>
    `;
    stageEl = plane.querySelector('[data-ic-stage]');
    fitStage();
  }

  /** 스테이지를 남는 자리에 **비율 그대로** 앉힌다.
   *
   *  ⚠️ CSS `aspect-ratio` 로는 안 된다. 한 축만 확실할 때는 맞지만, 폭·높이 양쪽에
   *     한계가 걸리면 먼저 걸린 쪽만 잘리고 다른 쪽이 안 따라와 그림이 눌린다
   *     (실측: 도크가 자라 높이가 줄자 1.462 -> 1.399). 좌표 환산은 스테이지 상자의
   *     비율에만 기대므로, 눌린 상자는 곧 거짓말하는 좌표다.
   */
  function fitStage() {
    if (!stageEl || !plane) return;
    const {w, h} = canvasSize();
    if (!(w > 0) || !(h > 0)) return;
    const style = getComputedStyle(plane);
    const availW = plane.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const availH = plane.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    if (!(availW > 0) || !(availH > 0)) return;
    const scale = Math.min(availW / w, availH / h);
    stageEl.style.width = `${Math.round(w * scale)}px`;
    stageEl.style.height = `${Math.round(h * scale)}px`;
  }

  // ── 조작 ────────────────────────────────────────────────────────────────
  function typingInPanel() {
    const active = document.activeElement;
    return !!(active && panel?.contains(active) && active.matches?.('input[type="number"]'));
  }

  function setViewMode(mode) {
    const next = mode === 'result' ? 'result' : 'edit';
    if (next === viewMode) return;
    viewMode = next;
    render();
  }

  /** 확대/회전을 정확히 얼마만큼 민다. 화면은 즉시, 서버는 묶어서. */
  function nudge(key, delta) {
    if (!state) return;
    if (key === 'scale') applyTransform('scale', clampPct((Number(state.base_scale) || 1) * 100 + delta));
    else applyTransform('rotation', wrapDeg((Number(state.base_rotation) || 0) + delta));
  }

  function applyTransform(key, value) {
    if (!state) return;
    // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
    if (key === 'scale') state.base_scale = value / 100;
    else state.base_rotation = value;
    const input = panel.querySelector(`[data-ic-tr="${key}"]`);
    const label = panel.querySelector(`[data-ic-val="${key}"]`);
    if (input && input.value !== String(value)) input.value = String(value);
    if (label) label.textContent = key === 'scale' ? `${value}%` : `${value}°`;
    sendTransform(key === 'scale' ? 'base_scale' : 'base_rotation',
      key === 'scale' ? value / 100 : value);
  }

  function onClick(event) {
    const action = event.target.closest?.('[data-ic]')?.dataset.ic;
    if (!action) return;
    if (action === 'collapse') {
      collapsed = !collapsed;
      write(COLLAPSE_KEY, collapsed ? '1' : '0');
      return render();
    }
    if (action === 'mode-edit') return setViewMode('edit');
    if (action === 'mode-result') return setViewMode('result');
    if (action === 'grid') {
      showGrid = !showGrid;
      write(GRID_KEY, showGrid ? '1' : '0');
      return render();
    }
    if (action === 'reset') return send('base_reset', null);
    if (action === 'zoom-in') return nudge('scale', 1);
    if (action === 'zoom-out') return nudge('scale', -1);
    if (action === 'rot-up') return nudge('rotation', 1);
    if (action === 'rot-down') return nudge('rotation', -1);
    // 90° 는 자주 쓰는 자리라 한 번에 간다 - 슬라이더로 정확히 90 을 맞추기는 번거롭다.
    if (action === 'rot-quarter') return nudge('rotation', 90);
    if (action === 'mask') return openMaskEditor();
    if (action === 'clear-mask') return send('clear_mask', 'true');
    if (action === 'generate') return onGenerate();
    if (action === 'close') return onClose();
  }

  function onChange(event) {
    if (event.target.closest?.('[data-ic="size"]')) send('canvas_size', event.target.value);
  }

  function onInput(event) {
    const transform = event.target?.dataset?.icTr;
    if (transform) {
      applyTransform(transform, transform === 'scale'
        ? clampPct(event.target.value)
        : wrapDeg(event.target.value));
      return;
    }
    const key = event.target?.dataset?.icRange;
    if (key) {
      // 값 표시는 여기서 직접 맞춘다 - 팝업이 안 열려 있어 저쪽 라벨은 존재하지 않는다.
      const raw = Math.max(key === 'strength' ? 1 : 0, Math.min(99, Math.round(Number(event.target.value) || 0)));
      const label = panel.querySelector(`[data-ic-val="${key}"]`);
      if (label) label.textContent = ratio(key === 'strength' && raw === 99 ? 1 : raw / 100);
      onSlider(key, raw);
      return;
    }
    if (event.target?.dataset?.icNum === 'repeat') onRepeat(event.target.value);
  }

  function onPanelPointerDown(event) {
    if (event.target?.matches?.('input[type="range"]')) rangeDragging = true;
  }

  function onPlanePointerDown(event) {
    if (!stageEl) return;
    const handle = event.target.closest?.('[data-ic-handle]');
    if (handle) {
      const placedW = Number(state.placed_width) || Number(state.base_width) || 0;
      const placedH = Number(state.placed_height) || Number(state.base_height) || 0;
      const ghost = stageEl.querySelector('[data-ic-ghost]');
      // 손잡이는 그림의 한가운데를 가리키므로, 좌상단 오프셋으로 되돌려 보낸다.
      posStage.beginDrag(event, handle, 'base', (x, y) => {
        const {w, h} = canvasSize();
        const pos = contentToPercent(x, y, w, h);
        handle.style.left = pos.left;
        handle.style.top = pos.top;
        const ox = Math.round(x - placedW / 2);
        const oy = Math.round(y - placedH / 2);
        pendingOffset = {x: ox, y: oy};
        // 그림 자체는 서버가 다시 합성해야 움직인다(놓을 때 한 번). 끄는 동안에는
        // **어디에 놓이는지**와 **얼마나 새 자리가 열리는지**를 유령으로 보여 준다 -
        // 손잡이 하나만 움직이면 무엇이 일어나는지 알 수 없다(사용자 지적).
        if (ghost && w > 0 && h > 0) {
          ghost.hidden = false;
          ghost.style.left = `${(ox / w) * 100}%`;
          ghost.style.top = `${(oy / h) * 100}%`;
          ghost.style.width = `${(placedW / w) * 100}%`;
          ghost.style.height = `${(placedH / h) * 100}%`;
        }
      });
      return;
    }
    const marker = event.target.closest?.('[data-ic-marker]');
    if (marker) posStage.beginDrag(event, marker, `char_${marker.dataset.icMarker}`);
  }

  function commit({x, y, key}) {
    if (key === 'base') {
      if (pendingOffset) {
        const {x: ox, y: oy} = pendingOffset;
        pendingOffset = null;
        // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
        if (state) { state.base_offset_x = ox; state.base_offset_y = oy; }
        send('base_offset', {x: ox, y: oy});
      }
      return;
    }
    const index = Number(String(key).replace('char_', ''));
    if (!Number.isFinite(index)) return;
    const character = (state?.characters || [])[index];
    if (character) character.position = {x, y};
    send(`char_position_${index}`, {x, y});
  }

  if (panel) {
    // 도크가 실제로 차지한 높이를 뷰어에 적어 둔다. 캔버스가 그만큼 비켜선다 -
    // 고정값으로 박으면 좁은 창에서 줄이 접혀 도크가 그림을 덮는다(실측 286px).
    // 도크 높이 -> plane 여백 -> 스테이지 크기. 셋이 사슬로 물려 있다.
    //
    // ⚠️ **콜백 안에서 레이아웃을 바꾸면 안 된다.** 바로 쓰면 같은 프레임 안에서
    //    관찰 대상이 또 바뀌어 브라우저가 "ResizeObserver loop completed with
    //    undelivered notifications" 를 던진다(실측). 다음 프레임으로 미루고,
    //    값이 그대로면 아예 쓰지 않는다 - 둘 다 있어야 사슬이 멎는다.
    const deferred = (fn) => {
      let queued = 0;
      return () => {
        if (queued) return;
        queued = requestAnimationFrame(() => { queued = 0; fn(); });
      };
    };

    if (viewer && typeof ResizeObserver === 'function') {
      let lastDockH = -1;
      const syncDockHeight = deferred(() => {
        const h = Math.round(panel.getBoundingClientRect().height);
        if (h === lastDockH) return;
        lastDockH = h;
        viewer.style.setProperty('--ic-dock-h', `${h}px`);
      });
      new ResizeObserver(syncDockHeight).observe(panel);
    }
    // 남는 자리가 바뀌면(도크가 접히거나 줄이 늘거나 창이 바뀌면) 다시 앉힌다.
    if (plane && typeof ResizeObserver === 'function') {
      let lastBox = '';
      const refit = deferred(() => {
        const box = `${plane.clientWidth}x${plane.clientHeight}`;
        if (box === lastBox) return;
        lastBox = box;
        fitStage();
      });
      new ResizeObserver(refit).observe(plane);
    }
    panel.addEventListener('click', onClick);
    panel.addEventListener('change', onChange);
    panel.addEventListener('input', onInput);
    panel.addEventListener('pointerdown', onPanelPointerDown);
    plane?.addEventListener('pointerdown', onPlanePointerDown);
    // 슬라이더는 패널 밖에서 손을 떼도 끝난다 - document 에서 받아야 놓치지 않는다.
    document.addEventListener('pointerup', () => { rangeDragging = false; });
    document.addEventListener('pointercancel', () => { rangeDragging = false; });
    posStage = createPosStage({
      // 스테이지는 매 렌더마다 새로 만들어진다 - 함수로 넘겨 늘 살아 있는 것을 잰다.
      stage: () => stageEl,
      getContentSize: canvasSize,
      onCommit: commit,
      onDragEnd: () => {
        // 재렌더가 유령을 지우지만, 커밋이 없어 다시 그리지 않는 경우도 있다.
        stageEl?.querySelector('[data-ic-ghost]')?.setAttribute('hidden', '');
        render();
      },
    });
  }

  return {
    render,
    /** 생성이 끝나면 결과를 봐야 한다 - 캔버스가 결과를 가리고 있으면 안 된다. */
    showResult() { setViewMode('result'); },
    /** Inpaint 를 눌러 세션이 열렸다. 도크가 **반드시** 눈에 보이게 한다.
     *
     *  ⚠️ 이게 없으면 버튼이 조용히 아무 일도 안 한 것처럼 보이는 길이 셋이나 된다:
     *    · 접어 둔 상태가 저장돼 있으면 24px 알약만 떠서 못 알아본다
     *    · 직전 세션에서 `결과 보기` 로 끝났으면 캔버스가 안 그려진다
     *    · 반복 칸에 커서가 남아 있으면 `typingInPanel` 가드가 렌더를 통째로 막는다
     *  세 가지 모두 여기서 풀고 그린다.
     */
    revealForSession() {
      viewMode = 'edit';
      if (collapsed) { collapsed = false; write(COLLAPSE_KEY, '0'); }
      if (document.activeElement && panel?.contains(document.activeElement)) {
        try { document.activeElement.blur(); } catch (_) {}
      }
      rangeDragging = false;
      render();
    },
    /** 지금 무대가 놓인 자리와 캔버스 해상도. 캐릭터 POS 무대가 여기 겹쳐 선다.
     *
     *  ⚠️ 캔버스가 떠 있는 동안 화면의 그림은 `#preview` 가 아니고, 생성 해상도도
     *     파라미터가 아니라 캔버스 크기다. 이걸 안 알려 주면 POS 무대가 파라미터
     *     비율로 서서 그림과 어긋난다(사용자 제보: "현재 이미지와 POS 해상도 불일치").
     */
    stageRect() {
      if (!stageEl || plane?.hidden) return null;
      const r = stageEl.getBoundingClientRect();
      const {w, h} = canvasSize();
      if (!(r.width > 0) || !(r.height > 0) || !(w > 0) || !(h > 0)) return null;
      return {left: r.left, top: r.top, width: r.width, height: r.height, w, h};
    },
    handleModuleState(payload) {
      if (payload && payload.module_id === 'img2img') render(payload);
    },
  };
}
