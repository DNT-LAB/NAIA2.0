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
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
}) {
  const root = document.getElementById('studioRoot');
  const STORAGE_KEY = 'naia.studio.v1';
  const DEFAULT_FRAME_COUNT = 9;
  const GENERATION_IDLE_GRACE_MS = 3500;
  const SEED_MODES = new Set(['random', 'reuse_previous', 'increment_previous']);
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
  const frameImages = new Map();

  function safeText(value) {
    return String(value ?? '');
  }

  function frameId(index) {
    return `F${String(index + 1).padStart(2, '0')}`;
  }

  function randomSeed() {
    return String(Math.floor(Math.random() * 10000000000));
  }

  function createFrame(index) {
    return {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}-${index}`,
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

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        prefix: state.prefix,
        postfix: state.postfix,
        globalNegative: state.globalNegative,
        globalResolution: state.globalResolution,
        repeat: state.repeat,
        seedMode: state.seedMode,
        fixSeed: state.fixSeed,
        frames: state.frames.map(frame => ({
          id: frame.id,
          enabled: frame.enabled,
          prompt: frame.prompt,
          negative: frame.negative,
          resolution: frame.resolution,
          seed: frame.seed,
          runCount: frame.runCount,
          lastSeed: frame.lastSeed,
          lastUpdated: frame.lastUpdated,
        })),
      }));
    } catch (error) {
      console.warn('Studio state save failed', error);
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
      _remote_queue_label: frameId(frameIndex),
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
      ? `<img src="${imageUrl}" alt="${escHtml(frameId(index))}">`
      : renderPromptList(frame);
    return `
      <button type="button" class="studio-frame-card${selected ? ' selected' : ''}${open ? ' open' : ''}${frame.enabled ? '' : ' disabled'}" data-studio-frame="${index}" aria-expanded="${open ? 'true' : 'false'}">
        <div class="studio-frame-label">
          <strong>${escHtml(frameId(index))}</strong>
          <span class="studio-status-dot" data-status="${escHtml(status)}" aria-label="${escHtml(status)}"></span>
        </div>
        <div class="studio-frame-preview${imageUrl ? ' has-image' : ''}">${preview}</div>
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
          <span>${escHtml(frameId(selectedIndex))}</span>
          <small>이미지 없음</small>
        </div>`;
    }
    return `
      <div class="studio-editor-image">
        <img src="${imageUrl}" alt="${escHtml(frameId(selectedIndex))}">
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
            <h3>${escHtml(frameId(selectedIndex))}</h3>
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
          <button type="button" data-studio-action="generate-selected" class="primary">선택 생성</button>
        </div>
      </section>`;
  }

  function renderQueueSummary() {
    const enabled = state.frames.filter(frame => frame.enabled).length;
    const total = enabled * Math.max(1, state.repeat);
    const runningText = activeJob
      ? `${frameId(activeJob.frameIndex)} 생성 중`
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
    const copy = {
      ...createFrame(state.frames.length),
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

  function addFrame() {
    state.frames.push(createFrame(state.frames.length));
    selectedIndex = state.frames.length - 1;
    editorOpen = true;
    saveState();
    render();
  }

  function resetFrames() {
    if (!window.confirm('Studio 프레임을 9칸 기본 상태로 초기화할까요?')) return;
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
    else if (action === 'clear-frame') clearSelectedFrame();
    else if (action === 'capture-current-new') captureCurrentAsNewFrame();
    else if (action === 'add-frame') addFrame();
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
