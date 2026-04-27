/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, generating = false, drawerOpen = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&#39;').replace(/"/g,'&quot;') : '';
let reconnTimer = null, genTimer = null, genStartTime = 0;
const genDurations = [];  // last 5 generation durations (ms)
let progressTimer = null;

// ---- Session generation stats ----
let sessionGenTotal = 0;
const sessionGenTimestamps = [];
let _initDone = false;  // init_complete 수신 후 true → 초기 시딩 제외
let syncingOptions = false, syncingPrompt = false, promptSendTimer = null;
// 사용자가 로컬 편집을 했지만 아직 서버로 flush되지 않은 상태 — 서버 브로드캐스트 덮어쓰기 차단
let _localPromptDirty = false;
let awaitingMyRandom = false;  // 내가 Random 클릭했는지 추적
let sessionId = null, sharedMode = false;
let _restoringSession = false;  // 재연결 복원 중 서버 초기값 무시 플래그
let desktopWindowVisible = true;
let desktopWindowControlAllowed = false;
const urlParams = new URLSearchParams(location.search);
const isDesktopShell = urlParams.get('desktop_shell') === '1';
if (isDesktopShell) document.body.classList.add('desktop-shell');

// ---- Shared Mode LocalStorage 세션 유지 ----
const SHARED_STORAGE_KEY = 'naia_shared_session';
let createWsMessageDispatcher = null;
let quickFilter = null;
let rightTabs = null;
let resultInfoResizer = null;
let resultHistory = null;
let promptHighlighter = null;
let moduleBadges = null;
let cloudflaredControls = null;
const wsDispatcherReady = import('./js/core/wsDispatcher.mjs')
  .then(module => {
    createWsMessageDispatcher = module.createWsMessageDispatcher;
  })
  .catch(error => {
    console.error('Failed to initialize WebSocket dispatcher module', error);
    throw error;
  });
const quickFilterReady = import('./js/features/quickFilter.mjs')
  .then(({createQuickFilterController}) => {
    quickFilter = createQuickFilterController({
      document,
      localStorage,
      WebSocket,
      getWs: () => ws,
      getRatingState: () => ratingState,
      syncRatingButtons,
      computeLocalFilteredCount: _computeLocalFilteredCount,
      updateSearchCount,
      saveSharedSession,
      closeAuxiliaryPopups,
      escHtml,
      catStyle,
      fmtCount,
      showToast,
    });
    quickFilter.bindInputs();
  })
  .catch(error => {
    console.error('Failed to initialize Quick Filter module', error);
  });
const rightTabsReady = import('./js/features/rightTabs.mjs')
  .then(({createRightTabsController}) => {
    rightTabs = createRightTabsController({
      document,
      onLeaveResult: hideViewerNav,
    });
  })
  .catch(error => {
    console.error('Failed to initialize right tabs module', error);
  });
const resultInfoResizerReady = import('./js/features/resultInfoResizer.mjs')
  .then(({createResultInfoResizer}) => {
    resultInfoResizer = createResultInfoResizer({
      document,
      window,
      localStorage,
    });
  })
  .catch(error => {
    console.error('Failed to initialize result info resizer module', error);
  });
const resultHistoryReady = import('./js/features/resultHistory.mjs')
  .then(({createResultHistoryController}) => {
    resultHistory = createResultHistoryController({
      document,
      window,
      localStorage,
      fetch: window.fetch.bind(window),
      preview,
      emptyMsg,
      resultInfoContent,
      escHtml,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize result history module', error);
  });
const promptHighlighterReady = import('./js/features/promptHighlighter.mjs')
  .then(({createPromptHighlighter}) => {
    promptHighlighter = createPromptHighlighter({
      document,
      promptEdit,
      escHtml,
    });
  })
  .catch(error => {
    console.error('Failed to initialize prompt highlighter module', error);
  });
const moduleBadgesReady = import('./js/features/moduleBadges.mjs')
  .then(({createModuleBadges}) => {
    moduleBadges = createModuleBadges({
      document,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      estimateTokenCount,
      setCharacterPromptText: value => { lastCharacterPromptText = value; },
      setCharacterTokenCount: value => { lastCharacterTokenCount = value; },
      updatePromptTokenEstimate,
    });
  })
  .catch(error => {
    console.error('Failed to initialize module badges module', error);
  });
const cloudflaredControlsReady = import('./js/features/cloudflaredControls.mjs')
  .then(({createCloudflaredControls}) => {
    cloudflaredControls = createCloudflaredControls({
      document,
      getWs: () => ws,
      WebSocket,
      getApiStatus: () => _apiStatusLast,
      navigator,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize cloudflared controls module', error);
  });

function saveSharedSession() {
  if (!sharedMode) return;
  const quickState = quickFilter ? quickFilter.getSharedSessionState() : {};
  const data = {
    params: _collectCurrentParams(),
    prompt: promptEdit.value,
    negative_prompt: negEdit.value,
    options: {},
    p_eng: _sharedPEng || null,
    cond: _sharedCond || null,
    ratings: Object.keys(ratingState).filter(k => ratingState[k]),
    tag_filter: quickState.tag_filter || null,
    tag_filter_exclude: quickState.tag_filter_exclude || null,
    tag_filter_active: !!quickState.tag_filter_active,
  };
  for (const [key, cb] of Object.entries(optBoxes)) {
    if (key !== 'auto_generate') data.options[key] = cb.checked;
  }
  try { localStorage.setItem(SHARED_STORAGE_KEY, JSON.stringify(data)); } catch(_) {}
}

function loadSharedSession() {
  try {
    const raw = localStorage.getItem(SHARED_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch(_) { return null; }
}

function clearSharedSession() {
  try { localStorage.removeItem(SHARED_STORAGE_KEY); } catch(_) {}
}

function _collectCurrentParams() {
  const p = {};
  if (paramEls.resolution.value) p.resolution = paramEls.resolution.value;
  if (paramEls.steps.value) p.steps = paramEls.steps.value;
  if (paramEls.cfg_scale.value) p.cfg_scale = paramEls.cfg_scale.value;
  if (paramEls.cfg_rescale.value) p.cfg_rescale = paramEls.cfg_rescale.value;
  if (paramEls.seed.value) p.seed = paramEls.seed.value;
  if (paramEls.sampler.value) p.sampler = paramEls.sampler.value;
  if (paramEls.scheduler.value) p.scheduler = paramEls.scheduler.value;
  if (paramEls.model.value) p.model = paramEls.model.value;
  // flags
  document.querySelectorAll('#paramFlags .param-flag').forEach(el => {
    p[el.dataset.key] = String(el.classList.contains('on'));
  });
  return p;
}

// Shared Mode 세션별 P.Eng / Cond 캐시 (모듈 set 시 갱신)
let _sharedPEng = null, _sharedCond = null;
let _sharedParamsInit = false;  // Shared Mode: 초기 params 수신 완료 여부
let _sharedOptionsInit = false;  // Shared Mode: 초기 options 수신 완료 여부
let _restoreSessionTimeout = null;  // init_complete 미수신 시 안전망 타이머

// ---- Result history rail ----
let pendingMeta = null; // meta arrives before blob

const $ = id => document.getElementById(id);
const preview      = $('preview');
const emptyMsg     = $('emptyMsg');
const setupLauncherBtn = $('setupLauncher');  // doubles as connection-status indicator
const modeApiCombo = $('modeApiCombo');
const desktopToggleBtn = $('desktopToggleBtn');
const btnGen       = $('btnGen');
const btnRnd       = $('btnRnd');
const promptEdit   = $('promptEdit');
const negEdit      = $('negEdit');
const metaRow      = $('metaRow');
const promptTokenLabel = $('promptTokenLabel');
const negativeTokenLabel = $('negativeTokenLabel');
const paramFlags   = $('paramFlags');
const paramEls = {
  model: $('pModel'), sampler: $('pSampler'), scheduler: $('pScheduler'),
  resolution: $('pResolution'), steps: $('pSteps'), cfg_scale: $('pCfgScale'),
  cfg_rescale: $('pCfgRescale'), seed: $('pSeed'),
};
const qResolution = $('qResolution');
const qRndRes = $('qRndRes');
const qAutoRes = $('qAutoRes');
let syncingParams = false;
const resultInfoContent = $('resultInfoContent');
const statsGenCount  = $('statsGenCount');
const statsSave      = $('statsSave');
let autoSaveEnabled  = true;
const promptDrawer = $('promptDrawer');
const toggleArrow  = $('toggleArrow');
const toggleArrow2 = $('toggleArrow2');
const toggleLabel  = $('toggleLabel');
const promptNewDot = $('promptNewDot');
const toggleBar    = document.querySelector('.prompt-toggle-bar');
const optBoxes = {
  prompt_fixed: $('optPromptFixed'),
  auto_generate: $('optAutoGen'),
  wildcard_standalone: $('optWcStandalone'),
};

// ---- Result history wrappers ----
function setHistoryRailCollapsed(collapsed, persist = true) { if (resultHistory) resultHistory.setRailCollapsed(collapsed, persist); }
function toggleHistoryRail() { if (resultHistory) resultHistory.toggleRail(); }
function initHistoryRail() { if (resultHistory) resultHistory.init(); }

function initResultInfoResizer() {
  if (resultInfoResizer) resultInfoResizer.init();
}

// ---- WebSocket ----

function handleWsBlob(data) {
  // Live preview: blob → 메인 뷰어에 즉시 표시
  const url = URL.createObjectURL(data);
  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = url;
  preview.src = url;
  preview.classList.add('show');
  emptyMsg.style.display = 'none';
  pendingMeta = null;
  setGen(false);
  // Stats update — init_complete 이후의 blob만 카운트 (초기 시딩 제외)
  if (_initDone) {
    sessionGenTotal++;
    sessionGenTimestamps.push(Date.now());
    updateGenStats();
  }
}

function onInitComplete() {
  _restoringSession = false;
  _initDone = true;
  if (_restoreSessionTimeout) { clearTimeout(_restoreSessionTimeout); _restoreSessionTimeout = null; }
  // 재연결 시 열려있는 모듈 자동 리프레시 (캐시 fallback 적용 위해)
  if (currentModuleId && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'get_module_state', module_id: currentModuleId}));
  }
  if (resultHistory) resultHistory.prepareInitialHistory();
  if (!sharedMode) {
    if (quickFilter) quickFilter.restorePreferences();
  }
}

function afterWsJsonMessage(m) {
  // Update search count from prompt_generated
  if (m.type === 'prompt_generated' && 'remaining' in m) {
    if (m.rating_counts) _cachedRatingCounts = m.rating_counts;
    const filtered = _computeLocalFilteredCount();
    updateSearchCount(filtered !== null ? filtered : m.remaining);
  }
}

function onWsMessageError(error) {
  console.warn('Failed to handle WebSocket message', error);
}

const wsMessageHandlers = {
  image_meta: m => { pendingMeta = m; updateMeta(m); },
  status: m => setGen(m.is_generating),
  prompt_generated: updatePromptOnly,
  random_failed: onRandomFailed,
  prompt_sync: syncPrompts,
  prompt_tokens: applyPromptTokenPayload,
  options: syncOptions,
  params: updateParams,
  mode: m => syncMode(m.mode),
  mode_result: onModeResult,
  api_status: updateApiStatus,
  verify_result: onVerifyResult,
  setup_blocked: onSetupBlocked,
  probe_result: onProbeResult,
  anlas_update: onAnlasUpdate,
  module_state: onModuleState,
  search_state: onSearchState,
  rating_update: onRatingUpdate,
  search_progress: onSearchProgress,
  depth_state: onDepthState,
  tag_search_result: onTagSearchResult,
  tag_lookup_result: onTagLookupResult,
  autocomplete_result: onAutocompleteResult,
  tag_filter_result: onTagFilterResult,
  tag_filter_assigned: onTagFilterAssigned,
  tag_filter_ac_result: onTagFilterAcResult,
  storage_list: onStorageList,
  wildcard_manager: onWildcardManager,
  filter_reset: onFilterReset,
  toast: m => showToast(m.message, m.level || 'success'),
  load_prompt: m => onLoadPrompt(m.prompt),
  viewer_new_image: onViewerNewImage,
  session: onSession,
  desktop_window_state: onDesktopWindowState,
  init_complete: onInitComplete,
};

function connect() {
  if (reconnTimer) { clearTimeout(reconnTimer); reconnTimer = null; }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.binaryType = 'blob';

  ws.onopen = () => {
    _initDone = false;
    _initialProbeDone = false;
    setLauncherConn(true);
    ws.send(JSON.stringify({type: 'get_search_state'}));
    // 클라이언트 상태 전송 (히스토리 수 0 — viewer는 REST로 로드)
    ws.send(JSON.stringify({
      type: 'client_state',
      history_count: 0,
      desktop_shell: isDesktopShell,
    }));
    // probe 는 api_status 첫 수신 시점에 1회 실행 (updateApiStatus 내부에서 트리거).
  };
  ws.onclose = () => {
    setLauncherConn(false);
    modeSwitching = false;
    if (modeSelect) modeSelect.disabled = true;
    desktopWindowControlAllowed = false;
    if (desktopToggleBtn) desktopToggleBtn.classList.add('hidden');
    reconnTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = createWsMessageDispatcher({
    BlobClass: Blob,
    onBlob: handleWsBlob,
    handlers: wsMessageHandlers,
    afterJson: afterWsJsonMessage,
    onError: onWsMessageError,
  });
}

// ---- Meta / Prompt display ----

function updateMetaChips(m) {
  const chips = [];
  if (m.model) chips.push(`<b>model</b> ${m.model}`);
  if (m.width && m.height) chips.push(`<b>res</b> ${m.width}x${m.height}`);
  if (m.seed) chips.push(`<b>seed</b> ${m.seed}`);
  if (m.steps) chips.push(`<b>steps</b> ${m.steps}`);
  if (m.cfg_scale) chips.push(`<b>cfg</b> ${m.cfg_scale}`);
  if (m.sampler) chips.push(`<b>sampler</b> ${m.sampler}`);
  if (m.size_kb) chips.push(`<b>file</b> ${m.size_kb}KB`);
  if (chips.length) metaRow.innerHTML = chips.map(c => `<span class="chip">${c}</span>`).join('');
}

function updateMeta(m) {
  // Don't overwrite prompt/negative — preserves user's comments (#) and line breaks
  updateMetaChips(m);
}

let lastCharacterTokenCount = 0;
let lastCharacterPromptText = '';
let lastMainTokenCount = null;
let lastMainTokenSourceText = '';
let lastMainTokenMode = '';
let lastNegativeTokenCount = null;
let lastNegativeTokenSourceText = '';
let lastNegativeTokenMode = '';

function cleanPromptForTokenEstimate(text, mode) {
  let cleaned = (text || '')
    .split(',')
    .map(part => part.trim())
    .filter(part => part && !part.startsWith('#'))
    .join(', ');
  if (mode === 'NAI') {
    cleaned = cleaned.replace(/-?\d+(?:\.\d+)?::/g, '').replace(/::/g, '');
  } else if (mode === 'WEBUI' || mode === 'COMFYUI') {
    cleaned = cleaned
      .replace(/\\[()]/g, ' ')
      .replace(/\(([^()]+?)(?::[+-]?\d*\.?\d+)?\)/g, '$1');
  }
  return cleaned.replace(/\s+/g, ' ').replace(/\s+,/g, ',').replace(/,+/g, ',').trim();
}

function estimateTokenCount(text, mode) {
  const cleaned = cleanPromptForTokenEstimate(text, mode);
  if (!cleaned) return 0;
  const base = Math.ceil(cleaned.length / 5);
  const correction = mode === 'NAI' ? 1.12 : 0.99;
  return Math.max(1, Math.ceil(base * correction));
}

function formatPromptTokenLabel(main, character, mode) {
  if (mode === 'NAI') {
    return `Estimated Tokens : ${main + character} (Main ${main} + Character ${character})`;
  }
  return `Estimated Tokens : ${main}`;
}

function formatNegativeTokenLabel(count) {
  return `Estimated Tokens : ${count}`;
}

function updateNegativeTokenEstimate() {
  if (!negativeTokenLabel) return;
  const mode = currentMode || modeSelect.value || 'NAI';
  const hasExactNegative = lastNegativeTokenCount !== null
    && lastNegativeTokenSourceText === negEdit.value
    && lastNegativeTokenMode === mode;
  const negative = hasExactNegative ? lastNegativeTokenCount : estimateTokenCount(negEdit.value, mode);
  negativeTokenLabel.textContent = formatNegativeTokenLabel(negative);
}

function updatePromptTokenEstimate() {
  const mode = currentMode || modeSelect.value || 'NAI';
  if (promptTokenLabel) {
    const hasExactMain = lastMainTokenCount !== null
      && lastMainTokenSourceText === promptEdit.value
      && lastMainTokenMode === mode;
    const main = hasExactMain ? lastMainTokenCount : estimateTokenCount(promptEdit.value, mode);
    const character = mode === 'NAI'
      ? (lastCharacterTokenCount || estimateTokenCount(lastCharacterPromptText, mode))
      : 0;
    promptTokenLabel.textContent = formatPromptTokenLabel(main, character, mode);
  }
  updateNegativeTokenEstimate();
}

function applyNegativeTokenPayload(m) {
  if (!negativeTokenLabel) return;
  if (Number.isFinite(Number(m.negative_token_count))) {
    const mode = currentMode || modeSelect.value || 'NAI';
    lastNegativeTokenCount = Number(m.negative_token_count);
    lastNegativeTokenSourceText = typeof m.negative_prompt === 'string' ? m.negative_prompt : negEdit.value;
    lastNegativeTokenMode = mode;
    negativeTokenLabel.textContent = formatNegativeTokenLabel(lastNegativeTokenCount);
    return;
  }
  updateNegativeTokenEstimate();
}

function applyPromptTokenPayload(m) {
  applyNegativeTokenPayload(m);
  if (!promptTokenLabel) return;
  if (m.prompt_token_label) {
    promptTokenLabel.textContent = m.prompt_token_label;
    if (m.prompt_token_counts) {
      if (Number.isFinite(Number(m.prompt_token_counts.main))) {
        lastMainTokenCount = Number(m.prompt_token_counts.main);
        lastMainTokenSourceText = typeof m.prompt === 'string' ? m.prompt : promptEdit.value;
        lastMainTokenMode = currentMode || modeSelect.value || 'NAI';
      }
      if (Number.isFinite(Number(m.prompt_token_counts.character))) {
        lastCharacterTokenCount = Number(m.prompt_token_counts.character);
      }
    }
    return;
  }
  if (m.prompt_token_counts) {
    const counts = m.prompt_token_counts;
    const main = Number(counts.main) || 0;
    const character = Number(counts.character) || 0;
    lastMainTokenCount = main;
    lastMainTokenSourceText = typeof m.prompt === 'string' ? m.prompt : promptEdit.value;
    lastMainTokenMode = currentMode || modeSelect.value || 'NAI';
    lastCharacterTokenCount = character;
    promptTokenLabel.textContent = formatPromptTokenLabel(main, character, currentMode || modeSelect.value || 'NAI');
    return;
  }
  updatePromptTokenEstimate();
}

function unlockRandomButton() {
  awaitingMyRandom = false;
  if (window._randomTimeout) {
    clearTimeout(window._randomTimeout);
    window._randomTimeout = null;
  }
  const fixed = !!(optBoxes.prompt_fixed && optBoxes.prompt_fixed.checked);
  btnRnd.disabled = fixed;
  btnRnd.style.opacity = fixed ? '0.4' : '';
}

function onRandomFailed(m) {
  unlockRandomButton();
  if (m && m.message) showToast(m.message, m.level || 'error', true);
}

function updatePromptOnly(messageOrPrompt, sourceArg) {
  const message = (typeof messageOrPrompt === 'object' && messageOrPrompt !== null)
    ? messageOrPrompt
    : {prompt: messageOrPrompt, source: sourceArg};
  const prompt = message.prompt;
  const source = message.source;
  if (!prompt) return;
  // 내가 요청한 Random일 때만 프롬프트 갱신 (다른 사용자의 Random으로 덮어쓰기 방지)
  if (source === 'random' && awaitingMyRandom) {
    unlockRandomButton();
    let acceptedPrompt = false;
    if (_isPromptEditingActive() && prompt !== promptEdit.value) {
      // 편집 중: 사용자 입력을 보호. Random 결과를 다시 받으려면 Random 다시 누르면 됨.
      // (deferredPromptSync는 blur flush 경로 제거로 더 이상 쓰지 않음)
    } else {
      syncingPrompt = true;
      promptEdit.value = prompt;
      syncingPrompt = false;
      updatePromptHighlight();
      applyPromptHighlightState();
      acceptedPrompt = true;
    }
    if (acceptedPrompt) applyPromptTokenPayload(message);
    else updatePromptTokenEstimate();
    // Show new-content dot if drawer is closed
    if (!drawerOpen) promptNewDot.classList.remove('hidden');
  }
  // Random 완료 → 버튼 복원 (source 무관)
  if (source === 'random') unlockRandomButton();
}

// ---- Params ----

function populateSelect(el, options, current) {
  if (options && options.length) {
    const existing = Array.from(el.options).map(o => o.value);
    if (existing.length !== options.length || existing.some((v, i) => v !== options[i])) {
      el.innerHTML = options.map(o => `<option value="${o}">${o}</option>`).join('');
    }
  }
  if (current !== undefined) el.value = current;
}

function updateParams(m) {
  // Shared Mode 재연결 복원 중: 서버 초기값(데스크톱) 무시, params만 복원 적용
  if (_restoringSession) {
    const saved = loadSharedSession();
    if (saved && saved.params) {
      // select 옵션은 서버에서 채워야 하므로 populateSelect는 실행하되 값은 복원값 사용
      syncingParams = true;
      populateSelect(paramEls.model, m.options_model, saved.params.model || m.model);
      populateSelect(paramEls.sampler, m.options_sampler, saved.params.sampler || m.sampler);
      populateSelect(paramEls.scheduler, m.options_scheduler, saved.params.scheduler || m.scheduler);
      populateSelect(paramEls.resolution, m.options_resolution, saved.params.resolution || m.resolution);
      populateSelect(qResolution, m.options_resolution, saved.params.resolution || m.resolution);
      if (saved.params.steps) paramEls.steps.value = saved.params.steps;
      else if (m.steps !== undefined) paramEls.steps.value = m.steps;
      if (saved.params.cfg_scale) paramEls.cfg_scale.value = saved.params.cfg_scale;
      else if (m.cfg_scale !== undefined) paramEls.cfg_scale.value = m.cfg_scale;
      if (saved.params.cfg_rescale) paramEls.cfg_rescale.value = saved.params.cfg_rescale;
      else if (m.cfg_rescale !== undefined) paramEls.cfg_rescale.value = m.cfg_rescale;
      if (saved.params.seed) paramEls.seed.value = saved.params.seed;
      else if (m.seed !== undefined) paramEls.seed.value = m.seed;
      if (m.steps_range) { paramEls.steps.min = m.steps_range[0]; paramEls.steps.max = m.steps_range[1]; }
      // 모드별 표시/숨김은 서버 값 그대로
      const mode = m.api_mode || '';
      document.querySelectorAll('.mode-nai').forEach(el => el.style.display = mode === 'NAI' ? '' : 'none');
      $('webuiParams').style.display = mode === 'WEBUI' ? '' : 'none';
      $('comfyuiParams').style.display = mode === 'COMFYUI' ? '' : 'none';
      // flags는 저장값 우선 적용
      const flags = [];
      const naiFlagsEnabled = m.nai_flags_enabled || {};
      if (mode === 'NAI') {
        for (const key of ['SMEA', 'DYN', 'VAR+', 'DECRISP']) {
          if (key in m) {
            const savedVal = saved.params[key];
            const on = savedVal !== undefined ? savedVal === 'true' : m[key];
            flags.push({key, name: key, on, enabled: naiFlagsEnabled[key] !== false});
          }
        }
      }
      if ('seed_fixed' in m) { const sv = saved.params.seed_fixed; flags.push({key: 'seed_fixed', name: 'Seed Fix', on: sv !== undefined ? sv === 'true' : m.seed_fixed, enabled: true}); }
      if ('random_resolution' in m) { const sv = saved.params.random_resolution; flags.push({key: 'random_resolution', name: 'Rnd Res', on: sv !== undefined ? sv === 'true' : m.random_resolution, enabled: true}); }
      if ('auto_fit_resolution' in m) { const sv = saved.params.auto_fit_resolution; flags.push({key: 'auto_fit_resolution', name: 'Auto Res', on: sv !== undefined ? sv === 'true' : m.auto_fit_resolution, enabled: true}); }
      paramFlags.innerHTML = flags.map(f =>
        `<span class="param-flag${f.on ? ' on' : ''}${f.enabled ? '' : ' disabled'}" data-key="${f.key}" onclick="${f.enabled ? 'toggleFlag(this)' : ''}">${f.name}</span>`
      ).join('');
      if ('random_resolution' in m) { const sv = saved.params.random_resolution; qRndRes.classList.toggle('on', sv !== undefined ? sv === 'true' : m.random_resolution); }
      if ('auto_fit_resolution' in m) { const sv = saved.params.auto_fit_resolution; qAutoRes.classList.toggle('on', sv !== undefined ? sv === 'true' : m.auto_fit_resolution); }
      // WEBUI HR — 서버 값 그대로 (LocalStorage에 미저장)
      if (mode === 'WEBUI') {
        if ('enable_hr' in m) $('pEnableHr').checked = m.enable_hr;
        if ('hr_scale' in m) $('pHrScale').value = m.hr_scale;
        populateSelect($('pHrUpscaler'), m.options_hr_upscaler, m.hr_upscaler);
        if ('denoising_strength' in m) $('pDenoise').value = m.denoising_strength;
        if ('hires_steps' in m) $('pHiresSteps').value = m.hires_steps;
        if ('hr_cfg' in m) $('pHrCfg').value = m.hr_cfg;
      }
      // ComfyUI sampling mode — 서버가 명시적으로 보낸 경우에만 적용 (EPS 기본값 리셋 방지)
      if (mode === 'COMFYUI' && 'sampling_mode' in m) {
        const sm = m.sampling_mode;
        $('flagEps').classList.toggle('on', sm === 'eps');
        $('flagVpred').classList.toggle('on', sm === 'v_prediction');
        $('flagAnima').classList.toggle('on', sm === 'anima');
        $('comfyuiRescaleRow').style.display = sm === 'anima' ? '' : 'none';
        if ('rescale_cfg' in m) $('pRescaleCfg').value = m.rescale_cfg;
      }
      syncingParams = false;
      _sharedParamsInit = true;
      return;
    }
  }
  // Shared Mode: 초기 1회만 서버 값 수용, 이후 broadcast 무시 (세션별 params 보호)
  if (sharedMode && _sharedParamsInit) return;
  if (sharedMode) _sharedParamsInit = true;
  syncingParams = true;
  populateSelect(paramEls.model, m.options_model, m.model);
  populateSelect(paramEls.sampler, m.options_sampler, m.sampler);
  populateSelect(paramEls.scheduler, m.options_scheduler, m.scheduler);
  populateSelect(paramEls.resolution, m.options_resolution, m.resolution);
  // Quick controls 동기화
  populateSelect(qResolution, m.options_resolution, m.resolution);
  if (m.steps !== undefined) paramEls.steps.value = m.steps;
  if (m.cfg_scale !== undefined) paramEls.cfg_scale.value = m.cfg_scale;
  if (m.cfg_rescale !== undefined) paramEls.cfg_rescale.value = m.cfg_rescale;
  if (m.seed !== undefined) paramEls.seed.value = m.seed;
  if (m.steps_range) {
    paramEls.steps.min = m.steps_range[0];
    paramEls.steps.max = m.steps_range[1];
  }
  // 모드별 표시/숨김
  const mode = m.api_mode || '';
  document.querySelectorAll('.mode-nai').forEach(el => el.style.display = mode === 'NAI' ? '' : 'none');
  $('webuiParams').style.display = mode === 'WEBUI' ? '' : 'none';
  $('comfyuiParams').style.display = mode === 'COMFYUI' ? '' : 'none';

  // 플래그 (공통 + NAI)
  const flags = [];
  const naiFlagsEnabled = m.nai_flags_enabled || {};
  if (mode === 'NAI') {
    for (const key of ['SMEA', 'DYN', 'VAR+', 'DECRISP']) {
      if (key in m) flags.push({key, name: key, on: m[key], enabled: naiFlagsEnabled[key] !== false});
    }
  }
  if ('seed_fixed' in m) flags.push({key: 'seed_fixed', name: 'Seed Fix', on: m.seed_fixed, enabled: true});
  if ('random_resolution' in m) flags.push({key: 'random_resolution', name: 'Rnd Res', on: m.random_resolution, enabled: true});
  if ('auto_fit_resolution' in m) flags.push({key: 'auto_fit_resolution', name: 'Auto Res', on: m.auto_fit_resolution, enabled: true});
  paramFlags.innerHTML = flags.map(f =>
    `<span class="param-flag${f.on ? ' on' : ''}${f.enabled ? '' : ' disabled'}" data-key="${f.key}" onclick="${f.enabled ? 'toggleFlag(this)' : ''}">${f.name}</span>`
  ).join('');
  // Quick flags 동기화
  if ('random_resolution' in m) qRndRes.classList.toggle('on', m.random_resolution);
  if ('auto_fit_resolution' in m) qAutoRes.classList.toggle('on', m.auto_fit_resolution);

  // WEBUI HR
  if (mode === 'WEBUI') {
    if ('enable_hr' in m) $('pEnableHr').checked = m.enable_hr;
    if ('hr_scale' in m) $('pHrScale').value = m.hr_scale;
    populateSelect($('pHrUpscaler'), m.options_hr_upscaler, m.hr_upscaler);
    if ('denoising_strength' in m) $('pDenoise').value = m.denoising_strength;
    if ('hires_steps' in m) $('pHiresSteps').value = m.hires_steps;
    if ('hr_cfg' in m) $('pHrCfg').value = m.hr_cfg;
  }

  // ComfyUI sampling mode — 서버가 명시적으로 보낸 경우에만 적용 (EPS 기본값 리셋 방지)
  if (mode === 'COMFYUI' && 'sampling_mode' in m) {
    const sm = m.sampling_mode;
    $('flagEps').classList.toggle('on', sm === 'eps');
    $('flagVpred').classList.toggle('on', sm === 'v_prediction');
    $('flagAnima').classList.toggle('on', sm === 'anima');
    $('comfyuiRescaleRow').style.display = sm === 'anima' ? '' : 'none';
    if ('rescale_cfg' in m) $('pRescaleCfg').value = m.rescale_cfg;
  }
  syncingParams = false;
}

function setParam(key, value) {
  if (syncingParams) return;
  // Quick ↔ Params 탭 양방향 동기화
  if (key === 'resolution') {
    paramEls.resolution.value = value;
    qResolution.value = value;
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_param', key, value}));
  }
  saveSharedSession();
}

function toggleFlag(el) {
  if (el.classList.contains('disabled')) return;
  const key = el.dataset.key;
  const isOn = el.classList.contains('on');
  el.classList.toggle('on', !isOn);
  setParam(key, String(!isOn));
  // Quick flags 동기화 (Params → Quick)
  if (key === 'random_resolution') qRndRes.classList.toggle('on', !isOn);
  if (key === 'auto_fit_resolution') qAutoRes.classList.toggle('on', !isOn);
}

function toggleQuickFlag(el, key) {
  const isOn = el.classList.contains('on');
  el.classList.toggle('on', !isOn);
  setParam(key, String(!isOn));
  // Params 탭 내 플래그도 동기화
  const paramEl = paramFlags.querySelector(`[data-key="${key}"]`);
  if (paramEl) paramEl.classList.toggle('on', !isOn);
}

function setSamplingMode(mode) {
  $('flagEps').classList.toggle('on', mode === 'eps');
  $('flagVpred').classList.toggle('on', mode === 'v_prediction');
  $('flagAnima').classList.toggle('on', mode === 'anima');
  $('comfyuiRescaleRow').style.display = mode === 'anima' ? '' : 'none';
  setParam('sampling_mode', mode);
}

// ---- Prompt sync ----

let _sharedPromptsInit = false;  // Shared Mode: 초기 prompts sync 완료 여부
let deferredPromptSync = null;

function _isPromptFieldFocused() {
  return document.activeElement === promptEdit || document.activeElement === negEdit;
}

// 사용자가 메인 프롬프트/네거티브를 편집 중인 상태 판정.
// focus 중이거나, 타이핑 후 서버 동기화 debounce가 남은 경우 → 서버 브로드캐스트로 덮어쓰기 금지.
function _isPromptEditingActive() {
  return _isPromptFieldFocused() || _localPromptDirty;
}

function _applyPromptSync(m) {
  syncingPrompt = true;
  if ('prompt' in m && m.prompt !== promptEdit.value) promptEdit.value = m.prompt;
  if ('negative_prompt' in m && m.negative_prompt !== negEdit.value) negEdit.value = m.negative_prompt;
  syncingPrompt = false;
  updateMetaChips(m);
  applyPromptTokenPayload(m);
  updatePromptHighlight();
  applyPromptHighlightState();
}

function flushDeferredPromptSync() {
  if (!deferredPromptSync || _isPromptFieldFocused()) return;
  const pending = deferredPromptSync;
  deferredPromptSync = null;
  _applyPromptSync(pending);
}

function syncPrompts(m) {
  if (_restoringSession) return;  // 복원 중: 서버 초기값 무시
  // Shared Mode: 초기 1회만 서버 값 수용 (이후 broadcast는 세션별 프롬프트 보호)
  if (sharedMode && _sharedPromptsInit) return;
  if (sharedMode) {
    _sharedPromptsInit = true;
    // LocalStorage에 저장된 프롬프트가 있으면 서버값 대신 유지
    const saved = loadSharedSession();
    let restoredPromptLocally = false;
    if (saved) {
      if (saved.prompt != null) { m.prompt = saved.prompt; restoredPromptLocally = true; }
      if (saved.negative_prompt != null) { m.negative_prompt = saved.negative_prompt; restoredPromptLocally = true; }
    }
    if (restoredPromptLocally) {
      delete m.prompt_token_label;
      delete m.prompt_token_counts;
    }
  }
  const promptChanged = 'prompt' in m && m.prompt !== promptEdit.value;
  const negativeChanged = 'negative_prompt' in m && m.negative_prompt !== negEdit.value;

  if (_isPromptEditingActive() && (promptChanged || negativeChanged)) {
    // 편집 중: 서버 값 버림. blur해도 자동 flush 안 함 (사용자 편집 보호).
    // 사용자 편집이 flush되면 서버가 다시 브로드캐스트하여 자연스럽게 동기화됨.
    deferredPromptSync = null;
    updateMetaChips(m);
    updatePromptTokenEstimate();
    return;
  }

  _applyPromptSync(m);
}

function onPromptEdit() {
  if (syncingPrompt) return;
  _localPromptDirty = true;
  lastMainTokenCount = null;
  lastNegativeTokenCount = null;
  updatePromptHighlight();
  updatePromptTokenEstimate();
  if (promptSendTimer) clearTimeout(promptSendTimer);
  promptSendTimer = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'set_prompt',
        prompt: promptEdit.value,
        negative_prompt: negEdit.value,
      }));
    }
    promptSendTimer = null;
    _localPromptDirty = false;
    saveSharedSession();
  }, 500);
}

