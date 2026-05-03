export function createArtistThumbController({
  document,
  fetch,
  escHtml,
  showToast,
  promptEdit,
  negEdit,
  onPromptEdit,
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
  const resultPreviewEl = document.getElementById('artistThumbResultPreview');
  const resultTitleEl = document.getElementById('artistThumbResultTitle');
  const resultCloseBtn = document.getElementById('artistThumbResultClose');
  const resultImageEl = document.getElementById('artistThumbResultImage');
  const resultEmptyEl = document.getElementById('artistThumbResultEmpty');

  const PAGE_SIZE = 48;
  let state = null;
  let statePromise = null;
  let listRequestId = 0;
  let optionsTimer = null;
  let currentPage = 0;
  let totalPages = 1;
  let selected = null;
  let wheelPageLocked = false;
  let downloadTimer = null;
  let pendingResultRequestId = '';
  let pendingResultMeta = null;
  let resultBlobUrl = '';
  let hasLoadedList = false;
  let positiveAutoValue = '';
  let randomViewActive = false;

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

  function showResultPreview(message = 'Waiting for generated image...') {
    if (resultPreviewEl) resultPreviewEl.hidden = false;
    if (resultEmptyEl) {
      resultEmptyEl.hidden = false;
      resultEmptyEl.textContent = message;
    }
    if (resultImageEl) {
      resultImageEl.removeAttribute('src');
      resultImageEl.classList.remove('show');
    }
  }

  function closeResultPreview() {
    pendingResultRequestId = '';
    pendingResultMeta = null;
    revokeResultBlobUrl();
    if (resultPreviewEl) resultPreviewEl.hidden = true;
    if (resultImageEl) {
      resultImageEl.removeAttribute('src');
      resultImageEl.classList.remove('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = false;
  }

  function currentModeInfo() {
    const mode = currentMode();
    return (state?.modes || []).find(item => item.key === mode) || null;
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
      renderGrid(data.items || []);
      updatePager();
      hasLoadedList = true;
      scrollGrid(options.anchor || 'top');
      const count = Number(data.total || 0).toLocaleString();
      const modeText = mode || '목록';
      const statusPrefix = data.random ? 'Random artists' : modeText;
      setStatus(`${statusPrefix} · ${data.filter_name || '전체 목록'} · ${count} artists`, 'ok');
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

  async function toggleFavorite() {
    const item = selectedPayload();
    if (!item) return;
    const next = !item.favorite;
    try {
      state = await postJson('/api/artist-thumb/favorite', {artist: item.artist, favorite: next});
      renderState();
      applyFavoriteState(item, next);
      showToast?.(next ? '관심 작가로 등록했습니다.' : '관심 작가에서 해제했습니다.', 'success');
    } catch (error) {
      showToast?.(error.message || 'Favorite failed', 'error');
    }
  }

  async function banSelected() {
    const item = selectedPayload();
    if (!item) return;
    try {
      state = await postJson('/api/artist-thumb/ban', {artist: item.artist, banned: true});
      selected = null;
      renderState();
      await loadPage(currentPage);
      if (selectedImage) {
        selectedImage.removeAttribute('src');
        selectedImage.classList.remove('show');
      }
      if (selectedEmpty) selectedEmpty.hidden = false;
      if (selectedName) selectedName.textContent = '아티스트를 선택하세요';
      if (selectedMeta) selectedMeta.textContent = '';
      [favoriteBtn, banBtn, copyBtn, insertBtn].forEach(button => {
        if (button) button.disabled = true;
      });
      showToast?.('제외 작가에 추가했습니다.', 'success');
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

  async function generateSelected() {
    const item = selectedPayload();
    if (!item) return;
    const requestId = makeRequestId();
    const artistPrompt = formatArtistPrompt(item.artist);
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
      if (resultTitleEl) resultTitleEl.textContent = `${item.artist} · generating`;
      showResultPreview('Waiting for generated image...');
      generateBtn.disabled = true;
      generateBtn.textContent = 'Requesting...';
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
      generateBtn.disabled = false;
      generateBtn.textContent = 'Generate 832 x 1216';
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
    showResultPreview('Receiving generated image...');
    return true;
  }

  function handleResultBlob(blob) {
    if (!pendingResultMeta || !blob) return false;
    revokeResultBlobUrl();
    resultBlobUrl = URL.createObjectURL(blob);
    if (resultImageEl) {
      resultImageEl.src = resultBlobUrl;
      resultImageEl.classList.add('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = true;
    pendingResultMeta = null;
    pendingResultRequestId = '';
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
      const image = card.querySelector('img')?.getAttribute('src') || '';
      const weight = card.querySelector('.artist-thumb-card-weight')?.textContent || '';
      selectArtist({
        artist: card.dataset.artist || '',
        image_url: image,
        weight: card.dataset.weight || weight,
        favorite: card.classList.contains('favorite'),
      });
    });
    favoriteBtn?.addEventListener('click', toggleFavorite);
    banBtn?.addEventListener('click', banSelected);
    copyBtn?.addEventListener('click', copySelected);
    insertBtn?.addEventListener('click', insertSelected);
    generateBtn?.addEventListener('click', generateSelected);
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
