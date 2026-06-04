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
  const spinnerEl = document.getElementById('setupCloudflaredSpinner');
  const connectLabel = connectBtn ? connectBtn.textContent : 'Cloudflared 연결';
  // Optimistic flag so the spinner appears the instant the user clicks Connect, before the
  // backend's first "connecting" api_status round-trips. Cleared once a resolved status arrives.
  let optimisticConnecting = false;

  function localizeStatus(status, active) {
    if (!status) return active ? '연결됨' : '연결 안 됨';
    return status
      .replace(/^Connected\b/, '연결됨')
      .replace(/^Disconnected\b/, '연결 안 됨');
  }

  function applyBusyUi(busy) {
    if (connectBtn) {
      connectBtn.disabled = busy;
      connectBtn.textContent = busy ? '연결 중…' : connectLabel;
      connectBtn.classList.toggle('is-connecting', busy);
    }
    if (spinnerEl) spinnerEl.classList.toggle('hidden', !busy);
    if (busy && statusEl) statusEl.textContent = 'Cloudflared 연결 중…';
  }

  function render(m) {
    if (!section) return;
    const allowed = m.cloudflared_control_allowed === true;
    section.classList.toggle('hidden', !allowed);
    if (!allowed) {
      optimisticConnecting = false;
      return;
    }

    const active = !!m.cloudflared_active;
    const url = m.cloudflared_url || '';
    // A resolved status (got a URL = connected, or inactive = idle/failed) clears the optimism.
    if (url || !active) optimisticConnecting = false;
    // "connecting" = the tunnel is marked active but no public URL has arrived yet.
    const busy = (active && !url) || optimisticConnecting;

    applyBusyUi(busy);
    if (!busy && statusEl) statusEl.textContent = localizeStatus(m.cloudflared_status_text, active);
    if (disconnectBtn) disconnectBtn.disabled = !active && !busy;

    if (linkEl) {
      if (url && !busy) {
        linkEl.classList.remove('hidden');
        linkEl.href = url;
        linkEl.textContent = url;
      } else {
        linkEl.classList.add('hidden');
        linkEl.removeAttribute('href');
        linkEl.textContent = '';
      }
    }
    if (copyBtn) copyBtn.classList.toggle('hidden', !url || busy);
  }

  function setEnabled(enabled) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (enabled) {
      // Instant feedback on click — the backend also emits a "connecting" api_status, but this
      // covers the round-trip so the button never looks like it did nothing.
      optimisticConnecting = true;
      applyBusyUi(true);
      if (disconnectBtn) disconnectBtn.disabled = false;
    } else {
      optimisticConnecting = false;
    }
    ws.send(JSON.stringify({ type: 'set_cloudflared_enabled', enabled: !!enabled }));
  }

  function copyUrl() {
    const status = getApiStatus() || {};
    const url = status.cloudflared_url || '';
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      showToast('클립보드에 복사했습니다.', 'success');
    }).catch(() => {
      showToast('복사에 실패했습니다.', 'error');
    });
  }

  return {
    render,
    setEnabled,
    copyUrl,
  };
}
