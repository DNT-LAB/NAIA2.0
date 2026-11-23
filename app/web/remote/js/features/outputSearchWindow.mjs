// History 창 - 히스토리 브라우저와 Output Search 를 합친 하나의 떠 있는 창(draggablePanel · 11-22).
// 본문은 outputSearch.mjs 하나를 쓴다 - 외부 브라우저 화면(output-search.html)도 같은 본문이다.
// 진입로는 히스토리 칸 머리의 ↗ 하나다. 범위 [이번 세션 | 전체] 는 본문 첫 줄에 있다.
// 떠 있는 창(draggablePanel) - 다른 창과 같은 URL(?v=)로 불러온다(다르면 창끼리 겹침 순서가 깨진다).
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';
import {createOutputSearch, OUTPUT_SEARCH_STYLE} from './outputSearch.mjs?v=20261123-livefeed2';

const STYLE = `
.dragpanel.output-search-win .dragpanel-body {padding:0;gap:0;overflow:hidden;display:flex;flex-direction:column}
.dragpanel.output-search-win .dragpanel-slot {justify-content:flex-end;gap:4px}
.output-search-win .osr-head-status {margin-right:auto;color:var(--text-dim);font-size:11px;white-space:nowrap}
.output-search-win .osr-head-btn {height:20px;padding:0 6px;font-size:11px;border:1px solid var(--border-dim);
  border-radius:4px;background:transparent;color:var(--text-muted);cursor:pointer}
.output-search-win .osr-head-btn:hover,.output-search-win .osr-head-btn.is-on {color:var(--text-primary);border-color:var(--border-glow)}
.output-search-win .osr {flex:1;min-height:0}
${OUTPUT_SEARCH_STYLE}
`;
// 뷰어 설정 판(viewerBindings 의 #vbPanel)은 레일 기준 겹침(10100)이라 떠 있는 창(10150) 밑에 깔린다 - 창에서 열 때만 올린다.
const SETTINGS_Z = '10400';

