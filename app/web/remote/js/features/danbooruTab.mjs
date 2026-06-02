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
  onGenerateFromPrompt = null,
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

  // Minimize-to-island state (the panel can collapse to a floating pill near
  // the Auto Save control while preserving the embedded view's page state).
  let minimized = false;
  let islandEl = null;
  let islandReposition = null;
  let islandRaf = 0;

  function escHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function tagGroupHtml(label, values) {
    const list = Array.isArray(values) ? values : [];
    // Group prompt = every tag in this group joined as a comma prompt (full list, not the
    // display-capped slice) so the copy button always yields the complete group.
    const groupPrompt = list.join(', ');
    const copyBtn = list.length
      ? `<button type="button" class="danbooru-group-copy" data-danbooru-copy-group="${escHtml(groupPrompt)}" title="이 그룹을 프롬프트로 복사" aria-label="Copy ${escHtml(label)} prompt">⧉</button>`
      : '';
    const body = list.length
      ? list.slice(0, 120)
          .map(tag => `<button type="button" class="danbooru-tag" data-danbooru-tag="${escHtml(tag)}">${escHtml(tag)}</button>`)
          .join('')
      : '<span class="danbooru-empty">—</span>';
    return `
      <section class="danbooru-tag-group">
        <h3><span class="danbooru-tag-group-name">${escHtml(label)}</span> <span class="danbooru-tag-count">· ${list.length}</span>${copyBtn}</h3>
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
          <div class="danbooru-result-actions">
            <button type="button" class="danbooru-copy-btn danbooru-apply-btn" data-danbooru-apply-prompt>프롬프트 적용</button>
            ${typeof onGenerateFromPrompt === 'function'
              ? '<button type="button" class="danbooru-gen-btn" data-danbooru-generate title="이 프롬프트로 즉시 이미지 생성">이미지 생성</button>'
              : ''}
          </div>
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
    // Embed mode: crawl tags from the already-loaded view DOM (uses the user's session,
    // Cloudflare-safe) and let the backend normalize them — avoids the backend's own
    // donmai request being reset. Falls back to the server-side fetch if extraction fails.
    let requestBody = {query};
    if (embedMode && naia && typeof naia.danbooruExtractPost === 'function') {
      try {
        const res = await naia.danbooruExtractPost();
        if (res && res.ok && res.extracted) {
          requestBody = {query, extracted: res.extracted};
        }
      } catch (_error) { /* fall back to server-side fetch */ }
    }
    try {
      const response = await fetchFn('/api/danbooru/post', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestBody),
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

  async function copyGroup(value) {
    const text = String(value || '').trim();
    if (!text) {
      if (showToast) showToast('복사할 태그가 없습니다.', 'error');
      return;
    }
    try {
      const clip = win.navigator && win.navigator.clipboard;
      if (clip && typeof clip.writeText === 'function') {
        await clip.writeText(text);
      } else {
        // Fallback for non-secure contexts where navigator.clipboard is absent.
        const scratch = document.createElement('textarea');
        scratch.value = text;
        scratch.style.position = 'fixed';
        scratch.style.opacity = '0';
        document.body.append(scratch);
        scratch.select();
        document.execCommand('copy');
        scratch.remove();
      }
      if (showToast) showToast('프롬프트를 복사했습니다.', 'success');
    } catch (error) {
      console.error('Danbooru group copy failed', error);
      if (showToast) showToast('복사 실패: ' + (error.message || ''), 'error');
    }
  }

  // Mirror of desktop on_generate_with_image_requested: build the prompt from the
  // post, then run it through the host generation pipeline immediately.
  function generateFromPost() {
    const prompt = String(lastPost?.prompt || '').trim();
    if (!prompt) {
      if (showToast) showToast('생성할 Danbooru 프롬프트가 없습니다.', 'error');
      return;
    }
    if (typeof onGenerateFromPrompt !== 'function') {
      applyPrompt();
      return;
    }
    // onGenerateFromPrompt가 false면 생성이 막힌 것(이미 생성 중/연결 없음) — 거짓 성공 토스트 금지.
    const started = onGenerateFromPrompt(prompt) !== false;
    if (showToast) {
      showToast(
        started
          ? 'Danbooru 프롬프트로 이미지 생성을 시작합니다.'
          : '지금은 생성할 수 없습니다 (이미 생성 중이거나 연결이 없습니다).',
        started ? 'success' : 'error',
      );
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

  // ---- Minimize-to-island --------------------------------------------------
  function ensureIsland() {
    if (islandEl) return islandEl;
    islandEl = document.createElement('div');
    islandEl.className = 'danbooru-mini-island';
    islandEl.hidden = true;
    islandEl.innerHTML = `
      <button type="button" class="danbooru-mini-label" data-danbooru-restore title="Danbooru 창 펼치기">📦 Danbooru</button>
      <button type="button" class="danbooru-mini-btn" data-danbooru-restore aria-label="펼치기" title="펼치기">▢</button>
      <button type="button" class="danbooru-mini-btn danbooru-mini-close" data-danbooru-island-close aria-label="닫기" title="닫기">×</button>`;
    islandEl.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof win.Element)) return;
      if (target.closest('[data-danbooru-island-close]')) {
        closePanel();
      } else if (target.closest('[data-danbooru-restore]')) {
        restorePanel();
      }
    });
    document.body.append(islandEl);
    return islandEl;
  }

  function positionIsland() {
    if (!islandEl || islandEl.hidden) return;
    // Top axis: vertically centered in the right tab bar (the topmost toolbar where
    // "브라우저에서 열기" lives); horizontally right-aligned to the Auto Save column.
    const bar = document.querySelector('.right-tab-bar');
    const save = document.getElementById('statsSave');
    const barRect = bar && bar.getBoundingClientRect();
    const saveRect = save && save.getBoundingClientRect();
    if (saveRect && saveRect.width > 0) {
      islandEl.style.right = `${Math.round(Math.max(8, win.innerWidth - saveRect.right))}px`;
    } else {
      islandEl.style.right = '14px';
    }
    islandEl.style.left = 'auto';
    if (barRect && barRect.height > 0) {
      // Center vertically in the bar, clamped so it can never settle off-screen.
      const centered = barRect.top + (barRect.height - islandEl.offsetHeight) / 2;
      const maxTop = win.innerHeight - islandEl.offsetHeight - 8;
      islandEl.style.top = `${Math.max(8, Math.min(Math.round(centered), maxTop))}px`;
    } else {
      islandEl.style.top = '10px';
    }
  }

  function schedulePositionIsland() {
    // Throttle to one reflow per frame — scroll/resize fire in bursts (capture phase
    // catches every scroller), mirroring the embed bounds path's scheduleReportBounds.
    if (islandRaf) win.cancelAnimationFrame(islandRaf);
    islandRaf = win.requestAnimationFrame(() => {
      islandRaf = 0;
      positionIsland();
    });
  }

  function showIsland() {
    ensureIsland();
    islandEl.hidden = false;
    positionIsland();
    if (!islandReposition) {
      islandReposition = () => schedulePositionIsland();
      win.addEventListener('resize', islandReposition, true);
      win.addEventListener('scroll', islandReposition, {capture: true, passive: true});
    }
  }

  function hideIsland() {
    if (islandEl) islandEl.hidden = true;
    if (islandReposition) {
      win.removeEventListener('resize', islandReposition, true);
      win.removeEventListener('scroll', islandReposition, true);
      islandReposition = null;
    }
    if (islandRaf) {
      win.cancelAnimationFrame(islandRaf);
      islandRaf = 0;
    }
  }

  function minimizePanel() {
    if (minimized) return;
    if (!panel || !panel.classList.contains('open')) return;
    minimized = true;
    // Detach the native view (removeChildView preserves its page state) so the
    // floating island and the main UI are unobstructed.
    if (embedMode) detachEmbed();
    panel.classList.remove('open');
    panel.hidden = true;
    showIsland();
  }

  function restorePanel() {
    if (!minimized || !panel) return;
    minimized = false;
    hideIsland();
    panel.hidden = false;
    panel.classList.add('open');
    if (embedMode) attachEmbed();
  }

  function embedDialogHtml() {
    return `
      <div class="danbooru-tool-dialog danbooru-embed">
        <header class="danbooru-tool-header">
          <div>
            <div class="danbooru-tool-kicker">Danbooru</div>
            <h2>Danbooru Browser</h2>
          </div>
          <div class="danbooru-header-actions">
            <button type="button" class="danbooru-min-btn" data-danbooru-minimize aria-label="최소화" title="최소화">–</button>
            <button type="button" class="danbooru-close-btn" data-danbooru-close aria-label="Close">×</button>
          </div>
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
      } else if (target.closest('[data-danbooru-generate]')) {
        generateFromPost();
      } else if (target.closest('[data-danbooru-minimize]')) {
        minimizePanel();
      } else if (target.closest('[data-danbooru-copy-group]')) {
        const copyBtn = target.closest('[data-danbooru-copy-group]');
        copyGroup(copyBtn.dataset.danbooruCopyGroup || '');
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
    minimized = false;
    hideIsland();
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
    minimized = false;
    hideIsland();
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
