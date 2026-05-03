/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, latestResultBlob = null, generating = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&#39;').replace(/"/g,'&quot;') : '';
let genTimer = null, genStartTime = 0;
const genDurations = [];  // last 5 generation durations (ms)

let _initDone = false;  // init_complete 수신 후 true → 초기 시딩 제외
let syncingOptions = false, syncingPrompt = false, promptSendTimer = null;
// 사용자가 로컬 편집을 했지만 아직 서버로 flush되지 않은 상태 — 서버 브로드캐스트 덮어쓰기 차단
let _localPromptDirty = false;
let awaitingMyRandom = false;  // 내가 Random 클릭했는지 추적
let sessionId = null;
const urlParams = new URLSearchParams(location.search);
const isDesktopShell = urlParams.get('desktop_shell') === '1';
const detachedMode = urlParams.get('detached') || '';
const detachedModuleId = urlParams.get('module') || '';
const detachedMetadataPath = urlParams.get('metadata_path') || urlParams.get('path') || '';
const detachedMetadataSource = urlParams.get('source') || '';
const detachedSnapshotToken = urlParams.get('snapshot') || '';
const detachedStandalone = urlParams.get('standalone') === '1';
const isDetachedShell = detachedMode === 'module' || detachedMode === 'metadata';
const isDetachedModule = detachedMode === 'module';
const isDetachedMetadata = detachedMode === 'metadata';
const DETACHED_MODULE_SNAPSHOT_PREFIX = 'naia.detachedModuleSnapshot.';
const detachedDesktopMediaQuery = {
  matches: true,
  addEventListener() {},
  removeEventListener() {},
};
if (isDesktopShell) document.body.classList.add('desktop-shell');
if (isDetachedShell) document.body.classList.add('detached-shell', `detached-${detachedMode}`);
if (isDetachedModule && detachedModuleId) {
  document.body.classList.add(`detached-module-${detachedModuleId.replace(/[^a-z0-9_-]/gi, '_')}`);
}

let wsClient = null;
let quickFilter = null;
let rightTabs = null;
let resultInfoResizer = null;
let resultHistory = null;
let resultEnhance = null;
let resultImageActions = null;
let resultContextMenu = null;
let resultImageInput = null;
let queuePanel = null;
let imageActionPopup = null;
let metadataViewer = null;
let pendingResultEnhanceConfig = null;
let resultEnhanceAssetRequestId = 0;
let promptHighlighter = null;
let moduleBadges = null;
let moduleLauncherControl = null;
let comfyuiWorkflowState = {
  has_custom: false,
  workflow_label: 'Basic Workflow',
};
let comfyuiWorkflowFileInput = null;
let cloudflaredControls = null;
let img2imgSessionPopup = null;
let generationProgress = null;
let setupController = null;
let desktopWindowControl = null;
let promptDrawerControl = null;
let tokenDisplayControl = null;
let autoSavePanel = null;
let saveDirectoryPanel = null;
let sessionGenerationStats = null;

