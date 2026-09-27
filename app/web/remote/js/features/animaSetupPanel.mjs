// API 설정 > "04 ANIMA" 탭 — NAIA 가 설치 · 관리하는 전용 ComfyUI(고정 그래프 Spectrum SPD · 모델 naiANIMA2d_v03).
// 사용자 지정 2026-09-27: 03 COMFYUI 다음 04 자리에(AI ASSIST 05 · GROK 06 으로 밀림).
// 백엔드 계약 = docs/ANIMA_MANAGED_ENGINE_CONTRACT_2026_09_27.md §8(/api/anima-engine/*). 백엔드가 없는 판(404)이면
// "이 버전에는 없음" 만 보이고 물러난다. 탭 이름 밑 글자 · 점도 여기서 채운다. style.css 는 건드리지 않는다(아래 STYLE).
// 예상 시간 · 속도는 싣지 않는다(사용자 지정) — 크기와 단계만.
// 설치 · 동의 · 엔진 제어는 NAIA 를 켠 PC 에서만(서버가 403) — 원격이면 안내만 하고 단추를 감춘다.
// 동의(I Agree)는 화면에서 받고 서버가 묶음 해시로 다시 검사한다(버튼을 우회해도 막힌다).

const POLL_BUSY_MS = 1000;
const POLL_IDLE_MS = 4000;
const API = '/api/anima-engine';
const STYLE_ID = 'animaSetupStyle';
const STYLE = `
#setupAnimaSection .anima-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
#setupAnimaSection .anima-label { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.2px;
  color: var(--text-dim); min-width: 64px; text-transform: uppercase; }
#setupAnimaSection .anima-val { font-size: 12px; color: var(--text-primary); }
#setupAnimaSection .anima-detail { font-size: 11px; color: var(--text-muted); line-height: 1.5; }
#setupAnimaSection .anima-note { font-size: 10px; color: var(--text-dim); line-height: 1.5; }
#setupAnimaSection .anima-hw { font-size: 11px; color: var(--text-dim); line-height: 1.5; }
#setupAnimaSection .anima-code { font-family: var(--font-mono); font-size: 10px; opacity: 0.75; margin-left: 6px; }
#setupAnimaSection .anima-opt { font-size: 9px; color: var(--text-dim); letter-spacing: 0.5px; margin-left: 4px; text-transform: none; }
#setupAnimaSection .anima-seg { display: inline-flex; border: 1px solid var(--border-dim); border-radius: 7px; overflow: hidden; }
#setupAnimaSection .anima-seg button { background: transparent; color: var(--text-muted); border: 0;
  border-right: 1px solid var(--border-dim); padding: 7px 12px; font-size: 12px; cursor: pointer; line-height: 1.3; }
#setupAnimaSection .anima-seg button:last-child { border-right: 0; }
#setupAnimaSection .anima-seg button:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-primary); }
#setupAnimaSection .anima-seg button.is-on { background: rgba(124,106,239,0.22); color: var(--text-primary); }
#setupAnimaSection .anima-seg button:disabled { opacity: 0.4; cursor: not-allowed; }
#setupAnimaSection .anima-steps { display: flex; gap: 4px; flex-wrap: wrap; }
#setupAnimaSection .anima-step { font-size: 10px; padding: 3px 9px; border: 1px solid var(--border-dim); border-radius: 10px;
  color: var(--text-dim); }
#setupAnimaSection .anima-step.done { color: var(--success); border-color: rgba(92,184,122,0.35); }
#setupAnimaSection .anima-step.now { color: var(--text-primary); border-color: rgba(124,106,239,0.6); background: rgba(124,106,239,0.18); }
#setupAnimaSection ul.anima-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
#setupAnimaSection .anima-checks li { font-size: 11px; color: var(--text-muted); }
#setupAnimaSection .anima-checks li.bad { color: #f07070; }
#setupAnimaSection .anima-dirs li { display: flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 10px;
  color: var(--text-muted); word-break: break-all; }
#setupAnimaSection .anima-x { background: none; border: 0; color: var(--text-dim); cursor: pointer; font-size: 11px; padding: 0 4px; }
#setupAnimaSection .anima-x:hover { color: #f07070; }
#setupAnimaSection details.anima-arts summary { cursor: pointer; font-size: 11px; color: var(--text-muted); }
#setupAnimaSection details.anima-arts li { font-size: 11px; color: var(--text-muted); margin-top: 3px; }
#setupAnimaSection details.anima-arts small { display: block; font-family: var(--font-mono); font-size: 9px; color: var(--text-dim);
  word-break: break-all; }
#setupAnimaSection .anima-lic li { border: 1px solid var(--border-dim); border-radius: 7px; padding: 6px 9px; background: var(--bg-card); }
#setupAnimaSection .anima-lic-head { display: flex; align-items: baseline; gap: 8px; }
#setupAnimaSection .anima-lic-head b { font-size: 12px; color: var(--text-primary); font-weight: 600; }
#setupAnimaSection .anima-lic-name { font-size: 10px; color: var(--text-dim); }
#setupAnimaSection .anima-lic-for { font-size: 10px; color: var(--text-dim); margin-top: 2px; line-height: 1.45; }
#setupAnimaSection .anima-link { margin-left: auto; background: none; border: 0; color: var(--accent-glow); cursor: pointer;
  font-size: 11px; padding: 0; flex: none; }
#setupAnimaSection .anima-link:hover { text-decoration: underline; }
#setupAnimaSection .anima-lic-text { max-height: 180px; overflow: auto; white-space: pre-wrap; word-break: break-word;
  font-family: var(--font-mono); font-size: 10px; line-height: 1.45; color: var(--text-muted);
  background: var(--bg-surface); border-radius: 6px; padding: 8px; margin: 6px 0 0; }
#setupAnimaSection .anima-notice { font-size: 10px; color: var(--text-muted); line-height: 1.5;
  border-left: 2px solid var(--border-glow); padding: 4px 9px; }
#setupAnimaSection .anima-notice p { margin: 0 0 4px; }
#setupAnimaSection .anima-notice p:last-child { margin-bottom: 0; }
#setupAnimaSection .setup-actions { margin-top: 4px; align-items: center; }
`;

