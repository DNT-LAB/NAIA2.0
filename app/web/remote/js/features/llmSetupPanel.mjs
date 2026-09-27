// API 설정 > "05 AI ASSIST" 탭(09-27 ANIMA 가 04 로 들어오며 밀림) — Assist · Boost 가 함께 쓰는 앱 llama-server 의 엔진 · 모델 · 모드를 한 곳에서(사용자 지정
// 2026-09-26: 받는 곳을 하나로 · NovelAI 탭 아래 공통 영역에서 제 탭으로). 탭 이름 밑 글자 · 점도 여기서 채운다. 상태는 /api/boost-v2/status 폴링, 모델 · 모드 저장은 PE 모듈의 boost_v2_settings
// (부분 저장 — 서버가 디스크 값에 합친다), 받기는 /api/boost-v2/model/download {model} · 엔진은 /api/boost-v2/engine/download.
//
// 모델 = [E2B | E4B | 26B] · 모드 = [CPU 모드 | GPU 모드](GPU 모드 = 설정 device 'gpu' 또는 GPU id, CPU 모드 = 'cpu').
// 처음 값 'auto' 는 서버가 가린다 — 외장 GPU 가 있으면 GPU 모드, 없으면 CPU 모드로 시작한다(사용자 지정 2026-09-27).
// 칸에는 메모리 사실(VRAM · RAM)과 [권장]만 싣는다 — 예상 속도는 PC 마다 달라 싣지 않는다(사용자 지정).
// 모델을 눌러 고르는 것은 **보기만** 바꾼다: 받아 둔 모델이면 [이 모델 쓰기], 아니면 [받기] — 다 받으면 서버가
// 그 모델로 바꾸고 뒤에서 준비(첫 실행의 셰이더 준비)까지 한다. style.css 는 건드리지 않는다(아래 STYLE).

const POLL_BUSY_MS = 1000;
const POLL_IDLE_MS = 4000;
const STYLE_ID = 'llmSetupStyle';
const STYLE = `
#setupLlmSection .llm-hw { font-size: 11px; color: var(--text-dim); line-height: 1.5; }
#setupLlmSection .llm-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
#setupLlmSection .llm-label { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.2px;
  color: var(--text-dim); min-width: 44px; text-transform: uppercase; }
#setupLlmSection .llm-seg { display: inline-flex; border: 1px solid var(--border-dim); border-radius: 7px; overflow: hidden; }
#setupLlmSection .llm-seg button { background: transparent; color: var(--text-muted); border: 0;
  border-right: 1px solid var(--border-dim); padding: 7px 12px; font-size: 12px; cursor: pointer; line-height: 1.3; }
#setupLlmSection .llm-seg button:last-child { border-right: 0; }
#setupLlmSection .llm-seg button:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-primary); }
#setupLlmSection .llm-seg button.is-on { background: rgba(124,106,239,0.22); color: var(--text-primary); }
#setupLlmSection .llm-seg button:disabled { opacity: 0.4; cursor: not-allowed; }
#setupLlmSection .llm-models button { text-align: left; min-width: 104px; }
#setupLlmSection .llm-models b { display: block; font-size: 12px; }
#setupLlmSection .llm-models small { display: block; font-size: 10px; color: var(--text-dim); margin-top: 2px; }
#setupLlmSection .llm-badge { display: inline-block; font-size: 9px; padding: 0 5px; border-radius: 3px; margin-left: 4px;
  vertical-align: 1px; letter-spacing: 0.3px; }
#setupLlmSection .llm-badge.rec { background: rgba(92,184,122,0.2); color: var(--success); }
#setupLlmSection .llm-badge.use { background: rgba(124,106,239,0.28); color: var(--text-primary); }
#setupLlmSection .llm-badge.no { background: rgba(240,64,64,0.16); color: #f07070; }
#setupLlmSection .llm-detail { font-size: 11px; color: var(--text-muted); line-height: 1.5; }
#setupLlmSection .llm-note { font-size: 10px; color: var(--text-dim); line-height: 1.5; }
/* GPU 고르기 = 설정 창 입력칸과 같은 콤보박스(select.setup-input -> customSelects 의 custom-setup-input). 줄을 다 먹지 않게. */
#setupLlmSection .llm-row .custom-select { flex: 1 1 260px; max-width: 440px; }
`;

