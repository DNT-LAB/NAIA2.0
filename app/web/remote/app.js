/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, latestResultBlob = null, generating = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&#39;').replace(/"/g,'&quot;') : '';
let genTimer = null, genStartTime = 0;
const genDurations = [];  // last 5 generation durations (ms)
// Ollama Auto Boost(=Ollama 모드) ON일 때 Random 버튼에 boost 재작성 경과시간을 실시간 표시.
let rndTimer = null, rndStartTime = 0;
const _RND_BTN_LABEL = '<span class="shortcut-hint">ALT + ENTER</span>Random';
let activePromptTab = 'prompt';
let presetGenerationPending = null;
let presetAutoGenToken = 0;
let presetAutoGenTimer = null;
let latestImageMeta = null;

// --- GPU 절약: 창이 비포커스/숨김일 때 모든 CSS 애니메이션 정지 ---
// Electron 컴포지터는 창이 가려져도 무한 애니메이션 때문에 매 프레임을 계속 그려
// backdrop-filter 재계산으로 GPU를 점유한다. 앞에 없을 땐 html.anims-paused로 멈춘다.
(() => {
  const root = document.documentElement;
  const setPaused = (paused) => { if (root) root.classList.toggle('anims-paused', !!paused); };
  const update = () => setPaused(document.hidden || (typeof document.hasFocus === 'function' && !document.hasFocus()));
  window.addEventListener('blur', () => setPaused(true));
  window.addEventListener('focus', () => setPaused(false));
  document.addEventListener('visibilitychange', update);
  update();
})();

// --- GPU-PROBE (진단용·기본 OFF): `?gpuprobe=1` URL 또는 localStorage 'naia_gpuprobe'='1'로만 활성.
//     idle/생성 GPU 소스(rAF 루프·transition·streaming) 추적용. 다시 쓸 수 있어 제거 대신 숨김. ---
(() => {
  try {
    const on = (new URLSearchParams(location.search).get('gpuprobe') === '1')
      || (typeof localStorage !== 'undefined' && localStorage.getItem('naia_gpuprobe') === '1');
    if (!on) return;
  } catch (_) { return; }
  let rafN = 0, rafLast = 0;
  const callers = {};
  const _raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = function (cb) {
    rafN++;
    if (rafN % 3 === 0) {
      try {
        const s = (new Error().stack || '').split('\n');
        const ln = s[2] || s[1] || '';
        const m = ln.match(/([\w.\-]+\.(?:m?js))(?::(\d+))?/);
        const k = m ? (m[1] + (m[2] ? ':' + m[2] : '')) : 'native';
        callers[k] = (callers[k] || 0) + 1;
      } catch (_) {}
    }
    return _raf(cb);
  };
  let imgN = 0, imgLast = 0;
  try {
    const rv = document.getElementById('resultViewer') || document.querySelector('.viewer') || document.body;
    new MutationObserver(() => { imgN++; }).observe(rv, { subtree: true, attributes: true, childList: true, attributeFilter: ['src', 'style', 'class'] });
  } catch (_) {}
  const box = document.createElement('div');
  box.id = '__gpuprobe';
  box.style.cssText = 'position:fixed;left:6px;bottom:6px;z-index:2147483647;background:rgba(0,0,0,0.9);color:#3f6;font:10px/1.4 monospace;padding:6px 8px;border:1px solid #3f6;border-radius:4px;max-width:440px;white-space:pre-wrap;pointer-events:none;';
  const upd = () => {
    try {
      if (document.body && !document.getElementById('__gpuprobe')) document.body.appendChild(box);
      const hz = rafN - rafLast; rafLast = rafN;
      const top = Object.entries(callers).sort((a, b) => b[1] - a[1]).slice(0, 3).map(e => e[0] + '×' + e[1]).join('  ');
      const anims = (document.getAnimations ? document.getAnimations() : []).filter(a => a.playState === 'running');
      const vids = [...document.querySelectorAll('video')];
      const imgHz = imgN - imgLast; imgLast = imgN;
      const animDetail = anims.map(a => {
        const t = a.effect && a.effect.target;
        const tag = t ? (t.id || (t.className || '').toString().split(' ')[0] || t.tagName || '').toString().trim().slice(0, 22) : '';
        return ((a.transitionProperty || a.animationName || (a.constructor && a.constructor.name) || '?')) + '@' + tag;
      }).slice(0, 5).join(' | ');
      box.textContent = 'GPU-PROBE v3\n'
        + 'rafHz=' + hz + '  imgHz=' + imgHz + '\n'
        + 'topRAF: ' + (top || '-') + '\n'
        + 'anims(' + anims.length + '): ' + (animDetail || '-') + '\n'
        + 'paused=' + document.documentElement.classList.contains('anims-paused')
        + '  videos=' + vids.length + '/' + vids.filter(v => !v.paused).length;
    } catch (e) { box.textContent = 'GPU-PROBE err: ' + (e && e.message); }
  };
  setInterval(upd, 1000);
  setTimeout(upd, 600);
})();

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
// SEAM observer (관측 전용 포커스-드롭 탐지기) — 기본 OFF. ?seam=1 또는 localStorage.naia_seam='1' 로 활성.
// 꺼져 있으면 모듈을 동적 import 조차 하지 않는다(오버헤드/위험 0).
const SEAM_OBSERVE = urlParams.get('seam') === '1'
  || (() => { try { return localStorage.getItem('naia_seam') === '1'; } catch (_) { return false; } })();
let seamObserver = null;
if (SEAM_OBSERVE) {
  import('./js/features/seamObserver.mjs?v=20260610-seam2')
    .then(m => { seamObserver = m.seamObserver; seamObserver.init(); })
    .catch(() => {});
}
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
let naiConfigured = false;  // api_status.nai_configured — NAI Director 버튼 게이팅
let grokReady = false;      // progrok proxy 'ready'(로그인 완료) — Grok 컨텍스트 메뉴 게이팅 (Electron 전용)
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

  // 가이드 툴팁(data-naia-guide)은 남색 스타일 + 700ms hover 지연으로 뜬다.
  // 기존 터스(terse)한 title 흡수 툴팁(data-naia-title)은 그대로 즉시 표시.
  const GUIDE_SHOW_DELAY = 700;
  let showTimer = null;

  const showTooltip = target => {
    const guideText = target?.dataset?.naiaGuide || '';
    const text = guideText || target?.dataset?.naiaTitle || '';
    if (!text) return;
    const isGuide = !!guideText;
    const open = () => {
      owner = target;
      // 가이드 툴팁은 줄바꿈(\n 토큰 또는 실제 개행)을 단락으로 렌더 (CSS white-space: pre-line)
      tooltip.textContent = isGuide ? text.replace(/\\n/g, '\n') : text;
      tooltip.classList.toggle('guide', isGuide);
      tooltip.classList.add('open');
      requestAnimationFrame(() => {
        if (owner === target) positionTooltip(target);
      });
    };
    clearTimeout(showTimer);
    // 명시적 [ⓘ 가이드] 버튼은 즉시 표시(의도적으로 올린 것). 기능 컨트롤의 가이드는 700ms 지연.
    const isGuideButton = !!(target.classList && target.classList.contains('header-guide-btn'));
    if (isGuide && !isGuideButton) {
      showTimer = setTimeout(open, GUIDE_SHOW_DELAY);
    } else {
      open();
    }
  };

  const hideTooltip = target => {
    if (target && owner && target !== owner) return;
    clearTimeout(showTimer);
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
    // hover 중이던 owner 가 재렌더로 DOM 에서 사라지면 pointerout 이 오지 않아 툴팁이 남는다
    // (인터랙티브 칩은 편집마다 재렌더됨). 고아 툴팁을 닫는다.
    if (owner && !owner.isConnected) hideTooltip();
  }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['title']});

  document.addEventListener('pointerover', event => {
    const target = event.target?.closest?.('[data-naia-title],[data-naia-guide]');
    if (target) showTooltip(target);
  });
  document.addEventListener('pointerout', event => {
    const target = event.target?.closest?.('[data-naia-title],[data-naia-guide]');
    if (target && !target.contains(event.relatedTarget)) hideTooltip(target);
  });
  document.addEventListener('focusin', event => {
    const target = event.target?.closest?.('[data-naia-title],[data-naia-guide]');
    if (target) showTooltip(target);
  });
  document.addEventListener('focusout', event => {
    const target = event.target?.closest?.('[data-naia-title],[data-naia-guide]');
    if (target) hideTooltip(target);
  });
  window.addEventListener('resize', () => hideTooltip());
  window.addEventListener('scroll', () => hideTooltip(), true);
}

