// Real temporary-search lifecycle. Live controls move between shells; their full
// local state and the server's independent result model restore without a search.
export function createTemporarySearchPreview({
  document: doc, getSource, getSearch, getQuickFilter, getRefine, getWs, showToast,
}) {
  let original = null;
  let pendingRestore = null;
  let busy = false;
  let foreign = false;
  let restoring = false;

  function captureForms() {
    return [...doc.querySelectorAll('#searchQuickWindow input, #searchQuickWindow textarea, #searchQuickWindow select, #temporarySearchWindow input, #temporarySearchWindow textarea, #temporarySearchWindow select, #searchRefineSideWindow input')]
      .filter(el => el.id && el.id !== 'searchExcludePermanent')
      .map(el => ({id: el.id, value: el.value, checked: el.checked, scrollTop: el.scrollTop}));
  }
  function capture() {
    return {forms: captureForms(), search: getSearch().snapshotWorkspace(),
      tag: getQuickFilter().snapshotTemporaryDraft(), refine: getRefine().snapshotWorkspace()};
  }
  function restore(snapshot) {
    restoring = true;
    try {
      getSearch().restoreWorkspace(snapshot.search);
      getQuickFilter().restoreWorkspace(snapshot.tag);
      getRefine().restoreWorkspace(snapshot.refine);
      for (const item of snapshot.forms) {
        const el = doc.getElementById(item.id);
        if (!el) continue;
        el.value = item.value;
        if ('checked' in el) el.checked = item.checked;
        el.scrollTop = item.scrollTop;
      }
    } finally { restoring = false; }
  }
  function leave() {
    if (!original) return;
    const resumeChildren = getSource().leaveTemporary();
    getQuickFilter().setTemporaryMode(false);
    getRefine().setTemporaryMode(false);
    pendingRestore = original;
    restore(original);
    original = null;
    resumeChildren?.();
  }
  async function toggle() {
    const ws = getWs();
    if (busy || foreign) return;
    if (!ws || ws.readyState !== 1) { showToast('서버 연결 후 다시 시도해주세요.', 'error'); return; }
    busy = true;
    getSource().setTemporaryBusy(true, original ? '원본 복귀 중…' : '임시 검색 준비 중…');
    if (!await getQuickFilter().awaitWorkspaceIdle()) {
      busy = false;
      getSource().setTemporaryBusy(foreign);
      showToast('필터 적용이 끝난 뒤 다시 시도해주세요.', 'warning');
      return;
    }
    getQuickFilter().pauseWorkspace();
    getSearch().pauseWorkspace();
    getSearch().flushWorkspace();
    ws.send(JSON.stringify({type: original ? 'end_temporary_search' : 'begin_temporary_search'}));
  }
  function onState(message) {
    busy = !!message.pending;
    foreign = !!message.active && !message.owned;
    if (message.error) showToast(message.error, 'error');
    // 전환 중에는 창을 바꾸지 않는다. 그래도 **표시는 늘 이 메시지대로** 맞춘다 - 예전에는 여기서
    // 일찍 빠져나가, 늦게 온 '전환 중' 이 마지막 말로 남으면 단추가 꺼진 채 굳었다.
    if (!busy) {
      if (message.active && message.owned && !original) {
        original = capture();
        pendingRestore = original;
        getQuickFilter().setTemporaryMode(true);
        getRefine().setTemporaryMode(true);
        getSource().enterTemporary();
      } else if (!message.active) leave();
    }
    getSource()?.setTemporaryBusy(busy || foreign,
      busy ? '진행 중인 작업을 마친 뒤 전환…' : foreign ? '다른 창에서 임시 검색 중' : '');
  }
  return {
    toggle, onState,
    isOpen: () => !!original,
    isRestoring: () => restoring,
    hasPendingRestore: () => !!pendingRestore,
    afterSearchState: message => {
      if (message.workspace_changed && pendingRestore) {
        restore(pendingRestore);
        pendingRestore = null;
      }
    },
    disconnected: () => {
      leave(); busy = false; foreign = false;
      getSource()?.setTemporaryBusy(false);
    },
  };
}
