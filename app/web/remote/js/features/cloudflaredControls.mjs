export function createCloudflaredControls({
  document,
  getWs,
  WebSocket,
  getApiStatus,
  navigator,
  showToast,
  openUrlInSystemBrowser = null,
}) {
  const section = document.getElementById('setupCloudflaredSection');
  const lanSection = document.getElementById('setupLanSection');
  const lanLinksEl = document.getElementById('setupLanLinks');
  const statusEl = document.getElementById('setupCloudflaredStatus');
  const connectBtn = document.getElementById('setupCloudflaredConnect');
  const disconnectBtn = document.getElementById('setupCloudflaredDisconnect');
  const linkEl = document.getElementById('setupCloudflaredLink');
  const copyBtn = document.getElementById('setupCloudflaredCopy');
  const spinnerEl = document.getElementById('setupCloudflaredSpinner');
  const connectLabel = connectBtn ? connectBtn.textContent : 'Cloudflared 연결';
  // 터널 링크도 LAN 링크와 동일하게 시스템 브라우저로 — Electron 내부 팝업 방지.
  if (linkEl && typeof openUrlInSystemBrowser === 'function') {
    linkEl.addEventListener('click', (event) => {
      const href = linkEl.getAttribute('href') || '';
      if (!/^https?:\/\//i.test(href)) return;
      event.preventDefault();
      openUrlInSystemBrowser(href);
    });
  }
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

  // 같은 네트워크(LAN) 접속 링크 — Cloudflared 제어와 동일하게 로컬(설정 가능)
  // 클라이언트에게만 표시. 표시 전용이라 별도 동작은 복사뿐이다.
  function renderLan(m, allowed) {
    if (!lanSection || !lanLinksEl) return;
    const urls = Array.isArray(m.lan_urls) ? m.lan_urls.filter(Boolean) : [];
    const show = allowed && urls.length > 0;
    lanSection.classList.toggle('hidden', !show);
    if (!show) {
      lanLinksEl.textContent = '';
      return;
    }
    lanLinksEl.textContent = '';
    urls.forEach(url => {
      const row = document.createElement('div');
      row.className = 'setup-cloudflared-linkrow';
      const link = document.createElement('a');
      link.className = 'setup-cloudflared-link';
      link.href = url;
      link.textContent = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      // Electron 셸에서 그냥 두면 window-open 핸들러가 내부 팝업(새 NAIA 창)을
      // 띄운다 — 시스템 브라우저로 우회(naia-open-browser:). 일반 브라우저에서는
      // 새 탭으로 연다. 헬퍼가 없으면 기본 동작 유지.
      if (typeof openUrlInSystemBrowser === 'function') {
        link.addEventListener('click', (event) => {
          event.preventDefault();
          openUrlInSystemBrowser(url);
        });
      }
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'setup-btn-ghost setup-btn-cloudflared';
      copy.textContent = '복사';
      copy.addEventListener('click', () => {
        navigator.clipboard.writeText(url).then(() => {
          showToast('클립보드에 복사했습니다.', 'success');
        }).catch(() => {
          showToast('복사에 실패했습니다.', 'error');
        });
      });
      row.appendChild(link);
      row.appendChild(copy);
      lanLinksEl.appendChild(row);
    });
  }

  function render(m) {
    if (!section) return;
    const allowed = m.cloudflared_control_allowed === true;
    renderLan(m, allowed);
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