export function createLlmSetupPanel({ document, fetch: fetchFn = window.fetch.bind(window), showToast = () => {},
  setModuleParam }) {
  const section = document.getElementById('setupLlmSection');
  if (!section) return { init() {}, refresh() {} };
  const elStatus = section.querySelector('[data-llm-status]');
  const elBody = section.querySelector('[data-llm-body]');

  let st = null;           // 마지막 상태
  let picked = null;       // 화면에서 고른 모델(아직 안 쓴다) — null 이면 지금 쓰는 모델
  let userPicked = false;  // 사람이 눌러 고른 것인가 — 아니면 모드가 바뀔 때 그 모드의 권장을 따라간다
  let pollTimer = 0;
  let busy = false;        // 요청 보내는 중(버튼 연타 막기)
  let drawn = '';          // 마지막으로 그린 입력(상태 + 고른 모델) — 같으면 다시 그리지 않는다

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function saveSettings(patch) {
    const sent = typeof setModuleParam === 'function'
      ? setModuleParam('prompt_engineering', 'boost_v2_settings', JSON.stringify(patch)) : false;
    if (sent === false) {
      showToast('연결이 끊겨 저장하지 못했습니다 — 재연결 후 다시 해 주세요', 'error');
      return false;
    }
    setTimeout(() => refresh(), 400);
    return true;
  }

  async function post(path, body) {
    const res = await fetchFn(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const error = new Error(data.error || `요청 실패 (${res.status})`);
      error.status = res.status;
      throw error;
    }
    return data;
  }

  function gb(mib) { return mib ? `${Math.round(mib / 1024)}GB` : ''; }

  function hardwareLine(hw) {
    const gpus = (hw.gpus || []).map(g => (g.kind === 'discrete'
      ? `${esc(g.name)} ${gb(g.vram_mib)}` : `${esc(g.name)}(내장)`));
    return `이 PC: ${esc(hw.cpu || 'CPU')} · RAM ${hw.ram_gib ? Math.round(hw.ram_gib) : '?'}GB · `
      + (gpus.length ? `GPU ${gpus.join(', ')}` : 'GPU 없음');
  }

  function headline() {
    const dl = st.download || {};
    const eng = st.engine_install || {};
    if (!st.engine_ready) return eng.active ? `엔진 받는 중 ${eng.percent || 0}%` : '엔진 없음';
    if (dl.active) return `받는 중 ${dl.percent || 0}%`;
    if (dl.phase === 'verify') return '검증 중…';
    if (st.priming) return `준비 중 · ${st.model_label}`;
    if (st.model_ready) return `준비됨 · ${st.model_label}${st.running ? ' · 실행 중' : ''}`;
    return '모델 없음';
  }

  // 탭 이름 밑 글자 · 점(다른 탭과 같은 옷: ok · warn · err)
  function paintNav() {
    const sub = document.getElementById('setupNavSubAi');
    const dot = document.getElementById('setupDotAi');
    const dl = st.download || {};
    const eng = st.engine_install || {};
    let text = '모델 없음';
    let state = 'warn';
    if (!st.engine_ready) { text = eng.active ? `엔진 ${eng.percent || 0}%` : '엔진 없음'; state = 'err'; }
    else if (dl.active || dl.phase === 'verify') text = `받는 중 ${dl.percent || 0}%`;
    else if (st.priming) text = '준비 중';
    else if (st.model_ready) { text = String(st.model_label || '').replace('Gemma 4 ', ''); state = 'ok'; }
    if (sub) sub.textContent = text;
    if (dot) dot.className = `setup-nav-dot ${state}`;
  }

  function progressHtml(state) {
    const pct = Math.max(0, Math.min(100, Number(state.percent) || 0));
    return `<div class="setup-update-progress"><div class="setup-update-progress-bar">
      <div class="setup-update-progress-fill" style="width:${pct}%"></div></div>
      <span class="setup-update-progress-text">${esc(state.message || `${pct}%`)}</span></div>`;
  }

  function render() {
    if (!st || !elBody) return;
    if (elStatus) elStatus.textContent = headline();
    paintNav();
    // 4초마다 오는 같은 상태로 칸을 갈아엎지 않는다 — 열어 둔 콤보박스 메뉴가 닫히고 커스텀 콤보박스가 다시 만들어졌다.
    const key = JSON.stringify([st, picked]);
    if (key === drawn && elBody.childElementCount) return;
    drawn = key;
    const hw = st.hardware || {};
    const models = st.models || [];
    const mode = st.mode === 'gpu' ? 'gpu' : 'cpu';
    const current = st.model_id;
    const view = models.find(m => m.id === (picked || current)) || models[0];
    const dl = st.download || {};
    const eng = st.engine_install || {};
    const parts = [`<div class="llm-hw">${hardwareLine(hw)}</div>`];

    if (!st.engine_ready) {
      parts.push(st.engine_is_default
        ? `<div class="llm-detail">llama.cpp 엔진이 없습니다(포터블엔 들어 있습니다 — 소스로 실행 중이면 받으세요).</div>
           <div class="llm-row">${eng.active ? progressHtml(eng)
            : '<button type="button" class="setup-btn-primary" data-llm-act="engine">엔진 받기 (35MB)</button>'}</div>`
        : `<div class="llm-detail">지정한 엔진 파일이 없습니다: ${esc(st.engine_path)}</div>`);
      if (eng.error) parts.push(`<div class="setup-result error">${esc(eng.error)}</div>`);
    }

    // [CPU 모드 | GPU 모드] — GPU 가 없으면 GPU 모드는 못 고른다. GPU 가 여럿이면 GPU 모드에서 어느 것인지 제 줄에서 고른다
    // (NAIA 표준 콤보박스 — select.setup-input 을 customSelects 가 custom-setup-input 으로 바꿔 그린다).
    const gpus = hw.gpus || [];
    const gpuLabel = g => `${g.name}${g.kind === 'discrete' ? ` · ${gb(g.vram_mib)}` : ' · 내장'}`;
    const autoGpu = gpus.find(g => g.id === st.gpu_device_auto);
    parts.push(`<div class="llm-row"><span class="llm-label">모드</span><span class="llm-seg">
      <button type="button" data-llm-mode="cpu" class="${mode === 'cpu' ? 'is-on' : ''}">CPU 모드</button>
      <button type="button" data-llm-mode="gpu" class="${mode === 'gpu' ? 'is-on' : ''}"
        ${st.gpu_available ? '' : 'disabled title="엔진이 쓸 수 있는 GPU 가 없습니다"'}>GPU 모드</button></span>
      ${st.gpu_fallback ? '<span class="llm-badge no" title="' + esc(st.gpu_fallback) + '">GPU 로 못 띄워 CPU 로 도는 중</span>' : ''}
      ${st.device_pref === 'auto' && mode === 'cpu' && st.gpu_available
        ? '<span class="llm-note">외장 GPU 가 없어 CPU 로 시작했습니다 — 내장 그래픽은 GPU 모드에서</span>' : ''}
    </div>`);
    if (mode === 'gpu' && gpus.length > 1) {
      const autoPicked = st.device_pref === 'auto' || st.device_pref === 'gpu';
      parts.push(`<div class="llm-row"><span class="llm-label">GPU</span>
        <select class="setup-input" data-llm-gpu aria-label="GPU 모드에서 쓸 GPU">
          <option value="gpu"${autoPicked ? ' selected' : ''}>자동 — ${esc(autoGpu ? gpuLabel(autoGpu) : '외장 우선')}</option>
          ${gpus.map(g => `<option value="${esc(g.id)}"${st.device_pref === g.id ? ' selected' : ''}>${esc(gpuLabel(g))}</option>`).join('')}
        </select></div>`);
    }

    // 모델 [E2B | E4B | 26B]
    parts.push(`<div class="llm-row"><span class="llm-label">모델</span><span class="llm-seg llm-models">${models.map(m => {
      const fit = m[mode] || {};
      const badges = [
        m.id === current && m.installed ? '<span class="llm-badge use">사용 중</span>' : '',
        m.recommended && m.recommended[mode] ? '<span class="llm-badge rec">권장</span>' : '',
        fit.fit === 'no' ? '<span class="llm-badge no">메모리 부족</span>' : '',
      ].join('');
      return `<button type="button" data-llm-model="${esc(m.id)}" class="${m.id === view.id ? 'is-on' : ''}">
        <b>${esc(m.label.replace('Gemma 4 ', ''))}${badges}</b>
        <small>${esc(m.quant)} · ${esc(m.size_gb)}GB · ${m.installed ? '받음' : m.partial_mb ? '받다 멈춤' : '안 받음'}</small></button>`;
    }).join('')}</span></div>`);

    if (view) {
      const fit = view[mode] || {};
      parts.push(`<div class="llm-detail">${esc(view.note)}${fit.why ? ` · ${esc(fit.why)}` : ''}</div>`);
      const downloadingThis = (dl.active || dl.phase === 'verify') && dl.model === view.id;
      const downloadingOther = (dl.active || dl.phase === 'verify') && dl.model && dl.model !== view.id;
      let action = '';
      if (downloadingThis) {
        action = `${progressHtml(dl)}<button type="button" class="setup-btn-ghost" data-llm-act="cancel">취소</button>`;
      } else if (!st.model_is_default) {
        action = `<span class="llm-note">모델 파일을 직접 지정해 쓰는 중입니다: ${esc(st.model_path)}</span>`;
      } else if (view.installed && view.id !== current) {
        action = `<button type="button" class="setup-btn-primary" data-llm-act="use">이 모델 쓰기</button>`;
      } else if (!view.installed) {
        action = `<button type="button" class="setup-btn-primary" data-llm-act="download"${downloadingOther ? ' disabled' : ''}>${
          view.partial_mb ? `이어받기 (${Math.round(view.partial_mb)}MB 받음)` : `받기 (${esc(view.size_gb)}GB)`}</button>${
          downloadingOther ? '<span class="llm-note">다른 모델을 받는 중입니다</span>' : ''}`;
      } else if (st.priming) {
        action = '<span class="llm-note">처음 쓰는 모델은 준비에 1분 가까이 걸릴 수 있습니다</span>';
      }
      if (action) parts.push(`<div class="llm-row">${action}</div>`);
      if (dl.error && dl.model === view.id) parts.push(`<div class="setup-result error">${esc(dl.error)}</div>`);
    }
    parts.push(`<div class="llm-note">Hugging Face HauhauCS 저장소에서 한 번 받아 이 PC 에 둡니다.
      Assist(Ctrl+O)와 Auto Boost 가 같은 모델을 씁니다.</div>`);
    elBody.innerHTML = parts.join('');
  }

  async function refresh() {
    try {
      const res = await fetchFn('/api/boost-v2/status', { cache: 'no-store' });
      st = await res.json();
      if (picked && picked === st.model_id && userPicked) { picked = null; userPicked = false; }
      if (!userPicked && !(st.models || []).some(m => m.id === st.model_id && m.installed)) {
        // 아직 아무것도 안 쓴다 — 이 모드의 권장을 먼저 보인다(모드를 바꾸면 따라간다)
        const mode = st.mode === 'gpu' ? 'gpu' : 'cpu';
        const rec = (st.models || []).find(m => m.recommended && m.recommended[mode]);
        picked = rec && rec.id !== st.model_id ? rec.id : null;
      }
      render();
    } catch (error) {
      if (elStatus) elStatus.textContent = '상태를 읽지 못했습니다';
    }
    schedule();
  }

  function schedule() {
    clearTimeout(pollTimer);
    if (section.offsetParent === null) return;          // 창이 닫혔다 — 다시 열 때 refresh() 가 잇는다
    const dl = (st && st.download) || {};
    const eng = (st && st.engine_install) || {};
    const active = dl.active || dl.phase === 'verify' || eng.active || (st && st.priming);
    pollTimer = setTimeout(refresh, active ? POLL_BUSY_MS : POLL_IDLE_MS);
  }

  async function onClick(event) {
    const modeBtn = event.target.closest('[data-llm-mode]');
    const modelBtn = event.target.closest('[data-llm-model]');
    const actBtn = event.target.closest('[data-llm-act]');
    if (!st) return;
    if (modeBtn && !modeBtn.disabled) {
      const next = modeBtn.getAttribute('data-llm-mode');
      if ((next === 'gpu') === (st.mode === 'gpu')) return;
      // GPU 모드 = 'gpu'(외장 우선, 내장뿐이면 내장 — 처음 값 'auto' 와 달리 내장도 쓴다). 여럿이면 아래 줄에서 고른다.
      saveSettings({ device: next === 'cpu' ? 'cpu' : 'gpu' });
      return;
    }
    if (modelBtn) {
      const id = modelBtn.getAttribute('data-llm-model');
      picked = id === st.model_id ? null : id;
      userPicked = picked !== null;
      render();
      return;
    }
    if (!actBtn || busy) return;
    const act = actBtn.getAttribute('data-llm-act');
    const target = picked || st.model_id;
    busy = true;
    actBtn.disabled = true;
    try {
      if (act === 'use') {
        if (saveSettings({ model: target })) {
          picked = null;
          userPicked = false;
          showToast('모델을 바꿨습니다 — 뒤에서 준비합니다', 'success');
        }
      } else if (act === 'download') {
        await post('/api/boost-v2/model/download', { model: target });
      } else if (act === 'cancel') {
        await post('/api/boost-v2/model/download/cancel', {});
      } else if (act === 'engine') {
        await post('/api/boost-v2/engine/download', {});
      }
    } catch (error) {
      showToast(error.status === 403 ? 'AI 모델은 NAIA 를 켠 PC 에서만 받을 수 있습니다' : error.message, 'error');
    } finally {
      busy = false;
      drawn = '';        // 상태가 그대로여도(거절 등) 눌러서 꺼 둔 단추를 되살리게 한 번은 다시 그린다
      refresh();
    }
  }

  function onChange(event) {
    const select = event.target.closest('[data-llm-gpu]');
    if (select) saveSettings({ device: select.value });
  }

  function init() {
    ensureStyle();
    section.addEventListener('click', onClick);
    section.addEventListener('change', onChange);
    refresh();   // 탭 이름 밑 상태를 처음부터 채운다(탭이 안 보이면 폴링은 이어 가지 않는다)
  }

  return { init, refresh };
}
