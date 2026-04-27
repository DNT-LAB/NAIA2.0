export function createCloudflaredControls({
  document,
  getWs,
  WebSocket,
  getApiStatus,
  navigator,
  showToast,
}) {
  const section = document.getElementById('setupCloudflaredSection');
  const statusEl = document.getElementById('setupCloudflaredStatus');
  const connectBtn = document.getElementById('setupCloudflaredConnect');
  const disconnectBtn = document.getElementById('setupCloudflaredDisconnect');
  const linkEl = document.getElementById('setupCloudflaredLink');
  const copyBtn = document.getElementById('setupCloudflaredCopy');

  function render(m) {
    if (!section) return;
    const allowed = m.cloudflared_control_allowed === true;
    section.classList.toggle('hidden', !allowed);
    if (!allowed) return;

    const active = !!m.cloudflared_active;
    const url = m.cloudflared_url || '';
    const status = m.cloudflared_status_text || (active ? 'Connected' : 'Disconnected');
    const isBusy = active && !url;

    if (statusEl) statusEl.textContent = status;
    if (connectBtn) connectBtn.disabled = active;
    if (disconnectBtn) disconnectBtn.disabled = !active && !isBusy;

    if (linkEl) {
      if (url) {
        linkEl.classList.remove('hidden');
        linkEl.href = url;
        linkEl.textContent = url;
      } else {
        linkEl.classList.add('hidden');
        linkEl.removeAttribute('href');
        linkEl.textContent = '';
      }
    }
    if (copyBtn) copyBtn.classList.toggle('hidden', !url);
  }

  function setEnabled(enabled) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'set_cloudflared_enabled', enabled: !!enabled }));
  }

  function copyUrl() {
    const status = getApiStatus() || {};
    const url = status.cloudflared_url || '';
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      showToast('Copied to clipboard', 'success');
    }).catch(() => {
      showToast('Copy failed', 'error');
    });
  }

  return {
    render,
    setEnabled,
    copyUrl,
  };
}