// ---- Prompt syntax highlight (main prompt only) ----
let currentMode = '';
function updatePromptHighlight() { if (promptHighlighter) promptHighlighter.update(); }
function syncPromptHighlight() { if (promptHighlighter) promptHighlighter.syncScroll(); }
function applyPromptHighlightState() { if (promptHighlighter) promptHighlighter.applyState(); }

function setNaiHighlightMode(mode) {
  currentMode = mode;
  if (promptHighlighter) promptHighlighter.setMode(mode);
}

// ---- Right panel top-level tabs ----

function switchRightTab(tabName) {
  if (rightTabs) rightTabs.switchTo(tabName);
}

// ---- Result history (disk-based image browser) ----
function initViewer() { if (resultHistory) resultHistory.initViewer(); }
function closeViewerLightbox() { if (resultHistory) resultHistory.closeLightbox(); }
function onLightboxClick(event) { if (resultHistory) resultHistory.onLightboxClick(event); }
function onViewerNewImage(message) { if (resultHistory) resultHistory.onNewImage(message); }
function jumpToLatestViewerImage() { if (resultHistory) resultHistory.jumpToLatest(); }
function openViewerPopup() { if (resultHistory) resultHistory.openPopup(); }
function closeViewerPopup() { if (resultHistory) resultHistory.closePopup(); }
function navViewerPopup(direction) { if (resultHistory) resultHistory.navPopup(direction); }
function toggleLightboxPrompt(forceVisible) { if (resultHistory) resultHistory.toggleLightboxPrompt(forceVisible); }
function viewerThumbClick(relPath) { if (resultHistory) resultHistory.thumbClick(relPath); }
function navViewer(direction) { if (resultHistory) resultHistory.navViewer(direction); }
function hideViewerNav() { if (resultHistory) resultHistory.hideNav(); }
function toggleVpPrompt(checked) { if (resultHistory) resultHistory.togglePopupPrompt(checked); }
function openResultFolder() { if (resultHistory) resultHistory.openFolder(); }
// ---- Stats functions ----

function toggleAutoSave() {
  openModule('auto_save');
}

function setAutoSaveEnabled(enabled) {
  autoSaveEnabled = !!enabled;
  if (lastAutoSaveModuleState) lastAutoSaveModuleState.auto_save = autoSaveEnabled;
  _updateSaveUI();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_option', key: 'auto_save', value: autoSaveEnabled}));
  }
}

function renderAutoSavePanel(state = lastAutoSaveModuleState) {
  const panelState = state || {
    auto_save: autoSaveEnabled,
    save_as_webp: false,
    history_limit_enabled: false,
    max_history_length: 2000,
    memory_action: 1,
    memory_action_options: [
      { value: 1, label: '[1] 1장씩 자동저장+정리' },
      { value: 2, label: '[2] 1장씩 저장없이 삭제' },
      { value: 3, label: '[3] 자동생성 중단' },
    ],
  };
  lastAutoSaveModuleState = panelState;
  const statusText = panelState.auto_save ? 'Enabled' : 'Disabled';
  const desc = sharedMode
    ? 'Shared Mode에서는 호스트의 Auto Save 설정을 따릅니다.'
    : 'Web Session은 시작 시 Auto Save가 강제로 켜집니다. 필요하면 여기서만 변경할 수 있습니다.';
  const actionOptions = (panelState.memory_action_options || []).map(opt =>
    `<option value="${opt.value}" ${String(opt.value) === String(panelState.memory_action) ? 'selected' : ''}>${escHtml(opt.label)}</option>`
  ).join('');
  moduleBody.innerHTML = `
    <div class="mod-settings-panel">
      <div class="mod-field">
        <span class="mod-field-label">Current Status</span>
        <div class="mod-status" style="text-align:left;min-height:0">${statusText}</div>
      </div>
      <div class="mod-field">
        <span class="mod-field-label">Policy</span>
        <div class="mod-status" style="text-align:left;line-height:1.6">${desc}</div>
      </div>
      <div class="mod-inline-row">
        <button class="mod-action-btn ${panelState.auto_save ? 'mod-stop' : 'mod-start'}"
                ${sharedMode ? 'disabled' : ''}
                onclick="setAutoSaveEnabled(${panelState.auto_save ? 'false' : 'true'})">
          ${panelState.auto_save ? 'Disable Auto Save' : 'Enable Auto Save'}
        </button>
        <button class="mod-btn-secondary" onclick="openSaveDirectoryPanel()">
          Save Directory Settings
        </button>
      </div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${panelState.save_as_webp ? 'checked' : ''} ${sharedMode ? 'disabled' : ''}
               onchange="onAutoSaveWebpChange(this.checked)">
        <span class="mod-checkbox-label">WEBP로 저장</span>
      </label>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${panelState.history_limit_enabled ? 'checked' : ''} ${sharedMode ? 'disabled' : ''}
               onchange="onHistoryLimitToggle(this.checked)">
        <span class="mod-checkbox-label">히스토리 큐 제한 활성화</span>
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Max History Length</span>
        <input class="mod-input" type="number" min="100" max="10000" step="100"
               value="${escHtml(String(panelState.max_history_length ?? 2000))}"
               ${panelState.history_limit_enabled && !sharedMode ? '' : 'disabled'}
               onchange="onHistoryLimitLengthChange(this.value)">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">On Limit Reached</span>
        <select class="mod-select" ${panelState.history_limit_enabled && !sharedMode ? '' : 'disabled'}
                onchange="onHistoryLimitActionChange(this.value)">
          ${actionOptions}
        </select>
      </label>
    </div>
  `;
}

function _updateSaveUI() {
  if (!statsSave) return;
  statsSave.classList.toggle('off', !autoSaveEnabled);
  // dot 뒤의 텍스트 노드만 교체 (dot span 유지)
  const dot = statsSave.querySelector('.stats-dot');
  const text = autoSaveEnabled ? 'Auto Save' : 'Auto Save OFF';
  if (dot) { dot.nextSibling.textContent = text; }
  statsSave.title = autoSaveEnabled ? 'Open auto-save settings (enabled)' : 'Open auto-save settings (disabled)';
  if (currentModuleId === 'auto_save' && modulePopup.classList.contains('open')) {
    renderAutoSavePanel();
  }
}

function updateGenStats() {
  // Count + Rate를 하나의 pill에 표시: "5 (1.2/m)"
  if (!statsGenCount) return;
  const now = Date.now();
  // Prune old timestamps
  while (sessionGenTimestamps.length > 0 && sessionGenTimestamps[0] < now - 3600000) {
    sessionGenTimestamps.shift();
  }
  // Rate 계산 (최근 10분)
  const tenMinAgo = now - 600000;
  const recent = sessionGenTimestamps.filter(t => t > tenMinAgo);
  let rateStr = '';
  if (recent.length >= 2) {
    const windowMs = now - recent[0];
    // 최소 60초 윈도우에서만 rate 표시 (짧은 구간 왜곡 방지)
    if (windowMs >= 60000) {
      rateStr = ' (' + (recent.length / (windowMs / 60000)).toFixed(1) + '/m)';
    }
  }
  statsGenCount.textContent = sessionGenTotal + rateStr;
}

function onLoadPrompt(prompt) {
  if (!prompt) return;
  // 사용자가 히스토리에서 "Load Prompt"를 명시적으로 클릭한 경우 — 편집 중이어도 즉시 적용.
  // (blur 시 자동 flush를 제거했으므로 defer하면 영원히 안 들어감)
  promptEdit.value = prompt;
  onPromptEdit();
  showToast('Prompt loaded', 'success');
}

function onSession(m) {
  if (m.session_id) sessionId = m.session_id;
  sharedMode = m.shared_server_mode || false;
  const autoGenCb = optBoxes.auto_generate;
  const naiOpt = modeSelect.querySelector('option[value="NAI"]');
  const sharedDisabledModules = ['automation', 'wildcard', 'chunk', 'search'];
  if (sharedMode) {
    // Auto Gen 차단
    if (autoGenCb) { autoGenCb.checked = false; autoGenCb.disabled = true; autoGenCb.parentElement.style.opacity = '0.4'; }
    // Auto Save 토글 차단 (호스트 전역 설정)
    if (statsSave) { statsSave.style.pointerEvents = 'none'; statsSave.style.opacity = '0.5'; }
    // Shared Mode 에선 모드 콤보박스 전체 비활성화 (호스트가 사전 설정)
    modeSelect.disabled = true;
    // API Configuration 진입점 자체 숨김 — Setup/연동은 호스트 전용
    if (setupLauncherBtn) setupLauncherBtn.style.display = 'none';
    // 혹시 모달이 열려 있으면 강제로 닫기 (Shared 전환 중 상태)
    if (setupOverlay && setupOverlay.classList.contains('open')) {
      _setupForced = false;
      setupOverlay.classList.remove('open');
    }
    // Anlas pill 숨김 — 호스트 잔액 노출 금지
    if (anlasPill) anlasPill.classList.add('hidden');
    // NAI 비활성화
    if (naiOpt) naiOpt.disabled = true;
    // Automation / WC / Chunk 비활성화
    sharedDisabledModules.forEach(mid => {
      const btn = document.querySelector(`.module-btn[data-module="${mid}"]`);
      if (btn) btn.classList.add('nai-only-disabled');
    });
    // 열려있는 차단 모듈 닫기
    if (sharedDisabledModules.includes(currentModuleId)) closeModule();
    // 초기 params/options/prompts 수신 대기 (select 옵션 목록 채우기 위해)
    _sharedParamsInit = false;
    _sharedOptionsInit = false;
    _sharedPromptsInit = false;
    // LocalStorage에서 세션 복원 (재연결 시)
    _restoreSharedSession();
  } else {
    // Shared Mode 해제 → 복원
    _restoringSession = false;  // 복원 가드 해제 (Shared ON → OFF 전환 시)
    if (_restoreSessionTimeout) { clearTimeout(_restoreSessionTimeout); _restoreSessionTimeout = null; }
    _sharedParamsInit = false;
    _sharedOptionsInit = false;
    _sharedPromptsInit = false;
    if (autoGenCb) { autoGenCb.disabled = false; autoGenCb.parentElement.style.opacity = ''; }
    if (statsSave) { statsSave.style.pointerEvents = ''; statsSave.style.opacity = ''; }
    modeSelect.disabled = false;
    if (setupLauncherBtn) setupLauncherBtn.style.display = '';
    // Anlas pill 은 서버가 다시 anlas_update 송신 시 자동으로 다시 표시됨
    if (naiOpt) naiOpt.disabled = false;
    sharedDisabledModules.forEach(mid => {
      const btn = document.querySelector(`.module-btn[data-module="${mid}"]`);
      if (btn) btn.classList.remove('nai-only-disabled');
    });
    clearSharedSession();
    if (quickFilter) quickFilter.reset({restoreSaved: true});
  }
  updateModeSelectAvailability();
}

function onDesktopWindowState(m) {
  if (typeof m.visible === 'boolean') desktopWindowVisible = m.visible;
  if (typeof m.control_allowed === 'boolean') desktopWindowControlAllowed = m.control_allowed;
  if (!desktopToggleBtn) return;

  if (!desktopWindowControlAllowed) {
    desktopToggleBtn.classList.add('hidden');
    return;
  }

  desktopToggleBtn.classList.remove('hidden');
  desktopToggleBtn.classList.toggle('visible-state', desktopWindowVisible);
  desktopToggleBtn.classList.toggle('hidden-state', !desktopWindowVisible);
  desktopToggleBtn.textContent = desktopWindowVisible ? 'HIDE DESKTOP' : 'SHOW DESKTOP';
  desktopToggleBtn.title = desktopWindowVisible ? 'Hide desktop app' : 'Show desktop app';
}

function toggleDesktopWindow() {
  if (!desktopWindowControlAllowed || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({
    type: 'set_desktop_window_visibility',
    visible: !desktopWindowVisible,
  }));
}

function _restoreSharedSession() {
  const saved = loadSharedSession();
  if (!saved) {
    // 저장된 세션 없음 (최초 접속) — GSQE 기본값을 서버에 전송
    if (ws && ws.readyState === WebSocket.OPEN) {
      const active = Object.keys(ratingState).filter(k => ratingState[k]);
      ws.send(JSON.stringify({type: 'set_active_ratings', ratings: active}));
    }
    syncRatingButtons();
    return;
  }
  // 서버 초기값(데스크톱 값) 무시 가드 ON
  _restoringSession = true;
  // 서버에 세션 복원 요청
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'restore_session', ...saved }));
  }
  // 클라이언트 UI 복원: options
  if (saved.options) {
    for (const [key, val] of Object.entries(saved.options)) {
      const cb = optBoxes[key];
      if (cb) cb.checked = val;
    }
    // Prompt Fixed → Random 버튼 차단
    if (optBoxes.prompt_fixed) {
      btnRnd.disabled = optBoxes.prompt_fixed.checked;
      btnRnd.style.opacity = optBoxes.prompt_fixed.checked ? '0.4' : '';
    }
    syncRatingBarVisibility();
  }
  // 클라이언트 UI 복원: prompt + negative prompt
  if (saved.prompt != null) { promptEdit.value = saved.prompt; updatePromptHighlight(); updatePromptTokenEstimate(); }
  if (saved.negative_prompt != null) {
    negEdit.value = saved.negative_prompt;
    updateNegativeTokenEstimate();
  }
  // Rating 복원
  if (saved.ratings && Array.isArray(saved.ratings)) {
    for (const k of ['g','s','q','e']) {
      ratingState[k] = saved.ratings.includes(k);
    }
    syncRatingButtons();
    // 서버 세션에 rating 저장
    if (ws && ws.readyState === WebSocket.OPEN) {
      const active = Object.keys(ratingState).filter(k => ratingState[k]);
      ws.send(JSON.stringify({type: 'set_active_ratings', ratings: active}));
    }
  }
  // Tag filter 복원
  if (quickFilter) quickFilter.restoreSharedState(saved);
  // P.Eng / Cond 캐시 복원 (모듈 열 때 사용)
  _sharedPEng = saved.p_eng || null;
  _sharedCond = saved.cond || null;
  // 가드 해제는 서버의 init_complete 메시지 수신 시 (onmessage 핸들러)
  // 안전망: init_complete 미수신 시 5초 후 강제 해제
  if (_restoreSessionTimeout) clearTimeout(_restoreSessionTimeout);
  _restoreSessionTimeout = setTimeout(() => {
    if (_restoringSession) {
      console.warn('init_complete timeout — forcing restore guard release');
      _restoringSession = false;
    }
    _restoreSessionTimeout = null;
  }, 5000);
}


