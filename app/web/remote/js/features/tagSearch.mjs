export function createTagSearchController({
  document,
  input,
  results,
  promptEdit,
  escHtml,
  getWs,
  WebSocket,
  onPromptEdit,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
}) {
  let timer = null;
  let composing = false;
  let stableTimer = null;
  let settleTimer = null;
  let compositionState = {
    active: false,
    baseValue: '',
    start: 0,
    end: 0,
    data: '',
  };
  const hangulRe = /[가-힣ㄱ-ㅎㅏ-ㅣ]/;

  function clearImeTimers() {
    if (stableTimer) {
      clearTimeoutFn(stableTimer);
      stableTimer = null;
    }
    if (settleTimer) {
      clearTimeoutFn(settleTimer);
      settleTimer = null;
    }
  }

  function captureCompositionAnchor() {
    compositionState.active = true;
    compositionState.baseValue = String(input.value || '');
    const start = input.selectionStart != null ? input.selectionStart : compositionState.baseValue.length;
    const end = input.selectionEnd != null ? input.selectionEnd : start;
    compositionState.start = Math.max(0, Math.min(start, compositionState.baseValue.length));
    compositionState.end = Math.max(compositionState.start, Math.min(end, compositionState.baseValue.length));
  }

  function compositionValue() {
    if (!compositionState.active || !compositionState.data) return '';
    const baseValue = String(compositionState.baseValue || '');
    const start = Math.max(0, Math.min(compositionState.start, baseValue.length));
    const end = Math.max(start, Math.min(compositionState.end, baseValue.length));
    return baseValue.substring(0, start) + compositionState.data + baseValue.substring(end);
  }

  function currentQuery() {
    const value = compositionState.active && compositionState.data ? compositionValue() : '';
    return (value || input.value || '').trim();
  }

  function scheduleStableRetry() {
    if (stableTimer) clearTimeoutFn(stableTimer);
    const value = compositionValue();
    if (!value || !hangulRe.test(value)) return;
    stableTimer = setTimeoutFn(() => {
      stableTimer = null;
      if (!compositionState.active || !compositionState.data) return;
      fireSearch();
    }, 2000);
  }

  input.addEventListener('compositionstart', () => {
    clearImeTimers();
    composing = true;
    compositionState.data = '';
    captureCompositionAnchor();
  });
  input.addEventListener('compositionupdate', event => {
    if (!compositionState.active) captureCompositionAnchor();
    composing = true;
    compositionState.data = String(event.data || '');
    fireSearch();
    scheduleStableRetry();
  });
  input.addEventListener('compositionend', event => {
    if (!compositionState.active) captureCompositionAnchor();
    compositionState.data = String(event.data || compositionState.data || '');
    composing = false;
    fireSearch();
    if (stableTimer) {
      clearTimeoutFn(stableTimer);
      stableTimer = null;
    }
    settleTimer = setTimeoutFn(() => {
      settleTimer = null;
      compositionState.active = false;
      compositionState.data = '';
      fireSearch();
    }, 50);
  });
  input.addEventListener('input', event => {
    if (composing || event.isComposing) {
      if (event.data) compositionState.data = String(event.data);
      fireSearch();
      scheduleStableRetry();
      return;
    }
    compositionState.active = false;
    compositionState.data = '';
    if (stableTimer) {
      clearTimeoutFn(stableTimer);
      stableTimer = null;
    }
    fireSearch();
  });

  document.addEventListener('click', event => {
    if (!event.target.closest('.tag-search-bar')) results.classList.remove('open');
  });

  function fireSearch() {
    clearTimeoutFn(timer);
    const query = currentQuery();
    if (!query) {
      results.classList.remove('open');
      return;
    }
    timer = setTimeoutFn(() => {
      const ws = getWs();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'tag_search', query }));
      }
    }, 150);
  }

  function onResult(message) {
    if (!input.value.trim()) {
      results.classList.remove('open');
      return;
    }
    if (!message.results || !message.results.length) {
      results.classList.remove('open');
      return;
    }
    const fmtCount = count => count >= 1e6
      ? (count/1e6).toFixed(1)+'M'
      : count >= 1e3
        ? (count/1e3).toFixed(0)+'k'
        : String(count);
    results.innerHTML = message.results.map((result, index) =>
      `<div class="tag-result-item" data-idx="${index}">
      <span class="tag-result-tag">${escHtml(result.tag)}</span>
      <span class="tag-result-desc">${escHtml(result.desc || result.group || '')}</span>
      <span class="tag-result-count">${fmtCount(result.count)}</span>
    </div>`
    ).join('');
    results.querySelectorAll('.tag-result-item').forEach(element => {
      const index = +element.dataset.idx;
      element.addEventListener('click', () => insertTag(message.results[index].tag));
    });
    results.classList.add('open');
  }

  function insertTag(tag) {
    const current = promptEdit.value;
    const start = promptEdit.selectionStart != null ? promptEdit.selectionStart : current.length;
    const st = promptEdit.scrollTop, sl = promptEdit.scrollLeft; // value 재대입은 scrollTop=0 리셋 → 복원
    const before = current.substring(0, start);
    const needSep = before.length > 0 && !before.endsWith(', ') && !before.endsWith(',') && before.trim().length > 0;
    const sep = needSep ? ', ' : '';
    promptEdit.value = before + sep + tag + ', ' + current.substring(start);
    promptEdit.focus({ preventScroll: true });
    const newPos = start + sep.length + tag.length + 2;
    promptEdit.selectionStart = promptEdit.selectionEnd = newPos;
    promptEdit.scrollTop = st; promptEdit.scrollLeft = sl; // 복원은 focus/selection 뒤(긴 프롬프트 스크롤 점프 방지)
    onPromptEdit();
    clearTimeoutFn(timer);
    input.value = '';
    results.classList.remove('open');
  }

  return {
    fireSearch,
    onResult,
    insertTag,
  };
}
