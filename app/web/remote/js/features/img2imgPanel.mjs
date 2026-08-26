export function createImg2ImgPanel({
  document,
  moduleBody,
  escHtml,
  setModuleParam,
  onModTextEdit,
  flushPendingModuleEdit,
  showToast,
  bindTagAssist = () => {},
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
  hideInpaintStrength = () => false,
  // 이 패널이 지금 화면을 소유하고 있는가. V5 인페인트는 팝업을 열지 않고 Result 안
  // 가상 캔버스에서 고치는데, 마스크 편집기는 여전히 **이 패널의 상태**를 본다.
  isOpen = () => true,
}) {
  const MASK_CELL_SIZE = 8;
  // 브러시 한계와 휠 한 칸. 슬라이더의 min/max/step 과 **같은 값**이어야 한다 -
  // 어긋나면 휠로만 갈 수 있는 크기가 생겨 슬라이더가 거짓말한다.
  const MASK_BRUSH_MIN = 8;
  const MASK_BRUSH_MAX = 160;
  const MASK_BRUSH_STEP = 8;
  const MASK_OVERLAY_COLOR = 'rgba(0, 0, 255, 0.47)';
  const sliderDebounce = {};
  const sliderPending = {};
  const maskDrafts = new Map();
  const maskCanvasDrafts = new WeakMap();
  let currentState = null;
  // 마스크 편집기를 열 때 건 것들(키·휠·리사이즈·본문 스크롤 잠금)을 되돌리는 함수.
  let maskDialogTeardown = null;
  let maskBrushSize = 48;
  let maskMode = 'paint';
  let lastRenderedStructureSignature = '';
  let deferredFocusedRenderState = null;
  let deferredFocusTarget = null;

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

  function focusedImg2imgTextarea() {
    const active = document.activeElement;
    if (!active || !moduleBody.contains(active) || active.tagName !== 'TEXTAREA') return null;
    const cls = active.classList;
    if (!cls) return null;
    if (cls.contains('mod-img2img-main-prompt')
      || cls.contains('mod-img2img-negative-prompt')
      || cls.contains('mod-char-prompt')
      || cls.contains('mod-char-uc')) {
      return active;
    }
    return null;
  }

  function img2imgStructureSignature(state) {
    if (!state || !state.active) return 'inactive';
    const characters = Array.isArray(state.characters) ? state.characters : [];
    // Everything that changes the DOM structure, EXCLUDING the prompt text
    // (main / negative / per-character) so a server echo for a local text edit
    // keeps the same signature and never replaces the focused textarea.
    // can_generate / requires_mask are mask/image-derived (not prompt-derived,
    // see headless_img2img_service), so including them keeps the generate button
    // fresh without destabilising the signature while typing.
    return JSON.stringify({
      mode: String(state.mode || '').toLowerCase(),
      can_generate: !!state.can_generate,
      requires_mask: !!state.requires_mask,
      has_mask: !!state.has_mask,
      has_mask_preview: !!state.mask_preview,
      has_preview: !!state.preview,
      generation_status: String(state.generation_status || 'idle'),
      width: Number(state.width) || 0,
      height: Number(state.height) || 0,
      resize_1mp: state.resize_1mp !== false,
      source_label: String(state.source_label || ''),
      characters: characters.map(character => [character?.id, !!character?.active]),
    });
  }

  function clearDeferredFocusedRender() {
    if (deferredFocusTarget) {
      deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
    }
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
  }

  function queueDeferredFocusedRender(textarea, state) {
    deferredFocusedRenderState = state;
    if (deferredFocusTarget === textarea) return;
    if (deferredFocusTarget) {
      deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
    }
    deferredFocusTarget = textarea;
    textarea.addEventListener('blur', flushDeferredFocusedRender, {once: true});
  }

  function flushDeferredFocusedRender() {
    const pendingState = deferredFocusedRenderState;
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
    if (!pendingState) return;
    setTimeoutFn(() => {
      if (!focusedImg2imgTextarea()) render(pendingState);
    }, 0);
  }

  function bindPromptTagAssist() {
    // Tag autocomplete on the img2img/inpaint prompt fields (main + negative +
    // character prompts), matching the main prompt box. The UC fields (.mod-uc) are
    // excluded, same convention as the Character panel. Must run after every full
    // render because moduleBody.innerHTML replaces the textarea elements.
    moduleBody.querySelectorAll('.mod-textarea:not(.mod-uc)').forEach(element => bindTagAssist(element));
  }

  function render(state) {
    // 팝업이 닫혀 있으면 상태만 받아 두고 나간다.
    // ⚠️ `moduleBody` 는 **모든 모듈이 나눠 쓰는 한 칸**이다 - 여기서 그리면 지금 열려
    //    있는 남의 모듈 화면을 덮어쓴다. 그래도 상태는 최신이어야 한다: V5 캔버스에서
    //    부르는 마스크 편집기가 `currentState` 로 세션을 확인하기 때문이다.
    // ⚠️ 이 검사는 `isOpen()` 게이트 **앞**이어야 한다. V5 는 팝업을 안 열어 늘
    //    조기 반환하는데, 그러면 열려 있는 마스크 편집창이 옛 캔버스 크기로 남고
    //    적용할 때 늘어난 잘못된 마스크가 저장된다(Codex 리뷰 CONCERN 1).
    if (state && state.active) {
      const liveCanvas = document.getElementById('img2imgMaskDialogCanvas');
      const liveDraft = liveCanvas ? maskCanvasDrafts.get(liveCanvas) : null;
      if (liveDraft
        && (liveDraft.sourceWidth !== (Number(state.width) || 0)
          || liveDraft.sourceHeight !== (Number(state.height) || 0))) {
        closeMaskEditor();
      }
    }
    if (!isOpen()) {
      currentState = (state && state.active) ? state : null;
      // 다시 열릴 때 반드시 새로 그리도록 - 서명을 남겨 두면 건너뛴다.
      lastRenderedStructureSignature = null;
      if (!currentState) closeMaskEditor();
      return;
    }
    const structureSignature = img2imgStructureSignature(state);
    const focusedTextarea = focusedImg2imgTextarea();
    if (focusedTextarea && state && state.active && lastRenderedStructureSignature === structureSignature) {
      // A server echo for a local text edit must not rebuild moduleBody.innerHTML:
      // replacing the focused textarea drops focus and collapses tag autocomplete
      // mid-typing (same regression fixed for the NAID4 Character panel, 38d3898).
      // Stash the latest state and flush it once the textarea blurs.
      currentState = state || null;
      queueDeferredFocusedRender(focusedTextarea, state);
      return;
    }
    clearDeferredFocusedRender();
    lastRenderedStructureSignature = structureSignature;
    currentState = state || null;
    if (state && state.active) {
      // 세션 해상도가 바뀌면(1MP 리사이즈 토글 등, 분리창 동시 편집 포함) 열린 마스크
      // 편집창의 캔버스 좌표 기준이 무너지므로 닫는다. 초안은 재오픈 시
      // draftMatchesState가 치수 불일치를 감지해 새로 만든다.
      const dialogCanvas = document.getElementById('img2imgMaskDialogCanvas');
      const dialogDraft = dialogCanvas ? maskCanvasDrafts.get(dialogCanvas) : null;
      if (dialogDraft
        && (dialogDraft.sourceWidth !== (Number(state.width) || 0)
          || dialogDraft.sourceHeight !== (Number(state.height) || 0))) {
        closeMaskEditor();
      }
    }
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
    const resize1mp = state.resize_1mp !== false;
    const characters = Array.isArray(state.characters) ? state.characters : [];
    const inpaint = isInpaint(state);
    const preview = state.preview
      ? `<img class="mod-img2img-preview-img" src="${state.preview}" alt="">`
      : '<div class="mod-empty">미리보기 없음</div>';
    const sourcePreview = renderSourcePreview(state);
    const generateLabel = inpaint ? '인페인트 생성' : '생성';
    const generateDisabled = state.can_generate ? '' : 'disabled';
    const generateTitle = state.requires_mask ? ' title="생성 전에 인페인트 마스크를 적용하세요"' : '';
    // V3 인페인트는 디노이징(강도) 개념이 없어 강도 슬라이더를 숨긴다(사용자 확인). V4/V4.5
    // 인페인트와 일반 img2img 는 그대로 표시.
    const hideStrength = inpaint && hideInpaintStrength();
    const strengthHtml = hideStrength ? '' : `
        <div class="mod-img2img-range">
          <label>강도 <strong id="img2imgStrengthValue">${formatRatio(state.strength_value)}</strong></label>
          <input type="range" min="1" max="99" value="${strength}" oninput="img2imgSlider('strength', this.value)">
        </div>`;
    const controlsHtml = `
      <div class="mod-img2img-controls">${strengthHtml}
        <div class="mod-img2img-range">
          <label>노이즈 <strong id="img2imgNoiseValue">${formatRatio(state.noise_value)}</strong></label>
          <input type="range" min="0" max="99" value="${noise}" oninput="img2imgSlider('noise', this.value)">
        </div>
        <div class="mod-field mod-img2img-repeat">
          <label class="mod-field-label">반복</label>
          <input class="mod-input" type="number" min="1" max="99" value="${repeat}" oninput="img2imgRepeat(this.value)">
        </div>
        <label class="mod-checkbox-item mod-img2img-resize-1mp" title="체크 시 이미지와 가장 가까운 비율의 64배수 ~1MP 해상도로 리사이즈해 생성합니다. 해제 시 원본 크기를 최대한 유지하되 NAI 제약에 맞춰 64배수 보정 및 1MP 초과 축소가 적용될 수 있습니다.">
          <input type="checkbox" ${resize1mp ? 'checked' : ''} oninput="img2imgResize1mp(this.checked)">
          <span class="mod-checkbox-label">해상도를 1MP로 리사이즈</span>
        </label>
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
    const generationStatus = String(state.generation_status || 'idle');
    const generationStatusLabels = {
      submitting: '생성 요청을 준비하는 중…',
      queued: '생성 큐에 등록됨 · 창을 닫아도 마스크는 유지됩니다.',
      running: '생성 중 · 완료 후 같은 마스크로 다시 시도할 수 있습니다.',
      completed: '생성 완료 · 같은 마스크로 다시 시도할 수 있습니다.',
      completed_with_errors: '일부 생성 실패 · 현재 마스크로 다시 시도할 수 있습니다.',
      error: state.generation_error || '생성 실패 · 현재 마스크로 다시 시도할 수 있습니다.',
    };
    const lifecycleHtml = generationStatusLabels[generationStatus]
      ? `<div class="mod-img2img-generation-status" data-status="${escHtml(generationStatus)}">${escHtml(generationStatusLabels[generationStatus])}</div>`
      : '';
    const actionsHtml = `
      ${lifecycleHtml}
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
      bindPromptTagAssist();
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
    bindPromptTagAssist();
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
        <div class="mod-img2img-mask-dialog-stage" id="img2imgMaskDialogStage">
          <!-- 항상 보이는 반투명 가이드(사용자 지정 2026-08-26).
               ⚠️ 클릭이 안 먹어야 하고, 그림과 겹치면 **그림이 이긴다** - 그래서
                  pointer-events:none + 프레임보다 낮은 z-index 다. -->
          <div class="mod-img2img-mask-guide" aria-hidden="true">
            <div><kbd>휠</kbd><span>브러시 크기</span></div>
            <div><kbd>TAB</kbd><span>칠하기 / 지우기</span></div>
            <div><kbd>ENTER</kbd><span>마스크 적용</span></div>
            <div><kbd>ESC</kbd><span>취소하고 닫기</span></div>
          </div>
          <div class="mod-img2img-mask-frame" id="img2imgMaskDialogFrame">
            ${preview}
            <canvas id="img2imgMaskDialogCanvas" class="mod-img2img-mask-canvas" aria-label="인페인트 마스크"></canvas>
          </div>
        </div>
      </div>`;
    dialog.addEventListener('click', event => {
      if (event.target === dialog) closeMaskEditor();
    });
    document.body.appendChild(dialog);
    bindMaskDialogShell(dialog);
    setTimeoutFn(() => {
      setupMaskCanvas(currentState, {
        canvasId: 'img2imgMaskDialogCanvas',
        imageId: 'img2imgMaskDialogBase',
      });
      fitMaskFrame();
    }, 0);
  }

  /** 그림을 스테이지에 **비율 그대로** 앉힌다.
   *
   *  ⚠️ CSS 로는 안 된다. 프레임은 `inline-block` 이라 높이가 auto 이고, 그 안의
   *     `<img>` 가 `max-height: 100%` 를 쓰면 auto 높이에 대한 백분율이라 **무시된다**
   *     (순환 의존). 그래서 그림이 스테이지를 넘고 스크롤이 생겼다(사용자 지적).
   *  ⚠️ 캔버스는 프레임에 `inset: 0` 으로 겹쳐 있으므로, 프레임을 px 로 못 박으면
   *     캔버스도 따라온다 - 좌표가 어긋날 자리가 없다.
   */
  function fitMaskFrame() {
    const stage = document.getElementById('img2imgMaskDialogStage');
    const frame = document.getElementById('img2imgMaskDialogFrame');
    const image = document.getElementById('img2imgMaskDialogBase');
    if (!stage || !frame || !image) return;
    const natW = image.naturalWidth || Number(currentState?.preview_width) || 0;
    const natH = image.naturalHeight || Number(currentState?.preview_height) || 0;
    if (!(natW > 0) || !(natH > 0)) return;
    const style = getComputedStyle(stage);
    const availW = stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const availH = stage.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    if (!(availW > 0) || !(availH > 0)) return;
    // ⚠️ 1 을 넘기지 않는다. 640px 미리보기를 늘리면 붓 자국만 뭉개진다.
    const scale = Math.min(availW / natW, availH / natH, 1);
    frame.style.width = `${Math.round(natW * scale)}px`;
    frame.style.height = `${Math.round(natH * scale)}px`;
  }

  /** 창 껍데기: 휠·단축키·리사이즈·본문 스크롤 잠금. 닫을 때 전부 되돌린다. */
  function bindMaskDialogShell(dialog) {
    const image = dialog.querySelector('#img2imgMaskDialogBase');
    if (image && !image.complete) image.addEventListener('load', fitMaskFrame, {once: true});

    // 휠은 **브러시 크기**다(사용자 지정). 기본 동작을 막아야 뒤 페이지가 안 굴러간다.
    const onWheel = event => {
      event.preventDefault();
      const step = event.deltaY < 0 ? MASK_BRUSH_STEP : -MASK_BRUSH_STEP;
      maskBrush(maskBrushSize + step);
      const slider = dialog.querySelector('.mod-img2img-mask-brush input[type="range"]');
      if (slider) slider.value = String(maskBrushSize);
    };
    dialog.addEventListener('wheel', onWheel, {passive: false});

    const onKeyDown = event => {
      if (!document.getElementById('img2imgMaskDialog')) return;
      const key = event.key;
      if (key !== 'Escape' && key !== 'Tab' && key !== 'Enter') return;
      // ⚠️ 브러시 슬라이더에 포커스가 있어도 가로챈다 - 이 창에서 Enter/Tab/Esc 가
      //    할 일은 하나뿐이고, 놓치면 포커스가 창 밖으로 빠져나간다.
      event.preventDefault();
      event.stopPropagation();
      if (key === 'Escape') return closeMaskEditor();
      if (key === 'Tab') return setMaskMode(maskMode === 'paint' ? 'erase' : 'paint');
      applyMask();
    };
    // ⚠️ capture 로 받는다. 전역 Escape 핸들러가 먼저 채 가면 이 창만 남고 다른 것이
    //    닫힌다.
    document.addEventListener('keydown', onKeyDown, true);

    const onResize = () => fitMaskFrame();
    window.addEventListener('resize', onResize);

    // 뒤 페이지가 굴러가지 않게(사용자 지정). 원래 값을 기억해 두고 되돌린다.
    const bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    maskDialogTeardown = () => {
      dialog.removeEventListener('wheel', onWheel);
      document.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('resize', onResize);
      document.body.style.overflow = bodyOverflow;
      maskDialogTeardown = null;
    };
  }

  function closeMaskEditor() {
    if (maskDialogTeardown) maskDialogTeardown();
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

  function resize1mp(checked) {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'resize_1mp', String(!!checked));
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
    const raw = Math.round(Number(value) || 48);
    maskBrushSize = Math.max(MASK_BRUSH_MIN, Math.min(MASK_BRUSH_MAX, raw));
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

  // 모델 변경 등 외부 요인으로 강도 슬라이더 표시 여부가 바뀔 때 캐시된 상태로 재렌더한다.
  function refresh() {
    if (currentState) render(currentState);
  }

  return {
    render,
    refresh,
    slider,
    repeat,
    resize1mp,
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
