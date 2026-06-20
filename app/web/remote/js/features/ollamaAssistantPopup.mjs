// Ollama Local Assistant popup — anchored into the right result pane.
// 상태/제어는 백엔드 프록시(/api/ollama/*) 경유 — 프론트가 직접 localhost:11434를
// 찌르면 폰/LAN/Cloudflared 세션에서는 그 기기 자신의 localhost를 가리켜 오동작한다.
// Dev0714 ollama_module의 3상태(미설치/서버OFF/연결됨) + 설치 안내(ollama.com) 패턴.

import {
  DEFAULT_MODEL,
  fetchOllamaConnection,
  postOllamaConnectionModel,
  setOllamaModelSelectOptions,
  shortOllamaModel,
} from './ollamaModelSelect.mjs?v=20260618-related-curated';

const DEFAULT_ENDPOINT = 'http://localhost:11434/v1';
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
  let assistMode = 'manual';   // 'fast'(원샷) | 'manual'(파이프라인) — 기본 Manual
  let assistRating = 'auto'; // 'auto'|'g'|'s'|'q'|'e' — 'auto'면 max_rating 생략→문장 수위 추론(기본)
  let assistLevel = 'rich';  // 'concise'|'standard'|'rich'|'max' — 분량/창의성, 기본 풍부(rich)
  let assistSolo = false;    // Solo 강제 — 켜면 1girl_solo 파티션 + 'solo' 태그
  let datasetReady = false;  // 이벤트 데이터셋(B 실조합 참조) 설치 여부
  // 고급 연결 설정 — 셀프호스팅(cloudflared 등) Ollama 엔드포인트/모델. 백엔드
  // /api/ollama/connection(루프백)에서 받아 런타임으로 쓴다. 하드코딩 상수는
  // 폴백/플레이스홀더로만 남긴다.
  let connModel = DEFAULT_MODEL;   // assist/status/pull/표시에 쓰는 현재 모델
  let connEndpointBase = '';       // 현재 base URL(슬래시·/v1 없음) — 에디터/복사용
  let connIsCustom = false;        // 원격(비-로컬) 엔드포인트 여부
  let canConfigure = false;        // GET /connection 성공(=루프백 호스트)일 때만 ⚙ 노출
  let installedModels = [];
  let curatedModels = [];

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

  // 비-ASCII(한글) 모델 경로 경고 배너 — 백엔드 status.path_warning이 있을 때만 표시.
  function setWarning(text) {
    const el = pick('.ollama-assistant-warning');
    if (!el) return;
    const msg = String(text || '').trim();
    el.textContent = msg ? '⚠ ' + msg : '';
    el.classList.toggle('hidden', !msg);
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
          // 모델 미전송 — 백엔드(연결 설정)가 SSOT(self.default_model). 원격
          // 클라이언트가 stale 기본 모델을 강제 송신하던 버그 차단.
          text, mode: assistMode,
          options: {
            // 'auto'면 max_rating을 보내지 않는다 → 백엔드 _resolve_max_rating이 문장
            // 수위로 추론(한국어 행위어 포함). 명시 등급은 그대로 상한 고정(통제권).
            ...(assistRating && assistRating !== 'auto' ? {max_rating: assistRating} : {}),
            level: assistLevel, solo: assistSolo,
          },
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

  // 기록 복원 — 기록 행 클릭 시 입력:결과 쌍을 "방금 변환을 마친 것처럼" 되살린다
  // (사용자 요청; 이전 동작=결과 복사만). 결과 영역은 renderAssistResult를 재사용해
  // 액션 버튼(프롬프트에 추가/복사)까지 동일하게 살아난다. 기록에는 최종 프롬프트만
  // 저장되므로 태그 분해/번역 줄은 재현하지 않는다. 등급/분량 버튼은 메타가 유효한
  // 값일 때만 동기화(메타의 rating은 실행 당시 *해석된* 등급 — auto로 돌렸다면 복원
  // 후 명시 등급이 된다). mode는 실행 전략이라 복원하지 않는다(manual 전환은 데이터셋
  // 다운로드 등 부수효과가 있는 클릭 핸들러 전용).
  function _syncAssistButtons(selector, datasetKey, want) {
    let hit = null;
    const btns = popup.querySelectorAll(selector);
    btns.forEach(b => { if (String(b.dataset[datasetKey] || '') === want) hit = b; });
    if (!hit) return false;
    btns.forEach(b => b.classList.toggle('active', b === hit));
    return true;
  }

  function restoreFromHistory(rec) {
    if (!rec || !popup) return;
    // 변환 진행 중 복원 금지 — 진행 중 런이 끝나면 결과 영역을 덮어써서
    // 복원된 입력과 새 결과가 불일치 쌍으로 남는다(경합).
    if (assistBusy) { showToast('변환 진행 중에는 복원할 수 없습니다.', 'info'); return; }
    const input = pick('.ollama-assist-input');
    if (input) input.value = String(rec.source || '');
    const meta = (rec && rec.meta) || {};
    const rating = String(meta.rating || '').toLowerCase() || 'auto';
    if (_syncAssistButtons('.ollama-assist-rating-btn', 'rating', rating)) assistRating = rating;
    const level = String(meta.level || '');
    if (level && _syncAssistButtons('.ollama-assist-level-btn', 'level', level)) assistLevel = level;
    renderAssistResult({ok: true, prompt: String(rec.translated || '')});
    position();
    showToast('기록 복원됨 — 입력·결과가 되살아났습니다', 'success');
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
      historyPanelReady = import('./translationHistoryPanel.mjs?v=20260612-histrestore2')
        .then(({createTranslationHistoryPanel}) => {
          historyPanel = createTranslationHistoryPanel({
            document, window: win, showToast, escHtml,
            onVisibilityChange: (visible) => _setHistoryBtnActive(visible),
            onRestore: restoreFromHistory,
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

  // ------------------------------------------------------------------
  // 고급 연결 설정 — 셀프호스팅(cloudflared 등) Ollama 엔드포인트/모델.
  // 백엔드 /api/ollama/connection(루프백 전용)에서 받고 저장한다. 원격 클라이언트는
  // 403을 받아 ⚙ 버튼이 숨겨진다(호스트의 프록시 타깃을 바꿀 수 없게).
  // ------------------------------------------------------------------
  async function fetchConnection() {
    try {
      const {status, payload} = await fetchOllamaConnection(win);
      if (status === 403 || !payload || payload.ok === false) {
        canConfigure = false;  // 비-루프백 클라이언트 — 설정 불가, ⚙ 숨김
        updateCfgButton();
        updateModelSelect();
        return;
      }
      canConfigure = true;
      connEndpointBase = String(payload.endpoint || '');
      connModel = String(payload.model || '') || DEFAULT_MODEL;
      connIsCustom = !!payload.is_custom;
    } catch (error) {
      canConfigure = false;
    }
    updateCfgButton();
    updateModelNote();
    updateModelSelect();
  }

  function updateCfgButton() {
    const btn = pick('.ollama-assistant-pop-cfg');
    if (btn) btn.classList.toggle('hidden', !canConfigure);
  }

  function updateModelNote() {
    const note = pick('.ollama-assist-modelnote');
    if (!note) return;
    // connModel은 status.model(공개 sanitized에도 포함)에서 채워지므로 원격
    // 클라이언트도 실제 구성 모델명을 표시한다(엔드포인트 URL은 비노출 유지).
    const remote = connIsCustom ? ' <span class="ollama-conn-remote">· 원격</span>' : '';
    note.innerHTML = `Model: <code>${escHtml(shortOllamaModel(connModel))}</code>${remote}`;
  }

  function updateModelSelect() {
    const select = pick('.ollama-assist-model-select');
    setOllamaModelSelectOptions(select, {
      models: installedModels,
      currentModel: connModel,
      disabled: !canConfigure,
    });
  }

  function curatedModelActions(canControl) {
    const items = Array.isArray(curatedModels) ? curatedModels : [];
    if (!items.length) return '';
    return items.map(item => {
      const model = String(item?.model || '').trim();
      const label = escHtml(String(item?.label || shortOllamaModel(model)));
      const size = item?.size ? ` · ${escHtml(String(item.size))}` : '';
      const state = item?.installed ? '설치됨' : '미설치';
      const button = (!item?.installed && canControl && model)
        ? `<button type="button" class="ollama-assistant-action" data-act="pull" data-model="${escHtml(model)}">${label}${size} 다운로드</button>`
        : `<span class="ollama-assistant-natural-line">${label}${size} · ${escHtml(state)}</span>`;
      return button;
    }).join('');
  }

  function toggleConnEditor(forceOpen) {
    const editor = pick('.ollama-conn-editor');
    if (!editor) return;
    const willOpen = forceOpen != null ? forceOpen : editor.classList.contains('hidden');
    if (willOpen) {
      // 현재값 프리필 — 기본(로컬)이면 빈 칸으로 둬 placeholder가 기본값을 보이게.
      const epIn = pick('.ollama-conn-endpoint');
      const mdIn = pick('.ollama-conn-model');
      if (epIn) epIn.value = connIsCustom ? connEndpointBase : '';
      if (mdIn) mdIn.value = (connModel && connModel !== DEFAULT_MODEL) ? connModel : '';
    }
    editor.classList.toggle('hidden', !willOpen);
    position();
  }

  async function saveConnection() {
    const epIn = pick('.ollama-conn-endpoint');
    const mdIn = pick('.ollama-conn-model');
    const endpoint = String(epIn?.value || '').trim();
    const model = String(mdIn?.value || '').trim();
    const saveBtn = pick('.ollama-conn-save');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '저장 중…'; }
    try {
      const {status, payload} = await fetchJson('/api/ollama/connection', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({endpoint, model}),
      });
      if (status === 403) {
        showToast(payload.error || 'NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
        return;
      }
      if (!payload || payload.ok === false) {
        showToast(payload?.error || '연결 설정 저장 실패', 'error');
        return;
      }
      connEndpointBase = String(payload.endpoint || '');
      connModel = String(payload.model || '') || DEFAULT_MODEL;
      connIsCustom = !!payload.is_custom;
      updateModelNote();
      updateModelSelect();
      toggleConnEditor(false);
      showToast(connIsCustom ? '원격 Ollama 엔드포인트로 전환했습니다.' : '기본 로컬 Ollama로 설정했습니다.', 'success');
      refreshStatus(true);
    } catch (error) {
      showToast('연결 설정 요청 실패', 'error');
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '저장'; }
    }
  }

  async function saveSelectedModel(model) {
    const selected = String(model || '').trim();
    if (!selected || !canConfigure) {
      updateModelSelect();
      return;
    }
    const select = pick('.ollama-assist-model-select');
    if (select) select.disabled = true;
    try {
      const {status, payload} = await postOllamaConnectionModel(win, {
        endpoint: connEndpointBase,
        model: selected,
      });
      if (status === 403) {
        showToast(payload.error || 'NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
        return;
      }
      if (!payload || payload.ok === false) {
        showToast(payload?.error || '모델 설정 저장 실패', 'error');
        return;
      }
      connEndpointBase = String(payload.endpoint || '');
      connModel = String(payload.model || '') || selected || DEFAULT_MODEL;
      connIsCustom = !!payload.is_custom;
      updateModelNote();
      updateModelSelect();
      showToast('Ollama 모델 설정을 저장했습니다.', 'success');
      refreshStatus(true);
    } catch (error) {
      showToast('모델 설정 요청 실패', 'error');
    } finally {
      updateModelSelect();
    }
  }

  async function resetConnection() {
    // 빈 endpoint/model 저장 = 기본값(로컬·기본 모델) 복귀.
    const epIn = pick('.ollama-conn-endpoint');
    const mdIn = pick('.ollama-conn-model');
    if (epIn) epIn.value = '';
    if (mdIn) mdIn.value = '';
    await saveConnection();
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
    setWarning('');  // 경로가 고쳐졌을 수 있으니 매 갱신 시 초기화 후 재설정.
    await fetchConnection();  // 현재 엔드포인트/모델 동기화(⚙ 노출 여부·connModel 포함)
    let data = null;
    try {
      // fresh=1(다시 확인): 백엔드 CLI 프로브 캐시 우회 — 방금 설치한 Ollama가 즉시 잡힌다.
      // model 미전송 — 백엔드 SSOT 기준으로 model_installed 판정(원격도 구성 모델 기준).
      const {payload} = await fetchJson(`/api/ollama/status?fresh=${fresh ? 1 : 0}`);
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
    // 모델은 백엔드 SSOT — status가 알려주는 실제 구성 모델로 표시를 맞춘다(원격 포함).
    installedModels = Array.isArray(data.models) ? data.models.map(item => String(item || '')).filter(Boolean) : [];
    curatedModels = Array.isArray(data.curated) ? data.curated : [];
    if (data.model) { connModel = String(data.model); }
    updateModelNote();
    updateModelSelect();
    // 비-ASCII(한글) 모델 경로 경고는 설치/실행/모델 상태와 무관하게 항상 노출한다
    // (모델 로딩 단계에서 터지는 llama-server 에러를 미리 안내). 원격 클라이언트는
    // path_warning 미포함 → 자동 숨김.
    setWarning(data.path_warning || '');
    // 원격(커스텀) 엔드포인트가 응답하지 않으면 '미설치/설치 페이지'가 아니라 연결
    // 문제로 안내한다 — 원격 서버는 NAIA가 켤 수 없으므로 '서버 시작' 버튼도 없다.
    if (data.is_custom_endpoint && !data.running) {
      setBadge('원격 연결 안 됨', 'err');
      setStatus('원격 Ollama 서버에 연결할 수 없습니다. 주소를 확인하거나 원격 호스트에서 직접 실행하세요. (⚙ 고급에서 주소 변경)');
      renderActions(`
        <button type="button" class="ollama-assistant-action secondary" data-act="recheck">다시 확인</button>`);
      bindActions();
      position();
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
      const curated = curatedModelActions(canControl);
      renderActions((curated ? curated : '')
        + `<button type="button" class="ollama-assistant-action secondary" data-act="copy-run">실행 명령 복사</button>`);
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

  async function startPull(model = '') {
    if (busy) return;
    busy = true;
    const targetModel = String(model || connModel || '').trim();
    try {
      // 다운로드는 활성 모델을 바꾸지 않는다 — pull은 {model}로 직접 받고, 설치 완료 후
      // 사용자가 셀렉터에서 선택해 활성화한다(미설치 모델로 활성 모델이 바뀌는 footgun 방지).
      const {status, payload} = await fetchJson('/api/ollama/pull', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(targetModel ? {model: targetModel} : {}),
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
        else if (act === 'pull') startPull(button.dataset.model || '');
        else if (act === 'cancel-pull') cancelPull();
        else if (act === 'dataset') startDataset();
        else if (act === 'copy-run') copyText('ollama run ' + connModel, '실행 명령');
        else if (act === 'copy-endpoint') copyText((connEndpointBase || 'http://localhost:11434') + '/v1', '엔드포인트');
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
        <button type="button" class="ollama-assistant-pop-cfg hidden" aria-label="고급 연결 설정" title="고급 — Ollama 엔드포인트/모델 변경">⚙</button>
        <button type="button" class="ollama-assistant-pop-min" aria-label="최소화">&minus;</button>
        <button type="button" class="ollama-assistant-pop-x" aria-label="닫기">&times;</button>
      </div>
      <div class="ollama-assistant-pop-body">
        <div class="ollama-conn-editor hidden">
          <div class="ollama-conn-title">고급 연결 — 셀프호스팅 Ollama</div>
          <label class="ollama-conn-label">엔드포인트 URL</label>
          <input type="text" class="ollama-conn-endpoint" spellcheck="false" autocomplete="off" placeholder="http://127.0.0.1:11434 (비우면 기본 로컬)" />
          <label class="ollama-conn-label">모델</label>
          <input type="text" class="ollama-conn-model" spellcheck="false" autocomplete="off" placeholder="비우면 기본 모델" />
          <div class="ollama-conn-hint">cloudflared 등으로 호스팅한 Ollama 주소를 넣으면 NAIA가 그쪽으로 프록시합니다. (이 PC에서만 설정 가능)</div>
          <div class="ollama-conn-actions">
            <button type="button" class="ollama-assistant-action ollama-conn-save">저장</button>
            <button type="button" class="ollama-assistant-action secondary ollama-conn-reset">기본값</button>
            <button type="button" class="ollama-assistant-action secondary ollama-conn-cancel">취소</button>
          </div>
        </div>
        <div class="ollama-assist hidden">
          <div class="ollama-assist-modelnote">Model: <code>${escHtml(shortOllamaModel(connModel))}</code></div>
          <div class="ollama-model-select-row">
            <label class="ollama-model-select-label">Model</label>
            <select class="ollama-model-select ollama-assist-model-select" aria-label="Ollama 모델 선택"></select>
          </div>
          <textarea class="ollama-assist-input" rows="6" placeholder="예: 교복 입은 소녀가 창가에 앉아 웃고 있는 장면"></textarea>
          <div class="ollama-assist-controls">
            <div class="ollama-assist-mode" role="group" aria-label="변환 모드">
              <button type="button" class="ollama-assist-mode-btn" data-mode="fast" title="원샷 — 빠름(1호출)">Fast</button>
              <button type="button" class="ollama-assist-mode-btn active" data-mode="manual" title="파이프라인 — 정밀(다단계 참조)">Manual</button>
            </div>
            <button type="button" class="ollama-assistant-action ollama-assist-run">태그로 변환</button>
            <button type="button" class="ollama-assist-history-btn" title="변환 기록 보기 (우측 패널)" aria-pressed="false">🕘 기록</button>
          </div>
          <div class="ollama-assist-knobs">
            <span class="ollama-assist-knob-label">등급</span>
            <div class="ollama-assist-rating" role="group" aria-label="등급 (콘텐츠 수위)">
              <button type="button" class="ollama-assist-rating-btn active" data-rating="auto" title="자동 — 문장의 수위를 보고 등급을 정함(권장). 직접 고르면 상한 고정">자동</button>
              <button type="button" class="ollama-assist-rating-btn" data-rating="g" title="General — 성적 요소 완전 차단">G</button>
              <button type="button" class="ollama-assist-rating-btn" data-rating="s" title="Sensitive — 약간의 노출 + 분위기(직접 노출/행위는 순화)">S</button>
              <button type="button" class="ollama-assist-rating-btn" data-rating="q" title="Questionable — 직접 노출 + 성행위 암시">Q</button>
              <button type="button" class="ollama-assist-rating-btn" data-rating="e" title="Explicit — 직접 묘사">E</button>
            </div>
            <span class="ollama-assist-knob-label">분량</span>
            <div class="ollama-assist-level" role="group" aria-label="분량">
              <button type="button" class="ollama-assist-level-btn" data-level="concise" title="태그만 간결히 (보완·이벤트참조 없음)">간결</button>
              <button type="button" class="ollama-assist-level-btn" data-level="standard" title="표준 (보완 3·이벤트참조 2)">표준</button>
              <button type="button" class="ollama-assist-level-btn active" data-level="rich" title="풍부 (보완 7·이벤트참조 4·긴 자연어)">풍부</button>
              <button type="button" class="ollama-assist-level-btn" data-level="max" title="최대 (보완 12·이벤트참조 6·가장 긴 자연어)">최대</button>
            </div>
            <button type="button" class="ollama-assist-solo-btn" aria-pressed="false" title="Solo 강제 — solo가 명시되지 않으면 1girl/1boy로, 켜면 1girl_solo + solo 태그">Solo</button>
          </div>
          <div class="ollama-assist-result"></div>
        </div>
        <div class="ollama-assistant-progress hidden"><div class="ollama-assistant-progress-fill"></div></div>
        <div class="ollama-assistant-warning hidden"></div>
        <div class="ollama-assistant-actions ollama-main-actions"></div>
        <div class="ollama-assistant-status"></div>
      </div>`;
    document.body.appendChild(popup);

    pick('.ollama-assistant-pop-x')?.addEventListener('click', close);
    pick('.ollama-assistant-pop-min')?.addEventListener('click', toggleMinimize);
    pick('.ollama-assist-model-select')?.addEventListener('change', event => {
      void saveSelectedModel(event.target.value);
    });
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
        assistRating = btn.dataset.rating || 'auto';
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
    // 고급 연결 설정(⚙) — stopPropagation으로 헤더 클릭(최소화 복귀)과 분리.
    pick('.ollama-assistant-pop-cfg')?.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleConnEditor();
    });
    pick('.ollama-conn-save')?.addEventListener('click', saveConnection);
    pick('.ollama-conn-reset')?.addEventListener('click', resetConnection);
    pick('.ollama-conn-cancel')?.addEventListener('click', () => toggleConnEditor(false));

    position();
    win.requestAnimationFrame(() => position());
    win.setTimeout(() => position(), 120);
    onResize = () => position();
    win.addEventListener('resize', onResize);

    refreshStatus();
  }

  // [Ollama] 버튼 토글용 — 현재 펼쳐져 보이는지(숨김/미생성이 아닌지).
  function isOpen() {
    return !!(popup && popup.style.display !== 'none');
  }

  return {open, close, destroy, isOpen};
}
