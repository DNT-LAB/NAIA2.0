export function createImg2ImgPanel({
  document,
  moduleBody,
  escHtml,
  setModuleParam,
  onModTextEdit,
  flushPendingModuleEdit,
  showToast,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
}) {
  const MASK_CELL_SIZE = 8;
  const MASK_OVERLAY_COLOR = 'rgba(0, 0, 255, 0.47)';
  const sliderDebounce = {};
  const sliderPending = {};
  const maskDrafts = new Map();
  const maskCanvasDrafts = new WeakMap();
  let currentState = null;
  let maskBrushSize = 48;
  let maskMode = 'paint';

  function formatRatio(value, fallback = '0.00') {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return number.toFixed(2);
  }

  function renderCharacter(character, index) {
    return `
      <div class="mod-char-block mod-img2img-char" data-img2img-char-index="${index}">
        <div class="mod-char-header">
          <label class="mod-checkbox-item" style="margin:0">
            <input type="checkbox" ${character.active ? 'checked' : ''} oninput="img2imgSetCharacterActive(${index}, this.checked)">
            <span class="mod-checkbox-label">C${character.id || index + 1}</span>
          </label>
          <button type="button" class="mod-btn-sm mod-btn-danger" onclick="img2imgRemoveCharacter(${index})">제거</button>
        </div>
        <textarea class="mod-textarea mod-char-prompt" placeholder="캐릭터 프롬프트..." oninput="img2imgText('char_prompt_${index}', this.value)">${escHtml(character.prompt || '')}</textarea>
        <textarea class="mod-textarea mod-uc mod-char-uc" placeholder="네거티브 프롬프트 (UC)..." oninput="img2imgText('char_uc_${index}', this.value)">${escHtml(character.uc || '')}</textarea>
      </div>`;
  }

  function isInpaint(state) {
    return String(state?.mode || '').toLowerCase() === 'inpaint';
  }

  function cssUrlString(value) {
    return String(value || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/[\r\n]/g, '');
  }

  function renderSourcePreview(state) {
    if (!state?.preview) return '<div class="mod-empty">미리보기 없음</div>';
    const mask = state.mask_preview
      ? `<div class="mod-img2img-source-mask" style="--img2img-mask-url:url('${escHtml(cssUrlString(state.mask_preview))}')"></div>`
      : '';
    return `
      <div class="mod-img2img-source-preview-frame">
        <img class="mod-img2img-source-img" src="${state.preview}" alt="">
        ${mask}
      </div>`;
  }

  function sessionKey(state = currentState) {
    return String(state?.window_id || '');
  }

  function sourceDimensions(state = currentState) {
    const width = Math.max(1, Math.floor(Number(state?.width) || Number(state?.preview_width) || 1));
    const height = Math.max(1, Math.floor(Number(state?.height) || Number(state?.preview_height) || 1));
    return {width, height};
  }

  function gridDimensions(width, height) {
    return {
      gridWidth: Math.max(1, Math.floor(width / MASK_CELL_SIZE)),
      gridHeight: Math.max(1, Math.floor(height / MASK_CELL_SIZE)),
    };
  }

  function createMaskDraft(state = currentState) {
    const {width, height} = sourceDimensions(state);
    const {gridWidth, gridHeight} = gridDimensions(width, height);
    return {
      sourceWidth: width,
      sourceHeight: height,
      gridWidth,
      gridHeight,
      cells: new Uint8Array(gridWidth * gridHeight),
    };
  }

  function draftMatchesState(draft, state = currentState) {
    if (!draft || !state) return false;
    const {width, height} = sourceDimensions(state);
    const {gridWidth, gridHeight} = gridDimensions(width, height);
    return draft.sourceWidth === width
      && draft.sourceHeight === height
      && draft.gridWidth === gridWidth
      && draft.gridHeight === gridHeight
      && draft.cells?.length === gridWidth * gridHeight;
  }

  function getOrCreateMaskDraft(state = currentState) {
    const key = sessionKey(state);
    let draft = key ? maskDrafts.get(key) : null;
    if (!draftMatchesState(draft, state)) {
      draft = createMaskDraft(state);
      if (key) maskDrafts.set(key, draft);
    }
    return draft;
  }

  function countMaskCells(draft) {
    if (!draft?.cells) return 0;
    let count = 0;
    for (let i = 0; i < draft.cells.length; i += 1) {
      if (draft.cells[i]) count += 1;
    }
    return count;
  }

  function renderMaskEditor(state) {
    if (!isInpaint(state)) return '';
    const draft = maskDrafts.get(sessionKey(state));
    const hasDraft = countMaskCells(draft) > 0;
    const status = hasDraft
      ? '마스크 초안 준비됨. 편집창에서 적용하세요.'
      : state.has_mask
      ? '마스크 적용됨'
      : '생성 전에 마스크를 그리고 적용하세요.';
    return `
      <div class="mod-img2img-mask-editor mod-img2img-mask-compact">
        <div class="mod-img2img-mask-top">
          <div>
            <div class="mod-section-label">인페인트 마스크</div>
            <div class="mod-img2img-mask-status" id="img2imgMaskStatus" data-img2img-mask-status>${escHtml(status)}</div>
          </div>
        </div>
        <div class="mod-img2img-mask-compact-actions">
          <button type="button" class="mod-action-btn mod-start" onclick="img2imgOpenMaskEditor()">Edit Mask</button>
          <button type="button" class="mod-btn-secondary" onclick="img2imgClearMask()">초기화</button>
        </div>
      </div>`;
  }

  function render(state) {
    currentState = state || null;
    if (!state || !state.active) {
      closeMaskEditor();
      moduleBody.innerHTML = `
        <div class="mod-empty">
          활성 Img2Img 세션이 없습니다. 결과 이미지 컨텍스트 메뉴나 이미지 붙여넣기로 이미지를 전송하세요.
        </div>`;
      return;
    }

    const strength = Number.isFinite(Number(state.strength)) ? Number(state.strength) : 70;
    const noise = Number.isFinite(Number(state.noise)) ? Number(state.noise) : 0;
    const repeat = Number.isFinite(Number(state.repeat)) ? Number(state.repeat) : 1;
    const characters = Array.isArray(state.characters) ? state.characters : [];
    const inpaint = isInpaint(state);
    const preview = state.preview
      ? `<img class="mod-img2img-preview-img" src="${state.preview}" alt="">`
      : '<div class="mod-empty">미리보기 없음</div>';
    const sourcePreview = renderSourcePreview(state);
    const generateLabel = inpaint ? '인페인트 생성' : '생성';
    const generateDisabled = state.can_generate ? '' : 'disabled';
    const generateTitle = state.requires_mask ? ' title="생성 전에 인페인트 마스크를 적용하세요"' : '';
    const controlsHtml = `
      <div class="mod-img2img-controls">
        <div class="mod-img2img-range">
          <label>강도 <strong id="img2imgStrengthValue">${formatRatio(state.strength_value)}</strong></label>
          <input type="range" min="1" max="99" value="${strength}" oninput="img2imgSlider('strength', this.value)">
        </div>
        <div class="mod-img2img-range">
          <label>노이즈 <strong id="img2imgNoiseValue">${formatRatio(state.noise_value)}</strong></label>
          <input type="range" min="0" max="99" value="${noise}" oninput="img2imgSlider('noise', this.value)">
        </div>
        <div class="mod-field mod-img2img-repeat">
          <label class="mod-field-label">반복</label>
          <input class="mod-input" type="number" min="1" max="99" value="${repeat}" oninput="img2imgRepeat(this.value)">
        </div>
      </div>`;
    const promptsHtml = `
      <div class="mod-img2img-prompt-block">
        <div class="mod-section-label">메인 프롬프트</div>
        <textarea class="mod-textarea mod-textarea-lg mod-img2img-main-prompt" id="img2imgMainPrompt" oninput="img2imgText('main_prompt', this.value)">${escHtml(state.main_prompt || '')}</textarea>
      </div>
      <div class="mod-img2img-prompt-block">
        <div class="mod-section-label">네거티브 프롬프트</div>
        <textarea class="mod-textarea mod-img2img-negative-prompt" id="img2imgNegativePrompt" oninput="img2imgText('negative_prompt', this.value)">${escHtml(state.negative_prompt || '')}</textarea>
      </div>`;
    const charactersHtml = `
      <div class="mod-char-actions">
        <button type="button" class="mod-btn-sm" onclick="img2imgAddCharacter()">+ 캐릭터 추가</button>
        <span class="mod-char-meta">캐릭터 슬롯 ${characters.length}개</span>
      </div>
      ${characters.map(renderCharacter).join('')}`;
    const actionsHtml = `
      <div class="mod-img2img-actions">
        <button type="button" class="mod-action-btn mod-start" ${generateDisabled}${generateTitle} onclick="img2imgGenerate()">${generateLabel}</button>
        <button type="button" class="mod-btn-secondary" onclick="img2imgClose()">세션 닫기</button>
      </div>`;

    if (inpaint) {
      moduleBody.innerHTML = `
        <div class="mod-img2img mod-img2img-inpaint">
          <div class="mod-img2img-inpaint-layout">
            <section class="mod-img2img-primary">
              ${promptsHtml}
              ${charactersHtml}
            </section>
            <aside class="mod-img2img-side">
              <div class="mod-img2img-source-card">
                <div class="mod-section-label">소스</div>
                <div class="mod-img2img-source-preview">${sourcePreview}</div>
                <div class="mod-info-chip">${escHtml(state.source_label || '결과 이미지')}</div>
                <div class="mod-img2img-meta">${escHtml(state.mode || 'inpaint')} · ${Number(state.width) || 0}×${Number(state.height) || 0}</div>
              </div>
              ${renderMaskEditor(state)}
              ${controlsHtml}
              ${actionsHtml}
            </aside>
          </div>
        </div>`;
      if (document.getElementById('img2imgMaskDialogCanvas')) {
        setTimeoutFn(() => updateMaskStatus(activeMaskCanvas(), currentState), 0);
      }
      return;
    }

    moduleBody.innerHTML = `
      <div class="mod-img2img">
        <div class="mod-img2img-body">
          <div class="mod-img2img-head">
            <div class="mod-img2img-preview">${preview}</div>
            <div class="mod-img2img-summary">
              <div class="mod-section-label">소스</div>
              <div class="mod-info-chip">${escHtml(state.source_label || '결과 이미지')}</div>
              <div class="mod-img2img-meta">${escHtml(state.mode || 'img2img')} · ${Number(state.width) || 0}×${Number(state.height) || 0}</div>
            </div>
          </div>
          <div class="mod-img2img-tune">
            ${controlsHtml}
            ${actionsHtml}
          </div>
        </div>

        ${renderMaskEditor(state)}

        ${promptsHtml}
        ${charactersHtml}
      </div>`;
  }

  function openMaskEditor() {
    if (!currentState || !isInpaint(currentState)) {
      showToast('활성 인페인트 세션이 없습니다', 'error');
      return;
    }
    closeMaskEditor();
    const preview = currentState.preview
      ? `<img id="img2imgMaskDialogBase" src="${currentState.preview}" alt="">`
      : '<div class="mod-empty">미리보기 없음</div>';
    const dialog = document.createElement('div');
    dialog.id = 'img2imgMaskDialog';
    dialog.className = 'mod-img2img-mask-dialog open';
    dialog.innerHTML = `
      <div class="mod-img2img-mask-dialog-card" role="dialog" aria-label="인페인트 마스크 편집">
        <div class="mod-img2img-mask-dialog-header">
          <div>
            <div class="module-popup-title">Edit Mask</div>
            <div class="mod-img2img-mask-status" data-img2img-mask-status id="img2imgMaskDialogStatus"></div>
          </div>
          <button type="button" class="history-close" onclick="img2imgCloseMaskEditor()">&times;</button>
        </div>
        <div class="mod-img2img-mask-dialog-tools">
          <div class="mod-img2img-mask-actions">
            <button type="button" class="mod-btn-sm${maskMode === 'paint' ? ' active' : ''}" data-mask-mode="paint" onclick="img2imgMaskMode('paint')">칠하기</button>
            <button type="button" class="mod-btn-sm${maskMode === 'erase' ? ' active' : ''}" data-mask-mode="erase" onclick="img2imgMaskMode('erase')">지우기</button>
            <button type="button" class="mod-btn-sm" onclick="img2imgClearMask()">초기화</button>
          </div>
          <label class="mod-img2img-mask-brush">
            브러시
            <input type="range" min="8" max="160" step="8" value="${maskBrushSize}" oninput="img2imgMaskBrush(this.value)">
            <strong data-img2img-mask-brush-value>${maskBrushSize}</strong>
          </label>
          <button type="button" class="mod-action-btn mod-start" onclick="img2imgApplyMask()">마스크 적용</button>
        </div>
        <div class="mod-img2img-mask-dialog-stage">
          <div class="mod-img2img-mask-frame">
            ${preview}
            <canvas id="img2imgMaskDialogCanvas" class="mod-img2img-mask-canvas" aria-label="인페인트 마스크"></canvas>
          </div>
        </div>
      </div>`;
    dialog.addEventListener('click', event => {
      if (event.target === dialog) closeMaskEditor();
    });
    document.body.appendChild(dialog);
    setTimeoutFn(() => setupMaskCanvas(currentState, {
      canvasId: 'img2imgMaskDialogCanvas',
      imageId: 'img2imgMaskDialogBase',
    }), 0);
  }

  function closeMaskEditor() {
    const dialog = document.getElementById('img2imgMaskDialog');
    if (dialog) dialog.remove();
  }

  function activeMaskCanvas() {
    return document.getElementById('img2imgMaskDialogCanvas') || document.getElementById('img2imgMaskCanvas');
  }

  function setupMaskCanvas(state, ids = {}) {
    const canvas = document.getElementById(ids.canvasId || 'img2imgMaskCanvas');
    const image = document.getElementById(ids.imageId || 'img2imgMaskBase');
    if (!canvas || !image) return;

    const key = sessionKey(state);
    let drawing = false;
    let lastPoint = null;

    const initialize = () => {
      const draft = getOrCreateMaskDraft(state);
      maskCanvasDrafts.set(canvas, draft);
      if (canvas.width !== draft.sourceWidth || canvas.height !== draft.sourceHeight) {
        canvas.width = draft.sourceWidth;
        canvas.height = draft.sourceHeight;
      }
      if (countMaskCells(draft) <= 0 && state.mask_preview) {
        loadMaskToCanvas(canvas, state.mask_preview);
      } else {
        renderMaskCanvas(canvas, draft);
      }
      updateMaskStatus(canvas, state);
    };

    if (image.complete) initialize();
    else image.addEventListener('load', initialize, {once: true});

    canvas.addEventListener('contextmenu', event => event.preventDefault());
    canvas.addEventListener('pointerdown', event => {
      event.preventDefault();
      drawing = true;
      lastPoint = canvasPoint(canvas, event);
      try { canvas.setPointerCapture(event.pointerId); } catch (_) { /* noop */ }
      drawMaskPoint(canvas, lastPoint, event.button === 2 || maskMode === 'erase');
      rememberMaskDraft(canvas, key);
      updateMaskStatus(canvas, state);
    });
    canvas.addEventListener('pointermove', event => {
      if (!drawing) return;
      event.preventDefault();
      const point = canvasPoint(canvas, event);
      drawMaskStroke(canvas, lastPoint, point, event.buttons === 2 || maskMode === 'erase');
      lastPoint = point;
      rememberMaskDraft(canvas, key);
      updateMaskStatus(canvas, state);
    });
    const stopDrawing = event => {
      if (!drawing) return;
      drawing = false;
      lastPoint = null;
      try { canvas.releasePointerCapture(event.pointerId); } catch (_) { /* noop */ }
    };
    canvas.addEventListener('pointerup', stopDrawing);
    canvas.addEventListener('pointercancel', stopDrawing);
    canvas.addEventListener('pointerleave', () => {
      drawing = false;
      lastPoint = null;
    });
  }

  function clearCanvas(canvas) {
    const draft = maskCanvasDrafts.get(canvas);
    if (draft?.cells) {
      draft.cells.fill(0);
      renderMaskCanvas(canvas, draft);
      return;
    }
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function canvasPoint(canvas, event) {
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * canvas.width;
    const y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * canvas.height;
    return {x, y};
  }

  function drawMaskPoint(canvas, point, erase = false) {
    const draft = maskCanvasDrafts.get(canvas);
    if (!draft) return;
    const gridPoint = pointToGrid(draft, point);
    paintGridBrush(draft, gridPoint.x, gridPoint.y, erase);
    renderMaskCanvas(canvas, draft);
  }

  function drawMaskStroke(canvas, from, to, erase = false) {
    if (!from) {
      drawMaskPoint(canvas, to, erase);
      return;
    }
    const draft = maskCanvasDrafts.get(canvas);
    if (!draft) return;
    const start = pointToGrid(draft, from);
    const end = pointToGrid(draft, to);
    paintGridLine(draft, start.x, start.y, end.x, end.y, erase);
    renderMaskCanvas(canvas, draft);
  }

  function pointToGrid(draft, point) {
    return {
      x: Math.max(0, Math.min(draft.gridWidth - 1, Math.floor(point.x / MASK_CELL_SIZE))),
      y: Math.max(0, Math.min(draft.gridHeight - 1, Math.floor(point.y / MASK_CELL_SIZE))),
    };
  }

  function paintGridBrush(draft, centerX, centerY, erase = false) {
    const brushSizeGrid = Math.max(1, Math.floor((Number(maskBrushSize) || 48) / MASK_CELL_SIZE));
    const halfBrush = Math.floor(brushSizeGrid / 2);
    const value = erase ? 0 : 1;
    for (let dy = -halfBrush; dy <= halfBrush; dy += 1) {
      const y = centerY + dy;
      if (y < 0 || y >= draft.gridHeight) continue;
      for (let dx = -halfBrush; dx <= halfBrush; dx += 1) {
        const x = centerX + dx;
        if (x < 0 || x >= draft.gridWidth) continue;
        draft.cells[y * draft.gridWidth + x] = value;
      }
    }
  }

  function paintGridLine(draft, x0, y0, x1, y1, erase = false) {
    let x = x0;
    let y = y0;
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let error = dx - dy;

    while (true) {
      paintGridBrush(draft, x, y, erase);
      if (x === x1 && y === y1) break;
      const error2 = 2 * error;
      if (error2 > -dy) {
        error -= dy;
        x += sx;
      }
      if (error2 < dx) {
        error += dx;
        y += sy;
      }
    }
  }

  function renderMaskCanvas(canvas, draft = maskCanvasDrafts.get(canvas)) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!draft?.cells) return;
    ctx.fillStyle = MASK_OVERLAY_COLOR;
    for (let gy = 0; gy < draft.gridHeight; gy += 1) {
      for (let gx = 0; gx < draft.gridWidth; gx += 1) {
        if (!draft.cells[gy * draft.gridWidth + gx]) continue;
        const x = gx * MASK_CELL_SIZE;
        const y = gy * MASK_CELL_SIZE;
        ctx.fillRect(
          x,
          y,
          Math.min(MASK_CELL_SIZE, draft.sourceWidth - x),
          Math.min(MASK_CELL_SIZE, draft.sourceHeight - y),
        );
      }
    }
  }

  function loadMaskToCanvas(canvas, dataUrl) {
    const draft = maskCanvasDrafts.get(canvas);
    if (!draft) return;
    const image = new Image();
    image.onload = () => {
      const tmp = document.createElement('canvas');
      tmp.width = draft.sourceWidth;
      tmp.height = draft.sourceHeight;
      const tmpCtx = tmp.getContext('2d');
      tmpCtx.drawImage(image, 0, 0, draft.sourceWidth, draft.sourceHeight);
      const src = tmpCtx.getImageData(0, 0, draft.sourceWidth, draft.sourceHeight);
      draft.cells.fill(0);
      for (let gy = 0; gy < draft.gridHeight; gy += 1) {
        for (let gx = 0; gx < draft.gridWidth; gx += 1) {
          let total = 0;
          let samples = 0;
          const startX = gx * MASK_CELL_SIZE;
          const startY = gy * MASK_CELL_SIZE;
          const endX = Math.min(startX + MASK_CELL_SIZE, draft.sourceWidth);
          const endY = Math.min(startY + MASK_CELL_SIZE, draft.sourceHeight);
          for (let y = startY; y < endY; y += 1) {
            for (let x = startX; x < endX; x += 1) {
              const i = (y * draft.sourceWidth + x) * 4;
              const alpha = src.data[i + 3];
              const value = alpha > 8
                ? (src.data[i] + src.data[i + 1] + src.data[i + 2]) / 3
                : 0;
              total += value;
              samples += 1;
            }
          }
          if (samples > 0 && total / samples > 127) {
            draft.cells[gy * draft.gridWidth + gx] = 1;
          }
        }
      }
      renderMaskCanvas(canvas, draft);
      rememberMaskDraft(canvas);
      updateMaskStatus(canvas, currentState);
    };
    image.src = dataUrl;
  }

  function rememberMaskDraft(canvas, key = sessionKey()) {
    if (!key) return;
    const draft = maskCanvasDrafts.get(canvas);
    if (draft) maskDrafts.set(key, draft);
  }

  function maskPixelCount(canvas) {
    return countMaskCells(maskCanvasDrafts.get(canvas));
  }

  function updateMaskStatus(canvas, state = currentState) {
    if (!canvas) return;
    const localCount = maskPixelCount(canvas);
    let text = '생성 전에 마스크를 그리고 적용하세요.';
    if (localCount > 0) {
      text = state?.has_mask ? '마스크 적용됨. 수정 후 다시 적용하면 갱신됩니다.' : '마스크 초안 준비됨. 생성 전에 적용하세요.';
    }
    document.querySelectorAll('[data-img2img-mask-status]').forEach(status => {
      status.textContent = text;
    });
  }

  function maskDataUrl(canvas) {
    const draft = maskCanvasDrafts.get(canvas);
    if (!draft) return {dataUrl: '', count: 0};
    const outCanvas = document.createElement('canvas');
    outCanvas.width = draft.sourceWidth;
    outCanvas.height = draft.sourceHeight;
    const outCtx = outCanvas.getContext('2d');
    const out = outCtx.createImageData(draft.sourceWidth, draft.sourceHeight);
    const count = countMaskCells(draft);
    for (let y = 0; y < draft.sourceHeight; y += 1) {
      for (let x = 0; x < draft.sourceWidth; x += 1) {
        const gx = Math.floor(x / MASK_CELL_SIZE);
        const gy = Math.floor(y / MASK_CELL_SIZE);
        const masked = gx < draft.gridWidth && gy < draft.gridHeight
          ? draft.cells[gy * draft.gridWidth + gx] > 0
          : false;
        const value = masked ? 255 : 0;
        const i = (y * draft.sourceWidth + x) * 4;
        out.data[i] = value;
        out.data[i + 1] = value;
        out.data[i + 2] = value;
        out.data[i + 3] = 255;
      }
    }
    outCtx.putImageData(out, 0, 0);
    return {dataUrl: outCanvas.toDataURL('image/png'), count};
  }

  function slider(key, rawValue) {
    const raw = Math.max(key === 'strength' ? 1 : 0, Math.min(99, Math.round(Number(rawValue) || 0)));
    const label = document.getElementById(key === 'strength' ? 'img2imgStrengthValue' : 'img2imgNoiseValue');
    if (label) label.textContent = formatRatio(key === 'strength' && raw === 99 ? 1 : raw / 100);
    sliderPending[key] = String(raw);
    if (sliderDebounce[key]) clearTimeoutFn(sliderDebounce[key]);
    sliderDebounce[key] = setTimeoutFn(() => commitSlider(key), 250);
  }

  function commitSlider(key) {
    if (!(key in sliderPending)) return;
    if (sliderDebounce[key]) {
      clearTimeoutFn(sliderDebounce[key]);
      delete sliderDebounce[key];
    }
    const value = sliderPending[key];
    delete sliderPending[key];
    setModuleParam('img2img', key, value);
  }

  function flushSliders() {
    Object.keys(sliderPending).forEach(commitSlider);
  }

  function repeat(value) {
    const count = Math.max(1, Math.min(99, Math.round(Number(value) || 1)));
    setModuleParam('img2img', 'repeat', String(count));
  }

  function text(key, value) {
    onModTextEdit('img2img', key, value);
  }

  function addCharacter() {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'add_character', 'true');
  }

  function removeCharacter(index) {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', `remove_character_${index}`, 'true');
  }

  function setCharacterActive(index, checked) {
    setModuleParam('img2img', `char_active_${index}`, String(checked));
  }

  function generate() {
    flushSliders();
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'generate', 'true');
  }

  function close() {
    flushPendingModuleEdit('img2img');
    closeMaskEditor();
    setModuleParam('img2img', 'close', 'true');
    showToast('Img2Img 세션을 닫았습니다', 'success');
  }

  function maskBrush(value) {
    maskBrushSize = Math.max(8, Math.min(160, Math.round(Number(value) || 48)));
    document.querySelectorAll('[data-img2img-mask-brush-value]').forEach(label => {
      label.textContent = String(maskBrushSize);
    });
  }

  function setMaskMode(mode) {
    maskMode = mode === 'erase' ? 'erase' : 'paint';
    document.querySelectorAll('.mod-img2img-mask-actions [data-mask-mode]').forEach(button => {
      button.classList.toggle('active', button.dataset.maskMode === maskMode);
    });
  }

  function applyMask() {
    const canvas = activeMaskCanvas();
    if (!canvas) {
      openMaskEditor();
      return;
    }
    const {dataUrl, count} = maskDataUrl(canvas);
    if (count < 8) {
      showToast('인페인트 마스크는 8개 이상의 8px 블록이 필요합니다', 'error');
      return;
    }
    rememberMaskDraft(canvas);
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'mask_png', dataUrl);
    closeMaskEditor();
    if (currentState) {
      render({
        ...currentState,
        has_mask: true,
        mask_preview: dataUrl,
        requires_mask: false,
        can_generate: true,
      });
    }
    showToast('인페인트 마스크를 적용했습니다', 'success');
  }

  function clearMask() {
    const canvas = activeMaskCanvas();
    if (canvas) {
      clearCanvas(canvas);
      updateMaskStatus(canvas, currentState);
    }
    const key = sessionKey();
    if (key) maskDrafts.delete(key);
    document.querySelectorAll('[data-img2img-mask-status]').forEach(status => {
      status.textContent = '생성 전에 마스크를 그리고 적용하세요.';
    });
    setModuleParam('img2img', 'clear_mask', 'true');
  }

  return {
    render,
    slider,
    repeat,
    text,
    addCharacter,
    removeCharacter,
    setCharacterActive,
    generate,
    close,
    openMaskEditor,
    closeMaskEditor,
    maskBrush,
    setMaskMode,
    applyMask,
    clearMask,
  };
}