// ---- Drawer & Tabs ----
const isPC = window.matchMedia('(min-width: 768px)');

function toggleDrawer() {
  if (isPC.matches) return;
  drawerOpen = !drawerOpen;
  promptDrawer.classList.toggle('open', drawerOpen);
  toggleBar.classList.toggle('open', drawerOpen);
  toggleArrow.classList.toggle('open', drawerOpen);
  toggleArrow2.classList.toggle('open', drawerOpen);
  toggleArrow.innerHTML = drawerOpen ? '&#9660;' : '&#9650;';
  toggleArrow2.innerHTML = drawerOpen ? '&#9660;' : '&#9650;';
  if (drawerOpen) {
    promptNewDot.classList.add('hidden');
    if (ws && ws.readyState === WebSocket.OPEN) ws.send('sync');
  }
}

isPC.addEventListener('change', () => {
  if (isPC.matches) {
    promptDrawer.classList.remove('open');
    drawerOpen = false;
  }
});

// ---- Mobile keyboard detection ----
// Hide bottom controls when virtual keyboard opens to maximize editing space
if (window.visualViewport) {
  const vv = window.visualViewport;
  const bottomCtrl = document.querySelector('.bottom-controls');
  const toggleBarEl = document.querySelector('.prompt-toggle-bar');
  let fullHeight = vv.height;
  let _kbOpen = false;
  // Update fullHeight when not focused (no keyboard)
  const modulePopupEl = document.querySelector('.module-popup');

  function _syncKbPositions() {
    // 모듈 팝업: 키보드 위에 전체 표시 (top 기준으로 전환)
    if (modulePopupEl) {
      modulePopupEl.style.top = vv.offsetTop + 'px';
      modulePopupEl.style.bottom = 'auto';
      modulePopupEl.style.maxHeight = vv.height + 'px';
    }
    relayoutFloatingPanels();
    // autocomplete/tag tooltip: viewport 상단에 고정 (키보드에 가려지지 않도록)
    if (tagTooltip) {
      tagTooltip.style.top = (vv.offsetTop + 4) + 'px';
      tagTooltip.style.maxHeight = Math.min(vv.height * 0.4, 200) + 'px';
    }
  }

  vv.addEventListener('resize', () => {
    if (isPC.matches) return;
    const shrink = fullHeight - vv.height;
    _kbOpen = shrink > 100; // >100px shrink = keyboard
    if (_kbOpen) {
      bottomCtrl.classList.add('kb-open');
      toggleBarEl.style.display = 'none';
      _syncKbPositions();
    } else {
      fullHeight = vv.height; // recalibrate
      bottomCtrl.classList.remove('kb-open');
      toggleBarEl.style.display = '';
      // 모듈 팝업: 원래 CSS로 복원
      if (modulePopupEl) {
        modulePopupEl.style.top = '';
        modulePopupEl.style.bottom = '';
        modulePopupEl.style.maxHeight = '';
      }
      relayoutFloatingPanels();
      // autocomplete/tag tooltip: 원래 CSS로 복원
      if (tagTooltip) {
        tagTooltip.style.top = '';
        tagTooltip.style.maxHeight = '';
      }
    }
  });

  // 키보드 열린 상태에서 브라우저 자동 스크롤 시 offsetTop 변화를 추적
  // (position:fixed는 layout viewport 기준 — iOS/Android 공통)
  vv.addEventListener('scroll', () => {
    if (_kbOpen) _syncKbPositions();
  });
}

window.addEventListener('resize', () => {
  relayoutFloatingPanels();
});

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
  $('tab' + name.charAt(0).toUpperCase() + name.slice(1)).classList.add('active');
}

// ---- Controls ----
function send(cmd) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (cmd === 'generate') {
    if (generating) return;
    if (promptSendTimer) { clearTimeout(promptSendTimer); promptSendTimer = null; }
    _localPromptDirty = false;
    ws.send(JSON.stringify({
      type: 'generate',
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    }));
    return;
  }
  if (cmd === 'random') {
    btnRnd.disabled = true;
    awaitingMyRandom = true;
    // 타임아웃 안전망: 일반 응답은 0.2초 내외이므로 2초면 충분합니다.
    if (window._randomTimeout) clearTimeout(window._randomTimeout);
    window._randomTimeout = setTimeout(() => {
      if (awaitingMyRandom) {
        unlockRandomButton();
      }
    }, 2000);
    // Shared Mode: 개인 rating 선호를 함께 전송
    if (sharedMode) {
      const active = Object.keys(ratingState).filter(k => ratingState[k]);
      ws.send(JSON.stringify({type: 'random', ratings: active}));
      return;
    }
  }
  ws.send(cmd);
}

function setGen(v) {
  generating = v;
  btnGen.disabled = v;
  if (v) {
    genStartTime = Date.now();
    btnGen.classList.add('generating');
    startGenTimer();
    startProgress();
  } else {
    if (genStartTime > 0) {
      const dur = Date.now() - genStartTime;
      if (dur > 500) { // ignore sub-500ms (errors/cancels)
        genDurations.push(dur);
        if (genDurations.length > 5) genDurations.shift();
      }
    }
    btnGen.classList.remove('generating');
    stopGenTimer();
    finishProgress();
    btnGen.innerHTML = '<span class="shortcut-hint">CTRL + ENTER</span>Generate';
  }
}

function startGenTimer() {
  stopGenTimer();
  genTimer = setInterval(() => {
    const elapsed = ((Date.now() - genStartTime) / 1000).toFixed(1);
    btnGen.innerHTML = `<span class="shortcut-hint">CTRL + ENTER</span>${elapsed}s`;
  }, 100);
}

function stopGenTimer() {
  if (genTimer) { clearInterval(genTimer); genTimer = null; }
}

// ---- Generation Progress Bar ----
function startProgress() {
  const bar = $('genProgressBar');
  const bar2 = $('genProgressBar2');
  const wrap = $('genProgress');
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  if (window._progressFinishTimeout) { clearTimeout(window._progressFinishTimeout); window._progressFinishTimeout = null; }
  bar.style.transition = 'none'; bar.style.width = '0%';
  bar2.style.transition = 'none'; bar2.style.width = '0%';
  void bar.offsetWidth;
  bar.style.transition = 'width 0.3s linear';
  bar2.style.transition = 'width 0.3s linear';
  wrap.classList.add('active');

  const estimated = genDurations.length > 0
    ? genDurations.reduce((a, b) => a + b, 0) / genDurations.length
    : 12000;

  progressTimer = setInterval(() => {
    const elapsed = Date.now() - genStartTime;
    const pct = Math.min((elapsed / estimated) * 100, 100);
    bar.style.width = pct + '%';
    // overtime: 2nd bar (orange) starts from 0%
    if (elapsed > estimated) {
      const overPct = Math.min(((elapsed - estimated) / estimated) * 100, 100);
      bar2.style.width = overPct + '%';
    }
  }, 50);
}

function finishProgress() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  if (window._progressFinishTimeout) { clearTimeout(window._progressFinishTimeout); window._progressFinishTimeout = null; }
  const bar = $('genProgressBar');
  const bar2 = $('genProgressBar2');
  const wrap = $('genProgress');
  bar.style.transition = 'width 0.2s ease-out';
  bar2.style.transition = 'width 0.2s ease-out';
  bar.style.width = '100%';
  window._progressFinishTimeout = setTimeout(() => {
    window._progressFinishTimeout = null;
    wrap.classList.remove('active');
    bar.style.width = '0%';
    bar2.style.width = '0%';
  }, 400);
}

// ---- Options sync ----
function syncOptions(m) {
  if (_restoringSession) return;  // 복원 중: 서버 초기값 무시
  // Shared Mode: 초기 1회만 서버 값 수용, 이후 broadcast 무시 (세션별 options 보호)
  if (sharedMode && _sharedOptionsInit) return;
  if (sharedMode) _sharedOptionsInit = true;
  syncingOptions = true;
  for (const [key, cb] of Object.entries(optBoxes)) {
    if (key in m) cb.checked = m[key];
  }
  syncingOptions = false;
  // Prompt Fixed 상태에 따라 Random 버튼 차단
  const pf = optBoxes.prompt_fixed;
  if (pf) {
    btnRnd.disabled = pf.checked;
    btnRnd.style.opacity = pf.checked ? '0.4' : '';
  }
  syncRatingBarVisibility();
  // Auto-save 상태 동기화
  if ('auto_save' in m) {
    autoSaveEnabled = m.auto_save;
    if (lastAutoSaveModuleState) lastAutoSaveModuleState.auto_save = m.auto_save;
    _updateSaveUI();
  }
}

function syncRatingBarVisibility() {
  const pf = optBoxes.prompt_fixed && optBoxes.prompt_fixed.checked;
  const wc = optBoxes.wildcard_standalone && optBoxes.wildcard_standalone.checked;
  const bar = document.querySelector('.tag-filter-rating-row');
  if (bar) bar.style.display = (pf || wc) ? 'none' : '';
}

function setOption(key, value) {
  if (syncingOptions) return;
  // Prompt Fixed → Random 버튼 차단/해제
  if (key === 'prompt_fixed') {
    btnRnd.disabled = !!value;
    btnRnd.style.opacity = value ? '0.4' : '';
  }
  if (key === 'prompt_fixed' || key === 'wildcard_standalone') {
    syncRatingBarVisibility();
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_option', key, value}));
  }
  saveSharedSession();
}

// ---- Mode sync ----
const modeSelect = $('modeSelect');
const uiLock = $('uiLock');
const toastEl = $('toast');
let syncingMode = false;
let modeSwitching = false;
let prevMode = modeSelect.value;
let toastTimer = null;
const API_MODES = ['NAI', 'WEBUI', 'COMFYUI'];

function isModeConnected(mode) {
  return _probeState && _probeState[mode] === 'ok';
}

function updateModeSelectAvailability() {
  if (!modeSelect) return;
  const anyConnected = API_MODES.some(mode => isModeConnected(mode));
  API_MODES.forEach(mode => {
    const opt = modeSelect.querySelector(`option[value="${mode}"]`);
    if (!opt) return;
    const connected = isModeConnected(mode);
    const displayFallback = !anyConnected && mode === modeSelect.value;
    opt.disabled = sharedMode ? opt.disabled : !(connected || displayFallback);
    opt.dataset.connected = connected ? '1' : '0';
  });

  if (sharedMode) {
    modeSelect.disabled = true;
  } else {
    modeSelect.disabled = modeSwitching || !anyConnected;
  }

  const currentConnected = isModeConnected(modeSelect.value);
  modeSelect.classList.toggle('mode-unavailable', !currentConnected);
  modeSelect.title = sharedMode
    ? 'Shared Server Mode controls API mode'
    : (anyConnected ? 'Only connected API modes are selectable' : 'No connected API session. Open API setup');
  if (modeApiCombo) {
    modeApiCombo.classList.toggle('has-connected-mode', anyConnected);
    modeApiCombo.classList.toggle('no-connected-mode', !anyConnected);
    modeApiCombo.classList.toggle('mode-unavailable', !currentConnected);
  }
}

function syncMode(mode) {
  syncingMode = true;
  modeSelect.value = mode;
  prevMode = mode;
  syncingMode = false;
  currentMode = mode;
  setNaiHighlightMode(mode);
  updatePromptTokenEstimate();
  // NAI 전용 모듈 버튼 비활성화 (character, character_reference, vibe_transfer)
  const isNai = mode === 'NAI';
  const naiOnlyModules = ['character', 'character_reference', 'vibe_transfer'];
  naiOnlyModules.forEach(mid => {
    const btn = document.querySelector(`.module-btn[data-module="${mid}"]`);
    if (btn) btn.classList.toggle('nai-only-disabled', !isNai);
  });
  // 비NAI 모드에서 열려있는 NAI 전용 모듈 닫기
  if (!isNai && naiOnlyModules.includes(currentModuleId)) {
    closeModule();
  }
  // Shared Mode + Cloudflared: NAI 옵션 비활성화
  if (sharedMode) {
    const naiOpt = modeSelect.querySelector('option[value="NAI"]');
    if (naiOpt) naiOpt.disabled = true;
  }
  updateModuleHeaderAction(currentModuleId);
  updateModeSelectAvailability();
}

function setMode(mode) {
  if (syncingMode) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!isModeConnected(mode)) {
    syncMode(prevMode);
    showToast(`${mode} API is not connected`, 'error', true);
    return;
  }
  uiLock.classList.add('active');
  modeSwitching = true;
  updateModeSelectAvailability();
  ws.send(JSON.stringify({type: 'set_mode', mode}));
}

function onModeResult(m) {
  uiLock.classList.remove('active');
  modeSwitching = false;
  if (m.success) {
    prevMode = m.mode;
    syncMode(m.mode);
    showToast(m.message || `${m.mode} mode active`, 'success');
  } else {
    syncMode(prevMode);
    showToast(m.message || 'Mode change failed', 'error', true);
  }
  updateModeSelectAvailability();
}

function showToast(msg, type, showConfigure) {
  if (toastTimer) clearTimeout(toastTimer);
  if (showConfigure) {
    toastEl.innerHTML = `${msg} — <a href="#" onclick="openApiPopup();return false" style="color:inherit;text-decoration:underline">Configure</a>`;
  } else {
    toastEl.textContent = msg;
  }
  toastEl.className = `toast ${type}`;
  requestAnimationFrame(() => toastEl.classList.add('show'));
  toastTimer = setTimeout(() => {
    toastEl.classList.remove('show');
  }, showConfigure ? 4000 : 2500);
}

// ---- Setup / Initial Configuration ----
// Sits on top of WS `api_status` / `verify_result` / `comfyui_models` / `setup_blocked`.
// When `setup_required` is true the modal is forced open and cannot be dismissed
// until at least one backend is verified.
const setupOverlay = $('apiPopupOverlay');
const setupDialog = $('setupDialog');
const setupCloseBtn = $('setupClose');
const setupSubTitle = document.querySelector('.setup-sub');
const _setupSubDefault = setupSubTitle ? setupSubTitle.textContent : '';
const setupNavDots    = { NAI: $('setupDotNai'),   WEBUI: $('setupDotWebui'),   COMFYUI: $('setupDotComfyui') };
const setupNavSubs    = { NAI: $('setupNavSubNai'), WEBUI: $('setupNavSubWebui'), COMFYUI: $('setupNavSubComfyui') };
const setupMetaEls    = { NAI: $('setupMetaNai'),  WEBUI: $('setupMetaWebui'),  COMFYUI: $('setupMetaComfyui') };
const setupResultEls  = { NAI: $('setupResultNai'), WEBUI: $('setupResultWebui'), COMFYUI: $('setupResultComfyui') };
const setupVerifyBtns = { NAI: $('setupBtnVerifyNai'), WEBUI: $('setupBtnVerifyWebui'), COMFYUI: $('setupBtnVerifyComfyui') };
let _setupForced = false;     // setup_required → true: close button hidden + backdrop ignored
let _setupAllowed = true;     // setup_allowed: gate check on server
let _apiStatusLast = null;
let _initialProbeDone = false; // WS 세션당 1회만 초기 probe 실행

function openApiPopup() {
  // Shared Mode 에서는 Setup/연동 원천 차단 (호스트 전용)
  if (sharedMode) return;
  setupOverlay.classList.add('open');
  if (_apiStatusLast) applySetupGate(_apiStatusLast);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send('sync');
    // probe 는 WS 첫 연결 때 1회만. 모달 재오픈 시엔 캐시된 dot 상태 유지.
    // (VERIFY / DISCONNECT 로 상태가 바뀌면 onVerifyResult / updateApiStatus 가 자동 반영.)
  }
}

// Live probe — keyring 값으로 실시간 ping. 저장 없음, 타임스탬프 영향 없음.
// State: 'ok' | 'err' | 'probing' | null(미설정)
const _probeState = { NAI: null, WEBUI: null, COMFYUI: null };
updateModeSelectAvailability();

function probeApi() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const last = _apiStatusLast || {};
  _probeState.NAI     = last.nai_configured ? 'probing' : null;
  _probeState.WEBUI   = (last.webui_url && last.webui_url.length)   ? 'probing' : null;
  _probeState.COMFYUI = (last.comfyui_url && last.comfyui_url.length) ? 'probing' : null;
  refreshDotsFromProbe();
  ws.send(JSON.stringify({ type: 'probe_api' }));
}

function onProbeResult(m) {
  const r = m.results || {};
  ['NAI', 'WEBUI', 'COMFYUI'].forEach(k => {
    if (r[k] === true)       _probeState[k] = 'ok';
    else if (r[k] === false) _probeState[k] = 'err';
    else                     _probeState[k] = null;  // not configured
  });
  refreshDotsFromProbe();
}

function refreshDotsFromProbe() {
  const map = { NAI: setupNavDots.NAI, WEBUI: setupNavDots.WEBUI, COMFYUI: setupNavDots.COMFYUI };
  Object.keys(map).forEach(k => {
    const el = map[k];
    if (!el) return;
    const s = _probeState[k];
    let cls = 'setup-nav-dot';
    if (s === 'ok')       cls += ' ok';
    else if (s === 'err') cls += ' err';
    else if (s === 'probing') cls += ' warn';
    el.className = cls;
  });
  updateModeSelectAvailability();
}

function closeApiPopup() {
  if (_setupForced) {
    showToast('Connect at least one backend first', 'error');
    return;
  }
  setupOverlay.classList.remove('open');
}

// Backdrop 클릭으로 모달 닫기 (단, setup_required 강제 모드에서는 무시)
function onSetupBackdrop(event) {
  if (event.target !== event.currentTarget) return;
  if (_setupForced) return;
  closeApiPopup();
}

