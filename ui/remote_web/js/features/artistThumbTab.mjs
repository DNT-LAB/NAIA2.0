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
  isComfyUiAnimaMode = () => false,
  isAnimaArtistMode = null,
}) {
  const modeEl = document.getElementById('artistThumbMode');
  const filterEl = document.getElementById('artistThumbFilter');
  const searchEl = document.getElementById('artistThumbSearch');
  const summaryEl = document.getElementById('artistThumbSummary');
  const statusEl = document.getElementById('artistThumbStatus');
  const gridEl = document.getElementById('artistThumbGrid');
  const prevBtn = document.getElementById('artistThumbPrevBtn');
  const nextBtn = document.getElementById('artistThumbNextBtn');
  const downloadBtn = document.getElementById('artistThumbDownloadBtn');
  const randomBtn = document.getElementById('artistThumbRandomBtn');
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

  function formatArtistPrompt(artist) {
    const name = String(artist || '').trim();
    if (!name) return '';
    try {
      const weight = artistWeightValue();
      if (weight == null) return baseArtistPrompt(name);
      const formattedWeight = formatArtistWeight(weight);
      if (!formattedWeight) return baseArtistPrompt(name);
      if (currentGenerationMode() === 'NAI') return `${formattedWeight}::artist:${name} ::`;
      const escaped = escapeStableDiffusionArtistName(name);
      if (usesAnimaArtistSyntax()) {
        return `(@${escaped}:${formattedWeight})`;
      }
      return `(${escaped}:${formattedWeight})`;
    } catch (_) {
      return baseArtistPrompt(name);
    }
  }

  function syncPromptFormat() {
    syncOptionsForCurrentMode();
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
    [modeEl, filterEl, searchEl, downloadBtn, selectBtn, randomBtn, prevBtn, nextBtn, gotoBtn, gotoInput].forEach(control => {
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
    setStatus(`${statusPrefix} · ${currentListFilterName || '전체 목록'} · ${Number(currentListTotal || 0).toLocaleString()} artists`, 'ok');
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
      filterEl.innerHTML = filters.map(filter => `
        <option value="${escHtml(filter.key)}">${escHtml(filter.name)} · ${Number(filter.count || 0).toLocaleString()}</option>
      `).join('');
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
        <button type="button" class="artist-thumb-card${active}${favorite}${remembered}${queued}${selectable}${batchSelected}${batchDim}" data-artist="${escHtml(item.artist)}" data-weight="${escHtml(String(item.weight || 0))}">
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
    };
  }

  function updatePager() {
    if (pageLabel) pageLabel.textContent = `${currentPage + 1} / ${totalPages}`;
    if (prevBtn) prevBtn.disabled = artistQueueRunning || currentPage <= 0;
    if (nextBtn) nextBtn.disabled = artistQueueRunning || currentPage >= totalPages - 1;
    if (gotoInput) {
      gotoInput.max = String(totalPages);
      gotoInput.placeholder = String(currentPage + 1);
      gotoInput.value = '';
      gotoInput.disabled = artistQueueRunning;
    }
    if (gotoBtn) gotoBtn.disabled = artistQueueRunning || totalPages <= 1;
  }

  function scrollGrid(anchor = 'top') {
    if (!gridEl) return;
    requestAnimationFrame(() => {
      if (!gridEl) return;
      gridEl.scrollTop = anchor === 'bottom' ? gridEl.scrollHeight : 0;
    });
  }

  async function loadPage(page = 0, options = {}) {
    if (artistQueueRunning && !options.force) return;
    if (selectionMode) setSelectionMode(false);
    await fetchState();
    const requestId = ++listRequestId;
    const mode = currentMode();
    const info = currentModeInfo();
    if (info && (!info.available || info.needs_update)) {
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
      } else if (info.needs_update) {
        setStatus(`${info.label || mode} 데이터 업데이트가 필요합니다. Update 버튼으로 갱신할 수 있습니다.`, 'error');
      } else {
        setStatus(`${info.label || mode} 데이터가 없습니다. Download 버튼으로 받을 수 있습니다.`, 'error');
      }
      return;
    }
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
    if (artistQueueRunning) return;
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
    ].filter(Boolean).join(' · ');
  }

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
    if (positiveEl) {
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
    event.preventDefault();
    event.stopPropagation();
    closeContextMenu();
    contextMenuItem = item;
    const menu = document.createElement('div');
    menu.className = 'result-context-menu artist-thumb-context-menu open';
    menu.setAttribute('role', 'menu');
    contextMenuEl = menu;
    const favoriteLabel = item.favorite ? '관심 해제' : '관심 추가';
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
          <span>제외 추가</span>
        </button>
      </div>
    `;
    menu.addEventListener('contextmenu', e => e.preventDefault());
    menu.addEventListener('click', event => {
      const button = event.target.closest('.result-context-item[data-action]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const action = button.dataset.action || '';
      const targetItem = contextMenuItem;
      closeContextMenu();
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

  function setArtistWeight(value) {
    const raw = Number.parseFloat(String(value ?? '1'));
    const next = Number.isFinite(raw) ? Math.max(0, Math.min(5, raw)) : 1;
    const display = formatArtistWeight(next) || '0';
    if (weightInput) weightInput.value = display;
    if (weightSlider) {
      weightSlider.value = String(Math.max(0, Math.min(2, next)));
    }
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

  async function banItem(item) {
    if (!item) return;
    state = await postJson('/api/artist-thumb/ban', {artist: item.artist, banned: true});
    const artist = item.artist;
    const shouldRemoveFromGrid = currentFilter() !== 'banned';
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
    if (selected?.artist === artist) {
      clearSelectedArtist();
    }
    showToast?.('제외 작가에 추가했습니다.', 'success');
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

  function generationPayloadForItem(item, requestId, overrides = {}) {
    const artistPrompt = formatArtistPrompt(item.artist);
    const activeResolution = currentActiveResolutionOverrides();
    const mergedOverrides = {...activeResolution, ...overrides};
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

  function bind() {
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
    randomGenerateBtn?.addEventListener('click', generateWithRandomPrompt);
    resultExpandBtn?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      setResultExpanded(true);
    });
    resultCloseBtn?.addEventListener('click', closeResultPreview);
    prefixEl?.addEventListener('input', scheduleSaveOptions);
    postfixEl?.addEventListener('input', scheduleSaveOptions);
    weightSlider?.addEventListener('input', event => setArtistWeight(event.target.value));
    weightInput?.addEventListener('input', event => setArtistWeight(event.target.value));
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

  bind();

  return {
    load,
    reload: () => load({force: true}),
    setActive,
    syncPromptFormat,
    handleResultMeta,
    handleResultBlob,
  };
}