function openUrlInSystemBrowser(target) {
  const targetUrl = new URL(target, window.location.href);
  if (targetUrl.hostname === '0.0.0.0') targetUrl.hostname = '127.0.0.1';
  if (isDesktopShell) {
    window.location.href = `naia-open-browser://open?url=${encodeURIComponent(targetUrl.toString())}`;
    return true;
  }
  const popup = window.open(targetUrl.toString(), '_blank');
  if (!popup) return false;
  try { popup.opener = null; } catch (error) {}
  popup.focus?.();
  return true;
}
let automationPanel = null;
let characterPanel = null;
let conditionalPromptPanel = null;
let wildcardPanel = null;
let wildcardManagerPanel = null;
let instantWildcardPanel = null;
let e621EventPanel = null;
let ollamaPanel = null;
let imageModulePanels = null;
let img2imgPanel = null;
let refinePanelControl = null;
let tagSearchController = null;
let mobileViewportControl = null;
let searchPanelControl = null;
let chunkPanelControl = null;
let danbooruFeedbackControl = null;
let danbooruTabControl = null;
let thumbTabControl = null;
let artistThumbControl = null;
let studioTabControl = null;
let customSelectsControl = null;
let promptEngineeringPopupRenderers = null;
let promptEngineeringPanelControl = null;
let promptEngineeringActions = null;
let promptEngineeringPopups = null;
let promptHighlightIndexPromise = null;
const moduleStateCache = new Map();
let detachedAttachPosted = false;
let transferredModuleStateGuard = {moduleId: '', until: 0, timer: null};
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
const danbooruTabReady = import('./js/features/danbooruTab.mjs')
  .then(({createDanbooruBrowserController}) => {
    danbooruTabControl = createDanbooruBrowserController({
      document,
      fetch: window.fetch.bind(window),
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Danbooru browser module', error);
  });
const thumbTabReady = import('./js/features/thumbTab.mjs')
  .then(({createThumbTabController}) => {
    thumbTabControl = createThumbTabController({
      document,
      escHtml,
      showToast,
      promptEdit,
      onPromptEdit,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Thumb tab module', error);
  });
const artistThumbReady = import('./js/features/artistThumbTab.mjs')
  .then(({createArtistThumbController}) => {
    artistThumbControl = createArtistThumbController({
      document,
      fetch: window.fetch.bind(window),
      escHtml,
      showToast,
      promptEdit,
      negEdit,
      onPromptEdit,
      getGenerationMode: () => currentMode || modeSelect.value || 'NAI',
      isComfyUiAnimaMode,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Artist Thumb tab module', error);
  });
const studioTabReady = import('./js/features/studioTab.mjs')
  .then(({createStudioTabController}) => {
    studioTabControl = createStudioTabController({
      document,
      localStorage,
      WebSocket,
      getWs: () => ws,
      getGenerating: () => generating,
      promptEdit,
      negEdit,
      getResolutionOptions: () => Array.from(paramEls.resolution?.options || [])
        .map(option => option.value || option.textContent || '')
        .filter(Boolean),
      getCurrentResolution: () => paramEls.resolution?.value || qResolution?.value || '',
      setParam,
      setPromptFields: applyPromptFields,
      generate: requestGenerate,
      showToast,
      escHtml,
    });
    studioTabControl.init();
  })
  .catch(error => {
    console.error('Failed to initialize Studio tab module', error);
  });
const customSelectsReady = import('./js/features/customSelects.mjs')
  .then(({createCustomSelectController}) => {
    customSelectsControl = createCustomSelectController({
      document,
      window,
    });
    customSelectsControl.start();
  })
  .catch(error => {
    console.error('Failed to initialize custom select module', error);
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
      renderPromptInfoHtml,
      onPromptInfoTagLookup: lookupPromptInfoTag,
      onDiskImageSelected: updateResultEnhanceForSavedPath,
    });
  })
  .catch(error => {
    console.error('Failed to initialize result history module', error);
  });
const resultEnhanceReady = import('./js/features/resultEnhance.mjs')
  .then(({createResultEnhanceController}) => {
    resultEnhance = createResultEnhanceController({
      document,
      window,
      WebSocket,
      getWs: () => ws,
      getMode: () => currentMode,
      showToast,
    });
    if (pendingResultEnhanceConfig) resultEnhance.setConfig(pendingResultEnhanceConfig);
  })
  .catch(error => {
    console.error('Failed to initialize result enhance module', error);
  });
function callResultImageAction(methodName, ...args) {
  const actions = resultImageActions;
  const method = actions ? actions[methodName] : null;
  if (typeof method !== 'function') {
    showToast('Image actions are not ready', 'error');
    return undefined;
  }
  return method(...args);
}

const resultImageActionsReady = import('./js/features/resultImageActions.mjs')
  .then(({createResultImageActions}) => {
    resultImageActions = createResultImageActions({
      document,
      window,
      fetch: window.fetch.bind(window),
      showToast,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      getWs: () => ws,
      getLatestResultBlob: () => latestResultBlob,
      useNativeClipboard: () => isDesktopShell,
      getPreviewImageUrl: () => (
        preview && preview.classList.contains('show') ? (preview.getAttribute('src') || '') : ''
      ),
      getMetadataViewer: () => metadataViewer,
      getQueuePanel: () => queuePanel,
      discardPendingModuleEdit,
      openModule,
      onLoadPrompt,
      applyMetadataSettings,
      switchRightTab,
    });
    resultImageActions.bindDragSource();
  })
  .catch(error => {
    console.error('Failed to initialize result image actions module', error);
  });
const metadataViewerReady = import('./js/features/metadataViewer.mjs')
  .then(({createMetadataViewer}) => {
    metadataViewer = createMetadataViewer({
      document,
      fetch,
      escHtml,
      showToast,
      onApplyPrompt: applyMetadataPrompt,
      onApplySettings: applyMetadataSettings,
      onApplyCharacterSettings: applyMetadataCharacterSettings,
      onSendImg2Img: payload => callResultImageAction('requestMetadataImageAction', payload, 'img2img'),
      onRestoreVibeTransfer: applyMetadataVibeTransfer,
      canUseDesktopImg2Img,
      getCurrentImageUrl: () => (
        preview && preview.classList.contains('show') ? (preview.getAttribute('src') || '') : ''
      ),
    });
  })
  .catch(error => {
    console.error('Failed to initialize metadata viewer module', error);
  });
const imageActionPopupReady = import('./js/features/imageActionPopup.mjs')
  .then(({createImageActionPopup}) => {
    imageActionPopup = createImageActionPopup({
      document,
      window,
      escHtml,
      showToast,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      canUseDesktopImg2Img,
      onImg2Img: payload => callResultImageAction('requestPopupImageAction', payload, 'img2img'),
      onInpaint: payload => callResultImageAction('requestPopupImageAction', payload, 'inpaint'),
      onDanbooru: payload => callResultImageAction('requestPopupImageAction', payload, 'danbooru'),
      onVibeTransfer: payload => callResultImageAction('requestPopupImageAction', payload, 'vibe'),
      onMetadata: payload => {
        if (!metadataViewer || typeof metadataViewer.displayPayload !== 'function') {
          showToast('Metadata viewer is not ready', 'error');
          return;
        }
        metadataViewer.displayPayload(payload.metadataPayload, {
          label: payload.label,
          blob: payload.blob,
          imageUrl: payload.imageUrl,
          revokeImageUrl: payload.revokeImageUrl,
        });
        switchRightTab('pngInfo', {skipMetadataRefresh: true});
        return true;
      },
    });
    imageActionPopup.bind();
  })
  .catch(error => {
    console.error('Failed to initialize image action popup module', error);
  });
const resultImageInputReady = import('./js/features/resultImageInput.mjs')
  .then(({createResultImageInput}) => {
    resultImageInput = createResultImageInput({
      document,
      window,
      fetch,
      showImageActionPopup: payload => {
        if (imageActionPopup) imageActionPopup.open(payload);
        else showToast('Image action popup is not ready', 'error');
      },
      showToast,
      onInternalDrop: info => callResultImageAction('handleInternalImageDrop', info) || false,
    });
    resultImageInput.bind();
  })
  .catch(error => {
    console.error('Failed to initialize result image input module', error);
  });
const queuePanelReady = import('./js/features/queuePanel.mjs')
  .then(({createQueuePanelController}) => {
    queuePanel = createQueuePanelController({
      document,
      fetch,
      localStorage,
      showToast,
      escHtml,
    });
    queuePanel.init();
  })
  .catch(error => {
    console.error('Failed to initialize queue panel module', error);
  });
const resultContextMenuReady = import('./js/features/resultContextMenu.mjs')
  .then(({createResultContextMenu}) => {
    resultContextMenu = createResultContextMenu({
      document,
      window,
      fetch,
      showToast,
      escHtml,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      getCurrentSavedPath: () => resultHistory ? resultHistory.latestImagePath : '',
      onPasteImage: () => {
        if (resultImageInput) resultImageInput.pasteFromClipboard();
        else showToast('Image input is not ready', 'error');
      },
      onShowMetadata: context => callResultImageAction('showMetadataInTab', context) || false,
      onShowMetadataDetached: openMetadataDetachedFromContext,
      onImageAction: (context, action) => callResultImageAction('requestContextImageAction', context, action),
      onLoadPrompt: context => callResultImageAction('loadPromptFromContext', context),
      onRerollPrompt: context => callResultImageAction('rerollPromptFromContext', context),
      onRestoreSettings: context => callResultImageAction('restoreSettingsFromContext', context),
      onOpenLocation: context => callResultImageAction('openLocationFromContext', context),
      onSaveImage: context => callResultImageAction('saveImageFromContext', context),
      onCopyImage: (context, format) => callResultImageAction('copyImageFromContext', context, format),
      onUpscaleNai: context => callResultImageAction('upscaleFromContext', context),
      onQueueResult: (context, options) => callResultImageAction('queueResultFromContext', context, options),
      canUseDesktopImg2Img,
    });
    resultContextMenu.bind();
  })
  .catch(error => {
    console.error('Failed to initialize result context menu module', error);
  });
const promptHighlighterReady = import('./js/features/promptHighlighter.mjs')
  .then(({createPromptHighlighter}) => {
    promptHighlighter = createPromptHighlighter({
      document,
      promptEdit,
      escHtml,
    });
    if (_bootFinalized) loadPromptHighlightIndex();
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
      openModule,
      openParamsTab: () => switchTab('params'),
      setAnimaWeight: setAnimaWeightFromBadge,
      openComfyUiTools,
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
      mediaQuery: layoutMediaQuery,
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
      escHtml,
      openModule,
      setModuleParam,
      showToast,
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
      onModTextEdit,
      setModuleParam,
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
const instantWildcardPanelReady = import('./js/features/instantWildcardPanel.mjs')
  .then(({createInstantWildcardPanel}) => {
    instantWildcardPanel = createInstantWildcardPanel({
      document,
      window,
      escHtml,
      setModuleParam,
      bindTagAssist,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize instant wildcard panel module', error);
  });
const e621EventPanelReady = import('./js/features/e621EventPanel.mjs')
  .then(({createE621EventPanel}) => {
    e621EventPanel = createE621EventPanel({
      document,
      escHtml,
      setModuleParam,
      bindTagAssist,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize E621 event panel module', error);
  });
const ollamaPanelReady = import('./js/features/ollamaPanel.mjs')
  .then(({createOllamaPanel}) => {
    ollamaPanel = createOllamaPanel({
      document,
      escHtml,
      setModuleParam,
      bindTagAssist,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Ollama panel module', error);
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
const img2imgPanelReady = import('./js/features/img2imgPanel.mjs')
  .then(({createImg2ImgPanel}) => {
    img2imgPanel = createImg2ImgPanel({
      document,
      moduleBody,
      escHtml,
      setModuleParam,
      onModTextEdit,
      flushPendingModuleEdit,
      showToast,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Img2Img panel', error);
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
      isPC: layoutMediaQuery,
      relayoutFloatingPanels,
      positionTagTooltip,
      getTagTooltip,
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
      getAcTarget: getTagAssistTarget,
      showToast,
      updateModuleBtnState,
      positionFloatingPanel,
      setModuleParam,
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
const pendingOptionValues = Object.create(null);

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
  latestResultBlob = data instanceof Blob ? data : null;
  if (studioTabControl) studioTabControl.handleResultBlob(data);
  if (artistThumbControl && typeof artistThumbControl.handleResultBlob === 'function') {
    artistThumbControl.handleResultBlob(data);
  }
  preview.src = url;
  preview.dataset.source = 'current';
  preview.dataset.path = '';
  preview.classList.add('show');
  emptyMsg.style.display = 'none';
  setGen(false);
  // Stats update — init_complete 이후의 blob만 카운트
  if (_initDone) {
    if (sessionGenerationStats) sessionGenerationStats.record();
  }
}

function setBootIndicator(text, progressPct, done) {
  const el = document.getElementById('bootIndicator');
  if (!el) return;
  const txt = document.getElementById('bootIndicatorText');
  const fill = document.getElementById('bootIndicatorBarFill');
  if (txt && text != null) txt.textContent = text;
  if (fill && progressPct != null) fill.style.width = Math.max(0, Math.min(100, progressPct)) + '%';
  if (done) {
    el.classList.add('done');
    setTimeout(() => { el.classList.add('hidden'); }, 900);
  } else {
    el.classList.remove('hidden', 'done');
  }
}

// ---- Boot finalization (사용자 사용 가능 시점 동기화) ----
// 사용자 입장에서 "사용 가능"이란 검색/자동완성/태그 lookup 이 동작하는 시점.
// 이는 서버의 lazy 인덱스(KR_tags + character_analysis) warmup 이 끝나야 가능하다.
// 그래서 finalize 트리거는 서버의 명시적 "lazy_indices_ready" broadcast.
// init_complete 는 캐시 도착 단계일 뿐 — 이걸로 finalize 하지 않는다.
let _bootFinalized = false;
let _bootSafetyTimer = null;
let _bootProgressTimer = null;
let _bootProgressPct = 75;
const BOOT_SAFETY_MS = 30000;  // lazy warmup 누락/실패 대비 절대 안전망 (인덱스 빌드 ~수초)

function _clearBootTimers() {
  if (_bootSafetyTimer) { clearTimeout(_bootSafetyTimer); _bootSafetyTimer = null; }
  if (_bootProgressTimer) { clearInterval(_bootProgressTimer); _bootProgressTimer = null; }
}

function finalizeBoot() {
  if (_bootFinalized) return;
  _bootFinalized = true;
  _clearBootTimers();
  setBootIndicator('Ready', 100, true);
}

function _startBootProgressAnimator() {
  // init_complete ~ lazy_indices_ready 사이에 점진적 진행률 애니메이션 (75% → 95% 캡)
  // 사용자에게 정지된 듯한 인상 방지. 실제 finalize 는 lazy_indices_ready 만이 트리거.
  if (_bootProgressTimer) clearInterval(_bootProgressTimer);
  _bootProgressPct = 75;
  setBootIndicator('Building tag indices…', _bootProgressPct, false);
  _bootProgressTimer = setInterval(() => {
    if (_bootFinalized) {
      clearInterval(_bootProgressTimer);
      _bootProgressTimer = null;
      return;
    }
    if (_bootProgressPct < 95) {
      _bootProgressPct += 1;
      setBootIndicator(null, _bootProgressPct, false);
    }
  }, 250);
}

function resetBootIndicatorState() {
  _bootFinalized = false;
  _bootProgressPct = 75;
  _clearBootTimers();
}

async function loadPromptHighlightIndex() {
  if (promptHighlightIndexPromise) return promptHighlightIndexPromise;
  promptHighlightIndexPromise = (async () => {
    try {
      await promptHighlighterReady;
      if (!promptHighlighter) return;
      const response = await fetch('/api/prompt-highlight-index', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const index = await response.json();
      promptHighlighter.setTagClassificationIndex(index);
      if (index?.stats) console.info('Prompt highlight index loaded', index.stats);
    } catch (error) {
      promptHighlightIndexPromise = null;
      console.warn('Failed to load prompt highlight index', error);
    }
  })();
  return promptHighlightIndexPromise;
}

function onLazyIndicesReady() {
  finalizeBoot();
  loadPromptHighlightIndex();
}

function onInitComplete() {
  _initDone = true;
  // 캐시 리플레이 도착 — 아직 사용 가능 단계 아님.
  // lazy 인덱스 warmup 완료 broadcast 가 와야 finalize.
  resetBootIndicatorState();
  _startBootProgressAnimator();
  // 절대 안전망 — broadcast 누락/예외 시에도 indicator 가 영원히 회전하지 않도록
  _bootSafetyTimer = setTimeout(finalizeBoot, BOOT_SAFETY_MS);
  // 재연결 시 열려있는 모듈 자동 리프레시 (캐시 fallback 적용 위해)
  if (currentModuleId && !isModuleStateGuarded(currentModuleId)) {
    requestModuleState(currentModuleId);
  }
  if (resultHistory) resultHistory.prepareInitialHistory();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'get_search_state'}));
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
  image_meta: updateMeta,
  status: m => setGen(m.is_generating),
  prompt_generated: updatePromptOnly,
  random_failed: onRandomFailed,
  prompt_sync: syncPrompts,
  prompt_tokens: applyPromptTokenPayload,
  options: syncOptions,
  params: updateParams,
  mode: m => syncMode(m.mode),
  result_enhance_state: m => { if (resultEnhance) resultEnhance.handleState(m); },
  result_enhance_config: m => {
    pendingResultEnhanceConfig = m;
    if (resultEnhance) resultEnhance.setConfig(m);
  },
  queue_state: m => { if (queuePanel) queuePanel.handleState(m); },
  comfyui_workflow_state: onComfyUiWorkflowState,
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
  lazy_indices_ready: onLazyIndicesReady,
};

const remoteWsClientReady = import('./js/core/remoteWsClient.mjs')
  .then(({createRemoteWsClient}) => {
    wsClient = createRemoteWsClient({
      window,
      location,
      WebSocket,
      BlobClass: Blob,
      handlers: wsMessageHandlers,
      onBlob: handleWsBlob,
      afterJson: afterWsJsonMessage,
      onMessageError: onWsMessageError,
      onSocketChange: socket => { ws = socket; },
      onOpen: socket => {
        _initDone = false;
        setBootIndicator('Loading state…', 60, false);
        if (setupController) setupController.resetInitialProbe();
        setLauncherConn(true);
        socket.send(JSON.stringify({type: 'get_search_state'}));
        // probe 는 api_status 첫 수신 시점에 1회 실행 (updateApiStatus 내부에서 트리거).
      },
      onClose: () => {
        // 재연결 사이클을 위해 boot finalize 상태 리셋 (다음 init_complete 가 다시 시퀀스 시작)
        resetBootIndicatorState();
        setBootIndicator('Reconnecting…', 20, false);
        setLauncherConn(false);
        modeSwitching = false;
        if (modeSelect) modeSelect.disabled = true;
        if (desktopWindowControl) desktopWindowControl.disable();
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize remote WebSocket client', error);
    throw error;
  });

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
  if (artistThumbControl && typeof artistThumbControl.handleResultMeta === 'function') {
    artistThumbControl.handleResultMeta(m);
  }
  if (resultEnhance) {
    resultEnhanceAssetRequestId += 1;
    resultEnhance.setCurrentMeta({
      ...m,
      source: 'current',
      path: '',
      can_enhance: !!m.can_enhance,
    });
  }
}

function enhanceMetaFromAsset(asset, fallback = {}) {
  const capabilities = asset?.capabilities || {};
  return {
    source: asset?.source || fallback.source || '',
    path: asset?.path ?? fallback.path ?? '',
    file_path: asset?.file_path ?? asset?.filePath ?? fallback.file_path ?? fallback.filePath ?? '',
    label: asset?.label ?? fallback.label ?? '',
    width: asset?.width ?? fallback.width,
    height: asset?.height ?? fallback.height,
    can_enhance: Boolean(asset?.can_enhance ?? asset?.canEnhance ?? capabilities.enhance ?? fallback.can_enhance ?? fallback.canEnhance),
  };
}

async function updateResultEnhanceForSavedPath(relPath = '') {
  if (!resultEnhance) return;
  const path = String(relPath || '');
  const requestId = ++resultEnhanceAssetRequestId;
  if (!path) {
    resultEnhance.clearCurrentMeta();
    return;
  }

  resultEnhance.setCurrentMeta(enhanceMetaFromAsset(null, {
    source: 'saved',
    path,
    can_enhance: false,
  }));

  try {
    const response = await fetch('/api/result/asset/saved?path=' + encodeURIComponent(path), {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const asset = await response.json();
    if (requestId !== resultEnhanceAssetRequestId || !resultEnhance) return;
    resultEnhance.setCurrentMeta(enhanceMetaFromAsset(asset, {
      source: 'saved',
      path,
    }));
  } catch (error) {
    console.warn('Failed to resolve saved result Enhance state', error);
    if (requestId === resultEnhanceAssetRequestId && resultEnhance) {
      resultEnhance.setCurrentMeta(enhanceMetaFromAsset(null, {
        source: 'saved',
        path,
        can_enhance: false,
      }));
    }
  }
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
  const fixed = getOptionChecked('prompt_fixed');
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
  const previous = el.value;
  if (options && options.length) {
    const existing = Array.from(el.options).map(o => o.value);
    if (existing.length !== options.length || existing.some((v, i) => v !== options[i])) {
      el.innerHTML = options.map(o => `<option value="${o}">${o}</option>`).join('');
    }
  }
  if (current !== undefined) el.value = current;
  else if (previous && Array.from(el.options).some(option => option.value === previous)) el.value = previous;
}

function normalizeComfyUiWorkflowState(m = {}) {
  const state = m.comfyui_workflow && typeof m.comfyui_workflow === 'object'
    ? m.comfyui_workflow
    : m;
  const hasCustom = 'has_custom' in state
    ? Boolean(state.has_custom)
    : Boolean(m.comfyui_workflow_has_custom);
  return {
    has_custom: hasCustom,
    workflow_label: state.workflow_label || m.comfyui_workflow_label || (hasCustom ? 'Custom Workflow' : 'Basic Workflow'),
    model_compat: state.model_compat || null,
    locked_loader_class: state.locked_loader_class || null,
    locked_model_display: state.locked_model_display || null,
  };
}

function onComfyUiWorkflowState(m) {
  comfyuiWorkflowState = normalizeComfyUiWorkflowState(m);
  if (moduleBadges) moduleBadges.updateComfyUiWorkflowState(comfyuiWorkflowState);
  if (moduleLauncherControl) moduleLauncherControl.updateState();
}

function updateParams(m) {
  const schemaOnly = !!m.schema_only;
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
  const currentFlagState = key => {
    const existing = paramFlags.querySelector(`[data-key="${key}"]`);
    if (existing) return existing.classList.contains('on');
    if (key === 'random_resolution') return qRndRes.classList.contains('on');
    if (key === 'auto_fit_resolution') return qAutoRes.classList.contains('on');
    return false;
  };
  const incomingFlagState = key => schemaOnly ? currentFlagState(key) : !!m[key];
  if (mode === 'NAI') {
    for (const key of ['SMEA', 'DYN', 'VAR+', 'DECRISP']) {
      if (schemaOnly || key in m) flags.push({key, name: key, on: incomingFlagState(key), enabled: naiFlagsEnabled[key] !== false});
    }
  }
  if (schemaOnly || 'seed_fixed' in m) flags.push({key: 'seed_fixed', name: 'Seed Fix', on: incomingFlagState('seed_fixed'), enabled: true});
  if (schemaOnly || 'random_resolution' in m) flags.push({key: 'random_resolution', name: 'Rnd Res', on: incomingFlagState('random_resolution'), enabled: true});
  if (schemaOnly || 'auto_fit_resolution' in m) flags.push({key: 'auto_fit_resolution', name: 'Auto Res', on: incomingFlagState('auto_fit_resolution'), enabled: true});
  paramFlags.innerHTML = flags.map(f =>
    `<span class="param-flag${f.on ? ' on' : ''}${f.enabled ? '' : ' disabled'}" data-key="${f.key}" onclick="${f.enabled ? 'toggleFlag(this)' : ''}">${f.name}</span>`
  ).join('');
  // Quick flags 동기화
  if ('random_resolution' in m) qRndRes.classList.toggle('on', m.random_resolution);
  else if (schemaOnly) qRndRes.classList.toggle('on', incomingFlagState('random_resolution'));
  if ('auto_fit_resolution' in m) qAutoRes.classList.toggle('on', m.auto_fit_resolution);
  else if (schemaOnly) qAutoRes.classList.toggle('on', incomingFlagState('auto_fit_resolution'));

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
    $('comfyuiAnimaWeightRow').style.display = sm === 'anima' ? '' : 'none';
    if ('rescale_cfg' in m) $('pRescaleCfg').value = m.rescale_cfg;
    if ('anima_weight' in m) $('pAnimaWeight').value = m.anima_weight;
  }
  if ('comfyui_workflow' in m || 'comfyui_workflow_has_custom' in m) onComfyUiWorkflowState(m);
  if (moduleBadges) moduleBadges.updateComfyUiParams(m);
  if (studioTabControl) studioTabControl.onParamsChanged();
  updateModuleHeaderAction(currentModuleId);
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
}

function setAnimaWeightFromBadge(value) {
  const input = $('pAnimaWeight');
  if (input) input.value = value;
  setParam('anima_weight', value);
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
  $('comfyuiAnimaWeightRow').style.display = mode === 'anima' ? '' : 'none';
  setParam('sampling_mode', mode);
  updateModuleHeaderAction(currentModuleId);
}

function getComfyUiWorkflowFileInput() {
  if (comfyuiWorkflowFileInput) return comfyuiWorkflowFileInput;
  comfyuiWorkflowFileInput = document.createElement('input');
  comfyuiWorkflowFileInput.type = 'file';
  comfyuiWorkflowFileInput.accept = 'image/png,.png';
  comfyuiWorkflowFileInput.hidden = true;
  comfyuiWorkflowFileInput.addEventListener('change', () => {
    const file = comfyuiWorkflowFileInput.files && comfyuiWorkflowFileInput.files[0];
    comfyuiWorkflowFileInput.value = '';
    if (file) uploadComfyUiWorkflowFile(file);
  });
  document.body.append(comfyuiWorkflowFileInput);
  return comfyuiWorkflowFileInput;
}

async function readJsonResponse(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

function applyComfyUiWorkflowResponse(data) {
  if (data?.workflow) onComfyUiWorkflowState(data.workflow);
  if (data?.params && Object.keys(data.params).length) updateParams(data.params);
}

function uploadComfyUiWorkflow() {
  if ((currentMode || modeSelect.value) !== 'COMFYUI') {
    showToast('ComfyUI mode is required', 'error');
    return;
  }
  getComfyUiWorkflowFileInput().click();
}

async function uploadComfyUiWorkflowFile(file) {
  if (!file) return;
  const isPng = file.type === 'image/png' || /\.png$/i.test(file.name || '');
  if (!isPng) {
    showToast('PNG workflow image is required', 'error');
    return;
  }
  try {
    const response = await fetch('/api/comfyui/workflow/upload', {
      method: 'POST',
      headers: {'Content-Type': file.type || 'image/png'},
      body: file,
    });
    const data = await readJsonResponse(response);
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || 'Workflow upload failed');
    }
    applyComfyUiWorkflowResponse(data);
    showToast('Custom Workflow enabled', 'success');
  } catch (error) {
    showToast(error?.message || 'Workflow upload failed', 'error');
  }
}

async function switchComfyUiWorkflowDefault() {
  if ((currentMode || modeSelect.value) !== 'COMFYUI') {
    showToast('ComfyUI mode is required', 'error');
    return;
  }
  try {
    const response = await fetch('/api/comfyui/workflow/default', {method: 'POST'});
    const data = await readJsonResponse(response);
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || 'Workflow switch failed');
    }
    applyComfyUiWorkflowResponse(data);
    showToast('Basic Workflow enabled', 'success');
  } catch (error) {
    showToast(error?.message || 'Workflow switch failed', 'error');
  }
}

function openComfyUiWeb() {
  if ((currentMode || modeSelect.value) !== 'COMFYUI') {
    showToast('ComfyUI mode is required', 'error');
    return;
  }
  const apiStatus = setupController ? setupController.getApiStatus() : null;
  if (apiStatus && !apiStatus.comfyui_url) {
    showToast('ComfyUI URL is not configured', 'error', true);
    return;
  }
  if (!openUrlInSystemBrowser('/api/comfyui/web')) {
    showToast('Popup blocked by browser', 'error');
  }
}

function openComfyUiTools() {
  if (moduleLauncherControl && typeof moduleLauncherControl.openCategory === 'function') {
    moduleLauncherControl.openCategory('comfyui_tools');
  }
}

// ---- Prompt sync ----

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
  }, 500);
}

function applyPromptText(prompt) {
  if (promptSendTimer) {
    clearTimeout(promptSendTimer);
    promptSendTimer = null;
  }
  syncingPrompt = true;
  promptEdit.value = String(prompt || '');
  syncingPrompt = false;
  _localPromptDirty = false;
  updatePromptHighlight();
  applyPromptHighlightState();
  updatePromptTokenEstimate();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'set_prompt',
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    }));
  }
}

function applyPromptFields(prompt, negative) {
  if (promptSendTimer) {
    clearTimeout(promptSendTimer);
    promptSendTimer = null;
  }
  syncingPrompt = true;
  promptEdit.value = String(prompt || '');
  negEdit.value = String(negative || '');
  syncingPrompt = false;
  _localPromptDirty = false;
  deferredPromptSync = null;
  updatePromptHighlight();
  applyPromptHighlightState();
  updatePromptTokenEstimate();
  updateNegativeTokenEstimate();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'set_prompt',
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    }));
  }
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

const DETACHED_MODULE_GEOMETRY = {
  prompt_engineering: {width: 640, height: 860},
  character: {width: 760, height: 860},
  conditional_prompt: {width: 1560, height: 900},
  wildcard: {width: 680, height: 780},
  instant_wildcard: {width: 680, height: 780},
  chunk: {width: 620, height: 700},
  search: {width: 680, height: 760},
  auto_save: {width: 620, height: 680},
  save_directory: {width: 620, height: 680},
  automation: {width: 760, height: 760},
  character_reference: {width: 900, height: 780},
  vibe_transfer: {width: 900, height: 780},
  img2img: {width: 1080, height: 860},
  e621_event: {width: 1120, height: 820},
  ollama: {width: 760, height: 780},
};
const DEFAULT_DETACHED_MODULE_GEOMETRY = {width: 720, height: 760};
const DETACHED_METADATA_GEOMETRY = {width: 1040, height: 820};

function detachedWindowFeatures({width, height}, {scrollbars = 'no'} = {}) {
  return `popup=yes,width=${width},height=${height},resizable=yes,scrollbars=${scrollbars}`;
}

function getDetachedModuleGeometry(moduleId) {
  return DETACHED_MODULE_GEOMETRY[moduleId] || DEFAULT_DETACHED_MODULE_GEOMETRY;
}

function switchRightTab(tabName, options = {}) {
  const activeTab = rightTabs ? rightTabs.switchTo(tabName) : tabName;
  if (tabName === 'pngInfo' && metadataViewer && !options.skipMetadataRefresh) metadataViewer.refresh();
  if (activeTab === 'thumb' && thumbTabControl) thumbTabControl.load();
  if (activeTab === 'artists' && artistThumbControl) artistThumbControl.load();
}

function buildDetachedUrl(kind, params = {}) {
  const url = new URL(location.href);
  url.searchParams.set('detached', kind);
  url.searchParams.delete('module');
  url.searchParams.delete('metadata_path');
  url.searchParams.delete('path');
  url.searchParams.delete('source');
  url.searchParams.delete('standalone');
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

function openDetachedWindow(url, name, features) {
  const popup = window.open(url, name, features);
  if (!popup) {
    showToast('Popup blocked by browser', 'error');
    return null;
  }
  popup.focus?.();
  return popup;
}

function isLivePopup(popup) {
  try {
    return !!popup && !popup.closed;
  } catch (_) {
    return false;
  }
}

function openDetachedModule(moduleId, options = {}) {
  if (!moduleId) return null;
  const snapshotToken = options.skipSnapshot ? '' : saveDetachedModuleSnapshot(moduleId);
  const params = {module: moduleId};
  if (snapshotToken) params.snapshot = snapshotToken;
  if (options.standalone) params.standalone = '1';
  return openDetachedWindow(
    buildDetachedUrl('module', params),
    options.windowName || `naia-module-${moduleId}-${Date.now()}`,
    detachedWindowFeatures(getDetachedModuleGeometry(moduleId))
  );
}

function openImg2ImgSessionSurface() {
  if (isDesktopLayout() && !isDetachedModule) {
    if (isLivePopup(img2imgSessionPopup)) {
      img2imgSessionPopup.focus?.();
      return true;
    }
    const popup = openDetachedModule('img2img', {
      standalone: true,
      skipSnapshot: true,
      windowName: 'naia-img2img-session',
    });
    if (popup) {
      img2imgSessionPopup = popup;
      if (currentModuleId === 'img2img' && modulePopup.classList.contains('open')) closeModule();
      return true;
    }
  }
  openModule('img2img', {forceOpen: true});
  return true;
}

function detachCurrentModule() {
  if (!currentModuleId) {
    showToast('No module is open', 'error');
    return;
  }
  if (isDetachedModule) {
    attachCurrentModule();
    return;
  }
  flushCurrentModuleEditsForDetach();
  const popup = openDetachedModule(currentModuleId);
  if (popup) closeModule();
}

function flushCurrentModuleEditsForDetach() {
  if (currentModuleId === 'prompt_engineering') {
    flushPromptEngineeringEdits();
  } else if (currentModuleId === 'character') {
    flushCharacterEdits();
  } else {
    flushPendingModuleEdit(currentModuleId);
  }
}

function saveDetachedModuleSnapshot(moduleId) {
  const state = collectModuleSnapshotState(moduleId);
  if (!state) return '';
  const token = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    localStorage.setItem(
      DETACHED_MODULE_SNAPSHOT_PREFIX + token,
      JSON.stringify({moduleId, state, createdAt: Date.now()}),
    );
    return token;
  } catch (error) {
    console.warn('Failed to save detached module snapshot', error);
    return '';
  }
}

function cloneModuleState(state) {
  if (!state) return null;
  try {
    return typeof structuredClone === 'function'
      ? structuredClone(state)
      : JSON.parse(JSON.stringify(state));
  } catch (_) {
    try { return JSON.parse(JSON.stringify(state)); } catch (error) {
      console.warn('Failed to clone module state snapshot', error);
      return null;
    }
  }
}

function collectModuleSnapshotState(moduleId) {
  const state = cloneModuleState(moduleStateCache.get(moduleId));
  if (!state) return null;

  if (moduleId === 'prompt_engineering') {
    const pre = document.getElementById('modPrePrompt');
    const post = document.getElementById('modPostPrompt');
    const autoHide = document.getElementById('modAutoHide');
    if (pre) state.pre_prompt = pre.value;
    if (post) state.post_prompt = post.value;
    if (autoHide) state.auto_hide = autoHide.value;
  } else if (moduleId === 'character' && Array.isArray(state.characters)) {
    document.querySelectorAll('[data-char-index]').forEach(block => {
      const idx = Number(block.dataset.charIndex);
      const character = state.characters[idx];
      if (!character) return;
      const prompt = block.querySelector('.mod-char-prompt');
      const uc = block.querySelector('.mod-char-uc');
      if (prompt) character.prompt = prompt.value;
      if (uc) character.uc = uc.value;
    });
  } else if (moduleId === 'conditional_prompt') {
    if (conditionalPromptPanel && typeof conditionalPromptPanel.collectState === 'function') {
      return conditionalPromptPanel.collectState(state);
    }
    const mode = document.getElementById('condEditorMode');
    const rules = document.getElementById('condRulesInput');
    if (mode) state.editor_mode = mode.value === 'v2' ? 'v2' : 'legacy';
    if (rules) {
      const key = rules.dataset.condRuleKey || 'rules';
      state[key] = rules.value;
      if ((state.editor_mode || '') === 'v2') {
        state.rules_v2 = rules.value;
      } else {
        state.rules_legacy = rules.value;
      }
      state.rules = rules.value;
      state.active_rules = rules.value;
    }
    const maxPasses = document.getElementById('condMaxPasses');
    const stopOnMatch = document.getElementById('condStopOnMatch');
    if (maxPasses || stopOnMatch) {
      const currentOptions = state.engine_options && typeof state.engine_options === 'object'
        ? state.engine_options
        : {};
      state.engine_options = {
        max_passes: maxPasses ? Math.max(1, Math.round(Number(maxPasses.value) || 1)) : (currentOptions.max_passes || 1),
        stop_on_match: stopOnMatch ? !!stopOnMatch.checked : !!currentOptions.stop_on_match,
      };
    }
  } else if (moduleId === 'e621_event') {
    const search = document.getElementById('e621SearchInput');
    const testbench = document.getElementById('e621Testbench');
    if (search) state.search_text = search.value;
    if (testbench) state.testbench = testbench.value;
  } else if (moduleId === 'img2img') {
    const mainPrompt = document.getElementById('img2imgMainPrompt');
    const negativePrompt = document.getElementById('img2imgNegativePrompt');
    if (mainPrompt) state.main_prompt = mainPrompt.value;
    if (negativePrompt) state.negative_prompt = negativePrompt.value;
    if (Array.isArray(state.characters)) {
      document.querySelectorAll('[data-img2img-char-index]').forEach(block => {
        const idx = Number(block.dataset.img2imgCharIndex);
        const character = state.characters[idx];
        if (!character) return;
        const prompt = block.querySelector('.mod-char-prompt');
        const uc = block.querySelector('.mod-char-uc');
        const active = block.querySelector('input[type="checkbox"]');
        if (prompt) character.prompt = prompt.value;
        if (uc) character.uc = uc.value;
        if (active) character.active = !!active.checked;
      });
    }
  }

  return state;
}

function takeDetachedModuleSnapshot(moduleId) {
  if (!detachedSnapshotToken) return null;
  const key = DETACHED_MODULE_SNAPSHOT_PREFIX + detachedSnapshotToken;
  try {
    const raw = localStorage.getItem(key);
    localStorage.removeItem(key);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    if (!payload || payload.moduleId !== moduleId || !payload.state) return null;
    return payload.state;
  } catch (error) {
    console.warn('Failed to read detached module snapshot', error);
    return null;
  }
}

function currentModuleTransferState(moduleId) {
  if (currentModuleId === moduleId) {
    flushCurrentModuleEditsForDetach();
  } else {
    flushPendingModuleEdit(moduleId);
  }
  const state = collectModuleSnapshotState(moduleId) || moduleStateCache.get(moduleId) || null;
  if (state && state.module_id === moduleId) moduleStateCache.set(moduleId, state);
  return state;
}

function postAttachModuleRequest(moduleId, options = {}) {
  if (!window.opener || window.opener.closed) return false;
  window.opener.postMessage({
    type: 'naia_attach_module',
    moduleId,
    state: currentModuleTransferState(moduleId),
  }, window.location.origin);
  if (options.markPosted !== false) detachedAttachPosted = true;
  return true;
}

function attachCurrentModule() {
  const moduleId = currentModuleId || detachedModuleId;
  if (!moduleId) {
    showToast('No module is open', 'error');
    return;
  }
  if (!postAttachModuleRequest(moduleId)) {
    showToast('Main window is unavailable', 'error');
    return;
  }
  window.close();
}

function handleDetachedMessage(event) {
  if (event.origin !== window.location.origin) return;
  const data = event.data || {};
  if (data.type !== 'naia_attach_module' || !data.moduleId) return;
  const moduleId = String(data.moduleId);
  const transferredState = (data.state && data.state.module_id === moduleId) ? data.state : null;
  if (!(currentModuleId === moduleId && modulePopup.classList.contains('open'))) {
    openModule(moduleId, {
      initialState: transferredState,
      skipStateRequest: !!transferredState,
      guardInitialState: !!transferredState,
    });
  } else if (transferredState) {
    moduleStateCache.set(moduleId, transferredState);
    renderModuleState(transferredState);
    guardTransferredModuleState(moduleId);
  }
  window.focus?.();
}

function handleDetachedBeforeUnload() {
  if (!isDetachedModule || detachedAttachPosted || detachedStandalone) return;
  const moduleId = currentModuleId || detachedModuleId;
  if (moduleId) postAttachModuleRequest(moduleId, {markPosted: true});
}

window.addEventListener('message', handleDetachedMessage);
window.addEventListener('beforeunload', handleDetachedBeforeUnload);

function guardTransferredModuleState(moduleId, delayMs = 900) {
  if (!moduleId) return;
  if (transferredModuleStateGuard.timer) {
    clearTimeout(transferredModuleStateGuard.timer);
    transferredModuleStateGuard.timer = null;
  }
  transferredModuleStateGuard.moduleId = moduleId;
  transferredModuleStateGuard.until = Date.now() + delayMs;
  transferredModuleStateGuard.timer = setTimeout(() => {
    if (currentModuleId === moduleId) requestModuleState(moduleId);
    if (transferredModuleStateGuard.moduleId === moduleId) {
      transferredModuleStateGuard = {moduleId: '', until: 0, timer: null};
    }
  }, delayMs);
}

function isModuleStateGuarded(moduleId) {
  return !!moduleId
    && transferredModuleStateGuard.moduleId === moduleId
    && Date.now() < transferredModuleStateGuard.until;
}

function openMetadataDetachedFromContext(context = {}) {
  const path = context.path || '';
  const source = context.source || '';
  const params = path
    ? {metadata_path: path}
    : {source: source === 'current' ? 'current' : 'current'};
  return openDetachedWindow(
    buildDetachedUrl('metadata', params),
    `naia-metadata-${Date.now()}`,
    detachedWindowFeatures(DETACHED_METADATA_GEOMETRY, {scrollbars: 'yes'})
  );
}

function detachMetadataViewer() {
  const source = metadataViewer?.getCurrentSource?.() || {};
  if (source.kind === 'saved' && source.path) {
    openMetadataDetachedFromContext({path: source.path, source: 'saved'});
    return;
  }
  if (source.kind === 'current') {
    openMetadataDetachedFromContext({source: 'current'});
    return;
  }
  showToast('Only saved/current result metadata can be detached', 'error');
}

function initializeDetachedShell() {
  if (!isDetachedShell) return;
  if (isDetachedModule) {
    document.title = `NAIA Module - ${detachedModuleId || 'Detached'}`;
    if (detachedModuleId) {
      const snapshot = takeDetachedModuleSnapshot(detachedModuleId);
      openModule(detachedModuleId, {
        initialState: snapshot,
        skipStateRequest: !!snapshot,
        guardInitialState: !!snapshot,
      });
    }
    return;
  }
  if (isDetachedMetadata) {
    document.title = 'NAIA Metadata';
    switchRightTab('pngInfo', {skipMetadataRefresh: true});
    if (detachedMetadataPath) {
      metadataViewer?.loadSaved(detachedMetadataPath, {silent: false});
    } else if (detachedMetadataSource === 'current' || !detachedMetadataSource) {
      metadataViewer?.loadCurrent({silent: false});
    } else {
      showToast('Unsupported detached metadata source', 'error');
    }
  }
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
function requestResultEnhance() { if (resultEnhance) resultEnhance.request(); }
function refreshMetadataViewer() { if (metadataViewer) metadataViewer.refresh(); }

function loadMetadataImageBlob(blob, label = 'Input Image') {
  if (!metadataViewer || typeof metadataViewer.loadImageBlob !== 'function') {
    showToast('Metadata viewer is not ready', 'error');
    return Promise.resolve(false);
  }
  return metadataViewer.loadImageBlob(blob, label || 'Input Image', {silent: false});
}

function pasteMetadataImageFromClipboard() {
  if (!resultImageInput || typeof resultImageInput.pasteFromClipboard !== 'function') {
    showToast('Image input is not ready', 'error');
    return;
  }
  resultImageInput.pasteFromClipboard({
    label: 'Clipboard Image',
    onImageBlob: loadMetadataImageBlob,
  });
}

function bindMetadataImageDropTarget() {
  if (!resultImageInput || typeof resultImageInput.bindDropTarget !== 'function') return;
  const stage = document.querySelector('.metadata-image-stage');
  if (!stage) return;
  resultImageInput.bindDropTarget(stage, {
    onImageBlob: loadMetadataImageBlob,
  });
}

function applyMetadataPrompt(payload) {
  if (!payload) return;
  if (promptEdit && payload.prompt != null) promptEdit.value = payload.prompt || '';
  if (negEdit && payload.negative != null) negEdit.value = payload.negative || '';
  if (promptSendTimer) {
    clearTimeout(promptSendTimer);
    promptSendTimer = null;
  }
  _localPromptDirty = false;
  updatePromptHighlight();
  updatePromptTokenEstimate();
  updateNegativeTokenEstimate();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'set_prompt',
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    }));
  }
  showToast('Prompt applied from metadata', 'success');
}

function ensureSelectValue(selectEl, value) {
  if (!selectEl || selectEl.tagName !== 'SELECT') return;
  const text = String(value);
  const exists = Array.from(selectEl.options || []).some(option => option.value === text);
  if (!exists) {
    const option = document.createElement('option');
    option.value = text;
    option.textContent = text;
    selectEl.appendChild(option);
  }
}

function applyMetadataParamValue(key, value) {
  if (value === undefined || value === null || value === '') return false;
  const text = String(value);
  const target = paramEls ? paramEls[key] : null;
  if (target) {
    ensureSelectValue(target, text);
    target.value = text;
  }
  if (key === 'resolution' && qResolution) {
    ensureSelectValue(qResolution, text);
    qResolution.value = text;
  }
  setParam(key, text);
  return true;
}

function normalizeMetadataBoolean(value) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  const text = String(value ?? '').trim().toLowerCase();
  return !['', '0', 'false', 'none', 'null', 'undefined'].includes(text);
}

function applyMetadataFlag(key, value) {
  if (value === undefined || value === null || value === '') return false;
  const enabled = normalizeMetadataBoolean(value);
  const flag = paramFlags ? paramFlags.querySelector(`[data-key="${CSS.escape(key)}"]`) : null;
  if (flag) flag.classList.toggle('on', enabled);
  setParam(key, String(enabled));
  return true;
}

function applyMetadataSettings(payload, options = {}) {
  const params = payload && payload.params ? payload.params : {};
  let applied = 0;
  [
    ['resolution', params.resolution],
    ['steps', params.steps],
    ['cfg_scale', params.cfg_scale],
    ['cfg_rescale', params.cfg_rescale],
    ['seed', params.seed],
    ['sampler', params.sampler],
    ['scheduler', params.scheduler],
    ['model', params.model],
  ].forEach(([key, value]) => {
    if (applyMetadataParamValue(key, value)) applied += 1;
  });
  [
    ['SMEA', params.sm],
    ['DYN', params.sm_dyn],
    ['VAR+', params['VAR+']],
  ].forEach(([key, value]) => {
    if (applyMetadataFlag(key, value)) applied += 1;
  });
  if (applied > 0) {
    if (!options.silent) showToast('Settings applied from metadata', 'success');
  } else if (!options.silent) {
    showToast('No applicable settings in metadata', 'error');
  }
  return applied;
}

function applyMetadataCharacterSettings(payload) {
  if ((currentMode || modeSelect.value) !== 'NAI') {
    showToast('Character prompts are only available in NAI mode', 'error');
    return;
  }
  const characters = Array.isArray(payload?.characters) ? payload.characters : [];
  const charactersUc = Array.isArray(payload?.charactersUc) ? payload.charactersUc : [];
  const validCharacters = characters
    .map(character => String(character ?? '').trim())
    .filter(Boolean);
  if (!validCharacters.length) {
    showToast('No character prompts in metadata', 'error');
    return;
  }
  applyMetadataSettings(payload, {silent: true});
  if (currentModuleId !== 'character') {
    openModule('character');
  }
  setModuleParam('character', 'bulk_characters', JSON.stringify({
    characters,
    characters_uc: charactersUc,
  }));
  showToast(`Applied ${validCharacters.length} character prompts from metadata`, 'success');
}

function applyMetadataVibeTransfer(payload) {
  if ((currentMode || modeSelect.value) !== 'NAI') {
    showToast('Vibe Transfer is only available in NAI mode', 'error');
    return;
  }
  const vibeTransfer = payload?.vibeTransfer;
  if (!vibeTransfer || !Array.isArray(vibeTransfer.reference_image_multiple) || !vibeTransfer.reference_image_multiple.length) {
    showToast('No Vibe Transfer data in metadata', 'error');
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('Remote connection is not open', 'error');
    return;
  }
  if (currentModuleId !== 'vibe_transfer') {
    openModule('vibe_transfer');
  }
  setModuleParam('vibe_transfer', 'restore_metadata', JSON.stringify(vibeTransfer));
  showToast(`Vibe Transfer restore requested (${vibeTransfer.reference_image_multiple.length})`, 'success');
}
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
  const autoGenCb = optBoxes.auto_generate;
  const naiOpt = modeSelect.querySelector('option[value="NAI"]');
  if (autoGenCb) { autoGenCb.disabled = false; autoGenCb.style.opacity = ''; }
  if (statsSave) { statsSave.style.pointerEvents = ''; statsSave.style.opacity = ''; }
  modeSelect.disabled = false;
  if (setupLauncherBtn) setupLauncherBtn.style.display = '';
  if (naiOpt) naiOpt.disabled = false;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'get_search_state'}));
  }
  updateModeSelectAvailability();
}

