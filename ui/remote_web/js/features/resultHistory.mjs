const HISTORY_RAIL_COLLAPSED_KEY = 'naia_history_rail_collapsed';
const PROMPT_CACHE_MAX = 80;

function encodeViewerPath(relPath) {
  return String(relPath || '').split('/').map(part => encodeURIComponent(part)).join('/');
}

function viewerMetaUrl(relPath) {
  const params = new URLSearchParams({path: String(relPath || '')});
  return '/api/viewer/meta?' + params.toString();
}

export function createResultHistoryController({
  document,
  window,
  localStorage,
  fetch,
  preview,
  emptyMsg,
  resultInfoContent,
  escHtml,
  showToast,
  onDiskImageSelected = () => {},
}) {
  const getEl = id => document.getElementById(id);
  const viewerTab = getEl('viewerTab');
  const viewerPanel = getEl('viewerPanel');
  const viewerRailToggle = getEl('viewerRailToggle');
  const viewerGrid = getEl('viewerGrid');
  const viewerCountEl = getEl('viewerCount');
  const viewerLoading = getEl('viewerLoading');

  let initialized = false;
  let viewerPage = 0;
  let viewerTotal = 0;
  let viewerLoadingMore = false;
  let viewerPopupOpen = false;
  let vpPage = 0;
  let vpLoading = false;
  let vpCurrentPath = '';
  let viewerNavPaths = [];
  let viewerNavIdx = -1;
  let currentViewerPath = '';
  let lightboxPromptVisible = false;
  let viewerPendingNewCount = 0;
  let latestImagePath = '';
  let promptFloatCache = {};
  let promptFloatCacheKeys = [];

  function setRailCollapsed(collapsed, persist = true) {
    if (!viewerPanel) return;
    viewerPanel.classList.toggle('collapsed', collapsed);
    if (viewerRailToggle) {
      viewerRailToggle.textContent = collapsed ? '‹' : '›';
      viewerRailToggle.title = collapsed ? 'Expand history' : 'Collapse history';
      viewerRailToggle.setAttribute('aria-label', collapsed ? 'Expand history' : 'Collapse history');
      viewerRailToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
    if (persist) {
      try { localStorage.setItem(HISTORY_RAIL_COLLAPSED_KEY, collapsed ? '1' : '0'); } catch (_) {}
    }
  }

  function toggleRail() {
    if (!viewerPanel) return;
    setRailCollapsed(!viewerPanel.classList.contains('collapsed'));
  }

  function initRail() {
    if (!viewerPanel) return;
    let collapsed = false;
    try { collapsed = localStorage.getItem(HISTORY_RAIL_COLLAPSED_KEY) === '1'; } catch (_) {}
    setRailCollapsed(collapsed, false);
  }

  function hasThumb(relPath) {
    if (!viewerGrid || !relPath) return false;
    return !!viewerGrid.querySelector(`.viewer-thumb[data-path="${CSS.escape(relPath)}"]`);
  }

  function appendThumb(relPath) {
    if (!viewerGrid) return;
    const img = document.createElement('img');
    img.className = 'viewer-thumb';
    img.loading = 'lazy';
    img.dataset.path = relPath;
    img.src = '/api/viewer/thumb/' + encodeViewerPath(relPath);
    img.onclick = () => thumbClick(relPath);
    viewerGrid.appendChild(img);
  }

  function prependThumb(relPath) {
    if (!viewerGrid) return;
    const img = document.createElement('img');
    img.className = 'viewer-thumb';
    img.loading = 'lazy';
    img.dataset.path = relPath;
    img.src = '/api/viewer/thumb/' + encodeViewerPath(relPath);
    img.onclick = () => thumbClick(relPath);
    viewerGrid.prepend(img);
  }

  async function loadPage(page) {
    if (viewerLoadingMore || !viewerGrid) return;
    viewerLoadingMore = true;
    if (viewerLoading) viewerLoading.style.display = '';
    try {
      const resp = await fetch(`/api/viewer/list?page=${page}&per_page=30`);
      const data = await resp.json();
      viewerTotal = data.total;
      if (viewerCountEl) viewerCountEl.textContent = viewerTotal;
      if (viewerTab) viewerTab.classList.toggle('visible', viewerTotal > 0);
      for (const entry of data.images) {
        if (hasThumb(entry.rel_path)) continue;
        appendThumb(entry.rel_path);
      }
      viewerPage = page + 1;
    } catch (error) {
      console.error('Viewer load failed:', error);
    }
    viewerLoadingMore = false;
    if (viewerLoading) viewerLoading.style.display = 'none';
  }

  function initViewer() {
    if (!viewerGrid) return;
    viewerPage = 0;
    viewerTotal = 0;
    viewerGrid.innerHTML = '';
    loadPage(0);
  }

  function prepareInitialHistory() {
    fetch('/api/viewer/list?page=0&per_page=1').then(resp => resp.json()).then(data => {
      viewerTotal = data.total;
      if (viewerCountEl) viewerCountEl.textContent = data.total;
      if (data.total > 0 && viewerGrid && viewerGrid.children.length === 0) initViewer();
    }).catch(() => {});
  }

  function rememberPromptMetaHtml(relPath, html) {
    promptFloatCache[relPath] = html;
    promptFloatCacheKeys = promptFloatCacheKeys.filter(key => key !== relPath);
    promptFloatCacheKeys.push(relPath);
    while (promptFloatCacheKeys.length > PROMPT_CACHE_MAX) {
      delete promptFloatCache[promptFloatCacheKeys.shift()];
    }
  }

  async function getPromptMetaHtml(relPath) {
    if (promptFloatCache[relPath]) return promptFloatCache[relPath];
    const resp = await fetch(viewerMetaUrl(relPath));
    const meta = await resp.json();
    let html = '';
    if (meta.prompt) {
      html += '<div class="pf-island"><span class="pf-label">Prompt</span>' + escHtml(meta.prompt) + '</div>';
    }
    if (meta.characters && meta.characters.length) {
      for (let i = 0; i < meta.characters.length; i++) {
        html += `<div class="pf-island"><span class="pf-label">Character ${i + 1}</span>` + escHtml(meta.characters[i]) + '</div>';
      }
    }
    if (!html) html = '<div class="pf-island"><span class="pf-label">No metadata</span></div>';
    rememberPromptMetaHtml(relPath, html);
    return html;
  }

  async function loadResultInfo(relPath) {
    if (!resultInfoContent || !relPath) return;
    resultInfoContent.innerHTML = '<span class="result-info-empty">loading metadata...</span>';
    try {
      resultInfoContent.innerHTML = await getPromptMetaHtml(relPath);
    } catch (_) {
      resultInfoContent.innerHTML = '<span class="result-info-empty">metadata unavailable</span>';
    }
  }

  async function loadPromptForFloat(relPath, floatId, contentId) {
    const pf = getEl(floatId);
    const content = getEl(contentId);
    if (!pf || !content) return;

    if (promptFloatCache[relPath]) {
      content.innerHTML = promptFloatCache[relPath];
      window.requestAnimationFrame(() => {
        content.classList.toggle('scrollable', content.scrollHeight > content.clientHeight);
      });
      pf.classList.add('visible');
      return;
    }

    content.innerHTML = '<span class="pf-label">Loading...</span>';
    pf.classList.add('visible');

    try {
      const html = await getPromptMetaHtml(relPath);
      content.innerHTML = html;
      window.requestAnimationFrame(() => {
        content.classList.toggle('scrollable', content.scrollHeight > content.clientHeight);
      });
    } catch (_) {
      content.innerHTML = '<span class="pf-label">Failed to load</span>';
    }
  }

  function lightboxBaseHtml() {
    const promptBtnText = lightboxPromptVisible ? 'Hide Prompt' : 'Show Prompt';
    return `
    <div class="viewer-lightbox-inner" onclick="event.stopPropagation()">
      <img id="viewerLightboxImg" alt="">
      <div class="prompt-float viewer-lightbox-prompt${lightboxPromptVisible ? ' visible' : ''}" id="viewerLightboxPrompt">
        <div class="prompt-float-content" id="viewerLightboxPromptContent"></div>
      </div>
      <div class="viewer-lightbox-controls">
        <button class="viewer-lightbox-btn${lightboxPromptVisible ? ' accent' : ''}" id="viewerLightboxPromptBtn" onclick="toggleLightboxPrompt()">${promptBtnText}</button>
        <button class="viewer-lightbox-btn danger" onclick="closeViewerLightbox()">Close</button>
      </div>
    </div>`;
  }

  function resetLightbox() {
    const lb = getEl('viewerLightbox');
    if (!lb) return;
    lb.innerHTML = lightboxBaseHtml();
  }

  function syncLightboxPromptUi() {
    const prompt = getEl('viewerLightboxPrompt');
    const btn = getEl('viewerLightboxPromptBtn');
    if (prompt) prompt.classList.toggle('visible', lightboxPromptVisible);
    if (btn) {
      btn.textContent = lightboxPromptVisible ? 'Hide Prompt' : 'Show Prompt';
      btn.classList.toggle('accent', lightboxPromptVisible);
    }
  }

  function closeLightbox() {
    const lb = getEl('viewerLightbox');
    if (lb) lb.classList.remove('open');
    lightboxPromptVisible = false;
    resetLightbox();
    viewerPopupOpen = false;
  }

  function onLightboxClick() {
    if (viewerPopupOpen) closePopup();
    else closeLightbox();
  }

  function ensureLatestBadge() {
    let el = getEl('viewerLatestBadge');
    if (el) return el;
    el = document.createElement('button');
    el.id = 'viewerLatestBadge';
    el.className = 'viewer-latest-badge';
    el.type = 'button';
    el.onclick = jumpToLatest;
    document.body.appendChild(el);
    return el;
  }

  function showLatestBadge() {
    const el = ensureLatestBadge();
    const count = viewerPendingNewCount;
    el.textContent = count > 1 ? `↓ 최신으로 (+${count})` : '↓ 최신으로';
    el.classList.add('visible');
  }

  function hideLatestBadge() {
    viewerPendingNewCount = 0;
    const el = getEl('viewerLatestBadge');
    if (el) el.classList.remove('visible');
  }

  function jumpToLatest() {
    if (viewerNavPaths.length === 0) {
      hideLatestBadge();
      return;
    }
    viewerNavIdx = 0;
    showImage(viewerNavPaths[0]);
    hideLatestBadge();
  }

  function showImage(relPath) {
    currentViewerPath = relPath;
    onDiskImageSelected(relPath);
    preview.src = '/api/viewer/image/' + encodeViewerPath(relPath);
    preview.dataset.source = 'saved';
    preview.dataset.path = relPath;
    preview.classList.add('show');
    emptyMsg.style.display = 'none';
    loadResultInfo(relPath);
    if (!viewerGrid) return;
    const thumbs = viewerGrid.querySelectorAll('.viewer-thumb');
    thumbs.forEach((thumb, index) => thumb.classList.toggle('active', index === viewerNavIdx));
  }

  function thumbClick(relPath) {
    if (window.innerWidth < 768) {
      const lb = getEl('viewerLightbox');
      currentViewerPath = relPath;
      latestImagePath = relPath;
      onDiskImageSelected(relPath);
      resetLightbox();
      const img = getEl('viewerLightboxImg');
      if (lb && img) {
        img.src = '/api/viewer/image/' + encodeViewerPath(relPath);
        img.dataset.source = 'saved';
        img.dataset.path = relPath;
        lb.classList.add('open');
        syncLightboxPromptUi();
        if (lightboxPromptVisible) {
          loadPromptForFloat(relPath, 'viewerLightboxPrompt', 'viewerLightboxPromptContent');
        }
      }
      return;
    }

    viewerNavPaths = [];
    const thumbs = viewerGrid ? viewerGrid.querySelectorAll('.viewer-thumb') : [];
    thumbs.forEach(thumb => {
      const path = thumb.dataset.path;
      if (path) {
        viewerNavPaths.push(path);
      } else {
        const src = thumb.getAttribute('src') || '';
        const match = src.match(/\/api\/viewer\/thumb\/(.+)$/);
        if (match) viewerNavPaths.push(decodeURI(match[1]));
      }
    });
    viewerNavIdx = viewerNavPaths.indexOf(relPath);
    if (viewerNavIdx < 0) {
      viewerNavPaths = [relPath];
      viewerNavIdx = 0;
    }
    hideLatestBadge();
    showImage(relPath);
  }

  function navViewer(direction) {
    const next = viewerNavIdx + direction;
    if (next >= 0 && next < viewerNavPaths.length) {
      viewerNavIdx = next;
      showImage(viewerNavPaths[viewerNavIdx]);
      if (viewerNavIdx === 0) hideLatestBadge();
    }
  }

  function hideNav() {
    viewerNavIdx = -1;
    currentViewerPath = '';
    if (viewerGrid) {
      viewerGrid.querySelectorAll('.viewer-thumb.active').forEach(thumb => thumb.classList.remove('active'));
    }
    hideLatestBadge();
  }

  function onNewImage(message) {
    if (!message.rel_path) return;
    latestImagePath = message.rel_path;
    viewerTotal++;
    if (viewerCountEl) viewerCountEl.textContent = viewerTotal;
    if (viewerTab) viewerTab.classList.add('visible');

    const alreadyInGrid = hasThumb(message.rel_path);
    const didPrepend = !alreadyInGrid && !!viewerGrid;
    if (didPrepend) prependThumb(message.rel_path);

    if (viewerNavIdx < 0 || !currentViewerPath || currentViewerPath === message.rel_path) {
      loadResultInfo(message.rel_path);
    }

    if (didPrepend && viewerNavIdx >= 0 && viewerNavPaths.length > 0
        && !viewerNavPaths.includes(message.rel_path)) {
      viewerNavPaths.unshift(message.rel_path);
      if (viewerNavIdx === 0) {
        showImage(message.rel_path);
      } else {
        viewerNavIdx += 1;
        viewerPendingNewCount += 1;
        showLatestBadge();
        const thumbs = viewerGrid.querySelectorAll('.viewer-thumb');
        thumbs.forEach((thumb, index) => thumb.classList.toggle('active', index === viewerNavIdx));
      }
    }

    if (viewerPopupOpen) {
      const vpGrid = getEl('vpGrid');
      if (vpGrid && !vpGrid.querySelector(`.viewer-thumb[data-path="${CSS.escape(message.rel_path)}"]`)) {
        const img = document.createElement('img');
        img.className = 'viewer-thumb';
        img.loading = 'lazy';
        img.dataset.path = message.rel_path;
        img.src = '/api/viewer/thumb/' + encodeViewerPath(message.rel_path);
        img.onclick = () => selectPopupImage(message.rel_path, img);
        vpGrid.prepend(img);
      }
      const count = getEl('vpCount');
      if (count) count.textContent = viewerTotal;
    }
  }

  function openPopup() {
    const lb = getEl('viewerLightbox');
    if (!lb) return;
    viewerPopupOpen = true;
    lb.innerHTML = `
    <div class="viewer-popup-inner" onclick="event.stopPropagation()">
      <div class="viewer-popup-header">
        <span class="viewer-panel-title">History <span id="vpCount">${viewerTotal}</span></span>
        <button class="history-close" onclick="closeViewerPopup()">&times;</button>
      </div>
      <div class="viewer-popup-body">
        <div class="viewer-popup-left" id="vpGrid"></div>
        <div class="viewer-popup-right" id="vpRight">
          <img class="vp-preview" id="vpPreview" alt="">
          <div class="prompt-float" id="vpPromptFloat">
            <div class="prompt-float-content" id="vpPromptContent"></div>
          </div>
          <div class="viewer-bottom-controls" style="display:flex">
            <button class="viewer-folder-btn" onclick="openResultFolder()">Open Folder</button>
          </div>
        </div>
      </div>
      <div class="viewer-panel-loading" id="vpLoading" style="display:none">Loading...</div>
    </div>`;
    lb.classList.add('open');
    vpPage = 0;
    loadPopupPage(0);
    const grid = getEl('vpGrid');
    if (grid) grid.addEventListener('scroll', popupScroll);
  }

  async function loadPopupPage(page) {
    if (vpLoading) return;
    vpLoading = true;
    const loading = getEl('vpLoading');
    if (loading) loading.style.display = '';
    try {
      const resp = await fetch(`/api/viewer/list?page=${page}&per_page=30`);
      const data = await resp.json();
      const grid = getEl('vpGrid');
      if (grid) {
        for (const entry of data.images) {
          if (grid.querySelector(`.viewer-thumb[data-path="${CSS.escape(entry.rel_path)}"]`)) continue;
          const img = document.createElement('img');
          img.className = 'viewer-thumb';
          img.loading = 'lazy';
          img.dataset.path = entry.rel_path;
          img.src = '/api/viewer/thumb/' + encodeViewerPath(entry.rel_path);
          img.onclick = () => selectPopupImage(entry.rel_path, img);
          grid.appendChild(img);
        }
      }
      vpPage = page + 1;
      viewerTotal = data.total;
      const count = getEl('vpCount');
      if (count) count.textContent = data.total;
    } catch (_) {}
    vpLoading = false;
    if (loading) loading.style.display = 'none';
  }

  function selectPopupImage(relPath, thumbEl) {
    vpCurrentPath = relPath;
    const previewEl = getEl('vpPreview');
    if (previewEl) {
      previewEl.src = '/api/viewer/image/' + encodeViewerPath(relPath);
      previewEl.dataset.source = 'saved';
      previewEl.dataset.path = relPath;
    }
    const grid = getEl('vpGrid');
    if (grid) grid.querySelectorAll('.viewer-thumb').forEach(thumb => thumb.classList.remove('active'));
    if (thumbEl) thumbEl.classList.add('active');
    const cb = getEl('vpPromptCb');
    if (cb && cb.checked) loadPromptForFloat(relPath, 'vpPromptFloat', 'vpPromptContent');
  }

  function togglePopupPrompt(checked) {
    const pf = getEl('vpPromptFloat');
    if (pf) pf.classList.toggle('visible', checked);
    if (checked && vpCurrentPath) loadPromptForFloat(vpCurrentPath, 'vpPromptFloat', 'vpPromptContent');
  }

  function popupScroll() {
    const grid = getEl('vpGrid');
    if (!grid || vpLoading) return;
    if (grid.scrollTop + grid.clientHeight >= grid.scrollHeight - 100) {
      if (grid.children.length < viewerTotal) loadPopupPage(vpPage);
    }
  }

  function closePopup() {
    viewerPopupOpen = false;
    const lb = getEl('viewerLightbox');
    if (lb) lb.classList.remove('open');
    lightboxPromptVisible = false;
    resetLightbox();
  }

  function navPopup(direction) {
    const grid = getEl('vpGrid');
    if (!grid) return;
    const thumbs = [...grid.querySelectorAll('.viewer-thumb')];
    if (thumbs.length === 0) return;
    const index = thumbs.findIndex(thumb => thumb.classList.contains('active'));
    const next = index + direction;
    if (next >= 0 && next < thumbs.length) {
      selectPopupImage(thumbs[next].dataset.path, thumbs[next]);
      thumbs[next].scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
  }

  function toggleLightboxPrompt(forceVisible) {
    lightboxPromptVisible = typeof forceVisible === 'boolean' ? forceVisible : !lightboxPromptVisible;
    syncLightboxPromptUi();
    if (lightboxPromptVisible && currentViewerPath) {
      loadPromptForFloat(currentViewerPath, 'viewerLightboxPrompt', 'viewerLightboxPromptContent');
    }
  }

  function bindInfiniteScroll() {
    if (!viewerGrid) return;
    viewerGrid.addEventListener('scroll', () => {
      if (viewerLoadingMore) return;
      const {scrollTop, scrollHeight, clientHeight} = viewerGrid;
      if (scrollTop + clientHeight >= scrollHeight - 80) {
        const loadedCount = viewerGrid.children.length;
        if (loadedCount < viewerTotal) loadPage(viewerPage);
      }
    });
  }

  function bindKeyboard() {
    document.addEventListener('keydown', event => {
      const tag = (event.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      if (viewerPopupOpen) {
        if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
          event.preventDefault();
          navPopup(-1);
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
          event.preventDefault();
          navPopup(1);
        } else if (event.key === 'Escape') {
          closePopup();
        }
        return;
      }

      if (viewerNavIdx < 0 || viewerNavPaths.length === 0) return;

      if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        event.preventDefault();
        navViewer(-1);
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        event.preventDefault();
        navViewer(1);
      } else if (event.key === 'Escape') {
        hideNav();
      }
    });
  }

  async function openFolder() {
    try {
      const resp = await fetch('/api/viewer/open-folder', {method: 'POST'});
      if (!resp.ok) {
        showToast('Open folder failed.', 'error');
        return;
      }
      showToast('Opened result folder.', 'success');
    } catch (_) {
      showToast('Open folder failed.', 'error');
    }
  }

  function init() {
    if (initialized) return;
    initialized = true;
    initRail();
    bindInfiniteScroll();
    bindKeyboard();
  }

  return {
    init,
    initViewer,
    prepareInitialHistory,
    toggleRail,
    setRailCollapsed,
    closeLightbox,
    onLightboxClick,
    onNewImage,
    jumpToLatest,
    openPopup,
    closePopup,
    navPopup,
    toggleLightboxPrompt,
    togglePopupPrompt,
    thumbClick,
    navViewer,
    hideNav,
    openFolder,
    loadResultInfo,
    get latestImagePath() { return latestImagePath; },
  };
}
