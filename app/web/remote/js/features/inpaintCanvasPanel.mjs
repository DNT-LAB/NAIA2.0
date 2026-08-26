// V5 인페인트 가상 캔버스.
//
// V5 는 인페인트를 별도 팝업으로 빼지 않는다(사용자 지정 2026-08-26).
//
// ⚠️ **캔버스는 결과 이미지와 같은 자리(plane)에 산다.** 아래에 작은 복제본을 하나 더
//    띄우면 어느 쪽이 진짜인지 알 수 없다(사용자 지적 2026-08-26). 가상 캔버스는
//    "원본과 실물을 분리해 두는 종이" 지, 별도의 미리보기가 아니다.
//
//    · 화면(스테이지)  -> `#inpaintCanvasPlane`  (결과 뷰어 위에 겹친다)
//    · 조작(컨트롤러)  -> `#inpaintCanvasPanel`  (Generation Info 안, 계속 떠 있다)
//
// 컨트롤러는 세션이 사는 동안 계속 떠 있고, 거기서 셋 중 하나를 고른다:
//    편집(캔버스를 본다) / 결과 보기(생성 결과를 본다) / 세션 닫기(끝낸다).
//
// ⚠️ 계열 판정은 백엔드가 한다(`canvas_supported`). 여기서 모델 표를 한 벌 더 들면
//    커스텀 모델이 등록될 때마다 두 곳이 어긋난다.
//
// 스테이지·격자·드래그는 `posStage.mjs` 를 쓴다. 캐릭터 POS 화면과 같은 몸짓이어야
// 한다는 사용자 지정이고, 그 규칙들은 실측으로 얻은 것이라 두 번 짜면 한쪽이 틀린다.
//
// ⚠️ 좌표는 전부 **캔버스 픽셀**로 주고받는다. 화면이 줄어 있어도 그대로다 - 화면
//    비율로 보내면 캔버스 크기를 바꾼 순간 전부 어긋난다.

import {contentToPercent, createPosStage, gridSvg} from './posStage.mjs';

const CANVAS_SIZES = ['832 x 1216', '1216 x 832', '1024 x 1024', '1152 x 896', '896 x 1152'];
const SCALE_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];
const GRID_KEY = 'naia.inpaintcanvas.grid.v1';

