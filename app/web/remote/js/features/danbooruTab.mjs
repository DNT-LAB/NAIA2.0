export function createDanbooruBrowserController({
  document,
  window: win = window,
  fetch: fetchFn = window.fetch.bind(window),
  showToast,
  onLoadPrompt = null,
}) {
  let panel = null;
  let queryInput = null;
  let statusEl = null;
  let resultEl = null;
  let lastQuery = '';
  let lastPost = null;

  function escHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function tagList(tags, group) {
    const values = Array.isArray(tags?.[group]) ? tags[group] : [];
    if (!values.length) return '<span class="danbooru-empty">empty</span>';
    return values.slice(0, 80)
      .map(tag => `<button type="button" class="danbooru-tag" data-danbooru-tag="${escHtml(tag)}">${escHtml(tag)}</button>`)
      .join('');
  }

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setBusy(busy) {
    panel?.querySelectorAll('[data-danbooru-busy-control]').forEach(el => {
      el.disabled = !!busy;
    });
  }

  function renderEmpty(message = 'Search by post id, URL, or tags.') {
    if (!resultEl) return;
    resultEl.innerHTML = `<div class="danbooru-result-empty">${escHtml(message)}</div>`;
  }

  function renderPost(post) {
    if (!resultEl) return;
    lastPost = post;
    const tags = post?.tags || {};
    const prompt = String(post?.prompt || '');
    const postUrl = String(post?.post_url || '');
    resultEl.innerHTML = `
      <section class="danbooru-result-card">
        <header class="danbooru-result-head">
          <div>
            <div class="danbooru-result-kicker">Post ${escHtml(post?.post_id || '')}</div>
            <a class="danbooru-result-link" href="${escHtml(postUrl)}" target="_blank" rel="noopener noreferrer">${escHtml(postUrl || 'Danbooru post')}</a>
          </div>
          <button type="button" class="danbooru-copy-btn" data-danbooru-apply-prompt>Apply Prompt</button>
        </header>
        <div class="danbooru-prompt-box">${escHtml(prompt || 'No prompt preview')}</div>
        <div class="danbooru-tag-groups">
          ${['artist', 'copyright', 'character', 'general', 'meta'].map(group => `
            <section class="danbooru-tag-group">
              <h3>${escHtml(group)}</h3>
              <div class="danbooru-tags">${tagList(tags, group)}</div>
            </section>
          `).join('')}
        </div>
      </section>
    `;
  }

  async function loadPost(queryOverride = null) {
    ensurePanel();
    const query = String(queryOverride ?? queryInput?.value ?? '').trim();
    if (!query) {
      renderEmpty('Enter a Danbooru post id, URL, or tag query.');
      setStatus('Query is empty', 'error');
      return false;
    }
    lastQuery = query;
    setBusy(true);
    setStatus('Loading Danbooru post...', 'busy');
    try {
      const response = await fetchFn('/api/danbooru/post', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      renderPost(data);
      setStatus('Loaded', 'ok');
      return true;
    } catch (error) {
      console.error('Danbooru post lookup failed', error);
      renderEmpty(error.message || 'Danbooru lookup failed');
      setStatus(error.message || 'Lookup failed', 'error');
      if (showToast) showToast(error.message || 'Danbooru lookup failed', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function openExternalBrowser({query: explicitQuery = null} = {}) {
    const query = String(explicitQuery ?? queryInput?.value ?? lastQuery ?? '').trim();
    setBusy(true);
    setStatus('Opening Danbooru web...', 'busy');
    try {
      const response = await fetchFn('/api/danbooru/browser/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (data.url) win.open(data.url, '_blank', 'noopener,noreferrer');
      setStatus('Opened in browser', 'ok');
      return true;
    } catch (error) {
      console.error('Danbooru browser open failed', error);
      setStatus(error.message || 'Open failed', 'error');
      if (showToast) showToast(error.message || 'Danbooru web open failed', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  }

  function applyPrompt() {
    const prompt = String(lastPost?.prompt || '').trim();
    if (!prompt) {
      if (showToast) showToast('No Danbooru prompt to apply', 'error');
      return;
    }
    if (typeof onLoadPrompt === 'function') {
      onLoadPrompt(prompt);
      if (showToast) showToast('Danbooru prompt applied', 'success');
    }
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('section');
    panel.className = 'danbooru-tool-panel';
    panel.innerHTML = `
      <div class="danbooru-tool-dialog">
        <header class="danbooru-tool-header">
          <div>
            <div class="danbooru-tool-kicker">Danbooru</div>
            <h2>Danbooru Tag Lookup</h2>
          </div>
          <button type="button" class="danbooru-close-btn" data-danbooru-close aria-label="Close">×</button>
        </header>
        <div class="danbooru-tool-search">
          <input class="danbooru-query-input" data-danbooru-query data-danbooru-busy-control placeholder="post id, URL, or tags">
          <button type="button" class="danbooru-load-btn" data-danbooru-load data-danbooru-busy-control>Load</button>
          <button type="button" class="danbooru-open-btn" data-danbooru-open-web data-danbooru-busy-control>Open Web</button>
        </div>
        <div class="danbooru-status" data-danbooru-status></div>
        <div class="danbooru-results" data-danbooru-results></div>
      </div>
    `;
    document.body.append(panel);
    queryInput = panel.querySelector('[data-danbooru-query]');
    statusEl = panel.querySelector('[data-danbooru-status]');
    resultEl = panel.querySelector('[data-danbooru-results]');
    renderEmpty();

    panel.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof win.Element)) return;
      if (target.closest('[data-danbooru-close]')) {
        closePanel();
      } else if (target.closest('[data-danbooru-load]')) {
        loadPost();
      } else if (target.closest('[data-danbooru-open-web]')) {
        openExternalBrowser();
      } else if (target.closest('[data-danbooru-apply-prompt]')) {
        applyPrompt();
      } else {
        const tag = target.closest('[data-danbooru-tag]');
        if (tag && queryInput) {
          queryInput.value = tag.dataset.danbooruTag || '';
          queryInput.focus();
        }
      }
    });
    queryInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') loadPost();
      if (event.key === 'Escape') closePanel();
    });
    return panel;
  }

  function openPanel({query = ''} = {}) {
    ensurePanel();
    if (queryInput && query) queryInput.value = query;
    panel.hidden = false;
    panel.classList.add('open');
    queryInput?.focus();
    setStatus('Ready', 'muted');
    return true;
  }

  function closePanel() {
    if (!panel) return;
    panel.classList.remove('open');
    panel.hidden = true;
  }

  function openBrowser(options = {}) {
    return openPanel(options);
  }

  return {
    closePanel,
    loadPost,
    openBrowser,
    openExternalBrowser,
    openPanel,
  };
}

export const createDanbooruTabController = createDanbooruBrowserController;
