// Ollama Local Assistant popup — anchored into the right result pane.
// 상태/제어는 백엔드 프록시(/api/ollama/*) 경유 — 프론트가 직접 localhost:11434를
// 찌르면 폰/LAN/Cloudflared 세션에서는 그 기기 자신의 localhost를 가리켜 오동작한다.
// Dev0714 ollama_module의 3상태(미설치/서버OFF/연결됨) + 설치 안내(ollama.com) 패턴.

const DEFAULT_ENDPOINT = 'http://localhost:11434/v1';
const DEFAULT_MODEL = 'hf.co/HauhauCS/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive:IQ3_M';

// 헤더 표기용 짧은 모델 라벨 — "<리포 끝 이름>:<양자화>"만 남긴다.
function _shortModel(full) {
  const s = String(full || '');
  const colon = s.lastIndexOf(':');
  const quant = colon >= 0 ? s.slice(colon + 1) : '';
  let name = colon >= 0 ? s.slice(0, colon) : s;
  name = name.split('/').pop() || name;
  return quant ? `${name}:${quant}` : name;
}
const RUN_COMMAND = `ollama run ${DEFAULT_MODEL}`;
const DOWNLOAD_PAGE = 'https://ollama.com/download';

export function createOllamaAssistantPopup({
  document,
  window: win = window,
  showToast = () => {},
  escHtml = value => String(value ?? ''),
  openUrlInSystemBrowser = null,
  onInsertTags = null,
}) {
  let popup = null;
  let onResize = null;
  let pollTimer = null;
  let busy = false;
  let assistMode = 'fast';   // 'fast'(원샷) | 'manual'(파이프라인)
  let assistRating = 's';    // 'g'|'s'|'q'|'e' — 최대 등급(상한 클램프)
  let assistLevel = 'standard';  // 'concise'|'standard'|'rich' — 분량/창의성
  let assistSolo = false;    // Solo 강제 — 켜면 1girl_solo 파티션 + 'solo' 태그
  let datasetReady = false;  // 이벤트 데이터셋(B 실조합 참조) 설치 여부

  function pick(selector) {
    return popup ? popup.querySelector(selector) : null;
  }

  function stopPolling() {
    if (pollTimer) {
      win.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // 닫기 = 숨김(DOM 유지) — 다시 펼쳐도 입력/결과/등급/분량 컨텍스트가 보존된다.
  function close() {
    stopPolling();
    if (onResize) {
      win.removeEventListener('resize', onResize);
      onResize = null;
    }
    hideHistory();
    if (popup) popup.style.display = 'none';
  }

  // 완전 파괴(런처 재초기화 등) — 평시엔 쓰지 않는다.
  function destroy() {
    close();
    if (historyPanel) { historyPanel.destroy(); historyPanel = null; historyPanelReady = null; }
    if (popup) { popup.remove(); popup = null; }
  }

  function toggleMinimize() {
    if (!popup) return;
    popup.classList.toggle('minimized');
    // 최소화하면 우측 도킹 패널도 숨긴다(펼치면 사용자가 [기록]으로 다시 연다).
    if (popup.classList.contains('minimized')) hideHistory();
    position();
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

  // ------------------------------------------------------------------
  // 태그 어시스트 — 무상태 2호출 파이프라인(/api/ollama/assist) 프런트.
  // LLM은 개념 추출/후보 선택만, 태그 진실은 NAIA 인덱스(백엔드)가 보장.
  // ------------------------------------------------------------------
  let assistBusy = false;

  function setAssistVisible(visible) {
    const section = pick('.ollama-assist');
    if (section) section.classList.toggle('hidden', !visible);
  }

  function renderAssistResult(data) {
    const out = pick('.ollama-assist-result');
    if (!out) return;
    out.textContent = '';
    if (!data || data.ok === false) {
      const err = document.createElement('div');
      err.className = 'ollama-assist-error';
      err.textContent = String(data?.error || '변환에 실패했습니다.');
      out.appendChild(err);
      return;
    }
    const prompt = String(data.prompt || '');
    const tags = (data.selected || []).map(i => i.tag)
      .concat((data.boosted || []).map(i => i.tag))
      .concat((data.enhanced || []).map(i => i.tag));

    // 사전 번역된 영어를 작게 표시(어떤 문장으로 변환됐는지 투명하게).
    if (data.translated) {
      const tr = document.createElement('div');
      tr.className = 'ollama-assist-translated';
      tr.textContent = `번역: ${data.translated}`;
      out.appendChild(tr);
    }

    // 결과 = 복사 쉬운 plain text(프롬프트 + 자연어 합본). 사용자 요청.
    const ta = document.createElement('textarea');
    ta.className = 'ollama-assist-output';
    ta.readOnly = true;
    ta.rows = Math.min(6, Math.max(2, Math.ceil(prompt.length / 48)));
    ta.value = prompt;
    out.appendChild(ta);

    // 추론된 태그만 따로 나열 (Danbooru/e621) — 한 줄 plain text.
    if (tags.length) {
      const tagLine = document.createElement('div');
      tagLine.className = 'ollama-assist-tagline';
      tagLine.innerHTML = `<span class="ollama-assist-tagline-label">태그</span><code>${escHtml(tags.join(', '))}</code>`;
      out.appendChild(tagLine);
    }

    if ((data.selected || []).length || prompt) {
      const row = document.createElement('div');
      row.className = 'ollama-assistant-actions';
      const insertBtn = document.createElement('button');
      insertBtn.type = 'button';
      insertBtn.className = 'ollama-assistant-action';
      insertBtn.textContent = '프롬프트에 추가';
      insertBtn.addEventListener('click', () => {
        if (typeof onInsertTags === 'function') onInsertTags(prompt);
        else copyText(prompt, '결과');
      });
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'ollama-assistant-action secondary';
      copyBtn.textContent = '복사';
      copyBtn.addEventListener('click', () => copyText(prompt, '결과'));
      const copyTagsBtn = document.createElement('button');
      copyTagsBtn.type = 'button';
      copyTagsBtn.className = 'ollama-assistant-action secondary';
      copyTagsBtn.textContent = '태그만 복사';
      copyTagsBtn.addEventListener('click', () => copyText(tags.join(', '), '태그'));
      row.appendChild(insertBtn);
      row.appendChild(copyBtn);
      row.appendChild(copyTagsBtn);
      out.appendChild(row);
    }
  }

  async function runAssist() {
    if (assistBusy) return;
    const input = pick('.ollama-assist-input');
    const runBtn = pick('.ollama-assist-run');
    const text = String(input?.value || '').trim();
    if (!text) {
      showToast('변환할 내용을 입력하세요.', 'info');
      return;
    }
    assistBusy = true;
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = '변환 중…'; }
    const out = pick('.ollama-assist-result');
    const stopProgress = startAssistProgress(out);
    try {
      const {payload} = await fetchJson('/api/ollama/assist', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          text, model: DEFAULT_MODEL, mode: assistMode,
          options: {max_rating: assistRating, level: assistLevel, solo: assistSolo},
        }),
      });
      stopProgress();
      renderAssistResult(payload);
    } catch (error) {
      stopProgress();
      renderAssistResult({ok: false, error: '백엔드 요청 실패'});
    } finally {
      assistBusy = false;
      if (runBtn) { runBtn.disabled = false; runBtn.textContent = '태그로 변환'; }
      position();
    }
  }

  // 변환 기록 — Ollama 팝업 우측에 도킹되는 2단 플로팅 패널(translationHistoryPanel).
  // [기록] 버튼이 토글한다. 패널은 첫 클릭 때 지연 로드(쓰지 않는 사용자는 비용 0).
  let historyPanel = null;
  let historyPanelReady = null;

  function _setHistoryBtnActive(on) {
    const btn = pick('.ollama-assist-history-btn');
    if (btn) {
      btn.classList.toggle('active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }

  function ensureHistoryPanel() {
    if (historyPanel) return Promise.resolve(historyPanel);
    if (!historyPanelReady) {
      historyPanelReady = import('./translationHistoryPanel.mjs?v=20260607-xhist3')
        .then(({createTranslationHistoryPanel}) => {
          historyPanel = createTranslationHistoryPanel({
            document, window: win, showToast, escHtml,
            onVisibilityChange: (visible) => _setHistoryBtnActive(visible),
          });
          return historyPanel;
        })
        .catch(error => {
          console.error('Failed to load translation history panel', error);
          return null;
        });
    }
    return historyPanelReady;
  }

  async function toggleHistory() {
    const p = await ensureHistoryPanel();
    if (!p) { showToast('변환 기록 패널을 불러오지 못했습니다.', 'error'); return; }
    p.toggle();
  }

  // 팝업이 닫히거나 최소화되면 우측 도킹 패널도 함께 숨긴다(고아 플로팅 방지).
  function hideHistory() {
    if (historyPanel) historyPanel.close();
  }

  // 진행 표시 — FE가 경과초(자체 시계, 부드럽게)를 틱하고 백엔드 단계를 폴링한다.
  // "단계 N/총 · <단계명> · <경과>s". 시간 추정치는 표기하지 않는다(사용자/GPU별 편차 큼).
  function startAssistProgress(out) {
    const t0 = (win.performance?.now ? win.performance.now() : Date.now());
    let stage = '';
    let step = 0;
    let total = 0;
    let stopped = false;
    const elapsed = () => {
      const now = (win.performance?.now ? win.performance.now() : Date.now());
      return Math.max(0, (now - t0) / 1000);
    };
    const render = () => {
      if (!out || stopped) return;
      const secs = elapsed().toFixed(1);
      const label = stage || (assistMode === 'fast' ? '생성' : '개념 추출');
      const counter = (step && total) ? `단계 ${step}/${total} · ` : '단계 1 · ';
      out.textContent = `${counter}${label} 중… · ${secs}s`;
    };
    render();
    const tick = win.setInterval(render, 200);
    const poll = win.setInterval(async () => {
      if (stopped) return;
      try {
        const {payload} = await fetchJson('/api/ollama/assist/progress');
        if (payload && payload.active) {
          stage = String(payload.stage || stage);
          step = Number(payload.step || step) || step;
          total = Number(payload.total || total) || total;
        }
      } catch (error) { /* 폴링 실패는 무시 — 자체 경과 시계는 계속 */ }
    }, 450);
    return () => {
      stopped = true;
      win.clearInterval(tick);
      win.clearInterval(poll);
    };
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
    // 어시스트 블록 내부에도 .ollama-assistant-actions(스타일 공유)가 있으므로
    // 메인 액션 컨테이너는 전용 클래스로 정확히 지정한다.
    const actions = pick('.ollama-main-actions');
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
    setAssistVisible(false);
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
      setStatus('아래에 원하는 장면을 한국어로 적으면 실제 태그로 변환합니다.');
      setAssistVisible(true);
      renderActions('');  // 어시스트 UI만 — 복사 버튼 제거(사용자 요청)
      // 브릿지: 이벤트 데이터셋이 받아지는 중이면 진행 UI를 이어받는다. 미설치라도
      // 별도 버튼 없이 — 모델 다운로드와 병렬로 받거나, Manual 선택 시 자동 시작.
      const ds = await fetchDatasetState();
      if (ds && ds.active) { enterDatasetMode(); bindActions(); position(); return; }
      datasetReady = !!(ds && ds.ready);
      if (!datasetReady) {
        setStatus('Manual 모드(실조합 참조)는 이벤트 데이터셋(~400MB)을 자동으로 받습니다. Fast는 즉시 사용.');
      }
    }
    bindActions();
    position();
  }

  // ------------------------------------------------------------------
  // 이벤트 데이터셋 브릿지 — Manual 모드 실조합 참조용. 모델 다운로드 후 후속.
  // ------------------------------------------------------------------
  async function fetchDatasetState() {
    try {
      const {payload} = await fetchJson('/api/ollama/dataset');
      const avail = payload.availability || {};
      return {
        active: !!payload.active,
        ready: avail.main === 'ready',
        percent: Number(payload.percent || 0),
        message: payload.message || '',
        error: payload.error || '',
        done: !!payload.done,
      };
    } catch (error) {
      return null;
    }
  }

  // 미설치 시 데이터셋 다운로드를 백그라운드로 시작(진행 UI 인계 안 함, fire 후 무시).
  // 모델 다운로드와 병렬로 받을 때 사용 — 진행은 모델 우선, 모델 완료 후 인계된다.
  async function kickDatasetIfMissing() {
    try {
      const ds = await fetchDatasetState();
      if (ds && !ds.ready && !ds.active) {
        await fetchJson('/api/ollama/dataset', {method: 'POST'});
      }
    } catch (error) { /* 베스트에포트 */ }
  }

  async function startDataset({showProgress = true} = {}) {
    if (busy) return;
    busy = true;
    try {
      const {status, payload} = await fetchJson('/api/ollama/dataset', {method: 'POST'});
      if (status === 403) { showToast(payload.error || 'NAIA가 실행 중인 PC에서만 가능합니다.', 'error'); return; }
      if (showProgress) enterDatasetMode();
    } catch (error) {
      showToast('데이터셋 다운로드 시작 실패', 'error');
    } finally {
      busy = false;
    }
  }

  function enterDatasetMode() {
    setBadge('이벤트 데이터셋 다운로드 중…', 'warn');
    setStatus('실조합 참조용 조합 데이터(~400MB)를 받는 중입니다.');
    renderActions('');
    setProgress(0, true);
    setAssistVisible(true);
    position();
    stopPolling();
    pollTimer = win.setInterval(async () => {
      if (!popup) { stopPolling(); return; }
      const ds = await fetchDatasetState();
      if (!popup || !ds) return;
      if (ds.active) {
        setStatus(`${ds.message || '데이터셋 다운로드 중...'} (${ds.percent}%)`);
        setProgress(ds.percent, true);
        return;
      }
      stopPolling();
      setProgress(ds.ready ? 100 : 0, false);
      datasetReady = !!ds.ready;
      if (ds.error) showToast(`데이터셋 다운로드 실패: ${ds.error}`, 'error');
      else if (ds.ready) showToast('이벤트 데이터셋 준비 완료 — Manual 실조합 참조 가능', 'success');
      refreshStatus();
    }, 1500);
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
      // 모델과 함께 이벤트 데이터셋(조합)도 병렬로 받아둔다 — 미설치일 때만
      // 백그라운드로 시작(진행 UI는 모델 우선, 모델 완료 후 데이터셋으로 인계).
      kickDatasetIfMissing();
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
        else if (act === 'dataset') startDataset();
        else if (act === 'copy-run') copyText(RUN_COMMAND, '실행 명령');
        else if (act === 'copy-endpoint') copyText(DEFAULT_ENDPOINT, '엔드포인트');
      });
    });
  }

  function open() {
    // 이미 만들어져 있으면 컨텍스트(입력/결과/등급/분량)를 유지한 채 다시 보인다.
    if (popup) {
      popup.style.display = '';
      popup.classList.remove('minimized');
      if (!onResize) { onResize = () => position(); win.addEventListener('resize', onResize); }
      position();
      win.requestAnimationFrame(() => position());
      refreshStatus();
      return;
    }
    popup = document.createElement('div');
    popup.className = 'ollama-assistant-popup';
    popup.innerHTML = `
      <div class="ollama-assistant-pop-header">
        <span class="ollama-assistant-pop-title">Ollama</span>
        <span class="ollama-assistant-pop-fulltitle"> · Local Assistant</span>
        <span class="ollama-assistant-badge"></span>
        <button type="button" class="ollama-assistant-pop-min" aria-label="최소화">&minus;</button>
        <button type="button" class="ollama-assistant-pop-x" aria-label="닫기">&times;</button>
      </div>
      <div class="ollama-assistant-pop-body">
        <div class="ollama-assist hidden">
          <div class="ollama-assist-modelnote">Model: <code>${escHtml(_shortModel(DEFAULT_MODEL))}</code></div>
          <textarea class="ollama-assist-input" rows="6" placeholder="예: 교복 입은 소녀가 창가에 앉아 웃고 있는 장면"></textarea>
          <div class="ollama-assist-controls">
            <div class="ollama-assist-mode" role="group" aria-label="변환 모드">
              <button type="button" class="ollama-assist-mode-btn active" data-mode="fast" title="원샷 — 빠름(1호출)">Fast</button>
              <button type="button" class="ollama-assist-mode-btn" data-mode="manual" title="파이프라인 — 정밀(다단계 참조)">Manual</button>
            </div>
            <button type="button" class="ollama-assistant-action ollama-assist-run">태그로 변환</button>
            <button type="button" class="ollama-assist-history-btn" title="변환 기록 보기 (우측 패널)" aria-pressed="false">🕘 기록</button>
          </div>
          <div class="ollama-assist-knobs">
            <span class="ollama-assist-knob-label">등급</span>
            <div class="ollama-assist-rating" role="group" aria-label="최대 등급">
              <button type="button" class="ollama-assist-rating-btn" data-rating="g" title="General — 전연령">G</button>
              <button type="button" class="ollama-assist-rating-btn active" data-rating="s" title="Sensitive — 노출/수영복 허용">S</button>
              <button type="button" class="ollama-assist-rating-btn" data-rating="q" title="Questionable — 선정적">Q</button>
              <button type="button" class="ollama-assist-rating-btn" data-rating="e" title="Explicit — 노골적 NSFW">E</button>
            </div>
            <span class="ollama-assist-knob-label">분량</span>
            <div class="ollama-assist-level" role="group" aria-label="분량">
              <button type="button" class="ollama-assist-level-btn" data-level="concise" title="태그만 간결히 (보완·이벤트참조 없음)">간결</button>
              <button type="button" class="ollama-assist-level-btn active" data-level="standard" title="표준 (보완 3·이벤트참조 2)">표준</button>
              <button type="button" class="ollama-assist-level-btn" data-level="rich" title="풍부 (보완 7·이벤트참조 4·긴 자연어)">풍부</button>
              <button type="button" class="ollama-assist-level-btn" data-level="max" title="최대 (보완 12·이벤트참조 6·가장 긴 자연어)">최대</button>
            </div>
            <button type="button" class="ollama-assist-solo-btn" aria-pressed="false" title="Solo 강제 — solo가 명시되지 않으면 1girl/1boy로, 켜면 1girl_solo + solo 태그">Solo</button>
          </div>
          <div class="ollama-assist-result"></div>
        </div>
        <div class="ollama-assistant-progress hidden"><div class="ollama-assistant-progress-fill"></div></div>
        <div class="ollama-assistant-actions ollama-main-actions"></div>
        <div class="ollama-assistant-status"></div>
      </div>`;
    document.body.appendChild(popup);

    pick('.ollama-assistant-pop-x')?.addEventListener('click', close);
    pick('.ollama-assistant-pop-min')?.addEventListener('click', toggleMinimize);
    // 최소화 상태에서 헤더(타이틀) 클릭 시 다시 펼친다.
    pick('.ollama-assistant-pop-header')?.addEventListener('click', (e) => {
      if (popup.classList.contains('minimized') &&
          !e.target.closest('.ollama-assistant-pop-x') &&
          !e.target.closest('.ollama-assistant-pop-min')) {
        toggleMinimize();
      }
    });
    pick('.ollama-assist-run')?.addEventListener('click', runAssist);
    pick('.ollama-assist-history-btn')?.addEventListener('click', toggleHistory);
    popup.querySelectorAll('.ollama-assist-mode-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        assistMode = btn.dataset.mode === 'manual' ? 'manual' : 'fast';
        popup.querySelectorAll('.ollama-assist-mode-btn').forEach(b =>
          b.classList.toggle('active', b === btn));
        // Manual 선택 시 데이터셋이 없으면 자동 다운로드 시작(사용자 요청).
        if (assistMode === 'manual' && !datasetReady) {
          const ds = await fetchDatasetState();
          datasetReady = !!(ds && ds.ready);
          if (ds && ds.active) { enterDatasetMode(); }
          else if (!datasetReady) {
            showToast('실조합 참조용 이벤트 데이터셋(~400MB)을 받기 시작합니다.', 'info');
            startDataset({showProgress: true});
          }
        }
      });
    });
    popup.querySelectorAll('.ollama-assist-rating-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        assistRating = btn.dataset.rating || 's';
        popup.querySelectorAll('.ollama-assist-rating-btn').forEach(b =>
          b.classList.toggle('active', b === btn));
      });
    });
    popup.querySelectorAll('.ollama-assist-level-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        assistLevel = btn.dataset.level || 'standard';
        popup.querySelectorAll('.ollama-assist-level-btn').forEach(b =>
          b.classList.toggle('active', b === btn));
      });
    });
    pick('.ollama-assist-solo-btn')?.addEventListener('click', (e) => {
      assistSolo = !assistSolo;
      const b = e.currentTarget;
      b.classList.toggle('active', assistSolo);
      b.setAttribute('aria-pressed', assistSolo ? 'true' : 'false');
    });

    position();
    win.requestAnimationFrame(() => position());
    win.setTimeout(() => position(), 120);
    onResize = () => position();
    win.addEventListener('resize', onResize);

    refreshStatus();
  }

  return {open, close, destroy};
}
