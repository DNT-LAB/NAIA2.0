export function createStudioTabController({
  document,
  localStorage,
  WebSocket,
  getWs,
  getGenerating,
  promptEdit,
  negEdit,
  getResolutionOptions,
  getCurrentResolution,
  setParam,
  setPromptFields,
  generate,
  showToast,
  escHtml,
  confirmDialog = async () => false,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
  BlobRef = globalThis.Blob,
  URLRef = globalThis.URL,
  FileReaderRef = globalThis.FileReader,
}) {
  const root = document.getElementById('studioRoot');
  const STORAGE_KEY = 'naia.studio.v1';
  const DEFAULT_FRAME_COUNT = 1;
  const GENERATION_IDLE_GRACE_MS = 3500;
  const SEED_MODES = new Set(['random', 'reuse_previous', 'increment_previous']);
  // JSON Export/Import 계약 (Codex 설계 검토).
  const EXPORT_TYPE = 'naia.studio.board';
  const EXPORT_VERSION = 1;
  const MAX_IMPORT_BYTES = 16 * 1024 * 1024;  // 이미지 미포함 보드는 작음 — 악성 거대 파일 방어용 상한
  const MAX_IMPORT_FRAMES = 300;
  let importing = false;
  let state = createDefaultState();
  let selectedIndex = 0;
  let queue = [];
  let activeJob = null;
  let running = false;
  let globalOpen = false;
  let editorOpen = false;
  let importOpen = false;
  let importText = '';
  let idleFailTimer = null;
  let dragSrcIndex = null;       // 진행 중인 카드 reorder 드래그의 출발 인덱스
  let suppressNextClick = false; // 실제 드래그 직후의 click이 에디터를 토글하지 않게 차단
  let cardMenu = null;           // {el, frameId, cleanup} — body에 붙는 카드 우클릭 메뉴
  const frameImages = new Map();

  function safeText(value) {
    return String(value ?? '');
  }

  function frameId(index) {
    return `F${String(index + 1).padStart(2, '0')}`;
  }

  function frameLabel(frame, index) {
    // 사용자 지정 이름이 있으면 그것을, 없으면 위치 기반 F01 라벨을 쓴다.
    const name = safeText(frame?.name).trim();
    return name || frameId(index);
  }

  function randomSeed() {
    return String(Math.floor(Math.random() * 10000000000));
  }

  function createFrame(index) {
    return {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}-${index}`,
      name: '',
      enabled: true,
      prompt: '',
      negative: '',
      resolution: '',
      seed: '',
      status: 'idle',
      runCount: 0,
      lastSeed: '',
      lastUpdated: '',
    };
  }

  function createDefaultState() {
    return {
      prefix: '',
      postfix: '',
      globalNegative: '',
      globalResolution: '',
      repeat: 1,
      seedMode: 'random',
      fixSeed: false,
      frames: Array.from({length: DEFAULT_FRAME_COUNT}, (_, index) => createFrame(index)),
    };
  }

  function sanitizeState(raw) {
    const next = createDefaultState();
    if (!raw || typeof raw !== 'object') return next;
    next.prefix = safeText(raw.prefix);
    next.postfix = safeText(raw.postfix);
    next.globalNegative = safeText(raw.globalNegative);
    next.globalResolution = safeText(raw.globalResolution);
    next.repeat = Math.max(1, Math.min(99, Math.round(Number(raw.repeat) || 1)));
    next.seedMode = SEED_MODES.has(raw.seedMode) ? raw.seedMode : (raw.fixSeed ? 'reuse_previous' : 'random');
    next.fixSeed = Boolean(raw.fixSeed);
    if (Array.isArray(raw.frames) && raw.frames.length) {
      next.frames = raw.frames.map((frame, index) => ({
        ...createFrame(index),
        id: safeText(frame?.id) || createFrame(index).id,
        name: safeText(frame?.name).slice(0, 60),
        enabled: frame?.enabled !== false,
        prompt: safeText(frame?.prompt),
        negative: safeText(frame?.negative),
        resolution: safeText(frame?.resolution),
        seed: safeText(frame?.seed),
        status: 'idle',
        runCount: Math.max(0, Math.round(Number(frame?.runCount) || 0)),
        lastSeed: safeText(frame?.lastSeed),
        lastUpdated: safeText(frame?.lastUpdated),
      }));
    }
    return next;
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) state = sanitizeState(JSON.parse(raw));
    } catch (error) {
      console.warn('Studio state restore failed', error);
      state = createDefaultState();
    }
    selectedIndex = Math.max(0, Math.min(selectedIndex, state.frames.length - 1));
  }

  function serializeBoardState() {
    // 영속(saveState)과 JSON 내보내기(exportBoard)가 공유하는 단일 직렬화 — 필드 드리프트 방지.
    // frameImages(생성 결과 objectURL)는 휘발성이라 의도적으로 제외한다.
    return {
      prefix: state.prefix,
      postfix: state.postfix,
      globalNegative: state.globalNegative,
      globalResolution: state.globalResolution,
      repeat: state.repeat,
      seedMode: state.seedMode,
      fixSeed: state.fixSeed,
      frames: state.frames.map(frame => ({
        id: frame.id,
        name: frame.name,
        enabled: frame.enabled,
        prompt: frame.prompt,
        negative: frame.negative,
        resolution: frame.resolution,
        seed: frame.seed,
        runCount: frame.runCount,
        lastSeed: frame.lastSeed,
        lastUpdated: frame.lastUpdated,
      })),
    };
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(serializeBoardState()));
      return true;
    } catch (error) {
      console.warn('Studio state save failed', error);
      return false;
    }
  }

  function selectedFrame() {
    return state.frames[selectedIndex] || state.frames[0];
  }

  function nonEmpty(parts) {
    return parts.map(part => safeText(part).trim()).filter(Boolean);
  }

  function composePrompt(frame) {
    return nonEmpty([state.prefix, frame?.prompt, state.postfix]).join(',\n');
  }

  function composeNegative(frame) {
    return nonEmpty([state.globalNegative, frame?.negative]).join(',\n');
  }

  function parseResolution(value) {
    const match = /(\d+)\s*[x×]\s*(\d+)/i.exec(safeText(value));
    if (!match) return null;
    const width = Number(match[1]);
    const height = Number(match[2]);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
    return {width: Math.round(width), height: Math.round(height)};
  }

  function buildGenerationOverrides(frame, frameIndex, seed) {
    const prompt = composePrompt(frame);
    const negative = composeNegative(frame);
    const resolution = frame?.resolution || state.globalResolution || getCurrentResolution() || '';
    const size = parseResolution(resolution);
    const overrides = {
      input: prompt,
      _raw_input: prompt,
      random_resolution: false,
      studio_request: true,
      studio_frame_index: frameIndex,
      _remote_queue_source: 'Studio',
      _remote_queue_label: frameLabel(frame, frameIndex),
    };
    if (negative) overrides.negative_prompt = negative;
    if (size) {
      overrides.width = size.width;
      overrides.height = size.height;
    }
    if (seed) {
      const numericSeed = Number(seed);
      overrides.seed = Number.isFinite(numericSeed) ? Math.trunc(numericSeed) : seed;
    }
    return overrides;
  }

  function seedModeLabel(value = state.seedMode) {
    if (value === 'reuse_previous') return '이전 프레임 시드 재사용';
    if (value === 'increment_previous') return '이전 프레임 +1';
    return '랜덤';
  }

  function renderSeedModeOptions(value = state.seedMode) {
    return [
      ['random', '랜덤'],
      ['reuse_previous', '이전 프레임 시드 재사용'],
      ['increment_previous', '이전 프레임 +1'],
    ].map(([mode, label]) =>
      `<option value="${mode}"${mode === value ? ' selected' : ''}>${escHtml(label)}</option>`
    ).join('');
  }

  function statusText(frame) {
    if (activeJob && state.frames[activeJob.frameIndex]?.id === frame.id) return 'generating';
    if (frame.status === 'done') return 'done';
    if (frame.status === 'error') return 'failed';
    if (!frame.enabled) return 'disabled';
    return 'ready';
  }

  function renderResolutionOptions(value = '') {
    const options = [
      {value: '', label: '현재 설정'},
      ...getResolutionOptions().map(option => ({value: option, label: option})),
    ];
    if (value && !options.some(option => option.value === value)) {
      options.push({value, label: value});
    }
    if (state.globalResolution && !options.some(option => option.value === state.globalResolution)) {
      options.push({value: state.globalResolution, label: state.globalResolution});
    }
    return options.map(option =>
      `<option value="${escHtml(option.value)}"${option.value === value ? ' selected' : ''}>${escHtml(option.label)}</option>`
    ).join('');
  }

  function previewText(text, fallback = '프레임 프롬프트 없음') {
    const clean = safeText(text).replace(/\s+/g, ' ').trim();
    return escHtml(clean || fallback);
  }

  function promptItems(text, limit = 12) {
    const items = safeText(text)
      .split(/[,\n]/)
      .map(item => item.trim())
      .filter(Boolean);
    return {
      shown: items.slice(0, limit),
      overflow: Math.max(0, items.length - limit),
    };
  }

  function renderPromptList(frame) {
    const {shown, overflow} = promptItems(frame.prompt);
    if (!shown.length) {
      return '<div class="studio-frame-empty">프롬프트 없음</div>';
    }
    return `
      <ul class="studio-frame-prompt-list">
        ${shown.map(item => `<li>${escHtml(item)}</li>`).join('')}
        ${overflow ? `<li class="muted">+ ${overflow}</li>` : ''}
      </ul>`;
  }

  function renderFrameCard(frame, index) {
    const selected = index === selectedIndex;
    const open = selected && editorOpen;
    const imageUrl = frameImages.get(frame.id);
    const status = statusText(frame);
    const preview = imageUrl
      ? `<img src="${imageUrl}" alt="${escHtml(frameLabel(frame, index))}">`
      : renderPromptList(frame);
    return `
      <button type="button" class="studio-frame-card${selected ? ' selected' : ''}${open ? ' open' : ''}${frame.enabled ? '' : ' disabled'}" data-studio-frame="${index}" draggable="true" aria-expanded="${open ? 'true' : 'false'}">
        <div class="studio-frame-label">
          <span class="studio-frame-grip" aria-hidden="true">⋮⋮</span>
          <strong>${escHtml(frameLabel(frame, index))}</strong>
          <span class="studio-status-dot" data-status="${escHtml(status)}" aria-label="${escHtml(status)}"></span>
        </div>
        <div class="studio-frame-preview${imageUrl ? ' has-image' : ''}">${preview}</div>
      </button>`;
  }

  function renderAddCard() {
    return `
      <button type="button" class="studio-frame-add" data-studio-action="add-frame" aria-label="새 프레임 추가">
        <span class="studio-frame-add-icon">+</span>
        <span class="studio-frame-add-label">새 프레임</span>
      </button>`;
  }

  function renderGlobalPanel() {
    return `
      <section class="studio-global-panel${globalOpen ? ' open' : ''}">
        <button type="button" class="studio-panel-toggle" data-studio-action="toggle-global">
          <span>공통 설정</span>
          <strong>${escHtml([
            state.globalResolution || getCurrentResolution() || '',
            `${Math.max(1, state.repeat)}x`,
            seedModeLabel(),
          ].filter(Boolean).join(' · ') || '현재 메인 설정 사용')}</strong>
        </button>
        <div class="studio-global-grid">
          <div class="studio-run-settings">
            <label class="studio-field">
              <span>Global Resolution</span>
              <select data-studio-global="globalResolution">${renderResolutionOptions(state.globalResolution)}</select>
            </label>
            <label class="studio-field">
              <span>Repeat</span>
              <input type="number" min="1" max="99" value="${escHtml(String(state.repeat))}" data-studio-global="repeat">
            </label>
            <label class="studio-field">
              <span>Seed</span>
              <select data-studio-global="seedMode">${renderSeedModeOptions()}</select>
            </label>
          </div>
        </div>
      </section>`;
  }

  function renderFixedPromptPanel() {
    return `
      <section class="studio-fixed-panel">
        <label class="studio-field">
          <span>선행 고정 프레임</span>
          <textarea data-studio-global="prefix" spellcheck="false" placeholder="모든 프레임 앞에 붙일 고정 프롬프트">${escHtml(state.prefix)}</textarea>
        </label>
        <label class="studio-field">
          <span>후행 고정 프레임</span>
          <textarea data-studio-global="postfix" spellcheck="false" placeholder="모든 프레임 뒤에 붙일 고정 프롬프트">${escHtml(state.postfix)}</textarea>
        </label>
        <label class="studio-field">
          <span>공통 네거티브</span>
          <textarea data-studio-global="globalNegative" spellcheck="false" placeholder="모든 프레임에 적용할 네거티브 프롬프트">${escHtml(state.globalNegative)}</textarea>
        </label>
      </section>`;
  }

  function renderImportPanel() {
    if (!importOpen) return '';
    return `
      <section class="studio-import-panel">
        <div class="studio-import-head">
          <div>
            <div class="studio-kicker">Batch Input</div>
            <h3>줄별 프롬프트 배치</h3>
          </div>
          <button type="button" data-studio-action="toggle-import">닫기</button>
        </div>
        <textarea class="studio-import-textarea" data-studio-import-lines spellcheck="false" placeholder="한 줄에 프레임 하나씩 입력">${escHtml(importText)}</textarea>
        <div class="studio-import-actions">
          <button type="button" data-studio-action="import-lines-replace">프레임 교체</button>
          <button type="button" data-studio-action="import-lines-append" class="primary">뒤에 추가</button>
        </div>
      </section>`;
  }

  function renderEditorImage(frame) {
    const imageUrl = frameImages.get(frame.id);
    if (!imageUrl) {
      return `
        <div class="studio-editor-image empty">
          <span>${escHtml(frameLabel(frame, selectedIndex))}</span>
          <small>이미지 없음</small>
        </div>`;
    }
    return `
      <div class="studio-editor-image">
        <img src="${imageUrl}" alt="${escHtml(frameLabel(frame, selectedIndex))}">
      </div>`;
  }

  function renderEditor() {
    const frame = selectedFrame();
    if (!frame || !editorOpen) return '';
    return `
      <section class="studio-editor">
        <div class="studio-editor-head">
          <div>
            <div class="studio-kicker">Frame Editor</div>
            <h3>${escHtml(frameLabel(frame, selectedIndex))}</h3>
          </div>
          <div class="studio-editor-head-actions">
            <label class="studio-toggle">
              <input type="checkbox" data-studio-frame-field="enabled"${frame.enabled ? ' checked' : ''}>
              <span>사용</span>
            </label>
            <button type="button" data-studio-action="close-editor" aria-label="프레임 편집기 닫기">닫기</button>
          </div>
        </div>
        <div class="studio-editor-primary">
          ${renderEditorImage(frame)}
          <label class="studio-field studio-field-tall studio-frame-prompt-field">
            <span>Frame Prompt</span>
            <textarea data-studio-frame-field="prompt" spellcheck="false">${escHtml(frame.prompt)}</textarea>
          </label>
        </div>
        <label class="studio-field">
          <span>Additional Negative</span>
          <textarea data-studio-frame-field="negative" spellcheck="false" placeholder="공통 네거티브 뒤에 추가할 프레임 전용 네거티브">${escHtml(frame.negative)}</textarea>
        </label>
        <div class="studio-editor-grid">
          <label class="studio-field">
            <span>Frame Name</span>
            <input type="text" maxlength="60" data-studio-frame-field="name" value="${escHtml(frame.name)}" placeholder="${escHtml(frameId(selectedIndex))}" spellcheck="false">
          </label>
          <label class="studio-field">
            <span>Resolution</span>
            <select data-studio-frame-field="resolution">${renderResolutionOptions(frame.resolution)}</select>
          </label>
          <label class="studio-field">
            <span>Seed</span>
            <select data-studio-global="seedMode">${renderSeedModeOptions()}</select>
          </label>
        </div>
        <div class="studio-editor-actions">
          <button type="button" data-studio-action="sync-current">현재 프롬프트 가져오기</button>
          <button type="button" data-studio-action="apply-current">메인에 적용</button>
          <button type="button" data-studio-action="duplicate-frame">복제</button>
          <button type="button" data-studio-action="clear-frame">비우기</button>
          <button type="button" data-studio-action="delete-frame" class="danger">삭제</button>
          <button type="button" data-studio-action="generate-selected" class="primary">선택 생성</button>
        </div>
      </section>`;
  }

  function renderQueueSummary() {
    const enabled = state.frames.filter(frame => frame.enabled).length;
    const total = enabled * Math.max(1, state.repeat);
    const runningText = activeJob
      ? `${frameLabel(state.frames[activeJob.frameIndex], activeJob.frameIndex)} 생성 중`
      : running
      ? '대기 중'
      : '준비됨';
    return `
      <div class="studio-queue-summary">
        <span>${enabled} frames</span>
        <span>${total} jobs</span>
        <span>${escHtml(runningText)}</span>
      </div>`;
  }

  function render() {
    if (!root) return;
    // 주의: 여기서 closeCardMenu()를 호출하지 않는다. 카드 메뉴는 body에 붙고 frameId로
    // 동작하므로 보드 재렌더에도 유효하다. render()에서 닫으면, 우클릭 직후 입력 blur가
    // 유발하는 부수적 change→render()가 방금 연 메뉴를 닫아 "메뉴가 나왔다 안 나왔다"
    // 하는 경합이 생긴다(사용자 버그). 닫기는 dismiss 리스너(외부클릭/Esc/스크롤/리사이즈)와
    // 메뉴 동작 핸들러에만 맡긴다.
    const frame = selectedFrame();
    const selectedSummary = frame
      ? previewText(composePrompt(frame), '선택 프레임 없음')
      : escHtml('선택 프레임 없음');
    root.innerHTML = `
      <div class="studio-tab">
        <header class="studio-toolbar">
          <div>
            <div class="studio-kicker">Studio</div>
            <h2>다중 프레임 생성 보드</h2>
          </div>
          <div class="studio-toolbar-actions">
            <button type="button" data-studio-action="capture-current-new">현재 캡처</button>
            <button type="button" data-studio-action="toggle-import">줄별 배치</button>
            <button type="button" data-studio-action="add-frame">빈 프레임</button>
            <span class="studio-toolbar-sep" aria-hidden="true"></span>
            <button type="button" data-studio-action="export-board">JSON 내보내기</button>
            <button type="button" data-studio-action="import-board" ${running || activeJob ? 'disabled' : ''}>JSON 불러오기</button>
            <span class="studio-toolbar-sep" aria-hidden="true"></span>
            <button type="button" data-studio-action="reset-frames" ${running || activeJob ? 'disabled' : ''}>초기화</button>
            <button type="button" data-studio-action="start-sequence" class="primary" ${running || activeJob ? 'disabled' : ''}>순차 생성</button>
            <button type="button" data-studio-action="stop-sequence" class="danger" ${running || activeJob ? '' : 'disabled'}>중지</button>
          </div>
        </header>
        ${renderImportPanel()}
        ${renderGlobalPanel()}
        <main class="studio-workspace">
          <section class="studio-board">
            <div class="studio-board-head">
              ${renderQueueSummary()}
              <div class="studio-selected-summary">${selectedSummary}</div>
            </div>
            <div class="studio-frame-grid">
              ${state.frames.map(renderFrameCard).join('')}
              ${renderAddCard()}
            </div>
            ${renderEditor()}
            ${renderFixedPromptPanel()}
          </section>
        </main>
      </div>`;
  }

  function shouldRenderForInput(target) {
    const tag = String(target?.tagName || '').toLowerCase();
    if (tag === 'textarea') return false;
    if (tag === 'input') {
      const type = String(target.type || '').toLowerCase();
      return type === 'checkbox' || type === 'radio';
    }
    return true;
  }

  function updateGlobal(field, target, options = {}) {
    if (field === 'repeat') {
      state.repeat = Math.max(1, Math.min(99, Math.round(Number(target.value) || 1)));
    } else if (field === 'seedMode') {
      state.seedMode = SEED_MODES.has(target.value) ? target.value : 'random';
    } else if (field === 'fixSeed') {
      state.fixSeed = Boolean(target.checked);
    } else {
      state[field] = safeText(target.value);
    }
    saveState();
    if (options.render !== false) render();
  }

  function updateFrame(field, target, options = {}) {
    const frame = selectedFrame();
    if (!frame) return;
    if (field === 'enabled') frame.enabled = Boolean(target.checked);
    else frame[field] = safeText(target.value);
    frame.status = frame.enabled ? 'idle' : 'idle';
    saveState();
    if (options.render !== false) render();
  }

  function currentPromptFrame(index) {
    return {
      ...createFrame(index),
      prompt: promptEdit?.value || '',
      negative: negEdit?.value || '',
      resolution: getCurrentResolution() || '',
    };
  }

  function captureCurrentAsNewFrame() {
    const prompt = promptEdit?.value || '';
    const negative = negEdit?.value || '';
    if (!prompt.trim() && !negative.trim()) {
      showToast('캡처할 현재 프롬프트가 비어 있습니다', 'error');
      return;
    }
    state.frames.push(currentPromptFrame(state.frames.length));
    selectedIndex = state.frames.length - 1;
    editorOpen = true;
    saveState();
    render();
    showToast('현재 프롬프트를 새 Studio 프레임으로 캡처했습니다', 'success');
  }

  function clearSelectedFrame() {
    const frame = selectedFrame();
    if (!frame) return;
    const oldUrl = frameImages.get(frame.id);
    if (oldUrl) URL.revokeObjectURL(oldUrl);
    frameImages.delete(frame.id);
    Object.assign(frame, {
      enabled: true,
      prompt: '',
      negative: '',
      resolution: '',
      seed: '',
      status: 'idle',
      runCount: 0,
      lastSeed: '',
      lastUpdated: '',
    });
    saveState();
    render();
  }

  function selectFrame(index) {
    const nextIndex = Math.max(0, Math.min(Number(index) || 0, state.frames.length - 1));
    if (nextIndex === selectedIndex) {
      editorOpen = !editorOpen;
    } else {
      selectedIndex = nextIndex;
      editorOpen = true;
    }
    render();
  }

  // ---- 카드 드래그 reorder ----
  function clearDragIndicators() {
    if (!root) return;
    root.querySelectorAll('.studio-frame-card.drag-over-before, .studio-frame-card.drag-over-after, .studio-frame-card.dragging')
      .forEach(card => card.classList.remove('drag-over-before', 'drag-over-after', 'dragging'));
  }

  function frameIndexFromEvent(event) {
    const card = event.target?.closest?.('[data-studio-frame]');
    if (!card || (root && !root.contains(card))) return null;
    const index = Number(card.dataset.studioFrame);
    return Number.isInteger(index) ? index : null;
  }

  function onCardDragStart(event) {
    const index = frameIndexFromEvent(event);
    if (index === null) return;
    if (running || activeJob) {
      // 큐/activeJob이 프레임 인덱스를 들고 있어 reorder는 큐를 오염시킨다.
      event.preventDefault();
      showToast('Studio 생성이 끝난 뒤 순서를 바꾸세요', 'error');
      return;
    }
    dragSrcIndex = index;
    suppressNextClick = true;
    closeCardMenu();
    try {
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(index));  // Firefox는 데이터 필요
      }
    } catch (_) { /* noop */ }
    const card = event.target?.closest?.('[data-studio-frame]');
    if (card) {
      card.classList.add('dragging');
      // drop 후 render()가 이 카드를 DOM에서 떼어내면 root 위임 dragend가 안 올 수 있다
      // (Codex R1). 출발 카드에 직접 1회용 dragend를 달아 suppressNextClick 해제를 보장.
      if (card.addEventListener) card.addEventListener('dragend', onCardDragEnd, {once: true});
    }
  }

  function onCardDragOver(event) {
    if (dragSrcIndex === null) return;
    const card = event.target?.closest?.('[data-studio-frame]');
    if (!card || (root && !root.contains(card))) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    let dropAfter = false;
    const rect = card.getBoundingClientRect ? card.getBoundingClientRect() : null;
    if (rect && rect.width) dropAfter = (Number(event.clientX) - rect.left) > rect.width / 2;
    card.classList.remove('drag-over-before', 'drag-over-after');
    card.classList.add(dropAfter ? 'drag-over-after' : 'drag-over-before');
  }

  function onCardDragLeave(event) {
    const card = event.target?.closest?.('[data-studio-frame]');
    if (card) card.classList.remove('drag-over-before', 'drag-over-after');
  }

  function onCardDrop(event) {
    if (dragSrcIndex === null) return;
    const card = event.target?.closest?.('[data-studio-frame]');
    if (!card || (root && !root.contains(card))) return;
    event.preventDefault();
    const targetIndex = Number(card.dataset.studioFrame);
    let dropAfter = false;
    const rect = card.getBoundingClientRect ? card.getBoundingClientRect() : null;
    if (rect && rect.width) dropAfter = (Number(event.clientX) - rect.left) > rect.width / 2;
    const srcIndex = dragSrcIndex;
    dragSrcIndex = null;
    moveFrame(srcIndex, targetIndex, dropAfter);
    // 성공 드롭은 render()로 출발 카드를 떼어내 dragend가 누락될 수 있으므로,
    // 여기서도 suppressNextClick을 확실히 해제한다(트레일링 click이 있으면 그쪽이 먼저 소비).
    setTimeoutFn(() => { suppressNextClick = false; }, 0);
  }

  function onCardDragEnd() {
    dragSrcIndex = null;
    clearDragIndicators();
    // 드래그 후 click이 안 오는 경우(일반적), 다음 정상 click이 억제되지 않도록 해제.
    // click이 오면 그쪽이 먼저 플래그를 소비한다.
    setTimeoutFn(() => { suppressNextClick = false; }, 0);
  }

  function moveFrame(srcIndex, targetIndex, dropAfter) {
    if (!Number.isInteger(srcIndex) || !Number.isInteger(targetIndex)) { clearDragIndicators(); return; }
    if (running || activeJob) { clearDragIndicators(); return; }  // 드래그 중 생성 시작 방어
    if (srcIndex < 0 || srcIndex >= state.frames.length) { clearDragIndicators(); return; }
    let insertIndex = targetIndex + (dropAfter ? 1 : 0);
    if (insertIndex === srcIndex || insertIndex === srcIndex + 1) { clearDragIndicators(); return; }  // 제자리
    const selectedId = selectedFrame()?.id;
    const wasEditorOpen = editorOpen;
    const [moved] = state.frames.splice(srcIndex, 1);
    if (srcIndex < insertIndex) insertIndex -= 1;  // src 제거로 한 칸 당겨짐
    insertIndex = Math.max(0, Math.min(insertIndex, state.frames.length));
    state.frames.splice(insertIndex, 0, moved);
    const foundSelected = state.frames.findIndex(frame => frame.id === selectedId);
    selectedIndex = foundSelected >= 0 ? foundSelected : Math.max(0, Math.min(selectedIndex, state.frames.length - 1));
    editorOpen = wasEditorOpen;
    saveState();
    render();
  }

  // ---- 카드 우클릭 메뉴 (복제 / 삭제) ----
  function closeCardMenu() {
    if (!cardMenu) return;
    try { cardMenu.cleanup(); } catch (_) { /* noop */ }
    if (cardMenu.el && cardMenu.el.remove) cardMenu.el.remove();
    cardMenu = null;
  }

  function openCardMenu(index, x, y) {
    closeCardMenu();
    const frame = state.frames[index];
    if (!frame) return;
    // 우클릭한 프레임을 선택 상태로(에디터는 토글하지 않음). 메뉴 동작은 id로 다시 해석한다.
    selectedIndex = Math.max(0, Math.min(index, state.frames.length - 1));
    const frameId = frame.id;
    // 선택 변경을 보드에 먼저 반영(render는 더 이상 메뉴를 닫지 않음). 이전 메뉴는 위에서
    // closeCardMenu()로 교체했고, 이번 메뉴는 render() 이후 새로 만든다.
    render();
    const menu = document.createElement('div');
    menu.className = 'studio-card-menu';
    menu.innerHTML = `
      <button type="button" class="studio-card-menu-item" data-studio-card-menu="duplicate">복제</button>
      <button type="button" class="studio-card-menu-item danger" data-studio-card-menu="delete">삭제</button>`;
    if (menu.style) {
      menu.style.position = 'fixed';
      menu.style.left = `${Math.max(0, Number(x) || 0)}px`;
      menu.style.top = `${Math.max(0, Number(y) || 0)}px`;
    }
    menu.addEventListener('click', event => {
      const item = event.target?.closest?.('[data-studio-card-menu]');
      if (!item) return;
      const menuAction = item.dataset.studioCardMenu;
      closeCardMenu();
      runCardMenuAction(menuAction, frameId);
    });
    const onDocMouseDown = event => {
      if (cardMenu && cardMenu.el && cardMenu.el.contains && cardMenu.el.contains(event.target)) return;
      closeCardMenu();
    };
    const onKeyDown = event => { if (event.key === 'Escape') closeCardMenu(); };
    const onScrollOrResize = () => closeCardMenu();
    document.addEventListener('mousedown', onDocMouseDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    if (root && root.addEventListener) root.addEventListener('scroll', onScrollOrResize, true);
    if (globalThis.addEventListener) {
      globalThis.addEventListener('resize', onScrollOrResize, true);
      globalThis.addEventListener('scroll', onScrollOrResize, true);
    }
    const cleanup = () => {
      document.removeEventListener('mousedown', onDocMouseDown, true);
      document.removeEventListener('keydown', onKeyDown, true);
      if (root && root.removeEventListener) root.removeEventListener('scroll', onScrollOrResize, true);
      if (globalThis.removeEventListener) {
        globalThis.removeEventListener('resize', onScrollOrResize, true);
        globalThis.removeEventListener('scroll', onScrollOrResize, true);
      }
    };
    if (document.body) document.body.appendChild(menu);
    cardMenu = {el: menu, frameId, cleanup};
    clampCardMenu(menu, x, y);
  }

  function clampCardMenu(menu, x, y) {
    if (!menu || !menu.getBoundingClientRect || !menu.style) return;
    const rect = menu.getBoundingClientRect();
    const vw = Number(globalThis.innerWidth) || 0;
    const vh = Number(globalThis.innerHeight) || 0;
    if (vw && rect.width && (Number(x) + rect.width) > vw) menu.style.left = `${Math.max(0, vw - rect.width - 4)}px`;
    if (vh && rect.height && (Number(y) + rect.height) > vh) menu.style.top = `${Math.max(0, vh - rect.height - 4)}px`;
  }

  function runCardMenuAction(menuAction, frameId) {
    const index = state.frames.findIndex(frame => frame.id === frameId);
    if (index < 0) return;  // 메뉴가 떠 있는 동안 프레임이 사라짐
    selectedIndex = index;
    if (menuAction === 'duplicate') duplicateFrame();
    else if (menuAction === 'delete') deleteSelectedFrame();
  }

  function onCardContextMenu(event) {
    const index = frameIndexFromEvent(event);
    if (index === null) return;
    event.preventDefault();
    openCardMenu(index, event.clientX, event.clientY);
  }

  function syncSelectedFromMain() {
    const frame = selectedFrame();
    if (!frame) return;
    frame.prompt = promptEdit?.value || '';
    frame.negative = negEdit?.value || '';
    frame.resolution = getCurrentResolution() || frame.resolution || '';
    frame.status = 'idle';
    saveState();
    render();
    showToast('현재 프롬프트를 Studio 프레임에 가져왔습니다', 'success');
  }

  function applyFrameParams(frame, seed) {
    const resolution = frame.resolution || state.globalResolution;
    if (resolution) setParam('resolution', resolution);
    if (seed) {
      setParam('seed', seed);
      setParam('seed_fixed', 'true');
    }
  }

  function previousFrameSeed(index) {
    for (let i = index - 1; i >= 0; i -= 1) {
      const seed = safeText(state.frames[i]?.lastSeed).trim();
      if (seed) return seed;
    }
    return '';
  }

  function incrementSeed(seed) {
    const clean = safeText(seed).trim();
    if (!clean) return randomSeed();
    try {
      return String(BigInt(clean) + 1n);
    } catch {
      const numeric = Number(clean);
      return Number.isFinite(numeric) ? String(Math.max(0, Math.floor(numeric)) + 1) : randomSeed();
    }
  }

  function resolveSeed(frameIndex) {
    const previous = previousFrameSeed(frameIndex);
    if (state.seedMode === 'reuse_previous') return previous || randomSeed();
    if (state.seedMode === 'increment_previous') return previous ? incrementSeed(previous) : randomSeed();
    return randomSeed();
  }

  function applySelectedToMain() {
    const frame = selectedFrame();
    if (!frame) return false;
    const prompt = composePrompt(frame);
    const negative = composeNegative(frame);
    if (!prompt) {
      showToast('선택 프레임의 프롬프트가 비어 있습니다', 'error');
      return false;
    }
    const seed = resolveSeed(selectedIndex);
    frame.lastSeed = seed;
    applyFrameParams(frame, seed);
    setPromptFields(prompt, negative);
    saveState();
    return true;
  }

  function duplicateFrame() {
    const frame = selectedFrame();
    if (!frame) return;
    if (running || activeJob) {
      // 복제는 selectedIndex+1에 삽입해 인덱스를 밀어 큐를 오염시킨다 — 생성 중 차단.
      showToast('Studio 생성이 끝난 뒤 복제하세요', 'error');
      return;
    }
    const copy = {
      ...createFrame(state.frames.length),
      name: frame.name.trim() ? `${frame.name.trim()} 복사`.slice(0, 60) : '',
      enabled: frame.enabled,
      prompt: frame.prompt,
      negative: frame.negative,
      resolution: frame.resolution,
      seed: frame.seed,
    };
    state.frames.splice(selectedIndex + 1, 0, copy);
    selectedIndex += 1;
    editorOpen = true;
    saveState();
    render();
  }

  async function deleteSelectedFrame() {
    const frame = selectedFrame();
    if (!frame) return;
    if (running || activeJob) {
      // 큐/activeJob이 프레임 인덱스를 들고 있어 도중 splice는 큐를 오염시킨다.
      showToast('Studio 생성이 끝난 뒤 프레임을 삭제하세요', 'error');
      return;
    }
    if (state.frames.length <= 1) {
      showToast('마지막 프레임은 삭제할 수 없습니다 — 비우기를 사용하세요', 'error');
      return;
    }
    const targetId = frame.id;
    const hasContent = Boolean(frame.prompt.trim() || frame.negative.trim() || frameImages.get(targetId));
    if (hasContent) {
      const confirmed = await Promise.resolve(confirmDialog(
        `${frameLabel(frame, state.frames.indexOf(frame))} 프레임을 삭제할까요?`,
        {title: '프레임 삭제', okText: '삭제', cancelText: '취소'},
      ));
      if (!confirmed) return;
      // 확인 대기 중 생성이 시작되었을 수 있다 — 재검사 (Codex V6).
      if (running || activeJob) {
        showToast('Studio 생성이 끝난 뒤 프레임을 삭제하세요', 'error');
        return;
      }
    }
    // 확인 대기 중 선택/구성이 바뀌었을 수 있으므로 인덱스가 아니라 id로 다시 찾는다.
    const targetIndex = state.frames.findIndex(item => item.id === targetId);
    if (targetIndex < 0) return;
    if (state.frames.length <= 1) {
      showToast('마지막 프레임은 삭제할 수 없습니다 — 비우기를 사용하세요', 'error');
      return;
    }
    const oldUrl = frameImages.get(targetId);
    if (oldUrl) URL.revokeObjectURL(oldUrl);
    frameImages.delete(targetId);
    state.frames.splice(targetIndex, 1);
    if (selectedIndex > targetIndex) selectedIndex -= 1;
    selectedIndex = Math.max(0, Math.min(selectedIndex, state.frames.length - 1));
    saveState();
    render();
  }

  function addFrame() {
    state.frames.push(createFrame(state.frames.length));
    selectedIndex = state.frames.length - 1;
    editorOpen = true;
    saveState();
    render();
  }

  async function resetFrames() {
    // 버튼 disabled만으로는 부족 — 액션 키 디스패치 경로가 남는다 (Codex V5).
    if (running || activeJob) {
      showToast('Studio 생성이 끝난 뒤 초기화하세요', 'error');
      return;
    }
    const confirmed = await Promise.resolve(confirmDialog('Studio 보드를 기본 상태(1개 프레임)로 초기화할까요?', {
      title: 'Studio 초기화',
      okText: '초기화',
      cancelText: '취소',
    }));
    if (!confirmed) return;
    if (running || activeJob) {
      showToast('Studio 생성이 끝난 뒤 초기화하세요', 'error');
      return;
    }
    frameImages.forEach(url => URL.revokeObjectURL(url));
    frameImages.clear();
    queue = [];
    activeJob = null;
    running = false;
    selectedIndex = 0;
    editorOpen = false;
    state = createDefaultState();
    saveState();
    render();
  }

  function boardHasContent() {
    if (state.prefix.trim() || state.postfix.trim() || state.globalNegative.trim()) return true;
    return state.frames.some(frame =>
      frame.prompt.trim() || frame.negative.trim() || frame.name.trim() || frameImages.get(frame.id));
  }

  function exportTimestamp() {
    // app 코드라 new Date() 사용 가능(Workflow 스크립트 제한과 무관). 파일명용 로컬 타임스탬프.
    const now = new Date();
    const pad = value => String(value).padStart(2, '0');
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
      + `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  }

  function exportBoard() {
    // export는 읽기 전용 스냅샷 — 생성 중에도 허용 (Codex 설계 검토).
    let url = '';
    try {
      const payload = {
        type: EXPORT_TYPE,
        version: EXPORT_VERSION,
        exportedAt: new Date().toISOString(),
        storageKey: STORAGE_KEY,
        board: serializeBoardState(),
      };
      const json = JSON.stringify(payload, null, 2);
      const blob = new BlobRef([json], {type: 'application/json'});
      url = URLRef.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `naia-studio-${exportTimestamp()}.json`;
      if (document.body) document.body.appendChild(anchor);
      anchor.click();
      if (anchor.remove) anchor.remove();
      showToast(`Studio 보드를 JSON으로 내보냈습니다 (${state.frames.length} 프레임)`, 'success');
    } catch (error) {
      console.error('Studio export failed', error);
      showToast('Studio 내보내기에 실패했습니다', 'error');
    } finally {
      if (url) setTimeoutFn(() => { try { URLRef.revokeObjectURL(url); } catch (_) { /* noop */ } }, 0);
    }
  }

  function parseImportPayload(text) {
    let raw = String(text ?? '');
    if (raw.charCodeAt(0) === 0xFEFF) raw = raw.slice(1);  // UTF-8 BOM 제거
    if (raw.length > MAX_IMPORT_BYTES) return {ok: false, error: '파일이 너무 큽니다'};
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_) {
      return {ok: false, error: 'JSON 형식이 올바르지 않습니다'};
    }
    if (!parsed || typeof parsed !== 'object' || parsed.type !== EXPORT_TYPE) {
      return {ok: false, error: 'NAIA Studio 보드 파일이 아닙니다'};
    }
    // 버전 검증: 모르는(상위) 버전은 의미가 달라졌을 수 있어 조용히 받지 않는다 (Codex V8).
    const fileVersion = Number(parsed.version);
    if (!Number.isFinite(fileVersion) || fileVersion < 1) {
      return {ok: false, error: '버전 정보가 없는 파일입니다'};
    }
    if (fileVersion > EXPORT_VERSION) {
      return {ok: false, error: '더 최신 버전에서 만든 파일입니다. 앱을 업데이트하세요'};
    }
    const board = parsed.board;
    if (!board || typeof board !== 'object' || !Array.isArray(board.frames)) {
      return {ok: false, error: '보드 데이터가 없습니다'};
    }
    // 명시적 import는 빈 frames를 9칸 기본값으로 슬그머니 만들지 않는다(sanitizeState 폴백과 분리).
    if (!board.frames.length) return {ok: false, error: '프레임이 비어 있는 파일입니다'};
    if (board.frames.length > MAX_IMPORT_FRAMES) {
      return {ok: false, error: `프레임이 너무 많습니다 (최대 ${MAX_IMPORT_FRAMES}개)`};
    }
    return {ok: true, board};
  }

  function readFileText(file) {
    return new Promise((resolve, reject) => {
      let reader;
      try {
        reader = new FileReaderRef();
      } catch (error) {
        reject(error);
        return;
      }
      reader.onload = () => resolve(String(reader.result ?? ''));
      reader.onerror = () => reject(reader.error || new Error('file read failed'));
      reader.onabort = () => reject(new Error('file read aborted'));
      reader.readAsText(file);
    });
  }

  function applyImportedBoard(board) {
    // sanitizeState로 모든 필드 정규화 후, 파일 내 중복/라이브 frameImages 키 충돌을 막기 위해
    // 프레임 id를 새로 발급한다 (Codex 설계 검토).
    const sanitized = sanitizeState(board);
    sanitized.frames = sanitized.frames.map((frame, index) => ({
      ...frame,
      id: createFrame(index).id,
      status: 'idle',
    }));
    frameImages.forEach(objectUrl => { try { URLRef.revokeObjectURL(objectUrl); } catch (_) { /* noop */ } });
    frameImages.clear();
    queue = [];
    activeJob = null;
    running = false;
    state = sanitized;
    selectedIndex = 0;
    editorOpen = false;
    const saved = saveState();
    render();
    if (saved) showToast(`Studio 보드를 불러왔습니다 (${state.frames.length} 프레임)`, 'success');
    else showToast('불러왔지만 저장 공간이 부족해 영속되지 않았습니다', 'error');
  }

  async function handleImportFile(file) {
    if (!file) return;
    if (running || activeJob) {
      showToast('Studio 생성이 끝난 뒤 불러오세요', 'error');
      return;
    }
    if (importing) return;
    if (Number(file.size) > MAX_IMPORT_BYTES) {
      showToast('파일이 너무 큽니다', 'error');
      return;
    }
    importing = true;
    try {
      let text;
      try {
        text = await readFileText(file);
      } catch (error) {
        console.error('Studio import read failed', error);
        showToast('파일을 읽지 못했습니다', 'error');
        return;
      }
      const result = parseImportPayload(text);
      if (!result.ok) {
        showToast(result.error, 'error');
        return;
      }
      // 파일 읽기(async) 사이에 생성이 시작됐을 수 있다 — 재검사.
      if (running || activeJob) {
        showToast('Studio 생성이 끝난 뒤 불러오세요', 'error');
        return;
      }
      if (boardHasContent()) {
        const confirmed = await Promise.resolve(confirmDialog(
          '현재 Studio 보드를 불러온 내용으로 교체할까요?',
          {title: 'Studio 불러오기', okText: '불러오기', cancelText: '취소'},
        ));
        if (!confirmed) return;
        if (running || activeJob) {
          showToast('Studio 생성이 끝난 뒤 불러오세요', 'error');
          return;
        }
      }
      applyImportedBoard(result.board);
    } finally {
      importing = false;
    }
  }

  function importBoard() {
    if (running || activeJob) {
      showToast('Studio 생성이 끝난 뒤 불러오세요', 'error');
      return;
    }
    if (importing) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    if (input.style) input.style.display = 'none';
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      if (input.remove) input.remove();
      // 같은 파일 재선택 시 change가 다시 발화하도록 value 리셋(분리 전이라 무해).
      try { input.value = ''; } catch (_) { /* noop */ }
      handleImportFile(file);
    });
    if (document.body) document.body.appendChild(input);
    input.click();
  }

  function frameFromLine(line, index) {
    return {
      ...createFrame(index),
      prompt: safeText(line).trim(),
      negative: negEdit?.value || '',
      resolution: state.globalResolution || getCurrentResolution() || '',
    };
  }

  function importLines(mode) {
    const lines = importText
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean);
    if (!lines.length) {
      showToast('배치할 프롬프트 줄이 없습니다', 'error');
      return;
    }
    if (mode === 'replace') {
      frameImages.forEach(url => URL.revokeObjectURL(url));
      frameImages.clear();
      state.frames = lines.map(frameFromLine);
      selectedIndex = 0;
    } else {
      const start = state.frames.length;
      state.frames.push(...lines.map((line, offset) => frameFromLine(line, start + offset)));
      selectedIndex = start;
    }
    editorOpen = false;
    importText = '';
    importOpen = false;
    saveState();
    render();
    showToast(`${lines.length}개 프레임을 Studio에 배치했습니다`, 'success');
  }

  function clearIdleFailTimer() {
    if (idleFailTimer) clearTimeoutFn(idleFailTimer);
    idleFailTimer = null;
  }

  function buildQueue(indices) {
    const repeat = Math.max(1, state.repeat);
    const jobs = [];
    for (let r = 0; r < repeat; r += 1) {
      indices.forEach(index => jobs.push(index));
    }
    return jobs;
  }

  function startSequence() {
    if (activeJob || getGenerating()) {
      showToast('현재 생성이 끝난 뒤 다시 시작하세요', 'error');
      return;
    }
    const enabled = state.frames
      .map((frame, index) => frame.enabled && composePrompt(frame).trim() ? index : null)
      .filter(index => index !== null);
    if (!enabled.length) {
      showToast('생성 가능한 Studio 프레임이 없습니다', 'error');
      return;
    }
    queue = buildQueue(enabled);
    running = true;
    startNextJob();
  }

  function generateSelected() {
    const frame = selectedFrame();
    if (!frame || !frame.enabled || !composePrompt(frame).trim()) {
      showToast('선택 프레임의 프롬프트가 비어 있거나 비활성 상태입니다', 'error');
      return;
    }
    if (activeJob || getGenerating()) {
      showToast('현재 생성이 끝난 뒤 다시 시작하세요', 'error');
      return;
    }
    queue = [selectedIndex];
    running = true;
    startNextJob();
  }

  function stopSequence() {
    queue = [];
    running = false;
    if (activeJob) {
      const frame = state.frames[activeJob.frameIndex];
      if (frame) frame.status = 'generating';
      showToast('현재 생성은 유지하고 이후 Studio 큐를 중지했습니다', 'success');
    }
    render();
  }

  function startNextJob() {
    clearIdleFailTimer();
    if (!queue.length) {
      running = false;
      activeJob = null;
      saveState();
      render();
      return;
    }
    if (getGenerating()) {
      setTimeoutFn(startNextJob, 500);
      return;
    }
    const frameIndex = queue.shift();
    const frame = state.frames[frameIndex];
    if (!frame || !frame.enabled || !composePrompt(frame).trim()) {
      setTimeoutFn(startNextJob, 0);
      return;
    }

    selectedIndex = frameIndex;
    editorOpen = false;
    const seed = resolveSeed(frameIndex);
    frame.lastSeed = seed;
    frame.status = 'generating';
    frame.lastUpdated = new Date().toISOString();
    activeJob = {
      frameIndex,
      token: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      startedAt: Date.now(),
    };
    const sent = generate({overrides: buildGenerationOverrides(frame, frameIndex, seed)});
    if (sent === false) {
      frame.status = 'error';
      activeJob = null;
      running = false;
      showToast('Studio 생성 요청을 보낼 수 없습니다', 'error');
      saveState();
      render();
      return;
    }
    saveState();
    render();
  }

  function handleResultBlob(blob) {
    if (!activeJob) return;
    const frame = state.frames[activeJob.frameIndex];
    clearIdleFailTimer();
    if (!frame) {
      activeJob = null;
      startNextJob();
      return;
    }
    const oldUrl = frameImages.get(frame.id);
    if (oldUrl) URL.revokeObjectURL(oldUrl);
    const url = URL.createObjectURL(blob);
    frameImages.set(frame.id, url);
    frame.status = 'done';
    frame.runCount = (Number(frame.runCount) || 0) + 1;
    frame.lastUpdated = new Date().toISOString();
    activeJob = null;
    saveState();
    render();
    setTimeoutFn(startNextJob, 350);
  }

  function markActiveFailed() {
    if (!activeJob) return;
    const frame = state.frames[activeJob.frameIndex];
    if (frame) {
      frame.status = 'error';
      frame.lastUpdated = new Date().toISOString();
    }
    activeJob = null;
    saveState();
    render();
    setTimeoutFn(startNextJob, 350);
  }

  function handleGenerationStatus(isGenerating) {
    if (isGenerating || !activeJob) {
      clearIdleFailTimer();
      return;
    }
    clearIdleFailTimer();
    idleFailTimer = setTimeoutFn(markActiveFailed, GENERATION_IDLE_GRACE_MS);
  }

  function onParamsChanged() {
    if (root && root.querySelector('.studio-tab')) render();
  }

  function handleAction(action) {
    if (action === 'sync-current') syncSelectedFromMain();
    else if (action === 'apply-current') applySelectedToMain();
    else if (action === 'duplicate-frame') duplicateFrame();
    else if (action === 'delete-frame') deleteSelectedFrame();
    else if (action === 'clear-frame') clearSelectedFrame();
    else if (action === 'capture-current-new') captureCurrentAsNewFrame();
    else if (action === 'add-frame') addFrame();
    else if (action === 'export-board') exportBoard();
    else if (action === 'import-board') importBoard();
    else if (action === 'reset-frames') resetFrames();
    else if (action === 'toggle-global') {
      globalOpen = !globalOpen;
      render();
    }
    else if (action === 'close-editor') {
      editorOpen = false;
      render();
    }
    else if (action === 'toggle-import') {
      importOpen = !importOpen;
      render();
    }
    else if (action === 'import-lines-append') importLines('append');
    else if (action === 'import-lines-replace') importLines('replace');
    else if (action === 'start-sequence') startSequence();
    else if (action === 'stop-sequence') stopSequence();
    else if (action === 'generate-selected') generateSelected();
  }

  function bind() {
    if (!root) return;
    root.addEventListener('click', event => {
      if (suppressNextClick) {
        // 실제 드래그 직후 발생하는 합성 click — 에디터 토글을 차단.
        suppressNextClick = false;
        return;
      }
      const frameButton = event.target.closest('[data-studio-frame]');
      if (frameButton && root.contains(frameButton)) {
        selectFrame(frameButton.dataset.studioFrame);
        return;
      }
      const action = event.target.closest('[data-studio-action]');
      if (action && root.contains(action)) {
        handleAction(action.dataset.studioAction);
      }
    });
    root.addEventListener('dragstart', onCardDragStart);
    root.addEventListener('dragover', onCardDragOver);
    root.addEventListener('dragleave', onCardDragLeave);
    root.addEventListener('drop', onCardDrop);
    root.addEventListener('dragend', onCardDragEnd);
    root.addEventListener('contextmenu', onCardContextMenu);
    root.addEventListener('input', event => {
      const globalField = event.target.dataset.studioGlobal;
      const frameField = event.target.dataset.studioFrameField;
      const render = shouldRenderForInput(event.target);
      if (globalField) updateGlobal(globalField, event.target, {render});
      if (frameField) updateFrame(frameField, event.target, {render});
      if (event.target.dataset.studioImportLines !== undefined) {
        importText = safeText(event.target.value);
      }
    });
    root.addEventListener('change', event => {
      const globalField = event.target.dataset.studioGlobal;
      const frameField = event.target.dataset.studioFrameField;
      if (globalField) updateGlobal(globalField, event.target);
      if (frameField) updateFrame(frameField, event.target);
    });
  }

  function init() {
    loadState();
    bind();
    render();
  }

  return {
    init,
    render,
    handleResultBlob,
    handleGenerationStatus,
    onParamsChanged,
  };
}
