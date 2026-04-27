/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, generating = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&#39;').replace(/"/g,'&quot;') : '';
let reconnTimer = null, genTimer = null, genStartTime = 0;
const genDurations = [];  // last 5 generation durations (ms)

let _initDone = false;  // init_complete 수신 후 true → 초기 시딩 제외
let syncingOptions = false, syncingPrompt = false, promptSendTimer = null;
// 사용자가 로컬 편집을 했지만 아직 서버로 flush되지 않은 상태 — 서버 브로드캐스트 덮어쓰기 차단
let _localPromptDirty = false;
let awaitingMyRandom = false;  // 내가 Random 클릭했는지 추적
let sessionId = null, sharedMode = false;
let _restoringSession = false;  // 재연결 복원 중 서버 초기값 무시 플래그
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
let generationProgress = null;
let setupController = null;
let desktopWindowControl = null;
let promptDrawerControl = null;
let tokenDisplayControl = null;
let autoSavePanel = null;
let saveDirectoryPanel = null;
let sessionGenerationStats = null;
let automationPanel = null;
let characterPanel = null;
let conditionalPromptPanel = null;
let wildcardPanel = null;
let wildcardManagerPanel = null;
let imageModulePanels = null;
let refinePanelControl = null;
let tagSearchController = null;
let mobileViewportControl = null;
let searchPanelControl = null;
let chunkPanelControl = null;
let danbooruFeedbackControl = null;
let promptEngineeringPopupRenderers = null;
let promptEngineeringPanelControl = null;
let promptEngineeringActions = null;
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
      getRatingState: getRatingStateSnapshot,
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
const tokenDisplayReady = import('./js/features/tokenDisplay.mjs')
  .then(({createTokenDisplay}) => {
    tokenDisplayControl = createTokenDisplay({
      promptEdit,
      negEdit,
      promptTokenLabel,
      negativeTokenLabel,
      modeSelect,
      getCurrentMode: () => currentMode,
    });
  })
  .catch(error => {
    console.error('Failed to initialize token display module', error);
  });