// 설치 단계를 사람이 읽을 몇 칸으로 묶는다(계약서 §5.2 의 phase 10개 -> 6칸).
const STEPS = [
  { label: '검사', phases: ['inspect'] },
  { label: '내려받기', phases: ['download'] },
  { label: '설치', phases: ['extract', 'install_nodes', 'write_config', 'promote'] },
  { label: '엔진 시작', phases: ['start'] },
  { label: '시험 생성', phases: ['preflight', 'smoke'] },
  { label: '완료', phases: ['activate'] },
];
const PHASE_LABEL = {
  inspect: 'PC 검사', download: '내려받는 중', extract: '압축 푸는 중', install_nodes: '노드 설치',
  write_config: '설정 쓰는 중', promote: '적용 중', start: '엔진 시작 중', preflight: '구성 확인',
  smoke: '시험 생성 중', activate: '마무리',
};
const ARTIFACT_LABEL = {
  comfyui_portable: 'ComfyUI 엔진', '7zr': '7-Zip 압축 해제 도구', spectrum: 'Spectrum 노드',
  unet: 'naiANIMA2d_v03 모델', text_encoder: 'Qwen 텍스트 인코더', vae: 'Qwen VAE',
};
const ACTION_LABEL = { present: '받아 둠', reuse: '있는 파일 사용', download: '받기' };
const IDLE_OPTIONS = [
  { v: 0, t: '안 끔' }, { v: 10, t: '10분' }, { v: 30, t: '30분' }, { v: 60, t: '1시간' }, { v: 120, t: '2시간' },
];
const REMOTE_NOTE = '설치와 엔진 제어는 NAIA 를 켠 PC 에서만 할 수 있습니다.';

