// Boost v2(llama.cpp · Gemma 4 E2B) 설정 영역 — Auto Boost Settings 팝업 안에서 백엔드가
// llama.cpp 일 때 그려진다. 설정 저장은 PE 모듈(set_module_param 'boost_v2_settings'),
// 상태·모델 다운로드는 /api/boost-v2/* 폴링. style.css 는 건드리지 않는다(기존 PE 팝업 클래스 +
// 인라인) — HEAD 의 CRLF 혼재 함정 때문.
const SECTIONS = [
  ['subject', 'Subject & Action', '인물·의상·표정·행동을 태그+문장으로'],
  ['composition', 'Composition & Angle', '샷·앵글·시야'],
  ['detail', 'Detail & Object', '배경 디테일·소품·질감'],
  ['lighting', 'Lighting', '광원·색온도·그림자'],
  ['quality', 'Quality', '분위기·렌더링 질감 (anime/realistic 같은 매체 태그 금지)'],
];
const POLL_ACTIVE_MS = 1000;
const POLL_IDLE_MS = 5000;

export function createBoostV2Panel({ document, escHtml, setModuleParam, showToast = () => {}, fetchImpl }) {
  const doFetch = fetchImpl || ((...args) => window.fetch(...args));
  // 저장 전 편집 — PE 상태가 다시 밀려와 재렌더돼도 입력을 잃지 않게 붙들어 둔다.
  let draft = null;
  let pollTimer = null;
  let lastStatus = null;
  let mountedRoot = null;
  const boundBodies = new WeakSet();

  function settingsFrom(m) {
    const s = (m && m.boost_v2_settings) || {};
    const sections = {};
    const preferences = {};
    for (const [key] of SECTIONS) {
      sections[key] = !s.sections || s.sections[key] !== false;
      preferences[key] = String((s.preferences && s.preferences[key]) || '');
    }
    return { sections, preferences, device: String(s.device || 'auto') };
  }

  function render(body, m) {
    if (!body) return;
    const saved = settingsFrom(m);
    const view = draft || saved;
    const rows = SECTIONS.map(([key, label, hint]) => `
      <div style="display:grid;grid-template-columns:minmax(150px,auto) 1fr;gap:6px;align-items:center;margin:3px 0">
        <label class="mod-checkbox-item" title="${escHtml(hint)}" style="margin:0">
          <input type="checkbox" data-boost-sec="${key}"${view.sections[key] ? ' checked' : ''}>
          <span class="mod-checkbox-label">${escHtml(label)}</span>
        </label>
        <input class="mod-input" data-boost-pref="${key}" value="${escHtml(view.preferences[key])}"
          placeholder="선호 문구 (어울릴 때만 쓰임)" spellcheck="false" autocomplete="off">
      </div>`).join('');
    body.innerHTML = `
      <div class="mod-boost-block" data-boost-v2-root="1">
        <div class="mod-boost-head"><span class="mod-boost-name">엔진 · 모델</span></div>
        <div data-boost-status style="font-size:12px;line-height:1.6">확인 중…</div>
        <label style="display:flex;gap:6px;align-items:center;font-size:12px;margin-top:6px"
          title="자동 = 외장 GPU > 내장 그래픽 > CPU. GPU 로 띄우지 못하면 엔진이 CPU 로 자동 전환합니다. 바꾸면 곧바로 옮겨 갑니다.">
          <span style="white-space:nowrap">할당 장치</span>
          <select class="mod-select" data-boost-device data-current="${escHtml(view.device)}" style="flex:1">
            <option value="auto"${view.device === 'auto' ? ' selected' : ''}>자동</option>
          </select>
        </label>
        <div data-boost-hw style="font-size:11px;color:var(--text-dim);margin-top:2px"></div>
        <div class="mod-inline-row" data-boost-actions style="margin-top:4px"></div>
        <div class="mod-boost-caption">Ollama 불필요. GPU 는 CPU 가 바쁠 때도 느려지지 않습니다. 모델은 처음 한 번 3.1GB 를 받습니다. 모델 입력에서 색상 태그는 항상 뺍니다.</div>
      </div>
      <div>
        <div class="mod-section-label">섹션 · 선호 문구</div>
        ${rows}
        <div class="mod-boost-caption">끈 섹션은 출력에서 빠집니다. 선호 문구는 장면에 어울릴 때만 쓰도록 모델에 전달됩니다. 결과는 프롬프트 본문 끝(postfix 앞)에 붙습니다.</div>
      </div>
      <div class="mod-inline-row">
        <button class="mod-btn-secondary" data-boost-act="save">Save Boost Settings</button>
        <span data-boost-dirty style="font-size:11px;color:var(--text-dim);margin-left:6px">${draft ? '저장 안 됨' : ''}</span>
      </div>`;
    mountedRoot = body.querySelector('[data-boost-v2-root]');
    // body 는 재렌더돼도 같은 요소다(innerHTML 만 바뀐다) — 리스너는 한 번만 건다.
    if (!boundBodies.has(body)) {
      boundBodies.add(body);
      body.addEventListener('input', onInput);
      body.addEventListener('change', onInput);
      body.addEventListener('click', onClick);
    }
    if (lastStatus) paintStatus(lastStatus);
    schedulePoll(0);
  }

  function readForm(root) {
    const sections = {};
    const preferences = {};
    for (const [key] of SECTIONS) {
      const box = root.querySelector(`[data-boost-sec="${key}"]`);
      const pref = root.querySelector(`[data-boost-pref="${key}"]`);
      sections[key] = !!(box && box.checked);
      preferences[key] = pref ? pref.value : '';
    }
    const device = root.querySelector('[data-boost-device]');
    return { sections, preferences, device: device ? device.value : 'auto' };
  }

  function onInput(event) {
    const target = event.target;
    if (!target || !(target.matches('[data-boost-sec]') || target.matches('[data-boost-pref]') || target.matches('[data-boost-device]'))) return;
    const body = event.currentTarget;
    draft = readForm(body);
    const mark = body.querySelector('[data-boost-dirty]');
    if (mark) mark.textContent = '저장 안 됨';
  }

  async function onClick(event) {
    const btn = event.target && event.target.closest('[data-boost-act]');
    if (!btn) return;
    const act = btn.getAttribute('data-boost-act');
    if (act === 'save') {
      const form = readForm(event.currentTarget);
      const sent = setModuleParam('prompt_engineering', 'boost_v2_settings', JSON.stringify(form));
      if (sent === false) {
        showToast('연결이 끊겨 저장하지 못했습니다 — 재연결 후 다시 저장하세요', 'error');
        return;
      }
      draft = null;
      showToast('Boost 설정 저장됨', 'success');
      return;
    }
    const routes = {
      download: '/api/boost-v2/model/download',
      cancel: '/api/boost-v2/model/download/cancel',
      unload: '/api/boost-v2/unload',
    };
    if (!routes[act]) return;
    btn.disabled = true;
    try {
      const res = await doFetch(routes[act], { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) showToast(data.error || `요청 실패 (${res.status})`, 'error');
      else if (act === 'unload') showToast('Boost 엔진을 내렸습니다', 'info');
    } catch (error) {
      showToast(`요청 실패: ${error}`, 'error');
    } finally {
      btn.disabled = false;
      schedulePoll(0);
    }
  }

  function paintStatus(st) {
    if (!mountedRoot || !mountedRoot.isConnected) return;
    const statusEl = mountedRoot.querySelector('[data-boost-status]');
    const actionsEl = mountedRoot.querySelector('[data-boost-actions]');
    if (!statusEl || !actionsEl) return;
    const dl = st.download || {};
    const ok = (flag) => (flag ? '<span style="color:var(--success,#4caf50)">✓</span>' : '<span style="color:var(--danger,#e57373)">✗</span>');
    const lines = [
      `${ok(st.engine_ready)} 엔진 llama-server${st.engine_ready ? '' : ' — 없음 (배포본에 포함, 개발 환경은 NAIA_LLAMA_SERVER)'}`,
      st.engine_ready ? `　사용 장치: ${deviceLabel(st)}${st.swapping ? ' · <span style="color:var(--accent,#4ea1ff)">전환 중…</span>' : ''}` : '',
      `${ok(st.model_ready)} 모델 Gemma 4 E2B Q4_0 (3.1GB)${st.model_ready ? '' : ' — 아직 없음'}`,
      st.running ? `● 실행 중${st.last_load_seconds ? ` · 로드 ${st.last_load_seconds}s` : ''}` : '○ 대기 (첫 Random 때 올라옵니다)',
    ];
    if (dl.active || dl.phase === 'verify') {
      lines.push(`<div style="height:6px;background:var(--bg-3,#333);border-radius:3px;overflow:hidden;margin-top:4px"><div style="height:100%;width:${Math.max(0, Math.min(100, Number(dl.percent) || 0))}%;background:var(--accent,#4ea1ff)"></div></div>`);
      lines.push(escHtml(dl.message || ''));
    } else if (dl.error) {
      lines.push(`<span style="color:var(--danger,#e57373)">${escHtml(dl.error)}</span>`);
    }
    statusEl.innerHTML = lines.filter(Boolean).join('<br>');
    // 할당 장치 목록은 서버가 이 PC 를 읽어 안다(CPU·RAM·GPU) — 한 번 채우고, 사용자가 고른 값(초안 포함)은 지킨다.
    const hw = st.hardware || {};
    const gpus = hw.gpus || [];
    const select = mountedRoot.querySelector('[data-boost-device]');
    if (select && select.options.length !== gpus.length + 2) {
      const current = (draft && draft.device) || select.getAttribute('data-current') || 'auto';
      const autoPick = gpus.find((g) => g.id === st.gpu_device_auto);
      const gb = (mib) => (mib ? ` · ${Math.round(mib / 1024)} GB` : '');
      select.innerHTML = `<option value="auto">자동 (지금: ${escHtml(autoPick ? autoPick.name : 'CPU')})</option>`
        + gpus.map((g) => `<option value="${escHtml(g.id)}">${escHtml(g.name)}${g.kind === 'discrete' ? `${gb(g.vram_mib)} · 외장` : ' · 내장 (시스템 메모리 공유)'}</option>`).join('')
        + `<option value="cpu">CPU · ${escHtml(hw.cpu || '')} · ${hw.threads || '?'}스레드</option>`;
      select.value = [...select.options].some((o) => o.value === current) ? current : 'auto';
    }
    const hwEl = mountedRoot.querySelector('[data-boost-hw]');
    if (hwEl) {
      hwEl.textContent = `이 PC: ${hw.cpu || 'CPU'} · ${hw.threads || '?'}스레드 · RAM ${hw.ram_gib ? Math.round(hw.ram_gib) + ' GB' : '?'} · GPU ${gpus.length}개`;
    }
    const buttons = [];
    if (!st.model_ready && st.model_is_default) {
      if (dl.active) buttons.push('<button class="mod-btn-secondary" data-boost-act="cancel">다운로드 취소</button>');
      else buttons.push(`<button class="mod-btn-secondary" data-boost-act="download">${dl.partial_mb ? `이어받기 (${dl.partial_mb}MB 받음)` : '모델 받기 (3.1GB)'}</button>`);
    }
    if (st.running) buttons.push('<button class="mod-btn-secondary" data-boost-act="unload">엔진 내리기</button>');
    actionsEl.innerHTML = buttons.join('');
  }

  function deviceLabel(st) {
    if (st.gpu_fallback) {
      return `CPU <span style="color:var(--warning,#e0a040)" title="${escHtml(st.gpu_fallback)}">(GPU 로 못 띄워 자동 전환)</span>`;
    }
    if (st.use_gpu && st.gpu_device_chosen_name) return escHtml(st.gpu_device_chosen_name);
    return st.device_pref === 'cpu' ? 'CPU (직접 선택)' : 'CPU (쓸 수 있는 GPU 없음)';
  }

  function schedulePoll(delay) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, delay);
  }

  async function poll() {
    pollTimer = null;
    // 팝업이 닫혔거나(숨김) 다시 그려져 떨어진 뿌리면 멈춘다 — 다음 render 가 다시 시작한다.
    if (!mountedRoot || !mountedRoot.isConnected || mountedRoot.offsetParent === null) return;
    try {
      const res = await doFetch('/api/boost-v2/status');
      lastStatus = await res.json();
      paintStatus(lastStatus);
    } catch (error) {
      // 상태 조회 실패는 조용히 — 다음 주기에 다시 본다.
    }
    const active = !!(lastStatus && lastStatus.download && (lastStatus.download.active || lastStatus.download.phase === 'verify'));
    schedulePoll(active ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  }

  // PE 패널의 Auto Boost 체크박스 게이트용: 엔진·모델이 다 있으면 켤 수 있다.
  async function fetchReady() {
    try {
      const res = await doFetch('/api/boost-v2/status');
      const st = await res.json();
      lastStatus = st;
      return !!(st && st.engine_ready && st.model_ready);
    } catch (error) {
      return false;
    }
  }

  return { render, fetchReady };
}
