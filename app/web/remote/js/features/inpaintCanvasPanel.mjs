// V5 인페인트 가상 캔버스 — Result 안에서 바로 고치는 화면.
//
// 스테이지·격자·드래그는 `posStage.mjs` 를 쓴다. 캐릭터 POS 화면과 같은 몸짓이어야
// 한다는 사용자 지정(2026-08-26)이고, 그 규칙들은 실측으로 얻은 것이라 두 번 짜면
// 반드시 한쪽이 틀린다.
//
// 화면이 다루는 것은 셋:
//   · 베이스 위치(끌기) — 캔버스 안에서 그림을 민다. 비는 자리는 서버가 자동으로 연다.
//   · 베이스 변형 — 확대/회전/초기화
//   · 캐릭터 마커 — 캔버스 어디에 누구를 둘지
//
// ⚠️ 좌표는 전부 **캔버스 픽셀**로 주고받는다. 화면이 줄어 있어도 그대로다 - 화면
//    비율로 보내면 캔버스 크기를 바꾼 순간 전부 어긋난다.

import {contentToPercent, createPosStage, gridSvg} from './posStage.mjs';

const CANVAS_SIZES = ['832 x 1216', '1216 x 832', '1024 x 1024', '1152 x 896', '896 x 1152'];
const SCALE_STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];
const GRID_KEY = 'naia.inpaintcanvas.grid.v1';

export function createInpaintCanvasPanel({panel, escHtml, setModuleParam, showToast}) {
  let state = null;
  let stageEl = null;
  let posStage = null;
  // 드래그 중 계산한 베이스 오프셋. DOM 에 붙여 두면 재렌더에 함께 날아간다.
  let pendingOffset = null;
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
    // ⚠️ 드래그 중에는 절대 다시 그리지 않는다(posStage 규칙 1). 서버 echo 가 와도
    //    마찬가지다 - 끌고 있던 노드가 교체되면 드래그가 통째로 무시된다.
    if (posStage?.isDragging()) return;
    if (!state?.active) { panel.innerHTML = ''; panel.hidden = true; return; }
    panel.hidden = false;

    const {w, h} = canvasSize();
    const on = !!state.canvas_active;
    panel.innerHTML = `
      <div class="ic-bar">
        <button type="button" class="ic-btn${on ? ' is-on' : ''}" data-ic="toggle">가상 캔버스</button>
        <select class="ic-select" data-ic="size" ${on ? '' : 'disabled'} aria-label="캔버스 해상도">
          ${CANVAS_SIZES.map(label => {
            const [sw, sh] = label.split('x').map(v => parseInt(v.trim(), 10));
            const sel = (sw === w && sh === h) ? ' selected' : '';
            return `<option value="${escHtml(label)}"${sel}>${escHtml(label)}</option>`;
          }).join('')}
        </select>
        <span class="ic-sep"></span>
        <button type="button" class="ic-btn" data-ic="zoom-out" ${on ? '' : 'disabled'} title="축소">−</button>
        <span class="ic-readout">${Math.round((Number(state.base_scale) || 1) * 100)}%</span>
        <button type="button" class="ic-btn" data-ic="zoom-in" ${on ? '' : 'disabled'} title="확대">+</button>
        <button type="button" class="ic-btn" data-ic="rotate" ${on ? '' : 'disabled'} title="90° 회전">⟳</button>
        <span class="ic-readout">${Math.round(Number(state.base_rotation) || 0)}°</span>
        <button type="button" class="ic-btn" data-ic="reset" ${on ? '' : 'disabled'} title="위치·확대·회전 초기화">초기화</button>
        <span class="ic-sep"></span>
        <button type="button" class="ic-btn${showGrid ? ' is-on' : ''}" data-ic="grid" title="격자">격자</button>
      </div>
      ${on ? stageHtml(w, h) : '<div class="ic-off">가상 캔버스를 켜면 결과 안에서 바로 고칠 수 있습니다.</div>'}
    `;
    stageEl = panel.querySelector('[data-ic-stage]');
    if (stageEl) {
      // 스테이지는 캔버스 비율을 그대로 쥔다 - 좌표 환산이 비율에만 기대기 때문이다.
      stageEl.style.aspectRatio = `${w} / ${h}`;
    }
  }

  function stageHtml(w, h) {
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
    return `
      <div class="ic-stage" data-ic-stage="1">
        ${preview ? `<img class="ic-canvas" src="${escHtml(preview)}" alt="canvas" draggable="false">` : ''}
        ${showGrid ? gridSvg(w, h, {className: 'ic-grid pos-grid'}) : ''}
        <button type="button" class="ic-handle" data-ic-handle="1"
          style="left:${handle.left};top:${handle.top}" title="끌어서 베이스 이미지를 옮깁니다">✥</button>
        ${chars.map(c => {
          const p = contentToPercent(c.position.x, c.position.y, w, h);
          return `<button type="button" class="ic-marker" data-ic-marker="${c.index}"
            style="left:${p.left};top:${p.top}" title="${escHtml(c.prompt)}">${c.index + 1}</button>`;
        }).join('')}
      </div>
      <div class="ic-hint">✥ 를 끌면 베이스가 움직이고, 비는 자리는 자동으로 열립니다. 숫자를 끌면 그 캐릭터의 자리가 바뀝니다.</div>
    `;
  }

  // ── 조작 ────────────────────────────────────────────────────────────────
  function currentScaleIndex() {
    const scale = Number(state?.base_scale) || 1;
    let best = 0;
    SCALE_STEPS.forEach((step, i) => {
      if (Math.abs(step - scale) < Math.abs(SCALE_STEPS[best] - scale)) best = i;
    });
    return best;
  }

  function onClick(event) {
    const action = event.target.closest?.('[data-ic]')?.dataset.ic;
    if (!action) return;
    if (action === 'toggle') return send('canvas_active', !state?.canvas_active);
    if (action === 'grid') {
      showGrid = !showGrid;
      try { localStorage.setItem(GRID_KEY, showGrid ? '1' : '0'); } catch (_) {}
      return render();
    }
    if (action === 'reset') return send('base_reset', null);
    if (action === 'rotate') return send('base_rotation', ((Number(state?.base_rotation) || 0) + 90) % 360);
    if (action === 'zoom-in' || action === 'zoom-out') {
      const i = currentScaleIndex();
      const next = SCALE_STEPS[Math.min(SCALE_STEPS.length - 1, Math.max(0, i + (action === 'zoom-in' ? 1 : -1)))];
      return send('base_scale', next);
    }
  }

  function onChange(event) {
    if (event.target.closest?.('[data-ic="size"]')) send('canvas_size', event.target.value);
  }

  function onPointerDown(event) {
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
    if (marker) {
      posStage.beginDrag(event, marker, `char_${marker.dataset.icMarker}`);
    }
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
    panel.addEventListener('pointerdown', onPointerDown);
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
    handleModuleState(payload) {
      if (payload && payload.module_id === 'img2img') render(payload);
    },
  };
}