function switchSetupTab(tab) {
  document.querySelectorAll('.setup-nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });
  document.querySelectorAll('.setup-tab-pane').forEach(el => {
    el.classList.toggle('active', el.dataset.pane === tab);
  });
}

function toggleSetupReveal(id, btn) {
  const el = $(id);
  if (!el) return;
  const hidden = el.type === 'password';
  el.type = hidden ? 'text' : 'password';
  btn.textContent = hidden ? '◈' : '◉';
}

function setSetupResult(mode, message, messageType) {
  const el = setupResultEls[mode];
  if (!el) return;
  const cls = (messageType === 'info' || messageType === 'warning' || messageType === 'error') ? messageType : '';
  el.className = 'setup-result ' + cls;
  el.textContent = message || '';
}

function setSetupLoading(mode, loading) {
  const btn = setupVerifyBtns[mode];
  if (!btn) return;
  btn.disabled = !!loading;
  btn.textContent = loading ? 'VERIFYING…' : 'VERIFY & SAVE';
}

let _setupBlockReason = '';
function _setupGateCheck() {
  if (!_setupAllowed) {
    showToast(_setupBlockReason || 'Setup blocked on this client', 'error');
    return false;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  return true;
}

function verifyNai() {
  if (!_setupGateCheck()) return;
  const token = $('setupNaiToken').value.trim();
  if (!token) { setSetupResult('NAI', 'Paste a token first', 'error'); return; }
  setSetupLoading('NAI', true);
  setSetupResult('NAI', '', '');
  ws.send(JSON.stringify({ type: 'verify_nai', token }));
}

function verifyWebui() {
  if (!_setupGateCheck()) return;
  const url = $('setupWebuiUrl').value.trim();
  if (!url) { setSetupResult('WEBUI', 'Enter a server URL first', 'error'); return; }
  setSetupLoading('WEBUI', true);
  setSetupResult('WEBUI', '', '');
  ws.send(JSON.stringify({ type: 'verify_webui', url }));
}

function verifyComfyui() {
  if (!_setupGateCheck()) return;
  const url = $('setupComfyuiUrl').value.trim();
  if (!url) { setSetupResult('COMFYUI', 'Enter a server URL first', 'error'); return; }
  setSetupLoading('COMFYUI', true);
  setSetupResult('COMFYUI', '', '');
  ws.send(JSON.stringify({ type: 'verify_comfyui', url }));
}

function clearApi(mode) {
  if (!_setupGateCheck()) return;
  if (!confirm(`Disconnect ${mode}?`)) return;
  ws.send(JSON.stringify({ type: 'clear_api', mode }));
  setSetupResult(mode, 'Disconnected', '');
  if (mode === 'NAI') $('setupNaiToken').value = '';
  if (mode === 'WEBUI') $('setupWebuiUrl').value = '';
  if (mode === 'COMFYUI') $('setupComfyuiUrl').value = '';
}

function onVerifyResult(m) {
  const mode = m.mode;
  setSetupLoading(mode, false);
  setSetupResult(mode, m.message, m.message_type);
  if (m.success && mode === 'NAI') {
    // Don't leave the token visible after success
    $('setupNaiToken').value = '';
  }
  // Reflect manual verify in the live dot (user just confirmed reachability)
  _probeState[mode] = m.success ? 'ok' : 'err';
  refreshDotsFromProbe();
}

function onSetupBlocked(m) {
  // probe_api 는 모달 열리지 않아도 ws.onopen 에서 자동 실행되므로,
  // 거부됐을 때 토스트를 띄우면 LAN 접속 사용자에게 불필요한 알림이 됨. 조용히 drop.
  if (m.command === 'probe_api') return;
  showToast(m.reason || 'Setup blocked on this client', 'error');
}

function renderCloudflaredControls(m) {
  if (cloudflaredControls) cloudflaredControls.render(m);
}

function setCloudflaredEnabled(enabled) {
  if (cloudflaredControls) cloudflaredControls.setEnabled(enabled);
}

function copyCloudflaredUrl() {
  if (cloudflaredControls) cloudflaredControls.copyUrl();
}

function applySetupGate(m) {
  _setupAllowed = m.setup_allowed !== false;
  _setupForced = !!m.setup_required;
  _setupBlockReason = m.setup_block_reason || '';
  setupDialog.classList.toggle('blocked', !_setupAllowed);
  if (_setupForced) {
    setupCloseBtn.classList.add('hidden');
    setupOverlay.classList.add('open');
  } else {
    setupCloseBtn.classList.remove('hidden');
  }
  if (setupSubTitle) {
    if (_setupAllowed) {
      setupSubTitle.classList.remove('blocked');
      setupSubTitle.textContent = _setupSubDefault;
    } else {
      setupSubTitle.classList.add('blocked');
      setupSubTitle.textContent = _setupBlockReason || 'Setup disabled — loopback access required.';
    }
  }
  // API launcher: violet pulse while no backend is connected
  if (setupLauncherBtn) setupLauncherBtn.classList.toggle('needs-setup', _setupForced);
  if (modeApiCombo) modeApiCombo.classList.toggle('needs-setup', _setupForced);
}

// API launcher doubles as the connection indicator. Three states:
//   online (success border) / offline (red border) / needs-setup (violet pulse)
function setLauncherConn(on) {
  if (!setupLauncherBtn) return;
  setupLauncherBtn.classList.toggle('online', !!on);
  setupLauncherBtn.classList.toggle('offline', !on);
  if (modeApiCombo) {
    modeApiCombo.classList.toggle('online', !!on);
    modeApiCombo.classList.toggle('offline', !on);
  }
}

// ---- NAI Anlas pill (viewer bottom-left) ----
// Desktop fetches subscription every 5 min + on every NAI generation,
// then broadcasts `anlas_update`. Web is read-only.
// NOTE: Opus 등급도 Anlas 를 소모하므로 무제한/∞ 표시 안 함. 단순 숫자만.
const anlasPill = $('anlasPill');
const anlasValue = $('anlasValue');
function onAnlasUpdate(m) {
  if (!anlasPill || !anlasValue) return;
  // Shared Mode 에서는 호스트 잔액을 절대 노출 안 함
  if (sharedMode) { anlasPill.classList.add('hidden'); return; }
  if (!m.available) {
    anlasPill.classList.add('hidden');
    return;
  }
  anlasPill.classList.remove('hidden');
  const n = Number(m.anlas || 0);
  anlasPill.classList.toggle('low', n > 0 && n < 100);
  anlasValue.textContent = n.toLocaleString();
}

function updateApiStatus(m) {
  _apiStatusLast = m;
  const lv = m.last_verified || {};

  // Dots are driven by live `probe_api` (see probeApi/onProbeResult), not by stored state.
  // Sub-labels reflect what's saved (token preview for NAI, host:port for WebUI/ComfyUI).
  // Hard-truncate the sub-label to keep the nav column fixed-width even when tunnels give very long URLs.
  const MAX_SUB = 18;
  const trunc = (s) => (s && s.length > MAX_SUB) ? (s.slice(0, MAX_SUB) + '…') : s;
  const subOf = (configured, preview) => {
    if (!configured) return 'NOT SET';
    if (!preview) return 'SAVED';
    return trunc(preview);
  };

  const hasNai   = !!m.nai_configured;
  const hasWebui = !!(m.webui_url && m.webui_url.length);
  const hasComfy = !!(m.comfyui_url && m.comfyui_url.length);

  if (setupNavSubs.NAI)     setupNavSubs.NAI.textContent     = subOf(hasNai, m.nai_token_preview || '');
  if (setupNavSubs.WEBUI)   setupNavSubs.WEBUI.textContent   = subOf(hasWebui, (m.webui_url || '').replace(/^https?:\/\//, ''));
  if (setupNavSubs.COMFYUI) setupNavSubs.COMFYUI.textContent = subOf(hasComfy, (m.comfyui_url || '').replace(/^https?:\/\//, ''));

  // If some mode went from configured→unconfigured (e.g. after clear_api),
  // drop the stale probe result so the dot goes dim instead of staying green.
  if (!hasNai   && _probeState.NAI     !== null) { _probeState.NAI     = null; refreshDotsFromProbe(); }
  if (!hasWebui && _probeState.WEBUI   !== null) { _probeState.WEBUI   = null; refreshDotsFromProbe(); }
  if (!hasComfy && _probeState.COMFYUI !== null) { _probeState.COMFYUI = null; refreshDotsFromProbe(); }

  if (setupMetaEls.NAI)     setupMetaEls.NAI.textContent     = lv.nai     || '—';
  if (setupMetaEls.WEBUI)   setupMetaEls.WEBUI.textContent   = lv.webui   || '—';
  if (setupMetaEls.COMFYUI) setupMetaEls.COMFYUI.textContent = lv.comfyui || '—';

  // Saved token preview — credentials never leave the server verbatim, just first 7 chars.
  const naiPrevEl = $('setupMetaNaiPreview');
  if (naiPrevEl) naiPrevEl.textContent = m.nai_token_preview ? (m.nai_token_preview + '…') : '—';
  const naiInput = $('setupNaiToken');
  if (naiInput) {
    naiInput.placeholder = hasNai
      ? (m.nai_token_preview ? 'Saved — paste new token to replace' : 'Saved — paste new token to replace')
      : 'paste NovelAI token';
  }

  // Populate URL fields only if the user hasn't typed something new
  const webuiUrlEl = $('setupWebuiUrl');
  if (webuiUrlEl && document.activeElement !== webuiUrlEl && !webuiUrlEl.value) {
    webuiUrlEl.value = (m.webui_url || '').replace(/^https?:\/\//, '');
  }
  const comfyUrlEl = $('setupComfyuiUrl');
  if (comfyUrlEl && document.activeElement !== comfyUrlEl && !comfyUrlEl.value) {
    comfyUrlEl.value = (m.comfyui_url || '').replace(/^https?:\/\//, '');
  }

  // ComfyUI model/sampling 은 Params 패널이 담당 (데스크탑 동기화). Setup 모달은 연결만 책임.

  applySetupGate(m);
  renderCloudflaredControls(m);

  // 첫 api_status 수신 시 세션당 1회 probe (이전 setTimeout 타이밍 의존 제거)
  if (!_initialProbeDone && ws && ws.readyState === WebSocket.OPEN) {
    _initialProbeDone = true;
    probeApi();
  }
}

// ---- Module floating panel ----
const modulePopup = $('modulePopup');
const moduleTitle = $('modulePopupTitle');
const moduleBody = $('modulePopupBody');
const modulePopupAction = $('modulePopupAction');
const chunkPanel = $('chunkPanel');
let currentModuleId = null;
let moduleSendTimer = null;
let pendingModuleEdit = null;
let lastAutoSaveModuleState = null;
let lastSaveDirectoryState = null;

// Preprocessing option definitions (key → display label)
const PP_OPTIONS = [
  ['remove_author', 'Remove Artist'],
  ['remove_work_title', 'Remove Work Title'],
  ['remove_character_name', 'Remove Character Name'],
  ['remove_character_features', 'Remove Char Features'],
  ['remove_clothes', 'Remove Clothing'],
  ['remove_color', 'Remove Color Tags'],
  ['remove_location_and_background_color', 'Remove Location/BG'],
  ['remove_expression', 'Remove Expression'],
  ['remove_pose_action', 'Remove Pose/Action'],
  ['remove_meta_tags', 'Remove Meta Tags'],
  ['remove_object_tags', 'Remove Object Tags'],
  ['remove_noise_tags', 'Remove Low-freq Tags'],
  ['e621_auto_boost', 'e621 Auto-Boost'],
  ['danbooru_auto_weight', 'Danbooru Auto-Weight'],
  ['tag_implication_compression', 'Tag Implication'],
];

const PP_OPTION_TONES = {
  remove_author: 'pe-tone-yellow',
  remove_work_title: 'pe-tone-yellow',
  remove_character_name: 'pe-tone-yellow',
  e621_auto_boost: 'pe-tone-pink',
  danbooru_auto_weight: 'pe-tone-teal',
  tag_implication_compression: 'pe-tone-teal',
};
const DANBOORU_MAGNITUDE_TABLE = {
  1:  { min_weight: 0.88, max_weight: 1.15, scale: 0.15, label: '약한' },
  2:  { min_weight: 0.84, max_weight: 1.25, scale: 0.25, label: '중간' },
  3:  { min_weight: 0.80, max_weight: 1.35, scale: 0.35, label: '추천' },
  4:  { min_weight: 0.75, max_weight: 1.42, scale: 0.42, label: '강한' },
  5:  { min_weight: 0.70, max_weight: 1.50, scale: 0.50, label: '최대' },
  6:  { min_weight: 0.62, max_weight: 1.60, scale: 0.60, label: '최대+' },
  7:  { min_weight: 0.55, max_weight: 1.70, scale: 0.70, label: '최대++' },
  8:  { min_weight: 0.50, max_weight: 1.80, scale: 0.80, label: '극한' },
  9:  { min_weight: 0.45, max_weight: 1.90, scale: 0.90, label: '극한+' },
  10: { min_weight: 0.40, max_weight: 2.00, scale: 1.00, label: '극한++' },
};
let lastPromptEngineeringState = null;

function updateModuleHeaderAction(moduleId) {
  if (!modulePopupAction) return;
  if (moduleId === 'prompt_engineering' && !sharedMode && modeSelect.value === 'NAI') {
    modulePopupAction.textContent = '추천 설정 적용';
    modulePopupAction.style.display = '';
    modulePopupAction.onclick = applyRecommendedPromptPreset;
    return;
  }
  modulePopupAction.style.display = 'none';
  modulePopupAction.onclick = null;
  modulePopupAction.textContent = '';
}

function openModule(moduleId) {
  // NAI 전용 모듈 가드
  if (['character', 'character_reference', 'vibe_transfer'].includes(moduleId) && modeSelect.value !== 'NAI') {
    showToast('This module is only available in NAI mode', 'error');
    return;
  }
  // Shared Mode: 데스크톱 전용 모듈 차단
  if (sharedMode && ['automation', 'wildcard', 'chunk', 'search'].includes(moduleId)) {
    showToast('This module is not available in Shared Server Mode', 'error');
    return;
  }
  // Toggle: same module clicked again → close
  if (currentModuleId === moduleId && modulePopup.classList.contains('open')) {
    closeModule();
    return;
  }
  flushPendingModuleEdit(currentModuleId);
  closeAuxiliaryPopups();
  currentModuleId = moduleId;
  modulePopup.classList.add('open');
  relayoutFloatingPanels();
  updateModuleBtnState();
  updateModuleHeaderAction(moduleId);
  moduleBody.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  const titles = {
    auto_save: 'Auto Save',
    save_directory: 'Save Directory',
    search: 'Prompt Search',
    prompt_engineering: 'Prompt Engineering',
    automation: 'Automation',
    character: 'NAID4 Character',
    character_reference: 'Character Reference',
    vibe_transfer: 'Vibe Transfer',
    conditional_prompt: 'Conditional Prompt',
    wildcard: 'Wildcard',
    chunk: 'Chunk',
  };
  moduleTitle.textContent = titles[moduleId] || moduleId;
  if (moduleId === 'auto_save' && lastAutoSaveModuleState) {
    renderAutoSavePanel(lastAutoSaveModuleState);
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    if (moduleId === 'search') {
      ws.send(JSON.stringify({type: 'get_search_state'}));
    } else {
      ws.send(JSON.stringify({type: 'get_module_state', module_id: moduleId}));
    }
  }
}

function closeModule() {
  flushPendingModuleEdit(currentModuleId);
  modulePopup.classList.remove('open');
  closeAuxiliaryPopups();
  currentModuleId = null;
  chunkTriggerInfo = null;
  updateModuleHeaderAction(null);
  updateModuleBtnState();
}

function updateModuleBtnState() {
  document.querySelectorAll('.module-btn').forEach(btn => {
    const isChunkBtn = btn.dataset.module === 'chunk';
    btn.classList.toggle('active', isChunkBtn ? chunkOpen : btn.dataset.module === currentModuleId);
  });
  const pb = document.querySelector('.module-prompt-btn');
  if (pb) pb.classList.toggle('active', currentModuleId === 'search');
}

const peE621Panel = $('peE621Panel');
const pePresetAddPanel = $('pePresetAddPanel');
const pePresetManagePanel = $('pePresetManagePanel');
const peDanbooruPanel = $('peDanbooruPanel');
const peDebugPanel = $('peDebugPanel');
let chunkOpen = false;
let chunkAnchorEl = null;
let peE621Open = false;
let pePresetAddOpen = false;
let pePresetManageOpen = false;
let peDanbooruOpen = false;
let peDebugOpen = false;

function requestPromptEngineeringState() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'get_module_state', module_id: 'prompt_engineering'}));
  }
}

function closeAllPePanels() {
  closePeE621Panel();
  closePePresetAddPanel();
  closePePresetManagePanel();
  closePeDanbooruPanel();
  closePeDebugPanel();
}

function closeAuxiliaryPopups(exceptPanel = null) {
  if (exceptPanel !== chunkPanel && chunkOpen) closeChunkPanel();
  if (exceptPanel !== refinePanel && refineOpen) closeRefine();
  if (exceptPanel !== pePresetAddPanel && pePresetAddOpen) closePePresetAddPanel();
  if (exceptPanel !== pePresetManagePanel && pePresetManageOpen) closePePresetManagePanel();
  if (exceptPanel !== peE621Panel && peE621Open) closePeE621Panel();
  if (exceptPanel !== peDanbooruPanel && peDanbooruOpen) closePeDanbooruPanel();
  if (exceptPanel !== peDebugPanel && peDebugOpen) closePeDebugPanel();

  const tagFilterPopup = document.getElementById('tagFilterPopup');
  if (exceptPanel !== tagFilterPopup && tagFilterPopup?.classList.contains('open')) {
    closeTagFilter();
  }
}

function openPePresetAddPanel() {
  if (sharedMode) return;
  if (pePresetAddOpen) { closePePresetAddPanel(); return; }
  closeAuxiliaryPopups(pePresetAddPanel);
  pePresetAddOpen = true;
  pePresetAddPanel.classList.add('open');
  positionFloatingPanel(pePresetAddPanel, modulePopup);
  const body = pePresetAddPanel.querySelector('.pe-popup-body');
  if (body) body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  syncPromptEngineeringPopups();
  requestPromptEngineeringState();
}

function closePePresetAddPanel() {
  pePresetAddOpen = false;
  pePresetAddPanel.classList.remove('open');
}

function openPePresetManagePanel() {
  if (sharedMode) return;
  if (pePresetManageOpen) { closePePresetManagePanel(); return; }
  closeAuxiliaryPopups(pePresetManagePanel);
  pePresetManageOpen = true;
  pePresetManagePanel.classList.add('open');
  positionFloatingPanel(pePresetManagePanel, modulePopup);
  const body = pePresetManagePanel.querySelector('.pe-popup-body');
  if (body) body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  syncPromptEngineeringPopups();
  requestPromptEngineeringState();
}

function closePePresetManagePanel() {
  pePresetManageOpen = false;
  pePresetManagePanel.classList.remove('open');
}

function openPeE621Panel() {
  if (peE621Open) { closePeE621Panel(); return; }
  closeAuxiliaryPopups(peE621Panel);
  peE621Open = true;
  peE621Panel.classList.add('open');
  positionFloatingPanel(peE621Panel, modulePopup);
  const body = peE621Panel.querySelector('.pe-popup-body');
  if (body) body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  syncPromptEngineeringPopups();
  requestPromptEngineeringState();
}

function closePeE621Panel() {
  peE621Open = false;
  peE621Panel.classList.remove('open');
}

function openPeDanbooruPanel() {
  if (peDanbooruOpen) { closePeDanbooruPanel(); return; }
  closeAuxiliaryPopups(peDanbooruPanel);
  peDanbooruOpen = true;
  peDanbooruPanel.classList.add('open');
  positionFloatingPanel(peDanbooruPanel, modulePopup);
  const body = peDanbooruPanel.querySelector('.pe-popup-body');
  if (body) body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  syncPromptEngineeringPopups();
  requestPromptEngineeringState();
}

function closePeDanbooruPanel() {
  peDanbooruOpen = false;
  peDanbooruPanel.classList.remove('open');
}

function openPeDebugPanel() {
  if (peDebugOpen) { closePeDebugPanel(); return; }
  closeAuxiliaryPopups(peDebugPanel);
  peDebugOpen = true;
  peDebugPanel.classList.add('open');
  positionFloatingPanel(peDebugPanel, modulePopup);
  const body = peDebugPanel.querySelector('.pe-popup-body');
  if (body) body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  syncPromptEngineeringPopups();
  refreshPromptEngineeringDebug();
}

function closePeDebugPanel() {
  peDebugOpen = false;
  peDebugPanel.classList.remove('open');
}

function syncPromptEngineeringPopups() {
  relayoutFloatingPanels();
  if (!lastPromptEngineeringState) return;
  if (pePresetAddOpen) renderPePresetAddPanel(lastPromptEngineeringState);
  if (pePresetManageOpen) renderPePresetManagePanel(lastPromptEngineeringState);
  if (peE621Open) renderPeE621Panel(lastPromptEngineeringState);
  if (peDanbooruOpen) renderPeDanbooruPanel(lastPromptEngineeringState);
  if (peDebugOpen) renderPeDebugPanel(lastPromptEngineeringState);
}

function onModuleState(m) {
  // Update status badges regardless of panel open state
  if (m.module_id === 'automation') updateAutoBadge(m);
  else if (m.module_id === 'auto_save') lastAutoSaveModuleState = m;
  else if (m.module_id === 'character') updateCharBadge(m);
  else if (m.module_id === 'character_reference') updateCharRefBadge(m);
  else if (m.module_id === 'vibe_transfer') updateVibeBadge(m);
  else if (m.module_id === 'save_directory') lastSaveDirectoryState = m;

  if (m.module_id === 'prompt_engineering') {
    lastPromptEngineeringState = m;
    syncPromptEngineeringPopups();
  }
  if (m.module_id === 'chunk' && chunkOpen) {
    renderChunk(m);
  }

  if (m.module_id !== currentModuleId) return;
  if (m.module_id === 'auto_save') renderAutoSavePanel(m);
  else if (m.module_id === 'prompt_engineering') renderPromptEngineering(m);
  else if (m.module_id === 'automation') renderAutomation(m);
  else if (m.module_id === 'character') renderCharacter(m);
  else if (m.module_id === 'conditional_prompt') renderConditionalPrompt(m);
  else if (m.module_id === 'character_reference') renderCharacterReference(m);
  else if (m.module_id === 'vibe_transfer') renderVibeTransfer(m);
  else if (m.module_id === 'save_directory') renderSaveDirectory(m);
  else if (m.module_id === 'wildcard') renderWildcard(m);
}

function openSaveDirectoryPanel() {
  openModule('save_directory');
}

function onAutoSaveWebpChange(checked) {
  if (lastAutoSaveModuleState) lastAutoSaveModuleState.save_as_webp = !!checked;
  setModuleParam('auto_save', 'save_as_webp', checked ? 'true' : 'false');
}

function onHistoryLimitToggle(checked) {
  if (lastAutoSaveModuleState) {
    lastAutoSaveModuleState.history_limit_enabled = !!checked;
    renderAutoSavePanel(lastAutoSaveModuleState);
  }
  setModuleParam('auto_save', 'history_limit_enabled', checked ? 'true' : 'false');
}

function onHistoryLimitLengthChange(value) {
  const parsed = parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    showToast('Valid history length required.', 'error');
    return;
  }
  if (lastAutoSaveModuleState) lastAutoSaveModuleState.max_history_length = parsed;
  setModuleParam('auto_save', 'max_history_length', String(parsed));
}

function onHistoryLimitActionChange(value) {
  if (lastAutoSaveModuleState) lastAutoSaveModuleState.memory_action = parseInt(value, 10);
  setModuleParam('auto_save', 'memory_action', value);
}

function browseSaveDirectory() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'browse_save_directory'}));
  }
}

function onSaveDirectoryToggle(checked) {
  if (lastSaveDirectoryState) {
    lastSaveDirectoryState.use_timestamp_folder = !!checked;
    renderSaveDirectory(lastSaveDirectoryState);
  }
  setModuleParam('save_directory', 'use_timestamp_folder', checked ? 'true' : 'false');
}

function onSaveDirectoryFilenameFormatChange(value) {
  if (lastSaveDirectoryState) {
    lastSaveDirectoryState.filename_format = value;
  }
  setModuleParam('save_directory', 'filename_format', value);
}

function onSaveDirectoryClassificationChange(value) {
  if (lastSaveDirectoryState) {
    lastSaveDirectoryState.classification_method = value;
    renderSaveDirectory(lastSaveDirectoryState);
  }
  setModuleParam('save_directory', 'classification_method', value);
}

function renderSaveDirectory(m) {
  lastSaveDirectoryState = m;
  const controlAllowed = !!m.control_allowed;
  const browseAllowed = !!m.browse_allowed;
  const filenameOptions = (m.filename_format_options || []).map(opt =>
    `<option value="${escHtml(opt.value)}" ${opt.value === m.filename_format ? 'selected' : ''}>${escHtml(opt.label)}</option>`
  ).join('');
  const classificationOptions = (m.classification_method_options || []).map(opt =>
    `<option value="${escHtml(opt.value)}" ${opt.value === m.classification_method ? 'selected' : ''}>${escHtml(opt.label)}</option>`
  ).join('');
  const rulesVisible = m.classification_method === 'prompt_recognition';
  const accessNotice = !controlAllowed
    ? `<div class="mod-notice">${escHtml(m.control_block_reason || 'This setting is read-only on this client.')}</div>`
    : '';
  const browseNotice = !browseAllowed && m.browse_block_reason
    ? `<div class="mod-debug-empty">${escHtml(m.browse_block_reason)}</div>`
    : '';

  moduleBody.innerHTML = `
    <div class="mod-settings-panel">
      <div class="mod-field">
        <span class="mod-field-label">Current Save Directory</span>
        <div class="mod-status" style="text-align:left;line-height:1.6;word-break:break-all">${escHtml(m.current_save_directory || '')}</div>
      </div>
      <div class="mod-field">
        <span class="mod-field-label">Session Timestamp</span>
        <div class="mod-status" style="text-align:left;min-height:0">${escHtml(m.session_timestamp || '—')}</div>
      </div>
      ${accessNotice}
      <label class="mod-field">
        <span class="mod-field-label">Base Save Path</span>
        <input class="mod-input" id="saveDirBasePath" value="${escHtml(m.base_path || '')}" readonly disabled autocomplete="off" spellcheck="false">
        <div class="mod-inline-row">
          <button class="mod-btn-secondary" ${browseAllowed ? '' : 'disabled'} onclick="browseSaveDirectory()">Browse</button>
        </div>
        ${browseNotice}
      </label>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.use_timestamp_folder ? 'checked' : ''} ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryToggle(this.checked)">
        <span class="mod-checkbox-label">날짜_시간 폴더 사용 (${escHtml(m.session_timestamp || 'session')}/)</span>
      </label>
      <div class="mod-field">
        <span class="mod-field-label">Current Counter</span>
        <div class="mod-status" style="text-align:left;min-height:0">${escHtml(String(m.save_counter ?? 1))}</div>
      </div>
      <label class="mod-field">
        <span class="mod-field-label">Filename Format</span>
        <select class="mod-select" ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryFilenameFormatChange(this.value)">
          ${filenameOptions}
        </select>
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Classification Method</span>
        <select class="mod-select" ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryClassificationChange(this.value)">
          ${classificationOptions}
        </select>
      </label>
      ${rulesVisible ? `
        <label class="mod-field">
          <span class="mod-field-label">Classification Rules</span>
          <textarea class="mod-textarea mod-textarea-lg" ${controlAllowed ? '' : 'disabled'}
                    placeholder="*1girl, (*solo&*1girl), (landscape|scenery)"
                    oninput="onModTextEdit('save_directory','classification_rules',this.value)">${escHtml(m.classification_rules || '')}</textarea>
        </label>
      ` : ''}
    </div>
  `;
}

// ---- Module button inline badges ----
function updateAutoBadge(m) {
  if (moduleBadges) moduleBadges.updateAuto(m);
}

function updateCharBadge(m) {
  if (moduleBadges) moduleBadges.updateCharacter(m);
}

function updateCharRefBadge(m) {
  if (moduleBadges) moduleBadges.updateCharacterReference(m);
}

function updateVibeBadge(m) {
  if (moduleBadges) moduleBadges.updateVibe(m);
}

// prompt_engineering 모듈의 편집 가능한 textarea 목록 (focus 보존 대상)
const PE_EDITABLE_IDS = ['modPrePrompt', 'modPostPrompt', 'modAutoHide'];

function _capturePromptEngineeringFocus() {
  const active = document.activeElement;
  if (!active || !PE_EDITABLE_IDS.includes(active.id)) return null;
  return {
    id: active.id,
    value: active.value,
    selectionStart: active.selectionStart,
    selectionEnd: active.selectionEnd,
    scrollTop: active.scrollTop,
  };
}

function _restorePromptEngineeringFocus(snap) {
  if (!snap) return;
  const el = document.getElementById(snap.id);
  if (!el) return;
  // 편집 중이던 로컬 값 + 커서/스크롤 복원. 서버 broadcast가 현재 편집값과 다른 값을 보내더라도
  // 사용자 로컬 편집을 우선 (debounce flush 후 서버에 반영됨).
  el.value = snap.value;
  el.scrollTop = snap.scrollTop;
  try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
  try { el.setSelectionRange(snap.selectionStart, snap.selectionEnd); } catch (e) {}
}