function onDesktopWindowState(m) {
  if (desktopWindowControl) desktopWindowControl.onState(m);
}

function toggleDesktopWindow() {
  if (desktopWindowControl) desktopWindowControl.toggle();
}

// ---- Drawer & Tabs ----
const isPC = window.matchMedia('(min-width: 768px)');
const layoutMediaQuery = isDetachedShell ? detachedDesktopMediaQuery : isPC;
const isDesktopLayout = () => isDetachedShell || isPC.matches;
function canUseDesktopImg2Img() {
  const coarsePointer = Boolean(window.matchMedia?.('(hover: none), (pointer: coarse)')?.matches);
  return isDesktopLayout() && !coarsePointer;
}

function toggleDrawer() {
  if (promptDrawerControl) promptDrawerControl.toggle();
}

function switchTab(name) {
  if (promptDrawerControl) promptDrawerControl.switchTab(name);
}

// ---- Controls ----
function requestGenerate(payload = {}) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  if (generating) return false;
  if (promptSendTimer) { clearTimeout(promptSendTimer); promptSendTimer = null; }
  _localPromptDirty = false;
  const message = {type: 'generate', ...(payload && typeof payload === 'object' ? payload : {})};
  ws.send(JSON.stringify(message));
  return true;
}

function send(cmd) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (cmd === 'generate') {
    requestGenerate({
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    });
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
    ws.send(JSON.stringify({type: 'random', ratings: getActiveRatings()}));
    return;
  }
  ws.send(cmd);
}

