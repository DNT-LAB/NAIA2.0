// API 설정 > "04 ANIMA" 탭 — NAIA 가 설치 · 관리하는 전용 ComfyUI(고정 그래프 Spectrum SPD · 모델 naiANIMA2d_v03).
// 사용자 지정 2026-09-27: 03 COMFYUI 다음 04 자리에(AI ASSIST 05 · GROK 06 으로 밀림).
// 백엔드 계약 = docs/ANIMA_MANAGED_ENGINE_CONTRACT_2026_09_27.md §8(/api/anima-engine/*). 백엔드가 없는 판(404)이면
// "이 버전에는 없음" 만 보이고 물러난다. 탭 이름 밑 글자 · 점도 여기서 채운다. style.css 는 건드리지 않는다(아래 STYLE).
// 예상 시간 · 속도는 싣지 않는다(사용자 지정) — 크기와 단계만.
// 설치 · 동의 · 엔진 제어는 NAIA 를 켠 PC 에서만(서버가 403) — 원격이면 안내만 하고 단추를 감춘다.
// 동의(I Agree)는 화면에서 받고 서버가 묶음 해시로 다시 검사한다(버튼을 우회해도 막힌다).
// 설치 화면은 짧게(사용자 지정 09-27 원격 시험): [설치] 맨 위 · 검사 · 받을 것은 오른쪽 칸 · 라이선스는 한 줄 동의 + [상세보기].

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
#setupAnimaSection .anima-arts-sum { margin-left: 8px; font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }
#setupAnimaSection ul.anima-arts-list { list-style: none; margin: 6px 0 0; padding: 2px 10px; border: 1px solid var(--border-dim);
  border-radius: 7px; background: var(--bg-card); }
#setupAnimaSection .anima-arts-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; column-gap: 10px;
  align-items: baseline; padding: 5px 0; font-size: 11px; color: var(--text-muted); border-top: 1px solid var(--border-dim); }
#setupAnimaSection .anima-arts-list li:first-child { border-top: 0; }
#setupAnimaSection .anima-arts-list li.is-have .anima-art-name { color: var(--text-dim); }
#setupAnimaSection .anima-art-name em { font-style: normal; font-size: 10px; color: var(--text-dim); margin-left: 6px; }
#setupAnimaSection .anima-art-have { grid-column: 2; font-size: 10px; color: var(--success); }
#setupAnimaSection .anima-art-size { grid-column: 3; font-family: var(--font-mono); font-size: 10px; color: var(--text-dim);
  text-align: right; }
#setupAnimaSection .anima-arts-list small { grid-column: 1 / -1; font-family: var(--font-mono); font-size: 9px;
  color: var(--text-dim); word-break: break-all; }
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
#setupAnimaSection [data-anima-body] > .setup-result { margin-top: 0; }
#setupAnimaSection .anima-install { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-start; }
#setupAnimaSection .anima-main { flex: 999 1 260px; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
#setupAnimaSection .anima-side { flex: 1 1 240px; min-width: 0; display: flex; flex-direction: column; gap: 8px;
  padding: 10px 12px; border: 1px solid var(--border-dim); border-radius: 8px; background: var(--bg-card); }
#setupAnimaSection .anima-main .setup-actions { margin-top: 0; }
#setupAnimaSection .anima-main .setup-field-label { margin: 0 0 6px; }
#setupAnimaSection .anima-main .setup-result { margin-top: 6px; }
#setupAnimaSection .anima-side .setup-result { margin-top: 0; }
#setupAnimaSection .anima-kv { display: flex; gap: 8px; align-items: baseline; }
#setupAnimaSection .anima-side .anima-label { min-width: 34px; }
#setupAnimaSection .anima-consent { display: flex; flex-direction: column; gap: 3px; }
#setupAnimaSection .anima-consent-top { display: flex; align-items: baseline; gap: 8px; margin-bottom: 3px; }
#setupAnimaSection .anima-consent-top .setup-field-label { margin: 0; }
#setupAnimaSection .anima-consent-base { font-size: 11px; color: var(--text-primary); }
#setupAnimaSection .anima-consent-base span { margin-left: 6px; font-size: 10px; color: var(--text-dim); }
#setupAnimaSection .anima-consent-names { font-size: 11px; color: var(--text-muted); line-height: 1.5; }
#setupAnimaSection .anima-consent-names span { white-space: nowrap; }
#setupAnimaSection .anima-agree { display: flex; align-items: center; gap: 8px; margin-top: 6px; cursor: pointer;
  font-size: 12px; font-weight: 600; color: var(--text-primary); }