function renderPromptEngineering(m) {
  const _peFocusSnap = _capturePromptEngineeringFocus();
  if (sharedMode) {
    if (_sharedPEng) {
      // 캐시 우선 적용 (서버는 데스크톱 값 반환, 세션 값이 우선)
      if (_sharedPEng.pre_prompt != null) m.pre_prompt = _sharedPEng.pre_prompt;
      if (_sharedPEng.post_prompt != null) m.post_prompt = _sharedPEng.post_prompt;
      if (_sharedPEng.auto_hide != null) m.auto_hide = _sharedPEng.auto_hide;
      if (_sharedPEng.preset != null) m.preset = _sharedPEng.preset;
      if (_sharedPEng.preprocessing_options) {
        if (!m.preprocessing) m.preprocessing = {};
        for (const [k, v] of Object.entries(_sharedPEng.preprocessing_options)) {
          m.preprocessing[k] = v;
        }
      }
    }
    // 렌더링된 최종 상태를 캐시에 전체 스냅샷 (편집 안 한 필드도 포함)
    _sharedPEng = {
      pre_prompt: m.pre_prompt || '',
      post_prompt: m.post_prompt || '',
      auto_hide: m.auto_hide || '',
      preset: m.preset || '',
      preprocessing_options: m.preprocessing ? {...m.preprocessing} : {},
    };
    saveSharedSession();
  }
  const canSaveCurrent = !!m.preset_can_save_current && !sharedMode;
  const canDeleteCurrent = !!m.preset_can_delete && !sharedMode;

  const presetOpts = (m.preset_options || [])
    .map(p => `<option value="${p}"${p === m.preset ? ' selected' : ''}>${p}</option>`).join('');

  const pp = m.preprocessing || {};
  const ppHtml = PP_OPTIONS.map(([key, label]) =>
    `<label class="mod-checkbox-item ${PP_OPTION_TONES[key] || ''}">
      <input type="checkbox" ${pp[key] ? 'checked' : ''} oninput="setPromptEngineeringOption('${key}', this.checked)">
      <span class="mod-checkbox-label">${label}</span>
    </label>`
  ).join('');

  const presetControlHtml = sharedMode ? `
    <div>
      <div class="mod-section-label">Preset</div>
      <select class="mod-select" id="modPreset" onchange="onPromptPresetChange(this.value)">${presetOpts}</select>
    </div>
  ` : `
    <div>
      <div class="mod-section-label">Quick Preset</div>
      <div class="mod-preset-toolbar">
        <select class="mod-select mod-preset-select" id="modPreset" onchange="onPromptPresetChange(this.value)">${presetOpts}</select>
        <button class="mod-btn-secondary mod-btn-compact" onclick="openPePresetAddPanel()">Add</button>
        <button class="mod-btn-secondary mod-btn-compact" onclick="openPePresetManagePanel()">Manage</button>
      </div>
    </div>
  `;

  const advancedHtml = sharedMode ? '' : `
    <div>
      <div class="mod-section-label">Tools</div>
      <div class="mod-inline-row">
        <button class="mod-btn-secondary" onclick="openPeE621Panel()">e621 Auto-Boost Settings</button>
        <button class="mod-btn-secondary" onclick="openPeDanbooruPanel()">Danbooru Auto-Weight Settings</button>
      </div>
      <div class="mod-inline-row">
        <button class="mod-btn-secondary" onclick="openPeDebugPanel()">Debug Snapshot</button>
      </div>
    </div>
  `;

  moduleBody.innerHTML = `
    ${presetControlHtml}
    <div>
      <div class="mod-section-label">Prefix Prompt</div>
      <textarea class="mod-textarea mod-textarea-lg" id="modPrePrompt" placeholder="prefix tags..." oninput="onModTextEdit('prompt_engineering','pre_prompt',this.value)">${escHtml(m.pre_prompt)}</textarea>
    </div>
    <div>
      <div class="mod-section-label">Postfix Prompt</div>
      <textarea class="mod-textarea mod-textarea-lg" id="modPostPrompt" placeholder="postfix tags..." oninput="onModTextEdit('prompt_engineering','post_prompt',this.value)">${escHtml(m.post_prompt)}</textarea>
    </div>
    <div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">Auto-Hide (Filter) <span class="mod-collapse-arrow">▶</span></div>
      <textarea class="mod-textarea collapsed" id="modAutoHide" placeholder="tags to filter out..." oninput="onModTextEdit('prompt_engineering','auto_hide',this.value)">${escHtml(m.auto_hide)}</textarea>
    </div>
    <div>
      <div class="mod-section-label">Preprocessing Options</div>
      <div class="mod-checkbox-grid">${ppHtml}</div>
    </div>
    ${advancedHtml}
  `;
  // Bind autocomplete to pre/post prompt textareas
  ['modPrePrompt', 'modPostPrompt'].forEach(id => {
    const el = document.getElementById(id);
    if (el) bindTagAssist(el);
  });
  // 재빌드 이전에 편집 중이던 필드 복원 (focus + value + selection)
  _restorePromptEngineeringFocus(_peFocusSnap);
}

function renderPePresetAddPanel(m) {
  const body = pePresetAddPanel.querySelector('.pe-popup-body');
  if (!body) return;
  body.innerHTML = `
    <div class="mod-section-label">Current Preset</div>
    <div class="mod-info-chip">${escHtml(m.preset || '(none)')}</div>
    <label class="mod-field">
      <span class="mod-field-label">New Preset Name</span>
      <input class="mod-input" id="modPresetNewName" placeholder="new preset name" autocomplete="off" spellcheck="false">
    </label>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="createPromptPreset()">Save As</button>
      <button class="mod-btn-secondary" onclick="closePePresetAddPanel()">Close</button>
    </div>
  `;
  const input = document.getElementById('modPresetNewName');
  if (input) {
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        createPromptPreset();
      }
    });
    requestAnimationFrame(() => input.focus());
  }
}

function renderPePresetManagePanel(m) {
  const body = pePresetManagePanel.querySelector('.pe-popup-body');
  if (!body) return;
  const canSaveCurrent = !!m.preset_can_save_current && !sharedMode;
  const canDeleteCurrent = !!m.preset_can_delete && !sharedMode;
  body.innerHTML = `
    <div class="mod-section-label">Current Preset</div>
    <div class="mod-info-chip">${escHtml(m.preset || '(none)')}</div>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" ${canSaveCurrent ? '' : 'disabled'} onclick="saveCurrentPromptPreset()">Save Current</button>
      <button class="mod-btn-danger" ${canDeleteCurrent ? '' : 'disabled'} onclick="deleteCurrentPromptPreset()">Delete Current</button>
    </div>
  `;
}

function renderPromptEngineeringDebug(snapshot) {
  const sourceInfo = snapshot.source_info || {};
  const filterLog = Array.isArray(snapshot.filter_log) ? snapshot.filter_log : [];
  const implicationInfo = Array.isArray(snapshot.implication_info) ? snapshot.implication_info : [];
  const e621Info = snapshot.e621_info || {};
  const originalCount = Number(snapshot.original_count || 0);
  const remainingCount = Number(snapshot.remaining_count || 0);
  const hasDebugData = filterLog.length || implicationInfo.length || (e621Info.results || []).length || Object.values(sourceInfo).some(Boolean);

  if (!hasDebugData) {
    return '<div class="mod-debug-empty">No debug data yet. Generate a prompt once.</div>';
  }

  const sourceRows = Object.entries(sourceInfo)
    .filter(([, value]) => value != null && String(value).trim() !== '')
    .map(([key, value]) => `<div class="mod-debug-meta"><span>${escHtml(key)}</span><strong>${escHtml(String(value))}</strong></div>`)
    .join('');

  const filterRounds = filterLog.map(entry => {
    const removed = Array.isArray(entry.removed) ? entry.removed : [];
    const status = !entry.enabled ? 'OFF' : (removed.length ? `ON · ${removed.length} removed` : 'ON');
    return `
      <div class="mod-debug-round">
        <div class="mod-debug-round-title">${escHtml(entry.name || 'Round')} <span>${status}</span></div>
        ${removed.length ? `<pre class="mod-debug-block">${escHtml(removed.join(', '))}</pre>` : ''}
      </div>
    `;
  }).join('');

  const implicationHtml = implicationInfo.length
    ? `
      <div class="mod-debug-round">
        <div class="mod-debug-round-title">Tag Implication <span>${implicationInfo.length} removed</span></div>
        <pre class="mod-debug-block">${escHtml(implicationInfo.map(item => `${item.removed} <- ${item.by}`).join('\n'))}</pre>
      </div>
    `
    : '';

  const e621Results = Array.isArray(e621Info.results) ? e621Info.results : [];
  const e621Html = e621Results.length
    ? `
      <div class="mod-debug-round">
        <div class="mod-debug-round-title">e621 Auto-Boost <span>${e621Results.length} suggested</span></div>
        <pre class="mod-debug-block">${escHtml(`input: ${(e621Info.input_tags || []).join(', ')}`)}</pre>
        <pre class="mod-debug-block">${escHtml(e621Results.map(item => `${item.tag} (${Number(item.score || 0).toFixed(4)}) [${item.cat || ''}] <- ${item.src || ''}`).join('\n'))}</pre>
      </div>
    `
    : '';

  return `
    ${sourceRows ? `<div class="mod-debug-meta-grid">${sourceRows}</div>` : ''}
    <div class="mod-debug-summary">Original ${originalCount} → Remaining ${remainingCount} · Removed ${Math.max(0, originalCount - remainingCount)}</div>
    ${filterRounds}
    ${implicationHtml}
    ${e621Html}
  `;
}

function renderPeE621Panel(m) {
  const body = peE621Panel.querySelector('.pe-popup-body');
  if (!body) return;
  const e621 = m.e621_settings || {};
  const e621Hidden = Array.isArray(e621.hidden_tags) ? e621.hidden_tags.join(', ') : '';
  body.innerHTML = `
    <div class="mod-section-label">Weight / Mode</div>
    <div class="mod-inline-row">
      <input class="mod-input" id="modE621Weight" type="number" min="-5" max="5" step="0.05" value="${escHtml(String(e621.weight ?? 0))}" placeholder="weight">
      <select class="mod-select" id="modE621Mode">
        <option value="stable"${e621.mode === 'stable' || !e621.mode ? ' selected' : ''}>stable</option>
        <option value="confused"${e621.mode === 'confused' ? ' selected' : ''}>confused</option>
      </select>
    </div>
    <div>
      <div class="mod-section-label">Hidden Tags</div>
      <textarea class="mod-textarea" id="modE621HiddenTags" placeholder="comma or newline separated tags">${escHtml(e621Hidden)}</textarea>
    </div>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="savePromptEngineeringE621Settings()">Save e621 Settings</button>
    </div>
  `;
}

function getDanbooruPreviewState(baseSettings = {}) {
  const numberValue = (id, fallback) => {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const parsed = parseFloat(el.value ?? '');
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const intValue = (id, fallback) => {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const parsed = parseInt(el.value ?? '', 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const magnitude = Math.max(1, Math.min(10, intValue('modDanMagnitude', Number(baseSettings.magnitude ?? 3))));
  const preset = DANBOORU_MAGNITUDE_TABLE[magnitude] || DANBOORU_MAGNITUDE_TABLE[3];
  const overrideOn = !!document.getElementById('modDanOverrideOn')?.checked;
  const ratingOverrideOn = !!document.getElementById('modDanRatingOverrideOn')?.checked;
  const minWeight = overrideOn
    ? numberValue('modDanOverrideMin', Number(baseSettings.override_min ?? preset.min_weight))
    : preset.min_weight;
  const maxWeight = overrideOn
    ? numberValue('modDanOverrideMax', Number(baseSettings.override_max ?? preset.max_weight))
    : preset.max_weight;
  const scale = overrideOn
    ? numberValue('modDanOverrideScale', Number(baseSettings.override_scale ?? preset.scale))
    : preset.scale;
  const blend = numberValue('modDanBlend', Number(baseSettings.rating_blend ?? 0.3));

  return {
    magnitude,
    label: preset.label,
    overrideOn,
    ratingOverrideOn,
    ratingOverride: document.getElementById('modDanRatingOverride')?.value || baseSettings.rating_override || 's',
    invertWeight: !!document.getElementById('modDanInvertWeight')?.checked,
    minWeight,
    maxWeight,
    scale,
    blend,
  };
}

function renderDanbooruVisualFeedback(state) {
  const spread = Math.max(0, state.maxWeight - state.minWeight);
  const chipTone = spread >= 0.9 ? 'danger' : spread >= 0.55 ? 'accent' : 'muted';
  const samples = [
    { label: 'Common', value: state.invertWeight ? state.maxWeight : state.minWeight, tone: state.invertWeight ? 'high' : 'low' },
    { label: 'Neutral', value: 1.0, tone: 'mid' },
    { label: 'Rare', value: state.invertWeight ? state.minWeight : state.maxWeight, tone: state.invertWeight ? 'low' : 'high' },
  ];
  const maxVisual = Math.max(2.0, state.maxWeight, state.minWeight, 1.0);
  const ratingLabelMap = { g: 'General', s: 'Sensitive', q: 'Questionable', e: 'Explicit' };
  const directionText = state.invertWeight ? 'High-frequency tags gain weight' : 'Rare tags gain weight';

  const sampleRows = samples.map((item) => {
    const pct = Math.max(6, Math.min(100, (item.value / maxVisual) * 100));
    return `
      <div class="mod-dan-sample-row">
        <span class="mod-dan-sample-label">${item.label}</span>
        <div class="mod-dan-sample-bar">
          <span class="mod-dan-sample-fill ${item.tone}" style="width:${pct}%"></span>
        </div>
        <strong>${item.value.toFixed(2)}</strong>
      </div>
    `;
  }).join('');

  return `
    <div class="mod-dan-feedback-card">
      <div class="mod-dan-feedback-head">
        <div>
          <div class="mod-dan-feedback-title">${state.magnitude}단계 · ${state.label}</div>
          <div class="mod-dan-feedback-subtitle">${state.overrideOn ? 'Custom curve active' : 'Preset curve active'} · ${directionText}</div>
        </div>
        <span class="mod-dan-pill ${chipTone}">spread ${spread.toFixed(2)}</span>
      </div>
      <div class="mod-dan-pill-row">
        <span class="mod-dan-pill muted">scale ${state.scale.toFixed(2)}</span>
        <span class="mod-dan-pill muted">blend ${(state.blend * 100).toFixed(0)}%</span>
        <span class="mod-dan-pill ${state.ratingOverrideOn ? 'accent' : 'muted'}">${state.ratingOverrideOn ? `IDF ${ratingLabelMap[state.ratingOverride] || state.ratingOverride}` : 'IDF auto'}</span>
        <span class="mod-dan-pill ${state.invertWeight ? 'danger' : 'muted'}">${state.invertWeight ? 'inverted' : 'normal'}</span>
      </div>
      <div class="mod-dan-range-caption">Effective weight curve</div>
      <div class="mod-dan-sample-list">${sampleRows}</div>
    </div>
  `;
}

function syncDanbooruFeedback(baseSettings = {}) {
  const feedback = document.getElementById('modDanFeedback');
  if (!feedback) return;
  const state = getDanbooruPreviewState(baseSettings);
  feedback.innerHTML = renderDanbooruVisualFeedback(state);

  const overrideOn = !!document.getElementById('modDanOverrideOn')?.checked;
  const ratingOverrideOn = !!document.getElementById('modDanRatingOverrideOn')?.checked;
  ['modDanOverrideScale', 'modDanOverrideMin', 'modDanOverrideMax'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !overrideOn;
  });
  const ratingSelect = document.getElementById('modDanRatingOverride');
  if (ratingSelect) ratingSelect.disabled = !ratingOverrideOn;
}

function bindDanbooruFeedback(baseSettings = {}) {
  const ids = [
    'modDanMagnitude',
    'modDanBlend',
    'modDanOverrideOn',
    'modDanOverrideScale',
    'modDanOverrideMin',
    'modDanOverrideMax',
    'modDanRatingOverrideOn',
    'modDanRatingOverride',
    'modDanInvertWeight',
  ];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const eventName = el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input';
    el.addEventListener(eventName, () => syncDanbooruFeedback(baseSettings));
  });
  syncDanbooruFeedback(baseSettings);
}

function renderPeDanbooruPanel(m) {
  const body = peDanbooruPanel.querySelector('.pe-popup-body');
  if (!body) return;
  const danbooru = m.danbooru_settings || {};
  body.innerHTML = `
    <div id="modDanFeedback"></div>
    <div class="mod-grid-2">
      <label class="mod-field">
        <span class="mod-field-label">Magnitude</span>
        <input class="mod-input" id="modDanMagnitude" type="number" min="1" max="10" step="1" value="${escHtml(String(danbooru.magnitude ?? 3))}">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Rating Blend</span>
        <input class="mod-input" id="modDanBlend" type="number" min="0" max="1" step="0.1" value="${escHtml(String(danbooru.rating_blend ?? 0.3))}">
      </label>
    </div>
    <label class="mod-checkbox-item">
      <input type="checkbox" id="modDanOverrideOn" ${danbooru.override_on ? 'checked' : ''}>
      <span class="mod-checkbox-label">Custom Override</span>
    </label>
    <div class="mod-grid-3">
      <label class="mod-field">
        <span class="mod-field-label">Scale</span>
        <input class="mod-input" id="modDanOverrideScale" type="number" min="0" max="5" step="0.05" value="${escHtml(String(danbooru.override_scale ?? 0.35))}">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Min</span>
        <input class="mod-input" id="modDanOverrideMin" type="number" min="0" max="5" step="0.05" value="${escHtml(String(danbooru.override_min ?? 0.8))}">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Max</span>
        <input class="mod-input" id="modDanOverrideMax" type="number" min="0" max="10" step="0.05" value="${escHtml(String(danbooru.override_max ?? 1.35))}">
      </label>
    </div>
    <label class="mod-checkbox-item">
      <input type="checkbox" id="modDanRatingOverrideOn" ${danbooru.rating_override_on ? 'checked' : ''}>
      <span class="mod-checkbox-label">Rating Override</span>
    </label>
    <div class="mod-inline-row">
      <select class="mod-select" id="modDanRatingOverride">
        <option value="g"${danbooru.rating_override === 'g' ? ' selected' : ''}>General</option>
        <option value="s"${danbooru.rating_override === 's' || !danbooru.rating_override ? ' selected' : ''}>Sensitive</option>
        <option value="q"${danbooru.rating_override === 'q' ? ' selected' : ''}>Questionable</option>
        <option value="e"${danbooru.rating_override === 'e' ? ' selected' : ''}>Explicit</option>
      </select>
    </div>
    <label class="mod-checkbox-item">
      <input type="checkbox" id="modDanInvertWeight" ${danbooru.invert_weight ? 'checked' : ''}>
      <span class="mod-checkbox-label">Invert Weight</span>
    </label>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="savePromptEngineeringDanbooruSettings()">Save Danbooru Settings</button>
    </div>
  `;
  bindDanbooruFeedback(danbooru);
}

function renderPeDebugPanel(m) {
  const body = peDebugPanel.querySelector('.pe-popup-body');
  if (!body) return;
  body.innerHTML = `
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="refreshPromptEngineeringDebug()">Refresh Debug</button>
    </div>
    ${renderPromptEngineeringDebug(m.debug_snapshot || {})}
  `;
}

function flushPromptEngineeringEdits() {
  if (currentModuleId !== 'prompt_engineering') return;
  flushPendingModuleEdit('prompt_engineering');
  const pre = document.getElementById('modPrePrompt');
  const post = document.getElementById('modPostPrompt');
  const autoHide = document.getElementById('modAutoHide');
  if (pre) setModuleParam('prompt_engineering', 'pre_prompt', pre.value, {skipPendingFlush: true});
  if (post) setModuleParam('prompt_engineering', 'post_prompt', post.value, {skipPendingFlush: true});
  if (autoHide) setModuleParam('prompt_engineering', 'auto_hide', autoHide.value, {skipPendingFlush: true});
}

function flushMainPromptAndParams() {
  if (promptSendTimer) {
    clearTimeout(promptSendTimer);
    promptSendTimer = null;
  }
  _localPromptDirty = false;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'set_prompt',
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    }));
    const params = _collectCurrentParams();
    Object.entries(params).forEach(([key, value]) => {
      ws.send(JSON.stringify({type: 'set_param', key, value}));
    });
  }
  saveSharedSession();
}

function flushPromptPresetSaveState() {
  flushPromptEngineeringEdits();
  flushMainPromptAndParams();
}

function onPromptPresetChange(value) {
  flushPromptPresetSaveState();
  setModuleParam('prompt_engineering', 'preset', value);
}

function saveCurrentPromptPreset() {
  flushPromptPresetSaveState();
  setModuleParam('prompt_engineering', 'preset_save_current', 'true');
}

function createPromptPreset() {
  const input = document.getElementById('modPresetNewName');
  const name = input ? input.value.trim() : '';
  if (!name) {
    showToast('Preset name required', 'error');
    return;
  }
  flushPromptPresetSaveState();
  setModuleParam('prompt_engineering', 'preset_create', name);
  if (input) input.value = '';
  closePePresetAddPanel();
}

function applyRecommendedPromptPreset() {
  if (sharedMode) return;
  if (modeSelect.value !== 'NAI') {
    showToast('추천 설정 적용은 NAI 모드에서만 사용할 수 있습니다.', 'error');
    return;
  }
  if (!confirm('추천 설정을 새 프리셋으로 만들고 즉시 적용하시겠습니까?')) return;
  setModuleParam('prompt_engineering', 'preset_apply_recommended', 'true');
}

function deleteCurrentPromptPreset() {
  const preset = document.getElementById('modPreset')?.value || '';
  if (!preset || preset === 'default' || preset === '*randomized') {
    showToast('This preset cannot be deleted', 'error');
    return;
  }
  if (!confirm(`Delete preset "${preset}"?`)) return;
  setModuleParam('prompt_engineering', 'preset_delete', preset);
  closePePresetManagePanel();
}

function savePromptEngineeringE621Settings() {
  const hiddenRaw = document.getElementById('modE621HiddenTags')?.value || '';
  const hiddenTags = hiddenRaw
    .split(/[\n,]+/)
    .map(tag => tag.trim())
    .filter(Boolean);
  const payload = {
    weight: parseFloat(document.getElementById('modE621Weight')?.value || '0') || 0,
    mode: document.getElementById('modE621Mode')?.value || 'stable',
    hidden_tags: hiddenTags,
  };
  setModuleParam('prompt_engineering', 'e621_settings', JSON.stringify(payload));
}