function setGen(v) {
  generating = v;
  if (studioTabControl) studioTabControl.handleGenerationStatus(v);
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
function getOptionChecked(key) {
  const control = optBoxes[key];
  return !!(control && control.dataset.checked === 'true');
}

function applyOptionState(key, value, options = {}) {
  const control = optBoxes[key];
  if (!control) return false;
  const next = !!value;
  const clearPending = options.clearPending !== false;
  control.dataset.checked = next ? 'true' : 'false';
  control.classList.toggle('is-on', next);
  if (clearPending) {
    delete pendingOptionValues[key];
    control.classList.remove('is-pending');
  }
  control.setAttribute('aria-pressed', next ? 'true' : 'false');

  if (key === 'prompt_fixed') {
    btnRnd.disabled = next;
    btnRnd.style.opacity = next ? '0.4' : '';
  }
  if (key === 'prompt_fixed' || key === 'wildcard_standalone') {
    syncRatingBarVisibility();
  }
  return true;
}

function markOptionPending(key, pending) {
  const control = optBoxes[key];
  if (pending) pendingOptionValues[key] = getOptionChecked(key);
  else delete pendingOptionValues[key];
  if (control) control.classList.toggle('is-pending', !!pending);
}

function hasPendingOption(key) {
  return Object.prototype.hasOwnProperty.call(pendingOptionValues, key);
}

function shouldApplyIncomingOption(key, next, sessionEcho) {
  if (!hasPendingOption(key)) return true;
  return sessionEcho || pendingOptionValues[key] === next;
}

function refreshAllOptionVisuals() {
  for (const key of Object.keys(optBoxes)) {
    applyOptionState(key, getOptionChecked(key));
  }
}

function syncOptions(m) {
  const sessionEcho = !!m._session_echo;
  syncingOptions = true;
  try {
    for (const key of Object.keys(optBoxes)) {
      if (key in m) {
        const next = !!m[key];
        if (!shouldApplyIncomingOption(key, next, sessionEcho)) continue;
        applyOptionState(key, next);
      }
    }
  } finally {
    syncingOptions = false;
  }
  // Auto-save 상태 동기화
  if ('auto_save' in m) {
    if (autoSavePanel) autoSavePanel.syncEnabled(m.auto_save);
  }
}

function syncRatingBarVisibility() {
  const pf = getOptionChecked('prompt_fixed');
  const wc = getOptionChecked('wildcard_standalone');
  const bar = document.querySelector('.tag-filter-rating-row');
  if (bar) bar.style.display = (pf || wc) ? 'none' : '';
}

function toggleOptionButton(key) {
  const control = optBoxes[key];
  if (!control || control.disabled) return;
  setOption(key, !getOptionChecked(key));
}

function setOption(key, value) {
  const next = !!value;
  if (syncingOptions) {
    applyOptionState(key, next);
    return;
  }
  if (!applyOptionState(key, next, {clearPending: false})) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_option', key, value: next}));
    markOptionPending(key, false);
  } else {
    markOptionPending(key, false);
  }
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
    opt.disabled = !(connected || displayFallback);
    opt.dataset.connected = connected ? '1' : '0';
  });

  modeSelect.disabled = modeSwitching || !anyConnected;

  const currentConnected = isModeConnected(modeSelect.value);
  modeSelect.classList.toggle('mode-unavailable', !currentConnected);
  modeSelect.title = anyConnected ? 'Only connected API modes are selectable' : 'No connected API session. Open API setup';
  if (modeApiCombo) {
    modeApiCombo.classList.toggle('has-connected-mode', anyConnected);
    modeApiCombo.classList.toggle('no-connected-mode', !anyConnected);
    modeApiCombo.classList.toggle('mode-unavailable', !currentConnected);
  }
  if (moduleLauncherControl) moduleLauncherControl.updateState();
}