let automationPanel = null;
let characterPanel = null;
let characterAssetControl = null;
let conditionalPromptPanel = null;
let eventStreamPanel = null;
let wildcardPanel = null;
let latestWildcardFreezeState = {locations: [], legacy: [], characters: []};
let frozenWildcardBar = null;
let extensionsPanel = null;
let lastExtensionsState = null;
let wildcardManagerPanel = null;
let instantWildcardPanel = null;
let e621EventPanel = null;
let imageModulePanels = null;
let img2imgPanel = null;
let lastAutoHiddenImg2ImgSubmission = '';
let refinePanelControl = null;
let tagSearchController = null;
let mobileViewportControl = null;
let searchPanelControl = null;
let chunkPanelControl = null;
let sequencePresetControl = null;
let danbooruFeedbackControl = null;
let resolutionManagerPanel = null;
let naiModelManagerPanel = null;
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
const quickFilterReady = import('./js/features/quickFilter.mjs?v=20260714-a3fix')
  .then(({createQuickFilterController}) => {
    quickFilter = createQuickFilterController({
      document,
      localStorage,
      WebSocket,
      getWs: () => ws,
      getRatingState: getRatingStateSnapshot,
      setActiveRatings: setRatingsFromList,
      syncRatingButtons,
      computeLocalFilteredCount: _computeLocalFilteredCount,
      updateSearchCount,
      closeAuxiliaryPopups,
      escHtml,
      catStyle,
      fmtCount,
      showToast,
      lockTagSurface,
      unlockTagSurface,
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
    const activeTab = rightTabs.setAvailability(tabAvailability);
    danbooruTabControl?.setActive?.(activeTab === 'danbooru');
    // Assets 탭이 숨겨지며 Result로 복귀한 경우 컨트롤 활성 상태도 동기화.
    characterAssetControl?.setActive?.(activeTab === 'charAssets');
    return;
  }
  pendingRightTabAvailability = {...(pendingRightTabAvailability || {}), ...tabAvailability};
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
const danbooruTabReady = import('./js/features/danbooruTab.mjs?v=20260714-a3fix')
  .then(({createDanbooruBrowserController}) => {
    danbooruTabControl = createDanbooruBrowserController({
      document,
      fetch: window.fetch.bind(window),
      hostElement: document.getElementById('danbooruTabRoot'),
      onRequestTab: tabName => switchRightTab(tabName),
      // 사용자가 헤더 토글로 팝업/우측탭을 바꾸면 우측 탭 가용성을 재적용한다
      // (팝업 모드=탭 숨김, 탭 모드=탭 노출).
      onDisplayModeChange: mode => applyRightTabAvailability({danbooru: mode === 'tab'}),
      showToast,
      onLoadPrompt,
      onGenerateFromPrompt,
      onInsertImageToHistory: payload => callResultImageAction('insertExternalToHistory', payload),
    });
    applyRightTabAvailability({danbooru: danbooruTabControl.mode === 'app'});
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
const artistThumbReady = import('./js/features/artistThumbTab.mjs?v=20260609-scrollfix1')
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
const characterViewerReady = import('./js/features/characterViewerTab.mjs?v=20260726-cvthumbdel1')
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
const characterAssetReady = import('./js/features/characterAssetTab.mjs?v=20260718-fix3')
  .then(({createCharacterAssetTabController}) => {
    characterAssetControl = createCharacterAssetTabController({
      document,
      fetch: window.fetch.bind(window),
      escHtml,
      showToast,
      showPromptDialog,
      bindTagAssist,
      getGenerationMode: () => currentMode || modeSelect.value || 'NAI',
      // onModuleState가 모든 module_state를 일반 캐시하므로(접속 직후 일괄 요청 포함)
      // 캐릭터 패널을 연 적이 없어도 C1 프리필이 최신 상태를 읽는다.
      getCharacterState: () => moduleStateCache.get('character') || null,
      // CR capability(is_naid45)는 모듈 팝업을 연 적 없어도 캐시에서 읽는다.
      // 게이트에서 버려지는 건 renderModuleState뿐이고 캐시 적재는 그 앞에서 일어난다.
      getCharacterReferenceState: () => moduleStateCache.get('character_reference') || null,
      onReferenceInsetPin: state => setReferenceInsetBadge(state),
    });
    // 리로드 복원: 백엔드 인셋 핀은 리로드와 무관하게 살아 있다(생성이 계속
    // 인셋으로 나감) - 배지가 없으면 사용자가 이유 모를 1152x896 생성을 본다.
    fetch('/api/character-asset/inset/state')
      .then(response => (response.ok ? response.json() : null))
      .then(state => setReferenceInsetBadge(state))
      .catch(() => {});
  })
  .catch(error => {
    console.error('Failed to initialize Character Asset tab module', error);
  });

// ---------------------------------------------------------------------------
// 레퍼런스 인셋 핀 배지 - Result 뷰어 좌상단 고정(캐릭터 에셋 [C1+레퍼런스 인셋]).
// 핀이 살아 있는 동안 plain 생성이 전부 1152x896 인셋 인페인트로 나가므로,
// 항상 보이는 배지 + X 즉시 해제를 제공한다(사용자 계약).
let referenceInsetState = null;

function setReferenceInsetBadge(state) {
  referenceInsetState = state && state.active ? state : null;
  renderReferenceInsetBadge();
}

function syncReferenceInsetWithCharRef(m) {
  // 강제 종료 조건(사용자 계약): CR이 활성화되면 백엔드(_persist 훅)가 인셋 핀을
  // 해제한다 - 여기서는 배지를 서버 상태로 재동기화하고 사용자에게 알린다.
  if (!referenceInsetState) return;
  const frames = Array.isArray(m.frames) ? m.frames : [];
  if (!frames.some(frame => frame && frame.is_enabled)) return;
  fetch('/api/character-asset/inset/state')
    .then(response => (response.ok ? response.json() : null))
    .then(state => {
      if (state && state.active) return;
      setReferenceInsetBadge(null);
      showToast('Character Reference 활성화로 레퍼런스 인셋이 해제되었습니다', 'warning');
    })
    .catch(() => {});
}

function renderReferenceInsetBadge() {
  const viewer = document.getElementById('resultViewer');
  if (!viewer) return;
  let badge = document.getElementById('referenceInsetBadge');
  if (!referenceInsetState) {
    badge?.remove();
    return;
  }
  const characterId = String(referenceInsetState.character_id || '');
  const variation = String(referenceInsetState.variation || '');
  const thumb = `/api/character-asset/thumb?id=${encodeURIComponent(characterId)}`
    + (variation ? `&variation=${encodeURIComponent(variation)}` : '') + '&size=grid';
  if (!badge) {
    badge = document.createElement('div');
    badge.id = 'referenceInsetBadge';
    badge.className = 'reference-inset-badge';
    viewer.appendChild(badge);
  }
  badge.innerHTML = `
    <img src="${thumb}" alt="레퍼런스 인셋 핀">
    <button type="button" class="reference-inset-badge-x" aria-label="레퍼런스 인셋 해제">x</button>
    <div class="reference-inset-badge-label">레퍼런스 인셋<br>1152x896 고정</div>`;
  badge.querySelector('.reference-inset-badge-x').onclick = async () => {
    try {
      await fetch('/api/character-asset/inset/unpin', {method: 'POST'});
    } catch (error) {
      console.error('reference inset unpin failed', error);
    }
    setReferenceInsetBadge(null);
    showToast('레퍼런스 인셋 핀 해제됨 - 일반 생성으로 복귀합니다', 'success');
  };
}
const studioTabReady = import('./js/features/studioTab.mjs?v=20260713-frame-cfg1')
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
      getCurrentCfgScale: () => paramEls.cfg_scale?.value || '',
      isCfgScaleLocked: () => isComfyUiFreeWorkflowActive(),
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
const customSelectsReady = import('./js/features/customSelects.mjs?v=20260602-director7')
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
const resultHistoryReady = import('./js/features/resultHistory.mjs?v=20260802-quicksave11')
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
      confirmDialog: showConfirmDialog,
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

const resultImageActionsReady = import('./js/features/resultImageActions.mjs?v=20260618-outpaint')
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
const metadataViewerReady = import('./js/features/metadataViewer.mjs?v=20260705-vibe-charref')
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
const imageActionPopupReady = import('./js/features/imageActionPopup.mjs?v=20260602-insert-history1')
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
      onInsertHistory: payload => callResultImageAction('insertExternalToHistory', payload),
      onMetadata: payload => {
        // 모바일은 메타데이터 탭이 없다 — 보이지 않는 곳에 로드하고 Result로
        // 강제되는 침묵 동작 대신 명시적으로 안내한다.
        if (!isDetachedShell && !isPC.matches) {
          showToast('모바일에서는 메타데이터 탭을 지원하지 않습니다. PC 화면에서 확인하세요.', 'info');
          return;
        }
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
const resultContextMenuReady = import('./js/features/resultContextMenu.mjs?v=20260717-charasset1')
  .then(({createResultContextMenu}) => {
    resultContextMenu = createResultContextMenu({
      document,
      window,
      fetch,
      showToast,
      escHtml,
      // 모바일(비분리창)은 우측 탭이 없으므로 '탭에서 보기' 항목을 숨긴다.
      canUseTabView: () => isDetachedShell || isPC.matches,
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
      onInstantOutpaint: context => callResultImageAction('outpaintFromContext', context),
      onWebUiEnhance: context => requestResultEnhanceFromContext(context),
      onGrokI2I: context => { if (grokI2iModal) grokI2iModal.open(context); },
      onGrokI2V: context => { if (grokI2vModal) grokI2vModal.open(context); },
      onDirector: context => openNaiDirector(context),
      onSetCharacterReference: context => callResultImageAction('requestContextImageAction', context, 'character_reference'),
      onSetVibeTransfer: context => callResultImageAction('requestContextImageAction', context, 'vibe'),
      onSaveCharacterAsset: context => {
        if (!characterAssetControl) {
          showToast('Character Asset tab is not ready', 'error');
          return;
        }
        // 클릭 시점의 이미지를 안정 경로로 고정한다 - '현재 결과'는 rel_path가
        // 없으므로 히스토리 최신 항목(__history_item__/{id})으로 핀한다. 저장
        // 버튼을 누르기 전에 새 결과가 도착해도 대상이 바뀌지 않는다.
        const pinnedPath = String(context?.path || '')
          || (resultHistory ? String(resultHistory.latestImagePath || '') : '');
        if (!pinnedPath) {
          showToast('저장할 이미지를 특정할 수 없습니다', 'error');
          return;
        }
        characterAssetControl.stageFromContext({...(context || {}), path: pinnedPath});
        switchRightTab('charAssets');
      },
      onDelete: (context, mode) => deleteResultFromContext(context, mode),
      onQueueResult: (context, options) => callResultImageAction('queueResultFromContext', context, options),
      getWildcardFreezeState: () => latestWildcardFreezeState,
      setWildcardFreezeState: state => { updateFrozenWildcardBar(state); },
      onToggleWildcardFreeze: (payload, freeze) => {
        setModuleParam('wildcard', freeze ? 'wildcard_freeze' : 'wildcard_unfreeze', JSON.stringify(payload || {}));
      },
      canUseDesktopImg2Img,
      canOpenLocalFiles: () => isLocalWebHost || isDesktopShell,
      isGrokReady: () => grokReady,  // Grok 변형/영상 항목은 로그인(proxy ready) 시에만 표시
    });
    resultContextMenu.bind();
  })
  .catch(error => {
    console.error('Failed to initialize result context menu module', error);
  });
const frozenWildcardBarReady = import('./js/features/frozenWildcardBar.mjs?v=20260705-multichar')
  .then(({createFrozenWildcardBar}) => {
    frozenWildcardBar = createFrozenWildcardBar({
      document,
      mount: document.getElementById('frozenWcBar'),
      escHtml,
      onUnfreeze: payload => setModuleParam('wildcard', 'wildcard_unfreeze', JSON.stringify(payload || {})),
      onReroll: payload => setModuleParam('wildcard', 'wildcard_reroll', JSON.stringify(payload || {})),
      onUnfreezeAll: payloads => (payloads || []).forEach(payload =>
        setModuleParam('wildcard', 'wildcard_unfreeze', JSON.stringify(payload || {}))),
    });
    frozenWildcardBar.render(latestWildcardFreezeState);
  })
  .catch(error => {
    console.error('Failed to initialize frozen wildcard bar module', error);
  });
let interactivePanel = null;
// WS 응답 라우팅. 모듈 로드 전에 도착한 메시지는 조용히 버려진다(요청한 적이 없으므로 안전).
let eventCorpusHandlers = null;
let resetEventCorpus = () => {};
let interactiveAutocomplete = null;
let interactiveAssetsPanel = null;
// Interactive 전용 캐릭터 레퍼런스. NAI 모듈과 상태가 독립이다.
let interactiveReferencePanel = null;
const interactiveReferenceReady = import('./js/features/interactiveReferencePanel.mjs?v=20260805-iref4')
  .then(({createInteractiveReferencePanel}) => {
    interactiveReferencePanel = createInteractiveReferencePanel({
      document, escHtml, showToast,
      getInteractivePanel: () => interactivePanel,
      // 붙이거나 뗄 때마다 캐릭터 헤더의 [Reference] 배지를 맞춘다.
      onChange: () => { if (interactivePanel) interactivePanel.refreshCharReference(); },
    });
    // **만들자마자 서버 상태를 한 번 읽는다.** 백엔드는 그대로 두고 브라우저만
    // 새로고침하면 패널은 기본값(OFF·배지 0)으로 시작하는데 백엔드는 켜진 채라,
    // 화면은 꺼졌다고 하면서 레퍼런스가 유료 생성에 실린다(Codex 지적 2026-08-05).
    // 이 기능 자체가 그 어긋남을 막으려고 만든 것이라 여기서 반드시 맞춘다.
    return interactiveReferencePanel.refresh();
  })
  .catch(error => console.error('Failed to init interactive reference panel', error));
const interactivePanelReady = import('./js/features/interactivePanel.mjs?v=20260805-ia191')
  .then(async ({createInteractivePanel}) => {
    const {
      requestEventCorpusQuery, requestEventCorpusStatus,
      onEventCorpusStatusResult, onEventCorpusQueryResult, resetEventCorpusClient,
    } = await import('./js/features/eventCorpusClient.mjs?v=20260723-ia1');
    const {createInteractiveAutocomplete} =
      await import('./js/features/interactiveAutocomplete.mjs?v=20260724-iac1');
    const {createInteractiveAssetsPanel} =
      await import('./js/features/interactiveAssetsPanel.mjs?v=20260805-iaas34');
    eventCorpusHandlers = {onStatus: onEventCorpusStatusResult, onQuery: onEventCorpusQueryResult};
    resetEventCorpus = resetEventCorpusClient;
    const wsSend = payload => {
      if (!ws || ws.readyState !== WebSocket.OPEN) throw Object.assign(new Error('offline'), {code: 'disconnected'});
      ws.send(JSON.stringify(payload));
    };
    interactiveAutocomplete = createInteractiveAutocomplete({document, window, escHtml, send: wsSend});
    // 조합 스냅샷 컨트롤(결과 좌하단). 패널을 늦게 참조하는 이유는 아래에서 만들기 때문.
    interactiveAssetsPanel = createInteractiveAssetsPanel({
      document, escHtml, showToast, showAppDialog, getPanel: () => interactivePanel,
    });
    interactivePanel = createInteractivePanel({
      document,
      blocksMount: $('iaBlocks'),
      panelMount: $('iaPanel'),
      toggleButton: $('iaModeToggle'),
      escHtml,
      showToast,
      autocomplete: interactiveAutocomplete,
      // 슬롯 입력창(textarea)에 범용 자동완성을 붙인다. 팝업 검색창에는 붙이지 않는다.
      bindTagAssist,
      getMode: () => currentMode || modeSelect?.value || 'NAI',
      // 베이스 프롬프트의 선행·후행. 모듈 상태는 접속 직후 일괄 캐시되므로
      // PE 패널을 연 적이 없어도 최신 값을 읽는다.
      getPromptEngineering: () => moduleStateCache.get('prompt_engineering') || null,
      // 반응형 생성. 생성 중이면 패널이 변화를 모았다가 끝난 뒤 한 번만 낸다.
      isGenerating: () => generating,
      // **정식 경로로 보낸다.** `requestGenerate()` 를 직접 부르면 빈 페이로드가 나가
      // 프롬프트도 Interactive 캐릭터 오버라이드도 실리지 않는다(실측: 요청은 가는데
      // 아무 일도 안 일어났다). `send('generate')` 가 프롬프트·네거티브·오버라이드·
      // Assets 스냅샷까지 조립한다.
      requestGeneration: () => send('generate'),
      // 캐릭터 헤더의 [Reference] — 세션 CR 모듈을 연다. 패널을 복제하지 않는 이유는
      // 같은 상태를 두 곳에서 그리면 한쪽만 낡기 때문이다(이 저장소의 단골 사고).
      onCharReference: () => {
        // 모듈 로딩이 아직이면 **끝난 뒤에 연다.** 예전에는 조용히 아무 일도
        // 안 일어나서 버튼이 고장 난 것처럼 보였다(2026-08-05 Codex 지적).
        if (interactiveReferencePanel) { interactiveReferencePanel.toggle(); return; }
        interactiveReferenceReady
          .then(() => interactiveReferencePanel && interactiveReferencePanel.toggle())
          .catch(() => showToast('레퍼런스 패널을 불러오지 못했습니다', 'error'));
      },
      // 버튼에 붙일 개수 배지의 근거. 켜 둔 프레임만 센다.
      // 배지는 **Interactive 전용 패널**의 개수를 센다. NAI 모듈 상태를 세면
      // 남의 상태를 표시하게 된다(2026-08-04 분리).
      getCharacterReferenceState: () =>
        (interactiveReferencePanel ? {count: interactiveReferencePanel.count()} : null),
      // 자동완성 '대상'이 아니라 '실제로 열려 있는지'를 넘긴다 — tagAssist 는 드롭다운을 닫아도
      // acTarget 을 비우지 않으므로, 대상만 보면 Enter/Escape 를 영원히 양보해 슬롯 편집이
      // 닫히지 않는다(실측 확인).
      getAutocompleteTarget: () => (isTagAutocompleteOpen() ? getTagAssistTarget() : null),
      queryCorpus: params => requestEventCorpusQuery(wsSend, params),
      corpusStatus: () => requestEventCorpusStatus(wsSend),
      onPromptChange: promptText => {
        // 작업 결과를 기억한다 — 블록을 만질 때마다 여기로 온다.
        scheduleInteractiveStateSave();
        // 블록 -> 프롬프트 문자열. Interactive 가 켜져 있는 동안 프롬프트의 소유자는 블록이다.
        //
        // 'input' 이벤트를 dispatch 하면 안 된다 — 프롬프트 자동완성이 그 경로에 붙어 있어서
        // 블록에서 태그를 넣을 때마다 엉뚱한 자동완성 팝업이 뜬다(라이브 테스트에서 확인).
        // 하이라이트/토큰/백엔드 전송만 필요하므로 onPromptEdit() 을 직접 부른다.
        if (promptEdit && promptEdit.value !== promptText) {
          promptEdit.value = promptText;
          onPromptEdit();
        }
      },
      onActiveChange: applyInteractiveModeGate,
      // 캐릭터 스택(Assets 바)이 현재 슬롯 목록을 따라간다.
      onRosterChange: rosterRows => {
        if (interactiveAssetsPanel) interactiveAssetsPanel.setRoster(rosterRows);
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize interactive panel module', error);
  });

// Interactive 모드에서는 Prompt Fixed / WC Solo 를 쓸 수 없다. 블록에서 프롬프트를
// 결정론적으로 조립하는데, prompt_fixed(랜덤 생성 잠금)와 wildcard_standalone(빈 source_row)
// 은 서로 다른 소스를 다투게 만든다.
//
// 여기서 하는 것은 **표시 전용**이다. 저장된 사용자 옵션 값은 건드리지 않는다 — set_option 은
// 전 클라이언트에 broadcast 되고 remote_options 로 영속되므로, 한 탭이 Interactive 를 켰다고
// 다른 탭의 설정과 저장값을 꺼버리면 안 된다. 실제 강제는 백엔드가 생성 요청 단위로 한다
// (app/backend/server/event_corpus_commands.py: apply_interactive_generation_gate).
const INTERACTIVE_BLOCKED_OPTIONS = ['prompt_fixed', 'wildcard_standalone'];

// ---- Interactive 작업 결과 보존 ----
// 브라우저 저장소에 둔다. 이건 순수 UI 조립 상태라 서버 세션 스키마
// (`app_settings.json` 의 remote_ui_state)를 넓힐 일이 아니고, Electron 은 프로필이
// 하나라 재시작해도 같은 값을 읽는다.
const INTERACTIVE_STATE_KEY = 'naia.interactive.state.v1';
let interactiveStateSaveTimer = null;

function scheduleInteractiveStateSave() {
  if (!interactivePanel?.exportState) return;
  if (interactiveStateSaveTimer) clearTimeout(interactiveStateSaveTimer);
  // 슬롯을 연타할 때마다 직렬화하지 않는다.
  interactiveStateSaveTimer = setTimeout(() => {
    interactiveStateSaveTimer = null;
    try {
      localStorage.setItem(INTERACTIVE_STATE_KEY,
                           JSON.stringify(interactivePanel.exportState()));
    } catch (_) { /* 용량 초과·프라이빗 모드 — 기억 못 하는 것이 기능을 막지는 않는다 */ }
  }, 400);
}

/** 디바운스 안에 닫으면 마지막 변경이 사라진다 — 언로드 시 즉시 쓴다. */
function flushInteractiveStateSave() {
  if (!interactiveStateSaveTimer) return;
  clearTimeout(interactiveStateSaveTimer);
  interactiveStateSaveTimer = null;
  try {
    localStorage.setItem(INTERACTIVE_STATE_KEY,
                         JSON.stringify(interactivePanel.exportState()));
  } catch (_) { /* 기억 못 하는 것이 종료를 막지는 않는다 */ }
}
window.addEventListener('pagehide', flushInteractiveStateSave);
// Electron 은 창을 숨기고 죽는 경우가 있어 pagehide 가 늦는다 — 숨김도 함께 본다.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushInteractiveStateSave();
});

function restoreInteractiveState() {
  if (!interactivePanel?.importState) return;
  try {
    const raw = localStorage.getItem(INTERACTIVE_STATE_KEY);
    if (raw) interactivePanel.importState(JSON.parse(raw));
  } catch (_) { /* 깨진 저장분은 무시하고 빈 상태로 시작한다 */ }
}
// Interactive 를 켜기 **직전**의 메인 프롬프트. 모드를 끄면 이걸로 되돌린다.
// Interactive 는 입력창을 자기 렌더값으로 덮어쓰는데, 예전에는 끌 때도 그 값이 남아
// **사용자가 쓰던 메인 프롬프트가 증발했다**(2026-08-05 사용자 지적).
// 블록 상태는 그대로 살아 있으니 다시 켜면 Interactive 프롬프트가 재조립된다 —
// 되돌린다고 잃는 것은 없다.
let promptBeforeInteractive = null;
let interactiveStateRestored = false;

function applyInteractiveModeGate(isActive) {
  // Interactive 에서는 최종 프롬프트를 상시 노출하지 않는다(사용자 결정). 전체 문자열은
  // 나중에 별도 미리보기 팝업으로만 확인한다.
  if (isActive) {
    // **원본을 먼저 잡는다.** `restoreInteractiveState()` 는 살아 있는 패널에
    // emitChange 를 일으켜 입력창을 조립값으로 덮는다 — 복원을 먼저 하면 그 조립값을
    // '사용자 원본'으로 잡아 두게 되고, 모드를 꺼도 원본이 안 돌아온다
    // (2026-08-05 Codex 지적: 저장된 작업 결과가 있을 때만 재현되는 순서 버그).
    if (promptBeforeInteractive === null && promptEdit) {
      promptBeforeInteractive = String(promptEdit.value || '');
    }
    // 지난 작업 결과를 되돌린다. 켤 때 한 번만 — 이후에는 살아 있는 상태가 진실이다.
    if (!interactiveStateRestored) { interactiveStateRestored = true; restoreInteractiveState(); }
  } else if (promptBeforeInteractive !== null) {
    if (promptEdit && promptEdit.value !== promptBeforeInteractive) {
      promptEdit.value = promptBeforeInteractive;
      onPromptEdit();          // 하이라이트·토큰 수·백엔드 동기화를 함께 되돌린다
    }
    promptBeforeInteractive = null;
  }
  document.body.classList.toggle('interactive-mode', !!isActive);
  // 베이스 프롬프트에 선행·후행을 넣으려면 PE 상태가 있어야 한다. 부팅 시 일괄
  // 캐시되는 모듈이 아니라(실측) 여기서 한 번 당겨 온다 — 도착하면 onPromptEngineeringState
  // 가 캐시에 넣고 refreshPrompt() 를 불러 프롬프트가 다시 조립된다.
  if (isActive && !moduleStateCache.get('prompt_engineering')) {
    requestModuleState('prompt_engineering');
  }
  // Assets 바는 Interactive 의 도구다 — 모드를 끄면 같이 사라진다.
  if (interactiveAssetsPanel) {
    interactiveAssetsPanel.setVisible(!!isActive);
    // 켜는 순간의 캐릭터 목록을 한 번 밀어 넣는다 — onRosterChange 는 '변할 때'만 온다.
    if (isActive && interactivePanel?.getCharacterRoster) {
      try { interactiveAssetsPanel.setRoster(interactivePanel.getCharacterRoster()); } catch (_) {}
    }
  }
  for (const key of INTERACTIVE_BLOCKED_OPTIONS) {
    const control = optBoxes[key];
    if (!control) continue;
    control.disabled = !!isActive;
    control.classList.toggle('is-disabled', !!isActive);
    control.title = isActive
      ? 'Interactive 모드에서는 사용할 수 없습니다 (블록이 프롬프트를 직접 조립합니다).'
      : '';
  }
  // Random 잠금 상태도 여기서 맞춘다 — 토글 직후 버튼이 남아 있으면 눌린다.
  if (typeof unlockRandomButton === 'function') unlockRandomButton({clearRequest: false});
  updateInteractiveNaiToolBlock();
}

// Interactive 모드에서는 NAI 전용 **Character** 도구만 차단한다 —
// 캐릭터 프롬프트는 Interactive 블록이 소유하므로 두 소스가 다투면 안 된다.
// Character Reference 는 다투지 않는다: 프롬프트가 아니라 **이미지**다. 예전엔 한 줄로
// 묶어 같이 막았고, 그래서 캐릭터 헤더의 [Reference] 가 목업으로 남아 있었다.
// 이제 그 버튼이 이 모듈을 연다(interactivePanel 의 onCharReference).
// (백엔드 스트립은 캐릭터->생성 배선 Phase 2 와 함께 처리한다.)
// Interactive 는 캐릭터 블록이 프롬프트의 소유자이고, 레퍼런스도 전용 패널이
// 따로 있다(상태 독립). 둘 다 NAI 모듈을 열면 상태가 갈라진다.
const INTERACTIVE_BLOCKED_NAI_TOOLS = ['character', 'character_reference'];
function updateInteractiveNaiToolBlock() {
  const blocked = document.body.classList.contains('interactive-mode');
  INTERACTIVE_BLOCKED_NAI_TOOLS.forEach(mid => {
    const btn = document.querySelector(`.module-btn[data-module="${mid}"]`);
    if (btn) btn.classList.toggle('interactive-blocked', blocked);
  });
  if (blocked && INTERACTIVE_BLOCKED_NAI_TOOLS.includes(currentModuleId)) {
    closeModule({ keepChunk: false });
  }
}

const promptHighlighterReady = import('./js/features/promptHighlighter.mjs?v=20260603-caret-align1')
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
const moduleBadgesReady = import('./js/features/moduleBadges.mjs?v=20260527-automation-countdown1')
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
const cloudflaredControlsReady = import('./js/features/cloudflaredControls.mjs?v=20260606-lan-link2')
  .then(({createCloudflaredControls}) => {
    cloudflaredControls = createCloudflaredControls({
      document,
      getWs: () => ws,
      WebSocket,
      getApiStatus: () => setupController ? setupController.getApiStatus() : null,
      navigator,
      showToast,
      openUrlInSystemBrowser,
    });
  })
  .catch(error => {
    console.error('Failed to initialize cloudflared controls module', error);
  });
const setupControllerReady = import('./js/features/setupController.mjs?v=20260716-sleepwake-reprobe1')
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
// --- Grok(xAI) I2I 연동 패널 (제거 가능): Setup 모달의 격리된 REST 전용 컨트롤러 ---
let grokConnectPanel = null;
const grokConnectPanelReady = import('./js/features/grokConnectPanel.mjs?v=20260602-grok8')
  .then(({createGrokConnectPanel}) => {
    grokConnectPanel = createGrokConnectPanel({document, fetch: window.fetch.bind(window), showToast});
  })
  .catch(error => {
    console.error('Failed to initialize grok connect panel module', error);
  });
// --- Grok I2I 모달 (제거 가능): 우클릭 → 이미지 변형 ---
let grokI2iModal = null;
const grokI2iModalReady = import('./js/features/grokI2iModal.mjs?v=20260602-grok14')
  .then(({createGrokI2iModal}) => {
    grokI2iModal = createGrokI2iModal({document, getWs: () => ws, WebSocket, showToast, escHtml});
  })
  .catch(error => {
    console.error('Failed to initialize grok i2i modal module', error);
  });
// --- Grok I2V 모달 (제거 가능): 우클릭 → 이미지→영상 ---
let grokI2vModal = null;
const grokI2vModalReady = import('./js/features/grokI2vModal.mjs?v=20260602-grok17')
  .then(({createGrokI2vModal}) => {
    grokI2vModal = createGrokI2vModal({document, getWs: () => ws, WebSocket, showToast, escHtml, fetch: window.fetch.bind(window)});
  })
  .catch(error => {
    console.error('Failed to initialize grok i2v modal module', error);
  });
// --- NAI Director Tools 모달 (제거 가능): GENERATION INFO [Director] → 현재 결과 변형 ---
let naiDirectorModal = null;
const naiDirectorModalReady = import('./js/features/naiDirectorModal.mjs?v=20260602-director5')
  .then(({createNaiDirectorModal}) => {
    naiDirectorModal = createNaiDirectorModal({document, getWs: () => ws, WebSocket, showToast, escHtml, bindTagAssist});
  })
  .catch(error => {
    console.error('Failed to initialize nai director modal module', error);
  });
// --- Ollama Local Assistant popup: Tools & Assistants 헤더 버튼 → 로컬 LLM 슬롯(초기 hold) ---
let ollamaAssistantPopup = null;
const ollamaAssistantPopupReady = import('./js/features/ollamaAssistantPopup.mjs?v=20260618-related-curated2')
  .then(({createOllamaAssistantPopup}) => {
    ollamaAssistantPopup = createOllamaAssistantPopup({
      document,
      showToast,
      escHtml,
      // Electron 셸에서 설치 페이지(ollama.com)를 내부 팝업 대신 시스템 브라우저로.
      openUrlInSystemBrowser,
      // 어시스트 결과 태그를 메인 프롬프트 끝에 덧붙인다.
      onInsertTags: text => {
        const tags = String(text || '').trim();
        if (!tags || !promptEdit) return;
        const current = promptEdit.value.replace(/[,\s]+$/, '');
        promptEdit.value = current ? `${current}, ${tags}` : tags;
        onPromptEdit();
        showToast('프롬프트에 추가했습니다.', 'success');
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize ollama assistant popup module', error);
  });
let ollamaChatPopup = null;
const ollamaChatPopupReady = import('./js/features/ollamaChatPopup.mjs?v=20260618-related-curated2')
  .then(({createOllamaChatPopup}) => {
    ollamaChatPopup = createOllamaChatPopup({
      document, window, showToast, escHtml,
      getContext: () => ({
        prompt: promptEdit?.value || '',
        tags: Array.from(new Set([
          ...Array.from(resultInfoContent?.querySelectorAll?.('.generation-info-tag[data-tag]') || [])
            .map(el => el?.dataset?.tag || ''),
          ...String(promptEdit?.value || '').split(','),
        ].map(tag => String(tag || '').trim()).filter(Boolean))).slice(0, 200),
        negative: negEdit?.value || '',
        resultInfo: resultInfoContent?.innerText || '',
      }),
      lookupTagInfo: lookupPromptInfoTag,
      hideTagInfo: () => tagAssist?.hidePromptInfoTooltip?.(),
    });
  })
  .catch(error => {
    console.error('Failed to initialize ollama chat popup module', error);
  });
// --- Translation History: Ollama 팝업이 소유하는 우측 도킹 2단 패널(translationHistoryPanel).
// 팝업의 작은 [🕘 기록] 버튼이 토글하며, 첫 클릭 때 지연 로드된다(ollamaAssistantPopup.mjs).
// app.js는 더 이상 직접 인스턴스화하지 않는다. ---
let translationHistoryPanel = null;
const translationHistoryPanelReady = Promise.resolve();
// --- Grok 로그인 상태 추적 (제거 가능): progrok proxy 가 'ready'(OAuth 로그인 완료)일 때만 결과
// 우클릭의 'Grok 변형/영상' 항목을 노출한다. Electron 전용(naiaShell 없으면 false=숨김 → 순수 브라우저도 숨김). ---
(function trackGrokReady() {
  const s = (typeof window !== 'undefined') ? window.naiaShell : null;
  if (!s || typeof s.onGrokStateChanged !== 'function') { grokReady = false; return; }
  const apply = (state) => { grokReady = !!state && state.proxyState === 'ready'; };
  if (typeof s.grokState === 'function') { s.grokState().then(apply).catch(() => {}); }
  s.onGrokStateChanged(apply);
})();
// --- Grok 영상 히스토리 클릭→재생 (제거 가능): 영상 썸네일 클릭 시 실제 mp4 재생 ---
let grokVideoHistory = null;
const grokVideoHistoryReady = import('./js/features/grokVideoHistory.mjs?v=20260602-grok12')
  .then(({createGrokVideoHistory}) => {
    grokVideoHistory = createGrokVideoHistory({document, fetch: window.fetch.bind(window)});
    grokVideoHistory.bind();
  })
  .catch(error => {
    console.error('Failed to initialize grok video history module', error);
  });
let dataMigrationPanel = null;
const dataMigrationReady = import('./js/features/dataMigrationPanel.mjs?v=20260606-migration7')
  .then(({createDataMigrationPanel}) => {
    dataMigrationPanel = createDataMigrationPanel({document, showToast});
  })
  .catch(error => {
    console.error('Failed to initialize data migration panel module', error);
  });
let dataBootstrapPanel = null;
const dataBootstrapReady = import('./js/features/dataBootstrapPanel.mjs?v=20260528-bootstrap2')
  .then(({createDataBootstrapPanel}) => {
    dataBootstrapPanel = createDataBootstrapPanel({
      document,
      showToast,
      // Reuse the existing migration popup; the user picks the previous NAIA
      // install and the data/tags bucket now appears in the bucket list.
      onOpenMigration: () => { if (dataMigrationPanel) dataMigrationPanel.open(); },
    });
    dataBootstrapPanel.init();
  })
  .catch(error => {
    console.error('Failed to initialize data bootstrap panel module', error);
  });
let updateBanner = null;
const updateBannerReady = import('./js/features/updateBannerControls.mjs?v=20260607-srcupd2')
  .then(({createUpdateBanner}) => {
    updateBanner = createUpdateBanner({document, showToast, confirmDialog: showConfirmDialog});
    updateBanner.init();
  })
  .catch(error => {
    console.error('Failed to initialize update banner module', error);
  });
const generationProgressReady = import('./js/features/generationProgress.mjs?v=20260617-gpufix')
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
const eventPresetReady = import('./js/features/eventPresetPanel.mjs?v=20260609-scrollfix1')
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
const autoSavePanelReady = import('./js/features/autoSavePanel.mjs?v=20260802-quicksave2')
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
      showAppDialog,
    });
  })
  .catch(error => {
    console.error('Failed to initialize auto save panel module', error);
  });
const saveDirectoryPanelReady = import('./js/features/saveDirectoryPanel.mjs?v=20260622-savedir-picker2')
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
const automationPanelReady = import('./js/features/automationPanel.mjs?v=20260530-automation-enh2')
  .then(({createAutomationPanel}) => {
    automationPanel = createAutomationPanel({
      document,
      setModuleParam,
    });
  })
  .catch(error => {
    console.error('Failed to initialize automation panel module', error);
  });
const characterPanelReady = import('./js/features/characterPanel.mjs?v=20260717-charasset2')
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
const conditionalPromptPanelReady = import('./js/features/conditionalPromptPanel.mjs?v=20260703-cond-split')
  .then(({createConditionalPromptPanel}) => {
    conditionalPromptPanel = createConditionalPromptPanel({
      document,
      escHtml,
      onModTextEdit,
      setModuleParam,
      bindTagAssist,
    });
  })
  .catch(error => {
    console.error('Failed to initialize conditional prompt panel module', error);
  });
const eventStreamPanelReady = import('./js/features/eventStreamPanel.mjs?v=20260607-stvibe-halve1')
  .then(({createEventStreamPanel}) => {
    eventStreamPanel = createEventStreamPanel({
      document,
      escHtml,
      setModuleParam,
      runStorytellerCycle,
      bindTagAssist,
      getApiMode: () => currentMode || modeSelect?.value || '',
    });
  })
  .catch(error => {
    console.error('Failed to initialize event stream panel module', error);
  });
const wildcardPanelReady = import('./js/features/wildcardPanel.mjs?v=20260704-wc-folder2')
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
let pendingExtLauncherItems = null;
function setExtensionLauncherItems(items, onClick) {
  if (moduleLauncherControl && typeof moduleLauncherControl.setExtensionItems === 'function') {
    moduleLauncherControl.setExtensionItems(items, onClick);
    // setExtensionItems → render() 가 leaf 버튼을 통째로 다시 그려 char-active/vibe-active/
    // auto-active 클래스를 날린다(그 후 updateCharacter 등은 모듈 상태 도착 때만 재호출). 확장
    // 리로드가 이 순서로 끼면 요약(Activated:)은 moduleBadges 캐시라 유지되지만 "NAI 전용
    // 도구"/Automation 카테고리 버튼은 비활성으로 보였다(Bug 1). 캐시 상태를 replay해 복원.
    replayLauncherModuleStates();
    moduleLauncherControl.updateState();
    return;
  }
  pendingExtLauncherItems = {items, onClick}; // 런처 모듈 초기화 후 flush
}
const extensionsPanelReady = import('./js/features/extensionsPanel.mjs?v=20260613-extsample')
  .then(({createExtensionsUi}) => {
    extensionsPanel = createExtensionsUi({
      document,
      escHtml,
      setModuleParam,
      showToast,
      requestState: () => requestModuleState('extensions'),
      setLauncherItems: setExtensionLauncherItems,
      openExternalUrl: openUrlInSystemBrowser,
    });
    if (lastExtensionsState) extensionsPanel.onState(lastExtensionsState);
  })
  .catch(error => {
    console.error('Failed to initialize extensions UI module', error);
  });
// Settings > Global > 폰트. 저장된 선택 자체는 index.html 의 인라인 부트 스크립트가
// 이미 적용해 둔 상태이고, 여기서는 UI 를 붙이고 서버 폰트 목록을 채운다.
let fontSettingsPanel = null;
const fontSettingsPanelReady = import('./js/features/fontSettingsPanel.mjs?v=20260722-font2')
  .then(({createFontSettingsPanel}) => {
    fontSettingsPanel = createFontSettingsPanel({
      document,
      localStorage,
      escHtml,
      showToast,
      confirmDialog: showConfirmDialog,
    });
    fontSettingsPanel.init();
  })
  .catch(error => {
    console.error('Failed to initialize font settings panel module', error);
  });
const wildcardManagerPanelReady = import('./js/features/wildcardManagerPanel.mjs?v=20260704-wc-folder2')
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
const e621EventPanelReady = import('./js/features/e621EventPanel.mjs?v=20260603-e621-focus1')
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
const imageModulePanelsReady = import('./js/features/imageModulePanels.mjs?v=20260805-cra5')
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
      // 캐릭터 에셋의 프롬프트를 Interactive 슬롯으로 나눠 넣을 때만 쓴다.
      // 게터로 넘기는 이유는 이 패널이 Interactive 패널보다 먼저 만들어지기 때문이다.
      getInteractivePanel: () => interactivePanel,
    });
  })
  .catch(error => {
    console.error('Failed to initialize image module panels', error);
  });
const img2imgPanelReady = import('./js/features/img2imgPanel.mjs?v=20260713-lifecycle1')
  .then(({createImg2ImgPanel}) => {
    img2imgPanel = createImg2ImgPanel({
      document,
      moduleBody,
      escHtml,
      setModuleParam,
      onModTextEdit,
      flushPendingModuleEdit,
      showToast,
      bindTagAssist,
      // V3 인페인트는 디노이징 미지원 → 강도 슬라이더 숨김(백엔드 img2img.strength 게이트와 동일 기준).
      hideInpaintStrength: () => naiModelBlocksReference(),
    });
  })
  .catch(error => {
    console.error('Failed to initialize Img2Img panel', error);
  });
const refinePanelReady = import('./js/features/refinePanel.mjs?v=20260530-refine-tab6')
  .then(({createRefinePanel}) => {
    refinePanelControl = createRefinePanel({
      document,
      container: refineView,
      escHtml,
      getWs: () => ws,
      WebSocket,
      enterMode: refineEnterMode,
      exitMode: refineExitMode,
      bindTagAssist,
    });
  })
  .catch(error => {
    console.error('Failed to initialize refine panel module', error);
  });
const tagSearchReady = import('./js/features/tagSearch.mjs?v=20260609-scrollfix1')
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
const mobileViewportReady = import('./js/features/mobileViewport.mjs?v=20260606-mobile-ui3')
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
const searchPanelReady = import('./js/features/searchPanel.mjs?v=20260714-predeploy1')
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
      lockTagSurface,
      unlockTagSurface,
    });
  })
  .catch(error => {
    console.error('Failed to initialize search panel module', error);
  });