const moduleBadgesReady = import('./js/features/moduleBadges.mjs')
  .then(({createModuleBadges}) => {
    moduleBadges = createModuleBadges({
      document,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      estimateTokenCount,
      setCharacterPromptText: value => { if (tokenDisplayControl) tokenDisplayControl.setCharacterPromptText(value); },
      setCharacterTokenCount: value => { if (tokenDisplayControl) tokenDisplayControl.setCharacterTokenCount(value); },
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
      getApiStatus: () => setupController ? setupController.getApiStatus() : null,
      navigator,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize cloudflared controls module', error);
  });
const setupControllerReady = import('./js/features/setupController.mjs')
  .then(({createSetupController}) => {
    setupController = createSetupController({
      document,
      getWs: () => ws,
      WebSocket,
      getSharedMode: () => sharedMode,
      showToast,
      updateModeSelectAvailability,
      renderCloudflaredControls,
      setupLauncherBtn,
      modeApiCombo,
    });
  })
  .catch(error => {
    console.error('Failed to initialize setup controller module', error);
  });
const generationProgressReady = import('./js/features/generationProgress.mjs')
  .then(({createGenerationProgress}) => {
    generationProgress = createGenerationProgress({
      document,
      window,
      getGenStartTime: () => genStartTime,
      getDurations: () => genDurations,
    });
  })
  .catch(error => {
    console.error('Failed to initialize generation progress module', error);
  });
const desktopWindowControlReady = import('./js/features/desktopWindowControl.mjs')
  .then(({createDesktopWindowControl}) => {
    desktopWindowControl = createDesktopWindowControl({
      document,
      getWs: () => ws,
      WebSocket,
    });
  })
  .catch(error => {
    console.error('Failed to initialize desktop window control module', error);
  });
const promptDrawerReady = import('./js/features/promptDrawer.mjs')
  .then(({createPromptDrawer}) => {
    promptDrawerControl = createPromptDrawer({
      document,
      getWs: () => ws,
      WebSocket,
      mediaQuery: isPC,
    });
  })
  .catch(error => {
    console.error('Failed to initialize prompt drawer module', error);
  });
const autoSavePanelReady = import('./js/features/autoSavePanel.mjs')
  .then(({createAutoSavePanel}) => {
    autoSavePanel = createAutoSavePanel({
      document,
      getWs: () => ws,
      WebSocket,
      getSharedMode: () => sharedMode,
      getCurrentModuleId: () => currentModuleId,
      isModulePopupOpen: () => modulePopup.classList.contains('open'),
      escHtml,
      openModule,
      setModuleParam,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize auto save panel module', error);
  });
const saveDirectoryPanelReady = import('./js/features/saveDirectoryPanel.mjs')
  .then(({createSaveDirectoryPanel}) => {
    saveDirectoryPanel = createSaveDirectoryPanel({
      document,
      getWs: () => ws,
      WebSocket,
      escHtml,
      openModule,
      setModuleParam,
    });
  })
  .catch(error => {
    console.error('Failed to initialize save directory panel module', error);
  });
const sessionGenerationStatsReady = import('./js/features/sessionGenerationStats.mjs')
  .then(({createSessionGenerationStats}) => {
    sessionGenerationStats = createSessionGenerationStats({
      statsGenCount,
    });
  })
  .catch(error => {
    console.error('Failed to initialize session generation stats module', error);
  });
const automationPanelReady = import('./js/features/automationPanel.mjs')
  .then(({createAutomationPanel}) => {
    automationPanel = createAutomationPanel({
      document,
      setModuleParam,
    });
  })
  .catch(error => {
    console.error('Failed to initialize automation panel module', error);
  });
const characterPanelReady = import('./js/features/characterPanel.mjs')
  .then(({createCharacterPanel}) => {
    characterPanel = createCharacterPanel({
      document,
      escHtml,
      bindTagAssist,
      flushCharacterEdits,
      setModuleParam,
    });
  })
  .catch(error => {
    console.error('Failed to initialize character panel module', error);
  });
const conditionalPromptPanelReady = import('./js/features/conditionalPromptPanel.mjs')
  .then(({createConditionalPromptPanel}) => {
    conditionalPromptPanel = createConditionalPromptPanel({
      document,
      escHtml,
      getSharedMode: () => sharedMode,
      getSharedCond: () => _sharedCond,
      setSharedCond: value => { _sharedCond = value; },
      saveSharedSession,
      onModTextEdit,
    });
  })
  .catch(error => {
    console.error('Failed to initialize conditional prompt panel module', error);
  });
const wildcardPanelReady = import('./js/features/wildcardPanel.mjs')
  .then(({createWildcardPanel}) => {
    wildcardPanel = createWildcardPanel({
      document,
      escHtml,
    });
  })
  .catch(error => {
    console.error('Failed to initialize wildcard panel module', error);
  });
const wildcardManagerPanelReady = import('./js/features/wildcardManagerPanel.mjs')
  .then(({createWildcardManagerPanel}) => {
    wildcardManagerPanel = createWildcardManagerPanel({
      document,
      moduleBody,
      escHtml,
      setModuleParam,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize wildcard manager panel module', error);
  });
const imageModulePanelsReady = import('./js/features/imageModulePanels.mjs')
  .then(({createImageModulePanels}) => {
    imageModulePanels = createImageModulePanels({
      document,
      moduleBody,
      escHtml,
      setModuleParam,
      showToast,
      openModule,
      getCurrentModuleId: () => currentModuleId,
    });
  })
  .catch(error => {
    console.error('Failed to initialize image module panels', error);
  });
const refinePanelReady = import('./js/features/refinePanel.mjs')
  .then(({createRefinePanel}) => {
    refinePanelControl = createRefinePanel({
      document,
      panel: refinePanel,
      modulePopup,
      escHtml,
      getWs: () => ws,
      WebSocket,
      closeAuxiliaryPopups,
      positionFloatingPanel,
    });
  })
  .catch(error => {
    console.error('Failed to initialize refine panel module', error);
  });
const tagSearchReady = import('./js/features/tagSearch.mjs')
  .then(({createTagSearchController}) => {
    tagSearchController = createTagSearchController({
      document,
      input: tagSearchInput,
      results: tagSearchResults,
      promptEdit,
      escHtml,
      getWs: () => ws,
      WebSocket,
      onPromptEdit,
    });
  })
  .catch(error => {
    console.error('Failed to initialize tag search module', error);
  });
const mobileViewportReady = import('./js/features/mobileViewport.mjs')
  .then(({createMobileViewportController}) => {
    mobileViewportControl = createMobileViewportController({
      window,
      document,
      isPC,
      relayoutFloatingPanels,
      getTagTooltip: () => tagTooltip,
    });
  })
  .catch(error => {
    console.error('Failed to initialize mobile viewport module', error);
  });
const searchPanelReady = import('./js/features/searchPanel.mjs')
  .then(({createSearchPanel}) => {
    searchPanelControl = createSearchPanel({
      document,
      moduleBody,
      searchCountEl,
      escHtml,
      getWs: () => ws,
      WebSocket,
      getQuickFilter: () => quickFilter,
      getSharedMode: () => sharedMode,
      getCurrentModuleId: () => currentModuleId,
      bindTagAssist,
    });
  })
  .catch(error => {
    console.error('Failed to initialize search panel module', error);
  });
const chunkPanelReady = import('./js/features/chunkPanel.mjs')
  .then(({createChunkPanel}) => {
    chunkPanelControl = createChunkPanel({
      document,
      panel: chunkPanel,
      moduleBody,
      modulePopup,
      promptEdit,
      getWs: () => ws,
      WebSocket,
      getSharedMode: () => sharedMode,
      getAcTarget: () => acTarget,
      showToast,
      updateModuleBtnState,
      positionFloatingPanel,
      onPromptEdit,
      fireModuleOninput: _fireModuleOninput,
      escHtml,
    });
  })
  .catch(error => {
    console.error('Failed to initialize chunk panel module', error);
  });
const danbooruFeedbackReady = import('./js/features/danbooruFeedback.mjs')
  .then(({createDanbooruFeedbackController}) => {
    danbooruFeedbackControl = createDanbooruFeedbackController({document});
  })
  .catch(error => {
    console.error('Failed to initialize Danbooru feedback module', error);
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
    ratings: getActiveRatings(),
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
    if (sessionGenerationStats) sessionGenerationStats.record();
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
    if (searchPanelControl) searchPanelControl.updatePromptGeneratedCount(m);
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
    if (setupController) setupController.resetInitialProbe();
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
    if (desktopWindowControl) desktopWindowControl.disable();
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

function cleanPromptForTokenEstimate(text, mode) {
  return tokenDisplayControl ? tokenDisplayControl.cleanPromptForTokenEstimate(text, mode) : '';
}

function estimateTokenCount(text, mode) {
  return tokenDisplayControl ? tokenDisplayControl.estimateTokenCount(text, mode) : 0;
}

function updateNegativeTokenEstimate() {
  if (tokenDisplayControl) tokenDisplayControl.updateNegativeTokenEstimate();
}

function updatePromptTokenEstimate() {
  if (tokenDisplayControl) tokenDisplayControl.updatePromptTokenEstimate();
}

function applyNegativeTokenPayload(m) {
  if (tokenDisplayControl) tokenDisplayControl.applyNegativeTokenPayload(m);
}

function applyPromptTokenPayload(m) {
  if (tokenDisplayControl) tokenDisplayControl.applyPromptTokenPayload(m);
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
    if (promptDrawerControl) promptDrawerControl.showNewContentDot();
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
  if (tokenDisplayControl) tokenDisplayControl.invalidatePromptCounts();
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
  if (autoSavePanel) autoSavePanel.open();
}

function setAutoSaveEnabled(enabled) {
  if (autoSavePanel) autoSavePanel.setEnabled(enabled);
}

function renderAutoSavePanel(state) {
  if (autoSavePanel) autoSavePanel.render(state);
}

function _updateSaveUI() {
  if (autoSavePanel) autoSavePanel.updateSaveUi();
}

function updateGenStats() {
  if (sessionGenerationStats) sessionGenerationStats.update();
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
    if (setupController) setupController.forceCloseForSharedMode();
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
  if (desktopWindowControl) desktopWindowControl.onState(m);
}

function toggleDesktopWindow() {
  if (desktopWindowControl) desktopWindowControl.toggle();
}

function _restoreSharedSession() {
  const saved = loadSharedSession();
  if (!saved) {
    // 저장된 세션 없음 (최초 접속) — GSQE 기본값을 서버에 전송
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'set_active_ratings', ratings: getActiveRatings()}));
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
    setRatingsFromList(saved.ratings);
    syncRatingButtons();
    // 서버 세션에 rating 저장
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'set_active_ratings', ratings: getActiveRatings()}));
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
  if (promptDrawerControl) promptDrawerControl.toggle();
}

function switchTab(name) {
  if (promptDrawerControl) promptDrawerControl.switchTab(name);
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
      ws.send(JSON.stringify({type: 'random', ratings: getActiveRatings()}));
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
  if (generationProgress) generationProgress.start();
}

function finishProgress() {
  if (generationProgress) generationProgress.finish();
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
    if (autoSavePanel) autoSavePanel.syncEnabled(m.auto_save);
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
  return setupController ? setupController.isModeConnected(mode) : false;
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
function openApiPopup() {
  if (setupController) setupController.openApiPopup();
}

function probeApi() {
  if (setupController) setupController.probeApi();
}

function onProbeResult(m) {
  if (setupController) setupController.onProbeResult(m);
}

function closeApiPopup() {
  if (setupController) setupController.closeApiPopup();
}

function onSetupBackdrop(event) {
  if (setupController) setupController.onSetupBackdrop(event);
}

function switchSetupTab(tab) {
  if (setupController) setupController.switchSetupTab(tab);
}

function toggleSetupReveal(id, btn) {
  if (setupController) setupController.toggleSetupReveal(id, btn);
}

function setSetupResult(mode, message, messageType) {
  if (setupController) setupController.setSetupResult(mode, message, messageType);
}

function setSetupLoading(mode, loading) {
  if (setupController) setupController.setSetupLoading(mode, loading);
}

function verifyNai() {
  if (setupController) setupController.verifyNai();
}

function verifyWebui() {
  if (setupController) setupController.verifyWebui();
}

function verifyComfyui() {
  if (setupController) setupController.verifyComfyui();
}

function clearApi(mode) {
  if (setupController) setupController.clearApi(mode);
}

function onVerifyResult(m) {
  if (setupController) setupController.onVerifyResult(m);
}

function onSetupBlocked(m) {
  if (setupController) setupController.onSetupBlocked(m);
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
  if (setupController) setupController.applySetupGate(m);
}

function setLauncherConn(on) {
  if (setupController) setupController.setLauncherConn(on);
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
  if (setupController) setupController.updateApiStatus(m);
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

let lastPromptEngineeringState = null;
const promptEngineeringPanelReady = import('./js/features/promptEngineeringPanel.mjs')
  .then(({createPromptEngineeringPanel}) => {
    promptEngineeringPanelControl = createPromptEngineeringPanel({
      document,
      moduleBody,
      escHtml,
      getSharedMode: () => sharedMode,
      getSharedPromptEngineering: () => _sharedPEng,
      setSharedPromptEngineering: value => { _sharedPEng = value; },
      saveSharedSession,
      bindTagAssist,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering panel module', error);
  });
const promptEngineeringActionsReady = import('./js/features/promptEngineeringActions.mjs')
  .then(({createPromptEngineeringActions}) => {
    promptEngineeringActions = createPromptEngineeringActions({
      document,
      getSharedMode: () => sharedMode,
      getMode: () => modeSelect.value,
      showToast,
      confirmDialog: message => confirm(message),
      flushPromptEngineeringEdits,
      flushMainPromptAndParams,
      setModuleParam,
      closePresetAddPanel: closePePresetAddPanel,
      closePresetManagePanel: closePePresetManagePanel,
      getLastPromptEngineeringState: () => lastPromptEngineeringState,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering actions module', error);
  });

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
  if (moduleId === 'auto_save' && autoSavePanel) {
    autoSavePanel.renderCached();
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
  if (chunkPanelControl) chunkPanelControl.clearTriggerInfo();
  updateModuleHeaderAction(null);
  updateModuleBtnState();
}

function updateModuleBtnState() {
  document.querySelectorAll('.module-btn').forEach(btn => {
    const isChunkBtn = btn.dataset.module === 'chunk';
    btn.classList.toggle('active', isChunkBtn ? isChunkOpen() : btn.dataset.module === currentModuleId);
  });
  const pb = document.querySelector('.module-prompt-btn');
  if (pb) pb.classList.toggle('active', currentModuleId === 'search');
}

const peE621Panel = $('peE621Panel');
const pePresetAddPanel = $('pePresetAddPanel');
const pePresetManagePanel = $('pePresetManagePanel');
const peDanbooruPanel = $('peDanbooruPanel');
const peDebugPanel = $('peDebugPanel');
const promptEngineeringPopupRenderersReady = import('./js/features/promptEngineeringPopupRenderers.mjs')
  .then(({createPromptEngineeringPopupRenderers}) => {
    promptEngineeringPopupRenderers = createPromptEngineeringPopupRenderers({
      document,
      requestAnimationFrame: window.requestAnimationFrame.bind(window),
      escHtml,
      getSharedMode: () => sharedMode,
      createPromptPreset,
      bindDanbooruFeedback,
      panels: {
        e621: peE621Panel,
        presetAdd: pePresetAddPanel,
        presetManage: pePresetManagePanel,
        danbooru: peDanbooruPanel,
        debug: peDebugPanel,
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering popup renderers module', error);
  });
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
  if (exceptPanel !== chunkPanel && isChunkOpen()) closeChunkPanel();
  if (exceptPanel !== refinePanel && refinePanelControl && refinePanelControl.isOpen()) closeRefine();
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
  else if (m.module_id === 'auto_save' && autoSavePanel) autoSavePanel.setState(m);
  else if (m.module_id === 'character') updateCharBadge(m);
  else if (m.module_id === 'character_reference') updateCharRefBadge(m);
  else if (m.module_id === 'vibe_transfer') updateVibeBadge(m);
  else if (m.module_id === 'save_directory' && saveDirectoryPanel) saveDirectoryPanel.setState(m);

  if (m.module_id === 'prompt_engineering') {
    lastPromptEngineeringState = m;
    syncPromptEngineeringPopups();
  }
  if (m.module_id === 'chunk' && isChunkOpen()) {
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
  if (saveDirectoryPanel) saveDirectoryPanel.open();
}

function onAutoSaveWebpChange(checked) {
  if (autoSavePanel) autoSavePanel.onWebpChange(checked);
}

function onHistoryLimitToggle(checked) {
  if (autoSavePanel) autoSavePanel.onHistoryLimitToggle(checked);
}

function onHistoryLimitLengthChange(value) {
  if (autoSavePanel) autoSavePanel.onHistoryLimitLengthChange(value);
}

function onHistoryLimitActionChange(value) {
  if (autoSavePanel) autoSavePanel.onHistoryLimitActionChange(value);
}

function browseSaveDirectory() {
  if (saveDirectoryPanel) saveDirectoryPanel.browse();
}

function onSaveDirectoryToggle(checked) {
  if (saveDirectoryPanel) saveDirectoryPanel.onTimestampToggle(checked);
}

function onSaveDirectoryFilenameFormatChange(value) {
  if (saveDirectoryPanel) saveDirectoryPanel.onFilenameFormatChange(value);
}

function onSaveDirectoryClassificationChange(value) {
  if (saveDirectoryPanel) saveDirectoryPanel.onClassificationChange(value);
}

function renderSaveDirectory(m) {
  if (saveDirectoryPanel) saveDirectoryPanel.render(m);
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

function renderPromptEngineering(m) {
  if (promptEngineeringPanelControl) promptEngineeringPanelControl.render(m);
}

function renderPePresetAddPanel(m) {
  if (promptEngineeringPopupRenderers) promptEngineeringPopupRenderers.renderPresetAdd(m);
}

function renderPePresetManagePanel(m) {
  if (promptEngineeringPopupRenderers) promptEngineeringPopupRenderers.renderPresetManage(m);
}

function renderPromptEngineeringDebug(snapshot) {
  return promptEngineeringPopupRenderers ? promptEngineeringPopupRenderers.renderDebugSnapshot(snapshot) : '';
}

function renderPeE621Panel(m) {
  if (promptEngineeringPopupRenderers) promptEngineeringPopupRenderers.renderE621(m);
}

function getDanbooruPreviewState(baseSettings = {}) {
  return danbooruFeedbackControl ? danbooruFeedbackControl.getPreviewState(baseSettings) : {};
}

function renderDanbooruVisualFeedback(state) {
  return danbooruFeedbackControl ? danbooruFeedbackControl.renderVisualFeedback(state) : '';
}

function syncDanbooruFeedback(baseSettings = {}) {
  if (danbooruFeedbackControl) danbooruFeedbackControl.sync(baseSettings);
}

function bindDanbooruFeedback(baseSettings = {}) {
  if (danbooruFeedbackControl) danbooruFeedbackControl.bind(baseSettings);
}

function renderPeDanbooruPanel(m) {
  if (promptEngineeringPopupRenderers) promptEngineeringPopupRenderers.renderDanbooru(m);
}

function renderPeDebugPanel(m) {
  if (promptEngineeringPopupRenderers) promptEngineeringPopupRenderers.renderDebugPanel(m);
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
  if (promptEngineeringActions) promptEngineeringActions.flushPresetSaveState();
}

function onPromptPresetChange(value) {
  if (promptEngineeringActions) promptEngineeringActions.onPresetChange(value);
}

function saveCurrentPromptPreset() {
  if (promptEngineeringActions) promptEngineeringActions.saveCurrentPreset();
}

function createPromptPreset() {
  if (promptEngineeringActions) promptEngineeringActions.createPreset();
}

function applyRecommendedPromptPreset() {
  if (promptEngineeringActions) promptEngineeringActions.applyRecommendedPreset();
}

function deleteCurrentPromptPreset() {
  if (promptEngineeringActions) promptEngineeringActions.deleteCurrentPreset();
}

function savePromptEngineeringE621Settings() {
  if (promptEngineeringActions) promptEngineeringActions.saveE621Settings();
}

function savePromptEngineeringDanbooruSettings() {
  if (promptEngineeringActions) promptEngineeringActions.saveDanbooruSettings();
}

function refreshPromptEngineeringDebug() {
  if (promptEngineeringActions) promptEngineeringActions.refreshDebug();
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
  if (promptEngineeringActions) promptEngineeringActions.setOption(key, checked);
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
  if (characterPanel) characterPanel.addSlot();
}

function removeCharacterSlot(index) {
  if (characterPanel) characterPanel.removeSlot(index);
}

function refreshCharacterPreview() {
  if (characterPanel) characterPanel.refreshPreview();
}

// ---- Automation module ----
function onAutoTypeChange(val) {
  if (automationPanel) automationPanel.onTypeChange(val);
}

function renderAutomation(m) {
  if (automationPanel) automationPanel.render(m);
}

// ---- Character module ----
function renderCharacter(m) {
  if (characterPanel) characterPanel.render(m);
}

// ---- Conditional Prompt module ----
function formatCondLog(log) {
  return conditionalPromptPanel ? conditionalPromptPanel.formatLog(log) : '';
}

function formatCondRules(text) {
  return conditionalPromptPanel ? conditionalPromptPanel.formatRules(text) : '<br>';
}

function onCondRulesInput(el) {
  if (conditionalPromptPanel) conditionalPromptPanel.onRulesInput(el);
}

function syncCondScroll(el) {
  if (conditionalPromptPanel) conditionalPromptPanel.syncScroll(el);
}

function renderConditionalPrompt(m) {
  if (conditionalPromptPanel) conditionalPromptPanel.render(m);
}

// ---- Wildcard Module ----
function renderWildcard(m) {
  if (wildcardPanel) wildcardPanel.render(m);
}

// ---- Chunk Module (instant wildcard tree browser) ----
function requestChunkState() {
  if (chunkPanelControl) chunkPanelControl.requestState();
}

function getChunkAnchor(target = null) {
  return chunkPanelControl ? chunkPanelControl.getAnchor(target) : modulePopup;
}

function openChunkPanel(anchorEl = null, toggle = false) {
  if (chunkPanelControl) chunkPanelControl.open(anchorEl, toggle);
}

function closeChunkPanel() {
  if (chunkPanelControl) chunkPanelControl.close();
}

function renderChunk(m) {
  if (chunkPanelControl) chunkPanelControl.render(m);
}

function chunkToggleGroup(groupEl) {
  if (chunkPanelControl) chunkPanelControl.toggleGroup(groupEl);
}

function chunkInsert(el) {
  if (chunkPanelControl) chunkPanelControl.insert(el);
}

function isChunkOpen() {
  return !!(chunkPanelControl && chunkPanelControl.isOpen());
}

// ---- Wildcard Manager (file browser + editor + generator) ----
function wcOpenBrowser() {
  if (wildcardManagerPanel) wildcardManagerPanel.openBrowser();
}

function onWildcardManager(m) {
  if (wildcardManagerPanel) wildcardManagerPanel.onMessage(m);
}

function wcRenderTree(tree) {
  if (wildcardManagerPanel) wildcardManagerPanel.renderTree(tree);
}

function wcRenderEditor(path, content) {
  if (wildcardManagerPanel) wildcardManagerPanel.renderEditor(path, content);
}

function wcToggleEdit() {
  if (wildcardManagerPanel) wildcardManagerPanel.toggleEdit();
}

function wcCancelEdit() {
  if (wildcardManagerPanel) wildcardManagerPanel.cancelEdit();
}

function wcSaveFile() {
  if (wildcardManagerPanel) wildcardManagerPanel.saveFile();
}

function wcDeleteFile() {
  if (wildcardManagerPanel) wildcardManagerPanel.deleteFile();
}

function wcAddEntry() {
  if (wildcardManagerPanel) wildcardManagerPanel.addEntry();
}

function wcShowPreview(name, result) {
  if (wildcardManagerPanel) wildcardManagerPanel.showPreview(name, result);
}

function wcPromptNewFile() {
  if (wildcardManagerPanel) wildcardManagerPanel.promptNewFile();
}

// ---- Image upload helper ----
function pasteModuleImage(moduleId) {
  if (imageModulePanels) imageModulePanels.pasteImage(moduleId);
}

function uploadModuleImage(moduleId, file) {
  if (imageModulePanels) imageModulePanels.uploadImage(moduleId, file);
}

// ---- Slider debounce for image modules ----
function onModSlider(moduleId, key, value) {
  if (imageModulePanels) imageModulePanels.onSlider(moduleId, key, value);
}

// ---- Character Reference module ----
function renderCharacterReference(m) {
  if (imageModulePanels) imageModulePanels.renderCharacterReference(m);
}

// ---- Vibe Transfer module ----
function renderVibeTransfer(m) {
  if (imageModulePanels) imageModulePanels.renderVibeTransfer(m);
}

// ---- Storage view ----
function requestStorage(moduleId) {
  if (imageModulePanels) imageModulePanels.requestStorage(moduleId);
}

function onStorageList(m) {
  if (imageModulePanels) imageModulePanels.onStorageList(m);
}

function renderCharRefStorage(m) {
  if (imageModulePanels) imageModulePanels.renderCharRefStorage(m);
}

function applyCharRefStorage(fileHash) {
  if (imageModulePanels) imageModulePanels.applyCharRefStorage(fileHash);
}

function renderVibeStorage(m) {
  if (imageModulePanels) imageModulePanels.renderVibeStorage(m);
}

function showVibeStorageTab(btn, model) {
  if (imageModulePanels) imageModulePanels.showVibeStorageTab(btn, model);
}

function applyVibeStorage(model, fileHash, ieValue) {
  if (imageModulePanels) imageModulePanels.applyVibeStorage(model, fileHash, ieValue);
}

// ---- Search system ----
const searchCountEl = $('searchCount');
const DEFAULT_RATING_STATE = {g: true, s: true, q: true, e: true};

function getRatingStateSnapshot() {
  return searchPanelControl ? searchPanelControl.getRatingState() : DEFAULT_RATING_STATE;
}

function getActiveRatings() {
  const state = getRatingStateSnapshot();
  return Object.keys(state).filter(key => state[key]);
}

function setRatingsFromList(ratings) {
  if (searchPanelControl) searchPanelControl.setRatingsFromList(ratings);
}

function _computeLocalFilteredCount() {
  return searchPanelControl ? searchPanelControl.computeLocalFilteredCount() : null;
}

function toggleRating(r) {
  if (searchPanelControl) searchPanelControl.toggleRating(r);
}

function onFilterReset(m) {
  if (searchPanelControl) searchPanelControl.onFilterReset(m);
}

function onRatingUpdate(m) {
  if (searchPanelControl) searchPanelControl.onRatingUpdate(m);
}

function syncRatingButtons() {
  if (searchPanelControl) searchPanelControl.syncRatingButtons();
}

function updateSearchCount(count) {
  if (searchPanelControl) searchPanelControl.updateSearchCount(count);
}

function onSearchState(m) {
  if (searchPanelControl) searchPanelControl.onSearchState(m);
}

function onSearchProgress(m) {
  if (searchPanelControl) searchPanelControl.onSearchProgress(m);
}

function renderSearch(m) {
  if (searchPanelControl) searchPanelControl.renderSearch(m);
}

function doSearch() {
  if (searchPanelControl) searchPanelControl.doSearch();
}

function loadParquet(filename) {
  if (searchPanelControl) searchPanelControl.loadParquet(filename);
}

function restoreSnapshot() {
  if (searchPanelControl) searchPanelControl.restoreSnapshot();
}

// ---- Refine (Depth Search) panel ----
const refinePanel = $('refinePanel');

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
  if (chunkPanelControl) chunkPanelControl.relayout();
  positionFloatingPanel(pePresetAddPanel, modulePopup);
  positionFloatingPanel(pePresetManagePanel, modulePopup);
  positionFloatingPanel(peE621Panel, modulePopup);
  positionFloatingPanel(peDanbooruPanel, modulePopup);
  positionFloatingPanel(peDebugPanel, modulePopup);
}

function openRefine() {
  if (refinePanelControl) refinePanelControl.open();
}

function closeRefine() {
  if (refinePanelControl) refinePanelControl.close();
}

function onDepthState(m) {
  if (refinePanelControl) refinePanelControl.onDepthState(m);
}

function depthFilter() {
  if (refinePanelControl) refinePanelControl.depthFilter();
}

function depthAction(action) {
  if (refinePanelControl) refinePanelControl.depthAction(action);
}

// ---- Tag search (KR/EN) ----
const tagSearchInput = $('tagSearchInput');
const tagSearchResults = $('tagSearchResults');
function fireTagSearch() {
  if (tagSearchController) tagSearchController.fireSearch();
}

function onTagSearchResult(m) {
  if (tagSearchController) tagSearchController.onResult(m);
}

function insertTag(tag) {
  if (tagSearchController) tagSearchController.insertTag(tag);
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
      if (chunkPanelControl) chunkPanelControl.setTriggerInfo(info);
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
  tokenDisplayReady,
  moduleBadgesReady,
  cloudflaredControlsReady,
  setupControllerReady,
  generationProgressReady,
  desktopWindowControlReady,
  promptDrawerReady,
  autoSavePanelReady,
  saveDirectoryPanelReady,
  sessionGenerationStatsReady,
  automationPanelReady,
  characterPanelReady,
  conditionalPromptPanelReady,
  wildcardPanelReady,
  wildcardManagerPanelReady,
  imageModulePanelsReady,
  refinePanelReady,
  tagSearchReady,
  mobileViewportReady,
  searchPanelReady,
  chunkPanelReady,
  danbooruFeedbackReady,
  promptEngineeringPopupRenderersReady,
  promptEngineeringPanelReady,
  promptEngineeringActionsReady,
])
  .then(() => {
    initHistoryRail();
    initResultInfoResizer();
    connect();
  })
  .catch(error => {
    console.error('Failed to initialize remote shell', error);
  });