function savePromptEngineeringDanbooruSettings() {
  const numberValue = (id, fallback) => {
    const parsed = parseFloat(document.getElementById(id)?.value ?? '');
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const intValue = (id, fallback) => {
    const parsed = parseInt(document.getElementById(id)?.value ?? '', 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const payload = {
    magnitude: intValue('modDanMagnitude', 3),
    rating_blend: numberValue('modDanBlend', 0.3),
    override_on: !!document.getElementById('modDanOverrideOn')?.checked,
    override_scale: numberValue('modDanOverrideScale', 0.35),
    override_min: numberValue('modDanOverrideMin', 0.8),
    override_max: numberValue('modDanOverrideMax', 1.35),
    rating_override_on: !!document.getElementById('modDanRatingOverrideOn')?.checked,
    rating_override: document.getElementById('modDanRatingOverride')?.value || 's',
    invert_weight: !!document.getElementById('modDanInvertWeight')?.checked,
  };
  setModuleParam('prompt_engineering', 'danbooru_settings', JSON.stringify(payload));
}

function refreshPromptEngineeringDebug() {
  setModuleParam('prompt_engineering', 'debug_refresh', 'true');
}

function flushPendingModuleEdit(moduleId = null) {
  if (!pendingModuleEdit) return;
  if (moduleId && pendingModuleEdit.moduleId !== moduleId) return;
  if (moduleSendTimer) {
    clearTimeout(moduleSendTimer);
    moduleSendTimer = null;
  }
  const pending = pendingModuleEdit;
  pendingModuleEdit = null;
  setModuleParam(pending.moduleId, pending.key, pending.value, {skipPendingFlush: true});
}

function setPromptEngineeringOption(key, checked) {
  if (lastPromptEngineeringState) {
    if (!lastPromptEngineeringState.preprocessing) lastPromptEngineeringState.preprocessing = {};
    lastPromptEngineeringState.preprocessing[key] = !!checked;
  }
  setModuleParam('prompt_engineering', `pp_${key}`, checked ? 'true' : 'false');
}

function setModuleParam(moduleId, key, value, options = {}) {
  if (!options.skipPendingFlush) flushPendingModuleEdit(moduleId);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_module_param', module_id: moduleId, key, value}));
  }
  // Shared Mode: P.Eng/Cond 로컬 캐시 갱신
  if (sharedMode) {
    if (moduleId === 'prompt_engineering') {
      if (!_sharedPEng) _sharedPEng = {};
      if (key === 'pre_prompt' || key === 'post_prompt' || key === 'auto_hide') {
        _sharedPEng[key] = value;
      } else if (key.startsWith('pp_')) {
        if (!_sharedPEng.preprocessing_options) _sharedPEng.preprocessing_options = {};
        _sharedPEng.preprocessing_options[key.slice(3)] = (value === 'true');
      } else if (key === 'preset') {
        _sharedPEng.preset = value;
      }
      saveSharedSession();
    } else if (moduleId === 'conditional_prompt') {
      if (!_sharedCond) _sharedCond = {};
      if (key === 'enabled') _sharedCond.enabled = (value === 'true');
      else if (key === 'rules') _sharedCond.rules = value;
      saveSharedSession();
    }
  }
}

function onModTextEdit(moduleId, key, value) {
  if (moduleSendTimer) clearTimeout(moduleSendTimer);
  pendingModuleEdit = {moduleId, key, value};
  moduleSendTimer = setTimeout(() => {
    const pending = pendingModuleEdit;
    pendingModuleEdit = null;
    moduleSendTimer = null;
    if (pending) setModuleParam(pending.moduleId, pending.key, pending.value, {skipPendingFlush: true});
  }, 500);
}

function flushCharacterEdits() {
  if (currentModuleId !== 'character') return;
  if (moduleSendTimer) {
    clearTimeout(moduleSendTimer);
    moduleSendTimer = null;
  }
  pendingModuleEdit = null;
  const chars = document.querySelectorAll('[data-char-index]');
  chars.forEach((block) => {
    const idx = block.dataset.charIndex;
    const prompt = block.querySelector('.mod-char-prompt');
    const uc = block.querySelector('.mod-char-uc');
    if (prompt) setModuleParam('character', `char_prompt_${idx}`, prompt.value);
    if (uc) setModuleParam('character', `char_uc_${idx}`, uc.value);
  });
}

function addCharacterSlot() {
  flushCharacterEdits();
  setModuleParam('character', 'add_character', 'true');
}

function removeCharacterSlot(index) {
  flushCharacterEdits();
  setModuleParam('character', `remove_character_${index}`, 'true');
}

function refreshCharacterPreview() {
  flushCharacterEdits();
  setModuleParam('character', 'preview_refresh', 'true');
}

// ---- Automation module ----
let lastAutoState = null;
function onAutoTypeChange(val) {
  setModuleParam('automation', 'auto_type', val);
  if (lastAutoState) {
    lastAutoState.auto_type = parseInt(val);
    renderAutomation(lastAutoState);
  }
}
function renderAutomation(m) {
  lastAutoState = m;
  const typeLabels = ['Unlimited', 'Timer', 'Count'];
  const typeRadios = typeLabels.map((label, i) =>
    `<label class="mod-checkbox-item">
      <input type="radio" name="autoType" value="${i}" ${m.auto_type === i ? 'checked' : ''} onchange="onAutoTypeChange(this.value)">
      <span class="mod-checkbox-label">${label}</span>
    </label>`
  ).join('');

  const isRunning = m.is_running;
  moduleBody.innerHTML = `
    <div>
      <div class="mod-section-label">Delay (seconds)</div>
      <div style="display:flex;gap:8px;align-items:center">
        <input class="mod-input" type="text" value="${m.delay || '0'}" onchange="setModuleParam('automation','delay',this.value)" style="flex:1">
        <label class="mod-checkbox-item" style="margin:0">
          <input type="checkbox" ${m.random_delay ? 'checked' : ''} oninput="setModuleParam('automation','random_delay',String(this.checked))">
          <span class="mod-checkbox-label">Random ±50%</span>
        </label>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Repeat Count</div>
      <input class="mod-input" type="text" value="${m.repeat || '1'}" onchange="setModuleParam('automation','repeat',this.value)">
    </div>
    <div>
      <div class="mod-section-label">Termination</div>
      <div class="mod-checkbox-grid" style="grid-template-columns:1fr 1fr 1fr">${typeRadios}</div>
    </div>
    ${m.auto_type === 1 ? `<div>
      <div class="mod-section-label">Timer (minutes)</div>
      <input class="mod-input" type="text" value="${m.timer_minutes || '30'}" onchange="setModuleParam('automation','timer_minutes',this.value)">
    </div>` : ''}
    ${m.auto_type === 2 ? `<div>
      <div class="mod-section-label">Count Limit</div>
      <input class="mod-input" type="text" value="${m.count_limit || '100'}" onchange="setModuleParam('automation','count_limit',this.value)">
    </div>` : ''}
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.notify ? 'checked' : ''} oninput="setModuleParam('automation','notify',String(this.checked))">
        <span class="mod-checkbox-label">Notify on completion</span>
      </label>
    </div>
    <div style="display:flex;gap:8px">
      <button class="mod-action-btn mod-start" ${isRunning ? 'disabled' : ''} onclick="setModuleParam('automation','start','1')">Start</button>
      <button class="mod-action-btn mod-stop" ${!isRunning ? 'disabled' : ''} onclick="setModuleParam('automation','stop','1')">Stop</button>
    </div>
    <div class="mod-status">${m.status || ''}</div>
  `;
}

// ---- Character module ----
function renderCharacter(m) {
  const chars = m.characters || [];
  const charsHtml = chars.map((c, i) => `
    <div class="mod-char-block" data-char-index="${i}">
      <div class="mod-char-header">
        <label class="mod-checkbox-item" style="margin:0">
          <input type="checkbox" ${c.active ? 'checked' : ''} oninput="setModuleParam('character','char_active_${i}',String(this.checked))">
          <span class="mod-checkbox-label">C${c.id}</span>
        </label>
        <button class="mod-btn-sm mod-btn-danger" ${chars.length > 1 ? '' : 'disabled'} onclick="removeCharacterSlot(${i})">Remove</button>
      </div>
      <textarea class="mod-textarea mod-char-prompt" placeholder="character prompt..." oninput="onModTextEdit('character','char_prompt_${i}',this.value)">${escHtml(c.prompt)}</textarea>
      <textarea class="mod-textarea mod-uc mod-char-uc" placeholder="negative prompt (UC)..." oninput="onModTextEdit('character','char_uc_${i}',this.value)">${escHtml(c.uc)}</textarea>
    </div>
  `).join('');
  const previewText = m.processed_preview_text || '';
  const previewEmpty = !previewText.trim();

  moduleBody.innerHTML = `
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.activated ? 'checked' : ''} oninput="setModuleParam('character','activated',String(this.checked))">
        <span class="mod-checkbox-label">Enable Character Prompts (NAID4+)</span>
      </label>
    </div>
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.reroll_on_generate ? 'checked' : ''} oninput="setModuleParam('character','reroll_on_generate',String(this.checked))">
        <span class="mod-checkbox-label">Process wildcards on Generate</span>
      </label>
    </div>
    <div class="mod-char-actions">
      <button class="mod-btn-sm" onclick="addCharacterSlot()">+ Add Character</button>
      <button class="mod-btn-sm mod-btn-encode" onclick="refreshCharacterPreview()">Refresh Preview</button>
      <span class="mod-char-meta">${m.active_count || 0} active / ${m.character_count || chars.length} slots</span>
    </div>
    ${charsHtml}
    <div class="mod-char-preview">
      <div class="mod-section-label">Final Applied Character Prompt</div>
      ${previewEmpty
        ? '<div class="mod-empty">No preview yet. Use Refresh Preview to process wildcards and show the applied character prompts.</div>'
        : `<pre class="mod-char-preview-text">${escHtml(previewText)}</pre>`}
    </div>
  `;
  // Bind autocomplete to character prompt textareas (not UC)
  moduleBody.querySelectorAll('.mod-textarea:not(.mod-uc)').forEach(el => bindTagAssist(el));
}

// ---- Conditional Prompt module ----
function formatCondLog(log) {
  if (!log) return '<span style="color:var(--text-dim)">No log yet</span>';
  return escHtml(log).split('\n').map(line => {
    if (!line.trim()) return '';
    if (line.includes('Condition Not Met') || line.includes('Error:'))
      return `<div style="color:#888">${line}</div>`;
    if (line.includes('Condition Met'))
      return `<div style="color:#4CAF50">${line}</div>`;
    if (line.startsWith('==='))
      return `<div style="color:#fff;font-weight:bold">${line}</div>`;
    return `<div>${line}</div>`;
  }).join('');
}

function formatCondRules(text) {
  if (!text) return '<br>';
  return text.split('\n').map(line => {
    if (!line) return '<div class="cond-line"> </div>';
    // 콤마 구분 엔트리별 # 주석 하이라이트
    let result = '';
    let i = 0, inQuote = false;
    let segStart = 0;
    while (i <= line.length) {
      if (i < line.length && line[i] === '"') inQuote = !inQuote;
      if (i === line.length || (line[i] === ',' && !inQuote)) {
        const seg = line.substring(segStart, i);
        const comma = i < line.length ? ',' : '';
        const esc = escHtml(seg);
        if (seg.trimStart().startsWith('#')) {
          result += `<span class="cond-comment">${esc}</span>${escHtml(comma)}`;
        } else {
          result += esc + escHtml(comma);
        }
        segStart = i + 1;
      }
      i++;
    }
    return `<div class="cond-line">${result || ' '}</div>`;
  }).join('') + '<br>';
}
function onCondRulesInput(el) {
  const hl = document.getElementById('condRulesHighlight');
  if (hl) hl.innerHTML = formatCondRules(el.value);
  onModTextEdit('conditional_prompt', 'rules', el.value);
}
function syncCondScroll(el) {
  const hl = document.getElementById('condRulesHighlight');
  if (hl) { hl.scrollTop = el.scrollTop; hl.scrollLeft = el.scrollLeft; }
}

function renderConditionalPrompt(m) {
  if (sharedMode) {
    if (_sharedCond) {
      // 캐시 우선 적용
      if (_sharedCond.enabled != null) m.enabled = _sharedCond.enabled;
      if (_sharedCond.rules != null) m.rules = _sharedCond.rules;
    }
    // 렌더링된 최종 상태를 캐시에 전체 스냅샷
    _sharedCond = { enabled: !!m.enabled, rules: m.rules || '' };
    saveSharedSession();
  }
  moduleBody.innerHTML = `
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.enabled ? 'checked' : ''} oninput="setModuleParam('conditional_prompt','enabled',String(this.checked))">
        <span class="mod-checkbox-label">Enable Conditional Prompt</span>
      </label>
    </div>
    <div>
      <div class="mod-section-label">Rules</div>
      <div class="cond-rules-wrap">
        <div class="cond-rules-highlight" id="condRulesHighlight">${formatCondRules(m.rules)}</div>
        <textarea class="mod-textarea cond-rules-input" id="condRulesInput" placeholder="(condition):action&#10;# comment lines ignored" oninput="onCondRulesInput(this)" onscroll="syncCondScroll(this)">${escHtml(m.rules)}</textarea>
      </div>
    </div>
    <div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
        Syntax Guide <span class="mod-collapse-arrow">▶</span>
      </div>
      <div class="collapsed" style="font-size:10px;color:var(--text-dim);line-height:1.5;padding:6px 0">
        <b>Condition:</b> tag, ~tag (NOT), *tag (exact), e|q|s|g (rating)<br>
        <b>Logic:</b> &amp; (AND), | (OR), () grouping<br>
        <b>Actions:</b><br>
        &nbsp; tag=new_tag (replace)<br>
        &nbsp; main+=tag (append to main)<br>
        &nbsp; prefix+=tag / postfix+=tag<br>
        &nbsp; ^ = multi-tag separator<br>
        &nbsp; "quoted, tags" for comma values<br>
        <b>Example:</b> (e):prefix+=nsfw^rating:explicit,
      </div>
    </div>
    <div>
      <button class="mod-action-btn mod-start" onclick="setModuleParam('conditional_prompt','test','1')">Test Rules</button>
    </div>
    <div>
      <div class="mod-section-label">Execution Log</div>
      <div class="mod-log-viewer" id="condLogViewer">${formatCondLog(m.log)}</div>
    </div>
  `;
}

// ---- Wildcard Module ----
function renderWildcard(m) {
  // History
  let historyHtml = '';
  if (m.history && m.history.length) {
    historyHtml = m.history.map(h => {
      const n = escHtml(h.name), v = escHtml(h.value);
      return `<div>▶ ${n}: ${v}</div>`;
    }).join('');
  } else {
    historyHtml = '<div class="mod-empty">No wildcards used</div>';
  }

  // Sequential/Dependent state
  let stateHtml = '';
  if (m.state && m.state.length) {
    stateHtml = m.state.map(s => `<div>▶ ${escHtml(s.name)}: ${s.current} / ${s.total}</div>`).join('');
  } else {
    stateHtml = '<div class="mod-empty">No active sequential wildcards</div>';
  }

  // Instant wildcard groups
  let instantHtml = '';
  if (m.instant_groups && m.instant_groups.length) {
    instantHtml = m.instant_groups.map(g => {
      const keys = (g.keys || []).map(k => escHtml(k)).join(', ');
      const more = g.count > 20 ? ` <span style="color:var(--text-dim)">+${g.count - 20} more</span>` : '';
      return `<div class="mod-wc-group">
        <div class="mod-wc-group-header">$${escHtml(g.name)} <span style="color:var(--text-dim)">(${g.count})</span></div>
        <div class="mod-wc-group-keys">${keys}${more}</div>
      </div>`;
    }).join('');
  } else {
    instantHtml = '<div class="mod-empty">No instant wildcards</div>';
  }

  moduleBody.innerHTML = `
    <div class="mod-section">
      <div class="mod-section-label">Used Wildcards</div>
      <div class="mod-wc-history">${historyHtml}</div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Sequential / Dependent State</div>
      <div class="mod-wc-state">${stateHtml}</div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Instant Wildcards</div>
      <div class="mod-wc-instant">${instantHtml}</div>
    </div>
    <div class="mod-section">
      <label class="mod-check-row">
        <input type="checkbox" ${m.prompt_squeeze ? 'checked' : ''} oninput="setModuleParam('wildcard','prompt_squeeze',String(this.checked))">
        <span style="font-size:12px">NovelAI 403 Prevention</span>
      </label>
    </div>
    <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <button class="mod-btn-sm" onclick="wcOpenBrowser()">Browse Files</button>
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reset_sequential','')">Reset Seq</button>
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reload','')">Reload</button>
      <span style="color:var(--text-dim);font-size:11px;margin-left:auto">Loaded: ${m.wildcard_count || 0}</span>
    </div>
  `;
}

// ---- Chunk Module (instant wildcard tree browser) ----
let chunkTriggerInfo = null;  // {raw, stripped, start, end} — 삽입 위치

function requestChunkState() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'get_module_state', module_id: 'chunk'}));
  }
}

function getChunkAnchor(target = null) {
  return target?.closest?.('.module-popup, .pe-popup, .refine-popup, .tag-filter-popup') || modulePopup;
}

function openChunkPanel(anchorEl = null, toggle = false) {
  if (sharedMode) {
    showToast('This module is not available in Shared Server Mode', 'error');
    return;
  }
  if (toggle && chunkOpen) {
    closeChunkPanel();
    return;
  }
  chunkAnchorEl = anchorEl || chunkAnchorEl || modulePopup;
  chunkOpen = true;
  if (chunkPanel) {
    chunkPanel.classList.add('open');
    const body = chunkPanel.querySelector('.pe-popup-body');
    if (body) {
      body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
    }
    positionFloatingPanel(chunkPanel, chunkAnchorEl);
  }
  updateModuleBtnState();
  requestChunkState();
}

function closeChunkPanel() {
  chunkOpen = false;
  chunkTriggerInfo = null;
  if (chunkPanel) chunkPanel.classList.remove('open');
  updateModuleBtnState();
}

function renderChunk(m) {
  const chunkBody = chunkPanel ? chunkPanel.querySelector('.pe-popup-body') : null;
  const renderTarget = (chunkOpen && chunkBody) ? chunkBody : moduleBody;
  const groups = m.groups || [];
  if (!groups.length) {
    renderTarget.innerHTML = '<div class="mod-empty">No instant wildcards found.<br>Add them via the desktop Instant Wildcard module.</div>';
    return;
  }
  let html = '<div class="chunk-hint">Select an item to insert at cursor. Type <code>$</code> in prompt to trigger.</div>';
  html += '<div class="chunk-tree">';
  for (const g of groups) {
    html += `<div class="chunk-group">`;
    html += `<div class="chunk-group-name" onclick="chunkToggleGroup(this.parentElement)">📁 ${escHtml(g.name)} <span class="wc-count">(${g.items.length})</span></div>`;
    html += '<div class="chunk-group-items">';
    for (const item of g.items) {
      const preview = item.value.length > 80 ? item.value.substring(0, 80) + '…' : item.value;
      html += `<div class="chunk-item" onclick="chunkInsert(this)" data-value="${escHtml(item.value)}">`;
      html += `<div class="chunk-item-key">${escHtml(item.key)}</div>`;
      html += `<div class="chunk-item-preview">${escHtml(preview)}</div>`;
      html += `</div>`;
    }
    html += '</div></div>';
  }
  html += '</div>';
  renderTarget.innerHTML = html;
  if (chunkOpen && chunkPanel) positionFloatingPanel(chunkPanel, chunkAnchorEl || modulePopup);
}

function chunkToggleGroup(groupEl) {
  const wasOpen = groupEl.classList.contains('open');
  // 다른 그룹 모두 닫기
  groupEl.parentElement.querySelectorAll('.chunk-group.open').forEach(g => g.classList.remove('open'));
  if (!wasOpen) groupEl.classList.add('open');
}

function chunkInsert(el) {
  const value = el.dataset.value;
  if (!value) return;
  const target = acTarget || promptEdit;
  const text = target.value || '';
  target.focus();
  let insertStart = 0;
  let insertEnd = 0;
  let insertText = '';
  if (chunkTriggerInfo) {
    // $로 트리거된 경우 — 트리거 토큰만 교체
    insertStart = chunkTriggerInfo.start;
    insertEnd = chunkTriggerInfo.end;
    insertText = value;
    chunkTriggerInfo = null;
  } else {
    // 모듈 버튼으로 열린 경우 — 커서 위치에 삽입
    const pos = target.selectionStart != null ? target.selectionStart : text.length;
    const before = text.substring(0, pos);
    // 앞에 콤마+공백 필요 여부
    const sep = before.trim().length > 0 && !/,\s*$/.test(before) ? ', ' : '';
    insertStart = pos;
    insertEnd = pos;
    insertText = sep + value;
  }
  target.value = text.substring(0, insertStart) + insertText + text.substring(insertEnd);
  const newPos = insertStart + insertText.length;
  target.selectionStart = target.selectionEnd = newPos;
  if (target === promptEdit) onPromptEdit();
  else _fireModuleOninput(target);
  // 자동 닫기
  closeChunkPanel();
}

// ---- Wildcard Manager (file browser + editor + generator) ----
let wcCurrentPath = '';
let wcEditMode = false;

function wcOpenBrowser() {
  setModuleParam('wildcard', 'get_file_tree', '');
}

function onWildcardManager(m) {
  if (m.action === 'file_tree') wcRenderTree(m.tree);
  else if (m.action === 'file_content') wcRenderEditor(m.path, m.content);
  else if (m.action === 'preview_result') wcShowPreview(m.name, m.result);
  else if (m.action === 'save_ok') showToast('File saved', 'success');
  else if (m.action === 'file_deleted') { showToast('File deleted', 'success'); wcCurrentPath = ''; }
}

function wcRenderTree(tree) {
  let html = '<div class="mod-section" style="display:flex;gap:6px;margin-bottom:8px">'
    + '<button class="mod-btn-sm" onclick="openModule(\'wildcard\')">← Back</button>'
    + '<button class="mod-btn-sm" onclick="wcPromptNewFile()">+ New File</button>'
    + '<button class="mod-btn-sm" onclick="setModuleParam(\'wildcard\',\'get_file_tree\',\'\')">Refresh</button>'
    + '</div>';
  html += '<div class="mod-wc-tree">';
  if (!tree || !tree.length) {
    html += '<div class="mod-empty">No wildcard files found</div>';
  } else {
    for (const item of tree) {
      if (item.type === 'folder') {
        html += `<div class="wc-folder"><div class="wc-folder-name" onclick="this.parentElement.classList.toggle('open')">📁 ${escHtml(item.name)} <span class="wc-count">(${item.files.length})</span></div>`;
        html += '<div class="wc-folder-children">';
        for (const f of item.files) {
          html += `<div class="wc-file" onclick="setModuleParam('wildcard','read_file','${escHtml(f.path)}')">📄 ${escHtml(f.name)} <span class="wc-count">${f.lines}L</span></div>`;
        }
        html += '</div></div>';
      } else {
        html += `<div class="wc-file" onclick="setModuleParam('wildcard','read_file','${escHtml(item.path)}')">📄 ${escHtml(item.name)} <span class="wc-count">${item.lines}L</span></div>`;
      }
    }
  }
  html += '</div>';
  // Generator guide
  html += `<div class="mod-section" style="margin-top:10px">
    <div class="mod-section-label">Wildcard Syntax Guide</div>
    <div class="wc-syntax-guide">
      <div><code>__name__</code> — Random pick from <code>name.txt</code></div>
      <div><code>__*name__</code> — Sequential (ordered)</div>
      <div><code>__*master__</code> + <code>__$master:slave__</code> — Dependent</div>
      <div><code>200:text</code> — Weighted entry (default 100)</div>
      <div><code>__folder/name__</code> — Subfolder path</div>
    </div>
  </div>`;
  moduleBody.innerHTML = html;
}

function wcRenderEditor(path, content) {
  wcCurrentPath = path;
  wcEditMode = false;
  const fname = path.split('/').pop();
  const wcName = fname.replace('.txt', '');
  moduleBody.innerHTML = `
    <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','get_file_tree','')">← Tree</button>
      <span class="wc-file-path">${escHtml(path)}</span>
      <span style="flex:1"></span>
      <button class="mod-btn-sm" id="wcEditBtn" onclick="wcToggleEdit()">Edit</button>
      <button class="mod-btn-sm mod-btn-danger" onclick="wcDeleteFile()">Delete</button>
    </div>
    <div class="mod-section">
      <textarea class="wc-editor" id="wcEditor" readonly>${escHtml(content)}</textarea>
    </div>
    <div class="mod-section" id="wcEditActions" style="display:none;gap:6px;flex-wrap:wrap">
      <button class="mod-btn-sm" style="background:#4CAF50;color:#fff" onclick="wcSaveFile()">Save</button>
      <button class="mod-btn-sm" onclick="wcCancelEdit()">Cancel</button>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Quick Add Entry</div>
      <div style="display:flex;gap:6px;align-items:center">
        <input type="text" class="wc-add-input" id="wcAddText" placeholder="tag or prompt text">
        <button class="mod-btn-sm" onclick="wcAddEntry()">Add</button>
      </div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Preview <code>__${escHtml(wcName)}__</code></div>
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','preview_wildcard','${escHtml(wcName)}')">Roll ×5</button>
        <div class="wc-preview" id="wcPreview"></div>
      </div>
    </div>
  `;
}

function wcToggleEdit() {
  const editor = document.getElementById('wcEditor');
  const actions = document.getElementById('wcEditActions');
  const btn = document.getElementById('wcEditBtn');
  if (!editor) return;
  wcEditMode = !wcEditMode;
  editor.readOnly = !wcEditMode;
  editor.classList.toggle('editing', wcEditMode);
  actions.style.display = wcEditMode ? 'flex' : 'none';
  btn.textContent = wcEditMode ? 'Cancel' : 'Edit';
}

function wcCancelEdit() {
  // Reload file to discard changes
  if (wcCurrentPath) setModuleParam('wildcard', 'read_file', wcCurrentPath);
}

function wcSaveFile() {
  const editor = document.getElementById('wcEditor');
  if (!editor || !wcCurrentPath) return;
  setModuleParam('wildcard', 'save_file', JSON.stringify({path: wcCurrentPath, content: editor.value}));
}

function wcDeleteFile() {
  if (!wcCurrentPath) return;
  if (!confirm('Delete ' + wcCurrentPath + '?')) return;
  setModuleParam('wildcard', 'delete_file', wcCurrentPath);
  setModuleParam('wildcard', 'get_file_tree', '');
}

function wcAddEntry() {
  const text = document.getElementById('wcAddText');
  const editor = document.getElementById('wcEditor');
  if (!text || !editor || !text.value.trim()) return;
  const line = text.value.trim();
  // Append to editor
  const current = editor.value;
  editor.value = current ? current + '\n' + line : line;
  text.value = '';
  // Auto-enable edit mode and save
  if (!wcEditMode) {
    wcEditMode = true;
    editor.readOnly = false;
    editor.classList.add('editing');
    const actions = document.getElementById('wcEditActions');
    if (actions) actions.style.display = 'flex';
    const btn = document.getElementById('wcEditBtn');
    if (btn) btn.textContent = 'Cancel';
  }
}

function wcShowPreview(name, result) {
  const el = document.getElementById('wcPreview');
  if (el) el.innerHTML = escHtml(result).replace(/\n/g, '<br>');
}

function wcPromptNewFile() {
  const name = prompt('New wildcard filename (e.g. "my_tags" or "folder/my_tags"):');
  if (!name || !name.trim()) return;
  setModuleParam('wildcard', 'create_file', name.trim());
}

// ---- Image upload helper ----
function pasteModuleImage(moduleId) {
  navigator.clipboard.read().then(items => {
    for (const item of items) {
      const imageType = item.types.find(t => t.startsWith('image/'));
      if (imageType) {
        item.getType(imageType).then(blob => {
          uploadModuleImage(moduleId, new File([blob], 'clipboard.png', {type: blob.type}));
        });
        return;
      }
    }
    showToast('No image in clipboard', 'error');
  }).catch(() => showToast('Clipboard access denied', 'error'));
}

