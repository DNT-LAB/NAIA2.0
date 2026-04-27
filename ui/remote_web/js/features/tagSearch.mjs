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

  input.addEventListener('compositionstart', () => {
    composing = true;
  });
  input.addEventListener('compositionend', () => {
    composing = false;
    fireSearch();
  });
  input.addEventListener('input', () => {
    if (!composing) fireSearch();
  });

  document.addEventListener('click', event => {
    if (!event.target.closest('.tag-search-bar')) results.classList.remove('open');
  });

  function fireSearch() {
    clearTimeoutFn(timer);
    const query = input.value.trim();
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
    const before = current.substring(0, start);
    const needSep = before.length > 0 && !before.endsWith(', ') && !before.endsWith(',') && before.trim().length > 0;
    const sep = needSep ? ', ' : '';
    promptEdit.value = before + sep + tag + ', ' + current.substring(start);
    promptEdit.focus();
    const newPos = start + sep.length + tag.length + 2;
    promptEdit.selectionStart = promptEdit.selectionEnd = newPos;
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
