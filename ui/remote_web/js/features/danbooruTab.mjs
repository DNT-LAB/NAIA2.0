export function createDanbooruTabController({
  document,
  fetch: fetchFn = window.fetch.bind(window),
  showToast,
}) {
  const queryInput = document.getElementById('danbooruQuery');
  const openBtn = document.getElementById('danbooruLoadBtn');
  const openNativeBtn = document.getElementById('danbooruOpenBrowserBtn');
  const statusEl = document.getElementById('danbooruStatus');
  let openedOnce = false;

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

  async function openBrowser({automatic = false} = {}) {
    const query = String(queryInput?.value || '').trim();
    setBusy(true);
    setStatus('단부루 웹 (Qt) 창을 여는 중...', 'busy');
    try {
      const response = await fetchFn('/api/danbooru/browser/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      openedOnce = true;
      setStatus('단부루 웹 (Qt) 창을 열었습니다.', 'ok');
      if (!automatic && showToast) showToast('단부루 웹 (Qt) 창을 열었습니다', 'success');
      return true;
    } catch (error) {
      console.error('PyQt6 Danbooru browser open failed', error);
      setStatus(error.message || '단부루 웹 (Qt) 창을 열지 못했습니다', 'error');
      if (!automatic && showToast) showToast(error.message || '단부루 웹 (Qt) 창을 열지 못했습니다', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  }

  function onActivated() {
    if (openedOnce) return;
    openBrowser({automatic: true});
  }

  function bind() {
    openBtn?.addEventListener('click', () => openBrowser());
    openNativeBtn?.addEventListener('click', () => openBrowser());
    queryInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') openBrowser();
    });
    setStatus('단부루 웹 (Qt) 창을 열 준비가 되었습니다.', 'muted');
  }

  bind();

  return {
    openBrowser,
    onActivated,
  };
}
