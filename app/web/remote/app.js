/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, latestResultBlob = null, generating = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&#39;').replace(/"/g,'&quot;') : '';
let genTimer = null, genStartTime = 0;
const genDurations = [];  // last 5 generation durations (ms)
let activePromptTab = 'prompt';
let presetGenerationPending = null;
let latestImageMeta = null;

let _initDone = false;  // init_complete 수신 후 true → 초기 시딩 제외
let syncingOptions = false, syncingPrompt = false, promptSendTimer = null;
// 사용자가 로컬 편집을 했지만 아직 서버로 flush되지 않은 상태 — 서버 브로드캐스트 덮어쓰기 차단
let _localPromptDirty = false;
let awaitingMyRandom = false;  // 내가 Random 클릭했는지 추적
let pendingRandomRequestId = '';
let initialStateRefreshTimer = null;
let promptHighlightIndexTimer = null;
let initialHistoryRefreshTimer = null;
let initialRandomPromptIssued = false;
let initialRandomPromptTimer = null;
let sessionBootstrapReceived = false;
let randomRequestSerial = 0;
let sessionId = null;
const urlParams = new URLSearchParams(location.search);
const isDesktopShell = urlParams.get('desktop_shell') === '1';
const isLocalWebHost = (() => {
  const host = String(location.hostname || '').toLowerCase();
  return (
    host === 'localhost'
    || host === '127.0.0.1'
    || host === '0.0.0.0'
    || host === '::1'
    || host === '[::1]'
    || host === '::ffff:127.0.0.1'
  );
})();
const canUseHostClipboardBridge = isDesktopShell || isLocalWebHost;
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
let pendingRightTabAvailability = null;
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
let resultUnsavedActionRequestId = 0;
let resultUnsavedActionAsset = null;
let resultUnsavedActionTimer = null;
let resultUnsavedActionBusy = false;
let promptHighlighter = null;
let moduleBadges = null;
let moduleLauncherControl = null;
let webUiHiresfixAssistState = {enabled: true, target: 512};
let comfyuiWorkflowState = {
  has_custom: false,
  workflow_label: 'Basic Workflow',
  workflow_type: '',
};
let comfyuiWorkflowFileInput = null;
let comfyuiFreeWorkflowFileInput = null;
let cloudflaredControls = null;
let generationProgress = null;
let setupController = null;
window.__naiaSetupControllerReady = false;
let promptDrawerControl = null;
let eventPresetPanel = null;
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

function initNaiaTitleTooltips() {
  if (document.body.dataset.naiaTitleTooltips === '1') return;
  document.body.dataset.naiaTitleTooltips = '1';

  const tooltip = document.createElement('div');
  tooltip.className = 'naia-title-tooltip';
  document.body.append(tooltip);
  let owner = null;

  const shouldKeepNativeTitle = element => {
    if (!(element instanceof Element)) return true;
    return element.matches('option, select, datalist, input[pattern], textarea[pattern]');
  };

  const adoptTitle = element => {
    if (!(element instanceof Element) || shouldKeepNativeTitle(element)) return;
    const title = element.getAttribute('title');
    if (!title) return;
    element.dataset.naiaTitle = title;
    if (!element.getAttribute('aria-label')) element.setAttribute('aria-label', title);
    element.removeAttribute('title');
  };

  const scanTitles = root => {
    if (!(root instanceof Element)) return;
    adoptTitle(root);
    root.querySelectorAll?.('[title]').forEach(adoptTitle);
  };

  const positionTooltip = target => {
    if (!target || !tooltip.classList.contains('open')) return;
    const rect = target.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    const gap = 8;
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
    let left = rect.left + (rect.width - tipRect.width) / 2;
    left = Math.max(gap, Math.min(left, viewportWidth - tipRect.width - gap));
    let top = rect.bottom + gap;
    if (top + tipRect.height > viewportHeight - gap) top = rect.top - tipRect.height - gap;
    top = Math.max(gap, Math.min(top, viewportHeight - tipRect.height - gap));
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
  };

  const showTooltip = target => {
    const text = target?.dataset?.naiaTitle || '';
    if (!text) return;
    owner = target;
    tooltip.textContent = text;
    tooltip.classList.add('open');
    requestAnimationFrame(() => {
      if (owner === target) positionTooltip(target);
    });
  };

  const hideTooltip = target => {
    if (target && owner && target !== owner) return;
    owner = null;
    tooltip.classList.remove('open');
  };

  scanTitles(document.body);
  new MutationObserver(mutations => {
    mutations.forEach(mutation => {
      if (mutation.type === 'attributes') {
        adoptTitle(mutation.target);
        return;
      }
      mutation.addedNodes.forEach(node => scanTitles(node));
    });
  }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['title']});

  document.addEventListener('pointerover', event => {
    const target = event.target?.closest?.('[data-naia-title]');
    if (target) showTooltip(target);
  });
  document.addEventListener('pointerout', event => {
    const target = event.target?.closest?.('[data-naia-title]');
    if (target && !target.contains(event.relatedTarget)) hideTooltip(target);
  });
  document.addEventListener('focusin', event => {
    const target = event.target?.closest?.('[data-naia-title]');
    if (target) showTooltip(target);
  });
  document.addEventListener('focusout', event => {
    const target = event.target?.closest?.('[data-naia-title]');
    if (target) hideTooltip(target);
  });
  window.addEventListener('resize', () => hideTooltip());
  window.addEventListener('scroll', () => hideTooltip(), true);
}

let automationPanel = null;
let characterPanel = null;
let conditionalPromptPanel = null;
let eventStreamPanel = null;
let wildcardPanel = null;
let wildcardManagerPanel = null;
let instantWildcardPanel = null;
let e621EventPanel = null;
let imageModulePanels = null;
let img2imgPanel = null;
let refinePanelControl = null;
let tagSearchController = null;
let mobileViewportControl = null;
let searchPanelControl = null;
let chunkPanelControl = null;
let danbooruFeedbackControl = null;
let resolutionManagerPanel = null;
let danbooruTabControl = null;
let thumbTabControl = null;
let artistThumbControl = null;
let characterViewerControl = null;
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
const quickFilterReady = import('./js/features/quickFilter.mjs?v=20260526-safe-rating-default1')
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
    if (pendingRightTabAvailability) {
      rightTabs.setAvailability(pendingRightTabAvailability);
      pendingRightTabAvailability = null;
    }
  })
  .catch(error => {
    console.error('Failed to initialize right tabs module', error);
  });

function applyRightTabAvailability(tabAvailability) {
  if (!tabAvailability || typeof tabAvailability !== 'object') return;
  if (rightTabs && typeof rightTabs.setAvailability === 'function') {
    rightTabs.setAvailability(tabAvailability);
    return;
  }
  pendingRightTabAvailability = {...tabAvailability};
}

async function loadRuntimeCapabilities() {
  try {
    const response = await fetch('/api/runtime/capabilities', {cache: 'no-store'});
    if (!response.ok) return;
    const payload = await response.json();
    if (payload) {
      applyRightTabAvailability(payload.right_tabs);
    }
  } catch (error) {
    // Older compatibility hosts may not expose this endpoint.
  }
}

loadRuntimeCapabilities();
const danbooruTabReady = import('./js/features/danbooruTab.mjs?v=20260525-runtime-danbooru1')
  .then(({createDanbooruBrowserController}) => {
    danbooruTabControl = createDanbooruBrowserController({
      document,
      fetch: window.fetch.bind(window),
      showToast,
      onLoadPrompt,
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
const artistThumbReady = import('./js/features/artistThumbTab.mjs?v=20260517-artist-active-resolution1')
  .then(({createArtistThumbController}) => {
    artistThumbControl = createArtistThumbController({
      document,
      fetch: window.fetch.bind(window),
      escHtml,
      showToast,
      promptEdit,
      negEdit,
      onPromptEdit,
      setPromptFields: applyPromptFields,
      getGenerationMode: () => currentMode || modeSelect.value || 'NAI',
      getCurrentGenerationParams: () => _collectCurrentParams(),
      isComfyUiAnimaMode,
      isAnimaArtistMode,
    });
  })
  .catch(error => {
    console.error('Failed to initialize Artist Thumb tab module', error);
  });
const characterViewerReady = import('./js/features/characterViewerTab.mjs?v=20260509-mobile-layout1')
  .then(({createCharacterViewerController}) => {
    characterViewerControl = createCharacterViewerController({
      document,
      fetch: window.fetch.bind(window),
      escHtml,
      showToast,
      promptEdit,
      negEdit,
      onPromptEdit,
      setPromptFields: applyPromptFields,
      getGenerationMode: () => currentMode || modeSelect.value || 'NAI',
    });
  })
  .catch(error => {
    console.error('Failed to initialize Character Viewer tab module', error);
  });
const studioTabReady = import('./js/features/studioTab.mjs?v=20260512-api-dialog-fallback1')
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
      confirmDialog: showConfirmDialog,
    });
    studioTabControl.init();
  })
  .catch(error => {
    console.error('Failed to initialize Studio tab module', error);
  });
const customSelectsReady = import('./js/features/customSelects.mjs?v=20260517-hiresfix-display1')
  .then(({createCustomSelectController}) => {
    customSelectsControl = createCustomSelectController({
      document,
      window,
      showToast,
      fetchFn: window.fetch.bind(window),
      useNativeClipboardFallback: () => canUseHostClipboardBridge,
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
const resultHistoryReady = import('./js/features/resultHistory.mjs?v=20260509_mobile_panel_pc_sync1')
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
      onDiskImageSelected: onResultHistorySelectionChanged,
    });
  })
  .catch(error => {
    console.error('Failed to initialize result history module', error);
  });