function uploadModuleImage(moduleId, file) {
  if (!file || !file.type.startsWith('image/')) return;
  const body = document.getElementById('modulePopupBody');
  if (body) {
    const ind = document.createElement('div');
    ind.className = 'mod-upload-indicator';
    ind.textContent = 'Uploading...';
    ind.id = 'uploadIndicator';
    body.prepend(ind);
  }
  // Client-side resize to max 2048px to save bandwidth
  const img = new Image();
  const reader = new FileReader();
  reader.onload = () => {
    img.onload = () => {
      let w = img.width, h = img.height;
      const MAX = 2048;
      if (w > MAX || h > MAX) {
        if (w > h) { h = Math.round(h * MAX / w); w = MAX; }
        else { w = Math.round(w * MAX / h); h = MAX; }
      }
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(img, 0, 0, w, h);
      const dataUrl = canvas.toDataURL('image/png');
      const b64 = dataUrl.split(',')[1];
      setModuleParam(moduleId, 'upload_image', b64);
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
}

// ---- Slider debounce for image modules ----
let _sliderDebounce = {};
function onModSlider(moduleId, key, value) {
  const k = moduleId + '.' + key;
  if (_sliderDebounce[k]) clearTimeout(_sliderDebounce[k]);
  _sliderDebounce[k] = setTimeout(() => {
    setModuleParam(moduleId, key, value);
    delete _sliderDebounce[k];
  }, 300);
}

// ---- Character Reference module ----
let _storageView = null; // tracks which storage is open

function renderCharacterReference(m) {
  if (!m.is_naid45) {
    moduleBody.innerHTML = '<div class="mod-notice">Character Reference requires NAID4.5F/C model</div>';
    return;
  }
  const frames = (m.frames || []).map((f, i) => `
    <div class="mod-ref-frame ${f.is_enabled ? '' : 'disabled'}">
      <div class="mod-ref-header">
        <img class="mod-ref-thumb" src="data:image/jpeg;base64,${f.thumbnail}" alt="${escHtml(f.file_name)}">
        <div class="mod-ref-controls">
          <div class="mod-ref-controls-row">
            <label class="mod-checkbox-item">
              <input type="checkbox" ${f.is_enabled ? 'checked' : ''}
                oninput="setModuleParam('character_reference','enable_${i}',String(this.checked))">
              <span class="mod-checkbox-label">Enable</span>
            </label>
            <select class="mod-select-sm"
              onchange="setModuleParam('character_reference','ref_type_${i}',this.value)">
              <option value="character&style" ${f.reference_type==='character&style'?'selected':''}>Char & Style</option>
              <option value="character" ${f.reference_type==='character'?'selected':''}>Character</option>
              <option value="style" ${f.reference_type==='style'?'selected':''}>Style</option>
            </select>
            <button class="mod-btn-sm mod-btn-danger" onclick="setModuleParam('character_reference','remove_frame_${i}','')">Remove</button>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Strength</span>
            <input type="range" min="0" max="20" step="1" value="${Math.round(f.strength*20)}"
              oninput="this.nextElementSibling.textContent=(this.value/20).toFixed(2);onModSlider('character_reference','strength_${i}',(this.value/20).toFixed(2))">
            <span class="mod-slider-value">${f.strength.toFixed(2)}</span>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Fidelity</span>
            <input type="range" min="0" max="20" step="1" value="${Math.round(f.fidelity*20)}"
              oninput="this.nextElementSibling.textContent=(this.value/20).toFixed(2);onModSlider('character_reference','fidelity_${i}',(this.value/20).toFixed(2))">
            <span class="mod-slider-value">${f.fidelity.toFixed(2)}</span>
          </div>
        </div>
      </div>
    </div>
  `).join('');

  moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('charRefFileInput').click()">Upload</button>
      <button class="mod-btn-upload" onclick="pasteModuleImage('character_reference')">Paste</button>
      <input type="file" id="charRefFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('character_reference',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('character_reference')">Storage</button>
    </div>
    ${frames.length ? frames : '<div class="mod-empty">No character references loaded</div>'}
  `;
}

// ---- Vibe Transfer module ----
function renderVibeTransfer(m) {
  const frames = (m.frames || []).map((f, i) => {
    const thumbHtml = f.is_no_image
      ? '<div class="mod-ref-noimage">No Image</div>'
      : `<img class="mod-ref-thumb" src="data:image/jpeg;base64,${f.thumbnail}" alt="${escHtml(f.file_name)}">`;

    const encHtml = f.is_no_image ? '' : `
      <div class="mod-ref-encoding">
        ${f.has_encoding
          ? '<span class="mod-encode-status encoded">Encoded</span>'
          : `<button class="mod-btn-sm mod-btn-encode" onclick="setModuleParam('vibe_transfer','encode_${i}','')">Encode (2 Anlas)</button>`}
        ${f.encoding_keys.length ? `<span class="mod-encode-keys">IE: ${f.encoding_keys.map(k=>Number(k).toFixed(2)).join(', ')}</span>` : ''}
      </div>`;

    return `
    <div class="mod-ref-frame ${f.is_enabled ? '' : 'disabled'}">
      <div class="mod-ref-header">
        ${thumbHtml}
        <div class="mod-ref-controls">
          <div class="mod-ref-controls-row">
            <label class="mod-checkbox-item">
              <input type="checkbox" ${f.is_enabled ? 'checked' : ''}
                oninput="setModuleParam('vibe_transfer','enable_${i}',String(this.checked))">
              <span class="mod-checkbox-label">Enable</span>
            </label>
            <button class="mod-btn-sm mod-btn-danger" onclick="setModuleParam('vibe_transfer','remove_frame_${i}','')">Remove</button>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Ref Strength</span>
            <input type="range" min="-100" max="100" step="1" value="${Math.round(f.reference_strength*100)}"
              oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2);onModSlider('vibe_transfer','ref_strength_${i}',(this.value/100).toFixed(2))">
            <span class="mod-slider-value">${f.reference_strength.toFixed(2)}</span>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Info Extracted</span>
            <input type="range" min="1" max="100" step="1" value="${Math.round(f.information_extracted*100)}"
              oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2);onModSlider('vibe_transfer','info_extracted_${i}',(this.value/100).toFixed(2))">
            <span class="mod-slider-value">${f.information_extracted.toFixed(2)}</span>
          </div>
          ${encHtml}
        </div>
      </div>
    </div>`;
  }).join('');

  moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('vibeFileInput').click()">Upload</button>
      <button class="mod-btn-upload" onclick="pasteModuleImage('vibe_transfer')">Paste</button>
      <input type="file" id="vibeFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('vibe_transfer',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('vibe_transfer')">Storage</button>
      <span class="mod-frame-count">${m.frame_count}/${m.max_frames}</span>
    </div>
    <label class="mod-checkbox-item" style="margin-bottom:8px">
      <input type="checkbox" ${m.normalize ? 'checked' : ''}
        oninput="setModuleParam('vibe_transfer','normalize',String(this.checked))">
      <span class="mod-checkbox-label">Normalize reference strength</span>
    </label>
    ${frames.length ? frames : '<div class="mod-empty">No vibe transfers loaded</div>'}
  `;
}

// ---- Storage view ----
function requestStorage(moduleId) {
  _storageView = moduleId;
  setModuleParam(moduleId, 'get_storage', '');
}

function onStorageList(m) {
  if (m.module_id === 'character_reference') renderCharRefStorage(m);
  else if (m.module_id === 'vibe_transfer') renderVibeStorage(m);
}

function renderCharRefStorage(m) {
  if (currentModuleId !== 'character_reference') return;
  const items = (m.items || []).map(it => `
    <div class="mod-storage-item" onclick="applyCharRefStorage('${escHtml(it.file_hash)}')" title="${escHtml(it.file_name)}">
      <img class="mod-storage-thumb" src="data:image/jpeg;base64,${it.thumbnail}" alt="">
      <span class="mod-storage-name">${escHtml(it.character_name || it.file_name)}</span>
    </div>
  `).join('');

  moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="setModuleParam('character_reference','get_storage','');/* refresh */">Refresh</button>
      <button class="mod-btn-sm" onclick="openModule('character_reference')">Back</button>
    </div>
    ${items.length
      ? '<div class="mod-storage-grid">' + items + '</div>'
      : '<div class="mod-empty">No saved references</div>'}
  `;
}

function applyCharRefStorage(fileHash) {
  setModuleParam('character_reference', 'apply_storage', fileHash);
  // 적용 후 메인 뷰로 복귀
  setTimeout(() => openModule('character_reference'), 500);
}

function renderVibeStorage(m) {
  if (currentModuleId !== 'vibe_transfer') return;
  const modelNames = Object.keys(m.models || {});
  const currentModel = m.current_model || '';

  // Build tabs
  const tabBtns = modelNames.map(name =>
    `<button class="mod-btn-sm mod-storage-tab ${name===currentModel?'active':''}" onclick="showVibeStorageTab(this,'${escHtml(name)}')">${escHtml(name)}</button>`
  ).join('');

  // Build tab contents
  const tabContents = modelNames.map(name => {
    const items = (m.models[name] || []).map(it => {
      const ieKeys = (it.encoding_keys || []);
      const defaultIe = ieKeys.length ? ieKeys[0] : 1.0;
      return `
        <div class="mod-storage-item" onclick="applyVibeStorage('${escHtml(name)}','${escHtml(it.file_hash)}',${defaultIe})" title="${escHtml(it.file_name)}">
          <img class="mod-storage-thumb" src="data:image/jpeg;base64,${it.thumbnail}" alt="">
          <span class="mod-storage-name">${escHtml(it.file_name)}</span>
          ${ieKeys.length ? `<span class="mod-encode-keys">IE: ${ieKeys.map(k=>Number(k).toFixed(2)).join(', ')}</span>` : ''}
        </div>`;
    }).join('');
    const vis = name === currentModel ? '' : 'style="display:none"';
    return `<div class="mod-storage-grid mod-vibe-tab" data-model="${escHtml(name)}" ${vis}>${items || '<div class="mod-empty">Empty</div>'}</div>`;
  }).join('');

  moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="setModuleParam('vibe_transfer','get_storage','')">Refresh</button>
      <button class="mod-btn-sm" onclick="openModule('vibe_transfer')">Back</button>
    </div>
    <div class="mod-storage-tabs">${tabBtns}</div>
    ${tabContents || '<div class="mod-empty">No saved vibes</div>'}
  `;
}

function showVibeStorageTab(btn, model) {
  // Toggle tab buttons
  btn.parentElement.querySelectorAll('.mod-storage-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  // Toggle content
  moduleBody.querySelectorAll('.mod-vibe-tab').forEach(el => {
    el.style.display = el.dataset.model === model ? '' : 'none';
  });
}

function applyVibeStorage(model, fileHash, ieValue) {
  setModuleParam('vibe_transfer', 'apply_storage', model + '|' + fileHash + '|' + ieValue);
}

// ---- Search system ----
const searchCountEl = $('searchCount');
let searchingActive = false;

// Rating filter state (synced with module-bar GSQE buttons)
let ratingState = {g: true, s: true, q: true, e: true};
let _cachedRatingCounts = null; // {g:N, s:N, q:N, e:N} — 서버 search_state에서 캐시

function _computeLocalFilteredCount() {
  // Tag Filter active 시 tag filter 결과의 rating_counts 사용, 아니면 전체 검색 결과
  const quickRatingCounts = quickFilter ? quickFilter.getRatingCounts() : null;
  const rc = (quickFilter && quickFilter.isActive() && quickRatingCounts) ? quickRatingCounts : _cachedRatingCounts;
  if (!rc || !Object.keys(rc).length) return null;
  let count = 0;
  for (const k of ['g','s','q','e']) {
    if (ratingState[k]) count += (rc[k] || 0);
  }
  return count;
}

function toggleRating(r) {
  ratingState[r] = !ratingState[r];
  syncRatingButtons();
  // If search module is open, sync its checkboxes too
  if (currentModuleId === 'search') {
    const cb = document.getElementById('sr_' + r);
    if (cb) cb.checked = ratingState[r];
  }
  if (sharedMode) {
    // 최소 1개 보장 (서버 set_active_ratings와 동일 정책)
    const anyActive = Object.values(ratingState).some(v => v);
    if (!anyActive) { ratingState.q = true; ratingState.e = true; syncRatingButtons(); }
    // 로컬 즉시 반영
    const localCount = _computeLocalFilteredCount();
    if (localCount !== null) updateSearchCount(localCount);
    // 서버 세션에 rating 저장 (응답으로 정확한 카운트 갱신)
    if (ws && ws.readyState === WebSocket.OPEN) {
      const active = Object.keys(ratingState).filter(k => ratingState[k]);
      ws.send(JSON.stringify({type: 'set_active_ratings', ratings: active}));
    }
    if (quickFilter) quickFilter.savePreferences();
    return;
  }
  // Send to server for instant count update
  if (ws && ws.readyState === WebSocket.OPEN) {
    const active = Object.keys(ratingState).filter(k => ratingState[k]);
    ws.send(JSON.stringify({type: 'set_active_ratings', ratings: active}));
  }
  if (quickFilter) quickFilter.savePreferences();
}

function onFilterReset(m) {
  // 서버에서 검색 데이터 교체 시 (새 검색/Parquet 로드/Depth Assign/복원)
  // GSQE 전체 활성화
  ratingState = {g: true, s: true, q: true, e: true};
  syncRatingButtons();
  // Tag filter 전체 초기화 (서버 전송 없이 — 이미 서버에서 처리됨)
  if (quickFilter) quickFilter.reset({persist: false});
  // Count/Rating 갱신
  if (m.rating_counts) _cachedRatingCounts = m.rating_counts;
  if (m.count != null) updateSearchCount(m.count);
  if (!sharedMode) {
    if (quickFilter) quickFilter.restorePreferences();
  } else {
    if (quickFilter) quickFilter.updateHighlight();
  }
}

function onRatingUpdate(m) {
  if (m.rating_counts) _cachedRatingCounts = m.rating_counts;
  if (sharedMode) {
    // Tag filter active 시 로컬 계산 우선 (서버 count는 전체 풀 기준이라 tag_filter 미반영)
    if (quickFilter && quickFilter.isActive() && quickFilter.getRatingCounts()) {
      const localCount = _computeLocalFilteredCount();
      if (localCount !== null) { updateSearchCount(localCount); return; }
    }
    if (m.count != null) updateSearchCount(m.count);
    return;
  }
  updateSearchCount(m.count || 0);
  // Sync active_ratings
  if (m.active_ratings) {
    for (const k of ['g','s','q','e']) {
      ratingState[k] = m.active_ratings.includes(k);
    }
    syncRatingButtons();
  }
  if (quickFilter) quickFilter.updateHighlight();
}

function syncRatingButtons() {
  document.querySelectorAll('.rating-btn').forEach(btn => {
    if (!btn.dataset.r) return; // Filter 버튼 등 data-r 없는 요소 스킵
    btn.classList.toggle('active', !!ratingState[btn.dataset.r]);
  });
  if (quickFilter) quickFilter.updateHighlight();
}

function updateSearchCount(count) {
  searchCountEl.textContent = count;
}

function onSearchState(m) {
  // rating_counts 캐시 (shared mode 로컬 카운트 계산용)
  if (m.rating_counts) _cachedRatingCounts = m.rating_counts;
  if (sharedMode && _cachedRatingCounts) {
    // Shared Mode: 개인 ratingState 기준으로 카운트 계산
    updateSearchCount(_computeLocalFilteredCount());
  } else {
    updateSearchCount(m.count || 0);
  }
  searchingActive = false;
  // Shared Mode: 서버 전역 rating 무시 (개인 rating 보호)
  if (!sharedMode) {
    // Sync rating state from server (prefer active_ratings over legacy ratings)
    if (m.active_ratings) {
      for (const k of ['g','s','q','e']) {
        ratingState[k] = m.active_ratings.includes(k);
      }
    } else if (m.ratings) {
      for (const k of ['g','s','q','e']) {
        if (k in m.ratings) ratingState[k] = !!m.ratings[k];
      }
    }
  }
  const savedQuick = (!sharedMode && quickFilter) ? quickFilter.loadPreferences() : null;
  if (savedQuick) {
    // localStorage rating preference wins over server defaults after reconnect/search refresh.
    for (const k of ['g', 's', 'q', 'e']) {
      ratingState[k] = savedQuick.ratings.includes(k);
    }
    syncRatingButtons();
  } else {
    syncRatingButtons();
  }
  if (currentModuleId === 'search') renderSearch(m);
}

function onSearchProgress(m) {
  if (currentModuleId === 'search') {
    const prog = moduleBody.querySelector('.search-progress');
    if (prog) prog.textContent = `Searching... ${m.completed}/${m.total}`;
  }
}

function renderSearch(m) {
  const ratingItems = [
    ['e', 'Explicit'], ['q', 'NSFW'], ['s', 'Sensitive'], ['g', 'General']
  ].map(([k, label]) =>
    `<label class="mod-checkbox-item">
      <input type="checkbox" id="sr_${k}" ${ratingState[k] ? 'checked' : ''}>
      <span class="mod-checkbox-label">${label}</span>
    </label>`
  ).join('');

  const parquets = (m.parquets || []).map(f =>
    `<div class="search-parquet-item" onclick="loadParquet('${escHtml(f)}')">${escHtml(f)}</div>`
  ).join('');

  moduleBody.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Remaining</div>
        <div class="search-count-display">${m.count || 0}</div>
      </div>
      <div class="search-top-actions">
        <button class="mod-action-btn mod-refine" onclick="openRefine()">Refine</button>
        <button class="mod-action-btn mod-restore" onclick="restoreSnapshot()">Restore</button>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Search Keyword</div>
      <input class="mod-input" id="searchQuery" type="text" value="${escHtml(m.query)}" placeholder="tags, keywords...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Keyword</div>
      <input class="mod-input" id="searchExclude" type="text" value="${escHtml(m.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">${ratingItems}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="mod-action-btn mod-start" onclick="doSearch()" ${searchingActive ? 'disabled' : ''}>Search</button>
      <span class="search-progress" style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)"></span>
    </div>
    ${parquets.length ? `<div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
        Custom Parquets (${m.parquets.length}) <span class="mod-collapse-arrow">▶</span>
      </div>
      <div class="search-parquet-list collapsed">${parquets}</div>
    </div>` : ''}
  `;

  // Bind tag autocomplete to Prompt Search inputs.
  ['searchQuery', 'searchExclude'].forEach(id => {
    const el = moduleBody.querySelector(`#${id}`);
    if (el) bindTagAssist(el, { excludeE621: true });
  });
}

function doSearch() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const query = (document.getElementById('searchQuery') || {}).value || '';
  const exclude = (document.getElementById('searchExclude') || {}).value || '';
  // Sync rating state from search module checkboxes back to bar buttons
  for (const k of ['e','q','s','g']) {
    const el = document.getElementById('sr_' + k);
    if (el) ratingState[k] = el.checked;
  }
  syncRatingButtons();
  if (quickFilter) quickFilter.savePreferences();
  const ratings = {};
  for (const k of ['e','q','s','g']) {
    ratings['rating_' + k] = ratingState[k];
  }
  searchingActive = true;
  ws.send(JSON.stringify({type: 'search', query, exclude, ...ratings}));
  const prog = moduleBody.querySelector('.search-progress');
  if (prog) prog.textContent = 'Starting...';
  const btn = moduleBody.querySelector('.mod-start');
  if (btn) btn.disabled = true;
}

function loadParquet(filename) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'load_parquet', filename}));
}

function restoreSnapshot() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'restore_snapshot'}));
}

// ---- Refine (Depth Search) panel ----
const refinePanel = $('refinePanel');
let refineOpen = false;

function getFloatingPanelWidth(panel) {
  if (panel === peDebugPanel) return 520;
  if (panel === refinePanel) return 400;
  return 420;
}

function positionFloatingPanel(panel, anchorEl = modulePopup) {
  if (!panel || !panel.classList.contains('open')) return;

  const vv = window.visualViewport;
  const viewportTop = vv ? vv.offsetTop : 0;
  const viewportLeft = vv ? vv.offsetLeft : 0;
  const viewportWidth = vv ? vv.width : window.innerWidth;
  const viewportHeight = vv ? vv.height : window.innerHeight;
  const margin = isPC.matches ? 16 : 12;
  const sideMargin = 12;
  const minWidth = Math.min(320, Math.max(260, viewportWidth - sideMargin * 2));
  const preferredWidth = Math.min(getFloatingPanelWidth(panel), viewportWidth - sideMargin * 2);

  panel.style.right = 'auto';
  panel.style.bottom = 'auto';

  if (!isPC.matches) {
    const width = Math.max(minWidth, preferredWidth);
    panel.style.left = `${viewportLeft + sideMargin}px`;
    panel.style.top = `${viewportTop + sideMargin}px`;
    panel.style.width = `${width}px`;
    panel.style.maxWidth = `${viewportWidth - sideMargin * 2}px`;
    panel.style.maxHeight = `${Math.max(220, viewportHeight - sideMargin * 2)}px`;
    return;
  }

  const anchorRect = anchorEl && anchorEl.classList.contains('open')
    ? anchorEl.getBoundingClientRect()
    : null;
  const fallbackWidth = Math.min(preferredWidth, viewportWidth - sideMargin * 2);

  if (!anchorRect) {
    panel.style.left = `${Math.max(viewportLeft + sideMargin, viewportLeft + viewportWidth - fallbackWidth - sideMargin)}px`;
    panel.style.top = `${viewportTop + sideMargin}px`;
    panel.style.width = `${fallbackWidth}px`;
    panel.style.maxWidth = `${viewportWidth - sideMargin * 2}px`;
    panel.style.maxHeight = `${Math.max(220, viewportHeight - sideMargin * 2)}px`;
    return;
  }

  const availableRight = viewportLeft + viewportWidth - sideMargin - (anchorRect.right + margin);
  const availableLeft = anchorRect.left - viewportLeft - sideMargin - margin;
  let width = Math.min(preferredWidth, Math.max(minWidth, availableRight));
  let left = anchorRect.right + margin;

  if (availableRight < minWidth && availableLeft > availableRight) {
    width = Math.min(preferredWidth, Math.max(minWidth, availableLeft));
    left = Math.max(viewportLeft + sideMargin, anchorRect.left - margin - width);
  } else {
    left = Math.min(left, viewportLeft + viewportWidth - sideMargin - width);
  }

  const top = Math.max(viewportTop + sideMargin, anchorRect.top);
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
  panel.style.width = `${width}px`;
  panel.style.maxWidth = `${viewportWidth - sideMargin * 2}px`;
  panel.style.maxHeight = `${Math.max(220, viewportHeight - (top - viewportTop) - sideMargin)}px`;
}

function relayoutFloatingPanels() {
  positionFloatingPanel(refinePanel, modulePopup);
  positionFloatingPanel(chunkPanel, chunkAnchorEl || modulePopup);
  positionFloatingPanel(pePresetAddPanel, modulePopup);
  positionFloatingPanel(pePresetManagePanel, modulePopup);
  positionFloatingPanel(peE621Panel, modulePopup);
  positionFloatingPanel(peDanbooruPanel, modulePopup);
  positionFloatingPanel(peDebugPanel, modulePopup);
}

function openRefine() {
  if (refineOpen) { closeRefine(); return; }
  closeAuxiliaryPopups(refinePanel);
  refineOpen = true;
  refinePanel.classList.add('open');
  positionFloatingPanel(refinePanel, modulePopup);
  if (ws && ws.readyState === WebSocket.OPEN) {
    // 먼저 현재 상태 요청 (이미 열려있을 수 있음)
    ws.send(JSON.stringify({type: 'get_depth_state'}));
    // 열려있지 않으면 open 요청 → 서버가 tab_added 시그널로 자동 브로드캐스트
    ws.send(JSON.stringify({type: 'depth_action', action: 'open'}));
  }
}

function closeRefine() {
  refineOpen = false;
  refinePanel.classList.remove('open');
}

