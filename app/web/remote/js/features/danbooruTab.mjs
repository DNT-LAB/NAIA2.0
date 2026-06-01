// Tag-group layout ported from future01 tabs/web_view.py:28-47.
// PRIMARY groups (general is NOT primary — it is broken down below).
const DANBOORU_PRIMARY_GROUPS = [
  ['artist', 'ARTIST'],
  ['copyright', 'COPYRIGHT'],
  ['character', 'CHARACTER'],
  ['meta', 'META'],
];
// 12 GENERAL BREAKDOWN buckets (must match danbooru_routes.DANBOORU_GENERAL_BREAKDOWN_KEYS order).
const DANBOORU_GENERAL_BREAKDOWN_GROUPS = [
  ['character_features', 'CHARACTER FEATURES'],
  ['subject_count', 'SUBJECT COUNT'],
  ['clothing_events', 'CLOTHING EVENTS'],
  ['clothes', 'CLOTHES'],
  ['colors', 'COLORS'],
  ['location_background', 'LOCATION / BACKGROUND'],
  ['expression', 'EXPRESSION'],
  ['pose_action', 'POSE / ACTION'],
  ['objects', 'OBJECTS'],
  ['meta_like', 'META-LIKE'],
  ['noise', 'LOW-FREQ / NOISE'],
  ['other', 'OTHER GENERALS'],
];

