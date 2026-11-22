// Output Search 를 앱 안에 띄우는 떠 있는 창(draggablePanel). 본문은 outputSearch.mjs 하나를 쓴다 -
// 외부 브라우저 화면(output-search.html)도 같은 본문이다.
// 떠 있는 창(draggablePanel) - 다른 창과 같은 URL(?v=)로 불러온다(다르면 창끼리 겹침 순서가 깨진다).
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';
import {createOutputSearch, OUTPUT_SEARCH_STYLE} from './outputSearch.mjs?v=20261122-a';

const STYLE = `
.dragpanel.output-search-win .dragpanel-body {padding:0;gap:0;overflow:hidden;display:flex;flex-direction:column}
.dragpanel.output-search-win .dragpanel-slot {justify-content:flex-end;gap:4px}
.output-search-win .osr-head-status {margin-right:auto;color:var(--text-dim);font-size:11px;white-space:nowrap}
.output-search-win .osr-head-btn {height:20px;padding:0 6px;font-size:11px;border:1px solid var(--border-dim);
  border-radius:4px;background:transparent;color:var(--text-muted);cursor:pointer}
.output-search-win .osr-head-btn:hover {color:var(--text-primary);border-color:var(--border-glow)}
.output-search-win .osr {flex:1;min-height:0}
${OUTPUT_SEARCH_STYLE}
`;

export function createOutputSearchWindow({
  document,
  window: win,
  showToast = () => {},
  confirmDialog = null,
  applyPrompt = null,
  openExternalUrl = null,
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
      try { return Boolean(await confirmDialog(message, {title: 'Output Search', okText: '휴지통으로'})); }
      catch (_) { return false; }
    }
    return win.confirm(message);
  }

  function ensure() {
    if (shell) return shell;
    shell = createPanel({
      id: 'outputSearchWindow',
      title: 'Output Search',
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
      <button type="button" class="osr-head-btn" data-osr-refresh title="다시 찾기">↻</button>
      <button type="button" class="osr-head-btn" data-osr-ext title="외부 브라우저로 열기">↗</button>`;
    shell.slot.addEventListener('click', event => {
      if (event.target.closest('[data-osr-refresh]')) view?.refresh();
      if (event.target.closest('[data-osr-ext]')) {
        const query = view?.externalParams() || '';
        if (!openUrl(`/output-search.html${query ? '?' + query : ''}`)) showToast('브라우저를 열지 못했습니다 — 팝업 차단을 확인해 주세요.', 'error');
      }
    });
    const host = document.createElement('div');
    shell.body.appendChild(host);
    view = createOutputSearch({
      document, window: win, host,
      storage: win.localStorage,
      applyPrompt, openUrl, confirmAsk,
      toast: (message, kind) => showToast(message, kind || 'info'),
      onStatus: ({partial, rows}) => {
        const node = shell.slot.querySelector('[data-osr-status]');
        if (node) node.textContent = partial ? `색인 중 ${Number(rows || 0).toLocaleString('en-US')}장` : '';
      },
    });
    return shell;
  }

  return {
    open() { ensure().open(); view?.focus(); },
    close() { shell?.close(); },
    toggle() {
      if (shell?.isOpen()) { shell.close(); return; }
      ensure().open();
      view?.focus();
    },
    isOpen: () => Boolean(shell?.isOpen()),
  };
}
