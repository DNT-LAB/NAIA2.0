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
  isComfyUiAnimaMode = () => false,
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
  const GENERATE_LABEL = 'Generate 832 x 1216';
  const RANDOM_GENERATE_LABEL = 'Generate with Random Prompt';
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
  let resultExpanded = false;
  let suppressResultCollapseClick = false;
  let suppressResultCollapseClickTimer = null;
  let contextMenuEl = null;
  let contextMenuItem = null;

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

  function escapeStableDiffusionArtistName(artist) {
    return String(artist || '').replace(/[()]/g, '\\$&');
  }

  function formatArtistPrompt(artist) {
    const name = String(artist || '').trim();
    if (!name) return '';
    const generationMode = currentGenerationMode();
    if (generationMode === 'NAI') return `artist:${name}`;
    const escaped = escapeStableDiffusionArtistName(name);
    if (generationMode === 'COMFYUI' && isComfyUiAnimaMode?.()) return `@${escaped}`;
    return escaped;
  }

  function syncPromptFormat() {
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
    URL.revokeObjectURL(resultBlobUrl);
    resultBlobUrl = '';
  }

  function updateResultExpandButton() {
    if (!resultExpandBtn) return;
    const hasImage = Boolean(resultBlobUrl && resultImageEl?.classList.contains('show'));
    resultExpandBtn.disabled = !hasImage || resultExpanded;
    resultExpandBtn.textContent = resultExpanded ? '확대 중' : '크게 보기';
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
    const canExpand = Boolean(resultPreviewEl && resultBlobUrl && resultImageEl?.classList.contains('show'));
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
    if (resultPreviewEl) resultPreviewEl.hidden = false;
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
      randomGenerateBtn.disabled = false;
      randomGenerateBtn.textContent = RANDOM_GENERATE_LABEL;
    }
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
    randomBtn.disabled = false;
    if (!mode) {
      randomBtn.title = '모드를 선택한 뒤 랜덤 작가를 불러올 수 있습니다.';
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
    const needsDownload = Boolean(info && !info.available);
    downloadBtn.hidden = !needsDownload && !activeForMode;
    downloadBtn.disabled = activeForMode || !mode;
    if (activeForMode) {
      const percent = Number(download.percent || 0);
      downloadBtn.textContent = percent > 0 ? `${percent}%` : 'Downloading...';
    } else {
      downloadBtn.textContent = 'Download';
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
          const suffix = mode.available ? '' : ' (download)';
          const title = mode.available
            ? `${label} · ${Number(mode.size_mb || 0).toLocaleString()} MB`
            : `${label} · data missing`;
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
    if (prefixEl && !prefixEl.dataset.seeded) {
      prefixEl.value = state.options?.prefix || '';
      prefixEl.dataset.seeded = '1';
    }
    if (postfixEl && !postfixEl.dataset.seeded) {
      postfixEl.value = state.options?.postfix || '';
      postfixEl.dataset.seeded = '1';
    }
    setSummary(`${Number(state.artist_count || 0).toLocaleString()} artists`);
    updateDownloadUi();
    updateRandomUi();
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
      const imageHtml = item.image_url
        ? `<img loading="lazy" src="${escHtml(item.image_url)}" alt="${escHtml(item.artist)}">`
        : '<span>No Image</span>';
      return `
        <button type="button" class="artist-thumb-card${active}${favorite}" data-artist="${escHtml(item.artist)}" data-weight="${escHtml(String(item.weight || 0))}">
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
    await fetchState();
    const requestId = ++listRequestId;
    const mode = currentMode();
    const info = currentModeInfo();
    if (info && !info.available) {
      randomViewActive = false;
      currentPage = 0;
      totalPages = 1;
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
    const mode = currentMode();
    const info = currentModeInfo();
    if (!mode) {
      showToast?.('모드를 먼저 선택하세요.', 'error');
      return;
    }
    if (info && !info.available) {
      showToast?.('데이터 다운로드 후 사용할 수 있습니다.', 'error');
      return;
    }
    await loadPage(currentPage, {anchor: 'top', random: true});
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

  function selectArtist(item) {
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
  }

  function selectedPayload() {
    if (!selected) {
      showToast?.('아티스트를 먼저 선택하세요.', 'error');
      return null;
    }
    return selected;
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
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
    menu.innerHTML = `
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

  function scheduleSaveOptions() {
    if (optionsTimer) clearTimeout(optionsTimer);
    optionsTimer = setTimeout(() => {
      optionsTimer = null;
      postJson('/api/artist-thumb/options', {
        prefix: prefixEl?.value || '',
        postfix: postfixEl?.value || '',
      }).catch(error => console.warn('Artist Thumb options save failed', error));
    }, 500);
  }

  async function setFavoriteForItem(item, favorite) {
    if (!item) return;
    state = await postJson('/api/artist-thumb/favorite', {artist: item.artist, favorite});
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

  async function generateSelected() {
    const item = selectedPayload();
    if (!item) return;
    const requestId = makeRequestId();
    const artistPrompt = formatArtistPrompt(item.artist);
    pendingResultAutoExpand = false;
    const payload = {
      request_id: requestId,
      artist: item.artist,
      prefix: prefixEl?.value || '',
      positive: positiveEl?.value || artistPrompt,
      postfix: postfixEl?.value || '',
      negative_prompt: negEdit?.value || '',
      width: 832,
      height: 1216,
    };
    try {
      pendingResultRequestId = requestId;
      pendingResultMeta = null;
      revokeResultBlobUrl();
      pendingResultSuppressPreview = false;
      if (resultTitleEl) resultTitleEl.textContent = `${item.artist} · generating`;
      showResultPreview('Waiting for generated image...');
      setGenerateBusy('manual', 'Requesting...');
      await postJson('/api/artist-thumb/options', {
        prefix: payload.prefix,
        postfix: payload.postfix,
      });
      await postJson('/api/artist-thumb/generate', payload);
      showToast?.('Artist Thumbnail 생성 요청을 보냈습니다.', 'success');
    } catch (error) {
      pendingResultRequestId = '';
      pendingResultMeta = null;
      showResultPreview(error.message || 'Generate failed');
      showToast?.(error.message || 'Generate failed', 'error');
    } finally {
      clearGenerateBusy();
    }
  }

  async function generateWithRandomPrompt() {
    const item = selectedPayload();
    if (!item) return;
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
      });
      const positive = String(randomPrompt.prompt || '');
      if (!positive.trim()) throw new Error('Random prompt is empty');
      const negative = String(randomPrompt.negative_prompt || negEdit?.value || '');
      const width = Number.parseInt(randomPrompt.width, 10) || 832;
      const height = Number.parseInt(randomPrompt.height, 10) || 1216;

      if (resultTitleEl) resultTitleEl.textContent = `${item.artist} · generating`;
      if (randomGenerateBtn) randomGenerateBtn.textContent = 'Requesting...';
      applyGeneratedPromptToEditor(positive, negative);
      await postJson('/api/artist-thumb/generate', {
        request_id: requestId,
        artist: item.artist,
        prefix: '',
        positive,
        postfix: '',
        negative_prompt: negative,
        width,
        height,
      });
      showToast?.('랜덤 프롬프트 생성 요청을 보냈습니다.', 'success');
    } catch (error) {
      pendingResultRequestId = '';
      pendingResultMeta = null;
      pendingResultAutoExpand = false;
      pendingResultSuppressPreview = false;
      if (resultPreviewEl) resultPreviewEl.hidden = true;
      showToast?.(error.message || 'Random prompt generate failed', 'error');
    } finally {
      clearGenerateBusy();
    }
  }

  function handleResultMeta(meta) {
    if (!meta || !meta.artist_thumb_request) return false;
    const requestId = String(meta.artist_thumb_request_id || '');
    if (pendingResultRequestId && requestId && requestId !== pendingResultRequestId) return false;
    if (!pendingResultRequestId && requestId) pendingResultRequestId = requestId;
    pendingResultMeta = meta;
    const artist = meta.artist_thumb_artist || selected?.artist || 'Artist Thumb';
    if (resultTitleEl) {
      const size = meta.width && meta.height ? ` · ${meta.width}x${meta.height}` : '';
      resultTitleEl.textContent = `${artist}${size}`;
    }
    if (!pendingResultSuppressPreview) {
      showResultPreview('Receiving generated image...');
    }
    return true;
  }

  function handleResultBlob(blob) {
    if (!pendingResultMeta || !blob) return false;
    revokeResultBlobUrl();
    resultBlobUrl = URL.createObjectURL(blob);
    if (resultPreviewEl) resultPreviewEl.hidden = false;
    if (resultImageEl) {
      resultImageEl.src = resultBlobUrl;
      resultImageEl.classList.add('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = true;
    pendingResultMeta = null;
    pendingResultRequestId = '';
    pendingResultSuppressPreview = false;
    updateResultExpandButton();
    if (pendingResultAutoExpand) {
      pendingResultAutoExpand = false;
      setResultExpanded(true);
    }
    return true;
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
    if (info.available) {
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
    randomBtn?.addEventListener('click', loadRandomArtists);
    gridEl?.addEventListener('wheel', onGridWheel, {passive: false});
    gridEl?.addEventListener('click', event => {
      const card = event.target.closest('.artist-thumb-card[data-artist]');
      if (!card || !gridEl.contains(card)) return;
      const item = itemFromCard(card);
      if (item) selectArtist(item);
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
    syncPromptFormat,
    handleResultMeta,
    handleResultBlob,
  };
}