const chunkPanelReady = import('./js/features/chunkPanel.mjs?v=20260606-remote-entry1')
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
      onOpenRemote: target => openRemotePanel(target),
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
const sequencePresetReady = import('./js/features/sequencePresetPanel.mjs?v=20260607-seqvibe6')
  .then(({createSequencePresetPanel}) => {
    sequencePresetControl = createSequencePresetPanel({
      panel: $('sequencePresetPanel'),
      escHtml,
      showToast,
      bindTagAssist,
      getApiMode: () => currentMode || modeSelect?.value || '',
    });
  })
  .catch(error => {
    console.error('Failed to initialize Sequence Preset panel', error);
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
const naiModelManagerReady = import('./js/features/naiModelManagerPanel.mjs?v=20260724-nai-models2')
  .then(({createNaiModelManagerPanel}) => {
    naiModelManagerPanel = createNaiModelManagerPanel({
      document,
      window,
      showToast,
      onStateChanged: payload => {
        const state = payload?.state || {};
        const metadata = [
          ...(Array.isArray(state.built_in) ? state.built_in : []),
          ...(Array.isArray(state.custom) ? state.custom : []),
        ];
        const selectedKey = payload?.model?.key
          || (payload?.selection_reset ? state.default_model : paramEls.model?.value)
          || state.default_model;
        updateParams({
          schema_only: true,
          api_mode: 'NAI',
          options_model: Array.isArray(state.options) ? state.options : [],
          options_model_meta: metadata,
          model: selectedKey,
        });
        if (payload?.model?.key) setParam('model', payload.model.key);
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize NAI model manager module', error);
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
    // The payload itself is committed via the editor's Apply (-> remote_params, which
    // _normalized_params merges for every path). Only the LIVE enable toggle rides the
    // generate overrides so a generate right after toggling reflects it immediately.
    const webuiCustomEnable = $('pWebuiCustomEnable');
    p.webui_custom_payload_enabled = !!(webuiCustomEnable && webuiCustomEnable.checked);
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
  applyInteractiveCharacterOverrides(overrides);
  return overrides;
}

// Interactive 모드에서는 캐릭터의 소유자가 Interactive 블록이다. 캐릭터 프롬프트를
// overrides.characters/uc 로 실어 NAI char_captions 에 반영하고, 같은 요청에서 캐릭터
// 모듈 / Character Reference 의 late-binding 을 차단한다(Vibe Transfer 는 유지 — 사용자 계약).
//
// characters 를 싣기만 해도 api_service 의 EarlyBinding 이 모듈 스냅샷보다 우선하지만,
// 활성 캐릭터가 없을 때는 fallback 이 캐릭터 모듈 프레임을 끌어오므로 skip 플래그가 필요하다.
// NAI 전용: characters/char-ref 는 다른 백엔드에서 쓰이지 않는다.
function applyInteractiveCharacterOverrides(overrides) {
  if (!interactivePanel?.isActive?.()) return;
  const mode = String(currentMode || modeSelect?.value || 'NAI').toUpperCase();
  if (mode !== 'NAI') return;
  overrides._skip_character_late_binding = true;
  overrides._skip_character_reference_late_binding = true;
  // Interactive 전용 레퍼런스를 실어 달라는 표시. 위 skip 플래그는 '붙이지 마라'는
  // 뜻이고 캐릭터 에셋 생성도 쓰므로, 그것에 의미를 얹으면 안 된다.
  overrides._interactive_reference_binding = true;
  let rows = [];
  try { rows = interactivePanel.getGenerationCharacters?.() || []; } catch (_) { rows = []; }
  if (!rows.length) return;
  // uc / character_positions 길이는 characters 와 반드시 일치해야 한다 — 어긋나면
  // NAICharacterData 가 거부하고 캐릭터가 조용히 사라진다(generation_request.py __post_init__).
  overrides.characters = rows.map(row => String(row.prompt || ''));
  overrides.uc = rows.map(row => String(row.uc || ''));
  // 패널이 center 를 안 준 경우(혼자일 때)는 **여기서 지어내지 않는다.** 예전에는
  // 0.5/0.5 로 채워서, 사용자가 정한 적 없는 좌표를 정한 것처럼 실어 보냈다.
  // 다만 이것만으로 'AI Choice' 가 되지는 않는다 — 백엔드(api_service.py `default_center`)가
  // char_captions 의 centers 를 빈 자리에서 0.5/0.5 로 다시 채운다. 그 폴백을 걷어낼지는
  // 캐릭터 모듈 등 다른 경로까지 함께 볼 문제라 여기서 건드리지 않는다.
  const positioned = rows.filter(row => row.center);
  if (positioned.length === rows.length && rows.length) {
    overrides.character_positions = rows.map(row => ({
      x: Number(row.center.x), y: Number(row.center.y),
    }));
  }
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
const naiModelMetaByKey = new Map();
let syncingParams = false;
const resultInfoContent = $('resultInfoContent');
const statsGenCount  = $('statsGenCount');
const statsSave      = $('statsSave');
const resultUnsavedActions = $('resultUnsavedActions');
const resultUnsavedSaveBtn = $('resultUnsavedSaveBtn');
const resultUnsavedDeleteBtn = $('resultUnsavedDeleteBtn');
const naiDirectorBtn = $('naiDirectorBtn');
const ollamaAssistantBtn = $('ollamaAssistantBtn');
const ollamaChatBtn = $('ollamaChatBtn');
const optBoxes = {
  prompt_fixed: $('optPromptFixed'),
  auto_generate: $('optAutoGen'),
  wildcard_standalone: $('optWcStandalone'),
  nai_streaming_preview: $('optNaiStreaming'),
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

// 🎬 NAI 스트리밍: nai_preview_meta 직후 도착하는 blob은 '중간 프리뷰'로 처리한다.
let nextBlobIsPreview = false;
let naiPreviewBlobUrl = null;

function handleNaiPreviewBlob(data) {
  // 중간 프리뷰: 메인 뷰어에 표시만 하고 완료/히스토리/통계 처리는 하지 않는다.
  try {
    const url = URL.createObjectURL(data);
    if (naiPreviewBlobUrl) URL.revokeObjectURL(naiPreviewBlobUrl);
    naiPreviewBlobUrl = url;
    preview.src = url;
    preview.dataset.source = 'preview';
    preview.classList.add('show');
    emptyMsg.style.display = 'none';
  } catch (e) {
    /* 프리뷰 표시 실패는 무시 (최종 결과에는 영향 없음) */
  }
}

function handleWsBlob(data) {
  // 🎬 NAI 스트리밍 중간 프리뷰 프레임이면 가볍게 표시만 하고 종료
  if (nextBlobIsPreview) {
    nextBlobIsPreview = false;
    handleNaiPreviewBlob(data);
    return;
  }
  // 최종 결과 도착: 남아있는 프리뷰 URL 정리
  if (naiPreviewBlobUrl) { try { URL.revokeObjectURL(naiPreviewBlobUrl); } catch {} naiPreviewBlobUrl = null; }
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
    maybeContinuePresetAutoGen();
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
  // 재시작/재연결 시 NAI 전용 도구(character/charref/vibe) 배지·Activated 요약 하이드레이션:
  // 모듈을 열지 않아도 복원된 활성 상태가 배지에 즉시 반영되도록 접속 직후 module_state 요청.
  for (const naiToolId of ['character', 'character_reference', 'vibe_transfer']) {
    if (naiToolId !== currentModuleId) requestModuleState(naiToolId);
  }
  // Frozen wildcard bar hydration — session-only freezes survive a front-end
  // reload while the backend stays up; pull them so the bar repopulates.
  if (currentModuleId !== 'wildcard') requestModuleState('wildcard');
  // Extensions 퀵 버튼(Tools/Fn)은 탭을 열지 않아도 부팅 직후 나타나야 한다.
  requestModuleState('extensions');
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

function onGenerationDispatched(m) {
  // 실제 디스패치된 시드를 Params 패널 시드 박스에 반영한다 — Seed Fix OFF면 서버가
  // 요청마다 시드를 재추첨하므로(534fa55) 박스의 직전 값과 어긋난다. 구체 시드(>=0)일
  // 때만 갱신한다(WEBUI/COMFYUI의 -1은 백엔드 랜덤 위임이라 실행 시드를 아직 모름).
  // 사용자가 시드 박스를 편집 중이거나 COMFYUI Free 잠금 표시 중에는 건드리지 않는다.
  if (!m || m.ok !== true) return;
  const seed = Number(m.params?.seed);
  if (!Number.isFinite(seed) || seed < 0) return;
  if (!paramEls?.seed || document.activeElement === paramEls.seed) return;
  if (isComfyUiFreeWorkflowActive()) return;
  const seedText = String(Math.trunc(seed));
  paramEls.seed.value = seedText;
  // remote_params에도 동기화 — 이후 Seed Fix를 켜면 메인 Generate(박스 직독)뿐
  // 아니라 시드 없는 overrides로 enqueue되는 서버 주도 경로(프리셋/Character Viewer
  // 등)도 같은 "마지막 실사용 시드"에 고정되게 한다(Codex High). Seed Fix OFF인
  // 동안의 영속은 무해 — 서버 리셋 가드(534fa55)가 매 요청 재추첨한다.
  setParam('seed', seedText);
}

const wsMessageHandlers = {
  image_meta: updateMeta,
  nai_preview_meta: () => { nextBlobIsPreview = true; },
  status: m => setGen(m.is_generating),
  prompt_generated: updatePromptOnly,
  random_failed: onRandomFailed,
  prompt_sync: syncPrompts,
  prompt_tokens: applyPromptTokenPayload,
  options: syncOptions,
  params: updateParams,
  generation_dispatched: onGenerationDispatched,
  img2img_generation_state: onImg2ImgGenerationState,
  mode: m => {
    syncMode(m.mode);
    // 글로벌 정책: 모드 전환 시 확장 퀵 팝업은 stale(모드별 선택지) — 닫고 재요청.
    if (extensionsPanel) extensionsPanel.onApiModeChanged?.();
  },
  result_enhance_state: m => { if (resultEnhance) resultEnhance.handleState(m); },
  grok_i2i_state: m => { if (grokI2iModal) grokI2iModal.onState(m); },
  nai_director_state: m => { if (naiDirectorModal) naiDirectorModal.onState(m); },
  grok_i2v_state: m => { if (grokI2vModal) grokI2vModal.onState(m); },
  grok_video_registered: m => { if (grokVideoHistory) grokVideoHistory.register(m.rel_path, m.video_id); },
  result_enhance_config: m => {
    pendingResultEnhanceConfig = m;
    if (resultEnhance) resultEnhance.setConfig(m);
  },
  queue_state: m => { if (queuePanel) queuePanel.handleState(m); },
  character_asset_generation_error: m => {
    if (characterAssetControl) characterAssetControl.handleGenerationError(m);
  },
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
  search_loading: onSearchLoading,
  bucket_dates: onBucketDates,
  depth_state: onDepthState,
  depth_sample: onDepthSample,
  tag_search_result: onTagSearchResult,
  tag_lookup_result: onTagLookupResult,
  autocomplete_result: onAutocompleteResult,
  translation_result: onTranslationResult,
  tag_filter_result: onTagFilterResult,
  tag_filter_assigned: onTagFilterAssigned,
  tag_filter_stale: onTagFilterStale,
  tag_filter_update: onTagFilterUpdate,
  tag_filter_ac_result: onTagFilterAcResult,
  event_corpus_status_result: m => eventCorpusHandlers?.onStatus(m),
  event_corpus_query_result: m => eventCorpusHandlers?.onQuery(m),
  interactive_autocomplete_result: m => interactiveAutocomplete?.onResult(m),
  interactive_related_result: m => interactiveAutocomplete?.onResult(m),
  storage_list: onStorageList,
  wildcard_manager: onWildcardManager,
  filter_reset: onFilterReset,
  toast: m => { showToast(m.message, m.level || 'success'); if (m.sound) playNotifySound(); if (m.sound === 'complete') flashTaskbarAttention(); },
  comfyui_sampling_mode_swapped: m => {
    // 백엔드 ComfyUI 자동 EPS↔ANIMA 스왑 확정 — UI sampling 플래그를 새 모드로 동기화.
    // (경고 토스트는 별도 toast 메시지로 처리됨)
    const sm = m.sampling_mode;
    if (sm === 'eps' || sm === 'v_prediction' || sm === 'anima') setSamplingMode(sm);
  },
  character_viewer_error: m => {
    if (characterViewerControl && typeof characterViewerControl.handleGenerationError === 'function') {
      characterViewerControl.handleGenerationError(m);
    } else {
      showToast(m.message || 'Character Viewer generation failed', 'error');
    }
  },
  event_preset_generation_error: onEventPresetGenerationError,
  preset_generation_error: onEventPresetGenerationError,
  sequence_preset_generation_error: m => showToast(
    `시퀀스 컷${m.frame ? ' ' + m.frame : ''} 생성 실패: ${m.message || 'failed'}`, 'error'),
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
        // 대기 중인 코퍼스 질의 정리. 안 하면 재연결 후에도 영원히 pending 인 Promise 가
        // 남아 Interactive 패널의 "불러오는 중…" 이 풀리지 않는다.
        try { resetEventCorpus('disconnected'); } catch (error) { /* non-fatal */ }
        // 재연결 사이클을 위해 boot finalize 상태 리셋 (다음 init_complete 가 다시 시퀀스 시작)
        resetBootIndicatorState();
        setBootIndicator('Reconnecting…', 20, false);
        setLauncherConn(false);
        modeSwitching = false;
        if (modeSelect) modeSelect.disabled = true;
        // 끊김 중이던 수동 Random 의 pending 상태 정리(FIX-C/RC-2): 안 비우면 재연결 후 좌측 패널
        // 재동기(scheduleInitialStateRefresh)가 awaitingMyRandom/pendingRandomRequestId 가드에 막혀
        // 영원히 deferral 되고, 늦게 도착한 random 브로드캐스트도 stale id 로 거부된다. 버튼도 재활성화.
        awaitingMyRandom = false;
        pendingRandomRequestId = '';
        if (window._randomTimeout) { clearTimeout(window._randomTimeout); window._randomTimeout = null; }
        if (typeof btnRnd !== 'undefined' && btnRnd) btnRnd.disabled = false;
        if (typeof stopRndTimer === 'function') stopRndTimer();  // Ollama boost 경과시간 라벨 복원(Codex INFO)
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
  if (characterAssetControl && typeof characterAssetControl.handleResultMeta === 'function') {
    characterAssetControl.handleResultMeta(m);
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
  // current 프리뷰에 안정적 history 식별자(rel_path)를 각인 → 삭제 시 "표시 중 이미지" 여부를
  // source가 아닌 동일성으로 정확히 판정 (오클리어 방지). source는 'current' 그대로 유지하므로
  // activeResultAssetUrl / buildImagePlaneContext 등 기존 흐름은 영향받지 않는다.
  const assetPath = String(asset?.path || '');
  if (preview && preview.dataset.source === 'current' && assetPath.startsWith('__history_item__/')) {
    preview.dataset.path = assetPath;
  }
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
    // 응답 후 "지금" 프리뷰 상태로 판정 (await 사이 새 결과 도착 시 최신 프리뷰/버퍼 보존).
    const stillDisplayed = Boolean(deletedPath) && preview?.dataset?.path === deletedPath;
    const stillCurrentResult = stillDisplayed && preview?.dataset?.source === 'current';
    if (stillDisplayed) {
      preview.removeAttribute('src');
      preview.classList.remove('show');
      preview.dataset.path = '';
      emptyMsg.style.display = '';
      if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
      if (resultEnhance) resultEnhance.clearCurrentMeta();
      if (stillCurrentResult) releaseLatestResultBuffers();
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

// 표시 중이던 "현재 결과"를 삭제할 때, 풀사이즈 blob·objectURL·메타 참조까지 즉시 해제한다.
// (이 버퍼들은 평소 handleWsBlob에서 다음 생성 때 교체되지만, 삭제 후엔 잔여 데이터가 남지 않아야 한다.)
function releaseLatestResultBuffers() {
  if (blobUrl) {
    try { URL.revokeObjectURL(blobUrl); } catch (error) { /* noop */ }
    blobUrl = null;
  }
  latestResultBlob = null;
  latestImageMeta = null;
}

// 결과/히스토리 컨텍스트 메뉴 "이미지 삭제" 핸들러.
// mode: 'history'(기본) = 히스토리에서만 제거 / 'disk' = 디스크 파일까지 삭제.
// 안전장치: 반드시 __history_item__/<id> rel_path로만 삭제 (오삭제·레이스 방지, 확인 다이얼로그 없음).
async function deleteResultFromContext(context, mode) {
  const deletedPath = String(context?.path || '');
  if (!deletedPath.startsWith('__history_item__/')) {
    showToast('삭제할 수 있는 히스토리 항목이 아닙니다', 'error');
    return;
  }
  const keepFile = mode !== 'disk';
  try {
    const response = await fetch('/api/result/action/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: deletedPath, keep_file: keepFile}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    renderResultUnsavedActions(null);
    if (resultHistory && data.rel_path) resultHistory.onRemoved(data);
    // 표시/버퍼 정리는 응답을 받은 "지금" 시점의 프리뷰 상태로 판정한다.
    // (await 사이 새 결과가 도착해 프리뷰가 교체됐다면 그 최신 프리뷰/버퍼는 건드리지 않는다 —
    //  오직 rel_path 동일성으로만 확인. current 프리뷰엔 renderResultUnsavedActions가 rel_path를 각인한다.)
    const stillDisplayed = Boolean(deletedPath) && preview?.dataset?.path === deletedPath;
    const stillCurrentResult = stillDisplayed && preview?.dataset?.source === 'current';
    if (stillDisplayed) {
      preview.removeAttribute('src');
      preview.classList.remove('show');
      preview.dataset.path = '';
      emptyMsg.style.display = '';
      if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
      if (resultEnhance) resultEnhance.clearCurrentMeta();
      if (stillCurrentResult) releaseLatestResultBuffers();
    }
    showToast(data.deleted_file ? '이미지 삭제됨 (디스크 파일 → 휴지통)' : '이미지 삭제됨 (히스토리)', 'success');
  } catch (error) {
    console.error('Result context delete failed', error);
    showToast(error.message || '이미지 삭제 실패', 'error');
  } finally {
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
  stopRndTimer();  // boost 경과 타이머 정지 + 'Random' 라벨 복원
  // Interactive 는 블록이 프롬프트를 조립한다 — Random 이 넣을 자리가 없다.
  // Prompt Fixed 와 같은 취급으로 잠근다(사용자 지시).
  const locked = getOptionChecked('prompt_fixed') || !!interactivePanel?.isActive?.();
  btnRnd.disabled = locked;
  btnRnd.style.opacity = locked ? '0.4' : '';
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
  // 패널 갱신은 'random' 프롬프트를 무조건 수용한다(single-user). 예전엔 request-id 일치
  // (isExpectedRandomPrompt)가 게이트라, 브로드캐스트/재연결로 도착한 '적용된' random 프롬프트가
  // 좌측 패널에 안 떴다(RC-1). 버튼 unlock 만 아래에서 request-id 로 게이트한다(isMyRandom).
  const isMyRandom = source === 'random' && isExpectedRandomPrompt(message);
  // 빈 프롬프트로는 패널을 비우지 않는다(Codex LOW): 내 random 응답(isMyRandom)이 아닌 한 prompt 가
  // 있을 때만 수용 — 남/stale random 의 빈 prompt 가 좌측 패널을 지우는 일 방지. (성공 random 은 항상
  // prompt 보유, 실패는 random_failed 로 분기되므로 실질 빈-수용은 발생하지 않음.)
  const acceptsRandomPrompt = source === 'random' && (!!prompt || isMyRandom);
  const acceptsGeneratedPrompt = (
    acceptsBootstrapPrompt ||
    acceptsRandomPrompt
    || isPresetSource
    || source === 'auto_generate'
    || source === 'result_reroll'
    || source === 'storyteller'   // RC-3: 스토리텔러 자동생성 프롬프트도 좌측 패널에 반영
    || source === 'automation'    // RC-3: 자동화 프롬프트도 좌측 패널에 반영
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
    if (isMyRandom) unlockRandomButton();   // 내가 요청한 random 응답일 때만 버튼 unlock(브로드캐스트로 온 남/재연결분은 패널만 갱신)
    if (promptSendTimer) {
      clearTimeout(promptSendTimer);
      promptSendTimer = null;
    }
    _localPromptDirty = false;
    deferredPromptSync = null;
    syncingPrompt = true;
    // Interactive 가 켜져 있으면 입력창의 주인은 블록이다. 서버 에코를 그대로 쓰면
    // 우리가 저장용으로 보낸 **원본**이 표시값을 덮어써 조립 결과가 사라진다.
    // 저장은 원본으로, 표시는 블록 조립값으로 — 둘을 갈라 둔다.
    if (!(interactivePanel?.isActive?.() && promptBeforeInteractive !== null)) {
      promptEdit.value = prompt;
    }
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

function populateSelect(el, options, current, labels = null) {
  if (!el) return;
  const previous = el.value;
  if (options && options.length) {
    const normalized = options.map(value => String(value));
    const labelFor = value => {
      if (labels instanceof Map && labels.has(value)) return String(labels.get(value));
      if (labels && typeof labels === 'object' && value in labels) return String(labels[value]);
      return value;
    };
    const existing = Array.from(el.options);
    const changed = (
      existing.length !== normalized.length
      || existing.some((option, index) => (
        option.value !== normalized[index]
        || option.textContent !== labelFor(normalized[index])
      ))
    );
    if (changed) {
      el.textContent = '';
      normalized.forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = labelFor(value);
        el.append(option);
      });
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
  const mode = m.api_mode || currentMode || modeSelect?.value || '';
  syncingParams = true;
  ensureResolutionPresetOptions();
  if (Array.isArray(m.options_model_meta)) {
    naiModelMetaByKey.clear();
    m.options_model_meta.forEach(item => {
      const key = String(item?.key || '').trim().toUpperCase();
      if (key) naiModelMetaByKey.set(key, item);
    });
  }
  const modelLabels = mode === 'NAI'
    ? new Map(
      Array.from(naiModelMetaByKey.entries())
        .filter(([, item]) => item?.source === 'user')
        .map(([key, item]) => [key, String(item?.label || key)])
    )
    : null;
  populateSelect(paramEls.model, m.options_model, m.model, modelLabels);
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
  document.querySelectorAll('.mode-nai').forEach(el => el.style.display = mode === 'NAI' ? '' : 'none');
  if (mode && mode !== 'NAI' && naiModelManagerPanel?.isOpen()) {
    naiModelManagerPanel.close();
  }
  // Assets 탭은 NAI 전용(사용자 지시 2026-07-18): 다른 모드로 바뀌면 숨기고,
  // 사용자가 그 탭을 펼치고 있었다면 setAvailability가 Result로 복귀시킨다.
  if (mode) applyRightTabAvailability({charAssets: mode === 'NAI'});
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
    // WEBUI Custom Payload — restore the APPLIED value from backend remote_params (per-mode
    // plane). Keep an applied cache; do NOT overwrite the editor textarea while the popup is
    // open (it would clobber an in-progress draft before the user hits Apply).
    if ('webui_custom_payload' in m) {
      _webuiCustomPayloadApplied = m.webui_custom_payload || '';
      const customPayloadEl = $('pWebuiCustomPayload');
      const cpPopup = $('webuiCustomPayloadPopup');
      const cpOpen = cpPopup && cpPopup.classList.contains('open');
      if (customPayloadEl && !cpOpen) customPayloadEl.value = _webuiCustomPayloadApplied;
    }
    const customPayloadCb = $('pWebuiCustomEnable');
    if (customPayloadCb && 'webui_custom_payload_enabled' in m) {
      customPayloadCb.checked = (m.webui_custom_payload_enabled === true || String(m.webui_custom_payload_enabled).toLowerCase() === 'true');
    }
    updateWebuiCustomPayloadIndicator();
    validateWebuiCustomPayload();
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
  // NAID3 로 바꾸면 NAI 전용 캐릭터 계열(Character/CR/VT)을 즉시 차단(런처 비활성 재계산 +
  // 열려 있으면 닫기)하고, 인페인트 강도 슬라이더 표시 여부도 갱신한다(V3=디노이징 미지원).
  if (key === 'model') {
    if (moduleLauncherControl) moduleLauncherControl.updateState();
    if (['character', 'character_reference', 'vibe_transfer'].includes(currentModuleId)
        && naiModelBlocksReference()
        && modulePopup.classList.contains('open')) {
      closeModule();
      showToast('NAID3에서는 Character / Character Reference / Vibe Transfer를 지원하지 않습니다 (다른 사양)', 'info');
    }
    if (img2imgPanel) img2imgPanel.refresh();
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

// --- WEBUI Custom Payload (alwayson_scripts) -------------------------------
// Paste a WEBUI generation's payload (or just its alwayson_scripts block) to inject user
// extensions (ControlNet/ADetailer/...) into every generation. The captured payload comes
// from the user's WEBUI side (the api-payload extension / a fork); NAIA only accepts it
// here and merges it into alwayson_scripts.
//
// Stored in backend remote_params under WEBUI-SPECIFIC keys (webui_custom_payload /
// webui_custom_payload_enabled) so EVERY generation path injects it — manual, random,
// auto-gen continuation, Event Preset, Studio, Result Enhance all merge remote_params via
// _normalized_params — while the NAI path (which reads the separate use_custom_api_params)
// can never receive it. The editor is restored from the schema broadcast (per-mode plane),
// like the WEBUI hires params; no localStorage (which previously caused a clobber).
// The payload lives in remote_params and is committed ONLY via the editor's Apply button.
// _webuiCustomPayloadApplied mirrors the last applied/known value (from the schema) so the
// editor can load it on open and the Edit button can show an applied indicator.
let _webuiCustomPayloadApplied = '';

function setWebuiCustomPayloadEnabled(on) {
  setParam('webui_custom_payload_enabled', String(!!on));
  updateWebuiCustomPayloadIndicator();
}

function openWebuiCustomPayloadEditor() {
  const popup = $('webuiCustomPayloadPopup');
  const el = $('pWebuiCustomPayload');
  if (!popup || !el) return;
  el.value = _webuiCustomPayloadApplied;   // load the applied value; discard any stale draft
  popup.classList.add('open');
  validateWebuiCustomPayload();
  try { el.focus(); } catch (e) {}
}

function closeWebuiCustomPayloadEditor() {
  const popup = $('webuiCustomPayloadPopup');
  if (popup) popup.classList.remove('open');
  const btn = $('pWebuiCustomEditBtn');
  if (btn) { try { btn.focus(); } catch (e) {} }
}

// If the user pasted a FULL WEBUI generation payload (top-level "alwayson_scripts"), return just
// the alwayson_scripts object pretty-printed; otherwise null (already a fragment, or unparseable).
// Mirrors Dev0714's converter — keep only the extension block, drop prompt/seed/width/etc.
function reduceToAlwaysonScripts(text) {
  const txt = (text || '').trim();
  if (!txt) return null;
  try {
    const obj = JSON.parse(txt);
    if (obj && typeof obj === 'object' && !Array.isArray(obj)
        && obj.alwayson_scripts && typeof obj.alwayson_scripts === 'object'
        && !Array.isArray(obj.alwayson_scripts)) {
      return JSON.stringify(obj.alwayson_scripts, null, 2);
    }
  } catch (e) {}
  return null;
}

function applyWebuiCustomPayload() {
  const el = $('pWebuiCustomPayload');
  if (!el) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('WS 연결이 끊겨 적용할 수 없습니다.', 'error');
    return;
  }
  // Paste-a-full-payload convenience: reduce the editor to just its alwayson_scripts block so the
  // stored remote_param (and the next view) is the clean fragment, not the whole payload.
  const original = el.value.trim();
  const reduced = reduceToAlwaysonScripts(el.value);
  const wasReduced = reduced !== null && reduced !== original;
  if (reduced !== null) el.value = reduced;
  const info = validateWebuiCustomPayload();
  setParam('webui_custom_payload', el.value);
  _webuiCustomPayloadApplied = el.value;
  updateWebuiCustomPayloadIndicator();
  const txt = (el.value || '').trim();
  if (!txt) {
    showToast('Custom Payload를 비웠습니다.', 'success');
  } else if (info.valid) {
    showToast(wasReduced
      ? `전체 payload에서 alwayson_scripts ${info.count}개 추출·적용됨`
      : `Custom Payload 적용됨 · alwayson 스크립트 ${info.count}개`, 'success');
  } else {
    // Backend _apply_custom_api_params runs _intelligent_json_corrector at generation time, so
    // an imperfect paste is still usable — commit it, but don't call it valid.
    showToast('적용됨 — JSON 형식 오류라 생성 시 자동 교정을 시도합니다.', 'warning');
  }
}

function onWebuiCustomPayloadInput() {
  validateWebuiCustomPayload();
}

function validateWebuiCustomPayload() {
  const hint = $('webuiCustomPayloadHint');
  const el = $('pWebuiCustomPayload');
  if (!el) return { valid: true, count: 0 };
  const txt = (el.value || '').trim();
  if (!txt) {
    if (hint) { hint.textContent = ''; hint.className = 'webui-custom-payload-hint'; }
    return { valid: true, count: 0 };
  }
  try {
    const obj = JSON.parse(txt);
    const block = (obj && typeof obj === 'object' && obj.alwayson_scripts && typeof obj.alwayson_scripts === 'object')
      ? obj.alwayson_scripts : obj;
    const n = (block && typeof block === 'object' && !Array.isArray(block)) ? Object.keys(block).length : 0;
    if (hint) { hint.textContent = `유효한 JSON · alwayson 스크립트 ${n}개`; hint.className = 'webui-custom-payload-hint ok'; }
    return { valid: true, count: n };
  } catch (e) {
    if (hint) { hint.textContent = 'JSON 형식 오류 — 생성 시 자동 교정을 시도합니다'; hint.className = 'webui-custom-payload-hint warn'; }
    return { valid: false, count: 0 };
  }
}

function updateWebuiCustomPayloadIndicator() {
  const btn = $('pWebuiCustomEditBtn');
  if (!btn) return;
  const txt = (_webuiCustomPayloadApplied || '').trim();
  if (!txt) {
    btn.textContent = 'Edit';
    btn.classList.remove('has-payload');
    btn.removeAttribute('title');
    return;
  }
  try {
    const obj = JSON.parse(txt);
    const block = (obj && typeof obj === 'object' && obj.alwayson_scripts && typeof obj.alwayson_scripts === 'object')
      ? obj.alwayson_scripts : obj;
    const n = (block && typeof block === 'object' && !Array.isArray(block)) ? Object.keys(block).length : 0;
    btn.textContent = `Edit · ${n}`;
    btn.title = `적용된 alwayson 스크립트 ${n}개`;
  } catch (e) {
    btn.textContent = 'Edit · !';
    btn.title = '적용된 payload가 JSON 형식 오류 — 생성 시 자동 교정을 시도합니다';
  }
  btn.classList.add('has-payload');
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
  // Interactive 가 켜져 있으면 입력창의 주인은 블록이다. 우리가 저장용으로 보낸
  // **원본**이 이 경로로 돌아와 조립값을 덮어쓰던 것을 막는다(실측: 조립값이 쓰인
  // 직후 원본이 다시 쓰였다). 네거티브는 Interactive 소관이 아니라 그대로 둔다.
  const interactiveOwnsPrompt = interactivePanel?.isActive?.() && promptBeforeInteractive !== null;
  if (!interactiveOwnsPrompt && 'prompt' in m && m.prompt !== promptEdit.value) {
    promptEdit.value = m.prompt;
  }
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
        // Interactive 가 켜져 있으면 입력창은 **블록이 조립한 표시값**이다. 그것을
        // 저장하면 켠 채로 종료했을 때 다음 실행에 그 값이 메인 프롬프트로 굳고
        // 사용자 원본이 사라진다(실측). 저장은 항상 원본으로 한다 — 생성은
        // 요청에 프롬프트를 직접 실어 보내므로 이 값에 의존하지 않는다.
        prompt: (interactivePanel?.isActive?.() && promptBeforeInteractive !== null)
          ? promptBeforeInteractive : promptEdit.value,
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
  // 모바일(<768px): 우측 탭 스트립을 숨기고 항상 Result 고정 — 다른 탭으로
  // 전환되면 되돌아올 UI가 없다. (탭 기능은 리모트 패널로 대체 예정)
  // 분리 창(detached metadata/module)은 pngInfo 전환에 의존하므로 예외.
  if (!isDetachedShell && typeof isPC !== 'undefined' && !isPC.matches && tabName !== 'result') {
    tabName = 'result';
  }
  const activeTab = rightTabs ? rightTabs.switchTo(tabName) : tabName;
  if (activeTab === 'settings') requestModuleState('extensions'); // 진입 시 재발견(새 설치 즉시 반영)
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
  if (characterAssetControl && typeof characterAssetControl.setActive === 'function') {
    characterAssetControl.setActive(activeTab === 'charAssets');
  }
  if (activeTab === 'charAssets' && characterAssetControl) characterAssetControl.load();
  if (danbooruTabControl && typeof danbooruTabControl.setActive === 'function') {
    danbooruTabControl.setActive(activeTab === 'danbooru');
  }
  return activeTab;
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
  // 분리된 메타데이터 창의 'Vibe Transfer 복원' 위임 → 메인 창에서 실제 복원 수행(메인 VT 갱신).
  // 메인 창은 isDetachedShell=false 라 applyMetadataVibeTransfer 가 로컬 경로(forceOpen+복원)로 동작.
  if (data.type === 'naia_restore_vibe' && data.vibeTransfer) {
    applyMetadataVibeTransfer({ vibeTransfer: data.vibeTransfer });
    window.focus?.();
    return;
  }
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
  // 방금 생성한 조합에 썸네일이 붙었을 수 있다 — 목록이 열려 있을 때만 다시 읽는다.
  if (interactiveAssetsPanel) interactiveAssetsPanel.refresh();
  scheduleResultUnsavedActionRefresh(180);
}
function onViewerHistoryRemoved(message) {
  // current 프리뷰로 표시 중이던 항목이 제거되면(다른 클라이언트 삭제/오버플로우 퇴출 포함)
  // 프리뷰·풀사이즈 버퍼까지 정리한다. (resultHistory.onRemoved는 source==='saved'만 정리)
  const removedPath = String(message?.rel_path || '');
  if (removedPath && preview?.dataset?.source === 'current' && preview?.dataset?.path === removedPath) {
    preview.removeAttribute('src');
    preview.classList.remove('show');
    preview.dataset.path = '';
    emptyMsg.style.display = '';
    if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
    if (resultEnhance) resultEnhance.clearCurrentMeta();
    releaseLatestResultBuffers();
  }
  if (resultHistory) resultHistory.onRemoved(message);
  // 캐릭터 에셋 벤치 후보는 history_id로 저장한다 - 퇴출되면 만료 표시.
  if (characterAssetControl && typeof characterAssetControl.handleHistoryRemoved === 'function') {
    characterAssetControl.handleHistoryRemoved(message);
  }
  scheduleResultUnsavedActionRefresh(80);
}
function onViewerHistoryCleared(message) {
  // 낡은 세대의 알림이면 컨트롤러가 false 를 준다 — 그때는 현재 결과를 건드리면 안 된다
  // (이미 그 뒤에 도착한 정상 이미지의 blob/메타를 날려 버린다).
  if (!resultHistory || !resultHistory.onCleared(message)) return;
  // 서버의 current asset 이 사라졌으므로 object URL/blob/meta 도 함께 놓는다
  // (삭제 경로와 같은 정리 — 안 하면 지운 결과가 메모리에 남는다).
  releaseLatestResultBuffers();
  // Enhance 는 자기 currentMeta 를 따로 들고 있다. 안 지우면 빈 화면에서 버튼이
  // 살아 있고, 누르면 이미 사라진 결과를 조회해 실패한다(단일 삭제 경로와 동일 처리).
  if (resultEnhance) resultEnhance.clearCurrentMeta();
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

// NAI Director Tools (제거 가능) — NAI 계정이 등록돼 있으면(api_status.nai_configured) 모드 무관 활성.
function updateNaiDirectorButton() {
  if (naiDirectorBtn) naiDirectorBtn.disabled = !naiConfigured;
}
async function openNaiDirector(presetContext = null) {
  if (!naiConfigured) { showToast('NAI 계정이 등록되어 있지 않습니다 (API 설정 → NAI).', 'error'); return; }
  await naiDirectorModalReady;
  if (!naiDirectorModal) { showToast('Director 모듈을 불러오지 못했습니다.', 'error'); return; }
  // Context-menu invocation passes the clicked image's context (already the director
  // shape via mergeAssetContext) — augment exactly that image.
  if (presetContext && presetContext.hasImage) {
    naiDirectorModal.open(presetContext);
    return;
  }
  // The [Director] button augments the CURRENTLY VIEWED image: a saved history item
  // when one is shown on the viewer, otherwise the latest result. Previously it always
  // fetched /api/result/asset/current (the latest), ignoring the viewed history item.
  const preview = document.getElementById('preview');
  const savedPath = preview && preview.dataset && preview.dataset.source === 'saved'
    ? String(preview.dataset.path || '') : '';
  let asset = null;
  try {
    const url = savedPath
      ? '/api/result/asset/saved?path=' + encodeURIComponent(savedPath)
      : '/api/result/asset/current';
    const resp = await fetch(url, {cache: 'no-store'});
    if (resp.ok) asset = await resp.json();
  } catch (error) { /* noop */ }
  if (!asset || !(asset.has_image ?? asset.hasImage)) {
    showToast('변형할 결과 이미지가 없습니다.', 'error');
    return;
  }
  naiDirectorModal.open({
    source: String(asset.source || (savedPath ? 'saved' : 'current')),
    path: String(asset.path || savedPath || ''),
    filePath: String(asset.file_path || asset.filePath || ''),
    label: String(asset.label || 'Result Image'),
    imageSrc: String(asset.image_url || asset.imageUrl || (savedPath ? '/api/viewer/image/' + encodeURI(savedPath) : '/api/latest-image')),
    hasImage: true,
  });
}

async function openOllamaAssistant() {
  await ollamaAssistantPopupReady;
  if (!ollamaAssistantPopup) {
    showToast('Ollama 모듈을 불러오지 못했습니다.', 'error');
    return;
  }
  ollamaAssistantPopup.open();
}
async function openOllamaChat() {
  await ollamaChatPopupReady;
  if (!ollamaChatPopup) {
    showToast('Ollama Chat 모듈을 불러오지 못했습니다.', 'error');
    return;
  }
  ollamaChatPopup.open();
}
if (ollamaAssistantBtn) {
  ollamaAssistantBtn.addEventListener('click', async () => {
    // [Ollama Assist] 버튼 재클릭 = 토글: 열려 있으면 닫고, 아니면 연다.
    await ollamaAssistantPopupReady;
    if (ollamaAssistantPopup && ollamaAssistantPopup.isOpen && ollamaAssistantPopup.isOpen()) {
      ollamaAssistantPopup.close();
    } else {
      openOllamaAssistant();
    }
  });
}
if (ollamaChatBtn) {
  ollamaChatBtn.addEventListener('click', async () => {
    await ollamaChatPopupReady;
    if (ollamaChatPopup && ollamaChatPopup.isOpen && ollamaChatPopup.isOpen()) {
      ollamaChatPopup.close();
    } else {
      openOllamaChat();
    }
  });
}

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
  const vibeTransfer = payload?.vibeTransfer;
  if (!vibeTransfer || !Array.isArray(vibeTransfer.reference_image_multiple) || !vibeTransfer.reference_image_multiple.length) {
    showToast('No Vibe Transfer data in metadata', 'error');
    return;
  }
  // 분리/팝업 메타데이터 창에서 호출되면(=opener 존재) 메인 창으로 복원을 위임한다. 분리창에서 직접
  // openModule('vibe_transfer') 하면 분리창 안에 VT 팝업이 뜨고, 복원이 분리창 ws 로만 가서 메인 VT는
  // 안 바뀐다(사용자 리포트: 메타데이터 팝업에서 복원 시 VT 창이 닫힌/안 뜬 것처럼 보임). 메인이
  // forceOpen 으로 VT를 열고 자기 ws 로 복원하면 메인 VT가 정상 갱신된다. 모드/연결 검증은 메인이 수행.
  if (isDetachedShell && window.opener && !window.opener.closed) {
    try {
      window.opener.postMessage({ type: 'naia_restore_vibe', vibeTransfer }, window.location.origin);
      showToast('메인 창의 Vibe Transfer로 복원 요청을 보냈습니다', 'success');
      return;
    } catch (error) {
      // 위임 실패 시 아래 로컬 경로로 폴백.
    }
  }
  if ((currentMode || modeSelect.value) !== 'NAI') {
    showToast('Vibe Transfer is only available in NAI mode', 'error');
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('Remote connection is not open', 'error');
    return;
  }
  // forceOpen: VT가 이미 열려 있으면 토글로 닫지 않고 제자리 갱신, 닫혀 있으면 연다(복원 시 닫힘 차단).
  openModule('vibe_transfer', { forceOpen: true });
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

// Danbooru 임베드의 "이미지 생성" 버튼 — 데스크톱 on_generate_with_image_requested 포팅.
// 추출 프롬프트를 메인 프롬프트 박스에 반영한 뒤 곧바로 생성 파이프라인으로 보낸다.
function onGenerateFromPrompt(prompt) {
  if (!prompt) return false;
  // requestGenerate의 가드(생성 중 / WS 닫힘)를 프롬프트 박스 수정 전에 먼저 적용한다.
  // 그래야 막힌 시도가 사용자의 현재 프롬프트를 덮어쓰지 않는다. (false 반환 → 호출자가 토스트 처리)
  if (generating) return false;
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  promptEdit.value = prompt;
  onPromptEdit();
  const negative = negEdit ? negEdit.value : '';
  // 이 경로도 buildWebGenerationOverrides 로 Interactive 캐릭터를 싣는다 — 조합을
  // 남기지 않으면 같은 캐릭터로 만든 그림이 Assets 에서 빠진다.
  // 위에서 이미 generating/ws 가드를 통과했으므로 true 로 답한다(호출자는 boolean 계약).
  void generateWithInteractiveSnapshot({
    prompt,
    negative_prompt: negative,
    overrides: buildWebGenerationOverrides(prompt, negative),
  });
  return true;
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
// 모바일 진입/전환 시 우측 탭을 Result로 강제 (모바일은 탭 스트립 자체가 숨김).
// 분리 창은 좁아도 자체 탭(pngInfo 등)에 의존하므로 제외.
if (!isDetachedShell) {
  isPC.addEventListener?.('change', () => {
    if (!isPC.matches) switchRightTab('result');
  });
  rightTabsReady.then(() => {
    if (!isPC.matches) switchRightTab('result');
  });
}
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
  if (activePromptTab !== 'preset') clearPresetAutoGenTimer();
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

function openFnSequence() {
  closeFnMenu();
  switchTab('sequence');
  sequencePresetReady.then(() => sequencePresetControl?.onOpen());
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
  if (activePromptTab !== 'preset') clearPresetAutoGenTimer();
  if (eventPresetPanel) eventPresetPanel.setActiveTab(activePromptTab === 'preset');
  updateGenerateButtonMode();
}

// ---- Controls ----
// Interactive 조합을 남기고 생성한다. 스냅샷 id 를 요청에 실으면 백엔드가 결과
// 이미지로 384px 썸네일을 붙인다(core/headless_result_service.py).
//
// 기록은 **생성할 때만** 한다(사용자 결정) — 만들다 만 조합으로 목록이 더러워지지
// 않게. 기록이 실패해도 생성은 그대로 진행한다.
async function generateWithInteractiveSnapshot(payload) {
  // 생성 중이거나 연결이 끊겼으면 기록도 하지 않는다. requestGenerate 가 어차피
  // 거부하는데 먼저 기록하면, 생성되지 않은 조합이 Assets 에 남는다
  // ("생성할 때만 기록" 계약 위반). 단축키는 버튼 비활성화를 우회하므로 실제로 닿는다.
  if (generating) return false;
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  const overrides = payload && payload.overrides;
  if (overrides && interactiveAssetsPanel && interactivePanel?.isActive?.()) {
    let chars = [];
    try { chars = interactivePanel.getSnapshotChars?.() || []; } catch (_) { chars = []; }
    // 씬 슬롯·구도도 함께 남긴다 — Assets 미리보기가 '이 그림이 어떤 설정에서
    // 나왔는가' 를 보여 주려면 캐릭터만으로는 모자란다.
    let globals = {};
    try { globals = interactivePanel.getSnapshotGlobals?.() || {}; } catch (_) { globals = {}; }
    if (chars.length) {
      const id = await interactiveAssetsPanel.record(chars, globals);
      if (id) overrides.interactive_snapshot_id = id;
    }
  }
  // 가드(생성 중 / WS 닫힘)는 requestGenerate 가 다시 본다 — await 사이에 상태가
  // 바뀌었어도 여기서 통과시키지 않는다.
  return requestGenerate(payload);
}

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

function updateRandomStreamBadge(state) {
  // 스트림(스토리/수동 진행) 활성 시 Random 버튼에 현재 시퀀스 위치 (n/m)를 표시한다.
  // 1.5 모델: 수동 Random도 스텝을 전진시키므로 버튼은 절대 잠그지 않는다.
  const btn = document.getElementById('btnRnd');
  if (!btn) return;
  let textNode = null;
  btn.childNodes.forEach(node => {
    if (node.nodeType === 3 && node.textContent.trim()) textNode = node;
  });
  if (!textNode) {
    textNode = document.createTextNode('Random');
    btn.appendChild(textNode);
  }
  const active = state?.active === true || String(state?.active).toLowerCase() === 'true';
  const total = Number(state?.node_count) || 0;
  if (active && total > 0) {
    const position = ((Number(state?.current_index) || 0) % total) + 1;
    textNode.textContent = `Random (${position}/${total})`;
  } else {
    textNode.textContent = 'Random';
  }
}

function runStorytellerCycle(request) {
  // One atomic command: the backend arms the cycle AND generates page 1 with these live
  // params server-side, so there is no separate "random" kick that could be skipped on the
  // preset tab or leave the cycle armed-but-idle on failure. `request` may be a bare count
  // or {count, steps} where steps is the authored 1.5-style step sequence.
  const req = (request && typeof request === 'object') ? request : {count: request};
  const pages = Math.max(1, parseInt(req.count, 10) || 1);
  const payload = {
    count: pages,
    overrides: _collectCurrentParams(),
    ratings: getActiveRatings(),
  };
  if (Array.isArray(req.steps) && req.steps.length) payload.steps = req.steps;
  setModuleParam('storyteller', 'run_cycle', JSON.stringify(payload));
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
  // Interactive 는 블록이 프롬프트를 조립한다 — Random 이 넣을 자리가 없다.
  // 버튼 비활성화만으로는 Alt+Enter 단축키가 이 함수를 직접 불러 새어 나간다
  // (2026-08-05 Codex 지적). **여기가 진짜 길목이다.** `force` 도 통과시키지 않는다.
  if (interactivePanel?.isActive?.()) {
    showToast('Interactive 모드에서는 Random 을 쓰지 않습니다', 'info');
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
  // When Ollama Auto Boost is armed the backend spends ~1-3s rewriting the prompt
  // before broadcasting prompt_generated, so the normal 2s safety re-enable would
  // free the button mid-boost and let the user spam it. Extend the safety timeout
  // to 15s only while the boost is on; normal random keeps the existing 2s behavior.
  const boostArmed = !!(lastPromptEngineeringState && lastPromptEngineeringState.ollama_auto_boost);
  const randomSafetyTimeoutMs = boostArmed ? 15000 : 2000;
  // Ollama 모드: Random 버튼에 boost 재작성 경과시간을 실시간 표시(Generate 버튼처럼).
  if (boostArmed) startRndTimer();
  window._randomTimeout = setTimeout(() => {
    if (awaitingMyRandom) {
      unlockRandomButton({clearRequest: false});
    }
  }, randomSafetyTimeoutMs);
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
    // Sequence 탭에서 그룹 팝업을 보고 있으면 메인 Generate = 그 그룹의 '연속 생성'(req1).
    // 이벤트 미선택 상태로 Generate 를 누르면 일반 프롬프트가 생성돼 혼동을 주므로, 적색
    // 토스트로 안내하고 요청을 스킵한다(일반 생성 폴백 차단). Auto Gen(백엔드 연속 루프)은
    // 이 수동 Generate 분기를 타지 않으므로 영향 없음.
    if (activePromptTab === 'sequence') {
      if (sequencePresetControl?.hasOpenGroup?.()) {
        sequencePresetControl.generateOpenGroup();
      } else {
        showToast('시퀀스 프리셋에서는 Generate 대신 Random 버튼을 누르거나, 생성할 이벤트를 선택한 뒤 Generate를 눌러주세요.', 'error');
      }
      return;
    }
    if (activePromptTab === 'preset') {
      void generateFromPresetTab();
      return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const prompt = promptEdit.value;
    const negative = negEdit.value;
    void generateWithInteractiveSnapshot({
      prompt,
      negative_prompt: negative,
      overrides: buildWebGenerationOverrides(prompt, negative),
    });
    return;
  }
  if (cmd === 'random') {
    // Pool still loading (chunk load / parquet load-merge-upload) → block Random
    // (covers the ALT+ENTER shortcut, which bypasses the button's pointer-events).
    if (poolLoad.isActive()) {
      showToast('검색 풀을 불러오는 중입니다. 완료 후 다시 시도해주세요.', 'error');
      return;
    }
    // Sequence 탭에서 메인 Random = 현재 매칭 전체에서 랜덤 그룹 연속 생성(req2/3).
    if (activePromptTab === 'sequence' && sequencePresetControl?.randomGenerate) {
      sequencePresetControl.randomGenerate();
      return;
    }
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
  const wasGenerating = generating;
  generating = next;
  // 반응형 생성: 생성 중에 쌓인 변화를 **여기서 한 번만** 낸다(큐잉 아님).
  if (wasGenerating && !next && interactivePanel?.notifyGenerationDone) {
    setTimeout(() => interactivePanel.notifyGenerationDone(), 0);
  }
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

function clearPresetAutoGenTimer() {
  presetAutoGenToken += 1;
  if (presetAutoGenTimer) {
    window.clearTimeout(presetAutoGenTimer);
    presetAutoGenTimer = null;
  }
}

function presetAutoGenConditionsHold(token = null, {requireIdle = false} = {}) {
  if (token !== null && token !== presetAutoGenToken) return false;
  if (activePromptTab !== 'preset') return false;
  if (!getOptionChecked('auto_generate')) return false;
  if (getOptionChecked('prompt_fixed')) return false;
  if (!eventPresetPanel?.canRandomize?.()) return false;
  if (requireIdle && (!!presetGenerationPending || generating)) return false;
  return true;
}

function maybeContinuePresetAutoGen() {
  clearPresetAutoGenTimer();
  if (!presetAutoGenConditionsHold()) return;
  const token = ++presetAutoGenToken;
  presetAutoGenTimer = window.setTimeout(() => {
    presetAutoGenTimer = null;
    if (!presetAutoGenConditionsHold(token, {requireIdle: true})) return;
    void randomizeFromPresetTab({continuationToken: token});
  }, 250);
}

async function generateFromPresetTab() {
  if (getOptionChecked('prompt_fixed') || !!presetGenerationPending || generating) {
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

async function randomizeFromPresetTab({continuationToken = null} = {}) {
  const isContinuation = continuationToken !== null;
  if (!isContinuation) clearPresetAutoGenTimer();
  if (isContinuation && !presetAutoGenConditionsHold(continuationToken, {requireIdle: true})) {
    updateGenerateButtonMode();
    return;
  }
  if (getOptionChecked('prompt_fixed') || !!presetGenerationPending || generating) {
    updateGenerateButtonMode();
    return;
  }
  btnRnd.disabled = true;
  try {
    const changed = await eventPresetPanel?.randomizeCurrentCategory?.();
    if (!changed) {
      showToast(eventPresetPanel?.randomizeUnavailableMessage?.() || '랜덤 선택 가능한 Preset이 없습니다.', 'error');
    } else if (isContinuation) {
      if (presetAutoGenConditionsHold(continuationToken, {requireIdle: true})) {
        await generateFromPresetTab();
      }
    } else if (getOptionChecked('auto_generate')) {
      await generateFromPresetTab();
    }
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

// Ollama 모드(Auto Boost ON) Random 버튼 경과시간 — Generate 버튼과 동일 패턴.
function startRndTimer() {
  stopRndTimer();
  rndStartTime = Date.now();
  rndTimer = setInterval(() => {
    const elapsed = ((Date.now() - rndStartTime) / 1000).toFixed(1);
    if (btnRnd) btnRnd.innerHTML = `<span class="shortcut-hint">ALT + ENTER</span>${elapsed}s`;
  }, 100);
}

function stopRndTimer() {
  if (rndTimer) {
    clearInterval(rndTimer);
    rndTimer = null;
    if (btnRnd) btnRnd.innerHTML = _RND_BTN_LABEL;  // 'Random' 라벨 복원
  }
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

  if (key === 'auto_generate' && !next) clearPresetAutoGenTimer();
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

// 알림음(Web Audio, 에셋 불필요) — sound 마커가 붙은 토스트(자동화 완료 등)에서 재생.
let _notifyAudioCtx = null;
function _ensureNotifyAudioCtx() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!_notifyAudioCtx) _notifyAudioCtx = new Ctx();
    if (_notifyAudioCtx.state === 'suspended') _notifyAudioCtx.resume();
    return _notifyAudioCtx;
  } catch (e) { return null; }
}
function playNotifySound() {
  const ctx = _ensureNotifyAudioCtx();
  if (!ctx) return;
  try {
    const now = ctx.currentTime;
    // 2음 차임(A5 → D6)
    [[880, 0], [1174.66, 0.13]].forEach(([freq, t]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const start = now + t;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.3, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.28);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.3);
    });
  } catch (e) { /* ignore */ }
}
// 브라우저 자동재생 정책: 첫 사용자 제스처에서 AudioContext를 미리 unlock(자동화는 사용자가
// 켜고 시작하므로 그 시점 제스처로 충분; 이후 완료 시 정지 상태 없이 즉시 재생).
let _notifyAudioPrimed = false;
function _primeNotifyAudio() {
  if (_notifyAudioPrimed) return;
  _notifyAudioPrimed = true;
  _ensureNotifyAudioCtx();
  document.removeEventListener('pointerdown', _primeNotifyAudio);
  document.removeEventListener('keydown', _primeNotifyAudio);
}
document.addEventListener('pointerdown', _primeNotifyAudio);
document.addEventListener('keydown', _primeNotifyAudio);

// Electron 셸: Automation 완료 시 작업표시줄 버튼 깜빡임(Windows 노란불)으로 주의를 끈다.
// 웹/비-Electron(naiaShell 없음)에서는 자동 no-op. main이 창 비활성일 때만 실제로 깜빡인다.
function flashTaskbarAttention() {
  try { window.naiaShell?.flashTaskbar?.(); } catch (e) { /* non-electron / no-op */ }
}

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
    // 자동 재프로브가 12초마다 실패 결과를 다시 가져오므로, 이미 강제 상태면 openApiPopup 을
    // 반복 호출하지 않는다 (dataBootstrapPanel.refresh 등 부수효과 반복 방지).
    const alreadyForced = setupController.isRuntimeSetupForced?.();
    setupController.setRuntimeSetupForced?.(true, '연결된 백엔드가 없습니다. API 설정을 확인하세요.');
    if (reason !== 'api_status' && !alreadyForced) openApiPopup();
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
  // **마지막 방어선.** setMode 가 막지만 백엔드 브로드캐스트·세션 복원처럼 프론트를
  // 거치지 않는 경로가 있다. NAI 가 아닌데 Interactive 가 살아 있으면 강제로 끈다 —
  // 끄는 경로가 프롬프트 원본 복원까지 함께 처리한다.
  if (!isNai && interactivePanel?.isActive?.()) {
    interactivePanel.setActive(false);
    showToast('Interactive 모드를 껐습니다 — NAI 전용입니다', 'info');
  }
  updateInteractiveNaiToolBlock();   // Interactive 활성 시 Character/CharRef 차단 유지
  // Interactive 헤더의 Position/Reference 는 NAI 전용 — 모드가 바뀌면 다시 그린다.
  if (interactivePanel?.onModeChanged) interactivePanel.onModeChanged();

  // 모드 전환 시 런처 카테고리 상태(category-status = 적용된 Character/Vibe/Ref 표시)를
  // 재계산한다. updateModeState()는 요약(Activated:)만 갱신하고 런처 버튼은 안 건드렸다 —
  // 이것이 사용자가 본 "요약은 맞는데 버튼은 비활성"의 경로 분리다(Bug 1, ComfyUI→NAI 재현).
  if (moduleLauncherControl) moduleLauncherControl.updateState();
  updateModuleHeaderAction(currentModuleId);
  updateModeSelectAvailability();
  if (resultEnhance) resultEnhance.update();
  if (artistThumbControl) artistThumbControl.syncPromptFormat();
  if (sequencePresetControl?.onModeChange) sequencePresetControl.onModeChange(mode);
}

function setMode(mode) {
  if (syncingMode) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  // Interactive 는 NAI 전용이다(캐릭터를 char_captions 로 싣는 배선이 NAI 스펙이다).
  // 켜진 채로 다른 모드로 넘어가면 조립한 프롬프트가 갈 곳이 없다 — 먼저 끄게 한다.
  if (mode !== 'NAI' && interactivePanel?.isActive?.()) {
    syncMode(prevMode);
    showToast('Interactive 모드를 먼저 끄세요 — NAI 전용입니다', 'error');
    return;
  }
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
  // 배경/테두리는 타입 클래스에만 있다 — 타입 없이 부르면 투명한 토스트가 된다.
  toastEl.className = `toast ${type || 'info'}`;
  // 표시를 requestAnimationFrame 대신 강제 reflow 후 동기 적용한다. Electron 백그라운드
  // 스로틀링(창 최소화/가림/hidden) 시 rAF 콜백이 보류되는 동안 제거용 setTimeout 만 발화해
  // 'show' 가 나중에 영구히 붙는 stuck-toast 버그를 차단. (수 초 대기 후 도착하는 토스트에서 발생)
  void toastEl.offsetWidth; // reflow → opacity transition 트리거
  toastEl.classList.add('show');
  toastTimer = setTimeout(() => {
    toastEl.classList.remove('show');
    toastTimer = null;
  }, showConfigure ? 4000 : 2500);
}
// 안전망: 창이 숨겨진 동안 제거 타이머가 발화해 끝난 뒤 복귀했을 때 남아있는 토스트를 정리.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && toastEl && toastEl.classList.contains('show') && !toastTimer) {
    toastEl.classList.remove('show');
  }
});

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
  // Callers may pass pre-built, already-escaped HTML via options.messageHtml
  // (e.g. multi-line notices with <br>). Fall back to escaping the plain
  // `message` arg. messageHtml must be sanitized by the caller — the only user,
  // freeWorkflowNoticeHtml, escHtml()s each line before joining with <br>.
  const messageMarkup = options.messageHtml != null ? String(options.messageHtml) : escHtml(message);

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'app-confirm-overlay';
    overlay.innerHTML = `
      <section class="app-confirm-dialog" role="dialog" aria-modal="true" aria-label="${escHtml(title)}">
        <div class="app-confirm-icon" aria-hidden="true">i</div>
        <div class="app-confirm-copy">
          <div class="app-confirm-title">${escHtml(title)}</div>
          <div class="app-confirm-message">${messageMarkup}</div>
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
  // Refresh the tag-data section every time the modal opens so the user sees
  // a current download state rather than the snapshot from app load.
  if (dataBootstrapPanel) dataBootstrapPanel.refresh();
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

// Setup 모달 "연결 다시 확인" 버튼 (index.html onclick) — WS 미연결 시 토스트 피드백 포함
function reprobeApiConnections() {
  if (setupController) setupController.reprobeConnections();
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

// --- Grok(xAI) I2I 연동 onclick 핸들러 (제거 가능) ---
function grokLogin() {
  if (grokConnectPanel) grokConnectPanel.login();
}

function grokLogout() {
  if (grokConnectPanel) grokConnectPanel.logout();
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

// 리모트 패널 진입점 — 프롬프트 영역 컨텍스트 메뉴 최상단 "리모트" 항목.
// 패널 본체(Dev0714 RemoteWindow 이식)는 후속 작업; 지금은 자리만 잡아둔다.
function openRemotePanel(_target) {
  showToast('리모트 패널은 준비 중입니다 — 다음 업데이트에서 제공됩니다.', 'info');
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
let lastAnlasValue = null;       // 직전 표시 잔량 — 감소 감지(소비 점멸)용.
let anlasFlashTimer = null;
function flashAnlasPill() {
  if (!anlasPill) return;
  anlasPill.classList.remove('anlas-flash');
  void anlasPill.offsetWidth;    // reflow로 애니메이션 재시작(연속 소비 시 매번 점멸).
  anlasPill.classList.add('anlas-flash');
  if (anlasFlashTimer) clearTimeout(anlasFlashTimer);
  anlasFlashTimer = setTimeout(() => { if (anlasPill) anlasPill.classList.remove('anlas-flash'); }, 750);
}
function onAnlasUpdate(m) {
  if (!anlasPill || !anlasValue) return;
  if (!m.available) {
    anlasPill.classList.add('hidden');
    lastAnlasValue = null;       // 숨김 시 기준 리셋 — 재표시 첫 값에 오점멸 방지.
    return;
  }
  anlasPill.classList.remove('hidden');
  const n = Number(m.anlas || 0);
  anlasPill.classList.toggle('low', n > 0 && n < 100);
  anlasValue.textContent = n.toLocaleString();
  // 잔량이 줄었을 때만(=소비) pill을 짧게 점멸. 초기 로드(기준 없음)·충전(증가)은 제외.
  if (lastAnlasValue !== null && n < lastAnlasValue) flashAnlasPill();
  lastAnlasValue = n;
}

function updateApiStatus(m) {
  if (setupController) setupController.updateApiStatus(m);
  if (m && typeof m === 'object' && 'nai_configured' in m) {
    naiConfigured = !!m.nai_configured;
    updateNaiDirectorButton();
  }
  reconcileActiveApiMode('api_status');
}

// ---- Module floating panel ----
const modulePopup = $('modulePopup');
const moduleTitle = $('modulePopupTitle');
const moduleGuideBtn = $('modulePopupGuide');
const moduleBody = $('modulePopupBody');
const modulePopupAction = $('modulePopupAction');
const modulePopupDetach = $('modulePopupDetach');

// 모듈 헤더 우측 [ⓘ 가이드] 버튼의 오버뷰 문구 (모듈별). 없으면 버튼 숨김.
const MODULE_OVERVIEW_GUIDES = {
  prompt_engineering: [
    'NAIA의 프롬프트 생성은 이 프롬프트 엔지니어링 모듈을 통해 진행됩니다.',
    '일반적인 프롬프트 구조: [랜덤 프롬프트 인원 수] · {Prefix Prompts} · [랜덤 프롬프트] · {Postfix Prompts}',
    'Auto-Hide에 입력한 프롬프트는 랜덤 프롬프트가 Prefix·Postfix와 결합되는 과정에서 소거됩니다.',
    'Preprocessing Options에서는 랜덤 프롬프트에 포함될 요소를 결정할 수 있습니다. 각 기능을 확인해 보세요.',
    '※ WC Solo 모드에서는 Auto-Hide와 Preprocessing Option이 적용되지 않고, {Prefix Prompt}·{Postfix Prompt}와 와일드카드만으로 구성됩니다.',
  ].join('\n\n'),
  search: [
    'Prompt Search — 태그·키워드로 아카이브 전체를 검색해 생성 풀(결과셋)을 새로 만듭니다. Quick(태그 필터)이 기존 결과셋을 가볍게 좁히는 것과 달리, 이쪽은 무거운 전체 검색이라 [검색] 버튼으로 명시적으로 실행합니다.',
    'Search Keyword(포함) 문법 — 쉼표로 구분한 태그를 모두 포함(AND). {a|b|c} = 그 그룹 중 하나라도 포함(OR). *tag = 정확히 그 태그만(부분일치 없이 완전 일치). 예: 1girl, {smile|grin}, *solo',
    'Exclude Keyword(제외) 문법 — 포함과 문법이 다릅니다. tag = 그 문자열이 든 행을 제외(부분일치 — 예: girl 은 1girl·cowgirl 까지 제외). ~tag = 정확히 그 태그만 제외(예: ~girl 은 1girl 을 남김). ※ 제외 칸에서는 {a|b}·*tag 는 동작하지 않습니다.',
    '공통 — 태그의 _(언더바)는 공백으로 처리됩니다. 검색은 켜진 등급(G/S/Q/E)에만 적용됩니다.',
    'Remaining = 현재 풀에 남은 프롬프트 수. Parquet = 커스텀 결과셋 불러오기/합치기/내보내기. 심층검색 = 결과셋을 테이블로 깊게 다듬기. 복원 = 직전 스냅샷으로 되돌리기.',
  ].join('\n\n'),
  automation: [
    '자동화는 Auto Generate(자동 생성)를 제어하는 컨트롤러입니다. [시작]을 누르면 자동 생성이 켜지고, 설정한 종료 조건에 도달하면 자동으로 꺼집니다 — 자동화 자체가 이미지를 생성하지 않고, 생성은 자동 생성 루프를 통해 진행됩니다.',
    '종료 조건 — 무제한: 직접 [정지]할 때까지 계속 / 타이머: 지정한 시간(분)이 지나면 종료 / 횟수: 지정한 장수를 생성하면 종료.',
    '반복 횟수 — 같은 프롬프트로 N회 생성한 뒤 다음 프롬프트로 넘어갑니다(시드는 매번 바뀌어 변주가 생깁니다). 값은 저장되지 않고 항상 1로 시작합니다.',
    '지속 자동화 — Auto Gen을 켜면 저장된 자동화 설정으로 자동 시작합니다(Auto Gen이 트리거). 완료(횟수/타이머)되면 자동화와 Auto Gen이 모두 꺼지므로 무한 생성되지 않으며, 다시 돌리려면 Auto Gen을 다시 켜면 됩니다.',
  ].join('\n\n'),
  vibe_transfer: [
    'Vibe Transfer — 참조 이미지의 분위기(색감·화풍·구도 등)를 추출해 생성에 반영하는 NAI 전용 도구입니다. Upload/Paste하거나 Storage(저장된 인코딩)·Cluster(묶음)에서 불러온 뒤 Enable하면 적용됩니다.',
    'Ref Strength — 반영 강도(-1~1). Info Extracted(IE) — 참조에서 추출하는 정보량(클수록 원본에 가깝게). 헤드리스에서는 미리 인코딩된 항목만 사용합니다(새 인코딩 생성 불가).',
    '여러 장을 동시에 켤 수 있고 5장 이상은 Anlas가 추가될 수 있습니다. 활성 강도 합이 1.0을 넘으면 Normalize로 정규화하세요. Character Reference와 상호배타입니다(하나를 켜면 다른 쪽이 꺼집니다).',
  ].join('\n\n'),
  character_reference: [
    'Character Reference — 참조 이미지의 캐릭터/화풍을 director 방식으로 반영하는 NAID4.5 전용 도구입니다. Upload/Paste하거나 Storage에서 불러온 뒤 Enable하면 적용됩니다.',
    '참조 유형 — Char & Style(캐릭터+화풍) / Character(캐릭터만) / Style(화풍만). Strength — 반영 강도. Fidelity — 원본 충실도(높을수록 참조에 가깝게).',
    'Vibe Transfer와 상호배타이며(하나를 켜면 다른 쪽이 꺼짐), NAID4.5F/C 모델에서만 동작합니다.',
  ].join('\n\n'),
  character: [
    'Character — 여러 캐릭터를 개별 슬롯으로 구성해 멀티 캐릭터 생성에 쓰는 NAI 전용 도구입니다. 활성화한 뒤 각 슬롯에 캐릭터별 프롬프트와 UC(네거티브)를 입력합니다.',
    '슬롯 상태 — active(생성에 사용) / inactive(미사용) / cold(보류: 입력은 유지하되 이번 생성에서 제외). 생성에는 active 슬롯만 캐릭터로 들어갑니다.',
    '프롬프트·UC에는 와일드카드(__name__)도 사용할 수 있고, 리롤을 켜면 자동 생성 중 캐릭터 구성을 매 생성마다 다시 적용합니다.',
  ].join('\n\n'),
  wildcard: [
    '와일드카드 — 프롬프트의 __이름__ 토큰을 생성 때마다 해당 파일(이름.txt)의 한 줄로 치환합니다. 좌측 Browse 트리에서 파일을 탐색하고, 파일을 클릭하면 내용 편집·미리보기·조립 팝업이 열립니다.',
    '호출 문법 — __name__ = 일반(랜덤 1줄) · __*name__ = 순차(순서대로 한 줄씩) · __*master__ + __$master:slave__ = 종속(master가 한 바퀴 돌 때마다 slave가 한 칸 전진). 가중치는 200:텍스트(기본 100), 하위폴더는 __folder/name__ 로 호출합니다.',
    '파일 팝업 — 하단 [랜덤 / 순차 / $종속:순차] 탭에서 무작위 샘플을 뽑아보고, $종속:순차에서 slave를 좌측 트리 클릭으로 지정하면 구문과 한 바퀴·완주 생성 횟수를 확인하고 복사·삽입할 수 있습니다.',
  ].join('\n\n'),
};

function applyModuleOverviewGuide(moduleId) {
  if (!moduleGuideBtn) return;
  const guide = MODULE_OVERVIEW_GUIDES[moduleId] || '';
  if (guide) {
    moduleGuideBtn.dataset.naiaGuide = guide;
    moduleGuideBtn.style.display = '';
  } else {
    delete moduleGuideBtn.dataset.naiaGuide;
    moduleGuideBtn.style.display = 'none';
  }
}
const chunkPanel = $('chunkPanel');
let currentModuleId = null;
let moduleSendTimer = null;
let pendingModuleEdit = null;

// ── Tag / Tag Filter surface lock ────────────────────────────────────────────
// A search / parquet load-merge / rating toggle / tag-filter search on a large
// archive (or a slow machine) mutates the shared result pool. Interleaving a
// second op before the first's reply corrupts the pool/rating state, so we lock
// the Tag Filter popup and (when open) the Search module while any such request
// is in flight. Release is keyed to the actual completion WS event, not a fixed
// timeout — so a fast backend barely shows the overlay while a slow one stays
// protected until it truly finishes.
//
// Lock reasons are tracked per SOURCE (not a single boolean) so an overlapping
// op can't be unlocked by another op's completion. Two independent completion
// channels exist: 'pool' ops (search / rating / parquet / restore / chunk-load)
// settle on search_state (or search_loading:false); a background 'tagfilter'
// search settles on tag_filter_result / _assigned. The pool ops are serialized
// server-side, so collapsing them to one 'pool' key is safe; only 'tagfilter'
// genuinely overlaps them. A 120ms show-delay suppresses the flash for
// sub-perceptual round-trips; the 90s safety timer force-clears every source if
// a reply is genuinely lost (re-armed by search_progress for long scans).
const tagSurfaceLock = (() => {
  const SHOW_DELAY_MS = 120;
  const SAFETY_MS = 90000;
  const sources = new Set();   // active lock reasons: 'pool' | 'tagfilter'
  let showTimer = null;
  let safetyTimer = null;
  const isBusy = () => sources.size > 0;
  function paint() {
    const on = isBusy();
    const tf = document.getElementById('tagFilterLock');
    if (tf) tf.classList.toggle('active', on);
    syncModuleSearchLock();
  }
  function syncModuleSearchLock() {
    const el = document.getElementById('moduleSearchLock');
    if (el) el.classList.toggle('active', isBusy() && currentModuleId === 'search');
  }
  function setCaption(text) {
    const value = String(text || '');
    document.querySelectorAll('.panel-lock-caption').forEach(el => { el.textContent = value; });
  }
  function clearTimers() {
    if (showTimer) { clearTimeout(showTimer); showTimer = null; }
    if (safetyTimer) { clearTimeout(safetyTimer); safetyTimer = null; }
  }
  function armSafety() {
    if (safetyTimer) clearTimeout(safetyTimer);
    safetyTimer = setTimeout(clearAll, SAFETY_MS);
  }
  function begin(source) {
    armSafety();
    const wasBusy = isBusy();
    sources.add(String(source || 'pool'));
    if (wasBusy) return;          // overlay already shown/pending — just tracked the extra source
    if (showTimer) clearTimeout(showTimer);
    showTimer = setTimeout(() => { showTimer = null; paint(); }, SHOW_DELAY_MS);
  }
  function refresh() { if (isBusy()) armSafety(); }   // progress heartbeat keeps a long scan locked
  function end(source) {
    sources.delete(String(source || 'pool'));
    if (isBusy()) { paint(); return; }   // other sources still in flight — stay locked
    clearTimers();
    setCaption('');
    paint();
  }
  function clearAll() {
    sources.clear();
    clearTimers();
    setCaption('');
    paint();
  }
  return { begin, refresh, end, clearAll, setCaption, syncModuleSearchLock, isBusy };
})();

// ── Search-pool load (chunk-load) progress + Random gate ─────────────────────
// A dedicated, authoritative state for the *pool load* (startup temp parquet,
// custom parquet load/merge/upload). Distinct from the tag-surface overlay: it
// owns (a) a persistent, always-visible progress toast (so the user sees it even
// with no panel open) and (b) the Random button gate. The gate is re-asserted on
// an interval so an unrelated button re-render can't silently re-enable Random
// mid-load; it clears ONLY on the genuine completion signal (search_loading
// loading:false), never on a stray event. Row progress re-arms nothing here —
// completion is explicit.
const poolLoad = (() => {
  const SAFETY_MS = 180000;   // force-release only if the authoritative search_state is genuinely lost
  let active = false;
  let loaded = 0;
  let total = 0;
  let phase = 'load';   // 'load' (chunk read, %) | 'filter' (tag-filter index build) | 'prepare' (between phases)
  let reassertTimer = null;
  let safetyTimer = null;
  function render() {
    const toast = document.getElementById('poolLoadToast');
    if (toast) {
      if (active) {
        if (phase === 'filter') {
          const pct = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : null;
          toast.textContent = pct !== null
            ? `태그 필터 전처리 ${pct}%   (${loaded.toLocaleString()} / ${total.toLocaleString()}행)`
            : '태그 필터 적용 중…  (대용량 풀 전처리)';
        } else if (phase === 'prepare') {
          toast.textContent = '검색 풀 준비 중…';
        } else {
          const pct = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : null;
          toast.textContent = pct !== null
            ? `검색 풀 로딩 중… ${pct}%   (${loaded.toLocaleString()} / ${total.toLocaleString()}행)`
            : '검색 풀 로딩 중…';
        }
        toast.classList.add('active');
      } else {
        toast.classList.remove('active');
      }
    }
    const btn = document.getElementById('btnRnd');
    if (btn) btn.classList.toggle('pool-locked', active);
  }
  function armTimers() {
    // Re-assert the gate periodically: if any other render clears .pool-locked,
    // it comes back within the interval while the pool is still preparing.
    if (!reassertTimer) reassertTimer = setInterval(render, 400);
    if (safetyTimer) clearTimeout(safetyTimer);
    safetyTimer = setTimeout(stop, SAFETY_MS);
  }
  function update(l, t, ph) {
    active = true;
    phase = ph === 'filter' ? 'filter' : 'load';
    loaded = Number(l) || 0;
    total = Number(t) || 0;
    render();
    armTimers();
  }
  // A phase's heavy work reported done, but the pool isn't authoritatively ready
  // yet (a reconstruct/assign may follow). Stay gated with an indeterminate
  // status until the final search_state calls stop() — no ungate gap between
  // load → reconstruct → filter.
  function hold() {
    if (!active) return;
    phase = 'prepare';
    render();
    armTimers();
  }
  function stop() {
    active = false;
    if (reassertTimer) { clearInterval(reassertTimer); reassertTimer = null; }
    if (safetyTimer) { clearTimeout(safetyTimer); safetyTimer = null; }
    render();
  }
  return { update, hold, stop, isActive: () => active, curPhase: () => (active ? phase : null) };
})();
const lockTagSurface = source => tagSurfaceLock.begin(source);
const unlockTagSurface = source => tagSurfaceLock.end(source);

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

const moduleLauncherReady = import('./js/features/moduleLauncher.mjs?v=20260704-v3-refblock')
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
      naiReferenceBlocked: () => naiModelBlocksReference(),
    });
    moduleLauncherControl.render();
    moduleLauncherControl.bind();
    if (pendingExtLauncherItems) {
      moduleLauncherControl.setExtensionItems(pendingExtLauncherItems.items, pendingExtLauncherItems.onClick);
      pendingExtLauncherItems = null;
    }
    // 재시작 복원: 런처는 async import 라, 적용된 도구(Character/CharRef/Vibe/Automation)의
    // module_state 가 render 이전에 도착하면 leaf 버튼이 아직 없어 배지 갱신이 no-op 으로 빠진다
    // (update* 가 btn==null 시 early-return). render 직후 캐시된 상태를 배지 갱신기로 재생해
    // leaf 클래스를 심고 updateState 로 카테고리 status 를 첫 페인트에 반영한다.
    replayLauncherModuleStates();
    moduleLauncherControl.updateState();
    ensureResolutionPresetOptions();
    updateWebUiHiresfixAssistControls();
    refreshResolutionPresetDisplay(currentMode || modeSelect?.value || 'NAI');
  })
  .catch(error => {
    console.error('Failed to initialize module launcher', error);
  });

let lastPromptEngineeringState = null;
const promptEngineeringPanelReady = import('./js/features/promptEngineeringPanel.mjs?v=20260724-catfilter9')
  .then(({createPromptEngineeringPanel}) => {
    promptEngineeringPanelControl = createPromptEngineeringPanel({
      document,
      moduleBody,
      escHtml,
      bindTagAssist,
      // Lazily resolve the action so panel/actions module import order doesn't matter.
      setOllamaAutoBoost: (checked) => {
        if (promptEngineeringActions) promptEngineeringActions.setOllamaAutoBoost(checked);
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering panel module', error);
  });
const promptEngineeringActionsReady = import('./js/features/promptEngineeringActions.mjs?v=20260724-catfilter9')
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
    // 재연결 시 좌측 패널을 현재 적용 프롬프트로 강제 재동기(FIX-B/RC-2) — session 메시지가 누락/레이스
    // 돼도 복구 보장. 백엔드가 prompt_sync{force:true} 로 응답한다.
    ws.send(JSON.stringify({type: 'get_prompt'}));
    ws.send(JSON.stringify({type: 'get_module_state', module_id: 'event_stream'}));
    ws.send(JSON.stringify({type: 'get_module_state', module_id: 'storyteller'}));
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

// NAID3(V3)는 Character / Character Reference / Vibe Transfer 가 V4 계열과 다른 사양이라
// 일시 차단한다(사용자 요청). pModel 값은 짧은 코드(NAID3 / NAID4.5F ...)이고 백엔드도
// `"NAID3" in model`(headless_remote_state_service)로 V3 를 판정하므로 동일 기준으로
// NAID3 일 때만 차단한다. NAID4.x/4.5 는 정상 허용. 모델 미확정(빈 값)이면 차단 안 함.
function naiModelBlocksReference() {
  if ((currentMode || modeSelect.value) !== 'NAI') return false;
  const sel = document.getElementById('pModel');
  const model = sel ? String(sel.value || '').trim().toUpperCase() : '';
  if (!model) return false;
  const metadata = naiModelMetaByKey.get(model);
  if (metadata?.capabilities && metadata.capabilities.v4_payload === false) return true;
  return model.includes('NAID3');
}

function openModule(moduleId, options = {}) {
  // NAI 전용 모듈 가드
  if (['character', 'character_reference', 'vibe_transfer'].includes(moduleId) && modeSelect.value !== 'NAI') {
    showToast('This module is only available in NAI mode', 'error');
    return;
  }
  // NAID3 에서 Character / CR / VT 차단 (다른 사양 — 일시 미지원)
  if (['character', 'character_reference', 'vibe_transfer'].includes(moduleId) && naiModelBlocksReference()) {
    showToast('NAID3에서는 Character / Character Reference / Vibe Transfer를 지원하지 않습니다 (다른 사양)', 'error');
    return;
  }
  if (imageModulePanels && moduleId !== 'vibe_transfer') {
    imageModulePanels.closeAllVibeClusterPanels();
  }
  // Leaving (or re-clicking) any module exits refine-mode first.
  if (refinePanelControl && refinePanelControl.isOpen()) refinePanelControl.close();
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
  applyModuleOverviewGuide(moduleId);
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
  if (refinePanelControl && refinePanelControl.isOpen()) refinePanelControl.close();
  if (currentModuleId === 'img2img' && img2imgPanel) img2imgPanel.closeMaskEditor();
  if (currentModuleId === 'vibe_transfer' && imageModulePanels && !options.keepVibeCluster) {
    imageModulePanels.closeAllVibeClusterPanels();
  }
  if (currentModuleId === 'character' && characterPanel) characterPanel.hideColdPanel();
  if (currentModuleId === 'prompt_engineering') flushPromptEngineeringEdits();
  else flushPendingModuleEdit(currentModuleId);
  modulePopup.classList.remove('open');
  modulePopup.classList.remove('refine-mode');
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
  // Reflect the busy overlay whenever the active module changes (the search-side
  // lock only applies while the Search module is the one on screen).
  tagSurfaceLock.syncModuleSearchLock();
}

const peE621Panel = $('peE621Panel');
const pePresetAddPanel = $('pePresetAddPanel');
const pePresetManagePanel = $('pePresetManagePanel');
const peDanbooruPanel = $('peDanbooruPanel');
const peOllamaBoostPanel = $('peOllamaBoostPanel');
const peDebugPanel = $('peDebugPanel');
const promptEngineeringPopupRenderersReady = import('./js/features/promptEngineeringPopupRenderers.mjs?v=20260723-catfilter9')
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
      setRandomizedWildcard: setRandomizedPromptWildcard,
      bindTagAssist,
      bindDanbooruFeedback,
      saveCategoryFilter: savePromptEngineeringCategoryFilter,
      // 사전 chip 호버 시 autocomplete 와 동일한 태그 설명 툴팁 재사용.
      bindTagHoverInfo: (root, selector) => {
        if (tagAssist && typeof tagAssist.bindTagChipInfoHover === 'function') {
          tagAssist.bindTagChipInfoHover(root, selector);
        }
      },
      panels: {
        e621: peE621Panel,
        presetAdd: pePresetAddPanel,
        presetManage: pePresetManagePanel,
        danbooru: peDanbooruPanel,
        ollamaBoost: peOllamaBoostPanel,
        debug: peDebugPanel,
      },
    });
  })
  .catch(error => {
    console.error('Failed to initialize Prompt Engineering popup renderers module', error);
  });
const promptEngineeringPopupsReady = import('./js/features/promptEngineeringPopups.mjs?v=20260620-emphframing1')
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
        ollamaBoost: peOllamaBoostPanel,
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
        ollamaBoost: renderPeOllamaBoostPanel,
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
  if (exceptPanel !== pePresetAddPanel && promptEngineeringPopups?.isOpen('presetAdd')) closePePresetAddPanel();
  if (exceptPanel !== pePresetManagePanel && promptEngineeringPopups?.isOpen('presetManage')) closePePresetManagePanel();
  if (exceptPanel !== peE621Panel && promptEngineeringPopups?.isOpen('e621')) closePeE621Panel();
  if (exceptPanel !== peDanbooruPanel && promptEngineeringPopups?.isOpen('danbooru')) closePeDanbooruPanel();
  if (exceptPanel !== peOllamaBoostPanel && promptEngineeringPopups?.isOpen('ollamaBoost')) closePeOllamaBoostPanel();
  if (exceptPanel !== peDebugPanel && promptEngineeringPopups?.isOpen('debug')) closePeDebugPanel();
  const resolutionPanel = document.getElementById('resolutionManagerPanel');
  if (exceptPanel !== resolutionPanel && resolutionManagerPanel?.isOpen()) closeResolutionManager();
  const naiModelPanel = document.getElementById('naiModelManagerPanel');
  if (exceptPanel !== naiModelPanel && naiModelManagerPanel?.isOpen()) closeNaiModelManager();
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

function openNaiModelManager() {
  if ((currentMode || modeSelect?.value || '').toUpperCase() !== 'NAI') {
    showToast('NAI 모드에서만 사용자 모델을 관리할 수 있습니다.', 'info');
    return;
  }
  const panel = document.getElementById('naiModelManagerPanel');
  closeAuxiliaryPopups(panel);
  if (naiModelManagerPanel) naiModelManagerPanel.open();
}

function closeNaiModelManager() {
  if (naiModelManagerPanel) naiModelManagerPanel.close();
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

function openPeOllamaBoostPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.openOllamaBoost();
}

function closePeOllamaBoostPanel() {
  if (promptEngineeringPopups) promptEngineeringPopups.closeOllamaBoost();
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
  if (seamObserver) seamObserver.watch('module_state', m && m.module_id);
  if (isModuleStateGuarded(m.module_id)) return;
  if (m.module_id) moduleStateCache.set(m.module_id, m);
  // Update status badges regardless of panel open state
  if (m.module_id === 'automation') updateAutoBadge(m);
  else if (m.module_id === 'auto_save' && autoSavePanel) autoSavePanel.setState(m);
  else if (m.module_id === 'character') updateCharBadge(m);
  else if (m.module_id === 'character_reference') {
    updateCharRefBadge(m);
    syncReferenceInsetWithCharRef(m);
    // Interactive 캐릭터 헤더의 [Reference] 배지도 이 상태를 쓴다.
    if (interactivePanel && typeof interactivePanel.refreshCharReference === 'function') {
      interactivePanel.refreshCharReference();
    }
  }
  else if (m.module_id === 'prompt_engineering') {
    // Interactive 의 베이스 프롬프트가 선행·후행을 품는다 — PE 가 바뀌면 즉시 다시 조립한다.
    if (interactivePanel && interactivePanel.isActive?.()) interactivePanel.refreshPrompt();
  }
  else if (m.module_id === 'vibe_transfer') updateVibeBadge(m);
  else if (m.module_id === 'save_directory' && saveDirectoryPanel) saveDirectoryPanel.setState(m);
  else if (m.module_id === 'img2img') updateImg2ImgResumeButton(m);
  // 위 배지 갱신이 leaf 버튼의 상태 클래스(char-active/charref-active/vibe-active/auto-active)를
  // 바꾸므로, 카테고리 버튼의 category-status 를 그 클래스에서 파생하는 런처를 명시적으로 재계산한다.
  // (런처의 MutationObserver 는 재시작 시 경합 — 적용된 도구로 부팅해도 첫 페인트에 상태가 안 뜸.)
  if (['automation', 'character', 'character_reference', 'vibe_transfer'].includes(m.module_id)) {
    moduleLauncherControl?.updateState();
  }
  else if (m.module_id === 'event_stream') {
    if (moduleLauncherControl) moduleLauncherControl.updateEventStreamState(m);
    if (eventStreamPanel) eventStreamPanel.setState(m);
    updateRandomStreamBadge(m);
  } else if (m.module_id === 'storyteller') {
    if (eventStreamPanel) eventStreamPanel.setStorytellerState(m);
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
  } else if (m.module_id === 'extensions') {
    // Settings 페이지 + 퀵 버튼(Tools/Fn) 동기화 — 탭/팝업 표시 여부와 무관하게 소비.
    renderExtensions(m);
  }

  if (m.module_id === 'prompt_engineering') {
    lastPromptEngineeringState = m;
    syncPromptEngineeringPopups();
    refreshHiresPresetSwapOptions(m);
  }
  if (m.module_id === 'chunk' && isChunkOpen()) {
    renderChunk(m);
  }
  // Frozen wildcard bar must stay live even when the wildcard panel isn't the
  // open module — freeze/unfreeze/reroll all broadcast a fresh wildcard state.
  if (m.module_id === 'wildcard') updateFrozenWildcardBar(m.frozen);

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
  else if (m.module_id === 'extensions') renderExtensions(m);
}

// ---- Extensions UI (Settings ▸ Extension + 퀵 버튼/팝업) ----
// 퀵 버튼 동기화 때문에 탭/팝업 표시 여부와 무관하게 항상 상태를 소비한다.
function renderExtensions(m) {
  lastExtensionsState = m;
  if (extensionsPanel) extensionsPanel.onState(m);
}

function openSaveDirectoryPanel() {
  if (saveDirectoryPanel) saveDirectoryPanel.open();
}

function onAutoSaveWebpChange(checked) {
  if (autoSavePanel) autoSavePanel.onWebpChange(checked);
}

function onQuicksaveModeChange(value) {
  if (autoSavePanel) autoSavePanel.onQuicksaveModeChange(value);
}

function onQuicksaveDirChange(value) {
  if (autoSavePanel) autoSavePanel.onQuicksaveDirChange(value);
}

function onQuicksaveFolderChange(value) {
  if (autoSavePanel) autoSavePanel.onQuicksaveFolderChange(value);
}

function pickQuicksaveDirectory() {
  if (autoSavePanel) autoSavePanel.pickQuicksaveDirectory();
}

function openQuicksaveFolder() {
  if (autoSavePanel) autoSavePanel.openQuicksaveFolder();
}

function clearResultHistory() {
  if (autoSavePanel) autoSavePanel.clearHistory();
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

function pickSaveDirectory() {
  if (saveDirectoryPanel) saveDirectoryPanel.pickAndApply();
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
  setAutomationRuntime(m);
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

// 런처 render 직후, render 이전에 도착해 leaf 버튼 부재로 흘려보낸 module_state 들을 다시 흘려
// leaf 상태 클래스를 심는다(부팅 시 적용된 NAI 도구의 카테고리 status 첫 페인트 보장). 캐시는
// 읽기 전용으로만 소비한다(배지 갱신기는 m 을 변형하지 않음).
function replayLauncherModuleStates() {
  const replays = [
    ['automation', updateAutoBadge],
    ['character', updateCharBadge],
    ['character_reference', updateCharRefBadge],
    ['vibe_transfer', updateVibeBadge],
  ];
  replays.forEach(([moduleId, updater]) => {
    const cached = moduleStateCache.get(moduleId);
    if (cached) {
      try { updater(cached); } catch (error) { console.warn('Failed to replay module state', moduleId, error); }
    }
  });
  const stream = moduleStateCache.get('event_stream');
  if (stream && moduleLauncherControl) {
    try { moduleLauncherControl.updateEventStreamState(stream); } catch (_) {}
  }
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

function renderPromptEngineeringDebug(snapshot, categoryFilters = {}) {
  return promptEngineeringPopupRenderers ? promptEngineeringPopupRenderers.renderDebugSnapshot(snapshot, categoryFilters) : '';
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

function renderPeOllamaBoostPanel(m) {
  if (promptEngineeringPopupRenderers) promptEngineeringPopupRenderers.renderOllamaBoost(m);
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

function setRandomizedPromptWildcard(front, back, enabled) {
  if (promptEngineeringActions) promptEngineeringActions.setRandomizedWildcard(front, back, enabled);
}

function savePromptEngineeringE621Settings() {
  if (promptEngineeringActions) promptEngineeringActions.saveE621Settings();
}

function savePromptEngineeringDanbooruSettings() {
  if (promptEngineeringActions) promptEngineeringActions.saveDanbooruSettings();
}

function savePromptEngineeringOllamaBoostSettings() {
  if (promptEngineeringActions) promptEngineeringActions.saveOllamaBoostSettings();
}

function refreshPromptEngineeringDebug() {
  if (promptEngineeringActions) promptEngineeringActions.refreshDebug();
}

function savePromptEngineeringCategoryFilter(category, exclude, include) {
  if (!promptEngineeringActions) return false;
  return promptEngineeringActions.saveCategoryFilter(category, exclude, include);
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

function setPromptEngineeringOllamaAutoBoost(checked) {
  if (promptEngineeringActions) promptEngineeringActions.setOllamaAutoBoost(checked);
}

function setModuleParam(moduleId, key, value, options = {}) {
  if (!options.skipPendingFlush) flushPendingModuleEdit(moduleId);
  // 전송 성공 여부 반환 — 재연결 중 조용히 유실되면 호출부(카테고리 필터 저장 등)가
  // dirty 를 유지하고 사용자에게 실패를 알릴 수 있어야 한다(Codex 리뷰 반영).
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({type: 'set_module_param', module_id: moduleId, key, value}));
      return true;
    } catch (error) {
      return false;
    }
  }
  return false;
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
// Live remaining time/count (future01 QTimer parity). The server pushes
// automation module_state on each generation/delay transition; between pushes a
// client-side 1s tick keeps the timer countdown smooth without server spam.
let automationRuntime = null;
let automationRuntimeAnchorMs = 0;
let automationTickTimer = null;

function automationKindOf(m) {
  const t = String(m && m.automation_type || '').trim().toLowerCase();
  if (t === 'timer' || t === 'count' || t === 'unlimited') return t;
  const byIndex = ['unlimited', 'timer', 'count'][Number(m && m.auto_type)];
  return byIndex || 'unlimited';
}

function formatAutomationClock(totalSeconds) {
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = n => String(n).padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
}

function liveAutomationRemainingSeconds() {
  if (!automationRuntime) return null;
  const base = Number(automationRuntime.remaining_seconds);
  if (!Number.isFinite(base)) return null;
  const elapsed = Math.floor((Date.now() - automationRuntimeAnchorMs) / 1000);
  return Math.max(0, base - elapsed);
}

function automationLiveState() {
  // Feed the badge formatter a state whose remaining_seconds has ticked down.
  if (!automationRuntime) return {is_running: false};
  if (automationKindOf(automationRuntime) === 'timer') {
    const rem = liveAutomationRemainingSeconds();
    if (rem != null) return {...automationRuntime, remaining_seconds: rem};
  }
  return automationRuntime;
}

function automationPanelStatusText() {
  const m = automationRuntime;
  if (!m || !m.is_running) return (m && m.status) || '';
  if (m.delay_info) return m.delay_info;
  const kind = automationKindOf(m);
  if (kind === 'timer') {
    const rem = liveAutomationRemainingSeconds();
    return rem == null ? 'Running' : `남은 시간 ${formatAutomationClock(rem)}`;
  }
  if (kind === 'count') {
    const c = Number(m.remaining_count);
    return Number.isFinite(c) ? `${c}회 남음` : 'Running';
  }
  const done = Number(m.completed_count);
  return Number.isFinite(done) ? `${done}회 생성됨` : 'Running';
}

function applyAutomationLiveDisplay() {
  if (moduleBadges) moduleBadges.updateAuto(automationLiveState());
  if (currentModuleId === 'automation' && automationPanel && automationPanel.setLiveStatus) {
    automationPanel.setLiveStatus(automationPanelStatusText());
  }
}

function startAutomationTick() {
  if (automationTickTimer) return;
  automationTickTimer = window.setInterval(applyAutomationLiveDisplay, 1000);
}

function stopAutomationTick() {
  if (automationTickTimer) {
    window.clearInterval(automationTickTimer);
    automationTickTimer = null;
  }
}

function setAutomationRuntime(m) {
  automationRuntime = m || {is_running: false};
  automationRuntimeAnchorMs = Date.now();
  if (m && m.is_running && automationKindOf(m) === 'timer') startAutomationTick();
  else stopAutomationTick();
  applyAutomationLiveDisplay();
}

function onAutoTypeChange(val) {
  if (automationPanel) automationPanel.onTypeChange(val);
}

function renderAutomation(m) {
  if (automationPanel) automationPanel.render(m);
  // The panel's render seeds mod-status from state.status; immediately replace
  // it with the live countdown/count so it is correct before the next tick.
  if (currentModuleId === 'automation') applyAutomationLiveDisplay();
}

// ---- Character module ----
function renderCharacter(m) {
  if (characterPanel) characterPanel.render(m);
}

function openCharacterAssetTab() {
  closeModule();
  switchRightTab('charAssets');
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
  // Hydrate the Storyteller hero section (saved steps + run state) alongside the
  // Event Stream debug state whenever the panel renders.
  requestModuleState('storyteller');
}

// ---- Wildcard Module ----
// Central sink for the wildcard freeze state → drives the top-left frozen bar.
// Wildcard module states only broadcast on user actions (freeze/unfreeze/reroll/
// jump/reload/boot), so an unconditional re-render is cheap; we deliberately do
// NOT dedupe, because the bar mutates its own state optimistically on unfreeze
// and a stale JSON guard could skip a needed authoritative re-render.
function updateFrozenWildcardBar(frozen) {
  const state = (frozen && typeof frozen === 'object')
    ? frozen : {locations: [], legacy: [], characters: []};
  latestWildcardFreezeState = state;
  if (frozenWildcardBar) frozenWildcardBar.render(state);
}

function renderWildcard(m) {
  updateFrozenWildcardBar(m && m.frozen);
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

function wcSimTab(tab) { if (wildcardManagerPanel) wildcardManagerPanel.setSimTab(tab); }
function wcPickSlave() { if (wildcardManagerPanel) wildcardManagerPanel.pickSlave(); }
function wcClearSlave() { if (wildcardManagerPanel) wildcardManagerPanel.clearSlave(); }
function wcRoll() { if (wildcardManagerPanel) wildcardManagerPanel.requestInspect(); }
// 순차 와일드카드 [Jump]: 다음 생성이 사용할 순차 위치를 강제 지정한다(1.5의 "생성 예약 후
// 취소로 순차 맞추기" 대체). 백엔드가 current_prompt_context 의 sequential_counters 를 세팅.
// 이름은 버튼의 data-* 에서 읽는다 — onclick 에 이름을 JS 문자열로 보간하지 않아 따옴표/특수
// 문자 인젝션이 원천 차단된다(Codex BLOCK 수정). dataset 은 HTML 엔티티를 자동 디코드해 원본
// 이름을 돌려준다.
async function wcJumpSeq(btn) {
  const ds = (btn && btn.dataset) || {};
  const name = ds.wcName || '';
  const max = Number(ds.wcTotal) || 0;
  const current = Number(ds.wcCurrent) || 1;
  if (!name || max <= 0) return;
  const answer = await Promise.resolve(showPromptDialog(
    `"${name}" 순차 위치로 점프 (1 ~ ${max}). 다음 생성이 이 위치 항목을 사용합니다.`,
    {
      title: '순차 와일드카드 Jump',
      okText: '이동',
      cancelText: '취소',
      defaultValue: String(current || 1),
      placeholder: `1 ~ ${max}`,
    },
  ));
  if (answer == null) return;
  const idx = parseInt(String(answer).trim(), 10);
  if (!Number.isFinite(idx) || idx < 1 || idx > max) {
    showToast(`1 ~ ${max} 사이의 숫자를 입력하세요.`, 'error');
    return;
  }
  setModuleParam('wildcard', 'set_sequential', JSON.stringify({ name, index: idx }));
}
function wcCopySyntax(btn) {
  const row = btn && btn.closest ? btn.closest('.wc-syntax-row') : null;
  const text = row ? (row.querySelector('.wc-syntax')?.textContent || '').trim() : '';
  if (!text) return;
  if (navigator.clipboard) navigator.clipboard.writeText(text);
  showToast('복사됨: ' + text, 'success');
}
function wcInsertSyntax(btn) {
  const row = btn && btn.closest ? btn.closest('.wc-syntax-row') : null;
  const text = row ? (row.querySelector('.wc-syntax')?.textContent || '').trim() : '';
  if (!text) return;
  const pe = document.getElementById('promptEdit');
  if (!pe) return;
  const cur = pe.value || '';
  pe.value = cur.trim() ? (cur.replace(/\s*$/, '') + ', ' + text) : text;
  pe.dispatchEvent(new Event('input', { bubbles: true }));
  showToast('프롬프트에 삽입됨', 'success');
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

function wcOpenFolder() {
  if (wildcardManagerPanel) wildcardManagerPanel.openFolder();
}

// ---- Image upload helper ----
function pasteModuleImage(moduleId) {
  if (imageModulePanels) imageModulePanels.pasteImage(moduleId);
}

function uploadModuleImage(moduleId, file) {
  if (imageModulePanels) imageModulePanels.uploadImage(moduleId, file);
}

// NAI .naiv4vibe / .naiv4vibebundle 가져오기: 파일(JSON 텍스트)을 읽어 백엔드로 전송.
// 백엔드가 사전 인코딩을 per-model 스토리지에 기록(Anlas 0) 후 [toast, storage_list] 반환 →
// Storage 브라우저가 즉시 갱신된다.
function importVibeFile(file) {
  if (!file) return;
  const send = text => {
    if (text && text.trim()) setModuleParam('vibe_transfer', 'import_vibe_file', text);
  };
  if (typeof file.text === 'function') {
    file.text().then(send).catch(err => console.error('Vibe import read failed', err));
  } else {
    const reader = new FileReader();
    reader.onload = () => send(String(reader.result || ''));
    reader.onerror = () => console.error('Vibe import read failed');
    reader.readAsText(file);
  }
}

// Vibe Storage 아이템 우클릭 메뉴: 위치 열기 / 삭제. 백엔드 set_param으로 위임.
function closeVibeStorageMenu() {
  document.getElementById('vibeStorageMenu')?.remove();
}
function showVibeStorageMenu(event, model, fileHash) {
  if (event) event.preventDefault();
  closeVibeStorageMenu();
  const menu = document.createElement('div');
  menu.id = 'vibeStorageMenu';
  menu.style.cssText = 'position:fixed;z-index:99999;min-width:140px;padding:4px;'
    + 'background:var(--bg-panel,#1a1830);border:1px solid var(--border-dim,#3a3550);'
    + 'border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,0.5);font-family:var(--font-mono,monospace)';
  const btn = 'display:block;width:100%;text-align:left;background:none;border:none;'
    + 'padding:7px 10px;font-size:12px;cursor:pointer;border-radius:4px';
  menu.innerHTML = `
    <button type="button" data-act="open" style="${btn};color:#e8e6f0">위치 열기</button>
    <button type="button" data-act="delete" style="${btn};color:#ff8a8a">삭제</button>`;
  document.body.appendChild(menu);
  const w = menu.offsetWidth || 150;
  const h = menu.offsetHeight || 80;
  menu.style.left = Math.max(4, Math.min(event.clientX, window.innerWidth - w - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(event.clientY, window.innerHeight - h - 4)) + 'px';
  menu.addEventListener('click', ev => {
    const act = ev.target && ev.target.dataset ? ev.target.dataset.act : '';
    if (act === 'open') {
      setModuleParam('vibe_transfer', 'open_location', model + '|' + fileHash);
    } else if (act === 'delete') {
      if (window.confirm('이 Vibe를 Storage에서 삭제할까요?')) {
        setModuleParam('vibe_transfer', 'delete_storage', model + '|' + fileHash);
      }
    }
    closeVibeStorageMenu();
  });
  setTimeout(() => document.addEventListener('click', closeVibeStorageMenu, {once: true}), 0);
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

function updateImg2ImgResumeButton(state) {
  const button = document.getElementById('img2imgResumeBtn');
  const dock = document.getElementById('img2imgResumeDock');
  if (!button) return;
  const status = String(state?.generation_status || 'idle');
  const mode = String(state?.mode || 'img2img').toLowerCase();
  const retryable = !!state?.active && (mode !== 'inpaint' || !!state?.has_mask);
  const hasSubmission = !['', 'idle', 'inactive', 'submitting'].includes(status);
  if (dock) dock.hidden = !(retryable && hasSubmission);
  const label = mode === 'inpaint' ? 'Inpaint' : 'Img2Img';
  const ico = document.createElement('span');
  ico.className = 'img2img-resume-ico';
  ico.textContent = mode === 'inpaint' ? '🖌' : '🎨';
  const txt = document.createElement('span');
  txt.textContent =
    status === 'queued' || status === 'running' ? `${label} 생성 중…`
    : status === 'completed_with_errors' ? `${label} 일부 실패 · 재시도`
    : status === 'error' ? `${label} 실패 · 재시도`
    : `${label} 재시도`;
  button.replaceChildren(ico, txt);
  button.dataset.status = status;
  button.title = status === 'running' || status === 'queued'
    ? '현재 생성 세션과 마스크를 다시 열기 (생성 완료 후 재시도 가능)'
    : '현재 소스와 마스크를 유지한 채 다시 열기';
  if (!state?.active) lastAutoHiddenImg2ImgSubmission = '';
}

function onImg2ImgGenerationState(message) {
  if (!message) return;
  const cached = moduleStateCache.get('img2img');
  const sameSession = cached
    && (!message.window_id || Number(cached.window_id) === Number(message.window_id));
  if (sameSession) {
    const merged = {...cached, ...message, type: 'module_state', module_id: 'img2img'};
    moduleStateCache.set('img2img', merged);
    if (currentModuleId === 'img2img') renderImg2Img(merged);
  }
  updateImg2ImgResumeButton(message);

  const submissionId = String(message.generation_submission_id || '');
  if (message.generation_status !== 'queued'
    || !submissionId
    || submissionId === lastAutoHiddenImg2ImgSubmission) return;
  lastAutoHiddenImg2ImgSubmission = submissionId;
  if (isDetachedModule && detachedModuleId === 'img2img') {
    window.close();
    return;
  }
  if (currentModuleId === 'img2img' && modulePopup.classList.contains('open')) {
    closeModule();
  }
  switchRightTab('result');
}

function resumeImg2ImgSession() {
  openModule('img2img', {forceOpen: true});
}

function dismissImg2ImgResume() {
  // 재개 dock 의 X — 세션을 정리(닫기)한다. 백엔드가 inactive img2img 상태를
  // 브로드캐스트하면 dock 이 확정 숨김되지만, 즉시성 위해 낙관적으로 먼저 숨긴다.
  const dock = document.getElementById('img2imgResumeDock');
  if (dock) dock.hidden = true;
  lastAutoHiddenImg2ImgSubmission = '';
  img2imgClose();
}

function img2imgSlider(key, value) {
  if (img2imgPanel) img2imgPanel.slider(key, value);
}

function img2imgRepeat(value) {
  if (img2imgPanel) img2imgPanel.repeat(value);
}

function img2imgResize1mp(checked) {
  if (img2imgPanel) img2imgPanel.resize1mp(checked);
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

// CR Storage 화면의 소스 탭 — 레퍼런스 보관함 / 캐릭터 에셋.


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
  tagSurfaceLock.end('tagfilter');
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
  // stale/superseded search_state(revision 가드 거부)는 pool 준비 완료가 아니므로 pool 잠금/
  // Random 게이트를 조기 해제하지 않는다 — newer 작업이 아직 진행 중(Codex NEW 선재 결함).
  const authoritative = searchPanelControl ? searchPanelControl.onSearchState(m) : true;
  if (authoritative === false) return;
  tagSurfaceLock.end('pool');   // completion of search / parquet load-merge / rating recompute / restore
  poolLoad.stop();              // authoritative 'pool ready' — clears load/reconstruct/filter gate + toast
}

function onSearchProgress(m) {
  if (searchPanelControl) searchPanelControl.onSearchProgress(m);
  tagSurfaceLock.refresh();   // long archive scan still running — keep locked, re-arm safety
}

function onSearchLoading(m) {
  // Chunked pool load (startup temp parquet / custom load-merge): lock Tag/Tag
  // Filter with a '풀 로딩 N%' caption while it streams, release + refresh on done.
  if (m && m.loading) {
    const phase = m.phase === 'filter' ? 'filter' : 'load';
    const total = Number(m.total) || 0;
    const loaded = Number(m.loaded) || 0;
    // Authoritative pool-prepare state: persistent toast + robust Random gate.
    poolLoad.update(loaded, total, phase);
    // Also raise the tag-surface overlay + caption (for an open Search/Filter popup).
    tagSurfaceLock.begin('pool');
    tagSurfaceLock.refresh();
    if (phase === 'filter') {
      if (total > 0) {
        const pct = Math.min(100, Math.round((loaded / total) * 100));
        tagSurfaceLock.setCaption(`태그 필터 전처리 ${pct}% (${loaded.toLocaleString()} / ${total.toLocaleString()}행)`);
      } else {
        tagSurfaceLock.setCaption('태그 필터 적용 중…');
      }
    } else {
      if (total > 0) {
        const pct = Math.min(100, Math.round((loaded / total) * 100));
        tagSurfaceLock.setCaption(`풀 로딩 ${pct}% (${loaded.toLocaleString()} / ${total.toLocaleString()}행)`);
      } else {
        tagSurfaceLock.setCaption('풀 로딩 중…');
      }
      // Live-climb the toolbar 'Prompt: N' with rows read so far (settles to the
      // authoritative filtered count on the completion search_state). Direct DOM —
      // the search panel module may not be ready this early at startup.
      const countEl = document.getElementById('searchCount');
      if (countEl) countEl.textContent = String(loaded);
    }
    return;
  }
  // A phase finished (load or filter), but the pool isn't authoritatively ready
  // until the final search_state — hold the gate (no ungate gap between load →
  // reconstruct → filter). After a LOAD phase, fetch the state to drive the
  // reconstruct; after a FILTER phase the natural tag_filter_result→assign→
  // search_state flow completes it, so don't kick a redundant get_search_state
  // (which could trigger an extra reconstruct).
  const wasFilterPhase = poolLoad.curPhase() === 'filter';
  poolLoad.hold();
  tagSurfaceLock.setCaption('검색 풀 준비 중…');
  tagSurfaceLock.refresh();
  if (!wasFilterPhase && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'get_search_state'}));
  }
}

function onBucketDates(m) {
  if (searchPanelControl) searchPanelControl.onBucketDates(m);
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

// ---- Refine (Depth Search) tab view (inside #modulePopup) ----
const refineView = $('refineView');

function getFloatingPanelWidth(panel) {
  if (panel === chunkPanel) return 420;
  if (panel === peDebugPanel) return 520;
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
  if (chunkPanelControl) chunkPanelControl.relayout();
  positionFloatingPanel(pePresetAddPanel, modulePopup);
  positionFloatingPanel(pePresetManagePanel, modulePopup);
  positionFloatingPanel(peE621Panel, modulePopup);
  positionFloatingPanel(peDanbooruPanel, modulePopup);
  positionFloatingPanel(peOllamaBoostPanel, modulePopup);
  positionFloatingPanel(peDebugPanel, modulePopup);
  if (wildcardManagerPanel) wildcardManagerPanel.relayout();
  if (imageModulePanels) imageModulePanels.relayoutVibeClusterPanel();
}

function refineEnterMode() {
  modulePopup.classList.add('refine-mode');
}

function refineExitMode() {
  modulePopup.classList.remove('refine-mode');
}

function openRefine() {
  // Refine is a tab of the Search surface — only enter from the search module.
  if (currentModuleId !== 'search') return;
  if (refinePanelControl) refinePanelControl.open();
}

function closeRefine() {
  if (refinePanelControl) refinePanelControl.close();
}

function refineBack() {
  closeRefine();
}

function refineSample() {
  if (refinePanelControl) refinePanelControl.refineSample();
}

function refineGenerate() {
  if (refinePanelControl) refinePanelControl.refineGenerate();
}

function onDepthState(m) {
  if (refinePanelControl) refinePanelControl.onDepthState(m);
}

function onDepthSample(m) {
  if (refinePanelControl) refinePanelControl.onDepthSample(m);
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

/** 자동완성 드롭다운이 실제로 열려 있는가. tagAssist 는 tagTooltip 을 ac-mode 로 재사용한다.
 *  (acTarget 은 드롭다운을 닫아도 남아 있어 '열림' 판정에 쓸 수 없다.) */
function isTagAutocompleteOpen() {
  const tooltip = $('tagTooltip');
  return !!tooltip && tooltip.classList.contains('open') && tooltip.classList.contains('ac-mode');
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
  // 실제 버블링 input 이벤트를 디스패치한다 — 인라인 oninput 속성과 document 레벨
  // 리스너(스토리텔러 스텝 카드의 검증 무효화 등)가 사용자 타이핑과 동일하게 반응.
  // 과거엔 인라인 oninput만 수동 호출해서 자동완성의 프로그램적 값 변경이 검증 ✓를
  // stale로 남기는 부류의 버그가 반복됐다(Codex 리뷰 F1).
  el.dispatchEvent(new Event('input', {bubbles: true}));
}

const tagAssistReady = import('./js/features/tagAssist.mjs?v=20260725-iasup2')
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
      // Interactive 슬롯 편집 중에는 태그 정보 툴팁(설명 + RELATED)을 띄우지 않는다 —
      // 앵커 팝업(팔레트/썸네일) 위에 겹쳐 가린다. 자동완성 드롭다운은 그대로 동작한다.
      isTagInfoSuppressed: () => document.body.classList.contains('interactive-editing'),
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

/** 지금 글자를 치고 있나. 여기서는 Ctrl+S 를 가로채지 않는다 —
 *  프롬프트를 쓰다 무심코 눌렀을 때 이미지가 저장되면 안 된다. */
function isTypingTarget(el) {
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT';
}

/** 결과(Result) 화면을 보고 있나. 분리 창에는 탭이 없으므로 그때는 항상 참이다. */
function isResultViewActive() {
  const pane = document.querySelector('.right-tab-pane[data-right-pane="result"]');
  if (!pane) return true;                       // 분리 창 — 결과가 곧 화면 전부다
  return pane.classList.contains('active') && !pane.hidden;
}

// Ctrl+S — **판정은 여기 한 곳에서만** 한다. 무엇을 저장할지는 문맥이 정한다:
//
//   글자 입력 중        -> 넘긴다(가로채지 않는다)
//   Result 화면이 아님   -> 넘긴다. 예전에는 어느 탭에 있든 발화했고, 처리하지 않을
//                          때조차 preventDefault 를 걸어 브라우저 기본까지 막았다
//                          (사용자 지적 2026-08-05).
//   히스토리 팝업 열림   -> 팝업이 맡는다(고른 것 일괄 저장). 없으면 아래로 내려간다.
//   그 외               -> 지금 보고 있는 이미지 하나를 빠른 저장
//
// 리스너를 하나로 묶어 두는 이유: document 리스너를 둘로 나누면 `preventDefault()` 가
// 서로를 막지 못해 **둘 다 실행된다**(파일 2개·토스트 2개). 히스토리 다중선택(PR #32)이
// 정확히 그 형태였다 — 새 동작은 리스너를 늘리지 말고 아래 분기를 채운다.
document.addEventListener('keydown', async e => {
  const isSave = (e.key === 's' || e.key === 'S')
    && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey;
  if (!isSave) return;
  if (isTypingTarget(e.target)) return;
  if (!isResultViewActive()) return;

  // 히스토리가 자기 규칙(고른 것 일괄 저장)을 가지고 있으면 그쪽이 우선이다.
  // **팝업 여부로 가르지 않는다** — 선택은 레일에서도 만들어진다(실측: 레일에서
  // Ctrl+클릭으로 3개를 골라 두고 Ctrl+S 를 눌렀는데 단건 저장이 나갔다).
  // 고른 것이 없으면 `handleSaveShortcut` 이 false 를 내므로 아래 단건으로 내려간다.
  if (typeof resultHistory?.handleSaveShortcut === 'function'
      && resultHistory.handleSaveShortcut()) {
    e.preventDefault();
    return;
  }

  const path = resultHistory ? resultHistory.currentImagePath : '';
  // 여기서부터는 우리가 처리한다 — 그때만 브라우저의 "페이지 저장"을 막는다.
  e.preventDefault();
  if (!path) { showToast('저장할 이미지가 없습니다', 'info'); return; }
  try {
    const r = await fetch('/api/result/quicksave', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || '저장 실패');
    const how = d.mode === 'move' ? '이동' : (d.mode === 'noop' ? '이미 있음' : '저장');
    showToast(how + ': ' + String(d.path || '').split(/[\\/]/).pop(), 'success');
  } catch (err) {
    showToast('빠른 저장 실패: ' + err.message, 'error');
  }
});

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
function commitPendingTagFilterText() { if (quickFilter) quickFilter.commitPendingInputs(); }
function clearTagFilter() { if (quickFilter) quickFilter.clear(); }
function reapplyReleasedTagFilter() { if (quickFilter) quickFilter.reapplyReleased(); }
function resetReleasedTagFilter() { if (quickFilter) quickFilter.resetReleased(); }
function toggleSaveTagFilterRow() { if (quickFilter) quickFilter.toggleSaveRow(); }
function toggleTagFilterPresets() { if (quickFilter) quickFilter.togglePresets(); }
function confirmSaveTagFilterPreset() { if (quickFilter) quickFilter.confirmSavePreset(); }
function loadTagFilterPreset(i) { if (quickFilter) quickFilter.loadPresetAt(i); }
function deleteTagFilterPreset(i) { if (quickFilter) quickFilter.deletePresetAt(i); }
function onTagFilterResult(m) {
  if (!quickFilter || quickFilter.onResult(m)) tagSurfaceLock.end('tagfilter');
}
function onTagFilterAssigned(m) {
  if (!quickFilter || quickFilter.onAssigned(m)) tagSurfaceLock.end('tagfilter');
}
function onTagFilterStale(m) {
  if (!quickFilter || quickFilter.onStale(m)) tagSurfaceLock.end('tagfilter');
}
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
  frozenWildcardBarReady,
  interactivePanelReady,
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
  extensionsPanelReady,
  fontSettingsPanelReady,
  wildcardManagerPanelReady,
  instantWildcardPanelReady,
  e621EventPanelReady,
  ollamaAssistantPopupReady,
  ollamaChatPopupReady,
  translationHistoryPanelReady,
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
  naiModelManagerReady,
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
