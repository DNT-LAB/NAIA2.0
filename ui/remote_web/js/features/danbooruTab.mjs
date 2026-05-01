export function createDanbooruTabController({
  document,
  escHtml,
  showToast,
  setPromptText,
  requestGenerate,
}) {
  const queryInput = document.getElementById('danbooruQuery');
  const loadBtn = document.getElementById('danbooruLoadBtn');
  const applyBtn = document.getElementById('danbooruApplyBtn');
  const generateBtn = document.getElementById('danbooruGenerateBtn');
  const statusEl = document.getElementById('danbooruStatus');
  const preview = document.getElementById('danbooruPreview');
  const previewEmpty = document.getElementById('danbooruPreviewEmpty');
  const metaEl = document.getElementById('danbooruMeta');
  const tagsEl = document.getElementById('danbooruTags');
  const promptEl = document.getElementById('danbooruPrompt');
  let lastPost = null;

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setBusy(busy) {
    if (loadBtn) loadBtn.disabled = !!busy;
    if (queryInput) queryInput.disabled = !!busy;
  }

  function fallbackPrompt(post) {
    const tags = post?.tags || {};
    const general = Array.isArray(tags.general) ? tags.general : [];
    return general.join(', ');
  }

  function currentPrompt() {
    return String(lastPost?.prompt || fallbackPrompt(lastPost) || '').trim();
  }

  function renderTags(tags = {}) {
    if (!tagsEl) return;
    const order = [
      ['artist', 'Artist'],
      ['copyright', 'Copyright'],
      ['character', 'Character'],
      ['general', 'General'],
      ['meta', 'Meta'],
    ];
    tagsEl.innerHTML = order.map(([key, label]) => {
      const values = Array.isArray(tags[key]) ? tags[key] : [];
      const body = values.length ? values.join(', ') : '—';
      return `
        <div class="danbooru-tag-group">
          <div class="danbooru-tag-title">${label} · ${values.length}</div>
          <div class="danbooru-tag-list">${escHtml(body)}</div>
        </div>
      `;
    }).join('');
  }

  function renderPost(post) {
    lastPost = post || null;
    const hasPost = !!lastPost;
    if (applyBtn) applyBtn.disabled = !hasPost;
    if (generateBtn) generateBtn.disabled = !hasPost;

    if (preview) {
      preview.classList.toggle('show', !!lastPost?.preview_url);
      if (lastPost?.preview_url) preview.src = lastPost.preview_url;
      else preview.removeAttribute('src');
    }
    if (previewEmpty) previewEmpty.style.display = lastPost?.preview_url ? 'none' : '';

    if (metaEl) {
      if (!lastPost) metaEl.textContent = '';
      else {
        const rating = lastPost.rating ? `rating ${lastPost.rating}` : 'rating —';
        const score = lastPost.score !== undefined && lastPost.score !== null ? `score ${lastPost.score}` : 'score —';
        metaEl.innerHTML = `
          <div><b>#${escHtml(String(lastPost.post_id || ''))}</b> · ${escHtml(rating)} · ${escHtml(score)}</div>
          <div>${lastPost.post_url ? `<a href="${escHtml(lastPost.post_url)}" target="_blank" rel="noopener noreferrer">${escHtml(lastPost.post_url)}</a>` : ''}</div>
        `;
      }
    }
    renderTags(lastPost?.tags || {});
    if (promptEl) promptEl.textContent = currentPrompt() || 'No prompt preview.';
  }

  async function load() {
    const query = String(queryInput?.value || '').trim();
    if (!query) {
      setStatus('Enter a Danbooru post URL or ID.', 'error');
      return;
    }
    setBusy(true);
    setStatus('Loading Danbooru post...', 'busy');
    try {
      const response = await fetch('/api/danbooru/post', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      renderPost(data);
      setStatus(`Loaded Danbooru post #${data.post_id}`, 'ok');
    } catch (error) {
      console.error('Danbooru lookup failed', error);
      renderPost(null);
      setStatus(error.message || 'Danbooru lookup failed', 'error');
      if (showToast) showToast(error.message || 'Danbooru lookup failed', 'error');
    } finally {
      setBusy(false);
    }
  }

  function applyPrompt() {
    const prompt = currentPrompt();
    if (!prompt) {
      if (showToast) showToast('No Danbooru prompt is available', 'error');
      return false;
    }
    setPromptText(prompt);
    if (showToast) showToast('Danbooru prompt applied', 'success');
    return true;
  }

  function generate() {
    if (!applyPrompt()) return;
    requestGenerate();
  }

  function bind() {
    loadBtn?.addEventListener('click', load);
    applyBtn?.addEventListener('click', applyPrompt);
    generateBtn?.addEventListener('click', generate);
    queryInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') load();
    });
    renderPost(null);
  }

  bind();

  return {
    load,
    applyPrompt,
    generate,
    renderPost,
  };
}
