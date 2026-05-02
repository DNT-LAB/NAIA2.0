export function createThumbTabController({
  document,
  escHtml,
  showToast,
  promptEdit,
  onPromptEdit,
}) {
  const summaryEl = document.getElementById('thumbSummary');
  const searchEl = document.getElementById('thumbSearch');
  const categoriesEl = document.getElementById('thumbCategories');
  const statusEl = document.getElementById('thumbStatus');
  const gridEl = document.getElementById('thumbGrid');

  let state = null;
  let statePromise = null;
  let activeCategory = '';
  let activeTags = [];
  const categoryCache = new Map();

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setSummary(message) {
    if (summaryEl) summaryEl.textContent = message || 'Style thumbnails';
  }

  function renderCategories() {
    if (!categoriesEl || !state) return;
    categoriesEl.innerHTML = (state.categories || []).map(category => `
      <button class="thumb-category-btn${category.key === activeCategory ? ' active' : ''}"
              type="button"
              data-category="${escHtml(category.key)}"
              title="${escHtml(category.description || category.name)}">
        <span class="thumb-category-name">${escHtml(category.name)}</span>
        <span class="thumb-category-count">${Number(category.available || 0)}</span>
      </button>
    `).join('');
  }

  function filteredTags() {
    const query = String(searchEl?.value || '').trim().toLowerCase();
    if (!query) return activeTags;
    return activeTags.filter(item => String(item.tag || '').toLowerCase().includes(query));
  }

  function renderGrid() {
    if (!gridEl) return;
    const tags = filteredTags();
    if (!tags.length) {
      gridEl.innerHTML = '<div class="thumb-empty">No matching style tags.</div>';
      return;
    }
    gridEl.innerHTML = tags.map(item => `
      <article class="thumb-card" data-tag="${escHtml(item.tag)}">
        <img class="thumb-card-image" loading="lazy" src="${escHtml(item.image_url)}" alt="${escHtml(item.tag)}">
        <div class="thumb-card-footer">
          <button class="thumb-insert-btn" type="button" data-tag="${escHtml(item.tag)}" title="${escHtml(item.tag)}">${escHtml(item.tag)}</button>
          <button class="thumb-copy-btn" type="button" data-tag="${escHtml(item.tag)}" title="Copy tag">Copy</button>
        </div>
      </article>
    `).join('');
  }

  function insertTag(tag) {
    const target = promptEdit;
    if (!target) return false;
    const text = target.value || '';
    const start = target.selectionStart != null ? target.selectionStart : text.length;
    const end = target.selectionEnd != null ? target.selectionEnd : start;
    const before = text.substring(0, start);
    const after = text.substring(end);
    const prefix = before.trim()
      ? (/[,\s]$/.test(before) ? '' : ', ')
      : '';
    const insertText = `${prefix}${tag}, `;
    target.value = before + insertText + after;
    const nextPos = before.length + insertText.length;
    target.focus();
    target.selectionStart = target.selectionEnd = nextPos;
    if (onPromptEdit) onPromptEdit();
    return true;
  }

  async function copyTag(tag) {
    try {
      await navigator.clipboard.writeText(tag);
      if (showToast) showToast('Tag copied', 'success');
    } catch (error) {
      console.warn('Thumb tag copy failed', error);
      if (showToast) showToast('Copy failed', 'error');
    }
  }

  async function fetchState() {
    setStatus('Loading style categories...', 'busy');
    const response = await fetch('/api/thumb/state', {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    state = data;
    activeCategory = data.selected || data.categories?.[0]?.key || '';
    setSummary(`${Number(data.total_available || 0).toLocaleString()} styles`);
    renderCategories();
    if (activeCategory) await loadCategory(activeCategory);
    else setStatus('No style categories available.', 'error');
  }

  async function load(options = {}) {
    if (state && !options.force) return;
    if (!statePromise || options.force) {
      statePromise = fetchState().catch(error => {
        statePromise = null;
        state = null;
        console.error('Thumb state load failed', error);
        setStatus(error.message || 'Thumb load failed', 'error');
        if (showToast) showToast(error.message || 'Thumb load failed', 'error');
      });
    }
    await statePromise;
  }

  async function loadCategory(categoryKey) {
    const key = String(categoryKey || '').trim();
    if (!key) return;
    activeCategory = key;
    renderCategories();
    setStatus('Loading style thumbnails...', 'busy');
    try {
      let data = categoryCache.get(key);
      if (!data) {
        const response = await fetch(`/api/thumb/category/${encodeURIComponent(key)}`, {cache: 'no-store'});
        data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        categoryCache.set(key, data);
      }
      activeTags = Array.isArray(data.tags) ? data.tags : [];
      renderGrid();
      setStatus(`${data.name || key} · ${activeTags.length.toLocaleString()} styles`, 'ok');
    } catch (error) {
      console.error('Thumb category load failed', error);
      activeTags = [];
      renderGrid();
      setStatus(error.message || 'Thumb category failed', 'error');
      if (showToast) showToast(error.message || 'Thumb category failed', 'error');
    }
  }

  function bind() {
    categoriesEl?.addEventListener('click', event => {
      const button = event.target.closest('.thumb-category-btn[data-category]');
      if (!button) return;
      loadCategory(button.dataset.category || '');
    });
    gridEl?.addEventListener('click', event => {
      const copyButton = event.target.closest('.thumb-copy-btn[data-tag]');
      if (copyButton) {
        copyTag(copyButton.dataset.tag || '');
        return;
      }
      const insertButton = event.target.closest('.thumb-insert-btn[data-tag]');
      if (insertButton && insertTag(insertButton.dataset.tag || '') && showToast) {
        showToast('Style tag inserted', 'success');
      }
    });
    searchEl?.addEventListener('input', renderGrid);
  }

  bind();

  return {
    load,
    loadCategory,
    renderGrid,
  };
}
