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
import {contentToPercent, createPosStage, gridSvg} from './posStage.mjs?v=20260826-freedrag1';

const CANVAS_SIZES = ['832 x 1216', '1216 x 832', '1024 x 1024', '1152 x 896', '896 x 1152'];
const GRID_KEY = 'naia.inpaintcanvas.grid.v1';
const COLLAPSE_KEY = 'naia.inpaintcanvas.collapsed.v1';

// 백엔드 `clamp_scale` 과 같은 한계. 어긋나면 화면이 보내 놓고 다른 값을 되받는다.
const SCALE_MIN_PCT = 10;
const SCALE_MAX_PCT = 400;
// 변형은 서버가 이미지를 다시 합성한다(리사이즈 + PNG 인코딩 + base64). 슬라이더가
// 움직이는 동안 매번 보내면 그만큼 합성이 쌓인다 - 마지막 값만 보낸다.
const TRANSFORM_DEBOUNCE_MS = 200;

// 중앙 버튼 드래그 감도. 세로 3px 당 1% - 한 화면(약 700px)에 대략 배율 전 구간이 든다.
const MIDDLE_SCALE_PX_PER_PCT = 3;
// 회전은 각도를 그대로 따라가되, 중앙 가까이에서는 각도가 튀므로 그 안은 무시한다.
const ROTATE_DEAD_ZONE_PX = 40;
// 베이스 미세 이동. Shift 는 자동 마스킹 반경과 같은 값으로 맞춘다.
const NUDGE_PX = 1;
const NUDGE_PX_COARSE = 16;
// 휠 한 칸. Shift 를 누르면 다섯 배로 간다(방향키와 같은 손버릇).
const WHEEL_SCALE_PCT = 2;
const WHEEL_ROTATE_DEG = 1;
const WHEEL_COARSE = 5;

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
      disarmSessionInput();     // 세션이 끝나면 입력을 **즉시** 돌려준다(사용자 지정)
      panel.innerHTML = '';
      panel.hidden = true;
      viewMode = 'edit';        // 다음 세션은 편집부터 시작한다
      renderPlane();
      return;
    }
    armSessionInput();
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
          ? '끌기=이동 · 휠=크기 · Ctrl+휠=회전 · 휠버튼 끌기도 같음 · 방향키=1px(Shift 16) · 0=초기화'
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
          <button type="button" class="ic-btn" data-ic="auto-mask" ${editing ? '' : 'disabled'}
            title="빈 곳과 그 경계(16px)를 한 번에 칠합니다">자동 마스킹</button>
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
    const chars = (state.characters || [])
      .map((c, i) => ({...c, index: i}))
      .filter(c => c.prompt && c.position);
    plane.innerHTML = `
      <div class="ic-stage" data-ic-stage="1">
        ${preview ? `<img class="ic-canvas" src="${escHtml(preview)}" alt="canvas" draggable="false">` : ''}
        ${showGrid ? gridSvg(w, h, {className: 'ic-grid pos-grid'}) : ''}
        <div class="ic-ghost" data-ic-ghost="1" hidden></div>
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

  function applyTransform(key, value, at) {
    if (!state) return;
    // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
    if (key === 'scale') state.base_scale = value / 100;
    else state.base_rotation = value;
    const input = panel.querySelector(`[data-ic-tr="${key}"]`);
    const label = panel.querySelector(`[data-ic-val="${key}"]`);
    if (input && input.value !== String(value)) input.value = String(value);
    if (label) label.textContent = key === 'scale' ? `${value}%` : `${value}°`;
    // 기준점을 안 주면 백엔드가 캔버스 한가운데를 잡는다(슬라이더·± 가 그 경우다).
    const payload = key === 'scale' ? {value: value / 100} : {value};
    if (at) payload.at = at;
    sendTransform(key === 'scale' ? 'base_scale' : 'base_rotation', payload);
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
    if (action === 'auto-mask') return send('auto_mask', 'true');
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
    // 숫자 마커가 **먼저**다. 그 위에서 누르면 그 캐릭터를 옮긴다.
    const marker = event.target.closest?.('[data-ic-marker]');
    if (marker) { posStage.beginDrag(event, marker, `char_${marker.dataset.icMarker}`); return; }
    if (event.button === 1) { event.preventDefault(); beginMiddleDrag(event); return; }
    if (event.button === 0) beginBaseDrag(event);
  }

  /** 그림 위 **어디서나** 끌어서 옮긴다(사용자 지정 2026-08-26, 파워포인트처럼).
   *
   *  ⚠️ 좌표를 `pointToContent` 로 받으면 안 된다. 그건 스테이지 밖을 **잘라낸다**
   *     (마커는 캔버스 안에 있어야 하니 그쪽에는 맞는 동작이다). 베이스를 밖으로 밀
   *     때는 커서가 스테이지를 벗어나는데, 그러면 델타가 가장자리에서 멈춰 **덜 간다**
   *     - 사용자 제보 "정확한 위치로 놓여지지 않습니다". 화면 픽셀 델타를 직접 재서
   *     캔버스 배율로만 나눈다.
   */
  function beginBaseDrag(event) {
    const host = stageEl;
    const {w, h} = canvasSize();
    const rect = host.getBoundingClientRect();
    if (!(rect.width > 0) || !(w > 0) || !(h > 0)) return;
    const perX = w / rect.width;
    const perY = h / rect.height;
    const startX = event.clientX;
    const startY = event.clientY;
    const startOffset = {
      x: Number(state.base_offset_x) || 0,
      y: Number(state.base_offset_y) || 0,
    };
    const placedW = Number(state.placed_width) || Number(state.base_width) || 0;
    const placedH = Number(state.placed_height) || Number(state.base_height) || 0;
    const ghost = host.querySelector('[data-ic-ghost]');

    posStage.beginFreeDrag(event, host, (ev) => {
      const ox = Math.round(startOffset.x + (ev.clientX - startX) * perX);
      const oy = Math.round(startOffset.y + (ev.clientY - startY) * perY);
      pendingOffset = {x: ox, y: oy};
      // 그림 자체는 서버가 다시 합성해야 움직인다(놓을 때 한 번). 끄는 동안에는
      // **어디에 놓이는지**와 **얼마나 새 자리가 열리는지**를 유령으로 보여 준다.
      if (ghost) {
        ghost.hidden = false;
        ghost.style.left = `${(ox / w) * 100}%`;
        ghost.style.top = `${(oy / h) * 100}%`;
        ghost.style.width = `${(placedW / w) * 100}%`;
        ghost.style.height = `${(placedH / h) * 100}%`;
      }
    }, () => {
      if (!pendingOffset) return;
      const {x: ox, y: oy} = pendingOffset;
      pendingOffset = null;
      if (state) { state.base_offset_x = ox; state.base_offset_y = oy; }
      send('base_offset', {x: ox, y: oy});
    });
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

  /** 이 조작들은 **인페인트 세션 안에서만** 산다(사용자 지정 2026-08-26).
   *
   *  ⚠️ 방향키와 중앙 버튼은 document 를 가로챈다. 세션이 끝나도 붙어 있으면 앱 전체의
   *     입력을 조용히 갉아먹는다 - 세션이 열릴 때 걸고, 닫히는 즉시 돌려준다.
   */
  let sessionInputTeardown = null;

  function armSessionInput() {
    if (sessionInputTeardown) return;

    // ⚠️ Chromium 은 중앙 버튼을 누르면 **자동 스크롤**(사방향 커서)을 띄운다.
    //    `pointerdown` 만 막아도 되는 것이 원칙이지만, 빌드에 따라 호환 `mousedown`
    //    으로 새는 경우가 있어 셋 다 막는다.
    const swallowMiddle = (event) => {
      if (event.button === 1 && plane?.contains(event.target)) event.preventDefault();
    };
    const swallowAux = (event) => {
      if (event.button === 1 && plane?.contains(event.target)) event.preventDefault();
    };
    document.addEventListener('mousedown', swallowMiddle, true);
    document.addEventListener('auxclick', swallowAux, true);

    // 휠 = 크기(커서 붙잡음), Ctrl+휠 = 회전.
    //
    // ⚠️ Ctrl+휠은 원래 **Electron 셸의 UI 배율**이다(`preload.cjs` 가 window 에
    //    capture 로 물고 stopPropagation 한다). 페이지에서는 가로챌 수 없어서, 그쪽
    //    예외 목록에 `.ic-plane` 을 적어 두고서야 여기까지 온다. 예외를 안 적으면
    //    이 리스너는 **영영 안 불린다**(사용자 제보 2026-08-26).
    const onWheel = (event) => {
      if (viewMode !== 'edit' || !state?.active) return;
      if (!plane?.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      const dir = event.deltaY < 0 ? 1 : -1;
      const boost = event.shiftKey ? WHEEL_COARSE : 1;
      if (event.ctrlKey) {
        nudge('rotation', dir * WHEEL_ROTATE_DEG * boost);
        return;
      }
      // 커서 아래를 붙잡고 키운다 - 안 붙잡으면 굴릴수록 그림이 도망간다.
      const next = clampPct((Number(state.base_scale) || 1) * 100 + dir * WHEEL_SCALE_PCT * boost);
      applyTransform('scale', next, canvasPointOf(event));
    };
    plane?.addEventListener('wheel', onWheel, {passive: false});

    // Ctrl 을 쥐면 **회전할 수 있다는 것을 커서로 알린다**(사용자 지적: 회전 커서가
    // 안 보인다). 표식은 매 렌더마다 새로 나는 스테이지가 아니라 **plane** 에 붙인다.
    const syncRotateCursor = (event) => {
      plane?.classList.toggle('is-rotate',
        !!(event?.ctrlKey) && viewMode === 'edit' && !!state?.active);
    };
    const dropRotateCursor = () => plane?.classList.remove('is-rotate');
    document.addEventListener('keydown', syncRotateCursor);
    document.addEventListener('keyup', syncRotateCursor);
    window.addEventListener('blur', dropRotateCursor);

    const onKeyDown = (event) => {
      if (viewMode !== 'edit' || !state?.active) return;
      const active = document.activeElement;
      // 글자를 치고 있으면 손대지 않는다.
      if (active && active.matches?.('input, textarea, select, [contenteditable="true"]')) return;
      const step = event.shiftKey ? NUDGE_PX_COARSE : NUDGE_PX;
      const move = {ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                    ArrowUp: [0, -step], ArrowDown: [0, step]}[event.key];
      if (move) {
        event.preventDefault();
        const ox = Math.round((Number(state.base_offset_x) || 0) + move[0]);
        const oy = Math.round((Number(state.base_offset_y) || 0) + move[1]);
        state.base_offset_x = ox;
        state.base_offset_y = oy;
        send('base_offset', {x: ox, y: oy});
        return;
      }
      if (event.key === '0') {
        event.preventDefault();
        send('base_reset', null);
      }
    };
    document.addEventListener('keydown', onKeyDown);

    sessionInputTeardown = () => {
      plane?.removeEventListener('wheel', onWheel);
      document.removeEventListener('keydown', syncRotateCursor);
      document.removeEventListener('keyup', syncRotateCursor);
      window.removeEventListener('blur', dropRotateCursor);
      dropRotateCursor();
      document.removeEventListener('mousedown', swallowMiddle, true);
      document.removeEventListener('auxclick', swallowAux, true);
      document.removeEventListener('keydown', onKeyDown);
      sessionInputTeardown = null;
    };
  }

  function disarmSessionInput() {
    if (sessionInputTeardown) sessionInputTeardown();
  }

  /** 화면 좌표를 캔버스 픽셀로. 확대의 기준점을 잡는 데 쓴다. */
  function canvasPointOf(event) {
    if (!stageEl) return null;
    const rect = stageEl.getBoundingClientRect();
    const {w, h} = canvasSize();
    if (!(rect.width > 0) || !(w > 0) || !(h > 0)) return null;
    return {
      x: Math.round((event.clientX - rect.left) / rect.width * w),
      y: Math.round((event.clientY - rect.top) / rect.height * h),
    };
  }

  /** 중앙 버튼 드래그: 크기(세로) / Ctrl 이면 회전(각도).
   *
   *  ⚠️ 크기는 **누른 지점**을, 회전은 **캔버스 한가운데**를 붙잡는다. 안 붙잡으면
   *     놓인 상자의 좌상단이 고정돼 키울수록 그림이 우하단으로 도망간다(실측:
   *     200% 에서 그림 한가운데가 캔버스 모서리, 400% 에서는 화면 밖).
   *  ⚠️ 중앙 버튼이 없는 입력기(터치·트랙패드·펜)가 있다 - 슬라이더와 ± 는 그대로
   *     남는다. 이건 빠른 길이지 유일한 길이 아니다.
   */
  function beginMiddleDrag(event) {
    const host = stageEl;
    const {w, h} = canvasSize();
    const rect = host.getBoundingClientRect();
    if (!(rect.width > 0) || !(w > 0) || !(h > 0)) return;
    const rotating = event.ctrlKey;
    const startScale = clampPct((Number(state.base_scale) || 1) * 100);
    const startRotation = wrapDeg(state.base_rotation);
    const startY = event.clientY;
    const at = canvasPointOf(event);   // 누른 지점 = 크기의 기준점
    if (rotating) plane?.classList.add('is-rotate');
    const pivot = {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
    const angleOf = (ev) => Math.atan2(ev.clientY - pivot.y, ev.clientX - pivot.x) * 180 / Math.PI;
    const startAngle = angleOf(event);
    const startDist = Math.hypot(event.clientX - pivot.x, event.clientY - pivot.y);
    let sent = null;

    posStage.beginFreeDrag(event, host, (ev) => {
      if (rotating) {
        if (startDist < ROTATE_DEAD_ZONE_PX) return;
        const next = wrapDeg(startRotation + (angleOf(ev) - startAngle));
        sent = {key: 'rotation', value: next};
        applyTransform('rotation', next);
      } else {
        const next = clampPct(startScale + (startY - ev.clientY) / MIDDLE_SCALE_PX_PER_PCT);
        sent = {key: 'scale', value: next};
        applyTransform('scale', next, at);
      }
    }, () => {
      // 놓는 순간 마지막 값을 곧바로 보낸다 - 디바운스가 남아 있으면 거기서 또 간다.
      if (!sent) return;
      if (sent.key === 'scale') sendTransform('base_scale', {value: sent.value / 100, at});
      else sendTransform('base_rotation', {value: sent.value});
      sent = null;
      if (rotating) plane?.classList.remove('is-rotate');
    });
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
