/**
 * 뷰어 숏컷 바인딩 — 버튼 하나로 보고 있는 그림을 정해 둔 폴더에 넘긴다.
 *
 * Dev0714 데스크톱 뷰어(`ui/image_viewer_window.py` 의 ViewerBindingsDialog)를 옮긴 것이다.
 * **앱(Electron)에서만 뜬다**: 폴더를 고르려면 시스템 폴더 선택 창이 필요한데 브라우저에는
 * 그런 것이 없다. 경로를 손으로 타이핑하게 하는 것은 오타 하나로 엉뚱한 데에 파일이 쌓이는
 * 길이라 하지 않는다.
 *
 * 실행 요청은 경로를 보내지 않는다 — `input_id` 만 보내고 어디에 쓸지는 서버가 저장된
 * 설정에서 찾는다(백엔드 주석 참조).
 */

const MAX_BINDINGS = 12;

// 뷰어 손버릇 설정. 숏컷 바인딩과 달리 파일시스템을 건드리지 않고 **이 기기에서만**
// 뜻이 있으므로 서버가 아니라 localStorage 에 둔다(레일 접힘·삭제 방식과 같은 자리).
const PREF_NO_CONFIRM = 'naia_history_delete_no_confirm';
const PREF_DELETE_KEY_D = 'naia_history_delete_key_d';
// 삭제 방식은 우클릭 메뉴가 쓰던 것과 **같은 키**다. 새 키를 파면 두 곳이
// 서로 다른 값을 보게 된다 — 한 벌만 둔다.
const PREF_DELETE_MODE = 'naia_result_delete_mode';

function readPref(key) {
  try { return localStorage.getItem(key) === '1'; } catch (_) { return false; }
}

function writePref(key, on) {
  try { localStorage.setItem(key, on ? '1' : '0'); } catch (_) {}
}

function readDeleteToDisk() {
  try { return localStorage.getItem(PREF_DELETE_MODE) === 'disk'; } catch (_) { return false; }
}

function writeDeleteToDisk(on) {
  try { localStorage.setItem(PREF_DELETE_MODE, on ? 'disk' : 'history'); } catch (_) {}
}

/**
 * innerHTML 에 넣기 전에 반드시 통과시킨다.
 *
 * 남이 심어 놓은 값이라서가 아니라 **내가 만든 값이 이미 위험하기 때문**이다:
 * `inputIdFromKey` 는 `KeyboardEvent.key` 를 그대로 쓰는데, `<` 키를 숏컷으로
 * 잡으면 `key:<` 가 되어 그 자리에서 태그가 열린다. 폴더 이름에도 `&` 나 `"`
 * 는 얼마든지 들어간다. (Codex 리뷰 P1)
 */