const ratio = (value) => (Number(value) || 0).toFixed(2);

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
  let showGrid = (() => {
    try { return localStorage.getItem(GRID_KEY) !== '0'; } catch (_) { return true; }
  })();

  const canvasSize = () => ({
    w: Number(state?.canvas_width) || 0,
    h: Number(state?.canvas_height) || 0,
  });

  function send(key, value) {
    try { setModuleParam('img2img', key, value); }
    catch (error) { showToast?.(`캔버스 설정 실패: ${error.message}`, 'error'); }
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
    panel.innerHTML = controllerHtml();
    renderPlane();
  }

  function controllerHtml() {
    const {w, h} = canvasSize();
    const on = !!state.canvas_active;
    const editing = viewMode === 'edit';
    // 캔버스 조작은 편집 모드에서만 뜻이 있다. 결과를 보는 중에 눌러 봐야 화면이
    // 안 바뀌어 "먹통" 으로 읽힌다.
    const off = editing ? '' : 'disabled';
    return `
      <div class="ic-bar">
        <div class="ic-modes" role="group" aria-label="인페인트 보기 모드">
          <button type="button" class="ic-btn${editing ? ' is-on' : ''}" data-ic="mode-edit">편집</button>
          <button type="button" class="ic-btn${editing ? '' : ' is-on'}" data-ic="mode-result">결과 보기</button>
        </div>
        <span class="ic-sep"></span>
        <button type="button" class="ic-btn${on ? ' is-on' : ''}" data-ic="toggle" ${off}>가상 캔버스</button>
        <select class="ic-select" data-ic="size" ${(on && editing) ? '' : 'disabled'} aria-label="캔버스 해상도">
          ${CANVAS_SIZES.map(label => {
            const [sw, sh] = label.split('x').map(v => parseInt(v.trim(), 10));
            const sel = (sw === w && sh === h) ? ' selected' : '';
            return `<option value="${escHtml(label)}"${sel}>${escHtml(label)}</option>`;
          }).join('')}
        </select>
        <button type="button" class="ic-btn" data-ic="zoom-out" ${(on && editing) ? '' : 'disabled'} title="축소">−</button>
        <span class="ic-readout">${Math.round((Number(state.base_scale) || 1) * 100)}%</span>
        <button type="button" class="ic-btn" data-ic="zoom-in" ${(on && editing) ? '' : 'disabled'} title="확대">+</button>
        <button type="button" class="ic-btn" data-ic="rotate" ${(on && editing) ? '' : 'disabled'} title="90° 회전">⟳</button>
        <span class="ic-readout">${Math.round(Number(state.base_rotation) || 0)}°</span>
        <button type="button" class="ic-btn" data-ic="reset" ${(on && editing) ? '' : 'disabled'} title="위치·확대·회전 초기화">초기화</button>
        <button type="button" class="ic-btn${showGrid ? ' is-on' : ''}" data-ic="grid" ${off} title="격자">격자</button>
        <span class="ic-spacer"></span>
        <span class="ic-hint">${editing
          ? '✥ 를 끌면 베이스가 움직이고, 비는 자리는 자동으로 열립니다.'
          : '생성 결과를 보는 중입니다. 편집을 누르면 캔버스로 돌아갑니다.'}</span>
      </div>
      ${runBarHtml(editing)}
    `;
  }

  // 팝업이 안 열리므로 인페인트 조작은 전부 여기 있어야 한다.
  function runBarHtml(editing) {
    const strength = Number.isFinite(Number(state.strength)) ? Number(state.strength) : 99;
    const noise = Number.isFinite(Number(state.noise)) ? Number(state.noise) : 0;
    const repeat = Number.isFinite(Number(state.repeat)) ? Number(state.repeat) : 1;
    const masked = !!state.has_mask;
    const genTitle = state.requires_mask
      ? ' title="생성 전에 마스크를 칠하거나 베이스를 옮겨 빈 자리를 여세요"' : '';
    return `
      <div class="ic-bar ic-bar-run">
        <button type="button" class="ic-btn ic-btn-mask" data-ic="mask" ${editing ? '' : 'disabled'}>마스크 그리기</button>
        <span class="ic-mask-state${masked ? ' is-on' : ''}">${masked ? '마스크 있음' : '마스크 없음'}</span>
        <button type="button" class="ic-btn" data-ic="clear-mask" ${masked ? '' : 'disabled'}>마스크 지우기</button>
        <span class="ic-sep"></span>
        <label class="ic-range">강도 <input type="range" min="1" max="99" value="${strength}" data-ic-range="strength">
          <strong data-ic-val="strength">${ratio(state.strength_value)}</strong></label>
        <label class="ic-range">노이즈 <input type="range" min="0" max="99" value="${noise}" data-ic-range="noise">
          <strong data-ic-val="noise">${ratio(state.noise_value)}</strong></label>
        <label class="ic-range ic-repeat">반복 <input type="number" min="1" max="99" value="${repeat}" data-ic-num="repeat"></label>
        <span class="ic-spacer"></span>
        <button type="button" class="ic-btn ic-btn-go" data-ic="generate" ${state.can_generate ? '' : 'disabled'}${genTitle}>인페인트 생성</button>
        <button type="button" class="ic-btn ic-btn-end" data-ic="close">세션 닫기</button>
      </div>
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
        ${state.canvas_active ? `<button type="button" class="ic-handle" data-ic-handle="1"
          style="left:${handle.left};top:${handle.top}" title="끌어서 베이스 이미지를 옮깁니다">✥</button>` : ''}
        ${chars.map(c => {
          const p = contentToPercent(c.position.x, c.position.y, w, h);
          return `<button type="button" class="ic-marker" data-ic-marker="${c.index}"
            style="left:${p.left};top:${p.top}" title="${escHtml(c.prompt)}">${c.index + 1}</button>`;
        }).join('')}
      </div>
    `;
    stageEl = plane.querySelector('[data-ic-stage]');
    if (stageEl && w > 0 && h > 0) {
      // 스테이지는 캔버스 비율을 그대로 쥔다 - 좌표 환산이 비율에만 기대기 때문이다.
      stageEl.style.aspectRatio = `${w} / ${h}`;
    }
  }

  // ── 조작 ────────────────────────────────────────────────────────────────
  function typingInPanel() {
    const active = document.activeElement;
    return !!(active && panel?.contains(active) && active.matches?.('input[type="number"]'));
  }

  function currentScaleIndex() {
    const scale = Number(state?.base_scale) || 1;
    let best = 0;
    SCALE_STEPS.forEach((step, i) => {
      if (Math.abs(step - scale) < Math.abs(SCALE_STEPS[best] - scale)) best = i;
    });
    return best;
  }

  function setViewMode(mode) {
    const next = mode === 'result' ? 'result' : 'edit';
    if (next === viewMode) return;
    viewMode = next;
    render();
  }

  function onClick(event) {
    const action = event.target.closest?.('[data-ic]')?.dataset.ic;
    if (!action) return;
    if (action === 'mode-edit') return setViewMode('edit');
    if (action === 'mode-result') return setViewMode('result');
    if (action === 'toggle') return send('canvas_active', !state?.canvas_active);
    if (action === 'grid') {
      showGrid = !showGrid;
      try { localStorage.setItem(GRID_KEY, showGrid ? '1' : '0'); } catch (_) {}
      return render();
    }
    if (action === 'reset') return send('base_reset', null);
    if (action === 'rotate') return send('base_rotation', ((Number(state?.base_rotation) || 0) + 90) % 360);
    if (action === 'mask') return openMaskEditor();
    if (action === 'clear-mask') return send('clear_mask', 'true');
    if (action === 'generate') return onGenerate();
    if (action === 'close') return onClose();
    if (action === 'zoom-in' || action === 'zoom-out') {
      const i = currentScaleIndex();
      const next = SCALE_STEPS[Math.min(SCALE_STEPS.length - 1, Math.max(0, i + (action === 'zoom-in' ? 1 : -1)))];
      return send('base_scale', next);
    }
  }

  function onChange(event) {
    if (event.target.closest?.('[data-ic="size"]')) send('canvas_size', event.target.value);
  }

  function onInput(event) {
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
      // 손잡이는 그림의 한가운데를 가리키므로, 좌상단 오프셋으로 되돌려 보낸다.
      posStage.beginDrag(event, handle, 'base', (x, y) => {
        const {w, h} = canvasSize();
        const pos = contentToPercent(x, y, w, h);
        handle.style.left = pos.left;
        handle.style.top = pos.top;
        pendingOffset = {
          x: Math.round(x - placedW / 2),
          y: Math.round(y - placedH / 2),
        };
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
      onDragEnd: () => render(),
    });
  }

  return {
    render,
    /** 생성이 끝나면 결과를 봐야 한다 - 캔버스가 결과를 가리고 있으면 안 된다. */
    showResult() { setViewMode('result'); },
    handleModuleState(payload) {
      if (payload && payload.module_id === 'img2img') render(payload);
    },
  };
}