const resultEnhanceReady = import('./js/features/resultEnhance.mjs?v=20260517-webui-enhance-queue1')
  .then(({createResultEnhanceController}) => {
    resultEnhance = createResultEnhanceController({
      document,
      window,
      WebSocket,
      getWs: () => ws,
      getMode: () => currentMode,
      showToast,
      getWebUiHiresSettings: () => getWebUiResultEnhanceSettings(),
      setWebUiHiresSetting: (key, value) => setWebUiResultEnhanceSetting(key, value),
      getWebUiHiresUpscalerOptions: () => getWebUiResultEnhanceUpscalerOptions(),
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

const resultImageActionsReady = import('./js/features/resultImageActions.mjs?v=20260526-clipboard-copy1')
  .then(({createResultImageActions}) => {
    resultImageActions = createResultImageActions({
      document,
      window,
      fetch: window.fetch.bind(window),
      showToast,
      getMode: () => currentMode || modeSelect.value || 'NAI',
      getWs: () => ws,
      getLatestResultBlob: () => latestResultBlob,
      useNativeClipboard: () => canUseHostClipboardBridge,
      getPreviewImageUrl: () => (
        preview && preview.classList.contains('show') ? (preview.getAttribute('src') || '') : ''
      ),
      getMetadataViewer: () => metadataViewer,
      getQueuePanel: () => queuePanel,
      discardPendingModuleEdit,
      openModule,
      openImg2ImgSessionSurface,
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
const imageActionPopupReady = import('./js/features/imageActionPopup.mjs?v=20260525-runtime-action-clean1')
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
const queuePanelReady = import('./js/features/queuePanel.mjs?v=20260520-random-latency1')
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
const resultContextMenuReady = import('./js/features/resultContextMenu.mjs?v=20260526-open-location1')
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
      onWebUiEnhance: context => requestResultEnhanceFromContext(context),
      onQueueResult: (context, options) => callResultImageAction('queueResultFromContext', context, options),
      canUseDesktopImg2Img,
      canOpenLocalFiles: () => isLocalWebHost || isDesktopShell,
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
    if (_bootFinalized) schedulePromptHighlightIndexLoad();
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
const moduleBadgesReady = import('./js/features/moduleBadges.mjs?v=20260523-comfyui-bypass1')
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
const cloudflaredControlsReady = import('./js/features/cloudflaredControls.mjs?v=20260506-api-setup-ko1')
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
const setupControllerReady = import('./js/features/setupController.mjs?v=20260526-setup-autoclose1')
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
      confirmDialog: showConfirmDialog,
    });
    window.__naiaSetupControllerReady = true;
  })
  .catch(error => {
    window.__naiaSetupControllerReady = false;
    console.error('Failed to initialize setup controller module', error);
  });
let dataMigrationPanel = null;
const dataMigrationReady = import('./js/features/dataMigrationPanel.mjs?v=20260527-migration2')
  .then(({createDataMigrationPanel}) => {
    dataMigrationPanel = createDataMigrationPanel({document, showToast});
  })
  .catch(error => {
    console.error('Failed to initialize data migration panel module', error);
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
const eventPresetReady = import('./js/features/eventPresetPanel.mjs?v=20260516-hires-assist1')
  .then(({createEventPresetPanel}) => {
    eventPresetPanel = createEventPresetPanel({
      document,
      promptEdit,
      applyPromptText,
      onPromptEdit,
      getGenerating: () => generating,
      showToast,
      escHtml,
      onGenerateStateChange: updateGenerateButtonMode,
      getGenerationOverrides: () => collectWebUiHiresfixAssistOverrides(currentMode || modeSelect.value || 'NAI'),
    });
    syncPromptTabStateFromDom();
  })
  .catch(error => {
    console.error('Failed to initialize Event Preset panel module', error);
  });
const autoSavePanelReady = import('./js/features/autoSavePanel.mjs?v=20260514-unsaved-bulk1')
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
const automationPanelReady = import('./js/features/automationPanel.mjs?v=20260526-automation-runtime1')
  .then(({createAutomationPanel}) => {
    automationPanel = createAutomationPanel({
      document,
      setModuleParam,
    });
  })
  .catch(error => {
    console.error('Failed to initialize automation panel module', error);
  });
const characterPanelReady = import('./js/features/characterPanel.mjs?v=20260514-character-cold6')
  .then(({createCharacterPanel}) => {
    characterPanel = createCharacterPanel({
      document,
      escHtml,
      bindTagAssist,
      flushCharacterEdits,
      setModuleParam,
      showPromptDialog,
    });
  })
  .catch(error => {
    console.error('Failed to initialize character panel module', error);
  });
const conditionalPromptPanelReady = import('./js/features/conditionalPromptPanel.mjs?v=20260526-capability-honesty1')
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
const eventStreamPanelReady = import('./js/features/eventStreamPanel.mjs')
  .then(({createEventStreamPanel}) => {
    eventStreamPanel = createEventStreamPanel({
      document,
      escHtml,
      setModuleParam,
    });
  })
  .catch(error => {
    console.error('Failed to initialize event stream panel module', error);
  });
const wildcardPanelReady = import('./js/features/wildcardPanel.mjs')
  .then(({createWildcardPanel}) => {
    wildcardPanel = createWildcardPanel({
      document,
      escHtml,
      renderInlineBrowser: () => wildcardManagerPanel?.renderInlineBrowser(),
    });
  })
  .catch(error => {
    console.error('Failed to initialize wildcard panel module', error);
  });
const wildcardManagerPanelReady = import('./js/features/wildcardManagerPanel.mjs?v=20260512-api-dialog-fallback1')
  .then(({createWildcardManagerPanel}) => {
    wildcardManagerPanel = createWildcardManagerPanel({
      document,
      moduleBody,
      modulePopup,
      escHtml,
      setModuleParam,
      showToast,
      closeAuxiliaryPopups,
      positionFloatingPanel,
      confirmDialog: showConfirmDialog,
      promptDialog: showPromptDialog,
    });
  })
  .catch(error => {
    console.error('Failed to initialize wildcard manager panel module', error);
  });
const instantWildcardPanelReady = import('./js/features/instantWildcardPanel.mjs?v=20260512-api-dialog-fallback1')
  .then(({createInstantWildcardPanel}) => {
    instantWildcardPanel = createInstantWildcardPanel({
      document,
      window,
      escHtml,
      setModuleParam,
      bindTagAssist,
      showToast,
      confirmDialog: showConfirmDialog,
      promptDialog: showPromptDialog,
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
const imageModulePanelsReady = import('./js/features/imageModulePanels.mjs?v=20260526-capability-honesty1')
  .then(({createImageModulePanels}) => {
    imageModulePanels = createImageModulePanels({
      document,
      moduleBody,
      escHtml,
      setModuleParam,
      showToast,
      openModule,
      getCurrentModuleId: () => currentModuleId,
      fetchFn: window.fetch.bind(window),
      useNativeClipboardFallback: () => canUseHostClipboardBridge,
      modulePopup,
      positionFloatingPanel,
      confirmDialog: showConfirmDialog,
      promptDialog: showPromptDialog,
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
const refinePanelReady = import('./js/features/refinePanel.mjs?v=20260505-search-parquet-v4')
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
const tagSearchReady = import('./js/features/tagSearch.mjs?v=20260510-ime-compose1')
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
const searchPanelReady = import('./js/features/searchPanel.mjs?v=20260527-rating-inflight-lock1')
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
const resolutionManagerReady = import('./js/features/resolutionManagerPanel.mjs')
  .then(({createResolutionManagerPanel}) => {
    resolutionManagerPanel = createResolutionManagerPanel({
      document,
      showToast,
      getApiMode: () => currentMode || modeSelect?.value || '',
      getCurrentResolution: () => paramEls.resolution?.value || qResolution?.value || '',
      onSaved: payload => {
        updateParams({
          schema_only: true,
          api_mode: payload.api_mode || currentMode || modeSelect?.value || '',
          options_resolution: payload.resolutions || [],
          resolution: payload.current_resolution,
        });
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize resolution manager module', error);
  });

function parseParamNumber(value, fallback = null) {
  if (value === undefined || value === null || String(value).trim() === '') return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function _collectCurrentParams() {
  const p = {};
  const mode = currentMode || modeSelect?.value || 'NAI';
  const parseNumber = parseParamNumber;
  const flagState = key => {
    const el = paramFlags?.querySelector?.(`[data-key="${key}"]`);
    return !!el?.classList.contains('on');
  };
  const randomResolution = flagState('random_resolution') || !!qRndRes?.classList.contains('on');
  const autoFitResolution = flagState('auto_fit_resolution') || !!qAutoRes?.classList.contains('on');
  const resolutionOptions = Array.from(paramEls.resolution?.options || [])
    .map(option => option.value)
    .filter(Boolean);
  const resolution = randomResolution && resolutionOptions.length
    ? resolutionOptions[Math.floor(Math.random() * resolutionOptions.length)]
    : (paramEls.resolution.value || qResolution?.value || '');
  if (resolution) {
    applyResolutionLabelToParams(p, resolution);
  }
  const steps = parseNumber(paramEls.steps.value);
  const cfgScale = parseNumber(paramEls.cfg_scale.value);
  const cfgRescale = parseNumber(paramEls.cfg_rescale.value);
  if (steps !== null) p.steps = Math.trunc(steps);
  if (cfgScale !== null) p.cfg_scale = cfgScale;
  if (cfgRescale !== null) p.cfg_rescale = cfgRescale;
  const seedFixed = flagState('seed_fixed');
  p.seed_fixed = seedFixed;
  if (seedFixed && paramEls.seed.value) {
    const seed = parseNumber(paramEls.seed.value);
    if (seed !== null) p.seed = Math.max(0, Math.trunc(seed));
  } else if (!seedFixed) {
    p.seed = mode === 'NAI' ? Math.floor(Math.random() * 10000000000) : -1;
  }
  if (paramEls.sampler.value) p.sampler = paramEls.sampler.value;
  if (paramEls.scheduler.value) p.scheduler = paramEls.scheduler.value;
  if (paramEls.model.value) p.model = paramEls.model.value;
  document.querySelectorAll('#paramFlags .param-flag').forEach(el => {
    p[el.dataset.key] = el.classList.contains('on');
  });
  p.random_resolution = randomResolution;
  p.auto_fit_resolution = autoFitResolution;
  p.prompt_fixed = getOptionChecked('prompt_fixed');
  p.wildcard_standalone = getOptionChecked('wildcard_standalone');
  applyResolutionPresetToParams(p, mode, randomResolution);
  const promptWeight = $('pAnimaWeight')?.value?.trim();

  if (mode === 'WEBUI') {
    const enableHr = $('pEnableHr');
    const hrScale = $('pHrScale');
    const hrUpscaler = $('pHrUpscaler');
    const denoise = $('pDenoise');
    const hiresSteps = $('pHiresSteps');
    const hrCfg = $('pHrCfg');
    if (enableHr) p.enable_hr = !!enableHr.checked;
    if (hrScale) p.hr_scale = parseNumber(hrScale.value, 2.0);
    if (hrUpscaler?.value) p.hr_upscaler = hrUpscaler.value;
    if (denoise) p.denoising_strength = parseNumber(denoise.value, 0.5);
    if (hiresSteps) p.hires_steps = Math.trunc(parseNumber(hiresSteps.value, 10));
    if (hrCfg) p.hr_cfg = parseNumber(hrCfg.value, 7.0);
    const presetSwap = ((_hiresPresetSwapValueKnown ? _hiresPresetSwapValue : $('pHiresPresetSwap')?.value) || '').trim();
    if (presetSwap) p.hires_preset_swap = presetSwap;
    if (promptWeight) {
      p.anima_weight = promptWeight;
      p.random_prompt_weight = promptWeight;
    }
    Object.assign(p, collectWebUiHiresfixAssistOverrides(mode));
  }

  if (mode === 'COMFYUI') {
    p.filename_prefix = 'NAIA_ComfyUI';
    if (isComfyUiFreeWorkflowActive()) {
      p.sampling_mode = 'bypass';
      p.comfyui_sampling_mode = 'bypass';
      p.workflow_type = 'bypass';
    } else {
      const samplingMode = currentComfyUiSamplingMode();
      p.sampling_mode = samplingMode;
      p.workflow_type = samplingMode === 'anima' ? 'unet' : 'checkpoint';
      if (samplingMode === 'anima') {
        const rescaleCfg = parseNumber($('pRescaleCfg')?.value);
        if (rescaleCfg !== null) p.rescale_cfg = rescaleCfg;
      }
    }
    if (promptWeight) {
      p.anima_weight = promptWeight;
      p.random_prompt_weight = promptWeight;
    }
    p._comfyui_workflow_mode = comfyuiWorkflowState?.has_custom ? 'custom' : 'basic';
  }
  return p;
}

function normalizeWebUiHiresfixAssistTarget(value) {
  return Number(value) === 768 ? 768 : 512;
}

function normalizeWebUiHiresfixAssistState(state = {}) {
  return {
    enabled: Boolean(state.enabled),
    target: normalizeWebUiHiresfixAssistTarget(state.target),
  };
}

function parseResolutionText(value) {
  const match = String(value || '').match(/(\d+)\s*x\s*(\d+)/i);
  if (!match) return null;
  const width = parseInt(match[1], 10);
  const height = parseInt(match[2], 10);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
  return {width, height};
}

function normalizeResolutionPresetId(value) {
  const id = String(value || '').trim().toLowerCase().replace(/-/g, '_');
  return RESOLUTION_PRESET_MAP.has(id) ? id : 'standard';
}

function resolutionPresetDef(value) {
  return RESOLUTION_PRESET_MAP.get(normalizeResolutionPresetId(value)) || RESOLUTION_PRESET_MAP.get('standard');
}

function resolutionPresetResolutionOptions(mode = currentMode || modeSelect?.value || 'NAI') {
  const state = activeResolutionPresetState(mode);
  if (!state?.enabled) return null;
  return resolutionPresetDef(state.preset)?.resolutions || null;
}

function isResolutionPresetEnabled(mode = currentMode || modeSelect?.value || 'NAI') {
  return Boolean(activeResolutionPresetState(mode)?.enabled);
}

function resolutionPresetControlSets(mode = currentMode || modeSelect?.value || 'NAI') {
  const normalized = String(mode || '').toUpperCase();
  const controls = [];
  const seen = new Set();
  const addControls = (enabled, preset) => {
    if (!enabled && !preset) return;
    const key = preset || enabled;
    if (seen.has(key)) return;
    seen.add(key);
    controls.push({enabled, preset});
  };
  if (normalized === 'WEBUI') {
    addControls($('pWebuiResolutionPresetEnabled'), $('pWebuiResolutionPreset'));
  }
  if (normalized === 'COMFYUI') {
    addControls($('pComfyuiResolutionPresetEnabled'), $('pComfyuiResolutionPreset'));
  }
  document.querySelectorAll(`[data-resolution-preset-select="${normalized}"]`).forEach(preset => {
    const scope = preset.closest('[data-resolution-preset-mode]') || document;
    const enabled = scope.querySelector(`[data-resolution-preset-enabled="${normalized}"]`);
    addControls(enabled, preset);
  });
  return controls;
}

function resolutionPresetControls(mode = currentMode || modeSelect?.value || 'NAI') {
  return resolutionPresetControlSets(mode)[0] || {enabled: null, preset: null};
}

function ensureResolutionPresetOptions() {
  for (const mode of ['WEBUI', 'COMFYUI']) {
    for (const {preset} of resolutionPresetControlSets(mode)) {
      if (!preset) continue;
      const existing = Array.from(preset.options || []).map(option => option.value);
      if (existing.length === RESOLUTION_PRESET_DEFS.length && existing.every((value, index) => value === RESOLUTION_PRESET_DEFS[index].id)) {
        continue;
      }
      preset.innerHTML = RESOLUTION_PRESET_DEFS
        .map(item => `<option value="${item.id}">${item.label}</option>`)
        .join('');
    }
  }
}

function syncResolutionPresetControls(mode, enabled, presetId) {
  ensureResolutionPresetOptions();
  for (const {enabled: enabledEl, preset} of resolutionPresetControlSets(mode)) {
    if (enabledEl) enabledEl.checked = Boolean(enabled);
    if (preset) preset.value = normalizeResolutionPresetId(presetId);
    const scope = preset?.closest('[data-resolution-preset-mode]') || enabledEl?.closest('.resolution-preset-row');
    scope?.classList.toggle('active', Boolean(enabled));
  }
}

function activeResolutionPresetState(mode = currentMode || modeSelect?.value || 'NAI') {
  const normalized = String(mode || '').toUpperCase();
  if (normalized !== 'WEBUI' && normalized !== 'COMFYUI') return null;
  ensureResolutionPresetOptions();
  const {enabled, preset} = resolutionPresetControls(normalized);
  return {
    enabled: Boolean(enabled?.checked),
    preset: normalizeResolutionPresetId(preset?.value),
  };
}

function applyResolutionLabelToParams(params, label) {
  const parsed = parseResolutionText(label);
  if (!parsed) return false;
  params.resolution = label;
  params.width = parsed.width;
  params.height = parsed.height;
  return true;
}

function applyResolutionPresetToParams(params, mode, randomResolution) {
  const state = activeResolutionPresetState(mode);
  if (!state?.enabled) return false;
  const preset = resolutionPresetDef(state.preset);
  const candidates = preset?.resolutions || [];
  if (!candidates.length) return false;
  let label = candidates[0];
  if (randomResolution) {
    label = candidates[Math.floor(Math.random() * candidates.length)];
  } else if (params.resolution && candidates.includes(params.resolution)) {
    label = params.resolution;
  }
  params.resolution_preset_enabled = true;
  params.resolution_preset = preset.id;
  return applyResolutionLabelToParams(params, label);
}

function setResolutionPresetEnabled(mode, enabled) {
  if (String(mode || '').toUpperCase() === 'WEBUI' && enabled) {
    updateWebUiHiresfixAssistControls({enabled: false});
    setModuleParam('webui_hiresfix_assist', 'enabled', 'false');
    setWebUiHiresfixEnabled(false);
  }
  syncResolutionPresetControls(mode, enabled, activeResolutionPresetState(mode)?.preset || 'standard');
  refreshResolutionPresetDisplay(mode);
  setParam('resolution_preset_enabled', String(Boolean(enabled)));
}

function setResolutionPreset(mode, presetId) {
  const normalizedPreset = normalizeResolutionPresetId(presetId);
  if (String(mode || '').toUpperCase() === 'WEBUI') {
    updateWebUiHiresfixAssistControls({enabled: false});
    setModuleParam('webui_hiresfix_assist', 'enabled', 'false');
    setWebUiHiresfixEnabled(false);
  }
  syncResolutionPresetControls(mode, true, normalizedPreset);
  refreshResolutionPresetDisplay(mode);
  setParam('resolution_preset_enabled', 'true');
  setParam('resolution_preset', normalizedPreset);
}

function nearestWebUiHiresfixAssistResolution(width, height, target) {
  const targetSide = normalizeWebUiHiresfixAssistTarget(target);
  const targetPixels = targetSide * targetSide;
  const multiple = 64;
  const sourceWidth = Number(width);
  const sourceHeight = Number(height);
  if (!Number.isFinite(sourceWidth) || !Number.isFinite(sourceHeight) || sourceWidth <= 0 || sourceHeight <= 0) {
    return {width: targetSide, height: targetSide};
  }
  const sourceRatio = sourceWidth / sourceHeight;
  const idealWidth = Math.sqrt(targetPixels * sourceRatio);
  const idealHeight = Math.sqrt(targetPixels / sourceRatio);
  const nearbyMultiples = value => {
    const base = Math.floor(value / multiple) * multiple;
    return Array.from(new Set(Array.from({length: 8}, (_, index) => Math.max(multiple, base + ((index - 3) * multiple)))))
      .sort((a, b) => a - b);
  };
  const widthCandidates = nearbyMultiples(idealWidth);
  const heightCandidates = nearbyMultiples(idealHeight);
  let best = {width: targetSide, height: targetSide};
  let bestScore = null;
  const isBetterScore = (score, previous) => {
    if (!previous) return true;
    for (let index = 0; index < score.length; index += 1) {
      if (score[index] < previous[index]) return true;
      if (score[index] > previous[index]) return false;
    }
    return false;
  };
  for (const candidateWidth of widthCandidates) {
    for (const candidateHeight of heightCandidates) {
      const candidateRatio = candidateWidth / candidateHeight;
      const ratioDelta = Math.abs(Math.log(candidateRatio / sourceRatio));
      const areaDelta = Math.abs(Math.log((candidateWidth * candidateHeight) / targetPixels));
      const orientationPenalty = Number((sourceWidth >= sourceHeight) !== (candidateWidth >= candidateHeight));
      const dimensionDelta = Math.abs(candidateWidth - idealWidth) + Math.abs(candidateHeight - idealHeight);
      const score = [ratioDelta + areaDelta, orientationPenalty, areaDelta, Math.trunc(dimensionDelta)];
      if (isBetterScore(score, bestScore)) {
        bestScore = score;
        best = {width: candidateWidth, height: candidateHeight};
      }
    }
  }
  return best;
}

function getCurrentSelectedResolution() {
  return parseResolutionText(paramEls?.resolution?.value || qResolution?.value || '');
}

function getWebUiHiresfixAssistState() {
  return normalizeWebUiHiresfixAssistState(webUiHiresfixAssistState);
}

function setWebUiHiresfixEnabled(enabled) {
  const nextEnabled = Boolean(enabled);
  const enableHr = $('pEnableHr');
  if (enableHr) enableHr.checked = nextEnabled;
  setParam('enable_hr', String(nextEnabled));
}

function updateWebUiHiresfixAssistControls(state = null) {
  if (state) webUiHiresfixAssistState = normalizeWebUiHiresfixAssistState({...webUiHiresfixAssistState, ...state});
  const normalized = getWebUiHiresfixAssistState();
  if (normalized.enabled && isResolutionPresetEnabled('WEBUI')) {
    normalized.enabled = false;
    webUiHiresfixAssistState = normalized;
  }
  document.querySelectorAll('[data-webui-hiresfix-assist-enabled]').forEach(toggle => {
    if (toggle.checked !== normalized.enabled) toggle.checked = normalized.enabled;
  });
  document.querySelectorAll('[data-webui-hiresfix-assist-target]').forEach(button => {
    const active = normalizeWebUiHiresfixAssistTarget(button.dataset.webuiHiresfixAssistTarget) === normalized.target;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  document.querySelectorAll('.webui-hires-assist-row, .module-hiresfix-assist-row').forEach(row => {
    row.classList.toggle('active', normalized.enabled);
  });
  updateWebUiHrScaleHint();
  if (moduleBadges && typeof moduleBadges.updateWebUiHiresfixAssist === 'function') {
    moduleBadges.updateWebUiHiresfixAssist(normalized);
  }
}

function setWebUiHiresfixAssistEnabled(enabled) {
  if (enabled) {
    const presetState = activeResolutionPresetState('WEBUI');
    if (presetState?.enabled) {
      syncResolutionPresetControls('WEBUI', false, presetState.preset);
      refreshResolutionPresetDisplay('WEBUI');
      setParam('resolution_preset_enabled', 'false');
    }
  }
  updateWebUiHiresfixAssistControls({enabled});
  setWebUiHiresfixEnabled(Boolean(enabled));
  setModuleParam('webui_hiresfix_assist', 'enabled', String(Boolean(enabled)));
}

function setWebUiHiresfixAssistTarget(target) {
  const normalizedTarget = normalizeWebUiHiresfixAssistTarget(target);
  updateWebUiHiresfixAssistControls({target: normalizedTarget});
  setModuleParam('webui_hiresfix_assist', 'target', String(normalizedTarget));
}

function getWebUiHiresfixAssistBaseResolution() {
  const selected = getCurrentSelectedResolution();
  if (!selected) return null;
  const state = getWebUiHiresfixAssistState();
  if (!state.enabled) return selected;
  return nearestWebUiHiresfixAssistResolution(selected.width, selected.height, state.target);
}

function webUiHiresFinalSize(base, scale) {
  return {
    width: Math.max(1, Math.round(base.width * scale)),
    height: Math.max(1, Math.round(base.height * scale)),
  };
}

function fitWebUiHiresfixAssistScale(base, scale) {
  const maxPixels = 1536 * 1536;
  const original = webUiHiresFinalSize(base, scale);
  if (original.width * original.height <= maxPixels) return scale;

  let tenths = Math.max(10, Math.floor(scale * 10 + 1e-9) - 1);
  while (tenths > 10) {
    const candidate = tenths / 10;
    const size = webUiHiresFinalSize(base, candidate);
    if (size.width * size.height <= maxPixels) return candidate;
    tenths -= 1;
  }
  return 1;
}

function updateWebUiHrScaleHint() {
  const hint = $('webuiHrScaleHint');
  if (!hint) return;
  const base = getWebUiHiresfixAssistBaseResolution();
  const assistState = getWebUiHiresfixAssistState();
  const scale = Number($('pHrScale')?.value || 2);
  if (!base || !Number.isFinite(scale) || scale <= 0) {
    hint.textContent = '';
    hint.title = '';
    hint.classList.remove('warning');
    return;
  }
  const effectiveScale = assistState.enabled ? fitWebUiHiresfixAssistScale(base, scale) : scale;
  const {width: finalWidth, height: finalHeight} = webUiHiresFinalSize(base, effectiveScale);
  const text = `(${base.width} x ${base.height} to ${finalWidth} x ${finalHeight})`;
  const exceedsSafeArea = finalWidth * finalHeight > 1536 * 1536;
  hint.textContent = text;
  hint.title = effectiveScale === scale
    ? text
    : `${text} / HR Scale ${scale.toFixed(1)} -> ${effectiveScale.toFixed(1)}`;
  hint.classList.toggle('warning', exceedsSafeArea);
  refreshHiresfixResolutionDisplay();
}

function collectWebUiHiresfixAssistOverrides(mode = currentMode || modeSelect?.value || 'NAI') {
  if (String(mode || '').toUpperCase() !== 'WEBUI') return {};
  const state = getWebUiHiresfixAssistState();
  return {
    webui_hiresfix_assist: Boolean(state.enabled),
    webui_hiresfix_assist_target: state.target,
  };
}

function getWebUiResultEnhanceSettings() {
  const hrUpscaler = $('pHrUpscaler');
  return {
    enable_hr: Boolean($('pEnableHr')?.checked),
    hr_scale: parseParamNumber($('pHrScale')?.value, 2.0),
    hr_upscaler: hrUpscaler?.value || 'Latent (nearest-exact)',
    denoising_strength: parseParamNumber($('pDenoise')?.value, 0.5),
    hires_steps: Math.trunc(parseParamNumber($('pHiresSteps')?.value, 10)),
    hr_cfg: parseParamNumber($('pHrCfg')?.value, 7.0),
    ...collectWebUiHiresfixAssistOverrides('WEBUI'),
  };
}

function getWebUiResultEnhanceUpscalerOptions() {
  return Array.from($('pHrUpscaler')?.options || [])
    .map(option => option.value)
    .filter(value => String(value || '').trim());
}

function setWebUiResultEnhanceSetting(key, value) {
  const normalizedKey = String(key || '');
  let normalizedValue = value;
  if (normalizedKey === 'hr_upscaler') {
    const select = $('pHrUpscaler');
    normalizedValue = String(value || '').trim();
    if (select && normalizedValue) {
      const hasOption = Array.from(select.options || []).some(option => option.value === normalizedValue);
      if (!hasOption) {
        const option = document.createElement('option');
        option.value = normalizedValue;
        option.textContent = normalizedValue;
        select.appendChild(option);
      }
      select.value = normalizedValue;
    }
  } else if (normalizedKey === 'hr_scale') {
    const input = $('pHrScale');
    normalizedValue = String(parseParamNumber(value, 2.0));
    if (input) input.value = normalizedValue;
  } else if (normalizedKey === 'denoising_strength') {
    const input = $('pDenoise');
    normalizedValue = String(parseParamNumber(value, 0.5));
    if (input) input.value = normalizedValue;
  } else if (normalizedKey === 'hires_steps') {
    const input = $('pHiresSteps');
    normalizedValue = String(Math.trunc(parseParamNumber(value, 10)));
    if (input) input.value = normalizedValue;
  } else if (normalizedKey === 'hr_cfg') {
    const input = $('pHrCfg');
    normalizedValue = String(parseParamNumber(value, 7.0));
    if (input) input.value = normalizedValue;
  } else {
    return;
  }
  setParam(normalizedKey, normalizedValue);
  if (normalizedKey === 'hr_scale') updateWebUiHrScaleHint();
}

function _compactHiresPreviewText(text, limit) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  return normalized.length > limit ? `${normalized.slice(0, Math.max(0, limit - 3))}...` : normalized;
}

function refreshHiresPresetSwapOptions(m) {
  const select = document.getElementById('pHiresPresetSwap');
  if (!select) return;
  const prevValue = _hiresPresetSwapValueKnown ? _hiresPresetSwapValue : select.value;
  const presets = Array.isArray(m?.webui_preset_options)
    ? m.webui_preset_options
    : (Array.isArray(m?.preset_options) ? m.preset_options : []);
  const summaries = Array.isArray(m?.webui_preset_summaries)
    ? m.webui_preset_summaries
    : (Array.isArray(m?.preset_summaries) ? m.preset_summaries : []);
  const summaryMap = new Map();
  summaries.forEach(s => {
    if (!s || !s.name) return;
    const mode = String(s.api_mode || '').toUpperCase();
    if (mode && mode !== 'WEBUI') return;
    summaryMap.set(String(s.name), s);
  });
  // 와일드카드 정합성 평가용 raw 본문 캐시 — 잘리지 않은 전문을 보관.
  _hiresPresetFullTextCache = new Map();
  _hiresCurrentPresetName = String(m?.preset || '');
  const currentSummary = _hiresCurrentPresetName && summaryMap.get(_hiresCurrentPresetName);
  _hiresPresetFullTextCache.set('__main__', currentSummary ? {
    pre: String(currentSummary.pre_prompt_preview || ''),
    post: String(currentSummary.post_prompt_preview || ''),
  } : { pre: '', post: '' });

  const opts = ['<option value="">현재 프리셋 사용</option>'];
  const validValues = new Set(['']);
  for (const raw of presets) {
    const name = String(raw || '');
    if (!name || name === '*randomized' || name === '(프리셋 없음)') continue;
    const s = summaryMap.get(name);
    if (s && String(s.api_mode || '').toUpperCase() !== 'WEBUI') continue;
    if (!s && Array.isArray(m?.preset_summaries)) continue;
    validValues.add(name);
    if (s) {
      _hiresPresetFullTextCache.set(name, {
        pre: String(s.pre_prompt_preview || ''),
        post: String(s.post_prompt_preview || ''),
      });
    }
    const attrs = s ? [
      `data-preview-name="${escHtml(s.name || name)}"`,
      `data-preview-mode="${escHtml(s.api_mode || '')}"`,
      `data-preview-prefix="${escHtml(_compactHiresPreviewText(s.pre_prompt_preview, 1200))}"`,
      `data-preview-description="${escHtml(_compactHiresPreviewText(s.description, 300))}"`,
      `data-preview-thumbnail="${escHtml(s.thumbnail_url || '')}"`,
    ].join(' ') : '';
    opts.push(`<option value="${escHtml(name)}" ${attrs}>${escHtml(name)}</option>`);
  }
  select.innerHTML = opts.join('');
  select.value = validValues.has(prevValue) ? prevValue : '';
  _hiresPresetSwapValue = select.value;
  _hiresPresetSwapValueKnown = true;
  refreshHiresPresetMismatchBadge();
  refreshHiresEditButtonState();
}

// Hires Preset Overlay editor — 전역 상태
let _hiresPresetFullTextCache = new Map();
let _hiresCurrentPresetName = '';
let _hiresOverlayEditorPreset = '';
let _hiresOverlayOverlayMap = new Map(); // preset_name → overlay body (서버 응답 캐시)
let _hiresPresetSwapValue = '';
let _hiresPresetSwapValueKnown = false;

function refreshHiresEditButtonState() {
  const btn = document.getElementById('hiresPresetEditBtn');
  const sel = document.getElementById('pHiresPresetSwap');
  if (!btn || !sel) return;
  btn.disabled = !sel.value;
}

// __wildcard__ 토큰 추출 (단순 표면 비교용 — fuzzy match 는 서버 와일드카드 해석에 위임)
function extractWildcardTokens(text) {
  if (!text) return new Set();
  const tokens = new Set();
  // 양옆 __ 로 감싸진 토큰. *prefix / $master:slave 같은 변종 prefix 도 핵심 키만 추출.
  // lazy 본문은 \s, , 만 금지하고 단일 underscore 는 허용 (예: __original_character__).
  // 본문 안에 또 다른 __ 가 들어가면 닫는 구분자로 우선 매칭 (lazy quantifier 보장).
  const re = /__(\*?\$?[^\s,_][^\s,]*?)__/g;
  let match;
  while ((match = re.exec(text)) !== null) {
    let key = match[1];
    // 종속 와일드카드: $master:slave → slave 만
    if (key.startsWith('$')) {
      const colonIdx = key.indexOf(':');
      if (colonIdx > 0) key = key.slice(colonIdx + 1);
      else key = key.slice(1);
    }
    if (key.startsWith('*')) key = key.slice(1);
    if (key) tokens.add(key);
  }
  return tokens;
}

function computeHiresWildcardDiff(mainPresetName, swapPresetName) {
  const swap = _hiresPresetFullTextCache.get(swapPresetName);
  const main = _hiresPresetFullTextCache.get('__main__');
  if (!swap) return { added: [], missing: [] };
  // Overlay 가 있으면 그것을 우선 사용
  const overlay = _hiresOverlayOverlayMap.get(swapPresetName);
  const swapPre = overlay ? overlay.prefix_prompt : swap.pre;
  const swapPost = overlay ? overlay.postfix_prompt : swap.post;
  const mainTokens = main ? new Set([
    ...extractWildcardTokens(main.pre),
    ...extractWildcardTokens(main.post),
  ]) : new Set();
  const swapTokens = new Set([
    ...extractWildcardTokens(swapPre),
    ...extractWildcardTokens(swapPost),
  ]);
  const added = [...swapTokens].filter(t => !mainTokens.has(t));
  const missing = [...mainTokens].filter(t => !swapTokens.has(t));
  return { added, missing };
}

function refreshHiresPresetMismatchBadge() {
  const anchor = document.getElementById('hiresPresetMismatchAnchor');
  const sel = document.getElementById('pHiresPresetSwap');
  if (!anchor || !sel) return;
  anchor.innerHTML = '';
  const swapName = sel.value;
  if (!swapName) return;
  const { added, missing } = computeHiresWildcardDiff(_hiresCurrentPresetName, swapName);
  if (added.length === 0 && missing.length === 0) return;

  const count = added.length + missing.length;
  const badge = document.createElement('div');
  badge.className = 'webui-hires-mismatch-badge';
  badge.title = '와일드카드 정합성 경고 (호버해서 상세 확인)';
  badge.textContent = String(count);

  const tooltip = document.createElement('div');
  tooltip.className = 'webui-hires-mismatch-tooltip';
  tooltip.hidden = true;
  const sections = [];
  if (added.length) {
    sections.push(`
      <div class="group-added">
        <span class="group-title">추가됨 — Hires 에서 새로 롤됨</span>
        <ul class="group-list">${added.map(t => `<li><span class="wc-token">__${escHtml(t)}__</span></li>`).join('')}</ul>
      </div>`);
  }
  if (missing.length) {
    sections.push(`
      <div class="group-missing">
        <span class="group-title">누락됨 — 메인의 효과가 Hires 에서 사라짐</span>
        <ul class="group-list">${missing.map(t => `<li><span class="wc-token">__${escHtml(t)}__</span></li>`).join('')}</ul>
      </div>`);
  }
  tooltip.innerHTML = sections.join('');

  badge.addEventListener('mouseenter', () => { tooltip.hidden = false; });
  badge.addEventListener('mouseleave', () => { tooltip.hidden = true; });
  badge.addEventListener('focus', () => { tooltip.hidden = false; });
  badge.addEventListener('blur', () => { tooltip.hidden = true; });
  badge.tabIndex = 0;

  anchor.append(badge, tooltip);
}

function refreshHiresOverlayWildcardDiff(presetName) {
  const box = document.getElementById('hiresOverlayWildcardDiff');
  if (!box) return;
  const name = String(presetName || '');
  if (!name) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  const { added, missing } = computeHiresWildcardDiff(_hiresCurrentPresetName, name);
  if (added.length === 0 && missing.length === 0) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  const sections = [`<div class="wcdiff-headline">와일드카드 정합성 경고 · ${added.length + missing.length}건</div>`];
  if (added.length) {
    sections.push(`
      <div class="group-added">
        <span class="group-title">추가됨 — Hires 에서 새로 롤됨</span>
        <ul class="group-list">${added.map(t => `<li><span class="wc-token">__${escHtml(t)}__</span></li>`).join('')}</ul>
      </div>`);
  }
  if (missing.length) {
    sections.push(`
      <div class="group-missing">
        <span class="group-title">누락됨 — 메인의 효과가 Hires 에서 사라짐</span>
        <ul class="group-list">${missing.map(t => `<li><span class="wc-token">__${escHtml(t)}__</span></li>`).join('')}</ul>
      </div>`);
  }
  box.innerHTML = sections.join('');
  box.hidden = false;
}

function _loadHiresOverlayForPreset(preset) {
  _hiresOverlayEditorPreset = preset;
  document.getElementById('hiresOverlayTitle').textContent = `Hires Overlay — ${preset}`;
  document.getElementById('hiresOverlayStatus').textContent = '서버에서 로드 중…';
  ['hiresOverlayPrefix', 'hiresOverlayPostfix', 'hiresOverlayNegative'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  refreshHiresOverlayWildcardDiff(preset);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'read_hires_preset_overlay', preset_name: preset}));
  }
}

function openHiresOverlayEditor() {
  const sel = document.getElementById('pHiresPresetSwap');
  const preset = sel?.value || '';
  if (!preset) {
    showToast('먼저 Hires 패스에 사용할 프리셋을 선택하세요.', 'warning');
    return;
  }
  document.getElementById('hiresOverlayPopup').classList.add('open');
  _loadHiresOverlayForPreset(preset);
}

function syncHiresOverlayEditorIfOpen(newPresetName) {
  const popup = document.getElementById('hiresOverlayPopup');
  if (!popup || !popup.classList.contains('open')) return;
  const preset = String(newPresetName || '');
  if (!preset) {
    closeHiresOverlayEditor();
    return;
  }
  if (preset === _hiresOverlayEditorPreset) return;
  _loadHiresOverlayForPreset(preset);
}

function closeHiresOverlayEditor() {
  document.getElementById('hiresOverlayPopup').classList.remove('open');
  _hiresOverlayEditorPreset = '';
  const box = document.getElementById('hiresOverlayWildcardDiff');
  if (box) { box.hidden = true; box.innerHTML = ''; }
}

function _readHiresOverlayBodyFromUI() {
  return {
    prefix_prompt: document.getElementById('hiresOverlayPrefix')?.value || '',
    postfix_prompt: document.getElementById('hiresOverlayPostfix')?.value || '',
    negative_prompt: document.getElementById('hiresOverlayNegative')?.value || '',
  };
}

function saveHiresOverlayEditor() {
  const preset = _hiresOverlayEditorPreset;
  if (!preset) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('WS 연결이 끊겨 저장할 수 없습니다.', 'error');
    return;
  }
  ws.send(JSON.stringify({
    type: 'write_hires_preset_overlay',
    preset_name: preset,
    action: 'save',
    body: _readHiresOverlayBodyFromUI(),
  }));
  // 저장 성공 응답이 오면 모달은 닫지 않고 status 만 갱신.
}

function resetHiresOverlayEditor() {
  const preset = _hiresOverlayEditorPreset;
  if (!preset) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('WS 연결이 끊겨 리셋할 수 없습니다.', 'error');
    return;
  }
  ws.send(JSON.stringify({
    type: 'write_hires_preset_overlay',
    preset_name: preset,
    action: 'reset',
  }));
}

function _applyHiresOverlayResponse(payload) {
  const preset = String(payload?.preset_name || '');
  const original = payload?.original || {};
  const overlay = payload?.overlay; // null 이면 sidecar 없음
  // 캐시 갱신
  if (overlay) {
    _hiresOverlayOverlayMap.set(preset, {
      prefix_prompt: String(overlay.prefix_prompt || ''),
      postfix_prompt: String(overlay.postfix_prompt || ''),
      negative_prompt: String(overlay.negative_prompt || ''),
    });
  } else {
    _hiresOverlayOverlayMap.delete(preset);
  }
  // 모달이 이 프리셋을 편집 중이면 UI 채우기
  if (_hiresOverlayEditorPreset === preset) {
    const fillFrom = overlay || original;
    const pre = document.getElementById('hiresOverlayPrefix');
    const post = document.getElementById('hiresOverlayPostfix');
    const neg = document.getElementById('hiresOverlayNegative');
    if (pre) pre.value = String(fillFrom.prefix_prompt || '');
    if (post) post.value = String(fillFrom.postfix_prompt || '');
    if (neg) neg.value = String(fillFrom.negative_prompt || '');
    const status = document.getElementById('hiresOverlayStatus');
    if (status) {
      if (overlay) {
        status.textContent = '● Overlay 활성 (sidecar 저장됨)';
        status.classList.add('overlay-active');
      } else {
        status.textContent = '○ Overlay 없음 — 원본 프리셋 표시 중';
        status.classList.remove('overlay-active');
      }
    }
  }
  // mismatch 배지 재계산
  refreshHiresPresetMismatchBadge();
  // 편집 모달 안의 wildcard diff 도 overlay 반영 후 재계산
  if (_hiresOverlayEditorPreset === preset) {
    refreshHiresOverlayWildcardDiff(preset);
  }
}

function currentComfyUiSamplingMode() {
  return $('flagAnima')?.classList.contains('on')
    ? 'anima'
    : ($('flagVpred')?.classList.contains('on') ? 'v_prediction' : 'eps');
}

const COMFYUI_FREE_BYPASS_TEXT = 'Ignore and bypass';
const COMFYUI_FREE_SEED_TEXT = 'Forced always random';
const COMFYUI_FREE_LOCKED_PARAM_KEYS = new Set(['model', 'sampler', 'scheduler', 'steps', 'cfg_scale', 'seed', 'sampling_mode', 'rescale_cfg']);

function buildWebGenerationOverrides(prompt, negativePrompt) {
  const overrides = _collectCurrentParams();
  overrides.input = prompt;
  overrides.negative_prompt = negativePrompt;
  overrides._raw_input = prompt;
  overrides._remote_web_session_params = true;
  overrides._remote_queue_source = 'Web';
  return overrides;
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
const fnMenuTrigger = $('fnMenuTrigger');
const fnMenu = $('fnMenu');
const translatorPopup = $('translatorPopup');
const translatorInput = $('translatorInput');
const translatorOutput = $('translatorOutput');
const resultViewer = $('resultViewer');
const metaRow      = $('metaRow');
const promptTokenLabel = $('promptTokenLabel');
const negativeTokenLabel = $('negativeTokenLabel');
const paramFlags   = $('paramFlags');
const paramEls = {
  model: $('pModel'), sampler: $('pSampler'), scheduler: $('pScheduler'),
  resolution: $('pResolution'), steps: $('pSteps'), cfg_scale: $('pCfgScale'),
  cfg_rescale: $('pCfgRescale'), seed: $('pSeed'),
  hr_scale: $('pHrScale'), hr_upscaler: $('pHrUpscaler'),
  denoising_strength: $('pDenoise'), hires_steps: $('pHiresSteps'), hr_cfg: $('pHrCfg'),
};
const RESOLUTION_PRESET_DEFS = [
  {id: 'draft', label: '512^2', resolutions: ['512 x 512', '448 x 576', '448 x 640', '384 x 640', '576 x 448', '640 x 448', '640 x 384']},
  {id: 'compact', label: '768^2', resolutions: ['768 x 768', '704 x 832', '704 x 896', '640 x 960', '832 x 704', '896 x 704', '960 x 640']},
  {id: 'standard', label: '1024^2', resolutions: ['1024 x 1024', '960 x 1088', '896 x 1152', '832 x 1216', '1088 x 960', '1152 x 896', '1216 x 832']},
  {id: 'hd', label: '1152^2', resolutions: ['1152 x 1152', '1088 x 1216', '1024 x 1280', '960 x 1408', '1216 x 1088', '1280 x 1024', '1408 x 960']},
  {id: 'hd_plus', label: '1216^2', resolutions: ['1216 x 1216', '1152 x 1280', '1088 x 1344', '960 x 1472', '1280 x 1152', '1344 x 1088', '1472 x 960']},
  {id: 'quality', label: '1344^2', resolutions: ['1344 x 1344', '1280 x 1472', '1216 x 1536', '1088 x 1600', '1472 x 1280', '1536 x 1216', '1600 x 1088']},
  {id: 'max', label: '1536^2', resolutions: ['1536 x 1536', '1408 x 1600', '1344 x 1728', '1216 x 1792', '1600 x 1408', '1728 x 1344', '1792 x 1216']},
];
const RESOLUTION_PRESET_MAP = new Map(RESOLUTION_PRESET_DEFS.map(item => [item.id, item]));
const qResolution = $('qResolution');
const qRndRes = $('qRndRes');
const qAutoRes = $('qAutoRes');
let baseResolutionOptions = [];
let baseResolutionValue = '';
let syncingParams = false;
const resultInfoContent = $('resultInfoContent');
const statsGenCount  = $('statsGenCount');
const statsSave      = $('statsSave');
const resultUnsavedActions = $('resultUnsavedActions');
const resultUnsavedSaveBtn = $('resultUnsavedSaveBtn');
const resultUnsavedDeleteBtn = $('resultUnsavedDeleteBtn');
const optBoxes = {
  prompt_fixed: $('optPromptFixed'),
  auto_generate: $('optAutoGen'),
  wildcard_standalone: $('optWcStandalone'),
};
const pendingOptionValues = Object.create(null);
let translatorPopupRequestId = '';
let translatorPopupRequestText = '';
let translatorPopupTimer = null;
let translatorPopupSeq = 0;
let translatorPopupComposing = false;
const translatorHangulRe = /[가-힣ㄱ-ㅎㅏ-ㅣ]/;
const TRANSLATOR_AUTO_TRANSLATE_MS = 600;
// ---- Result history wrappers ----
const mobileHistoryMediaQuery = window.matchMedia('(max-width: 767px)');
function isMobileHistoryViewport() {
  return mobileHistoryMediaQuery.matches;
}
function syncMobileHistoryRailOpen(open) {
  document.body.classList.toggle('mobile-history-open', Boolean(open) && isMobileHistoryViewport());
}
function setHistoryRailCollapsed(collapsed, persist = true) {
  if (!resultHistory) return;
  resultHistory.setRailCollapsed(collapsed, persist);
  syncMobileHistoryRailOpen(!collapsed);
}
function toggleHistoryRail() {
  const viewerPanel = $('viewerPanel');
  const nextCollapsed = !viewerPanel?.classList.contains('collapsed');
  setHistoryRailCollapsed(nextCollapsed);
}
function toggleMobileHistoryRail() {
  setHistoryRailCollapsed(document.body.classList.contains('mobile-history-open'), false);
}
function initHistoryRail() {
  if (resultHistory) resultHistory.init();
  if (isMobileHistoryViewport()) setHistoryRailCollapsed(true, false);
}

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
  if (characterViewerControl && typeof characterViewerControl.handleResultBlob === 'function') {
    characterViewerControl.handleResultBlob(data);
  }
  preview.src = url;
  preview.dataset.source = 'current';
  preview.dataset.path = '';
  preview.classList.add('show');
  emptyMsg.style.display = 'none';
  scheduleResultUnsavedActionRefresh(180);
  const pendingPresetRequestId = String(presetGenerationPending?.requestId || '');
  const imagePresetRequestId = String(
    latestImageMeta?.remote_preset_request_id
    || latestImageMeta?.event_preset_request_id
    || ''
  );
  const isPendingPresetResult = pendingPresetRequestId
    ? imagePresetRequestId === pendingPresetRequestId
    : (!!presetGenerationPending && (
      !!latestImageMeta?.remote_preset_request
      || !!latestImageMeta?.event_preset_request
    ));
  if (isPendingPresetResult) {
    clearPresetGenerationOptions({autoGenerate: false});
    eventPresetPanel?.focusResultImage?.();
    presetGenerationPending = null;
  }
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

function schedulePromptHighlightIndexLoad(delayMs = 5000) {
  if (promptHighlightIndexPromise) return;
  if (promptHighlightIndexTimer) clearTimeout(promptHighlightIndexTimer);
  promptHighlightIndexTimer = setTimeout(() => {
    promptHighlightIndexTimer = null;
    if (awaitingMyRandom || pendingRandomRequestId) {
      schedulePromptHighlightIndexLoad(1000);
      return;
    }
    loadPromptHighlightIndex();
  }, Math.max(250, Number(delayMs) || 5000));
}

function onLazyIndicesReady() {
  finalizeBoot();
  schedulePromptHighlightIndexLoad();
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
  scheduleInitialHistoryRefresh();
  scheduleInitialStateRefresh();
  const cachedPe = moduleStateCache.get('prompt_engineering');
  if (cachedPe) refreshHiresPresetSwapOptions(cachedPe);
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
  clear_api_result: onClearApiResult,
  setup_blocked: onSetupBlocked,
  probe_result: onProbeResult,
  anlas_update: onAnlasUpdate,
  module_state: onModuleState,
  hires_preset_overlay: _applyHiresOverlayResponse,
  prompt_engineering_preset_thumbnail_updated: onPromptEngineeringPresetThumbnailUpdated,
  search_state: onSearchState,
  rating_update: onRatingUpdate,
  search_progress: onSearchProgress,
  depth_state: onDepthState,
  tag_search_result: onTagSearchResult,
  tag_lookup_result: onTagLookupResult,
  autocomplete_result: onAutocompleteResult,
  translation_result: onTranslationResult,
  tag_filter_result: onTagFilterResult,
  tag_filter_assigned: onTagFilterAssigned,
  tag_filter_update: onTagFilterUpdate,
  tag_filter_ac_result: onTagFilterAcResult,
  storage_list: onStorageList,
  wildcard_manager: onWildcardManager,
  filter_reset: onFilterReset,
  toast: m => showToast(m.message, m.level || 'success'),
  character_viewer_error: m => {
    if (characterViewerControl && typeof characterViewerControl.handleGenerationError === 'function') {
      characterViewerControl.handleGenerationError(m);
    } else {
      showToast(m.message || 'Character Viewer generation failed', 'error');
    }
  },
  event_preset_generation_error: onEventPresetGenerationError,
  preset_generation_error: onEventPresetGenerationError,
  load_prompt: m => onLoadPrompt(m.prompt),
  viewer_new_image: onViewerNewImage,
  viewer_history_removed: onViewerHistoryRemoved,
  viewer_history_cleared: onViewerHistoryCleared,
  session: onSession,
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
        scheduleInitialStateRefresh();
        // probe 는 api_status 첫 수신 시점에 1회 실행 (updateApiStatus 내부에서 트리거).
      },
      onClose: () => {
        if (initialStateRefreshTimer) {
          clearTimeout(initialStateRefreshTimer);
          initialStateRefreshTimer = null;
        }
        if (promptHighlightIndexTimer) {
          clearTimeout(promptHighlightIndexTimer);
          promptHighlightIndexTimer = null;
        }
        if (initialHistoryRefreshTimer) {
          clearTimeout(initialHistoryRefreshTimer);
          initialHistoryRefreshTimer = null;
        }
        // 재연결 사이클을 위해 boot finalize 상태 리셋 (다음 init_complete 가 다시 시퀀스 시작)
        resetBootIndicatorState();
        setBootIndicator('Reconnecting…', 20, false);
        setLauncherConn(false);
        modeSwitching = false;
        if (modeSelect) modeSelect.disabled = true;
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
  latestImageMeta = m && typeof m === 'object' ? m : null;
  updateMetaChips(m);
  if (artistThumbControl && typeof artistThumbControl.handleResultMeta === 'function') {
    artistThumbControl.handleResultMeta(m);
  }
  if (characterViewerControl && typeof characterViewerControl.handleResultMeta === 'function') {
    characterViewerControl.handleResultMeta(m);
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

function requestResultEnhanceFromContext(context = {}) {
  if (!resultEnhance) {
    showToast('Enhance is not ready', 'error');
    return;
  }
  const capabilities = context?.capabilities || {};
  resultEnhance.request(enhanceMetaFromAsset(context, {
    can_enhance: Boolean(context?.can_enhance ?? context?.canEnhance ?? capabilities.enhance),
  }));
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

function onResultHistorySelectionChanged(relPath = '') {
  updateResultEnhanceForSavedPath(relPath);
  scheduleResultUnsavedActionRefresh();
}

function activeResultAssetUrl() {
  if (!preview || !preview.classList.contains('show')) return '';
  const source = String(preview.dataset?.source || '').toLowerCase();
  const path = String(preview.dataset?.path || '');
  if (source === 'saved' && path) {
    const params = new URLSearchParams({path});
    return '/api/result/asset/saved?' + params.toString();
  }
  return '/api/result/asset/current';
}

function isUnsavedHistoryAsset(asset) {
  if (!asset || typeof asset !== 'object') return false;
  const path = String(asset.path || '');
  const filePath = String(asset.file_path || asset.filePath || '');
  return Boolean(asset.has_image ?? asset.hasImage)
    && path.startsWith('__history_item__/')
    && !filePath;
}

function setResultUnsavedActionBusy(busy) {
  resultUnsavedActionBusy = !!busy;
  if (resultUnsavedSaveBtn) resultUnsavedSaveBtn.disabled = resultUnsavedActionBusy;
  if (resultUnsavedDeleteBtn) resultUnsavedDeleteBtn.disabled = resultUnsavedActionBusy;
}

function renderResultUnsavedActions(asset = null) {
  resultUnsavedActionAsset = asset;
  const visible = isUnsavedHistoryAsset(asset);
  if (resultUnsavedActions) resultUnsavedActions.hidden = !visible;
  if (!visible) setResultUnsavedActionBusy(false);
}

async function refreshResultUnsavedActions() {
  if (!resultUnsavedActions) return;
  const url = activeResultAssetUrl();
  const requestId = ++resultUnsavedActionRequestId;
  if (!url) {
    renderResultUnsavedActions(null);
    return;
  }
  try {
    const response = await fetch(url, {cache: 'no-store'});
    if (requestId !== resultUnsavedActionRequestId) return;
    if (!response.ok) {
      renderResultUnsavedActions(null);
      return;
    }
    renderResultUnsavedActions(await response.json());
  } catch (error) {
    if (requestId === resultUnsavedActionRequestId) renderResultUnsavedActions(null);
  }
}

function scheduleResultUnsavedActionRefresh(delay = 120) {
  if (resultUnsavedActionTimer) clearTimeout(resultUnsavedActionTimer);
  resultUnsavedActionTimer = setTimeout(() => {
    resultUnsavedActionTimer = null;
    void refreshResultUnsavedActions();
  }, delay);
}

function resultHistoryActionPayload(asset = resultUnsavedActionAsset) {
  return {
    source: asset?.source || (preview?.dataset?.source || 'current'),
    path: asset?.path || preview?.dataset?.path || '',
    file_path: asset?.file_path || asset?.filePath || '',
    label: asset?.label || 'Result Image',
  };
}

async function saveDisplayedHistoryImage() {
  if (!isUnsavedHistoryAsset(resultUnsavedActionAsset) || resultUnsavedActionBusy) return;
  setResultUnsavedActionBusy(true);
  try {
    const response = await fetch('/api/result/action/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(resultHistoryActionPayload()),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    renderResultUnsavedActions(data.asset || null);
    if (data.asset?.path) updateResultEnhanceForSavedPath(data.asset.path);
    showToast('Image saved to history folder', 'success');
  } catch (error) {
    console.error('Result history save failed', error);
    showToast(error.message || 'Image save failed', 'error');
  } finally {
    setResultUnsavedActionBusy(false);
    scheduleResultUnsavedActionRefresh(250);
  }
}

async function deleteDisplayedHistoryImage() {
  if (!isUnsavedHistoryAsset(resultUnsavedActionAsset) || resultUnsavedActionBusy) return;
  const deletedPath = String(resultUnsavedActionAsset.path || '');
  const deletingDisplayedImage = preview?.dataset?.source === 'current' || preview?.dataset?.path === deletedPath;
  setResultUnsavedActionBusy(true);
  try {
    const response = await fetch('/api/result/action/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(resultHistoryActionPayload()),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    renderResultUnsavedActions(null);
    if (resultHistory && data.rel_path) resultHistory.onRemoved(data);
    if (deletingDisplayedImage) {
      preview.removeAttribute('src');
      preview.classList.remove('show');
      preview.dataset.path = '';
      emptyMsg.style.display = '';
      if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
      if (resultEnhance) resultEnhance.clearCurrentMeta();
    }
    showToast('History item deleted', 'success');
  } catch (error) {
    console.error('Result history delete failed', error);
    showToast(error.message || 'History delete failed', 'error');
  } finally {
    setResultUnsavedActionBusy(false);
    scheduleResultUnsavedActionRefresh(250);
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

function createRandomRequestId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  randomRequestSerial += 1;
  return `random-${Date.now().toString(36)}-${randomRequestSerial.toString(36)}`;
}

function randomRequestIdFromMessage(message = {}) {
  return String(
    message.random_request_id
    || message.remote_random_request_id
    || message.requestId
    || ''
  ).trim();
}

function isExpectedRandomPrompt(message = {}) {
  const requestId = randomRequestIdFromMessage(message);
  if (requestId) return !!pendingRandomRequestId && requestId === pendingRandomRequestId;
  return awaitingMyRandom;
}

function unlockRandomButton({clearRequest = true} = {}) {
  awaitingMyRandom = false;
  if (clearRequest) pendingRandomRequestId = '';
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

function resolutionLabelFromMessage(message = {}) {
  if (message.resolution) return String(message.resolution);
  const detected = message.detected_resolution;
  if (detected && typeof detected === 'object') {
    const width = Number(detected.width ?? detected[0]);
    const height = Number(detected.height ?? detected[1]);
    if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
      return `${Math.trunc(width)} x ${Math.trunc(height)}`;
    }
  }
  return '';
}

function applyGeneratedResolutionUpdate(message = {}) {
  const label = resolutionLabelFromMessage(message);
  if (!label) return;
  ensureSelectValue(paramEls.resolution, label);
  ensureSelectValue(qResolution, label);
  paramEls.resolution.value = label;
  qResolution.value = label;
  baseResolutionValue = label;
  refreshResolutionPresetDisplay(currentMode || modeSelect?.value || 'NAI', label);
  updateWebUiHrScaleHint();
}

function hasPromptEngineeringDebugSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return false;
  const sourceInfo = snapshot.source_info || {};
  const filterLog = Array.isArray(snapshot.filter_log) ? snapshot.filter_log : [];
  const implicationInfo = Array.isArray(snapshot.implication_info) ? snapshot.implication_info : [];
  const e621Results = Array.isArray(snapshot.e621_info?.results) ? snapshot.e621_info.results : [];
  return Boolean(
    filterLog.length
    || implicationInfo.length
    || e621Results.length
    || Object.values(sourceInfo).some(value => value != null && String(value).trim() !== '')
  );
}

function applyPromptEngineeringDebugSnapshot(snapshot) {
  if (!hasPromptEngineeringDebugSnapshot(snapshot)) return;
  const currentState = cloneModuleState(moduleStateCache.get('prompt_engineering') || lastPromptEngineeringState) || {
    type: 'module_state',
    module_id: 'prompt_engineering',
    available: true,
    runtime: 'web',
  };
  currentState.debug_snapshot = snapshot;
  moduleStateCache.set('prompt_engineering', currentState);
  lastPromptEngineeringState = currentState;
  syncPromptEngineeringPopups();
}

function updatePromptOnly(messageOrPrompt, sourceArg) {
  const message = (typeof messageOrPrompt === 'object' && messageOrPrompt !== null)
    ? messageOrPrompt
    : {prompt: messageOrPrompt, source: sourceArg};
  const prompt = message.prompt == null ? '' : String(message.prompt);
  const source = message.source;
  const isPresetSource = source === 'event_preset' || source === 'preset';
  const acceptsBootstrapPrompt = source === 'bootstrap_random';
  const acceptsRandomPrompt = source === 'random' && isExpectedRandomPrompt(message);
  const acceptsGeneratedPrompt = (
    acceptsBootstrapPrompt ||
    acceptsRandomPrompt
    || isPresetSource
    || source === 'auto_generate'
    || source === 'result_reroll'
  );
  if (!prompt && !acceptsGeneratedPrompt) return;
  const messagePresetRequestId = String(
    source === 'preset'
      ? (message.remote_preset_request_id || message.requestId || '')
      : (message.event_preset_request_id || message.requestId || '')
  );
  if (
    isPresetSource
    && presetGenerationPending
    && (
      !String(presetGenerationPending.requestId || '')
      || messagePresetRequestId === String(presetGenerationPending.requestId || '')
    )
  ) {
    clearPresetGenerationOptions({autoGenerate: false});
  }
  // 명시적인 prompt 생성 이벤트는 서버의 generation state가 authoritative하다.
  if (acceptsGeneratedPrompt) {
    if (source === 'random') unlockRandomButton();
    if (promptSendTimer) {
      clearTimeout(promptSendTimer);
      promptSendTimer = null;
    }
    _localPromptDirty = false;
    deferredPromptSync = null;
    syncingPrompt = true;
    promptEdit.value = prompt;
    syncingPrompt = false;
    applyGeneratedResolutionUpdate(message);
    updatePromptHighlight();
    applyPromptHighlightState();
    applyPromptTokenPayload(message);
    applyPromptEngineeringDebugSnapshot(message.debug_snapshot);
    // Show new-content dot if drawer is closed
    if (promptDrawerControl) promptDrawerControl.showNewContentDot();
  }
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

function refreshResolutionPresetDisplay(mode = currentMode || modeSelect?.value || 'NAI', preferred = undefined) {
  const presetOptions = resolutionPresetResolutionOptions(mode);
  const active = Array.isArray(presetOptions) && presetOptions.length > 0;
  const options = active ? presetOptions : baseResolutionOptions;
  let current = preferred !== undefined ? preferred : (active ? paramEls.resolution?.value : baseResolutionValue);
  if (current && options.length && !options.includes(String(current))) current = undefined;
  if (current === undefined && active) current = options[0];
  if (current === undefined && !active) current = baseResolutionValue || options[0];

  populateSelect(paramEls.resolution, options, current);
  populateSelect(qResolution, options, current);
  [paramEls.resolution, qResolution].forEach(select => {
    select?.classList.toggle('resolution-preset-active', active);
    if (select) {
      select.dataset.resolutionPresetActive = active ? 'true' : 'false';
    }
  });
  refreshHiresfixResolutionDisplay();
  if (typeof customSelectsControl?.scan === 'function') customSelectsControl.scan();
}

function resetResolutionOptionLabels(select) {
  Array.from(select?.options || []).forEach(option => {
    option.textContent = option.value;
  });
}

function plannedWebUiHiresfixFinalResolution() {
  if (String(currentMode || modeSelect?.value || '').toUpperCase() !== 'WEBUI') return null;
  if (isResolutionPresetEnabled('WEBUI')) return null;
  const state = getWebUiHiresfixAssistState();
  if (!state.enabled) return null;
  const base = getWebUiHiresfixAssistBaseResolution();
  const scale = Number($('pHrScale')?.value || 2);
  if (!base || !Number.isFinite(scale) || scale <= 0) return null;
  const effectiveScale = fitWebUiHiresfixAssistScale(base, scale);
  const finalSize = webUiHiresFinalSize(base, effectiveScale);
  return {
    base,
    finalSize,
    label: `${finalSize.width} x ${finalSize.height}`,
  };
}

function refreshHiresfixResolutionDisplay() {
  const planned = plannedWebUiHiresfixFinalResolution();
  [paramEls.resolution, qResolution].forEach(select => {
    if (!select) return;
    resetResolutionOptionLabels(select);
    select.classList.toggle('resolution-hiresfix-active', Boolean(planned));
    select.dataset.resolutionHiresfixActive = planned ? 'true' : 'false';
    if (planned) {
      const baseLabel = `${planned.base.width}x${planned.base.height}`;
      const finalLabel = `${planned.finalSize.width}x${planned.finalSize.height}`;
      select.dataset.customSelectLabel = `HR ${finalLabel}`;
      select.dataset.customSelectTitle = `${planned.base.width} x ${planned.base.height} -> ${planned.label}`;
      select.dataset.resolutionHiresfixFinal = planned.label;
      select.dataset.resolutionHiresfixBase = `${planned.base.width} x ${planned.base.height}`;
    } else {
      delete select.dataset.customSelectLabel;
      delete select.dataset.customSelectTitle;
      delete select.dataset.resolutionHiresfixFinal;
      delete select.dataset.resolutionHiresfixBase;
    }
  });
  if (typeof customSelectsControl?.scan === 'function') customSelectsControl.scan();
}

function setSelectWithFallback(el, preferred, fallbacks = []) {
  if (!el) return '';
  const values = Array.from(el.options).map(option => option.value);
  const candidates = [preferred, ...fallbacks].filter(value => value !== undefined && value !== null && String(value).trim() !== '');
  const match = candidates.find(value => values.includes(String(value)));
  if (match !== undefined) {
    el.value = String(match);
    return el.value;
  }
  if (values.length) el.value = values[0];
  return el.value;
}

function normalizeComfyUiWorkflowState(m = {}) {
  const state = m.comfyui_workflow && typeof m.comfyui_workflow === 'object'
    ? m.comfyui_workflow
    : m;
  const hasCustom = 'has_custom' in state
    ? Boolean(state.has_custom)
    : Boolean(m.comfyui_workflow_has_custom);
  const workflowType = state.workflow_type || m.comfyui_workflow_type || '';
  const isBypass = isComfyUiBypassWorkflowType(workflowType);
  return {
    has_custom: hasCustom,
    workflow_label: isBypass
      ? 'Bypass Workflow'
      : (state.workflow_label || m.comfyui_workflow_label || (hasCustom ? 'Custom Workflow' : 'Basic Workflow')),
    workflow_type: isBypass ? 'bypass' : workflowType,
    model_compat: state.model_compat || null,
    locked_loader_class: state.locked_loader_class || null,
    locked_model_display: state.locked_model_display || null,
  };
}

function isComfyUiBypassWorkflowType(value) {
  return ['bypass', 'free'].includes(String(value || '').trim().toLowerCase());
}

function isComfyUiFreeWorkflowActive(mode = currentMode || modeSelect?.value || '') {
  return String(mode || '').toUpperCase() === 'COMFYUI'
    && isComfyUiBypassWorkflowType(comfyuiWorkflowState?.workflow_type);
}

function setSelectToBypass(el) {
  if (!el) return;
  if (el.options.length !== 1 || el.options[0]?.value !== COMFYUI_FREE_BYPASS_TEXT) {
    el.textContent = '';
    const option = document.createElement('option');
    option.value = COMFYUI_FREE_BYPASS_TEXT;
    option.textContent = COMFYUI_FREE_BYPASS_TEXT;
    el.append(option);
  }
  el.value = COMFYUI_FREE_BYPASS_TEXT;
}

function applyComfyUiFreeParamLock(mode = currentMode || modeSelect?.value || '') {
  const locked = isComfyUiFreeWorkflowActive(mode);
  [paramEls.model, paramEls.sampler, paramEls.scheduler].forEach(el => {
    if (!el) return;
    if (locked) setSelectToBypass(el);
    el.disabled = locked;
    el.classList.toggle('param-bypass-lock', locked);
    el.dataset.customSelectLabel = locked ? COMFYUI_FREE_BYPASS_TEXT : '';
    el.dataset.customSelectTitle = locked ? 'Controlled by the Bypass custom workflow' : '';
  });

  [paramEls.steps, paramEls.cfg_scale, paramEls.seed].forEach(el => {
    if (!el) return;
    const displayText = el === paramEls.seed ? COMFYUI_FREE_SEED_TEXT : COMFYUI_FREE_BYPASS_TEXT;
    if (locked) {
      if (!el.dataset.originalType) el.dataset.originalType = el.type || 'text';
      el.type = 'text';
      el.value = displayText;
    } else if (el.dataset.originalType) {
      el.type = el.dataset.originalType;
      delete el.dataset.originalType;
    }
    el.readOnly = locked;
    el.disabled = locked;
    el.classList.toggle('param-bypass-lock', locked);
    el.title = locked ? (el === paramEls.seed ? 'Forced random by the Bypass custom workflow' : 'Controlled by the Bypass custom workflow') : '';
  });

  const samplingBypass = $('comfyuiSamplingBypass');
  const samplingFlags = [$('flagEps'), $('flagVpred'), $('flagAnima')].filter(Boolean);
  samplingFlags.forEach(el => {
    el.classList.toggle('disabled', locked);
    el.classList.toggle('param-bypass-lock', locked);
    el.style.display = locked ? 'none' : '';
    el.title = locked ? 'Controlled by the Bypass custom workflow' : '';
  });
  if (samplingBypass) {
    samplingBypass.style.display = locked ? '' : 'none';
  }

  const rescaleRow = $('comfyuiRescaleRow');
  const rescaleInput = $('pRescaleCfg');
  if (rescaleRow) {
    rescaleRow.style.display = locked
      ? ''
      : (currentComfyUiSamplingMode() === 'anima' ? '' : 'none');
  }
  if (rescaleInput) {
    if (locked) {
      if (!rescaleInput.dataset.originalType) rescaleInput.dataset.originalType = rescaleInput.type || 'number';
      rescaleInput.type = 'text';
      rescaleInput.value = COMFYUI_FREE_BYPASS_TEXT;
    } else if (rescaleInput.dataset.originalType) {
      rescaleInput.type = rescaleInput.dataset.originalType;
      delete rescaleInput.dataset.originalType;
    }
    rescaleInput.readOnly = locked;
    rescaleInput.disabled = locked;
    rescaleInput.classList.toggle('param-bypass-lock', locked);
    rescaleInput.title = locked ? 'Controlled by the Bypass custom workflow' : '';
  }

  if (typeof customSelectsControl?.scan === 'function') customSelectsControl.scan();
}

function updateRandomPromptWeightRow(mode, samplingMode = null) {
  const row = $('randomPromptWeightRow');
  if (!row) return;
  const normalizedMode = String(mode || currentMode || modeSelect?.value || '').toUpperCase();
  const visible = normalizedMode === 'WEBUI' || normalizedMode === 'COMFYUI';
  row.style.display = visible ? '' : 'none';
  const label = $('randomPromptWeightLabel');
  if (label) label.textContent = 'Prompt Weight';
}

function onComfyUiWorkflowState(m) {
  comfyuiWorkflowState = normalizeComfyUiWorkflowState(m);
  applyComfyUiFreeParamLock();
  if (moduleBadges) moduleBadges.updateComfyUiWorkflowState(comfyuiWorkflowState);
  if (moduleLauncherControl) moduleLauncherControl.updateState();
}

function updateParams(m) {
  const schemaOnly = !!m.schema_only;
  syncingParams = true;
  ensureResolutionPresetOptions();
  populateSelect(paramEls.model, m.options_model, m.model);
  populateSelect(paramEls.sampler, m.options_sampler, m.sampler);
  populateSelect(paramEls.scheduler, m.options_scheduler, m.scheduler);
  if (Array.isArray(m.options_resolution) && m.options_resolution.length) {
    baseResolutionOptions = m.options_resolution.slice();
  }
  if (m.resolution !== undefined) {
    baseResolutionValue = m.resolution;
  }
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
  if (
    (mode === 'WEBUI' || mode === 'COMFYUI')
    && ('resolution_preset_enabled' in m || 'resolution_preset' in m)
  ) {
    const currentPresetState = activeResolutionPresetState(mode) || {enabled: false, preset: 'standard'};
    const nextEnabled = 'resolution_preset_enabled' in m
      ? Boolean(m.resolution_preset_enabled)
      : currentPresetState.enabled;
    const nextPreset = 'resolution_preset' in m
      ? m.resolution_preset
      : currentPresetState.preset;
    syncResolutionPresetControls(mode, nextEnabled, nextPreset);
    if (mode === 'WEBUI' && nextEnabled) {
      updateWebUiHiresfixAssistControls({enabled: false});
      setWebUiHiresfixEnabled(false);
    }
  }
  refreshResolutionPresetDisplay(mode, m.resolution);

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
    const hrUpscalerSelect = $('pHrUpscaler');
    populateSelect(hrUpscalerSelect, m.options_hr_upscaler, undefined);
    setSelectWithFallback(hrUpscalerSelect, m.hr_upscaler, ['Latent (nearest-exact)', 'Latent', 'Lanczos']);
    if ('denoising_strength' in m) $('pDenoise').value = m.denoising_strength;
    if ('hires_steps' in m) $('pHiresSteps').value = m.hires_steps;
    if ('hr_cfg' in m) $('pHrCfg').value = m.hr_cfg;
    if ('hires_preset_swap' in m) {
      _hiresPresetSwapValue = String(m.hires_preset_swap || '').trim();
      _hiresPresetSwapValueKnown = true;
      const swapSelect = $('pHiresPresetSwap');
      if (swapSelect) {
        const hasOption = Array.from(swapSelect.options || []).some(option => option.value === _hiresPresetSwapValue);
        swapSelect.value = hasOption ? _hiresPresetSwapValue : '';
        refreshHiresPresetMismatchBadge();
        refreshHiresEditButtonState();
      }
    }
    if ('anima_weight' in m) $('pAnimaWeight').value = m.anima_weight;
    updateWebUiHiresfixAssistControls();
    updateWebUiHrScaleHint();
  }

  // ComfyUI sampling mode — 서버가 명시적으로 보낸 경우에만 적용 (EPS 기본값 리셋 방지)
  if (mode === 'COMFYUI' && 'sampling_mode' in m) {
    const sm = m.sampling_mode;
    $('flagEps').classList.toggle('on', sm === 'eps');
    $('flagVpred').classList.toggle('on', sm === 'v_prediction');
    $('flagAnima').classList.toggle('on', sm === 'anima');
    $('comfyuiRescaleRow').style.display = sm === 'anima' ? '' : 'none';
    if ('rescale_cfg' in m) $('pRescaleCfg').value = m.rescale_cfg;
    if ('anima_weight' in m) $('pAnimaWeight').value = m.anima_weight;
  }
  updateRandomPromptWeightRow(mode, mode === 'COMFYUI' && 'sampling_mode' in m ? m.sampling_mode : null);
  if (artistThumbControl && typeof artistThumbControl.syncPromptFormat === 'function') {
    artistThumbControl.syncPromptFormat();
  }
  if ('comfyui_workflow' in m || 'comfyui_workflow_has_custom' in m) onComfyUiWorkflowState(m);
  if (moduleBadges) moduleBadges.updateComfyUiParams(m);
  if (studioTabControl) studioTabControl.onParamsChanged();
  updateModuleHeaderAction(currentModuleId);
  syncingParams = false;
  if (resultEnhance) resultEnhance.update();
}

function setParam(key, value) {
  if (syncingParams) return;
  if (isComfyUiFreeWorkflowActive() && COMFYUI_FREE_LOCKED_PARAM_KEYS.has(key)) return;
  // Quick ↔ Params 탭 양방향 동기화
  if (key === 'resolution') {
    paramEls.resolution.value = value;
    qResolution.value = value;
    if (!resolutionPresetResolutionOptions()) baseResolutionValue = value;
    if (typeof customSelectsControl?.scan === 'function') customSelectsControl.scan();
    updateWebUiHrScaleHint();
  } else if (key === 'hr_scale') {
    updateWebUiHrScaleHint();
  } else if (key === 'enable_hr') {
    const enabled = value === true || String(value).toLowerCase() === 'true';
    const enableHr = $('pEnableHr');
    if (enableHr) enableHr.checked = enabled;
    if (!enabled && getWebUiHiresfixAssistState().enabled) {
      updateWebUiHiresfixAssistControls({enabled: false});
      setModuleParam('webui_hiresfix_assist', 'enabled', 'false');
    }
    updateWebUiHrScaleHint();
    refreshHiresfixResolutionDisplay();
  } else if (key === 'hires_preset_swap') {
    _hiresPresetSwapValue = String(value || '').trim();
    _hiresPresetSwapValueKnown = true;
  } else if (key === 'model' && artistThumbControl && typeof artistThumbControl.syncPromptFormat === 'function') {
    artistThumbControl.syncPromptFormat();
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_param', key, value}));
  }
  if (moduleBadges && ['enable_hr', 'hr_scale', 'anima_weight'].includes(key)) {
    moduleBadges.updateComfyUiParams(_collectCurrentParams());
  }
  if (resultEnhance && ['enable_hr', 'hr_scale', 'hr_upscaler', 'denoising_strength', 'hires_steps', 'hr_cfg'].includes(key)) {
    resultEnhance.update();
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
  if (isComfyUiFreeWorkflowActive()) return;
  $('flagEps').classList.toggle('on', mode === 'eps');
  $('flagVpred').classList.toggle('on', mode === 'v_prediction');
  $('flagAnima').classList.toggle('on', mode === 'anima');
  $('comfyuiRescaleRow').style.display = mode === 'anima' ? '' : 'none';
  updateRandomPromptWeightRow('COMFYUI', mode);
  setParam('sampling_mode', mode);
  updateModuleHeaderAction(currentModuleId);
}

function getComfyUiWorkflowFileInput({free = false} = {}) {
  const existing = free ? comfyuiFreeWorkflowFileInput : comfyuiWorkflowFileInput;
  if (existing) return existing;

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = free ? 'application/json,.json' : 'application/json,image/png,image/webp,.json,.png,.webp';
  input.hidden = true;
  input.addEventListener('change', () => {
    const file = input.files && input.files[0];
    input.value = '';
    if (file) uploadComfyUiWorkflowFile(file, {free});
  });
  document.body.append(input);
  if (free) {
    comfyuiFreeWorkflowFileInput = input;
  } else {
    comfyuiWorkflowFileInput = input;
  }
  return input;
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

function freeWorkflowNoticeHtml() {
  return [
    '1. 2개의 문자열 노드, 2개의 정수 노드, 1개의 이미지 혹은 WEBP 저장 노드가 필요합니다.',
    '2. 각 문자열 노드의 이름을 naia_prompt, naia_negative 로 수정, 정수 노드의 이름을 naia_width, naia_height로 수정합니다. 이름이 틀리면 업로드가 거부됩니다.',
    '3. Bypass 모드에서는 NAIA가 위 4개의 Primitive 노드와 저장 노드만 제어합니다. 모델, sampler, scheduler, steps, CFG, sampling mode, Rescale CFG는 NAIA에서 수정하지 않습니다.',
    '4. json 내 seed 입력 영역은 매 실행 랜덤값으로 강제됩니다. seed를 0으로 초기화할 필요는 없습니다.',
    '5. 파라미터 수정시 json 파일을 다시 업로드 하십시오.',
    '* json 내보내기는 [파일] > [내보내기 (API)] 로 내보내면 됩니다.',
  ].map(line => escHtml(line)).join('<br>');
}

async function uploadComfyUiFreeWorkflow() {
  if ((currentMode || modeSelect.value) !== 'COMFYUI') {
    showToast('ComfyUI mode is required', 'error');
    return;
  }
  const confirmed = await showConfirmDialog('', {
    title: '[ Bypass 모드 주의사항 ]',
    messageHtml: freeWorkflowNoticeHtml(),
    okText: '.json 업로드',
    cancelText: '취소',
    dialogClass: 'app-confirm-dialog-bypass-workflow',
  });
  if (!confirmed) return;
  getComfyUiWorkflowFileInput({free: true}).click();
}

async function uploadComfyUiWorkflowFile(file, {free = false} = {}) {
  if (!file) return;
  const isWorkflowImage = ['image/png', 'image/webp'].includes(file.type) || /\.(png|webp)$/i.test(file.name || '');
  const isWorkflowJson = file.type === 'application/json' || /\.json$/i.test(file.name || '');
  if (free && !isWorkflowJson) {
    showToast('JSON workflow file is required for Bypass mode', 'error');
    return;
  }
  if (!free && !isWorkflowImage && !isWorkflowJson) {
    showToast('JSON, PNG, or WEBP workflow file is required', 'error');
    return;
  }
  try {
    const response = await fetch(free ? '/api/comfyui/workflow/bypass/upload' : '/api/comfyui/workflow/upload', {
      method: 'POST',
      headers: {'Content-Type': file.type || 'application/octet-stream'},
      body: file,
    });
    const data = await readJsonResponse(response);
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || 'Workflow upload failed');
    }
    applyComfyUiWorkflowResponse(data);
    showToast(free ? 'Bypass Workflow enabled' : 'Custom Workflow enabled', 'success');
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
  const forceSync = !!m.force || !!m.desktop_sync;

  if (!forceSync && _isPromptEditingActive() && (promptChanged || negativeChanged)) {
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
  event_stream: {width: 520, height: 640},
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
  if (artistThumbControl && typeof artistThumbControl.setActive === 'function') {
    artistThumbControl.setActive(activeTab === 'artists');
  }
  if (activeTab === 'artists' && artistThumbControl) artistThumbControl.load();
  if (characterViewerControl && typeof characterViewerControl.setActive === 'function') {
    characterViewerControl.setActive(activeTab === 'characters');
  }
  if (activeTab === 'characters' && characterViewerControl) characterViewerControl.load();
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

// ---- Result history (Desktop History mirror) ----
function initViewer() { if (resultHistory) resultHistory.initViewer(); }
function closeViewerLightbox() { if (resultHistory) resultHistory.closeLightbox(); }
function onLightboxClick(event) { if (resultHistory) resultHistory.onLightboxClick(event); }
function onViewerNewImage(message) {
  if (resultHistory) resultHistory.onNewImage(message);
  scheduleResultUnsavedActionRefresh(180);
}
function onViewerHistoryRemoved(message) {
  if (resultHistory) resultHistory.onRemoved(message);
  scheduleResultUnsavedActionRefresh(80);
}
function onViewerHistoryCleared(message) {
  if (resultHistory) resultHistory.onCleared(message);
  renderResultUnsavedActions(null);
}
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

function applyMetadataCheckboxParamValue(key, value, elementId) {
  if (value === undefined || value === null || value === '') return false;
  const enabled = normalizeMetadataBoolean(value);
  const target = $(elementId);
  if (target) target.checked = enabled;
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
    ['hr_scale', params.hr_scale],
    ['hr_upscaler', params.hr_upscaler],
    ['denoising_strength', params.denoising_strength],
    ['hires_steps', params.hires_steps],
    ['hr_cfg', params.hr_cfg],
  ].forEach(([key, value]) => {
    if (applyMetadataParamValue(key, value)) applied += 1;
  });
  if (applyMetadataCheckboxParamValue('enable_hr', params.enable_hr, 'pEnableHr')) applied += 1;
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

function onAutoSaveToggle(enabled) {
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
  sessionBootstrapReceived = true;
  if ('prompt' in m || 'negative_prompt' in m) {
    syncPrompts({
      type: 'prompt_sync',
      prompt: m.prompt || '',
      negative_prompt: m.negative_prompt || '',
      force: true,
    });
  }
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
  scheduleInitialRandomPrompt();
  updateModeSelectAvailability();
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
  activePromptTab = name || 'prompt';
  if (promptDrawerControl) promptDrawerControl.switchTab(name);
  if (eventPresetPanel) eventPresetPanel.setActiveTab(activePromptTab === 'preset');
  updateGenerateButtonMode();
}

function positionFnMenu() {
  if (!fnMenu || !fnMenuTrigger || fnMenu.hidden) return;
  const rect = fnMenuTrigger.getBoundingClientRect();
  const gap = 5;
  const menuRect = fnMenu.getBoundingClientRect();
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
  const left = Math.max(8, Math.min(rect.right - menuRect.width, viewportWidth - menuRect.width - 8));
  fnMenu.style.left = `${Math.round(left)}px`;
  fnMenu.style.top = `${Math.round(rect.bottom + gap)}px`;
}

function closeFnMenu() {
  if (!fnMenu) return;
  fnMenu.hidden = true;
  fnMenuTrigger?.setAttribute('aria-expanded', 'false');
}

function toggleFnMenu(event) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  if (!fnMenu || !fnMenuTrigger) return;
  const nextOpen = fnMenu.hidden;
  if (!nextOpen) {
    closeFnMenu();
    return;
  }
  fnMenu.hidden = false;
  fnMenuTrigger.setAttribute('aria-expanded', 'true');
  positionFnMenu();
}

function openFnPreset() {
  closeFnMenu();
  switchTab('preset');
}

function positionTranslatorPopup() {
  if (!translatorPopup || translatorPopup.hidden) return;
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
  const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
  const viewerRect = resultViewer?.getBoundingClientRect?.();
  const fnRect = fnMenuTrigger?.getBoundingClientRect?.();
  const popupRect = translatorPopup.getBoundingClientRect();
  let popupWidth = popupRect.width || 620;
  const height = popupRect.height || 300;
  let left = 18;
  let top = 76;
  if (viewerRect && viewerRect.width > 220 && viewerRect.height > 160) {
    const targetWidth = Math.min(
      Math.max(460, Math.round(viewerRect.width * 0.56)),
      Math.min(640, viewerRect.width - 28),
    );
    translatorPopup.style.width = `${Math.max(320, targetWidth)}px`;
    const nextRect = translatorPopup.getBoundingClientRect();
    const nextWidth = nextRect.width || targetWidth;
    popupWidth = nextWidth;
    const anchorLeft = fnRect ? Math.max(viewerRect.left + 16, fnRect.right + 18) : viewerRect.left + 18;
    left = Math.min(anchorLeft, viewerRect.right - nextWidth - 18);
    top = viewerRect.top + 18;
  } else if (fnRect) {
    left = fnRect.right + 14;
    top = fnRect.bottom + 10;
  }
  left = Math.max(12, Math.min(left, viewportWidth - popupWidth - 12));
  top = Math.max(54, Math.min(top, viewportHeight - height - 12));
  translatorPopup.style.left = `${Math.round(left)}px`;
  translatorPopup.style.top = `${Math.round(top)}px`;
}

function openTranslatorPopup() {
  closeFnMenu();
  if (!translatorPopup) return;
  translatorPopup.hidden = false;
  positionTranslatorPopup();
  translatorInput?.focus();
  translatorInput?.select?.();
  scheduleTranslatorPopupTranslation();
}

function closeTranslatorPopup() {
  if (!translatorPopup) return;
  translatorPopup.hidden = true;
  clearTranslatorPopupTimer();
  clearPendingTranslatorPopupTranslation();
}

function clearTranslatorPopupTimer() {
  if (!translatorPopupTimer) return;
  window.clearTimeout(translatorPopupTimer);
  translatorPopupTimer = null;
}

function clearPendingTranslatorPopupTranslation(text = '', requestId = '') {
  if (!text && !requestId) {
    translatorPopupRequestText = '';
    translatorPopupRequestId = '';
    return;
  }
  if (text && translatorPopupRequestText !== text) return;
  if (requestId && translatorPopupRequestId !== requestId) return;
  translatorPopupRequestText = '';
  translatorPopupRequestId = '';
}

function requestTranslatorPopupTranslate(options = {}) {
  const force = options === true || !!options.force;
  const text = translatorInput?.value?.trim() || '';
  clearTranslatorPopupTimer();
  if (!text) {
    if (translatorOutput) translatorOutput.value = '';
    clearPendingTranslatorPopupTranslation();
    return;
  }
  if (!force && !translatorHangulRe.test(text)) {
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    if (force) showToast('Remote connection is not open', 'error');
    return;
  }
  if (!force && translatorPopupRequestText === text) return;
  translatorPopupRequestText = text;
  translatorPopupRequestId = `translate-${Date.now()}-${++translatorPopupSeq}`;
  const requestId = translatorPopupRequestId;
  if (translatorOutput) translatorOutput.value = '...';
  ws.send(JSON.stringify({
    type: 'translate_text',
    direction: 'ko_en',
    text,
    requestId,
  }));
  window.setTimeout(() => clearPendingTranslatorPopupTranslation(text, requestId), 10000);
}

function scheduleTranslatorPopupTranslation() {
  clearTranslatorPopupTimer();
  if (!translatorPopup || translatorPopup.hidden || translatorPopupComposing) return;
  const text = translatorInput?.value?.trim() || '';
  if (!text) {
    if (translatorOutput) translatorOutput.value = '';
    clearPendingTranslatorPopupTranslation();
    return;
  }
  if (!translatorHangulRe.test(text)) return;
  translatorPopupTimer = window.setTimeout(() => {
    translatorPopupTimer = null;
    requestTranslatorPopupTranslate({force: false});
  }, TRANSLATOR_AUTO_TRANSLATE_MS);
}

function onTranslationResult(message) {
  const requestId = String(message?.requestId || '');
  if (requestId && requestId !== translatorPopupRequestId) return;
  clearPendingTranslatorPopupTranslation('', requestId);
  const translated = String(message?.translated || '');
  if (translatorOutput) translatorOutput.value = translated;
  if (!translated) showToast(message?.error || 'Translation failed', 'error');
}

async function copyTranslatorOutput() {
  const text = translatorOutput?.value || '';
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    showToast('Translation copied', 'success');
  } catch (error) {
    showToast('Clipboard copy failed', 'error');
  }
}

function insertTranslatorOutput() {
  const text = translatorOutput?.value || '';
  if (!text) return;
  const target = promptEdit || document.activeElement;
  if (!target || typeof target.setRangeText !== 'function') return;
  const start = Number.isFinite(target.selectionStart) ? target.selectionStart : target.value.length;
  const end = Number.isFinite(target.selectionEnd) ? target.selectionEnd : target.value.length;
  target.setRangeText(text, start, end, 'end');
  target.focus();
  onPromptEdit();
}

if (translatorInput) {
  translatorInput.addEventListener('input', scheduleTranslatorPopupTranslation);
  translatorInput.addEventListener('compositionstart', () => {
    translatorPopupComposing = true;
    clearTranslatorPopupTimer();
  });
  translatorInput.addEventListener('compositionend', () => {
    translatorPopupComposing = false;
    scheduleTranslatorPopupTranslation();
  });
}

document.addEventListener('click', event => {
  if (
    fnMenu
    && !fnMenu.hidden
    && !fnMenu.contains(event.target)
    && !fnMenuTrigger?.contains(event.target)
  ) {
    closeFnMenu();
  }
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  closeFnMenu();
  if (translatorPopup && !translatorPopup.hidden) closeTranslatorPopup();
});
window.addEventListener('resize', () => {
  positionFnMenu();
  positionTranslatorPopup();
});

function currentPromptTabFromDom() {
  const activeButton = document.querySelector('.tab-btn.active[data-tab]');
  if (activeButton?.dataset?.tab) return activeButton.dataset.tab;
  const activePage = document.querySelector('.tab-page.active[id^="tab"]');
  if (activePage?.id) {
    const raw = activePage.id.slice(3);
    if (raw) return raw.charAt(0).toLowerCase() + raw.slice(1);
  }
  return activePromptTab || 'prompt';
}

function syncPromptTabStateFromDom() {
  activePromptTab = currentPromptTabFromDom();
  if (eventPresetPanel) eventPresetPanel.setActiveTab(activePromptTab === 'preset');
  updateGenerateButtonMode();
}

// ---- Controls ----
function requestGenerate(payload = {}) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  if (generating) return false;
  flushPromptEngineeringEdits();
  if (promptSendTimer) { clearTimeout(promptSendTimer); promptSendTimer = null; }
  _localPromptDirty = false;
  const message = {type: 'generate', ...(payload && typeof payload === 'object' ? payload : {})};
  ws.send(JSON.stringify(message));
  return true;
}

function requestRandomPrompt({force = false, bootstrap = false} = {}) {
  flushPromptEngineeringEdits();
  if (activePromptTab === 'preset') {
    if (!force) void randomizeFromPresetTab();
    return false;
  }
  if (!force && getOptionChecked('prompt_fixed')) {
    updateGenerateButtonMode();
    return false;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  if (bootstrap) {
    ws.send(JSON.stringify({
      type: 'bootstrap_random',
      random_request_id: createRandomRequestId(),
      ratings: getActiveRatings(),
      overrides: _collectCurrentParams(),
    }));
    return true;
  }
  if (promptSendTimer) {
    clearTimeout(promptSendTimer);
    promptSendTimer = null;
  }
  _localPromptDirty = false;
  btnRnd.disabled = true;
  awaitingMyRandom = true;
  pendingRandomRequestId = createRandomRequestId();
  if (window._randomTimeout) clearTimeout(window._randomTimeout);
  window._randomTimeout = setTimeout(() => {
    if (awaitingMyRandom) {
      unlockRandomButton({clearRequest: false});
    }
  }, 2000);
  ws.send(JSON.stringify({
    type: 'random',
    random_request_id: pendingRandomRequestId,
    ratings: getActiveRatings(),
    overrides: _collectCurrentParams(),
  }));
  return true;
}

function scheduleInitialRandomPrompt(delay = 350) {
  if (initialRandomPromptIssued) return;
  if (!sessionBootstrapReceived) return;
  if (initialRandomPromptTimer) clearTimeout(initialRandomPromptTimer);
  initialRandomPromptTimer = setTimeout(() => {
    initialRandomPromptTimer = null;
    if (initialRandomPromptIssued) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (generating || awaitingMyRandom || pendingRandomRequestId) return;
    if (String(promptEdit?.value || '').trim()) {
      initialRandomPromptIssued = true;
      return;
    }
    initialRandomPromptIssued = true;
    requestRandomPrompt({force: true, bootstrap: true});
  }, Math.max(0, Number(delay) || 0));
}

function send(cmd) {
  if (cmd === 'generate') {
    if (activePromptTab === 'preset') {
      void generateFromPresetTab();
      return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const prompt = promptEdit.value;
    const negative = negEdit.value;
    requestGenerate({
      prompt,
      negative_prompt: negative,
      overrides: buildWebGenerationOverrides(prompt, negative),
    });
    return;
  }
  if (cmd === 'random') {
    requestRandomPrompt();
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(cmd);
}

function setGen(v) {
  const next = Boolean(v);
  if (generating === next) {
    if (next) {
      btnGen.disabled = true;
      btnGen.classList.add('generating');
      if (!genTimer && genStartTime > 0) startGenTimer();
    } else {
      updateGenerateButtonMode();
    }
    if (resultEnhance) resultEnhance.update();
    return;
  }
  generating = next;
  if (studioTabControl) studioTabControl.handleGenerationStatus(next);
  if (eventPresetPanel?.setGeneratingStatus) eventPresetPanel.setGeneratingStatus(next);
  btnGen.disabled = next;
  if (next) {
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
    updateGenerateButtonMode();
  }
  if (resultEnhance) resultEnhance.update();
}

function updateGenerateButtonMode() {
  if (!btnGen) return;
  const presetMode = activePromptTab === 'preset';
  btnGen.classList.toggle('preset-mode', presetMode);
  if (btnRnd) {
    const promptFixed = getOptionChecked('prompt_fixed');
    btnRnd.disabled = presetMode
      ? (promptFixed || !!presetGenerationPending || generating || !eventPresetPanel?.canRandomize?.())
      : (promptFixed || awaitingMyRandom);
  }
  if (!generating) {
    const promptFixed = getOptionChecked('prompt_fixed');
    btnGen.disabled = presetMode
      ? (promptFixed || !!presetGenerationPending || !eventPresetPanel?.canGenerate?.())
      : false;
    btnGen.innerHTML = '<span class="shortcut-hint">CTRL + ENTER</span>Generate';
  }
}

function clearPresetGenerationOptions({autoGenerate = true} = {}) {
  if (autoGenerate && getOptionChecked('auto_generate')) setOption('auto_generate', false);
  if (getOptionChecked('wildcard_standalone')) setOption('wildcard_standalone', false);
}

async function generateFromPresetTab() {
  if (getOptionChecked('prompt_fixed')) {
    updateGenerateButtonMode();
    return;
  }
  if (!eventPresetPanel?.canGenerate?.()) {
    updateGenerateButtonMode();
    return;
  }
  clearPresetGenerationOptions({autoGenerate: false});
  presetGenerationPending = {requestId: ''};
  updateGenerateButtonMode();
  const requested = await eventPresetPanel.generateCurrentPreset();
  if (requested?.requestId) presetGenerationPending = {requestId: requested.requestId};
  else presetGenerationPending = null;
  updateGenerateButtonMode();
}

async function randomizeFromPresetTab() {
  if (getOptionChecked('prompt_fixed') || !!presetGenerationPending || generating) {
    updateGenerateButtonMode();
    return;
  }
  btnRnd.disabled = true;
  try {
    const shouldGenerate = getOptionChecked('auto_generate');
    const changed = await eventPresetPanel?.randomizeCurrentCategory?.();
    if (!changed) showToast(eventPresetPanel?.randomizeUnavailableMessage?.() || '랜덤 선택 가능한 Preset이 없습니다.', 'error');
    else if (shouldGenerate) await generateFromPresetTab();
  } catch (error) {
    showToast(error?.message || 'Event Preset 랜덤 생성에 실패했습니다.', 'error');
  } finally {
    updateGenerateButtonMode();
  }
}

function onEventPresetGenerationError(message = {}) {
  const requestId = String(message.requestId || '');
  const pendingRequestId = String(presetGenerationPending?.requestId || '');
  if (!presetGenerationPending || !pendingRequestId || requestId === pendingRequestId) {
    presetGenerationPending = null;
    updateGenerateButtonMode();
  }
  showToast(message.message || 'Event Preset generation failed', 'error');
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
    updateGenerateButtonMode();
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
let autoModeFallbackInFlight = false;
let autoModeFallbackTarget = '';
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

function findConnectedFallbackMode(activeMode = '') {
  return API_MODES.find(mode => mode !== activeMode && isModeConnected(mode)) || '';
}

function reconcileActiveApiMode(reason = '') {
  if (!setupController || !modeSelect) return;
  const apiStatus = setupController.getApiStatus ? setupController.getApiStatus() : null;
  const activeMode = String(apiStatus?.active_mode || currentMode || modeSelect.value || '').toUpperCase();
  if (activeMode && isModeConnected(activeMode)) {
    setupController.setRuntimeSetupForced?.(false);
    return;
  }

  const fallbackMode = findConnectedFallbackMode(activeMode);
  if (fallbackMode) {
    setupController.setRuntimeSetupForced?.(false);
    if (!autoModeFallbackInFlight && !modeSwitching && activeMode !== fallbackMode
        && ws && ws.readyState === WebSocket.OPEN) {
      autoModeFallbackInFlight = true;
      autoModeFallbackTarget = fallbackMode;
      const source = activeMode || '현재 모드';
      showToast(`${source} 연결이 해제되어 ${fallbackMode}로 전환합니다.`, 'success');
      setMode(fallbackMode);
    }
    return;
  }

  const probeSettled = setupController.hasProbeCompleted?.() && !setupController.isProbePending?.();
  if (probeSettled && !setupController.hasConnectedMode?.()) {
    setupController.setRuntimeSetupForced?.(true, '연결된 백엔드가 없습니다. API 설정을 확인하세요.');
    if (reason !== 'api_status') openApiPopup();
  }
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
  updateRandomPromptWeightRow(mode);
  applyComfyUiFreeParamLock(mode);
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
  const wasAutoFallback = autoModeFallbackInFlight;
  uiLock.classList.remove('active');
  modeSwitching = false;
  autoModeFallbackInFlight = false;
  if (m.success) {
    autoModeFallbackTarget = '';
    prevMode = m.mode;
    syncMode(m.mode);
    showToast(m.message || `${m.mode} mode active`, 'success');
  } else {
    syncMode(prevMode);
    showToast(m.message || 'Mode change failed', 'error', true);
    if (wasAutoFallback) {
      setupController?.setRuntimeSetupForced?.(
        true,
        `${autoModeFallbackTarget || 'fallback'} 전환 실패 - API 설정을 확인하세요.`
      );
      setupController?.probeApi?.();
      openApiPopup();
      autoModeFallbackTarget = '';
    }
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

let appDialogCleanup = null;
function showAppDialog(message, options = {}) {
  if (appDialogCleanup) {
    appDialogCleanup(null);
    appDialogCleanup = null;
  }

  const isPrompt = options.type === 'prompt';
  const title = options.title || (isPrompt ? '입력' : '확인');
  const okText = options.okText || '확인';
  const cancelText = options.cancelText || '취소';
  const defaultValue = String(options.defaultValue ?? '');
  const inputHtml = isPrompt ? `
          <input class="app-confirm-input" type="text" data-dialog-input value="${escHtml(defaultValue)}" placeholder="${escHtml(options.placeholder || '')}">
        ` : '';

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'app-confirm-overlay';
    overlay.innerHTML = `
      <section class="app-confirm-dialog" role="dialog" aria-modal="true" aria-label="${escHtml(title)}">
        <div class="app-confirm-icon" aria-hidden="true">i</div>
        <div class="app-confirm-copy">
          <div class="app-confirm-title">${escHtml(title)}</div>
          <div class="app-confirm-message">${escHtml(message)}</div>
          ${inputHtml}
        </div>
        <div class="app-confirm-actions">
          <button class="app-confirm-btn app-confirm-btn-primary" data-confirm-action="ok" type="button">${escHtml(okText)}</button>
          <button class="app-confirm-btn" data-confirm-action="cancel" type="button">${escHtml(cancelText)}</button>
        </div>
      </section>
    `;

    const cleanup = result => {
      if (appDialogCleanup !== cleanup) return;
      appDialogCleanup = null;
      document.removeEventListener('keydown', onKeyDown, true);
      overlay.remove();
      resolve(result);
    };
    const finishOk = () => {
      const input = overlay.querySelector('[data-dialog-input]');
      cleanup(isPrompt ? (input?.value ?? '') : true);
    };
    const cancel = () => cleanup(isPrompt ? null : false);
    const onKeyDown = event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        cancel();
      } else if (event.key === 'Enter' && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        finishOk();
      }
    };

    overlay.addEventListener('click', event => {
      if (event.target === overlay) {
        cancel();
        return;
      }
      const button = event.target.closest('[data-confirm-action]');
      if (!button) return;
      if (button.dataset.confirmAction === 'ok') finishOk();
      else cancel();
    });

    appDialogCleanup = cleanup;
    document.addEventListener('keydown', onKeyDown, true);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => {
      overlay.classList.add('open');
      const initialFocus = overlay.querySelector('[data-dialog-input]')
        || overlay.querySelector('[data-confirm-action="ok"]');
      initialFocus?.focus();
      if (initialFocus?.select) initialFocus.select();
    });
  });
}

function showConfirmDialog(message, options = {}) {
  return showAppDialog(message, { ...options, type: 'confirm' });
}

function showPromptDialog(message, options = {}) {
  return showAppDialog(message, { ...options, type: 'prompt' });
}

// ---- Setup / Initial Configuration ----
// Sits on top of WS `api_status` / `verify_result` / `comfyui_models` / `setup_blocked`.
// When `setup_required` is true the modal is forced open and cannot be dismissed
// until at least one backend is verified.
function openApiPopup() {
  if (setupController) setupController.openApiPopup();
}

function openDataMigration() {
  if (dataMigrationPanel) dataMigrationPanel.open();
}

function openCurrentDataFolder() {
  if (dataMigrationPanel) dataMigrationPanel.openDataFolder();
}

function probeApi() {
  if (setupController) setupController.probeApi();
}

function onProbeResult(m) {
  if (setupController) setupController.onProbeResult(m);
  reconcileActiveApiMode('probe_result');
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

function onClearApiResult(m) {
  if (setupController) setupController.onClearApiResult(m);
  if (m && m.success) reconcileActiveApiMode('clear_api_result');
}

function onVerifyResult(m) {
  if (setupController) setupController.onVerifyResult(m);
  reconcileActiveApiMode('verify_result');
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
  reconcileActiveApiMode('api_status');
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

const moduleLauncherReady = import('./js/features/moduleLauncher.mjs?v=20260523-comfyui-bypass1')
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
      uploadComfyUiFreeWorkflow,
      openComfyUiWeb,
      setModuleParam,
    });
    moduleLauncherControl.render();
    moduleLauncherControl.bind();
    ensureResolutionPresetOptions();
    updateWebUiHiresfixAssistControls();
    refreshResolutionPresetDisplay(currentMode || modeSelect?.value || 'NAI');
  })
  .catch(error => {
    console.error('Failed to initialize module launcher', error);
  });

let lastPromptEngineeringState = null;
const promptEngineeringPanelReady = import('./js/features/promptEngineeringPanel.mjs?v=20260508-preset-hover1')
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
const promptEngineeringActionsReady = import('./js/features/promptEngineeringActions.mjs?v=20260526-webui-recommended-preset1')
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
      && moduleId !== 'img2img'
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
  if (moduleId === 'prompt_engineering' && (
    (currentMode || modeSelect.value) === 'NAI'
    || (currentMode || modeSelect.value) === 'WEBUI'
    || isComfyUiAnimaMode()
  )) {
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

function currentWebUiModelName() {
  return String(paramEls?.model?.value || '').trim();
}

function isWebUiAnimaModel(mode = currentMode || modeSelect.value || '', modelName = currentWebUiModelName()) {
  return String(mode || '').toUpperCase() === 'WEBUI'
    && String(modelName || '').toLowerCase().includes('anima');
}

function isAnimaArtistMode() {
  return isComfyUiAnimaMode() || isWebUiAnimaModel();
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

function scheduleInitialStateRefresh(delayMs = 5000) {
  if (initialStateRefreshTimer) clearTimeout(initialStateRefreshTimer);
  initialStateRefreshTimer = setTimeout(() => {
    initialStateRefreshTimer = null;
    if (awaitingMyRandom || pendingRandomRequestId) {
      scheduleInitialStateRefresh(1000);
      return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({type: 'get_search_state'}));
    ws.send(JSON.stringify({type: 'get_module_state', module_id: 'event_stream'}));
    ws.send(JSON.stringify({type: 'get_module_state', module_id: 'webui_hiresfix_assist'}));
  }, Math.max(250, Number(delayMs) || 5000));
}

function scheduleInitialHistoryRefresh(delayMs = 5000) {
  if (initialHistoryRefreshTimer) clearTimeout(initialHistoryRefreshTimer);
  initialHistoryRefreshTimer = setTimeout(() => {
    initialHistoryRefreshTimer = null;
    if (awaitingMyRandom || pendingRandomRequestId) {
      scheduleInitialHistoryRefresh(1000);
      return;
    }
    if (resultHistory) resultHistory.prepareInitialHistory();
  }, Math.max(250, Number(delayMs) || 5000));
}

function openModule(moduleId, options = {}) {
  // NAI 전용 모듈 가드
  if (['character', 'character_reference', 'vibe_transfer'].includes(moduleId) && modeSelect.value !== 'NAI') {
    showToast('This module is only available in NAI mode', 'error');
    return;
  }
  if (imageModulePanels && moduleId !== 'vibe_transfer') {
    imageModulePanels.closeAllVibeClusterPanels();
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
  if (characterPanel && moduleId !== 'character') characterPanel.hideColdPanel();
  if (currentModuleId === 'prompt_engineering') flushPromptEngineeringEdits();
  else flushPendingModuleEdit(currentModuleId);
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
    event_stream: 'Event Stream',
    wildcard: '와일드카드 관리',
    instant_wildcard: 'Instant Wildcard',
    chunk: '와일드카드 청크',
    e621_event: 'E621 연구모듈',
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
  if (currentModuleId === 'vibe_transfer' && imageModulePanels && !options.keepVibeCluster) {
    imageModulePanels.closeAllVibeClusterPanels();
  }
  if (currentModuleId === 'character' && characterPanel) characterPanel.hideColdPanel();
  if (currentModuleId === 'prompt_engineering') flushPromptEngineeringEdits();
  else flushPendingModuleEdit(currentModuleId);
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
const promptEngineeringPopupRenderersReady = import('./js/features/promptEngineeringPopupRenderers.mjs?v=20260514-randomized-preview3')
  .then(({createPromptEngineeringPopupRenderers}) => {
    promptEngineeringPopupRenderers = createPromptEngineeringPopupRenderers({
      document,
      requestAnimationFrame: window.requestAnimationFrame.bind(window),
      escHtml,
      createPromptPreset,
      addRandomizedPreset: addRandomizedPromptPreset,
      removeRandomizedPreset: removeRandomizedPromptPreset,
      switchRandomizedPreset: switchRandomizedPromptPreset,
      clearRandomizedPresets: clearRandomizedPromptPresets,
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
  const resolutionPanel = document.getElementById('resolutionManagerPanel');
  if (exceptPanel !== resolutionPanel && resolutionManagerPanel?.isOpen()) closeResolutionManager();
  const wildcardEditorPanel = document.getElementById('wildcardEditorPopup');
  if (exceptPanel !== wildcardEditorPanel && wildcardManagerPanel?.isEditorOpen()) wildcardManagerPanel.closeEditor();

  const tagFilterPopup = document.getElementById('tagFilterPopup');
  if (exceptPanel !== tagFilterPopup && tagFilterPopup?.classList.contains('open')) {
    closeTagFilter();
  }
}

function openResolutionManager() {
  const panel = document.getElementById('resolutionManagerPanel');
  closeAuxiliaryPopups(panel);
  if (resolutionManagerPanel) resolutionManagerPanel.open();
}

function closeResolutionManager() {
  if (resolutionManagerPanel) resolutionManagerPanel.close();
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
  else if (m.module_id === 'event_stream') {
    if (moduleLauncherControl) moduleLauncherControl.updateEventStreamState(m);
    if (eventStreamPanel) eventStreamPanel.setState(m);
  } else if (m.module_id === 'webui_hiresfix_assist') {
    if (m.enabled) {
      const presetState = activeResolutionPresetState('WEBUI');
      if (presetState?.enabled) {
        syncResolutionPresetControls('WEBUI', false, presetState.preset);
        refreshResolutionPresetDisplay('WEBUI');
        setParam('resolution_preset_enabled', 'false');
      }
    }
    updateWebUiHiresfixAssistControls(m);
    if ('enabled' in m) setWebUiHiresfixEnabled(getWebUiHiresfixAssistState().enabled);
  }

  if (m.module_id === 'prompt_engineering') {
    lastPromptEngineeringState = m;
    syncPromptEngineeringPopups();
    refreshHiresPresetSwapOptions(m);
  }
  if (m.module_id === 'chunk' && isChunkOpen()) {
    renderChunk(m);
  }

  if (m.module_id !== currentModuleId) return;
  renderModuleState(m);
}

function onPromptEngineeringPresetThumbnailUpdated(m) {
  document.dispatchEvent(new CustomEvent('prompt-engineering-thumbnail-updated', { detail: m || {} }));
  if (m?.message) showToast(m.message, 'success');
}

function renderModuleState(m) {
  if (m.module_id === 'auto_save') renderAutoSavePanel(m);
  else if (m.module_id === 'prompt_engineering') renderPromptEngineering(m);
  else if (m.module_id === 'automation') renderAutomation(m);
  else if (m.module_id === 'character') renderCharacter(m);
  else if (m.module_id === 'conditional_prompt') renderConditionalPrompt(m);
  else if (m.module_id === 'event_stream') renderEventStream(m);
  else if (m.module_id === 'character_reference') renderCharacterReference(m);
  else if (m.module_id === 'vibe_transfer') renderVibeTransfer(m);
  else if (m.module_id === 'img2img') renderImg2Img(m);
  else if (m.module_id === 'save_directory') renderSaveDirectory(m);
  else if (m.module_id === 'wildcard') renderWildcard(m);
  else if (m.module_id === 'instant_wildcard') renderInstantWildcard(m);
  else if (m.module_id === 'e621_event') renderE621Event(m);
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

function saveAllUnsavedHistory() {
  if (autoSavePanel) autoSavePanel.saveAllUnsavedHistory();
}

function downloadUnsavedHistory() {
  if (autoSavePanel) autoSavePanel.downloadUnsavedHistory();
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

function addRandomizedPromptPreset() {
  if (promptEngineeringActions) promptEngineeringActions.addRandomizedPreset();
}

function removeRandomizedPromptPreset(preset) {
  if (promptEngineeringActions) promptEngineeringActions.removeRandomizedPreset(preset);
}

function switchRandomizedPromptPreset(preset) {
  if (promptEngineeringActions) promptEngineeringActions.switchRandomizedPreset(preset);
}

function clearRandomizedPromptPresets() {
  if (promptEngineeringActions) promptEngineeringActions.clearRandomizedPresets();
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

function setCharacterSlotState(index, slotState) {
  if (characterPanel) characterPanel.setSlotState(index, slotState);
}

function toggleCharacterColdPanel() {
  if (characterPanel) characterPanel.toggleColdPanel();
}

function renameCharacterSlot(index) {
  if (characterPanel) characterPanel.renameSlot(index);
}

function setCharacterColdSearch(value) {
  if (characterPanel) characterPanel.setColdSearch(value);
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

// ---- Event Stream module ----
function renderEventStream(m) {
  if (eventStreamPanel) eventStreamPanel.render(m);
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

function wcCloseEditor() {
  if (wildcardManagerPanel) wildcardManagerPanel.closeEditor();
}

function wcToggleFolder(element) {
  if (wildcardManagerPanel) wildcardManagerPanel.toggleFolder(element);
}

function wcOpenFile(element) {
  if (wildcardManagerPanel) wildcardManagerPanel.openFile(element);
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

function openVibeClusterPanel() {
  if (imageModulePanels) imageModulePanels.openVibeClusterPanel();
}

function openVibeClusterListPanel() {
  if (imageModulePanels) imageModulePanels.openVibeClusterListPanel();
}

function closeVibeClusterPanel() {
  if (imageModulePanels) imageModulePanels.closeVibeClusterPanel();
}

function closeVibeClusterSavePanel() {
  if (imageModulePanels) imageModulePanels.closeVibeClusterSavePanel();
}

function saveVibeCluster() {
  if (imageModulePanels) imageModulePanels.saveVibeCluster();
}

function pasteVibeClusterThumbnail(targetId = '') {
  if (imageModulePanels) imageModulePanels.pasteVibeClusterThumbnail(targetId);
}

function setVibeClusterSaveThumbnail(file) {
  if (imageModulePanels) imageModulePanels.setVibeClusterSaveThumbnail(file);
}

function toggleVibeClusterLoadMenu(id, event) {
  if (imageModulePanels) imageModulePanels.toggleVibeClusterLoadMenu(id, event);
}

function toggleVibeClusterManageMenu(id, event) {
  if (imageModulePanels) imageModulePanels.toggleVibeClusterManageMenu(id, event);
}

function loadVibeCluster(id, mode) {
  if (imageModulePanels) imageModulePanels.loadVibeCluster(id, mode);
}

function renameVibeCluster(id) {
  if (imageModulePanels) imageModulePanels.renameVibeCluster(id);
}

function deleteVibeCluster(id) {
  if (imageModulePanels) imageModulePanels.deleteVibeCluster(id);
}

function chooseVibeClusterThumbnail(id) {
  if (imageModulePanels) imageModulePanels.chooseVibeClusterThumbnail(id);
}

function updateVibeClusterThumbnailFromFile(id, file) {
  if (imageModulePanels) imageModulePanels.updateVibeClusterThumbnailFromFile(id, file);
}

function vibeClusterThumbTarget() {
  return imageModulePanels ? imageModulePanels.vibeClusterThumbTargetValue() : '';
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
const DEFAULT_RATING_STATE = {g: true, s: true, q: true, e: false};

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

function toggleSearchParquetMenu(event) {
  if (searchPanelControl) searchPanelControl.toggleParquetMenu(event);
}

function openSearchParquetUpload(action) {
  if (searchPanelControl) searchPanelControl.openParquetUpload(action);
}

function selectSearchParquetMode(mode) {
  if (searchPanelControl) searchPanelControl.selectParquetMode(mode);
}

function searchParquetAction(action) {
  if (searchPanelControl) searchPanelControl.runParquetAction(action);
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
  if (panel?.classList?.contains('vibe-cluster-popover')) return 560;
  if (panel?.classList?.contains('vibe-cluster-save-popover')) return 560;
  if (panel?.classList?.contains('wc-editor-popup')) return 560;
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
  if (wildcardManagerPanel) wildcardManagerPanel.relayout();
  if (imageModulePanels) imageModulePanels.relayoutVibeClusterPanel();
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
const CAT_COLORS = { artist: '#d4736a', copyright: '#a87fd4', character: '#6abf7b', e621: '#d4c36a', wildcard: '#6ac4d4', vibe_cluster: '#9d8bff' };
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

function lookupPromptInfoTag(tag, options = {}) {
  if (tagAssist) tagAssist.lookupPromptInfoTag(tag, options);
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

const tagAssistReady = import('./js/features/tagAssist.mjs?v=20260525-tag-autocomplete-cache1')
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
      getEventPresetPanel: () => eventPresetPanel,
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
function onTagFilterUpdate(m) { if (quickFilter) quickFilter.onUpdate(m); }
function onTagFilterAcResult(m) { if (quickFilter) quickFilter.onAutocompleteResult(m); }
Promise.all([
  quickFilterReady,
  remoteWsClientReady,
  rightTabsReady,
  danbooruTabReady,
  thumbTabReady,
  artistThumbReady,
  characterViewerReady,
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
  promptDrawerReady,
  eventPresetReady,
  autoSavePanelReady,
  saveDirectoryPanelReady,
  sessionGenerationStatsReady,
  automationPanelReady,
  characterPanelReady,
  conditionalPromptPanelReady,
  eventStreamPanelReady,
  wildcardPanelReady,
  wildcardManagerPanelReady,
  instantWildcardPanelReady,
  e621EventPanelReady,
  imageModulePanelsReady,
  img2imgPanelReady,
  refinePanelReady,
  tagSearchReady,
  tagAssistReady,
  mobileViewportReady,
  searchPanelReady,
  chunkPanelReady,
  danbooruFeedbackReady,
  resolutionManagerReady,
  promptEngineeringPopupRenderersReady,
  promptEngineeringPanelReady,
  promptEngineeringActionsReady,
  promptEngineeringPopupsReady,
])
  .then(() => {
    initNaiaTitleTooltips();
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
