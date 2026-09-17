export function createArtistThumbController({
  document,
  fetch,
  escHtml,
  showToast,
  promptEdit,
  negEdit,
  onPromptEdit,
  setPromptFields,
  getGenerationMode = () => 'NAI',
  getCurrentGenerationParams = null,
  // Auto Res·Rnd Res 를 **무시한** 사용자 선택 해상도(사용자 지정 2026-08-29).
  getUserChosenResolution = null,
  isComfyUiAnimaMode = () => false,
  isAnimaArtistMode = null,
  // 리모컨(떠 있는 조작판). 둘 다 지연 로드라 인스턴스를 직접 받지 않고 그때그때 묻는다.
  getRemoteController = () => null,
  // Prompt Engineering 의 부분 미러(믹스 판 아래 빠른 수정). 셋 다 app.js 가 쥔 길이다 -
  // 특히 쓰기에는 프리셋 도장이 필요해서 여기서 만들면 안 된다.
  getPeField = null,
  setPeField = null,
  getPePreset = () => '',
  requestPeState = () => {},
  // 리모컨을 켜면 오른쪽 화면을 Result 로 보낸다(사용자 지정) - 조각이 창으로 빠져
  // 나가 이 탭에는 자리 표시만 남기 때문이다.
  showResultTab = () => {},
}) {
  const modeEl = document.getElementById('artistThumbMode');
  const filterEl = document.getElementById('artistThumbFilter');
  const searchEl = document.getElementById('artistThumbSearch');
  const summaryEl = document.getElementById('artistThumbSummary');
  const statusEl = document.getElementById('artistThumbStatus');
  const gridEl = document.getElementById('artistThumbGrid');
  const openFolderBtn = document.getElementById('artistThumbOpenFolderBtn');
  const prevBtn = document.getElementById('artistThumbPrevBtn');
  const nextBtn = document.getElementById('artistThumbNextBtn');
  const downloadBtn = document.getElementById('artistThumbDownloadBtn');
  const randomBtn = document.getElementById('artistThumbRandomBtn');
  const remoteBtn = document.getElementById('artistThumbRemoteBtn');
  const selectBtn = document.getElementById('artistThumbSelectBtn');
  const batchBtn = document.getElementById('artistThumbBatchBtn');
  const batchMenu = document.getElementById('artistThumbBatchMenu');
  const pageLabel = document.getElementById('artistThumbPageLabel');
  const gotoInput = document.getElementById('artistThumbGotoInput');
  const gotoBtn = document.getElementById('artistThumbGotoBtn');
  const selectedImage = document.getElementById('artistThumbSelectedImage');
  const selectedEmpty = document.getElementById('artistThumbSelectedEmpty');
  const selectedName = document.getElementById('artistThumbSelectedName');
  const selectedMeta = document.getElementById('artistThumbSelectedMeta');
  const favoriteBtn = document.getElementById('artistThumbFavoriteBtn');
  const banBtn = document.getElementById('artistThumbBanBtn');
  const copyBtn = document.getElementById('artistThumbCopyBtn');
  const insertBtn = document.getElementById('artistThumbInsertBtn');
  const prefixEl = document.getElementById('artistThumbPrefix');
  const positiveEl = document.getElementById('artistThumbPositive');
  const weightSlider = document.getElementById('artistThumbWeightSlider');
  const weightInput = document.getElementById('artistThumbWeightInput');
  const postfixEl = document.getElementById('artistThumbPostfix');
  const prefixDefaultBtn = document.getElementById('artistThumbPrefixDefaultBtn');
  const postfixDefaultBtn = document.getElementById('artistThumbPostfixDefaultBtn');
  const generateBtn = document.getElementById('artistThumbGenerateBtn');
  const randomGenerateBtn = document.getElementById('artistThumbRandomGenerateBtn');
  const resultPreviewEl = document.getElementById('artistThumbResultPreview');
  const resultTitleEl = document.getElementById('artistThumbResultTitle');
  const resultExpandBtn = document.getElementById('artistThumbResultExpand');
  const resultCloseBtn = document.getElementById('artistThumbResultClose');
  const resultImageEl = document.getElementById('artistThumbResultImage');
  const resultEmptyEl = document.getElementById('artistThumbResultEmpty');

  const PAGE_SIZE = 48;
  const MAX_RESULT_MEMORY = 128;
  const ARTIST_QUEUE_RESULT_TIMEOUT_MS = 20 * 60 * 1000;
  const ARTIST_RANDOM_PROMPT_TIMEOUT_MS = 55 * 1000;
  const FALLBACK_GENERATE_WIDTH = 832;
  const FALLBACK_GENERATE_HEIGHT = 1216;
  const GENERATE_LABEL = 'Generate';
  const RANDOM_GENERATE_LABEL = 'Generate with Random Prompt';
  const BATCH_LABEL = '일괄생성';
  const BATCH_CANCEL_LABEL = '생성 취소';
  const ACTIVE_RESOLUTION_PARAM_KEYS = [
    'api_mode',
    'resolution',
    'width',
    'height',
    'random_resolution',
    'auto_fit_resolution',
    'resolution_preset_enabled',
    'resolution_preset',
    'enable_hr',
    'hr_scale',
    'hr_upscaler',
    'denoising_strength',
    'hires_steps',
    'hr_cfg',
    'hires_preset_swap',
    'webui_hiresfix_assist',
    'webui_hiresfix_assist_target',
  ];
  let state = null;
  let statePromise = null;
  let listRequestId = 0;
  let optionsTimer = null;
  let currentPage = 0;
  let totalPages = 1;
  let currentListTotal = 0;
  let currentListFilterName = '전체 목록';
  let selected = null;
  let wheelPageLocked = false;
  let downloadTimer = null;
  let pendingResultRequestId = '';
  let pendingResultMeta = null;
  let resultBlobUrl = '';
  let hasLoadedList = false;
  let positiveAutoValue = '';
  let randomViewActive = false;
  let pendingResultAutoExpand = false;
  let pendingResultSuppressPreview = false;
  let pendingResultKeepPreview = false;
  let resultPreviewOpen = false;
  let resultExpanded = false;
  let artistTabActive = document.querySelector('[data-right-pane="artists"]')?.classList.contains('active') || false;
  // 리모컨에 올라가 있는가. 올라가 있으면 탭이 안 떠 있어도 격자는 **보이는 중**이다.
  let remoteOnboarded = false;
  // 믹스 모드(리모컨 전용). 켜져 있으면 ARTIST PROMPT 칸의 주인이 **큐**로 넘어간다.
  let mixQueue = null;
  let peQuick = null;
  let mixOn = false;
  // 앵커 그룹 `{아이디: 합친 글}`. 생성 요청에 실어 보내면 서버가 `<anchor:ID>` 자리에
  // 꽂는다(`core/artist_anchor.py`). 큐가 바뀔 때마다 갱신된다.
  let mixAnchorGroups = {};
  // 아티스트 그룹(저장 + 임시). 스토어가 유일한 주인이고 창·메뉴는 구독만 한다.
  let groupsApi = null;        // {store, createWindow, broker}
  const groupWindows = new Map();   // groupId -> window api
  let lastTempGroupId = '';
  const mixBtn = document.createElement('button');
  mixBtn.type = 'button';
  mixBtn.className = 'artist-thumb-page-btn rctl-mix-btn';
  mixBtn.textContent = '믹스 모드 OFF';
  mixBtn.setAttribute('aria-pressed', 'false');
  mixBtn.title = '아티스트 여러 명을 순서·가중치와 함께 쌓습니다. 켜면 창 옆에 큐가 열립니다.';

  /** 격자가 사람 눈에 닿아 있는가 - 탭이 떠 있거나, 리모컨에 올라가 있거나.
   *  ⚠️ `artistTabActive` 하나로 판단하면 리모컨에 올려 둔 격자가 조용히 낡는다. */
  function gridVisible() {
    return artistTabActive || remoteOnboarded;
  }
  let suppressResultCollapseClick = false;
  let suppressResultCollapseClickTimer = null;
  let contextMenuEl = null;
  let contextMenuItem = null;
  const resultMemory = new Map();
  const resultWaiters = new Map();
  const artistQueueEntries = [];
  const selectedBatchArtists = new Map();
  let resultBlobUrlManaged = false;
  let selectionMode = false;
  let artistQueueRunning = false;
  let artistQueueCancelRequested = false;
  let artistQueueMode = '';
  let artistQueueSerial = 0;
  let activeArtistQueueEntry = null;
  let activeOptionsMode = '';
  let optionsSaveSerial = 0;

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setSummary(message) {
    if (summaryEl) summaryEl.textContent = message || 'Artist dictionary';
  }

  function formatWeight(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number) || number <= 0) return '';
    if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}k`;
    return String(number);
  }

  function currentMode() {
    return String(modeEl?.value || '').trim();
  }

  function currentFilter() {
    return String(filterEl?.value || 'all').trim() || 'all';
  }

  function currentGenerationMode() {
    return String(getGenerationMode?.() || 'NAI').trim().toUpperCase();
  }

  function currentOptionsMode() {
    const mode = currentGenerationMode();
    return ['NAI', 'WEBUI', 'COMFYUI'].includes(mode) ? mode : 'NAI';
  }

  function escapeStableDiffusionArtistName(artist) {
    return String(artist || '').replace(/[()]/g, '\\$&');
  }

  function usesAnimaArtistSyntax() {
    const checker = typeof isAnimaArtistMode === 'function'
      ? isAnimaArtistMode
      : isComfyUiAnimaMode;
    return Boolean(checker?.());
  }

  function baseArtistPrompt(artist) {
    const name = String(artist || '').trim();
    if (!name) return '';
    const generationMode = currentGenerationMode();
    if (generationMode === 'NAI') return `artist:${name}`;
    const escaped = escapeStableDiffusionArtistName(name);
    if (usesAnimaArtistSyntax()) return `@${escaped}`;
    return escaped;
  }

  function artistWeightValue() {
    const raw = String(weightInput?.value || weightSlider?.value || '1').trim();
    const value = Number.parseFloat(raw);
    if (!Number.isFinite(value) || value === 0 || value === 1) return null;
    return value;
  }

  function formatArtistWeight(value) {
    return Number(value).toFixed(2).replace(/\.?0+$/, '');
  }

  /** 아티스트 토큰 하나. **서식은 이 함수만 만든다** - 믹스 큐도 이것을 받아 쓴다.
   *  두 곳에서 만들면 반드시 어긋난다(모드별 표기가 셋이다).
   *  @param withPrefix `artist:` 를 붙일지(NAI 에서만 뜻이 있다 - SD 계열엔 그런 접두어가 없다)
   */
  function formatArtistToken(artist, weight = 1, options = {}) {
    const name = String(artist || '').trim();
    if (!name) return '';
    const withPrefix = options.withPrefix !== false;
    const raw = Number.parseFloat(weight);
    const value = Number.isFinite(raw) ? raw : 1;
    const weighted = value !== 1;
    const formattedWeight = weighted ? formatArtistWeight(value) : '';
    try {
      if (currentGenerationMode() === 'NAI') {
        const body = withPrefix ? `artist:${name}` : name;
        return weighted && formattedWeight ? `${formattedWeight}::${body} ::` : body;
      }
      const escaped = escapeStableDiffusionArtistName(name);
      const body = usesAnimaArtistSyntax() ? `@${escaped}` : escaped;
      return weighted && formattedWeight ? `(${body}:${formattedWeight})` : body;
    } catch (_) {
      return baseArtistPrompt(name);
    }
  }

  function formatArtistPrompt(artist) {
    const name = String(artist || '').trim();
    if (!name) return '';
    const weight = artistWeightValue();
    return formatArtistToken(name, weight == null ? 1 : weight, {withPrefix: true});
  }

  function syncPromptFormat() {
    syncOptionsForCurrentMode();
    // 믹스 모드에서는 칸의 주인이 큐다 - 여기서 덮으면 조립 결과가 날아간다.
    if (mixOn && mixQueue) { applyMixComposition(mixQueue.compose()); return; }
    if (!selected || !positiveEl) return;
    const nextValue = formatArtistPrompt(selected.artist);
    if (!positiveAutoValue || positiveEl.value === positiveAutoValue) {
      positiveEl.value = nextValue;
    }
    positiveAutoValue = nextValue;
  }

  function makeRequestId() {
    return `artist-thumb-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function revokeResultBlobUrl() {
    if (!resultBlobUrl) return;
    if (resultBlobUrlManaged) URL.revokeObjectURL(resultBlobUrl);
    resultBlobUrl = '';
    resultBlobUrlManaged = false;
  }

  function setResultBlobUrl(url, managed = false) {
    revokeResultBlobUrl();
    resultBlobUrl = String(url || '');
    resultBlobUrlManaged = Boolean(managed);
  }

  function clearResultMemoryEntry(artist) {
    const key = String(artist || '').trim();
    const entry = resultMemory.get(key);
    if (!entry) return;
    URL.revokeObjectURL(entry.url);
    resultMemory.delete(key);
  }

  function pruneResultMemory() {
    while (resultMemory.size > MAX_RESULT_MEMORY) {
      const oldestKey = resultMemory.keys().next().value;
      clearResultMemoryEntry(oldestKey);
    }
  }

  function rememberArtistResult(artist, blob, meta = {}) {
    const key = String(artist || '').trim();
    if (!key || !blob) return null;
    clearResultMemoryEntry(key);
    const entry = {
      artist: key,
      url: URL.createObjectURL(blob),
      meta: {...meta, artist_thumb_artist: key},
      createdAt: Date.now(),
    };
    resultMemory.set(key, entry);
    pruneResultMemory();
    updateRememberedCards();
    return entry;
  }

  function rememberedResultForArtist(artist) {
    return resultMemory.get(String(artist || '').trim()) || null;
  }

  function titleForResultMemory(entry) {
    const meta = entry?.meta || {};
    const size = meta.width && meta.height ? ` · ${meta.width}x${meta.height}` : '';
    return `${entry?.artist || 'Artist Thumb'}${size}`;
  }

  function showRememberedResult(artist) {
    const entry = rememberedResultForArtist(artist);
    if (!entry) return false;
    setResultExpanded(false);
    setResultBlobUrl(entry.url, false);
    resultPreviewOpen = true;
    applyResultPreviewVisibility();
    if (resultTitleEl) resultTitleEl.textContent = titleForResultMemory(entry);
    if (resultImageEl) {
      resultImageEl.src = entry.url;
      resultImageEl.classList.add('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = true;
    updateResultExpandButton();
    return true;
  }

  /** 서버에 저장된 썸네일을 그 아티스트 카드에 바로 입힌다.
   *
   *  ⚠️ 목록을 다시 불러오지 않는다 — 그러면 스크롤·선택이 튀고, 일괄생성
   *     중이라면 매 장마다 전체 목록을 재조회하게 된다.
   *  ⚠️ 매번 덮어쓰므로 URL 이 같다 — 캐시 버스터가 없으면 옛 그림이 남는다.
   *  ⚠️ **공식 팩/즐겨찾기 그림은 밀어내지 않는다**(사용자 지정 2026-09-14).
   *     서버는 이미 `모드 팩 -> 즐겨찾기 -> 생성물` 순으로 골라 준다
   *     (`artist_thumbnail_service.item_image_url`). 그런데 여기서 무조건 갈아 끼우는
   *     바람에, 생성 직후부터 새로고침 전까지 팩 그림이 사라져 보였다. 같은 규약을
   *     여기에도 건다 - **빈 칸이거나 내가 만든 그림일 때만** 덮는다.
   */
  const GENERATED_IMAGE_PATH = '/api/artist-thumb/generated-image';

  function applySavedThumbnail(artist, url) {
    const key = String(artist || '').trim();
    if (!key || !url) return;
    const card = gridEl?.querySelector(`.artist-thumb-card[data-artist="${CSS.escape(key)}"]`);
    const host = card?.querySelector('.artist-thumb-card-image');
    if (!host) return;
    const src = `${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`;
    let img = host.querySelector('img');
    if (img && !String(img.getAttribute('src') || '').includes(GENERATED_IMAGE_PATH)) return;
    if (!img) {
      host.innerHTML = '';
      img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = key;
      host.appendChild(img);
    }
    img.src = src;
  }

  function updateRememberedCards() {
    gridEl?.querySelectorAll('.artist-thumb-card[data-artist]').forEach(card => {
      const remembered = resultMemory.has(card.dataset.artist || '');
      card.classList.toggle('remembered', remembered);
      let mark = card.querySelector('.artist-thumb-memory-mark');
      if (remembered && !mark) {
        mark = document.createElement('span');
        mark.className = 'artist-thumb-memory-mark';
        mark.textContent = 'RESULT';
        card.prepend(mark);
      } else if (!remembered && mark) {
        mark.remove();
      }
    });
  }

  function hasQueuedArtist(artist) {
    const key = String(artist || '').trim();
    return Boolean(key && artistQueueEntries.some(entry => entry.item?.artist === key));
  }

  function updateQueuedCards() {
    gridEl?.querySelectorAll('.artist-thumb-card[data-artist]').forEach(card => {
      const queued = !selectionMode && hasQueuedArtist(card.dataset.artist || '');
      card.classList.toggle('in-queue', queued);
      let mark = card.querySelector('.artist-thumb-queue-mark');
      if (queued && !mark) {
        mark = document.createElement('span');
        mark.className = 'artist-thumb-queue-mark';
        mark.textContent = 'IN QUEUE';
        card.prepend(mark);
      } else if (!queued && mark) {
        mark.remove();
      }
    });
  }

  function updateSelectionCards() {
    gridEl?.querySelectorAll('.artist-thumb-card[data-artist]').forEach(card => {
      const artist = card.dataset.artist || '';
      const checked = selectedBatchArtists.has(artist);
      card.classList.toggle('selectable', selectionMode);
      card.classList.toggle('batch-selected', checked);
      card.classList.toggle('batch-dim', selectionMode && !checked);
      let mark = card.querySelector('.artist-thumb-check');
      if (selectionMode && !mark) {
        mark = document.createElement('span');
        mark.className = 'artist-thumb-check';
        mark.setAttribute('aria-hidden', 'true');
        card.prepend(mark);
      } else if (!selectionMode && mark) {
        mark.remove();
        return;
      }
      if (mark) mark.classList.toggle('checked', checked);
    });
    if (selectBtn) selectBtn.classList.toggle('active', selectionMode);
    updateQueuedCards();
  }

  function selectedBatchItemsInGridOrder() {
    if (!gridEl) return [];
    return [...gridEl.querySelectorAll('.artist-thumb-card.batch-selected[data-artist]')]
      .map(card => selectedBatchArtists.get(card.dataset.artist || '') || itemFromCard(card))
      .filter(Boolean);
  }

  function visibleGridItemsInGridOrder() {
    if (!gridEl) return [];
    return [...gridEl.querySelectorAll('.artist-thumb-card[data-artist]')]
      .map(card => itemFromCard(card))
      .filter(Boolean);
  }

  function updateResultExpandButton() {
    if (!resultExpandBtn) return;
    const hasImage = Boolean(resultBlobUrl && resultImageEl?.classList.contains('show'));
    resultExpandBtn.disabled = !hasImage || resultExpanded;
    resultExpandBtn.textContent = resultExpanded ? '확대 중' : '크게 보기';
  }

  function applyResultPreviewVisibility() {
    if (!resultPreviewEl) return;
    resultPreviewEl.hidden = !(resultPreviewOpen && artistTabActive);
    updateResultExpandButton();
  }

  function clearResultCollapseClickBlock() {
    suppressResultCollapseClick = false;
    if (suppressResultCollapseClickTimer) {
      clearTimeout(suppressResultCollapseClickTimer);
      suppressResultCollapseClickTimer = null;
    }
    document.removeEventListener('click', blockResultCollapseClick, true);
  }

  function blockResultCollapseClick(event) {
    if (!suppressResultCollapseClick) return;
    event.preventDefault();
    event.stopPropagation();
    clearResultCollapseClickBlock();
  }

  function armResultCollapseClickBlock() {
    clearResultCollapseClickBlock();
    suppressResultCollapseClick = true;
    document.addEventListener('click', blockResultCollapseClick, true);
    suppressResultCollapseClickTimer = setTimeout(clearResultCollapseClickBlock, 350);
  }

  function collapseResultOnPointer(event) {
    if (!resultExpanded) return;
    setResultExpanded(false);
    armResultCollapseClickBlock();
    event.preventDefault();
    event.stopPropagation();
  }

  function setResultExpanded(expanded) {
    const canExpand = Boolean(artistTabActive && resultPreviewOpen && resultPreviewEl && resultBlobUrl && resultImageEl?.classList.contains('show'));
    resultExpanded = Boolean(expanded && canExpand);
    resultPreviewEl?.classList.toggle('is-expanded', resultExpanded);
    document.body?.classList.toggle('artist-thumb-result-spotlight', resultExpanded);
    document.removeEventListener('pointerdown', collapseResultOnPointer, true);
    if (resultExpanded) {
      clearResultCollapseClickBlock();
      document.addEventListener('pointerdown', collapseResultOnPointer, true);
    }
    updateResultExpandButton();
  }

  function showResultPreview(message = 'Waiting for generated image...') {
    setResultExpanded(false);
    resultPreviewOpen = true;
    applyResultPreviewVisibility();
    if (resultEmptyEl) {
      resultEmptyEl.hidden = false;
      resultEmptyEl.textContent = message;
    }
    if (resultImageEl) {
      resultImageEl.removeAttribute('src');
      resultImageEl.classList.remove('show');
    }
    updateResultExpandButton();
  }

  function closeResultPreview() {
    setResultExpanded(false);
    clearResultCollapseClickBlock();
    pendingResultRequestId = '';
    pendingResultMeta = null;
    pendingResultAutoExpand = false;
    pendingResultSuppressPreview = false;
    pendingResultKeepPreview = false;
    resultPreviewOpen = false;
    revokeResultBlobUrl();
    if (resultPreviewEl) resultPreviewEl.hidden = true;
    if (resultImageEl) {
      resultImageEl.removeAttribute('src');
      resultImageEl.classList.remove('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = false;
    updateResultExpandButton();
  }

  function setGenerateBusy(source, label) {
    if (generateBtn) generateBtn.disabled = true;
    if (randomGenerateBtn) randomGenerateBtn.disabled = true;
    if (source === 'manual' && generateBtn) generateBtn.textContent = label || 'Requesting...';
    if (source === 'random' && randomGenerateBtn) randomGenerateBtn.textContent = label || 'Randomizing...';
  }

  function clearGenerateBusy() {
    if (generateBtn) {
      generateBtn.disabled = false;
      generateBtn.textContent = GENERATE_LABEL;
    }
    if (randomGenerateBtn) {
      randomGenerateBtn.disabled = artistQueueRunning;
      randomGenerateBtn.textContent = RANDOM_GENERATE_LABEL;
    }
    updateArtistActionAvailability();
  }

  function updateArtistActionAvailability() {
    const locked = artistQueueRunning;
    // ⚠️ 페이지 이동은 **잠그지 않는다**(사용자 지시 2026-08-30). 큐는 자기 배열
    //    (`artistQueueEntries`)로 돌지 화면을 읽지 않으므로, 넘겨도 아무 영향이 없다.
    //    막아서 얻는 것이 없이 큐가 도는 동안 목록을 훑지 못하게만 했다.
    [modeEl, filterEl, searchEl, downloadBtn, selectBtn, randomBtn].forEach(control => {
      if (control) control.disabled = locked;
    });
    if (generateBtn) generateBtn.disabled = false;
    if (randomGenerateBtn) randomGenerateBtn.disabled = false;
    updatePager();
    if (batchBtn) {
      batchBtn.disabled = false;
      batchBtn.textContent = locked ? BATCH_CANCEL_LABEL : BATCH_LABEL;
      batchBtn.classList.toggle('danger', locked);
    }
    if (batchMenu && locked) batchMenu.hidden = true;
    updateRandomUi();
    updateDownloadUi();
  }

  function currentModeInfo() {
    const mode = currentMode();
    return (state?.modes || []).find(item => item.key === mode) || null;
  }

  function updateListStatus() {
    const mode = currentMode();
    const modeText = mode || '목록';
    const statusPrefix = randomViewActive ? 'Random artists' : modeText;
    const base = `${statusPrefix} · ${currentListFilterName || '전체 목록'} · ${Number(currentListTotal || 0).toLocaleString()} artists`;
    // 갱신이 걸려 있으면 **지금 보는 것이 옛 팩**이라고 말해 준다 - 막지는 않지만
    // 모른 채로 두지도 않는다(사용자 제보 2026-09-03).
    const info = currentModeInfo();
    if (info?.needs_update) {
      setStatus(`${base} · 옛 데이터입니다 — [Update] 로 갱신하세요`, 'busy');
      return;
    }
    setStatus(base, 'ok');
  }

  function updateRandomUi() {
    if (!randomBtn) return;
    const mode = currentMode();
    const info = currentModeInfo();
    randomBtn.disabled = artistQueueRunning;
    if (!mode) {
      randomBtn.title = '모드를 선택한 뒤 랜덤 작가를 불러올 수 있습니다.';
    } else if (info?.needs_update) {
      randomBtn.title = '데이터 업데이트 후 랜덤 작가를 불러올 수 있습니다.';
    } else if (info && !info.available) {
      randomBtn.title = '데이터 다운로드 후 랜덤 작가를 불러올 수 있습니다.';
    } else {
      randomBtn.title = '현재 조건에서 한 페이지 분량의 랜덤 작가를 보여줍니다.';
    }
  }

  function updateDownloadUi() {
    if (!downloadBtn) return;
    const info = currentModeInfo();
    const download = state?.download || {};
    const mode = currentMode();
    const activeForMode = Boolean(download.active && download.mode === mode);
    const needsDownload = Boolean(info && (!info.available || info.needs_update));
    downloadBtn.hidden = !needsDownload && !activeForMode;
    downloadBtn.disabled = artistQueueRunning || activeForMode || !mode;
    if (activeForMode) {
      const percent = Number(download.percent || 0);
      downloadBtn.textContent = percent > 0 ? `${percent}%` : 'Downloading...';
    } else {
      downloadBtn.textContent = info?.needs_update ? 'Update' : 'Download';
    }
  }

  function renderState() {
    if (!state) return;
    // 폴더 열기는 호스트 PC 의 탐색기를 연다 - 원격(폰·다른 PC)에서는 숨긴다(라우트도 403 으로 막는다).
    if (openFolderBtn) openFolderBtn.hidden = state.local === false;
    if (modeEl) {
      const previous = modeEl.value || '';
      const modes = state.modes || [];
      modeEl.innerHTML = [
        '<option value="">모드 선택...</option>',
        ...modes.map(mode => {
          const label = mode.label || mode.key;
          const suffix = mode.needs_update ? ' (update)' : (mode.available ? '' : ' (download)');
          const title = mode.needs_update
            ? `${label} · update required · ${Number(mode.size_mb || 0).toLocaleString()} / ${Number(mode.expected_size_mb || 0).toLocaleString()} MB`
            : (mode.available
              ? `${label} · ${Number(mode.size_mb || 0).toLocaleString()} MB`
              : `${label} · data missing`);
          return `<option value="${escHtml(mode.key)}" title="${escHtml(title)}">${escHtml(label + suffix)}</option>`;
        }),
      ].join('');
      modeEl.value = modes.some(mode => mode.key === previous) ? previous : '';
    }
    if (filterEl) {
      const previous = filterEl.value || 'all';
      const filters = state.filters || [];
      // 생성한 모델 묶음은 성격이 달라 구분선으로 가른다. <select> 안에서는 disabled
      // option 이 가장 널리 먹는 구분선이다(<hr> 은 최신 Chromium 에서만 산다).
      filterEl.innerHTML = filters.map(filter => (filter.separator
        ? `<option disabled>──── ${escHtml(filter.name || '')} ────</option>`
        : `<option value="${escHtml(filter.key)}">${escHtml(filter.name)} · ${Number(filter.count || 0).toLocaleString()}</option>`
      )).join('');
      filterEl.value = filters.some(filter => filter.key === previous) ? previous : 'all';
    }
    syncOptionsForCurrentMode();
    setSummary(`${Number(state.artist_count || 0).toLocaleString()} artists`);
    updateDownloadUi();
    updateArtistActionAvailability();
  }

  async function fetchState(options = {}) {
    if (state && !options.force) return state;
    if (!statePromise || options.force) {
      statePromise = fetch('/api/artist-thumb/state', {cache: 'no-store'})
        .then(async response => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
          state = data;
          renderState();
          return data;
        })
        .catch(error => {
          statePromise = null;
          console.error('Artist Thumb state failed', error);
          setStatus(error.message || 'Artist state failed', 'error');
          showToast?.(error.message || 'Artist state failed', 'error');
          throw error;
        });
    }
    return statePromise;
  }

  function listUrl(page, options = {}) {
    const params = new URLSearchParams({
      mode: currentMode(),
      filter: currentFilter(),
      query: String(searchEl?.value || '').trim(),
      page: String(page),
      per_page: String(PAGE_SIZE),
    });
    if (options.random) params.set('random_sample', '1');
    return `/api/artist-thumb/list?${params.toString()}`;
  }

  function renderGrid(items) {
    if (!gridEl) return;
    if (!items.length) {
      gridEl.innerHTML = '<div class="artist-thumb-empty">No matching artists.</div>';
      return;
    }
    const selectedArtist = selected?.artist || '';
    gridEl.innerHTML = items.map(item => {
      const active = item.artist === selectedArtist ? ' active' : '';
      const favorite = item.favorite ? ' favorite' : '';
      const banned = item.banned ? ' banned' : '';        // 제외 작가 - 해제 토글의 근거(버그 리포트 #1)
      const remembered = resultMemory.has(item.artist) ? ' remembered' : '';
      const queued = !selectionMode && hasQueuedArtist(item.artist) ? ' in-queue' : '';
      const selectable = selectionMode ? ' selectable' : '';
      const batchSelected = selectedBatchArtists.has(item.artist) ? ' batch-selected' : '';
      const batchDim = selectionMode && !selectedBatchArtists.has(item.artist) ? ' batch-dim' : '';
      const imageHtml = item.image_url
        ? `<img loading="lazy" src="${escHtml(item.image_url)}" alt="${escHtml(item.artist)}">`
        : '<span>No Image</span>';
      const checkHtml = selectionMode
        ? `<span class="artist-thumb-check${selectedBatchArtists.has(item.artist) ? ' checked' : ''}" aria-hidden="true"></span>`
        : '';
      const memoryHtml = remembered ? '<span class="artist-thumb-memory-mark">RESULT</span>' : '';
      const queueHtml = queued ? '<span class="artist-thumb-queue-mark">IN QUEUE</span>' : '';
      return `
        <button type="button" class="artist-thumb-card${active}${favorite}${banned}${remembered}${queued}${selectable}${batchSelected}${batchDim}" data-artist="${escHtml(item.artist)}" data-weight="${escHtml(String(item.weight || 0))}">
          ${checkHtml}
          ${memoryHtml}
          ${queueHtml}
          <div class="artist-thumb-card-image">${imageHtml}</div>
          <div class="artist-thumb-card-info">
            <span class="artist-thumb-card-name" title="${escHtml(item.artist)}">${escHtml(item.artist)}</span>
            <span class="artist-thumb-card-weight">${escHtml(formatWeight(item.weight))}</span>
          </div>
        </button>
      `;
    }).join('');
  }

  function itemFromCard(card) {
    if (!card) return null;
    const image = card.querySelector('img')?.getAttribute('src') || '';
    const weight = card.dataset.weight || card.querySelector('.artist-thumb-card-weight')?.textContent || '';
    return {
      artist: card.dataset.artist || '',
      image_url: image,
      weight,
      favorite: card.classList.contains('favorite'),
      banned: card.classList.contains('banned'),
    };
  }

  function updatePager() {
    if (pageLabel) pageLabel.textContent = `${currentPage + 1} / ${totalPages}`;
    if (prevBtn) prevBtn.disabled = currentPage <= 0;
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages - 1;
    if (gotoInput) {
      gotoInput.max = String(totalPages);
      gotoInput.placeholder = String(currentPage + 1);
      gotoInput.value = '';
    }
    if (gotoBtn) gotoBtn.disabled = totalPages <= 1;
  }

  function scrollGrid(anchor = 'top') {
    if (!gridEl) return;
    requestAnimationFrame(() => {
      if (!gridEl) return;
      gridEl.scrollTop = anchor === 'bottom' ? gridEl.scrollHeight : 0;
    });
  }

  async function loadPage(page = 0, options = {}) {
    if (selectionMode) setSelectionMode(false);
    await fetchState();
    const requestId = ++listRequestId;
    const mode = currentMode();
    const info = currentModeInfo();
    // ⚠️ **파일이 아예 없을 때만 막는다**(사용자 제보 2026-09-03).
    //    예전에는 `!available || needs_update` 로 막아, 갱신이 걸린 순간부터 2.5GB 를
    //    다 받을 때까지 격자가 "No matching artists." 로 비어 있었다 - 옛 팩이 디스크에
    //    멀쩡히 있는데도 아무것도 못 봤다. 갱신은 **알리는 것**이지 막는 것이 아니다.
    //    (`available` 은 "최신인가" 지 "볼 수 있는가" 가 아니다 - `exists` 로 본다.)
    const hasFile = info ? (info.exists !== undefined ? info.exists : info.available) : false;
    if (info && !hasFile) {
      randomViewActive = false;
      currentPage = 0;
      totalPages = 1;
      clearSelectedArtist();
      renderGrid([]);
      updatePager();
      updateDownloadUi();
      updateRandomUi();
      const download = state?.download || {};
      if (download.active && download.mode === mode) {
        setStatus(download.message || 'Artist Thumbnail 데이터 다운로드 중...', 'busy');
      } else {
        setStatus(`${info.label || mode} 데이터가 없습니다. Download 버튼으로 받을 수 있습니다.`, 'error');
      }
      return;
    }
    // ⚠️ 이 둘은 **막던 분기 안에만** 있었다. 갱신 중에도 목록을 그리게 바꾸면서 그
    //    분기를 안 타게 됐고, 그 바람에 [Update] 버튼이 통째로 사라졌다(사용자 제보
    //    2026-09-03). 어느 길로 오든 도구 줄은 다시 그려야 한다.
    updateDownloadUi();
    updateRandomUi();
    randomViewActive = Boolean(options.random);
    setStatus(mode ? 'Loading artist thumbnails...' : '모드를 선택하면 썸네일을 로드합니다.', mode ? 'busy' : '');
    if (gridEl) gridEl.classList.add('loading');
    try {
      const response = await fetch(listUrl(page, options), {cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (requestId !== listRequestId) return;
      currentPage = Number(data.page || 0);
      totalPages = Math.max(1, Number(data.total_pages || 1));
      randomViewActive = Boolean(data.random);
      currentListTotal = Number(data.total || 0);
      currentListFilterName = data.filter_name || '전체 목록';
      renderGrid(data.items || []);
      updatePager();
      hasLoadedList = true;
      scrollGrid(options.anchor || 'top');
      updateListStatus();
    } catch (error) {
      if (requestId !== listRequestId) return;
      console.error('Artist Thumb list failed', error);
      randomViewActive = false;
      renderGrid([]);
      updatePager();
      setStatus(error.message || 'Artist list failed', 'error');
      showToast?.(error.message || 'Artist list failed', 'error');
    } finally {
      if (requestId === listRequestId && gridEl) gridEl.classList.remove('loading');
    }
  }

  async function loadAdjacentPage(direction) {
    const nextPage = currentPage + direction;
    if (wheelPageLocked || nextPage < 0 || nextPage >= totalPages) return;
    wheelPageLocked = true;
    try {
      await loadPage(nextPage, {anchor: direction > 0 ? 'top' : 'bottom'});
    } finally {
      setTimeout(() => {
        wheelPageLocked = false;
      }, 260);
    }
  }

  function onGridWheel(event) {
    if (!gridEl || wheelPageLocked) return;
    if (randomViewActive) return;
    const atTop = gridEl.scrollTop <= 2;
    const atBottom = gridEl.scrollTop + gridEl.clientHeight >= gridEl.scrollHeight - 2;
    if (event.deltaY > 0 && atBottom && currentPage < totalPages - 1) {
      event.preventDefault();
      loadAdjacentPage(1);
    } else if (event.deltaY < 0 && atTop && currentPage > 0) {
      event.preventDefault();
      loadAdjacentPage(-1);
    }
  }

  function gotoPage() {
    if (artistQueueRunning) return;
    if (!gotoInput) return;
    const raw = Number.parseInt(String(gotoInput.value || '').trim(), 10);
    if (!Number.isFinite(raw)) {
      gotoInput.value = '';
      return;
    }
    const page = Math.max(1, Math.min(totalPages, raw)) - 1;
    loadPage(page, {anchor: page < currentPage ? 'bottom' : 'top'});
  }

  async function loadRandomArtists() {
    if (artistQueueRunning) return;
    if (selectionMode) setSelectionMode(false);
    const mode = currentMode();
    const info = currentModeInfo();
    if (!mode) {
      showToast?.('모드를 먼저 선택하세요.', 'error');
      return;
    }
    if (info && (!info.available || info.needs_update)) {
      showToast?.(info.needs_update ? '데이터 업데이트 후 사용할 수 있습니다.' : '데이터 다운로드 후 사용할 수 있습니다.', 'error');
      return;
    }
    await loadPage(currentPage, {anchor: 'top', random: true});
  }

  function setSelectionMode(enabled) {
    if (artistQueueRunning) return;
    selectionMode = Boolean(enabled);
    if (!selectionMode) selectedBatchArtists.clear();
    updateSelectionCards();
  }

  function toggleSelectionMode() {
    setSelectionMode(!selectionMode);
  }

  function toggleBatchSelection(item) {
    if (!item?.artist || artistQueueRunning) return;
    if (selectedBatchArtists.has(item.artist)) selectedBatchArtists.delete(item.artist);
    else selectedBatchArtists.set(item.artist, item);
    updateSelectionCards();
  }

  function closeBatchMenu() {
    if (batchMenu) batchMenu.hidden = true;
  }

  function toggleBatchMenu(event) {
    event?.preventDefault();
    event?.stopPropagation();
    if (artistQueueRunning) {
      cancelArtistQueue();
      return;
    }
    if (!batchMenu) return;
    batchMenu.hidden = !batchMenu.hidden;
  }

  function renderSelectedMeta(item) {
    if (!selectedMeta || !item) return;
    const weight = formatWeight(item.weight);
    selectedMeta.textContent = [
      weight ? `weight ${weight}` : '',
      item.favorite ? 'favorite' : '',
      item.banned ? '제외 작가' : '',
    ].filter(Boolean).join(' · ');
  }
  function banLabel(item) { return item?.banned ? '제외 해제' : '제외'; }

  function applyFavoriteState(item, favorite) {
    if (!item) return;
    item.favorite = favorite;
    if (selected && selected.artist === item.artist) {
      selected.favorite = favorite;
      renderSelectedMeta(selected);
    }
    if (favoriteBtn) favoriteBtn.textContent = favorite ? '관심 작가 해제' : '관심 작가 등록';
    gridEl?.querySelectorAll('.artist-thumb-card').forEach(card => {
      if (card.dataset.artist === item.artist) {
        card.classList.toggle('favorite', favorite);
      }
    });
  }

  function clearSelectedArtist() {
    selected = null;
    if (selectedImage) {
      selectedImage.removeAttribute('src');
      selectedImage.classList.remove('show');
    }
    if (selectedEmpty) selectedEmpty.hidden = false;
    if (selectedName) selectedName.textContent = '아티스트를 선택하세요';
    if (selectedMeta) selectedMeta.textContent = '';
    if (positiveEl && (!positiveAutoValue || positiveEl.value === positiveAutoValue)) {
      positiveEl.value = '';
    }
    positiveAutoValue = '';
    [favoriteBtn, banBtn, copyBtn, insertBtn].forEach(button => {
      if (button) button.disabled = true;
    });
    gridEl?.querySelectorAll('.artist-thumb-card.active').forEach(card => card.classList.remove('active'));
  }

  function selectArtist(item, options = {}) {
    selected = item;
    if (mixOn && mixQueue) {
      // 격자에서 고른 작가는 **임시 블럭** 한 자리를 차지하고 다음 선택에 갈린다.
      mixQueue.setTempArtist(item.artist, item.image_url || '');
    } else if (positiveEl) {
      positiveAutoValue = formatArtistPrompt(item.artist);
      positiveEl.value = positiveAutoValue;
    }
    if (selectedName) selectedName.textContent = item.artist;
    renderSelectedMeta(item);
    if (selectedImage) {
      selectedImage.src = item.image_url || '';
      selectedImage.classList.toggle('show', Boolean(item.image_url));
    }
    if (selectedEmpty) selectedEmpty.hidden = Boolean(item.image_url);
    [favoriteBtn, banBtn, copyBtn, insertBtn].forEach(button => {
      if (button) button.disabled = false;
    });
    if (favoriteBtn) favoriteBtn.textContent = item.favorite ? '관심 작가 해제' : '관심 작가 등록';
    if (banBtn) banBtn.textContent = banLabel(item);
    gridEl?.querySelectorAll('.artist-thumb-card').forEach(card => {
      card.classList.toggle('active', card.dataset.artist === item.artist);
    });
    if (options.showRemembered !== false) showRememberedResult(item.artist);
  }

  function selectedPayload() {
    if (!selected) {
      showToast?.('아티스트를 먼저 선택하세요.', 'error');
      return null;
    }
    return selected;
  }

  async function postJson(url, payload, options = {}) {
    const timeoutMs = Number(options.timeoutMs || 0);
    const controller = timeoutMs > 0 ? new AbortController() : null;
    let timer = null;
    if (controller) {
      timer = setTimeout(() => controller.abort(), timeoutMs);
    }
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload || {}),
        signal: controller?.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    } catch (error) {
      if (error?.name === 'AbortError') {
        throw new Error(options.timeoutMessage || 'Request timed out');
      }
      throw error;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  function waitForArtistResult(requestId, artist) {
    const key = String(requestId || '');
    if (!key) return Promise.reject(new Error('missing request id'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        resultWaiters.delete(key);
        reject(new Error(`${artist || 'Artist Thumb'} 결과 수신 시간이 초과되었습니다.`));
      }, ARTIST_QUEUE_RESULT_TIMEOUT_MS);
      resultWaiters.set(key, {resolve, reject, timer});
    });
  }

  function resolveArtistResultWaiter(requestId, entry) {
    const key = String(requestId || '');
    const waiter = resultWaiters.get(key);
    if (!waiter) return;
    clearTimeout(waiter.timer);
    resultWaiters.delete(key);
    waiter.resolve(entry);
  }

  function rejectAllArtistResultWaiters(error) {
    resultWaiters.forEach(waiter => {
      clearTimeout(waiter.timer);
      waiter.reject(error);
    });
    resultWaiters.clear();
  }

  function closeContextMenu() {
    if (contextMenuEl) {
      contextMenuEl.remove();
      contextMenuEl = null;
    }
    contextMenuItem = null;
    document.removeEventListener('pointerdown', onContextMenuPointerDown, true);
    document.removeEventListener('keydown', onContextMenuKeyDown, true);
    window.removeEventListener('blur', closeContextMenu);
    window.removeEventListener('resize', closeContextMenu);
  }

  function onContextMenuPointerDown(event) {
    if (contextMenuEl?.contains(event.target)) return;
    closeContextMenu();
  }

  function onContextMenuKeyDown(event) {
    if (event.key === 'Escape') closeContextMenu();
  }

  function positionContextMenu(menu, x, y) {
    const margin = 8;
    const rect = menu.getBoundingClientRect();
    const left = Math.min(Math.max(margin, x), window.innerWidth - rect.width - margin);
    const top = Math.min(Math.max(margin, y), window.innerHeight - rect.height - margin);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function openContextMenu(event, item) {
    if (!item?.artist) return;
    if (!groupsApi) {
      // 처음 한 번은 그룹을 읽은 뒤 연다 - 빈 목록을 보여 주면 '그룹이 없다' 로 읽힌다.
      const {clientX, clientY} = event;
      event.preventDefault();
      event.stopPropagation();
      void ensureGroups().then(() => openContextMenu(
        {clientX, clientY, preventDefault() {}, stopPropagation() {}}, item));
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    closeContextMenu();
    contextMenuItem = item;
    const menu = document.createElement('div');
    menu.className = 'result-context-menu artist-thumb-context-menu open';
    menu.setAttribute('role', 'menu');
    contextMenuEl = menu;
    const favoriteLabel = item.favorite ? '관심 해제' : '관심 추가';
    const banMenuLabel = item.banned ? '제외 해제' : '제외 추가';
    const queued = hasQueuedArtist(item.artist);
    const queueGroupHtml = queued
      ? `
        <button type="button" class="result-context-item artist-thumb-queue-cancel" data-action="queue-cancel" role="menuitem">
          <span>생성 예약 취소</span>
        </button>
      `
      : `
        <button type="button" class="result-context-item artist-thumb-queue-fixed" data-action="queue-fixed" role="menuitem">
          <span>생성 예약 (고정)</span>
        </button>
        <button type="button" class="result-context-item artist-thumb-queue-random" data-action="queue-random" role="menuitem">
          <span>생성 예약 (랜덤)</span>
        </button>
      `;
    menu.innerHTML = `
      <div class="result-context-group">
        ${queueGroupHtml}
      </div>
      <div class="result-context-group">
        <button type="button" class="result-context-item" data-action="favorite" role="menuitem">
          <span>${favoriteLabel}</span>
        </button>
        <button type="button" class="result-context-item danger" data-action="ban" role="menuitem">
          <span>${banMenuLabel}</span>
        </button>
      </div>
      ${groupMenuHtml(true)}
    `;
    menu.addEventListener('contextmenu', e => e.preventDefault());
    menu.addEventListener('click', event => {
      const button = event.target.closest('.result-context-item[data-action]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const action = button.dataset.action || '';
      const targetItem = contextMenuItem;
      if (action === 'group-new') {
        // 메뉴를 닫지 않고 이름 칸을 편다. 만들면서 이 작가를 넣는다.
        revealNewGroupForm(menu, name => createGroupWith(name, targetItem));
        return;
      }
      closeContextMenu();
      if (action === 'temp-add') { void putInTempWindow(targetItem); return; }
      if (action === 'group-pick') { void addToGroup(button.dataset.groupId, targetItem); return; }
      if (action === 'favorite') {
        setFavoriteForItem(targetItem, !targetItem.favorite).catch(error => {
          showToast?.(error.message || 'Favorite failed', 'error');
        });
      } else if (action === 'queue-fixed') {
        enqueueArtistGeneration(targetItem, 'fixed');
      } else if (action === 'queue-random') {
        enqueueArtistGeneration(targetItem, 'random');
      } else if (action === 'queue-cancel') {
        cancelQueuedArtist(targetItem?.artist);
      } else if (action === 'ban') {
        banItem(targetItem).catch(error => {
          showToast?.(error.message || 'Ban failed', 'error');
        });
      }
    });
    document.body.appendChild(menu);
    positionContextMenu(menu, event.clientX, event.clientY);
    document.addEventListener('pointerdown', onContextMenuPointerDown, true);
    document.addEventListener('keydown', onContextMenuKeyDown, true);
    window.addEventListener('blur', closeContextMenu);
    window.addEventListener('resize', closeContextMenu);
  }

  function ensureOptionsState() {
    if (!state) return null;
    const source = state.options && typeof state.options === 'object' ? state.options : {};
    const legacy = {
      prefix: String(source.prefix || ''),
      postfix: String(source.postfix || ''),
    };
    const rawModes = source.modes && typeof source.modes === 'object' ? source.modes : {};
    const modes = {};
    for (const mode of ['NAI', 'WEBUI', 'COMFYUI']) {
      const values = rawModes[mode] && typeof rawModes[mode] === 'object' ? rawModes[mode] : {};
      modes[mode] = {
        prefix: Object.prototype.hasOwnProperty.call(values, 'prefix') ? String(values.prefix || '') : legacy.prefix,
        postfix: Object.prototype.hasOwnProperty.call(values, 'postfix') ? String(values.postfix || '') : legacy.postfix,
      };
    }
    const mode = ['NAI', 'WEBUI', 'COMFYUI'].includes(String(source.mode || '').toUpperCase())
      ? String(source.mode || '').toUpperCase()
      : currentOptionsMode();
    state.options = {
      ...source,
      version: 2,
      mode,
      prefix: modes[mode]?.prefix || '',
      postfix: modes[mode]?.postfix || '',
      modes,
    };
    return state.options;
  }

  // 권장 기본값(사용자 지정 2026-08-26). 서버의 저장 기본값은 빈 문자열이라
  // — 비워 둔 사람과 일부러 비운 사람을 가를 수 없어야 하므로 — 권장값은
  // 버튼을 눌렀을 때만 들어간다. 자동으로 채우지 않는다.
  const RECOMMENDED_PREFIX = '1girl';
  const RECOMMENDED_POSTFIX = 'original, hair between eyes, medium breasts, year2025, '
    + 'masterpiece, very aesthetic, high-quality digital art, high complexity';

  /** 값만 넣으면 자동저장이 안 돌아간다 — `input` 을 직접 띄워 기존
   *  자동저장(scheduleSaveOptions)에 태워 보낸다. */
  function applyRecommended(el, value) {
    if (!el) return;
    el.value = value;
    el.dataset.seeded = '1';
    el.dispatchEvent(new Event('input', {bubbles: true}));
  }

  function readOptionFields() {
    return {
      prefix: prefixEl?.value || '',
      postfix: postfixEl?.value || '',
    };
  }

  function writeOptionFields(values) {
    if (prefixEl) {
      prefixEl.value = values?.prefix || '';
      prefixEl.dataset.seeded = '1';
    }
    if (postfixEl) {
      postfixEl.value = values?.postfix || '';
      postfixEl.dataset.seeded = '1';
    }
  }

  function optionValuesForMode(mode) {
    const options = ensureOptionsState();
    return options?.modes?.[mode] || {prefix: '', postfix: ''};
  }

  function cacheOptionFields(mode, values = readOptionFields()) {
    const modeKey = ['NAI', 'WEBUI', 'COMFYUI'].includes(String(mode || '').toUpperCase())
      ? String(mode || '').toUpperCase()
      : currentOptionsMode();
    const options = ensureOptionsState();
    if (!options) return values;
    options.modes[modeKey] = {
      prefix: String(values.prefix || ''),
      postfix: String(values.postfix || ''),
    };
    if (options.mode === modeKey) {
      options.prefix = options.modes[modeKey].prefix;
      options.postfix = options.modes[modeKey].postfix;
    }
    return options.modes[modeKey];
  }

  function currentOptionsPayload(mode = activeOptionsMode || currentOptionsMode(), values = readOptionFields()) {
    return {
      mode,
      prefix: values.prefix || '',
      postfix: values.postfix || '',
    };
  }

  async function saveOptionsForMode(mode = activeOptionsMode || currentOptionsMode(), values = readOptionFields()) {
    const serial = ++optionsSaveSerial;
    const payload = currentOptionsPayload(mode, values);
    cacheOptionFields(payload.mode, payload);
    const saved = await postJson('/api/artist-thumb/options', payload);
    if (saved && typeof saved === 'object') {
      const activeMode = activeOptionsMode || currentOptionsMode();
      const activeValues = readOptionFields();
      const savedModes = saved.modes && typeof saved.modes === 'object' ? {...saved.modes} : {};
      if (payload.mode !== activeMode || serial !== optionsSaveSerial) {
        savedModes[activeMode] = {
          ...(savedModes[activeMode] && typeof savedModes[activeMode] === 'object' ? savedModes[activeMode] : {}),
          prefix: activeValues.prefix || '',
          postfix: activeValues.postfix || '',
        };
      }
      state = {
        ...(state || {}),
        options: {
          ...saved,
          modes: savedModes,
        },
      };
      ensureOptionsState();
      if (payload.mode !== activeMode || serial !== optionsSaveSerial) {
        cacheOptionFields(activeMode, activeValues);
      }
    }
    return saved;
  }

  function saveCurrentOptions() {
    return saveOptionsForMode(activeOptionsMode || currentOptionsMode(), readOptionFields());
  }

  function syncOptionsForCurrentMode() {
    if (!state || (!prefixEl && !postfixEl)) return;
    const nextMode = currentOptionsMode();
    if (!activeOptionsMode) {
      writeOptionFields(optionValuesForMode(nextMode));
      activeOptionsMode = nextMode;
      return;
    }
    if (activeOptionsMode === nextMode) return;
    const previousMode = activeOptionsMode;
    const previousValues = readOptionFields();
    cacheOptionFields(previousMode, previousValues);
    saveOptionsForMode(previousMode, previousValues)
      .catch(error => console.warn('Artist Thumb options save failed', error));
    writeOptionFields(optionValuesForMode(nextMode));
    activeOptionsMode = nextMode;
  }

  /** 손잡이와 숫자칸에 값을 **그리기만** 한다. 되돌려 밀지 않는다 -
   *  큐에서 올라온 값을 여기서 다시 큐로 보내면 둘이 서로를 밀어 무한히 돈다. */
  function paintWeightControls(value) {
    const raw = Number.parseFloat(String(value ?? '1'));
    const next = Number.isFinite(raw) ? Math.max(0, Math.min(5, raw)) : 1;
    const display = formatArtistWeight(next) || '0';
    // 입력 중에는 재포맷 writeback 금지 — 타이핑마다 .value를 덮어쓰면 캐럿이 끝으로 튄다
    // (type=number라 selectionStart 복원 불가). 커밋(change/blur) 시에만 정규화한다.
    if (weightInput && document.activeElement !== weightInput) weightInput.value = display;
    // ⚠️ 손잡이는 0~2 지만 큐는 음수도 받는다 - 범위 밖이면 끝에 붙여 둔다.
    if (weightSlider) weightSlider.value = String(Math.max(0, Math.min(2, next)));
    return next;
  }

  function setArtistWeight(value) {
    const next = paintWeightControls(value);
    // 믹스 모드에서는 슬라이더가 **임시 블럭**을 민다(죽은 손잡이를 남기지 않는다).
    if (mixOn && mixQueue?.setTempWeight(next)) return;
    syncPromptFormat();
  }

  function scheduleSaveOptions() {
    if (optionsTimer) clearTimeout(optionsTimer);
    optionsTimer = setTimeout(() => {
      optionsTimer = null;
      saveCurrentOptions().catch(error => console.warn('Artist Thumb options save failed', error));
    }, 500);
  }

  async function setFavoriteForItem(item, favorite) {
    if (!item) return;
    state = await postJson('/api/artist-thumb/favorite', {
      artist: item.artist,
      favorite,
      mode: currentMode(),
    });
    renderState();
    applyFavoriteState(item, favorite);
    showToast?.(favorite ? '관심 작가로 등록했습니다.' : '관심 작가에서 해제했습니다.', 'success');
  }

  async function toggleFavorite() {
    const item = selectedPayload();
    if (!item) return;
    const next = !item.favorite;
    try {
      await setFavoriteForItem(item, next);
    } catch (error) {
      showToast?.(error.message || 'Favorite failed', 'error');
    }
  }

  /** 제외 토글. 이미 제외된 작가면 **해제**한다(버그 리포트 #1 - 전에는 언제나 추가라 한번 제외하면 영구였다).
   *  카드는 지금 필터에서 **보이면 안 되는 쪽**일 때만 지운다: 추가 → 일반 필터에서, 해제 → '제외 작가' 필터에서. */
  async function banItem(item) {
    if (!item) return;
    const banned = !item.banned;
    state = await postJson('/api/artist-thumb/ban', {artist: item.artist, banned});
    const artist = item.artist;
    const inBannedFilter = currentFilter() === 'banned';
    const shouldRemoveFromGrid = banned ? !inBannedFilter : inBannedFilter;
    item.banned = banned;
    if (selected && selected.artist === artist) {
      selected.banned = banned;
      renderSelectedMeta(selected);
      if (banBtn) banBtn.textContent = banLabel(selected);
    }
    renderState();
    let removedCount = 0;
    if (shouldRemoveFromGrid) {
      gridEl?.querySelectorAll('.artist-thumb-card').forEach(card => {
        if (card.dataset.artist === artist) {
          card.remove();
          removedCount += 1;
        }
      });
    }
    if (removedCount > 0) {
      currentListTotal = Math.max(0, currentListTotal - removedCount);
      totalPages = Math.max(1, Math.ceil(currentListTotal / PAGE_SIZE));
      if (currentPage >= totalPages) currentPage = Math.max(0, totalPages - 1);
      updatePager();
      updateListStatus();
    }
    if (shouldRemoveFromGrid && selected?.artist === artist) {
      clearSelectedArtist();
    } else {
      gridEl?.querySelectorAll('.artist-thumb-card').forEach(card => {
        if (card.dataset.artist === artist) card.classList.toggle('banned', banned);
      });
    }
    showToast?.(banned ? '제외 작가에 추가했습니다.' : '제외 작가에서 뺐습니다.', 'success');
  }

  async function banSelected() {
    const item = selectedPayload();
    if (!item) return;
    try {
      await banItem(item);
    } catch (error) {
      showToast?.(error.message || 'Ban failed', 'error');
    }
  }

  async function copySelected() {
    const item = selectedPayload();
    if (!item) return;
    try {
      await navigator.clipboard.writeText(item.artist);
      showToast?.('작가명을 복사했습니다.', 'success');
    } catch (_) {
      showToast?.('복사에 실패했습니다.', 'error');
    }
  }

  function insertSelected() {
    const item = selectedPayload();
    if (!item || !promptEdit) return;
    const tag = formatArtistPrompt(item.artist);
    const text = promptEdit.value || '';
    const start = promptEdit.selectionStart != null ? promptEdit.selectionStart : text.length;
    const end = promptEdit.selectionEnd != null ? promptEdit.selectionEnd : start;
    const before = text.substring(0, start);
    const after = text.substring(end);
    const prefix = before.trim() ? (/[,\s]$/.test(before) ? '' : ', ') : '';
    const insertText = `${prefix}${tag}, `;
    promptEdit.value = before + insertText + after;
    const nextPos = before.length + insertText.length;
    promptEdit.focus();
    promptEdit.selectionStart = promptEdit.selectionEnd = nextPos;
    onPromptEdit?.();
    showToast?.('프롬프트에 삽입했습니다.', 'success');
  }

  function applyGeneratedPromptToEditor(prompt, negativePrompt) {
    if (!promptEdit) return;
    const nextPrompt = String(prompt || '');
    const nextNegative = negativePrompt != null
      ? String(negativePrompt || '')
      : String(negEdit?.value || '');
    if (typeof setPromptFields === 'function') {
      setPromptFields(nextPrompt, nextNegative);
      return;
    }
    promptEdit.value = nextPrompt;
    if (negEdit && negativePrompt != null) {
      negEdit.value = nextNegative;
    }
    onPromptEdit?.();
  }

  function parsePositiveInt(value) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  function parseResolutionLabel(value) {
    const match = String(value || '').match(/(\d+)\s*x\s*(\d+)/i);
    if (!match) return null;
    const width = parsePositiveInt(match[1]);
    const height = parsePositiveInt(match[2]);
    return width && height ? {width, height} : null;
  }

  function currentActiveResolutionOverrides() {
    if (typeof getCurrentGenerationParams !== 'function') return {};
    let params = null;
    try {
      params = getCurrentGenerationParams();
    } catch (error) {
      console.warn('Artist Thumbnail generation params unavailable', error);
      return {};
    }
    if (!params || typeof params !== 'object') return {};

    const overrides = {};
    ACTIVE_RESOLUTION_PARAM_KEYS.forEach(key => {
      if (Object.prototype.hasOwnProperty.call(params, key)) {
        overrides[key] = params[key];
      }
    });

    let width = parsePositiveInt(overrides.width);
    let height = parsePositiveInt(overrides.height);
    if ((!width || !height) && overrides.resolution) {
      const parsed = parseResolutionLabel(overrides.resolution);
      if (parsed) {
        width = parsed.width;
        height = parsed.height;
      }
    }
    if (!width || !height) return {};

    overrides.width = width;
    overrides.height = height;
    overrides.artist_thumb_use_active_resolution = true;
    return overrides;
  }

  /** 이 화면이 쓸 해상도를 정한다 (사용자 지정 2026-08-29).
   *
   *  · **Auto Res 는 언제나 무시한다.** 그것은 랜덤 프롬프트의 소스 행에서 읽은
   *    값이라 아티스트 썸네일과 아무 상관이 없다.
   *  · **단일 [Generate] 는 Rnd Res 도 무시한다.** 아티스트를 비교하는 화면이라
   *    장마다 크기가 달라지면 비교가 안 된다.
   *  · `with random` 만 Rnd Res 를 따른다(그쪽은 매번 다른 그림이 목적이다).
   *
   *  ⚠️ `getCurrentGenerationParams()`(= `_collectCurrentParams`)는 Rnd Res 면
   *     **추첨**하고, 컨트롤에는 Auto Res 감지값이 앉아 있을 수 있다 - 그래서
   *     기본은 `getUserChosenResolution()`(서버에 저장된 사용자 선택)을 쓴다.
   */
  function resolutionOverridesFor(mode) {
    if (mode === 'random' && typeof getCurrentGenerationParams === 'function') {
      const rolled = currentActiveResolutionOverrides();
      if (rolled && rolled.width && rolled.height) return rolled;
    }
    if (typeof getUserChosenResolution === 'function') {
      try {
        const chosen = getUserChosenResolution();
        if (chosen && chosen.width && chosen.height) {
          return {resolution: chosen.resolution, width: chosen.width, height: chosen.height};
        }
      } catch (error) {
        console.warn('Artist Thumbnail resolution unavailable', error);
      }
    }
    return currentActiveResolutionOverrides();
  }

  function generationPayloadForItem(item, requestId, overrides = {}) {
    const artistPrompt = formatArtistPrompt(item.artist);
    const activeResolution = resolutionOverridesFor(overrides.__resMode || 'fixed');
    const mergedOverrides = {...activeResolution, ...overrides};
    // ⚠️ `__resMode` 는 **내부 표식**이다. 서버 스키마에 없으므로 반환에 섞지 않는다.
    return {
      ...activeResolution,
      request_id: requestId,
      artist: item.artist,
      prefix: mergedOverrides.prefix != null ? mergedOverrides.prefix : (prefixEl?.value || ''),
      positive: mergedOverrides.positive != null ? mergedOverrides.positive : (positiveEl?.value || artistPrompt),
      postfix: mergedOverrides.postfix != null ? mergedOverrides.postfix : (postfixEl?.value || ''),
      negative_prompt: mergedOverrides.negative_prompt != null ? mergedOverrides.negative_prompt : (negEdit?.value || ''),
      width: parsePositiveInt(mergedOverrides.width) || FALLBACK_GENERATE_WIDTH,
      height: parsePositiveInt(mergedOverrides.height) || FALLBACK_GENERATE_HEIGHT,
    };
  }

  async function requestArtistGeneration(payload, options = {}) {
    const keepPreview = Boolean(options.keepPreview && resultBlobUrl && resultImageEl?.classList.contains('show'));
    pendingResultRequestId = payload.request_id;
    pendingResultMeta = null;
    if (!keepPreview) revokeResultBlobUrl();
    pendingResultSuppressPreview = Boolean(options.suppressPreview);
    pendingResultKeepPreview = keepPreview;
    pendingResultAutoExpand = Boolean(options.autoExpand);
    if (resultTitleEl && !keepPreview) resultTitleEl.textContent = `${payload.artist} · generating`;
    if (!pendingResultSuppressPreview && !keepPreview) showResultPreview('Waiting for generated image...');
    await saveCurrentOptions();
    await postJson('/api/artist-thumb/generate', payload);
  }

  async function generateSelected() {
    const item = selectedPayload();
    if (!item) return;
    if (artistGenerationActive() || artistQueueRunning) {
      enqueueArtistGeneration(item, 'fixed');
      return;
    }
    const requestId = makeRequestId();
    pendingResultAutoExpand = false;
    const payload = generationPayloadForItem(item, requestId);
    try {
      setGenerateBusy('manual', 'Requesting...');
      await requestArtistGeneration(payload);
      showToast?.('Artist Thumbnail 생성 요청을 보냈습니다.', 'success');
    } catch (error) {
      clearPendingArtistRequest();
      showResultPreview(error.message || 'Generate failed');
      showToast?.(error.message || 'Generate failed', 'error');
      resumeArtistQueueIfReady();
    } finally {
      clearGenerateBusy();
    }
  }

  async function generateWithRandomPrompt() {
    const item = selectedPayload();
    if (!item) return;
    if (artistGenerationActive() || artistQueueRunning) {
      enqueueArtistGeneration(item, 'random');
      return;
    }
    const artistPrompt = String(positiveEl?.value || formatArtistPrompt(item.artist) || '').trim();
    if (!artistPrompt) {
      showToast?.('Artist Prompt가 비어 있습니다.', 'error');
      return;
    }
    const requestId = makeRequestId();
    try {
      pendingResultRequestId = requestId;
      pendingResultMeta = null;
      pendingResultAutoExpand = true;
      pendingResultSuppressPreview = true;
      revokeResultBlobUrl();
      if (resultTitleEl) resultTitleEl.textContent = `${item.artist} · random prompt`;
      if (resultPreviewEl) resultPreviewEl.hidden = true;
      setGenerateBusy('random', 'Randomizing...');

      const randomPrompt = await postJson('/api/artist-thumb/random-prompt', {
        artist_prompt: artistPrompt,
        // 앵커 그룹은 `<anchor:ID>` 자리에서 펼쳐진다. 선행부(첫 앵커 이전)만
        // `artist_prompt` 로 간다 - 둘 다 비면 서버가 400 을 준다.
        anchor_groups: mixOn ? mixAnchorGroups : undefined,
        timeout: 45,
      }, {
        timeoutMs: ARTIST_RANDOM_PROMPT_TIMEOUT_MS,
        timeoutMessage: 'Random prompt request timed out',
      });
      const positive = String(randomPrompt.prompt || '');
      if (!positive.trim()) throw new Error('Random prompt is empty');
      const negative = String(randomPrompt.negative_prompt || negEdit?.value || '');

      if (resultTitleEl) resultTitleEl.textContent = `${item.artist} · generating`;
      if (randomGenerateBtn) randomGenerateBtn.textContent = 'Requesting...';
      applyGeneratedPromptToEditor(positive, negative);
      await requestArtistGeneration(generationPayloadForItem(item, requestId, {
        __resMode: 'random',        // 이쪽만 Rnd Res 를 따른다
        prefix: '',
        positive,
        postfix: '',
        negative_prompt: negative,
      }), {suppressPreview: true, autoExpand: true});
      showToast?.('랜덤 프롬프트 생성 요청을 보냈습니다.', 'success');
    } catch (error) {
      clearPendingArtistRequest();
      if (resultPreviewEl) resultPreviewEl.hidden = true;
      showToast?.(error.message || 'Random prompt generate failed', 'error');
      resumeArtistQueueIfReady();
    } finally {
      clearGenerateBusy();
    }
  }

  async function buildQueuedPayload(item, requestId, mode) {
    if (mode !== 'random') {
      return generationPayloadForItem(item, requestId, {
        positive: formatArtistPrompt(item.artist),
      });
    }
    const artistPrompt = String(formatArtistPrompt(item.artist) || '').trim();
    if (!artistPrompt) throw new Error(`${item.artist} Artist Prompt가 비어 있습니다.`);
    const randomPrompt = await postJson('/api/artist-thumb/random-prompt', {
      artist_prompt: artistPrompt,
      timeout: 45,
    }, {
      timeoutMs: ARTIST_RANDOM_PROMPT_TIMEOUT_MS,
      timeoutMessage: `${item.artist} random prompt request timed out`,
    });
    const positive = String(randomPrompt.prompt || '');
    if (!positive.trim()) throw new Error(`${item.artist} random prompt is empty`);
    const negative = String(randomPrompt.negative_prompt || negEdit?.value || '');
    return generationPayloadForItem(item, requestId, {
      __resMode: 'random',          // 큐의 random 항목도 같다
      prefix: '',
      positive,
      postfix: '',
      negative_prompt: negative,
    });
  }

  function normalizeQueueMode(mode) {
    return mode === 'random' ? 'random' : 'fixed';
  }

  function queueModeLabel(mode) {
    return normalizeQueueMode(mode) === 'random' ? '랜덤' : '고정';
  }

  function artistGenerationActive() {
    return Boolean(pendingResultRequestId);
  }

  function updateWaitingQueueStatus() {
    if (artistQueueEntries.length && !artistQueueRunning) {
      setStatus(`Artist queue waiting · ${artistQueueEntries.length}`, 'busy');
    }
  }

  function resumeArtistQueueIfReady() {
    if (!artistQueueEntries.length || artistQueueRunning || artistGenerationActive()) return;
    startArtistQueueRunner();
  }

  function clearPendingArtistRequest() {
    pendingResultRequestId = '';
    pendingResultMeta = null;
    pendingResultAutoExpand = false;
    pendingResultSuppressPreview = false;
    pendingResultKeepPreview = false;
  }

  function enqueueArtistGeneration(item, mode = 'fixed', options = {}) {
    if (!item?.artist) return null;
    if (artistQueueCancelRequested) {
      if (!options.silent) showToast?.('Artist queue cancellation is pending.', 'error');
      return null;
    }
    const queueMode = normalizeQueueMode(mode);
    const entry = {
      id: `artist-queue-${++artistQueueSerial}`,
      item: {...item},
      mode: queueMode,
    };
    artistQueueEntries.push(entry);
    updateQueuedCards();
    updateArtistActionAvailability();
    if (!options.silent) {
      showToast?.(`${item.artist} 생성 예약 (${queueModeLabel(queueMode)})`, 'success');
    }
    if (options.start !== false) {
      if (!artistGenerationActive() && !artistQueueRunning) {
        startArtistQueueRunner();
      } else {
        updateWaitingQueueStatus();
      }
    }
    return entry;
  }

  function cancelQueuedArtist(artist) {
    const key = String(artist || '').trim();
    if (!key) return 0;
    const before = artistQueueEntries.length;
    for (let index = artistQueueEntries.length - 1; index >= 0; index -= 1) {
      if (artistQueueEntries[index]?.item?.artist === key) {
        artistQueueEntries.splice(index, 1);
      }
    }
    const removed = before - artistQueueEntries.length;
    if (!removed) return 0;
    updateQueuedCards();
    updateArtistActionAvailability();
    if (artistQueueEntries.length) {
      setStatus(`Artist queue waiting · ${artistQueueEntries.length}`, 'busy');
    } else if (!artistQueueRunning) {
      setStatus('Artist queue reservation cancelled.', 'ok');
    }
    showToast?.(`${key} 예약을 취소했습니다.`, 'success');
    return removed;
  }

  function enqueueArtistBatch(items, mode) {
    const queueMode = normalizeQueueMode(mode);
    let count = 0;
    items.forEach(item => {
      if (enqueueArtistGeneration(item, queueMode, {silent: true, start: false})) count += 1;
    });
    updateQueuedCards();
    if (count > 0) {
      showToast?.(`Artist queue reserved (${count})`, 'success');
      if (!artistGenerationActive() && !artistQueueRunning) {
        startArtistQueueRunner();
      } else {
        updateWaitingQueueStatus();
      }
    }
    return count;
  }

  async function runQueuedArtistGeneration(entry, index, total) {
    const item = entry?.item;
    const mode = normalizeQueueMode(entry?.mode);
    if (!item?.artist) throw new Error('Artist queue item is invalid');
    const requestId = makeRequestId();
    setStatus(`Artist queue ${index + 1} / ${total} · ${item.artist} (${queueModeLabel(mode)})`, 'busy');
    let resultPromise = null;
    try {
      const payload = await buildQueuedPayload(item, requestId, mode);
      resultPromise = waitForArtistResult(requestId, item.artist);
      await requestArtistGeneration(payload, {keepPreview: true});
      return await resultPromise;
    } catch (error) {
      const waiter = resultWaiters.get(requestId);
      if (waiter) {
        clearTimeout(waiter.timer);
        resultWaiters.delete(requestId);
      }
      throw error;
    }
  }

  function cancelArtistQueue() {
    if (!artistQueueRunning && !artistQueueEntries.length) return;
    artistQueueCancelRequested = true;
    artistQueueEntries.length = 0;
    updateQueuedCards();
    if (batchBtn) batchBtn.textContent = '취소 대기...';
    setStatus('Artist queue cancellation requested. Current generation will finish first.', 'busy');
  }

  function startArtistQueue(mode) {
    if (artistQueueRunning) return;
    const items = selectionMode ? selectedBatchItemsInGridOrder() : visibleGridItemsInGridOrder();
    if (!items.length) {
      showToast?.(selectionMode ? '일괄 생성할 아티스트를 선택하세요.' : '일괄 생성할 썸네일이 없습니다.', 'error');
      if (!selectionMode) setSelectionMode(true);
      return;
    }
    closeBatchMenu();
    setSelectionMode(false);
    enqueueArtistBatch(items, mode);
  }

  async function startArtistQueueRunner() {
    if (artistQueueRunning) return;
    if (artistGenerationActive()) {
      updateWaitingQueueStatus();
      return;
    }
    if (!artistQueueEntries.length) {
      updateArtistActionAvailability();
      return;
    }
    artistQueueRunning = true;
    artistQueueCancelRequested = false;
    artistQueueMode = '';
    updateArtistActionAvailability();
    let completed = 0;
    try {
      while (artistQueueEntries.length) {
        if (artistQueueCancelRequested) break;
        const entry = artistQueueEntries.shift();
        activeArtistQueueEntry = entry;
        artistQueueMode = normalizeQueueMode(entry?.mode);
        updateQueuedCards();
        const total = completed + 1 + artistQueueEntries.length;
        await runQueuedArtistGeneration(entry, completed, total);
        completed += 1;
        activeArtistQueueEntry = null;
      }
      if (artistQueueCancelRequested) {
        showToast?.(`Artist queue cancelled (${completed})`, 'success');
        setStatus(`Artist queue cancelled · ${completed}`, 'ok');
      } else {
        showToast?.(`Artist queue completed (${completed})`, 'success');
        setStatus(`Artist queue completed · ${completed}`, 'ok');
      }
    } catch (error) {
      console.error('Artist queue failed', error);
      clearPendingArtistRequest();
      artistQueueEntries.length = 0;
      showToast?.(error.message || 'Artist queue failed', 'error');
      setStatus(error.message || 'Artist queue failed', 'error');
    } finally {
      artistQueueRunning = false;
      artistQueueCancelRequested = false;
      artistQueueMode = '';
      activeArtistQueueEntry = null;
      rejectAllArtistResultWaiters(new Error('Artist queue stopped'));
      clearGenerateBusy();
      updateQueuedCards();
      updateArtistActionAvailability();
    }
  }

  function handleResultMeta(meta) {
    if (!meta || !meta.artist_thumb_request) return false;
    const requestId = String(meta.artist_thumb_request_id || '');
    if (pendingResultRequestId && requestId && requestId !== pendingResultRequestId) return false;
    if (!pendingResultRequestId && requestId) pendingResultRequestId = requestId;
    pendingResultMeta = meta;
    const artist = meta.artist_thumb_artist || selected?.artist || 'Artist Thumb';
    if (resultTitleEl && !pendingResultKeepPreview) {
      const size = meta.width && meta.height ? ` · ${meta.width}x${meta.height}` : '';
      resultTitleEl.textContent = `${artist}${size}`;
    }
    if (!pendingResultSuppressPreview && !pendingResultKeepPreview) {
      showResultPreview('Receiving generated image...');
    }
    return true;
  }

  function handleResultBlob(blob) {
    if (!pendingResultMeta || !blob) return false;
    const meta = pendingResultMeta;
    const requestId = String(meta.artist_thumb_request_id || pendingResultRequestId || '');
    const artist = String(meta.artist_thumb_artist || selected?.artist || '').trim();
    const rememberedEntry = rememberArtistResult(artist, blob, meta);
    // 서버가 썸네일로 저장했으면 카드에 바로 반영한다(재시작 후에도 남는 그림).
    if (meta.artist_thumb_saved && meta.artist_thumb_url) {
      applySavedThumbnail(artist, meta.artist_thumb_url);
      // ⚠️ 처음 쓰는 모델이면 FILTER 의 '생성한 모델' 에 그 줄이 아직 없다 — 서버는
      //    이미 알고 있으므로 state 만 다시 받아 목록을 고친다.
      //
      //    판단은 **화면의 select 를 직접 본다.** 목적이 "사용자가 그 모델을 고를 수
      //    있는가" 이기 때문이다(내부 state 와 화면이 어긋나도 화면 쪽이 진실이다).
      //    매번 부르지는 않는다 - `/state` 가 60ms 인데 일괄생성이면 장마다 쌓인다.
      const modelKey = meta.artist_thumb_model ? `model:${meta.artist_thumb_model}` : '';
      const shown = modelKey && filterEl
        && [...filterEl.options].some(option => option.value === modelKey);
      if (modelKey && !shown) fetchState({force: true}).catch(() => {});
    }
    setResultBlobUrl(rememberedEntry?.url || URL.createObjectURL(blob), !rememberedEntry);
    resultPreviewOpen = true;
    applyResultPreviewVisibility();
    if (resultTitleEl) resultTitleEl.textContent = titleForResultMemory(rememberedEntry || {artist, meta});
    if (resultImageEl) {
      resultImageEl.src = resultBlobUrl;
      resultImageEl.classList.add('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = true;
    const skipAutoExpandForQueuedNext = artistQueueEntries.length > 0;
    pendingResultMeta = null;
    pendingResultRequestId = '';
    pendingResultSuppressPreview = false;
    pendingResultKeepPreview = false;
    updateResultExpandButton();
    if (pendingResultAutoExpand) {
      pendingResultAutoExpand = false;
      if (artistTabActive && !skipAutoExpandForQueuedNext) setResultExpanded(true);
    }
    resolveArtistResultWaiter(requestId, rememberedEntry);
    resumeArtistQueueIfReady();
    return true;
  }

  function setActive(active) {
    const nextActive = Boolean(active);
    if (artistTabActive === nextActive) return;
    artistTabActive = nextActive;
    if (!artistTabActive) setResultExpanded(false);
    applyResultPreviewVisibility();
  }

  function stopDownloadPolling() {
    if (downloadTimer) {
      clearInterval(downloadTimer);
      downloadTimer = null;
    }
  }

  function startDownloadPolling(mode) {
    stopDownloadPolling();
    downloadTimer = setInterval(async () => {
      try {
        await fetchState({force: true});
        const download = state?.download || {};
        updateDownloadUi();
        if (download.mode === mode) {
          setStatus(download.message || '', download.error ? 'error' : (download.active ? 'busy' : 'ok'));
        }
        if (!download.active) {
          stopDownloadPolling();
          if (!download.error && download.mode === mode) {
            await fetchState({force: true});
            await loadPage(0, {anchor: 'top'});
          }
        }
      } catch (error) {
        stopDownloadPolling();
        showToast?.(error.message || 'Download status failed', 'error');
      }
    }, 900);
  }

  async function downloadSelectedMode() {
    const mode = currentMode();
    const info = currentModeInfo();
    if (!mode || !info) {
      showToast?.('다운로드할 모드를 선택하세요.', 'error');
      return;
    }
    if (info.available && !info.needs_update) {
      showToast?.('이미 다운로드된 모드입니다.', 'success');
      return;
    }
    try {
      downloadBtn.disabled = true;
      downloadBtn.textContent = 'Starting...';
      const download = await postJson('/api/artist-thumb/download', {mode});
      state = {...(state || {}), download};
      updateDownloadUi();
      setStatus(download.message || '다운로드를 시작했습니다.', 'busy');
      startDownloadPolling(mode);
    } catch (error) {
      updateDownloadUi();
      showToast?.(error.message || 'Download failed', 'error');
      setStatus(error.message || 'Download failed', 'error');
    }
  }

  async function openThumbnailFolder() {
    if (!openFolderBtn || openFolderBtn.disabled) return;
    openFolderBtn.disabled = true;
    try {
      const response = await fetch('/api/artist-thumb/open-folder', {method: 'POST'});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      showToast?.(`NAIA 실행 PC에서 폴더를 열었습니다: ${data.path}`, 'success');
    } catch (error) {
      showToast?.(error.message || '폴더를 열지 못했습니다.', 'error');
    } finally {
      openFolderBtn.disabled = false;
    }
  }

  function bind() {
    openFolderBtn?.addEventListener('click', openThumbnailFolder);
    modeEl?.addEventListener('change', () => loadPage(0, {anchor: 'top'}));
    filterEl?.addEventListener('change', () => loadPage(0, {anchor: 'top'}));
    searchEl?.addEventListener('input', () => {
      if (searchEl._artistTimer) clearTimeout(searchEl._artistTimer);
      searchEl._artistTimer = setTimeout(() => loadPage(0, {anchor: 'top'}), 180);
    });
    prevBtn?.addEventListener('click', () => loadPage(Math.max(0, currentPage - 1), {anchor: 'bottom'}));
    nextBtn?.addEventListener('click', () => loadPage(Math.min(totalPages - 1, currentPage + 1), {anchor: 'top'}));
    gotoBtn?.addEventListener('click', gotoPage);
    gotoInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        gotoPage();
      }
    });
    downloadBtn?.addEventListener('click', downloadSelectedMode);
    selectBtn?.addEventListener('click', toggleSelectionMode);
    batchBtn?.addEventListener('click', toggleBatchMenu);
    batchMenu?.addEventListener('click', event => {
      const button = event.target.closest('[data-artist-batch-mode]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      startArtistQueue(button.dataset.artistBatchMode || 'fixed');
    });
    document.addEventListener('click', event => {
      if (batchMenu?.hidden) return;
      if (event.target.closest('.artist-thumb-bulk-wrap')) return;
      closeBatchMenu();
    });
    randomBtn?.addEventListener('click', loadRandomArtists);
    modeEl?.addEventListener('change', syncRemoteSelectTitles);
    filterEl?.addEventListener('change', syncRemoteSelectTitles);
    remoteBtn?.addEventListener('click', () => setRemote(!remoteOnboarded));
    mixBtn.addEventListener('click', () => { void setMixMode(!mixOn); });
    gridEl?.addEventListener('wheel', onGridWheel, {passive: false});
    gridEl?.addEventListener('click', event => {
      const card = event.target.closest('.artist-thumb-card[data-artist]');
      if (!card || !gridEl.contains(card)) return;
      const item = itemFromCard(card);
      if (!item) return;
      if (selectionMode) {
        toggleBatchSelection(item);
        return;
      }
      selectArtist(item);
    });
    // ── 방향키로 아티스트 고르기 (사용자 지정 2026-08-29) ────────────────────
    //
    // 히스토리 뷰어와 **같은 손버릇**: 좌우는 한 칸, 상하는 **한 줄**.
    // 넷 다 ±1 로 두면 다열 목록에서 손이 예측한 대로 안 움직인다(그쪽 주석 참조).
    // ⚠️ 마지막 줄에서 아래로 가면 **다음 페이지**로 넘어간다(사용자 지정).
    //    이미 있는 `loadAdjacentPage` 를 쓴다 - 휠 넘김과 같은 길이라 잠금도 공유된다.
    function gridColumnCount() {
      if (!gridEl) return 1;
      try {
        const template = String(getComputedStyle(gridEl).gridTemplateColumns || '').trim();
        if (!template || template === 'none') return 1;
        return Math.max(1, template.split(/\s+/).length);
      } catch (_) {
        return 1;
      }
    }

    function visibleCards() {
      return Array.from(gridEl?.querySelectorAll('.artist-thumb-card[data-artist]') || []);
    }

    async function moveSelection(delta) {
      const cards = visibleCards();
      if (!cards.length) return;
      const key = selected ? String(selected.artist || '') : '';
      let at = cards.findIndex(c => c.dataset.artist === key);
      if (at < 0) {
        // 고른 것이 없으면 방향에 따라 양 끝에서 시작한다.
        const first = itemFromCard(delta >= 0 ? cards[0] : cards[cards.length - 1]);
        if (first) selectArtist(first);
        return;
      }
      const next = at + delta;
      if (next >= 0 && next < cards.length) {
        const item = itemFromCard(cards[next]);
        if (item) {
          selectArtist(item);
          cards[next].scrollIntoView({block: 'nearest'});
        }
        return;
      }
      // 목록 밖으로 나갔다 - 페이지를 넘긴다. 넘긴 뒤 들어온 자리에서 이어 고른다.
      const direction = next < 0 ? -1 : 1;
      if (direction > 0 ? currentPage >= totalPages - 1 : currentPage <= 0) return;
      await loadAdjacentPage(direction);
      const after = visibleCards();
      if (!after.length) return;
      const landing = direction > 0 ? after[0] : after[after.length - 1];
      const item = itemFromCard(landing);
      if (item) {
        selectArtist(item);
        landing.scrollIntoView({block: 'nearest'});
      }
    }

    document.addEventListener('keydown', event => {
      // 이 탭이 보이지 않으면 방향키를 가로채지 않는다 - 다른 화면의 손버릇을 뺏는다.
      const pane = document.getElementById('rightTabArtists');
      if (!pane || pane.hidden || pane.offsetParent === null) return;
      if (event.altKey || event.metaKey) return;
      // 입력 중에는 손대지 않는다 - 검색창·프롬프트 칸에서 화살표는 캐럿 이동이다.
      const el = document.activeElement;
      const tag = el ? String(el.tagName || '').toUpperCase() : '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      if (selectionMode) return;

      const columns = gridColumnCount();
      if (event.key === 'ArrowLeft') { event.preventDefault(); void moveSelection(-1); }
      else if (event.key === 'ArrowRight') { event.preventDefault(); void moveSelection(1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); void moveSelection(-columns); }
      else if (event.key === 'ArrowDown') { event.preventDefault(); void moveSelection(columns); }
      else if (event.key === 'Enter') {
        // ⚠️ 사용자 지정: 여기서는 **Ctrl+Enter 가 with random** 이다. 메인 화면의
        //    관례(Ctrl+Enter = 그냥 생성)와 반대지만, 이 화면의 주 동작이 그쪽이다.
        event.preventDefault();
        if (event.ctrlKey) void generateWithRandomPrompt();
        else void generateSelected();
      }
    });

    // 격자 카드는 끌기 원본이다. 4px 를 넘기 전에는 아무 일도 없어 클릭(선택)은 그대로다.
    gridEl?.addEventListener('pointerdown', event => {
      const card = event.target.closest('.artist-thumb-card[data-artist]');
      if (!card || !gridEl.contains(card)) return;
      const item = itemFromCard(card);
      if (!item?.artist) return;
      void ensureGroups().then(({broker}) => {
        // 모듈을 처음 불러오는 사이에 손을 뗐으면 끌기를 걸지 않는다.
        if (!(event.buttons & 1)) return;
        broker.arm(event, {kind: 'artist', artist: item.artist, weight: 1,
                           image: item.image_url || '', label: item.artist},
                   {onStart: () => getRemoteController?.()?.hideZoom?.()});
      });
    });

    gridEl?.addEventListener('contextmenu', event => {
      const card = event.target.closest('.artist-thumb-card[data-artist]');
      if (!card || !gridEl.contains(card)) return;
      const item = itemFromCard(card);
      if (item) openContextMenu(event, item);
    });
    favoriteBtn?.addEventListener('click', toggleFavorite);
    banBtn?.addEventListener('click', banSelected);
    copyBtn?.addEventListener('click', copySelected);
    insertBtn?.addEventListener('click', insertSelected);
    generateBtn?.addEventListener('click', generateSelected);
    randomGenerateBtn?.addEventListener('click', () => {
      // 생성을 눌렀으면 이제 그림을 볼 차례다 - 판은 스스로 비켜 준다(사용자 지정).
      getRemoteController?.()?.foldSideNow?.();
      generateWithRandomPrompt();
    });
    resultExpandBtn?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      setResultExpanded(true);
    });
    resultCloseBtn?.addEventListener('click', closeResultPreview);
    prefixEl?.addEventListener('input', scheduleSaveOptions);
    postfixEl?.addEventListener('input', scheduleSaveOptions);
    // ⚠️ 버튼이 <label> 안에 있다 — preventDefault 없으면 라벨이 클릭을
    //    텍스트에리어로 넘겨 커서가 뒤늦게 들어간다.
    prefixDefaultBtn?.addEventListener('click', event => {
      event.preventDefault();
      applyRecommended(prefixEl, RECOMMENDED_PREFIX);
    });
    postfixDefaultBtn?.addEventListener('click', event => {
      event.preventDefault();
      applyRecommended(postfixEl, RECOMMENDED_POSTFIX);
    });
    weightSlider?.addEventListener('input', event => setArtistWeight(event.target.value));
    weightInput?.addEventListener('input', event => setArtistWeight(event.target.value));
    // 커밋 시점(blur/Enter)에만 정규화 표시를 반영 — 입력 중 캐럿 점프 방지(위 가드와 짝).
    weightInput?.addEventListener('change', event => setArtistWeight(event.target.value));
  }

  async function load(options = {}) {
    try {
      await fetchState(options);
      if (hasLoadedList && !options.force) {
        renderState();
        updatePager();
        syncPromptFormat();
        return;
      }
      await loadPage(currentPage);
    } catch (error) {
      console.error('Artist Thumb load failed', error);
    }
  }

  // ── 리모컨(사용자 지정 2026-09-14) ─────────────────────────────────────
  //  Artist Thumbnail 로 랜덤 그림을 계속 뽑아 보려면 탭 하나를 포기해야 했다 - 그림은
  //  Result 탭, 다음 작가는 Artists 탭. 여기 조각만 떠 있는 창으로 옮겨 둘 다 본다.
  //  ⚠️ **베끼지 않고 진짜 노드를 옮긴다.** 이 모듈이 요소를 id 로 한 번만 잡아 두고 그
  //     참조로만 일하기 때문에 자리를 옮겨도 배선/렌더링이 그대로 산다. 베끼면 라벨과
  //     비활성 상태를 두 곳에서 관리하게 된다.
  const REMOTE_KEY = 'artists';

  /** 향상된 `<select>` 는 네이티브(숨김) + `.custom-select` 껍데기 **두 조각**이다.
   *  둘을 같이 옮겨야 한다 - 껍데기만 옮기면 값이 안 따라오고, 네이티브만 옮기면
   *  화면에 아무것도 안 보인다(네이티브는 `display:none`). 메뉴는 이미 body 에 산다. */
  function selectPair(select) {
    if (!select) return [];
    const shell = select.nextElementSibling?.classList?.contains('custom-select')
      ? select.nextElementSibling : null;
    return shell ? [select, shell] : [select];
  }

  function remoteRows() {
    const weight = weightSlider?.closest('.artist-thumb-weight-control') || null;
    const goto = gotoInput?.closest('.artist-thumb-goto') || null;
    const modePair = selectPair(modeEl);
    const filterPair = selectPair(filterEl);
    return [
      // 남는 높이를 다 먹는 줄. 관찰이 본론이라 격자가 가장 크다.
      {nodes: [gridEl], fill: true},
      // 페이지 - 앞/뒤 + 몇 쪽인지 + 바로 뛰기.
      {
        className: 'rctl-pager',
        nodes: [
          {node: prevBtn, tag: 'prev'},
          {node: pageLabel, tag: 'page'},
          {node: nextBtn, tag: 'next'},
          // Next 와 Go 사이의 빈 자리(사용자 지정). 리모컨에서만 만든 단추라 원래
          // 자리가 없다 - `lift` 가 부모 없는 노드는 그냥 지나가고 창과 함께 사라진다.
          {node: mixBtn, tag: 'mix'},
          {node: goto, tag: 'goto'},
        ],
      },
      // 1 : 1 : 2 - [모드][필터][Get Random Artist](사용자 지정).
      {
        className: 'rctl-source',
        nodes: [
          ...modePair.map(node => ({node, tag: 'mode'})),
          ...filterPair.map(node => ({node, tag: 'filter'})),
          {node: randomBtn, tag: 'rnd'},
        ],
      },
      // 고른 작가 한 줄 - **이름 칸은 가중치가 반영된 프롬프트 그 자체**다(사용자 지정).
      // 아래에 썸네일을 또 보여 주는 것은 격자와 겹치는 중복이라 뺐다.
      {
        className: 'rctl-artist-head',
        nodes: [
          {node: positiveEl, tag: 'name'},
          {node: weight, tag: 'weight'},
        ],
      },
      {nodes: [favoriteBtn, banBtn], className: 'rctl-row-split'},
      {nodes: [randomGenerateBtn], className: 'rctl-row-split'},
    ];
  }

  /** 모드/필터는 좁은 칸이라 글자가 잘린다 - 지금 보고 있는 것을 툴팁으로 준다. */
  function syncRemoteSelectTitles() {
    if (!remoteOnboarded) return;
    const label = (select, prefix) => {
      if (!select) return;
      const text = select.options?.[select.selectedIndex]?.textContent?.trim() || '';
      const title = text ? `${prefix}: ${text}` : prefix;
      select.title = title;
      const shell = select.nextElementSibling?.classList?.contains('custom-select')
        ? select.nextElementSibling : null;
      if (shell) shell.title = title;
    };
    label(modeEl, '썸네일 모드');
    label(filterEl, '필터');
  }

  /** 믹스 큐가 조립한 글을 ARTIST PROMPT 칸으로 보낸다(사용자 지정 - 그 칸이
   *  Generate 와 Generate with Random Prompt 가 쓰는 자리다). */
  function applyMixComposition(text, groups) {
    mixAnchorGroups = groups && typeof groups === 'object' ? groups : {};
    if (positiveEl) {
      positiveEl.value = text;
      positiveAutoValue = text;
    }
    // 접혀 있는 동안 그림 위에 얹을 줄들 - 켜진 블럭만, 큐에 보이는 그대로.
    // 가중치는 뺀다(접힘은 훑어보기다 - 9px 로 `0.9::artist:x ::` 는 잡음이다).
    const lines = (mixQueue?.snapshot() || [])
      .filter(b => b.enabled && String(b.artist || '').trim())
      .map(b => (b.withPrefix ? `artist:${b.artist}` : b.artist));
    getRemoteController?.()?.setSideSummary?.(lines);
  }

  // ── 아티스트 그룹 ──────────────────────────────────────────────────────
  //  ⚠️ 세 모듈은 **다른 곳과 같은 주소**로 불러야 한다(중개자가 둘로 뜨면 받는 쪽이
  //     서로 안 보인다). 계약 시험이 주소를 대조한다.
  async function ensureGroups() {
    if (groupsApi) return groupsApi;
    const [{createArtistGroupsStore}, {createArtistGroupWindow}, {dragBrokerFor}] = await Promise.all([
      import('./artistGroupsStore.mjs?v=20260917-grp1'),
      import('./artistGroupWindow.mjs?v=20260917-grp1'),
      import('./dragBroker.mjs?v=20260917-grp1'),
    ]);
    const store = createArtistGroupsStore({fetch});
    groupsApi = {store, createWindow: createArtistGroupWindow, broker: dragBrokerFor(document)};
    try { await store.load(); } catch (error) {
      showToast?.(`그룹 목록을 읽지 못했습니다 — ${error.message}`, 'error');
    }
    return groupsApi;
  }

  /** 이름 목록 -> {이름: {image_url, known}}. 격자와 **같은 그림 규칙**(서버 한 곳). */
  async function describeArtists(names) {
    const data = await postJson('/api/artist-thumb/describe', {mode: currentMode(), artists: names});
    const out = {};
    for (const item of data?.items || []) out[item.artist] = item;
    return out;
  }

  /** 그룹 창의 카드를 누름 = 격자에서 고른 것과 같다. */
  function pickFromGroup(artist) {
    const card = gridEl?.querySelector(`.artist-thumb-card[data-artist="${CSS.escape(artist)}"]`);
    const item = card ? itemFromCard(card) : {artist, image_url: '', weight: '', favorite: false, banned: false};
    selectArtist(item);
  }

  /** 그룹 -> 믹스 큐. 믹스 모드가 꺼져 있으면 먼저 켠다(큐가 곧 받을 곳이다). */
  async function sendToQueue(items) {
    if (!mixOn) await setMixMode(true);
    if (!mixQueue) { showToast?.('믹스 큐를 열지 못했습니다.', 'error'); return; }
    const n = mixQueue.insertArtists(items);
    if (n) showToast?.(`${n}명을 큐에 넣었습니다.`, 'info');
  }

  async function openGroupWindow(groupId) {
    const {store, createWindow} = await ensureGroups();
    const open = groupWindows.get(groupId);
    if (open) { open.focus(); return open; }
    if (!store.get(groupId)) { showToast?.('그룹을 찾지 못했습니다.', 'error'); return null; }
    const remote = getRemoteController?.();
    const win = createWindow({
      document,
      store,
      groupId,
      escHtml,
      showToast: (msg, kind) => showToast?.(msg, kind),
      describe: describeArtists,
      onPick: pickFromGroup,
      onSendToQueue: items => { void sendToQueue(items); },
      onDragStart: () => remote?.hideZoom?.(),
      onClosed: info => {
        groupWindows.delete(groupId);
        if (lastTempGroupId === groupId) lastTempGroupId = '';
        if (info?.reopen) void openGroupWindow(info.reopen);
      },
    });
    groupWindows.set(groupId, win);
    if (store.isTemp(groupId)) lastTempGroupId = groupId;
    return win;
  }

  async function newTempWindow(items = []) {
    const {store} = await ensureGroups();
    const group = store.createTemp(items);
    return openGroupWindow(group.id);
  }

  /** 우클릭 [임시 창에 올리기]: 열린 임시 창이 있으면 거기, 없으면 새로. */
  async function putInTempWindow(item) {
    const {store} = await ensureGroups();
    const payload = [{artist: item.artist}];
    if (lastTempGroupId && store.get(lastTempGroupId) && groupWindows.has(lastTempGroupId)) {
      await store.add(lastTempGroupId, payload);
      groupWindows.get(lastTempGroupId).focus();
      return;
    }
    await newTempWindow(payload);
  }

  async function addToGroup(groupId, item) {
    const {store} = await ensureGroups();
    try {
      const result = await store.add(groupId, [{artist: item.artist}]);
      const name = store.get(groupId)?.name || '그룹';
      showToast?.(result.added ? `'${name}' 에 넣었습니다.` : `이미 '${name}' 에 있습니다.`, 'info');
    } catch (error) {
      showToast?.(`그룹에 넣지 못했습니다 — ${error.message}`, 'error');
    }
  }

  async function createGroupWith(name, item) {
    const {store} = await ensureGroups();
    try {
      const group = await store.create(name, item ? [{artist: item.artist}] : []);
      showToast?.(`'${group.name}' 그룹을 만들었습니다.`, 'info');
      return group;
    } catch (error) {
      showToast?.(error.message, 'error');
      return null;
    }
  }

  function groupMenuHtml(withTempAdd) {
    const store = groupsApi?.store;
    const saved = store ? store.all().filter(g => !store.isTemp(g.id)) : [];
    const rows = saved.map(g => `
        <button type="button" class="result-context-item artist-thumb-group-item"
                data-action="group-pick" data-group-id="${escHtml(g.id)}" role="menuitem">
          <span>${escHtml(g.name)}</span><span class="artist-thumb-group-count">${(g.items || []).length}</span>
        </button>`).join('');
    return `
      <div class="result-context-group artist-thumb-group-section">
        ${withTempAdd ? `<button type="button" class="result-context-item" data-action="temp-add" role="menuitem">
          <span>임시 창에 올리기</span></button>` : ''}
        <div class="artist-thumb-group-label">${withTempAdd ? '그룹에 등록' : '그룹 창 열기'}</div>
        <div class="artist-thumb-group-list">${rows || '<div class="artist-thumb-group-empty">아직 그룹이 없습니다</div>'}</div>
        <button type="button" class="result-context-item" data-action="group-new" role="menuitem">
          <span>+ 새 그룹…</span></button>
        <form class="artist-thumb-group-new" hidden>
          <input type="text" maxlength="40" spellcheck="false" placeholder="그룹 이름">
          <button type="submit">만들기</button>
        </form>
      </div>`;
  }

  /** 메뉴 안의 [+ 새 그룹…] - 메뉴를 닫지 않고 이름 칸을 편다. */
  function revealNewGroupForm(menu, onName) {
    const form = menu.querySelector('.artist-thumb-group-new');
    if (!form) return;
    form.hidden = false;
    const input = form.querySelector('input');
    input.focus();
    input.addEventListener('keydown', event => {
      event.stopPropagation();               // Ctrl+Enter 등 전역 단축키가 새지 않게
      if (event.key === 'Escape') closeContextMenu();
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      closeContextMenu();
      void onName(name);
    }, {once: true});
  }

  /** 믹스 판 머리의 [그룹] - 그룹 창을 열거나 새로 만든다. */
  async function openGroupsLauncher(anchor) {
    await ensureGroups();
    closeContextMenu();
    const {store} = groupsApi;
    const temps = store.all().filter(g => store.isTemp(g.id));
    const tempRows = temps.map((g, i) => `
        <button type="button" class="result-context-item" data-action="group-pick" data-group-id="${escHtml(g.id)}" role="menuitem">
          <span>임시 창 ${i + 1}</span><span class="artist-thumb-group-count">${(g.items || []).length}</span>
        </button>`).join('');
    const menu = document.createElement('div');
    menu.className = 'result-context-menu artist-thumb-context-menu artist-thumb-groups-launcher open';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `
      <div class="result-context-group">
        <button type="button" class="result-context-item" data-action="temp-new" role="menuitem">
          <span>+ 임시 창</span></button>
        ${tempRows}
      </div>
      ${groupMenuHtml(false)}`;
    contextMenuEl = menu;
    menu.addEventListener('contextmenu', e => e.preventDefault());
    menu.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const action = button.dataset.action;
      if (action === 'group-new') {
        revealNewGroupForm(menu, async name => {
          const group = await createGroupWith(name, null);
          if (group) void openGroupWindow(group.id);
        });
        return;
      }
      closeContextMenu();
      if (action === 'temp-new') void newTempWindow([]);
      else if (action === 'group-pick') void openGroupWindow(button.dataset.groupId);
    });
    document.body.appendChild(menu);
    const r = anchor?.getBoundingClientRect?.() || {left: 100, bottom: 100};
    positionContextMenu(menu, r.left, r.bottom + 4);
    document.addEventListener('pointerdown', onContextMenuPointerDown, true);
    document.addEventListener('keydown', onContextMenuKeyDown, true);
    window.addEventListener('blur', closeContextMenu);
    window.addEventListener('resize', closeContextMenu);
  }

  // ── 앵커 <-> prefix/postfix 글 ────────────────────────────────────────
  //  큐는 글을 안 갖고 있고, PE 는 큐를 모른다. 둘을 아는 곳은 여기뿐이다.
  const PE_ANCHOR_FIELDS = ['pre_prompt', 'post_prompt'];

  function peText(key) {
    try { return String(getPeField?.(key) ?? ''); } catch (_) { return ''; }
  }

  function peTextHasAnchor(id) {
    return PE_ANCHOR_FIELDS.some(key => anchorsApi?.hasAnchorId(peText(key), id));
  }

  function putAnchorInPrefix(id) {
    if (!anchorsApi || typeof setPeField !== 'function') return;
    const next = anchorsApi.appendAnchor(peText('pre_prompt'), id);
    setPeField('pre_prompt', next, getPePreset?.() ?? '');
    peQuick?.sync();
  }

  function dropAnchorFromText(id) {
    if (!anchorsApi || typeof setPeField !== 'function') return;
    for (const key of PE_ANCHOR_FIELDS) {
      const before = peText(key);
      if (!anchorsApi.hasAnchorId(before, id)) continue;
      setPeField(key, anchorsApi.removeAnchor(before, id), getPePreset?.() ?? '');
    }
    peQuick?.sync();
  }

  let anchorsApi = null;

  async function ensureMixQueue() {
    if (mixQueue) return mixQueue;
    const remote = getRemoteController?.();
    if (!remote) return null;
    if (!anchorsApi) anchorsApi = await import('./artistAnchors.mjs?v=20260915-anchor1');
    await ensureGroups();
    const {createMixQueuePanel} = await import('./mixQueuePanel.mjs?v=20260917-wheel1');
    mixQueue = createMixQueuePanel({
      document,
      escHtml,
      showToast,
      formatToken: (artist, weight, options) => formatArtistToken(artist, weight, options),
      onChange: applyMixComposition,
      // 블럭에 올린 확대 보기는 **믹스 판 옆**에 뜬다(격자 칸은 창 옆 - 판을 덮는다).
      onHoverBlock: (element, block) => {
        const src = mixThumbUrl(block);
        if (!src) { remote.hideZoom?.(); return; }
        remote.showZoomBeside?.(element, {src, title: block.artist, note: ''}, remote.sideRect?.());
      },
      onLeaveBlock: () => remote.hideZoom?.(),
      // 큐 안에서 임시 블럭의 가중치가 바뀌면 메인 손잡이도 따라간다(사용자 지정).
      onTempWeight: value => paintWeightControls(value),
      onPin: on => remote.setSidePinned?.(on),
      // 표식이 prefix/postfix 에 살아 있는가. 글의 주인은 PE 라 여기서 물어 준다.
      hasAnchorIn: id => peTextHasAnchor(id),
      // 추가/복원 = prefix **맨 뒤**에 표식을 넣는다(사용자 지정).
      onAnchorAdd: id => putAnchorInPrefix(id),
      onAnchorRemove: id => dropAnchorFromText(id),
      onGroupsMenu: anchor => { void openGroupsLauncher(anchor); },
      onDragStart: () => remote.hideZoom?.(),
    });
    // 믹스 레이아웃 **아래**에 PE 빠른 수정(사용자 지정). 값을 만들 권한은 없다.
    if (!peQuick && typeof getPeField === 'function' && typeof setPeField === 'function') {
      const {createPeQuickEdit} = await import('./peQuickEdit.mjs?v=20260915-peq1');
      peQuick = createPeQuickEdit({
        document, escHtml, showToast,
        getField: key => getPeField(key),
        setField: (key, text, seenPreset) => setPeField(key, text, seenPreset),
        getPreset: () => getPePreset(),
        requestState: () => requestPeState(),
      });
    }
    remote.mountSide?.(mixQueue.el, peQuick?.el);
    return mixQueue;
  }

  /** 블럭의 그림 - 격자에 그 카드가 떠 있으면 그 주소를 그대로 쓴다. */
  function mixThumbUrl(block) {
    if (block?.image) return block.image;
    const card = gridEl?.querySelector(`.artist-thumb-card[data-artist="${CSS.escape(block?.artist || '')}"]`);
    return card?.querySelector('img')?.getAttribute('src') || '';
  }

  async function setMixMode(next) {
    const want = Boolean(next);
    const remote = getRemoteController?.();
    if (want && !remote) { showToast('리모컨에서만 쓸 수 있습니다.', 'error'); return; }
    const queue = want ? await ensureMixQueue() : mixQueue;
    if (want && !queue) { showToast('믹스 큐를 열지 못했습니다.', 'error'); return; }
    mixOn = want;
    mixBtn.textContent = `믹스 모드 ${mixOn ? 'ON' : 'OFF'}`;
    mixBtn.classList.toggle('is-on', mixOn);
    mixBtn.setAttribute('aria-pressed', mixOn ? 'true' : 'false');
    // 이 칸이 여러 명을 담게 되니 줄바꿈을 허용한다(옷은 `.is-mix` 가 쥔다).
    mixBtn.closest('.dragpanel')?.classList.toggle('is-mix', mixOn);
    queue?.setOpen(mixOn);
    // 펼친 채 닫으면 마지막 편집이 날아간다 - 칸을 벗어난 것과 같이 친다.
    if (!mixOn) peQuick?.flush();
    remote?.showSide?.(mixOn);
    if (mixOn) peQuick?.sync();
    if (mixOn) {
      if (selected) queue.setTempArtist(selected.artist, selected.image_url || '');
      applyMixComposition(queue.compose());
    } else if (selected) {
      // 큐를 닫으면 칸의 주인이 다시 '고른 작가 하나' 로 돌아온다.
      syncPromptFormat();
    }
  }

  /** 리모컨에서는 카드가 112px 까지 줄어든다 - 마우스를 올리면 창 옆에 크게 띄운다. */
  function remoteHoverPreview() {
    return {
      selector: '.artist-thumb-card[data-artist]',
      resolve: card => {
        const src = card.querySelector('img')?.getAttribute('src') || '';
        if (!src) return null;   // 'No Image' 칸은 띄울 것이 없다
        return {
          src,
          title: card.dataset.artist || '',
          note: card.querySelector('.artist-thumb-card-weight')?.textContent || '',
        };
      },
    };
  }

  function syncRemoteButton() {
    if (!remoteBtn) return;
    remoteBtn.classList.toggle('is-on', remoteOnboarded);
    remoteBtn.setAttribute('aria-pressed', remoteOnboarded ? 'true' : 'false');
  }

  function setRemote(next, {fromRemote = false} = {}) {
    const want = Boolean(next);
    const remote = getRemoteController?.();
    if (want && !remote) {
      showToast('리모컨을 아직 불러오지 못했습니다.', 'error');
      return;
    }
    if (want === remoteOnboarded) return;
    if (want) {
      const ghosts = new Map([
        [gridEl, '썸네일이 리모컨에 있습니다. [리모컨] 을 다시 누르면 돌아옵니다.'],
        // 이 둘은 3열 grid 안이라 표식을 안 남기면 남은 칸이 밀려 머리줄이 뒤틀린다.
        [modeEl, {text: '', slim: true}],
        [filterEl, {text: '', slim: true}],
      ]);
      const ok = remote.onboard(REMOTE_KEY, {
        title: 'Artist Thumbnail',
        rows: remoteRows(),
        hoverPreview: remoteHoverPreview(),
        ghosts,
        // 리모컨을 [x] 로 닫으면 조각이 제자리로 돌아온다 - 토글도 같이 꺼져야 한다.
        onRelease: () => setRemote(false, {fromRemote: true}),
      });
      if (!ok) {
        showToast('리모컨으로 옮길 항목을 찾지 못했습니다.', 'error');
        return;
      }
      remoteOnboarded = true;
      syncRemoteSelectTitles();
      // 첫 끌기가 모듈 로딩에 먹히지 않게 미리 올린다(카드를 잡는 순간엔 이미 준비돼 있다).
      void ensureGroups();
      // 조각을 실제로 옮긴 뒤에만 옮겨 간다. 끌 때는 되돌리지 않는다 - 그때쯤이면
      // 사용자가 다른 것을 보고 있고, 화면을 낚아채는 쪽이 더 나쁘다.
      showResultTab();
    } else {
      remoteOnboarded = false;
      // 믹스 판은 리모컨에 붙어 있다 - 창이 내려가면 같이 내린다.
      if (mixOn) void setMixMode(false);
      if (!fromRemote) remote?.offboard?.(REMOTE_KEY);
    }
    syncRemoteButton();
  }

  bind();

  return {
    load,
    reload: () => load({force: true}),
    setActive,
    syncPromptFormat,
    /** 백엔드(NAI/WEBUI/COMFYUI)가 바뀌면 '생성한 모델' 필터와 카드 그림이 그 모드
     *  기준으로 다시 갈려야 한다. 예전에는 프롬프트 표기만 고쳐서, WEBUI 로 바꿔도
     *  NAI 의 모델 목록·썸네일이 그대로 남았다(Codex #5).
     *  ⚠️ 탭이 안 떠 있으면 목록 재조회는 하지 않는다 - 안 보는 화면 때문에 95k 행을
     *     훑을 이유가 없다. 다음에 열 때 `onOpen` 이 받아 온다. */
    async onApiModeChange() {
      syncPromptFormat();
      if (!state) return;
      try {
        await fetchState({force: true});
        if (gridVisible()) await loadPage(currentPage, {anchor: 'top'});
      } catch (_) { /* 상태 갱신 실패가 모드 전환을 막으면 안 된다 */ }
    },
    handleResultMeta,
    handleResultBlob,
    /** PE 상태가 새로 오면(프리셋 전환 등) 빠른 수정 칸도 따라가야 한다.
     *  ⚠️ 치는 중인 칸은 건드리지 않는다 - 그 판정은 패널이 한다. */
    syncPromptEngineering: () => {
      peQuick?.sync();
      // ⚠️ 표식을 옮기는 동안 잘라내기와 붙여넣기 사이에서 잠깐 사라진다 -
      //    **회복도 추적**해야 해서 올 때마다 다시 잰다(사용자 지정).
      mixQueue?.recheckAnchors();
    },
  };
}
