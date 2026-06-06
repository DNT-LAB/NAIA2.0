// Ollama Local Assistant popup — anchored into the right result pane.
// 상태/제어는 백엔드 프록시(/api/ollama/*) 경유 — 프론트가 직접 localhost:11434를
// 찌르면 폰/LAN/Cloudflared 세션에서는 그 기기 자신의 localhost를 가리켜 오동작한다.
// Dev0714 ollama_module의 3상태(미설치/서버OFF/연결됨) + 설치 안내(ollama.com) 패턴.

const DEFAULT_ENDPOINT = 'http://localhost:11434/v1';
const DEFAULT_MODEL = 'hf.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q4_K_M';
const RUN_COMMAND = `ollama run ${DEFAULT_MODEL}`;
const DOWNLOAD_PAGE = 'https://ollama.com/download';

export function createOllamaAssistantPopup({
  document,
  window: win = window,
  showToast = () => {},
  escHtml = value => String(value ?? ''),
  openUrlInSystemBrowser = null,
}) {
  let popup = null;
  let onResize = null;
  let pollTimer = null;
  let busy = false;

  function pick(selector) {
    return popup ? popup.querySelector(selector) : null;
  }

  function stopPolling() {
    if (pollTimer) {
      win.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function close() {
    stopPolling();
    if (onResize) {
      win.removeEventListener('resize', onResize);
      onResize = null;
    }
    if (popup) {
      popup.remove();
      popup = null;
    }
  }

  function setStatus(text, type = '') {
    const status = pick('.ollama-assistant-status');
    if (!status) return;
    status.className = 'ollama-assistant-status' + (type ? ' ' + type : '');
    status.textContent = text || '';
  }

  function setBadge(text, tone) {
    const badge = pick('.ollama-assistant-badge');
    if (!badge) return;
    badge.className = 'ollama-assistant-badge' + (tone ? ' ' + tone : '');
    badge.textContent = text || '';
  }

  function position() {
    if (!popup) return;
    const pw = popup.offsetWidth;
    const ph = popup.offsetHeight;
    const margin = 8;
    // 데스크톱: 우측 결과 영역에 배치 — 런처 버튼 옆에 띄우면 프롬프트
    // 칼럼을 가리므로 결과 패널 좌상단(여백 16px)을 기본 위치로 쓴다.
    const pane = document.querySelector('.right-tab-pane.active')
      || document.getElementById('rightTabResult');
    const paneRect = pane ? pane.getBoundingClientRect() : null;
    if (paneRect && win.innerWidth >= 768 && paneRect.width >= pw + 32) {
      const paneMargin = 16;
      const left = Math.max(margin, Math.min(paneRect.left + paneMargin, win.innerWidth - pw - margin));
      const top = Math.max(margin, Math.min(paneRect.top + paneMargin, win.innerHeight - ph - margin));
      popup.style.left = `${Math.round(left)}px`;
      popup.style.top = `${Math.round(top)}px`;
      return;
    }
    // 폴백(모바일/좁은 화면): 기존 런처 버튼 앵커.
    const btn = document.getElementById('ollamaAssistantBtn');
    const rect = btn ? btn.getBoundingClientRect() : null;
    let left = rect ? (rect.right - pw) : (win.innerWidth - pw - 16);
    left = Math.max(margin, Math.min(left, win.innerWidth - pw - margin));
    let top = rect ? (rect.bottom + margin) : 48;
    if (top + ph > win.innerHeight - margin && rect) top = rect.top - ph - margin;
    top = Math.max(margin, Math.min(top, win.innerHeight - ph - margin));
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  async function copyText(text, label) {
    try {
      if (!win.navigator?.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await win.navigator.clipboard.writeText(text);
      showToast(`${label} 복사됨`, 'success');
    } catch (error) {
      showToast('클립보드 복사 실패', 'error');
    }
  }

  function openDownloadPage() {
    if (typeof openUrlInSystemBrowser === 'function') {
      openUrlInSystemBrowser(DOWNLOAD_PAGE);
      return;
    }
    win.open(DOWNLOAD_PAGE, '_blank', 'noopener');
  }

  function renderActions(html) {
    const actions = pick('.ollama-assistant-actions');
    if (actions) actions.innerHTML = html;
  }

  function setProgress(percent, visible) {
    const wrap = pick('.ollama-assistant-progress');
    const fill = pick('.ollama-assistant-progress-fill');
    if (!wrap || !fill) return;
    wrap.classList.toggle('hidden', !visible);
    fill.style.width = `${Math.max(0, Math.min(100, Number(percent) || 0))}%`;
  }

  async function fetchJson(url, options) {
    const response = await win.fetch(url, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    return {status: response.status, payload: payload || {}};
  }

  // ------------------------------------------------------------------
  // 상태 머신: 확인 중 → 미설치 / 서버 OFF / 실행 중(모델 유무)
  // ------------------------------------------------------------------

  async function refreshStatus(fresh = false) {
    if (!popup) return;
    setBadge('확인 중…', '');
    setStatus('Ollama 상태를 확인하는 중입니다.');
    renderActions('');
    setProgress(0, false);
    let data = null;
    try {
      // fresh=1(다시 확인): 백엔드 CLI 프로브 캐시 우회 — 방금 설치한 Ollama가 즉시 잡힌다.
      const {payload} = await fetchJson(`/api/ollama/status?model=${encodeURIComponent(DEFAULT_MODEL)}&fresh=${fresh ? 1 : 0}`);
      data = payload;
    } catch (error) {
      setBadge('확인 실패', 'err');
      setStatus('백엔드에 연결할 수 없습니다.', 'error');
      return;
    }
    if (!popup) return;
    if (!data || data.ok === false) {
      setBadge('확인 실패', 'err');
      setStatus(String(data?.error || 'Ollama 상태를 확인하지 못했습니다.'), 'error');
      return;
    }
    if (!data.installed) {
      setBadge('Ollama 미설치', 'err');
      setStatus('이 PC에 Ollama가 없습니다. 설치 후 "다시 확인"을 누르세요.');
      renderActions(`
        <button type="button" class="ollama-assistant-action" data-act="install">Ollama 설치 페이지 열기</button>
        <button type="button" class="ollama-assistant-action secondary" data-act="recheck">다시 확인</button>`);
      bindActions();
      position();
      return;
    }
    const canControl = data.control_allowed !== false;
    if (!data.running) {
      setBadge('설치됨 · 서버 꺼짐', 'warn');
      setStatus(canControl
        ? 'Ollama는 설치되어 있지만 서버가 꺼져 있습니다.'
        : '서버 시작은 NAIA가 실행 중인 PC에서만 가능합니다.');
      renderActions(canControl ? `
        <button type="button" class="ollama-assistant-action" data-act="start-server">서버 시작</button>
        <button type="button" class="ollama-assistant-action secondary" data-act="recheck">다시 확인</button>` : `
        <button type="button" class="ollama-assistant-action secondary" data-act="recheck">다시 확인</button>`);
      bindActions();
      position();
      return;
    }
    // 서버 실행 중 — 다운로드가 진행 중이면 이어서 폴링.
    const pull = (await fetchJson('/api/ollama/pull/status')).payload;
    if (pull && pull.active) {
      enterPullMode();
      return;
    }
    if (!data.model_installed) {
      setBadge(`실행 중${data.version ? ' · ' + escHtml(data.version) : ''}`, 'ok');
      setStatus(canControl
        ? '서버는 켜져 있지만 대상 모델이 없습니다. 다운로드하세요 (수 GB).'
        : '대상 모델이 없습니다 — 다운로드는 NAIA가 실행 중인 PC에서 시작하세요.');
      renderActions(canControl ? `
        <button type="button" class="ollama-assistant-action" data-act="pull">모델 다운로드</button>
        <button type="button" class="ollama-assistant-action secondary" data-act="copy-run">실행 명령 복사</button>` : `
        <button type="button" class="ollama-assistant-action secondary" data-act="copy-run">실행 명령 복사</button>`);
    } else {
      setBadge(`실행 중 · 모델 준비됨 ✓`, 'ok');
      setStatus(`모델 ${data.models?.length || 0}개 설치됨 — 연결 UI는 다음 업데이트에서 제공됩니다.`);
      renderActions(`
        <button type="button" class="ollama-assistant-action" data-act="copy-run">실행 명령 복사</button>
        <button type="button" class="ollama-assistant-action secondary" data-act="copy-endpoint">엔드포인트 복사</button>`);
    }
    bindActions();
    position();
  }

  async function startServer() {
    if (busy) return;
    busy = true;
    setBadge('서버 시작 중…', 'warn');
    setStatus('ollama serve를 시작하고 응답을 기다립니다 (최대 10초).');
    renderActions('');
    try {
      const {status, payload} = await fetchJson('/api/ollama/server/start', {method: 'POST'});
      if (status === 403) {
        showToast(payload.error || 'NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
      } else if (!payload.ok) {
        showToast(payload.error || '서버 시작 실패', 'error');
      }
    } catch (error) {
      showToast('서버 시작 요청 실패', 'error');
    } finally {
      busy = false;
      refreshStatus();
    }
  }

  async function startPull() {
    if (busy) return;
    busy = true;
    try {
      const {status, payload} = await fetchJson('/api/ollama/pull', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model: DEFAULT_MODEL}),
      });
      if (status === 403) {
        showToast(payload.error || 'NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
        return;
      }
      enterPullMode();
    } catch (error) {
      showToast('다운로드 시작 실패', 'error');
    } finally {
      busy = false;
    }
  }

  function enterPullMode() {
    setBadge('모델 다운로드 중…', 'warn');
    renderActions(`
      <button type="button" class="ollama-assistant-action secondary" data-act="cancel-pull">다운로드 취소</button>`);
    bindActions();
    setProgress(0, true);
    position();
    stopPolling();
    pollTimer = win.setInterval(async () => {
      if (!popup) {
        stopPolling();
        return;
      }
      let pull = null;
      try {
        pull = (await fetchJson('/api/ollama/pull/status')).payload;
      } catch (error) {
        return; // 일시 오류 — 다음 틱에 재시도
      }
      if (!popup || !pull) return;
      if (pull.active) {
        const size = pull.total_mb > 0 ? ` (${pull.completed_mb}/${pull.total_mb} MB)` : '';
        setStatus(`${pull.status || '다운로드 중...'}${size}`);
        setProgress(pull.percent, true);
        return;
      }
      stopPolling();
      setProgress(pull.done ? 100 : 0, false);
      if (pull.error) {
        showToast(`모델 다운로드 실패: ${pull.error}`, 'error');
      } else if (pull.done) {
        showToast('모델 다운로드 완료', 'success');
      }
      refreshStatus();
    }, 1000);
  }

  async function cancelPull() {
    try {
      const {status, payload} = await fetchJson('/api/ollama/pull/cancel', {method: 'POST'});
      if (status === 403) {
        showToast(payload.error || '취소는 NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
      }
    } catch (error) { /* 폴링이 상태를 회수 */ }
  }

  function bindActions() {
    const actions = pick('.ollama-assistant-actions');
    if (!actions) return;
    actions.querySelectorAll('[data-act]').forEach(button => {
      button.addEventListener('click', () => {
        const act = button.dataset.act;
        if (act === 'install') openDownloadPage();
        else if (act === 'recheck') refreshStatus(true);
        else if (act === 'start-server') startServer();
        else if (act === 'pull') startPull();
        else if (act === 'cancel-pull') cancelPull();
        else if (act === 'copy-run') copyText(RUN_COMMAND, '실행 명령');
        else if (act === 'copy-endpoint') copyText(DEFAULT_ENDPOINT, '엔드포인트');
      });
    });
  }

  function open() {
    close();
    popup = document.createElement('div');
    popup.className = 'ollama-assistant-popup';
    popup.innerHTML = `
      <div class="ollama-assistant-pop-header">
        <span class="ollama-assistant-pop-title">Ollama · Local Assistant</span>
        <span class="ollama-assistant-badge"></span>
        <button type="button" class="ollama-assistant-pop-x" aria-label="닫기">&times;</button>
      </div>
      <div class="ollama-assistant-pop-body">
        <div class="ollama-assistant-field">
          <span class="ollama-assistant-fld-label">Endpoint</span>
          <code>${escHtml(DEFAULT_ENDPOINT)}</code>
        </div>
        <div class="ollama-assistant-field">
          <span class="ollama-assistant-fld-label">Model</span>
          <code>${escHtml(DEFAULT_MODEL)}</code>
        </div>
        <div class="ollama-assistant-progress hidden"><div class="ollama-assistant-progress-fill"></div></div>
        <div class="ollama-assistant-actions"></div>
        <div class="ollama-assistant-status"></div>
      </div>`;
    document.body.appendChild(popup);

    pick('.ollama-assistant-pop-x')?.addEventListener('click', close);

    position();
    win.requestAnimationFrame(() => position());
    win.setTimeout(() => position(), 120);
    onResize = () => position();
    win.addEventListener('resize', onResize);

    refreshStatus();
  }

  return {open, close};
}