function onDepthState(m) {
  if (!refineOpen) return;
  if (!m.open) {
    const msg = m.error === 'no_search_results'
      ? 'No search results loaded.<br><span style="font-size:10px">Run a search first</span>'
      : 'Preparing data...';
    refinePanel.querySelector('.refine-body').innerHTML =
      `<div style="text-align:center;color:var(--text-dim);padding:20px">${msg}</div>`;
    return;
  }
  const body = refinePanel.querySelector('.refine-body');
  // 카운트만 업데이트 (입력 필드가 이미 있으면 리빌드 방지)
  const existing = body.querySelector('#depthQuery');
  if (existing) {
    const counts = body.querySelectorAll('.search-count-display');
    if (counts[0]) counts[0].textContent = m.count || 0;
    if (counts[1]) counts[1].textContent = m.original || 0;
    // 스테이징 카운트 갱신
    const sc = body.querySelector('.depth-staging-count');
    if (sc) sc.textContent = m.staging_count || 0;
    return;
  }
  const r = m.ratings || {e:true,q:true,s:true,g:true};
  const f = m.filters || {};
  const ck = (name, def) => { const v = f[name]; return v ? v.enabled : def; };
  const fv = (name, def) => { const v = f[name]; return v ? escHtml(v.value) : def; };
  body.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Filtered</div>
        <div class="search-count-display" style="font-size:18px">${m.count || 0}</div>
      </div>
      <div>
        <div class="mod-section-label">Original</div>
        <div class="search-count-display" style="font-size:18px;color:var(--text-muted)">${m.original || 0}</div>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Filter Tags</div>
      <input class="mod-input" id="depthQuery" type="text" value="${escHtml(m.query)}" placeholder="filter tags...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Tags</div>
      <input class="mod-input" id="depthExclude" type="text" value="${escHtml(m.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_e" ${r.e?'checked':''}><span class="mod-checkbox-label">E</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_q" ${r.q?'checked':''}><span class="mod-checkbox-label">Q</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_s" ${r.s?'checked':''}><span class="mod-checkbox-label">S</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_g" ${r.g?'checked':''}><span class="mod-checkbox-label">G</span></label>
      </div>
    </div>
    <div class="mod-section-label" style="margin-top:4px">Numeric Filters</div>
    <div class="depth-filter-grid">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_min" ${ck('token_min',false)?'checked':''}><span class="mod-checkbox-label">Tokens ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_min" type="number" value="${fv('token_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_max" ${ck('token_max',false)?'checked':''}><span class="mod-checkbox-label">Tokens ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_max" type="number" value="${fv('token_max','150')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_min" ${ck('id_min',false)?'checked':''}><span class="mod-checkbox-label">ID ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_min" type="number" value="${fv('id_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_max" ${ck('id_max',false)?'checked':''}><span class="mod-checkbox-label">ID ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_max" type="number" value="${fv('id_max','99999999')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_score_min" ${ck('score_min',false)?'checked':''}><span class="mod-checkbox-label">Score ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_score_min" type="number" value="${fv('score_min','0')}">
    </div>
    <div class="mod-checkbox-grid" style="margin-top:4px">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_rem_char" ${f.rem_char?'checked':''}><span class="mod-checkbox-label">Has Character</span></label>
      <label class="mod-checkbox-item"><input type="checkbox" id="df_only_empty_char" ${f.only_empty_char?'checked':''}><span class="mod-checkbox-label">No Character</span></label>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
      <button class="mod-action-btn mod-start" style="flex:1" onclick="depthFilter()">Filtered Search</button>
      <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('restore')">Restore</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="mod-action-btn mod-start" style="flex:1;background:var(--accent)" onclick="depthAction('assign')">Assign to Main</button>
      <button class="mod-action-btn mod-refine" style="flex:1" onclick="depthAction('promote')" title="Set current filtered results as the new baseline">Set as Baseline</button>
    </div>
    <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')" style="margin-top:6px">
      Staging & Export <span class="mod-collapse-arrow">▶</span>
    </div>
    <div class="collapsed" style="display:flex;flex-direction:column;gap:6px">
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('stage')">+ Stage Current</button>
        <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)">Staged: <span class="depth-staging-count">${m.staging_count||0}</span></span>
      </div>
      <div style="display:flex;gap:6px">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('merge_staging')">Merge Staged</button>
        <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('clear_staging')">Clear</button>
      </div>
      <button class="mod-action-btn" style="width:100%" onclick="depthAction('export')">Export to Custom Parquet</button>
    </div>
  `;
}

function depthFilter() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const query = ($('depthQuery') || {}).value || '';
  const exclude = ($('depthExclude') || {}).value || '';
  const ratings = {};
  for (const k of ['e','q','s','g']) {
    const el = $('dr_' + k);
    ratings[k] = el ? el.checked : true;
  }
  const filters = {};
  for (const name of ['token_min','token_max','id_min','id_max','score_min']) {
    const check = $('df_' + name);
    const inp = $('dfv_' + name);
    if (check && inp) filters[name] = {enabled: check.checked, value: inp.value};
  }
  filters.rem_char = ($('df_rem_char') || {}).checked || false;
  filters.only_empty_char = ($('df_only_empty_char') || {}).checked || false;
  ws.send(JSON.stringify({type: 'depth_action', action: 'filter', query, exclude, ratings, filters}));
}

function depthAction(action) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'depth_action', action}));
}

// ---- Tag search (KR/EN) ----
const tagSearchInput = $('tagSearchInput');
const tagSearchResults = $('tagSearchResults');
let tagSearchTimer = null;

let tagComposing = false;
tagSearchInput.addEventListener('compositionstart', () => { tagComposing = true; });
tagSearchInput.addEventListener('compositionend', () => {
  tagComposing = false;
  fireTagSearch();
});
tagSearchInput.addEventListener('input', () => {
  if (!tagComposing) fireTagSearch();
});
function fireTagSearch() {
  clearTimeout(tagSearchTimer);
  const q = tagSearchInput.value.trim();
  if (!q) { tagSearchResults.classList.remove('open'); return; }
  tagSearchTimer = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'tag_search', query: q}));
    }
  }, 150);  // 150ms — 실시간 체감
}

// 외부 클릭 시 결과 닫기
document.addEventListener('click', e => {
  if (!e.target.closest('.tag-search-bar')) tagSearchResults.classList.remove('open');
});

function onTagSearchResult(m) {
  // 입력이 이미 지워졌으면 (태그 삽입 후) 무시
  if (!tagSearchInput.value.trim()) { tagSearchResults.classList.remove('open'); return; }
  if (!m.results || !m.results.length) {
    tagSearchResults.classList.remove('open');
    return;
  }
  const fmtCount = n => n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);
  tagSearchResults.innerHTML = m.results.map((r, i) =>
    `<div class="tag-result-item" data-idx="${i}">
      <span class="tag-result-tag">${escHtml(r.tag)}</span>
      <span class="tag-result-desc">${escHtml(r.desc || r.group || '')}</span>
      <span class="tag-result-count">${fmtCount(r.count)}</span>
    </div>`
  ).join('');
  // data 속성 + addEventListener로 XSS 방지
  tagSearchResults.querySelectorAll('.tag-result-item').forEach(el => {
    const idx = +el.dataset.idx;
    el.addEventListener('click', () => insertTag(m.results[idx].tag));
  });
  tagSearchResults.classList.add('open');
}

function insertTag(tag) {
  const pe = promptEdit;
  const cur = pe.value;
  const start = pe.selectionStart != null ? pe.selectionStart : cur.length;
  // 커서 앞 문자 기준으로 쉼표 구분 판단
  const before = cur.substring(0, start);
  const needSep = before.length > 0 && !before.endsWith(', ') && !before.endsWith(',') && before.trim().length > 0;
  const sep = needSep ? ', ' : '';
  pe.value = before + sep + tag + ', ' + cur.substring(start);
  pe.focus();
  const newPos = start + sep.length + tag.length + 2;
  pe.selectionStart = pe.selectionEnd = newPos;
  onPromptEdit();
  clearTimeout(tagSearchTimer);
  tagSearchInput.value = '';
  tagSearchResults.classList.remove('open');
}

// ---- Tag tooltip + Autocomplete system ----
const tagTooltip = $('tagTooltip');
let lastLookupTag = '';
let tagLookupTimer = null;
// Autocomplete state
let acMode = false;
let acResults = [];
let acSel = -1;
let acTimer = null;
let lastAcQuery = '';
let acTarget = null; // active textarea for autocomplete/hint
let acComposing = false; // IME composition guard

// PC에서 모듈 내 편집 시 tooltip을 왼쪽(프롬프트 영역)에 표시
function _syncTooltipSide() {
  if (!tagTooltip || window.innerWidth < 768) return;
  const inModule = acTarget && acTarget.closest('.module-popup, .refine-popup, .tag-filter-popup');
  tagTooltip.classList.toggle('left-side', !!inModule);
}

const fmtCount = n => n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);
const CAT_COLORS = { artist: '#d4736a', copyright: '#a87fd4', character: '#6abf7b', e621: '#d4c36a', wildcard: '#6ac4d4' };
function catStyle(cat) { return cat && CAT_COLORS[cat] ? ` style="color:${CAT_COLORS[cat]}"` : ''; }

// Extract active token info at cursor (comma-delimited, NAI weight/bracket aware)
function getActiveTokenInfo(textarea) {
  const text = textarea.value;
  const pos = textarea.selectionStart != null ? textarea.selectionStart : -1;
  if (pos < 0 || text.length === 0) return null;
  let start = text.lastIndexOf(',', pos - 1) + 1;
  let end = text.indexOf(',', pos);
  if (end === -1) end = text.length;
  while (start < end && /\s/.test(text[start])) start++;
  let rawEnd = end;
  while (rawEnd > start && /\s/.test(text[rawEnd - 1])) rawEnd--;
  const raw = text.substring(start, rawEnd);
  if (!raw || raw.startsWith('#')) return null;
  let stripped = raw;
  stripped = stripped.replace(/^-?\(+/, '');
  stripped = stripped.replace(/(?::[\d.]+)?\)+$/, '');
  stripped = stripped.replace(/^\d+(?:\.\d+)?::/, '');
  stripped = stripped.replace(/\s*::$/, '');
  stripped = stripped.trim();
  if (!stripped) return null;
  return { raw, stripped, start, end: rawEnd };
}

function getTagAtCursor(textarea) {
  const info = getActiveTokenInfo(textarea);
  return info ? info.stripped : '';
}

// ---- Info mode (tag_lookup) ----
function checkTagHint() {
  if (acMode) return;
  const target = acTarget || promptEdit;
  const tag = getTagAtCursor(target);
  if (tag === lastLookupTag) return;
  lastLookupTag = tag;
  if (!tag) { tagTooltip.classList.remove('open', 'ac-mode'); return; }
  tagTooltip.classList.remove('open', 'ac-mode');
  clearTimeout(tagLookupTimer);
  tagLookupTimer = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN)
      ws.send(JSON.stringify({type: 'tag_lookup', tag}));
  }, 200);
}

function onTagLookupResult(m) {
  if (acMode) return;
  if (!m.tag) { tagTooltip.classList.remove('open', 'ac-mode'); return; }
  if (m.tag.toLowerCase() !== lastLookupTag.toLowerCase()) return;
  const groupText = [m.group, m.subgroup].filter(Boolean).join(' / ');
  let html = '<div class="tag-tooltip-main">' +
    `<span class="tag-tooltip-tag"${catStyle(m.cat)}>${escHtml(m.tag)}</span>` +
    `<span class="tag-tooltip-count">${fmtCount(m.count||0)}</span>` +
    (groupText ? ` <span class="tag-tooltip-group">${escHtml(groupText)}</span>` : '') +
    (m.desc ? `<span class="tag-tooltip-desc">${escHtml(m.desc)}</span>` : '') +
    '</div>';
  if (m.implications && m.implications.length) {
    html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">implies</span>' +
      m.implications.map(t => `<span class="tag-tooltip-extra-tag" data-insert="${escHtml(t)}">${escHtml(t)}</span>`).join('') + '</div>';
  }
  if (m.related && m.related.length) {
    html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">related</span>' +
      m.related.map(t => `<span class="tag-tooltip-extra-tag" data-insert="${escHtml(t)}">${escHtml(t)}</span>`).join('') + '</div>';
  }
  // 캐릭터 상세 정보 (character_analysis)
  const cd = m.character_details;
  if (cd) {
    const fmtPct = p => p >= 10 ? Math.round(p) + '%' : p.toFixed(1) + '%';
    const DISPLAY_MAX = 6;
    const mkTag = (t, cls) => `<span class="tag-tooltip-extra-tag char-tag ${cls}" data-insert="${escHtml(t.tag)}">${escHtml(t.tag)} <small>${fmtPct(t.pct)}</small></span>`;
    // copyright 라벨
    let charTags = '';
    if (cd.copyright) charTags += `<span class="char-copyright">${escHtml(cd.copyright)}</span>`;
    // 분홍(personal_color) + 녹색(characteristics) + 연노랑(body) 한 줄로
    if (cd.personal_color) charTags += cd.personal_color.slice(0, DISPLAY_MAX).map(t => mkTag(t, 'ct-pc')).join('');
    if (cd.personal_color && cd.personal_color.length > DISPLAY_MAX) charTags += `<span class="char-more">+${cd.personal_color.length - DISPLAY_MAX}</span>`;
    if (cd.characteristics) charTags += cd.characteristics.slice(0, DISPLAY_MAX).map(t => mkTag(t, 'ct-ch')).join('');
    if (cd.characteristics && cd.characteristics.length > DISPLAY_MAX) charTags += `<span class="char-more">+${cd.characteristics.length - DISPLAY_MAX}</span>`;
    if (cd.breast_size_top) charTags += `<span class="tag-tooltip-extra-tag char-tag ct-body" data-insert="${escHtml(cd.breast_size_top)}">${escHtml(cd.breast_size_top)}</span>`;
    if (charTags) html += `<div class="tag-tooltip-extra char-details-row">${charTags}</div>`;
    // Copy All: 특성 태그만 (캐릭터 이름 제외 — 이미 입력된 상태)
    const allTags = [];
    if (cd.personal_color) cd.personal_color.forEach(t => allTags.push(t.tag));
    if (cd.breast_size_top) allTags.push(cd.breast_size_top);
    if (cd.characteristics) cd.characteristics.forEach(t => allTags.push(t.tag));
    html += `<div class="char-copy-row"><button class="char-copy-btn" data-tags="${escHtml(allTags.join(', '))}">\u{1F4CB} Copy All</button>` +
      `<small class="char-sample-count">${cd.total_rows || 0} samples</small></div>`;
  }
  tagTooltip.innerHTML = html;
  tagTooltip.classList.remove('ac-mode');
  tagTooltip.classList.add('open');
  _syncTooltipSide();
  // Click on related/implies/character tag → insert next to current token
  tagTooltip.querySelectorAll('.tag-tooltip-extra-tag[data-insert]').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault();
      const target = acTarget || promptEdit;
      const tag = el.dataset.insert;
      const info = getActiveTokenInfo(target);
      if (!info) return;
      const text = target.value;
      target.value = text.substring(0, info.end) + ', ' + tag + text.substring(info.end);
      const newPos = info.end + 2 + tag.length;
      target.selectionStart = target.selectionEnd = newPos;
      target.focus();
      if (target === promptEdit) onPromptEdit();
      else _fireModuleOninput(target);
      lastLookupTag = '';
      checkTagHint();
    });
  });
  // Copy All 버튼 핸들러
  const copyBtn = tagTooltip.querySelector('.char-copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('mousedown', e => {
      e.preventDefault();
      navigator.clipboard.writeText(copyBtn.dataset.tags).then(() => {
        showToast('Copied to clipboard', 'success');
      }).catch(() => {
        showToast('Copy failed', 'error');
      });
    });
  }
}

// ---- Autocomplete mode ----
function scheduleAutocomplete() {
  const target = acTarget || promptEdit;
  const info = getActiveTokenInfo(target);
  const allowTriggers = !sharedMode && target !== negEdit;
  const isChunkTrigger = !!(info && allowTriggers && info.stripped.startsWith('$'));
  if (!info || (!isChunkTrigger && info.stripped.length < 2)) {
    hideAutocomplete();
    checkTagHint();
    return;
  }
  if (info.stripped === lastAcQuery) return;
  lastAcQuery = info.stripped;
  clearTimeout(acTimer);
  clearTimeout(tagLookupTimer);
  acTimer = setTimeout(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const s = info.stripped;
    if (allowTriggers && s.startsWith('__')) {
      // Wildcard autocomplete: __keyword → search wildcard names
      const q = s.replace(/^_+/, '').replace(/_+$/, '');
      if (q.length >= 1) ws.send(JSON.stringify({type: 'autocomplete_wildcard', query: q}));
    } else if (allowTriggers && s.startsWith('$')) {
      // Chunk trigger: open floating Chunk panel
      clearTimeout(acTimer);
      chunkTriggerInfo = info;
      openChunkPanel(getChunkAnchor(target));
      return;
    } else {
      ws.send(JSON.stringify({type: 'autocomplete', query: s}));
    }
  }, 150);
}

function onAutocompleteResult(m) {
  // Accept results for wildcard queries too
  const q = lastAcQuery;
  const matchesWc = q && q.startsWith('__') && m.query === q.replace(/^_+/, '').replace(/_+$/, '');
  if (!matchesWc && m.query !== q) return;
  const target = acTarget || promptEdit;
  const results = (m.results || []).filter(r => !(target && target._excludeE621Autocomplete && r.cat === 'e621'));
  if (!results.length) {
    hideAutocomplete();
    checkTagHint();
    return;
  }
  acResults = results;
  acSel = -1;
  acMode = true;
  renderAutocomplete();
}

function renderAutocomplete() {
  let html = '<div class="tag-ac-list">';
  acResults.forEach((r, i) => {
    const sel = i === acSel ? ' selected' : '';
    const wcType = r._wc_type;
    const tagColor = wcType ? catStyle(wcType) : catStyle(r.cat);
    const prefix = wcType === 'wildcard' ? '__' : '';
    const suffix = wcType === 'wildcard' ? '__' : '';
    html += `<div class="tag-ac-item${sel}" data-idx="${i}">` +
      `<span class="tag-ac-tag"${tagColor}>${escHtml(prefix + r.tag + suffix)}</span>` +
      `<span class="tag-ac-group">${escHtml(r.group || '')}</span>` +
      `<span class="tag-ac-count">${wcType ? escHtml(r.desc || '') : fmtCount(r.count)}</span>` +
      '</div>';
  });
  html += '</div>';
  tagTooltip.innerHTML = html;
  tagTooltip.classList.add('open', 'ac-mode');
  _syncTooltipSide();
  tagTooltip.querySelectorAll('.tag-ac-item').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault();
      selectAutocomplete(+el.dataset.idx);
    });
  });
}

function selectAutocomplete(idx) {
  const r = acResults[idx];
  if (!r) return;
  const target = acTarget || promptEdit;
  const info = getActiveTokenInfo(target);
  if (!info) return;
  let newTag = r.tag;
  // Wildcard result: wrap with __name__
  if (r._wc_type === 'wildcard') {
    newTag = '__' + r.tag + '__';
    swapToken(target, info, newTag);
    hideAutocomplete();
    return;
  }
  // 비NAI 모드: () → \(\) 이스케이프 (A1111/ComfyUI 가중치 구문 충돌 방지)
  if (modeSelect.value !== 'NAI') {
    newTag = newTag.replace(/\(/g, '\\(').replace(/\)/g, '\\)');
  }
  // Preserve prefix (artist:, character:, @) if present in token
  const sLower = info.stripped.toLowerCase();
  if (sLower.startsWith('@') && !newTag.startsWith('@')) {
    newTag = '@' + newTag;
  } else {
    for (const pfx of ['artist:', 'character:']) {
      if (sLower.startsWith(pfx) && !newTag.toLowerCase().startsWith(pfx)) {
        newTag = pfx + newTag;
        break;
      }
    }
  }
  swapToken(target, info, newTag);
  hideAutocomplete();
  lastLookupTag = newTag;
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({type: 'tag_lookup', tag: r.tag}));
}

function swapToken(textarea, tokenInfo, newTag) {
  const text = textarea.value;
  const raw = tokenInfo.raw;
  const stripped = tokenInfo.stripped;
  const rawLower = raw.toLowerCase();
  const strippedLower = stripped.toLowerCase();
  const idx = rawLower.indexOf(strippedLower);
  let prefix = '', suffix = '';
  if (idx >= 0) {
    prefix = raw.substring(0, idx);
    suffix = raw.substring(idx + stripped.length);
  }
  const replacement = prefix + newTag + suffix;
  textarea.value = text.substring(0, tokenInfo.start) + replacement + text.substring(tokenInfo.end);
  const newPos = tokenInfo.start + replacement.length;
  textarea.selectionStart = textarea.selectionEnd = newPos;
  textarea.focus();
  if (textarea === promptEdit) onPromptEdit();
  else _fireModuleOninput(textarea);
}

// Trigger the module oninput handler for non-main textareas
function _fireModuleOninput(el) {
  const handler = el.getAttribute('oninput');
  if (handler) new Function('event', handler).call(el, {target: el});
}

function hideAutocomplete() {
  acMode = false;
  acResults = [];
  acSel = -1;
  lastAcQuery = '';
  clearTimeout(acTimer);
  tagTooltip.classList.remove('open', 'ac-mode');
}

// ---- Bind autocomplete/hint to a textarea ----
function bindTagAssist(textarea, options = {}) {
  textarea._excludeE621Autocomplete = !!options.excludeE621;
  let composing = false;
  textarea.addEventListener('compositionstart', () => { composing = true; });
  textarea.addEventListener('compositionend', () => {
    composing = false;
    scheduleAutocomplete();
  });
  textarea.addEventListener('input', () => {
    acTarget = textarea;
    if (!composing) scheduleAutocomplete();
  });
  textarea.addEventListener('click', () => {
    acTarget = textarea;
    if (acMode) hideAutocomplete();
    checkTagHint();
  });
  textarea.addEventListener('keyup', e => {
    if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) {
      if (acMode) hideAutocomplete();
      checkTagHint();
    }
  });
  textarea.addEventListener('focus', () => {
    acTarget = textarea;
    if (!acMode) checkTagHint();
  });
  textarea.addEventListener('blur', () => {
    setTimeout(() => {
      if (document.activeElement !== textarea) {
        hideAutocomplete();
        tagTooltip.classList.remove('open', 'ac-mode');
      }
    }, 200);
  });
  textarea.addEventListener('keydown', e => {
    if (!acMode || !acResults.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      acSel = Math.min(acSel + 1, acResults.length - 1);
      renderAutocomplete();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      acSel = Math.max(acSel - 1, -1);
      renderAutocomplete();
    } else if ((e.key === 'Enter' || e.key === 'Tab') && acSel >= 0) {
      e.preventDefault();
      e.stopPropagation();
      selectAutocomplete(acSel);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hideAutocomplete();
      checkTagHint();
    }
  });
}

// Bind main prompt + negative prompt textarea
bindTagAssist(promptEdit);
bindTagAssist(negEdit);
// Main prompt also syncs to server
promptEdit.addEventListener('focus', () => { applyPromptHighlightState(); });
promptEdit.addEventListener('blur', () => {
  applyPromptHighlightState();
  // blur 시 flush 제거: 편집값을 서버 값으로 자동 덮어쓰지 않음 (Q2-B).
  // 남은 defer 값은 버려서 stale overwrite 방지.
  deferredPromptSync = null;
});
negEdit.addEventListener('blur', () => {
  deferredPromptSync = null;
});
promptEdit.addEventListener('compositionend', () => { onPromptEdit(); });
promptEdit.addEventListener('input', () => { onPromptEdit(); });
applyPromptHighlightState();
updatePromptTokenEstimate();

// ---- Keyboard shortcuts ----
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.ctrlKey && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    send('generate');
  } else if (e.key === 'Enter' && e.altKey && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    send('random');
  }
});

// ---- Init ----
negEdit.addEventListener('input', onPromptEdit);

// ---- Tag Filter ----
function toggleTagFilter() { if (quickFilter) quickFilter.toggle(); }
function openTagFilter() { if (quickFilter) quickFilter.open(); }
function closeTagFilter() { if (quickFilter) quickFilter.close(); }
function renderTagFilterChips() { /* rendered by quickFilter controller */ }
function renderTagFilterExcludeChips() { /* rendered by quickFilter controller */ }
function removeTagFilterExcludeTag(idx) { if (quickFilter) quickFilter.removeExcludeTag(idx); }
function removeTagFilterTag(idx) { if (quickFilter) quickFilter.removeIncludeTag(idx); }
function applyTagFilter() { if (quickFilter) quickFilter.apply(); }
function assignTagFilter() { if (quickFilter) quickFilter.assign(); }
function clearTagFilter() { if (quickFilter) quickFilter.clear(); }
function onTagFilterResult(m) { if (quickFilter) quickFilter.onResult(m); }
function onTagFilterAssigned(m) { if (quickFilter) quickFilter.onAssigned(m); }
function onTagFilterAcResult(m) { if (quickFilter) quickFilter.onAutocompleteResult(m); }
Promise.all([
  quickFilterReady,
  wsDispatcherReady,
  rightTabsReady,
  resultInfoResizerReady,
  resultHistoryReady,
  promptHighlighterReady,
  moduleBadgesReady,
  cloudflaredControlsReady,
])
  .then(() => {
    initHistoryRail();
    initResultInfoResizer();
    connect();
  })
  .catch(error => {
    console.error('Failed to initialize remote shell', error);
  });