export function createAnimaSetupPanel({ document, fetch: fetchFn = window.fetch.bind(window), showToast = () => {},
  onEngineChanged = () => {} }) {
  const section = document.getElementById('setupAnimaSection');
  if (!section) return { init() {}, refresh() {} };
  const elStatus = section.querySelector('[data-anima-status]');
  const elBody = section.querySelector('[data-anima-body]');

  let st = null;             // 마지막 GET /status
  let missing = false;       // 백엔드 라우트가 없다(404) — 이 판에는 기능이 없다
  let remote = false;        // 🔒 라우트가 403 — NAIA 를 켠 PC 가 아니다
  let plan = null;           // POST /inspect 결과
  let planError = null;      // {code, message}
  let inspecting = false;
  let autoInspected = false; // 설치 칸을 처음 볼 때 한 번만 저절로 검사한다
  let lic = null;            // GET /licenses
  const licOpen = new Set(); // 원문을 펼친 항목 id
  const licText = {};        // id -> 원문
  let agreed = false;        // 이번 화면에서 I Agree 를 체크했는가
  let rootDraft = null;      // 사람이 고친 설치 위치(null = 설정 · 제안값)
  let dirDraft = '';         // 폴더 입력칸
  let loraDraft = '';
  let artsOpen = false;      // "받을 것" 펼침
  let busy = false;          // 요청 보내는 중(연타 막기)
  let pollTimer = 0;
  let drawn = '';            // 마지막으로 그린 입력 — 같으면 다시 그리지 않는다(입력 중인 칸을 지키려고)
  let lastState = '';

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function fmtBytes(n) {
    const v = Number(n) || 0;
    if (v >= 1024 ** 3) return `${(v / 1024 ** 3).toFixed(1)}GB`;
    if (v >= 1024 ** 2) return `${Math.round(v / 1024 ** 2)}MB`;
    return `${Math.max(0, Math.round(v / 1024))}KB`;
  }

  const install = () => (st && st.install) || {};
  const settings = () => (st && st.settings) || {};
  const visible = () => section.offsetParent !== null;

  function downloadPct(ins) {
    if (ins.phase !== 'download' || !Number(ins.bytes_total)) return null;
    return Math.max(0, Math.min(100, Math.floor((Number(ins.bytes_done) || 0) * 100 / Number(ins.bytes_total))));
  }

  function consentStored() {
    return Boolean(st && st.consent && st.consent.agreed && lic && st.consent.bundle_sha256 === lic.bundle_sha256);
  }

  function currentRoot() {
    if (rootDraft != null) return rootDraft.trim();
    return String(settings().engine_root || (plan && (plan.engine_root || plan.suggested_root)) || '').trim();
  }

  async function call(method, path, body) {
    const init = { method, cache: 'no-store' };
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    const res = await fetchFn(`${API}${path}`, init);
    const data = await res.json().catch(() => ({}));
    if (res.status === 403) remote = true;
    if (!res.ok || data.ok === false) {
      const error = new Error(data.error || `요청 실패 (${res.status})`);
      error.status = res.status;
      error.code = data.code || '';
      throw error;
    }
    return data;
  }

  // ---- 머리글 · 탭 이름 밑 글자 · 점(다른 탭과 같은 옷: ok · warn · err) ----

  function headline() {
    if (missing) return '이 버전에는 없음';
    if (!st) return '확인 중…';
    const ins = install();
    if (ins.state === 'preparing') {
      const pct = downloadPct(ins);
      return `설치 중 · ${PHASE_LABEL[ins.phase] || '준비'}${pct != null ? ` ${pct}%` : ''}`;
    }
    if (ins.state === 'ready') {
      const running = (st.engine || {}).state === 'running' ? ' · 실행 중' : '';
      return (st.comfyui_engine === 'managed' ? '준비됨 · 생성에 사용 중' : '준비됨 · 사용 안 함') + running;
    }
    if (ins.state === 'failed') return '설치 실패';
    if (ins.state === 'canceled') return '설치 취소됨';
    if (ins.state === 'blocked') return '이 PC 에서는 설치할 수 없음';
    return '설치 안 됨';
  }

  function paintNav() {
    const sub = document.getElementById('setupNavSubAnima');
    const dot = document.getElementById('setupDotAnima');
    let text = '확인 중';
    let state = '';
    if (missing) text = '없음';
    else if (st) {
      const ins = install();
      if (ins.state === 'preparing') {
        const pct = downloadPct(ins);
        text = pct != null ? `설치 ${pct}%` : '설치 중';
        state = 'warn';
      } else if (ins.state === 'ready') {
        text = st.comfyui_engine === 'managed' ? '사용 중' : '준비됨';
        state = 'ok';
      } else if (ins.state === 'failed' || ins.state === 'blocked') {
        text = ins.state === 'blocked' ? '설치 불가' : '설치 실패';
        state = 'err';
      } else text = ins.state === 'canceled' ? '취소됨' : '미설치';
    }
    if (sub) sub.textContent = text;
    if (dot) dot.className = `setup-nav-dot${state ? ` ${state}` : ''}`;
  }

  function progressHtml(pct, text) {
    return `<div class="setup-update-progress"><div class="setup-update-progress-bar">
      <div class="setup-update-progress-fill" style="width:${pct}%"></div></div>
      <span class="setup-update-progress-text">${esc(text)}</span></div>`;
  }

  // ---- 설치 전(미설치 · 실패 · 취소 · 차단) ----

  function viewPlan() {
    if (inspecting) return '<div class="anima-row"><span class="anima-label">PC</span><span class="anima-note">검사 중…</span></div>';
    if (planError) {
      return `<div class="setup-result error">${esc(planError.message)}${planError.code
        ? `<span class="anima-code">${esc(planError.code)}</span>` : ''}</div>
        <div class="anima-row"><button type="button" class="setup-btn-ghost" data-anima-act="inspect">다시 검사</button></div>`;
    }
    if (!plan) {
      return `<div class="anima-row"><button type="button" class="setup-btn-ghost" data-anima-act="inspect">PC 검사</button>
        <span class="anima-note">RTX 20 시리즈 이상 NVIDIA GPU 가 필요합니다</span></div>`;
    }
    const gpu = plan.gpu || {};
    const vram = Number(gpu.vram_mb) ? ` · ${Math.round(Number(gpu.vram_mb) / 1024)}GB` : '';
    const gpuText = gpu.name ? `${gpu.name}${vram}${gpu.driver ? ` · 드라이버 ${gpu.driver}` : ''}` : 'NVIDIA GPU 를 찾지 못했습니다';
    const checks = (plan.checks || []).filter(c => !c.ok || c.message)
      .map(c => `<li class="${c.ok ? '' : 'bad'}">${c.ok ? '✓' : '✕'} ${esc(c.message || c.code || c.id)}</li>`).join('');
    const arts = (plan.artifacts || []).map(a => `<li>${esc(ARTIFACT_LABEL[a.id] || a.id)} · ${fmtBytes(a.size)} · ${
      esc(ACTION_LABEL[a.action] || a.action)}${a.action === 'reuse' && a.path ? `<small>${esc(a.path)}</small>` : ''}</li>`).join('');
    return `<div class="anima-row"><span class="anima-label">GPU</span><span class="anima-val">${esc(gpuText)}</span></div>
      ${checks ? `<ul class="anima-list anima-checks">${checks}</ul>` : ''}
      <div class="anima-row"><span class="anima-label">용량</span><span class="anima-detail">받을 용량 ${fmtBytes(plan.download_bytes)}
        · 필요한 공간 ${fmtBytes(plan.required_bytes)} · 남은 공간 ${fmtBytes(plan.free_bytes)}</span></div>
      ${arts ? `<details class="anima-arts"${artsOpen ? ' open' : ''}><summary>받을 것</summary><ul class="anima-list">${arts}</ul></details>` : ''}
      <div class="anima-row"><button type="button" class="setup-btn-ghost" data-anima-act="inspect">다시 검사</button></div>`;
  }

  function viewRoot() {
    return `<label class="setup-field-label" for="setupAnimaRoot">설치 위치</label>
      <input class="setup-input setup-input-mono" id="setupAnimaRoot" data-anima-input="root" type="text"
             value="${esc(currentRoot())}" spellcheck="false" autocomplete="off">
      <div class="anima-note">NAIA 폴더 밖에 둡니다 — NAIA 를 새 버전으로 바꿔도 다시 받지 않습니다.</div>`;
  }

  function dirsHtml(dirs, attr) {
    const rows = dirs.map((d, i) => `<li><span>${esc(d)}</span>
      <button type="button" class="anima-x" data-${attr}="${i}" title="빼기" aria-label="빼기">✕</button></li>`).join('');
    return rows ? `<ul class="anima-list anima-dirs">${rows}</ul>` : '';
  }

  function viewModelDirs() {
    return `<div class="setup-field-label">이미 받은 모델 폴더<span class="anima-opt">선택</span></div>
      ${dirsHtml(settings().model_dirs || [], 'anima-rmdir')}
      <div class="setup-input-row">
        <input class="setup-input setup-input-mono" data-anima-input="dir" type="text" value="${esc(dirDraft)}"
               placeholder="예: D:\\ComfyUI\\models" spellcheck="false" autocomplete="off">
        <button type="button" class="setup-btn-ghost" data-anima-act="adddir">추가</button>
      </div>
      <div class="anima-note">같은 파일이 있으면 받지 않고 그 자리를 그대로 씁니다.</div>`;
  }

  function viewLicenses() {
    if (!lic) return '<div class="anima-note">라이선스를 불러오는 중…</div>';
    const items = (lic.items || []).map(item => {
      const open = licOpen.has(item.id);
      return `<li><div class="anima-lic-head"><b>${esc(item.title)}</b><span class="anima-lic-name">${esc(item.license || '')}</span>
          <button type="button" class="anima-link" data-anima-lic="${esc(item.id)}">${open ? '접기' : '원문'}</button></div>
        ${item.applies_to ? `<div class="anima-lic-for">${esc(item.applies_to)}</div>` : ''}
        ${open ? `<pre class="anima-lic-text">${esc(licText[item.id] == null ? '불러오는 중…' : licText[item.id])}</pre>` : ''}</li>`;
    }).join('');
    const notices = Object.values(lic.notices || {}).filter(Boolean).map(n => `<p>${esc(n)}</p>`).join('');
    const consent = consentStored()
      ? '<div class="anima-note">이미 동의했습니다.</div>'
      : `<label class="setup-toggle-row" for="setupAnimaAgree">
           <input type="checkbox" id="setupAnimaAgree" data-anima-agree${agreed ? ' checked' : ''}>
           <span class="setup-toggle-text"><b>위 라이선스에 모두 동의합니다 (I Agree)</b></span></label>`;
    return `<div class="setup-field-label">라이선스</div>
      <ul class="anima-list anima-lic">${items}</ul>
      ${notices ? `<div class="anima-notice">${notices}</div>` : ''}
      ${consent}`;
  }

  function viewInstallActions() {
    const ins = install();
    const blockers = plan ? (plan.checks || []).filter(c => !c.ok) : [];
    const consentOk = agreed || consentStored();
    const ready = Boolean(plan) && !blockers.length && consentOk && Boolean(lic) && Boolean(currentRoot());
    const why = !plan ? 'PC 검사를 먼저 합니다'
      : blockers.length ? '검사를 통과하지 못했습니다'
        : !currentRoot() ? '설치 위치를 적어 주세요'
          : !consentOk ? '라이선스에 동의해야 설치할 수 있습니다' : '';
    const label = ins.state === 'failed' || ins.state === 'canceled' ? '다시 시작' : '설치';
    return `<div class="setup-actions">
      <button type="button" class="setup-btn-primary" data-anima-act="prepare"${ready && !busy ? '' : ' disabled'}>${
        label}${plan ? ` (${fmtBytes(plan.download_bytes)})` : ''}</button>
      ${why ? `<span class="anima-note">${esc(why)}</span>` : ''}</div>`;
  }

  function viewInstaller() {
    const ins = install();
    const parts = ['<div class="anima-detail">NAIA 가 공식 ComfyUI · Spectrum 노드 · 모델을 받아 이 PC 전용 엔진을 만듭니다. '
      + '설치하면 서버 주소 없이 생성합니다.</div>'];
    if (ins.state === 'failed' || ins.state === 'blocked') {
      parts.push(`<div class="setup-result error">${esc(ins.message || '설치하지 못했습니다')}${ins.code
        ? `<span class="anima-code">${esc(ins.code)}</span>` : ''}</div>`);
    } else if (ins.state === 'canceled') {
      parts.push('<div class="anima-note">설치를 취소했습니다. 다시 시작하면 받은 만큼 이어서 받습니다.</div>');
    }
    if (remote) {
      parts.push(`<div class="anima-note">${REMOTE_NOTE}</div>`);
      return parts.join('');
    }
    parts.push(viewPlan(), viewRoot(), viewModelDirs(), viewLicenses(), viewInstallActions());
    return parts.join('');
  }

  // ---- 설치 중 ----

  function viewPreparing() {
    const ins = install();
    const at = STEPS.findIndex(step => step.phases.includes(ins.phase));
    const steps = STEPS.map((step, i) => `<span class="anima-step${i < at ? ' done' : i === at ? ' now' : ''}">${
      i < at ? '✓ ' : ''}${esc(step.label)}</span>`).join('');
    const parts = [`<div class="anima-steps">${steps}</div>`];
    const pct = downloadPct(ins);
    if (pct != null) {
      parts.push(progressHtml(pct, `${fmtBytes(ins.bytes_done)} / ${fmtBytes(ins.bytes_total)}${
        ins.current_item ? ` · ${ins.current_item}` : ''}`));
    } else {
      parts.push(`<div class="anima-detail">${esc(PHASE_LABEL[ins.phase] || '준비 중')}…${
        ins.current_item ? ` ${esc(ins.current_item)}` : ''}</div>`);
    }
    if (ins.phase === 'start' || ins.phase === 'smoke') {
      parts.push('<div class="anima-note">처음에는 모델을 메모리에 올리느라 오래 걸릴 수 있습니다.</div>');
    }
    (ins.warnings || []).forEach(w => parts.push(`<div class="anima-note">⚠ ${esc(w.message || w)}</div>`));
    if (!remote) {
      parts.push(`<div class="setup-actions"><button type="button" class="setup-btn-ghost" data-anima-act="cancel"${
        busy ? ' disabled' : ''}>취소</button></div>`);
    }
    return parts.join('');
  }

  // ---- 준비됨 ----

  function viewReady() {
    const eng = st.engine || {};
    const rc = st.receipt || {};
    const managed = st.comfyui_engine === 'managed';
    const parts = [];
    parts.push(`<div class="anima-row"><span class="anima-label">생성 엔진</span><span class="anima-seg">
        <button type="button" data-anima-engine="external" class="${managed ? '' : 'is-on'}"${remote ? ' disabled' : ''}>외부 ComfyUI</button>
        <button type="button" data-anima-engine="managed" class="${managed ? 'is-on' : ''}"${remote ? ' disabled' : ''}>ANIMA</button>
      </span></div>
      <div class="anima-note">COMFYUI 모드가 어느 엔진으로 생성할지 고릅니다. 외부 ComfyUI 주소는 03 탭에 그대로 남습니다.</div>`);
    const engText = {
      running: `실행 중${eng.port ? ` · 127.0.0.1:${eng.port}` : ''}`, starting: '시작 중…', stopping: '끄는 중…',
      crashed: '비정상 종료', stopped: '꺼짐',
    }[eng.state] || '꺼짐';
    const engBtn = remote ? ''
      : eng.state === 'running' ? '<button type="button" class="setup-btn-ghost" data-anima-act="stop">끄기</button>'
        : eng.state === 'stopped' || eng.state === 'crashed' || !eng.state
          ? '<button type="button" class="setup-btn-ghost" data-anima-act="start">켜기</button>' : '';
    parts.push(`<div class="anima-row"><span class="anima-label">엔진</span><span class="anima-val">${esc(engText)}</span>${engBtn}</div>`);
    if (eng.state === 'crashed' && eng.message) parts.push(`<div class="setup-result error">${esc(eng.message)}</div>`);
    const gpu = rc.gpu || {};
    const ss = rc.system_stats || {};
    const bits = [gpu.name, ss.comfyui_version && `ComfyUI ${ss.comfyui_version}`, ss.pytorch_version && `PyTorch ${ss.pytorch_version}`]
      .filter(Boolean);
    if (bits.length) parts.push(`<div class="anima-hw">${esc(bits.join(' · '))}</div>`);
    if (remote) {
      parts.push(`<div class="anima-note">${REMOTE_NOTE}</div>`);
      return parts.join('');
    }
    const idle = Number(settings().idle_minutes ?? 30);
    parts.push(`<div class="anima-row"><span class="anima-label">자동 끄기</span><span class="anima-seg">${IDLE_OPTIONS.map(o =>
      `<button type="button" data-anima-idle="${o.v}" class="${o.v === idle ? 'is-on' : ''}">${o.t}</button>`).join('')}</span></div>
      <div class="anima-note">생성이 없으면 이 시간 뒤 엔진을 내려 그래픽 메모리를 돌려줍니다. 다음 생성 때 다시 켭니다.</div>`);
    parts.push(`<div class="setup-field-label">LoRA 폴더<span class="anima-opt">선택</span></div>
      ${dirsHtml(settings().lora_dirs || [], 'anima-rmlora')}
      <div class="setup-input-row">
        <input class="setup-input setup-input-mono" data-anima-input="lora" type="text" value="${esc(loraDraft)}"
               placeholder="예: D:\\ComfyUI\\models\\loras" spellcheck="false" autocomplete="off">
        <button type="button" class="setup-btn-ghost" data-anima-act="addlora">추가</button>
      </div>`);
    parts.push(`<div class="anima-note">설치 위치: ${esc(settings().engine_root || '')}</div>
      <div class="setup-actions"><button type="button" class="setup-btn-ghost" data-anima-act="repair"${busy ? ' disabled' : ''}>다시 검증</button>
        <span class="anima-note">파일이 손상됐을 때 확인하고 필요한 것만 다시 받습니다.</span></div>`);
    return parts.join('');
  }

  // ---- 그리기 ----

  function render() {
    if (!elBody) return;
    if (elStatus) elStatus.textContent = headline();
    paintNav();
    const key = JSON.stringify([missing, remote, st, plan, planError, inspecting, lic && lic.bundle_sha256,
      [...licOpen], Object.keys(licText), agreed, busy, artsOpen]);
    if (key === drawn && elBody.childElementCount) return;
    drawn = key;
    // 입력 중인 칸을 지킨다(폴링이 칸을 다시 그려도 글자 · 커서가 남게)
    const active = document.activeElement;
    const focusKey = active && elBody.contains(active) ? active.getAttribute('data-anima-input') : null;
    const selection = focusKey && typeof active.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
    let html;
    if (missing) html = '<div class="anima-note">이 버전에는 ANIMA 엔진이 아직 없습니다.</div>';
    else if (!st) html = '';
    else if (install().state === 'preparing') html = viewPreparing();
    else if (install().state === 'ready') html = viewReady();
    else html = viewInstaller();
    elBody.innerHTML = html;
    if (focusKey) {
      const input = elBody.querySelector(`[data-anima-input="${focusKey}"]`);
      if (input) {
        input.focus();
        if (selection) { try { input.setSelectionRange(selection[0], selection[1]); } catch (_) { /* number 등 */ } }
      }
    }
  }

  // ---- 서버 ----

  async function loadLicenses() {
    try {
      lic = await call('GET', '/licenses');
    } catch (error) {
      lic = null;
    }
    render();
  }

  async function inspect() {
    inspecting = true;
    planError = null;
    render();
    try {
      const root = currentRoot();
      const data = await call('POST', '/inspect', root ? { engine_root: root } : {});
      plan = data.plan || null;   // 설치 위치 칸은 rootDraft 가 없으면 설정 -> plan 의 제안값 순으로 읽는다(currentRoot)
    } catch (error) {
      if (error.status !== 403) planError = { code: error.code, message: error.message };
    } finally {
      inspecting = false;
      render();
    }
  }

  async function refresh() {
    try {
      const res = await fetchFn(`${API}/status`, { cache: 'no-store' });
      if (res.status === 404) {
        missing = true;
        st = null;
      } else {
        missing = false;
        st = await res.json();
      }
    } catch (error) {
      if (elStatus) elStatus.textContent = '상태를 읽지 못했습니다';
      schedule();
      return;
    }
    const state = st ? install().state : '';
    // 설치가 끝났다 — 엔진이 바뀌었을 수 있으니 기존 연결 확인 흐름(probe_api)을 다시 태운다(계약서 §9.5)
    if (lastState === 'preparing' && state === 'ready') onEngineChanged(st.comfyui_engine);
    lastState = state;
    if (st && state !== 'preparing' && state !== 'ready' && visible()) {
      if (!lic) loadLicenses();
      if (!plan && !inspecting && !autoInspected && !remote) {
        autoInspected = true;
        inspect();
      }
    }
    render();
    schedule();
  }

  function schedule() {
    clearTimeout(pollTimer);
    if (!visible() || missing) return;                 // 창이 닫혔다 — 다시 열 때 refresh() 가 잇는다
    pollTimer = setTimeout(refresh, install().state === 'preparing' ? POLL_BUSY_MS : POLL_IDLE_MS);
  }

  async function saveSettings(patch) {
    await call('POST', '/settings', patch);
    await refresh();
  }

  function addDir(kind) {
    const value = (kind === 'lora' ? loraDraft : dirDraft).trim();
    if (!value) return null;
    const key = kind === 'lora' ? 'lora_dirs' : 'model_dirs';
    const dirs = [...(settings()[key] || [])];
    if (!dirs.includes(value)) dirs.push(value);
    return { [key]: dirs };
  }

  function removeDir(kind, index) {
    const key = kind === 'lora' ? 'lora_dirs' : 'model_dirs';
    const dirs = [...(settings()[key] || [])];
    dirs.splice(index, 1);
    return { [key]: dirs };
  }

  async function run(button, task) {
    if (busy) return;
    busy = true;
    if (button) button.disabled = true;
    try {
      await task();
    } catch (error) {
      showToast(error.status === 403 ? REMOTE_NOTE : error.message, 'error');
    } finally {
      busy = false;
      drawn = '';          // 상태가 그대로여도(거절 등) 꺼 둔 단추를 되살리게 한 번은 다시 그린다
      refresh();
    }
  }

  async function onClick(event) {
    const licBtn = event.target.closest('[data-anima-lic]');
    if (licBtn) {
      const id = licBtn.getAttribute('data-anima-lic');
      if (licOpen.has(id)) licOpen.delete(id);
      else {
        licOpen.add(id);
        if (licText[id] == null) {
          fetchFn(`${API}/licenses/${encodeURIComponent(id)}`, { cache: 'no-store' })
            .then(res => (res.ok ? res.text() : Promise.reject(new Error(String(res.status)))))
            .then(text => { licText[id] = text; render(); })
            .catch(() => { licText[id] = '원문을 불러오지 못했습니다.'; render(); });
        }
      }
      render();
      return;
    }
    if (!st) return;
    const engineBtn = event.target.closest('[data-anima-engine]');
    if (engineBtn && !engineBtn.disabled) {
      const engine = engineBtn.getAttribute('data-anima-engine');
      if ((engine === 'managed') === (st.comfyui_engine === 'managed')) return;
      run(engineBtn, async () => {
        await call('POST', '/select', { engine });
        onEngineChanged(engine);
        showToast(engine === 'managed' ? 'ANIMA 로 생성합니다 (메인 모드 표시: ANIMA)' : '외부 ComfyUI 로 되돌렸습니다', 'success');
      });
      return;
    }
    const idleBtn = event.target.closest('[data-anima-idle]');
    if (idleBtn) {
      run(idleBtn, () => saveSettings({ idle_minutes: Number(idleBtn.getAttribute('data-anima-idle')) }));
      return;
    }
    const rmDir = event.target.closest('[data-anima-rmdir]');
    const rmLora = event.target.closest('[data-anima-rmlora]');
    if (rmDir || rmLora) {
      const kind = rmLora ? 'lora' : 'model';
      const index = Number((rmLora || rmDir).getAttribute(rmLora ? 'data-anima-rmlora' : 'data-anima-rmdir'));
      run(rmLora || rmDir, async () => {
        await saveSettings(removeDir(kind, index));
        if (kind === 'model') await inspect();
      });
      return;
    }
    const actBtn = event.target.closest('[data-anima-act]');
    if (!actBtn || actBtn.disabled) return;
    const act = actBtn.getAttribute('data-anima-act');
    if (act === 'inspect') { inspect(); return; }
    run(actBtn, async () => {
      if (act === 'prepare') {
        const body = { select_on_ready: true, force_verify: false, engine_root: currentRoot() };
        if (!consentStored()) body.consent = { bundle_sha256: lic ? lic.bundle_sha256 : '', agreed: agreed === true };
        const data = await call('POST', '/prepare', body);
        if (data.status) st = data.status;
      } else if (act === 'repair') {
        const data = await call('POST', '/prepare', { select_on_ready: false, force_verify: true });
        if (data.status) st = data.status;
      } else if (act === 'cancel') {
        await call('POST', '/cancel', {});
      } else if (act === 'start') {
        await call('POST', '/engine/start', {});
      } else if (act === 'stop') {
        await call('POST', '/engine/stop', {});
      } else if (act === 'adddir' || act === 'addlora') {
        const kind = act === 'addlora' ? 'lora' : 'model';
        const patch = addDir(kind);
        if (!patch) return;
        await saveSettings(patch);
        if (kind === 'lora') loraDraft = ''; else dirDraft = '';
        if (kind === 'model') await inspect();
      }
    });
  }

  function onInput(event) {
    const input = event.target.closest('[data-anima-input]');
    if (!input) return;
    const kind = input.getAttribute('data-anima-input');
    if (kind === 'root') rootDraft = input.value;
    else if (kind === 'dir') dirDraft = input.value;
    else if (kind === 'lora') loraDraft = input.value;
  }

  function onChange(event) {
    const agree = event.target.closest('[data-anima-agree]');
    if (agree) {
      agreed = agree.checked;
      render();
      return;
    }
    // 설치 위치를 다 고쳤다 — 그 위치로 공간 · 규칙을 다시 잰다
    if (event.target.closest('[data-anima-input="root"]')) inspect();
  }

  function onKeydown(event) {
    if (event.key !== 'Enter') return;
    const input = event.target.closest('[data-anima-input]');
    if (!input) return;
    const kind = input.getAttribute('data-anima-input');
    const act = kind === 'dir' ? 'adddir' : kind === 'lora' ? 'addlora' : null;
    if (!act) return;
    event.preventDefault();
    elBody.querySelector(`[data-anima-act="${act}"]`)?.click();
  }

  function onToggle(event) {
    if (event.target.matches && event.target.matches('details.anima-arts')) artsOpen = event.target.open;
  }

  function init() {
    ensureStyle();
    section.addEventListener('click', onClick);
    section.addEventListener('input', onInput);
    section.addEventListener('change', onChange);
    section.addEventListener('keydown', onKeydown);
    section.addEventListener('toggle', onToggle, true);
    refresh();   // 탭 이름 밑 상태를 처음부터 채운다(탭이 안 보이면 폴링은 이어 가지 않는다)
  }

  return { init, refresh };
}
