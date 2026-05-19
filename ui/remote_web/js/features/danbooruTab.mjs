export function createDanbooruBrowserController({
  document,
  fetch: fetchFn = window.fetch.bind(window),
  showToast,
}) {
  const queryInput = document.getElementById('danbooruQuery');
  const openBtn = document.getElementById('danbooruLoadBtn');
  const openNativeBtn = document.getElementById('danbooruOpenBrowserBtn');
  const statusEl = document.getElementById('danbooruStatus');

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setBusy(busy) {
    [openBtn, openNativeBtn, queryInput].forEach(el => {
      if (el) el.disabled = !!busy;
    });
  }

  async function openBrowser({automatic = false, query: explicitQuery = null} = {}) {
    const query = String(explicitQuery ?? queryInput?.value ?? '').trim();
    setBusy(true);
    setStatus('단부루 웹을 여는 중...', 'busy');
    try {
      const response = await fetchFn('/api/danbooru/browser/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (data.url) {
        window.open(data.url, '_blank', 'noopener,noreferrer');
      }
      setStatus('단부루 웹을 열었습니다.', 'ok');
      if (!automatic && showToast) showToast('단부루 웹을 열었습니다', 'success');
      return true;
    } catch (error) {
      console.error('Danbooru browser open failed', error);
      setStatus(error.message || '단부루 웹을 열지 못했습니다', 'error');
      if (!automatic && showToast) showToast(error.message || '단부루 웹을 열지 못했습니다', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  }

  function bind() {
    openBtn?.addEventListener('click', () => openBrowser());
    openNativeBtn?.addEventListener('click', () => openBrowser());
    queryInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') openBrowser();
    });
    setStatus('단부루 웹을 열 준비가 되었습니다.', 'muted');
  }

  bind();

  return {
    openBrowser,
  };
}

export const createDanbooruTabController = createDanbooruBrowserController;
