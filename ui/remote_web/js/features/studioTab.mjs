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
  let state = createDefaultState();
  let selectedIndex = 0;
  let queue = [];
  let activeJob = null;
  let running = false;
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

  function renderFrameCard(frame, index) {
    const selected = index === selectedIndex;
    const imageUrl = frameImages.get(frame.id);
    const status = statusText(frame);
    const preview = imageUrl
      ? `<img src="${imageUrl}" alt="">`
      : `<span>${escHtml(frameId(index))}</span>`;
    return `
      <button type="button" class="studio-frame-card${selected ? ' selected' : ''}${frame.enabled ? '' : ' disabled'}" data-studio-frame="${index}">
        <div class="studio-frame-preview">${preview}</div>
        <div class="studio-frame-info">
          <div class="studio-frame-top">
            <strong>${escHtml(frameId(index))}</strong>
            <span data-status="${escHtml(status)}">${escHtml(status)}</span>
          </div>
          <p>${previewText(frame.prompt)}</p>
          <div class="studio-frame-meta">
            <span>${escHtml(frame.resolution || state.globalResolution || getCurrentResolution() || 'current res')}</span>
            <span>${frame.runCount ? `${frame.runCount}x` : '0x'}</span>
          </div>
        </div>
      </button>`;
  }

  function renderGlobalPanel() {
    return `
      <section class="studio-global-panel">
        <div class="studio-global-grid">
          <label class="studio-field">
            <span>Prefix</span>
            <textarea data-studio-global="prefix" spellcheck="false">${escHtml(state.prefix)}</textarea>
          </label>
          <label class="studio-field">
            <span>Postfix</span>
            <textarea data-studio-global="postfix" spellcheck="false">${escHtml(state.postfix)}</textarea>
          </label>
          <label class="studio-field">
            <span>Global Negative</span>
            <textarea data-studio-global="globalNegative" spellcheck="false">${escHtml(state.globalNegative)}</textarea>
          </label>
          <div class="studio-run-settings">
            <label class="studio-field">
              <span>Global Resolution</span>
              <select data-studio-global="globalResolution">${renderResolutionOptions(state.globalResolution)}</select>
            </label>
            <label class="studio-field">
              <span>Repeat</span>
              <input type="number" min="1" max="99" value="${escHtml(String(state.repeat))}" data-studio-global="repeat">
            </label>
            <label class="studio-toggle">
              <input type="checkbox" data-studio-global="fixSeed"${state.fixSeed ? ' checked' : ''}>
              <span>Seed 고정</span>
            </label>
          </div>
        </div>
      </section>`;
  }

  function renderEditor() {
    const frame = selectedFrame();
    if (!frame) return '';
    return `
      <aside class="studio-editor">
        <div class="studio-editor-head">
          <div>
            <div class="studio-kicker">Frame Editor</div>
            <h3>${escHtml(frameId(selectedIndex))}</h3>
          </div>
          <label class="studio-toggle">
            <input type="checkbox" data-studio-frame-field="enabled"${frame.enabled ? ' checked' : ''}>
            <span>사용</span>
          </label>
        </div>
        <label class="studio-field studio-field-tall">
          <span>Frame Prompt</span>
          <textarea data-studio-frame-field="prompt" spellcheck="false">${escHtml(frame.prompt)}</textarea>
        </label>
        <label class="studio-field">
          <span>Frame Negative</span>
          <textarea data-studio-frame-field="negative" spellcheck="false">${escHtml(frame.negative)}</textarea>
        </label>
        <div class="studio-editor-grid">
          <label class="studio-field">
            <span>Resolution</span>
            <select data-studio-frame-field="resolution">${renderResolutionOptions(frame.resolution)}</select>
          </label>
          <label class="studio-field">
            <span>Seed</span>
            <input data-studio-frame-field="seed" value="${escHtml(frame.seed)}" placeholder="auto">
          </label>
        </div>
        <div class="studio-composed">
          <div>
            <span>Composed Prompt</span>
            <pre>${escHtml(composePrompt(frame) || 'empty')}</pre>
          </div>
          <div>
            <span>Composed Negative</span>
            <pre>${escHtml(composeNegative(frame) || 'empty')}</pre>
          </div>
        </div>
        <div class="studio-editor-actions">
          <button type="button" data-studio-action="sync-current">현재 프롬프트 가져오기</button>
          <button type="button" data-studio-action="apply-current">메인에 적용</button>
          <button type="button" data-studio-action="duplicate-frame">복제</button>
          <button type="button" data-studio-action="generate-selected" class="primary">선택 생성</button>
        </div>
      </aside>`;
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
            <button type="button" data-studio-action="add-frame">프레임 추가</button>
            <button type="button" data-studio-action="reset-frames">9칸 초기화</button>
            <button type="button" data-studio-action="start-sequence" class="primary" ${running || activeJob ? 'disabled' : ''}>순차 생성</button>
            <button type="button" data-studio-action="stop-sequence" class="danger" ${running || activeJob ? '' : 'disabled'}>중지</button>
          </div>
        </header>
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
          </section>
          ${renderEditor()}
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

  function selectFrame(index) {
    selectedIndex = Math.max(0, Math.min(Number(index) || 0, state.frames.length - 1));
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

  function applySelectedToMain() {
    const frame = selectedFrame();
    if (!frame) return false;
    const prompt = composePrompt(frame);
    const negative = composeNegative(frame);
    if (!prompt) {
      showToast('선택 프레임의 프롬프트가 비어 있습니다', 'error');
      return false;
    }
    const seed = state.fixSeed ? (frame.seed || frame.lastSeed || randomSeed()) : (frame.seed || randomSeed());
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
    saveState();
    render();
  }

  function addFrame() {
    state.frames.push(createFrame(state.frames.length));
    selectedIndex = state.frames.length - 1;
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
    state = createDefaultState();
    saveState();
    render();
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
    const seed = state.fixSeed ? (frame.seed || frame.lastSeed || randomSeed()) : (frame.seed || randomSeed());
    frame.lastSeed = seed;
    frame.status = 'generating';
    frame.lastUpdated = new Date().toISOString();
    activeJob = {
      frameIndex,
      token: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      startedAt: Date.now(),
    };
    applyFrameParams(frame, seed);
    setPromptFields(composePrompt(frame), composeNegative(frame));
    saveState();
    render();
    generate();
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
    else if (action === 'add-frame') addFrame();
    else if (action === 'reset-frames') resetFrames();
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