function syncMode(mode) {
  const previousMode = currentMode || modeSelect.value || prevMode;
  if (previousMode && previousMode !== mode) {
    closeOpenModulesForModeSwitch();
  }
  syncingMode = true;
  modeSelect.value = mode;
  prevMode = mode;
  syncingMode = false;
  currentMode = mode;
  setNaiHighlightMode(mode);
  updatePromptTokenEstimate();
  if (moduleBadges) moduleBadges.updateModeState();
  // 모드 전용 모듈 상태 갱신 (NAI 전용 도구는 비NAI에서 숨김)
  const isNai = mode === 'NAI';
  const naiOnlyModules = ['character', 'character_reference', 'vibe_transfer'];
  naiOnlyModules.forEach(mid => {
    const btn = document.querySelector(`.module-btn[data-module="${mid}"]`);
    if (btn) btn.classList.toggle('nai-only-disabled', !isNai);
  });
  updateModuleHeaderAction(currentModuleId);
  updateModeSelectAvailability();
  if (resultEnhance) resultEnhance.update();
  if (artistThumbControl) artistThumbControl.syncPromptFormat();
}

function setMode(mode) {
  if (syncingMode) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!isModeConnected(mode)) {
    syncMode(prevMode);
    showToast(`${mode} API is not connected`, 'error', true);
    return;
  }
  if ((currentMode || prevMode || modeSelect.value) !== mode) {
    closeOpenModulesForModeSwitch();
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

let confirmDialogResolve = null;
function showConfirmDialog(message, options = {}) {
  if (confirmDialogResolve) {
    confirmDialogResolve(false);
    confirmDialogResolve = null;
  }

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'app-confirm-overlay';
    overlay.innerHTML = `
      <section class="app-confirm-dialog" role="dialog" aria-modal="true" aria-label="${escHtml(options.title || 'Confirm')}">
        <div class="app-confirm-icon" aria-hidden="true">i</div>
        <div class="app-confirm-copy">
          <div class="app-confirm-title">${escHtml(options.title || '확인')}</div>
          <div class="app-confirm-message">${escHtml(message)}</div>
        </div>
        <div class="app-confirm-actions">
          <button class="app-confirm-btn app-confirm-btn-primary" data-confirm-action="ok" type="button">${escHtml(options.okText || 'OK')}</button>
          <button class="app-confirm-btn" data-confirm-action="cancel" type="button">${escHtml(options.cancelText || 'Cancel')}</button>
        </div>
      </section>
    `;

    const cleanup = result => {
      if (confirmDialogResolve !== cleanup) return;
      confirmDialogResolve = null;
      document.removeEventListener('keydown', onKeyDown, true);
      overlay.remove();
      resolve(result);
    };
    const onKeyDown = event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        cleanup(false);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        cleanup(true);
      }
    };

    overlay.addEventListener('click', event => {
      if (event.target === overlay) {
        cleanup(false);
        return;
      }
      const button = event.target.closest('[data-confirm-action]');
      if (!button) return;
      cleanup(button.dataset.confirmAction === 'ok');
    });

    confirmDialogResolve = cleanup;
    document.addEventListener('keydown', onKeyDown, true);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => {
      overlay.classList.add('open');
      overlay.querySelector('[data-confirm-action="ok"]')?.focus();
    });
  });
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
const modulePopupDetach = $('modulePopupDetach');
const chunkPanel = $('chunkPanel');
let currentModuleId = null;
let moduleSendTimer = null;
let pendingModuleEdit = null;