#setupAnimaSection .anima-agree input { margin: 0; cursor: pointer; }
#setupAnimaSection .anima-agreed { margin-top: 6px; font-size: 11px; color: var(--success); }
#setupAnimaSection .anima-lic-more { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
#setupAnimaSection .anima-path-row { display: flex; align-items: center; gap: 8px; }
#setupAnimaSection .anima-path { flex: 1; min-width: 0; font-family: var(--font-mono); font-size: 11px;
  color: var(--text-primary); word-break: break-all; }
#setupAnimaSection .anima-path-row em { flex: none; font-style: normal; font-size: 10px; color: var(--text-dim); }
#setupAnimaSection .anima-diag { display: flex; gap: 14px; align-items: center; }
#setupAnimaSection .anima-diag .anima-link { margin-left: 0; }
#setupAnimaSection .anima-diag-text { max-height: 260px; overflow: auto; white-space: pre-wrap; word-break: break-word;
  font-family: var(--font-mono); font-size: 10px; line-height: 1.45; color: var(--text-muted); user-select: text;
  background: var(--bg-surface); border: 1px solid var(--border-dim); border-radius: 6px; padding: 8px; margin: 0; }
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
// 라이선스 동의 한 줄(사용자 지정 09-27): 바탕 = NVIDIA Cosmos(NVIDIA Open Model License), 나머지는 짧은 이름으로.
const LIC_BASE = 'nvidia_open_model';
const LIC_SHORT = {
  gpl3_naia: 'NAIA', gpl3_comfyui: 'ComfyUI', portable_components: 'PyTorch', mit_spectrum: 'MIT (Spectrum)',
  circlestone_nc: 'CircleStone ANIMA', apache2_qwen: 'Apache 2.0 (Qwen)', lgpl_7zip: '7-Zip LGPL 2.1',
  nvidia_open_model: 'NVIDIA Open Model License',
};
const IDLE_OPTIONS = [
  { v: 0, t: '안 끔' }, { v: 10, t: '10분' }, { v: 30, t: '30분' }, { v: 60, t: '1시간' }, { v: 120, t: '2시간' },
];
const REMOTE_NOTE = '설치와 엔진 제어는 NAIA 를 켠 PC 에서만 할 수 있습니다.';