function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function createViewerBindings({
  getEl,
  showToast,
  onItemRemoved,
  openSaveDirectory = null,
  getSaveDirectory = () => '',
  requestSaveDirectory = () => {},
  openQuicksaveSettings = null,
}) {
  let settings = {bindings: [], quicksave_dir: '', quicksave_resolved: ''};
  let loaded = false;
  let capturing = null;      // 지금 입력을 받고 있는 행 (index)
  let panelOpen = false;
  let anchorEl = null;       // 판을 띄운 버튼 — 그 아래에 붙인다
  let busy = false;
  const prefs = {
    noConfirm: readPref(PREF_NO_CONFIRM),
    deleteKeyD: readPref(PREF_DELETE_KEY_D),
    deleteToDisk: readDeleteToDisk(),
  };

  const isAppMode = () => Boolean(globalThis.naiaShell?.pickDirectory);

  // ── 입력 식별 ────────────────────────────────────────────────────────────
  // 데스크톱은 Qt 의 키 정수를 그대로 썼지만, 웹에서는 `KeyboardEvent.key` 가 사람이
  // 읽을 수 있으면서 자판 배열에도 흔들리지 않는다. 마우스는 button 번호로 굳힌다.
  const MOUSE_NAMES = {1: 'middle', 3: 'back', 4: 'forward'};

  function inputIdFromMouse(button) {
    return `mouse:${MOUSE_NAMES[button] || button}`;
  }

  function inputIdFromKey(event) {
    const parts = [];
    if (event.ctrlKey) parts.push('ctrl');
    if (event.altKey) parts.push('alt');
    if (event.shiftKey) parts.push('shift');
    const key = String(event.key || '');
    parts.push(key.length === 1 ? key.toLowerCase() : key);
    return `key:${parts.join('+')}`;
  }

  function inputLabel(inputId) {
    const text = String(inputId || '');
    if (text.startsWith('mouse:')) {
      const name = text.slice(6);
      return {middle: '마우스 휠 클릭', back: '마우스 뒤로', forward: '마우스 앞으로'}[name]
        || `마우스 ${name}`;
    }
    if (text.startsWith('key:')) {
      return text.slice(4).split('+')
        .map(p => ({ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift'}[p] || p))
        .join(' + ');
    }
    return text || '(없음)';
  }

  // ── 저장소 ───────────────────────────────────────────────────────────────
  /**
   * 뷰어를 열 때마다 다시 읽는다.
   *
   * 한 번만 읽고 캐시했더니, 창을 둘 열어 둔 상태에서 한쪽이 설정을 바꾸면 다른
   * 쪽은 옛 목록을 들고 있었다(실측). 파일이 엉뚱한 데로 가지는 **않는다** —
   * 무엇을 어디에 할지는 서버가 매번 자기 설정을 다시 읽어 정하고, 여기 있는
   * 값은 '이 키가 발화하는가'와 토스트 문구에만 쓰인다. 그래도 방금 지운 숏컷이
   * 계속 먹거나 새로 만든 것이 안 먹는 것은 그 자체로 고장이다. 팝업 한 번에
   * GET 한 번이면 이 부류가 통째로 사라진다.
   */
  async function load(force = true) {
    try {
      const resp = await fetch('/api/viewer/bindings');
      if (resp.ok) settings = await resp.json();
      loaded = true;
    } catch (_) {
      // 못 읽어도 뷰어는 열려야 한다 — 들고 있던 것으로 간다.
    }
    return settings;
  }

  async function persist() {
    try {
      const resp = await fetch('/api/viewer/bindings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({bindings: settings.bindings}),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok) throw new Error(data.error || `HTTP ${resp.status}`);
      settings = data;
      return true;
    } catch (error) {
      showToast(`숏컷 저장 실패: ${error.message}`, 'error');
      return false;
    }
  }

  // ── 실행 ─────────────────────────────────────────────────────────────────
  function hasBinding(inputId) {
    return settings.bindings.some(b => b.input_id === inputId);
  }

  async function dispatch(inputId, relPath) {
    if (busy || !relPath) return false;
    const binding = settings.bindings.find(b => b.input_id === inputId);
    if (!binding) return false;
    busy = true;
    try {
      const resp = await fetch('/api/viewer/bindings/dispatch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: relPath, input_id: inputId}),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok) throw new Error(data.error || `HTTP ${resp.status}`);
      if (binding.action === 'trash') {
        // 삭제는 목록에서도 빠져야 한다. 브로드캐스트가 오기 전에 먼저 걷는다 —
        // 방금 지운 것이 잠깐이라도 남아 있으면 또 누르게 된다.
        if (data.removed) onItemRemoved?.(data.removed);
        showToast('휴지통으로 보냈습니다.', 'success');
      } else {
        const where = String(data.path || '').replace(/^.*[\\/]/, '');
        showToast(`${binding.action === 'move' ? '이동' : '복사'} — ${where}`, 'success');
      }
      return true;
    } catch (error) {
      showToast(`숏컷 실패: ${error.message}`, 'error');
      return false;
    } finally {
      busy = false;
    }
  }

  // ── 설정 패널 ────────────────────────────────────────────────────────────
  function rowHtml(binding, index) {
    const actions = ['copy', 'move', 'trash'];
    const labels = settings.action_labels || {copy: '복사', move: '이동', trash: '삭제 (휴지통)'};
    const options = actions.map(a =>
      `<option value="${a}"${binding.action === a ? ' selected' : ''}>${esc(labels[a])}</option>`).join('');
    const dest = binding.dest_path || '';
    return `
      <div class="vb-row" data-vb-row="${index}">
        <button type="button" class="vb-capture" data-vb-capture="${index}"
                title="누르면 다음에 누르는 키나 마우스 버튼을 받습니다">${esc(inputLabel(binding.input_id))}</button>
        <select class="vb-action" data-vb-action="${index}">${options}</select>
        <button type="button" class="vb-dest" data-vb-dest="${index}"
                title="${esc(dest || '따로 안 정하면 Ctrl+S 빠른 저장 경로로 갑니다')}">${
                  esc(dest ? shortPath(dest) : '빠른 저장 경로')}</button>
        <button type="button" class="vb-del" data-vb-del="${index}" aria-label="삭제">&times;</button>
      </div>`;
  }

  function shortPath(path) {
    const parts = String(path).split(/[\\/]/).filter(Boolean);
    return parts.length <= 2 ? path : `…/${parts.slice(-2).join('/')}`;
  }

  function toggleHtml(id, label, on, hint) {
    return `
      <button type="button" class="vb-toggle${on ? ' is-on' : ''}" id="${id}"
              role="switch" aria-checked="${on ? 'true' : 'false'}">
        <span class="vb-toggle-track"><span class="vb-toggle-knob"></span></span>
        <span class="vb-toggle-label">${esc(label)}${
          hint ? `<em>${esc(hint)}</em>` : ''}</span>
      </button>`;
  }

  /**
   * 판은 **팝업 밖**, `document.body` 에 산다.
   *
   * 처음에는 히스토리 팝업 안에 넣었는데, 그러면 팝업이 열려 있을 때만 쓸 수 있다.
   * 레일(136px)에서도 같은 설정을 열어야 하는데 그 폭 안에서는 아무것도 못 그린다.
   * body 로 빼면 한 벌로 둘 다 된다 — 누른 버튼 아래에 붙여 띄운다.
   */
  function ensureHost() {
    let host = document.getElementById('vbPanel');
    if (!host) {
      host = document.createElement('div');
      host.id = 'vbPanel';
      host.className = 'vb-panel';
      document.body.appendChild(host);
      // 판 바깥을 누르면 닫는다. 판을 연 버튼을 다시 누르는 경우는 토글이
      // 처리하므로 여기서 빼 준다 — 안 그러면 닫고 곧바로 다시 연다.
      document.addEventListener('pointerdown', event => {
        if (!panelOpen) return;
        if (host.contains(event.target)) return;
        if (anchorEl && anchorEl.contains(event.target)) return;
        setPanelOpen(false);
      }, true);
    }
    return host;
  }

  function positionPanel(host) {
    if (!anchorEl) return;
    const box = anchorEl.getBoundingClientRect();
    const width = host.offsetWidth || 380;
    // 오른쪽 모서리를 버튼에 맞추되 화면 밖으로 나가지 않게 민다.
    let left = Math.min(box.right - width, window.innerWidth - width - 10);
    left = Math.max(10, left);
    const below = box.bottom + 6;
    const height = host.offsetHeight || 240;
    // 아래에 자리가 없으면 위로 뒤집는다(레일 발치 버튼이 그렇다).
    const top = below + height > window.innerHeight - 10
      ? Math.max(10, box.top - height - 6)
      : below;
    host.style.left = `${Math.round(left)}px`;
    host.style.top = `${Math.round(top)}px`;
  }

  function render() {
    const host = ensureHost();
    if (!host) return;
    // 숏컷 구역은 앱에서만 그린다 — 폴더를 고르려면 시스템 선택 창이 필요하다.
    // 위의 손버릇 토글은 폴더와 무관하므로 브라우저에서도 뜬다.
    const shortcutSection = isAppMode() ? `
      <div class="vb-sec">숏컷</div>
      <div class="vb-body">
        ${settings.bindings.map(rowHtml).join('')
          || '<div class="vb-empty">아직 없습니다. 아래에서 하나 더하세요.</div>'}
        <button type="button" class="vb-add" id="vbAdd"
                ${settings.bindings.length >= MAX_BINDINGS ? 'disabled' : ''}>+ 숏컷 더하기</button>
      </div>
      <button type="button" class="vb-link" id="vbQuicksaveDir"
              title="${esc(settings.quicksave_resolved || '')}">
        <span class="vb-link-label">기본 대상</span>
        <span class="vb-link-value">${
          esc(settings.quicksave_resolved ? shortPath(settings.quicksave_resolved) : '빠른 저장 경로')}</span>
      </button>
      <div class="vb-note">경로를 안 정한 숏컷은 <b>Ctrl+S 빠른 저장</b>과 같은 곳으로 갑니다.</div>` : '';

    host.innerHTML = `
      <div class="vb-head">
        <span class="vb-title">뷰어 설정</span>
        <span class="vb-spring"></span>
        <button type="button" class="vb-close" id="vbClose" aria-label="닫기">&times;</button>
      </div>
      <div class="vb-body vb-prefs">
        ${toggleHtml('vbDeleteToDisk', '저장 파일도 함께 삭제', prefs.deleteToDisk,
                     prefs.deleteToDisk
                       ? '파일은 휴지통으로 갑니다'
                       : '지금은 히스토리에서만 지웁니다 — 파일은 그대로 남습니다')}
        ${toggleHtml('vbNoConfirm', '삭제할 때 묻지 않음', prefs.noConfirm,
                     '되돌리려면 휴지통에서 꺼내야 합니다')}
        ${toggleHtml('vbDeleteKeyD', 'Ctrl+D 로 삭제', prefs.deleteKeyD,
                     'Ctrl+S 가 저장인 것과 짝을 맞춥니다')}
      </div>
      <div class="vb-sec">저장</div>
      <div class="vb-body">
        <button type="button" class="vb-link" id="vbSaveDir">
          <span class="vb-link-label">저장 경로</span>
          <span class="vb-link-value">${esc(shortPath(getSaveDirectory() || '아직 모름'))}</span>
        </button>
      </div>
      ${shortcutSection}`;
    bind(host);
    positionPanel(host);
  }

  function bind(host) {
    const on = (id, event, fn) => { const el = getEl(id); if (el) el.addEventListener(event, fn); };
    on('vbClose', 'click', () => setPanelOpen(false));
    on('vbSaveDir', 'click', () => {
      // 저장 경로는 이미 자기 판이 있다(기본 경로·세션 폴더·파일명 규칙·분류).
      // 여기에 한 벌 더 그리면 반드시 어긋나므로 그쪽을 열어 준다.
      setPanelOpen(false);
      if (typeof openSaveDirectory === 'function') openSaveDirectory();
      else showToast('저장 경로 설정을 열 수 없습니다.', 'error');
    });
    on('vbDeleteToDisk', 'click', () => {
      prefs.deleteToDisk = !prefs.deleteToDisk;
      writeDeleteToDisk(prefs.deleteToDisk);
      render();
    });
    on('vbNoConfirm', 'click', () => {
      prefs.noConfirm = !prefs.noConfirm;
      writePref(PREF_NO_CONFIRM, prefs.noConfirm);
      render();
    });
    on('vbDeleteKeyD', 'click', () => {
      prefs.deleteKeyD = !prefs.deleteKeyD;
      writePref(PREF_DELETE_KEY_D, prefs.deleteKeyD);
      render();
    });
    on('vbQuicksaveDir', 'click', () => {
      // 빠른 저장 경로는 Auto Save 판이 주인이다. 여기서 한 벌 더 그리면
      // 사용자가 두 곳을 맞춰 놓고 살아야 한다 — 그쪽을 열어 준다.
      setPanelOpen(false);
      if (typeof openQuicksaveSettings === 'function') openQuicksaveSettings();
      else showToast('빠른 저장 설정을 열 수 없습니다.', 'error');
    });
    on('vbAdd', 'click', async () => {
      if (settings.bindings.length >= MAX_BINDINGS) return;
      settings.bindings.push({input_id: '', action: 'copy', dest_path: ''});
      render();
      startCapture(settings.bindings.length - 1);
    });

    host.querySelectorAll('[data-vb-capture]').forEach(btn =>
      btn.addEventListener('click', () => startCapture(Number(btn.dataset.vbCapture))));
    host.querySelectorAll('[data-vb-action]').forEach(sel =>
      sel.addEventListener('change', async () => {
        const i = Number(sel.dataset.vbAction);
        settings.bindings[i].action = sel.value;
        await persist();
        render();
      }));
    host.querySelectorAll('[data-vb-dest]:not(.is-global)').forEach(btn =>
      btn.addEventListener('click', () => pickDest(Number(btn.dataset.vbDest))));
    host.querySelectorAll('[data-vb-del]').forEach(btn =>
      btn.addEventListener('click', async () => {
        settings.bindings.splice(Number(btn.dataset.vbDel), 1);
        await persist();
        render();
      }));
  }

  // 바인딩별 경로 고르기. 공용 폴더는 없어졌다(빠른 저장 경로를 쓴다).
  async function pickDest(index) {
    const picked = await globalThis.naiaShell?.pickDirectory?.().catch(() => null);
    // 선택 창을 그냥 닫으면 빈 값이 온다 — 그때 경로를 지우면 안 된다.
    const path = typeof picked === 'string' ? picked : (picked?.path || picked?.directory || '');
    if (!path) return;
    settings.bindings[index].dest_path = path;
    await persist();
    render();
  }

  function startCapture(index) {
    capturing = index;
    const btn = document.querySelector(`[data-vb-capture="${index}"]`);
    if (btn) {
      btn.classList.add('is-capturing');
      btn.textContent = '누르세요…';
    }
  }

  async function finishCapture(inputId) {
    const index = capturing;
    capturing = null;
    if (index === null || !settings.bindings[index]) { render(); return; }
    // 같은 입력이 이미 다른 행에 있으면 그쪽을 비운다 — 하나의 입력은 한 가지 일만 한다.
    settings.bindings.forEach((b, i) => { if (i !== index && b.input_id === inputId) b.input_id = ''; });
    settings.bindings[index].input_id = inputId;
    // 입력을 못 받은 채 남은 빈 행은 버린다.
    settings.bindings = settings.bindings.filter(b => b.input_id);
    await persist();
    render();
  }

  function setPanelOpen(open, anchor = null) {
    panelOpen = Boolean(open);
    if (anchor) anchorEl = anchor;
    const host = ensureHost();
    host.classList.toggle('open', panelOpen);
    // 판을 연 버튼만 눌린 티를 낸다(레일과 팝업에 각각 하나씩 있다).
    document.querySelectorAll('[data-viewer-settings-btn]').forEach(b =>
      b.classList.toggle('is-on', panelOpen && b === anchorEl));
    if (panelOpen) {
      render();
      // 저장 경로 상태는 그 모듈을 한 번도 안 열었으면 아직 안 와 있다.
      // 그때만 달라고 한다 — 도착하면 refresh() 가 다시 그린다.
      if (!getSaveDirectory()) requestSaveDirectory();
    } else capturing = null;
  }

  return {
    isAppMode,
    // 삭제 흐름이 물어볼 값 — 패널에서 켜고 끈 그대로 읽는다.
    skipDeleteConfirm: () => prefs.noConfirm,
    deleteKeyDEnabled: () => prefs.deleteKeyD,
    load,
    hasBinding,
    dispatch,
    setPanelOpen,
    // 저장 경로 상태가 뒤늦게 도착했을 때 판을 다시 그린다(열려 있을 때만).
    refresh: () => { if (panelOpen) render(); },
    // 다른 버튼에서 누르면 그쪽으로 옮겨 붙는다(닫히지 않는다).
    togglePanel: anchor => setPanelOpen(!(panelOpen && anchorEl === anchor), anchor),
    isPanelOpen: () => panelOpen,
    isCapturing: () => capturing !== null,
    finishCapture,
    inputIdFromMouse,
    inputIdFromKey,
  };
}