function openDanbooruBrowserTool() {
  if (danbooruTabControl?.openBrowser) {
    danbooruTabControl.openBrowser();
    return;
  }
  danbooruTabReady.then(() => {
    if (danbooruTabControl?.openBrowser) {
      danbooruTabControl.openBrowser();
    } else {
      showToast('Danbooru browser is not ready', 'error');
    }
  });
}

const moduleLauncherReady = import('./js/features/moduleLauncher.mjs')
  .then(({createModuleLauncher}) => {
    moduleLauncherControl = createModuleLauncher({
      document,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      getCurrentModuleId: () => currentModuleId,
      isModulePopupOpen: () => modulePopup.classList.contains('open'),
      isChunkOpen,
      openModule,
      openChunkPanel,
      openDanbooruBrowser: openDanbooruBrowserTool,
      getComfyUiWorkflowState: () => comfyuiWorkflowState,
      switchComfyUiWorkflowDefault,
      uploadComfyUiWorkflow,
      openComfyUiWeb,
    });
    moduleLauncherControl.render();
    moduleLauncherControl.bind();
  })
  .catch(error => {
    console.error('Failed to initialize module launcher', error);
  });

let lastPromptEngineeringState = null;
const promptEngineeringPanelReady = import('./js/features/promptEngineeringPanel.mjs')
  .then(({createPromptEngineeringPanel}) => {
    promptEngineeringPanelControl = createPromptEngineeringPanel({
      document,
      moduleBody,
      escHtml,
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
      getMode: () => modeSelect.value,
      showToast,
      confirmDialog: showConfirmDialog,
      flushPromptEngineeringEdits,
      flushMainPromptAndParams,
      setModuleParam,
      closePresetAddPanel: closePePresetAddPanel,
      closePresetManagePanel: closePePresetManagePanel,
      getLastPromptEngineeringState: () => lastPromptEngineeringState,
      isComfyUiAnimaMode,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering actions module', error);
  });

function updateModuleHeaderAction(moduleId) {
  if (modulePopupDetach) {
    const showDetachAction = Boolean(moduleId)
      && !(isDetachedModule && (detachedStandalone || detachedModuleId === 'img2img'));
    modulePopupDetach.style.display = showDetachAction ? '' : 'none';
    if (showDetachAction) {
      modulePopupDetach.textContent = isDetachedModule ? '↙' : '↗';
      modulePopupDetach.title = isDetachedModule ? 'Attach to main window' : 'Open detached window';
      modulePopupDetach.setAttribute(
        'aria-label',
        isDetachedModule ? 'Attach to main window' : 'Open detached window',
      );
    }
  }
  if (!modulePopupAction) return;
  if (moduleId === 'prompt_engineering' && ((currentMode || modeSelect.value) === 'NAI' || isComfyUiAnimaMode())) {
    modulePopupAction.textContent = '추천 설정 적용';
    modulePopupAction.style.display = '';
    modulePopupAction.onclick = applyRecommendedPromptPreset;
    return;
  }
  modulePopupAction.style.display = 'none';
  modulePopupAction.onclick = null;
  modulePopupAction.textContent = '';
}

function isComfyUiAnimaMode() {
  return (currentMode || modeSelect.value) === 'COMFYUI'
    && Boolean($('flagAnima')?.classList.contains('on'));
}

function requestModuleState(moduleId) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  if (moduleId === 'search') {
    ws.send(JSON.stringify({type: 'get_search_state'}));
  } else {
    ws.send(JSON.stringify({type: 'get_module_state', module_id: moduleId}));
  }
  return true;
}

function openModule(moduleId, options = {}) {
  // NAI 전용 모듈 가드
  if (['character', 'character_reference', 'vibe_transfer'].includes(moduleId) && modeSelect.value !== 'NAI') {
    showToast('This module is only available in NAI mode', 'error');
    return;
  }
  // Toggle: same module clicked again → close
  if (currentModuleId === moduleId && modulePopup.classList.contains('open')) {
    if (options.forceOpen) {
      relayoutFloatingPanels();
      updateModuleBtnState();
      updateModuleHeaderAction(moduleId);
      if (options.initialState && options.initialState.module_id === moduleId) {
        moduleStateCache.set(moduleId, options.initialState);
        renderModuleState(options.initialState);
        if (options.guardInitialState) guardTransferredModuleState(moduleId);
      }
      if (!options.skipStateRequest) {
        requestModuleState(moduleId);
      }
      return;
    }
    closeModule();
    return;
  }
  if (currentModuleId === 'img2img' && img2imgPanel) img2imgPanel.closeMaskEditor();
  flushPendingModuleEdit(currentModuleId);
  // chunk 는 1차 모듈과 공존 — 닫지 않고 새 anchor 로 재정렬만
  closeAuxiliaryPopups(null, { keepChunk: moduleId !== 'chunk' });
  currentModuleId = moduleId;
  modulePopup.classList.toggle('module-popup-e621', moduleId === 'e621_event');
  modulePopup.classList.toggle('module-popup-img2img', moduleId === 'img2img');
  modulePopup.classList.toggle('module-popup-conditional', moduleId === 'conditional_prompt');
  modulePopup.classList.remove('module-popup-inpaint');
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
    img2img: 'Img2Img',
    conditional_prompt: '조건부 프롬프트',
    wildcard: '와일드카드 관리',
    instant_wildcard: 'Instant Wildcard',
    chunk: '와일드카드 청크',
    e621_event: 'E621 연구모듈',
    ollama: 'Ollama',
  };
  moduleTitle.textContent = moduleLauncherControl?.moduleTitle(moduleId) || titles[moduleId] || moduleId;
  if (moduleId === 'auto_save' && autoSavePanel) {
    autoSavePanel.renderCached();
  }
  if (options.initialState && options.initialState.module_id === moduleId) {
    moduleStateCache.set(moduleId, options.initialState);
    renderModuleState(options.initialState);
    if (options.guardInitialState) guardTransferredModuleState(moduleId);
  }
  if (!options.skipStateRequest) {
    requestModuleState(moduleId);
  }
}