export function createAnimaSetupPanel({ document, fetch: fetchFn = window.fetch.bind(window), showToast = () => {},
  onEngineChanged = () => {}, onModelsChanged = () => {} }) {
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
  let loraDraft = '';        // LoRA 폴더 입력칸
  let licMore = false;       // 라이선스 [상세보기] 펼침
  let artsOpen = false;      // "받을 것" 펼침
  let busy = false;          // 요청 보내는 중(연타 막기)
  let pollTimer = 0;
  let drawn = '';            // 마지막으로 그린 입력 — 같으면 다시 그리지 않는다(입력 중인 칸을 지키려고)
  let lastState = '';
  let lastEngine = '';
  // 실패 화면의 [자세히] · [에러 로그 복사](사용자 지정 09-29 - Radeon 등 NVIDIA 가 아닌 PC 의 제보용)
  let diag = null;           // 마지막으로 받은 진단 텍스트(GET /diagnostics)
  let diagOpen = false;      // [자세히] 펼침
  let diagLoading = false;
  let diagPlaced = false;    // 한 화면에 한 번만 - 그리기마다 되돌린다
  let lastError = null;      // 마지막 요청 오류 {code, message} - 알림은 사라지니 화면에도 남긴다(다음 요청 때 지운다)

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
      // 백엔드 문구는 '[코드] 설명'(core/anima_engine/runtime.py)인데 이 창은 코드를 따로 붙인다(anima-code) —
      // 앞의 [코드] 를 떼야 한 번만 보인다(통합 시험 09-27: "[PATH_INVALID] … PATH_INVALID"). 알림은 run() 이 붙인다.
      const code = data.code || '';
      const text = String(data.error || `요청 실패 (${res.status})`);
      const error = new Error(code && text.startsWith(`[${code}] `) ? text.slice(code.length + 3) : text);
      error.status = res.status;
      error.code = code;
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

  function errorHtml(e) {
    return `<div class="setup-result error">${esc(e.message)}${e.code ? `<span class="anima-code">${esc(e.code)}</span>` : ''}</div>`;
  }

  // [자세히] · [에러 로그 복사] - 맨 위의 실패 옆에 한 번만. 원격 기기는 뺀다(진단은 이 PC 에서 nvidia-smi · 그래픽 카드
  // 조회를 돌린다 - 서버도 로컬만 받는다). 진단 텍스트는 누를 때마다 새로 모은다.
  function diagOnce() {
    if (diagPlaced || remote) return '';
    diagPlaced = true;
    return `<div class="anima-diag">
        <button type="button" class="anima-link" data-anima-diag="toggle">${diagOpen ? '접기' : '자세히'}</button>
        <button type="button" class="anima-link" data-anima-diag="copy">에러 로그 복사</button>
      </div>${diagOpen ? `<pre class="anima-diag-text">${esc(diagLoading && !diag ? '진단 정보를 모으는 중…' : diag || '')}</pre>` : ''}`;
  }

  // 설치 위치가 거절됐다(PATH_*) — 오류는 입력칸 밑에 둔다(오른쪽 칸에 두면 고칠 자리와 떨어진다)
  const pathError = () => Boolean(planError) && /^PATH_/.test(planError.code || '');

  // 오른쪽 칸 — PC 검사 결과 · 받을 것 · 다시 검사(사용자 지정 09-27). 받을 용량은 [설치] 단추와 '받을 것' 이 이미 말한다.
  // 검사가 실패했으면 옛 결과를 보이지 않는다(다른 설치 위치를 잰 숫자다).
  function viewCheck() {
    if (inspecting) return '<div class="anima-note">PC 검사 중…</div>';
    const again = `<div class="anima-row"><button type="button" class="setup-btn-ghost" data-anima-act="inspect">${
      plan || planError ? '다시 검사' : 'PC 검사'}</button></div>`;
    if (planError && !pathError()) return errorHtml(planError) + diagOnce() + again;
    if (planError) return `<div class="anima-note">설치 위치를 고치면 다시 검사합니다</div>${again}`;
    if (!plan) return `<div class="anima-note">RTX 20 시리즈 이상 NVIDIA GPU 가 필요합니다</div>${again}`;
    const gpu = plan.gpu || {};
    const vram = Number(gpu.vram_mb) ? ` · ${Math.round(Number(gpu.vram_mb) / 1024)}GB` : '';
    const gpuText = gpu.name ? `${gpu.name}${vram}` : 'NVIDIA GPU 를 찾지 못했습니다';
    const checks = (plan.checks || []).filter(c => !c.ok || c.message)
      .map(c => `<li class="${c.ok ? '' : 'bad'}">${c.ok ? '✓' : '✕'} ${esc(c.message || c.code || c.id)}</li>`).join('');
    return `<div class="anima-kv"><span class="anima-label">GPU</span><span class="anima-val"${
        gpu.driver ? ` title="드라이버 ${esc(gpu.driver)}"` : ''}>${esc(gpuText)}</span></div>
      ${checks ? `<ul class="anima-list anima-checks">${checks}</ul>` : ''}${(plan.checks || []).some(c => !c.ok) ? diagOnce() : ''}
      <div class="anima-kv"><span class="anima-label">용량</span><span class="anima-detail">필요 ${fmtBytes(plan.required_bytes)}
        · 남은 ${fmtBytes(plan.free_bytes)}</span></div>
      ${viewArtifacts()}
      ${again}`;
  }

  // 받을 것 — 서버는 Spectrum 을 파일마다(spectrum:nodes.py …) 보낸다. 한 줄로 묶고 큰 것부터 놓는다. 제목이 이미
  // '받을 것' 이라 줄마다 '받기' 를 되풀이하지 않고, 이미 있는 것만 표시한다(사용자 지적 09-27: 16줄 나열이 난잡했다).
  function artifactRows(list) {
    const rows = [];
    const spectrum = [];
    for (const a of list) {
      if (String(a.id).startsWith('spectrum:')) spectrum.push(a);
      else rows.push({ label: ARTIFACT_LABEL[a.id] || a.id, size: Number(a.size) || 0, action: a.action, path: a.path });
    }
    if (spectrum.length) {
      rows.push({ label: ARTIFACT_LABEL.spectrum, note: `파일 ${spectrum.length}개`,
        size: spectrum.reduce((sum, a) => sum + (Number(a.size) || 0), 0),
        action: spectrum.some(a => a.action === 'download') ? 'download' : spectrum[0].action });
    }
    return rows.sort((a, b) => b.size - a.size);
  }

  function viewArtifacts() {
    const rows = artifactRows(plan.artifacts || []);
    if (!rows.length) return '';
    const toGet = rows.filter(r => r.action === 'download').length;
    const have = rows.length - toGet;
    const sum = [toGet ? `${toGet}개 · ${fmtBytes(plan.download_bytes)}` : '없음 · 모두 있음', have && toGet ? `있는 것 ${have}개` : '']
      .filter(Boolean).join(' · ');
    const items = rows.map(r => `<li${r.action === 'download' ? '' : ' class="is-have"'}>
        <span class="anima-art-name">${esc(r.label)}${r.note ? `<em>${esc(r.note)}</em>` : ''}</span>${
        r.action === 'download' ? '' : `<span class="anima-art-have">${esc(ACTION_LABEL[r.action] || r.action)}</span>`}
        <span class="anima-art-size">${fmtBytes(r.size)}</span>${
        r.action === 'reuse' && r.path ? `<small>${esc(r.path)}</small>` : ''}</li>`).join('');
    return `<details class="anima-arts"${artsOpen ? ' open' : ''}><summary>받을 것<span class="anima-arts-sum">${esc(sum)}</span></summary>
      <ul class="anima-arts-list">${items}</ul></details>`;
  }

  function viewRoot() {
    return `<div><label class="setup-field-label" for="setupAnimaRoot">설치 위치</label>
      <input class="setup-input setup-input-mono" id="setupAnimaRoot" data-anima-input="root" type="text"
             value="${esc(currentRoot())}" spellcheck="false" autocomplete="off"
             title="NAIA 폴더 밖에 둡니다 — NAIA 를 새 버전으로 바꿔도 다시 받지 않습니다">
      ${pathError() ? errorHtml(planError) : ''}</div>`;
  }

  function dirsHtml(dirs, attr) {
    const rows = dirs.map((d, i) => `<li><span>${esc(d)}</span>
      <button type="button" class="anima-x" data-${attr}="${i}" title="빼기" aria-label="빼기">✕</button></li>`).join('');
    return rows ? `<ul class="anima-list anima-dirs">${rows}</ul>` : '';
  }

  // 라이선스 — Cosmos 고지를 바탕 줄로, 나머지는 이름만 한 줄로 모아 한 번에 동의받는다(사용자 지정 09-27: 실제 ComfyUI
  // 설치도 이렇게 긴 동의서를 요구하지 않는다). 카드 · 원문 · 고지문 전체는 [상세보기]. 동의 대상은 언제나 서버 목록
  // 전체다(묶음 해시) — 짧은 이름이 없는 항목은 제목 그대로 싣는다.
  function viewLicenses() {
    if (!lic) return '<div class="anima-note">라이선스를 불러오는 중…</div>';
    const items = lic.items || [];
    const base = items.find(item => item.id === LIC_BASE);
    const notice = (lic.notices || {})[LIC_BASE];
    const short = item => LIC_SHORT[item.id] || item.title;
    // 이름은 통째로만 줄을 바꾼다('CircleStone / ANIMA' 처럼 끊기지 않게)
    const names = items.filter(item => item !== base).map(item => `<span>${esc(short(item))}</span>`).join(' · ');
    const baseLine = base
      ? `<div class="anima-consent-base">${esc(notice || short(base))}${notice ? `<span>${esc(short(base))}</span>` : ''}</div>` : '';
    const agree = consentStored()
      ? '<div class="anima-agreed">✓ 모두 동의했습니다</div>'
      : `<label class="anima-agree" for="setupAnimaAgree">
           <input type="checkbox" id="setupAnimaAgree" data-anima-agree${agreed ? ' checked' : ''}>
           <span>모두 동의합니다 (I Agree)</span></label>`;
    return `<div class="anima-consent">
        <div class="anima-consent-top"><span class="setup-field-label">라이선스</span>
          <button type="button" class="anima-link" data-anima-licmore>${licMore ? '접기' : '상세보기'}</button></div>
        ${baseLine}
        <div class="anima-consent-names">${names}</div>
        ${agree}
        ${licMore ? viewLicenseDetails(base) : ''}
      </div>`;
  }

  function viewLicenseDetails(base) {
    const items = (lic.items || []).map(item => {
      const open = licOpen.has(item.id);
      return `<li><div class="anima-lic-head"><b>${esc(item.title)}</b><span class="anima-lic-name">${esc(item.license || '')}</span>
          <button type="button" class="anima-link" data-anima-lic="${esc(item.id)}">${open ? '접기' : '원문'}</button></div>
        ${item.applies_to ? `<div class="anima-lic-for">${esc(item.applies_to)}</div>` : ''}
        ${open ? `<pre class="anima-lic-text">${esc(licText[item.id] == null ? '불러오는 중…' : licText[item.id])}</pre>` : ''}</li>`;
    }).join('');
    // 바탕 줄에 이미 보인 Cosmos 고지는 되풀이하지 않는다
    const notices = Object.entries(lic.notices || {}).filter(([id, n]) => n && !(base && id === LIC_BASE))
      .map(([, n]) => `<p>${esc(n)}</p>`).join('');
    return `<div class="anima-lic-more"><ul class="anima-list anima-lic">${items}</ul>
      ${notices ? `<div class="anima-notice">${notices}</div>` : ''}</div>`;
  }

  function viewInstallActions() {
    const ins = install();
    const blockers = plan ? (plan.checks || []).filter(c => !c.ok) : [];
    const consentOk = agreed || consentStored();
    // 검사 중이거나 실패한 채면 잠근다 — 옛 검사 결과(plan)가 남아 있어도 지금 칸의 위치는 아직 · 이미 거절됐다
    const why = inspecting ? 'PC 검사 중입니다'
      : planError ? (pathError() ? '설치 위치를 확인해 주세요' : 'PC 검사를 다시 해 주세요')
      : !plan ? 'PC 검사를 먼저 합니다'
        : blockers.length ? '검사를 통과하지 못했습니다'
          : !currentRoot() ? '설치 위치를 적어 주세요'
            : !consentOk ? '라이선스에 동의해야 설치할 수 있습니다' : '';
    const ready = !why && Boolean(lic);
    const label = ins.state === 'failed' || ins.state === 'canceled' ? '다시 시작' : '설치';
    return `<div class="setup-actions">
      <button type="button" class="setup-btn-primary" data-anima-act="prepare"${ready && !busy ? '' : ' disabled'}>${
        label}${plan ? ` (${fmtBytes(plan.download_bytes)})` : ''}</button>
      ${why ? `<span class="anima-note">${esc(why)}</span>` : ''}</div>`;
  }

  // 사용자 지정 09-27(원격 시험): [설치] 를 맨 위로, PC 검사 · 받을 것 · 다시 검사는 오른쪽 칸(좁으면 아래로 접힌다).
  // 설명 문단 · 이미 받은 모델 폴더 칸은 뺐다.
  function viewInstaller() {
    const ins = install();
    const parts = [];
    const failed = ins.state === 'failed' || ins.state === 'blocked';
    if (failed) {
      parts.push(errorHtml({ message: ins.message || '설치하지 못했습니다', code: ins.code }));
    } else if (ins.state === 'canceled') {
      parts.push('<div class="anima-note">설치를 취소했습니다. 다시 시작하면 받은 만큼 이어서 받습니다.</div>');
    }
    if (lastError) parts.push(errorHtml(lastError));
    if (failed || lastError) parts.push(diagOnce());
    if (remote) {
      parts.push(`<div class="anima-note">${REMOTE_NOTE}</div>`);
      return parts.join('');
    }
    parts.push(`<div class="anima-install">
        <div class="anima-main">${viewInstallActions()}${viewRoot()}${viewLicenses()}</div>
        <div class="anima-side">${viewCheck()}</div>
      </div>`);
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
    // 엔진 시작 단계는 ComfyUI 를 켤 뿐이다 - 모델은 시험 생성 때 올라간다(09-29 지적: 시작 단계에 '모델을 올리느라' 가
    // 떠 있었다). 시작은 로그가 이어지는 동안 기다린다(runtime START_* - 출력 없이 3분이면 멈춘다).
    if (ins.phase === 'start') {
      parts.push('<div class="anima-note">ANIMA 엔진(ComfyUI)을 켜는 중입니다 — 처음 켤 때는 오래 걸릴 수 있습니다.</div>');
    } else if (ins.phase === 'smoke') {
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
    // [생성 엔진: 외부 ComfyUI | ANIMA] 줄은 없앴다(사용자 지정 09-27) — 메인 모드 선택의 COMFYUI ↔ ANIMA 와 같은
    // 스위치라 혼란스러웠다. 엔진은 메인 모드 선택에서만 바꾼다(app.js onComfyEngineChanged).
    const parts = [];
    const engText = {
      running: `실행 중${eng.port ? ` · 127.0.0.1:${eng.port}` : ''}`, starting: '시작 중…', stopping: '끄는 중…',
      crashed: '비정상 종료', stopped: '꺼짐',
    }[eng.state] || '꺼짐';
    const engBtn = remote ? ''
      : eng.state === 'running' ? '<button type="button" class="setup-btn-ghost" data-anima-act="stop">끄기</button>'
        : eng.state === 'stopped' || eng.state === 'crashed' || !eng.state
          ? '<button type="button" class="setup-btn-ghost" data-anima-act="start">켜기</button>' : '';
    parts.push(`<div class="anima-row"><span class="anima-label">엔진</span><span class="anima-val">${esc(engText)}</span>${engBtn}</div>`);
    const crashed = eng.state === 'crashed' && eng.message;
    if (crashed) parts.push(errorHtml({ message: eng.message, code: eng.code }));
    if (lastError) parts.push(errorHtml(lastError));
    if (crashed || lastError) parts.push(diagOnce());
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
    // ANIMA 모델 경로(사용자 지정 09-28) — 경로 하나 · [변경](폴더 고르기 창) · [초기화](지정 위치 = 엔진의 모델 폴더).
    // 기본 모델은 경로를 바꿔도 목록 맨 앞에 남는다(대비책). ANIMA 인지는 가리지 않는다 — 개인 병합 모델일 수 있고,
    // 안 맞는 파일이면 생성 단계에서 엔진이 오류로 끝낸다. 앞 폴더와 이름이 같은 파일만 서버가 뺀다.
    const models = st.models || {};
    const chosen = (settings().unet_dirs || [])[0] || '';
    const skipped = models.skipped || [];
    const skipTitle = skipped.map(x => `${x.name} — ${x.reason === 'shadowed' ? '같은 이름이 앞 폴더에 있음' : x.reason}`).join('\n');
    parts.push(`<div class="setup-field-label">ANIMA 모델 경로</div>
      <div class="anima-path-row">
        <span class="anima-path" data-anima-unet-path>${esc(chosen || models.default_dir || '')}</span>${chosen ? '' : '<em>기본</em>'}
        <button type="button" class="setup-btn-ghost" data-anima-act="pickunet">변경</button>
        <button type="button" class="setup-btn-ghost" data-anima-act="resetunet"${chosen ? '' : ' disabled'}>초기화</button>
      </div>
      <div class="anima-note" data-anima-models>메인 화면 Model 칸에서 고릅니다 · 모델 ${(models.available || []).length}개${skipped.length
        ? ` · <span title="${esc(skipTitle)}">이름이 겹쳐 뺀 파일 ${skipped.length}개</span>` : ''}</div>`);
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
      [...licOpen], Object.keys(licText), agreed, busy, artsOpen, licMore, diag, diagOpen, diagLoading, lastError]);
    if (key === drawn && elBody.childElementCount) return;
    drawn = key;
    // 입력 중인 칸을 지킨다(폴링이 칸을 다시 그려도 글자 · 커서가 남게)
    const active = document.activeElement;
    const focusKey = active && elBody.contains(active) ? active.getAttribute('data-anima-input') : null;
    const selection = focusKey && typeof active.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
    let html;
    diagPlaced = false;
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

  // 진단 정보(GET /diagnostics) - nvidia-smi · Windows 그래픽 카드 조회를 도느라 1~2초 걸린다
  async function loadDiag() {
    diagLoading = true;
    render();
    try {
      diag = String((await call('GET', '/diagnostics')).text || '');
    } catch (error) {
      diag = `진단 정보를 모으지 못했습니다: ${error.code ? `[${error.code}] ` : ''}${error.message}`;
    } finally {
      diagLoading = false;
      render();
    }
    return diag;
  }

  // [에러 로그 복사] - 누른 때의 상태로 새로 모아 복사한다. ⚠️ 클립보드 쓰기는 **누른 순간** 시작한다(받아 올 글을
  // 약속으로 넘긴다 - ClipboardItem). 받아 온 뒤(1~2초)에 쓰면 사용자 조작 밖이라 브라우저가 막았다(라이브 09-29).
  // 그래도 막히면 [자세히] 를 펼쳐 글 전체를 선택해 둔다 - Ctrl+C 한 번이면 된다.
  async function copyDiag() {
    const fresh = loadDiag();
    const clip = globalThis.navigator && globalThis.navigator.clipboard;
    try {
      if (typeof globalThis.ClipboardItem === 'function' && clip && typeof clip.write === 'function') {
        await clip.write([new globalThis.ClipboardItem({
          'text/plain': fresh.then(text => new Blob([text], { type: 'text/plain' })) })]);
      } else {
        await clip.writeText(await fresh);
      }
      showToast('에러 로그를 복사했습니다 — 제보에 붙여 넣어 주세요', 'success');
    } catch (_) {
      await fresh;
      diagOpen = true;
      render();
      const pre = elBody && elBody.querySelector('.anima-diag-text');
      const selection = globalThis.getSelection && globalThis.getSelection();
      if (pre && selection && typeof document.createRange === 'function') {
        const range = document.createRange();
        range.selectNodeContents(pre);
        selection.removeAllRanges();
        selection.addRange(range);
      }
      showToast('자동 복사가 막혔습니다 — 펼친 글이 선택돼 있으니 Ctrl+C 를 눌러 주세요', 'error');
    }
  }

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

  // 상태를 받았다 - 조회와 설치([설치] · [복구]) 응답이 둘 다 여기로 온다.
  // 설치가 끝났다 — 엔진이 바뀌었을 수 있으니 기존 연결 확인 흐름(probe_api)을 다시 태운다(계약서 §9.5).
  // 설치 작업 없이 바로 준비됨이 된 것(이미 끝난 설치를 가져다 썼다 - 09-29)도 같다. 첫 조회('')는 아니다.
  // 준비된 채 엔진 선택만 바뀐 것도 알린다: 설치 응답보다 조회가 먼저 와 '외부' 를 알린 뒤 '관리형' 이 되면
  // 준비됨 -> 준비됨이라 알림이 빠졌다(Codex 09-29).
  function applyStatus(next) {
    st = next;
    const state = st ? install().state : '';
    const engine = st ? String(st.comfyui_engine || '') : '';
    if (lastState && state === 'ready' && (lastState !== 'ready' || engine !== lastEngine)) onEngineChanged(engine);
    lastState = state;
    lastEngine = engine;
  }

  async function refresh() {
    let next = null;
    try {
      const res = await fetchFn(`${API}/status`, { cache: 'no-store' });
      if (res.status === 404) {
        missing = true;
      } else {
        missing = false;
        next = await res.json();
      }
    } catch (error) {
      if (elStatus) elStatus.textContent = '상태를 읽지 못했습니다';
      schedule();
      return;
    }
    applyStatus(next);
    const state = st ? install().state : '';
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

  // [변경] — 앱(Electron)이면 폴더 고르기 창(제목 · 지금 경로에서 연다), 브라우저면 경로를 적는다(데이터 이전 화면과 같은 방식)
  async function pickModelFolder() {
    const current = (settings().unet_dirs || [])[0] || (st.models || {}).default_dir || '';
    const shell = globalThis.naiaShell;
    if (shell && typeof shell.pickDirectory === 'function') {
      try {
        return await shell.pickDirectory({ title: 'ANIMA 모델 폴더 선택', defaultPath: current });
      } catch (_) {
        return null;
      }
    }
    const entered = globalThis.prompt?.('ANIMA 모델 폴더의 전체 경로를 입력하세요', current);
    return entered ? String(entered).trim() : null;
  }

  const sameFolder = (a, b) => Boolean(a && b)
    && String(a).replace(/[\\/]+$/, '').toLowerCase() === String(b).replace(/[\\/]+$/, '').toLowerCase();

  // 폴더 목록 칸(lora_dirs · unet_dirs) — 서버가 폴더를 바꾸면 엔진을 내렸다가 다음 생성 때 새 경로로 켠다
  function addDirPatch(key, draft) {
    const value = draft.trim();
    if (!value) return null;
    const dirs = [...(settings()[key] || [])];
    if (!dirs.includes(value)) dirs.push(value);
    return { [key]: dirs };
  }

  function removeDirPatch(key, index) {
    const dirs = [...(settings()[key] || [])];
    dirs.splice(index, 1);
    return { [key]: dirs };
  }

  async function run(button, task) {
    if (busy) return;
    busy = true;
    lastError = null;
    if (button) button.disabled = true;
    try {
      await task();
    } catch (error) {
      if (error.status !== 403) lastError = { code: error.code || '', message: error.message };
      showToast(error.status === 403 ? REMOTE_NOTE : `${error.code ? `[${error.code}] ` : ''}${error.message}`, 'error');
    } finally {
      busy = false;
      drawn = '';          // 상태가 그대로여도(거절 등) 꺼 둔 단추를 되살리게 한 번은 다시 그린다
      refresh();
    }
  }

  async function onClick(event) {
    const diagBtn = event.target.closest('[data-anima-diag]');
    if (diagBtn) {
      if (diagBtn.getAttribute('data-anima-diag') === 'copy') copyDiag();
      else {
        diagOpen = !diagOpen;
        if (diagOpen) loadDiag();
        else render();
      }
      return;
    }
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
    if (event.target.closest('[data-anima-licmore]')) {
      licMore = !licMore;
      render();
      return;
    }
    if (!st) return;
    const idleBtn = event.target.closest('[data-anima-idle]');
    if (idleBtn) {
      run(idleBtn, () => saveSettings({ idle_minutes: Number(idleBtn.getAttribute('data-anima-idle')) }));
      return;
    }
    const rmLora = event.target.closest('[data-anima-rmlora]');
    if (rmLora) {
      const index = Number(rmLora.getAttribute('data-anima-rmlora'));
      run(rmLora, () => saveSettings(removeDirPatch('lora_dirs', index)));
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
        if (data.status) applyStatus(data.status);
      } else if (act === 'repair') {
        const data = await call('POST', '/prepare', { select_on_ready: false, force_verify: true });
        if (data.status) applyStatus(data.status);
      } else if (act === 'cancel') {
        await call('POST', '/cancel', {});
      } else if (act === 'start') {
        await call('POST', '/engine/start', {});
      } else if (act === 'stop') {
        await call('POST', '/engine/stop', {});
      } else if (act === 'addlora') {
        const patch = addDirPatch('lora_dirs', loraDraft);
        if (!patch) return;
        await saveSettings(patch);
        loraDraft = '';
      } else if (act === 'pickunet') {
        const folder = await pickModelFolder();
        if (!folder) return;
        // 지정 위치를 골랐으면 초기화와 같다(같은 폴더를 두 번 넣지 않는다)
        await saveSettings({ unet_dirs: sameFolder(folder, (st.models || {}).default_dir) ? [] : [folder] });
        onModelsChanged();     // 메인 Model 칸 목록을 새로 받는다
      } else if (act === 'resetunet') {
        await saveSettings({ unet_dirs: [] });
        onModelsChanged();
      }
    });
  }

  function onInput(event) {
    const input = event.target.closest('[data-anima-input]');
    if (!input) return;
    const kind = input.getAttribute('data-anima-input');
    if (kind === 'root') rootDraft = input.value;
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
    const act = kind === 'lora' ? 'addlora' : null;
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