export function createOutputSearchWindow({
  document,
  window: win,
  showToast = () => {},
  confirmDialog = null,
  applyPrompt = null,
  // 그림에서 불러오기 · 모드 문 · 메타데이터 탭(11-23) - outputSearch.mjs 로 그대로 넘긴다.
  loadImage = null,
  loadState = null,
  showMetadata = null,
  openExternalUrl = null,
  // 이번 세션의 손(resultHistory.sessionActions) - 삭제 · 저장 규칙을 레일과 한 벌로 쓴다.
  session = null,
  createPanel = options => createDraggablePanel({document, window: win, ...options}),
}) {
  let shell = null;
  let view = null;
  const style = document.createElement('style');
  style.textContent = STYLE;
  document.head.appendChild(style);

  const openUrl = url => (typeof openExternalUrl === 'function' ? openExternalUrl(url) : Boolean(win.open(url, '_blank')));

  async function confirmAsk(message) {
    if (typeof confirmDialog === 'function') {
      try { return Boolean(await confirmDialog(message, {title: 'History', okText: '확인'})); }
      catch (_) { return false; }
    }
    return win.confirm(message);
  }

  function ensure(scope) {
    if (shell) return shell;
    shell = createPanel({
      id: 'outputSearchWindow',
      title: 'History',
      variant: 'output-search-win',
      storageKey: 'naia.outputSearch.window',
      width: Math.min(1120, Math.max(560, win.innerWidth - 120)),
      height: Math.min(760, Math.max(420, win.innerHeight - 140)),
      minWidth: 420,
      minHeight: 300,
      maxWidth: 2400,
      resizable: true,
    });
    shell.slot.innerHTML = `
      <span class="osr-head-status" data-osr-status></span>
      ${session ? '<button type="button" class="osr-head-btn" data-osr-settings data-viewer-settings-btn title="뷰어 설정 - 숏컷 바인딩 · 삭제 방식">⚙</button>' : ''}
      <button type="button" class="osr-head-btn" data-osr-refresh title="다시 찾기">↻</button>
      <button type="button" class="osr-head-btn" data-osr-ext title="외부 브라우저로 열기">↗</button>`;
    shell.slot.addEventListener('click', event => {
      if (event.target.closest('[data-osr-refresh]')) view?.refresh();
      const gear = event.target.closest('[data-osr-settings]');
      if (gear && session?.toggleSettings) {
        session.toggleSettings(gear);
        const panel = document.getElementById('vbPanel');
        if (panel) panel.style.zIndex = SETTINGS_Z;
      }
      if (event.target.closest('[data-osr-ext]')) {
        const query = view?.externalParams() || '';
        if (!openUrl(`/output-search.html${query ? '?' + query : ''}`)) showToast('브라우저를 열지 못했습니다 — 팝업 차단을 확인해 주세요.', 'error');
      }
    });
    // 창 머리 · 단추에 초점이 있을 때 누른 키도 창의 것이다. 안 막으면 뒤의 히스토리 레일(document 리스너)이
    // Del · Ctrl+A · Ctrl+D · Esc 를 **레일의 선택**에 쓴다 - 창에서 Del 을 눌렀는데 레일 그림이 지워진다.
    // Ctrl+S 도 여기서 끝낸다(창의 고른 것을 저장 - 메인 프리뷰 저장으로 넘어가지 않게).
    shell.el.addEventListener('keydown', event => {
      if (session?.isCapturing?.()) return;           // 숏컷 입력을 받는 중이면 그쪽 몫
      const key = String(event.key || '');
      const low = key.toLowerCase();
      const ctrl = event.ctrlKey || event.metaKey;
      if (ctrl && !event.altKey && !event.shiftKey && low === 's') {
        event.preventDefault();
        event.stopPropagation();
        view?.saveShortcut();
        return;
      }
      if (key === 'Delete' || key === 'Backspace' || key === 'Escape' || (ctrl && (low === 'a' || low === 'd'))) {
        event.stopPropagation();
      }
    });
    const host = document.createElement('div');
    shell.body.appendChild(host);
    view = createOutputSearch({
      document, window: win, host,
      storage: win.localStorage,
      initial: {scope},
      applyPrompt, loadImage, loadState, showMetadata, session, openUrl, confirmAsk,
      toast: (message, kind) => showToast(message, kind || 'info'),
      onStatus: ({partial, rows}) => {
        const node = shell.slot.querySelector('[data-osr-status]');
        if (node) node.textContent = partial ? `색인 중 ${Number(rows || 0).toLocaleString('en-US')}장` : '';
      },
    });
    return shell;
  }

  function show(scope) {
    const fresh = !shell;
    ensure(scope).open();
    if (!fresh && scope && view?.scope() !== scope) view.setScope(scope);
    else if (!fresh) view?.poke?.();
    view?.focus();
  }

  return {
    open(scope = 'session') { show(scope); },
    close() { shell?.close(); },
    /** 열려 있으면 닫는다. 다른 범위를 달라고 하면 닫지 않고 그 범위로 바꾼다. */
    toggle(scope = null) {
      if (shell?.isOpen() && (!scope || view?.scope() === scope)) { shell.close(); return; }
      show(scope || 'session');
    },
    isOpen: () => Boolean(shell?.isOpen()),
    /** 앱의 웹소켓 알림(새 그림 · 빠짐 · 비움)을 넘겨받는다 - 창을 한 번도 안 열었으면 할 일이 없다. */
    sessionEvent(type, payload) { view?.sessionEvent(type, payload); },
    /** Ctrl+S - 앱의 단일 판정이 부른다. 이 창 안에서 눌렀으면 true. */
    handleSaveShortcut(event) {
      if (!shell?.isOpen() || !view || !shell.el.contains(event.target)) return false;
      view.saveShortcut();
      return true;
    },
  };
}