function closeModule(options = {}) {
  if (isDetachedModule) {
    if (window.opener) window.close();
    return;
  }
  if (currentModuleId === 'img2img' && img2imgPanel) img2imgPanel.closeMaskEditor();
  flushPendingModuleEdit(currentModuleId);
  modulePopup.classList.remove('open');
  modulePopup.classList.remove('module-popup-e621');
  modulePopup.classList.remove('module-popup-img2img');
  modulePopup.classList.remove('module-popup-conditional');
  modulePopup.classList.remove('module-popup-inpaint');
  closeAuxiliaryPopups(null, { keepChunk: options.keepChunk !== false });
  currentModuleId = null;
  if (chunkPanelControl) chunkPanelControl.clearTriggerInfo();
  updateModuleHeaderAction(null);
  updateModuleBtnState();
  if (chunkPanelControl) chunkPanelControl.relayout();
}

function closeOpenModulesForModeSwitch() {
  if (isDetachedModule) return;
  const hasPrimaryModule = Boolean(currentModuleId) || modulePopup.classList.contains('open');
  if (hasPrimaryModule) {
    closeModule({ keepChunk: false });
  } else {
    closeAuxiliaryPopups(null, { keepChunk: false });
    if (chunkPanelControl) chunkPanelControl.clearTriggerInfo();
    updateModuleBtnState();
  }
}

function updateModuleBtnState() {
  document.querySelectorAll('.module-btn[data-module]').forEach(btn => {
    const isChunkBtn = btn.dataset.module === 'chunk';
    btn.classList.toggle('active', isChunkBtn ? isChunkOpen() : btn.dataset.module === currentModuleId);
  });
  const pb = document.querySelector('.module-prompt-btn');
  if (pb) pb.classList.toggle('active', currentModuleId === 'search');
  if (moduleLauncherControl) moduleLauncherControl.updateState();
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
const promptEngineeringPopupsReady = import('./js/features/promptEngineeringPopups.mjs')
  .then(({createPromptEngineeringPopups}) => {
    promptEngineeringPopups = createPromptEngineeringPopups({
      getWs: () => ws,
      WebSocket,
      modulePopup,
      panels: {
        e621: peE621Panel,
        presetAdd: pePresetAddPanel,
        presetManage: pePresetManagePanel,
        danbooru: peDanbooruPanel,
        debug: peDebugPanel,
      },
      positionFloatingPanel,
      relayoutFloatingPanels,
      closeAuxiliaryPopups,
      refreshDebug: refreshPromptEngineeringDebug,
      getLastState: () => lastPromptEngineeringState,
      renderers: {
        presetAdd: renderPePresetAddPanel,
        presetManage: renderPePresetManagePanel,
        e621: renderPeE621Panel,
        danbooru: renderPeDanbooruPanel,
        debug: renderPeDebugPanel,
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering popups module', error);
  });

function closeAllPePanels() {
  if (promptEngineeringPopups) promptEngineeringPopups.closeAll();
}

function closeAuxiliaryPopups(exceptPanel = null, options = {}) {
  // chunk 는 prompt-engineering 등 1차 모듈 popup 과 동시에 사용하도록 설계됨.
  // 명시적으로 닫지 않는 한 살아남게 유지하고 새 anchor 로 재정렬만 한다.
  if (exceptPanel !== chunkPanel && isChunkOpen()) {
    if (options.keepChunk) {
      if (chunkPanelControl) chunkPanelControl.relayout();
    } else {
      closeChunkPanel();
    }
  }
  if (exceptPanel !== refinePanel && refinePanelControl && refinePanelControl.isOpen()) closeRefine();
  if (exceptPanel !== pePresetAddPanel && promptEngineeringPopups?.isOpen('presetAdd')) closePePresetAddPanel();
  if (exceptPanel !== pePresetManagePanel && promptEngineeringPopups?.isOpen('presetManage')) closePePresetManagePanel();
  if (exceptPanel !== peE621Panel && promptEngineeringPopups?.isOpen('e621')) closePeE621Panel();
  if (exceptPanel !== peDanbooruPanel && promptEngineeringPopups?.isOpen('danbooru')) closePeDanbooruPanel();
  if (exceptPanel !== peDebugPanel && promptEngineeringPopups?.isOpen('debug')) closePeDebugPanel();

  const tagFilterPopup = document.getElementById('tagFilterPopup');
  if (exceptPanel !== tagFilterPopup && tagFilterPopup?.classList.contains('open')) {
    closeTagFilter();
  }
}

function openPePresetAddPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.openPresetAdd();
}

function closePePresetAddPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.closePresetAdd();
}

function openPePresetManagePanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.openPresetManage();
}

function closePePresetManagePanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.closePresetManage();
}

function openPeE621Panel() {
  if (promptEngineeringPopups) promptEngineeringPopups.openE621();
}

function closePeE621Panel() {
  if (promptEngineeringPopups) promptEngineeringPopups.closeE621();
}

function openPeDanbooruPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.openDanbooru();
}

function closePeDanbooruPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.closeDanbooru();
}

function openPeDebugPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.openDebug();
}

function closePeDebugPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.closeDebug();
}

function syncPromptEngineeringPopups() {
  if (promptEngineeringPopups) promptEngineeringPopups.sync(lastPromptEngineeringState);
}

function onModuleState(m) {
  if (isModuleStateGuarded(m.module_id)) return;
  if (m.module_id) moduleStateCache.set(m.module_id, m);
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
  renderModuleState(m);
}