export function createDanbooruBrowserController({
  document,
  window: win = window,
  fetch: fetchFn = window.fetch.bind(window),
  showToast,
  onLoadPrompt = null,
}) {
  // Electron shell exposes a native WebContentsView bridge; a plain browser does not.
  const naia = (win && win.naiaShell) || null;
  const embedMode = !!(naia && typeof naia.danbooruAttach === 'function');

  let panel = null;
  let queryInput = null;
  let addressInput = null;
  let viewRegion = null;
  let statusEl = null;
  let resultEl = null;
  let lastQuery = '';
  let lastPost = null;

  // Embedded-view state (Electron only).
  let embedActive = false;
  let lastAutoPostId = null;
  let autoExtractTimer = 0;
  let boundsRaf = 0;
  let unsubscribeNav = null;
  let boundsListener = null;

  function escHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function tagGroupHtml(label, values) {
    const list = Array.isArray(values) ? values : [];
    const body = list.length
      ? list.slice(0, 120)
          .map(tag => `<button type="button" class="danbooru-tag" data-danbooru-tag="${escHtml(tag)}">${escHtml(tag)}</button>`)
          .join('')
      : '<span class="danbooru-empty">—</span>';
    return `
      <section class="danbooru-tag-group">
        <h3>${escHtml(label)} <span class="danbooru-tag-count">· ${list.length}</span></h3>
        <div class="danbooru-tags">${body}</div>
      </section>`;
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
    const breakdown = post?.general_breakdown || {};
    const breakdownTotal = DANBOORU_GENERAL_BREAKDOWN_GROUPS.reduce(
      (sum, [key]) => sum + (Array.isArray(breakdown[key]) ? breakdown[key].length : 0),
      0,
    );
    const primaryHtml = DANBOORU_PRIMARY_GROUPS
      .map(([key, label]) => tagGroupHtml(label, tags[key]))
      .join('');
    // Only non-empty buckets are rendered (desktop setVisible(bool(tags))).
    const breakdownHtml = DANBOORU_GENERAL_BREAKDOWN_GROUPS
      .filter(([key]) => Array.isArray(breakdown[key]) && breakdown[key].length)
      .map(([key, label]) => tagGroupHtml(label, breakdown[key]))
      .join('') || '<span class="danbooru-empty">—</span>';
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
        <div class="danbooru-tag-groups">${primaryHtml}</div>
        <div class="danbooru-breakdown-head">GENERAL BREAKDOWN <span class="danbooru-tag-count">· ${breakdownTotal}</span></div>
        <div class="danbooru-tag-groups danbooru-breakdown-groups">${breakdownHtml}</div>
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
      setStatus(`#${data.post_id} 태그를 읽었습니다.`, 'ok');
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
    const query = String(explicitQuery ?? addressInput?.value ?? queryInput?.value ?? lastQuery ?? '').trim();
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

  // ---- Embedded native view (Electron only) --------------------------------
  function currentViewRect() {
    if (!viewRegion) return null;
    const r = viewRegion.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return {x: r.left, y: r.top, width: r.width, height: r.height};
  }

  function reportBounds() {
    if (!embedActive || !naia) return;
    const rect = currentViewRect();
    if (rect) naia.danbooruSetBounds(rect);
  }

  function scheduleReportBounds() {
    if (!embedActive) return;
    if (boundsRaf) win.cancelAnimationFrame(boundsRaf);
    boundsRaf = win.requestAnimationFrame(() => {
      boundsRaf = 0;
      reportBounds();
    });
  }

  function onDidNavigate(info) {
    if (addressInput && info && info.url) addressInput.value = info.url;
    const postId = info && info.postId ? String(info.postId) : null;
    if (!postId || postId === lastAutoPostId) return;
    lastAutoPostId = postId;
    if (autoExtractTimer) win.clearTimeout(autoExtractTimer);
    autoExtractTimer = win.setTimeout(() => loadPost(postId), 200);
  }

  async function navigateEmbed(text = null) {
    if (!naia) return;
    const value = String(text ?? addressInput?.value ?? '').trim();
    setBusy(true);
    setStatus('이동 중...', 'busy');
    try {
      const res = await naia.danbooruNavigate(value);
      if (res && res.ok) {
        if (addressInput && res.url) addressInput.value = res.url;
        setStatus('', 'muted');
      } else {
        setStatus((res && res.error) || '이동 실패', 'error');
      }
    } catch (error) {
      setStatus(error.message || '이동 실패', 'error');
    } finally {
      setBusy(false);
    }
  }

  function attachEmbed() {
    if (!embedMode || embedActive) return;
    embedActive = true;
    const rect = currentViewRect() || {x: 0, y: 0, width: 0, height: 0};
    naia.danbooruAttach(rect);
    if (typeof naia.onDanbooruDidNavigate === 'function') {
      unsubscribeNav = naia.onDanbooruDidNavigate(onDidNavigate);
    }
    boundsListener = () => scheduleReportBounds();
    win.addEventListener('resize', boundsListener, true);
    win.addEventListener('scroll', boundsListener, true);
    // Track late layout/reflow after the panel opens.
    win.requestAnimationFrame(() => win.requestAnimationFrame(reportBounds));
  }

  function detachEmbed() {
    if (!embedMode || !embedActive) return;
    embedActive = false;
    if (boundsRaf) {
      win.cancelAnimationFrame(boundsRaf);
      boundsRaf = 0;
    }
    if (autoExtractTimer) {
      win.clearTimeout(autoExtractTimer);
      autoExtractTimer = 0;
    }
    if (boundsListener) {
      win.removeEventListener('resize', boundsListener, true);
      win.removeEventListener('scroll', boundsListener, true);
      boundsListener = null;
    }
    if (typeof unsubscribeNav === 'function') {
      unsubscribeNav();
      unsubscribeNav = null;
    }
    try { naia.danbooruDetach(); } catch (_error) {}
  }

  function embedDialogHtml() {
    return `
      <div class="danbooru-tool-dialog danbooru-embed">
        <header class="danbooru-tool-header">
          <div>
            <div class="danbooru-tool-kicker">Danbooru</div>
            <h2>Danbooru Browser</h2>
          </div>
          <button type="button" class="danbooru-close-btn" data-danbooru-close aria-label="Close">×</button>
        </header>
        <div class="danbooru-embed-body">
          <div class="danbooru-embed-left">
            <div class="danbooru-embed-toolbar">
              <button type="button" class="danbooru-nav-btn" data-danbooru-back data-danbooru-busy-control aria-label="Back">←</button>
              <button type="button" class="danbooru-nav-btn" data-danbooru-forward data-danbooru-busy-control aria-label="Forward">→</button>
              <button type="button" class="danbooru-nav-btn" data-danbooru-reload data-danbooru-busy-control aria-label="Reload">⟳</button>
              <input class="danbooru-address-input" data-danbooru-address data-danbooru-busy-control placeholder="URL, post ID, or tag query">
              <button type="button" class="danbooru-nav-btn danbooru-go-btn" data-danbooru-go data-danbooru-busy-control>이동</button>
            </div>
            <div class="danbooru-view-region" data-danbooru-view-region></div>
          </div>
          <div class="danbooru-embed-right">
            <div class="danbooru-status" data-danbooru-status></div>
            <div class="danbooru-results" data-danbooru-results></div>
          </div>
        </div>
      </div>`;
  }

  function lookupDialogHtml() {
    return `
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
      </div>`;
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('section');
    panel.className = 'danbooru-tool-panel';
    if (embedMode) panel.classList.add('danbooru-tool-panel-embed');
    panel.innerHTML = embedMode ? embedDialogHtml() : lookupDialogHtml();
    document.body.append(panel);
    queryInput = panel.querySelector('[data-danbooru-query]');
    addressInput = panel.querySelector('[data-danbooru-address]');
    viewRegion = panel.querySelector('[data-danbooru-view-region]');
    statusEl = panel.querySelector('[data-danbooru-status]');
    resultEl = panel.querySelector('[data-danbooru-results]');
    renderEmpty(embedMode ? '포스트를 열면 자동으로 태그를 읽습니다.' : undefined);

    panel.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof win.Element)) return;
      if (target.closest('[data-danbooru-close]')) {
        closePanel();
      } else if (target.closest('[data-danbooru-load]')) {
        loadPost();
      } else if (target.closest('[data-danbooru-open-web]')) {
        openExternalBrowser();
      } else if (target.closest('[data-danbooru-back]')) {
        naia?.danbooruBack();
      } else if (target.closest('[data-danbooru-forward]')) {
        naia?.danbooruForward();
      } else if (target.closest('[data-danbooru-reload]')) {
        naia?.danbooruReload();
      } else if (target.closest('[data-danbooru-go]')) {
        navigateEmbed();
      } else if (target.closest('[data-danbooru-apply-prompt]')) {
        applyPrompt();
      } else {
        const tag = target.closest('[data-danbooru-tag]');
        if (tag) {
          const value = tag.dataset.danbooruTag || '';
          if (embedMode) {
            // Danbooru tag search uses underscores within a tag ('blue hair' -> 'blue_hair').
            const tagQuery = value.trim().replace(/\s+/g, '_');
            if (addressInput) addressInput.value = tagQuery;
            navigateEmbed(tagQuery);
          } else if (queryInput) {
            queryInput.value = value;
            queryInput.focus();
          }
        }
      }
    });
    queryInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') loadPost();
      if (event.key === 'Escape') closePanel();
    });
    addressInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') navigateEmbed();
      if (event.key === 'Escape') closePanel();
    });
    return panel;
  }

  function openPanel({query = ''} = {}) {
    ensurePanel();
    if (queryInput && query) queryInput.value = query;
    if (embedMode && addressInput && query) addressInput.value = query;
    panel.hidden = false;
    panel.classList.add('open');
    if (embedMode) {
      attachEmbed();
      setStatus('포스트를 열면 자동으로 태그를 읽습니다.', 'muted');
      if (query) navigateEmbed(query);
    } else {
      queryInput?.focus();
      setStatus('Ready', 'muted');
    }
    return true;
  }

  function closePanel() {
    if (!panel) return;
    detachEmbed();
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