function renderModuleState(m) {
  if (m.module_id === 'auto_save') renderAutoSavePanel(m);
  else if (m.module_id === 'prompt_engineering') renderPromptEngineering(m);
  else if (m.module_id === 'automation') renderAutomation(m);
  else if (m.module_id === 'character') renderCharacter(m);
  else if (m.module_id === 'conditional_prompt') renderConditionalPrompt(m);
  else if (m.module_id === 'character_reference') renderCharacterReference(m);
  else if (m.module_id === 'vibe_transfer') renderVibeTransfer(m);
  else if (m.module_id === 'img2img') renderImg2Img(m);
  else if (m.module_id === 'save_directory') renderSaveDirectory(m);
  else if (m.module_id === 'wildcard') renderWildcard(m);
  else if (m.module_id === 'instant_wildcard') renderInstantWildcard(m);
  else if (m.module_id === 'e621_event') renderE621Event(m);
  else if (m.module_id === 'ollama') renderOllama(m);
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

function discardPendingModuleEdit(moduleId = null) {
  if (!pendingModuleEdit) return;
  if (moduleId && pendingModuleEdit.moduleId !== moduleId) return;
  if (moduleSendTimer) {
    clearTimeout(moduleSendTimer);
    moduleSendTimer = null;
  }
  pendingModuleEdit = null;
}

function setPromptEngineeringOption(key, checked) {
  if (promptEngineeringActions) promptEngineeringActions.setOption(key, checked);
}

function setModuleParam(moduleId, key, value, options = {}) {
  if (!options.skipPendingFlush) flushPendingModuleEdit(moduleId);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_module_param', module_id: moduleId, key, value}));
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

// ---- Instant Wildcard editor ----
function renderInstantWildcard(m) {
  if (instantWildcardPanel) instantWildcardPanel.render(m);
}

function instantWildcardSelectFile(value) {
  if (instantWildcardPanel) instantWildcardPanel.selectFile(value);
}

function instantWildcardSelectKey(element) {
  if (instantWildcardPanel) instantWildcardPanel.selectKey(element);
}

function instantWildcardReload() {
  if (instantWildcardPanel) instantWildcardPanel.reload();
}

function instantWildcardAddGroup() {
  if (instantWildcardPanel) instantWildcardPanel.addGroup();
}

function instantWildcardSave() {
  if (instantWildcardPanel) instantWildcardPanel.save();
}

function instantWildcardRename() {
  if (instantWildcardPanel) instantWildcardPanel.rename();
}

function instantWildcardDelete() {
  if (instantWildcardPanel) instantWildcardPanel.deleteCurrent();
}

// ---- E621 Event module ----
function renderE621Event(m) {
  if (e621EventPanel) e621EventPanel.render(m);
}

function e621Search() {
  if (e621EventPanel) e621EventPanel.search();
}

function e621Reset() {
  if (e621EventPanel) e621EventPanel.reset();
}

function e621SetViewMode(value) {
  if (e621EventPanel) e621EventPanel.setViewMode(value);
}

function e621SelectCategory(element) {
  if (e621EventPanel) e621EventPanel.selectCategory(element);
}

function e621SelectFolder(element) {
  if (e621EventPanel) e621EventPanel.selectFolder(element);
}

function e621SelectTag(element) {
  if (e621EventPanel) e621EventPanel.selectTag(element);
}

function e621ToggleStar() {
  if (e621EventPanel) e621EventPanel.toggleStar();
}

function e621HideSelected() {
  if (e621EventPanel) e621EventPanel.hideSelected();
}

function e621RestoreHidden(element) {
  if (e621EventPanel) e621EventPanel.restoreHidden(element);
}

function e621OnTestbenchInput(element) {
  if (e621EventPanel) e621EventPanel.onTestbenchInput(element);
}

function e621Generate() {
  if (e621EventPanel) e621EventPanel.generate();
}

// ---- Ollama module ----
function renderOllama(m) {
  if (ollamaPanel) ollamaPanel.render(m);
}

function ollamaRefresh() {
  if (ollamaPanel) ollamaPanel.refresh();
}

function ollamaServerAction(action) {
  if (ollamaPanel) ollamaPanel.serverAction(action);
}

function ollamaInputChanged(element) {
  if (ollamaPanel) ollamaPanel.inputChanged(element);
}

function ollamaConvert() {
  if (ollamaPanel) ollamaPanel.convert();
}

function ollamaCancel() {
  if (ollamaPanel) ollamaPanel.cancel();
}

function ollamaCopyOutput() {
  if (ollamaPanel) ollamaPanel.copyOutput();
}

// ---- Chunk Module (instant wildcard tree browser) ----
function requestChunkState() {
  if (chunkPanelControl) chunkPanelControl.requestState();
}

function getChunkAnchor(target = null) {
  return chunkPanelControl ? chunkPanelControl.getAnchor(target) : modulePopup;
}

function openChunkPanel(anchorEl = null, toggle = false) {
  if (!chunkPanelControl) return;
  if (!(toggle && isChunkOpen())) closeAuxiliaryPopups(chunkPanel);
  chunkPanelControl.open(anchorEl, toggle);
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

function chunkSaveNew(event) {
  return chunkPanelControl ? chunkPanelControl.saveNew(event) : false;
}

function chunkUseSelection() {
  if (chunkPanelControl) chunkPanelControl.useSelection();
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

function onVibeRefStrengthDraft(index, value, source = '') {
  if (imageModulePanels) imageModulePanels.updateVibeRefStrengthDraft(index, value, source);
}

function commitVibeRefStrength(index, value) {
  if (imageModulePanels) imageModulePanels.commitVibeRefStrength(index, value);
}

function onVibeIeDraft(index, value) {
  if (imageModulePanels) imageModulePanels.updateVibeIeDraft(index, value);
}

function commitVibeIeDraft(index, value) {
  if (imageModulePanels) imageModulePanels.commitVibeIeDraft(index, value);
}

function selectVibeEncoding(index, ieValue) {
  if (imageModulePanels) imageModulePanels.selectVibeEncoding(index, ieValue);
}

function encodeVibeFrame(index) {
  if (imageModulePanels) imageModulePanels.encodeVibeFrame(index);
}

// ---- Character Reference module ----
function renderCharacterReference(m) {
  if (imageModulePanels) imageModulePanels.renderCharacterReference(m);
}

// ---- Vibe Transfer module ----
function renderVibeTransfer(m) {
  if (imageModulePanels) imageModulePanels.renderVibeTransfer(m);
}

// ---- Img2Img module ----
function renderImg2Img(m) {
  const mode = String(m?.mode || '').toLowerCase();
  const title = mode === 'inpaint' ? 'Inpaint' : 'Img2Img';
  if (currentModuleId === 'img2img' && moduleTitle) moduleTitle.textContent = title;
  if (modulePopup) modulePopup.classList.toggle('module-popup-inpaint', mode === 'inpaint');
  if (isDetachedModule && detachedModuleId === 'img2img') {
    document.title = `NAIA Module - ${title.toLowerCase()}`;
  }
  if (img2imgPanel) img2imgPanel.render(m);
}

function img2imgSlider(key, value) {
  if (img2imgPanel) img2imgPanel.slider(key, value);
}

function img2imgRepeat(value) {
  if (img2imgPanel) img2imgPanel.repeat(value);
}

function img2imgText(key, value) {
  if (img2imgPanel) img2imgPanel.text(key, value);
}

function img2imgAddCharacter() {
  if (img2imgPanel) img2imgPanel.addCharacter();
}

function img2imgRemoveCharacter(index) {
  if (img2imgPanel) img2imgPanel.removeCharacter(index);
}

function img2imgSetCharacterActive(index, checked) {
  if (img2imgPanel) img2imgPanel.setCharacterActive(index, checked);
}

function img2imgGenerate() {
  if (img2imgPanel) img2imgPanel.generate();
}

function img2imgClose() {
  if (img2imgPanel) img2imgPanel.close();
}

function img2imgOpenMaskEditor() {
  if (img2imgPanel) img2imgPanel.openMaskEditor();
}

function img2imgCloseMaskEditor() {
  if (img2imgPanel) img2imgPanel.closeMaskEditor();
}

function img2imgMaskBrush(value) {
  if (img2imgPanel) img2imgPanel.maskBrush(value);
}

function img2imgMaskMode(mode) {
  if (img2imgPanel) img2imgPanel.setMaskMode(mode);
}

function img2imgApplyMask() {
  if (img2imgPanel) img2imgPanel.applyMask();
}

function img2imgClearMask() {
  if (img2imgPanel) img2imgPanel.clearMask();
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
  if (panel === chunkPanel) return 420;
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
  const desktopLayout = isDesktopLayout();
  const margin = desktopLayout ? 16 : 12;
  const sideMargin = 12;
  const minWidth = Math.min(320, Math.max(260, viewportWidth - sideMargin * 2));
  const preferredWidth = Math.min(getFloatingPanelWidth(panel), viewportWidth - sideMargin * 2);

  panel.style.right = 'auto';
  panel.style.bottom = 'auto';

  if (!desktopLayout) {
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
const fmtCount = n => n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);
const CAT_COLORS = { artist: '#d4736a', copyright: '#a87fd4', character: '#6abf7b', e621: '#d4c36a', wildcard: '#6ac4d4' };
function catStyle(cat) { return cat && CAT_COLORS[cat] ? ` style="color:${CAT_COLORS[cat]}"` : ''; }

let tagAssist = null;
const pendingTagAssistBinds = [];

function getTagTooltip() {
  return tagAssist ? tagAssist.getTooltip() : $('tagTooltip');
}

function getTagAssistTarget() {
  return tagAssist ? tagAssist.getAcTarget() : null;
}

function positionTagTooltip() {
  if (tagAssist) tagAssist.positionTagTooltip();
}

function renderPromptInfoHtml(label, text) {
  if (tagAssist) return tagAssist.renderPromptInfoHtml(label, text);
  return `<div class="pf-island"><span class="pf-label">${escHtml(label)}</span>` +
    `<span class="generation-info-tags">${escHtml(text)}</span></div>`;
}

function lookupPromptInfoTag(tag) {
  if (tagAssist) tagAssist.lookupPromptInfoTag(tag);
}

function bindTagAssist(textarea, options = {}) {
  if (!textarea) return;
  if (tagAssist) {
    tagAssist.bindTagAssist(textarea, options);
    return;
  }
  pendingTagAssistBinds.push([textarea, options]);
}

function onTagLookupResult(m) {
  if (tagAssist) tagAssist.onTagLookupResult(m);
}

function onAutocompleteResult(m) {
  if (tagAssist) tagAssist.onAutocompleteResult(m);
}

function _fireModuleOninput(el) {
  const handler = el.getAttribute('oninput');
  if (handler) new Function('event', handler).call(el, {target: el});
}

const tagAssistReady = import('./js/features/tagAssist.mjs')
  .then(({createTagAssistController}) => {
    tagAssist = createTagAssistController({
      document,
      window,
      navigator,
      tooltip: $('tagTooltip'),
      promptEdit,
      negEdit,
      WebSocket,
      getWs: () => ws,
      getMode: () => modeSelect.value,
      getChunkPanelControl: () => chunkPanelControl,
      openChunkPanel,
      getChunkAnchor,
      onPromptEdit,
      fireModuleOninput: _fireModuleOninput,
      escHtml,
      fmtCount,
      catStyle,
      showToast,
    });
    tagAssist.bindDefaultTextareas();
    pendingTagAssistBinds.splice(0).forEach(([textarea, options]) => {
      tagAssist.bindTagAssist(textarea, options);
    });
  })
  .catch(error => {
    console.error('Failed to initialize tag assist module', error);
    throw error;
  });
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
  remoteWsClientReady,
  rightTabsReady,
  danbooruTabReady,
  thumbTabReady,
  artistThumbReady,
  studioTabReady,
  customSelectsReady,
  resultInfoResizerReady,
  resultHistoryReady,
  resultEnhanceReady,
  resultImageActionsReady,
  metadataViewerReady,
  imageActionPopupReady,
  resultImageInputReady,
  queuePanelReady,
  resultContextMenuReady,
  promptHighlighterReady,
  tokenDisplayReady,
  moduleLauncherReady,
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
  instantWildcardPanelReady,
  e621EventPanelReady,
  ollamaPanelReady,
  imageModulePanelsReady,
  img2imgPanelReady,
  refinePanelReady,
  tagSearchReady,
  tagAssistReady,
  mobileViewportReady,
  searchPanelReady,
  chunkPanelReady,
  danbooruFeedbackReady,
  promptEngineeringPopupRenderersReady,
  promptEngineeringPanelReady,
  promptEngineeringActionsReady,
  promptEngineeringPopupsReady,
])
  .then(() => {
    initHistoryRail();
    initResultInfoResizer();
    bindMetadataImageDropTarget();
    refreshAllOptionVisuals();
    initializeDetachedShell();
    setBootIndicator('Connecting…', 25, false);
    if (wsClient) wsClient.connect();
  })
  .catch(error => {
    console.error('Failed to initialize remote shell', error);
  });
